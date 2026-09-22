from __future__ import annotations

import importlib.util
import math
from pathlib import Path

from factor_factory.primary_evaluator import (
    normalize_primary_evaluator_payload,
    validate_primary_evaluator_payload,
)
from skills.factor_forge_step5.modules.evaluator import build_step4_quality_gate
from skills.factor_forge_step5.modules.case_builder import (
    build_factor_business_review as build_step5_business_review,
    build_long_side_review,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _plan() -> dict:
    return {
        "primary_backend": "mszq_portfolio",
        "primary_evaluator_version": "factorforge_primary_evaluator_plan_v1",
        "frequency": "monthly",
        "scope": "local_is_only",
        "metric_policy": "primary_backend_explicit",
        "backends": [{
            "name": "mszq_portfolio",
            "mode": "monthly_dplus1_vwap_tplus20_local_is",
            "script_path": "/study/implementation/custom_evaluator.py",
            "args": ["--prepared-inputs", "/study/prepared/evaluator.json"],
        }],
    }


def _payload(artifacts: dict[str, str], *, right_censored_recovery: bool = False) -> dict:
    return {
        "backend": "mszq_portfolio",
        "status": "success",
        "schema_id": "study_primary_v1",
        "ic_summary": {"rank_ic_mean": 0.03, "pearson_ic_mean": 0.02},
        "performance": {"net_valuation_complete": True, "gross_valuation_complete": True},
        "long_side_performance": {
            "metric_period": "daily",
            "annualization_factor": 252,
            "long_side_annual_return": 0.11,
            "long_side_annual_volatility": 0.19,
            "long_side_sharpe": 0.58,
            "long_side_max_drawdown": -0.16,
            "long_side_recovery_days": None if right_censored_recovery else 31,
            "long_side_recovery_status": "NOT_RECOVERED_BY_WINDOW_END" if right_censored_recovery else "RECOVERED",
            "long_side_recovery_lower_bound_days": 47 if right_censored_recovery else None,
            "long_side_recovery_observation_end": "2025-07-11" if right_censored_recovery else None,
            "long_side_turnover_mean_daily": 0.04,
            "trading_cogs_daily": 0.00012,
            "cost_adjusted_long_side_sharpe": 0.58,
            "gross_zero_cost_counterfactual_annual_return": 0.14,
            "gross_zero_cost_counterfactual_sharpe": 0.72,
        },
        "artifacts": artifacts,
    }


def test_normalization_uses_only_declared_primary_fields() -> None:
    normalized = normalize_primary_evaluator_payload(_payload({}), _plan())
    assert normalized is not None
    assert normalized["backend"] == "mszq_portfolio"
    assert normalized["frequency"] == "monthly"
    assert normalized["metrics"]["rank_ic_mean"] == 0.03
    assert normalized["metrics"]["rank_ic_ir"] is None
    assert normalized["metrics"]["long_side_sharpe"] == 0.58
    assert normalized["metrics"]["gross_zero_cost_counterfactual_annual_return"] == 0.14
    assert normalized["metric_sources"]["long_side_sharpe"] == "long_side_performance.long_side_sharpe"
    assert normalized["metric_sources"]["gross_zero_cost_counterfactual_annual_return"] == "long_side_performance.gross_zero_cost_counterfactual_annual_return"
    assert "group_top_decile_mean_return" not in normalized["metrics"]


def test_primary_payload_requires_actual_valuation_and_metrics() -> None:
    payload = _payload({key: f"/tmp/{key}.csv" for key in ("daily_nav", "trades", "monthly_ic", "performance", "coverage")})
    assert validate_primary_evaluator_payload(payload, _plan()) == []
    payload["performance"]["gross_valuation_complete"] = False
    codes = {item["code"] for item in validate_primary_evaluator_payload(payload, _plan())}
    assert "PRIMARY_EVALUATOR_GROSS_VALUATION_INCOMPLETE" in codes


def test_primary_partial_no_trade_or_unknown_valuation_stays_missing_not_zero() -> None:
    no_trade = _payload({})
    no_trade["status"] = "partial"
    no_trade["long_side_performance"]["long_side_sharpe"] = None
    no_trade["long_side_performance"]["cost_adjusted_long_side_sharpe"] = None
    normalized = normalize_primary_evaluator_payload(no_trade, _plan())
    assert normalized is not None
    assert normalized["metrics"]["long_side_sharpe"] is None
    assert normalized["metrics"]["rank_ic_ir"] is None
    codes = {item["code"] for item in validate_primary_evaluator_payload(no_trade, _plan())}
    assert "PRIMARY_EVALUATOR_METRICS_MISSING" in codes
    unknown = _payload({})
    unknown["status"] = "partial"
    unknown["performance"]["net_valuation_complete"] = False
    codes = {item["code"] for item in validate_primary_evaluator_payload(unknown, _plan())}
    assert "PRIMARY_EVALUATOR_NET_VALUATION_INCOMPLETE" in codes


def test_right_censored_recovery_is_complete_evidence_but_not_a_recovered_day_count() -> None:
    payload = _payload(
        {key: f"/tmp/{key}.csv" for key in ("daily_nav", "trades", "monthly_ic", "performance", "coverage")},
        right_censored_recovery=True,
    )
    normalized = normalize_primary_evaluator_payload(payload, _plan())
    assert normalized is not None
    assert normalized["metrics"]["long_side_recovery_days"] is None
    assert normalized["metrics"]["long_side_recovery_status"] == "NOT_RECOVERED_BY_WINDOW_END"
    assert validate_primary_evaluator_payload(payload, _plan()) == []


def test_step5_gate_accepts_declared_right_censoring_as_observed_evidence(tmp_path: Path) -> None:
    artifacts = {}
    for key in ("daily_nav", "trades", "monthly_ic", "performance", "coverage"):
        path = tmp_path / f"{key}.csv"
        path.write_text("observed\n1\n", encoding="utf-8")
        artifacts[key] = str(path)
    gate = build_step4_quality_gate(
        [{
            "backend": "mszq_portfolio",
            "status": "success",
            "payload": _payload(artifacts, right_censored_recovery=True),
            "payload_path": "payload.json",
        }],
        {"run_status": "success", "evaluation_plan": _plan()},
    )
    assert gate["verdict"] == "PASS"


def test_step5_primary_gate_checks_real_custom_artifacts_without_deciles(tmp_path: Path) -> None:
    artifacts = {}
    for key in ("daily_nav", "trades", "monthly_ic", "performance", "coverage"):
        path = tmp_path / f"{key}.csv"
        path.write_text("observed\n1\n", encoding="utf-8")
        artifacts[key] = str(path)
    payload = _payload(artifacts)
    gate = build_step4_quality_gate(
        [{"backend": "mszq_portfolio", "status": "success", "payload": payload, "payload_path": "payload.json"}],
        {"run_status": "success", "evaluation_plan": _plan()},
    )
    assert gate["verdict"] == "PASS"
    assert not any("DECILE" in item["code"] for item in gate["issues"])


def test_step5_rules_close_complete_declared_primary_with_right_censoring(tmp_path: Path) -> None:
    """A primary payload is complete evidence even when recovery is censored."""
    artifacts = {}
    for key in ("daily_nav", "trades", "monthly_ic", "performance", "coverage"):
        path = tmp_path / f"{key}.csv"
        path.write_text("observed\n1\n", encoding="utf-8")
        artifacts[key] = str(path)
    payload = _payload(artifacts, right_censored_recovery=True)
    payload["long_side_performance"]["long_side_annual_return"] = -0.04
    payload["long_side_performance"]["long_side_sharpe"] = -0.10
    payload["long_side_performance"]["cost_adjusted_long_side_sharpe"] = -0.10
    normalized = normalize_primary_evaluator_payload(payload, _plan())
    assert normalized is not None
    output = tmp_path / "factor.parquet"
    output.write_text("placeholder", encoding="utf-8")
    bundle = {"objects": {"factor_run_master": {
        "run_status": "success", "can_enter_step5": True,
        "output_paths": [str(output)], "evaluation_plan": _plan(),
    }}}
    evaluation = {
        "artifact_ready": True,
        "step4_quality_gate": {"verdict": "PASS"},
        "backend_summary": [{
            "backend": "mszq_portfolio", "status": "success",
            "key_metrics": normalized["metrics"],
        }],
    }
    for relative in (
        "skills/factor-forge-step5/modules/rules.py",
        "skills/factor_forge_step5/modules/rules.py",
    ):
        spec = importlib.util.spec_from_file_location("rules_primary_status_" + relative.replace("/", "_"), REPO_ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        assert module.determine_final_status(bundle, evaluation) == "validated"

        missing_primary = {**evaluation, "backend_summary": [{
            "backend": "other_backend", "status": "success",
            "key_metrics": normalized["metrics"],
        }]}
        assert module.determine_final_status(bundle, missing_primary) == "partial"


def test_step5_validator_primary_evidence_requires_explicit_gross_counterfactual() -> None:
    path = REPO_ROOT / "skills/factor-forge-step5/scripts/validate_step5.py"
    spec = importlib.util.spec_from_file_location("step5_primary_validator_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    payload = _payload({}, right_censored_recovery=True)
    payload["long_side_performance"]["long_side_annual_return"] = -0.04
    payload["long_side_performance"]["long_side_sharpe"] = -0.10
    payload["long_side_performance"]["cost_adjusted_long_side_sharpe"] = -0.10
    normalized = normalize_primary_evaluator_payload(payload, _plan())
    assert normalized is not None
    frm = {"evaluation_plan": _plan()}
    evaluation = {"backend_summary": [{
        "backend": "mszq_portfolio", "status": "success",
        "key_metrics": normalized["metrics"],
    }]}
    plan, metrics, missing = module.custom_primary_evidence(frm, evaluation)
    assert plan and plan["backend"] == "mszq_portfolio"
    assert metrics["long_side_annual_return"] == -0.04
    assert missing == []

    no_gross = {**normalized["metrics"]}
    no_gross["gross_zero_cost_counterfactual_annual_return"] = None
    _, _, missing = module.custom_primary_evidence(frm, {"backend_summary": [{
        "backend": "mszq_portfolio", "status": "success", "key_metrics": no_gross,
    }]})
    assert "gross_zero_cost_counterfactual_annual_return" in missing


def test_step5_primary_net_cost_and_right_censored_recovery_are_preserved() -> None:
    normalized = normalize_primary_evaluator_payload(_payload({}, right_censored_recovery=True), _plan())
    assert normalized is not None
    metrics = normalized["metrics"]
    review = build_step5_business_review(metrics)
    quality = review["factor_business_quality"]
    assert quality["return_basis"] == "net_after_explicit_trading_costs"
    assert quality["trading_cogs_already_included_in_return"] is True
    assert quality["gross_revenue"] is None
    assert quality["net_revenue_after_cogs"] == 0.11
    assert math.isclose(review["economic_net_alpha"], 0.11 - 0.5 * 0.19 ** 2 - 0.38 * 0.03 - 0.16 / 6.0)
    assert review["recovery_status"] == "right_censored_not_recovered"
    assert review["recovery_lower_bound_days"] == 47
    assert review["recovery_observation_end"] == "2025-07-11"
    long_review = build_long_side_review({"backend_summary": [{"backend": "mszq_portfolio", "key_metrics": metrics}]})
    assert long_review["status"] == "mixed"
    assert "right-censored" in long_review["note"]


def test_step5_legacy_plan_still_requires_self_quant() -> None:
    gate = build_step4_quality_gate(
        [{"backend": "mszq_portfolio", "status": "success", "payload": {"status": "success"}}],
        {"run_status": "success", "evaluation_plan": {"backends": [{"name": "mszq_portfolio"}] }},
    )
    assert any(item["code"] == "SELF_QUANT_BACKEND_MISSING" for item in gate["issues"])


def test_step3_prepared_plan_is_local_and_rejects_builtin_alias() -> None:
    path = REPO_ROOT / "skills/factor-forge-step3/scripts/run_step3.py"
    spec = importlib.util.spec_from_file_location("step3_primary_plan_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    prepared = {
        "input_mode": "derived_state_with_daily",
        "sample_window_actual": {"start": "20160104", "end": "20250711"},
        "daily_df_parquet": "study/full/daily.parquet",
        "derived_state_root": "study/full/state",
        "calendar_dates": ["20160104"],
        "step3b_daily_df_parquet": "study/sample/daily.parquet",
        "step3b_derived_state_root": "study/sample/state",
        "step3b_calendar_dates": ["20160104"],
        "step3b_sample_window": {"start": "20160104", "end": "20160331"},
        "evaluation_plan": _plan(),
    }
    assert module.validate_prepared_local_inputs(prepared)["evaluation_plan"]["primary_backend"] == "mszq_portfolio"
    prepared["evaluation_plan"] = {**_plan(), "primary_backend": "self_quant_analyzer"}
    try:
        module.validate_prepared_local_inputs(prepared)
    except SystemExit as exc:
        assert "EVALUATION_PLAN_INVALID" in str(exc)
    else:
        raise AssertionError("builtin alias must be rejected")


def test_step4_preserves_explicit_primary_plan() -> None:
    path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location("step4_primary_plan_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    resolved = module.build_evaluation_plan({"evaluation_plan": _plan()})
    assert resolved["primary_backend"] == "mszq_portfolio"
    assert resolved["frequency"] == "monthly"
    assert resolved["scope"] == "local_is_only"


def test_step6_headline_metrics_reads_declared_primary_not_self_quant() -> None:
    path = REPO_ROOT / "skills/factor-forge-step6/scripts/run_step6.py"
    spec = importlib.util.spec_from_file_location("step6_primary_plan_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    metrics = module.extract_headline_metrics(
        {"mszq_portfolio": _payload({})}, _plan(),
    )
    assert metrics["primary_evaluator_backend"] == "mszq_portfolio"
    assert metrics["rank_ic_mean"] == 0.03
    assert "group_top_decile_mean_return" not in metrics


def test_step6_does_not_charge_primary_net_return_twice_for_trading_cogs() -> None:
    path = REPO_ROOT / "skills/factor-forge-step6/scripts/run_step6.py"
    spec = importlib.util.spec_from_file_location("step6_primary_cost_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    payload = _payload({}, right_censored_recovery=True)
    metrics = module.extract_headline_metrics({"mszq_portfolio": payload}, _plan())
    review = module.build_factor_business_review(metrics)
    quality = review["factor_business_quality"]
    assert quality["trading_cogs_already_included_in_return"] is True
    assert quality["gross_revenue"] is None
    assert quality["net_revenue_after_cogs"] == 0.11
    assert module.build_long_side_adoption_review(metrics)["long_side_status"] == "mixed"


def test_step6_brief_labels_primary_net_and_only_uses_observed_gross_counterfactual() -> None:
    path = REPO_ROOT / "skills/factor-forge-step6/scripts/run_step6.py"
    spec = importlib.util.spec_from_file_location("step6_primary_brief_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    normalized = normalize_primary_evaluator_payload(_payload({}), _plan())
    assert normalized is not None
    brief = module.build_loop_research_brief(
        {"evidence_summary": {"headline_metrics": normalized["metrics"]}},
        {},
    )
    assert any(value.startswith("Gross long-side annual return is positive") for value in brief["metric_analysis"]["supporting_evidence"])
    markdown = module.render_loop_research_brief_markdown(brief)
    assert "Long-side net annual return" in markdown
    assert "Gross zero-cost counterfactual annual return" in markdown
    payload = _payload({})
    del payload["long_side_performance"]["gross_zero_cost_counterfactual_annual_return"]
    normalized_without_gross = normalize_primary_evaluator_payload(payload, _plan())
    assert normalized_without_gross is not None
    brief_without_gross = module.build_loop_research_brief(
        {"evidence_summary": {"headline_metrics": normalized_without_gross["metrics"]}},
        {},
    )
    assert any("Net long-side annual return is positive" in value for value in brief_without_gross["metric_analysis"]["supporting_evidence"])
    assert not any(value.startswith("Gross long-side") for value in brief_without_gross["metric_analysis"]["supporting_evidence"])


def test_step6_right_censor_is_inconclusive_not_a_missing_evidence_block() -> None:
    path = REPO_ROOT / "skills/factor-forge-step6/scripts/run_step6.py"
    spec = importlib.util.spec_from_file_location("step6_primary_censor_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    payload = _payload({}, right_censored_recovery=True)
    metrics = module.extract_headline_metrics({"mszq_portfolio": payload}, _plan())
    bundle = {
        "factor_run_master": {
            "evaluation_plan": _plan(),
            "evaluation_results": {"backend_runs": [{"backend": "mszq_portfolio", "status": "success"}]},
            "diagnostic_summary": {"row_count": 10, "date_count": 2, "ticker_count": 5},
            "implementation_mode_decision": {"selected_mode": "direct_code"},
        },
        "factor_case_master": {"evidence_quality": {"identity_chain_verified": True, "long_side_metrics_present": True}},
        "factor_evaluation": {},
    }
    audit = module.build_evidence_audit(bundle, {"mszq_portfolio": payload}, metrics)
    assert audit["long_side_evidence_quality"]["recovery_status"] == "right_censored_not_recovered"
    assert audit["long_side_evidence_quality"]["long_side_verdict"] == "inconclusive"
    assert audit["evidence_verdict"] == "usable_with_warnings"
