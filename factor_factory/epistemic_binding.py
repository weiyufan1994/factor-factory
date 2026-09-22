from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import re
import secrets
import stat
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from factor_factory.research_org.contracts import (
    stable_json_hash,
    strict_json_loads,
    validate_content_hash,
    with_content_hash,
    write_workspace_json_once,
)


P0_PACKET_MANIFEST_SHA256 = (
    "58c3585881f52c4ed60c4e7fb582e9b30acf0063433c12363915d54f0b985c4f"
)
P0_PACKET_ID = "FACTORFORGE_EPISTEMIC_GRAPH_V2_P0_BINDING_REVIEW_20260822_R2"
P0_AUTHORITY_REGISTRY_PATH = "02_authority_principal_store_binding_registry.json"
P0_ADAPTER_REGISTRY_PATH = "03_native_adapter_consumer_registry.json"
P0_MANIFEST_PATH = "packet_manifest.json"

INVENTORY_SCHEMA_ID = "factorforge_epistemic_binding_expected_inventory_v1"
BLANK_TEMPLATE_SCHEMA_ID = "factorforge_epistemic_binding_blank_readback_v1"
VALIDATION_RECEIPT_SCHEMA_ID = (
    "factorforge_epistemic_binding_offline_validation_receipt_v1"
)
SCHEMA_VERSION = "1.0.0"

INVENTORY_RELATIVE_PATH = "factorforge_epistemic_binding_expected_inventory_v1.json"
BLANK_TEMPLATE_RELATIVE_PATH = (
    "factorforge_epistemic_binding_blank_readback_v1.json"
)

EXPECTED_ARTIFACT_COUNT = 11
EXPECTED_DIRECTORY_FILE_COUNT = 12
EXPECTED_AUTHORITY_COUNT = 5
EXPECTED_SOD_PROFILE_COUNT = 24
EXPECTED_ROOT_COUNT = 3
EXPECTED_ROOT_RELATIONSHIP_COUNT = 3
EXPECTED_REQUIRED_RELATIONSHIP_COUNT = 4
EXPECTED_STORE_COUNT = 12
EXPECTED_DELIVERY_ENDPOINT_COUNT = 2
EXPECTED_PRINCIPAL_DEPLOYMENT_COUNT = 33
EXPECTED_EVENT_DEPLOYMENT_COUNT = 67
EXPECTED_EXTERNAL_TRUST_DEPLOYMENT_COUNT = 1
EXPECTED_DEPLOYMENT_COUNT = 101
EXPECTED_ADAPTER_COUNT = 40
EXPECTED_UNIQUE_SCHEMA_ADAPTER_COUNT = 2
EXPECTED_DISCRIMINATED_ADAPTER_COUNT = 38

MAX_P0_MANIFEST_BYTES = 256 * 1024
MAX_P0_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_STAGE1A_JSON_BYTES = 4 * 1024 * 1024
MAX_STAGE1A_STRING_BYTES = 2 * 1024

INCOMPLETE_VERDICT = (
    "VALID_STAGE1A_PREP__INCOMPLETE__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING"
)
REJECTED_VERDICT = "BLOCK_STAGE1A_PREP_INVALID"

UNBOUND_STATE = "UNBOUND"
PROHIBITED_STATE = "PROHIBITED_NOT_AUTHORIZED"
NOT_AUTHORIZED_STATUS = "NOT_AUTHORIZED__UNBOUND_BLOCKING"

EXPECTED_AUTHORITY_IDS = frozenset(
    {
        "FF_HOST_MEMORY_AUTHORITY_CURRENT",
        "FF_HOST_AGENT_DELIVERY_AUTHORITY_CURRENT",
        "FF_ONTOLOGY_STEWARD_V1",
        "FF_PROJECTION_EXPORT_STEWARD_V1",
        "FF_REFERENCE_STEWARD_V1",
    }
)

CANONICAL_MEMORY_ROOT = (
    "FF_HOST_MEMORY_AUTHORITY_CURRENT.CANONICAL_RESEARCHER_MEMORY_STORE_ROOT"
)
EPISTEMIC_TRANSACTION_ROOT = (
    "FF_HOST_MEMORY_AUTHORITY_CURRENT.EPISTEMIC_TRANSACTION_NAMESPACE_ROOT"
)
DELIVERY_ROOT = (
    "FF_HOST_AGENT_DELIVERY_AUTHORITY_CURRENT.HOST_PRIVATE_DELIVERY_STATE_ROOT"
)

REQUEST_DELIVERY_STORE = "FF_RAG_OPAQUE_REQUEST_DELIVERY_LEDGER_CURRENT"
RESPONSE_DELIVERY_STORE = "FF_RAG_OPAQUE_RESPONSE_DELIVERY_LEDGER_CURRENT"

EXPECTED_ROOT_SPECS = (
    (CANONICAL_MEMORY_ROOT, "FF_HOST_MEMORY_AUTHORITY_CURRENT"),
    (EPISTEMIC_TRANSACTION_ROOT, "FF_HOST_MEMORY_AUTHORITY_CURRENT"),
    (DELIVERY_ROOT, "FF_HOST_AGENT_DELIVERY_AUTHORITY_CURRENT"),
)

EXPECTED_ROOT_RELATIONSHIP_SPECS = (
    (
        "ROOT_REL_MEMORY_CANONICAL_TO_TRANSACTION",
        CANONICAL_MEMORY_ROOT,
        EPISTEMIC_TRANSACTION_ROOT,
        "DISJOINT_SIBLING",
    ),
    (
        "ROOT_REL_DELIVERY_TO_CANONICAL_MEMORY",
        DELIVERY_ROOT,
        CANONICAL_MEMORY_ROOT,
        "DISJOINT_SUBTREE",
    ),
    (
        "ROOT_REL_DELIVERY_TO_EPISTEMIC_TRANSACTION",
        DELIVERY_ROOT,
        EPISTEMIC_TRANSACTION_ROOT,
        "DISJOINT_SUBTREE",
    ),
)

EXPECTED_FORBIDDEN_PHYSICAL_RELATIONSHIPS = (
    "ALIAS",
    "SAME_ROOT",
    "ANCESTOR",
    "DESCENDANT",
    "SYMLINK_EQUIVALENT",
    "HARDLINK_EQUIVALENT",
    "BIND_MOUNT_EQUIVALENT",
    "OBJECT_PREFIX_OR_TABLE_OVERLAP",
)

EXPECTED_STORE_IDS = frozenset(
    {
        "FF_BMF_NAMESPACE_REGISTRY_CURRENT",
        "FF_HYPOTHESIS_IDENTITY_RESERVATION_REGISTRY_CURRENT",
        "FF_DIAGNOSIS_MATERIAL_ASSESSMENT_SCOPE_REGISTRY_CURRENT",
        "FF_DIAGNOSIS_LOWER_LAYER_ASSESSMENT_LEDGER_CURRENT",
        "FF_DIAGNOSIS_ASSESSMENT_HEAD_COMMITMENT_REGISTRY_CURRENT",
        "FF_DIAGNOSIS_OUTCOME_REVIEW_REGISTRY_CURRENT",
        "FF_DIAGNOSIS_SUBMISSION_REQUEST_LEDGER_CURRENT",
        "FF_SOURCE_HANDOFF_GATE_EVENT_LEDGER_CURRENT",
        "FF_CURRENT_STEP1_HANDOFF_VALIDATION_REGISTRY_CURRENT",
        "FF_STEP1_CHIEF_CONTEXT_LEDGER_CURRENT",
        REQUEST_DELIVERY_STORE,
        RESPONSE_DELIVERY_STORE,
    }
)

UNIQUE_SCHEMA_ADAPTER_IDS = frozenset(
    {
        "factorforge_source_selection_rank_tie_native_adapter_v1",
        "factorforge_current_step1_clean_route_authorization_native_adapter_v1",
    }
)

EXPECTED_DEPLOYMENT_STATUS_COUNTS = {
    "UNBOUND_BLOCKING": 97,
    "PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING": 3,
    NOT_AUTHORIZED_STATUS: 1,
}

EXPECTED_ADAPTER_STATUS_COUNTS = {
    "UNBOUND_BLOCKING": 30,
    "PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING": 5,
    NOT_AUTHORIZED_STATUS: 5,
}

EXPECTED_AUTHORITY_CEILING = {
    "host_readback_authority": False,
    "runtime_authority": False,
    "skill_authority": False,
    "canonical_write_authority": False,
    "oos_authority": False,
    "signature_generation_authority": False,
    "key_generation_authority": False,
}

FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "private_key",
        "private_key_bytes",
        "private_path",
        "filesystem_path",
        "secret",
        "secret_value",
        "canonical_payload",
        "canonical_memory_payload",
        "oos_locator",
        "oos_path",
        "signature",
        "detached_signature",
        "public_key",
        "public_key_bytes",
        "physical_endpoint",
        "physical_path",
        "password",
        "credential",
        "credentials",
        "access_token",
        "refresh_token",
        "api_key",
        "authorization",
    }
)

WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
PRIVATE_URI_RE = re.compile(
    r"^(?:file|https?|ftp|s3|gs|ssh|scp|nfs|smb|postgres(?:ql)?|mysql|mongodb(?:\+srv)?):",
    re.IGNORECASE,
)
CREDENTIAL_VALUE_RES = (
    re.compile(r"^sk-[A-Za-z0-9_-]{8,}$"),
    re.compile(r"^AKIA[0-9A-Z]{16}$"),
    re.compile(r"^gh[pousr]_[A-Za-z0-9]{20,}$"),
    re.compile(r"^Bearer\S+$", re.IGNORECASE),
)
JSON_POINTER_RE = re.compile(
    r"^/(?:[A-Za-z0-9_.~-]+)(?:/(?:[A-Za-z0-9_.~-]+))*$"
)
PUBLIC_REASON_CODE_ALLOWLIST = frozenset(
    {
        "DEPLOYMENT_REMAINS_UNBOUND_BLOCKING",
        "HOST_READBACK_ABSENT",
        "INVENTORY_CANONICAL_JSON_BYTES_MISMATCH",
        "INVENTORY_CONTENT_SHA256",
        "INVENTORY_CONTENT_SHA256_MISMATCH",
        "INVENTORY_EXACT_STATIC_SET_OR_CARDINALITY_MISMATCH",
        "INVENTORY_UNREADABLE_OR_OVERSIZED",
        "OFFLINE_STATIC_CONFORMANCE_PASS",
        "REDACTED_STAGE1A_PREP_REJECTION",
        "STAGE1A_PREP_BUILD_FAILED",
        "STAGE1A_PREP_VALIDATOR_UNEXPECTED_FAILURE",
        "TEMPLATE_CANONICAL_JSON_BYTES_MISMATCH",
        "TEMPLATE_CONTENT_SHA256",
        "TEMPLATE_CONTENT_SHA256_MISMATCH",
        "TEMPLATE_EXACT_STATIC_SET_OR_CARDINALITY_MISMATCH",
        "TEMPLATE_ILLEGAL_READBACK_STATE",
        "TEMPLATE_INVENTORY_HASH_BINDING_MISMATCH",
        "TEMPLATE_READBACK_STATE_SET_EMPTY",
        "TEMPLATE_UNBOUND_STATE_MISSING",
        "TEMPLATE_UNREADABLE_OR_OVERSIZED",
    }
)


class EpistemicBindingError(RuntimeError):
    """A fail-closed Stage1A-PREP offline-validation violation."""

    def __init__(self, reasons: Iterable[str]) -> None:
        normalized = sorted({str(reason) for reason in reasons if str(reason)})
        self.reasons = tuple(normalized or ["UNSPECIFIED_STAGE1A_PREP_REJECTION"])
        super().__init__(";".join(self.reasons))


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise EpistemicBindingError([reason])


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EpistemicBindingError([f"{label}_OBJECT_REQUIRED"])
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EpistemicBindingError([f"{label}_ARRAY_REQUIRED"])
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str] | frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != set(expected):
        reasons: list[str] = []
        if set(expected) - actual:
            reasons.append(f"{label}_MISSING_REQUIRED_KEYS")
        if actual - set(expected):
            reasons.append(f"{label}_UNKNOWN_KEYS_PRESENT")
        raise EpistemicBindingError(reasons)


def _validate_authority_ceiling(value: Any, *, label: str) -> None:
    ceiling = _require_mapping(value, f"{label}_AUTHORITY_CEILING")
    _require_exact_keys(
        ceiling,
        set(EXPECTED_AUTHORITY_CEILING),
        f"{label}_AUTHORITY_CEILING",
    )
    _require(
        all(item is False for item in ceiling.values()),
        f"{label}_AUTHORITY_CEILING_MISMATCH",
    )


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_stable_regular_file_at(
    directory_descriptor: int,
    name: str,
    *,
    max_bytes: int,
    require_private: bool = False,
) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise EpistemicBindingError(["REGULAR_FILE_OPEN_FAILED"]) from exc
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "FILE_NOT_SINGLE_LINK_REGULAR",
        )
        if require_private:
            _require(
                before.st_uid == os.geteuid()
                and stat.S_IMODE(before.st_mode) & 0o077 == 0,
                "FILE_NOT_OWNER_PRIVATE",
            )
        _require(before.st_size <= max_bytes, "FILE_SIZE_LIMIT_EXCEEDED")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            _require(total <= max_bytes, "FILE_SIZE_LIMIT_EXCEEDED")
        after = os.fstat(descriptor)
        _require(
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ),
            "FILE_CHANGED_DURING_READ",
        )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _directory_snapshot_at(
    directory_descriptor: int,
) -> dict[str, tuple[int, int, int, int, int, int]]:
    try:
        names = os.listdir(directory_descriptor)
    except OSError as exc:
        raise EpistemicBindingError(["P0_DIRECTORY_UNREADABLE"]) from exc
    snapshot: dict[str, tuple[int, int, int, int, int, int]] = {}
    reasons: list[str] = []
    for name in names:
        try:
            metadata = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except OSError:
            reasons.append("P0_DIRECTORY_ENTRY_UNREADABLE")
            continue
        if not stat.S_ISREG(metadata.st_mode):
            reasons.append("P0_DIRECTORY_ENTRY_NOT_REGULAR")
        if metadata.st_nlink != 1:
            reasons.append("P0_DIRECTORY_ENTRY_LINK_COUNT_INVALID")
        snapshot[name] = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
    if reasons:
        raise EpistemicBindingError(reasons)
    return snapshot


def _read_packet_json_at(
    packet_descriptor: int,
    relative_path: str,
    *,
    max_bytes: int,
) -> tuple[dict[str, Any], bytes]:
    raw = _read_stable_regular_file_at(
        packet_descriptor,
        relative_path,
        max_bytes=max_bytes,
    )
    try:
        payload = strict_json_loads(raw, label=relative_path)
    except Exception as exc:
        raise EpistemicBindingError(["P0_JSON_INVALID"]) from exc
    if not isinstance(payload, dict):
        raise EpistemicBindingError(["P0_JSON_OBJECT_REQUIRED"])
    return payload, raw


