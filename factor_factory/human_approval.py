from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

HUMAN_APPROVAL_TRUST_VERSION = "factorforge_human_approval_trust_manifest_v1"
HUMAN_APPROVAL_RECEIPT_VERSION = "factorforge_external_human_approval_receipt_v3"
HUMAN_APPROVAL_DECISION = "APPROVE_FRESH_OOS_CHILD_REVISION"
BLOCK_HUMAN_APPROVAL = "BLOCK_FACTORFORGE_EXTERNAL_HUMAN_APPROVAL_INVALID"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z")


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_approval_trust_path(root: Path) -> Path:
    return root / "identity" / "human_approval_trust.json"


def _resolve_workspace_path(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if candidate != resolved_root and resolved_root not in candidate.parents:
        return None
    return candidate


def _iso8601_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _verify_ed25519(public_key_b64: str, signature_b64: str, message: bytes) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True)
        )
        public_key.verify(base64.b64decode(signature_b64, validate=True), message)
    except (ImportError, ValueError, TypeError, InvalidSignature):
        return False
    return True


def validate_human_approval_trust_manifest(payload: Any) -> list[str]:
    reasons: list[str] = []
    expected_fields = {"contract_version", "keys", "content_sha256"}
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        return [f"{BLOCK_HUMAN_APPROVAL}:trust_manifest_shape"]
    if payload.get("contract_version") != HUMAN_APPROVAL_TRUST_VERSION:
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:trust_manifest_version")
    keys = payload.get("keys")
    if not isinstance(keys, dict) or not keys:
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:trust_keys_missing")
    else:
        for key_id, key in keys.items():
            if not isinstance(key_id, str) or not _SAFE_ID_RE.fullmatch(key_id):
                reasons.append(f"{BLOCK_HUMAN_APPROVAL}:trust_key_id")
                continue
            if (
                not isinstance(key, dict)
                or set(key) != {"algorithm", "public_key_b64", "status"}
                or key.get("algorithm") != "Ed25519"
                or key.get("status") != "ACTIVE"
            ):
                reasons.append(f"{BLOCK_HUMAN_APPROVAL}:trust_key:{key_id}")
                continue
            try:
                raw = base64.b64decode(
                    str(key.get("public_key_b64") or ""), validate=True
                )
            except (ValueError, TypeError):
                raw = b""
            if len(raw) != 32 or hashlib.sha256(raw).hexdigest() != key_id:
                reasons.append(f"{BLOCK_HUMAN_APPROVAL}:trust_key_material:{key_id}")
    unsigned = dict(payload)
    content_sha256 = unsigned.pop("content_sha256", None)
    if content_sha256 != stable_hash(unsigned):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:trust_manifest_hash")
    return list(dict.fromkeys(reasons))


