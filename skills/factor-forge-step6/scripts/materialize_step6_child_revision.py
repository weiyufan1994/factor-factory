#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.formula.parser import parse_formula
from factor_factory.artifact_identity import stable_hash

MATERIALIZATION_VERSION = "factorforge_step6_child_revision_materialization_v1"
EXECUTABLE_REVISION_SPEC_VERSION = "factorforge_executable_revision_spec_v1"
MAIN_AGENT_COUNCIL_SYNTHESIS_VERSION = "factorforge_main_agent_council_synthesis_v1"
TARGET_EXISTS_BLOCK = "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_TARGET_EXISTS"
DAILY_SNAPSHOT_MISSING_BLOCK = "BLOCK_FACTORFORGE_CHILD_DAILY_SNAPSHOT_MISSING"
SYNTHESIS_MISSING_BLOCK = "BLOCK_FACTORFORGE_MAIN_AGENT_COUNCIL_SYNTHESIS_MISSING"
CHILD_FORMULA_MISSING_BLOCK = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_CHILD_FORMULA_MISSING"
SELECTED_LAW_MISSING_BLOCK = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_SELECTED_LAW_MISSING"
METRIC_SIGNATURE_MISSING_BLOCK = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_METRIC_SIGNATURE_MISSING"
FALSIFICATION_MISSING_BLOCK = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FALSIFICATION_MISSING"
KILL_CRITERIA_MISSING_BLOCK = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_KILL_CRITERIA_MISSING"
ORCHESTRATOR_MISMATCH_BLOCK = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_ORCHESTRATOR_MISMATCH"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def object_path(root: Path, kind: str, report_id: str) -> Path:
    names = {
        "alpha_idea_master": ("alpha_idea_master", f"alpha_idea_master__{report_id}.json"),
        "factor_spec_master": ("factor_spec_master", f"factor_spec_master__{report_id}.json"),
        "data_prep_master": ("data_prep_master", f"data_prep_master__{report_id}.json"),
        "qlib_adapter_config": ("data_prep_master", f"qlib_adapter_config__{report_id}.json"),
        "handoff_to_step3": ("handoff", f"handoff_to_step3__{report_id}.json"),
        "handoff_to_step4": ("handoff", f"handoff_to_step4__{report_id}.json"),
        "handoff_to_step3b": ("handoff", f"handoff_to_step3b__{report_id}.json"),
        "research_iteration_master": ("research_iteration_master", f"research_iteration_master__{report_id}.json"),
        "executable_revision_spec": ("research_iteration_master", f"executable_revision_spec__{report_id}.json"),
    }
    rel_dir, name = names[kind]
    return root / "objects" / rel_dir / name


def materialization_report_path(root: Path, parent: str, child: str) -> Path:
    digest = hashlib.sha256(f"{parent}\0{child}".encode("utf-8")).hexdigest()[:16]
    short_parent = parent[:40].rstrip("_")
    short_child = child[:40].rstrip("_")
    filename = f"child_revision_materialization__{short_parent}__{short_child}__{digest}.json"
    return root / "objects" / "runtime_context" / filename


def child_daily_input_path(root: Path, child: str, suffix: str) -> Path:
    return root / "runs" / child / "step3a_local_inputs" / f"daily_input__{child}.{suffix}"


def child_daily_meta_path(root: Path, child: str) -> Path:
    return root / "runs" / child / "step3a_local_inputs" / f"daily_input_meta__{child}.json"


