from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factor_factory.research_org.contracts import (
    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
    ResearchOrganizationError,
    stable_json_hash,
)

TRUST_MANIFEST_CONTRACT_VERSION = "factorforge_research_org_trust_manifest_v1"
SIGNED_RECEIPT_CONTRACT_VERSION = "factorforge_signed_runtime_receipt_v1"
_SAFE_INSTALLATION_ID = re.compile(r"[a-z0-9][a-z0-9-]{7,62}\Z")


def _crypto() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["cryptography_dependency_missing"],
        ) from exc
    return (
        serialization,
        Ed25519PrivateKey,
        Ed25519PublicKey,
        InvalidSignature,
        serialization.Encoding,
    )


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["signed_receipt_not_canonical_json"],
        ) from exc


def validate_public_trust_manifest(manifest: Any) -> list[str]:
    """Validate the public half of a research-runtime trust store.

    The manifest is safe to project into a factor workspace.  It does not grant
    authority by itself; formal callers still bind it to the Host-private
    runtime ledger.  This validator exists so downstream artifacts can verify
    signatures without ever loading a private key.
    """

    reasons: list[str] = []
    fields = {"contract_version", "installation_id", "keys", "manifest_sha256"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        return ["trust_manifest.fields"]
    if manifest.get("contract_version") != TRUST_MANIFEST_CONTRACT_VERSION:
        reasons.append("trust_manifest.contract_version")
    if not _SAFE_INSTALLATION_ID.fullmatch(str(manifest.get("installation_id") or "")):
        reasons.append("trust_manifest.installation_id")
    keys = manifest.get("keys")
    expected_kinds = {"runtime_adapter", "host_admission"}
    if not isinstance(keys, dict) or set(keys) != expected_kinds:
        reasons.append("trust_manifest.keys")
        keys = {}
    for issuer_kind in sorted(expected_kinds):
        key = keys.get(issuer_kind)
        if (
            not isinstance(key, dict)
            or set(key) != {"algorithm", "key_id", "public_key_b64"}
            or key.get("algorithm") != "Ed25519"
        ):
            reasons.append(f"trust_manifest.key:{issuer_kind}")
            continue
        try:
            raw = base64.b64decode(str(key.get("public_key_b64") or ""), validate=True)
        except (ValueError, TypeError):
            raw = b""
        if (
            len(raw) != 32
            or key.get("key_id") != hashlib.sha256(raw).hexdigest()
        ):
            reasons.append(f"trust_manifest.key_material:{issuer_kind}")
    unsigned = dict(manifest)
    digest = unsigned.pop("manifest_sha256", None)
    if digest != stable_json_hash(unsigned):
        reasons.append("trust_manifest.manifest_sha256")
    return list(dict.fromkeys(reasons))


def verify_signed_receipt_with_manifest(
    receipt: Any,
    *,
    trust_manifest: Any,
    expected_issuer: str,
) -> list[str]:
    """Verify a signed runtime receipt from only its public trust manifest."""

    reasons = validate_public_trust_manifest(trust_manifest)
    if expected_issuer not in {"runtime_adapter", "host_admission"}:
        return [*reasons, "signed_receipt.expected_issuer"]
    if not isinstance(receipt, dict):
        return [*reasons, "signed_receipt.object_required"]
    if receipt.get("contract_version") != SIGNED_RECEIPT_CONTRACT_VERSION:
        reasons.append("signed_receipt.contract_version")
    keys = trust_manifest.get("keys") if isinstance(trust_manifest, dict) else {}
    key = keys.get(expected_issuer) if isinstance(keys, dict) else None
    issuer = receipt.get("issuer") if isinstance(receipt.get("issuer"), dict) else {}
    expected_key_id = key.get("key_id") if isinstance(key, dict) else None
    if issuer != {"kind": expected_issuer, "key_id": expected_key_id}:
        reasons.append("signed_receipt.issuer")
    unsigned = dict(receipt)
    signature = unsigned.pop("signature", None)
    receipt_id = unsigned.pop("receipt_id", None)
    try:
        expected_id = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
    except ResearchOrganizationError:
        reasons.append("signed_receipt.canonical_json")
        return list(dict.fromkeys(reasons))
    if receipt_id != expected_id:
        reasons.append("signed_receipt.receipt_id")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "value_b64"}
        or signature.get("algorithm") != "Ed25519"
    ):
        reasons.append("signed_receipt.signature")
        return list(dict.fromkeys(reasons))
    try:
        signature_bytes = base64.b64decode(
            str(signature.get("value_b64") or ""), validate=True
        )
        public_bytes = base64.b64decode(
            str((key or {}).get("public_key_b64") or ""), validate=True
        )
    except (ValueError, TypeError):
        reasons.append("signed_receipt.signature_encoding")
        return list(dict.fromkeys(reasons))
    _serialization, _private_cls, public_cls, invalid_signature, _encoding = _crypto()
    try:
        public_key = public_cls.from_public_bytes(public_bytes)
        public_key.verify(
            signature_bytes,
            _canonical_bytes({**unsigned, "receipt_id": receipt_id}),
        )
    except (ValueError, invalid_signature):
        reasons.append("signed_receipt.signature_invalid")
    return list(dict.fromkeys(reasons))


