"""Offline integration of real stage consumers, not a formal research run.

Only runtime roots are redirected. Factor generation, sample writing, Step4
compute, metrics/tables/plots, and Step5 payload/quality handling execute their
real implementations on a fixed synthetic panel.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from factor_factory.formula.pandas_codegen import generate_pandas_formula_code
from factor_factory.formula.parser import parse_formula
from skills.factor_forge_step5.modules.evaluator import build_factor_evaluation
from skills.factor_forge_step5.modules.rules import determine_final_status


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem + "_mode_integration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operator_direct_hybrid_compute_and_metric_consumers_agree(tmp_path, monkeypatch):
    ff = tmp_path / "offline_fixture"
    (ff / "objects").mkdir(parents=True)
    monkeypatch.setenv("FACTORFORGE_ROOT", str(ff))
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    for key in ("FACTORFORGE_SHARED_EVALUATION_CONTEXT", "FACTORFORGE_FORMULA_ENGINE",
                "FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS", "FACTORFORGE_FACTOR_WORKSPACE"):
        monkeypatch.delenv(key, raising=False)
    stage3 = _load(ROOT / "skills/factor-forge-step3/scripts/run_step3b.py")
    stage4 = _load(ROOT / "skills/factor-forge-step4/scripts/run_step4.py")
    adapter = _load(ROOT / "skills/factor-forge-step4/scripts/self_quant_adapter.py")
    import factor_factory.data_access.step4 as data_access
    monkeypatch.setattr(data_access, "RUNS", ff / "runs")
    monkeypatch.setattr(data_access, "OBJ", ff / "objects")

    rng = np.random.default_rng(91)
    days = pd.bdate_range("2024-01-02", periods=24).strftime("%Y%m%d")
    codes = [f"{n:06d}.SZ" for n in range(1, 31)]
    daily = pd.MultiIndex.from_product([days, codes], names=["trade_date", "ts_code"]).to_frame(index=False)
    daily["open"] = 100. + np.tile(np.arange(30), 24)
    daily["close"] = daily.open + rng.normal(size=len(daily))
    daily["pct_chg"] = np.repeat(np.resize([1.2, -.15, 1.5, -.1], 24), 30) + rng.normal(0, .05, len(daily))
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    expected = daily[["ts_code", "trade_date"]].assign(factor_value=daily.close - daily.open)
    formula = parse_formula("close - open", available_columns=list(daily.columns), raise_on_error=True)
    results = {}

    for mode in ("operator", "direct_code", "hybrid"):
        report_id = "IT_OFFLINE_" + mode.upper()
        run = ff / "runs" / report_id
        local_inputs = run / "step3a_local_inputs"
        local_inputs.mkdir(parents=True)
        input_path = local_inputs / f"daily_input__{report_id}.parquet"
        daily.to_parquet(input_path, index=False)
        implementation = tmp_path / (mode + "_factor.py")
        if mode == "operator":
            source = generate_pandas_formula_code(report_id=report_id, factor_id=report_id, formula_ir=formula)
        elif mode == "direct_code":
            source = stage3.ensure_direct_code_keyword_adapter(
                "import numpy as np\n"
                "def compute_factor(daily_df, *, minute_df=None):\n"
                "    values = np.select([np.isfinite(daily_df.close)], [daily_df.close-daily_df.open], default=np.nan)\n"
                "    return daily_df[['ts_code','trade_date']].assign(factor_value=values)\n"
            )
        else:
            source = stage3.generate_hybrid_code(
                report_id=report_id, factor_id=report_id, formula_ir=formula,
                custom_block={"function_name": "apply_custom_block", "source_code":
                    "def apply_custom_block(operator_df, daily_df):\n"
                    "    return operator_df.rename(columns={'operator_value':'factor_value'})"},
                boundary={}, contract={"hybrid_contract_version": "offline_fixture"},
            )
        implementation.write_text(source)
        sample = stage3.generate_first_run_factor_values(
            report_id, report_id, implementation,
            {"input_mode": "daily_only", "daily_df_parquet": str(input_path)},
            {"scope": "offline_engineering_fixture"}, csv_output_policy="no_csv",
        )
        assert sample["is_formal_factor_values"] is False
        assert sample["formal_factor_values_owner"] == "Step4"
        sample_path = run / f"step3b_sample_factor_values__{report_id}.parquet"
        pd.testing.assert_frame_equal(pd.read_parquet(sample_path), expected, check_exact=True)
        formal_path = run / f"factor_values__{report_id}.parquet"
        assert not formal_path.exists()
        computed = stage4.compute_factor_with_contract(_load(implementation), daily, pd.DataFrame())
        computed = computed.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(computed, expected, check_exact=True)
        computed.to_parquet(formal_path, index=False)
        payload = adapter.run_self_quant_quick(report_id)
        assert payload["signal_timing_contract"]["same_day_return_used_as_label"] is False
        payload_path = ff / "evaluations" / report_id / "self_quant_analyzer/evaluation_payload.json"
        payload_path.write_text(json.dumps(payload, allow_nan=False))
        frame = {"report_id": report_id, "factor_id": report_id, "run_status": payload["status"],
                 "output_paths": [str(formal_path)], "evaluation_results": {"backend_runs": [{
                     "backend": "self_quant_analyzer", "status": payload["status"],
                     "payload_path": str(payload_path), "artifact_paths": list(payload["artifacts"].values()),
                 }]}}
        bundle = {"report_id": report_id, "workspace_root": str(ff),
                  "objects": {"factor_run_master": frame}, "paths": {}}
        evaluation = build_factor_evaluation(bundle)
        results[mode] = {"ic": payload["ic_summary"], "long_side": payload["long_side_performance"],
                         "key_metrics": evaluation["backend_summary"][0]["key_metrics"],
                         "quality_verdict": evaluation["step4_quality_gate"]["verdict"],
                         "final_status": determine_final_status(bundle, evaluation)}
        assert evaluation["step4_quality_gate"]["verdict"] != "BLOCK", evaluation["step4_quality_gate"]
        assert len(evaluation["backend_summary"]) == 1
        # A broken current payload must fail even while all old tables remain.
        payload_path.write_text("{broken")
        broken = build_factor_evaluation(bundle)
        assert broken["step4_quality_gate"]["verdict"] == "BLOCK"
        assert determine_final_status(bundle, broken) == "failed"
        payload_path.write_text(json.dumps(payload, allow_nan=False))

    assert results["operator"] == results["direct_code"] == results["hybrid"]
    (tmp_path / "pipeline-receipt.json").write_text(json.dumps({
        "scope": "offline_engineering_fixture_not_formal_research", "rows_per_mode": len(daily),
        "three_modes_exact_equal": True, "results": results,
        "formal_ultimate_or_research_review_executed": False,
    }, indent=2, allow_nan=False))