def load_verified_p0_packet(packet_root: Path) -> dict[str, Any]:
    """Load the exact frozen P0 packet without consulting any other source."""

    _require(packet_root.is_absolute(), "P0_PACKET_PATH_MUST_BE_ABSOLUTE")
    try:
        packet_descriptor = _open_absolute_directory_fd(packet_root)
    except OSError as exc:
        raise EpistemicBindingError(["P0_DIRECTORY_UNREADABLE"]) from exc
    try:
        packet_root_before = os.fstat(packet_descriptor)
        entries_before = _directory_snapshot_at(packet_descriptor)
        manifest, manifest_raw = _read_packet_json_at(
            packet_descriptor,
            P0_MANIFEST_PATH,
            max_bytes=MAX_P0_MANIFEST_BYTES,
        )
        _require(
            _sha256_bytes(manifest_raw) == P0_PACKET_MANIFEST_SHA256,
            "P0_MANIFEST_SHA256_MISMATCH",
        )
        _require(manifest.get("packet_id") == P0_PACKET_ID, "P0_PACKET_ID_MISMATCH")
        artifacts = _require_list(manifest.get("artifacts"), "P0_ARTIFACTS")
        _require(
            len(artifacts) == EXPECTED_ARTIFACT_COUNT,
            "P0_ARTIFACT_COUNT_MISMATCH",
        )

        declared: dict[str, Mapping[str, Any]] = {}
        reasons: list[str] = []
        for index, raw_row in enumerate(artifacts):
            row = _require_mapping(raw_row, f"P0_ARTIFACT_{index}")
            if set(row) != {"path", "bytes", "sha256"}:
                reasons.append(f"P0_ARTIFACT_{index}_SHAPE_INVALID")
                continue
            path = row.get("path")
            size = row.get("bytes")
            digest = row.get("sha256")
            if (
                not isinstance(path, str)
                or not path
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                or "/" in path
            ):
                reasons.append(f"P0_ARTIFACT_{index}_PATH_INVALID")
                continue
            if path in declared:
                reasons.append("P0_ARTIFACT_DUPLICATE")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                reasons.append(f"P0_ARTIFACT_{index}_SIZE_INVALID")
            if not isinstance(digest, str) or len(digest) != 64:
                reasons.append(f"P0_ARTIFACT_{index}_SHA256_INVALID")
            declared[path] = row
        if reasons:
            raise EpistemicBindingError(reasons)

        expected_names = set(declared) | {P0_MANIFEST_PATH}
        _require(
            len(entries_before) == EXPECTED_DIRECTORY_FILE_COUNT,
            "P0_DIRECTORY_FILE_COUNT_MISMATCH",
        )
        _require(
            set(entries_before) == expected_names,
            "P0_DIRECTORY_CLOSURE_MISMATCH",
        )

        artifact_payloads: dict[str, bytes] = {}
        for path, row in sorted(declared.items()):
            raw = _read_stable_regular_file_at(
                packet_descriptor,
                path,
                max_bytes=MAX_P0_ARTIFACT_BYTES,
            )
            if len(raw) != row["bytes"]:
                reasons.append("P0_ARTIFACT_BYTES_MISMATCH")
            if _sha256_bytes(raw) != row["sha256"]:
                reasons.append("P0_ARTIFACT_SHA256_MISMATCH")
            artifact_payloads[path] = raw
        if reasons:
            raise EpistemicBindingError(reasons)

        for required_path in (P0_AUTHORITY_REGISTRY_PATH, P0_ADAPTER_REGISTRY_PATH):
            _require(
                required_path in artifact_payloads,
                "P0_REQUIRED_ARTIFACT_MISSING",
            )

        try:
            authority_registry = strict_json_loads(
                artifact_payloads[P0_AUTHORITY_REGISTRY_PATH],
                label=P0_AUTHORITY_REGISTRY_PATH,
            )
            adapter_registry = strict_json_loads(
                artifact_payloads[P0_ADAPTER_REGISTRY_PATH],
                label=P0_ADAPTER_REGISTRY_PATH,
            )
        except Exception as exc:
            raise EpistemicBindingError(["P0_REGISTRY_JSON_INVALID"]) from exc
        _require(isinstance(authority_registry, dict), "P0_AUTHORITY_REGISTRY_INVALID")
        _require(isinstance(adapter_registry, dict), "P0_ADAPTER_REGISTRY_INVALID")

        _require(
            _read_stable_regular_file_at(
                packet_descriptor,
                P0_MANIFEST_PATH,
                max_bytes=MAX_P0_MANIFEST_BYTES,
            )
            == manifest_raw,
            "P0_MANIFEST_CHANGED_DURING_READ",
        )
        for path, first_read in artifact_payloads.items():
            _require(
                _read_stable_regular_file_at(
                    packet_descriptor,
                    path,
                    max_bytes=MAX_P0_ARTIFACT_BYTES,
                )
                == first_read,
                "P0_ARTIFACT_CHANGED_DURING_READ",
            )
        entries_after = _directory_snapshot_at(packet_descriptor)
        packet_root_after = os.fstat(packet_descriptor)
        _require(entries_after == entries_before, "P0_DIRECTORY_CHANGED_DURING_READ")
        _require(
            (
                packet_root_before.st_dev,
                packet_root_before.st_ino,
                packet_root_before.st_mtime_ns,
                packet_root_before.st_ctime_ns,
            )
            == (
                packet_root_after.st_dev,
                packet_root_after.st_ino,
                packet_root_after.st_mtime_ns,
                packet_root_after.st_ctime_ns,
            ),
            "P0_DIRECTORY_IDENTITY_CHANGED_DURING_READ",
        )
        try:
            packet_path_after = os.stat(packet_root, follow_symlinks=False)
        except OSError as exc:
            raise EpistemicBindingError(["P0_DIRECTORY_UNREADABLE"]) from exc
        _require(
            (packet_path_after.st_dev, packet_path_after.st_ino)
            == (packet_root_after.st_dev, packet_root_after.st_ino),
            "P0_DIRECTORY_PATH_IDENTITY_CHANGED_DURING_READ",
        )
        return {
            "manifest": manifest,
            "authority_registry": authority_registry,
            "adapter_registry": adapter_registry,
        }
    finally:
        os.close(packet_descriptor)


def _static_row_hash(row: Mapping[str, Any], *excluded_fields: str) -> str:
    static = {key: value for key, value in row.items() if key not in excluded_fields}
    return stable_json_hash(static)


def _collect_declared_roots(authorities: list[Any]) -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    for raw_authority in authorities:
        authority = _require_mapping(raw_authority, "AUTHORITY")
        authority_id = authority.get("logical_authority_id")
        logical_roots = authority.get("logical_root_bindings")
        if not isinstance(logical_roots, Mapping):
            continue
        for value in logical_roots.values():
            if isinstance(value, Mapping) and isinstance(value.get("root_anchor_id"), str):
                roots.append(
                    {
                        "root_anchor_id": value["root_anchor_id"],
                        "authority_boundary": authority_id,
                    }
                )
    roots.sort(key=lambda row: row["root_anchor_id"])
    return roots


