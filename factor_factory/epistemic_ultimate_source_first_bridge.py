from __future__ import annotations

"""Agent-facing Source-First bridge for the Ultimate epistemic advisory route.

The bridge deliberately separates work that requires research judgment from
mechanical RAG configuration.  A research agent must first author a closed,
source-only semantic overlay.  Only after that overlay has compiled through the
Source-First kernel does this module resolve the canonical knowledge indexes,
mint a session-scoped secret, and run the existing candidate kernel.

Nothing in this module is a formal Step1 artifact, a proof input, an OOS read,
or canonical-memory authority.
"""

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factor_factory.epistemic_source_first_kernel_adapter_offline import (
    compile_source_first_kernel_session_candidate,
)
from factor_factory.epistemic_ultimate_shadow import (
    AUTHORITY_EFFECT,
    EXPECTED_REAL_KNOWLEDGE_PATHS,
    OUTPUT_PARENT_NAME,
    _publish_package,
    _secret_absent,
    validate_native_factor_workspace,
)
from factor_factory.research_org.contracts import strict_json_loads
from factor_factory.research_org.rfc8785_canonical import framed_sha256
from scripts.build_factorforge_epistemic_kernel_offline_candidate import (
    build_candidate,
    validate_epistemic_kernel_input_payload,
)


