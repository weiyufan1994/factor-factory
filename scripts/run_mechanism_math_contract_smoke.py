#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.mechanism_math.classifier import build_mechanism_math_contract
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract
from factor_factory.artifact_identity import (
    STEP2_SOURCE_CONTRACT_VERSION,
    build_artifact_identity,
    build_formula_hash,
    build_spec_hash,
)

CANONICAL_ROOTS = [
    "objects",
    "runs",
    "evaluations",
    "generated_code",
    "archive",
    "factorforge",
    "data/clean",
]


def is_tmp(path: Path) -> bool:
    raw = str(path)
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = raw
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if item.is_file():
                files.add(str(item.relative_to(REPO_ROOT)))
    return files


def case_result(name: str, ok: bool, expected: str, actual: Any, proof_path: str | None = None) -> dict[str, Any]:
    return {
        "case": name,
        "ok": bool(ok),
        "expected": expected,
        "actual": actual,
        "proof_path": proof_path,
    }


def validate_case(name: str, spec: dict[str, Any], expected_family: str | None = None, expected_status: str = "specified") -> dict[str, Any]:
    contract = build_mechanism_math_contract(spec)
    failures = validate_mechanism_math_contract(contract)
    ok = not failures and contract.get("math_model_status") == expected_status
    if expected_family is not None:
        ok = ok and contract.get("model_family") == expected_family
    return case_result(
        name,
        ok,
        f"valid {expected_status} contract" + (f" with model_family={expected_family}" if expected_family else ""),
        {
            "model_family": contract.get("model_family"),
            "math_model_status": contract.get("math_model_status"),
            "failures": failures,
            "state_or_object": contract.get("state_or_object"),
            "target_functional": contract.get("target_functional"),
            "revision_operators": contract.get("revision_operators"),
        },
    )


def alpha019_formula_specific_case() -> dict[str, Any]:
    spec = {
        "factor_id": "ALPHA019_LIKE",
        "canonical_spec": {
            "formula_text": (
                "multiply("
                "negate(sign(plus(minus(close, delay(close, 7)), delta(close, 7)))), "
                "plus(1, rank(plus(1, sum(returns, 250))))"
                ")"
            ),
            "required_inputs": ["close", "returns"],
            "operators": ["multiply", "negate", "sign", "plus", "minus", "delay", "delta", "rank", "sum"],
        },
        "research_contract": {
            "formula_understanding": {"interaction_structure": "slow_state_x_short_horizon_threshold"},
            "economic_hypothesis": {
                "macro_return_source": "mixed",
                "second_layer": {
                    "subtype": "slow_winner_state_short_horizon_reversal_or_threshold_migration",
                    "expected_counterparty_or_payer": "trend extrapolators and delayed updaters around winner-state pullbacks",
                    "why_they_may_pay": "they extrapolate slow winner state or react late around threshold crossings",
                },
            },
            "math_hypothesis_candidates": [
                {
                    "model_family": "stochastic_process",
                    "process_or_distribution_hypothesis": "return process with slow trend state and short-horizon reversal/dislocation component",
                }
            ],
        },
    }
    contract = build_mechanism_math_contract(spec)
    failures = validate_mechanism_math_contract(contract)
    blob = json.dumps(contract, ensure_ascii=False).lower()
    ok = (
        not failures
        and contract.get("model_family") == "stochastic_process"
        and contract.get("math_model_status") == "specified"
        and all(token in blob for token in ["slow", "short", "threshold", "rank", "sum(returns,250)"])
        and "price_volume_microstructure" not in blob
    )
    return case_result(
        "alpha019_slow_winner_short_reversal_stochastic_process_pass",
        ok,
        "Alpha019-like formula-specific stochastic_process contract, not price-volume template",
        {
            "model_family": contract.get("model_family"),
            "math_model_status": contract.get("math_model_status"),
            "failures": failures,
            "state_or_object": contract.get("state_or_object"),
            "factor_as_estimator": contract.get("factor_as_estimator"),
            "process_hypothesis": contract.get("process_hypothesis"),
            "conditional_distribution_hypothesis": contract.get("conditional_distribution_hypothesis"),
            "formula_understanding": contract.get("formula_understanding"),
        },
    )


def price_only_stale_price_volume_text_case() -> dict[str, Any]:
    spec = {
        "canonical_spec": {
            "formula_text": "rank(delta(close, 20))",
            "required_inputs": ["close"],
            "operators": ["rank", "delta"],
        },
        "research_contract": {
            "economic_mechanism": "published formula may capture behavioral, liquidity, or microstructure effects embedded in ranked price-volume transformations",
            "economic_hypothesis": {
                "macro_return_source": "mixed",
                "second_layer": {
                    "subtype": "short_horizon_price_state_reversal_or_continuation",
                    "expected_counterparty_or_payer": "investors extrapolating recent price states",
                    "why_they_may_pay": "recent price states may contain temporary impact or behavioral extrapolation",
                },
            },
            "math_hypothesis_candidates": [
                {
                    "model_family": "ranked_price_state_process",
                    "state_or_object": "cross-sectional security-day price state",
                    "process_or_distribution_hypothesis": "conditional drift depends on ranked recent price movement",
                    "observable_estimator": "rank(delta(close,20))",
                    "target_functional": "E[r_i,t+1 | price_state_i,t]",
                    "why_suitable": "formula uses only price-state fields",
                }
            ],
        },
    }
    contract = build_mechanism_math_contract(spec)
    failures = validate_mechanism_math_contract(contract)
    features = ((contract.get("formula_understanding") or {}).get("formula_features") or {})
    ok = (
        not failures
        and contract.get("model_family") == "stochastic_process"
        and contract.get("model_family") != "price_volume_microstructure"
        and features.get("has_volume") is False
    )
    return case_result(
        "price_only_formula_stale_price_volume_text_not_microstructure",
        ok,
        "price-only formula with stale price-volume thesis text must not select price_volume_microstructure",
        {
            "model_family": contract.get("model_family"),
            "math_model_status": contract.get("math_model_status"),
            "failures": failures,
            "has_volume": features.get("has_volume"),
            "formula_fields": features.get("fields"),
            "classification_evidence": contract.get("classification_evidence"),
        },
    )