def _expected_root_relationships(authority_registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    authorities = {
        row.get("logical_authority_id"): row
        for row in _require_list(authority_registry.get("authority_boundaries"), "AUTHORITIES")
        if isinstance(row, Mapping)
    }
    memory = _require_mapping(
        authorities.get("FF_HOST_MEMORY_AUTHORITY_CURRENT"),
        "MEMORY_AUTHORITY",
    )
    delivery = _require_mapping(
        authorities.get("FF_HOST_AGENT_DELIVERY_AUTHORITY_CURRENT"),
        "DELIVERY_AUTHORITY",
    )
    memory_roots = _require_mapping(memory.get("logical_root_bindings"), "MEMORY_ROOTS")
    _require(
        memory_roots.get("required_relationship") == "DISJOINT_SIBLING",
        "MEMORY_ROOT_RELATIONSHIP_MISMATCH",
    )
    delivery_roots = _require_mapping(
        delivery.get("logical_root_bindings"),
        "DELIVERY_ROOTS",
    )
    source_pairs = set()
    for raw_row in _require_list(
        delivery_roots.get("required_relationships"),
        "DELIVERY_RELATIONSHIPS",
    ):
        row = _require_mapping(raw_row, "DELIVERY_RELATIONSHIP")
        if row.get("left_ref_kind") == row.get("right_ref_kind") == "ROOT_ANCHOR":
            source_pairs.add(
                (
                    row.get("left_ref"),
                    row.get("right_ref"),
                    row.get("required_relationship"),
                )
            )
    expected_delivery_pairs = {
        (left, right, relationship)
        for _, left, right, relationship in EXPECTED_ROOT_RELATIONSHIP_SPECS[1:]
    }
    _require(
        source_pairs == expected_delivery_pairs,
        "DELIVERY_ROOT_RELATIONSHIP_SET_MISMATCH",
    )
    root_law = _require_mapping(
        authority_registry.get("root_anchor_reference_integrity_law"),
        "ROOT_ANCHOR_INTEGRITY_LAW",
    )
    forbidden = _require_list(
        root_law.get("forbidden_physical_relationships"),
        "FORBIDDEN_PHYSICAL_RELATIONSHIPS",
    )
    _require(
        tuple(forbidden) == EXPECTED_FORBIDDEN_PHYSICAL_RELATIONSHIPS,
        "FORBIDDEN_PHYSICAL_RELATIONSHIP_SET_MISMATCH",
    )
    return [
        {
            "relationship_id": relationship_id,
            "left_root_anchor_id": left,
            "right_root_anchor_id": right,
            "required_relationship": relationship,
            "forbidden_relationships": list(
                EXPECTED_FORBIDDEN_PHYSICAL_RELATIONSHIPS
            ),
        }
        for relationship_id, left, right, relationship in EXPECTED_ROOT_RELATIONSHIP_SPECS
    ]


def _compile_authorities(authority_registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = _require_list(authority_registry.get("authority_boundaries"), "AUTHORITIES")
    _require(len(source) == EXPECTED_AUTHORITY_COUNT, "AUTHORITY_COUNT_MISMATCH")
    output: list[dict[str, Any]] = []
    for raw_row in source:
        row = _require_mapping(raw_row, "AUTHORITY")
        output.append(
            {
                "logical_authority_id": row.get("logical_authority_id"),
                "owner_role": row.get("owner_role"),
                "baseline_effective_status": row.get("effective_status"),
                "static_row_sha256": _static_row_hash(row, "deployment_observation"),
            }
        )
    output.sort(key=lambda row: row["logical_authority_id"])
    _require(
        {row["logical_authority_id"] for row in output} == EXPECTED_AUTHORITY_IDS,
        "AUTHORITY_ID_SET_MISMATCH",
    )
    return output


def _compile_sod_profiles(
    authority_registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    source = _require_list(authority_registry.get("sod_profiles"), "SOD_PROFILES")
    _require(
        len(source) == EXPECTED_SOD_PROFILE_COUNT,
        "SOD_PROFILE_COUNT_MISMATCH",
    )
    output: list[dict[str, Any]] = []
    for raw_row in source:
        row = _require_mapping(raw_row, "SOD_PROFILE")
        _require_exact_keys(
            row,
            {"profile_id", "constraint_kind", "dynamic_closure_ref"},
            "SOD_PROFILE",
        )
        output.append(
            {
                "profile_id": row["profile_id"],
                "constraint_kind": row["constraint_kind"],
                "dynamic_closure_ref": row["dynamic_closure_ref"],
                "static_row_sha256": stable_json_hash(row),
            }
        )
    output.sort(key=lambda row: row["profile_id"])
    _require(
        len({row["profile_id"] for row in output}) == EXPECTED_SOD_PROFILE_COUNT,
        "SOD_PROFILE_ID_COLLISION",
    )
    return output


def _compile_roots(authority_registry: Mapping[str, Any]) -> list[dict[str, str]]:
    authorities = _require_list(authority_registry.get("authority_boundaries"), "AUTHORITIES")
    roots = _collect_declared_roots(authorities)
    _require(len(roots) == EXPECTED_ROOT_COUNT, "ROOT_COUNT_MISMATCH")
    expected = {
        (root_anchor_id, authority_boundary)
        for root_anchor_id, authority_boundary in EXPECTED_ROOT_SPECS
    }
    actual = {
        (row["root_anchor_id"], row["authority_boundary"])
        for row in roots
    }
    _require(actual == expected, "ROOT_SET_MISMATCH")
    return roots


def _compile_delivery_endpoints(
    authority_registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    delivery_authority = next(
        (
            row
            for row in _require_list(
                authority_registry.get("authority_boundaries"),
                "AUTHORITIES",
            )
            if isinstance(row, Mapping)
            and row.get("logical_authority_id")
            == "FF_HOST_AGENT_DELIVERY_AUTHORITY_CURRENT"
        ),
        None,
    )
    delivery = _require_mapping(delivery_authority, "DELIVERY_AUTHORITY")
    roots = _require_mapping(delivery.get("logical_root_bindings"), "DELIVERY_ROOTS")
    source = _require_list(roots.get("derived_ledger_endpoints"), "DELIVERY_ENDPOINTS")
    _require(
        len(source) == EXPECTED_DELIVERY_ENDPOINT_COUNT,
        "DELIVERY_ENDPOINT_COUNT_MISMATCH",
    )
    allowed_keys = {
        "logical_store_id",
        "authority_boundary",
        "root_anchor",
        "relative_locator",
        "design_schema_id",
    }
    output: list[dict[str, Any]] = []
    for raw_row in source:
        row = _require_mapping(raw_row, "DELIVERY_ENDPOINT")
        _require_exact_keys(row, allowed_keys, "DELIVERY_ENDPOINT")
        output.append(dict(row))
    output.sort(key=lambda row: row["logical_store_id"])
    _require(
        {row["logical_store_id"] for row in output}
        == {REQUEST_DELIVERY_STORE, RESPONSE_DELIVERY_STORE},
        "DELIVERY_ENDPOINT_ID_SET_MISMATCH",
    )
    _require(
        all(row["root_anchor"] == DELIVERY_ROOT for row in output),
        "DELIVERY_ENDPOINT_ROOT_MISMATCH",
    )
    return output


def _compile_stores(authority_registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = _require_list(authority_registry.get("stores"), "STORES")
    _require(len(source) == EXPECTED_STORE_COUNT, "STORE_COUNT_MISMATCH")
    output: list[dict[str, Any]] = []
    for raw_row in source:
        row = _require_mapping(raw_row, "STORE")
        decision = _require_mapping(row.get("logical_binding_decision"), "STORE_DECISION")
        output.append(
            {
                "logical_store_id": row.get("logical_id"),
                "design_schema_id": row.get("design_schema_id"),
                "authority_boundary": row.get("authority_boundary"),
                "root_anchor_id": decision.get("root_anchor"),
                "relative_locator": decision.get("relative_locator"),
                "store_family": decision.get("store_family"),
                "baseline_effective_status": row.get("effective_status"),
                "static_row_sha256": _static_row_hash(row, "deployment_observation"),
            }
        )
    output.sort(key=lambda row: row["logical_store_id"])
    _require(
        {row["logical_store_id"] for row in output} == EXPECTED_STORE_IDS,
        "STORE_ID_SET_MISMATCH",
    )
    _require(
        all(row["baseline_effective_status"] == "UNBOUND_BLOCKING" for row in output),
        "STORE_BASELINE_STATUS_MISMATCH",
    )
    endpoint_keys = {
        (row["root_anchor_id"], row["relative_locator"])
        for row in output
    }
    _require(len(endpoint_keys) == EXPECTED_STORE_COUNT, "STORE_ENDPOINT_KEY_COLLISION")
    for row in output:
        expected_root = (
            DELIVERY_ROOT
            if row["logical_store_id"] in {REQUEST_DELIVERY_STORE, RESPONSE_DELIVERY_STORE}
            else EPISTEMIC_TRANSACTION_ROOT
        )
        _require(row["root_anchor_id"] == expected_root, "STORE_ROOT_ASSIGNMENT_MISMATCH")
    return output


def _compile_deployment_rows(
    authority_registry: Mapping[str, Any],
    *,
    sod_profile_ids: frozenset[str],
) -> dict[str, list[dict[str, Any]]]:
    principal_source = _require_list(
        authority_registry.get("principal_requirements"),
        "PRINCIPAL_REQUIREMENTS",
    )
    event_source = _require_list(
        authority_registry.get("principal_event_purpose_bindings"),
        "EVENT_BINDINGS",
    )
    trust_source = _require_list(
        authority_registry.get("external_trust_domain_bindings"),
        "EXTERNAL_TRUST_BINDINGS",
    )
    _require(
        len(principal_source) == EXPECTED_PRINCIPAL_DEPLOYMENT_COUNT,
        "PRINCIPAL_DEPLOYMENT_COUNT_MISMATCH",
    )
    _require(
        len(event_source) == EXPECTED_EVENT_DEPLOYMENT_COUNT,
        "EVENT_DEPLOYMENT_COUNT_MISMATCH",
    )
    _require(
        len(trust_source) == EXPECTED_EXTERNAL_TRUST_DEPLOYMENT_COUNT,
        "EXTERNAL_TRUST_DEPLOYMENT_COUNT_MISMATCH",
    )

    principals: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    external_trust: list[dict[str, Any]] = []
    for source_index, raw_row in enumerate(principal_source):
        row = _require_mapping(raw_row, "PRINCIPAL_DEPLOYMENT")
        _require(row.get("deployment_row") is None, "PRINCIPAL_DEPLOYMENT_NOT_NULL")
        principals.append(
            {
                "row_kind": "PRINCIPAL_REQUIREMENT",
                "row_id": row.get("logical_principal"),
                "action_role": row.get("action_role"),
                "source_registry_artifact": P0_AUTHORITY_REGISTRY_PATH,
                "deployment_row_json_pointer": (
                    f"/principal_requirements/{source_index}/deployment_row"
                ),
                "baseline_effective_status": row.get("effective_status"),
                "static_row_sha256": _static_row_hash(row, "deployment_row"),
            }
        )
    for source_index, raw_row in enumerate(event_source):
        row = _require_mapping(raw_row, "EVENT_DEPLOYMENT")
        _require(row.get("deployment_row") is None, "EVENT_DEPLOYMENT_NOT_NULL")
        sod_profile_ref = row.get("sod_profile_ref")
        _require(
            isinstance(sod_profile_ref, str) and sod_profile_ref in sod_profile_ids,
            "EVENT_SOD_PROFILE_REF_UNRESOLVED",
        )
        events.append(
            {
                "row_kind": "EVENT_PURPOSE_BINDING",
                "row_id": row.get("binding_id"),
                "principal_requirement_ref": row.get("principal_requirement_ref"),
                "sod_profile_ref": sod_profile_ref,
                "source_registry_artifact": P0_AUTHORITY_REGISTRY_PATH,
                "deployment_row_json_pointer": (
                    f"/principal_event_purpose_bindings/{source_index}/deployment_row"
                ),
                "baseline_effective_status": row.get("effective_status"),
                "static_row_sha256": _static_row_hash(row, "deployment_row"),
            }
        )
    for source_index, raw_row in enumerate(trust_source):
        row = _require_mapping(raw_row, "EXTERNAL_TRUST_DEPLOYMENT")
        _require(row.get("deployment_row") is None, "EXTERNAL_TRUST_DEPLOYMENT_NOT_NULL")
        external_trust.append(
            {
                "row_kind": "EXTERNAL_TRUST_DOMAIN",
                "row_id": row.get("logical_trust_domain_id"),
                "external_owner_ref": row.get("external_owner_ref"),
                "allowed_event_binding_ids": row.get("allowed_event_binding_ids"),
                "source_registry_artifact": P0_AUTHORITY_REGISTRY_PATH,
                "deployment_row_json_pointer": (
                    f"/external_trust_domain_bindings/{source_index}/deployment_row"
                ),
                "baseline_effective_status": row.get("effective_status"),
                "static_row_sha256": _static_row_hash(row, "deployment_row"),
            }
        )

    principals.sort(key=lambda row: row["row_id"])
    events.sort(key=lambda row: row["row_id"])
    external_trust.sort(key=lambda row: row["row_id"])
    all_rows = principals + events + external_trust
    _require(len(all_rows) == EXPECTED_DEPLOYMENT_COUNT, "DEPLOYMENT_COUNT_MISMATCH")
    _require(
        len({(row["row_kind"], row["row_id"]) for row in all_rows})
        == EXPECTED_DEPLOYMENT_COUNT,
        "DEPLOYMENT_ROW_ID_COLLISION",
    )
    _require(
        len({row["deployment_row_json_pointer"] for row in all_rows})
        == EXPECTED_DEPLOYMENT_COUNT,
        "DEPLOYMENT_ROW_JSON_POINTER_COLLISION",
    )
    _require(
        {row["sod_profile_ref"] for row in events} == set(sod_profile_ids),
        "EVENT_SOD_PROFILE_REFERENCE_CLOSURE_MISMATCH",
    )
    _require(
        dict(Counter(row["baseline_effective_status"] for row in all_rows))
        == EXPECTED_DEPLOYMENT_STATUS_COUNTS,
        "DEPLOYMENT_STATUS_COUNTS_MISMATCH",
    )
    return {
        "principal_rows": principals,
        "event_rows": events,
        "external_trust_rows": external_trust,
    }


def _compile_adapters(adapter_registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = _require_list(adapter_registry.get("adapters"), "ADAPTERS")
    _require(len(source) == EXPECTED_ADAPTER_COUNT, "ADAPTER_COUNT_MISMATCH")
    output: list[dict[str, Any]] = []
    unique_count = 0
    discriminated_count = 0
    for raw_row in source:
        row = _require_mapping(raw_row, "ADAPTER")
        schema_id = row.get("adapter_schema_id")
        discriminator = row.get("adapter_discriminator")
        if schema_id in UNIQUE_SCHEMA_ADAPTER_IDS:
            _require(discriminator is None, "UNIQUE_ADAPTER_DISCRIMINATOR_FORBIDDEN")
            _require(
                row.get("locator_branch") == "UNIQUE_SCHEMA_LOCATOR",
                "UNIQUE_ADAPTER_BRANCH_MISMATCH",
            )
            branch = "UNIQUE_SCHEMA_LOCATOR"
            unique_count += 1
        else:
            _require(
                isinstance(discriminator, str) and discriminator,
                "DISCRIMINATED_ADAPTER_DISCRIMINATOR_MISSING",
            )
            _require(
                "locator_branch" not in row,
                "DISCRIMINATED_ADAPTER_BRANCH_METADATA_FORBIDDEN",
            )
            branch = "DISCRIMINATED_SCHEMA_LOCATOR"
            discriminated_count += 1
        consumers = _require_list(row.get("consumers"), "ADAPTER_CONSUMERS")
        _require(bool(consumers), "ADAPTER_CONSUMERS_EMPTY")
        consumer_hashes = sorted(
            stable_json_hash(_require_mapping(consumer, "ADAPTER_CONSUMER"))
            for consumer in consumers
        )
        compiled = {
            "row_id": row.get("row_id"),
            "adapter_schema_id": schema_id,
            "locator_branch_registry_metadata": branch,
            "consumer_count": len(consumers),
            "consumer_tuple_sha256s": consumer_hashes,
            "baseline_effective_status": row.get("effective_status"),
            "static_row_sha256": stable_json_hash(row),
        }
        if branch == "DISCRIMINATED_SCHEMA_LOCATOR":
            compiled["adapter_discriminator"] = discriminator
        output.append(compiled)
    output.sort(key=lambda row: row["row_id"])
    _require(
        unique_count == EXPECTED_UNIQUE_SCHEMA_ADAPTER_COUNT,
        "UNIQUE_ADAPTER_COUNT_MISMATCH",
    )
    _require(
        discriminated_count == EXPECTED_DISCRIMINATED_ADAPTER_COUNT,
        "DISCRIMINATED_ADAPTER_COUNT_MISMATCH",
    )
    _require(
        len({row["row_id"] for row in output}) == EXPECTED_ADAPTER_COUNT,
        "ADAPTER_ROW_ID_COLLISION",
    )
    _require(
        dict(Counter(row["baseline_effective_status"] for row in output))
        == EXPECTED_ADAPTER_STATUS_COUNTS,
        "ADAPTER_STATUS_COUNTS_MISMATCH",
    )
    return output


def _assert_sanitized_closed_output(payload: Mapping[str, Any], *, label: str) -> None:
    reasons: list[str] = []
    stack: list[tuple[str, str | None, Any]] = [(label, None, payload)]
    while stack:
        path, parent_key, value = stack.pop()
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized in FORBIDDEN_OUTPUT_KEYS:
                    reasons.append("SANITIZED_OUTPUT_FORBIDDEN_KEY")
                stack.append((f"{path}_{key}", normalized, nested))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                stack.append((f"{path}_{index}", parent_key, nested))
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > MAX_STAGE1A_STRING_BYTES:
                reasons.append("SANITIZED_OUTPUT_STRING_TOO_LARGE")
            if any(character.isspace() for character in value):
                reasons.append("SANITIZED_OUTPUT_FREE_PROSE_OR_WHITESPACE_FORBIDDEN")
            if parent_key == "deployment_row_json_pointer":
                if not JSON_POINTER_RE.fullmatch(value):
                    reasons.append("SANITIZED_OUTPUT_CANONICAL_JSON_POINTER_INVALID")
                continue
            lowered = value.lower()
            if (
                value.startswith(("/", "~"))
                or WINDOWS_ABSOLUTE_PATH_RE.match(value)
                or PRIVATE_URI_RE.match(value)
                or "/users/" in lowered
                or "-----begin" in lowered
                or any(pattern.match(value) for pattern in CREDENTIAL_VALUE_RES)
            ):
                reasons.append("SANITIZED_OUTPUT_PRIVATE_OR_KEY_MATERIAL_FORBIDDEN")
    if reasons:
        raise EpistemicBindingError(reasons)


def build_expected_inventory(packet_root: Path) -> dict[str, Any]:
    packet = load_verified_p0_packet(packet_root)
    manifest = packet["manifest"]
    authority_registry = packet["authority_registry"]
    adapter_registry = packet["adapter_registry"]

    authorities = _compile_authorities(authority_registry)
    sod_profiles = _compile_sod_profiles(authority_registry)
    roots = _compile_roots(authority_registry)
    root_relationships = _expected_root_relationships(authority_registry)
    delivery_endpoints = _compile_delivery_endpoints(authority_registry)
    stores = _compile_stores(authority_registry)
    deployment_rows = _compile_deployment_rows(
        authority_registry,
        sod_profile_ids=frozenset(row["profile_id"] for row in sod_profiles),
    )
    adapters = _compile_adapters(adapter_registry)

    inventory = {
        "artifact_type": INVENTORY_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "p0_packet_id": P0_PACKET_ID,
        "p0_packet_manifest_sha256": P0_PACKET_MANIFEST_SHA256,
        "p0_artifacts": [
            {
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in sorted(manifest["artifacts"], key=lambda item: item["path"])
        ],
        "counts": {
            "p0_artifacts": EXPECTED_ARTIFACT_COUNT,
            "p0_directory_regular_files": EXPECTED_DIRECTORY_FILE_COUNT,
            "authorities": EXPECTED_AUTHORITY_COUNT,
            "sod_profiles": EXPECTED_SOD_PROFILE_COUNT,
            "roots": EXPECTED_ROOT_COUNT,
            "root_relationships": EXPECTED_ROOT_RELATIONSHIP_COUNT,
            "required_relationships_total": EXPECTED_REQUIRED_RELATIONSHIP_COUNT,
            "delivery_endpoints": EXPECTED_DELIVERY_ENDPOINT_COUNT,
            "stores": EXPECTED_STORE_COUNT,
            "principal_deployment_rows": EXPECTED_PRINCIPAL_DEPLOYMENT_COUNT,
            "event_deployment_rows": EXPECTED_EVENT_DEPLOYMENT_COUNT,
            "external_trust_deployment_rows": EXPECTED_EXTERNAL_TRUST_DEPLOYMENT_COUNT,
            "deployment_rows_total": EXPECTED_DEPLOYMENT_COUNT,
            "adapters": EXPECTED_ADAPTER_COUNT,
            "unique_schema_adapters": EXPECTED_UNIQUE_SCHEMA_ADAPTER_COUNT,
            "discriminated_adapters": EXPECTED_DISCRIMINATED_ADAPTER_COUNT,
        },
        "authorities": authorities,
        "sod_profiles": sod_profiles,
        "roots": roots,
        "root_relationships": root_relationships,
        "delivery_endpoints": delivery_endpoints,
        "delivery_endpoint_relationship": {
            "relationship_id": "ENDPOINT_REL_REQUEST_TO_RESPONSE",
            "left_store_id": REQUEST_DELIVERY_STORE,
            "right_store_id": RESPONSE_DELIVERY_STORE,
            "required_relationship": "DISJOINT_SIBLING",
            "forbidden_relationships": list(
                EXPECTED_FORBIDDEN_PHYSICAL_RELATIONSHIPS
            ),
        },
        "stores": stores,
        "deployment_rows": deployment_rows,
        "adapters": adapters,
        "authority_ceiling": dict(EXPECTED_AUTHORITY_CEILING),
    }
    output = with_content_hash(inventory, hash_field="content_sha256")
    _assert_sanitized_closed_output(output, label="INVENTORY")
    _require(
        len(_canonical_output_bytes(output)) <= MAX_STAGE1A_JSON_BYTES,
        "INVENTORY_SIZE_LIMIT_EXCEEDED",
    )
    return output


def _readback_state(baseline_status: str) -> str:
    return PROHIBITED_STATE if baseline_status == NOT_AUTHORIZED_STATUS else UNBOUND_STATE


def _build_blank_readback_template_from_expected(
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    validate_expected_inventory_shape(inventory)
    deployment = _require_mapping(inventory["deployment_rows"], "DEPLOYMENT_ROWS")
    template = {
        "artifact_type": BLANK_TEMPLATE_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "p0_packet_manifest_sha256": P0_PACKET_MANIFEST_SHA256,
        "inventory_content_sha256": inventory["content_sha256"],
        "readback_mode": "BLANK_OFFLINE_TEMPLATE_ONLY",
        "authorities": [
            {
                "logical_authority_id": row["logical_authority_id"],
                "baseline_effective_status": row["baseline_effective_status"],
                "readback_state": _readback_state(row["baseline_effective_status"]),
            }
            for row in inventory["authorities"]
        ],
        "sod_profiles": [dict(row) for row in inventory["sod_profiles"]],
        "roots": [
            {
                **row,
                "readback_state": UNBOUND_STATE,
            }
            for row in inventory["roots"]
        ],
        "root_relationships": [
            {
                **row,
                "readback_state": UNBOUND_STATE,
            }
            for row in inventory["root_relationships"]
        ],
        "delivery_endpoints": [
            {
                **row,
                "readback_state": UNBOUND_STATE,
            }
            for row in inventory["delivery_endpoints"]
        ],
        "delivery_endpoint_relationship": {
            **inventory["delivery_endpoint_relationship"],
            "readback_state": UNBOUND_STATE,
        },
        "stores": [
            {
                "logical_store_id": row["logical_store_id"],
                "design_schema_id": row["design_schema_id"],
                "authority_boundary": row["authority_boundary"],
                "root_anchor_id": row["root_anchor_id"],
                "relative_locator": row["relative_locator"],
                "store_family": row["store_family"],
                "baseline_effective_status": row["baseline_effective_status"],
                "readback_state": UNBOUND_STATE,
            }
            for row in inventory["stores"]
        ],
        "deployment_rows": {
            section: [
                {
                    "row_kind": row["row_kind"],
                    "row_id": row["row_id"],
                    "source_registry_artifact": row["source_registry_artifact"],
                    "deployment_row_json_pointer": row[
                        "deployment_row_json_pointer"
                    ],
                    **(
                        {"sod_profile_ref": row["sod_profile_ref"]}
                        if "sod_profile_ref" in row
                        else {}
                    ),
                    "baseline_effective_status": row["baseline_effective_status"],
                    "readback_state": _readback_state(
                        row["baseline_effective_status"]
                    ),
                }
                for row in deployment[section]
            ]
            for section in (
                "principal_rows",
                "event_rows",
                "external_trust_rows",
            )
        },
        "adapters": [
            {
                **{
                    key: row[key]
                    for key in (
                        "row_id",
                        "adapter_schema_id",
                        "locator_branch_registry_metadata",
                        "baseline_effective_status",
                    )
                },
                **(
                    {"adapter_discriminator": row["adapter_discriminator"]}
                    if "adapter_discriminator" in row
                    else {}
                ),
                "readback_state": _readback_state(
                    row["baseline_effective_status"]
                ),
            }
            for row in inventory["adapters"]
        ],
        "authority_ceiling": dict(inventory["authority_ceiling"]),
    }
    output = with_content_hash(template, hash_field="content_sha256")
    _assert_sanitized_closed_output(output, label="TEMPLATE")
    _require(
        len(_canonical_output_bytes(output)) <= MAX_STAGE1A_JSON_BYTES,
        "TEMPLATE_SIZE_LIMIT_EXCEEDED",
    )
    return output


def build_blank_readback_template(packet_root: Path) -> dict[str, Any]:
    """Build a blank template only from the exact frozen packet."""

    return _build_blank_readback_template_from_expected(
        build_expected_inventory(packet_root)
    )


def _canonical_output_bytes(payload: Mapping[str, Any]) -> bytes:
    import json

    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _validate_content_hash_or_reject(
    payload: Mapping[str, Any],
    *,
    label: str,
) -> None:
    reasons = validate_content_hash(
        payload,
        hash_field="content_sha256",
        label=label,
    )
    if reasons:
        raise EpistemicBindingError(
            [reason.upper().replace(".", "_") for reason in reasons]
        )


def validate_expected_inventory_shape(inventory: Mapping[str, Any]) -> None:
    _require_exact_keys(
        inventory,
        {
            "artifact_type",
            "schema_version",
            "p0_packet_id",
            "p0_packet_manifest_sha256",
            "p0_artifacts",
            "counts",
            "authorities",
            "sod_profiles",
            "roots",
            "root_relationships",
            "delivery_endpoints",
            "delivery_endpoint_relationship",
            "stores",
            "deployment_rows",
            "adapters",
            "authority_ceiling",
            "content_sha256",
        },
        "INVENTORY",
    )
    _require(inventory["artifact_type"] == INVENTORY_SCHEMA_ID, "INVENTORY_SCHEMA_ID_MISMATCH")
    _require(inventory["schema_version"] == SCHEMA_VERSION, "INVENTORY_SCHEMA_VERSION_MISMATCH")
    _require(inventory["p0_packet_id"] == P0_PACKET_ID, "INVENTORY_PACKET_ID_MISMATCH")
    _require(
        inventory["p0_packet_manifest_sha256"] == P0_PACKET_MANIFEST_SHA256,
        "INVENTORY_MANIFEST_BINDING_MISMATCH",
    )
    _validate_authority_ceiling(
        inventory["authority_ceiling"],
        label="INVENTORY",
    )
    _validate_content_hash_or_reject(inventory, label="inventory")
    _assert_sanitized_closed_output(inventory, label="INVENTORY")


def validate_blank_template_shape(template: Mapping[str, Any]) -> None:
    _require_exact_keys(
        template,
        {
            "artifact_type",
            "schema_version",
            "p0_packet_manifest_sha256",
            "inventory_content_sha256",
            "readback_mode",
            "authorities",
            "sod_profiles",
            "roots",
            "root_relationships",
            "delivery_endpoints",
            "delivery_endpoint_relationship",
            "stores",
            "deployment_rows",
            "adapters",
            "authority_ceiling",
            "content_sha256",
        },
        "TEMPLATE",
    )
    _require(template["artifact_type"] == BLANK_TEMPLATE_SCHEMA_ID, "TEMPLATE_SCHEMA_ID_MISMATCH")
    _require(template["schema_version"] == SCHEMA_VERSION, "TEMPLATE_SCHEMA_VERSION_MISMATCH")
    _require(
        template["p0_packet_manifest_sha256"] == P0_PACKET_MANIFEST_SHA256,
        "TEMPLATE_MANIFEST_BINDING_MISMATCH",
    )
    _require(
        template["readback_mode"] == "BLANK_OFFLINE_TEMPLATE_ONLY",
        "TEMPLATE_READBACK_MODE_MISMATCH",
    )
    _validate_authority_ceiling(
        template["authority_ceiling"],
        label="TEMPLATE",
    )
    _validate_content_hash_or_reject(template, label="template")
    _assert_sanitized_closed_output(template, label="TEMPLATE")


def _read_explicit_json(path: Path, *, label: str) -> dict[str, Any]:
    _require(path.is_absolute(), f"{label}_PATH_MUST_BE_ABSOLUTE")
    parent_descriptor: int | None = None
    try:
        parent_descriptor = _open_absolute_directory_fd(path.parent)
        raw = _read_stable_regular_file_at(
            parent_descriptor,
            path.name,
            max_bytes=MAX_STAGE1A_JSON_BYTES,
        )
        payload = strict_json_loads(raw, label=label)
        canonical_raw = _canonical_output_bytes(payload)
    except Exception as exc:
        raise EpistemicBindingError([f"{label}_UNREADABLE_OR_OVERSIZED"]) from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    if not isinstance(payload, dict):
        raise EpistemicBindingError([f"{label}_OBJECT_REQUIRED"])
    _require(
        raw == canonical_raw,
        f"{label}_CANONICAL_JSON_BYTES_MISMATCH",
    )
    return payload


def _validation_receipt(
    *,
    verdict: str,
    reason_codes: Iterable[str],
    inventory_content_sha256: str | None = None,
    template_content_sha256: str | None = None,
) -> dict[str, Any]:
    public_reason_codes = sorted(
        {
            code
            if code in PUBLIC_REASON_CODE_ALLOWLIST
            else "REDACTED_STAGE1A_PREP_REJECTION"
            for raw_code in reason_codes
            for code in [str(raw_code)]
        }
    )

    def public_digest(value: str | None) -> str:
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            return value
        return "UNAVAILABLE"

    payload = {
        "artifact_type": VALIDATION_RECEIPT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "p0_packet_manifest_sha256": P0_PACKET_MANIFEST_SHA256,
        "inventory_content_sha256": public_digest(inventory_content_sha256),
        "template_content_sha256": public_digest(template_content_sha256),
        "validation_status": verdict,
        "reason_codes": public_reason_codes,
        "runtime_authority": False,
        "host_readback_authority": False,
        "binding_authority": False,
        "publication_authority": False,
        "consumption_authority": False,
        "signature_generation_authority": False,
    }
    output = with_content_hash(payload, hash_field="content_sha256")
    _assert_sanitized_closed_output(output, label="VALIDATION_RECEIPT")
    return output


def build_rejected_validation_receipt(
    *,
    boundary: str,
) -> dict[str, Any]:
    """Build a closed, redacted fail-closed receipt for a CLI boundary."""

    reason_code = {
        "BUILD_CLI": "STAGE1A_PREP_BUILD_FAILED",
        "VALIDATE_CLI": "STAGE1A_PREP_VALIDATOR_UNEXPECTED_FAILURE",
    }.get(boundary, "REDACTED_STAGE1A_PREP_REJECTION")
    return _validation_receipt(
        verdict=REJECTED_VERDICT,
        reason_codes=[reason_code],
    )


def validate_stage1a_files(
    *,
    packet_root: Path,
    inventory_path: Path,
    template_path: Path,
) -> dict[str, Any]:
    supplied_inventory: dict[str, Any] | None = None
    supplied_template: dict[str, Any] | None = None
    try:
        expected_inventory = build_expected_inventory(packet_root)
        expected_template = _build_blank_readback_template_from_expected(
            expected_inventory
        )
        supplied_inventory = _read_explicit_json(inventory_path, label="INVENTORY")
        supplied_template = _read_explicit_json(template_path, label="TEMPLATE")
        validate_expected_inventory_shape(supplied_inventory)
        validate_blank_template_shape(supplied_template)
        _require(
            supplied_inventory == expected_inventory,
            "INVENTORY_EXACT_STATIC_SET_OR_CARDINALITY_MISMATCH",
        )
        _require(
            supplied_template == expected_template,
            "TEMPLATE_EXACT_STATIC_SET_OR_CARDINALITY_MISMATCH",
        )
        _require(
            supplied_template.get("inventory_content_sha256")
            == supplied_inventory.get("content_sha256"),
            "TEMPLATE_INVENTORY_HASH_BINDING_MISMATCH",
        )
        states = _collect_readback_states(supplied_template)
        _require(bool(states), "TEMPLATE_READBACK_STATE_SET_EMPTY")
        _require(
            states <= {UNBOUND_STATE, PROHIBITED_STATE},
            "TEMPLATE_ILLEGAL_READBACK_STATE",
        )
        _require(UNBOUND_STATE in states, "TEMPLATE_UNBOUND_STATE_MISSING")
        return _validation_receipt(
            verdict=INCOMPLETE_VERDICT,
            reason_codes=[
                "OFFLINE_STATIC_CONFORMANCE_PASS",
                "HOST_READBACK_ABSENT",
                "DEPLOYMENT_REMAINS_UNBOUND_BLOCKING",
            ],
            inventory_content_sha256=supplied_inventory["content_sha256"],
            template_content_sha256=supplied_template["content_sha256"],
        )
    except EpistemicBindingError as exc:
        return _validation_receipt(
            verdict=REJECTED_VERDICT,
            reason_codes=exc.reasons,
        )
    except Exception:
        return _validation_receipt(
            verdict=REJECTED_VERDICT,
            reason_codes=["STAGE1A_PREP_VALIDATOR_UNEXPECTED_FAILURE"],
        )


def _collect_readback_states(template: Mapping[str, Any]) -> set[str]:
    states: set[str] = set()
    stack: list[Any] = [template]
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            state = value.get("readback_state")
            if isinstance(state, str):
                states.add(state)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return states


def _open_absolute_directory_fd(path: Path) -> int:
    _require(path.is_absolute(), "DIRECTORY_PATH_MUST_BE_ABSOLUTE")
    _require(".." not in path.parts, "DIRECTORY_PATH_TRAVERSAL_FORBIDDEN")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            if component in {"", "."}:
                continue
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _entry_exists_at(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise EpistemicBindingError(["OUTPUT_ENTRY_STATUS_UNREADABLE"]) from exc


def _ancestor_directory_identities(descriptor: int) -> set[tuple[int, int]]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    current = os.dup(descriptor)
    identities: set[tuple[int, int]] = set()
    try:
        while True:
            current_stat = os.fstat(current)
            current_identity = (current_stat.st_dev, current_stat.st_ino)
            identities.add(current_identity)
            parent = os.open("..", flags, dir_fd=current)
            parent_stat = os.fstat(parent)
            parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
            if parent_identity == current_identity:
                os.close(parent)
                break
            os.close(current)
            current = parent
    finally:
        os.close(current)
    return identities


def _require_output_parent_outside_protected_roots(
    parent_descriptor: int,
    *,
    packet_root: Path,
) -> None:
    output_ancestry = _ancestor_directory_identities(parent_descriptor)
    protected_roots = (
        packet_root,
        Path(__file__).resolve().parents[1],
    )
    for protected_root in protected_roots:
        try:
            protected_descriptor = _open_absolute_directory_fd(protected_root)
        except OSError as exc:
            raise EpistemicBindingError(
                ["PROTECTED_ROOT_IDENTITY_OPEN_FAILED"]
            ) from exc
        try:
            protected_stat = os.fstat(protected_descriptor)
            _require(
                (protected_stat.st_dev, protected_stat.st_ino)
                not in output_ancestry,
                "OUTPUT_PARENT_INSIDE_PROTECTED_ROOT_FORBIDDEN",
            )
        finally:
            os.close(protected_descriptor)


def _create_private_staging_directory(parent_descriptor: int) -> str:
    for _ in range(16):
        name = f".stage1a-prep-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
            return name
        except FileExistsError:
            continue
        except OSError as exc:
            raise EpistemicBindingError(
                ["STAGING_DIRECTORY_CREATE_FAILED"]
            ) from exc
    raise EpistemicBindingError(["STAGING_DIRECTORY_NAME_EXHAUSTED"])


def _read_regular_file_at(
    directory_descriptor: int,
    name: str,
    *,
    max_bytes: int,
) -> bytes:
    return _read_stable_regular_file_at(
        directory_descriptor,
        name,
        max_bytes=max_bytes,
        require_private=True,
    )


def _validate_staging_directory_closure(
    staging_descriptor: int,
    *,
    inventory: Mapping[str, Any],
    template: Mapping[str, Any],
) -> None:
    try:
        names = set(os.listdir(staging_descriptor))
    except OSError as exc:
        raise EpistemicBindingError(["STAGING_DIRECTORY_LIST_FAILED"]) from exc
    expected_names = {
        INVENTORY_RELATIVE_PATH,
        BLANK_TEMPLATE_RELATIVE_PATH,
    }
    _require(names == expected_names, "STAGING_DIRECTORY_CLOSURE_MISMATCH")
    _require(
        _read_regular_file_at(
            staging_descriptor,
            INVENTORY_RELATIVE_PATH,
            max_bytes=MAX_STAGE1A_JSON_BYTES,
        )
        == _canonical_output_bytes(inventory),
        "STAGED_INVENTORY_BYTES_MISMATCH",
    )
    _require(
        _read_regular_file_at(
            staging_descriptor,
            BLANK_TEMPLATE_RELATIVE_PATH,
            max_bytes=MAX_STAGE1A_JSON_BYTES,
        )
        == _canonical_output_bytes(template),
        "STAGED_TEMPLATE_BYTES_MISMATCH",
    )


def _atomic_publish_directory_noreplace_at(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    """Atomically rename within one pinned parent without replacing a target."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source_name)
    destination_bytes = os.fsencode(destination_name)
    ctypes.set_errno(0)
    if sys.platform == "darwin":
        rename_exclusive = getattr(libc, "renameatx_np", None)
        if rename_exclusive is None:
            raise EpistemicBindingError(
                ["ATOMIC_NOREPLACE_DIRECTORY_PUBLISH_UNAVAILABLE"]
            )
        rename_exclusive.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(
            parent_descriptor,
            source_bytes,
            parent_descriptor,
            destination_bytes,
            0x00000034,  # Darwin RENAME_EXCL|NOFOLLOW_ANY|RESOLVE_BENEATH.
        )
    elif sys.platform.startswith("linux"):
        rename_exclusive = getattr(libc, "renameat2", None)
        if rename_exclusive is None:
            raise EpistemicBindingError(
                ["ATOMIC_NOREPLACE_DIRECTORY_PUBLISH_UNAVAILABLE"]
            )
        rename_exclusive.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(
            parent_descriptor,
            source_bytes,
            parent_descriptor,
            destination_bytes,
            0x00000001,  # Linux RENAME_NOREPLACE.
        )
    else:
        raise EpistemicBindingError(
            ["ATOMIC_NOREPLACE_DIRECTORY_PUBLISH_UNAVAILABLE"]
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise EpistemicBindingError(
            ["OUTPUT_ROOT_APPEARED_BEFORE_ATOMIC_PUBLISH"]
        )
    raise EpistemicBindingError(
        ["ATOMIC_NOREPLACE_DIRECTORY_PUBLISH_FAILED"]
    )


def write_stage1a_inventory_bundle(
    *,
    packet_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    _require(output_root.is_absolute(), "OUTPUT_ROOT_MUST_BE_ABSOLUTE")
    _require(
        ".." not in output_root.parts and output_root.name not in {"", ".", ".."},
        "OUTPUT_ROOT_PATH_INVALID",
    )
    inventory = build_expected_inventory(packet_root)
    template = _build_blank_readback_template_from_expected(inventory)
    try:
        parent_descriptor = _open_absolute_directory_fd(output_root.parent)
    except OSError as exc:
        raise EpistemicBindingError(
            ["OUTPUT_PARENT_IDENTITY_OPEN_FAILED"]
        ) from exc
    try:
        parent_before = os.fstat(parent_descriptor)
        _require(
            stat.S_ISDIR(parent_before.st_mode)
            and parent_before.st_uid == os.geteuid()
            and stat.S_IMODE(parent_before.st_mode) & 0o077 == 0,
            "OUTPUT_PARENT_NOT_PRIVATE_SINGLE_WRITER",
        )
        _require_output_parent_outside_protected_roots(
            parent_descriptor,
            packet_root=packet_root,
        )
        _require(
            not _entry_exists_at(parent_descriptor, output_root.name),
            "OUTPUT_ROOT_ALREADY_EXISTS_OR_IS_SYMLINK",
        )
        staging_name = _create_private_staging_directory(parent_descriptor)
        staging_root = output_root.parent / staging_name
        staging_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        staging_descriptor = os.open(
            staging_name,
            staging_flags,
            dir_fd=parent_descriptor,
        )
        try:
            pinned_staging = os.fstat(staging_descriptor)
            _require(
                stat.S_ISDIR(pinned_staging.st_mode)
                and pinned_staging.st_uid == os.geteuid()
                and stat.S_IMODE(pinned_staging.st_mode) & 0o077 == 0,
                "STAGING_DIRECTORY_NOT_PRIVATE",
            )
            pinned_identity = (pinned_staging.st_dev, pinned_staging.st_ino)
            write_workspace_json_once(
                staging_root,
                INVENTORY_RELATIVE_PATH,
                inventory,
            )
            write_workspace_json_once(
                staging_root,
                BLANK_TEMPLATE_RELATIVE_PATH,
                template,
            )
            receipt = validate_stage1a_files(
                packet_root=packet_root,
                inventory_path=staging_root / INVENTORY_RELATIVE_PATH,
                template_path=staging_root / BLANK_TEMPLATE_RELATIVE_PATH,
            )
            _require(
                receipt.get("validation_status") == INCOMPLETE_VERDICT,
                "STAGED_BUNDLE_OFFLINE_VALIDATION_FAILED",
            )
            _validate_staging_directory_closure(
                staging_descriptor,
                inventory=inventory,
                template=template,
            )
            parent_now = os.fstat(parent_descriptor)
            _require(
                (parent_now.st_dev, parent_now.st_ino)
                == (parent_before.st_dev, parent_before.st_ino)
                and parent_now.st_uid == os.geteuid()
                and stat.S_IMODE(parent_now.st_mode) & 0o077 == 0,
                "OUTPUT_PARENT_IDENTITY_CHANGED",
            )
            current_staging = os.stat(
                staging_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            _require(
                stat.S_ISDIR(current_staging.st_mode)
                and (current_staging.st_dev, current_staging.st_ino)
                == pinned_identity,
                "STAGING_DIRECTORY_IDENTITY_CHANGED_BEFORE_PUBLISH",
            )
            _require(
                not _entry_exists_at(parent_descriptor, output_root.name),
                "OUTPUT_ROOT_APPEARED_BEFORE_ATOMIC_PUBLISH",
            )
            os.fsync(staging_descriptor)
            _atomic_publish_directory_noreplace_at(
                parent_descriptor,
                staging_name,
                output_root.name,
            )
            published_output = os.stat(
                output_root.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            _require(
                stat.S_ISDIR(published_output.st_mode)
                and (published_output.st_dev, published_output.st_ino)
                == pinned_identity,
                "PUBLISHED_DIRECTORY_IDENTITY_MISMATCH",
            )
            os.fsync(parent_descriptor)
        finally:
            os.close(staging_descriptor)
    finally:
        os.close(parent_descriptor)
    return receipt


__all__ = [
    "BLANK_TEMPLATE_RELATIVE_PATH",
    "EpistemicBindingError",
    "INCOMPLETE_VERDICT",
    "INVENTORY_RELATIVE_PATH",
    "P0_PACKET_MANIFEST_SHA256",
    "REJECTED_VERDICT",
    "build_blank_readback_template",
    "build_expected_inventory",
    "build_rejected_validation_receipt",
    "load_verified_p0_packet",
    "validate_blank_template_shape",
    "validate_expected_inventory_shape",
    "validate_stage1a_files",
    "write_stage1a_inventory_bundle",
]