def resolved_path(root: Path, raw: Any) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if path.is_absolute():
        if path.exists():
            return path
        parts = path.parts
        for anchor in ("runs", "objects", "generated_code", "knowledge"):
            if anchor not in parts:
                continue
            idx = parts.index(anchor)
            candidate = root.joinpath(*parts[idx:])
            if candidate.exists():
                return candidate
        return path
    candidates = [root / path]
    parts = path.parts
    if parts and parts[0] == root.name:
        candidates.append(root.parent / path)
        candidates.append(root / Path(*parts[1:]))
    candidates.append(root.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


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


def declared_daily_source_keys(data_prep: dict[str, Any]) -> list[str]:
    local_inputs = data_prep.get("local_input_paths")
    if not isinstance(local_inputs, dict):
        return []
    return [key for key in ("daily_df_parquet", "daily_df_csv") if local_inputs.get(key)]


def planned_target_paths(root: Path, parent: str, child: str, parent_data_prep: dict[str, Any]) -> dict[str, Path]:
    targets = {
        "alpha_idea_master": object_path(root, "alpha_idea_master", child),
        "factor_spec_master": object_path(root, "factor_spec_master", child),
        "data_prep_master": object_path(root, "data_prep_master", child),
        "executable_revision_spec": object_path(root, "executable_revision_spec", child),
        "materialization_report": materialization_report_path(root, parent, child),
    }
    for suffix, source in resolved_daily_sources(root, parent_data_prep).items():
        if source.exists():
            targets[f"child_daily_input_{suffix}"] = child_daily_input_path(root, child, suffix)
    local_inputs = parent_data_prep.get("local_input_paths")
    if isinstance(local_inputs, dict):
        meta_source = resolved_path(root, local_inputs.get("daily_input_meta_json"))
        if meta_source and meta_source.exists():
            targets["child_daily_input_meta_json"] = child_daily_meta_path(root, child)
    for kind in ("qlib_adapter_config", "handoff_to_step3", "handoff_to_step4"):
        if object_path(root, kind, parent).exists():
            targets[kind] = object_path(root, kind, child)
    return targets


def ensure_child_qlib_adapter_config(root: Path, parent: str, child: str) -> dict[str, Any]:
    parent_cfg = object_path(root, "qlib_adapter_config", parent)
    child_cfg = object_path(root, "qlib_adapter_config", child)
    if parent_cfg.exists():
        payload = rewrite_common(
            load_json(parent_cfg),
            child_report_id=child,
            branch_id=None,
            parent_run_id=None,
            artifact_role="qlib_adapter_config",
            producer="ultimate_loop_child_materializer",
        )
        payload["parent_qlib_adapter_config_ref"] = str(parent_cfg)
        payload["qlib_adapter_config_lineage"] = {
            "version": "factorforge_child_qlib_adapter_config_lineage_v1",
            "parent_report_id": parent,
            "child_report_id": child,
            "parent_qlib_adapter_config_path": str(parent_cfg),
            "parent_qlib_adapter_config_sha256": sha256_file(parent_cfg),
            "status": "copied_from_parent",
        }
        status = "copied_from_parent"
    else:
        payload = {
            "version": "factorforge_qlib_adapter_config_v1",
            "report_id": child,
            "producer": "ultimate_loop_child_materializer",
            "status": "not_applicable",
            "qlib_native_status": "not_applicable",
            "reason": "direct_code_derived_state_not_supported_by_qlib",
            "parent_report_id": parent,
            "created_at_utc": utc_now(),
            "qlib_adapter_config_lineage": {
                "version": "factorforge_child_qlib_adapter_config_lineage_v1",
                "parent_report_id": parent,
                "child_report_id": child,
                "parent_qlib_adapter_config_path": str(parent_cfg),
                "status": "not_applicable_created",
            },
        }
        status = "not_applicable_created"
    write_json(child_cfg, payload)

    child_handoff = object_path(root, "handoff_to_step4", child)
    if child_handoff.exists():
        handoff = load_json(child_handoff)
        handoff["qlib_adapter_config_ref"] = child_cfg.name
        handoff["qlib_adapter_config_path"] = str(child_cfg)
        handoff.setdefault("qlib_adapter_config_lineage", payload.get("qlib_adapter_config_lineage"))
        write_json(child_handoff, handoff)

    return {"status": status, "path": str(child_cfg)}


def executable_revision_spec_path(root: Path, child: str) -> Path:
    return object_path(root, "executable_revision_spec", child)


def default_orchestrator_synthesis_path(root: Path, parent: str) -> Path:
    return (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / parent
        / f"main_agent_council_synthesis__{parent}.json"
    )


def formula_hash(formula_text: str) -> str:
    parsed = parse_formula(formula_text)
    if parsed.get("parse_status") != "success":
        raise ValueError("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED: " + "; ".join(parsed.get("parse_errors") or []))
    return str(parsed.get("formula_hash") or "")


def parent_formula_hash_for_audit(formula_text: str) -> str:
    parsed = parse_formula(formula_text)
    if parsed.get("parse_status") == "success":
        return str(parsed.get("formula_hash") or "")
    return stable_hash(
        {
            "formula_text": formula_text,
            "parse_status": "not_formula_ir_parent",
            "parse_errors": parsed.get("parse_errors") or [],
            "hash_role": "parent_formula_audit_hash",
        }
    )


def child_formula_or_law(selected: dict[str, Any]) -> str:
    return (
        nonempty_str(selected.get("child_formula"))
        or nonempty_str(selected.get("child_formula_or_law"))
        or nonempty_str(selected.get("direct_code_law"))
        or nonempty_str(selected.get("formula_law"))
    )


def selected_implementation_mode(parent_spec: dict[str, Any], parent_handoff: dict[str, Any], selected: dict[str, Any]) -> str:
    explicit = nonempty_str(selected.get("implementation_mode"))
    if explicit:
        return explicit
    if isinstance(selected.get("direct_code_revision_contract"), dict) and selected["direct_code_revision_contract"]:
        return "direct_code"
    identity = parent_spec.get("artifact_identity") if isinstance(parent_spec.get("artifact_identity"), dict) else {}
    contract = parent_spec.get("implementation_contract") if isinstance(parent_spec.get("implementation_contract"), dict) else {}
    mode = (
        nonempty_str(identity.get("implementation_mode"))
        or nonempty_str(parent_spec.get("implementation_mode"))
        or nonempty_str(parent_handoff.get("implementation_mode"))
        or nonempty_str(parent_handoff.get("execution_mode"))
        or nonempty_str(contract.get("mode"))
        or nonempty_str(contract.get("implementation_mode"))
    )
    return mode or "operator"


def child_revision_hash(child_formula: str, implementation_mode: str, selected: dict[str, Any]) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    if implementation_mode == "operator":
        child_formula_ir = parse_formula(child_formula)
        if child_formula_ir.get("parse_status") != "success":
            raise ValueError("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED: " + "; ".join(child_formula_ir.get("parse_errors") or []))
        return child_formula_ir, str(child_formula_ir.get("formula_hash") or ""), {}
    contract_key = "direct_code_revision_contract" if implementation_mode == "direct_code" else "hybrid_revision_contract"
    revision_contract = selected.get(contract_key)
    if not isinstance(revision_contract, dict) or not revision_contract:
        revision_contract = selected.get("direct_code_revision_contract")
    if not isinstance(revision_contract, dict) or not revision_contract:
        raise ValueError(f"BLOCK_FACTORFORGE_EXECUTABLE_REVISION_DIRECT_CODE_CONTRACT_MISSING: implementation_mode={implementation_mode}")
    code_law_hash = stable_hash(
        {
            "hash_role": f"{implementation_mode}_child_code_law_hash",
            "implementation_mode": implementation_mode,
            "child_formula_or_law": child_formula,
            "revision_contract": revision_contract,
        }
    )
    return None, code_law_hash, revision_contract


def nonempty_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def nonempty_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) and bool(value) else []