SCHEMA_VERSION = "1.0.0"
OVERLAY_SCHEMA_ID = "factorforge_epistemic_agent_source_first_overlay_v1"
RECEIPT_SCHEMA_ID = "factorforge_epistemic_source_first_advisory_bridge_receipt_v1"
RECEIPT_DOMAIN = "FF_EPISTEMIC_SOURCE_FIRST_ADVISORY_BRIDGE_RECEIPT_V1"
RUN_ID_DOMAIN = "FF_EPISTEMIC_SOURCE_FIRST_ADVISORY_BRIDGE_RUN_ID_V1"
ATTEMPT_ID_DOMAIN = "FF_EPISTEMIC_SOURCE_FIRST_ADVISORY_BRIDGE_ATTEMPT_ID_V1"
ATTEMPT_STATE_DOMAIN = "FF_EPISTEMIC_SOURCE_FIRST_ADVISORY_BRIDGE_ATTEMPT_STATE_V1"
KNOWLEDGE_SNAPSHOT_DOMAIN = (
    "FF_EPISTEMIC_SOURCE_FIRST_ADVISORY_KNOWLEDGE_SNAPSHOT_V1"
)
ATTEMPT_STATE_SCHEMA_ID = "factorforge_epistemic_source_first_attempt_state_v1"
MAX_OVERLAY_BYTES = 8 * 1024 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
INPUT_PARENT_NAME = "candidate_epistemic_shadow_inputs"
CANONICAL_REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAMES = (
    "00_kernel_candidate.json",
    "01_chief_advisory.json",
    "02_shadow_receipt.json",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

FIXED_PHASE_POLICY = {
    "policy_version": "source-first-offline-a0-candidate-v1",
    "phase": "A0",
    "requested_lane_subset": [
        "structural_isomorph",
        "cross_math_analogy",
        "near_miss_failure",
        "direct_counterexample",
    ],
    "top_k_per_lane": 3,
}

SEMANTIC_FIELDS = (
    "source_text",
    "source_lineage",
    "author_claims",
    "analyst_notes",
    "selected_semantic_body",
    "formalization_provenance",
    "pre_a0_predictions",
)
OVERLAY_FIELDS = {
    "schema_id",
    "schema_version",
    "report_id",
    "agent_source_only_attestation",
    *SEMANTIC_FIELDS,
}
ATTESTATION_FIELDS = {
    "attestation_mode",
    "source_understanding_completed_before_retrieval",
    "knowledge_or_case_retrieval_consulted",
    "current_factor_metrics_or_oos_consulted",
    "semantic_fields_authored_by_current_research_agent",
    "independent_pre_retrieval_attestation_present",
}
EXPECTED_ATTESTATION = {
    "attestation_mode": (
        "AGENT_CLAIMED_SOURCE_ONLY_PRE_RETRIEVAL__NOT_INDEPENDENTLY_VERIFIED"
    ),
    "source_understanding_completed_before_retrieval": True,
    "knowledge_or_case_retrieval_consulted": False,
    "current_factor_metrics_or_oos_consulted": False,
    "semantic_fields_authored_by_current_research_agent": True,
    "independent_pre_retrieval_attestation_present": False,
}

BASIC_BINDING_FIELDS = {
    "relative_path",
    "bytes",
    "raw_sha256",
    "device",
    "inode",
    "mtime_ns",
    "link_count",
}
ATTEMPT_BINDING_FIELDS = BASIC_BINDING_FIELDS | {
    "attempt_id",
    "content_sha256",
}
FACTORFORGE_ROOT_BINDING_FIELDS = {
    "resolved_path",
    "device",
    "inode",
    "workspace_relationship",
    "binding_source",
}
ATTEMPT_STATE_CORE_FIELDS = {
    "schema_id",
    "schema_version",
    "attempt_id",
    "report_id",
    "factor_id",
    "research_id",
    "workspace_manifest_raw_sha256",
    "source_first_overlay_raw_sha256",
    "source_first_content_sha256",
    "knowledge_snapshot_content_sha256",
    "session_scope_secret_hex",
    "candidate_only",
    "signed",
    "authority_effect",
}
RECEIPT_CORE_FIELDS = {
    "schema_id",
    "schema_version",
    "artifact_status",
    "run_id",
    "attempt_id",
    "report_id",
    "factor_id",
    "research_id",
    "factorforge_root_binding",
    "workspace_manifest_binding",
    "source_first_overlay_binding",
    "private_attempt_state_binding",
    "source_first_preflight",
    "knowledge_snapshot",
    "kernel_candidate_content_sha256",
    "chief_advisory_raw_sha256",
    "package_artifacts",
    "rag_configuration",
    "ordering_guards",
    "consumer_policy",
    "formal_pipeline_effect",
    "execution_boundary",
    "candidate_only",
    "signed",
    "authority_effect",
}
PACKAGE_ARTIFACT_FIELDS = {"ordinal", "path", "bytes", "raw_sha256"}


class SourceFirstAdvisoryBridgeError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedSourceFirstAdvisoryPackage:
    receipt: dict[str, Any]
    chief_advisory_raw: bytes


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise SourceFirstAdvisoryBridgeError(reason)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _closed(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    _require(set(value) == fields, f"{label}:closed_fields")
    return value


def validate_agent_source_first_overlay(
    value: Any, *, report_id: str
) -> dict[str, Any]:
    overlay = _closed(value, OVERLAY_FIELDS, "source_first_overlay")
    _require(overlay["schema_id"] == OVERLAY_SCHEMA_ID, "source_first_overlay:schema_id")
    _require(
        overlay["schema_version"] == SCHEMA_VERSION,
        "source_first_overlay:schema_version",
    )
    _require(overlay["report_id"] == report_id, "source_first_overlay:report_id")
    attestation = _closed(
        overlay["agent_source_only_attestation"],
        ATTESTATION_FIELDS,
        "source_first_overlay.agent_source_only_attestation",
    )
    _require(
        dict(attestation) == EXPECTED_ATTESTATION,
        "source_first_overlay:source_only_attestation_required",
    )
    source_text = overlay["source_text"]
    _require(
        isinstance(source_text, str) and bool(source_text.strip()),
        "source_first_overlay.source_text:nonempty",
    )
    return dict(overlay)


def _source_inputs(overlay: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_bytes": overlay["source_text"].encode("utf-8"),
        "source_lineage": overlay["source_lineage"],
        "author_claims": overlay["author_claims"],
        "analyst_notes": overlay["analyst_notes"],
        "selected_semantic_body": overlay["selected_semantic_body"],
        "formalization_provenance": overlay["formalization_provenance"],
        "pre_a0_predictions": overlay["pre_a0_predictions"],
        "phase_policy_candidate": dict(FIXED_PHASE_POLICY),
    }


def _canonical_real_knowledge_inputs(repo_root: Path) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    resolved: dict[str, Any] = {}
    for field, relative in EXPECTED_REAL_KNOWLEDGE_PATHS.items():
        candidate = repo / relative
        _require(not candidate.is_symlink(), f"knowledge.{field}:symlink_forbidden")
        path = candidate.resolve(strict=True)
        _require(
            path.is_file() and repo in path.parents,
            f"knowledge.{field}:canonical_regular_file_required",
        )
        metadata = path.stat()
        _require(
            stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
            f"knowledge.{field}:physical_identity",
        )
        resolved[field] = str(path)
    resolved["top_k_per_lane"] = FIXED_PHASE_POLICY["top_k_per_lane"]
    return resolved


def _canonical_knowledge_snapshot(repo_root: Path) -> dict[str, Any]:
    """Bind every file the canonical real-knowledge route may consume."""

    repo = repo_root.resolve(strict=True)
    inputs = _canonical_real_knowledge_inputs(repo)
    paths = [Path(str(inputs[field])) for field in EXPECTED_REAL_KNOWLEDGE_PATHS]
    nodes_root_declared = repo / "knowledge" / "因子工厂" / "graph" / "nodes"
    _require(
        nodes_root_declared.is_dir() and not nodes_root_declared.is_symlink(),
        "knowledge_snapshot.nodes_root:direct_real_directory_required",
    )
    nodes_root = nodes_root_declared.resolve(strict=True)
    _require(
        nodes_root.parent
        == (repo / "knowledge" / "因子工厂" / "graph").resolve(strict=True)
        and nodes_root.stat().st_dev == repo.stat().st_dev
        and not os.path.ismount(nodes_root),
        "knowledge_snapshot.nodes_root:isolation",
    )
    node_names = sorted(os.listdir(nodes_root))
    _require(bool(node_names), "knowledge_snapshot.nodes_root:empty")
    paths.extend(nodes_root / name for name in node_names)
    rows: list[dict[str, Any]] = []
    for ordinal, path in enumerate(paths):
        _require(
            path.is_absolute() and repo in path.parents,
            f"knowledge_snapshot[{ordinal}]:outside_repo",
        )
        raw, metadata = _read_direct_child(
            parent=path.parent,
            name=path.name,
            label=f"knowledge_snapshot[{ordinal}]",
            max_bytes=MAX_PACKAGE_BYTES,
        )
        _require(
            metadata.st_dev == repo.stat().st_dev,
            f"knowledge_snapshot[{ordinal}]:cross_device_forbidden",
        )
        rows.append(
            {
                "ordinal": ordinal,
                "relative_path": path.relative_to(repo).as_posix(),
                "bytes": len(raw),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "files": rows,
        "content_sha256": framed_sha256(KNOWLEDGE_SNAPSHOT_DOMAIN, rows),
    }


def _compile_agent_source_first_overlay(
    overlay_value: Any, *, report_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    overlay = validate_agent_source_first_overlay(overlay_value, report_id=report_id)
    source_inputs = _source_inputs(overlay)
    source_first = compile_source_first_kernel_session_candidate(**source_inputs)
    request_branch = source_first["artifacts"]["a0_request_candidate"]["request_branch"]
    _require(
        request_branch == "A0_HOST_PREISSUANCE_CANDIDATE",
        "source_first_overlay:a0_eligible_formalized_seed_required",
    )
    preflight = {
        "source_first_content_sha256": source_first["content_sha256"],
        "blind_seed_content_sha256": source_first["artifacts"][
            "blind_mechanism_seed"
        ]["content_sha256"],
        "a0_request_candidate_content_sha256": source_first["artifacts"][
            "a0_request_candidate"
        ]["content_sha256"],
        "request_branch": request_branch,
        "source_compiled_before_knowledge_resolution": True,
        "caller_semantic_origin_independently_verified": False,
    }
    return overlay, preflight


def _assemble_agent_managed_kernel_input(
    overlay: Mapping[str, Any],
    *,
    repo_root: Path,
    session_secret: str,
) -> dict[str, Any]:
    real_knowledge_inputs = _canonical_real_knowledge_inputs(repo_root)
    _require(
        re.fullmatch(r"[0-9a-f]{64}", session_secret) is not None,
        "session_secret:exact32_lowercase_hex_required",
    )
    kernel_input = {
        **{name: overlay[name] for name in SEMANTIC_FIELDS},
        "phase_policy_candidate": dict(FIXED_PHASE_POLICY),
        "retrieval_corpus_objects": None,
        "real_knowledge_inputs": real_knowledge_inputs,
        "session_scope_secret_hex": session_secret,
        "diagnosis_inputs": None,
    }
    validate_epistemic_kernel_input_payload(kernel_input)
    return kernel_input


def _build_agent_managed_kernel_input_with_context(
    overlay_value: Any,
    *,
    report_id: str,
    repo_root: Path,
    secret_factory: Callable[[int], str] = secrets.token_hex,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile the blind seed before secret mint or knowledge resolution."""

    # This is the ordering gate.  The pure compiler performs no file, index,
    # secret, environment, data, code, result, or network discovery.  An
    # ineligible source stops here without leaving an attempt state.
    overlay, preflight = _compile_agent_source_first_overlay(
        overlay_value,
        report_id=report_id,
    )
    session_secret = secret_factory(32)
    _require(
        isinstance(session_secret, str),
        "session_secret:string_required",
    )
    kernel_input = _assemble_agent_managed_kernel_input(
        overlay,
        repo_root=repo_root,
        session_secret=session_secret,
    )
    return kernel_input, preflight


def _read_overlay_file(
    *, workspace: Path, overlay_path: Path, report_id: str
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    _require(overlay_path.is_absolute(), "source_first_overlay_path:absolute_required")
    _require(not overlay_path.is_symlink(), "source_first_overlay_path:symlink_forbidden")
    parent = workspace / INPUT_PARENT_NAME
    _require(
        parent.is_dir() and not parent.is_symlink(),
        "source_first_overlay_parent:missing_or_symlink",
    )
    resolved_parent = parent.resolve(strict=True)
    _require(
        resolved_parent.parent == workspace and not os.path.ismount(resolved_parent),
        "source_first_overlay_parent:isolation",
    )
    resolved = overlay_path.resolve(strict=True)
    _require(
        resolved.parent == resolved_parent,
        "source_first_overlay_path:direct_candidate_child_required",
    )
    raw, before = _read_direct_child(
        parent=resolved_parent,
        name=resolved.name,
        label="source_first_overlay",
        max_bytes=MAX_OVERLAY_BYTES,
    )
    payload = strict_json_loads(raw, label="source-first-agent-overlay")
    overlay = validate_agent_source_first_overlay(payload, report_id=report_id)
    binding = {
        "relative_path": str(resolved.relative_to(workspace)),
        "bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "device": str(before.st_dev),
        "inode": str(before.st_ino),
        "mtime_ns": str(before.st_mtime_ns),
        "link_count": before.st_nlink,
    }
    return overlay, raw, binding


def _same_file_snapshot(path: Path, raw: bytes, binding: Mapping[str, Any]) -> bool:
    try:
        current_raw, metadata = _read_direct_child(
            parent=path.parent,
            name=path.name,
            label="bridge_snapshot",
            max_bytes=MAX_PACKAGE_BYTES,
        )
    except Exception:
        return False
    return (
        metadata.st_nlink == 1
        and str(metadata.st_dev) == binding["device"]
        and str(metadata.st_ino) == binding["inode"]
        and str(metadata.st_mtime_ns) == binding["mtime_ns"]
        and metadata.st_size == binding["bytes"]
        and hashlib.sha256(current_raw).hexdigest() == binding["raw_sha256"]
        and current_raw == raw
    )


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mtime_ns,
        value.st_size,
        value.st_nlink,
    )


def _read_direct_child(
    *,
    parent: Path,
    name: str,
    label: str,
    max_bytes: int = MAX_OVERLAY_BYTES,
    exact_mode: int | None = None,
) -> tuple[bytes, os.stat_result]:
    _require(parent.is_absolute(), f"{label}:parent_absolute_required")
    _require(
        re.fullmatch(r"[A-Za-z0-9_.-]{1,192}", name) is not None
        and name not in {".", ".."},
        f"{label}:unsafe_child_name",
    )
    _require(not parent.is_symlink(), f"{label}:parent_symlink_forbidden")
    grandparent = parent.parent.resolve(strict=True)
    grandparent_fd = os.open(
        grandparent,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    parent_fd: int | None = None
    descriptor: int | None = None
    try:
        parent_entry_before = os.stat(
            parent.name,
            dir_fd=grandparent_fd,
            follow_symlinks=False,
        )
        _require(
            stat.S_ISDIR(parent_entry_before.st_mode),
            f"{label}:parent_directory_required",
        )
        parent_fd = os.open(
            parent.name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=grandparent_fd,
        )
        parent_stat = os.fstat(parent_fd)
        _require(
            (parent_stat.st_dev, parent_stat.st_ino)
            == (parent_entry_before.st_dev, parent_entry_before.st_ino),
            f"{label}:parent_entry_identity_mismatch",
        )
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), f"{label}:regular_file_required")
        _require(before.st_nlink == 1, f"{label}:hardlink_forbidden")
        _require(before.st_dev == parent_stat.st_dev, f"{label}:cross_device_forbidden")
        _require(0 < before.st_size <= max_bytes, f"{label}:size")
        if exact_mode is not None:
            _require(
                stat.S_IMODE(before.st_mode) == exact_mode,
                f"{label}:mode_mismatch",
            )
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            _require(bool(chunk), f"{label}:short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        _require(_stat_identity(before) == _stat_identity(after), f"{label}:read_drift")
        parent_after = os.fstat(parent_fd)
        parent_entry_after = os.stat(
            parent.name,
            dir_fd=grandparent_fd,
            follow_symlinks=False,
        )
        _require(
            (parent_after.st_dev, parent_after.st_ino)
            == (parent_entry_after.st_dev, parent_entry_after.st_ino)
            == (parent_stat.st_dev, parent_stat.st_ino),
            f"{label}:parent_entry_replaced_during_read",
        )
        return b"".join(chunks), after
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(grandparent_fd)


def _external_factorforge_root_binding(
    *,
    expected_factorforge_root: Path,
    workspace: Path,
    workspace_binding: Mapping[str, Any],
) -> dict[str, Any]:
    _require(
        expected_factorforge_root.is_absolute(),
        "factorforge_root_binding:absolute_required",
    )
    _require(
        expected_factorforge_root.is_dir() and not expected_factorforge_root.is_symlink(),
        "factorforge_root_binding:real_directory_required",
    )
    resolved = expected_factorforge_root.resolve(strict=True)
    _require(
        expected_factorforge_root == resolved,
        "factorforge_root_binding:canonical_path_required",
    )
    _require(not os.path.ismount(resolved), "factorforge_root_binding:mount_forbidden")
    _require(
        workspace_binding.get("factorforge_root") == str(resolved),
        "factorforge_root_binding:manifest_external_equality",
    )
    _require(
        workspace != resolved and resolved in workspace.parents,
        "factorforge_root_binding:workspace_not_descendant",
    )
    root_stat = resolved.stat()
    workspace_stat = workspace.stat()
    _require(
        root_stat.st_dev == workspace_stat.st_dev,
        "factorforge_root_binding:workspace_cross_device_forbidden",
    )
    return {
        "resolved_path": str(resolved),
        "device": str(root_stat.st_dev),
        "inode": str(root_stat.st_ino),
        "workspace_relationship": "EXACT_EXTERNAL_EQUALITY_AND_DESCENDANT",
        "binding_source": "ULTIMATE_OPERATING_CONTEXT_ARGUMENT",
    }


def _same_root_snapshot(binding: Mapping[str, Any]) -> bool:
    try:
        path = Path(str(binding.get("resolved_path") or ""))
        metadata = path.stat()
    except OSError:
        return False
    return (
        path.is_absolute()
        and path == path.resolve(strict=True)
        and path.is_dir()
        and not path.is_symlink()
        and not os.path.ismount(path)
        and str(metadata.st_dev) == binding.get("device")
        and str(metadata.st_ino) == binding.get("inode")
    )


def _attempt_id(
    *,
    report_id: str,
    workspace_binding: Mapping[str, Any],
    overlay_binding: Mapping[str, Any],
    preflight: Mapping[str, Any],
    knowledge_snapshot: Mapping[str, Any],
) -> str:
    return framed_sha256(
        ATTEMPT_ID_DOMAIN,
        {
            "report_id": report_id,
            "factor_id": workspace_binding["factor_id"],
            "research_id": workspace_binding["research_id"],
            "workspace_manifest_raw_sha256": workspace_binding["raw_sha256"],
            "source_first_overlay_raw_sha256": overlay_binding["raw_sha256"],
            "source_first_content_sha256": preflight[
                "source_first_content_sha256"
            ],
            "knowledge_snapshot_content_sha256": knowledge_snapshot[
                "content_sha256"
            ],
        },
    )[:32]


def _validate_attempt_state(
    value: Any,
    *,
    attempt_id: str,
    report_id: str,
    workspace_binding: Mapping[str, Any],
    overlay_binding: Mapping[str, Any],
    preflight: Mapping[str, Any],
    knowledge_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    state = _closed(
        value,
        ATTEMPT_STATE_CORE_FIELDS | {"content_sha256"},
        "private_attempt_state",
    )
    core = {key: state[key] for key in ATTEMPT_STATE_CORE_FIELDS}
    _require(
        state["content_sha256"] == framed_sha256(ATTEMPT_STATE_DOMAIN, core),
        "private_attempt_state:content_sha256",
    )
    _require(state["schema_id"] == ATTEMPT_STATE_SCHEMA_ID, "private_attempt_state:schema_id")
    _require(state["schema_version"] == SCHEMA_VERSION, "private_attempt_state:schema_version")
    _require(state["attempt_id"] == attempt_id, "private_attempt_state:attempt_id")
    _require(state["report_id"] == report_id, "private_attempt_state:report_id")
    _require(
        state["factor_id"] == workspace_binding["factor_id"]
        and state["research_id"] == workspace_binding["research_id"],
        "private_attempt_state:workspace_identity",
    )
    _require(
        state["workspace_manifest_raw_sha256"] == workspace_binding["raw_sha256"]
        and state["source_first_overlay_raw_sha256"] == overlay_binding["raw_sha256"],
        "private_attempt_state:input_identity",
    )
    _require(
        state["source_first_content_sha256"]
        == preflight["source_first_content_sha256"],
        "private_attempt_state:source_first_identity",
    )
    _require(
        state["knowledge_snapshot_content_sha256"]
        == knowledge_snapshot["content_sha256"],
        "private_attempt_state:knowledge_snapshot_identity",
    )
    _require(
        isinstance(state["session_scope_secret_hex"], str)
        and re.fullmatch(r"[0-9a-f]{64}", state["session_scope_secret_hex"]) is not None,
        "private_attempt_state:session_secret",
    )
    _require(
        state["candidate_only"] is True
        and state["signed"] is False
        and state["authority_effect"] == AUTHORITY_EFFECT,
        "private_attempt_state:authority_boundary",
    )
    return dict(state)


def _load_or_create_attempt_state(
    *,
    workspace: Path,
    report_id: str,
    workspace_binding: Mapping[str, Any],
    overlay_binding: Mapping[str, Any],
    preflight: Mapping[str, Any],
    knowledge_snapshot: Mapping[str, Any],
    secret_factory: Callable[[int], str],
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    attempt_id = _attempt_id(
        report_id=report_id,
        workspace_binding=workspace_binding,
        overlay_binding=overlay_binding,
        preflight=preflight,
        knowledge_snapshot=knowledge_snapshot,
    )
    name = f"bridge_attempt_{attempt_id}.json"
    parent = workspace / INPUT_PARENT_NAME
    workspace_fd = os.open(
        workspace,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    parent_fd: int | None = None
    try:
        parent_entry = os.stat(
            INPUT_PARENT_NAME,
            dir_fd=workspace_fd,
            follow_symlinks=False,
        )
        _require(
            stat.S_ISDIR(parent_entry.st_mode),
            "private_attempt_state:parent_directory_required",
        )
        parent_fd = os.open(
            INPUT_PARENT_NAME,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=workspace_fd,
        )
        _require(
            (os.fstat(parent_fd).st_dev, os.fstat(parent_fd).st_ino)
            == (parent_entry.st_dev, parent_entry.st_ino),
            "private_attempt_state:parent_entry_identity",
        )
        try:
            existing_fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            existing_fd = None
        if existing_fd is not None:
            os.close(existing_fd)
        if existing_fd is None:
            session_secret = secret_factory(32)
            _require(
                isinstance(session_secret, str)
                and re.fullmatch(r"[0-9a-f]{64}", session_secret) is not None,
                "session_secret:exact32_lowercase_hex_required",
            )
            core = {
                "schema_id": ATTEMPT_STATE_SCHEMA_ID,
                "schema_version": SCHEMA_VERSION,
                "attempt_id": attempt_id,
                "report_id": report_id,
                "factor_id": workspace_binding["factor_id"],
                "research_id": workspace_binding["research_id"],
                "workspace_manifest_raw_sha256": workspace_binding["raw_sha256"],
                "source_first_overlay_raw_sha256": overlay_binding["raw_sha256"],
                "source_first_content_sha256": preflight[
                    "source_first_content_sha256"
                ],
                "knowledge_snapshot_content_sha256": knowledge_snapshot[
                    "content_sha256"
                ],
                "session_scope_secret_hex": session_secret,
                "candidate_only": True,
                "signed": False,
                "authority_effect": AUTHORITY_EFFECT,
            }
            payload = {
                **core,
                "content_sha256": framed_sha256(ATTEMPT_STATE_DOMAIN, core),
            }
            raw = _json_bytes(payload)
            try:
                write_fd = os.open(
                    name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                write_fd = None
            if write_fd is not None:
                try:
                    view = memoryview(raw)
                    while view:
                        written = os.write(write_fd, view)
                        _require(written > 0, "private_attempt_state:short_write")
                        view = view[written:]
                    os.fsync(write_fd)
                except Exception:
                    try:
                        os.unlink(name, dir_fd=parent_fd)
                    except OSError:
                        pass
                    raise
                finally:
                    os.close(write_fd)
                os.fsync(parent_fd)
        raw, metadata = _read_direct_child(
            parent=parent,
            name=name,
            label="private_attempt_state",
            exact_mode=0o600,
        )
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(workspace_fd)
    state = _validate_attempt_state(
        strict_json_loads(raw, label="private-attempt-state"),
        attempt_id=attempt_id,
        report_id=report_id,
        workspace_binding=workspace_binding,
        overlay_binding=overlay_binding,
        preflight=preflight,
        knowledge_snapshot=knowledge_snapshot,
    )
    binding = {
        "relative_path": f"{INPUT_PARENT_NAME}/{name}",
        "bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "device": str(metadata.st_dev),
        "inode": str(metadata.st_ino),
        "mtime_ns": str(metadata.st_mtime_ns),
        "link_count": metadata.st_nlink,
        "attempt_id": attempt_id,
        "content_sha256": state["content_sha256"],
    }
    return state, raw, binding


def _same_attempt_snapshot(
    *, workspace: Path, raw: bytes, binding: Mapping[str, Any]
) -> bool:
    try:
        relative = Path(str(binding["relative_path"]))
        if relative.parent.as_posix() != INPUT_PARENT_NAME:
            return False
        current, metadata = _read_direct_child(
            parent=workspace / INPUT_PARENT_NAME,
            name=relative.name,
            label="private_attempt_state_replay",
            exact_mode=0o600,
        )
    except (OSError, KeyError, SourceFirstAdvisoryBridgeError):
        return False
    return (
        _stat_identity(metadata)[0] == int(str(binding["device"]))
        and _stat_identity(metadata)[1] == int(str(binding["inode"]))
        and str(metadata.st_mtime_ns) == binding["mtime_ns"]
        and len(current) == binding["bytes"]
        and hashlib.sha256(current).hexdigest() == binding["raw_sha256"]
        and current == raw
    )


def _run_source_first_advisory_bridge_with_context(
    *,
    workspace: Path,
    overlay_path: Path,
    report_id: str,
    repo_root: Path,
    expected_factorforge_root: Path,
    secret_factory: Callable[[int], str] = secrets.token_hex,
) -> Path:
    """Publish a candidate-only pre-conjecture advisory package."""

    repo = repo_root.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    workspace_manifest, workspace_binding, workspace_manifest_raw = (
        validate_native_factor_workspace(
            workspace=workspace, repo_root=repo
        )
    )
    root_binding = _external_factorforge_root_binding(
        expected_factorforge_root=expected_factorforge_root,
        workspace=workspace,
        workspace_binding=workspace_binding,
    )
    active_report_id = workspace_manifest.get("active_report_id")
    root_report_id = workspace_manifest.get("root_report_id")
    _require(
        report_id in {active_report_id, root_report_id},
        "workspace_manifest:report_id_not_active_or_root",
    )
    overlay, overlay_raw, overlay_binding = _read_overlay_file(
        workspace=workspace,
        overlay_path=overlay_path,
        report_id=report_id,
    )
    overlay, preflight = _compile_agent_source_first_overlay(
        overlay,
        report_id=report_id,
    )
    knowledge_snapshot = _canonical_knowledge_snapshot(repo)
    attempt_state, attempt_raw, attempt_binding = _load_or_create_attempt_state(
        workspace=workspace,
        report_id=report_id,
        workspace_binding=workspace_binding,
        overlay_binding=overlay_binding,
        preflight=preflight,
        knowledge_snapshot=knowledge_snapshot,
        secret_factory=secret_factory,
    )
    session_secret = str(attempt_state["session_scope_secret_hex"])
    kernel_input = _assemble_agent_managed_kernel_input(
        overlay,
        repo_root=repo,
        session_secret=session_secret,
    )
    candidate = build_candidate(kernel_input)
    _require(
        _canonical_knowledge_snapshot(repo) == knowledge_snapshot,
        "bridge:knowledge_snapshot_drift_during_build",
    )
    candidate_bytes = _json_bytes(candidate)
    advisory = candidate["chief_research_advisory"]
    advisory_bytes = _json_bytes(advisory)
    _require(
        _secret_absent([candidate_bytes, advisory_bytes], kernel_input),
        "bridge:secret_persisted_in_candidate_or_advisory",
    )

    run_id = "shadow_" + framed_sha256(
        RUN_ID_DOMAIN,
        {
            "attempt_id": attempt_binding["attempt_id"],
            "report_id": report_id,
            "workspace_manifest_raw_sha256": workspace_binding["raw_sha256"],
            "overlay_raw_sha256": overlay_binding["raw_sha256"],
            "factorforge_root_binding": root_binding,
        },
    )[:32]
    receipt_core = {
        "schema_id": RECEIPT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "SOURCE_FIRST_ADVISORY_COMPLETE__NO_AUTHORITY_EFFECT",
        "run_id": run_id,
        "attempt_id": attempt_binding["attempt_id"],
        "report_id": report_id,
        "factor_id": workspace_binding["factor_id"],
        "research_id": workspace_binding["research_id"],
        "factorforge_root_binding": root_binding,
        "workspace_manifest_binding": workspace_binding,
        "source_first_overlay_binding": overlay_binding,
        "private_attempt_state_binding": attempt_binding,
        "source_first_preflight": preflight,
        "knowledge_snapshot": knowledge_snapshot,
        "kernel_candidate_content_sha256": candidate["content_sha256"],
        "chief_advisory_raw_sha256": hashlib.sha256(advisory_bytes).hexdigest(),
        "package_artifacts": [
            {
                "ordinal": 0,
                "path": "00_kernel_candidate.json",
                "bytes": len(candidate_bytes),
                "raw_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            },
            {
                "ordinal": 1,
                "path": "01_chief_advisory.json",
                "bytes": len(advisory_bytes),
                "raw_sha256": hashlib.sha256(advisory_bytes).hexdigest(),
            },
        ],
        "rag_configuration": {
            "managed_by": "ULTIMATE_AGENT_SOURCE_FIRST_BRIDGE",
            "user_configuration_required": False,
            "canonical_index_relative_paths": {
                field: str(relative)
                for field, relative in EXPECTED_REAL_KNOWLEDGE_PATHS.items()
            },
            "requested_lane_subset": list(
                FIXED_PHASE_POLICY["requested_lane_subset"]
            ),
            "top_k_per_lane": FIXED_PHASE_POLICY["top_k_per_lane"],
            "session_secret_persisted_in_package": False,
        },
        "ordering_guards": {
            "agent_overlay_required_before_bridge": True,
            "source_compiled_before_knowledge_resolution": True,
            "retrieval_executed_only_after_blind_seed": True,
            "retrieval_may_rewrite_source_understanding": False,
            "caller_pre_retrieval_claim_independently_verified": False,
        },
        "consumer_policy": {
            "allowed_consumers": ["RESEARCH_AGENT_ADVISORY_REVIEW"],
            "forbidden_direct_consumers": [
                "FORMAL_STEP1_ARTIFACT",
                "STEP2",
                "STEP3",
                "STEP4",
                "STEP5",
                "STEP6",
                "COUNCIL_DECISION",
            ],
        },
        "formal_pipeline_effect": {
            "formal_command_contract_changed": False,
            "formal_proof_eligibility_contributor": False,
            "factor_verdict_contributor": False,
            "operating_contract_delta_activated": True,
        },
        "execution_boundary": {
            "formal_artifacts_written": False,
            "official_registry_written": False,
            "canonical_memory_or_oos_accessed": False,
            "diagnostic_tests_executed": False,
            "promotion_or_qualification_performed": False,
            "network_access_performed": False,
        },
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    receipt = {
        **receipt_core,
        "content_sha256": framed_sha256(RECEIPT_DOMAIN, receipt_core),
    }
    receipt_bytes = _json_bytes(receipt)
    _require(
        _secret_absent([candidate_bytes, advisory_bytes, receipt_bytes], kernel_input),
        "bridge:secret_persisted_in_package",
    )

    overlay_resolved = overlay_path.resolve(strict=True)

    def replay_inputs() -> None:
        _require(
            _same_file_snapshot(overlay_resolved, overlay_raw, overlay_binding),
            "bridge:overlay_snapshot_drift",
        )
        current_manifest = workspace / workspace_binding["relative_path"]
        _require(
            _same_file_snapshot(
                current_manifest, workspace_manifest_raw, workspace_binding
            ),
            "bridge:workspace_manifest_snapshot_drift",
        )
        _require(
            _same_attempt_snapshot(
                workspace=workspace,
                raw=attempt_raw,
                binding=attempt_binding,
            ),
            "bridge:private_attempt_state_snapshot_drift",
        )
        _require(_same_root_snapshot(root_binding), "bridge:factorforge_root_drift")
        _require(
            _canonical_knowledge_snapshot(repo) == knowledge_snapshot,
            "bridge:knowledge_snapshot_drift",
        )

    receipt_path = _publish_package(
        workspace=workspace,
        run_id=run_id,
        payloads={
            "00_kernel_candidate.json": candidate_bytes,
            "01_chief_advisory.json": advisory_bytes,
            "02_shadow_receipt.json": receipt_bytes,
        },
        before_receipt=replay_inputs,
        after_receipt=replay_inputs,
        expected_workspace_device=workspace_binding["workspace_device"],
        expected_workspace_inode=workspace_binding["workspace_inode"],
    )
    _validate_source_first_advisory_package_with_context(
        receipt_path=receipt_path,
        repo_root=repo,
        expected_factorforge_root=expected_factorforge_root,
    )
    return receipt_path


def _binding_matches(
    *, raw: bytes, metadata: os.stat_result, binding: Mapping[str, Any]
) -> bool:
    return (
        set(binding) >= BASIC_BINDING_FIELDS
        and binding.get("bytes") == len(raw)
        and binding.get("raw_sha256") == hashlib.sha256(raw).hexdigest()
        and binding.get("device") == str(metadata.st_dev)
        and binding.get("inode") == str(metadata.st_ino)
        and binding.get("mtime_ns") == str(metadata.st_mtime_ns)
        and binding.get("link_count") == metadata.st_nlink == 1
    )


def _validate_source_first_advisory_package_with_context(
    *,
    receipt_path: Path,
    repo_root: Path,
    expected_factorforge_root: Path,
) -> ValidatedSourceFirstAdvisoryPackage:
    """Replay the exact3 package and all live Source-First input bindings."""

    _require(receipt_path.is_absolute(), "receipt:absolute_path_required")
    _require(receipt_path.name == PACKAGE_NAMES[2], "receipt:filename")
    _require(not receipt_path.is_symlink(), "receipt:symlink_forbidden")
    resolved_receipt = receipt_path.resolve(strict=True)
    _require(receipt_path == resolved_receipt, "receipt:canonical_path_required")
    run_root = resolved_receipt.parent
    output_root = run_root.parent
    workspace = output_root.parent.resolve(strict=True)
    _require(output_root.name == OUTPUT_PARENT_NAME, "receipt:output_parent")
    _require(
        re.fullmatch(r"shadow_[0-9a-f]{32}", run_root.name) is not None,
        "receipt:run_id_path",
    )
    _require(
        not output_root.is_symlink()
        and not run_root.is_symlink()
        and not os.path.ismount(output_root)
        and not os.path.ismount(run_root),
        "receipt:package_root_isolation",
    )
    repo = repo_root.resolve(strict=True)
    workspace_manifest, workspace_binding, workspace_manifest_raw = (
        validate_native_factor_workspace(workspace=workspace, repo_root=repo)
    )
    root_binding = _external_factorforge_root_binding(
        expected_factorforge_root=expected_factorforge_root,
        workspace=workspace,
        workspace_binding=workspace_binding,
    )
    _require(_same_root_snapshot(root_binding), "receipt:factorforge_root_drift")

    workspace_fd = os.open(
        workspace,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    output_fd: int | None = None
    run_fd: int | None = None
    try:
        workspace_stat = os.fstat(workspace_fd)
        output_fd = os.open(
            OUTPUT_PARENT_NAME,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=workspace_fd,
        )
        output_stat = os.fstat(output_fd)
        _require(
            output_stat.st_dev == workspace_stat.st_dev,
            "receipt:output_root_cross_device_forbidden",
        )
        run_fd = os.open(
            run_root.name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=output_fd,
        )
        run_stat = os.fstat(run_fd)
        _require(
            run_stat.st_dev == workspace_stat.st_dev,
            "receipt:run_root_cross_device_forbidden",
        )
        _require(
            sorted(os.listdir(run_fd)) == sorted(PACKAGE_NAMES),
            "receipt:exact3_closure",
        )
        package_raw: dict[str, bytes] = {}
        package_stats: dict[str, os.stat_result] = {}
        for name in PACKAGE_NAMES:
            raw, metadata = _read_direct_child(
                parent=run_root,
                name=name,
                label=f"receipt.package.{name}",
                max_bytes=MAX_PACKAGE_BYTES,
            )
            package_raw[name] = raw
            package_stats[name] = metadata
        current_run_stat = os.stat(
            run_root.name,
            dir_fd=output_fd,
            follow_symlinks=False,
        )
        _require(
            (current_run_stat.st_dev, current_run_stat.st_ino)
            == (run_stat.st_dev, run_stat.st_ino),
            "receipt:run_root_identity_drift",
        )
        _require(
            sorted(os.listdir(run_fd)) == sorted(PACKAGE_NAMES),
            "receipt:exact3_closure_drift",
        )
    finally:
        if run_fd is not None:
            os.close(run_fd)
        if output_fd is not None:
            os.close(output_fd)
        os.close(workspace_fd)

    receipt_raw = package_raw[PACKAGE_NAMES[2]]
    receipt_value = strict_json_loads(receipt_raw, label="source-first-advisory-receipt")
    receipt = _closed(
        receipt_value,
        RECEIPT_CORE_FIELDS | {"content_sha256"},
        "receipt",
    )
    core = {key: receipt[key] for key in RECEIPT_CORE_FIELDS}
    _require(
        receipt["content_sha256"] == framed_sha256(RECEIPT_DOMAIN, core),
        "receipt:content_sha256",
    )
    _require(receipt["schema_id"] == RECEIPT_SCHEMA_ID, "receipt:schema_id")
    _require(receipt["schema_version"] == SCHEMA_VERSION, "receipt:schema_version")
    _require(receipt["run_id"] == run_root.name, "receipt:run_id")
    _require(
        receipt["artifact_status"]
        == "SOURCE_FIRST_ADVISORY_COMPLETE__NO_AUTHORITY_EFFECT",
        "receipt:artifact_status",
    )
    _require(
        receipt["candidate_only"] is True
        and receipt["signed"] is False
        and receipt["authority_effect"] == AUTHORITY_EFFECT,
        "receipt:authority_boundary",
    )
    _require(
        receipt["factorforge_root_binding"] == root_binding,
        "receipt:factorforge_root_binding_replay",
    )
    _require(
        receipt["workspace_manifest_binding"] == workspace_binding,
        "receipt:workspace_manifest_binding_replay",
    )
    manifest_path = workspace / str(workspace_binding["relative_path"])
    _require(
        _same_file_snapshot(
            manifest_path,
            workspace_manifest_raw,
            workspace_binding,
        ),
        "receipt:workspace_manifest_snapshot_replay",
    )
    _require(
        receipt["factor_id"] == workspace_binding["factor_id"]
        and receipt["research_id"] == workspace_binding["research_id"],
        "receipt:workspace_identity",
    )
    report_id = receipt["report_id"]
    _require(
        isinstance(report_id, str)
        and report_id in {
            workspace_manifest.get("active_report_id"),
            workspace_manifest.get("root_report_id"),
        },
        "receipt:report_id",
    )

    overlay_binding = _closed(
        receipt["source_first_overlay_binding"],
        BASIC_BINDING_FIELDS,
        "receipt.source_first_overlay_binding",
    )
    overlay_relative = Path(str(overlay_binding["relative_path"]))
    _require(
        not overlay_relative.is_absolute()
        and overlay_relative.parent.as_posix() == INPUT_PARENT_NAME
        and overlay_relative.name not in {"", ".", ".."},
        "receipt:overlay_relative_path",
    )
    overlay, overlay_raw, current_overlay_binding = _read_overlay_file(
        workspace=workspace,
        overlay_path=(workspace / overlay_relative).resolve(strict=True),
        report_id=report_id,
    )
    _require(
        dict(overlay_binding) == current_overlay_binding,
        "receipt:overlay_binding_replay",
    )
    overlay, preflight = _compile_agent_source_first_overlay(
        overlay,
        report_id=str(report_id),
    )
    knowledge_snapshot = _canonical_knowledge_snapshot(repo)
    _require(
        receipt["knowledge_snapshot"] == knowledge_snapshot,
        "receipt:knowledge_snapshot_replay",
    )
    expected_attempt_id = _attempt_id(
        report_id=str(report_id),
        workspace_binding=workspace_binding,
        overlay_binding=overlay_binding,
        preflight=preflight,
        knowledge_snapshot=knowledge_snapshot,
    )
    _require(
        receipt["attempt_id"] == expected_attempt_id,
        "receipt:attempt_id_derivation",
    )

    attempt_binding = _closed(
        receipt["private_attempt_state_binding"],
        ATTEMPT_BINDING_FIELDS,
        "receipt.private_attempt_state_binding",
    )
    attempt_relative = Path(str(attempt_binding["relative_path"]))
    _require(
        not attempt_relative.is_absolute()
        and attempt_relative.parent.as_posix() == INPUT_PARENT_NAME
        and attempt_relative.name
        == f"bridge_attempt_{receipt['attempt_id']}.json",
        "receipt:attempt_relative_path",
    )
    attempt_raw, attempt_stat = _read_direct_child(
        parent=workspace / INPUT_PARENT_NAME,
        name=attempt_relative.name,
        label="receipt.private_attempt_state",
        exact_mode=0o600,
    )
    _require(
        _binding_matches(raw=attempt_raw, metadata=attempt_stat, binding=attempt_binding),
        "receipt:attempt_binding_replay",
    )
    _require(
        attempt_binding["attempt_id"] == receipt["attempt_id"],
        "receipt:attempt_id_binding",
    )
    attempt_state = _validate_attempt_state(
        strict_json_loads(attempt_raw, label="receipt-private-attempt-state"),
        attempt_id=str(receipt["attempt_id"]),
        report_id=str(report_id),
        workspace_binding=workspace_binding,
        overlay_binding=overlay_binding,
        preflight=preflight,
        knowledge_snapshot=knowledge_snapshot,
    )
    _require(
        attempt_state["content_sha256"] == attempt_binding["content_sha256"],
        "receipt:attempt_content_binding",
    )

    session_secret = str(attempt_state["session_scope_secret_hex"])
    kernel_input = _assemble_agent_managed_kernel_input(
        overlay,
        repo_root=repo,
        session_secret=session_secret,
    )
    _require(
        receipt["source_first_preflight"] == preflight,
        "receipt:source_first_preflight_replay",
    )
    candidate = build_candidate(kernel_input)
    _require(
        _canonical_knowledge_snapshot(repo) == knowledge_snapshot,
        "receipt:knowledge_snapshot_drift_during_rebuild",
    )
    candidate_raw = _json_bytes(candidate)
    advisory = candidate["chief_research_advisory"]
    advisory_raw = _json_bytes(advisory)
    _require(
        package_raw[PACKAGE_NAMES[0]] == candidate_raw,
        "receipt:candidate_rebuild_mismatch",
    )
    _require(
        package_raw[PACKAGE_NAMES[1]] == advisory_raw,
        "receipt:advisory_rebuild_mismatch",
    )
    _require(
        receipt["kernel_candidate_content_sha256"] == candidate["content_sha256"],
        "receipt:candidate_content_identity",
    )
    _require(
        receipt["chief_advisory_raw_sha256"]
        == hashlib.sha256(advisory_raw).hexdigest(),
        "receipt:advisory_raw_identity",
    )
    package_rows = receipt["package_artifacts"]
    _require(
        isinstance(package_rows, list) and len(package_rows) == 2,
        "receipt:package_exact2",
    )
    for ordinal, name in enumerate(PACKAGE_NAMES[:2]):
        row = _closed(
            package_rows[ordinal],
            PACKAGE_ARTIFACT_FIELDS,
            f"receipt.package_artifacts[{ordinal}]",
        )
        raw = package_raw[name]
        _require(
            row
            == {
                "ordinal": ordinal,
                "path": name,
                "bytes": len(raw),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
            },
            f"receipt:package_artifact_{ordinal}",
        )
    _require(
        all(
            package_stats[name].st_nlink == 1
            and package_stats[name].st_dev == workspace.stat().st_dev
            for name in PACKAGE_NAMES
        ),
        "receipt:package_physical_identity",
    )
    expected_run_id = "shadow_" + framed_sha256(
        RUN_ID_DOMAIN,
        {
            "attempt_id": receipt["attempt_id"],
            "report_id": report_id,
            "workspace_manifest_raw_sha256": workspace_binding["raw_sha256"],
            "overlay_raw_sha256": overlay_binding["raw_sha256"],
            "factorforge_root_binding": root_binding,
        },
    )[:32]
    _require(receipt["run_id"] == expected_run_id, "receipt:run_id_replay")
    _require(
        receipt["execution_boundary"]
        == {
            "formal_artifacts_written": False,
            "official_registry_written": False,
            "canonical_memory_or_oos_accessed": False,
            "diagnostic_tests_executed": False,
            "promotion_or_qualification_performed": False,
            "network_access_performed": False,
        },
        "receipt:execution_boundary",
    )
    _require(
        receipt["rag_configuration"]
        == {
            "managed_by": "ULTIMATE_AGENT_SOURCE_FIRST_BRIDGE",
            "user_configuration_required": False,
            "canonical_index_relative_paths": {
                field: str(relative)
                for field, relative in EXPECTED_REAL_KNOWLEDGE_PATHS.items()
            },
            "requested_lane_subset": list(FIXED_PHASE_POLICY["requested_lane_subset"]),
            "top_k_per_lane": FIXED_PHASE_POLICY["top_k_per_lane"],
            "session_secret_persisted_in_package": False,
        },
        "receipt:rag_configuration",
    )
    _require(
        receipt["ordering_guards"]
        == {
            "agent_overlay_required_before_bridge": True,
            "source_compiled_before_knowledge_resolution": True,
            "retrieval_executed_only_after_blind_seed": True,
            "retrieval_may_rewrite_source_understanding": False,
            "caller_pre_retrieval_claim_independently_verified": False,
        },
        "receipt:ordering_guards",
    )
    _require(
        receipt["consumer_policy"]
        == {
            "allowed_consumers": ["RESEARCH_AGENT_ADVISORY_REVIEW"],
            "forbidden_direct_consumers": [
                "FORMAL_STEP1_ARTIFACT",
                "STEP2",
                "STEP3",
                "STEP4",
                "STEP5",
                "STEP6",
                "COUNCIL_DECISION",
            ],
        },
        "receipt:consumer_policy",
    )
    _require(
        receipt["formal_pipeline_effect"]
        == {
            "formal_command_contract_changed": False,
            "formal_proof_eligibility_contributor": False,
            "factor_verdict_contributor": False,
            "operating_contract_delta_activated": True,
        },
        "receipt:formal_pipeline_effect",
    )
    _require(
        _secret_absent([package_raw[name] for name in PACKAGE_NAMES], kernel_input),
        "receipt:session_secret_persisted_in_package",
    )
    return ValidatedSourceFirstAdvisoryPackage(
        receipt=dict(receipt),
        chief_advisory_raw=advisory_raw,
    )


def run_source_first_advisory_bridge(
    *,
    workspace: Path,
    overlay_path: Path,
    report_id: str,
) -> Path:
    """Run the sole operating bridge under this installed repository root."""

    return _run_source_first_advisory_bridge_with_context(
        workspace=workspace,
        overlay_path=overlay_path,
        report_id=report_id,
        repo_root=CANONICAL_REPO_ROOT,
        expected_factorforge_root=CANONICAL_REPO_ROOT,
        secret_factory=secrets.token_hex,
    )


def validate_source_first_advisory_package(
    *, receipt_path: Path
) -> ValidatedSourceFirstAdvisoryPackage:
    """Validate and return bytes under the same protected operating root."""

    return _validate_source_first_advisory_package_with_context(
        receipt_path=receipt_path,
        repo_root=CANONICAL_REPO_ROOT,
        expected_factorforge_root=CANONICAL_REPO_ROOT,
    )


def run_and_validate_source_first_advisory(
    *, workspace: Path, overlay_path: Path, report_id: str
) -> ValidatedSourceFirstAdvisoryPackage:
    """Complete the agent's intake handoff without reopening advisory content.

    This composes the existing protected public APIs; it adds no research
    semantics, authority, or formal-step execution. Validation failures must
    propagate, never fall back to consuming the published file by path.
    """

    receipt_path = run_source_first_advisory_bridge(
        workspace=workspace, overlay_path=overlay_path, report_id=report_id
    )
    return validate_source_first_advisory_package(receipt_path=receipt_path)


__all__ = [
    "ATTEMPT_STATE_SCHEMA_ID",
    "EXPECTED_ATTESTATION",
    "FIXED_PHASE_POLICY",
    "OVERLAY_SCHEMA_ID",
    "RECEIPT_SCHEMA_ID",
    "SourceFirstAdvisoryBridgeError",
    "ValidatedSourceFirstAdvisoryPackage",
    "run_and_validate_source_first_advisory",
    "run_source_first_advisory_bridge",
    "validate_agent_source_first_overlay",
    "validate_source_first_advisory_package",
]
