#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def stable_hash(payload: Any) -> str | None:
    if payload in (None, "", [], {}):
        return None
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_read_error": f"{type(exc).__name__}: {exc}", "_path": str(path)}


def first_dict(*items: Any) -> dict[str, Any]:
    for item in items:
        if isinstance(item, dict) and item:
            return item
    return {}


def nested(payload: dict[str, Any], *keys: str) -> Any:
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def candidate_paths(root: Path, report_id: str) -> dict[str, Path]:
    return {
        "factor_spec_master": root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
        "data_prep_master": root / "objects" / "data_prep_master" / f"data_prep_master__{report_id}.json",
        "factor_run_master": root / "objects" / "factor_run_master" / f"factor_run_master__{report_id}.json",
        "factor_run_diagnostics": root / "objects" / "validation" / f"factor_run_diagnostics__{report_id}.json",
        "factor_evaluation": root / "objects" / "validation" / f"factor_evaluation__{report_id}.json",
        "run_metadata": root / "runs" / report_id / f"run_metadata__{report_id}.json",
        "ultimate_run_report": root / "objects" / "runtime_context" / f"ultimate_run_report__{report_id}.json",
        "ultimate_loop_report": root / "objects" / "runtime_context" / f"ultimate_loop_report__{report_id}.json",
        "revision_council_summary": root / "objects" / "revision_council" / report_id / f"revision_council_summary__{report_id}.json",
        "main_agent_synthesis": root / "objects" / "revision_council" / report_id / f"main_agent_council_synthesis__{report_id}.json",
        "executable_revision_spec": root / "objects" / "research_iteration_master" / f"executable_revision_spec__{report_id}.json",
    }