def nonempty_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) and bool(value) else {}


def resolve_synthesis_path(root: Path, parent: str, parent_handoff: dict[str, Any], explicit_synthesis_path: str | None = None) -> Path:
    if explicit_synthesis_path:
        path = Path(explicit_synthesis_path).expanduser()
        return path if path.is_absolute() else root / path
    raw = (
        parent_handoff.get("orchestrator_synthesis_path")
        or parent_handoff.get("main_agent_council_synthesis_path")
        or (parent_handoff.get("selected_revision") or {}).get("orchestrator_synthesis_path")
    )
    if isinstance(raw, str) and raw.strip():
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        return path
    return default_orchestrator_synthesis_path(root, parent)


def load_orchestrator_synthesis(
    root: Path,
    parent: str,
    parent_handoff: dict[str, Any],
    explicit_synthesis_path: str | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = resolve_synthesis_path(root, parent, parent_handoff, explicit_synthesis_path)
    if not path.exists():
        raise ValueError(
            f"{SYNTHESIS_MISSING_BLOCK}: main-agent council synthesis is required before child materialization"
        )
    synthesis = load_json(path)
    if synthesis.get("contract_version") != MAIN_AGENT_COUNCIL_SYNTHESIS_VERSION:
        raise ValueError(
            f"{ORCHESTRATOR_MISMATCH_BLOCK}: invalid synthesis contract_version={synthesis.get('contract_version')!r}"
        )
    if synthesis.get("report_id") != parent:
        raise ValueError(
            f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis report_id does not match parent"
        )
    if synthesis.get("canonical_write_permission") is not False:
        raise ValueError(f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis must set canonical_write_permission=false")
    if synthesis.get("execution_allowed_by_default") is not False:
        raise ValueError(f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis must set execution_allowed_by_default=false")
    if synthesis.get("human_approval_required") is not True:
        raise ValueError(f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis must require human approval")

    selected = synthesis.get("selected_revision")
    if not isinstance(selected, dict):
        raise ValueError(f"{CHILD_FORMULA_MISSING_BLOCK}: synthesis.selected_revision is required")
    if not nonempty_str(selected.get("law_id")):
        raise ValueError(f"{SELECTED_LAW_MISSING_BLOCK}: synthesis.selected_revision.law_id is required")
    if not child_formula_or_law(selected):
        raise ValueError(f"{CHILD_FORMULA_MISSING_BLOCK}: synthesis.selected_revision.child_formula is required")
    if not nonempty_dict(selected.get("expected_metric_signature")):
        raise ValueError(f"{METRIC_SIGNATURE_MISSING_BLOCK}: synthesis.selected_revision.expected_metric_signature is required")
    if not nonempty_list(selected.get("falsification_tests")):
        raise ValueError(f"{FALSIFICATION_MISSING_BLOCK}: synthesis.selected_revision.falsification_tests is required")
    if not nonempty_list(selected.get("kill_criteria")):
        raise ValueError(f"{KILL_CRITERIA_MISSING_BLOCK}: synthesis.selected_revision.kill_criteria is required")

    law_id = nonempty_str(selected.get("law_id"))
    prior = synthesis.get("prior_revision_memory") if isinstance(synthesis.get("prior_revision_memory"), dict) else {}
    if not prior and isinstance(parent_handoff.get("prior_revision_memory"), dict):
        prior = parent_handoff["prior_revision_memory"]
    if prior.get("falsified_revision") or prior.get("prior_revision_outcome") == "falsified":
        forbidden_rules = {str(item) for item in (prior.get("forbidden_repeat_revision_rules") or [])}
        if law_id in forbidden_rules:
            raise ValueError(f"{ORCHESTRATOR_MISMATCH_BLOCK}: selected law repeats a falsified prior revision rule")
    return path, synthesis, selected


def build_executable_revision_spec(
    *,
    root: Path,
    parent: str,
    child: str,
    branch_id: str,
    parent_spec: dict[str, Any],
    parent_handoff: dict[str, Any],
    parent_iteration: dict[str, Any],
    parent_handoff_path: Path,
    source_handoff_sha256: str,
    explicit_synthesis_path: str | None = None,
    branch_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = parent_spec.get("canonical_spec") if isinstance(parent_spec.get("canonical_spec"), dict) else {}
    parent_formula = str(canonical.get("formula_text") or "").strip()
    if not parent_formula:
        raise ValueError("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_PARENT_FORMULA_MISSING")
    synthesis_path, synthesis, selected_revision = load_orchestrator_synthesis(
        root,
        parent,
        parent_handoff,
        explicit_synthesis_path,
    )
    child_formula = child_formula_or_law(selected_revision)
    derivation_rule = nonempty_str(selected_revision.get("law_id"))
    implementation_mode = selected_implementation_mode(parent_spec, parent_handoff, selected_revision)
    parent_formula_hash = parent_formula_hash_for_audit(parent_formula)
    child_formula_ir, child_formula_hash, direct_code_revision_contract = child_revision_hash(child_formula, implementation_mode, selected_revision)
    revision_type = str((parent_handoff.get("executable_revision_spec") or {}).get("revision_type") or parent_handoff.get("revision_type") or "formula_mutation")
    if implementation_mode != "operator" and revision_type == "formula_mutation":
        revision_type = f"{implementation_mode}_mutation"
    if revision_type != "audit_rerun" and child_formula_hash == parent_formula_hash:
        raise ValueError("BLOCK_FACTORFORGE_CHILD_REVISION_NO_EFFECT")
    prior = synthesis.get("prior_revision_memory") if isinstance(synthesis.get("prior_revision_memory"), dict) else {}
    if not prior and isinstance(parent_handoff.get("prior_revision_memory"), dict):
        prior = parent_handoff["prior_revision_memory"]
    if prior.get("falsified_revision") or prior.get("prior_revision_outcome") == "falsified":
        forbidden_hashes = {str(item) for item in (prior.get("forbidden_repeat_formula_hashes") or [])}
        if child_formula_hash in forbidden_hashes:
            raise ValueError(f"{ORCHESTRATOR_MISMATCH_BLOCK}: selected child formula recreates a forbidden prior formula hash")
    selected_ids = [derivation_rule]
    spec_branch_id = nonempty_str(branch_context.get("law_id")) if branch_context else branch_id
    spec = {
        "contract_version": EXECUTABLE_REVISION_SPEC_VERSION,
        "created_at_utc": utc_now(),
        "parent_report_id": parent,
        "child_report_id": child,
        "branch_id": spec_branch_id or branch_id,
        "source_handoff_path": str(parent_handoff_path),
        "source_handoff_sha256": source_handoff_sha256,
        "source_council_summary_path": str(root / "objects" / "research_iteration_master" / "revision_council" / parent / f"revision_council_summary__{parent}.json"),
        "source_orchestrator_synthesis_path": str(synthesis_path),
        "source_orchestrator_synthesis_sha256": sha256_file(synthesis_path),
        "selected_revision_law_ids": selected_ids,
        "revision_type": revision_type,
        "implementation_mode": implementation_mode,
        "derivation_rule": derivation_rule,
        "parent_formula": parent_formula,
        "child_formula": child_formula,
        "parent_formula_hash": parent_formula_hash,
        "child_formula_hash": child_formula_hash,
        "child_code_law_hash": child_formula_hash if implementation_mode != "operator" else None,
        "child_formula_ir": child_formula_ir,
        "direct_code_revision_contract": direct_code_revision_contract or None,
        "formula_mutation_description": selected_revision.get("formula_mutation_description")
        or f"Apply {derivation_rule} from main-agent Council synthesis.",
        "expected_metric_signature": selected_revision.get("expected_metric_signature") or {},
        "falsification_tests": selected_revision.get("falsification_tests") or [],
        "kill_criteria": selected_revision.get("kill_criteria") or [],
        "orchestrator_synthesis": {
            "contract_version": synthesis.get("contract_version"),
            "producer": synthesis.get("producer"),
            "consensus_summary": synthesis.get("consensus_summary"),
            "disagreement_summary": synthesis.get("disagreement_summary"),
            "selected_revision": {
                "law_id": derivation_rule,
                "source_agent_roles": selected_revision.get("source_agent_roles") or [],
                "why_selected": selected_revision.get("why_selected"),
                "economic_mechanism_link": selected_revision.get("economic_mechanism_link"),
                "math_model_link": selected_revision.get("math_model_link"),
            },
        },
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval": {
            "status": "approved_for_materialization",
            "source": "approved_step3b_handoff",
            "approved_by": "user_or_default_approval_artifact",
        },
        "parent_iteration_path": str(object_path(root, "research_iteration_master", parent)),
    }
    if branch_context:
        spec["branch_role"] = branch_context["branch_role"]
        spec["branch_index"] = branch_context["branch_index"]
        spec["branch_group_id"] = branch_context["branch_group_id"]
        spec["source_multibranch_synthesis_path"] = branch_context["source_multibranch_synthesis_path"]
        spec["source_multibranch_synthesis_sha256"] = branch_context["source_multibranch_synthesis_sha256"]
        spec["sibling_branch_count"] = branch_context["sibling_branch_count"]
        spec["branch_context"] = branch_context
    return spec


def existing_target_paths(targets: dict[str, Path]) -> dict[str, str]:
    return {kind: str(path) for kind, path in targets.items() if path.exists()}


def idempotent_marker_matches(report_path: Path, *, parent: str, child: str, source_handoff_sha256: str) -> bool:
    if not report_path.exists():
        return False
    report = load_json(report_path)
    return (
        report.get("materialization_version") == MATERIALIZATION_VERSION
        and report.get("parent_report_id") == parent
        and report.get("child_report_id") == child
        and report.get("source_handoff_sha256") == source_handoff_sha256
    )


def child_identity(identity: dict[str, Any], *, child_report_id: str, branch_id: str, parent_run_id: str | None, artifact_role: str, producer: str) -> dict[str, Any]:
    out = dict(identity or {})
    out["report_id"] = child_report_id
    out["branch_id"] = branch_id
    out["run_id"] = f"{child_report_id}__run_001"
    out["parent_run_id"] = parent_run_id
    out["artifact_role"] = artifact_role
    out["producer"] = producer
    return out


def rewrite_common(payload: dict[str, Any], *, child_report_id: str, branch_id: str, parent_run_id: str | None, artifact_role: str, producer: str) -> dict[str, Any]:
    out = json.loads(json.dumps(payload))
    out["report_id"] = child_report_id
    out["parent_report_id"] = out.get("parent_report_id") or payload.get("report_id")
    out["branch_id"] = branch_id
    identity = out.get("artifact_identity")
    if isinstance(identity, dict):
        out["artifact_identity"] = child_identity(
            identity,
            child_report_id=child_report_id,
            branch_id=branch_id,
            parent_run_id=parent_run_id,
            artifact_role=artifact_role,
            producer=producer,
        )
    return out


def apply_executable_revision_contract(
    payload: dict[str, Any],
    executable_revision_spec: dict[str, Any],
    *,
    root: Path,
    child_report_id: str,
) -> dict[str, Any]:
    """Keep child control artifacts aligned with the executable revision spec."""
    implementation_mode = nonempty_str(executable_revision_spec.get("implementation_mode")) or "operator"
    formula_ir = executable_revision_spec.get("child_formula_ir") if isinstance(executable_revision_spec.get("child_formula_ir"), dict) else {}
    formula_hash_value = str(executable_revision_spec.get("child_formula_hash") or formula_ir.get("formula_hash") or "")
    payload["implementation_mode"] = implementation_mode
    if "execution_mode" in payload:
        payload["execution_mode"] = implementation_mode
    payload["formula_hash"] = formula_hash_value or payload.get("formula_hash")
    payload["executable_revision_spec_ref"] = str(executable_revision_spec_path(root, child_report_id))
    if implementation_mode == "operator":
        payload["code_hash"] = None
        payload["code_contract_hash"] = None
        payload["factor_impl_ref"] = None
        payload["factor_impl_stub_ref"] = None
    if isinstance(payload.get("artifact_identity"), dict):
        identity = payload["artifact_identity"]
        identity["implementation_mode"] = implementation_mode
        identity["formula_hash"] = formula_hash_value or identity.get("formula_hash")
        if implementation_mode == "operator":
            identity["code_hash"] = None
            identity["code_contract_hash"] = None
    if "factor_spec_master_ref" in payload:
        payload["factor_spec_master_ref"] = f"factor_spec_master__{child_report_id}.json"
    if "data_prep_master_ref" in payload:
        payload["data_prep_master_ref"] = f"data_prep_master__{child_report_id}.json"
    if "implementation_plan_master_ref" in payload:
        payload["implementation_plan_master_ref"] = None
    if "hybrid_execution_scaffold_ref" in payload:
        if implementation_mode == "operator":
            payload["hybrid_execution_scaffold_ref"] = None
    contract = payload.get("implementation_contract")
    if isinstance(contract, dict):
        contract["implementation_mode"] = implementation_mode
        contract["mode"] = implementation_mode
        contract["formula_hash"] = formula_hash_value
        if implementation_mode == "operator":
            contract["formula_ir"] = formula_ir
            contract["operator_set"] = formula_ir.get("operator_set") or []
            contract["required_fields"] = formula_ir.get("required_fields") or []
            contract.pop("source_code", None)
            contract.pop("code_hash", None)
            contract.pop("code_contract_hash", None)
        else:
            revision_contract = executable_revision_spec.get("direct_code_revision_contract")
            if isinstance(revision_contract, dict) and revision_contract:
                existing_code_contract = contract.get("code_contract") if isinstance(contract.get("code_contract"), dict) else {}
                merged_code_contract = dict(existing_code_contract)
                merged_code_contract.update(revision_contract)
                contract["code_contract"] = merged_code_contract
                contract["direct_code_revision_contract"] = revision_contract
            contract["formula_ir"] = None
            contract["operator_set"] = []
            if isinstance(revision_contract, dict):
                required_fields = revision_contract.get("required_fields") or revision_contract.get("fields") or []
                if required_fields:
                    contract["required_fields"] = required_fields
        canonical = payload.get("canonical_spec")
        if isinstance(canonical, dict):
            canonical["formula_text"] = executable_revision_spec.get("child_formula") or canonical.get("formula_text")
            canonical["formula_hash"] = formula_hash_value or canonical.get("formula_hash")
            if implementation_mode == "operator":
                canonical["formula_ir"] = formula_ir
                canonical["operator_set"] = formula_ir.get("operator_set") or []
                canonical["required_fields"] = formula_ir.get("required_fields") or []
            else:
                canonical["formula_ir"] = None
                canonical["operator_set"] = []
                canonical["operators"] = []
                revision_contract = executable_revision_spec.get("direct_code_revision_contract")
                if isinstance(revision_contract, dict):
                    canonical["required_fields"] = revision_contract.get("required_fields") or canonical.get("required_fields") or []
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize a Step6-approved parent handoff into child Step3B inputs.")
    ap.add_argument("--parent-report-id", required=True)
    ap.add_argument("--child-report-id", required=True)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--synthesis-path", default=None)
    ap.add_argument("--branch-group-id", default=None)
    ap.add_argument("--branch-index", type=int, default=None)
    ap.add_argument("--branch-role", default=None)
    ap.add_argument("--branch-law-id", default=None)
    ap.add_argument("--source-multibranch-synthesis-path", default=None)
    ap.add_argument("--source-multibranch-synthesis-sha256", default=None)
    ap.add_argument("--sibling-branch-count", type=int, default=None)
    args = ap.parse_args()

    if os.getenv("FACTORFORGE_ULTIMATE_RUN") != "1" and os.getenv("FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE") != "1":
        print("BLOCKED_DIRECT_MATERIALIZE: child revision materialization must be invoked by the ultimate loop orchestrator.")
        return 1

    ctx = resolve_factorforge_context(args.factorforge_root)
    root = ctx.factorforge_root
    parent = args.parent_report_id
    child = args.child_report_id
    if parent == child:
        print("BLOCK_FACTORFORGE_LOOP_CHILD_REPORT_ID_COLLISION")
        return 1

    parent_handoff_path = object_path(root, "handoff_to_step3b", parent)
    parent_iteration_path = object_path(root, "research_iteration_master", parent)
    if not parent_handoff_path.exists() or not parent_iteration_path.exists():
        print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
        return 1

    source_handoff_sha256 = sha256_file(parent_handoff_path)
    parent_handoff = load_json(parent_handoff_path)
    parent_iteration = load_json(parent_iteration_path)
    revision_strategy = (((parent_iteration.get("research_judgment") or {}).get("research_memo") or {}).get("revision_strategy") or {})
    if revision_strategy.get("loop_authorization") != "approved_for_step3b_handoff":
        print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
        return 1

    branch_id = str(parent_handoff.get("new_branch_id") or parent_handoff.get("revision_id") or child.rsplit("__", 1)[-1]).strip()
    if not branch_id:
        print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
        return 1
    parent_identity = parent_handoff.get("parent_identity") or {}
    parent_run_id = parent_handoff.get("parent_run_id") or parent_identity.get("run_id")

    required_parent_paths = {
        "alpha_idea_master": object_path(root, "alpha_idea_master", parent),
        "factor_spec_master": object_path(root, "factor_spec_master", parent),
        "data_prep_master": object_path(root, "data_prep_master", parent),
    }
    missing = [str(path) for path in required_parent_paths.values() if not path.exists()]
    if missing:
        print("BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED")
        print(json.dumps({"missing_parent_artifacts": missing}, ensure_ascii=False, indent=2))
        return 1
    parent_data_prep = load_json(required_parent_paths["data_prep_master"])
    declared_daily_keys = declared_daily_source_keys(parent_data_prep)
    resolved_daily = resolved_daily_sources(root, parent_data_prep)
    missing_daily = sorted(
        key for key in declared_daily_keys
        if key.removeprefix("daily_df_") not in resolved_daily
    )
    if missing_daily:
        local_inputs = parent_data_prep.get("local_input_paths") if isinstance(parent_data_prep.get("local_input_paths"), dict) else {}
        print(DAILY_SNAPSHOT_MISSING_BLOCK)
        print(
            json.dumps(
                {
                    "parent_report_id": parent,
                    "child_report_id": child,
                    "missing_daily_source_keys": missing_daily,
                    "declared_paths": {key: local_inputs.get(key) for key in missing_daily},
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    targets = planned_target_paths(root, parent, child, parent_data_prep)
    existing_targets = existing_target_paths(targets)
    report_path = materialization_report_path(root, parent, child)
    if existing_targets:
        if idempotent_marker_matches(report_path, parent=parent, child=child, source_handoff_sha256=source_handoff_sha256):
            report = load_json(report_path)
            print(json.dumps({"status": "idempotent_noop", "report_path": str(report_path), **report}, ensure_ascii=False, indent=2))
            return 0
        print(TARGET_EXISTS_BLOCK)
        print(
            json.dumps(
                {
                    "reason": "child_materialization_target_already_exists",
                    "parent_report_id": parent,
                    "child_report_id": child,
                    "existing_targets": existing_targets,
                    "materialization_report_path": str(report_path),
                    "source_handoff_sha256": source_handoff_sha256,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    materialized: dict[str, str] = {}
    producer = "ultimate_loop_child_materializer"
    parent_spec = load_json(required_parent_paths["factor_spec_master"])
    try:
        branch_context = None
        branch_args = {
            "branch_group_id": args.branch_group_id,
            "branch_index": args.branch_index,
            "branch_role": args.branch_role,
            "law_id": args.branch_law_id,
            "source_multibranch_synthesis_path": args.source_multibranch_synthesis_path,
            "source_multibranch_synthesis_sha256": args.source_multibranch_synthesis_sha256,
            "sibling_branch_count": args.sibling_branch_count,
        }
        if any(value is not None for value in branch_args.values()):
            missing_branch_args = sorted(key for key, value in branch_args.items() if value is None or value == "")
            if missing_branch_args:
                print(f"{ORCHESTRATOR_MISMATCH_BLOCK}: incomplete branch context: {','.join(missing_branch_args)}")
                return 1
            if args.branch_role not in {"exploit", "exploration"}:
                print(f"{ORCHESTRATOR_MISMATCH_BLOCK}: invalid branch_role={args.branch_role!r}")
                return 1
            branch_context = {
                "parent_report_id": parent,
                "child_report_id": child,
                "branch_group_id": str(args.branch_group_id),
                "branch_index": int(args.branch_index),
                "branch_role": str(args.branch_role),
                "law_id": str(args.branch_law_id),
                "source_multibranch_synthesis_path": str(args.source_multibranch_synthesis_path),
                "source_multibranch_synthesis_sha256": str(args.source_multibranch_synthesis_sha256),
                "sibling_branch_count": int(args.sibling_branch_count),
            }
        executable_revision_spec = build_executable_revision_spec(
            root=root,
            parent=parent,
            child=child,
            branch_id=branch_id,
            parent_spec=parent_spec,
            parent_handoff=parent_handoff,
            parent_iteration=parent_iteration,
            parent_handoff_path=parent_handoff_path,
            source_handoff_sha256=source_handoff_sha256,
            explicit_synthesis_path=args.synthesis_path,
            branch_context=branch_context,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    write_json(executable_revision_spec_path(root, child), executable_revision_spec)
    materialized["executable_revision_spec"] = str(executable_revision_spec_path(root, child))

    for kind, source in required_parent_paths.items():
        role = kind
        payload = rewrite_common(
            load_json(source),
            child_report_id=child,
            branch_id=branch_id,
            parent_run_id=parent_run_id,
            artifact_role=role,
            producer=producer,
        )
        if kind == "factor_spec_master":
            payload = apply_executable_revision_contract(
                payload,
                executable_revision_spec,
                root=root,
                child_report_id=child,
            )
            payload["revision_identity"] = {
                "contract_version": "factorforge_child_revision_identity_v1",
                "parent_report_id": parent,
                "child_report_id": child,
                "revision_spec_path": str(executable_revision_spec_path(root, child)),
                "parent_formula_hash": executable_revision_spec["parent_formula_hash"],
                "child_formula_hash": executable_revision_spec["child_formula_hash"],
                "implementation_mode": executable_revision_spec.get("implementation_mode"),
                "revision_noop": executable_revision_spec["parent_formula_hash"] == executable_revision_spec["child_formula_hash"],
                "revision_identity_status": "audit_rerun" if executable_revision_spec["revision_type"] == "audit_rerun" else "changed",
            }
        if kind == "data_prep_master":
            local_inputs = payload.setdefault("local_input_paths", {})
            if isinstance(local_inputs, dict):
                copied_daily: dict[str, str] = {}
                for suffix, daily_source in resolved_daily.items():
                    child_daily = targets[f"child_daily_input_{suffix}"]
                    child_daily.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(daily_source, child_daily)
                    copied_daily[suffix] = str(child_daily)
                    local_inputs[f"daily_df_{suffix}"] = str(child_daily)
                    materialized[f"child_daily_input_{suffix}"] = str(child_daily)
                meta_source = resolved_path(root, (parent_data_prep.get("local_input_paths") or {}).get("daily_input_meta_json"))
                if meta_source and meta_source.exists() and "child_daily_input_meta_json" in targets:
                    child_meta = targets["child_daily_input_meta_json"]
                    child_meta.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(meta_source, child_meta)
                    local_inputs["daily_input_meta_json"] = str(child_meta)
                    materialized["child_daily_input_meta_json"] = str(child_meta)
                if local_inputs.get("daily_df_parquet"):
                    local_inputs["preferred_daily_format"] = "parquet"
                if local_inputs.get("daily_df_csv"):
                    local_inputs["audit_daily_format"] = "csv"
                daily_io = local_inputs.get("daily_io_contract")
                if isinstance(daily_io, dict):
                    if "parquet" in copied_daily:
                        daily_io["performance_path"] = "parquet"
                    if "csv" in copied_daily:
                        daily_io["audit_path"] = "csv"
                        daily_io["csv_path"] = copied_daily["csv"]
                    if "csv" not in copied_daily:
                        daily_io["csv_path"] = None
                    daily_io["csv_sample_path"] = None
                local_inputs["input_mode"] = local_inputs.get("input_mode") or "daily_only"
        payload = apply_executable_revision_contract(
            payload,
            executable_revision_spec,
            root=root,
            child_report_id=child,
        )
        target = object_path(root, kind, child)
        write_json(target, payload)
        materialized[kind] = str(target)

    optional_roles = {
        "qlib_adapter_config": "qlib_adapter_config",
        "handoff_to_step3": "handoff_to_step3",
        "handoff_to_step4": "handoff_to_step4_seed",
    }
    for kind, role in optional_roles.items():
        source = object_path(root, kind, parent)
        if not source.exists():
            continue
        payload = rewrite_common(
            load_json(source),
            child_report_id=child,
            branch_id=branch_id,
            parent_run_id=parent_run_id,
            artifact_role=role,
            producer=producer,
        )
        if kind == "handoff_to_step4":
            payload["factor_impl_ref"] = None
            payload["factor_impl_stub_ref"] = None
            payload["step6_parent_handoff_ref"] = str(parent_handoff_path)
        payload = apply_executable_revision_contract(
            payload,
            executable_revision_spec,
            root=root,
            child_report_id=child,
        )
        target = object_path(root, kind, child)
        write_json(target, payload)
        materialized[kind] = str(target)

    qlib_config_result = ensure_child_qlib_adapter_config(root, parent, child)
    materialized["qlib_adapter_config"] = qlib_config_result["path"]
    materialized["qlib_adapter_config_status"] = qlib_config_result["status"]

    report_branch_id = executable_revision_spec.get("branch_id") or branch_id
    report = {
        "materialization_version": MATERIALIZATION_VERSION,
        "created_at_utc": utc_now(),
        "parent_report_id": parent,
        "child_report_id": child,
        "parent_handoff_path": str(parent_handoff_path),
        "source_handoff_sha256": source_handoff_sha256,
        "branch_id": report_branch_id,
        "source_branch_id": branch_id,
        "parent_run_id": parent_run_id,
        "materialized_artifacts": materialized,
        "executable_revision_spec_path": str(executable_revision_spec_path(root, child)),
        "parent_formula_hash": executable_revision_spec.get("parent_formula_hash"),
        "child_formula_hash": executable_revision_spec.get("child_formula_hash"),
        "revision_identity_status": "audit_rerun" if executable_revision_spec.get("revision_type") == "audit_rerun" else "changed",
        "generated_code_written": False,
        "clean_data_touched": False,
        "official_promotion_written": False,
    }
    if branch_context:
        report.update(
            {
                "branch_role": branch_context["branch_role"],
                "branch_index": branch_context["branch_index"],
                "branch_group_id": branch_context["branch_group_id"],
                "source_multibranch_synthesis_path": branch_context["source_multibranch_synthesis_path"],
                "source_multibranch_synthesis_sha256": branch_context["source_multibranch_synthesis_sha256"],
                "sibling_branch_count": branch_context["sibling_branch_count"],
                "branch_context": branch_context,
            }
        )
    write_json(report_path, report)
    print(json.dumps({"status": "materialized", "report_path": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
