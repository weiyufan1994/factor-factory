#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.child_materialization import (
    validate_child_materialization_readback,
)
from factor_factory.research_org.contracts import ResearchOrganizationError
from factor_factory.research_org.runtime_trust import load_runtime_trust_store

APPROVAL_VERSION = "factorforge_main_agent_multibranch_synthesis_approval_v1"
MATERIALIZATION_VERSION = "factorforge_multibranch_child_materialization_v1"
TOKEN_NOT_ENABLED = "BLOCK_FACTORFORGE_MULTIBRANCH_MATERIALIZATION_NOT_ENABLED"
TOKEN_APPROVAL_MISSING = "BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_MISSING"
TOKEN_APPROVAL_INVALID = "BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_INVALID"
TOKEN_SOURCE_CHANGED = "BLOCK_FACTORFORGE_MULTIBRANCH_SOURCE_SYNTHESIS_CHANGED"
TOKEN_ADAPTER_CHANGED = "BLOCK_FACTORFORGE_MULTIBRANCH_ADAPTER_SYNTHESIS_CHANGED"
TOKEN_FAILED = "BLOCK_FACTORFORGE_MULTIBRANCH_MATERIALIZATION_FAILED"
TOKEN_CHILD_COLLISION = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_ID_COLLISION"
TOKEN_DUP_HASH = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_FORMULA_DUPLICATE"
TOKEN_PREFLIGHT_FAILED = "BLOCK_FACTORFORGE_MULTIBRANCH_PREFLIGHT_FAILED"
TOKEN_INCIDENT_CONTEXT_REQUIRED = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_REQUIRED"
)
TOKEN_INCIDENT_CONTEXT_INCOMPLETE = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_INCOMPLETE"
)
TOKEN_INCIDENT_CONTEXT_INVALID = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_INVALID"
)
TOKEN_INCIDENT_CONTEXT_MISMATCH = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_RUNTIME_TRUST_CONTEXT_MISMATCH"
)
OOS_HOST_TRUST_ROOT_ENV = "FACTORFORGE_OOS_HOST_TRUST_ROOT"
OOS_HOST_INSTALLATION_ID_ENV = "FACTORFORGE_OOS_HOST_INSTALLATION_ID"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[WRITE] {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if text else ""


def resolve_incident_host_context(
    trust_root_raw: str | None,
    installation_id_raw: str | None,
) -> tuple[Path, str]:
    """Require one explicit, pre-existing Host pair for this mutating CLI."""

    trust_raw = str(trust_root_raw or "").strip()
    installation_id = str(installation_id_raw or "").strip()
    if bool(trust_raw) != bool(installation_id):
        raise ValueError(TOKEN_INCIDENT_CONTEXT_INCOMPLETE)
    if not trust_raw:
        raise ValueError(TOKEN_INCIDENT_CONTEXT_REQUIRED)
    try:
        trust_root = Path(trust_raw).expanduser().resolve(strict=True)
        load_runtime_trust_store(
            trust_root,
            installation_id=installation_id,
        )
    except (OSError, ValueError, ResearchOrganizationError) as exc:
        raise ValueError(TOKEN_INCIDENT_CONTEXT_INVALID) from exc

    ambient_trust = str(os.environ.get(OOS_HOST_TRUST_ROOT_ENV) or "").strip()
    ambient_installation = str(
        os.environ.get(OOS_HOST_INSTALLATION_ID_ENV) or ""
    ).strip()
    if bool(ambient_trust) != bool(ambient_installation):
        raise ValueError(TOKEN_INCIDENT_CONTEXT_MISMATCH)
    if ambient_trust:
        try:
            ambient_root = Path(ambient_trust).expanduser().resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ValueError(TOKEN_INCIDENT_CONTEXT_MISMATCH) from exc
        if ambient_root != trust_root or ambient_installation != installation_id:
            raise ValueError(TOKEN_INCIDENT_CONTEXT_MISMATCH)
    return trust_root, installation_id


def council_dir(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def approval_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis_approval__{report_id}.json"


def aggregate_report_path(root: Path, report_id: str, loop_index: int) -> Path:
    return root / "objects" / "runtime_context" / f"multibranch_child_materialization__{report_id}__loop{loop_index:02d}.json"


def child_materialization_report_path(root: Path, parent: str, child: str) -> Path:
    digest = hashlib.sha256(f"{parent}\0{child}".encode("utf-8")).hexdigest()[:16]
    short_parent = parent[:40].rstrip("_")
    short_child = child[:40].rstrip("_")
    filename = f"child_revision_materialization__{short_parent}__{short_child}__{digest}.json"
    return root / "objects" / "runtime_context" / filename


def object_path(root: Path, kind: str, report_id: str) -> Path:
    names = {
        "alpha_idea_master": ("alpha_idea_master", f"alpha_idea_master__{report_id}.json"),
        "factor_spec_master": ("factor_spec_master", f"factor_spec_master__{report_id}.json"),
        "data_prep_master": ("data_prep_master", f"data_prep_master__{report_id}.json"),
        "qlib_adapter_config": ("data_prep_master", f"qlib_adapter_config__{report_id}.json"),
        "handoff_to_step3": ("handoff", f"handoff_to_step3__{report_id}.json"),
        "handoff_to_step4": ("handoff", f"handoff_to_step4__{report_id}.json"),
        "executable_revision_spec": ("research_iteration_master", f"executable_revision_spec__{report_id}.json"),
    }
    rel_dir, name = names[kind]
    return root / "objects" / rel_dir / name


def executable_revision_spec_path(root: Path, child: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child}.json"


def resolved_path(root: Path, raw: Any) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if path.is_absolute():
        return path
    candidates = [root / path]
    parts = path.parts
    if parts and parts[0] == root.name:
        candidates.append(root.parent / path)
        candidates.append(root / Path(*parts[1:]))
    candidates.append(root.parent / path)
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def resolved_daily_sources(root: Path, data_prep: dict[str, Any]) -> dict[str, Path]:
    local_inputs = data_prep.get("local_input_paths")
    if not isinstance(local_inputs, dict):
        return {}
    sources: dict[str, Path] = {}
    for suffix, key in (("parquet", "daily_df_parquet"), ("csv", "daily_df_csv")):
        path = resolved_path(root, local_inputs.get(key))
        if path and path.exists():
            sources[suffix] = path
    return sources


def child_daily_input_path(root: Path, child: str, suffix: str) -> Path:
    return root / "runs" / child / "step3a_local_inputs" / f"daily_input__{child}.{suffix}"


def child_daily_meta_path(root: Path, child: str) -> Path:
    return root / "runs" / child / "step3a_local_inputs" / f"daily_input_meta__{child}.json"


def planned_target_paths(root: Path, parent: str, child: str, parent_data_prep: dict[str, Any]) -> dict[str, Path]:
    targets = {
        "alpha_idea_master": object_path(root, "alpha_idea_master", child),
        "factor_spec_master": object_path(root, "factor_spec_master", child),
        "data_prep_master": object_path(root, "data_prep_master", child),
        "qlib_adapter_config": object_path(root, "qlib_adapter_config", child),
        "executable_revision_spec": object_path(root, "executable_revision_spec", child),
        "materialization_report": child_materialization_report_path(root, parent, child),
    }
    for suffix, source in resolved_daily_sources(root, parent_data_prep).items():
        if source.exists():
            targets[f"child_daily_input_{suffix}"] = child_daily_input_path(root, child, suffix)
    local_inputs = parent_data_prep.get("local_input_paths")
    if isinstance(local_inputs, dict):
        meta_source = resolved_path(root, local_inputs.get("daily_input_meta_json"))
        if meta_source and meta_source.exists():
            targets["child_daily_input_meta_json"] = child_daily_meta_path(root, child)
    for kind in ("handoff_to_step3", "handoff_to_step4"):
        if object_path(root, kind, parent).exists():
            targets[kind] = object_path(root, kind, child)
    return targets


def artifact_identity_report_id(payload: dict[str, Any]) -> str:
    identity = payload.get("artifact_identity") if isinstance(payload.get("artifact_identity"), dict) else {}
    return str(identity.get("report_id") or payload.get("report_id") or "")


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(payload, ensure_ascii=False))
    for key in ("report_id", "artifact_identity", "lineage_repair", "created_at_utc", "updated_at_utc"):
        clone.pop(key, None)
    return clone


def validate_lineage_repair(root: Path, report_id: str, artifact_kind: str, payload: dict[str, Any], path: Path) -> dict[str, Any]:
    repair = payload.get("lineage_repair")
    if not isinstance(repair, dict):
        return {"status": "not_repaired", "path": str(path)}
    if repair.get("status") != "pass" or repair.get("target_report_id") != report_id or repair.get("artifact_kind") != artifact_kind:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: invalid lineage_repair for {artifact_kind}")
    source_raw = repair.get("source_artifact_path")
    source_sha = repair.get("source_artifact_sha256")
    if not isinstance(source_raw, str) or not source_raw or not isinstance(source_sha, str) or not source_sha:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: lineage_repair source identity missing for {artifact_kind}")
    source_path = Path(source_raw).expanduser()
    if not source_path.is_absolute():
        source_path = root / source_path
    if not source_path.exists() or sha256_file(source_path) != source_sha:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: lineage_repair source artifact changed for {artifact_kind}")
    if repair.get("repair_scope") != "identity_wrapper_only":
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: lineage_repair scope must be identity_wrapper_only for {artifact_kind}")
    semantic_before = str(repair.get("semantic_payload_sha256_before") or "")
    semantic_after = str(repair.get("semantic_payload_sha256_after") or "")
    current_semantic = stable_hash(semantic_payload(payload))
    source_semantic = stable_hash(semantic_payload(load_json(source_path)))
    if not semantic_before or not semantic_after or semantic_before != semantic_after:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: lineage_repair semantic hash contract invalid for {artifact_kind}")
    if current_semantic != semantic_after:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: repaired {artifact_kind} semantic payload changed after repair")
    if source_semantic != semantic_before:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: lineage_repair source semantic payload changed for {artifact_kind}")
    return {
        "status": "repaired",
        "path": str(path),
        "source_report_id": repair.get("source_report_id"),
        "source_artifact_sha256": source_sha,
    }


def validate_required_parent_artifact(root: Path, report_id: str, artifact_kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = object_path(root, artifact_kind, report_id)
    if not path.exists():
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: parent {artifact_kind} missing at {path}")
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: parent {artifact_kind} is not a JSON object")
    observed_report_id = artifact_identity_report_id(payload)
    if observed_report_id != report_id:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: parent {artifact_kind} report_id mismatch: {observed_report_id!r}")
    repair_status = validate_lineage_repair(root, report_id, artifact_kind, payload, path)
    return payload, {
        "artifact_kind": artifact_kind,
        "path": str(path),
        "sha256": sha256_file(path),
        "lineage_repair": repair_status,
    }


def validate_direct_code_law(branch: dict[str, Any]) -> dict[str, Any]:
    implementation_mode = str(branch.get("implementation_mode") or "")
    child_formula = str(branch.get("child_formula") or "")
    contract = branch.get("direct_code_revision_contract") if isinstance(branch.get("direct_code_revision_contract"), dict) else {}
    embedded_law_id = child_formula.removeprefix("direct_code_law:").strip() if child_formula.startswith("direct_code_law:") else ""
    contract_law_id = str(contract.get("code_law_id") or "").strip()
    branch_law_id = str(branch.get("law_id") or "").strip()
    law_id = contract_law_id or branch_law_id or embedded_law_id
    if implementation_mode != "direct_code" and not child_formula.startswith("direct_code_law:"):
        return {"status": "not_applicable"}
    if not law_id:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: direct_code branch law_id missing")
    declared_law_ids = {item for item in (contract_law_id, branch_law_id, embedded_law_id) if item}
    if len(declared_law_ids) > 1:
        raise ValueError(
            f"{TOKEN_PREFLIGHT_FAILED}: direct_code law identity mismatch: "
            f"branch_law_id={branch_law_id!r} code_law_id={contract_law_id!r} child_formula_law_id={embedded_law_id!r}"
        )
    try:
        from factor_factory.factor_laws.moneyflow.registry import resolve_law

        resolved = resolve_law(law_id)
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: direct_code law unavailable: {law_id}: {exc}") from exc
    return {
        "status": "available",
        "law_id": law_id,
        "law_hash": resolved.code_law_hash,
        "implementation_mode": "direct_code",
    }


def preflight_materialization(root: Path, report_id: str, approval: dict[str, Any], *, check_child_targets: bool = True) -> dict[str, Any]:
    parent_payloads: dict[str, dict[str, Any]] = {}
    parent_artifacts: list[dict[str, Any]] = []
    for artifact_kind in ("alpha_idea_master", "factor_spec_master", "data_prep_master"):
        payload, status = validate_required_parent_artifact(root, report_id, artifact_kind)
        parent_payloads[artifact_kind] = payload
        parent_artifacts.append(status)

    data_prep = parent_payloads["data_prep_master"]
    declared_sources = []
    local_inputs = data_prep.get("local_input_paths") if isinstance(data_prep.get("local_input_paths"), dict) else {}
    for key in ("daily_df_parquet", "daily_df_csv"):
        if local_inputs.get(key):
            path = resolved_path(root, local_inputs.get(key))
            if not path or not path.exists():
                raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: parent data source missing: {key}")
            declared_sources.append({"key": key, "path": str(path), "sha256": sha256_file(path)})
    if not declared_sources:
        raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: parent data source missing: daily_df_parquet or daily_df_csv must be declared")

    target_paths: list[dict[str, Any]] = []
    direct_code_laws: list[dict[str, Any]] = []
    seen_targets: dict[Path, str] = {}
    for branch in approval.get("selected_branches") or []:
        child = str(branch.get("child_report_id") or "")
        if not child:
            raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: child_report_id missing")
        if check_child_targets:
            for kind, path in planned_target_paths(root, report_id, child, data_prep).items():
                if path in seen_targets:
                    raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: child target collision between {seen_targets[path]} and {child}: {path}")
                seen_targets[path] = child
                if path.exists():
                    raise ValueError(f"{TOKEN_PREFLIGHT_FAILED}: child target already exists: {kind} {path}")
                target_paths.append({"child_report_id": child, "kind": kind, "path": str(path)})
        direct_code_laws.append({"child_report_id": child, **validate_direct_code_law(branch)})

    return {
        "contract_version": "factorforge_multibranch_materialization_preflight_v1",
        "status": "pass",
        "checked_at_utc": utc_now(),
        "parent_report_id": report_id,
        "parent_artifacts": parent_artifacts,
        "declared_daily_sources": declared_sources,
        "child_target_collision_checked": check_child_targets,
        "child_target_paths": target_paths,
        "direct_code_laws": direct_code_laws,
        "step4_backend_policy": {
            "status": "checked",
            "qlib_not_applicable_allowed_for_direct_code": True,
        },
    }


def validate_approval(root: Path, report_id: str, approval: dict[str, Any]) -> None:
    if approval.get("contract_version") != APPROVAL_VERSION:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: invalid contract_version")
    if approval.get("parent_report_id") != report_id:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: parent_report_id mismatch")
    if approval.get("canonical_write_permission") is not False:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: canonical_write_permission must be false")
    if approval.get("execution_allowed_by_default") is not False:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: execution_allowed_by_default must be false")
    if approval.get("human_approval_required") is not True:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: human_approval_required must be true")
    source_path_raw = approval.get("source_multibranch_synthesis_path")
    if not isinstance(source_path_raw, str) or not source_path_raw:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: source_multibranch_synthesis_path missing")
    source_path = Path(source_path_raw).expanduser()
    if not source_path.is_absolute():
        source_path = root / source_path
    if not source_path.exists():
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: source synthesis missing")
    current_sha = sha256_file(source_path)
    if approval.get("source_multibranch_synthesis_sha256") != current_sha:
        raise ValueError(f"{TOKEN_SOURCE_CHANGED}: source multibranch synthesis changed after approval")
    branches = approval.get("selected_branches")
    if not isinstance(branches, list) or not branches:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: selected_branches missing")
    child_ids: set[str] = set()
    child_hashes: set[str] = set()
    for idx, raw in enumerate(branches):
        branch = raw if isinstance(raw, dict) else {}
        child = str(branch.get("child_report_id") or "")
        child_hash = str(branch.get("child_formula_hash") or "")
        law_id = str(branch.get("law_id") or "")
        branch_role = str(branch.get("branch_role") or "")
        if not child or not child_hash:
            raise ValueError(f"{TOKEN_APPROVAL_INVALID}: branch[{idx}] child identity missing")
        if child == report_id or child in child_ids:
            raise ValueError(f"{TOKEN_CHILD_COLLISION}: branch[{idx}]")
        if child_hash in child_hashes:
            raise ValueError(f"{TOKEN_DUP_HASH}: branch[{idx}]")
        adapter_path_raw = branch.get("adapter_synthesis_path")
        adapter_sha = str(branch.get("adapter_synthesis_sha256") or "")
        if not isinstance(adapter_path_raw, str) or not adapter_path_raw or not adapter_sha:
            raise ValueError(f"{TOKEN_APPROVAL_INVALID}: branch[{idx}] adapter synthesis identity missing")
        adapter_path = Path(adapter_path_raw).expanduser()
        if not adapter_path.is_absolute():
            adapter_path = root / adapter_path
        if not adapter_path.exists():
            raise ValueError(f"{TOKEN_APPROVAL_INVALID}: branch[{idx}] adapter synthesis missing")
        if sha256_file(adapter_path) != adapter_sha:
            raise ValueError(f"{TOKEN_ADAPTER_CHANGED}: branch[{idx}] adapter synthesis changed after approval")
        adapter = load_json(adapter_path)
        selected = adapter.get("selected_revision") if isinstance(adapter.get("selected_revision"), dict) else {}
        branch_context = adapter.get("branch_context") if isinstance(adapter.get("branch_context"), dict) else {}
        if (
            str(selected.get("child_formula") or "") != str(branch.get("child_formula") or "")
            or str(selected.get("law_id") or "") != law_id
            or str(branch_context.get("child_report_id") or "") != child
            or str(branch_context.get("law_id") or "") != law_id
            or str(branch_context.get("branch_role") or "") != branch_role
            or str(adapter.get("source_multibranch_synthesis_sha256") or "") != str(approval.get("source_multibranch_synthesis_sha256") or "")
        ):
            raise ValueError(f"{TOKEN_ADAPTER_CHANGED}: branch[{idx}] adapter synthesis content mismatch")
        child_ids.add(child)
        child_hashes.add(child_hash)


def run_child_materializer(
    root: Path,
    parent: str,
    branch: dict[str, Any],
    approval: dict[str, Any],
    *,
    incident_trust_root: Path | None,
    incident_installation_id: str | None,
    expected_host_trust_manifest_sha256: str | None,
) -> dict[str, Any]:
    child = str(branch["child_report_id"])
    branch_context = branch.get("branch_context") if isinstance(branch.get("branch_context"), dict) else {}
    command = [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
        "--parent-report-id",
        parent,
        "--child-report-id",
        child,
        "--factorforge-root",
        str(root),
        "--synthesis-path",
        str(branch["adapter_synthesis_path"]),
        "--branch-group-id",
        str(approval["branch_group_id"]),
        "--branch-index",
        str(branch["branch_index"]),
        "--branch-role",
        str(branch["branch_role"]),
        "--branch-law-id",
        str(branch.get("law_id") or branch_context.get("law_id")),
        "--source-multibranch-synthesis-path",
        str(approval["source_multibranch_synthesis_path"]),
        "--source-multibranch-synthesis-sha256",
        str(approval["source_multibranch_synthesis_sha256"]),
        "--sibling-branch-count",
        str(approval["selected_branch_count"]),
    ]
    if incident_trust_root is not None and incident_installation_id:
        command.extend(
            [
                "--incident-trust-root",
                str(incident_trust_root),
                "--incident-installation-id",
                incident_installation_id,
            ]
        )
    if expected_host_trust_manifest_sha256:
        command.extend(
            [
                "--expected-host-trust-manifest-sha256",
                expected_host_trust_manifest_sha256,
            ]
        )
    env = dict(os.environ)
    env.pop(OOS_HOST_TRUST_ROOT_ENV, None)
    env.pop(OOS_HOST_INSTALLATION_ID_ENV, None)
    if incident_trust_root is not None and incident_installation_id:
        env[OOS_HOST_TRUST_ROOT_ENV] = str(incident_trust_root)
        env[OOS_HOST_INSTALLATION_ID_ENV] = incident_installation_id
    env["FACTORFORGE_ROOT"] = str(root)
    env["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
    proc = subprocess.run(command, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    materialization_path = child_materialization_report_path(root, parent, child)
    spec_path = executable_revision_spec_path(root, child)
    return {
        "child_report_id": child,
        "branch_role": branch.get("branch_role"),
        "branch_index": branch.get("branch_index"),
        "law_id": branch.get("law_id") or branch_context.get("law_id"),
        "child_formula_hash": branch.get("child_formula_hash"),
        "materialization_command": command,
        "materialization_rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "materialization_report_path": str(materialization_path),
        "executable_revision_spec_path": str(spec_path),
        "materialization_report_exists": materialization_path.exists(),
        "executable_revision_spec_exists": spec_path.exists(),
    }


def existing_materialization_reusable(
    root: Path,
    report_id: str,
    approval: dict[str, Any],
    *,
    loop_index: int,
    incident_trust_root: Path | None,
    incident_installation_id: str | None,
    expected_host_trust_manifest_sha256: str | None,
) -> dict[str, Any] | None:
    path = aggregate_report_path(root, report_id, loop_index)
    if not path.exists():
        return None
    report = load_json(path)
    if (
        report.get("contract_version") != MATERIALIZATION_VERSION
        or report.get("status") != "PASS"
        or report.get("parent_report_id") != report_id
        or int(report.get("loop_index") or -1) != loop_index
        or str(report.get("source_multibranch_synthesis_sha256") or "") != str(approval.get("source_multibranch_synthesis_sha256") or "")
        or int(report.get("selected_branch_count") or -1) != int(approval.get("selected_branch_count") or -2)
    ):
        return None
    children = report.get("children") if isinstance(report.get("children"), list) else []
    branches = approval.get("selected_branches") if isinstance(approval.get("selected_branches"), list) else []
    if len(children) != len(branches):
        return None
    by_child = {str(child.get("child_report_id") or ""): child for child in children if isinstance(child, dict)}
    current_revalidations: list[dict[str, Any]] = []
    for branch in branches:
        child_id = str(branch.get("child_report_id") or "")
        child = by_child.get(child_id)
        if not child:
            return None
        expected = {
            "branch_role": str(branch.get("branch_role") or ""),
            "branch_index": int(branch.get("branch_index") or -1),
            "law_id": str(branch.get("law_id") or ""),
            "child_formula_hash": str(branch.get("child_formula_hash") or ""),
        }
        actual = {
            "branch_role": str(child.get("branch_role") or ""),
            "branch_index": int(child.get("branch_index") or -1),
            "law_id": str(child.get("law_id") or ""),
            "child_formula_hash": str(child.get("child_formula_hash") or ""),
        }
        if actual != expected:
            return None
        report_path_raw = str(child.get("materialization_report_path") or "")
        spec_path_raw = str(child.get("executable_revision_spec_path") or "")
        if not report_path_raw or not spec_path_raw:
            return None
        report_path = Path(report_path_raw)
        spec_path = Path(spec_path_raw)
        if not report_path.is_absolute():
            report_path = root / report_path
        if not spec_path.is_absolute():
            spec_path = root / spec_path
        if not report_path.exists() or not spec_path.exists():
            return None
        child_report = load_json(report_path)
        child_spec = load_json(spec_path)
        if (
            str(child_report.get("child_report_id") or "") != child_id
            or str(child_report.get("child_formula_hash") or "") != expected["child_formula_hash"]
            or str(child_spec.get("child_report_id") or "") != child_id
            or str(child_spec.get("child_formula_hash") or "") != expected["child_formula_hash"]
        ):
            return None
        parent_handoff = (
            root
            / "objects"
            / "handoff"
            / f"handoff_to_step3b__{report_id}.json"
        )
        if not parent_handoff.is_file() or parent_handoff.is_symlink():
            return None
        if validate_child_materialization_readback(
            workspace_root=root,
            report_path=report_path,
            parent_report_id=report_id,
            child_report_id=child_id,
            source_handoff_sha256=sha256_file(parent_handoff),
            required_target_kinds={
                "alpha_idea_master",
                "factor_spec_master",
                "data_prep_master",
                "executable_revision_spec",
                "qlib_adapter_config",
                "state_dependency_contract",
                "state_resolution",
            },
        ):
            return None
        # A structural aggregate/report replay cannot authorize current reuse.
        # Re-enter the canonical child materializer: for EVO/pre-OOS children it
        # replays preregistration, fresh allocation, and Web authority before its
        # idempotent readback while the incident registry is the outermost lock.
        current = run_child_materializer(
            root,
            report_id,
            branch,
            approval,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        current_revalidations.append(current)
        if current["materialization_rc"] != 0:
            detail = (
                f"{current.get('stdout_tail') or ''}\n"
                f"{current.get('stderr_tail') or ''}"
            ).strip()
            raise ValueError(
                f"{TOKEN_FAILED}:current_revalidation_failed:{child_id}:{detail}"
            )
    reused = dict(report)
    reused["materialization_reused"] = True
    reused["reused_existing_report_path"] = str(path)
    reused["current_authority_revalidations"] = current_revalidations
    return reused


def materialize(
    root: Path,
    report_id: str,
    *,
    loop_index: int,
    incident_trust_root: Path | None,
    incident_installation_id: str | None,
    expected_host_trust_manifest_sha256: str | None,
) -> dict[str, Any]:
    path = approval_path(root, report_id)
    if not path.exists():
        raise ValueError(TOKEN_APPROVAL_MISSING)
    approval = load_json(path)
    validate_approval(root, report_id, approval)
    try:
        reuse_preflight = preflight_materialization(root, report_id, approval, check_child_targets=False)
    except ValueError as exc:
        payload = base_report(root, report_id, approval, loop_index, [], status="BLOCK")
        payload["block_reason"] = TOKEN_PREFLIGHT_FAILED
        payload["preflight"] = {
            "contract_version": "factorforge_multibranch_materialization_preflight_v1",
            "status": "blocked",
            "checked_at_utc": utc_now(),
            "error": str(exc),
        }
        write_json(aggregate_report_path(root, report_id, loop_index), payload)
        raise
    existing = existing_materialization_reusable(
        root,
        report_id,
        approval,
        loop_index=loop_index,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    if existing is not None:
        existing["preflight"] = reuse_preflight
        print(f"SKIPPED_EXISTING_MULTIBRANCH_MATERIALIZATION: {aggregate_report_path(root, report_id, loop_index)}")
        return existing
    try:
        preflight = preflight_materialization(root, report_id, approval, check_child_targets=True)
    except ValueError as exc:
        payload = base_report(root, report_id, approval, loop_index, [], status="BLOCK", preflight=reuse_preflight)
        payload["block_reason"] = TOKEN_PREFLIGHT_FAILED
        payload["preflight"] = {
            "contract_version": "factorforge_multibranch_materialization_preflight_v1",
            "status": "blocked",
            "checked_at_utc": utc_now(),
            "error": str(exc),
            "reuse_preflight": reuse_preflight,
        }
        write_json(aggregate_report_path(root, report_id, loop_index), payload)
        raise
    children: list[dict[str, Any]] = []
    for branch in approval["selected_branches"]:
        result = run_child_materializer(
            root,
            report_id,
            branch,
            approval,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        children.append(result)
        if result["materialization_rc"] != 0:
            payload = base_report(root, report_id, approval, loop_index, children, status="BLOCK", preflight=preflight)
            payload["block_reason"] = TOKEN_FAILED
            write_json(aggregate_report_path(root, report_id, loop_index), payload)
            raise ValueError(TOKEN_FAILED)
    payload = base_report(root, report_id, approval, loop_index, children, status="PASS", preflight=preflight)
    write_json(aggregate_report_path(root, report_id, loop_index), payload)
    return payload


def base_report(
    root: Path,
    report_id: str,
    approval: dict[str, Any],
    loop_index: int,
    children: list[dict[str, Any]],
    *,
    status: str,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": MATERIALIZATION_VERSION,
        "created_at_utc": utc_now(),
        "status": status,
        "parent_report_id": report_id,
        "loop_index": loop_index,
        "branch_group_id": approval.get("branch_group_id"),
        "source_approval_path": str(approval_path(root, report_id)),
        "source_multibranch_synthesis_path": approval.get("source_multibranch_synthesis_path"),
        "source_multibranch_synthesis_sha256": approval.get("source_multibranch_synthesis_sha256"),
        "selected_branch_count": approval.get("selected_branch_count"),
        "children": children,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "clean_data_touched": False,
        "official_promotion_written": False,
        "preflight": preflight or {},
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Materialize all approved children from a main-agent multibranch synthesis approval.")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--loop-index", type=int, default=1)
    ap.add_argument("--expected-host-trust-manifest-sha256", default=None)
    ap.add_argument("--incident-trust-root", default=None)
    ap.add_argument("--incident-installation-id", default=None)
    ap.add_argument(
        "--allow-legacy-incident-context-smoke",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    ap.add_argument("--allow-manual", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if os.environ.get("FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE") != "1" and not args.allow_manual:
        print(TOKEN_NOT_ENABLED)
        return 1
    try:
        ctx = resolve_factorforge_context(args.factorforge_root)
        root = ctx.factorforge_root.expanduser().resolve(strict=True)
        legacy_smoke = bool(
            args.allow_legacy_incident_context_smoke
            and os.environ.get("FACTORFORGE_LEGACY_RESEARCH_PROTOCOL_SMOKE") == "1"
            and str(root).startswith(("/tmp/", "/private/tmp/"))
            and not args.incident_trust_root
            and not args.incident_installation_id
        )
        if legacy_smoke:
            incident_trust_root = None
            incident_installation_id = None
        else:
            incident_trust_root, incident_installation_id = (
                resolve_incident_host_context(
                    args.incident_trust_root,
                    args.incident_installation_id,
                )
            )
        if incident_trust_root is not None and (
            incident_trust_root == root
            or incident_trust_root in root.parents
            or root in incident_trust_root.parents
        ):
            raise ValueError(TOKEN_INCIDENT_CONTEXT_INVALID)
        report = materialize(
            root,
            args.report_id,
            loop_index=args.loop_index,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report.get("materialization_reused") is True:
        print("SKIPPED_EXISTING_MULTIBRANCH_MATERIALIZATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
