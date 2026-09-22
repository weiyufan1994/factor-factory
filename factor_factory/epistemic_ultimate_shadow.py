from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from factor_factory.research_org.contracts import strict_json_loads
from factor_factory.research_org.rfc8785_canonical import framed_sha256
from factor_factory.research_workspace import (
    REQUIRED_WORKSPACE_DIRS,
    default_workspace_root,
    validate_workspace_manifest,
    workspace_manifest_path,
)
from factor_factory.epistemic_kernel_composition_offline import (
    compose_epistemic_kernel_candidate,
)
from scripts.build_factorforge_epistemic_kernel_offline_candidate import (
    build_candidate,
    epistemic_kernel_composition_inputs,
    validate_epistemic_kernel_input_payload,
)


SCHEMA_VERSION = "1.0.0"
REQUEST_SCHEMA_ID = "factorforge_ultimate_epistemic_shadow_request_v1"
RESULT_SCHEMA_ID = "factorforge_ultimate_epistemic_shadow_result_v1"
FORMAL_ARTIFACT_SNAPSHOT_SCHEMA_ID = (
    "factorforge_ultimate_epistemic_preproof_artifact_snapshot_v1"
)
RESULT_DOMAIN = "FF_ULTIMATE_EPISTEMIC_SHADOW_RESULT_V1"
FORMAL_ARTIFACT_SNAPSHOT_DOMAIN = (
    "FF_ULTIMATE_EPISTEMIC_PREPROOF_ARTIFACT_SNAPSHOT_V1"
)
ARTIFACT_BINDING_DOMAIN = "FF_ULTIMATE_EPISTEMIC_SHADOW_ARTIFACT_BINDINGS_V1"
DIAGNOSIS_INPUT_BINDING_DOMAIN = (
    "FF_ULTIMATE_EPISTEMIC_SHADOW_DIAGNOSIS_INPUT_BINDINGS_V1"
)
RUN_ID_DOMAIN = "FF_ULTIMATE_EPISTEMIC_SHADOW_RUN_ID_V1"

HOOK_STEP1 = "POST_STEP1_PRE_STEP2_SOURCE_FIRST_A0_SHADOW"
HOOK_FAILURE = "POST_STEP5_FAILURE_DIAGNOSIS_SHADOW"
HOOKS = frozenset({HOOK_STEP1, HOOK_FAILURE})

AUTHORITY_EFFECT = "NONE"
MAX_JSON_BYTES = 32 * 1024 * 1024
REQUEST_PARENT_NAME = "candidate_epistemic_shadow_requests"
DIAGNOSIS_INPUT_PARENT_NAME = "candidate_epistemic_shadow_diagnosis_inputs"
OUTPUT_PARENT_NAME = "candidate_epistemic_shadow"

REQUEST_FIELDS = {
    "schema_id",
    "schema_version",
    "report_id",
    "hook",
    "kernel_input_candidate",
    "derivation_ledger",
    "diagnosis_target_scope",
    "isolation_policy",
    "candidate_only",
    "signed",
    "authority_effect",
}
RESULT_CORE_FIELDS = {
    "schema_id",
    "schema_version",
    "artifact_status",
    "shadow_run_id",
    "report_id",
    "factor_id",
    "research_id",
    "hook",
    "request_binding",
    "runtime_manifest_binding",
    "workspace_manifest_binding",
    "official_artifact_bindings",
    "official_artifact_binding_commitment",
    "formal_proof_binding",
    "formal_artifact_snapshot",
    "diagnosis_input_root_binding",
    "diagnosis_input_bindings",
    "diagnosis_input_binding_commitment",
    "derivation_ledger_validation",
    "diagnosis_target_scope",
    "kernel_candidate_content_sha256",
    "chief_advisory_raw_sha256",
    "package_artifacts",
    "execution_boundary",
    "consumer_policy",
    "formal_pipeline_effect",
    "candidate_only",
    "signed",
    "authority_effect",
}
ISOLATION_POLICY = {
    "official_artifact_mutation_allowed": False,
    "official_registry_write_allowed": False,
    "step2_6_consumer_allowed": False,
    "canonical_or_oos_access_allowed": False,
    "promotion_or_qualification_allowed": False,
}
KERNEL_INPUT_NAMES = (
    "source_text",
    "source_lineage",
    "author_claims",
    "analyst_notes",
    "selected_semantic_body",
    "formalization_provenance",
    "pre_a0_predictions",
    "phase_policy_candidate",
)
DERIVATION_FIELDS = {
    "ordinal",
    "target_pointer",
    "derivation_class",
    "source_artifact_role",
    "source_pointer",
    "source_value_sha256",
}
DERIVATION_CLASSES = frozenset(
    {
        "DIRECT_COPY",
        "AGENT_PARAPHRASE",
        "PRE_RETRIEVAL_ANALYST_INFERENCE",
        "CALLER_SUPPLIED_PRE_RETRIEVAL_CANDIDATE",
        "NEW_ASSUMPTION",
        "UNRESOLVED",
    }
)
DIAGNOSIS_SCOPE_FIELDS = {
    "target_report_id",
    "target_factor_id",
    "linkage_status",
}

OFFICIAL_ARTIFACTS = {
    HOOK_STEP1: (
        ("ALPHA_IDEA_MASTER", "alpha_idea_master"),
    ),
    HOOK_FAILURE: (
        ("ALPHA_IDEA_MASTER", "alpha_idea_master"),
        ("FACTOR_SPEC_MASTER", "factor_spec_master"),
        ("FACTOR_RUN_MASTER", "factor_run_master"),
        ("FACTOR_EVALUATION", "factor_evaluation"),
        ("FACTOR_CASE_MASTER", "factor_case_master"),
        ("HANDOFF_TO_STEP6", "handoff_to_step6"),
    ),
}

CANONICAL_OBJECT_PATHS = {
    "ALPHA_IDEA_MASTER": ("alpha_idea_master", "alpha_idea_master"),
    "FACTOR_SPEC_MASTER": ("factor_spec_master", "factor_spec_master"),
    "FACTOR_RUN_MASTER": ("factor_run_master", "factor_run_master"),
    "FACTOR_EVALUATION": ("validation", "factor_evaluation"),
    "FACTOR_CASE_MASTER": ("factor_case_master", "factor_case_master"),
    "HANDOFF_TO_STEP6": ("handoff", "handoff_to_step6"),
}
SOURCE_PRODUCER_BY_TYPE = {
    "pdf_report": "step2_pdf_report",
    "paper_canonical_formula": "step12_canonical_formula_intake",
    "natural_language_hypothesis": "step12_hypothesis_intake",
}
DOWNSTREAM_ROLE_PRODUCERS = {
    "FACTOR_RUN_MASTER": "step4",
    "FACTOR_EVALUATION": "step5",
    "FACTOR_CASE_MASTER": "step5",
    "HANDOFF_TO_STEP6": "step5",
}
DOWNSTREAM_ARTIFACT_ROLES = {
    "FACTOR_SPEC_MASTER": "factor_spec_master",
    "FACTOR_RUN_MASTER": "factor_run_master",
    "FACTOR_EVALUATION": "factor_evaluation",
    "FACTOR_CASE_MASTER": "factor_case_master",
    "HANDOFF_TO_STEP6": "handoff_to_step6",
}
FAILURE_IDENTITY_COHERENCE_FIELDS = (
    "report_id",
    "factor_id",
    "source_type",
    "implementation_mode",
    "contract_version",
    "upstream_producer",
    "formula_hash",
    "code_contract_hash",
    "custom_block_hash",
    "hybrid_hash",
    "spec_hash",
    "branch_id",
)
FAILURE_CODE_COHERENCE_ROLES = (
    "FACTOR_RUN_MASTER",
    "FACTOR_EVALUATION",
    "FACTOR_CASE_MASTER",
    "HANDOFF_TO_STEP6",
)
DIAGNOSIS_PATH_ROLES = (
    ("STAGE2_MANIFEST", "stage2_manifest_path", "stage2_manifest_raw_bytes"),
    ("DIAGNOSIS_FIXTURE", "fixture_json_path", "fixture_raw_bytes"),
    (
        "ASSERTION_DEPENDENCY_DAG",
        "assertion_dependency_json_path",
        "assertion_dependency_raw_bytes",
    ),
)

EXPECTED_REAL_KNOWLEDGE_PATHS = {
    "node_index_path": Path("knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl"),
    "edge_index_path": Path("knowledge/因子工厂/graph/factor_knowledge_edges.jsonl"),
    "taxonomy_path": Path("knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json"),
}

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PROTECTED_FACTORFORGE_ROOT_COMPONENTS = frozenset(
    {"canonical", "deploy", "deployment", "host", "oos", "runtime", "skill", "skills"}
)
FORMAL_ARTIFACT_SNAPSHOT_FIELDS = {
    "schema_id",
    "schema_version",
    "report_id",
    "factor_id",
    "research_id",
    "hook",
    "official_artifact_bindings",
    "official_artifact_binding_commitment",
    "candidate_only",
    "signed",
    "authority_effect",
    "content_sha256",
}
BASIC_FILE_BINDING_FIELDS = {
    "relative_path",
    "bytes",
    "raw_sha256",
    "device",
    "inode",
    "mtime_ns",
    "link_count",
}
WORKSPACE_MANIFEST_BINDING_FIELDS = BASIC_FILE_BINDING_FIELDS | {
    "factor_id",
    "research_id",
    "factorforge_root",
    "workspace_root",
    "workspace_device",
    "workspace_inode",
}
OFFICIAL_ARTIFACT_BINDING_FIELDS = BASIC_FILE_BINDING_FIELDS | {
    "ordinal",
    "artifact_role",
    "report_id",
    "contract_version",
    "producer",
    "source_type",
    "validated_identity",
}
DIAGNOSIS_INPUT_BINDING_FIELDS = BASIC_FILE_BINDING_FIELDS | {
    "ordinal",
    "input_role",
    "candidate_root_only",
}
FORMAL_PROOF_BINDING_FIELDS = BASIC_FILE_BINDING_FIELDS | {
    "status",
    "formal_proof_eligible",
    "current_formal_authority_verified",
    "requested_steps",
    "required_command_names",
    "oos_used",
}
DIAGNOSIS_ROOT_BINDING_FIELDS = {"relative_path", "device", "inode"}


class EpistemicUltimateShadowError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise EpistemicUltimateShadowError(reason)