def _safe_private_directory(path: Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.exists() or candidate.is_symlink():
        metadata = candidate.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"unsafe_trust_root:{candidate}"],
            )
    else:
        candidate.mkdir(parents=True, mode=0o700)
    candidate = candidate.resolve(strict=True)
    candidate.chmod(0o700)
    return candidate


def _existing_safe_private_directory(path: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.exists() or candidate.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            [f"trust_root_missing:{candidate}"],
        )
    metadata = candidate.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            [f"unsafe_trust_root:{candidate}"],
        )
    return candidate.resolve(strict=True)


def _write_private_file_once(path: Path, payload: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_private_file(path: Path, *, max_bytes: int = 32_768) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o077
            or before.st_nlink != 1
            or not 0 < before.st_size <= max_bytes
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"unsafe_trust_file:{path.name}"],
            )
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or (before.st_dev, before.st_ino, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_mtime_ns)
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"changed_trust_file:{path.name}"],
            )
        return payload
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class RuntimeTrustStore:
    root: Path
    installation_id: str
    adapter_key_id: str
    host_key_id: str
    adapter_public_key_b64: str
    host_public_key_b64: str

    @property
    def public_manifest(self) -> dict[str, Any]:
        payload = {
            "contract_version": TRUST_MANIFEST_CONTRACT_VERSION,
            "installation_id": self.installation_id,
            "keys": {
                "runtime_adapter": {
                    "algorithm": "Ed25519",
                    "key_id": self.adapter_key_id,
                    "public_key_b64": self.adapter_public_key_b64,
                },
                "host_admission": {
                    "algorithm": "Ed25519",
                    "key_id": self.host_key_id,
                    "public_key_b64": self.host_public_key_b64,
                },
            },
        }
        payload["manifest_sha256"] = stable_json_hash(payload)
        return payload

    def sign(self, issuer_kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if issuer_kind not in {"runtime_adapter", "host_admission"}:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"unsupported_receipt_issuer:{issuer_kind}"],
            )
        serialization, private_cls, _public_cls, _invalid, _encoding = _crypto()
        key_id = (
            self.adapter_key_id
            if issuer_kind == "runtime_adapter"
            else self.host_key_id
        )
        private_name = (
            "adapter_ed25519.pem"
            if issuer_kind == "runtime_adapter"
            else "host_ed25519.pem"
        )
        private_key = serialization.load_pem_private_key(
            _read_private_file(self.root / private_name),
            password=None,
        )
        if not isinstance(private_key, private_cls):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"invalid_private_key:{issuer_kind}"],
            )
        unsigned = dict(payload)
        unsigned.pop("receipt_id", None)
        unsigned.pop("signature", None)
        unsigned["contract_version"] = SIGNED_RECEIPT_CONTRACT_VERSION
        unsigned["issuer"] = {
            "kind": issuer_kind,
            "key_id": key_id,
        }
        receipt_id = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
        signed_body = {**unsigned, "receipt_id": receipt_id}
        signature = private_key.sign(_canonical_bytes(signed_body))
        return {
            **signed_body,
            "signature": {
                "algorithm": "Ed25519",
                "value_b64": base64.b64encode(signature).decode("ascii"),
            },
        }

    def verify(
        self,
        receipt: Mapping[str, Any],
        *,
        expected_issuer: str,
    ) -> list[str]:
        reasons: list[str] = []
        if receipt.get("contract_version") != SIGNED_RECEIPT_CONTRACT_VERSION:
            reasons.append("signed_receipt.contract_version")
        issuer = receipt.get("issuer") if isinstance(receipt.get("issuer"), dict) else {}
        expected_key_id = (
            self.adapter_key_id
            if expected_issuer == "runtime_adapter"
            else self.host_key_id
        )
        if issuer != {"kind": expected_issuer, "key_id": expected_key_id}:
            reasons.append("signed_receipt.issuer")
        unsigned = dict(receipt)
        signature = unsigned.pop("signature", None)
        receipt_id = unsigned.pop("receipt_id", None)
        expected_id = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
        if receipt_id != expected_id:
            reasons.append("signed_receipt.receipt_id")
        if (
            not isinstance(signature, dict)
            or set(signature) != {"algorithm", "value_b64"}
            or signature.get("algorithm") != "Ed25519"
        ):
            reasons.append("signed_receipt.signature")
            return reasons
        try:
            signature_bytes = base64.b64decode(
                str(signature.get("value_b64") or ""),
                validate=True,
            )
        except (ValueError, TypeError):
            reasons.append("signed_receipt.signature_encoding")
            return reasons
        serialization, _private_cls, public_cls, invalid_signature, encoding = _crypto()
        public_b64 = (
            self.adapter_public_key_b64
            if expected_issuer == "runtime_adapter"
            else self.host_public_key_b64
        )
        try:
            public_key = public_cls.from_public_bytes(
                base64.b64decode(public_b64, validate=True)
            )
            public_key.verify(
                signature_bytes,
                _canonical_bytes({**unsigned, "receipt_id": receipt_id}),
            )
        except (ValueError, invalid_signature):
            reasons.append("signed_receipt.signature_invalid")
        _ = serialization, encoding
        return reasons