def price_only_bad_structured_price_volume_candidate_case() -> dict[str, Any]:
    spec = {
        "canonical_spec": {
            "formula_text": "rank(delta(close, 20))",
            "required_inputs": ["close"],
            "operators": ["rank", "delta"],
        },
        "research_contract": {
            "economic_hypothesis": {
                "macro_return_source": "mixed",
                "second_layer": {
                    "subtype": "price_volume_pressure",
                    "expected_counterparty_or_payer": "liquidity traders",
                    "why_they_may_pay": "claimed volume pressure despite the formula using only price fields",
                },
            },
            "math_hypothesis_candidates": [
                {
                    "model_family": "price_volume_microstructure",
                    "state_or_object": "price-volume state",
                    "process_or_distribution_hypothesis": "claimed price-volume impact",
                    "observable_estimator": "rank(delta(close,20))",
                    "target_functional": "E[r_i,t+1 | claimed_price_volume_state_i,t]",
                    "why_suitable": "intentionally polluted structured candidate for smoke coverage",
                }
            ],
        },
    }
    contract = build_mechanism_math_contract(spec)
    failures = validate_mechanism_math_contract(contract)
    features = ((contract.get("formula_understanding") or {}).get("formula_features") or {})
    ok = (
        not failures
        and contract.get("model_family") != "price_volume_microstructure"
        and features.get("has_volume") is False
    )
    return case_result(
        "price_only_formula_bad_structured_price_volume_candidate_not_microstructure",
        ok,
        "price-only formula with bad structured price_volume candidate must not select price_volume_microstructure",
        {
            "model_family": contract.get("model_family"),
            "math_model_status": contract.get("math_model_status"),
            "failures": failures,
            "has_volume": features.get("has_volume"),
            "formula_fields": features.get("fields"),
            "classification_evidence": contract.get("classification_evidence"),
        },
    )