def _closed(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    _require(set(value) == fields, f"{label}:closed_fields")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    _require(
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)),
        f"{label}:array_required",
    )
    return value


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _canonical_value_sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _read_regular_file(path: Path, *, label: str) -> tuple[bytes, os.stat_result]:
    _require(path.is_absolute(), f"{label}:absolute_path_required")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        _require(stat.S_ISREG(metadata.st_mode), f"{label}:regular_file_required")
        _require(0 < metadata.st_size <= MAX_JSON_BYTES, f"{label}:size")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            _require(bool(chunk), f"{label}:short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        _require(len(raw) == metadata.st_size, f"{label}:size_drift")
        return raw, metadata
    finally:
        os.close(descriptor)


def _parse_json(raw: bytes, *, label: str) -> dict[str, Any]:
    payload = strict_json_loads(raw, label=label)
    _require(isinstance(payload, dict), f"{label}:object_required")
    return payload


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _resolve_inside(path: Path, root: Path, *, label: str) -> Path:
    _require(path.is_absolute(), f"{label}:absolute_path_required")
    _require(not path.is_symlink(), f"{label}:symlink_forbidden")
    resolved = path.resolve(strict=True)
    _require(_is_within(resolved, root), f"{label}:outside_workspace")
    return resolved


def _path_component_tokens(path: Path) -> set[str]:
    return {
        token
        for part in path.parts
        for token in re.split(r"[^a-z0-9]+", part.casefold())
        if token
    }


def validate_native_factor_workspace(
    *,
    workspace: Path,
    repo_root: Path,
    expected_factor_id: str | None = None,
    expected_research_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Replay the repository's native factor-workspace identity contract.

    A runtime manifest alone is self-asserted.  Candidate writes are therefore
    admitted only under the exact ``factor_research/<factor>/<research>`` root
    bound by the native workspace manifest and its restrictive write policy.
    """

    _require(workspace.is_absolute(), "workspace:absolute_path_required")
    _require(
        workspace.is_dir() and not workspace.is_symlink(),
        "workspace:real_directory_required",
    )
    resolved_workspace = workspace.resolve(strict=True)
    _require(not os.path.ismount(resolved_workspace), "workspace:mount_forbidden")
    manifest_path = workspace_manifest_path(resolved_workspace)
    _require(
        manifest_path.parent == resolved_workspace and not manifest_path.is_symlink(),
        "workspace_manifest:direct_nonsymlink_child_required",
    )
    raw, metadata = _read_regular_file(manifest_path, label="workspace_manifest")
    _require(metadata.st_nlink == 1, "workspace_manifest:hardlink_forbidden")
    workspace_stat = resolved_workspace.stat()
    _require(
        metadata.st_dev == workspace_stat.st_dev,
        "workspace_manifest:cross_device_forbidden",
    )
    manifest = _parse_json(raw, label="workspace_manifest")
    failures = validate_workspace_manifest(manifest)
    _require(not failures, "workspace_manifest:native_validation:" + "|".join(failures))
    factor_id = manifest.get("factor_id")
    research_id = manifest.get("research_id")
    _require(_nonempty(factor_id), "workspace_manifest:factor_id")
    _require(_nonempty(research_id), "workspace_manifest:research_id")
    if expected_factor_id is not None:
        _require(factor_id == expected_factor_id, "workspace_manifest:factor_id_mismatch")
    if expected_research_id is not None:
        _require(
            research_id == expected_research_id,
            "workspace_manifest:research_id_mismatch",
        )
    manifest_repo = Path(str(manifest.get("repo_root") or "")).expanduser()
    _require(manifest_repo.is_absolute(), "workspace_manifest:repo_root_absolute")
    _require(
        manifest_repo.resolve(strict=True) == repo_root.resolve(strict=True),
        "workspace_manifest:repo_root_mismatch",
    )
    factorforge_root = Path(str(manifest.get("factorforge_root") or "")).expanduser()
    _require(
        factorforge_root.is_absolute()
        and factorforge_root.is_dir()
        and not factorforge_root.is_symlink(),
        "workspace_manifest:factorforge_root_real_directory_required",
    )
    factorforge_root = factorforge_root.resolve(strict=True)
    _require(
        not (
            _path_component_tokens(factorforge_root)
            & PROTECTED_FACTORFORGE_ROOT_COMPONENTS
        ),
        "workspace_manifest:protected_factorforge_root_forbidden",
    )
    expected_workspace = default_workspace_root(
        factorforge_root=factorforge_root,
        factor_id=str(factor_id),
        research_id=str(research_id),
    ).resolve(strict=True)
    _require(
        expected_workspace == resolved_workspace,
        "workspace_manifest:noncanonical_factor_research_path",
    )
    declared_workspace = Path(str(manifest.get("workspace_root") or "")).expanduser()
    _require(
        declared_workspace.is_absolute()
        and declared_workspace.resolve(strict=True) == resolved_workspace,
        "workspace_manifest:workspace_root_mismatch",
    )
    _require(
        manifest.get("created_by") == "factor_forge_ultimate",
        "workspace_manifest:created_by",
    )
    _require(manifest.get("status") == "active", "workspace_manifest:status")
    _require(
        manifest.get("write_policy")
        == {
            "production_writes_must_stay_under_workspace": True,
            "repo_root_knowledge_write_allowed": False,
            "repo_root_data_write_allowed": False,
            "vault_export_requires_explicit_flag": True,
        },
        "workspace_manifest:write_policy",
    )
    protected_repo_roots = tuple(
        repo_root / name
        for name in (
            ".git",
            "canonical",
            "data",
            "deploy",
            "docs",
            "factor_factory",
            "knowledge",
            "oos",
            "runtime",
            "scripts",
            "tests",
        )
    )
    for candidate in protected_repo_roots:
        if candidate.exists() or candidate.is_symlink():
            protected = candidate.resolve(strict=True)
            _require(
                not _is_within(resolved_workspace, protected),
                f"workspace:protected_repo_root_overlap:{candidate.name}",
            )
    for relative in REQUIRED_WORKSPACE_DIRS:
        required = resolved_workspace / relative
        _require(
            required.is_dir() and not required.is_symlink(),
            f"workspace:required_real_directory:{relative}",
        )
        resolved_required = required.resolve(strict=True)
        _require(
            _is_within(resolved_required, resolved_workspace)
            and resolved_required.stat().st_dev == workspace_stat.st_dev
            and not os.path.ismount(resolved_required),
            f"workspace:required_directory_isolation:{relative}",
        )
    binding = {
        "relative_path": str(manifest_path.relative_to(resolved_workspace)),
        "bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "device": str(metadata.st_dev),
        "inode": str(metadata.st_ino),
        "mtime_ns": str(metadata.st_mtime_ns),
        "link_count": metadata.st_nlink,
        "factor_id": factor_id,
        "research_id": research_id,
        "factorforge_root": str(factorforge_root),
        "workspace_root": str(resolved_workspace),
        "workspace_device": str(workspace_stat.st_dev),
        "workspace_inode": str(workspace_stat.st_ino),
    }
    return manifest, binding, raw


def _json_pointer(value: Any, pointer: str, *, label: str) -> Any:
    _require(isinstance(pointer, str) and pointer.startswith("/"), f"{label}:pointer")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            _require(part in current, f"{label}:pointer_missing:{pointer}")
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            _require(part.isdigit(), f"{label}:array_index_required:{pointer}")
            index = int(part)
            _require(0 <= index < len(current), f"{label}:index_missing:{pointer}")
            current = current[index]
        else:
            raise EpistemicUltimateShadowError(f"{label}:pointer_not_container:{pointer}")
    return current


def _artifact_report_id(payload: Mapping[str, Any]) -> str:
    direct = payload.get("report_id")
    if isinstance(direct, str) and direct:
        return direct
    identity = payload.get("artifact_identity")
    if isinstance(identity, Mapping):
        nested = identity.get("report_id")
        if isinstance(nested, str) and nested:
            return nested
    return ""


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_official_artifact_identity(
    *,
    role: str,
    payload: Mapping[str, Any],
    report_id: str,
    factor_id: str,
    research_id: str,
    branch_id: str,
) -> dict[str, Any]:
    """Validate the native role before attaching an official role label.

    This is deliberately a structural identity replay, not a substitute for
    the formal Step validators.  It prevents a same-report arbitrary JSON file
    from being laundered into an official role by this observation sidecar.
    """

    _require(_artifact_report_id(payload) == report_id, f"artifact.{role}:report_id")
    _require(payload.get("factor_id") == factor_id, f"artifact.{role}:factor_id")
    if role == "ALPHA_IDEA_MASTER":
        source_type = payload.get("source_type")
        producer = payload.get("producer")
        _require(
            payload.get("contract_version") == "factorforge.step1.alpha_idea_master.v2",
            f"artifact.{role}:contract_version",
        )
        _require(
            source_type in SOURCE_PRODUCER_BY_TYPE,
            f"artifact.{role}:source_type",
        )
        _require(
            producer == SOURCE_PRODUCER_BY_TYPE[source_type],
            f"artifact.{role}:producer",
        )
        _require(
            isinstance(payload.get("final_factor"), Mapping),
            f"artifact.{role}:final_factor",
        )
        return {
            "report_id": report_id,
            "factor_id": factor_id,
            "research_id": research_id,
            "branch_id": branch_id,
            "implementation_mode": None,
            "source_type": source_type,
            "contract_version": payload["contract_version"],
            "producer": producer,
            "artifact_role": "alpha_idea_master",
        }

    identity = payload.get("artifact_identity")
    _require(isinstance(identity, Mapping), f"artifact.{role}:artifact_identity")
    source_type = identity.get("source_type")
    implementation_mode = identity.get("implementation_mode")
    expected_artifact_role = DOWNSTREAM_ARTIFACT_ROLES[role]
    _require(identity.get("report_id") == report_id, f"artifact.{role}:identity_report")
    _require(identity.get("factor_id") == factor_id, f"artifact.{role}:identity_factor")
    _require(
        source_type in SOURCE_PRODUCER_BY_TYPE,
        f"artifact.{role}:identity_source_type",
    )
    _require(
        implementation_mode in {"operator", "direct_code", "hybrid"},
        f"artifact.{role}:identity_implementation_mode",
    )
    _require(
        identity.get("contract_version") == "factorforge_step2_source_contract_v2",
        f"artifact.{role}:identity_contract_version",
    )
    _require(
        identity.get("artifact_role") == expected_artifact_role,
        f"artifact.{role}:identity_artifact_role",
    )
    _require(
        _nonempty(identity.get("spec_hash")),
        f"artifact.{role}:identity_spec_hash",
    )
    expected_branch = branch_id or "main"
    _require(
        identity.get("branch_id") == expected_branch,
        f"artifact.{role}:identity_branch",
    )
    expected_producer = (
        SOURCE_PRODUCER_BY_TYPE[source_type]
        if role == "FACTOR_SPEC_MASTER"
        else DOWNSTREAM_ROLE_PRODUCERS[role]
    )
    _require(
        identity.get("producer") == expected_producer,
        f"artifact.{role}:identity_producer",
    )
    if role == "FACTOR_SPEC_MASTER":
        _require(payload.get("contract_version") == identity["contract_version"], f"artifact.{role}:top_contract")
        _require(payload.get("source_type") == source_type, f"artifact.{role}:top_source_type")
        _require(payload.get("producer") == expected_producer, f"artifact.{role}:top_producer")
    elif role == "FACTOR_RUN_MASTER":
        _require(payload.get("producer") == expected_producer, f"artifact.{role}:top_producer")
    elif role in {"FACTOR_CASE_MASTER", "HANDOFF_TO_STEP6"}:
        _require(payload.get("created_by_step") == "step5", f"artifact.{role}:created_by_step")
    return {
        **{field: identity.get(field) for field in FAILURE_IDENTITY_COHERENCE_FIELDS},
        "report_id": report_id,
        "factor_id": factor_id,
        "research_id": research_id,
        "producer": expected_producer,
        "artifact_role": expected_artifact_role,
        "code_hash": identity.get("code_hash"),
    }


def _validate_failure_artifact_coherence(
    payloads: Mapping[str, Mapping[str, Any]],
) -> None:
    """Require one factor lineage across the exact6 failure inputs."""

    _require(
        set(payloads) == {role for role, _ in OFFICIAL_ARTIFACTS[HOOK_FAILURE]},
        "failure_artifacts:exact6",
    )
    spec_identity = payloads["FACTOR_SPEC_MASTER"].get("artifact_identity")
    _require(isinstance(spec_identity, Mapping), "failure_artifacts:spec_identity")
    for role in FAILURE_CODE_COHERENCE_ROLES:
        identity = payloads[role].get("artifact_identity")
        _require(isinstance(identity, Mapping), f"failure_artifacts.{role}:identity")
        for field in FAILURE_IDENTITY_COHERENCE_FIELDS:
            _require(
                identity.get(field) == spec_identity.get(field),
                f"failure_artifacts.{role}:coherence:{field}",
            )
    code_hash = payloads["FACTOR_RUN_MASTER"]["artifact_identity"].get("code_hash")
    _require(
        isinstance(code_hash, str) and SHA256_RE.fullmatch(code_hash) is not None,
        "failure_artifacts:code_hash_anchor",
    )
    for role in FAILURE_CODE_COHERENCE_ROLES[1:]:
        _require(
            payloads[role]["artifact_identity"].get("code_hash") == code_hash,
            f"failure_artifacts.{role}:code_hash_coherence",
        )
    _require(
        payloads["ALPHA_IDEA_MASTER"].get("source_type")
        == spec_identity.get("source_type"),
        "failure_artifacts:alpha_source_type_coherence",
    )


def _artifact_binding(
    *,
    role: str,
    path: Path,
    workspace: Path,
    report_id: str,
    factor_id: str,
    research_id: str,
    branch_id: str,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    resolved = _resolve_inside(path, workspace, label=f"artifact.{role}")
    directory, stem = CANONICAL_OBJECT_PATHS[role]
    expected = (
        workspace / "objects" / directory / f"{stem}__{report_id}.json"
    ).resolve(strict=True)
    _require(resolved == expected, f"artifact.{role}:noncanonical_role_path")
    raw, metadata = _read_regular_file(resolved, label=f"artifact.{role}")
    _require(metadata.st_nlink == 1, f"artifact.{role}:hardlink_forbidden")
    _require(
        metadata.st_dev == workspace.stat().st_dev,
        f"artifact.{role}:cross_device_forbidden",
    )
    payload = _parse_json(raw, label=f"artifact.{role}")
    validated_identity = _validate_official_artifact_identity(
        role=role,
        payload=payload,
        report_id=report_id,
        factor_id=factor_id,
        research_id=research_id,
        branch_id=branch_id,
    )
    binding = {
        "artifact_role": role,
        "relative_path": str(resolved.relative_to(workspace)),
        "bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "device": str(metadata.st_dev),
        "inode": str(metadata.st_ino),
        "mtime_ns": str(metadata.st_mtime_ns),
        "link_count": metadata.st_nlink,
        "report_id": report_id,
        "contract_version": payload.get("contract_version"),
        "producer": payload.get("producer"),
        "source_type": payload.get("source_type"),
        "validated_identity": validated_identity,
    }
    return binding, payload, raw


def _same_artifact_snapshot(
    *, binding: Mapping[str, Any], workspace: Path, raw_expected: bytes
) -> bool:
    path = workspace / str(binding["relative_path"])
    raw, metadata = _read_regular_file(path, label=f"artifact_replay.{binding['artifact_role']}")
    return bool(
        raw == raw_expected
        and hashlib.sha256(raw).hexdigest() == binding["raw_sha256"]
        and str(metadata.st_dev) == binding["device"]
        and str(metadata.st_ino) == binding["inode"]
        and metadata.st_size == binding["bytes"]
        and str(metadata.st_mtime_ns) == binding["mtime_ns"]
        and metadata.st_nlink == binding["link_count"] == 1
    )


def _same_workspace_snapshot(
    *, binding: Mapping[str, Any], workspace: Path, raw_expected: bytes, label: str
) -> bool:
    path = workspace / str(binding["relative_path"])
    raw, metadata = _read_regular_file(path, label=label)
    return bool(
        raw == raw_expected
        and str(metadata.st_dev) == binding["device"]
        and str(metadata.st_ino) == binding["inode"]
        and metadata.st_size == binding["bytes"]
        and str(metadata.st_mtime_ns) == binding["mtime_ns"]
        and metadata.st_nlink == binding["link_count"] == 1
    )


def _load_diagnosis_inputs(
    *, kernel_input: Mapping[str, Any], workspace: Path
) -> tuple[dict[str, bytes], dict[str, Any], list[dict[str, Any]], dict[str, bytes]]:
    diagnosis = kernel_input.get("diagnosis_inputs")
    _require(isinstance(diagnosis, Mapping), "diagnosis_inputs:object_required")
    _require(
        set(diagnosis)
        == {
            "stage2_manifest_path",
            "fixture_json_path",
            "assertion_dependency_json_path",
        },
        "diagnosis_inputs:closed_path_fields",
    )
    root_path = workspace / DIAGNOSIS_INPUT_PARENT_NAME
    _require(
        root_path.is_dir() and not root_path.is_symlink(),
        "diagnosis_input_root:missing_or_symlink",
    )
    root = root_path.resolve(strict=True)
    _require(root.parent == workspace, "diagnosis_input_root:not_direct_workspace_child")
    _require(not os.path.ismount(root), "diagnosis_input_root:mount_forbidden")
    root_stat = root.stat()
    root_binding = {
        "relative_path": DIAGNOSIS_INPUT_PARENT_NAME,
        "device": str(root_stat.st_dev),
        "inode": str(root_stat.st_ino),
    }
    raw_inputs: dict[str, bytes] = {}
    raw_by_role: dict[str, bytes] = {}
    bindings: list[dict[str, Any]] = []
    physical_identities: set[tuple[int, int]] = set()
    for ordinal, (role, path_field, raw_field) in enumerate(DIAGNOSIS_PATH_ROLES):
        path_value = diagnosis[path_field]
        _require(isinstance(path_value, str), f"diagnosis_inputs.{path_field}:path")
        path = Path(path_value).expanduser()
        resolved = _resolve_inside(path, root, label=f"diagnosis_inputs.{path_field}")
        _require(
            resolved.parent == root,
            f"diagnosis_inputs.{path_field}:direct_child_required",
        )
        _require(
            not os.path.ismount(resolved),
            f"diagnosis_inputs.{path_field}:mount_forbidden",
        )
        raw, metadata = _read_regular_file(
            resolved, label=f"diagnosis_inputs.{path_field}"
        )
        _require(
            metadata.st_nlink == 1,
            f"diagnosis_inputs.{path_field}:hardlink_forbidden",
        )
        _require(
            metadata.st_dev == root_stat.st_dev,
            f"diagnosis_inputs.{path_field}:cross_device_forbidden",
        )
        strict_json_loads(raw, label=f"diagnosis_inputs.{path_field}")
        identity = (metadata.st_dev, metadata.st_ino)
        _require(
            identity not in physical_identities,
            "diagnosis_inputs:physical_identity_reuse_forbidden",
        )
        physical_identities.add(identity)
        raw_inputs[raw_field] = raw
        raw_by_role[role] = raw
        bindings.append(
            {
                "ordinal": ordinal,
                "input_role": role,
                "relative_path": str(resolved.relative_to(workspace)),
                "bytes": len(raw),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "device": str(metadata.st_dev),
                "inode": str(metadata.st_ino),
                "mtime_ns": str(metadata.st_mtime_ns),
                "link_count": metadata.st_nlink,
                "candidate_root_only": True,
            }
        )
    return raw_inputs, root_binding, bindings, raw_by_role


def _build_shadow_candidate(
    *, kernel_input: Mapping[str, Any], hook: str, workspace: Path
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]], dict[str, bytes]]:
    if hook == HOOK_STEP1:
        return build_candidate(dict(kernel_input)), None, [], {}
    without_diagnosis = dict(kernel_input)
    without_diagnosis["diagnosis_inputs"] = None
    composition_inputs = epistemic_kernel_composition_inputs(without_diagnosis)
    raw_inputs, root_binding, bindings, raw_by_role = _load_diagnosis_inputs(
        kernel_input=kernel_input,
        workspace=workspace,
    )
    composition_inputs["diagnosis_inputs"] = raw_inputs
    return (
        compose_epistemic_kernel_candidate(**composition_inputs),
        root_binding,
        bindings,
        raw_by_role,
    )


def _validate_real_knowledge_inputs(kernel_input: Mapping[str, Any], repo_root: Path) -> None:
    _require(
        kernel_input.get("retrieval_corpus_objects") is None,
        "request.kernel_input_candidate:synthetic_corpus_forbidden_in_ultimate_shadow",
    )
    real = kernel_input.get("real_knowledge_inputs")
    if real is None:
        _require(
            kernel_input.get("session_scope_secret_hex") is None,
            "request.kernel_input_candidate:secret_without_retrieval",
        )
        return
    _require(
        isinstance(real, Mapping)
        and set(real) == {*EXPECTED_REAL_KNOWLEDGE_PATHS, "top_k_per_lane"},
        "request.kernel_input_candidate.real_knowledge_inputs:closed_fields",
    )
    _require(
        isinstance(real["top_k_per_lane"], int)
        and not isinstance(real["top_k_per_lane"], bool)
        and 1 <= real["top_k_per_lane"] <= 10,
        "request.kernel_input_candidate.real_knowledge_inputs:top_k_range",
    )
    for field, relative in EXPECTED_REAL_KNOWLEDGE_PATHS.items():
        raw_path = Path(str(real[field])).expanduser()
        _require(raw_path.is_absolute(), f"request.real_knowledge.{field}:absolute")
        expected = (repo_root / relative).resolve(strict=True)
        _require(not raw_path.is_symlink(), f"request.real_knowledge.{field}:symlink")
        actual = raw_path.resolve(strict=True)
        _require(actual == expected, f"request.real_knowledge.{field}:not_repo_canonical")


def _validate_diagnosis_scope(
    request: Mapping[str, Any], *, hook: str, report_id: str, factor_id: str
) -> None:
    diagnosis = request["kernel_input_candidate"].get("diagnosis_inputs")
    scope = request["diagnosis_target_scope"]
    if hook == HOOK_STEP1:
        _require(diagnosis is None, "request.step1_hook:diagnosis_forbidden")
        _require(scope is None, "request.step1_hook:diagnosis_scope_forbidden")
        return
    _require(isinstance(diagnosis, Mapping), "request.failure_hook:diagnosis_required")
    closed_scope = _closed(scope, DIAGNOSIS_SCOPE_FIELDS, "request.diagnosis_target_scope")
    _require(
        closed_scope["target_report_id"] == report_id,
        "request.diagnosis_target_scope:report_id",
    )
    _require(
        closed_scope["target_factor_id"] == factor_id,
        "request.diagnosis_target_scope:factor_id_mismatch",
    )
    _require(
        closed_scope["linkage_status"]
        == "CALLER_CLAIMED_CURRENT_FACTOR_TARGET__NOT_INDEPENDENTLY_VERIFIED",
        "request.diagnosis_target_scope:linkage_status",
    )


def _validate_request(
    payload: Mapping[str, Any],
    *,
    hook: str,
    report_id: str,
    factor_id: str,
    repo_root: Path,
) -> dict[str, Any]:
    request = _closed(payload, REQUEST_FIELDS, "request")
    _require(request["schema_id"] == REQUEST_SCHEMA_ID, "request:schema_id")
    _require(request["schema_version"] == SCHEMA_VERSION, "request:schema_version")
    _require(request["report_id"] == report_id, "request:report_id")
    _require(request["hook"] == hook, "request:hook")
    _require(hook in HOOKS, "request:unsupported_hook")
    _require(request["candidate_only"] is True, "request:candidate_only")
    _require(request["signed"] is False, "request:signed")
    _require(request["authority_effect"] == AUTHORITY_EFFECT, "request:authority_effect")
    _require(request["isolation_policy"] == ISOLATION_POLICY, "request:isolation_policy")
    kernel_input = validate_epistemic_kernel_input_payload(
        request["kernel_input_candidate"]
    )
    _validate_real_knowledge_inputs(kernel_input, repo_root)
    _validate_diagnosis_scope(
        request,
        hook=hook,
        report_id=report_id,
        factor_id=factor_id,
    )
    return dict(request)


def _validate_derivation_ledger(
    *,
    request: Mapping[str, Any],
    official_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = _array(request["derivation_ledger"], "request.derivation_ledger")
    _require(len(rows) == len(KERNEL_INPUT_NAMES), "request.derivation_ledger:exact8")
    expected_pointers = [
        f"/kernel_input_candidate/{name}" for name in KERNEL_INPUT_NAMES
    ]
    normalized: list[dict[str, Any]] = []
    for ordinal, (raw, expected_pointer) in enumerate(zip(rows, expected_pointers)):
        row = _closed(raw, DERIVATION_FIELDS, f"request.derivation_ledger[{ordinal}]")
        _require(row["ordinal"] == ordinal, f"request.derivation_ledger[{ordinal}]:ordinal")
        _require(
            row["target_pointer"] == expected_pointer,
            f"request.derivation_ledger[{ordinal}]:target_pointer",
        )
        _require(
            row["derivation_class"] in DERIVATION_CLASSES,
            f"request.derivation_ledger[{ordinal}]:derivation_class",
        )
        target_value = _json_pointer(
            request,
            expected_pointer,
            label=f"request.derivation_ledger[{ordinal}].target",
        )
        role = row["source_artifact_role"]
        pointer = row["source_pointer"]
        source_hash = row["source_value_sha256"]
        if role is None or pointer is None or source_hash is None:
            _require(
                role is None and pointer is None and source_hash is None,
                f"request.derivation_ledger[{ordinal}]:partial_source_binding",
            )
            _require(
                row["derivation_class"] != "DIRECT_COPY",
                f"request.derivation_ledger[{ordinal}]:direct_copy_requires_source",
            )
        else:
            _require(
                isinstance(role, str) and role in official_payloads,
                f"request.derivation_ledger[{ordinal}]:source_role",
            )
            _require(
                isinstance(pointer, str),
                f"request.derivation_ledger[{ordinal}]:source_pointer",
            )
            _require(
                isinstance(source_hash, str) and SHA256_RE.fullmatch(source_hash),
                f"request.derivation_ledger[{ordinal}]:source_value_sha256",
            )
            source_value = _json_pointer(
                official_payloads[role],
                pointer,
                label=f"request.derivation_ledger[{ordinal}].source",
            )
            _require(
                _canonical_value_sha256(source_value) == source_hash,
                f"request.derivation_ledger[{ordinal}]:source_value_hash_mismatch",
            )
            if row["derivation_class"] == "DIRECT_COPY":
                _require(
                    target_value == source_value,
                    f"request.derivation_ledger[{ordinal}]:direct_copy_mismatch",
                )
        normalized.append(dict(row))
    return {
        "status": "PASS",
        "row_count": len(normalized),
        "target_pointer_order": expected_pointers,
        "source_grounded_uplift_performed": False,
        "rows": normalized,
    }


def _load_manifest(
    *, manifest_path: Path, report_id: str, repo_root: Path
) -> tuple[
    dict[str, Any],
    Path,
    dict[str, Any],
    bytes,
    dict[str, Any],
    bytes,
]:
    raw, metadata = _read_regular_file(manifest_path, label="runtime_manifest")
    _require(metadata.st_nlink == 1, "runtime_manifest:hardlink_forbidden")
    manifest = _parse_json(raw, label="runtime_manifest")
    _require(
        manifest.get("contract_version") == "factorforge_runtime_context_v2",
        "runtime_manifest:isolated_workspace_v2_required",
    )
    _require(manifest.get("report_id") == report_id, "runtime_manifest:report_id")
    workspace_raw = manifest.get("factor_workspace")
    _require(isinstance(workspace_raw, str) and workspace_raw, "runtime_manifest:factor_workspace")
    workspace_path = Path(workspace_raw).expanduser()
    _require(
        workspace_path.is_absolute() and workspace_path.is_dir() and not workspace_path.is_symlink(),
        "runtime_manifest:factor_workspace_real_directory_required",
    )
    workspace = workspace_path.resolve(strict=True)
    _require(
        metadata.st_dev == workspace.stat().st_dev,
        "runtime_manifest:cross_device_forbidden",
    )
    manifest_resolved = _resolve_inside(
        manifest_path, workspace, label="runtime_manifest"
    )
    manifest_repo = Path(str(manifest.get("repo_root") or "")).expanduser()
    _require(manifest_repo.is_absolute(), "runtime_manifest:repo_root_absolute")
    _require(
        manifest_repo.resolve(strict=True) == repo_root,
        "runtime_manifest:repo_root_mismatch",
    )
    factor_id = str(manifest.get("factor_id") or "")
    research_id = str(manifest.get("research_id") or "")
    _require(bool(factor_id), "runtime_manifest:factor_id")
    _require(bool(research_id), "runtime_manifest:research_id")
    _, workspace_manifest_binding, workspace_manifest_raw = (
        validate_native_factor_workspace(
            workspace=workspace,
            repo_root=repo_root,
            expected_factor_id=factor_id,
            expected_research_id=research_id,
        )
    )
    binding = {
        "relative_path": str(manifest_resolved.relative_to(workspace)),
        "bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "device": str(metadata.st_dev),
        "inode": str(metadata.st_ino),
        "mtime_ns": str(metadata.st_mtime_ns),
        "link_count": metadata.st_nlink,
    }
    return (
        manifest,
        workspace,
        binding,
        raw,
        workspace_manifest_binding,
        workspace_manifest_raw,
    )


def _load_post_step5_formal_proof(
    *,
    proof_path: Path,
    expected_raw_sha256: str,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    workspace: Path,
    report_id: str,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    _require(
        isinstance(expected_raw_sha256, str)
        and SHA256_RE.fullmatch(expected_raw_sha256) is not None,
        "formal_proof:expected_raw_sha256",
    )
    expected_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json"
    ).resolve(strict=True)
    resolved = _resolve_inside(proof_path, workspace, label="formal_proof")
    _require(resolved == expected_path, "formal_proof:noncanonical_path")
    raw, metadata = _read_regular_file(resolved, label="formal_proof")
    _require(metadata.st_nlink == 1, "formal_proof:hardlink_forbidden")
    _require(
        metadata.st_dev == workspace.stat().st_dev,
        "formal_proof:cross_device_forbidden",
    )
    _require(
        hashlib.sha256(raw).hexdigest() == expected_raw_sha256,
        "formal_proof:raw_sha256_mismatch",
    )
    proof = _parse_json(raw, label="formal_proof")
    required_presence = {
        "contract_version",
        "report_id",
        "factor_id",
        "research_id",
        "factor_workspace",
        "active_root",
        "manifest_path",
        "start_step",
        "end_step",
        "requested_steps",
        "dry_run",
        "status",
        "failure",
        "formal_proof_eligible",
        "current_formal_authority_verified",
        "proof_semantics",
        "formal_command_contract",
        "commands",
        "web_research_preflight",
        "evo_v2_execution_gate",
        "web_resume_start_step",
        "evo_child_command_recovery",
        "web_oos_recovery",
        "evo_child_agent_execution_container",
    }
    _require(
        required_presence <= set(proof),
        "formal_proof:required_presence",
    )
    factor_id = str(manifest.get("factor_id") or "")
    research_id = str(manifest.get("research_id") or "")
    _require(proof.get("contract_version") == "factorforge_ultimate_wrapper_v1", "formal_proof:contract_version")
    _require(proof.get("report_id") == report_id, "formal_proof:report_id")
    _require(proof.get("factor_id") == factor_id, "formal_proof:factor_id")
    _require(proof.get("research_id") == research_id, "formal_proof:research_id")
    _require(proof.get("factor_workspace") == str(workspace), "formal_proof:workspace")
    _require(proof.get("active_root") == str(workspace), "formal_proof:active_root")
    proof_manifest = Path(str(proof.get("manifest_path") or "")).expanduser()
    _require(
        proof_manifest.is_absolute()
        and proof_manifest.resolve(strict=True) == manifest_path.resolve(strict=True),
        "formal_proof:manifest_path",
    )
    requested_steps = proof.get("requested_steps")
    _require(
        isinstance(requested_steps, list)
        and bool(requested_steps)
        and requested_steps[-1] == "5"
        and "5" in requested_steps
        and "6" not in requested_steps,
        "formal_proof:exact_non_step6_range_ending_step5",
    )
    _require(proof.get("end_step") == "5", "formal_proof:end_step")
    _require(proof.get("dry_run") is False, "formal_proof:dry_run")
    _require(proof.get("status") == "PASS", "formal_proof:status")
    _require(proof.get("failure") is None, "formal_proof:failure")
    _require(proof.get("formal_proof_eligible") is True, "formal_proof:eligible")
    _require(
        proof.get("current_formal_authority_verified") is True,
        "formal_proof:current_authority",
    )
    _require(
        proof.get("proof_semantics") == "formal_execution_proof",
        "formal_proof:semantics",
    )
    command_contract = proof.get("formal_command_contract")
    _require(isinstance(command_contract, Mapping), "formal_proof:command_contract")
    _require(command_contract.get("satisfied") is True, "formal_proof:command_contract_unsatisfied")
    required_names = command_contract.get("required_command_names")
    executed_names = command_contract.get("executed_command_names")
    rows = proof.get("commands")
    _require(
        isinstance(required_names, list)
        and isinstance(executed_names, list)
        and isinstance(rows, list),
        "formal_proof:command_arrays",
    )
    actual_names = [
        row.get("name") if isinstance(row, Mapping) else None for row in rows
    ]
    _require(
        required_names == executed_names == actual_names,
        "formal_proof:command_order_mismatch",
    )
    _require(
        all(
            isinstance(row, Mapping)
            and row.get("status") == "PASS"
            and row.get("returncode") == 0
            for row in rows
        ),
        "formal_proof:command_failure",
    )
    _require(actual_names.count("validate_step5") == 1, "formal_proof:validate_step5_exact1")
    forbidden_command_tokens = ("oos", "evo", "council", "release", "revision")
    _require(
        not any(
            token in str(name).casefold()
            for name in actual_names
            for token in forbidden_command_tokens
        ),
        "formal_proof:oos_or_revision_command_forbidden",
    )
    _require(proof.get("web_research_preflight") is None, "formal_proof:web_preflight_forbidden")
    _require(proof.get("evo_v2_execution_gate") is None, "formal_proof:evo_gate_forbidden")
    _require(proof.get("web_resume_start_step") is None, "formal_proof:web_resume_forbidden")
    _require(proof.get("evo_child_command_recovery") is None, "formal_proof:evo_recovery_forbidden")
    _require(
        "evo_v2_post_oos_terminal_closure" not in proof,
        "formal_proof:oos_closure_forbidden",
    )
    _require(
        "current_evo_terminal_authority" not in proof,
        "formal_proof:evo_terminal_forbidden",
    )
    _require(
        "current_factor_proof_authority" not in proof,
        "formal_proof:factor_proof_forbidden",
    )
    _require(
        proof.get("web_oos_recovery")
        == {
            "recovery_required": False,
            "allowed_execution": "NORMAL",
            "artifact_refs": [],
            "finalization_receipt_present": False,
        },
        "formal_proof:oos_recovery_not_clean",
    )
    container = proof.get("evo_child_agent_execution_container")
    _require(
        isinstance(container, Mapping)
        and container.get("required") is False
        and container.get("status") == "NOT_APPLICABLE",
        "formal_proof:evo_container_forbidden",
    )
    binding = {
        "relative_path": str(resolved.relative_to(workspace)),
        "bytes": len(raw),
        "raw_sha256": expected_raw_sha256,
        "device": str(metadata.st_dev),
        "inode": str(metadata.st_ino),
        "mtime_ns": str(metadata.st_mtime_ns),
        "link_count": metadata.st_nlink,
        "status": "PASS",
        "formal_proof_eligible": True,
        "current_formal_authority_verified": True,
        "requested_steps": list(requested_steps),
        "required_command_names": list(required_names),
        "oos_used": False,
    }
    return proof, binding, raw


def _load_official_artifacts(
    *,
    manifest: Mapping[str, Any],
    workspace: Path,
    hook: str,
    report_id: str,
    factor_id: str,
    research_id: str,
    branch_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, bytes]]:
    objects = manifest.get("objects")
    _require(isinstance(objects, Mapping), "runtime_manifest.objects:object_required")
    bindings: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    raw_by_role: dict[str, bytes] = {}
    for role, object_key in OFFICIAL_ARTIFACTS[hook]:
        raw_path = objects.get(object_key)
        _require(isinstance(raw_path, str) and raw_path, f"runtime_manifest.objects:{object_key}")
        binding, payload, raw = _artifact_binding(
            role=role,
            path=Path(raw_path).expanduser(),
            workspace=workspace,
            report_id=report_id,
            factor_id=factor_id,
            research_id=research_id,
            branch_id=branch_id,
        )
        bindings.append({"ordinal": len(bindings), **binding})
        payloads[role] = payload
        raw_by_role[role] = raw
    if hook == HOOK_FAILURE:
        _validate_failure_artifact_coherence(payloads)
    return bindings, payloads, raw_by_role


def _formal_artifact_snapshot_from_bindings(
    *,
    report_id: str,
    factor_id: str,
    research_id: str,
    bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_bindings = [dict(row) for row in bindings]
    core = {
        "schema_id": FORMAL_ARTIFACT_SNAPSHOT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "factor_id": factor_id,
        "research_id": research_id,
        "hook": HOOK_FAILURE,
        "official_artifact_bindings": normalized_bindings,
        "official_artifact_binding_commitment": framed_sha256(
            ARTIFACT_BINDING_DOMAIN, normalized_bindings
        ),
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return {
        **core,
        "content_sha256": framed_sha256(FORMAL_ARTIFACT_SNAPSHOT_DOMAIN, core),
    }


def capture_failure_artifact_snapshot(
    *, manifest_path: Path, report_id: str, repo_root: Path
) -> dict[str, Any]:
    """Capture the exact6 current files before the wrapper seals its proof.

    The object remains candidate-only and unsigned.  Its sole purpose is to
    prevent the post-proof sidecar from silently accepting a later artifact
    generation while claiming to diagnose the just-completed Step5 run.
    """

    repo = repo_root.resolve(strict=True)
    manifest, workspace, _, _, _, _ = _load_manifest(
        manifest_path=manifest_path.resolve(strict=True),
        report_id=report_id,
        repo_root=repo,
    )
    factor_id = str(manifest.get("factor_id") or "")
    research_id = str(manifest.get("research_id") or "")
    branch_id = str(manifest.get("branch_id") or "main")
    bindings, _, _ = _load_official_artifacts(
        manifest=manifest,
        workspace=workspace,
        hook=HOOK_FAILURE,
        report_id=report_id,
        factor_id=factor_id,
        research_id=research_id,
        branch_id=branch_id,
    )
    return _formal_artifact_snapshot_from_bindings(
        report_id=report_id,
        factor_id=factor_id,
        research_id=research_id,
        bindings=bindings,
    )


def _validate_formal_artifact_snapshot(
    snapshot: Mapping[str, Any],
    *,
    report_id: str,
    factor_id: str,
    research_id: str,
    current_bindings: Sequence[Mapping[str, Any]],
    formal_proof_binding: Mapping[str, Any],
) -> dict[str, Any]:
    closed = _closed(
        snapshot,
        FORMAL_ARTIFACT_SNAPSHOT_FIELDS,
        "formal_artifact_snapshot",
    )
    expected = _formal_artifact_snapshot_from_bindings(
        report_id=report_id,
        factor_id=factor_id,
        research_id=research_id,
        bindings=current_bindings,
    )
    _require(
        dict(closed) == expected,
        "formal_artifact_snapshot:current_exact6_mismatch",
    )
    proof_mtime = int(str(formal_proof_binding.get("mtime_ns") or "-1"))
    _require(
        all(int(str(row.get("mtime_ns") or "-1")) <= proof_mtime for row in current_bindings),
        "formal_artifact_snapshot:artifact_modified_after_formal_proof",
    )
    return expected


def _secret_absent(payloads: Sequence[bytes], kernel_input: Mapping[str, Any]) -> bool:
    secret_hex = kernel_input.get("session_scope_secret_hex")
    if secret_hex is None:
        return True
    _require(
        isinstance(secret_hex, str) and re.fullmatch(r"[0-9a-fA-F]{64}", secret_hex),
        "request.kernel_input_candidate:session_secret",
    )
    secret = bytes.fromhex(secret_hex)
    standard_b64 = base64.b64encode(secret)
    urlsafe_b64 = base64.urlsafe_b64encode(secret)
    needles = {
        secret,
        secret_hex.encode("ascii"),
        secret_hex.lower().encode("ascii"),
        secret_hex.upper().encode("ascii"),
        standard_b64,
        standard_b64.rstrip(b"="),
        urlsafe_b64,
        urlsafe_b64.rstrip(b"="),
    }
    return not any(needle in payload for needle in needles for payload in payloads)


def _open_or_create_dir_at(parent_fd: int, name: str) -> int:
    _require(re.fullmatch(r"[a-z0-9_]{1,96}", name) is not None, "publish:unsafe_dir_name")
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    metadata = os.fstat(descriptor)
    _require(stat.S_ISDIR(metadata.st_mode), "publish:directory_required")
    return descriptor


def _write_once_at(directory_fd: int, name: str, payload: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        directory_stat = os.fstat(directory_fd)
        metadata = os.fstat(descriptor)
        _require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and metadata.st_dev == directory_stat.st_dev,
            "publish:new_file_physical_identity",
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "publish:short_write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_at(directory_fd: int, name: str) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        directory_stat = os.fstat(directory_fd)
        metadata = os.fstat(descriptor)
        _require(stat.S_ISREG(metadata.st_mode), "publish:existing_file_not_regular")
        _require(metadata.st_nlink == 1, "publish:existing_file_hardlink_forbidden")
        _require(
            metadata.st_dev == directory_stat.st_dev,
            "publish:existing_file_cross_device_forbidden",
        )
        output = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            output.extend(chunk)
        return bytes(output)
    finally:
        os.close(descriptor)


def _publish_package(
    *,
    workspace: Path,
    run_id: str,
    payloads: Mapping[str, bytes],
    before_receipt: Callable[[], None],
    after_receipt: Callable[[], None],
    expected_workspace_device: str,
    expected_workspace_inode: str,
) -> Path:
    expected_names = (
        "00_kernel_candidate.json",
        "01_chief_advisory.json",
        "02_shadow_receipt.json",
    )
    _require(tuple(payloads) == expected_names, "publish:exact3_order")
    workspace_fd = os.open(
        workspace,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    parent_fd: int | None = None
    run_fd: int | None = None
    staging_name: str | None = None
    validate_existing_final = False
    try:
        workspace_stat = workspace.stat()
        fd_stat = os.fstat(workspace_fd)
        _require(
            (workspace_stat.st_dev, workspace_stat.st_ino)
            == (fd_stat.st_dev, fd_stat.st_ino),
            "publish:workspace_identity_drift",
        )
        _require(
            str(fd_stat.st_dev) == expected_workspace_device
            and str(fd_stat.st_ino) == expected_workspace_inode,
            "publish:workspace_binding_mismatch",
        )
        parent_fd = _open_or_create_dir_at(workspace_fd, OUTPUT_PARENT_NAME)
        os.fsync(workspace_fd)
        parent_stat = os.fstat(parent_fd)
        _require(
            parent_stat.st_dev == fd_stat.st_dev,
            "publish:output_parent_cross_device_forbidden",
        )
        _require(
            not os.path.ismount(workspace / OUTPUT_PARENT_NAME),
            "publish:output_parent_mount_forbidden",
        )
        try:
            run_fd = os.open(
                run_id,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            validate_existing_final = True
        except FileNotFoundError:
            staging_name = (
                f"staging_{run_id.removeprefix('shadow_')}_{os.getpid()}_"
                f"{secrets.token_hex(8)}"
            )
            os.mkdir(staging_name, mode=0o700, dir_fd=parent_fd)
            run_fd = os.open(
                staging_name,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            _write_once_at(
                run_fd,
                "00_kernel_candidate.json",
                payloads["00_kernel_candidate.json"],
            )
            _write_once_at(
                run_fd,
                "01_chief_advisory.json",
                payloads["01_chief_advisory.json"],
            )
            before_receipt()
            _write_once_at(
                run_fd,
                "02_shadow_receipt.json",
                payloads["02_shadow_receipt.json"],
            )
            after_receipt()
            os.fsync(run_fd)
            try:
                os.rename(
                    staging_name,
                    run_id,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                staging_name = None
                os.fsync(parent_fd)
                final_fd: int | None = None
                try:
                    final_fd = os.open(
                        run_id,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                    final_stat = os.fstat(final_fd)
                    staging_stat = os.fstat(run_fd)
                    _require(
                        (final_stat.st_dev, final_stat.st_ino)
                        == (staging_stat.st_dev, staging_stat.st_ino),
                        "publish:final_entry_identity_mismatch",
                    )
                    os.close(run_fd)
                    run_fd = final_fd
                    final_fd = None
                finally:
                    if final_fd is not None:
                        os.close(final_fd)
                validate_existing_final = True
            except FileExistsError:
                # A concurrent writer won.  Its final package must be exactly
                # the same content-addressed object before this call succeeds.
                os.close(run_fd)
                run_fd = None
                run_fd = os.open(
                    run_id,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
                validate_existing_final = True
        _require(
            os.fstat(run_fd).st_dev == parent_stat.st_dev,
            "publish:run_root_cross_device_forbidden",
        )
        if validate_existing_final:
            _require(
                not os.path.ismount(workspace / OUTPUT_PARENT_NAME / run_id),
                "publish:run_root_mount_forbidden",
            )
        if validate_existing_final:
            existing_names = sorted(os.listdir(run_fd))
            _require(
                existing_names == sorted(payloads),
                "publish:idempotent_package_closure_mismatch",
            )
            for name, payload in payloads.items():
                _require(
                    _read_at(run_fd, name) == payload,
                    f"publish:idempotent_bytes_mismatch:{name}",
                )
            before_receipt()
            after_receipt()
            final_entry = os.stat(
                run_id,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            open_final = os.fstat(run_fd)
            _require(
                (final_entry.st_dev, final_entry.st_ino)
                == (open_final.st_dev, open_final.st_ino),
                "publish:final_entry_replaced_during_replay",
            )
            _require(
                sorted(os.listdir(run_fd)) == sorted(payloads),
                "publish:final_closure_drift",
            )
        if staging_name is not None:
            # The concurrent final package was accepted.  Remove our private
            # staging copy; no incomplete `shadow_*` directory was observable.
            staging_fd = os.open(
                staging_name,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                for name in reversed(tuple(payloads)):
                    os.unlink(name, dir_fd=staging_fd)
            finally:
                os.close(staging_fd)
            os.rmdir(staging_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            staging_name = None
        return workspace / OUTPUT_PARENT_NAME / run_id / "02_shadow_receipt.json"
    except Exception:
        if staging_name is not None and parent_fd is not None:
            try:
                cleanup_fd = os.open(
                    staging_name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
            except OSError:
                cleanup_fd = None
            if cleanup_fd is not None:
                try:
                    for name in reversed(tuple(payloads)):
                        try:
                            os.unlink(name, dir_fd=cleanup_fd)
                        except FileNotFoundError:
                            pass
                finally:
                    os.close(cleanup_fd)
            try:
                os.rmdir(staging_name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if run_fd is not None:
            os.close(run_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(workspace_fd)


def run_ultimate_epistemic_shadow(
    *,
    manifest_path: Path,
    request_path: Path,
    hook: str,
    report_id: str,
    repo_root: Path,
    formal_proof_path: Path | None = None,
    formal_proof_raw_sha256: str | None = None,
    formal_artifact_snapshot: Mapping[str, Any] | None = None,
) -> Path:
    """Run one isolated observation sidecar without joining formal authority."""

    _require(hook in HOOKS, "hook:unsupported")
    repo = repo_root.resolve(strict=True)
    (
        manifest,
        workspace,
        manifest_binding,
        manifest_raw,
        workspace_manifest_binding,
        workspace_manifest_raw,
    ) = _load_manifest(
        manifest_path=manifest_path.resolve(strict=True),
        report_id=report_id,
        repo_root=repo,
    )
    factor_id = str(manifest.get("factor_id") or "")
    research_id = str(manifest.get("research_id") or "")
    branch_id = str(manifest.get("branch_id") or "main")
    _require(bool(factor_id), "runtime_manifest:factor_id")
    _require(bool(research_id), "runtime_manifest:research_id")
    request_root = workspace / REQUEST_PARENT_NAME
    _require(
        request_root.is_dir() and not request_root.is_symlink(),
        "request_parent:missing_or_symlink",
    )
    request_root_resolved = request_root.resolve(strict=True)
    _require(
        request_root_resolved.parent == workspace
        and request_root_resolved.stat().st_dev == workspace.stat().st_dev
        and not os.path.ismount(request_root_resolved),
        "request_parent:isolation",
    )
    request_resolved = _resolve_inside(
        request_path, request_root_resolved, label="request"
    )
    _require(request_resolved.parent == request_root_resolved, "request:direct_child_required")
    request_raw, request_stat = _read_regular_file(request_resolved, label="request")
    _require(request_stat.st_nlink == 1, "request:hardlink_forbidden")
    _require(
        request_stat.st_dev == workspace.stat().st_dev,
        "request:cross_device_forbidden",
    )
    request_payload = _validate_request(
        _parse_json(request_raw, label="request"),
        hook=hook,
        report_id=report_id,
        factor_id=factor_id,
        repo_root=repo,
    )
    formal_proof_binding: dict[str, Any] | None = None
    formal_proof_raw: bytes | None = None
    if hook == HOOK_FAILURE:
        _require(formal_proof_path is not None, "formal_proof:required_for_failure_hook")
        _require(
            formal_proof_raw_sha256 is not None,
            "formal_proof:expected_hash_required_for_failure_hook",
        )
        _, formal_proof_binding, formal_proof_raw = _load_post_step5_formal_proof(
            proof_path=formal_proof_path,
            expected_raw_sha256=formal_proof_raw_sha256,
            manifest_path=manifest_path,
            manifest=manifest,
            workspace=workspace,
            report_id=report_id,
        )
        _require(
            isinstance(formal_artifact_snapshot, Mapping),
            "formal_artifact_snapshot:required_for_failure_hook",
        )
    else:
        _require(formal_proof_path is None, "formal_proof:forbidden_for_step1_hook")
        _require(
            formal_proof_raw_sha256 is None,
            "formal_proof:hash_forbidden_for_step1_hook",
        )
        _require(
            formal_artifact_snapshot is None,
            "formal_artifact_snapshot:forbidden_for_step1_hook",
        )
    official_bindings, official_payloads, official_raw = _load_official_artifacts(
        manifest=manifest,
        workspace=workspace,
        hook=hook,
        report_id=report_id,
        factor_id=factor_id,
        research_id=research_id,
        branch_id=branch_id,
    )
    validated_formal_artifact_snapshot: dict[str, Any] | None = None
    if hook == HOOK_FAILURE:
        _require(
            formal_proof_binding is not None,
            "formal_artifact_snapshot:formal_proof_binding_required",
        )
        validated_formal_artifact_snapshot = _validate_formal_artifact_snapshot(
            formal_artifact_snapshot,
            report_id=report_id,
            factor_id=factor_id,
            research_id=research_id,
            current_bindings=official_bindings,
            formal_proof_binding=formal_proof_binding,
        )
    derivation = _validate_derivation_ledger(
        request=request_payload,
        official_payloads=official_payloads,
    )
    (
        candidate,
        diagnosis_root_binding,
        diagnosis_input_bindings,
        diagnosis_raw_by_role,
    ) = _build_shadow_candidate(
        kernel_input=request_payload["kernel_input_candidate"],
        hook=hook,
        workspace=workspace,
    )
    candidate_bytes = _json_bytes(candidate)
    advisory = candidate["chief_research_advisory"]
    advisory_bytes = _json_bytes(advisory)
    _require(
        _secret_absent(
            [candidate_bytes, advisory_bytes], request_payload["kernel_input_candidate"]
        ),
        "shadow:session_secret_persisted",
    )
    for binding in official_bindings:
        role = str(binding["artifact_role"])
        _require(
            _same_artifact_snapshot(
                binding=binding,
                workspace=workspace,
                raw_expected=official_raw[role],
            ),
            f"shadow:official_artifact_mutated_during_build:{role}",
        )
    artifact_commitment = framed_sha256(
        ARTIFACT_BINDING_DOMAIN, official_bindings
    )
    request_binding = {
        "relative_path": str(request_resolved.relative_to(workspace)),
        "bytes": len(request_raw),
        "raw_sha256": hashlib.sha256(request_raw).hexdigest(),
        "device": str(request_stat.st_dev),
        "inode": str(request_stat.st_ino),
        "mtime_ns": str(request_stat.st_mtime_ns),
        "link_count": request_stat.st_nlink,
    }
    diagnosis_binding_commitment = framed_sha256(
        DIAGNOSIS_INPUT_BINDING_DOMAIN,
        {
            "root_binding": diagnosis_root_binding,
            "input_bindings": diagnosis_input_bindings,
        },
    )
    run_id = "shadow_" + framed_sha256(
        RUN_ID_DOMAIN,
        {
            "hook": hook,
            "report_id": report_id,
            "request_binding": request_binding,
            "runtime_manifest_binding": manifest_binding,
            "workspace_manifest_binding": workspace_manifest_binding,
            "official_artifact_binding_commitment": artifact_commitment,
            "formal_proof_binding": formal_proof_binding,
            "formal_artifact_snapshot_content_sha256": (
                validated_formal_artifact_snapshot["content_sha256"]
                if validated_formal_artifact_snapshot is not None
                else None
            ),
            "diagnosis_input_binding_commitment": diagnosis_binding_commitment,
            "kernel_candidate_content_sha256": candidate["content_sha256"],
        },
    )[:32]
    result_core = {
        "schema_id": RESULT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "SHADOW_OBSERVATION_COMPLETE__NO_AUTHORITY_EFFECT",
        "shadow_run_id": run_id,
        "report_id": report_id,
        "factor_id": factor_id,
        "research_id": research_id,
        "hook": hook,
        "request_binding": request_binding,
        "runtime_manifest_binding": manifest_binding,
        "workspace_manifest_binding": workspace_manifest_binding,
        "official_artifact_bindings": official_bindings,
        "official_artifact_binding_commitment": artifact_commitment,
        "formal_proof_binding": formal_proof_binding,
        "formal_artifact_snapshot": validated_formal_artifact_snapshot,
        "diagnosis_input_root_binding": diagnosis_root_binding,
        "diagnosis_input_bindings": diagnosis_input_bindings,
        "diagnosis_input_binding_commitment": diagnosis_binding_commitment,
        "derivation_ledger_validation": derivation,
        "diagnosis_target_scope": request_payload["diagnosis_target_scope"],
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
        "execution_boundary": {
            "official_artifacts_mutated": False,
            "official_registry_written": False,
            "step2_6_inputs_emitted": False,
            "canonical_write_performed": False,
            "protected_oos_root_access_performed": False,
            "candidate_input_provenance_independently_verified": False,
            "promotion_or_qualification_performed": False,
            "diagnostic_tests_executed": False,
            "network_access_performed": False,
        },
        "consumer_policy": {
            "allowed_consumers": ["RESEARCH_AGENT_SHADOW_REVIEW"],
            "forbidden_consumers": ["STEP2", "STEP3", "STEP4", "STEP5", "STEP6"],
        },
        "formal_pipeline_effect": {
            "formal_command_contract_changed": False,
            "formal_proof_eligibility_contributor": False,
            "factor_verdict_contributor": False,
            "operating_contract_delta_activated": False,
        },
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    result = dict(result_core)
    result["content_sha256"] = framed_sha256(RESULT_DOMAIN, result_core)
    receipt_bytes = _json_bytes(result)
    _require(
        _secret_absent(
            [candidate_bytes, advisory_bytes, receipt_bytes],
            request_payload["kernel_input_candidate"],
        ),
        "shadow:session_secret_persisted_in_package",
    )
    def assert_all_inputs_unchanged() -> None:
        _require(
            _same_workspace_snapshot(
                binding=manifest_binding,
                workspace=workspace,
                raw_expected=manifest_raw,
                label="runtime_manifest_replay",
            ),
            "shadow:runtime_manifest_mutated",
        )
        _require(
            _same_workspace_snapshot(
                binding=workspace_manifest_binding,
                workspace=workspace,
                raw_expected=workspace_manifest_raw,
                label="workspace_manifest_replay",
            ),
            "shadow:workspace_manifest_mutated",
        )
        _require(
            _same_workspace_snapshot(
                binding=request_binding,
                workspace=workspace,
                raw_expected=request_raw,
                label="request_replay",
            ),
            "shadow:request_mutated",
        )
        for binding in official_bindings:
            role = str(binding["artifact_role"])
            _require(
                _same_artifact_snapshot(
                    binding=binding,
                    workspace=workspace,
                    raw_expected=official_raw[role],
                ),
                f"shadow:official_artifact_mutated_before_receipt:{role}",
            )
        for binding in diagnosis_input_bindings:
            role = str(binding["input_role"])
            _require(
                _same_workspace_snapshot(
                    binding=binding,
                    workspace=workspace,
                    raw_expected=diagnosis_raw_by_role[role],
                    label=f"diagnosis_input_replay.{role}",
                ),
                f"shadow:diagnosis_input_mutated:{role}",
            )
        if diagnosis_root_binding is not None:
            root_now = workspace / str(diagnosis_root_binding["relative_path"])
            _require(
                root_now.is_dir()
                and not root_now.is_symlink()
                and str(root_now.stat().st_dev) == diagnosis_root_binding["device"]
                and str(root_now.stat().st_ino) == diagnosis_root_binding["inode"],
                "shadow:diagnosis_input_root_mutated",
            )
        if formal_proof_binding is not None and formal_proof_raw is not None:
            _require(
                _same_workspace_snapshot(
                    binding=formal_proof_binding,
                    workspace=workspace,
                    raw_expected=formal_proof_raw,
                    label="formal_proof_replay",
                ),
                "shadow:formal_proof_mutated",
            )

    receipt_path = _publish_package(
        workspace=workspace,
        run_id=run_id,
        payloads={
            "00_kernel_candidate.json": candidate_bytes,
            "01_chief_advisory.json": advisory_bytes,
            "02_shadow_receipt.json": receipt_bytes,
        },
        before_receipt=assert_all_inputs_unchanged,
        after_receipt=assert_all_inputs_unchanged,
        expected_workspace_device=workspace_manifest_binding["workspace_device"],
        expected_workspace_inode=workspace_manifest_binding["workspace_inode"],
    )
    validate_ultimate_epistemic_shadow_package(receipt_path)
    return receipt_path


def _binding_path_inside_workspace(
    *,
    workspace: Path,
    binding: Mapping[str, Any],
    label: str,
    expected_relative_path: str | None = None,
    expected_parent: str | None = None,
) -> Path:
    raw_relative = binding.get("relative_path")
    _require(
        isinstance(raw_relative, str) and bool(raw_relative),
        f"{label}:relative_path_required",
    )
    relative = Path(raw_relative)
    _require(not relative.is_absolute(), f"{label}:absolute_binding_forbidden")
    _require(
        raw_relative == relative.as_posix()
        and all(part not in {"", ".", ".."} for part in relative.parts),
        f"{label}:noncanonical_relative_path",
    )
    if expected_relative_path is not None:
        _require(
            raw_relative == expected_relative_path,
            f"{label}:canonical_role_path_mismatch",
        )
    resolved = _resolve_inside(
        workspace / relative,
        workspace,
        label=f"{label}.binding_path",
    )
    _require(
        resolved.relative_to(workspace).as_posix() == raw_relative,
        f"{label}:resolved_relative_path_mismatch",
    )
    if expected_parent is not None:
        expected_parent_path = (workspace / expected_parent).resolve(strict=True)
        _require(
            resolved.parent == expected_parent_path,
            f"{label}:canonical_parent_mismatch",
        )
        _require(
            expected_parent_path.parent == workspace
            and expected_parent_path.stat().st_dev == workspace.stat().st_dev
            and not os.path.ismount(expected_parent_path),
            f"{label}:canonical_parent_isolation",
        )
    return resolved


def _read_current_bound_file(
    *,
    workspace: Path,
    binding: Mapping[str, Any],
    label: str,
    expected_fields: set[str],
    expected_relative_path: str | None = None,
    expected_parent: str | None = None,
) -> tuple[Path, bytes]:
    closed = _closed(binding, expected_fields, label)
    path = _binding_path_inside_workspace(
        workspace=workspace,
        binding=closed,
        label=label,
        expected_relative_path=expected_relative_path,
        expected_parent=expected_parent,
    )
    raw, metadata = _read_regular_file(path, label=label)
    _require(
        isinstance(closed.get("bytes"), int)
        and not isinstance(closed.get("bytes"), bool)
        and len(raw) == closed["bytes"],
        f"{label}:bytes_mismatch",
    )
    _require(
        isinstance(closed.get("raw_sha256"), str)
        and SHA256_RE.fullmatch(str(closed["raw_sha256"])) is not None
        and hashlib.sha256(raw).hexdigest() == closed["raw_sha256"],
        f"{label}:raw_sha256_mismatch",
    )
    _require(
        str(metadata.st_dev) == closed.get("device")
        and str(metadata.st_ino) == closed.get("inode")
        and str(metadata.st_mtime_ns) == closed.get("mtime_ns"),
        f"{label}:physical_identity_mismatch",
    )
    _require(
        metadata.st_nlink == closed.get("link_count") == 1,
        f"{label}:hardlink_forbidden",
    )
    return path, raw


def _binding_matches_current_file(
    *,
    workspace: Path,
    binding: Mapping[str, Any],
    label: str,
    expected_fields: set[str] = BASIC_FILE_BINDING_FIELDS,
    expected_relative_path: str | None = None,
    expected_parent: str | None = None,
) -> bool:
    try:
        _read_current_bound_file(
            workspace=workspace,
            binding=binding,
            label=label,
            expected_fields=expected_fields,
            expected_relative_path=expected_relative_path,
            expected_parent=expected_parent,
        )
    except (OSError, EpistemicUltimateShadowError, ValueError):
        return False
    return True


def validate_ultimate_epistemic_shadow_package(receipt_path: Path) -> dict[str, Any]:
    """Replay the closed exact3 package and every still-live input binding."""

    _require(receipt_path.is_absolute(), "receipt:absolute_path_required")
    _require(receipt_path.name == "02_shadow_receipt.json", "receipt:filename")
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
    _require(not run_root.is_symlink(), "receipt:run_root_symlink")
    _require(not os.path.ismount(output_root), "receipt:output_root_mount_forbidden")
    _require(not os.path.ismount(run_root), "receipt:run_root_mount_forbidden")
    _require(
        sorted(path.name for path in run_root.iterdir())
        == [
            "00_kernel_candidate.json",
            "01_chief_advisory.json",
            "02_shadow_receipt.json",
        ],
        "receipt:exact3_closure",
    )
    workspace_device = workspace.stat().st_dev
    receipt_raw, receipt_stat = _read_regular_file(resolved_receipt, label="receipt")
    _require(
        receipt_stat.st_nlink == 1 and receipt_stat.st_dev == workspace_device,
        "receipt:physical_identity",
    )
    receipt = _parse_json(receipt_raw, label="receipt")
    _require(
        set(receipt) == RESULT_CORE_FIELDS | {"content_sha256"},
        "receipt:closed_fields",
    )
    core = {key: value for key, value in receipt.items() if key != "content_sha256"}
    _require(receipt["content_sha256"] == framed_sha256(RESULT_DOMAIN, core), "receipt:content_sha256")
    _require(receipt["schema_id"] == RESULT_SCHEMA_ID, "receipt:schema_id")
    _require(receipt["schema_version"] == SCHEMA_VERSION, "receipt:schema_version")
    _require(receipt["shadow_run_id"] == run_root.name, "receipt:run_id")
    _require(receipt["hook"] in HOOKS, "receipt:hook")
    _require(
        isinstance(receipt["report_id"], str)
        and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", receipt["report_id"])
        is not None,
        "receipt:report_id_path_safety",
    )
    _require(_nonempty(receipt["factor_id"]), "receipt:factor_id")
    _require(_nonempty(receipt["research_id"]), "receipt:research_id")
    _require(receipt["candidate_only"] is True, "receipt:candidate_only")
    _require(receipt["signed"] is False, "receipt:signed")
    _require(receipt["authority_effect"] == AUTHORITY_EFFECT, "receipt:authority_effect")
    _require(
        receipt["artifact_status"]
        == "SHADOW_OBSERVATION_COMPLETE__NO_AUTHORITY_EFFECT",
        "receipt:artifact_status",
    )
    _require(
        receipt["execution_boundary"]
        == {
            "official_artifacts_mutated": False,
            "official_registry_written": False,
            "step2_6_inputs_emitted": False,
            "canonical_write_performed": False,
            "protected_oos_root_access_performed": False,
            "candidate_input_provenance_independently_verified": False,
            "promotion_or_qualification_performed": False,
            "diagnostic_tests_executed": False,
            "network_access_performed": False,
        },
        "receipt:execution_boundary",
    )
    _require(
        receipt["formal_pipeline_effect"]
        == {
            "formal_command_contract_changed": False,
            "formal_proof_eligibility_contributor": False,
            "factor_verdict_contributor": False,
            "operating_contract_delta_activated": False,
        },
        "receipt:formal_pipeline_effect",
    )
    _require(
        receipt["consumer_policy"]
        == {
            "allowed_consumers": ["RESEARCH_AGENT_SHADOW_REVIEW"],
            "forbidden_consumers": ["STEP2", "STEP3", "STEP4", "STEP5", "STEP6"],
        },
        "receipt:consumer_policy",
    )
    derivation = receipt["derivation_ledger_validation"]
    _require(
        isinstance(derivation, Mapping)
        and derivation.get("status") == "PASS"
        and derivation.get("row_count") == 8
        and derivation.get("source_grounded_uplift_performed") is False,
        "receipt:derivation_ledger_validation",
    )
    candidate_path = run_root / "00_kernel_candidate.json"
    advisory_path = run_root / "01_chief_advisory.json"
    candidate_raw, candidate_stat = _read_regular_file(
        candidate_path, label="receipt.candidate"
    )
    advisory_raw, advisory_stat = _read_regular_file(
        advisory_path, label="receipt.advisory"
    )
    _require(
        candidate_stat.st_nlink == advisory_stat.st_nlink == 1
        and candidate_stat.st_dev == advisory_stat.st_dev == workspace_device,
        "receipt:package_artifact_physical_identity",
    )
    candidate = _parse_json(candidate_raw, label="receipt.candidate")
    _parse_json(advisory_raw, label="receipt.advisory")
    _require(
        candidate.get("content_sha256") == receipt["kernel_candidate_content_sha256"],
        "receipt:candidate_content_identity",
    )
    _require(
        hashlib.sha256(advisory_raw).hexdigest()
        == receipt["chief_advisory_raw_sha256"],
        "receipt:advisory_identity",
    )
    package_rows = receipt["package_artifacts"]
    _require(isinstance(package_rows, list) and len(package_rows) == 2, "receipt:package_exact2")
    for ordinal, (row, path, raw) in enumerate(
        zip(package_rows, (candidate_path, advisory_path), (candidate_raw, advisory_raw))
    ):
        _require(
            isinstance(row, Mapping)
            and row.get("ordinal") == ordinal
            and row.get("path") == path.name
            and row.get("bytes") == len(raw)
            and row.get("raw_sha256") == hashlib.sha256(raw).hexdigest(),
            f"receipt:package_artifact_{ordinal}",
        )
    report_id = str(receipt["report_id"])
    factor_id = str(receipt["factor_id"])
    research_id = str(receipt["research_id"])
    hook = str(receipt["hook"])
    repo_root = Path(__file__).resolve().parents[1]
    runtime_relative = (
        Path("objects")
        / "runtime_context"
        / f"factorforge_runtime_manifest__{report_id}.json"
    ).as_posix()
    runtime_path = workspace / runtime_relative
    (
        current_manifest,
        current_workspace,
        current_runtime_binding,
        _,
        current_workspace_binding,
        _,
    ) = _load_manifest(
        manifest_path=runtime_path,
        report_id=report_id,
        repo_root=repo_root,
    )
    _require(current_workspace == workspace, "receipt:native_workspace_mismatch")
    _require(
        current_manifest.get("factor_id") == factor_id
        and current_manifest.get("research_id") == research_id,
        "receipt:runtime_identity_mismatch",
    )
    runtime_binding = _closed(
        receipt["runtime_manifest_binding"],
        BASIC_FILE_BINDING_FIELDS,
        "receipt.runtime_manifest",
    )
    workspace_binding = _closed(
        receipt["workspace_manifest_binding"],
        WORKSPACE_MANIFEST_BINDING_FIELDS,
        "receipt.workspace_manifest",
    )
    _require(
        dict(runtime_binding) == current_runtime_binding,
        "receipt:runtime_manifest_replay",
    )
    _require(
        dict(workspace_binding) == current_workspace_binding,
        "receipt:workspace_manifest_replay",
    )
    _require(
        _binding_matches_current_file(
            workspace=workspace,
            binding=runtime_binding,
            label="receipt.runtime_manifest",
            expected_relative_path=runtime_relative,
        ),
        "receipt:runtime_manifest_path_replay",
    )
    _require(
        _binding_matches_current_file(
            workspace=workspace,
            binding=workspace_binding,
            label="receipt.workspace_manifest",
            expected_fields=WORKSPACE_MANIFEST_BINDING_FIELDS,
            expected_relative_path="manifest.json",
        ),
        "receipt:workspace_manifest_path_replay",
    )

    request_binding = _closed(
        receipt["request_binding"],
        BASIC_FILE_BINDING_FIELDS,
        "receipt.request",
    )
    _, request_raw = _read_current_bound_file(
        workspace=workspace,
        binding=request_binding,
        label="receipt.request",
        expected_fields=BASIC_FILE_BINDING_FIELDS,
        expected_parent=REQUEST_PARENT_NAME,
    )
    request_payload = _validate_request(
        _parse_json(request_raw, label="receipt.request"),
        hook=hook,
        report_id=report_id,
        factor_id=factor_id,
        repo_root=repo_root,
    )
    _require(
        receipt["diagnosis_target_scope"]
        == request_payload["diagnosis_target_scope"],
        "receipt:diagnosis_target_scope_replay",
    )

    official = receipt["official_artifact_bindings"]
    _require(isinstance(official, list), "receipt:official_bindings")
    expected_roles = [role for role, _ in OFFICIAL_ARTIFACTS[hook]]
    _require(len(official) == len(expected_roles), "receipt:official_exact_count")
    for ordinal, (row, role) in enumerate(zip(official, expected_roles)):
        closed_row = _closed(
            row,
            OFFICIAL_ARTIFACT_BINDING_FIELDS,
            f"receipt.official[{ordinal}]",
        )
        directory, stem = CANONICAL_OBJECT_PATHS[role]
        expected_relative = (
            Path("objects") / directory / f"{stem}__{report_id}.json"
        ).as_posix()
        _require(
            closed_row["ordinal"] == ordinal
            and closed_row["artifact_role"] == role,
            f"receipt:official_role_order:{ordinal}",
        )
        _require(
            _binding_matches_current_file(
                workspace=workspace,
                binding=closed_row,
                label=f"receipt.official.{role}",
                expected_fields=OFFICIAL_ARTIFACT_BINDING_FIELDS,
                expected_relative_path=expected_relative,
            ),
            f"receipt:official_artifact_path_replay:{role}",
        )
    current_official, current_official_payloads, _ = _load_official_artifacts(
        manifest=current_manifest,
        workspace=workspace,
        hook=hook,
        report_id=report_id,
        factor_id=factor_id,
        research_id=research_id,
        branch_id=str(current_manifest.get("branch_id") or "main"),
    )
    _require(official == current_official, "receipt:official_artifact_replay")
    _require(
        framed_sha256(ARTIFACT_BINDING_DOMAIN, official)
        == receipt["official_artifact_binding_commitment"],
        "receipt:official_binding_commitment",
    )
    _require(
        receipt["derivation_ledger_validation"]
        == _validate_derivation_ledger(
            request=request_payload,
            official_payloads=current_official_payloads,
        ),
        "receipt:derivation_ledger_replay",
    )

    diagnosis_rows = receipt["diagnosis_input_bindings"]
    _require(isinstance(diagnosis_rows, list), "receipt:diagnosis_bindings")
    _require(
        framed_sha256(
            DIAGNOSIS_INPUT_BINDING_DOMAIN,
            {
                "root_binding": receipt["diagnosis_input_root_binding"],
                "input_bindings": diagnosis_rows,
            },
        )
        == receipt["diagnosis_input_binding_commitment"],
        "receipt:diagnosis_binding_commitment",
    )
    if hook == HOOK_FAILURE:
        _require(len(diagnosis_rows) == 3, "receipt:diagnosis_exact3")
        root_binding = _closed(
            receipt["diagnosis_input_root_binding"],
            DIAGNOSIS_ROOT_BINDING_FIELDS,
            "receipt.diagnosis_root",
        )
        _require(
            root_binding["relative_path"] == DIAGNOSIS_INPUT_PARENT_NAME,
            "receipt:diagnosis_root_path",
        )
        diagnosis_root = _resolve_inside(
            workspace / DIAGNOSIS_INPUT_PARENT_NAME,
            workspace,
            label="receipt.diagnosis_root",
        )
        diagnosis_root_stat = diagnosis_root.stat()
        _require(
            diagnosis_root.parent == workspace
            and not os.path.ismount(diagnosis_root)
            and diagnosis_root_stat.st_dev == workspace_device
            and str(diagnosis_root_stat.st_dev) == root_binding["device"]
            and str(diagnosis_root_stat.st_ino) == root_binding["inode"],
            "receipt:diagnosis_root_replay",
        )
        expected_diagnosis_roles = [role for role, _, _ in DIAGNOSIS_PATH_ROLES]
        for ordinal, (row, role) in enumerate(
            zip(diagnosis_rows, expected_diagnosis_roles)
        ):
            closed_row = _closed(
                row,
                DIAGNOSIS_INPUT_BINDING_FIELDS,
                f"receipt.diagnosis[{ordinal}]",
            )
            _require(
                closed_row["ordinal"] == ordinal
                and closed_row["input_role"] == role
                and closed_row["candidate_root_only"] is True,
                f"receipt:diagnosis_role_order:{ordinal}",
            )
            _require(
                _binding_matches_current_file(
                    workspace=workspace,
                    binding=closed_row,
                    label=f"receipt.diagnosis.{role}",
                    expected_fields=DIAGNOSIS_INPUT_BINDING_FIELDS,
                    expected_parent=DIAGNOSIS_INPUT_PARENT_NAME,
                ),
                f"receipt:diagnosis_input_path_replay:{role}",
            )
        _, current_root_binding, current_diagnosis_rows, _ = (
            _load_diagnosis_inputs(
                kernel_input=request_payload["kernel_input_candidate"],
                workspace=workspace,
            )
        )
        _require(
            dict(root_binding) == current_root_binding
            and diagnosis_rows == current_diagnosis_rows,
            "receipt:diagnosis_input_replay",
        )
        formal_binding = _closed(
            receipt["formal_proof_binding"],
            FORMAL_PROOF_BINDING_FIELDS,
            "receipt.formal_proof",
        )
        formal_relative = (
            Path("objects")
            / "runtime_context"
            / f"ultimate_run_report__{report_id}.json"
        ).as_posix()
        _require(
            formal_binding["oos_used"] is False
            and _binding_matches_current_file(
                workspace=workspace,
                binding=formal_binding,
                label="receipt.formal_proof",
                expected_fields=FORMAL_PROOF_BINDING_FIELDS,
                expected_relative_path=formal_relative,
            ),
            "receipt:formal_proof_path_replay",
        )
        _, current_formal_binding, _ = _load_post_step5_formal_proof(
            proof_path=workspace / formal_relative,
            expected_raw_sha256=str(formal_binding["raw_sha256"]),
            manifest_path=runtime_path,
            manifest=current_manifest,
            workspace=workspace,
            report_id=report_id,
        )
        _require(
            dict(formal_binding) == current_formal_binding,
            "receipt:formal_proof_replay",
        )
        _require(
            isinstance(receipt["formal_artifact_snapshot"], Mapping),
            "receipt:formal_artifact_snapshot_required",
        )
        _validate_formal_artifact_snapshot(
            receipt["formal_artifact_snapshot"],
            report_id=report_id,
            factor_id=factor_id,
            research_id=research_id,
            current_bindings=current_official,
            formal_proof_binding=current_formal_binding,
        )
    else:
        _require(diagnosis_rows == [], "receipt:diagnosis_forbidden")
        _require(
            receipt["diagnosis_input_root_binding"] is None,
            "receipt:diagnosis_root_forbidden",
        )
        _require(
            receipt["formal_proof_binding"] is None,
            "receipt:formal_proof_forbidden",
        )
        _require(
            receipt["formal_artifact_snapshot"] is None,
            "receipt:formal_artifact_snapshot_forbidden",
        )
    expected_run_id = "shadow_" + framed_sha256(
        RUN_ID_DOMAIN,
        {
            "hook": hook,
            "report_id": report_id,
            "request_binding": dict(request_binding),
            "runtime_manifest_binding": dict(runtime_binding),
            "workspace_manifest_binding": dict(workspace_binding),
            "official_artifact_binding_commitment": receipt[
                "official_artifact_binding_commitment"
            ],
            "formal_proof_binding": receipt["formal_proof_binding"],
            "formal_artifact_snapshot_content_sha256": (
                receipt["formal_artifact_snapshot"]["content_sha256"]
                if receipt["formal_artifact_snapshot"] is not None
                else None
            ),
            "diagnosis_input_binding_commitment": receipt[
                "diagnosis_input_binding_commitment"
            ],
            "kernel_candidate_content_sha256": receipt[
                "kernel_candidate_content_sha256"
            ],
        },
    )[:32]
    _require(
        receipt["shadow_run_id"] == expected_run_id,
        "receipt:run_id_derivation_replay",
    )
    return receipt


__all__ = [
    "AUTHORITY_EFFECT",
    "capture_failure_artifact_snapshot",
    "DIAGNOSIS_INPUT_PARENT_NAME",
    "EpistemicUltimateShadowError",
    "HOOK_FAILURE",
    "HOOK_STEP1",
    "ISOLATION_POLICY",
    "REQUEST_PARENT_NAME",
    "REQUEST_SCHEMA_ID",
    "RESULT_SCHEMA_ID",
    "run_ultimate_epistemic_shadow",
    "validate_native_factor_workspace",
    "validate_ultimate_epistemic_shadow_package",
]