def validate_external_human_approval_receipt(
    receipt: Any,
    *,
    trust_manifest: Any,
    workspace_root: Path,
    report_id: str,
    run_id: str,
    synthesis_path: Path,
    selected_law_id: str,
    selected_law_hash: str,
    child_formula_hash: str,
    mechanism_delta_path: Path,
    economic_backprojection_path: Path,
) -> list[str]:
    reasons = validate_human_approval_trust_manifest(trust_manifest)
    fields = {
        "contract_version",
        "report_id",
        "run_id",
        "decision",
        "synthesis",
        "selected_law",
        "mechanism_delta",
        "economic_backprojection",
        "child_intent",
        "issued_at_utc",
        "issuer",
        "receipt_id",
        "signature",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields:
        return [*reasons, f"{BLOCK_HUMAN_APPROVAL}:receipt_shape"]
    if receipt.get("contract_version") != HUMAN_APPROVAL_RECEIPT_VERSION:
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:receipt_version")
    if receipt.get("report_id") != report_id or receipt.get("run_id") != run_id:
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:run_identity")
    if receipt.get("decision") != HUMAN_APPROVAL_DECISION:
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:decision")
    if not _iso8601_utc(receipt.get("issued_at_utc")):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:issued_at_utc")

    expected_files = {
        "synthesis": synthesis_path,
        "mechanism_delta": mechanism_delta_path,
        "economic_backprojection": economic_backprojection_path,
    }
    for field, expected_path in expected_files.items():
        binding = receipt.get(field)
        expected_binding_fields = {"path", "sha256"}
        if field in {"mechanism_delta", "economic_backprojection"}:
            expected_binding_fields.add("delta_id")
        if not isinstance(binding, dict) or set(binding) != expected_binding_fields:
            reasons.append(f"{BLOCK_HUMAN_APPROVAL}:{field}_binding_shape")
            continue
        resolved = _resolve_workspace_path(workspace_root, binding.get("path"))
        expected = expected_path.resolve(strict=False)
        if resolved != expected or not expected.is_file() or expected.is_symlink():
            reasons.append(f"{BLOCK_HUMAN_APPROVAL}:{field}_path")
        elif binding.get("sha256") != sha256_file(expected):
            reasons.append(f"{BLOCK_HUMAN_APPROVAL}:{field}_sha256")

    law = receipt.get("selected_law")
    if (
        not isinstance(law, dict)
        or set(law) != {"law_id", "law_or_formula_hash", "child_formula_hash"}
        or law.get("law_id") != selected_law_id
        or law.get("law_or_formula_hash") != selected_law_hash
        or law.get("child_formula_hash") != child_formula_hash
    ):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:selected_law_binding")

    delta_payload: dict[str, Any] = {}
    backprojection_payload: dict[str, Any] = {}
    try:
        delta_payload = json.loads(mechanism_delta_path.read_text(encoding="utf-8"))
        backprojection_payload = json.loads(
            economic_backprojection_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:evo_artifact_invalid")
    delta_id = (
        (delta_payload.get("minimal_extension") or {}).get("delta_id")
        if isinstance(delta_payload, dict)
        else None
    )
    if (
        not isinstance(delta_id, str)
        or not delta_id
        or (receipt.get("mechanism_delta") or {}).get("delta_id") != delta_id
        or (receipt.get("economic_backprojection") or {}).get("delta_id") != delta_id
        or backprojection_payload.get("delta_id") != delta_id
    ):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:delta_binding")

    intent = receipt.get("child_intent")
    intent_fields = {
        "action",
        "child_report_id",
        "child_formula_hash",
        "fresh_sealed_oos_required",
        "reuse_parent_ancestor_or_sibling_oos_allowed",
        "oos_allocation_id",
        "oos_allocation_ref",
        "oos_allocation_sha256",
        "oos_registry_prefix_ref",
    }
    if (
        not isinstance(intent, dict)
        or set(intent) != intent_fields
        or intent.get("action") != "MATERIALIZE_AND_TEST_FRESH_OOS_CHILD"
        or not isinstance(intent.get("child_report_id"), str)
        or not intent.get("child_report_id")
        or intent.get("child_report_id") == report_id
        or intent.get("child_formula_hash") != child_formula_hash
        or intent.get("fresh_sealed_oos_required") is not True
        or intent.get("reuse_parent_ancestor_or_sibling_oos_allowed") is not False
        or not isinstance(intent.get("oos_allocation_id"), str)
        or not intent.get("oos_allocation_id")
        or not isinstance(intent.get("oos_allocation_ref"), str)
        or not intent.get("oos_allocation_ref")
        or not isinstance(intent.get("oos_allocation_sha256"), str)
        or not _SHA256_RE.fullmatch(intent.get("oos_allocation_sha256"))
        or not isinstance(intent.get("oos_registry_prefix_ref"), dict)
    ):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:child_intent")
    else:
        allocation_path = _resolve_workspace_path(
            workspace_root, intent.get("oos_allocation_ref")
        )
        expected_allocation_path = (
            workspace_root
            / "objects"
            / "research_protocol"
            / f"evo_oos_allocation__{intent['child_report_id']}.json"
        ).resolve(strict=False)
        if (
            allocation_path != expected_allocation_path
            or not allocation_path.is_file()
            or allocation_path.is_symlink()
            or intent.get("oos_allocation_sha256") != sha256_file(allocation_path)
        ):
            reasons.append(f"{BLOCK_HUMAN_APPROVAL}:child_oos_allocation_binding")
        if allocation_path is not None:
            # Import lazily because the OOS contract reuses this module's
            # canonical JSON encoding for its own signed Host receipts.
            from factor_factory.evo_oos import (
                validate_fresh_child_oos_allocation_structural,
                validate_oos_registry_allocation_prefix,
            )

            prefix_reasons = validate_oos_registry_allocation_prefix(
                intent.get("oos_registry_prefix_ref"),
                root=workspace_root,
                allocation_id=str(intent["oos_allocation_id"]),
                report_id=str(intent["child_report_id"]),
            )
            reasons.extend(
                f"{BLOCK_HUMAN_APPROVAL}:child_oos_registry_prefix:{reason}"
                for reason in prefix_reasons
            )

            oos_reasons = validate_fresh_child_oos_allocation_structural(
                root=workspace_root,
                parent_report_id=report_id,
                child_report_id=str(intent["child_report_id"]),
                allocation_id=str(intent["oos_allocation_id"]),
                allocation_ref=str(intent["oos_allocation_ref"]),
            )
            reasons.extend(
                f"{BLOCK_HUMAN_APPROVAL}:fresh_oos:{reason}" for reason in oos_reasons
            )

    issuer = receipt.get("issuer")
    if (
        not isinstance(issuer, dict)
        or set(issuer) != {"kind", "human_id", "key_id"}
        or issuer.get("kind") != "external_human"
        or not isinstance(issuer.get("human_id"), str)
        or not _SAFE_ID_RE.fullmatch(str(issuer.get("human_id") or ""))
        or not isinstance(issuer.get("key_id"), str)
    ):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:issuer_not_external_human")
        issuer = {}
    key_id = str(issuer.get("key_id") or "")
    key = (
        (trust_manifest.get("keys") or {}).get(key_id)
        if isinstance(trust_manifest, dict)
        else None
    )
    if not isinstance(key, dict) or key.get("status") != "ACTIVE":
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:issuer_untrusted")

    unsigned = dict(receipt)
    signature = unsigned.pop("signature", None)
    receipt_id = unsigned.pop("receipt_id", None)
    expected_receipt_id = stable_hash(unsigned)
    if receipt_id != expected_receipt_id or not _SHA256_RE.fullmatch(
        str(receipt_id or "")
    ):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:receipt_id")
    signed_body = {**unsigned, "receipt_id": receipt_id}
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "value_b64"}
        or signature.get("algorithm") != "Ed25519"
        or not isinstance(key, dict)
        or not _verify_ed25519(
            str(key.get("public_key_b64") or ""),
            str(signature.get("value_b64") or ""),
            canonical_json_bytes(signed_body),
        )
    ):
        reasons.append(f"{BLOCK_HUMAN_APPROVAL}:signature")
    return list(dict.fromkeys(reasons))