def backend_status(run_master: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    backend_runs = (
        nested(run_master, "evaluation_results", "backend_runs")
        or nested(diagnostics, "evaluation_results", "backend_runs")
        or []
    )
    out: dict[str, Any] = {}
    if isinstance(backend_runs, list):
        for item in backend_runs:
            if not isinstance(item, dict):
                continue
            name = str(item.get("backend") or item.get("name") or "unknown")
            out[name] = {
                "status": item.get("status"),
                "mode": nested(item, "backend_config", "mode") or item.get("mode"),
                "payload_path": item.get("payload_path"),
                "summary": item.get("summary"),
            }
    return out


def core_metrics(factor_eval: dict[str, Any], run_master: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        factor_eval,
        nested(run_master, "evaluation_results"),
        nested(diagnostics, "evaluation_results"),
    ]
    keys = [
        "rank_ic_mean",
        "ic_mean",
        "ic_ir",
        "icir",
        "turnover_mean",
        "long_side_annual_return",
        "long_side_sharpe",
        "long_side_max_drawdown",
        "max_drawdown",
        "cost_adjusted_annual_return",
        "cost_adjusted_sharpe",
        "recovery_days",
    ]
    found: dict[str, Any] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and key not in found:
                    found[key] = item
                if len(found) < len(keys):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                if len(found) < len(keys):
                    walk(item)

    for candidate in candidates:
        walk(candidate)
    return found


def parent_report_id(fsm: dict[str, Any], executable: dict[str, Any], run_meta: dict[str, Any]) -> str | None:
    for value in [
        fsm.get("parent_report_id"),
        nested(fsm, "revision", "parent_report_id"),
        nested(fsm, "artifact_identity", "parent_report_id"),
        executable.get("parent_report_id"),
        nested(run_meta, "revision", "revises"),
    ]:
        if value:
            return str(value)
    return None


def law_payload(fsm: dict[str, Any], executable: dict[str, Any], synthesis: dict[str, Any]) -> dict[str, Any]:
    selected = first_dict(
        executable.get("selected_revision"),
        executable.get("revision"),
        nested(synthesis, "selected_revision"),
        nested(synthesis, "approval", "selected_revision"),
    )
    formula_text = (
        nested(fsm, "canonical_spec", "formula_text")
        or fsm.get("formula_text")
        or selected.get("child_formula")
        or selected.get("child_formula_or_law")
    )
    law_id = (
        executable.get("law_id")
        or selected.get("law_id")
        or selected.get("selected_revision_law_id")
        or selected.get("revision_id")
        or nested(fsm, "implementation_contract", "code_contract", "law_id")
    )
    direct_code_law = (
        executable.get("direct_code_law")
        or selected.get("direct_code_law")
        or selected.get("child_formula_or_law")
        or nested(fsm, "implementation_contract", "code_contract", "direct_code_law")
    )
    return {
        "selected_law_id": law_id,
        "formula_text": formula_text,
        "formula_hash": stable_hash(formula_text),
        "direct_code_law": direct_code_law,
        "code_law_hash": stable_hash(direct_code_law or law_id),
    }


def summarize(root: Path, report_id: str) -> dict[str, Any]:
    paths = candidate_paths(root, report_id)
    payloads = {name: read_json(path) for name, path in paths.items()}
    fsm = payloads["factor_spec_master"]
    dpm = payloads["data_prep_master"]
    run_master = payloads["factor_run_master"]
    diagnostics = payloads["factor_run_diagnostics"]
    factor_eval = payloads["factor_evaluation"]
    run_meta = payloads["run_metadata"]
    ultimate = payloads["ultimate_run_report"]
    loop_report = payloads["ultimate_loop_report"]
    synthesis = payloads["main_agent_synthesis"]
    executable = payloads["executable_revision_spec"]
    input_io = run_meta.get("input_io_profile") if isinstance(run_meta.get("input_io_profile"), dict) else {}
    factor_io = run_meta.get("step4_factor_io_profile") if isinstance(run_meta.get("step4_factor_io_profile"), dict) else {}
    csv_policy = run_meta.get("step4_factor_csv_policy_observed") if isinstance(run_meta.get("step4_factor_csv_policy_observed"), dict) else {}
    acceptance = run_master.get("acceptance_summary") if isinstance(run_master.get("acceptance_summary"), dict) else {}
    side_effects = {
        "ultimate_forbidden_side_effects": ultimate.get("forbidden_side_effects") or ultimate.get("canonical_side_effects") or [],
        "loop_forbidden_side_effects": loop_report.get("canonical_side_effects") or [],
        "acceptance_side_effects": acceptance.get("side_effects") if isinstance(acceptance.get("side_effects"), dict) else {},
    }
    law = law_payload(fsm, executable, synthesis)
    return {
        "version": "factorforge_run_artifact_summary_v1",
        "report_id": report_id,
        "parent_report_id": parent_report_id(fsm, executable, run_meta),
        "artifact_root": str(root),
        "artifact_paths": {name: str(path) for name, path in paths.items()},
        "artifact_exists": {name: path.exists() for name, path in paths.items()},
        "selected_law_id": law.get("selected_law_id"),
        "implementation_mode": (
            nested(fsm, "implementation_contract", "mode")
            or nested(fsm, "implementation_contract", "implementation_mode")
            or nested(run_meta, "implementation_mode_decision", "implementation_mode")
            or nested(dpm, "implementation_plan_master", "implementation_mode")
        ),
        "formula_hash": law.get("formula_hash"),
        "code_law_hash": law.get("code_law_hash"),
        "law_payload": law,
        "step3b_backend": {
            "producer": run_meta.get("producer"),
            "performance_profile_version": nested(run_meta, "performance_profile", "version"),
            "csv_output_policy": nested(run_meta, "performance_profile", "csv_output_profile", "csv_output_policy"),
        },
        "step4_backend": backend_status(run_master, diagnostics),
        "derived_state_proof": {
            "source": factor_io.get("source"),
            "derived_state_hit": bool(factor_io.get("minute_derived_state_profile")),
            "minute_derived_state_profile": factor_io.get("minute_derived_state_profile"),
            "minute_derived_factor_profile": factor_io.get("minute_derived_factor_profile"),
        },
        "daily_basic_cache_proof": {
            "daily_basic_selected_format": input_io.get("daily_basic_selected_format"),
            "daily_basic_cache_hit": input_io.get("daily_basic_cache_hit"),
            "daily_basic_cache_path": input_io.get("daily_basic_cache_path"),
            "daily_basic_rows": input_io.get("daily_basic_rows"),
            "daily_basic_dates": input_io.get("daily_basic_dates"),
            "daily_basic_tickers": input_io.get("daily_basic_tickers"),
            "daily_basic_load_seconds": input_io.get("daily_basic_load_seconds"),
            "backtest_base_reuse_hit": input_io.get("backtest_base_reuse_hit"),
            "backtest_base_cache_path": input_io.get("backtest_base_cache_path"),
        },
        "csv_policy_proof": csv_policy,
        "core_metrics": core_metrics(factor_eval, run_master, diagnostics),
        "side_effect_proof": side_effects,
        "run_status": run_master.get("run_status") or diagnostics.get("run_status") or run_meta.get("run_status_candidate"),
        "failure_reason": run_master.get("failure_reason"),
        "ultimate_loop_budget": {
            "approval_consumed_loop_slot": loop_report.get("approval_consumed_loop_slot"),
            "approval_bridge_requires_additional_loop_for_child": loop_report.get("approval_bridge_requires_additional_loop_for_child"),
            "final_outcome": loop_report.get("final_outcome"),
            "stop_reason": loop_report.get("stop_reason"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only Factor Forge run artifact summary/probe.")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--factorforge-root", default=os.getenv("FACTORFORGE_ROOT") or str(REPO_ROOT))
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()
    summary = summarize(Path(args.factorforge_root).expanduser(), args.report_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2 if args.pretty else None, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
