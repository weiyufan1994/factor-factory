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

MATERIALIZATION_VERSION = "factorforge_step6_child_revision_materialization_v1"
EXECUTABLE_REVISION_SPEC_VERSION = "factorforge_executable_revision_spec_v1"
TARGET_EXISTS_BLOCK = "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_TARGET_EXISTS"


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
    return root / "objects" / "runtime_context" / f"child_revision_materialization__{parent}__{child}.json"


def child_daily_input_path(root: Path, child: str, suffix: str) -> Path:
    return root / "runs" / child / "step3a_local_inputs" / f"daily_input__{child}.{suffix}"


def resolved_path(root: Path, raw: Any) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


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
    for kind in ("qlib_adapter_config", "handoff_to_step3", "handoff_to_step4"):
        if object_path(root, kind, parent).exists():
            targets[kind] = object_path(root, kind, child)
    return targets


def executable_revision_spec_path(root: Path, child: str) -> Path:
    return object_path(root, "executable_revision_spec", child)


def formula_hash(formula_text: str) -> str:
    parsed = parse_formula(formula_text)
    if parsed.get("parse_status") != "success":
        raise ValueError("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED: " + "; ".join(parsed.get("parse_errors") or []))
    return str(parsed.get("formula_hash") or "")


def derive_child_formula(parent_formula: str, parent_spec: dict[str, Any], parent_handoff: dict[str, Any]) -> tuple[str, str]:
    """Create a conservative executable formula from approved revision intent.

    The materializer does not run research. It only turns a known revision class
    into an explicit child formula so Step3B cannot silently rerun the parent.
    """
    explicit = (
        parent_handoff.get("child_formula")
        or (parent_handoff.get("executable_revision_spec") or {}).get("child_formula")
        or (parent_handoff.get("selected_revision") or {}).get("child_formula")
    )
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip(), "explicit_handoff_child_formula"

    canonical = parent_spec.get("canonical_spec") if isinstance(parent_spec.get("canonical_spec"), dict) else {}
    fields = {str(x).lower() for x in (canonical.get("required_inputs") or canonical.get("required_fields") or [])}
    lower_formula = parent_formula.lower()
    has_open_close = {"open", "close"}.issubset(fields) or ("open" in lower_formula and "close" in lower_formula)
    has_volume = bool({"volume", "vol"}.intersection(fields)) or "volume" in lower_formula or "vol" in lower_formula
    revision_text = json.dumps(parent_handoff, ensure_ascii=False).lower()
    if has_open_close and not has_volume and any(token in revision_text for token in ["sign", "monotonic", "orientation", "state split", "positive long-side", "formula expression"]):
        return "rank(minus(divide(close, open), 1))", "open_close_sign_orientation_challenge"
    return f"negate({parent_formula})", "generic_sign_challenge"


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
) -> dict[str, Any]:
    canonical = parent_spec.get("canonical_spec") if isinstance(parent_spec.get("canonical_spec"), dict) else {}
    parent_formula = str(canonical.get("formula_text") or "").strip()
    if not parent_formula:
        raise ValueError("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_PARENT_FORMULA_MISSING")
    child_formula, derivation_rule = derive_child_formula(parent_formula, parent_spec, parent_handoff)
    parent_formula_hash = formula_hash(parent_formula)
    child_formula_ir = parse_formula(child_formula)
    if child_formula_ir.get("parse_status") != "success":
        raise ValueError("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED: " + "; ".join(child_formula_ir.get("parse_errors") or []))
    child_formula_hash = str(child_formula_ir.get("formula_hash") or "")
    revision_type = str((parent_handoff.get("executable_revision_spec") or {}).get("revision_type") or parent_handoff.get("revision_type") or "formula_mutation")
    if revision_type != "audit_rerun" and child_formula_hash == parent_formula_hash:
        raise ValueError("BLOCK_FACTORFORGE_CHILD_REVISION_NO_EFFECT")
    research_judgment = parent_handoff.get("research_judgment") if isinstance(parent_handoff.get("research_judgment"), dict) else {}
    research_memo = research_judgment.get("research_memo") if isinstance(research_judgment.get("research_memo"), dict) else {}
    final_revision = research_memo.get("final_revision_strategy") or research_memo.get("revision_strategy") or research_judgment.get("final_revision_strategy") or {}
    selected_ids = final_revision.get("selected_council_proposal_ids") or []
    return {
        "contract_version": EXECUTABLE_REVISION_SPEC_VERSION,
        "created_at_utc": utc_now(),
        "parent_report_id": parent,
        "child_report_id": child,
        "branch_id": branch_id,
        "source_handoff_path": str(parent_handoff_path),
        "source_handoff_sha256": source_handoff_sha256,
        "source_council_summary_path": str(root / "objects" / "research_iteration_master" / "revision_council" / parent / f"revision_council_summary__{parent}.json"),
        "selected_revision_law_ids": selected_ids,
        "revision_type": revision_type,
        "derivation_rule": derivation_rule,
        "parent_formula": parent_formula,
        "child_formula": child_formula,
        "parent_formula_hash": parent_formula_hash,
        "child_formula_hash": child_formula_hash,
        "child_formula_ir": child_formula_ir,
        "formula_mutation_description": f"Apply {derivation_rule} to create an executable child formula from the approved Step6/Council revision law.",
        "expected_metric_signature": (final_revision.get("expected_metric_signature") if isinstance(final_revision, dict) else None) or {},
        "falsification_tests": final_revision.get("falsification_tests") or final_revision.get("math_falsification_tests") or [],
        "kill_criteria": final_revision.get("kill_criteria") or [],
        "implementation_mode": "operator",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval": {
            "status": "approved_for_materialization",
            "source": "approved_step3b_handoff",
            "approved_by": "user_or_default_approval_artifact",
        },
        "parent_iteration_path": str(object_path(root, "research_iteration_master", parent)),
    }


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize a Step6-approved parent handoff into child Step3B inputs.")
    ap.add_argument("--parent-report-id", required=True)
    ap.add_argument("--child-report-id", required=True)
    ap.add_argument("--factorforge-root", default=None)
    args = ap.parse_args()

    if os.getenv("FACTORFORGE_ULTIMATE_RUN") != "1":
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
            formula_ir = executable_revision_spec["child_formula_ir"]
            formula_hash = formula_ir.get("formula_hash")
            payload.setdefault("canonical_spec", {})
            payload["canonical_spec"]["formula_text"] = executable_revision_spec["child_formula"]
            payload["canonical_spec"]["formula_ir"] = formula_ir
            payload["canonical_spec"]["operator_set"] = formula_ir.get("operator_set") or []
            payload["canonical_spec"]["operators"] = formula_ir.get("operator_set") or []
            payload["canonical_spec"]["required_inputs"] = formula_ir.get("required_fields") or []
            payload["canonical_spec"]["required_fields"] = formula_ir.get("required_fields") or []
            payload["canonical_spec"]["formula_hash"] = formula_hash
            payload["executable_revision_spec_ref"] = str(executable_revision_spec_path(root, child))
            payload["revision_identity"] = {
                "contract_version": "factorforge_child_revision_identity_v1",
                "parent_report_id": parent,
                "child_report_id": child,
                "revision_spec_path": str(executable_revision_spec_path(root, child)),
                "parent_formula_hash": executable_revision_spec["parent_formula_hash"],
                "child_formula_hash": executable_revision_spec["child_formula_hash"],
                "revision_noop": executable_revision_spec["parent_formula_hash"] == executable_revision_spec["child_formula_hash"],
                "revision_identity_status": "audit_rerun" if executable_revision_spec["revision_type"] == "audit_rerun" else "changed",
            }
            if formula_hash:
                payload["formula_hash"] = formula_hash
                payload.setdefault("implementation_contract", {})
                if isinstance(payload["implementation_contract"], dict):
                    payload["implementation_contract"]["formula_ir"] = formula_ir
                    payload["implementation_contract"]["formula_hash"] = formula_hash
                    payload["implementation_contract"]["operator_set"] = formula_ir.get("operator_set") or []
                    payload["implementation_contract"]["required_fields"] = formula_ir.get("required_fields") or []
                if isinstance(payload.get("artifact_identity"), dict):
                    payload["artifact_identity"]["formula_hash"] = formula_hash
        if kind == "data_prep_master":
            local_inputs = payload.setdefault("local_input_paths", {})
            if isinstance(local_inputs, dict):
                for suffix, daily_source in resolved_daily_sources(root, parent_data_prep).items():
                    child_daily = targets[f"child_daily_input_{suffix}"]
                    child_daily.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(daily_source, child_daily)
                    local_inputs[f"daily_df_{suffix}"] = str(child_daily)
                    materialized[f"child_daily_input_{suffix}"] = str(child_daily)
                if local_inputs.get("daily_df_parquet"):
                    local_inputs["preferred_daily_format"] = "parquet"
                if local_inputs.get("daily_df_csv"):
                    local_inputs["audit_daily_format"] = "csv"
                local_inputs["input_mode"] = local_inputs.get("input_mode") or "daily_only"
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
        target = object_path(root, kind, child)
        write_json(target, payload)
        materialized[kind] = str(target)

    report = {
        "materialization_version": MATERIALIZATION_VERSION,
        "created_at_utc": utc_now(),
        "parent_report_id": parent,
        "child_report_id": child,
        "parent_handoff_path": str(parent_handoff_path),
        "source_handoff_sha256": source_handoff_sha256,
        "branch_id": branch_id,
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
    write_json(report_path, report)
    print(json.dumps({"status": "materialized", "report_path": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