def ensure_runtime_trust_store(
    trust_root: Path,
    *,
    installation_id: str,
) -> RuntimeTrustStore:
    if not _SAFE_INSTALLATION_ID.fullmatch(installation_id):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            [f"invalid_installation_id:{installation_id}"],
        )
    root = _safe_private_directory(trust_root)
    lock_path = root / "trust.lock"
    lock_descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        serialization, private_cls, _public_cls, _invalid, _encoding = _crypto()
        for name in ("adapter_ed25519.pem", "host_ed25519.pem"):
            path = root / name
            if not path.exists() and not path.is_symlink():
                private_key = private_cls.generate()
                payload = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
                try:
                    _write_private_file_once(path, payload)
                except FileExistsError:
                    pass
            _read_private_file(path)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)

    return _load_runtime_trust_store(root, installation_id=installation_id)


def _load_runtime_trust_store(
    root: Path,
    *,
    installation_id: str,
) -> RuntimeTrustStore:
    serialization, private_cls, _public_cls, _invalid, encoding = _crypto()

    def public_material(name: str) -> tuple[str, str]:
        key = serialization.load_pem_private_key(
            _read_private_file(root / name),
            password=None,
        )
        if not isinstance(key, private_cls):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"invalid_private_key:{name}"],
            )
        raw = key.public_key().public_bytes(
            encoding=encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode("ascii")

    adapter_id, adapter_public = public_material("adapter_ed25519.pem")
    host_id, host_public = public_material("host_ed25519.pem")
    return RuntimeTrustStore(
        root=root,
        installation_id=installation_id,
        adapter_key_id=adapter_id,
        host_key_id=host_id,
        adapter_public_key_b64=adapter_public,
        host_public_key_b64=host_public,
    )


def load_runtime_trust_store(
    trust_root: Path,
    *,
    installation_id: str,
) -> RuntimeTrustStore:
    if not _SAFE_INSTALLATION_ID.fullmatch(installation_id):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            [f"invalid_installation_id:{installation_id}"],
        )
    root = _existing_safe_private_directory(trust_root)
    return _load_runtime_trust_store(root, installation_id=installation_id)
