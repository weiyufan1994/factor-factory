"""Explicit local-IS bridge for a study-owned primary Step4 evaluator.

It does not manufacture legacy decile/backtest evidence: absent fields remain
``None`` and the evaluator's declared payload remains the sole metric source.
"""
from __future__ import annotations

import math
from typing import Any

PRIMARY_EVALUATOR_SCOPE = "local_is_only"
PRIMARY_EVALUATOR_PLAN_VERSION = "factorforge_primary_evaluator_plan_v1"
PRIMARY_LONG_METRICS = (
    "long_side_annual_return", "long_side_annual_volatility", "long_side_sharpe",
    "long_side_max_drawdown", "long_side_recovery_days", "long_side_turnover_mean_daily",
    "trading_cogs_daily", "cost_adjusted_long_side_sharpe",
)
PRIMARY_GROSS_COUNTERFACTUAL_METRICS = (
    "gross_zero_cost_counterfactual_annual_return",
    "gross_zero_cost_counterfactual_sharpe",
)
PRIMARY_REQUIRED_ARTIFACTS = ("daily_nav", "trades", "monthly_ic", "performance", "coverage")
RIGHT_CENSORED_RECOVERY_STATUS = "NOT_RECOVERED_BY_WINDOW_END"


def primary_evaluator_plan(evaluation_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(evaluation_plan, dict) or not evaluation_plan.get("primary_backend"):
        return None
    backend = str(evaluation_plan.get("primary_backend") or "").strip()
    frequency = str(evaluation_plan.get("frequency") or "").strip().lower()
    scope = str(evaluation_plan.get("scope") or "").strip()
    if not backend:
        raise ValueError("primary_backend is required")
    if backend in {"self_quant_analyzer", "qlib_backtest"}:
        raise ValueError("primary_backend must not alias a builtin backend")
    if frequency not in {"daily", "weekly", "monthly"}:
        raise ValueError("frequency must be daily, weekly, or monthly")
    if scope != PRIMARY_EVALUATOR_SCOPE:
        raise ValueError("custom primary evaluator is local_is_only")
    backends = evaluation_plan.get("backends")
    if not isinstance(backends, list):
        raise ValueError("evaluation_plan.backends must be a list")
    cfg = next((item for item in backends if isinstance(item, dict) and item.get("name") == backend), None)
    if cfg is None:
        raise ValueError("primary_backend must appear in evaluation_plan.backends")
    if not (cfg.get("script_path") or cfg.get("adapter_script")):
        raise ValueError("custom primary backend requires script_path or adapter_script")
    return {"version": str(evaluation_plan.get("primary_evaluator_version") or PRIMARY_EVALUATOR_PLAN_VERSION), "backend": backend, "frequency": frequency, "scope": scope, "backend_config": dict(cfg)}


def validate_primary_evaluator_plan(evaluation_plan: dict[str, Any] | None) -> list[str]:
    try:
        primary_evaluator_plan(evaluation_plan)
    except ValueError as exc:
        return [str(exc)]
    return []


def _finite(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_primary_evaluator_payload(payload: dict[str, Any] | None, evaluation_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    plan = primary_evaluator_plan(evaluation_plan)
    if plan is None:
        return None
    raw = payload if isinstance(payload, dict) else {}
    if raw.get("backend") not in {None, plan["backend"]}:
        return {"backend": plan["backend"], "frequency": plan["frequency"], "status": "invalid_backend_identity", "metrics": {}, "metric_sources": {}}
    ic = raw.get("ic_summary") if isinstance(raw.get("ic_summary"), dict) else {}
    long_side = raw.get("long_side_performance") if isinstance(raw.get("long_side_performance"), dict) else {}
    metrics, sources = {}, {}
    for key in ("rank_ic_mean", "rank_ic_ir", "pearson_ic_mean", "pearson_ic_ir"):
        metrics[key] = _finite(ic.get(key))
        if metrics[key] is not None: sources[key] = f"ic_summary.{key}"
    for key in PRIMARY_LONG_METRICS:
        metrics[key] = _finite(long_side.get(key))
        if metrics[key] is not None: sources[key] = f"long_side_performance.{key}"
    # Optional only: preserve a study's independently simulated same-rules
    # zero-cost account when present.  Gross must never be inferred from net
    # return and COGS.
    for key in PRIMARY_GROSS_COUNTERFACTUAL_METRICS:
        metrics[key] = _finite(long_side.get(key))
        if metrics[key] is not None: sources[key] = f"long_side_performance.{key}"
    for key in ("long_side_recovery_status", "long_side_recovery_lower_bound_days", "long_side_recovery_observation_end"):
        metrics[key] = _finite(long_side.get(key)) if key.endswith("lower_bound_days") else long_side.get(key)
        if metrics[key] is not None: sources[key] = f"long_side_performance.{key}"
    metrics["turnover"] = metrics.get("long_side_turnover_mean_daily")
    metrics["trading_cogs"] = metrics.get("trading_cogs_daily")
    if metrics["turnover"] is not None: sources["turnover"] = "long_side_performance.long_side_turnover_mean_daily"
    if metrics["trading_cogs"] is not None: sources["trading_cogs"] = "long_side_performance.trading_cogs_daily"
    metrics["cost_adjusted_annual_return"] = metrics.get("long_side_annual_return")
    annualization = _finite(long_side.get("annualization_factor"))
    metrics["trading_cogs_annual"] = metrics["trading_cogs"] * annualization if metrics["trading_cogs"] is not None and annualization is not None else None
    metrics["return_basis"] = "net_after_explicit_trading_costs"
    metrics["trading_cogs_included_in_return"] = True
    metrics["metric_period"] = long_side.get("metric_period")
    metrics["annualization_factor"] = annualization
    if metrics["cost_adjusted_annual_return"] is not None: sources["cost_adjusted_annual_return"] = "long_side_performance.long_side_annual_return (net)"
    if metrics["trading_cogs_annual"] is not None: sources["trading_cogs_annual"] = "long_side_performance.trading_cogs_daily * annualization_factor"
    if metrics["metric_period"] is not None: sources["metric_period"] = "long_side_performance.metric_period"
    if annualization is not None: sources["annualization_factor"] = "long_side_performance.annualization_factor"
    return {"backend": plan["backend"], "frequency": plan["frequency"], "scope": plan["scope"], "status": raw.get("status"), "metrics": metrics, "metric_sources": sources, "artifacts": raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {}, "raw_payload": raw}


def primary_payload_missing_evidence(normalized: dict[str, Any] | None) -> list[str]:
    if not isinstance(normalized, dict): return ["primary_payload_missing"]
    metrics = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
    missing = [key for key in ("rank_ic_mean", "pearson_ic_mean", *PRIMARY_LONG_METRICS) if metrics.get(key) is None]
    if "long_side_recovery_days" in missing and metrics.get("long_side_recovery_status") == RIGHT_CENSORED_RECOVERY_STATUS and _finite(metrics.get("long_side_recovery_lower_bound_days")) is not None and isinstance(metrics.get("long_side_recovery_observation_end"), str) and metrics["long_side_recovery_observation_end"].strip():
        missing.remove("long_side_recovery_days")
    if metrics.get("metric_period") != "daily": missing.append("metric_period=daily")
    if metrics.get("annualization_factor") is None: missing.append("annualization_factor")
    return missing


def recovery_evidence_complete(metrics: dict[str, Any] | None) -> bool:
    values = metrics if isinstance(metrics, dict) else {}
    return _finite(values.get("long_side_recovery_days")) is not None or (values.get("long_side_recovery_status") == RIGHT_CENSORED_RECOVERY_STATUS and _finite(values.get("long_side_recovery_lower_bound_days")) is not None and isinstance(values.get("long_side_recovery_observation_end"), str) and bool(values["long_side_recovery_observation_end"].strip()))


def validate_primary_evaluator_payload(payload: dict[str, Any] | None, evaluation_plan: dict[str, Any] | None) -> list[dict[str, str]]:
    normalized = normalize_primary_evaluator_payload(payload, evaluation_plan)
    if normalized is None: return [{"code": "PRIMARY_EVALUATOR_PLAN_MISSING", "message": "custom primary evaluator plan is missing"}]
    raw, metrics = normalized.get("raw_payload") or {}, normalized.get("metrics") or {}
    issues = []
    if normalized.get("status") not in {"success", "partial"}: issues.append({"code": "PRIMARY_EVALUATOR_STATUS_INVALID", "message": "primary evaluator must report success or partial"})
    missing = primary_payload_missing_evidence(normalized)
    if missing: issues.append({"code": "PRIMARY_EVALUATOR_METRICS_MISSING", "message": "primary evaluator has NOT_EVALUATED or missing metrics: " + ",".join(missing)})
    performance = raw.get("performance") if isinstance(raw.get("performance"), dict) else {}
    if performance.get("net_valuation_complete") is not True: issues.append({"code": "PRIMARY_EVALUATOR_NET_VALUATION_INCOMPLETE", "message": "primary evaluator net valuation must be complete"})
    if performance.get("gross_valuation_complete") is not True: issues.append({"code": "PRIMARY_EVALUATOR_GROSS_VALUATION_INCOMPLETE", "message": "primary evaluator gross counterfactual valuation must be complete"})
    if metrics.get("long_side_recovery_days") is None and metrics.get("long_side_recovery_status") != RIGHT_CENSORED_RECOVERY_STATUS: issues.append({"code": "PRIMARY_EVALUATOR_RECOVERY_CENSORING_UNDECLARED", "message": "missing recovery days must declare right-censored NOT_RECOVERED_BY_WINDOW_END evidence"})
    artifacts = normalized.get("artifacts") if isinstance(normalized.get("artifacts"), dict) else {}
    absent = [key for key in PRIMARY_REQUIRED_ARTIFACTS if not artifacts.get(key)]
    if absent: issues.append({"code": "PRIMARY_EVALUATOR_ARTIFACTS_MISSING", "message": "primary evaluator missing artifacts: " + ",".join(absent)})
    return issues
