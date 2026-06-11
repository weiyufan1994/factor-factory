#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_step4_module():
    path = REPO_ROOT / "skills" / "factor-forge-step4" / "scripts" / "run_step4.py"
    spec = importlib.util.spec_from_file_location("factorforge_step4_framework_smoke_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Step4 module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_summary_fixture(root: Path, report_id: str) -> None:
    write_json(root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json", {
        "report_id": report_id,
        "parent_report_id": "PARENT",
        "canonical_spec": {"formula_text": "direct_code_law: miller_flow_v7"},
        "implementation_contract": {"implementation_mode": "direct_code", "code_contract": {"law_id": "miller_flow_v7"}},
    })
    write_json(root / "objects" / "data_prep_master" / f"data_prep_master__{report_id}.json", {
        "report_id": report_id,
        "implementation_plan_master": {"implementation_mode": "direct_code"},
    })
    write_json(root / "objects" / "factor_run_master" / f"factor_run_master__{report_id}.json", {
        "report_id": report_id,
        "run_status": "success",
        "evaluation_results": {
            "backend_runs": [
                {"backend": "self_quant_analyzer", "status": "success", "payload_path": "/tmp/self_quant.json"},
                {"backend": "qlib_backtest", "status": "skipped", "summary": {"reason": "not requested"}},
            ]
        },
        "acceptance_summary": {"side_effects": {"clean_data_mutated": False, "search_worker_started": False, "official_promotion_written": False}},
    })
    write_json(root / "objects" / "validation" / f"factor_run_diagnostics__{report_id}.json", {
        "report_id": report_id,
        "run_status": "success",
        "evaluation_results": {"backend_runs": []},
    })
    write_json(root / "objects" / "validation" / f"factor_evaluation__{report_id}.json", {
        "rank_ic_mean": 0.0305,
        "turnover_mean": 0.2552,
        "long_side_max_drawdown": -0.2329,
    })
    write_json(root / "runs" / report_id / f"run_metadata__{report_id}.json", {
        "report_id": report_id,
        "producer": "step3b",
        "performance_profile": {"version": "factorforge_step3b_performance_profile_v1", "csv_output_profile": {"csv_output_policy": "sample_csv"}},
        "input_io_profile": {
            "daily_basic_selected_format": "parquet",
            "daily_basic_cache_hit": True,
            "daily_basic_cache_path": "/cache/daily_basic",
            "daily_basic_rows": 100,
            "daily_basic_dates": 10,
            "daily_basic_tickers": 20,
            "daily_basic_load_seconds": 0.2,
            "backtest_base_reuse_hit": True,
            "backtest_base_cache_path": "/cache/backtest_base",
        },
        "step4_factor_io_profile": {
            "source": "step4_minute_derived_flow_state_recompute",
            "minute_derived_state_profile": {"status": "ready", "row_count": 100},
            "minute_derived_factor_profile": {"compute_mode": "module_compute_factor_from_derived_state"},
        },
        "step4_factor_csv_policy_observed": {
            "source": "step4_env",
            "csv_output_policy": "sample_csv",
            "factor_csv_write_allowed": False,
            "factor_csv_written_by_step4": False,
        },
    })
    write_json(root / "objects" / "runtime_context" / f"ultimate_loop_report__{report_id}.json", {
        "report_id": report_id,
        "approval_consumed_loop_slot": True,
        "approval_bridge_requires_additional_loop_for_child": True,
        "final_outcome": "max_loops_reached",
        "stop_reason": "max_loops_reached",
    })
    write_json(root / "objects" / "revision_council" / report_id / f"main_agent_council_synthesis__{report_id}.json", {
        "selected_revision": {"law_id": "miller_flow_v7", "child_formula_or_law": "direct_code_law: miller_flow_v7"},
    })
    write_json(root / "objects" / "research_iteration_master" / f"executable_revision_spec__{report_id}.json", {
        "parent_report_id": "PARENT",
        "law_id": "miller_flow_v7",
        "direct_code_law": "direct_code_law: miller_flow_v7",
    })


def main() -> None:
    step4 = load_step4_module()
    old_policy = os.environ.get("FACTORFORGE_CSV_OUTPUT_POLICY")
    os.environ["FACTORFORGE_CSV_OUTPUT_POLICY"] = "sample_csv"
    env_policy = step4.step4_factor_csv_policy_from_step3b({})
    os.environ["FACTORFORGE_CSV_OUTPUT_POLICY"] = "bad_policy"
    invalid_policy_blocks = False
    try:
        step4.step4_factor_csv_policy_from_step3b({})
    except SystemExit as exc:
        invalid_policy_blocks = str(exc).startswith("BLOCK_STEP4_INVALID_FACTOR_CSV_POLICY")
    if old_policy is None:
        os.environ.pop("FACTORFORGE_CSV_OUTPUT_POLICY", None)
    else:
        os.environ["FACTORFORGE_CSV_OUTPUT_POLICY"] = old_policy
    qlib_not_applicable = step4.qlib_native_status_from_backend_runs(
        [
            {
                "backend": "qlib_backtest",
                "status": "skipped",
                "summary": {"qlib_native_status": "not_applicable"},
            }
        ],
        {"backends": {"qlib_native": {"status": "skipped"}}},
    )
    date_coverage_ok = (
        step4._normal_date_value("2025-07-11") == "20250711"
        and step4._normal_date_value("20250711") == "20250711"
    )

    from scripts.summarize_factorforge_run_artifacts import summarize

    with tempfile.TemporaryDirectory(prefix="factorforge_framework_evidence_smoke_") as tmp:
        root = Path(tmp)
        report_id = "FRAMEWORK_EVIDENCE_SMOKE"
        build_summary_fixture(root, report_id)
        summary = summarize(root, report_id)
        checks = {
            "csv_policy_env_sample_blocks_full_csv": (
                env_policy.get("source") == "step4_env"
                and env_policy.get("csv_output_policy") == "sample_csv"
                and env_policy.get("factor_csv_write_allowed") is False
            ),
            "csv_policy_invalid_env_blocks": invalid_policy_blocks,
            "qlib_not_applicable_summary_status": qlib_not_applicable == "not_applicable",
            "coverage_date_formats_normalize": date_coverage_ok,
            "summary_reports_parent_and_law": summary.get("parent_report_id") == "PARENT" and summary.get("selected_law_id") == "miller_flow_v7",
            "summary_reports_direct_code_hash": bool(summary.get("code_law_hash")),
            "summary_reports_derived_state": summary.get("derived_state_proof", {}).get("derived_state_hit") is True,
            "summary_reports_daily_basic_cache": summary.get("daily_basic_cache_proof", {}).get("daily_basic_cache_hit") is True,
            "summary_reports_csv_policy": summary.get("csv_policy_proof", {}).get("source") == "step4_env",
            "summary_reports_core_metrics": summary.get("core_metrics", {}).get("rank_ic_mean") == 0.0305,
            "summary_reports_loop_budget": summary.get("ultimate_loop_budget", {}).get("approval_consumed_loop_slot") is True,
        }
        verdict = "ACCEPT" if all(checks.values()) else "REJECT"
        print(json.dumps({"verdict": verdict, "checks": checks, "summary": summary}, ensure_ascii=False, indent=2, default=str))
        if verdict != "ACCEPT":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