def negative_contract_case(name: str, contract: dict[str, Any], expected_code: str) -> dict[str, Any]:
    failures = validate_mechanism_math_contract(contract)
    codes = [item.get("code") for item in failures]
    return case_result(
        name,
        expected_code in codes,
        f"BLOCK with {expected_code}",
        {"codes": codes, "failures": failures},
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_table(path: Path, header: list[str], rows: list[list[Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(item) for item in row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def write_placeholder(path: Path, label: str = "artifact") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((label + "\n").encode("utf-8"))
    return str(path)


def build_metric_bundle() -> dict[str, Any]:
    return {
        "rank_ic_mean": 0.035,
        "rank_ic_std": 0.08,
        "rank_ic_ir": 0.55,
        "pearson_ic_mean": 0.025,
        "pearson_ic_std": 0.07,
        "pearson_ic_ir": 0.40,
        "long_side_mean_return_daily": 0.0008,
        "long_side_annual_return": 0.20,
        "long_side_return_std_daily": 0.006,
        "long_side_annual_volatility": 0.10,
        "long_side_sharpe": 1.20,
        "long_side_max_drawdown": -0.06,
        "long_side_recovery_days": 20,
        "long_side_turnover_mean_daily": 0.05,
        "trading_cogs_daily": 0.00015,
        "trading_cogs_annual": 0.0378,
        "cost_adjusted_return_daily": 0.00065,
        "cost_adjusted_annual_return": 0.1622,
        "cost_adjusted_long_side_sharpe": 0.95,
        "cost_adjusted_long_side_max_drawdown": -0.07,
        "cost_adjusted_long_side_recovery_days": 25,
        "metric_period": "daily",
        "annualization_factor": 252,
        "top_decile_mean_return": 0.16,
        "bottom_decile_mean_return": -0.03,
        "long_short_spread_mean": 0.19,
        "long_short_spread_std": 0.04,
        "long_short_spread_ir": 0.7,
        "long_short_final_nav": 1.12,
        "group_member_count_min": 2,
        "group_member_count_median": 3,
        "group_member_count_max": 4,
    }


def build_legacy_step5_fixture(root: Path, rid: str) -> dict[str, Any]:
    objects = root / "objects"
    eval_dir = root / "evaluations" / rid / "self_quant_analyzer"
    run_dir = root / "runs" / rid
    factor_values = write_table(
        run_dir / "factor_values.csv",
        ["ts_code", "trade_date", "factor_value"],
        [["000001.SZ", "2020-01-02", 0.1], ["000002.SZ", "2020-01-02", 0.2]],
    )

    canonical_spec = {
        "factor_id": rid,
        "factor_name": "Legacy Alpha013-like fixture",
        "formula_text": "delay(correlation(rank(high), rank(volume), 3), 1)",
        "required_inputs": ["high", "volume"],
        "operators": ["correlation", "rank", "delay"],
        "thesis_summary": "Synthetic legacy fixture for mechanism math contract backfill.",
    }
    factor_spec = {
        "report_id": rid,
        "factor_id": rid,
        "source_type": "formula_text",
        "implementation_mode": "operator",
        "contract_version": STEP2_SOURCE_CONTRACT_VERSION,
        "canonical_spec": canonical_spec,
        "implementation_contract": {"mode": "operator", "formula_text": canonical_spec["formula_text"]},
        "research_contract": {"objective": "synthetic_smoke_only"},
    }
    spec_hash = build_spec_hash(factor_spec)
    formula_hash = build_formula_hash(factor_spec)
    branch_id = f"branch_{rid.lower()}"
    run_id = f"run_{rid.lower()}"
    factor_spec["spec_hash"] = spec_hash
    factor_spec["artifact_identity"] = build_artifact_identity(
        report_id=rid,
        factor_id=rid,
        source_type="formula_text",
        implementation_mode="operator",
        contract_version=STEP2_SOURCE_CONTRACT_VERSION,
        producer="step2_legacy_fixture",
        upstream_producer="synthetic_smoke",
        spec_hash=spec_hash,
        branch_id=branch_id,
        artifact_role="factor_spec_master",
        run_id=run_id,
        formula_hash=formula_hash,
    )
    write_json(objects / "factor_spec_master" / f"factor_spec_master__{rid}.json", factor_spec)

    metrics = build_metric_bundle()
    artifacts = {
        "rank_ic_timeseries_png": write_placeholder(eval_dir / "rank_ic_timeseries.png", "png"),
        "pearson_ic_timeseries_png": write_placeholder(eval_dir / "pearson_ic_timeseries.png", "png"),
        "coverage_by_day_png": write_placeholder(eval_dir / "coverage_by_day.png", "png"),
        "quantile_returns_10groups_csv": write_table(
            eval_dir / "quantile_returns_10groups.csv",
            ["trade_date", *[f"q{i}" for i in range(1, 11)]],
            [["2020-01-02", *[0.001 * i for i in range(1, 11)]]],
        ),
        "quantile_nav_10groups_csv": write_table(
            eval_dir / "quantile_nav_10groups.csv",
            ["trade_date", *[f"q{i}" for i in range(1, 11)]],
            [["2020-01-01", *[1.0 for _ in range(10)]], ["2020-01-02", *[1.0 + 0.001 * i for i in range(1, 11)]]],
        ),
        "quantile_counts_10groups_csv": write_table(
            eval_dir / "quantile_counts_10groups.csv",
            ["trade_date", *[f"q{i}" for i in range(1, 11)]],
            [["2020-01-02", *[2 for _ in range(10)]]],
        ),
        "quantile_summary_table_csv": write_table(
            eval_dir / "quantile_summary_table.csv",
            ["group", "mean_return"],
            [[f"q{i}", 0.001 * i] for i in range(1, 11)],
        ),
        "long_short_returns_10groups_csv": write_table(
            eval_dir / "long_short_returns_10groups.csv",
            ["trade_date", "long_short"],
            [["2020-01-02", 0.002]],
        ),
        "long_short_nav_10groups_csv": write_table(
            eval_dir / "long_short_nav_10groups.csv",
            ["trade_date", "long_short"],
            [["2020-01-01", 1.0], ["2020-01-02", 1.002]],
        ),
        "quantile_nav_10groups_png": write_placeholder(eval_dir / "quantile_nav_10groups.png", "png"),
        "quantile_counts_10groups_png": write_placeholder(eval_dir / "quantile_counts_10groups.png", "png"),
        "long_short_nav_10groups_png": write_placeholder(eval_dir / "long_short_nav_10groups.png", "png"),
        "long_side_returns_csv": write_table(eval_dir / "long_side_returns.csv", ["trade_date", "long"], [["2020-01-02", 0.001]]),
        "long_side_nav_csv": write_table(eval_dir / "long_side_nav.csv", ["trade_date", "long"], [["2020-01-01", 1.0], ["2020-01-02", 1.001]]),
        "long_side_turnover_csv": write_table(eval_dir / "long_side_turnover.csv", ["trade_date", "turnover"], [["2020-01-02", 0.05]]),
        "long_side_nav_png": write_placeholder(eval_dir / "long_side_nav.png", "png"),
        "cost_adjusted_long_side_nav_png": write_placeholder(eval_dir / "cost_adjusted_long_side_nav.png", "png"),
    }
    payload = {
        "report_id": rid,
        "factor_id": rid,
        "backend": "self_quant_analyzer",
        "status": "success",
        "standard_metric_contract": {"checks": [{"status": "PASS", "code": "synthetic_smoke"}]},
        "ic_summary": {key: metrics[key] for key in ["rank_ic_mean", "rank_ic_std", "rank_ic_ir", "pearson_ic_mean", "pearson_ic_std", "pearson_ic_ir"]},
        "long_side_performance": {
            key: metrics[key]
            for key in [
                "metric_period",
                "annualization_factor",
                "long_side_mean_return_daily",
                "long_side_annual_return",
                "long_side_return_std_daily",
                "long_side_annual_volatility",
                "long_side_sharpe",
                "long_side_max_drawdown",
                "long_side_recovery_days",
                "long_side_turnover_mean_daily",
                "trading_cogs_daily",
                "trading_cogs_annual",
                "cost_adjusted_return_daily",
                "cost_adjusted_annual_return",
                "cost_adjusted_long_side_sharpe",
                "cost_adjusted_long_side_max_drawdown",
                "cost_adjusted_long_side_recovery_days",
            ]
        },
        "group_backtest_summary": {
            key: metrics[key]
            for key in [
                "top_decile_mean_return",
                "bottom_decile_mean_return",
                "long_short_spread_mean",
                "long_short_spread_std",
                "long_short_spread_ir",
                "long_short_final_nav",
                "group_member_count_min",
                "group_member_count_median",
                "group_member_count_max",
            ]
        },
        "artifacts": artifacts,
        "artifact_paths": list(artifacts.values()),
    }
    payload_path = eval_dir / "evaluation_payload.json"
    write_json(payload_path, payload)

    run_identity = build_artifact_identity(
        report_id=rid,
        factor_id=rid,
        source_type="formula_text",
        implementation_mode="operator",
        contract_version=STEP2_SOURCE_CONTRACT_VERSION,
        producer="step4_fixture",
        upstream_producer="step3b_fixture",
        spec_hash=spec_hash,
        branch_id=branch_id,
        artifact_role="factor_run_master",
        run_id=run_id,
        formula_hash=formula_hash,
    )
    factor_run_master = {
        "report_id": rid,
        "factor_id": rid,
        "run_status": "success",
        "can_enter_step5": True,
        "output_paths": [factor_values],
        "diagnostic_summary": {"row_count": 2, "date_count": 1, "ticker_count": 2, "coverage_ratio": 1.0},
        "sample_window_actual": {"start": "2020-01-01", "end": "2020-01-02"},
        "implementation_mode_decision": {
            "selected_mode": "operator",
            "implementation_source": "synthetic_legacy_backfill_smoke",
        },
        "evaluation_results": {
            "backend_runs": [
                {
                    "backend": "self_quant_analyzer",
                    "status": "success",
                    "payload_path": str(payload_path),
                    "artifact_paths": list(artifacts.values()),
                    "artifact_identity": {**run_identity, "artifact_role": "self_quant_payload", "producer": "self_quant_analyzer"},
                }
            ]
        },
        "artifact_identity": run_identity,
    }
    write_json(objects / "factor_run_master" / f"factor_run_master__{rid}.json", factor_run_master)
    write_json(
        objects / "data_prep_master" / f"data_prep_master__{rid}.json",
        {"report_id": rid, "factor_id": rid, "sample_window": {"start": "2020-01-01", "end": "2020-01-02"}, "data_sources": ["synthetic_smoke"]},
    )
    write_json(
        objects / "handoff" / f"handoff_to_step5__{rid}.json",
        {
            "report_id": rid,
            "factor_id": rid,
            "factor_run_master_path": str(objects / "factor_run_master" / f"factor_run_master__{rid}.json"),
            "artifact_identity": {**run_identity, "artifact_role": "handoff_to_step5", "producer": "step4_fixture"},
        },
    )
    write_json(
        objects / "research_iteration_master" / f"researcher_memo__{rid}.json",
        {
            "report_id": rid,
            "factor_id": rid,
            "memo_type": "synthetic_step6_researcher_agent_memo",
            "scope": "legacy mechanism math backfill smoke only",
            "summary": "Synthetic memo proves Step6 researcher memo plumbing is present; no real factor research was run.",
            "evidence_review": "Uses synthetic self_quant payload created under /tmp.",
            "recommendation": "Validate contract propagation only.",
        },
    )
    return {
        "factor_spec_path": str(objects / "factor_spec_master" / f"factor_spec_master__{rid}.json"),
        "spec_hash": spec_hash,
        "formula_hash": formula_hash,
        "run_id": run_id,
        "branch_id": branch_id,
    }


def legacy_backfill_step5_step6_case(root: Path) -> dict[str, Any]:
    rid = "MECH_MATH_LEGACY_BACKFILL"
    fixture = build_legacy_step5_fixture(root, rid)
    debug_env = dict(os.environ)
    debug_env.pop("FACTORFORGE_ROOT", None)
    debug_env["FACTORFORGE_ALLOW_DIRECT_STEP"] = "1"
    debug_env["FACTORFORGE_DEBUG_ROOT"] = str(root)
    validate_env = dict(os.environ)
    validate_env["FACTORFORGE_ROOT"] = str(root)

    commands = {
        "backfill": [sys.executable, "scripts/backfill_mechanism_math_contract.py", "--report-id", rid, "--factorforge-root", str(root), "--confirm-legacy-artifact"],
        "run_step5": [sys.executable, "skills/factor-forge-step5/scripts/run_step5.py", "--report-id", rid],
        "validate_step5": [sys.executable, "skills/factor-forge-step5/scripts/validate_step5.py", "--report-id", rid],
        "run_step6": [sys.executable, "skills/factor-forge-step6/scripts/run_step6.py", "--report-id", rid],
        "validate_step6": [sys.executable, "skills/factor-forge-step6/scripts/validate_step6.py", "--report-id", rid],
    }
    results: dict[str, Any] = {}
    ok = True
    awaiting_main_agent_memo = False
    for name, cmd in commands.items():
        command_env = debug_env if name in {"run_step5", "run_step6"} else validate_env
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=command_env, text=True, capture_output=True)
        results[name] = {
            "command": cmd,
            "rc": proc.returncode,
            "stdout_tail": proc.stdout[-1600:],
            "stderr_tail": proc.stderr[-1600:],
        }
        if name == "run_step6" and proc.returncode != 0:
            output = proc.stdout + proc.stderr
            awaiting_main_agent_memo = "AWAITING_MAIN_AGENT_MECHANISM_MEMO" in output
            if awaiting_main_agent_memo:
                break
        if proc.returncode != 0:
            ok = False
            break

    spec_after = json.loads(Path(fixture["factor_spec_path"]).read_text(encoding="utf-8"))
    identity = spec_after.get("artifact_identity") or {}
    preserved = {
        "spec_hash": spec_after.get("spec_hash") == fixture["spec_hash"] == identity.get("spec_hash"),
        "formula_hash": fixture["formula_hash"] == identity.get("formula_hash"),
        "run_id": fixture["run_id"] == identity.get("run_id"),
        "branch_id": fixture["branch_id"] == identity.get("branch_id"),
        "canonical_has_no_backfilled_contract": "mechanism_math_contract" not in (spec_after.get("canonical_spec") or {}),
        "canonical_has_no_backfilled_measurement_program": "mechanism_conditioned_measurement_program" not in (spec_after.get("canonical_spec") or {}),
    }
    contract = spec_after.get("mechanism_math_contract") or {}
    measurement_program = spec_after.get("mechanism_conditioned_measurement_program") or {}
    selected_models = [
        item
        for item in ((measurement_program.get("model_selection") or {}).get("candidate_models") or [])
        if isinstance(item, dict) and item.get("selected") is True
    ]
    case_path = root / "objects" / "factor_case_master" / f"factor_case_master__{rid}.json"
    iteration_path = root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json"
    questionnaire_path = root / "objects" / "research_iteration_master" / f"main_agent_mechanism_questionnaire__{rid}.json"
    questionnaire = json.loads(questionnaire_path.read_text(encoding="utf-8")) if questionnaire_path.exists() else {}
    ok = (
        ok
        and awaiting_main_agent_memo
        and all(preserved.values())
        and bool(contract)
        and len(selected_models) == 1
        and selected_models[0].get("model_family") == contract.get("model_family")
        and measurement_program.get("math_tool_selection", {}).get("search_space_policy") == "open_and_mechanism_conditioned"
        and case_path.exists()
        and questionnaire.get("report_id") == rid
        and questionnaire.get("execution_allowed_by_default") is False
    )
    return case_result(
        "legacy_step2_missing_mechanism_math_backfill_reaches_main_agent_gate",
        ok,
        "legacy factor_spec -> migration-only mechanism and measurement contracts -> Step5 PASS -> Step6 requires a current-agent memo",
        {
            "commands": results,
            "lineage_preserved": preserved,
            "contract_status": contract.get("math_model_status"),
            "model_family": contract.get("model_family"),
            "measurement_program_selected_model_family": (
                selected_models[0].get("model_family") if selected_models else None
            ),
            "measurement_program_search_policy": (
                measurement_program.get("math_tool_selection", {}).get("search_space_policy")
            ),
            "factor_case_exists": case_path.exists(),
            "research_iteration_exists": iteration_path.exists(),
            "awaiting_main_agent_memo": awaiting_main_agent_memo,
            "questionnaire_exists": questionnaire_path.exists(),
        },
        str(questionnaire_path) if questionnaire_path.exists() else str(case_path),
    )


def run_backfill_only(root: Path, rid: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    return subprocess.run(
        [sys.executable, "scripts/backfill_mechanism_math_contract.py", "--report-id", rid, "--factorforge-root", str(root), "--confirm-legacy-artifact"],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
    )


def legacy_backfill_requires_explicit_confirmation_case(root: Path) -> dict[str, Any]:
    rid = "MECH_MATH_BACKFILL_CONFIRMATION_REQUIRED"
    fixture = build_legacy_step5_fixture(root, rid)
    spec_path = Path(fixture["factor_spec_path"])
    before = spec_path.read_text(encoding="utf-8")
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/backfill_mechanism_math_contract.py",
            "--report-id",
            rid,
            "--factorforge-root",
            str(root),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    token = "BLOCK_MECHANISM_MATH_BACKFILL_LEGACY_CONFIRMATION_REQUIRED"
    unchanged = spec_path.read_text(encoding="utf-8") == before
    return case_result(
        "legacy_backfill_requires_explicit_confirmation",
        proc.returncode == 1
        and token in (proc.stdout + proc.stderr)
        and unchanged,
        token,
        {
            "rc": proc.returncode,
            "token_present": token in (proc.stdout + proc.stderr),
            "factor_spec_unchanged": unchanged,
        },
        str(spec_path),
    )


def current_measurement_program_cannot_be_legacy_backfilled_case(root: Path) -> dict[str, Any]:
    rid = "MECH_MATH_BACKFILL_CURRENT_PROGRAM"
    fixture = build_legacy_step5_fixture(root, rid)
    initial = run_backfill_only(root, rid)
    spec_path = Path(fixture["factor_spec_path"])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    program_present = bool(spec.get("mechanism_conditioned_measurement_program"))
    spec.pop("mechanism_math_contract", None)
    write_json(spec_path, spec)
    before = spec_path.read_text(encoding="utf-8")
    proc = run_backfill_only(root, rid)
    token = "BLOCK_MECHANISM_MATH_BACKFILL_CURRENT_PROGRAM_PRESENT"
    unchanged = spec_path.read_text(encoding="utf-8") == before
    return case_result(
        "current_measurement_program_cannot_be_legacy_backfilled",
        initial.returncode == 0
        and program_present
        and proc.returncode == 1
        and token in (proc.stdout + proc.stderr)
        and unchanged,
        token,
        {
            "initial_backfill_rc": initial.returncode,
            "program_present": program_present,
            "current_artifact_probe_rc": proc.returncode,
            "token_present": token in (proc.stdout + proc.stderr),
            "factor_spec_unchanged": unchanged,
        },
        str(spec_path),
    )


def legacy_backfill_invalid_handoff_block_case(root: Path) -> dict[str, Any]:
    rid = "MECH_MATH_BACKFILL_INVALID_HANDOFF"
    fixture = build_legacy_step5_fixture(root, rid)
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step5__{rid}.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    invalid_contract = build_mechanism_math_contract(
        {"formula_text": "delta(close, 20)", "required_inputs": ["close"], "operators": ["delta"]}
    )
    invalid_contract.pop("state_or_object", None)
    handoff["mechanism_math_contract"] = invalid_contract
    write_json(handoff_path, handoff)
    before_handoff_text = handoff_path.read_text(encoding="utf-8")
    spec_path = Path(fixture["factor_spec_path"])
    before_spec_text = spec_path.read_text(encoding="utf-8")

    proc = run_backfill_only(root, rid)
    after_handoff_text = handoff_path.read_text(encoding="utf-8")
    after_spec_text = spec_path.read_text(encoding="utf-8")
    token = "BLOCK_MECHANISM_MATH_BACKFILL_EXISTING_INVALID_HANDOFF"
    return case_result(
        "legacy_backfill_existing_invalid_handoff_contract_block",
        proc.returncode != 0
        and token in (proc.stdout + proc.stderr)
        and before_handoff_text == after_handoff_text
        and before_spec_text == after_spec_text
        and "mechanism_math_contract" not in json.loads(after_spec_text),
        f"BLOCK with {token}; handoff and factor_spec unchanged",
        {
            "rc": proc.returncode,
            "token_present": token in (proc.stdout + proc.stderr),
            "handoff_unchanged": before_handoff_text == after_handoff_text,
            "factor_spec_unchanged": before_spec_text == after_spec_text,
            "factor_spec_still_missing_contract": "mechanism_math_contract" not in json.loads(after_spec_text),
            "stdout_tail": proc.stdout[-1200:],
            "stderr_tail": proc.stderr[-1200:],
        },
        str(handoff_path),
    )


def legacy_backfill_conflicting_handoff_block_case(root: Path) -> dict[str, Any]:
    rid = "MECH_MATH_BACKFILL_CONFLICT_HANDOFF"
    fixture = build_legacy_step5_fixture(root, rid)
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step5__{rid}.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    different_valid_contract = build_mechanism_math_contract(
        {"formula_text": "delta(close, 20)", "required_inputs": ["close"], "operators": ["delta"]}
    )
    assert not validate_mechanism_math_contract(different_valid_contract)
    handoff["mechanism_math_contract"] = different_valid_contract
    write_json(handoff_path, handoff)
    before_handoff_text = handoff_path.read_text(encoding="utf-8")
    spec_path = Path(fixture["factor_spec_path"])
    before_spec_text = spec_path.read_text(encoding="utf-8")

    proc = run_backfill_only(root, rid)
    after_handoff_text = handoff_path.read_text(encoding="utf-8")
    after_spec_text = spec_path.read_text(encoding="utf-8")
    token = "BLOCK_MECHANISM_MATH_BACKFILL_HANDOFF_CONFLICT"
    return case_result(
        "legacy_backfill_existing_valid_different_handoff_contract_block",
        proc.returncode != 0
        and token in (proc.stdout + proc.stderr)
        and before_handoff_text == after_handoff_text
        and before_spec_text == after_spec_text
        and "mechanism_math_contract" not in json.loads(after_spec_text),
        f"BLOCK with {token}; handoff and factor_spec unchanged",
        {
            "rc": proc.returncode,
            "token_present": token in (proc.stdout + proc.stderr),
            "handoff_unchanged": before_handoff_text == after_handoff_text,
            "factor_spec_unchanged": before_spec_text == after_spec_text,
            "factor_spec_still_missing_contract": "mechanism_math_contract" not in json.loads(after_spec_text),
            "stdout_tail": proc.stdout[-1200:],
            "stderr_tail": proc.stderr[-1200:],
        },
        str(handoff_path),
    )


def legacy_backfill_existing_invalid_top_level_block_case(root: Path) -> dict[str, Any]:
    rid = "MECH_MATH_BACKFILL_INVALID_TOP_LEVEL"
    fixture = build_legacy_step5_fixture(root, rid)
    spec_path = Path(fixture["factor_spec_path"])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    invalid_contract = build_mechanism_math_contract(
        {"formula_text": "delta(close, 20)", "required_inputs": ["close"], "operators": ["delta"]}
    )
    invalid_contract.pop("target_functional", None)
    spec["mechanism_math_contract"] = invalid_contract
    write_json(spec_path, spec)
    before_spec_text = spec_path.read_text(encoding="utf-8")

    proc = run_backfill_only(root, rid)
    after_spec_text = spec_path.read_text(encoding="utf-8")
    token = "BLOCK_MECHANISM_MATH_BACKFILL_EXISTING_INVALID"
    return case_result(
        "legacy_backfill_existing_invalid_top_level_contract_block",
        proc.returncode != 0
        and token in (proc.stdout + proc.stderr)
        and before_spec_text == after_spec_text,
        f"BLOCK with {token}; factor_spec unchanged",
        {
            "rc": proc.returncode,
            "token_present": token in (proc.stdout + proc.stderr),
            "factor_spec_unchanged": before_spec_text == after_spec_text,
            "stdout_tail": proc.stdout[-1200:],
            "stderr_tail": proc.stderr[-1200:],
        },
        str(spec_path),
    )


def invalid_promotion_brief_case(root: Path) -> dict[str, Any]:
    rid = "MECH_MATH_INVALID_PROMOTE"
    objects = root / "objects" / "research_iteration_master"
    objects.mkdir(parents=True, exist_ok=True)
    brief_path = objects / f"loop_research_brief__{rid}__iter1.json"
    md_path = objects / f"loop_research_brief__{rid}__iter1.md"
    required_metrics = {
        "rank_ic_mean": 0.01,
        "rank_ic_ir": 0.2,
        "pearson_ic_mean": 0.01,
        "pearson_ic_ir": 0.2,
        "long_side_annual_return": 0.05,
        "long_side_annual_volatility": 0.1,
        "long_side_sharpe": 0.5,
        "long_side_max_drawdown": -0.1,
        "long_side_recovery_days": 20,
        "long_side_turnover_mean_daily": 0.1,
        "trading_cogs_annual": 0.0756,
        "cost_adjusted_annual_return": -0.02,
        "cost_adjusted_long_side_sharpe": -0.1,
        "cost_adjusted_long_side_max_drawdown": -0.12,
        "group_top_decile_mean_return": 0.01,
        "group_bottom_decile_mean_return": -0.01,
        "group_long_short_spread_mean": 0.02,
        "group_long_short_spread_ir": 0.4,
    }
    chart_evidence = {
        "rank_ic_timeseries": "missing: fixture",
        "pearson_ic_timeseries": "missing: fixture",
        "long_side_nav": "missing: fixture",
        "cost_adjusted_long_side_nav": "missing: fixture",
        "quantile_nav": "missing: fixture",
        "long_short_nav_diagnostic_only": "missing: fixture",
        "coverage_by_day": "missing: fixture",
    }
    brief = {
        "brief_version": "factorforge_loop_research_brief_v1",
        "report_id": rid,
        "factor_id": rid,
        "iteration_no": 1,
        "decision_snapshot": {"decision": "promote_official", "loop_authorization": "not_needed"},
        "economic_interpretation": {"formula": "x", "mechanism_fit": "strong"},
        "metrics": required_metrics,
        "chart_evidence": chart_evidence,
        "metric_analysis": {},
        "knowledge_comparison": {},
        "next_research_direction": {"why_not_portfolio_fix": "Expression changes only; no forbidden portfolio repair."},
        "final_loop_conclusion": {"current_conclusion": "invalid test", "promotion_requirements": ["already met"]},
        "mechanism_math_summary": {"math_model_status": "invalid", "model_family": "other"},
    }
    brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text("\n".join([f"## {idx}." for idx in range(1, 10)]), encoding="utf-8")
    iteration = {
        "report_id": rid,
        "factor_id": rid,
        "iteration_no": 1,
        "loop_research_brief": {
            "markdown_path": str(md_path),
            "json_path": str(brief_path),
            "brief_version": "factorforge_loop_research_brief_v1",
            "iteration_no": 1,
        },
    }
    code = (
        "import json\n"
        "import importlib.util\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path('skills/factor-forge-step6/scripts').resolve()))\n"
        "spec=importlib.util.spec_from_file_location('validate_step6', Path('skills/factor-forge-step6/scripts/validate_step6.py'))\n"
        "module=importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        f"iteration={json.dumps(iteration)!r}\n"
        "checks=module.loop_research_brief_checks(json.loads(iteration), 'promote_official')\n"
        "bad=[c for c in checks if not c.get('ok')]\n"
        "print(json.dumps({'bad': bad, 'checks': checks}, ensure_ascii=False))\n"
        "raise SystemExit(1 if not any(c.get('name')=='loop_research_brief_invalid_math_no_promotion' and not c.get('ok') for c in checks) else 0)\n"
    )
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return case_result(
        "invalid_math_model_promotion_block",
        proc.returncode == 0,
        "validate_step6 loop brief checks BLOCK invalid math promotion",
        {"rc": proc.returncode, "stdout_tail": proc.stdout[-1200:], "stderr_tail": proc.stderr[-1200:]},
        str(brief_path),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_mechanism_math_contract_smoke_{int(time.time())}")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not is_tmp(root):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT")
        raise SystemExit(1)
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = file_snapshot()

    cases: list[dict[str, Any]] = [
        alpha019_formula_specific_case(),
        price_only_stale_price_volume_text_case(),
        price_only_bad_structured_price_volume_candidate_case(),
        validate_case(
            "valuation_identity_pb_roe_pass",
            {"formula_text": "roe / pb", "required_inputs": ["roe", "pb"], "operators": ["divide"]},
            "valuation_identity",
        ),
        validate_case(
            "momentum_stochastic_process_pass",
            {"formula_text": "delta(close, 20)", "required_inputs": ["close"], "operators": ["delta"]},
            "stochastic_process",
        ),
        validate_case(
            "alpha013_price_volume_microstructure_pass",
            {"formula_text": "correlation(rank(high), rank(volume), 3)", "required_inputs": ["high", "volume"], "operators": ["correlation", "rank"]},
            "price_volume_microstructure",
        ),
        validate_case(
            "alpha016_covariance_price_volume_microstructure_pass",
            {"formula_text": "(-1 * rank(covariance(rank(high), rank(volume), 5)))", "required_inputs": ["high", "volume"], "operators": ["covariance", "rank"]},
            "price_volume_microstructure",
        ),
        validate_case(
            "price_volatility_covariance_not_price_volume_pass",
            {"formula_text": "covariance(rank(close), rank(volatility), 5)", "required_inputs": ["close", "volatility"], "operators": ["covariance", "rank"]},
            "stochastic_process",
        ),
        validate_case(
            "neutralization_linear_projection_pass",
            {"formula_text": "neutralize(raw_signal, industry)", "required_inputs": ["raw_signal", "industry"], "operators": ["neutralize"]},
            "linear_factor_projection",
        ),
        validate_case(
            "neutralized_price_volume_covariance_projection_pass",
            {"formula_text": "neutralize(covariance(rank(high), rank(volume), 5), industry)", "required_inputs": ["high", "volume", "industry"], "operators": ["neutralize", "covariance", "rank"]},
            "linear_factor_projection",
        ),
        validate_case(
            "under_specified_factor_pass",
            {"formula_text": "custom_unknown_blob(x)", "required_inputs": ["x"], "operators": ["custom_unknown_blob"]},
            "other",
            "under_specified",
        ),
    ]

    base = build_mechanism_math_contract({"formula_text": "delta(close, 20)", "required_inputs": ["close"], "operators": ["delta"]})
    missing_state = dict(base)
    missing_state.pop("state_or_object", None)
    cases.append(negative_contract_case("specified_missing_state_block", missing_state, "mechanism_math_state_or_object_missing"))
    missing_target = dict(base)
    missing_target.pop("target_functional", None)
    cases.append(negative_contract_case("specified_missing_target_block", missing_target, "mechanism_math_target_functional_missing"))
    missing_process = dict(base)
    missing_process.pop("process_hypothesis", None)
    cases.append(negative_contract_case("specified_missing_process_hypothesis_block", missing_process, "mechanism_math_process_hypothesis_missing"))
    missing_distribution = dict(base)
    missing_distribution.pop("conditional_distribution_hypothesis", None)
    cases.append(negative_contract_case("specified_missing_conditional_distribution_block", missing_distribution, "mechanism_math_conditional_distribution_hypothesis_missing"))
    missing_mechanism_tests = dict(base)
    missing_mechanism_tests.pop("mechanism_falsification_tests", None)
    cases.append(negative_contract_case("specified_missing_mechanism_falsification_tests_block", missing_mechanism_tests, "mechanism_math_mechanism_falsification_tests_missing"))
    portfolio_repair = json.loads(json.dumps(base))
    portfolio_repair["revision_operators"][0]["math_change"] = "repair the portfolio expression by changing rebalance"
    cases.append(negative_contract_case("portfolio_repair_revision_block", portfolio_repair, "mechanism_math_revision_operator_0_portfolio_repair_forbidden"))
    contradiction = build_mechanism_math_contract({"formula_text": "correlation(high, volume)", "required_inputs": ["high", "volume"], "operators": ["correlation"]})
    contradiction["model_family"] = "valuation_identity"
    contradiction["economic_mechanism"] = "price-volume signal"
    contradiction["factor_as_estimator"] = "price-volume estimator"
    contradiction["state_or_object"] = "price-volume state"
    cases.append(negative_contract_case("valuation_family_price_volume_contradiction_block", contradiction, "mechanism_math_model_family_observable_inputs_contradiction"))
    stale_alpha016_projection = build_mechanism_math_contract({"formula_text": "(-1 * rank(covariance(rank(high), rank(volume), 5)))", "required_inputs": ["high", "volume"], "operators": ["covariance", "rank"]})
    stale_alpha016_projection["model_family"] = "linear_factor_projection"
    stale_alpha016_projection["state_or_object"] = "orthogonalized residual signal state"
    stale_alpha016_projection["factor_as_estimator"] = "the factor applies projection or residualization to estimate signal orthogonal to nuisance exposures"
    cases.append(negative_contract_case("alpha016_stale_projection_family_mismatch_block", stale_alpha016_projection, "mechanism_math_price_volume_dependence_family_mismatch"))
    pure_microstructure_with_projection = build_mechanism_math_contract({"formula_text": "neutralize(covariance(rank(high), rank(volume), 5), industry)", "required_inputs": ["high", "volume", "industry"], "operators": ["neutralize", "covariance", "rank"]})
    pure_microstructure_with_projection["model_family"] = "price_volume_microstructure"
    pure_microstructure_with_projection["state_or_object"] = "latent price-volume pressure or liquidity-shock state"
    pure_microstructure_with_projection["factor_as_estimator"] = "rank covariance estimates price-volume dependence"
    cases.append(negative_contract_case("neutralized_price_volume_as_pure_microstructure_block", pure_microstructure_with_projection, "mechanism_math_price_volume_projection_family_mismatch"))
    invalid = dict(base)
    invalid["math_model_status"] = "invalid"
    invalid["invalid_reason"] = "contradictory model"
    cases.append(negative_contract_case("invalid_contract_self_valid_with_reason_pass", invalid, "__no_failure_expected__") if False else case_result(
        "invalid_contract_with_reason_is_valid_contract_but_not_promotion",
        not validate_mechanism_math_contract(invalid),
        "invalid contract may be stored only with reason; promotion is blocked elsewhere",
        {"failures": validate_mechanism_math_contract(invalid)},
    ))
    cases.append(invalid_promotion_brief_case(root))
    cases.append(legacy_backfill_existing_invalid_top_level_block_case(root))
    cases.append(legacy_backfill_invalid_handoff_block_case(root))
    cases.append(legacy_backfill_conflicting_handoff_block_case(root))
    cases.append(legacy_backfill_requires_explicit_confirmation_case(root))
    cases.append(current_measurement_program_cannot_be_legacy_backfilled_case(root))
    cases.append(legacy_backfill_step5_step6_case(root))

    after = file_snapshot()
    new_files = sorted(after - before)
    pollution = [item for item in new_files if "MECH_MATH" in item or "mechanism_math_contract_smoke" in item]
    verdict = "ACCEPT" if all(item["ok"] for item in cases) and not pollution else "BLOCK"
    summary = {
        "verdict": verdict,
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution},
    }
    summary_path = root / "mechanism_math_contract_smoke_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if verdict != "ACCEPT":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
