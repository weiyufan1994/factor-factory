from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _validator():
    path = Path(__file__).resolve().parents[1] / "skills/factor-forge-step6/scripts/validate_step6.py"
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("step6_primary_validator_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _custom_status() -> dict:
    return {
        "version": "factorforge_step6_evidence_status_v1",
        "wrapper_validation_status": "PASS",
        "primary_evaluator_backend": "study_primary",
        "primary_evaluator_evidence_status": "complete",
        "self_quant_evidence_status": "not_required",
        "qlib_native_status": "not_attempted",
        "long_side_evidence_status": "complete",
        "cost_model_status": "complete",
        "drawdown_geometry_status": "complete",
        "research_decision": "reject",
        "promotion_gate_status": "blocked_by_cost",
    }


def _brief_metrics(module) -> dict:
    return {
        key: 0.1
        for key in module.CORE_LOOP_BRIEF_METRICS
        if key not in module.CUSTOM_PRIMARY_OPTIONAL_LOOP_BRIEF_METRICS
        and key != "long_side_recovery_days"
    }


def test_custom_primary_replaces_self_quant_only_when_declared_complete() -> None:
    module = _validator()
    checks = {item["name"]: item for item in module.validate_evidence_status_contract(_custom_status())}
    assert checks["evidence_status_self_quant"]["ok"] is True
    assert checks["evidence_status_custom_primary_when_self_quant_not_required"]["ok"] is True

    invalid = _custom_status()
    invalid["primary_evaluator_evidence_status"] = "unknown"
    checks = {item["name"]: item for item in module.validate_evidence_status_contract(invalid)}
    assert checks["evidence_status_self_quant"]["ok"] is False
    assert checks["evidence_status_custom_primary_when_self_quant_not_required"]["ok"] is False


def test_custom_primary_loop_brief_allows_only_declared_not_evaluated_diagnostics() -> None:
    module = _validator()
    iteration = {
        "evidence_status": _custom_status(),
        "evidence_summary": {"headline_metrics": {
            "long_side_recovery_status": "NOT_RECOVERED_BY_WINDOW_END",
            "long_side_recovery_lower_bound_days": 195,
            "long_side_recovery_observation_end": "2025-07-11",
        }},
    }
    metrics = _brief_metrics(module)
    assert module.loop_brief_missing_core_metrics(iteration, metrics) == []

    metrics.pop("long_side_sharpe")
    assert module.loop_brief_missing_core_metrics(iteration, metrics) == ["long_side_sharpe"]


def test_legacy_or_undeclared_censoring_cannot_bypass_core_metrics() -> None:
    module = _validator()
    iteration = {
        "evidence_status": {
            **_custom_status(),
            "primary_evaluator_backend": "self_quant_analyzer",
            "primary_evaluator_evidence_status": "complete",
            "self_quant_evidence_status": "complete",
        },
        "evidence_summary": {"headline_metrics": {}},
    }
    missing = module.loop_brief_missing_core_metrics(iteration, _brief_metrics(module))
    assert "long_side_recovery_days" in missing
    assert "rank_ic_ir" in missing
    assert "group_top_decile_mean_return" in missing
