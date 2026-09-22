from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from factor_factory.human_approval import canonical_json_bytes
from factor_factory.oos_exposure_incident import (
    OOS_EXPOSURE_INSTALLATION_ID_ENV,
    OOS_EXPOSURE_TRUST_ROOT_ENV,
    oos_exposure_incident_block_reasons,
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)

OOS_REGISTRY_VERSION = "factorforge_evo_oos_allocation_registry_v2"
OOS_ALLOCATION_VERSION = "factorforge_fresh_sealed_oos_allocation_v2"
BLOCK_OOS_ALLOCATION = "BLOCK_FACTORFORGE_EVO_FRESH_OOS_ALLOCATION_INVALID"
WAITING_FRESH_OOS = "WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION"
OOS_HOST_AUTHORITY = "ULTIMATE_HOST_SIGNED_APPEND_ONLY_CAS"
OOS_RELEASE_GATE_ACTOR = "FACTOR_PROOF_RELEASE_GATE"
OOS_ALLOCATION_RECEIPT_TYPE = "EVO_FRESH_SEALED_OOS_ALLOCATION"
OOS_CONSUMPTION_PURPOSE = "FINAL_OOS_EVALUATION"
RESEARCH_RELEASE_MANIFEST_VERSION = "factorforge_oos_release_manifest_v1"
OOS_REGISTRY_ALLOCATION_PREFIX_VERSION = (
    "factorforge_evo_oos_registry_allocation_prefix_v1"
)
OOS_ALLOCATION_BUILD_AUTHORITY_VERSION = (
    "factorforge_evo_oos_allocation_build_authority_v1"
)
OOS_ALLOCATION_AUTHORITY_SECURE = "HOST_PRIVATE_CARRIER_DERIVED"
OOS_ALLOCATION_AUTHORITY_LEGACY_TEST = "LEGACY_TEST_ONLY_DIRECT_HASH_INPUT"
OOS_PRIVATE_LOCATOR_TYPE = "EVO_FRESH_SEALED_OOS_PRIVATE_CARRIER"
OOS_PRIVATE_LOCATOR_SCOPE = "HOST_PRIVATE_OOS_RELEASE_ONLY"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,159}\Z")


def _required_incident_host_context(
    trust_root: Path | None,
    installation_id: str | None,
) -> tuple[Path, str]:
    trust_raw = (
        os.fspath(trust_root.expanduser().resolve(strict=False))
        if trust_root is not None
        else os.environ.get(OOS_EXPOSURE_TRUST_ROOT_ENV, "")
    )
    installation_raw = (
        installation_id
        if installation_id is not None
        else os.environ.get(OOS_EXPOSURE_INSTALLATION_ID_ENV, "")
    )
    if not trust_raw and not installation_raw:
        trust_raw = os.environ.get("FACTORFORGE_OOS_HOST_TRUST_ROOT", "")
        installation_raw = os.environ.get(
            "FACTORFORGE_OOS_HOST_INSTALLATION_ID", ""
        )
    if not trust_raw or not installation_raw:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:incident_host_context_required")
    return Path(trust_raw).expanduser().resolve(strict=True), str(installation_raw)


@contextmanager
def _current_incident_authority_guard(
    *,
    trust_root: Path | None,
    installation_id: str | None,
    guard: object | None,
):
    resolved_trust, resolved_installation = _required_incident_host_context(
        trust_root,
        installation_id,
    )
    if guard is not None:
        validate_oos_exposure_private_registry_guard(
            guard,
            trust_root=resolved_trust,
            installation_id=resolved_installation,
        )
        yield guard, resolved_trust, resolved_installation
        return
    with oos_exposure_private_registry_guard(
        resolved_trust,
        installation_id=resolved_installation,
    ) as active_guard:
        yield active_guard, resolved_trust, resolved_installation


def stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _pretty_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _pretty_json_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_pretty_json_bytes(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def oos_registry_path(root: Path) -> Path:
    return root / "objects" / "research_protocol" / "evo_oos_allocation_registry.json"


def oos_allocation_path(root: Path, report_id: str) -> Path:
    return (
        root / "objects" / "research_protocol" / f"evo_oos_allocation__{report_id}.json"
    )


def oos_allocation_receipt_path(root: Path, report_id: str) -> Path:
    return (
        root
        / "objects"
        / "research_protocol"
        / f"evo_oos_allocation_host_receipt__{report_id}.json"
    )


def oos_host_trust_manifest_path(root: Path) -> Path:
    return root / "identity" / "evo_oos_host_trust_manifest.json"


def _private_oos_locator_id(
    *, allocation_id: str, report_id: str, parent_report_id: str
) -> str:
    return stable_hash(
        {
            "contract_version": OOS_ALLOCATION_BUILD_AUTHORITY_VERSION,
            "purpose": "HOST_PRIVATE_OOS_CARRIER_LOCATOR",
            "allocation_id": allocation_id,
            "report_id": report_id,
            "parent_report_id": parent_report_id,
        }
    )


def private_oos_locator_path(trust_root: Path, private_locator_id: str) -> Path:
    if not _SHA256_RE.fullmatch(private_locator_id):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_locator_id")
    return (
        trust_root.expanduser().resolve(strict=True)
        / "evo_oos_private_allocations"
        / f"{private_locator_id}.json"
    )


def child_control_paths(root: Path, report_id: str) -> dict[str, Path]:
    protocol = root / "objects" / "research_protocol"
    return {
        "research_state": protocol / f"research_state__{report_id}.json",
        "research_conjecture": protocol / f"research_conjecture__{report_id}.json",
        "approach_registry": protocol / f"approach_registry__{report_id}.json",
        "search_trial_ledger": protocol / f"search_trial_ledger__{report_id}.json",
        "threshold_registration": protocol
        / f"threshold_registration__{report_id}.json",
        "oos_allocation": oos_allocation_path(root, report_id),
        "oos_allocation_registry": oos_registry_path(root),
    }


def _evo_child_intent_path(root: Path, report_id: str) -> Path:
    return (
        root / "objects" / "research_protocol" / f"evo_child_intent__{report_id}.json"
    )


def _evo_child_lineage_markers(root: Path, report_id: str) -> list[str]:
    """Return canonical evidence that ``report_id`` is an EVO child.

    Legacy OOS release is intentionally available only to an original candidate.
    Once the Host has emitted a child intent or a child-lineage projection, losing
    the allocation files must not silently reclassify that child as legacy.
    """

    markers: list[str] = []
    intent_path = _evo_child_intent_path(root, report_id)
    if intent_path.exists() or intent_path.is_symlink():
        markers.append("evo_child_intent")

    executable_spec = (
        root
        / "objects"
        / "research_iteration_master"
        / f"executable_revision_spec__{report_id}.json"
    )
    if executable_spec.exists() or executable_spec.is_symlink():
        markers.append("executable_revision_spec")

    for path in (root / "objects" / "handoff").glob("handoff_to_step3b__*.json"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        intent = payload.get("fresh_oos_child_intent")
        if payload.get("child_report_id") == report_id or (
            isinstance(intent, dict) and intent.get("child_report_id") == report_id
        ):
            markers.append("parent_child_handoff")
            break

    for path in (root / "objects" / "runtime_context").glob(
        "child_revision_materialization__*.json"
    ):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if payload.get("child_report_id") == report_id:
            markers.append("child_materialization_lineage")
            break
    return list(dict.fromkeys(markers))


def _missing_evo_child_oos_authority_reasons(
    root: Path,
    report_id: str,
) -> list[str]:
    if not _evo_child_lineage_markers(root, report_id):
        return []
    reasons: list[str] = []
    allocation_path = oos_allocation_path(root, report_id)
    registry_path = oos_registry_path(root)
    if not allocation_path.is_file() or allocation_path.is_symlink():
        reasons.append(f"{WAITING_FRESH_OOS}:allocation_missing_or_noncanonical")
    if not registry_path.is_file() or registry_path.is_symlink():
        reasons.append(f"{WAITING_FRESH_OOS}:registry_missing")
    return reasons


def _report_has_evo_lineage_authority_marker(root: Path, report_id: str) -> bool:
    """Return whether public state proves this identity already entered EVO lineage.

    The allocation registry is the only canonical source of the complete signed
    ancestor chain.  Allocation/Host receipts and later child projections are
    therefore fail-closed witnesses that a missing registry was deleted rather
    than evidence that the report may be treated as a new lineage root.
    """

    protocol = root / "objects" / "research_protocol"
    runtime = root / "objects" / "runtime_context"
    explicit_markers = (
        oos_allocation_path(root, report_id),
        oos_allocation_receipt_path(root, report_id),
        _evo_child_intent_path(root, report_id),
        runtime / f"evo_child_preregistration__{report_id}.json",
        runtime / f"evo_child_materialization_admission__{report_id}.json",
        protocol / f"evo_child_materialization_ticket__{report_id}__authorization.json",
        protocol / f"evo_child_materialization_ticket__{report_id}__ready.json",
    )
    if any(path.exists() or path.is_symlink() for path in explicit_markers):
        return True
    return bool(_evo_child_lineage_markers(root, report_id))


def _allocation_ancestor_report_ids(root: Path, report_id: str) -> list[str]:
    """Resolve every signed allocation ancestor; malformed ancestry is fatal."""

    registry_path = oos_registry_path(root)
    if not registry_path.exists() and not registry_path.is_symlink():
        if _report_has_evo_lineage_authority_marker(root, report_id):
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:incident_lineage_registry_missing"
            )
        return [report_id]
    if not registry_path.is_file() or registry_path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:incident_lineage_registry_unsafe")
    try:
        registry = _read_json(registry_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"{BLOCK_OOS_ALLOCATION}:incident_lineage_registry_invalid"
        ) from exc
    reasons = validate_oos_registry(registry, workspace_root=root)
    if reasons:
        raise ValueError(";".join(reasons))
    by_report: dict[str, Mapping[str, Any]] = {}
    for event in registry.get("events") or []:
        if not isinstance(event, Mapping) or event.get("event_type") != "ALLOCATE":
            continue
        allocated_report = str(event.get("report_id") or "")
        if allocated_report in by_report:
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:incident_lineage_ambiguous")
        by_report[allocated_report] = event
    ancestry: list[str] = []
    seen: set[str] = set()
    current = report_id
    while current:
        if current in seen:
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:incident_lineage_cycle")
        seen.add(current)
        ancestry.append(current)
        event = by_report.get(current)
        if event is None:
            break
        parent = event.get("parent_report_id")
        if not isinstance(parent, str) or not _SAFE_ID_RE.fullmatch(parent):
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:incident_lineage_broken")
        current = parent
    return ancestry


def _allocation_incident_reasons(
    *,
    root: Path,
    report_id: str,
    parent_report_id: str,
    trust_root: Path,
    installation_id: str,
) -> list[str]:
    identities = [report_id, *_allocation_ancestor_report_ids(root, parent_report_id)]
    reasons: list[str] = []
    for identity in dict.fromkeys(identities):
        reasons.extend(
            oos_exposure_incident_block_reasons(
                root,
                identity,
                trust_root=trust_root,
                installation_id=installation_id,
            )
        )
    return list(dict.fromkeys(reasons))


def formal_oos_incident_reasons(
    *,
    workspace_root: Path,
    report_id: str,
    trust_root: Path | None = None,
    installation_id: str | None = None,
) -> list[str]:
    root = workspace_root.expanduser().resolve(strict=False)
    try:
        identities = _allocation_ancestor_report_ids(root, report_id)
    except ValueError as exc:
        return [str(exc)]
    reasons: list[str] = []
    for identity in identities:
        reasons.extend(
            oos_exposure_incident_block_reasons(
                root,
                identity,
                trust_root=trust_root,
                installation_id=installation_id,
            )
        )
    return list(dict.fromkeys(reasons))


def _public_marker_incident_reasons(
    *,
    workspace_root: Path,
    report_id: str,
) -> list[str]:
    """Return immutable public-marker blocks before Host context resolution."""

    return [
        reason
        for reason in formal_oos_incident_reasons(
            workspace_root=workspace_root,
            report_id=report_id,
        )
        if reason.endswith(":marker_present")
    ]


def _window(raw: Any) -> tuple[date, date] | None:
    if isinstance(raw, str) and raw.count("/") == 1:
        start_raw, end_raw = raw.split("/", 1)
    elif isinstance(raw, dict) and set(raw) == {"start", "end"}:
        start_raw, end_raw = raw.get("start"), raw.get("end")
    else:
        return None
    try:
        start = date.fromisoformat(str(start_raw or ""))
        end = date.fromisoformat(str(end_raw or ""))
    except ValueError:
        return None
    return (start, end) if start <= end else None


def _overlap(left: tuple[date, date], right: tuple[date, date]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def _resolve(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if path != resolved_root and resolved_root not in path.parents:
        return None
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:json_object_required")
    return payload


def _relative_ref(root: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()


def _build_authority_reasons(
    payload: Any,
    *,
    workspace_root: Path,
    event: Mapping[str, Any],
) -> list[str]:
    token = f"{BLOCK_OOS_ALLOCATION}:allocation_build_authority"
    fields = {
        "contract_version",
        "allocation_id",
        "report_id",
        "parent_report_id",
        "selected_revision",
        "authority_refs",
        "calendar_authority",
        "universe_binding",
        "oos_window",
        "sealed_token_sha256",
        "sealed_carrier_sha256",
        "dataset_snapshot_sha256",
        "projection_row_count",
        "projection_period_count",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        return [f"{token}:shape"]
    reasons: list[str] = []
    if payload.get("contract_version") != OOS_ALLOCATION_BUILD_AUTHORITY_VERSION:
        reasons.append(f"{token}:version")
    for field in (
        "allocation_id",
        "report_id",
        "parent_report_id",
        "oos_window",
        "sealed_token_sha256",
        "sealed_carrier_sha256",
        "dataset_snapshot_sha256",
    ):
        expected = (
            event.get(field)
            if field != "dataset_snapshot_sha256"
            else event.get("dataset_snapshot_sha256")
        )
        if payload.get(field) != expected:
            reasons.append(f"{token}:binding:{field}")
    selected = payload.get("selected_revision")
    if (
        not isinstance(selected, Mapping)
        or not isinstance(selected.get("child_formula"), str)
        or not selected.get("child_formula")
        or not isinstance(selected.get("child_formula_hash"), str)
        or not _SHA256_RE.fullmatch(str(selected.get("child_formula_hash") or ""))
    ):
        reasons.append(f"{token}:selected_revision")
    references = payload.get("authority_refs")
    if not isinstance(references, Mapping) or not references:
        reasons.append(f"{token}:authority_refs")
    else:
        for label, reference in references.items():
            path = _resolve(
                workspace_root,
                reference.get("path") if isinstance(reference, Mapping) else None,
            )
            if (
                not isinstance(label, str)
                or not label
                or not isinstance(reference, Mapping)
                or set(reference) != {"path", "sha256"}
                or path is None
                or not path.is_file()
                or path.is_symlink()
                or reference.get("sha256") != sha256_file(path)
            ):
                reasons.append(f"{token}:authority_ref:{label}")
    calendar = payload.get("calendar_authority")
    calendar_fields = {
        "snapshot_id",
        "open_dates_sha256",
        "raw_file_sha256",
        "registry_sha256",
        "registry_git_commit",
        "registry_git_blob",
    }
    if (
        not isinstance(calendar, Mapping)
        or set(calendar) != calendar_fields
        or any(not isinstance(value, str) or not value for value in calendar.values())
        or any(
            not _SHA256_RE.fullmatch(str(calendar.get(field) or ""))
            for field in ("open_dates_sha256", "raw_file_sha256", "registry_sha256")
        )
    ):
        reasons.append(f"{token}:calendar_authority")
    universe = payload.get("universe_binding")
    if (
        not isinstance(universe, Mapping)
        or set(universe) != {"universe_id", "investability_mask_id"}
        or any(not isinstance(value, str) or not value for value in universe.values())
    ):
        reasons.append(f"{token}:universe_binding")
    for field in ("projection_row_count", "projection_period_count"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            reasons.append(f"{token}:{field}")
    return list(dict.fromkeys(reasons))


def _host_receipt_reference_reasons(
    reference: Any,
    *,
    workspace_root: Path,
    event: dict[str, Any],
    registry_parent_sha256: str | None,
) -> list[str]:
    token = f"{BLOCK_OOS_ALLOCATION}:allocation_host_receipt"
    fields = {
        "path",
        "sha256",
        "receipt_id",
        "trust_manifest_ref",
        "trust_manifest_sha256",
    }
    if not isinstance(reference, dict) or set(reference) != fields:
        return [f"{token}:shape"]
    receipt_path = _resolve(workspace_root, reference.get("path"))
    trust_path = _resolve(workspace_root, reference.get("trust_manifest_ref"))
    if (
        receipt_path is None
        or receipt_path
        != oos_allocation_receipt_path(
            workspace_root, str(event.get("report_id") or "")
        ).resolve(strict=False)
        or not receipt_path.is_file()
        or receipt_path.is_symlink()
    ):
        return [f"{token}:path"]
    if (
        trust_path is None
        or trust_path
        != oos_host_trust_manifest_path(workspace_root).resolve(strict=False)
        or not trust_path.is_file()
        or trust_path.is_symlink()
    ):
        return [f"{token}:trust_manifest_path"]
    if reference.get("sha256") != sha256_file(receipt_path):
        return [f"{token}:sha256"]
    try:
        receipt = _read_json(receipt_path)
        trust_manifest = _read_json(trust_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return [f"{token}:invalid_json"]
    if validate_public_trust_manifest(trust_manifest):
        return [f"{token}:trust_manifest_invalid"]
    if reference.get("trust_manifest_sha256") != trust_manifest.get("manifest_sha256"):
        return [f"{token}:trust_manifest_sha256"]
    if reference.get("receipt_id") != receipt.get("receipt_id"):
        return [f"{token}:receipt_id"]
    signature_reasons = verify_signed_receipt_with_manifest(
        receipt,
        trust_manifest=trust_manifest,
        expected_issuer="host_admission",
    )
    if signature_reasons:
        return [f"{token}:{reason}" for reason in signature_reasons]
    expected_fields = {
        "contract_version",
        "issuer",
        "receipt_type",
        "allocation_id",
        "report_id",
        "parent_report_id",
        "lineage_root_report_id",
        "allocation_content_sha256",
        "allocation_file_sha256",
        "dataset_snapshot_sha256",
        "oos_window",
        "sealed_token_sha256",
        "registry_parent_sha256",
        "previous_event_sha256",
        "trust_manifest_sha256",
        "authority_scope",
        "allocation_authority_mode",
        "receipt_id",
        "signature",
    }
    if event.get("sealed_carrier_sha256") is not None:
        expected_fields.add("sealed_carrier_sha256")
    if event.get("build_authority_sha256") is not None:
        expected_fields.add("build_authority_sha256")
        expected_fields.add("build_authority")
    if set(receipt) != expected_fields:
        return [f"{token}:receipt_shape"]
    expected = {
        "receipt_type": OOS_ALLOCATION_RECEIPT_TYPE,
        "allocation_id": event.get("allocation_id"),
        "report_id": event.get("report_id"),
        "parent_report_id": event.get("parent_report_id"),
        "lineage_root_report_id": event.get("lineage_root_report_id"),
        "allocation_file_sha256": event.get("allocation_sha256"),
        "dataset_snapshot_sha256": event.get("dataset_snapshot_sha256"),
        "oos_window": event.get("oos_window"),
        "sealed_token_sha256": event.get("sealed_token_sha256"),
        "registry_parent_sha256": registry_parent_sha256,
        "previous_event_sha256": event.get("previous_event_sha256"),
        "trust_manifest_sha256": trust_manifest.get("manifest_sha256"),
        "authority_scope": "HOST_FRESH_OOS_ALLOCATION_ONLY",
        "allocation_authority_mode": event.get("allocation_authority_mode"),
    }
    if event.get("sealed_carrier_sha256") is not None:
        expected["sealed_carrier_sha256"] = event.get(
            "sealed_carrier_sha256"
        )
    if event.get("build_authority_sha256") is not None:
        expected["build_authority_sha256"] = event.get(
            "build_authority_sha256"
        )
        authority = receipt.get("build_authority")
        if (
            not isinstance(authority, dict)
            or stable_hash(authority) != event.get("build_authority_sha256")
        ):
            return [f"{token}:build_authority"]
        authority_reasons = _build_authority_reasons(
            authority,
            workspace_root=workspace_root,
            event=event,
        )
        if authority_reasons:
            return authority_reasons
        expected["build_authority"] = authority
    allocation_path = _resolve(workspace_root, event.get("allocation_ref"))
    if allocation_path is None:
        return [f"{token}:allocation_path"]
    try:
        allocation = _read_json(allocation_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return [f"{token}:allocation_invalid"]
    expected["allocation_content_sha256"] = allocation.get("content_sha256")
    mismatched = [
        field for field, value in expected.items() if receipt.get(field) != value
    ]
    return [f"{token}:binding:{field}" for field in mismatched]


def validate_oos_allocation(payload: Any, *, workspace_root: Path) -> list[str]:
    reasons: list[str] = []
    fields = {
        "contract_version",
        "allocation_id",
        "report_id",
        "parent_report_id",
        "lineage_root_report_id",
        "dataset_snapshot_sha256",
        "oos_window",
        "sealed_token_sha256",
        "release_state",
        "consumed",
        "host_authority",
        "allocation_authority_mode",
        "content_sha256",
    }
    optional_fields = {"sealed_carrier_sha256", "build_authority_sha256"}
    if (
        not isinstance(payload, dict)
        or not fields.issubset(payload)
        or set(payload) - fields - optional_fields
    ):
        return [f"{BLOCK_OOS_ALLOCATION}:allocation_shape"]
    if payload.get("contract_version") != OOS_ALLOCATION_VERSION:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:allocation_version")
    for field in (
        "allocation_id",
        "report_id",
        "parent_report_id",
        "lineage_root_report_id",
    ):
        if not isinstance(payload.get(field), str) or not _SAFE_ID_RE.fullmatch(
            payload[field]
        ):
            reasons.append(f"{BLOCK_OOS_ALLOCATION}:{field}")
    if payload.get("report_id") == payload.get("parent_report_id"):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:self_parent")
    for field in ("dataset_snapshot_sha256", "sealed_token_sha256"):
        if not isinstance(payload.get(field), str) or not _SHA256_RE.fullmatch(
            payload[field]
        ):
            reasons.append(f"{BLOCK_OOS_ALLOCATION}:{field}")
    if "sealed_carrier_sha256" in payload and (
        not isinstance(payload.get("sealed_carrier_sha256"), str)
        or not _SHA256_RE.fullmatch(payload["sealed_carrier_sha256"])
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_sha256")
    if "build_authority_sha256" in payload and (
        not isinstance(payload.get("build_authority_sha256"), str)
        or not _SHA256_RE.fullmatch(payload["build_authority_sha256"])
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:build_authority_sha256")
    if "build_authority_sha256" in payload and "sealed_carrier_sha256" not in payload:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:build_authority_carrier_pair")
    if _window(payload.get("oos_window")) is None:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:oos_window")
    if (
        payload.get("release_state") != "SEALED_UNRELEASED"
        or payload.get("consumed") is not False
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:not_fresh_sealed")
    if payload.get("host_authority") != OOS_HOST_AUTHORITY:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:host_authority")
    if payload.get("allocation_authority_mode") not in {
        OOS_ALLOCATION_AUTHORITY_SECURE,
        OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
    }:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:allocation_authority_mode")
    if payload.get("allocation_authority_mode") == OOS_ALLOCATION_AUTHORITY_SECURE and (
        "sealed_carrier_sha256" not in payload
        or "build_authority_sha256" not in payload
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:secure_build_authority_missing")
    unsigned = dict(payload)
    digest = unsigned.pop("content_sha256", None)
    if digest != stable_hash(unsigned):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:allocation_hash")
    return list(dict.fromkeys(reasons))


def validate_oos_registry(payload: Any, *, workspace_root: Path) -> list[str]:
    reasons: list[str] = []
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {"contract_version", "host_authority", "events", "content_sha256"}
        or payload.get("contract_version") != OOS_REGISTRY_VERSION
        or payload.get("host_authority") != OOS_HOST_AUTHORITY
    ):
        return [f"{BLOCK_OOS_ALLOCATION}:registry_shape"]
    events = payload.get("events")
    if not isinstance(events, list):
        return [f"{BLOCK_OOS_ALLOCATION}:registry_events"]
    previous_hash: str | None = None
    allocations: dict[str, dict[str, Any]] = {}
    allocated_reports: dict[str, str] = {}
    consumed: set[str] = set()
    lineage_allocations: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        prefix = f"{BLOCK_OOS_ALLOCATION}:event:{index}"
        if not isinstance(event, dict):
            reasons.append(f"{prefix}:shape")
            continue
        event_type = event.get("event_type")
        common = {
            "sequence",
            "event_type",
            "allocation_id",
            "report_id",
            "parent_report_id",
            "lineage_root_report_id",
            "actor",
            "allocation_authority_mode",
            "previous_event_sha256",
            "event_sha256",
        }
        extra = (
            {
                "allocation_ref",
                "allocation_sha256",
                "dataset_snapshot_sha256",
                "oos_window",
                "sealed_token_sha256",
                "actor_receipt_ref",
            }
            if event_type == "ALLOCATE"
            else {
                "consumption_purpose",
                "consumption_evidence_ref",
                "allocation_event_sha256",
                "allocation_host_receipt_id",
            }
            if event_type == "CONSUME"
            else set()
        )
        if event_type == "ALLOCATE" and event.get("sealed_carrier_sha256") is not None:
            extra.add("sealed_carrier_sha256")
        if event_type == "ALLOCATE" and event.get("build_authority_sha256") is not None:
            extra.add("build_authority_sha256")
        if not extra or set(event) != common | extra:
            reasons.append(f"{prefix}:shape")
            continue
        unsigned_event = dict(event)
        event_hash = unsigned_event.pop("event_sha256", None)
        if event_hash != stable_hash(unsigned_event):
            reasons.append(f"{prefix}:hash")
        expected_actor = (
            "Ultimate Host" if event_type == "ALLOCATE" else OOS_RELEASE_GATE_ACTOR
        )
        if (
            isinstance(event.get("sequence"), bool)
            or not isinstance(event.get("sequence"), int)
            or event.get("sequence") != index + 1
            or event.get("actor") != expected_actor
            or event.get("previous_event_sha256") != previous_hash
        ):
            reasons.append(f"{prefix}:chain")
        previous_hash = str(event_hash or "")
        allocation_id = str(event.get("allocation_id") or "")
        if event_type == "ALLOCATE":
            allocation_path = _resolve(workspace_root, event.get("allocation_ref"))
            if (
                allocation_path is None
                or not allocation_path.is_file()
                or allocation_path.is_symlink()
            ):
                reasons.append(f"{prefix}:allocation_ref")
                continue
            if event.get("allocation_sha256") != sha256_file(allocation_path):
                reasons.append(f"{prefix}:allocation_sha256")
                continue
            try:
                allocation = json.loads(allocation_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                reasons.append(f"{prefix}:allocation_invalid")
                continue
            reasons.extend(
                validate_oos_allocation(allocation, workspace_root=workspace_root)
            )
            if allocation_id in allocations:
                reasons.append(f"{prefix}:duplicate_allocation_id")
            report_id = str(event.get("report_id") or "")
            if report_id in allocated_reports:
                reasons.append(f"{prefix}:duplicate_report_allocation")
            bindings = (
                "allocation_id",
                "report_id",
                "parent_report_id",
                "lineage_root_report_id",
                "dataset_snapshot_sha256",
                "oos_window",
                "sealed_token_sha256",
                "allocation_authority_mode",
            )
            if event.get("sealed_carrier_sha256") is not None:
                bindings = (*bindings, "sealed_carrier_sha256")
            if event.get("build_authority_sha256") is not None:
                bindings = (*bindings, "build_authority_sha256")
            if any(event.get(field) != allocation.get(field) for field in bindings):
                reasons.append(f"{prefix}:allocation_binding")
            prior_events = events[:index]
            if prior_events:
                prior_unsigned = {
                    "contract_version": OOS_REGISTRY_VERSION,
                    "host_authority": OOS_HOST_AUTHORITY,
                    "events": prior_events,
                }
                prior_registry = {
                    **prior_unsigned,
                    "content_sha256": stable_hash(prior_unsigned),
                }
                registry_parent_sha256 = _pretty_json_sha256(prior_registry)
            else:
                registry_parent_sha256 = None
            reasons.extend(
                _host_receipt_reference_reasons(
                    event.get("actor_receipt_ref"),
                    workspace_root=workspace_root,
                    event=event,
                    registry_parent_sha256=registry_parent_sha256,
                )
            )
            new_window = _window(event.get("oos_window"))
            for earlier in lineage_allocations:
                if event.get("sealed_token_sha256") == earlier.get(
                    "sealed_token_sha256"
                ):
                    reasons.append(f"{prefix}:sealed_token_reused")
                earlier_window = _window(earlier.get("oos_window"))
                if (
                    new_window is not None
                    and earlier_window is not None
                    and event.get("lineage_root_report_id")
                    == earlier.get("lineage_root_report_id")
                    and event.get("dataset_snapshot_sha256")
                    == earlier.get("dataset_snapshot_sha256")
                    and _overlap(new_window, earlier_window)
                ):
                    reasons.append(f"{prefix}:lineage_dataset_window_reused")
            allocations[allocation_id] = event
            allocated_reports[report_id] = allocation_id
            lineage_allocations.append(event)
        else:
            allocation = allocations.get(allocation_id)
            evidence = event.get("consumption_evidence_ref")
            evidence_path = _resolve(
                workspace_root,
                (evidence or {}).get("path") if isinstance(evidence, dict) else None,
            )
            if allocation is None or allocation_id in consumed:
                reasons.append(f"{prefix}:allocation_not_available")
            if allocation is not None and any(
                event.get(field) != allocation.get(field)
                for field in ("report_id", "parent_report_id", "lineage_root_report_id")
            ):
                reasons.append(f"{prefix}:allocation_identity")
            if allocation is not None and (
                event.get("allocation_event_sha256") != allocation.get("event_sha256")
                or event.get("allocation_host_receipt_id")
                != (allocation.get("actor_receipt_ref") or {}).get("receipt_id")
            ):
                reasons.append(f"{prefix}:allocation_authority_binding")
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"path", "sha256"}
                or evidence_path is None
                or not evidence_path.is_file()
                or evidence_path.is_symlink()
                or evidence.get("sha256") != sha256_file(evidence_path)
            ):
                reasons.append(f"{prefix}:consumption_evidence")
            elif allocation is not None:
                try:
                    release = _read_json(evidence_path)
                except (OSError, json.JSONDecodeError, ValueError):
                    reasons.append(f"{prefix}:consumption_evidence_payload")
                else:
                    reasons.extend(
                        _release_evidence_contract_reasons(
                            release,
                            workspace_root=workspace_root,
                        )
                    )
                    if (
                        release.get("release_status") != "RELEASED"
                        or release.get("report_id") != allocation.get("report_id")
                        or release.get("dataset_snapshot_hash")
                        != allocation.get("dataset_snapshot_sha256")
                        or release.get("oos_release_token_hash")
                        != allocation.get("sealed_token_sha256")
                        or _window(release.get("oos_window"))
                        != _window(allocation.get("oos_window"))
                    ):
                        reasons.append(f"{prefix}:consumption_evidence_binding")
            if event.get("consumption_purpose") != OOS_CONSUMPTION_PURPOSE:
                reasons.append(f"{prefix}:consumption_purpose")
            consumed.add(allocation_id)
    unsigned_registry = dict(payload)
    registry_hash = unsigned_registry.pop("content_sha256", None)
    if registry_hash != stable_hash(unsigned_registry):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:registry_hash")
    return list(dict.fromkeys(reasons))


def _related_reports(root: Path, parent_report_id: str) -> set[str]:
    parent_by_child: dict[str, str] = {}
    registry_path = oos_registry_path(root)
    if registry_path.is_file() and not registry_path.is_symlink():
        try:
            registry = _read_json(registry_path)
        except (OSError, json.JSONDecodeError, ValueError):
            registry = {}
        for event in registry.get("events") or []:
            if not isinstance(event, dict) or event.get("event_type") != "ALLOCATE":
                continue
            child = event.get("report_id")
            parent = event.get("parent_report_id")
            if isinstance(child, str) and isinstance(parent, str):
                parent_by_child[child] = parent
    for path in (root / "objects" / "runtime_context").glob(
        "child_revision_materialization__*.json"
    ):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        child = row.get("child_report_id")
        parent = row.get("parent_report_id")
        if isinstance(child, str) and isinstance(parent, str):
            parent_by_child.setdefault(child, parent)
    ancestors = {parent_report_id}
    cursor = parent_report_id
    while cursor in parent_by_child and parent_by_child[cursor] not in ancestors:
        cursor = parent_by_child[cursor]
        ancestors.add(cursor)
    related = set(ancestors)
    changed = True
    while changed:
        changed = False
        for child, parent in parent_by_child.items():
            if parent in related and child not in related:
                related.add(child)
                changed = True
    return related


def expected_lineage_root_report_id(root: Path, parent_report_id: str) -> str:
    registry_path = oos_registry_path(root)
    if not registry_path.exists() and not registry_path.is_symlink():
        if _report_has_evo_lineage_authority_marker(root, parent_report_id):
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:incident_lineage_registry_missing"
            )
        return parent_report_id
    if not registry_path.is_file() or registry_path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_path_unsafe")
    try:
        registry = _read_json(registry_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_invalid") from exc
    registry_reasons = validate_oos_registry(registry, workspace_root=root)
    if registry_reasons:
        raise ValueError(";".join(registry_reasons))
    parent_allocations = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "ALLOCATE"
        and event.get("report_id") == parent_report_id
    ]
    if len(parent_allocations) > 1:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:parent_lineage_ambiguous")
    if parent_allocations:
        return str(parent_allocations[0]["lineage_root_report_id"])
    return parent_report_id


def _released_lineage_reuse_reasons(
    *,
    root: Path,
    parent_report_id: str,
    allocation: dict[str, Any],
    exclude_report_id: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    candidate_window = _window(allocation.get("oos_window"))
    related = _related_reports(root, parent_report_id)
    for release_path in (root / "objects").glob("**/oos_release_manifest*.json"):
        if not release_path.is_file() or release_path.is_symlink():
            continue
        try:
            release = _read_json(release_path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if (
            release.get("report_id") not in related
            or release.get("report_id") == exclude_report_id
            or release.get("release_status") != "RELEASED"
        ):
            continue
        released_window = _window(release.get("oos_window"))
        if release.get("oos_release_token_hash") == allocation.get(
            "sealed_token_sha256"
        ):
            reasons.append(f"{BLOCK_OOS_ALLOCATION}:ancestor_or_sibling_token_reused")
        if (
            candidate_window is not None
            and released_window is not None
            and release.get("dataset_snapshot_hash")
            == allocation.get("dataset_snapshot_sha256")
            and _overlap(candidate_window, released_window)
        ):
            reasons.append(
                f"{BLOCK_OOS_ALLOCATION}:ancestor_or_sibling_dataset_window_reused"
            )
    return list(dict.fromkeys(reasons))


def validate_fresh_child_oos_allocation(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    allocation_id: str,
    allocation_ref: str,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    marker_reasons = _public_marker_incident_reasons(
        workspace_root=root,
        report_id=child_report_id,
    )
    if marker_reasons:
        return marker_reasons
    try:
        with _current_incident_authority_guard(
            trust_root=incident_trust_root,
            installation_id=incident_installation_id,
            guard=_incident_guard,
        ) as (guard, trust_root, installation_id):
            return _validate_fresh_child_oos_allocation_guarded(
                root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                allocation_id=allocation_id,
                allocation_ref=allocation_ref,
                incident_trust_root=trust_root,
                incident_installation_id=installation_id,
                _incident_guard=guard,
            )
    except (OSError, ValueError) as exc:
        return [str(exc)]


def _validate_fresh_child_oos_allocation_guarded(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    allocation_id: str,
    allocation_ref: str,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> list[str]:
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    reasons: list[str] = []
    reasons.extend(
        _allocation_incident_reasons(
            root=root,
            report_id=child_report_id,
            parent_report_id=parent_report_id,
            trust_root=incident_trust_root,
            installation_id=incident_installation_id,
        )
    )
    if reasons:
        return list(dict.fromkeys(reasons))
    return validate_fresh_child_oos_allocation_structural(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        allocation_id=allocation_id,
        allocation_ref=allocation_ref,
    )


def validate_fresh_child_oos_allocation_structural(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    allocation_id: str,
    allocation_ref: str,
) -> list[str]:
    """Replay allocation bytes only; no present-tense Host authority is granted."""

    reasons: list[str] = []
    allocation_path = _resolve(root, allocation_ref)
    expected_path = oos_allocation_path(root, child_report_id).resolve(strict=False)
    if (
        allocation_path != expected_path
        or not expected_path.is_file()
        or expected_path.is_symlink()
    ):
        return [f"{WAITING_FRESH_OOS}:allocation_missing_or_noncanonical"]
    try:
        allocation = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"{BLOCK_OOS_ALLOCATION}:allocation_invalid"]
    reasons.extend(validate_oos_allocation(allocation, workspace_root=root))
    if allocation.get("allocation_authority_mode") != OOS_ALLOCATION_AUTHORITY_SECURE:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:formal_child_requires_private_carrier_build")
    if (
        allocation.get("allocation_id") != allocation_id
        or allocation.get("report_id") != child_report_id
        or allocation.get("parent_report_id") != parent_report_id
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:child_binding")
    try:
        expected_lineage = expected_lineage_root_report_id(root, parent_report_id)
    except ValueError as exc:
        reasons.append(str(exc))
        expected_lineage = None
    if (
        expected_lineage is not None
        and allocation.get("lineage_root_report_id") != expected_lineage
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:lineage_root_binding")
    registry_path = oos_registry_path(root)
    if not registry_path.is_file() or registry_path.is_symlink():
        reasons.append(f"{WAITING_FRESH_OOS}:registry_missing")
        return list(dict.fromkeys(reasons))
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:registry_invalid")
        return list(dict.fromkeys(reasons))
    reasons.extend(validate_oos_registry(registry, workspace_root=root))
    events = registry.get("events") if isinstance(registry, dict) else []
    allocations = [
        event
        for event in events or []
        if isinstance(event, dict)
        and event.get("event_type") == "ALLOCATE"
        and event.get("allocation_id") == allocation_id
    ]
    consumptions = [
        event
        for event in events or []
        if isinstance(event, dict)
        and event.get("event_type") == "CONSUME"
        and event.get("allocation_id") == allocation_id
    ]
    if len(allocations) != 1 or consumptions:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:allocation_not_available")
    else:
        event = allocations[0]
        if event.get("allocation_ref") != expected_path.relative_to(
            root
        ).as_posix() or event.get("allocation_sha256") != sha256_file(expected_path):
            reasons.append(f"{BLOCK_OOS_ALLOCATION}:registry_allocation_binding")

    reasons.extend(
        _released_lineage_reuse_reasons(
            root=root,
            parent_report_id=parent_report_id,
            allocation=allocation,
        )
    )
    return list(dict.fromkeys(reasons))


def build_oos_registry_allocation_prefix(
    *,
    root: Path,
    allocation_id: str,
    report_id: str,
) -> dict[str, Any]:
    """Freeze one allocation's authority without freezing future appends.

    The projection commits to the complete registry prefix visible at issuance,
    the exact allocation event, and its Host receipt.  A consumer can therefore
    accept a later registry only when it is a valid append-only descendant of
    that prefix; it must not compare against the later whole-file hash.
    """

    workspace = root.expanduser().resolve(strict=True)
    registry_path = oos_registry_path(workspace)
    if not registry_path.is_file() or registry_path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_missing")
    registry = _read_json(registry_path)
    reasons = validate_oos_registry(registry, workspace_root=workspace)
    if reasons:
        raise ValueError(";".join(reasons))
    if registry_path.read_bytes() != _pretty_json_bytes(registry):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_not_canonical")
    matches = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "ALLOCATE"
        and event.get("allocation_id") == allocation_id
        and event.get("report_id") == report_id
    ]
    if len(matches) != 1:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:allocation_event_identity")
    event = matches[0]
    events = list(registry["events"])
    prefix = _registry_payload(events)
    return {
        "contract_version": OOS_REGISTRY_ALLOCATION_PREFIX_VERSION,
        "path": _relative_ref(workspace, registry_path),
        "prefix_event_count": len(events),
        "prefix_file_sha256": _pretty_json_sha256(prefix),
        "prefix_content_sha256": prefix["content_sha256"],
        "prefix_terminal_event_sha256": events[-1]["event_sha256"],
        "allocation_event_sequence": event["sequence"],
        "allocation_event_sha256": event["event_sha256"],
        "allocation_host_receipt_ref": dict(event["actor_receipt_ref"]),
    }


def validate_oos_registry_allocation_prefix(
    projection: Any,
    *,
    root: Path,
    allocation_id: str,
    report_id: str,
) -> list[str]:
    """Verify an issuance prefix against the current append-only registry."""

    token = f"{BLOCK_OOS_ALLOCATION}:registry_allocation_prefix"
    fields = {
        "contract_version",
        "path",
        "prefix_event_count",
        "prefix_file_sha256",
        "prefix_content_sha256",
        "prefix_terminal_event_sha256",
        "allocation_event_sequence",
        "allocation_event_sha256",
        "allocation_host_receipt_ref",
    }
    if not isinstance(projection, Mapping) or set(projection) != fields:
        return [f"{token}:shape"]
    reasons: list[str] = []
    if projection.get("contract_version") != OOS_REGISTRY_ALLOCATION_PREFIX_VERSION:
        reasons.append(f"{token}:version")
    for field in (
        "prefix_file_sha256",
        "prefix_content_sha256",
        "prefix_terminal_event_sha256",
        "allocation_event_sha256",
    ):
        if not isinstance(projection.get(field), str) or not _SHA256_RE.fullmatch(
            str(projection.get(field) or "")
        ):
            reasons.append(f"{token}:{field}")
    prefix_count = projection.get("prefix_event_count")
    event_sequence = projection.get("allocation_event_sequence")
    if (
        isinstance(prefix_count, bool)
        or not isinstance(prefix_count, int)
        or prefix_count <= 0
        or isinstance(event_sequence, bool)
        or not isinstance(event_sequence, int)
        or event_sequence <= 0
        or event_sequence > prefix_count
    ):
        reasons.append(f"{token}:sequence")
    workspace = root.expanduser().resolve(strict=True)
    registry_path = _resolve(workspace, projection.get("path"))
    expected_path = oos_registry_path(workspace).resolve(strict=False)
    if (
        registry_path != expected_path
        or not expected_path.is_file()
        or expected_path.is_symlink()
    ):
        reasons.append(f"{token}:path")
        return list(dict.fromkeys(reasons))
    try:
        registry = _read_json(expected_path)
    except (OSError, json.JSONDecodeError, ValueError):
        reasons.append(f"{token}:registry_invalid")
        return list(dict.fromkeys(reasons))
    reasons.extend(validate_oos_registry(registry, workspace_root=workspace))
    if expected_path.read_bytes() != _pretty_json_bytes(registry):
        reasons.append(f"{token}:registry_not_canonical")
    events = registry.get("events") if isinstance(registry, dict) else None
    if not isinstance(events, list) or not isinstance(prefix_count, int):
        reasons.append(f"{token}:events")
        return list(dict.fromkeys(reasons))
    if len(events) < prefix_count:
        reasons.append(f"{token}:not_descendant")
        return list(dict.fromkeys(reasons))
    prefix = _registry_payload(list(events[:prefix_count]))
    if (
        projection.get("prefix_file_sha256") != _pretty_json_sha256(prefix)
        or projection.get("prefix_content_sha256") != prefix["content_sha256"]
        or projection.get("prefix_terminal_event_sha256")
        != events[prefix_count - 1].get("event_sha256")
    ):
        reasons.append(f"{token}:prefix_mismatch")
    if not isinstance(event_sequence, int) or event_sequence > len(events):
        reasons.append(f"{token}:allocation_event_missing")
        return list(dict.fromkeys(reasons))
    allocation_event = events[event_sequence - 1]
    if (
        not isinstance(allocation_event, dict)
        or allocation_event.get("event_type") != "ALLOCATE"
        or allocation_event.get("allocation_id") != allocation_id
        or allocation_event.get("report_id") != report_id
        or allocation_event.get("event_sha256")
        != projection.get("allocation_event_sha256")
        or allocation_event.get("actor_receipt_ref")
        != projection.get("allocation_host_receipt_ref")
    ):
        reasons.append(f"{token}:allocation_event_binding")
    if any(
        isinstance(event, dict)
        and event.get("event_type") == "CONSUME"
        and event.get("allocation_id") == allocation_id
        for event in events
    ):
        reasons.append(f"{token}:allocation_consumed")
    return list(dict.fromkeys(reasons))


def write_registry_cas(
    path: Path,
    payload: dict[str, Any],
    *,
    expected_parent_sha256: str | None,
) -> None:
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked_registry(path):
        _write_registry_cas_unlocked(
            path,
            payload,
            expected_parent_sha256=expected_parent_sha256,
        )


@contextmanager
def _locked_registry(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(raw)
    try:
        encoded = _pretty_json_bytes(payload)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_once_or_same(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:immutable_path_unsafe")
        try:
            existing = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:immutable_path_invalid") from exc
        if existing != payload or path.read_bytes() != _pretty_json_bytes(existing):
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:immutable_path_conflict")
        return
    _atomic_write_json(path, payload)


def _write_private_oos_locator(
    *,
    trust_store: Any,
    trust_root: Path,
    allocation_id: str,
    report_id: str,
    parent_report_id: str,
    private_root: Path,
    carrier: Path,
    sealed_carrier_sha256: str,
    dataset_snapshot_sha256: str,
    build_authority_sha256: str,
) -> dict[str, Any]:
    locator_id = _private_oos_locator_id(
        allocation_id=allocation_id,
        report_id=report_id,
        parent_report_id=parent_report_id,
    )
    locator_path = private_oos_locator_path(trust_root, locator_id)
    locator_payload = {
        "receipt_type": OOS_PRIVATE_LOCATOR_TYPE,
        "private_locator_id": locator_id,
        "allocation_id": allocation_id,
        "report_id": report_id,
        "parent_report_id": parent_report_id,
        "private_root": str(private_root),
        "sealed_oos_carrier_path": str(carrier),
        "sealed_carrier_sha256": sealed_carrier_sha256,
        "dataset_snapshot_sha256": dataset_snapshot_sha256,
        "build_authority_sha256": build_authority_sha256,
        "authority_scope": OOS_PRIVATE_LOCATOR_SCOPE,
        "trust_manifest_sha256": trust_store.public_manifest["manifest_sha256"],
    }
    locator = trust_store.sign("host_admission", locator_payload)
    locator_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    locator_path.parent.chmod(0o700)
    with _locked_registry(locator_path):
        _write_json_once_or_same(locator_path, locator)
        locator_path.chmod(0o600)
    locator_metadata = locator_path.lstat()
    if (
        locator_path.is_symlink()
        or not locator_path.is_file()
        or locator_metadata.st_uid != os.getuid()
        or locator_metadata.st_mode & 0o077
        or locator_metadata.st_nlink != 1
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_locator_unsafe")
    return {
        "private_locator_id": locator_id,
        "private_locator_receipt_id": locator["receipt_id"],
        "private_locator_status": "HOST_PRIVATE_PERSISTED",
    }


def resolve_host_private_oos_carrier(
    *,
    workspace_root: Path,
    trust_root: Path,
    installation_id: str,
    allocation_id: str,
    report_id: str,
    parent_report_id: str,
    expected_host_trust_manifest_sha256: str,
    expected_sealed_carrier_sha256: str,
    expected_dataset_snapshot_sha256: str,
    expected_build_authority_sha256: str,
    agent_visible_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Resolve one restart-safe carrier locator without publishing its path."""

    try:
        workspace = workspace_root.expanduser().resolve(strict=True)
        private_trust_raw = trust_root.expanduser()
        if private_trust_raw.is_symlink():
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:private_locator_trust_root_unsafe"
            )
        private_trust = private_trust_raw.resolve(strict=True)
        visible_roots = [
            workspace,
            Path(__file__).resolve().parents[1],
            *[
                item.expanduser().resolve(strict=True)
                for item in list(agent_visible_roots or [])
            ],
        ]
        if (
            private_trust.stat().st_uid != os.getuid()
            or private_trust.stat().st_mode & 0o077
            or any(
                private_trust == visible
                or visible in private_trust.parents
                or private_trust in visible.parents
                for visible in visible_roots
            )
        ):
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:private_locator_trust_root_unsafe"
            )
        store = load_runtime_trust_store(
            private_trust,
            installation_id=installation_id,
        )
    except (OSError, RuntimeError):
        raise ValueError(
            f"{BLOCK_OOS_ALLOCATION}:private_locator_trust_unavailable"
        ) from None
    if (
        not _SHA256_RE.fullmatch(expected_host_trust_manifest_sha256)
        or store.public_manifest.get("manifest_sha256")
        != expected_host_trust_manifest_sha256
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_locator_host_trust_pin")
    locator_id = _private_oos_locator_id(
        allocation_id=allocation_id,
        report_id=report_id,
        parent_report_id=parent_report_id,
    )
    try:
        locator_path = private_oos_locator_path(private_trust, locator_id)
        if locator_path.is_symlink() or not locator_path.is_file():
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_locator_unsafe")
        locator_metadata = locator_path.lstat()
        if (
            locator_metadata.st_uid != os.getuid()
            or locator_metadata.st_mode & 0o077
            or locator_metadata.st_nlink != 1
        ):
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_locator_unsafe")
        locator = _read_json(locator_path)
    except OSError:
        raise ValueError(
            f"{BLOCK_OOS_ALLOCATION}:private_locator_unavailable"
        ) from None
    signature_reasons = verify_signed_receipt_with_manifest(
        locator,
        trust_manifest=store.public_manifest,
        expected_issuer="host_admission",
    )
    expected_fields = {
        "contract_version",
        "issuer",
        "receipt_type",
        "private_locator_id",
        "allocation_id",
        "report_id",
        "parent_report_id",
        "private_root",
        "sealed_oos_carrier_path",
        "sealed_carrier_sha256",
        "dataset_snapshot_sha256",
        "build_authority_sha256",
        "authority_scope",
        "trust_manifest_sha256",
        "receipt_id",
        "signature",
    }
    if signature_reasons or set(locator) != expected_fields:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_locator_signature_or_shape")
    expected = {
        "receipt_type": OOS_PRIVATE_LOCATOR_TYPE,
        "private_locator_id": locator_id,
        "allocation_id": allocation_id,
        "report_id": report_id,
        "parent_report_id": parent_report_id,
        "sealed_carrier_sha256": expected_sealed_carrier_sha256,
        "dataset_snapshot_sha256": expected_dataset_snapshot_sha256,
        "build_authority_sha256": expected_build_authority_sha256,
        "authority_scope": OOS_PRIVATE_LOCATOR_SCOPE,
        "trust_manifest_sha256": store.public_manifest["manifest_sha256"],
    }
    if any(locator.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_locator_binding")
    try:
        private_root_raw = Path(str(locator["private_root"])).expanduser()
        if private_root_raw.is_symlink():
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:private_locator_carrier_symlink"
            )
        private_root = private_root_raw.resolve(strict=True)
        carrier = Path(str(locator["sealed_oos_carrier_path"])).expanduser()
        if carrier.is_symlink():
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:private_locator_carrier_symlink"
            )
        carrier = carrier.resolve(strict=True)
        if (
            private_root.stat().st_uid != os.getuid()
            or private_root.stat().st_mode & 0o077
            or private_root not in carrier.parents
            or any(
                private_root == visible
                or visible in private_root.parents
                or private_root in visible.parents
                for visible in visible_roots
            )
            or not carrier.is_file()
            or carrier.stat().st_uid != os.getuid()
            or carrier.stat().st_mode & 0o077
            or carrier.lstat().st_nlink != 1
            or sha256_file(carrier) != expected_sealed_carrier_sha256
        ):
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:private_locator_carrier_unsafe"
            )
    except OSError:
        raise ValueError(
            f"{BLOCK_OOS_ALLOCATION}:private_locator_carrier_unavailable"
        ) from None
    return {
        "private_locator_id": locator_id,
        "sealed_oos_carrier_path": carrier,
        "sealed_oos_private_root": private_root,
        "sealed_carrier_sha256": expected_sealed_carrier_sha256,
        "dataset_snapshot_sha256": expected_dataset_snapshot_sha256,
        "build_authority_sha256": expected_build_authority_sha256,
    }


def _write_registry_cas_unlocked(
    path: Path,
    payload: dict[str, Any],
    *,
    expected_parent_sha256: str | None,
) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_path_unsafe")
    current_sha = sha256_file(path) if path.is_file() else None
    if current_sha != expected_parent_sha256:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_cas_mismatch")
    if path.is_file():
        try:
            current = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_invalid") from exc
        current_reasons = validate_oos_registry(
            current,
            workspace_root=path.resolve(strict=False).parents[2],
        )
        if current_reasons:
            raise ValueError(";".join(current_reasons))
        current_events = current.get("events") or []
        next_events = payload.get("events") if isinstance(payload, dict) else None
        if (
            not isinstance(next_events, list)
            or len(next_events) < len(current_events)
            or next_events[: len(current_events)] != current_events
        ):
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_not_append_only")
    reasons = validate_oos_registry(
        payload,
        workspace_root=path.resolve(strict=False).parents[2],
    )
    if reasons:
        raise ValueError(";".join(reasons))
    _atomic_write_json(path, payload)


def _registry_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    unsigned = {
        "contract_version": OOS_REGISTRY_VERSION,
        "host_authority": OOS_HOST_AUTHORITY,
        "events": events,
    }
    return {**unsigned, "content_sha256": stable_hash(unsigned)}


def build_fresh_child_oos_allocation(
    *,
    allocation_id: str,
    report_id: str,
    parent_report_id: str,
    lineage_root_report_id: str,
    dataset_snapshot_sha256: str,
    oos_start: str,
    oos_end: str,
    sealed_token_sha256: str,
    sealed_carrier_sha256: str | None = None,
    build_authority_sha256: str | None = None,
    allocation_authority_mode: str = OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
) -> dict[str, Any]:
    unsigned = {
        "contract_version": OOS_ALLOCATION_VERSION,
        "allocation_id": allocation_id,
        "report_id": report_id,
        "parent_report_id": parent_report_id,
        "lineage_root_report_id": lineage_root_report_id,
        "dataset_snapshot_sha256": dataset_snapshot_sha256,
        "oos_window": {"start": oos_start, "end": oos_end},
        "sealed_token_sha256": sealed_token_sha256,
        "release_state": "SEALED_UNRELEASED",
        "consumed": False,
        "host_authority": OOS_HOST_AUTHORITY,
        "allocation_authority_mode": allocation_authority_mode,
    }
    if sealed_carrier_sha256 is not None:
        unsigned["sealed_carrier_sha256"] = sealed_carrier_sha256
    if build_authority_sha256 is not None:
        unsigned["build_authority_sha256"] = build_authority_sha256
    return {**unsigned, "content_sha256": stable_hash(unsigned)}


def _allocate_fresh_child_oos(
    *,
    workspace_root: Path,
    allocation_id: str,
    report_id: str,
    parent_report_id: str,
    dataset_snapshot_sha256: str,
    oos_start: str,
    oos_end: str,
    sealed_token_sha256: str,
    sealed_carrier_sha256: str | None = None,
    build_authority_sha256: str | None = None,
    build_authority: Mapping[str, Any] | None = None,
    allocation_authority_mode: str,
    expected_registry_sha256: str | None,
    trust_root: Path,
    installation_id: str,
    lineage_root_report_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    """Host-sign and append one fresh child allocation under a locked CAS."""

    root = workspace_root.expanduser().resolve(strict=True)
    public_incident_reasons: list[str] = []
    for identity in dict.fromkeys((report_id, parent_report_id)):
        public_incident_reasons.extend(
            _public_marker_incident_reasons(
                workspace_root=root,
                report_id=identity,
            )
        )
    if public_incident_reasons:
        raise ValueError(";".join(dict.fromkeys(public_incident_reasons)))

    with _current_incident_authority_guard(
        trust_root=trust_root,
        installation_id=installation_id,
        guard=_incident_guard,
    ) as (guard, resolved_trust, resolved_installation):
        return _allocate_fresh_child_oos_guarded(
            workspace_root=workspace_root,
            allocation_id=allocation_id,
            report_id=report_id,
            parent_report_id=parent_report_id,
            dataset_snapshot_sha256=dataset_snapshot_sha256,
            oos_start=oos_start,
            oos_end=oos_end,
            sealed_token_sha256=sealed_token_sha256,
            sealed_carrier_sha256=sealed_carrier_sha256,
            build_authority_sha256=build_authority_sha256,
            build_authority=build_authority,
            allocation_authority_mode=allocation_authority_mode,
            expected_registry_sha256=expected_registry_sha256,
            trust_root=resolved_trust,
            installation_id=resolved_installation,
            lineage_root_report_id=lineage_root_report_id,
            _incident_guard=guard,
        )


def _allocate_fresh_child_oos_guarded(
    *,
    workspace_root: Path,
    allocation_id: str,
    report_id: str,
    parent_report_id: str,
    dataset_snapshot_sha256: str,
    oos_start: str,
    oos_end: str,
    sealed_token_sha256: str,
    sealed_carrier_sha256: str | None,
    build_authority_sha256: str | None,
    build_authority: Mapping[str, Any] | None,
    allocation_authority_mode: str,
    expected_registry_sha256: str | None,
    trust_root: Path,
    installation_id: str,
    lineage_root_report_id: str | None,
    _incident_guard: object,
) -> dict[str, Any]:
    """Publish while the Host-private incident registry head is locked."""

    root = workspace_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:workspace_root")
    incident_reasons = _allocation_incident_reasons(
        root=root,
        report_id=report_id,
        parent_report_id=parent_report_id,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    private_root = trust_root.expanduser().resolve(strict=True)
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=private_root,
        installation_id=installation_id,
    )
    if private_root == root or root in private_root.parents:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:trust_root_inside_workspace")
    expected_lineage = expected_lineage_root_report_id(root, parent_report_id)
    if (
        lineage_root_report_id is not None
        and lineage_root_report_id != expected_lineage
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:lineage_root_binding")
    lineage_root = expected_lineage
    if allocation_authority_mode == OOS_ALLOCATION_AUTHORITY_SECURE:
        if (
            not isinstance(build_authority, Mapping)
            or build_authority_sha256 != stable_hash(dict(build_authority))
            or sealed_carrier_sha256 is None
        ):
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:secure_build_authority_invalid")
    elif allocation_authority_mode == OOS_ALLOCATION_AUTHORITY_LEGACY_TEST:
        if build_authority is not None or build_authority_sha256 is not None:
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:legacy_build_authority_forbidden")
    else:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:allocation_authority_mode")
    allocation = build_fresh_child_oos_allocation(
        allocation_id=allocation_id,
        report_id=report_id,
        parent_report_id=parent_report_id,
        lineage_root_report_id=lineage_root,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        oos_start=oos_start,
        oos_end=oos_end,
        sealed_token_sha256=sealed_token_sha256,
        sealed_carrier_sha256=sealed_carrier_sha256,
        build_authority_sha256=build_authority_sha256,
        allocation_authority_mode=allocation_authority_mode,
    )
    allocation_reasons = validate_oos_allocation(allocation, workspace_root=root)
    if allocation_reasons:
        raise ValueError(";".join(allocation_reasons))

    trust_store = load_runtime_trust_store(
        private_root,
        installation_id=installation_id,
    )
    trust_manifest = trust_store.public_manifest
    if validate_public_trust_manifest(trust_manifest):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:trust_manifest_invalid")
    trust_path = oos_host_trust_manifest_path(root)

    registry_path = oos_registry_path(root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    allocation_path = oos_allocation_path(root, report_id)
    receipt_path = oos_allocation_receipt_path(root, report_id)
    with _locked_registry(registry_path):
        _write_json_once_or_same(trust_path, trust_manifest)
        if registry_path.is_symlink() or (
            registry_path.exists() and not registry_path.is_file()
        ):
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_path_unsafe")
        current_sha = sha256_file(registry_path) if registry_path.is_file() else None
        if registry_path.is_file():
            current = _read_json(registry_path)
            current_reasons = validate_oos_registry(current, workspace_root=root)
            if current_reasons:
                raise ValueError(";".join(current_reasons))
            if registry_path.read_bytes() != _pretty_json_bytes(current):
                raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_not_canonical")
        else:
            current = _registry_payload([])
        events = list(current["events"])
        if current_sha != expected_registry_sha256:
            exact_events = [
                event
                for event in events
                if event.get("event_type") == "ALLOCATE"
                and event.get("allocation_id") == allocation_id
                and event.get("report_id") == report_id
            ]
            consumed = any(
                event.get("event_type") == "CONSUME"
                and event.get("allocation_id") == allocation_id
                for event in events
            )
            receipt_parent = None
            if len(exact_events) == 1:
                receipt_ref = exact_events[0].get("actor_receipt_ref") or {}
                receipt_candidate = _resolve(root, receipt_ref.get("path"))
                if (
                    receipt_candidate is not None
                    and receipt_candidate.is_file()
                    and not receipt_candidate.is_symlink()
                ):
                    receipt_parent = _read_json(receipt_candidate).get(
                        "registry_parent_sha256"
                    )
            if (
                not consumed
                and len(exact_events) == 1
                and receipt_parent == expected_registry_sha256
                and allocation_path.is_file()
                and not allocation_path.is_symlink()
                and _read_json(allocation_path) == allocation
                and exact_events[0].get("allocation_sha256")
                == sha256_file(allocation_path)
            ):
                return {
                    "verdict": "PASS",
                    "status": "IDENTICAL_REPLAY",
                    "allocation_ref": _relative_ref(root, allocation_path),
                    "allocation_sha256": sha256_file(allocation_path),
                    "registry_ref": _relative_ref(root, registry_path),
                    "registry_sha256": current_sha,
                    "registry_content_sha256": current["content_sha256"],
                    "lineage_root_report_id": lineage_root,
                }
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:registry_cas_mismatch")
        locked_parent_allocations = [
            event
            for event in events
            if event.get("event_type") == "ALLOCATE"
            and event.get("report_id") == parent_report_id
        ]
        if len(locked_parent_allocations) > 1:
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:parent_lineage_ambiguous")
        locked_lineage = (
            str(locked_parent_allocations[0]["lineage_root_report_id"])
            if locked_parent_allocations
            else parent_report_id
        )
        if lineage_root != locked_lineage:
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:lineage_registry_race")
        existing = [
            event
            for event in events
            if event.get("event_type") == "ALLOCATE"
            and (
                event.get("allocation_id") == allocation_id
                or event.get("report_id") == report_id
            )
        ]
        if existing:
            consumed = any(
                event.get("event_type") == "CONSUME"
                and event.get("allocation_id") == allocation_id
                for event in events
            )
            if (
                not consumed
                and len(existing) == 1
                and allocation_path.is_file()
                and not allocation_path.is_symlink()
                and _read_json(allocation_path) == allocation
                and existing[0].get("allocation_id") == allocation_id
                and existing[0].get("allocation_sha256") == sha256_file(allocation_path)
            ):
                return {
                    "verdict": "PASS",
                    "status": "IDENTICAL_REPLAY",
                    "allocation_ref": _relative_ref(root, allocation_path),
                    "allocation_sha256": sha256_file(allocation_path),
                    "registry_ref": _relative_ref(root, registry_path),
                    "registry_sha256": current_sha,
                    "registry_content_sha256": current["content_sha256"],
                    "lineage_root_report_id": lineage_root,
                }
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:duplicate_allocation_or_report")

        new_window = _window(allocation["oos_window"])
        for earlier in (
            event for event in events if event.get("event_type") == "ALLOCATE"
        ):
            if earlier.get("sealed_token_sha256") == sealed_token_sha256:
                raise ValueError(f"{BLOCK_OOS_ALLOCATION}:sealed_token_reused")
            earlier_window = _window(earlier.get("oos_window"))
            if (
                new_window is not None
                and earlier_window is not None
                and earlier.get("lineage_root_report_id") == lineage_root
                and earlier.get("dataset_snapshot_sha256") == dataset_snapshot_sha256
                and _overlap(new_window, earlier_window)
            ):
                raise ValueError(
                    f"{BLOCK_OOS_ALLOCATION}:lineage_dataset_window_reused"
                )
        release_reasons = _released_lineage_reuse_reasons(
            root=root,
            parent_report_id=parent_report_id,
            allocation=allocation,
        )
        if release_reasons:
            raise ValueError(";".join(release_reasons))

        _write_json_once_or_same(allocation_path, allocation)
        previous_event_sha256 = events[-1]["event_sha256"] if events else None
        receipt_payload = {
                "receipt_type": OOS_ALLOCATION_RECEIPT_TYPE,
                "allocation_id": allocation_id,
                "report_id": report_id,
                "parent_report_id": parent_report_id,
                "lineage_root_report_id": lineage_root,
                "allocation_content_sha256": allocation["content_sha256"],
                "allocation_file_sha256": sha256_file(allocation_path),
                "dataset_snapshot_sha256": dataset_snapshot_sha256,
                "oos_window": allocation["oos_window"],
                "sealed_token_sha256": sealed_token_sha256,
                "registry_parent_sha256": current_sha,
                "previous_event_sha256": previous_event_sha256,
                "trust_manifest_sha256": trust_manifest["manifest_sha256"],
                "authority_scope": "HOST_FRESH_OOS_ALLOCATION_ONLY",
                "allocation_authority_mode": allocation_authority_mode,
        }
        if sealed_carrier_sha256 is not None:
            receipt_payload["sealed_carrier_sha256"] = sealed_carrier_sha256
        if build_authority_sha256 is not None:
            receipt_payload["build_authority_sha256"] = build_authority_sha256
            receipt_payload["build_authority"] = dict(build_authority or {})
        receipt = trust_store.sign("host_admission", receipt_payload)
        _write_json_once_or_same(receipt_path, receipt)
        receipt_ref = {
            "path": _relative_ref(root, receipt_path),
            "sha256": sha256_file(receipt_path),
            "receipt_id": receipt["receipt_id"],
            "trust_manifest_ref": _relative_ref(root, trust_path),
            "trust_manifest_sha256": trust_manifest["manifest_sha256"],
        }
        event_unsigned = {
            "sequence": len(events) + 1,
            "event_type": "ALLOCATE",
            "allocation_id": allocation_id,
            "report_id": report_id,
            "parent_report_id": parent_report_id,
            "lineage_root_report_id": lineage_root,
            "actor": "Ultimate Host",
            "allocation_authority_mode": allocation_authority_mode,
            "previous_event_sha256": previous_event_sha256,
            "allocation_ref": _relative_ref(root, allocation_path),
            "allocation_sha256": sha256_file(allocation_path),
            "dataset_snapshot_sha256": dataset_snapshot_sha256,
            "oos_window": allocation["oos_window"],
            "sealed_token_sha256": sealed_token_sha256,
            "actor_receipt_ref": receipt_ref,
        }
        if sealed_carrier_sha256 is not None:
            event_unsigned["sealed_carrier_sha256"] = sealed_carrier_sha256
        if build_authority_sha256 is not None:
            event_unsigned["build_authority_sha256"] = build_authority_sha256
        event = {**event_unsigned, "event_sha256": stable_hash(event_unsigned)}
        next_registry = _registry_payload([*events, event])
        _write_registry_cas_unlocked(
            registry_path,
            next_registry,
            expected_parent_sha256=current_sha,
        )
        return {
            "verdict": "PASS",
            "status": "ALLOCATED",
            "allocation_ref": _relative_ref(root, allocation_path),
            "allocation_sha256": sha256_file(allocation_path),
            "allocation_content_sha256": allocation["content_sha256"],
            "host_receipt_ref": _relative_ref(root, receipt_path),
            "host_receipt_sha256": sha256_file(receipt_path),
            "host_receipt_id": receipt["receipt_id"],
            "trust_manifest_ref": _relative_ref(root, trust_path),
            "trust_manifest_sha256": trust_manifest["manifest_sha256"],
            "registry_ref": _relative_ref(root, registry_path),
            "registry_sha256": sha256_file(registry_path),
            "registry_content_sha256": next_registry["content_sha256"],
            "lineage_root_report_id": lineage_root,
        }


def allocate_fresh_child_oos(
    *,
    workspace_root: Path,
    allocation_id: str,
    report_id: str,
    parent_report_id: str,
    dataset_snapshot_sha256: str,
    oos_start: str,
    oos_end: str,
    sealed_token_sha256: str,
    expected_registry_sha256: str | None,
    trust_root: Path,
    installation_id: str,
    lineage_root_report_id: str | None = None,
    sealed_carrier_sha256: str | None = None,
    legacy_test_only: bool = False,
) -> dict[str, Any]:
    """Legacy direct-hash test helper; never valid for a formal EVO child.

    Production code must use :func:`build_and_allocate_fresh_child_oos`, which
    opens the exact private carrier and derives all authority hashes itself.
    The explicit flag prevents this compatibility surface from masquerading as
    a production Host allocator.
    """

    if legacy_test_only is not True:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:direct_hash_allocator_forbidden")
    return _allocate_fresh_child_oos(
        workspace_root=workspace_root,
        allocation_id=allocation_id,
        report_id=report_id,
        parent_report_id=parent_report_id,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        oos_start=oos_start,
        oos_end=oos_end,
        sealed_token_sha256=sealed_token_sha256,
        sealed_carrier_sha256=sealed_carrier_sha256,
        build_authority_sha256=None,
        build_authority=None,
        allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
        expected_registry_sha256=expected_registry_sha256,
        trust_root=trust_root,
        installation_id=installation_id,
        lineage_root_report_id=lineage_root_report_id,
    )


def _file_reference(root: Path, path: Path) -> dict[str, str]:
    raw = path.expanduser()
    if raw.is_symlink():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:authority_file_unsafe")
    resolved = raw.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:authority_file_unsafe")
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"{BLOCK_OOS_ALLOCATION}:authority_file_outside_workspace"
        ) from exc
    return {"path": relative.as_posix(), "sha256": sha256_file(resolved)}


def _load_verified_oos_allocation_semantics(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    oos_start: str,
    oos_end: str,
    trust_root: Path,
    installation_id: str,
    admissions_root: Path | None,
) -> dict[str, Any]:
    """Replay the signed selected revision and protected parent proof contract.

    This loader deliberately reuses the same pre-OOS source replay and parent
    preregistration replay used by the human bridge and child preregistration.
    It projects only the formula needed to derive the sealed panel; it does not
    author or publish child economic semantics.
    """

    from factor_factory.console.web_factor_proof import web_factor_proof_paths
    from factor_factory.evo_child_preregistration import _parent_contract_context
    from factor_factory.formula.parser import parse_formula
    from factor_factory.pre_oos_human_bridge import _selected_projection
    from factor_factory.revision_council.pre_oos_outcome import (
        pre_oos_outcome_verifier_path,
        validate_materialized_pre_oos_council_outcome,
    )

    try:
        outcome_report, outcome_reasons = (
            validate_materialized_pre_oos_council_outcome(
                workspace_root=root,
                report_id=parent_report_id,
                expected_transition_state="MINIMAL_MECHANISM_DELTA",
            )
        )
        if outcome_report is None or outcome_reasons:
            raise ValueError(";".join(outcome_reasons or ["outcome_missing"]))
        selected, _selected_result, selected_path, _synthesis, _spec_path = (
            _selected_projection(
                root=root,
                report_id=parent_report_id,
                report=outcome_report,
            )
        )
        parent = _parent_contract_context(
            root=root,
            parent_report_id=parent_report_id,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{BLOCK_OOS_ALLOCATION}:allocation_authority_replay:{exc}"
        ) from exc

    selected = selected if isinstance(selected, Mapping) else {}
    parent_plan = parent.get("plan")
    parent_spec = parent.get("metric_verifier_spec")
    calendar = parent.get("calendar")
    if not all(
        isinstance(item, Mapping) and item
        for item in (parent_plan, parent_spec, calendar)
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:protected_contract_shape")
    identity = parent_plan.get("identity")
    evidence = parent_plan.get("evidence_policy")
    implementation = parent_plan.get("implementation")
    identity = identity if isinstance(identity, Mapping) else {}
    evidence = evidence if isinstance(evidence, Mapping) else {}
    implementation = implementation if isinstance(implementation, Mapping) else {}
    if (
        identity.get("report_id") != parent_report_id
        or child_report_id == parent_report_id
        or implementation.get("mode") != "operator"
        or parent_spec.get("report_id") != parent_report_id
        or parent_spec.get("verification_scope") != "production"
    ):
        raise ValueError(
            f"{BLOCK_OOS_ALLOCATION}:protected_contract_identity_or_mode"
        )
    child_formula = selected.get("child_formula")
    daily_fields = (parent_plan.get("data_plan") or {}).get("daily_fields")
    if (
        not isinstance(child_formula, str)
        or not child_formula.strip()
        or not isinstance(daily_fields, list)
        or not daily_fields
        or any(not isinstance(item, str) or not item for item in daily_fields)
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:selected_formula_or_data_contract")
    formula_ir = parse_formula(
        child_formula,
        available_columns=["ts_code", "trade_date", *daily_fields],
    )
    if (
        formula_ir.get("parse_status") != "success"
        or formula_ir.get("formula_hash") != selected.get("child_formula_hash")
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:selected_formula_binding")

    dates = calendar.get("dates")
    if (
        not isinstance(dates, list)
        or dates != sorted(set(dates))
        or any(not isinstance(item, str) or _window(f"{item}/{item}") is None for item in dates)
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:trusted_calendar_invalid")
    requested_window = _window({"start": oos_start, "end": oos_end})
    parent_window = _window(
        {
            "start": evidence.get("oos_start"),
            "end": evidence.get("oos_end"),
        }
    )
    if requested_window is None or parent_window is None:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:oos_window")
    if _overlap(requested_window, parent_window):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:parent_reserved_oos_overlap")
    eligible = [item for item in dates if oos_start <= item <= oos_end]
    parent_metric_window = parent_spec.get("window_contract")
    parent_metric_window = (
        parent_metric_window if isinstance(parent_metric_window, Mapping) else {}
    )
    minimum_periods = parent_metric_window.get("minimum_periods")
    if (
        isinstance(minimum_periods, bool)
        or not isinstance(minimum_periods, int)
        or minimum_periods < 60
        or len(eligible) < minimum_periods + 2
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:oos_window_calendar_coverage")
    if (
        parent_metric_window.get("universe_id") != evidence.get("universe_id")
        or parent_metric_window.get("investability_mask_id")
        != evidence.get("investability_mask_id")
        or not isinstance(evidence.get("universe_id"), str)
        or not evidence.get("universe_id")
        or not isinstance(evidence.get("investability_mask_id"), str)
        or not evidence.get("investability_mask_id")
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:authoritative_universe_binding")

    plan = deepcopy(dict(parent_plan))
    plan["identity"]["report_id"] = child_report_id
    plan["research_object"]["formula_or_law"] = child_formula
    plan["evidence_policy"]["oos_start"] = oos_start
    plan["evidence_policy"]["oos_end"] = oos_end

    paths = web_factor_proof_paths(root, parent_report_id)
    selected_path = Path(selected_path)
    plan_path = Path(parent["plan_path"])
    spec_path = Path(parent["metric_verifier_spec_path"])
    threshold_path = Path(parent["threshold_registration_path"])
    preregistration_path = Path(parent["web_preregistration_path"])
    conjecture_path = Path(parent["research_conjecture_path"])
    if spec_path != paths["spec"]:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:protected_spec_path")
    return {
        "plan": plan,
        "parent_spec": deepcopy(dict(parent_spec)),
        "calendar": deepcopy(dict(calendar)),
        "signal_dates": eligible[:-2],
        "selected_revision": deepcopy(dict(selected)),
        "authority_refs": {
            "selected_revision_result": _file_reference(root, selected_path),
            "pre_oos_outcome_verifier": _file_reference(
                root, pre_oos_outcome_verifier_path(root, parent_report_id)
            ),
            "parent_web_research_plan": _file_reference(root, plan_path),
            "parent_research_conjecture": _file_reference(root, conjecture_path),
            "parent_metric_verifier_spec": _file_reference(root, spec_path),
            "parent_threshold_registration": _file_reference(root, threshold_path),
            "parent_web_preregistration": _file_reference(
                root, preregistration_path
            ),
        },
        "universe_binding": {
            "universe_id": evidence["universe_id"],
            "investability_mask_id": evidence["investability_mask_id"],
        },
    }


def _project_allocation_metric_spec(
    *,
    root: Path,
    parent_spec: Mapping[str, Any],
    child_report_id: str,
    oos_start: str,
    oos_end: str,
    signal_dates: list[str],
    sealed_token_sha256: str,
) -> dict[str, Any]:
    spec = deepcopy(dict(parent_spec))
    spec["report_id"] = child_report_id
    research_windows = deepcopy(dict(spec.get("research_windows") or {}))
    research_windows["oos_window"] = f"{oos_start}/{oos_end}"
    spec["research_windows"] = research_windows
    window = deepcopy(dict(spec.get("window_contract") or {}))
    window.update(
        {
            "oos_window": f"{oos_start}/{oos_end}",
            "observed_start_date": signal_dates[0],
            "observed_end_date": signal_dates[-1],
            "oos_release_token_hash": sealed_token_sha256,
            "search_trial_ledger_ref": (
                "objects/research_protocol/"
                f"search_trial_ledger__{child_report_id}.json"
            ),
            "oos_release_manifest_ref": (
                "objects/research_protocol/"
                f"oos_release_manifest__{child_report_id}.json"
            ),
        }
    )
    spec["window_contract"] = window
    spec["window_hash"] = stable_hash(window)
    spec["threshold_registration_ref"] = (
        "objects/research_protocol/"
        f"threshold_registration__{child_report_id}.json"
    )
    return spec


def build_and_allocate_fresh_child_oos(
    *,
    workspace_root: Path,
    allocation_id: str,
    report_id: str,
    parent_report_id: str,
    oos_start: str,
    oos_end: str,
    sealed_oos_carrier_path: Path,
    sealed_oos_private_root: Path,
    expected_registry_sha256: str | None,
    trust_root: Path,
    installation_id: str,
    admissions_root: Path | None = None,
    agent_visible_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Host-only carrier-to-allocation transaction.

    Raw and derived hashes, release token, selected revision, calendar and
    universe bindings are all computed or replayed inside this function.  No
    caller-supplied data hash can become allocation authority.
    """

    root = workspace_root.expanduser().resolve(strict=True)
    incident_reasons = _allocation_incident_reasons(
        root=root,
        report_id=report_id,
        parent_report_id=parent_report_id,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    private_root_raw = sealed_oos_private_root.expanduser()
    carrier_raw = sealed_oos_carrier_path.expanduser()
    if private_root_raw.is_symlink() or carrier_raw.is_symlink():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_path_symlink")
    private_root = private_root_raw.resolve(strict=True)
    carrier = carrier_raw.resolve(strict=True)
    host_trust_raw = trust_root.expanduser()
    if host_trust_raw.is_symlink():
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:host_trust_root_unsafe")
    host_trust = host_trust_raw.resolve(strict=True)
    visible_roots = [
        root,
        Path(__file__).resolve().parents[1],
        *[
            item.expanduser().resolve(strict=True)
            for item in list(agent_visible_roots or [])
        ],
    ]
    if (
        not private_root.is_dir()
        or private_root.stat().st_uid != os.getuid()
        or private_root.stat().st_mode & 0o077
        or any(
            private_root == visible
            or visible in private_root.parents
            or private_root in visible.parents
            for visible in visible_roots
        )
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_private_root_unsafe")
    if (
        not host_trust.is_dir()
        or host_trust.stat().st_uid != os.getuid()
        or host_trust.stat().st_mode & 0o077
        or any(
            host_trust == visible
            or visible in host_trust.parents
            or host_trust in visible.parents
            for visible in visible_roots
        )
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:host_trust_root_unsafe")
    if private_root not in carrier.parents:
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_outside_private_root")
    current = private_root
    for part in carrier.relative_to(private_root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_path_symlink")
    if (
        not carrier.is_file()
        or carrier.stat().st_uid != os.getuid()
        or carrier.stat().st_mode & 0o077
        or carrier.lstat().st_nlink != 1
    ):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_unsafe")
    if not _SAFE_ID_RE.fullmatch(allocation_id):
        raise ValueError(f"{BLOCK_OOS_ALLOCATION}:allocation_id")
    semantics = _load_verified_oos_allocation_semantics(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=report_id,
        oos_start=oos_start,
        oos_end=oos_end,
        trust_root=host_trust,
        installation_id=installation_id,
        admissions_root=(
            admissions_root.expanduser().resolve(strict=True)
            if admissions_root is not None
            else None
        ),
    )
    raw_hash = sha256_file(carrier)
    token_seed = {
        "contract_version": OOS_ALLOCATION_BUILD_AUTHORITY_VERSION,
        "purpose": "FRESH_CHILD_SEALED_OOS_RELEASE_TOKEN",
        "allocation_id": allocation_id,
        "report_id": report_id,
        "parent_report_id": parent_report_id,
        "oos_window": {"start": oos_start, "end": oos_end},
        "sealed_carrier_sha256": raw_hash,
        "selected_revision_sha256": stable_hash(
            dict(semantics["selected_revision"])
        ),
        "protected_authority_refs_sha256": stable_hash(
            dict(semantics["authority_refs"])
        ),
        "universe_binding_sha256": stable_hash(
            dict(semantics["universe_binding"])
        ),
    }
    sealed_token_sha256 = stable_hash(token_seed)
    metric_spec = _project_allocation_metric_spec(
        root=root,
        parent_spec=semantics["parent_spec"],
        child_report_id=report_id,
        oos_start=oos_start,
        oos_end=oos_end,
        signal_dates=list(semantics["signal_dates"]),
        sealed_token_sha256=sealed_token_sha256,
    )

    build_key = hashlib.sha256(
        f"{allocation_id}\0{report_id}".encode("utf-8")
    ).hexdigest()
    build_guard = private_root / f".factorforge_oos_build__{build_key}.guard"
    staging = private_root / f".factorforge_oos_build__{build_key}.staging"
    with _locked_registry(build_guard):
        if staging.exists() or staging.is_symlink():
            if staging.is_symlink() or not staging.is_dir():
                raise ValueError(f"{BLOCK_OOS_ALLOCATION}:private_staging_unsafe")
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        private_panel = staging / f"derived_oos_panel__{report_id}.parquet"
        try:
            from factor_factory.console.web_factor_proof import (
                project_host_private_sealed_oos_panel,
            )

            projection = project_host_private_sealed_oos_panel(
                workspace_root=root,
                report_id=report_id,
                plan=dict(semantics["plan"]),
                metric_verifier_spec=metric_spec,
                calendar=dict(semantics["calendar"]),
                sealed_oos_carrier_path=carrier,
                sealed_oos_private_root=private_root,
                expected_sealed_carrier_sha256=raw_hash,
                private_output_path=private_panel,
                sealed_oos_agent_visible_roots=[
                    Path(__file__).resolve().parents[1],
                    *list(agent_visible_roots or []),
                ],
            )
            if sha256_file(carrier) != raw_hash:
                raise ValueError(
                    f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_changed_during_projection"
                )
            derived_hash = sha256_file(private_panel)
            if (
                projection.get("panel_sha256") != derived_hash
                or projection.get("row_count", 0) <= 0
                or projection.get("period_count")
                != len(semantics["signal_dates"])
            ):
                raise ValueError(
                    f"{BLOCK_OOS_ALLOCATION}:derived_panel_projection_binding"
                )
            build_authority = {
                "contract_version": OOS_ALLOCATION_BUILD_AUTHORITY_VERSION,
                "allocation_id": allocation_id,
                "report_id": report_id,
                "parent_report_id": parent_report_id,
                "selected_revision": dict(semantics["selected_revision"]),
                "authority_refs": dict(semantics["authority_refs"]),
                "calendar_authority": {
                    key: semantics["calendar"].get(key)
                    for key in (
                        "snapshot_id",
                        "open_dates_sha256",
                        "raw_file_sha256",
                        "registry_sha256",
                        "registry_git_commit",
                        "registry_git_blob",
                    )
                },
                "universe_binding": dict(semantics["universe_binding"]),
                "oos_window": {"start": oos_start, "end": oos_end},
                "sealed_token_sha256": sealed_token_sha256,
                "sealed_carrier_sha256": raw_hash,
                "dataset_snapshot_sha256": derived_hash,
                "projection_row_count": projection["row_count"],
                "projection_period_count": projection["period_count"],
            }
            build_authority_sha256 = stable_hash(build_authority)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # Long carrier projection is complete and its build lock is released.
    # Only the short authority publication transaction is serialized against
    # incident registration, followed by the workspace OOS registry and the
    # private locator lock in that fixed order.
    with oos_exposure_private_registry_guard(
        host_trust,
        installation_id=installation_id,
    ) as incident_guard:
        incident_reasons = _allocation_incident_reasons(
            root=root,
            report_id=report_id,
            parent_report_id=parent_report_id,
            trust_root=host_trust,
            installation_id=installation_id,
        )
        if incident_reasons:
            raise ValueError(";".join(incident_reasons))
        if sha256_file(carrier) != raw_hash:
            raise ValueError(
                f"{BLOCK_OOS_ALLOCATION}:sealed_carrier_changed_before_publication"
            )
        result = _allocate_fresh_child_oos(
            workspace_root=root,
            allocation_id=allocation_id,
            report_id=report_id,
            parent_report_id=parent_report_id,
            dataset_snapshot_sha256=derived_hash,
            oos_start=oos_start,
            oos_end=oos_end,
            sealed_token_sha256=sealed_token_sha256,
            sealed_carrier_sha256=raw_hash,
            build_authority_sha256=build_authority_sha256,
            build_authority=build_authority,
            allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_SECURE,
            expected_registry_sha256=expected_registry_sha256,
            trust_root=host_trust,
            installation_id=installation_id,
            _incident_guard=incident_guard,
        )
        trust_store = load_runtime_trust_store(
            host_trust,
            installation_id=installation_id,
        )
        locator_result = _write_private_oos_locator(
            trust_store=trust_store,
            trust_root=host_trust,
            allocation_id=allocation_id,
            report_id=report_id,
            parent_report_id=parent_report_id,
            private_root=private_root,
            carrier=carrier,
            sealed_carrier_sha256=raw_hash,
            dataset_snapshot_sha256=derived_hash,
            build_authority_sha256=build_authority_sha256,
        )
    return {
        **result,
        "sealed_carrier_sha256": raw_hash,
        "dataset_snapshot_sha256": derived_hash,
        "sealed_token_sha256": sealed_token_sha256,
        "build_authority_sha256": build_authority_sha256,
        "projection_row_count": projection["row_count"],
        "projection_period_count": projection["period_count"],
        "oos_panel_published": False,
        **locator_result,
    }


def _release_payload_binding_reasons(
    *,
    release: dict[str, Any],
    allocation: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if (
        release.get("release_status") != "RELEASED"
        or release.get("report_id") != allocation.get("report_id")
        or release.get("dataset_snapshot_hash")
        != allocation.get("dataset_snapshot_sha256")
        or release.get("oos_release_token_hash")
        != allocation.get("sealed_token_sha256")
        or _window(release.get("oos_window")) != _window(allocation.get("oos_window"))
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_allocation_binding")
    return reasons


def _release_evidence_contract_reasons(
    release: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> list[str]:
    required_fields = {
        "version",
        "release_status",
        "report_id",
        "factor_id",
        "release_sequence",
        "search_trial_ledger_ref",
        "search_trial_ledger_sha256",
        "threshold_registration_ref",
        "threshold_registration_sha256",
        "dataset_snapshot_hash",
        "window_hash",
        "evaluation_contract_hash",
        "oos_window",
        "observed_start_date",
        "observed_end_date",
        "observed_period_count",
        "oos_release_token_hash",
        "release_manifest_sha256",
    }
    if not isinstance(release, dict) or not required_fields.issubset(release):
        return [f"{BLOCK_OOS_ALLOCATION}:release_evidence_shape"]
    if release.get("version") != RESEARCH_RELEASE_MANIFEST_VERSION:
        return [f"{BLOCK_OOS_ALLOCATION}:release_evidence_version"]
    digest = release.get("release_manifest_sha256")
    unsigned = {
        key: value for key, value in release.items() if key != "release_manifest_sha256"
    }
    expected = _research_release_hash(unsigned)
    if digest != expected:
        return [f"{BLOCK_OOS_ALLOCATION}:release_evidence_hash"]
    reasons: list[str] = []
    if (
        isinstance(release.get("release_sequence"), bool)
        or not isinstance(release.get("release_sequence"), int)
        or release.get("release_sequence") <= 0
        or isinstance(release.get("observed_period_count"), bool)
        or not isinstance(release.get("observed_period_count"), int)
        or release.get("observed_period_count") <= 0
        or _window(release.get("oos_window")) is None
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_evidence_values")
    for field in (
        "search_trial_ledger_sha256",
        "threshold_registration_sha256",
        "dataset_snapshot_hash",
        "window_hash",
        "evaluation_contract_hash",
        "oos_release_token_hash",
    ):
        if not isinstance(release.get(field), str) or not _SHA256_RE.fullmatch(
            release[field]
        ):
            reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_evidence:{field}")
    if workspace_root is not None:
        root = workspace_root.resolve(strict=False)
        for ref_field, sha_field in (
            ("search_trial_ledger_ref", "search_trial_ledger_sha256"),
            ("threshold_registration_ref", "threshold_registration_sha256"),
        ):
            path = _resolve(root, release.get(ref_field))
            if (
                path is None
                or not path.is_file()
                or path.is_symlink()
                or release.get(sha_field) != sha256_file(path)
            ):
                reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_evidence:{ref_field}")
    return list(dict.fromkeys(reasons))


def _research_release_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _release_binding_reasons(
    *,
    root: Path,
    release_path: Path,
    release: dict[str, Any],
    allocation: dict[str, Any],
) -> list[str]:
    resolved_release = release_path.expanduser().resolve(strict=False)
    if (
        (resolved_release != root and root not in resolved_release.parents)
        or not resolved_release.is_file()
        or resolved_release.is_symlink()
    ):
        return [f"{BLOCK_OOS_ALLOCATION}:release_evidence_path"]
    return _release_payload_binding_reasons(
        release=release,
        allocation=allocation,
    )


def validate_oos_release_preflight(
    *,
    workspace_root: Path,
    report_id: str,
    release_manifest_payload: dict[str, Any],
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    """Validate a child allocation before any OOS release file is written."""

    marker_reasons = _public_marker_incident_reasons(
        workspace_root=workspace_root,
        report_id=report_id,
    )
    if marker_reasons:
        return marker_reasons

    try:
        with _current_incident_authority_guard(
            trust_root=incident_trust_root,
            installation_id=incident_installation_id,
            guard=_incident_guard,
        ) as (guard, trust_root, installation_id):
            return _validate_oos_release_preflight_guarded(
                workspace_root=workspace_root,
                report_id=report_id,
                release_manifest_payload=release_manifest_payload,
                incident_trust_root=trust_root,
                incident_installation_id=installation_id,
                _incident_guard=guard,
            )
    except (OSError, ValueError) as exc:
        return [str(exc)]


def _validate_oos_release_preflight_guarded(
    *,
    workspace_root: Path,
    report_id: str,
    release_manifest_payload: dict[str, Any],
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> list[str]:

    root = workspace_root.expanduser().resolve(strict=False)
    allocation_path = oos_allocation_path(root, report_id)
    registry_path = oos_registry_path(root)
    child_authority_reasons = _missing_evo_child_oos_authority_reasons(
        root,
        report_id,
    )
    if child_authority_reasons:
        return child_authority_reasons
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        return incident_reasons
    registry: dict[str, Any] | None = None
    if registry_path.is_file() and not registry_path.is_symlink():
        try:
            registry = _read_json(registry_path)
        except (OSError, json.JSONDecodeError, ValueError):
            return [f"{BLOCK_OOS_ALLOCATION}:registry_invalid"]
    registry_has_report = bool(
        registry
        and any(
            event.get("event_type") == "ALLOCATE"
            and event.get("report_id") == report_id
            for event in registry.get("events") or []
            if isinstance(event, dict)
        )
    )
    if not allocation_path.exists() and not registry_has_report:
        return []
    if (
        not allocation_path.is_file()
        or allocation_path.is_symlink()
        or registry is None
    ):
        return [f"{BLOCK_OOS_ALLOCATION}:release_allocation_unregistered"]
    try:
        allocation = _read_json(allocation_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return [f"{BLOCK_OOS_ALLOCATION}:release_allocation_invalid"]
    reasons = [
        *validate_oos_allocation(allocation, workspace_root=root),
        *validate_oos_registry(registry, workspace_root=root),
        *_release_evidence_contract_reasons(
            release_manifest_payload,
            workspace_root=root,
        ),
        *_release_payload_binding_reasons(
            release=release_manifest_payload,
            allocation=allocation,
        ),
        *validate_fresh_child_oos_allocation(
            root=root,
            parent_report_id=str(allocation.get("parent_report_id") or ""),
            child_report_id=report_id,
            allocation_id=str(allocation.get("allocation_id") or ""),
            allocation_ref=_relative_ref(root, allocation_path),
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        ),
    ]
    allocations = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "ALLOCATE"
        and event.get("report_id") == report_id
    ]
    consumptions = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "CONSUME"
        and event.get("report_id") == report_id
    ]
    if len(allocations) != 1 or consumptions:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:allocation_not_available")
    elif allocations[0].get("allocation_ref") != _relative_ref(
        root, allocation_path
    ) or allocations[0].get("allocation_sha256") != sha256_file(allocation_path):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:registry_allocation_binding")
    return list(dict.fromkeys(reasons))


def validate_oos_release_authorization(
    *,
    workspace_root: Path,
    report_id: str,
    oos_window: Any,
    sealed_token_sha256: Any,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    """Check signed one-time authority before opening or deriving an OOS panel."""

    marker_reasons = _public_marker_incident_reasons(
        workspace_root=workspace_root,
        report_id=report_id,
    )
    if marker_reasons:
        return marker_reasons

    try:
        with _current_incident_authority_guard(
            trust_root=incident_trust_root,
            installation_id=incident_installation_id,
            guard=_incident_guard,
        ) as (guard, trust_root, installation_id):
            return _validate_oos_release_authorization_guarded(
                workspace_root=workspace_root,
                report_id=report_id,
                oos_window=oos_window,
                sealed_token_sha256=sealed_token_sha256,
                incident_trust_root=trust_root,
                incident_installation_id=installation_id,
                _incident_guard=guard,
            )
    except (OSError, ValueError) as exc:
        return [str(exc)]


def _validate_oos_release_authorization_guarded(
    *,
    workspace_root: Path,
    report_id: str,
    oos_window: Any,
    sealed_token_sha256: Any,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> list[str]:

    root = workspace_root.expanduser().resolve(strict=False)
    allocation_path = oos_allocation_path(root, report_id)
    registry_path = oos_registry_path(root)
    child_authority_reasons = _missing_evo_child_oos_authority_reasons(
        root,
        report_id,
    )
    if child_authority_reasons:
        return child_authority_reasons
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        return incident_reasons
    if not allocation_path.exists() and not registry_path.exists():
        return []
    if not allocation_path.is_file() or allocation_path.is_symlink():
        if registry_path.is_file() and not registry_path.is_symlink():
            try:
                registry = _read_json(registry_path)
            except (OSError, json.JSONDecodeError, ValueError):
                return [f"{BLOCK_OOS_ALLOCATION}:registry_invalid"]
            if not any(
                event.get("event_type") == "ALLOCATE"
                and event.get("report_id") == report_id
                for event in registry.get("events") or []
                if isinstance(event, dict)
            ):
                return []
        return [f"{BLOCK_OOS_ALLOCATION}:release_allocation_unregistered"]
    try:
        allocation = _read_json(allocation_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return [f"{BLOCK_OOS_ALLOCATION}:release_allocation_invalid"]
    canonical_release = (
        root
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{report_id}.json"
    )
    if canonical_release.exists() or canonical_release.is_symlink():
        if not canonical_release.is_file() or canonical_release.is_symlink():
            return [f"{BLOCK_OOS_ALLOCATION}:release_evidence_path"]
        try:
            release = _read_json(canonical_release)
            registry = _read_json(registry_path)
        except (OSError, json.JSONDecodeError, ValueError):
            return [f"{BLOCK_OOS_ALLOCATION}:release_evidence_invalid"]
        reasons = [
            *validate_oos_allocation(allocation, workspace_root=root),
            *validate_oos_registry(registry, workspace_root=root),
            *_release_evidence_contract_reasons(
                release,
                workspace_root=root,
            ),
            *_release_payload_binding_reasons(
                release=release,
                allocation=allocation,
            ),
        ]
        allocations = [
            event
            for event in registry.get("events") or []
            if isinstance(event, dict)
            and event.get("event_type") == "ALLOCATE"
            and event.get("report_id") == report_id
        ]
        consumptions = [
            event
            for event in registry.get("events") or []
            if isinstance(event, dict)
            and event.get("event_type") == "CONSUME"
            and event.get("report_id") == report_id
        ]
        expected_evidence = {
            "path": _relative_ref(root, canonical_release),
            "sha256": sha256_file(canonical_release),
        }
        if len(allocations) != 1 or len(consumptions) > 1:
            reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_registry_state")
        elif consumptions and (
            consumptions[0].get("allocation_id") != allocations[0].get("allocation_id")
            or consumptions[0].get("consumption_evidence_ref") != expected_evidence
        ):
            reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_consumption_binding")
        return list(dict.fromkeys(reasons))
    reasons = validate_fresh_child_oos_allocation(
        root=root,
        parent_report_id=str(allocation.get("parent_report_id") or ""),
        child_report_id=report_id,
        allocation_id=str(allocation.get("allocation_id") or ""),
        allocation_ref=_relative_ref(root, allocation_path),
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    if _window(oos_window) != _window(
        allocation.get("oos_window")
    ) or sealed_token_sha256 != allocation.get("sealed_token_sha256"):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_allocation_binding")
    return list(dict.fromkeys(reasons))


def validate_child_oos_finalizer_authority(
    *,
    workspace_root: Path,
    parent_report_id: str,
    child_report_id: str,
    allocation_id: str,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    """Accept only a fresh allocation or its exact crash-replay release state."""

    marker_reasons = _public_marker_incident_reasons(
        workspace_root=workspace_root,
        report_id=child_report_id,
    )
    if marker_reasons:
        return marker_reasons

    try:
        with _current_incident_authority_guard(
            trust_root=incident_trust_root,
            installation_id=incident_installation_id,
            guard=_incident_guard,
        ) as (guard, trust_root, installation_id):
            return _validate_child_oos_finalizer_authority_guarded(
                workspace_root=workspace_root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                allocation_id=allocation_id,
                incident_trust_root=trust_root,
                incident_installation_id=installation_id,
                _incident_guard=guard,
            )
    except (OSError, ValueError) as exc:
        return [str(exc)]


def _validate_child_oos_finalizer_authority_guarded(
    *,
    workspace_root: Path,
    parent_report_id: str,
    child_report_id: str,
    allocation_id: str,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> list[str]:

    root = workspace_root.expanduser().resolve(strict=False)
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=child_report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        return incident_reasons
    allocation_path = oos_allocation_path(root, child_report_id)
    registry_path = oos_registry_path(root)
    release_path = (
        root
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{child_report_id}.json"
    )
    if (
        not allocation_path.is_file()
        or allocation_path.is_symlink()
        or not registry_path.is_file()
        or registry_path.is_symlink()
    ):
        return [f"{BLOCK_OOS_ALLOCATION}:finalizer_authority_missing"]
    try:
        allocation = _read_json(allocation_path)
        registry = _read_json(registry_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return [f"{BLOCK_OOS_ALLOCATION}:finalizer_authority_invalid"]
    reasons = [
        *validate_oos_allocation(allocation, workspace_root=root),
        *validate_oos_registry(registry, workspace_root=root),
    ]
    if (
        allocation.get("allocation_authority_mode")
        != OOS_ALLOCATION_AUTHORITY_SECURE
        or allocation.get("allocation_id") != allocation_id
        or allocation.get("report_id") != child_report_id
        or allocation.get("parent_report_id") != parent_report_id
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:finalizer_allocation_binding")
    try:
        expected_lineage = expected_lineage_root_report_id(root, parent_report_id)
    except ValueError as exc:
        reasons.append(str(exc))
        expected_lineage = None
    if (
        expected_lineage is not None
        and allocation.get("lineage_root_report_id") != expected_lineage
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:lineage_root_binding")
    events = registry.get("events") if isinstance(registry, Mapping) else []
    allocations = [
        event
        for event in events or []
        if isinstance(event, Mapping)
        and event.get("event_type") == "ALLOCATE"
        and event.get("allocation_id") == allocation_id
        and event.get("report_id") == child_report_id
    ]
    consumptions = [
        event
        for event in events or []
        if isinstance(event, Mapping)
        and event.get("event_type") == "CONSUME"
        and event.get("allocation_id") == allocation_id
        and event.get("report_id") == child_report_id
    ]
    if len(allocations) != 1 or len(consumptions) > 1:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:finalizer_registry_state")
        return list(dict.fromkeys(reasons))
    if not release_path.exists() and not release_path.is_symlink():
        reasons.extend(
            validate_fresh_child_oos_allocation(
                root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                allocation_id=allocation_id,
                allocation_ref=allocation_path.relative_to(root).as_posix(),
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            )
        )
        return list(dict.fromkeys(reasons))
    if not release_path.is_file() or release_path.is_symlink():
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:finalizer_release_unsafe")
        return list(dict.fromkeys(reasons))
    try:
        release = _read_json(release_path)
    except (OSError, json.JSONDecodeError, ValueError):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_evidence_invalid")
        return list(dict.fromkeys(reasons))
    reasons.extend(
        _release_evidence_contract_reasons(release, workspace_root=root)
    )
    reasons.extend(
        _release_binding_reasons(
            root=root,
            release_path=release_path,
            release=release,
            allocation=allocation,
        )
    )
    reasons.extend(
        _released_lineage_reuse_reasons(
            root=root,
            parent_report_id=parent_report_id,
            allocation=allocation,
            exclude_report_id=child_report_id,
        )
    )
    if consumptions:
        reasons.extend(
            validate_oos_release_consumption(
                workspace_root=root,
                report_id=child_report_id,
                release_manifest_path=release_path,
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            )
        )
    return list(dict.fromkeys(reasons))


def validate_oos_release_consumption(
    *,
    workspace_root: Path,
    report_id: str,
    release_manifest_path: Path,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    marker_reasons = _public_marker_incident_reasons(
        workspace_root=workspace_root,
        report_id=report_id,
    )
    if marker_reasons:
        return marker_reasons
    try:
        with _current_incident_authority_guard(
            trust_root=incident_trust_root,
            installation_id=incident_installation_id,
            guard=_incident_guard,
        ) as (guard, trust_root, installation_id):
            return _validate_oos_release_consumption_guarded(
                workspace_root=workspace_root,
                report_id=report_id,
                release_manifest_path=release_manifest_path,
                incident_trust_root=trust_root,
                incident_installation_id=installation_id,
                _incident_guard=guard,
            )
    except (OSError, ValueError) as exc:
        return [str(exc)]


def _validate_oos_release_consumption_guarded(
    *,
    workspace_root: Path,
    report_id: str,
    release_manifest_path: Path,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> list[str]:
    root = workspace_root.expanduser().resolve(strict=False)
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    allocation_path = oos_allocation_path(root, report_id)
    registry_path = oos_registry_path(root)
    child_authority_reasons = _missing_evo_child_oos_authority_reasons(
        root,
        report_id,
    )
    if child_authority_reasons:
        return child_authority_reasons
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        return incident_reasons
    return validate_oos_release_consumption_structural(
        workspace_root=root,
        report_id=report_id,
        release_manifest_path=release_manifest_path,
    )


def validate_oos_release_consumption_structural(
    *,
    workspace_root: Path,
    report_id: str,
    release_manifest_path: Path,
) -> list[str]:
    """Byte/registry replay only; this is not current formal authority."""

    root = workspace_root.expanduser().resolve(strict=False)
    allocation_path = oos_allocation_path(root, report_id)
    registry_path = oos_registry_path(root)
    child_authority_reasons = _missing_evo_child_oos_authority_reasons(
        root,
        report_id,
    )
    if child_authority_reasons:
        return child_authority_reasons
    registry: dict[str, Any] | None = None
    if registry_path.is_file() and not registry_path.is_symlink():
        try:
            registry = _read_json(registry_path)
        except (OSError, json.JSONDecodeError, ValueError):
            return [f"{BLOCK_OOS_ALLOCATION}:registry_invalid"]
    registry_has_report = bool(
        registry
        and any(
            event.get("event_type") == "ALLOCATE"
            and event.get("report_id") == report_id
            for event in registry.get("events") or []
            if isinstance(event, dict)
        )
    )
    if not allocation_path.exists() and not registry_has_report:
        return []
    if (
        not allocation_path.is_file()
        or allocation_path.is_symlink()
        or registry is None
    ):
        return [f"{BLOCK_OOS_ALLOCATION}:release_allocation_unregistered"]
    reasons = validate_oos_registry(registry, workspace_root=root)
    try:
        allocation = _read_json(allocation_path)
        release = _read_json(release_manifest_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return [*reasons, f"{BLOCK_OOS_ALLOCATION}:release_evidence_invalid"]
    reasons.extend(validate_oos_allocation(allocation, workspace_root=root))
    reasons.extend(
        _release_evidence_contract_reasons(
            release,
            workspace_root=root,
        )
    )
    reasons.extend(
        _release_binding_reasons(
            root=root,
            release_path=release_manifest_path,
            release=release,
            allocation=allocation,
        )
    )
    allocations = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "ALLOCATE"
        and event.get("report_id") == report_id
    ]
    consumptions = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "CONSUME"
        and event.get("report_id") == report_id
    ]
    if len(allocations) != 1:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_allocation_unregistered")
        return list(dict.fromkeys(reasons))
    if len(consumptions) != 1:
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_consumption_count")
        return list(dict.fromkeys(reasons))
    allocation_event = allocations[0]
    consumption = consumptions[0]
    expected_evidence = {
        "path": _relative_ref(root, release_manifest_path),
        "sha256": sha256_file(release_manifest_path),
    }
    if (
        consumption.get("allocation_id") != allocation_event.get("allocation_id")
        or consumption.get("consumption_evidence_ref") != expected_evidence
        or consumption.get("allocation_event_sha256")
        != allocation_event.get("event_sha256")
        or consumption.get("allocation_host_receipt_id")
        != (allocation_event.get("actor_receipt_ref") or {}).get("receipt_id")
    ):
        reasons.append(f"{BLOCK_OOS_ALLOCATION}:release_consumption_binding")
    return list(dict.fromkeys(reasons))


def consume_oos_allocation_for_release(
    *,
    workspace_root: Path,
    report_id: str,
    release_manifest_path: Path,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    """Consume a Host allocation exactly once when the canonical OOS release exists."""

    marker_reasons = _public_marker_incident_reasons(
        workspace_root=workspace_root,
        report_id=report_id,
    )
    if marker_reasons:
        raise ValueError(";".join(marker_reasons))

    with _current_incident_authority_guard(
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
        guard=_incident_guard,
    ) as (guard, trust_root, installation_id):
        return _consume_oos_allocation_for_release_guarded(
            workspace_root=workspace_root,
            report_id=report_id,
            release_manifest_path=release_manifest_path,
            incident_trust_root=trust_root,
            incident_installation_id=installation_id,
            _incident_guard=guard,
        )


def _consume_oos_allocation_for_release_guarded(
    *,
    workspace_root: Path,
    report_id: str,
    release_manifest_path: Path,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> dict[str, Any]:
    """Guarded implementation; lock order is incident registry then OOS registry."""

    root = workspace_root.expanduser().resolve(strict=True)
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    allocation_path = oos_allocation_path(root, report_id)
    registry_path = oos_registry_path(root)
    child_authority_reasons = _missing_evo_child_oos_authority_reasons(
        root,
        report_id,
    )
    if child_authority_reasons:
        raise ValueError(";".join(child_authority_reasons))
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    if not allocation_path.exists() and not registry_path.exists():
        return {"verdict": "PASS", "status": "NOT_APPLICABLE_LEGACY_RELEASE"}
    with _locked_registry(registry_path):
        if not registry_path.is_file() or registry_path.is_symlink():
            if not allocation_path.exists():
                return {"verdict": "PASS", "status": "NOT_APPLICABLE_LEGACY_RELEASE"}
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:release_allocation_unregistered")
        registry = _read_json(registry_path)
        registry_reasons = validate_oos_registry(registry, workspace_root=root)
        if registry_reasons:
            raise ValueError(";".join(registry_reasons))
        allocations = [
            event
            for event in registry["events"]
            if event.get("event_type") == "ALLOCATE"
            and event.get("report_id") == report_id
        ]
        if not allocations:
            if allocation_path.exists() or allocation_path.is_symlink():
                raise ValueError(
                    f"{BLOCK_OOS_ALLOCATION}:release_allocation_unregistered"
                )
            child_authority_reasons = _missing_evo_child_oos_authority_reasons(
                root,
                report_id,
            )
            if child_authority_reasons:
                raise ValueError(";".join(child_authority_reasons))
            return {"verdict": "PASS", "status": "NOT_APPLICABLE_LEGACY_RELEASE"}
        if (
            len(allocations) != 1
            or not allocation_path.is_file()
            or allocation_path.is_symlink()
        ):
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:release_allocation_unregistered")
        allocation = _read_json(allocation_path)
        release = _read_json(release_manifest_path)
        binding_reasons = [
            *validate_oos_allocation(allocation, workspace_root=root),
            *_release_evidence_contract_reasons(
                release,
                workspace_root=root,
            ),
            *_release_binding_reasons(
                root=root,
                release_path=release_manifest_path,
                release=release,
                allocation=allocation,
            ),
        ]
        if binding_reasons:
            raise ValueError(";".join(binding_reasons))
        allocation_event = allocations[0]
        evidence_ref = {
            "path": _relative_ref(root, release_manifest_path),
            "sha256": sha256_file(release_manifest_path),
        }
        consumptions = [
            event
            for event in registry["events"]
            if event.get("event_type") == "CONSUME"
            and event.get("allocation_id") == allocation_event.get("allocation_id")
        ]
        if consumptions:
            if (
                len(consumptions) == 1
                and consumptions[0].get("consumption_evidence_ref") == evidence_ref
                and consumptions[0].get("allocation_event_sha256")
                == allocation_event.get("event_sha256")
            ):
                return {
                    "verdict": "PASS",
                    "status": "IDENTICAL_CONSUMPTION_REPLAY",
                    "registry_sha256": sha256_file(registry_path),
                    "consumption_event_sha256": consumptions[0]["event_sha256"],
                }
            raise ValueError(f"{BLOCK_OOS_ALLOCATION}:allocation_already_consumed")
        current_sha = sha256_file(registry_path)
        event_unsigned = {
            "sequence": len(registry["events"]) + 1,
            "event_type": "CONSUME",
            "allocation_id": allocation_event["allocation_id"],
            "report_id": allocation_event["report_id"],
            "parent_report_id": allocation_event["parent_report_id"],
            "lineage_root_report_id": allocation_event["lineage_root_report_id"],
            "actor": OOS_RELEASE_GATE_ACTOR,
            "allocation_authority_mode": allocation_event[
                "allocation_authority_mode"
            ],
            "previous_event_sha256": registry["events"][-1]["event_sha256"],
            "consumption_purpose": OOS_CONSUMPTION_PURPOSE,
            "consumption_evidence_ref": evidence_ref,
            "allocation_event_sha256": allocation_event["event_sha256"],
            "allocation_host_receipt_id": allocation_event["actor_receipt_ref"][
                "receipt_id"
            ],
        }
        event = {**event_unsigned, "event_sha256": stable_hash(event_unsigned)}
        next_registry = _registry_payload([*registry["events"], event])
        _write_registry_cas_unlocked(
            registry_path,
            next_registry,
            expected_parent_sha256=current_sha,
        )
        post_reasons = validate_oos_release_consumption(
            workspace_root=root,
            report_id=report_id,
            release_manifest_path=release_manifest_path,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
        if post_reasons:
            raise ValueError(";".join(post_reasons))
        return {
            "verdict": "PASS",
            "status": "CONSUMED",
            "registry_sha256": sha256_file(registry_path),
            "registry_content_sha256": next_registry["content_sha256"],
            "consumption_event_sha256": event["event_sha256"],
        }
