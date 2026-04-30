from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .rules import build_evaluation_summary


PLACEHOLDER_NEXT_ACTIONS = {
    "validated": [
        "Write back durable factor case knowledge",
        "Run robustness extension on wider sample window",
        "Compare expression-direction variants that preserve long-side-only adoption constraints",
    ],
    "partial": [
        "Fill missing evaluation backend outputs",
        "Repair archive or validation gaps and rerun Step 5",
    ],
    "failed": [
        "Repair Step 4 or upstream handoff before rerunning Step 5",
        "Restore missing run artifacts or evaluation payloads",
    ],
}


LONG_ONLY_ADOPTION_CONSTRAINTS = {
    "no_short_selling": True,
    "no_direct_decile_trading": True,
    "primary_objective": "long_side_risk_adjusted_alpha",
    "revision_scope": "factor_expression_and_step3b_code_only",
    "forbidden_decision_basis": [
        "short_leg_returns",
        "long_short_spread_as_adoption_metric",
        "direct_decile_portfolio_trading",
        "portfolio_expression_repair",
    ],
}

DEFAULT_TURNOVER_COST_RATE = 0.003

LONG_SIDE_PERFORMANCE_THRESHOLDS = {
    "candidate_min_sharpe": 0.50,
    "official_min_sharpe": 0.80,
    "max_drawdown_soft_limit": -0.35,
    "recovery_days_soft_limit": 252,
    "volatility_drag_model": "log_growth_proxy = mean_return - 0.5 * volatility^2",
    "default_turnover_cost_rate": DEFAULT_TURNOVER_COST_RATE,
    "trading_cogs_model": "annual_trading_cogs = daily_turnover * 0.003 * 252 when explicit costs are missing",
    "risk_capital_model": "risk_capital_required = 2.0 * volatility unless VaR/ES is available",
    "drawdown_provision_model": "drawdown_provision = abs(max_drawdown) / expected_drawdown_cycle_years",
    "default_required_return_on_risk_capital": 0.03,
    "default_expected_drawdown_cycle_years": 6.0,
    "business_analogy": {
        "revenue": "long-side expected return / risk premium",
        "cogs": "transaction cost, explicit impact cost, and turnover cost",
        "volatility_drag": "stochastic-process drag on geometric growth, not direct COGS",
        "risk_capital": "capital buffer implied by VaR/ES or volatility",
        "capital_impairment": "maximum drawdown / asset impairment",
        "drawdown_provision": "strategic risk reserve calibrated by drawdown, VaR, ES, and cycle length",
        "payback": "time required to recover from drawdown",
        "risk_budget_driver": "drawdown depth, recovery time, and confidence in repeatability",
    },
}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _first_metric(metrics: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = _safe_float(metrics.get(key))
        if value is not None:
            return value
    return None


def _collect_backend_metrics(evaluation: Dict[str, Any]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for backend in evaluation.get("backend_summary") or []:
        if not isinstance(backend, dict):
            continue
        key_metrics = backend.get("key_metrics") or {}
        if not isinstance(key_metrics, dict):
            continue
        for key, value in key_metrics.items():
            metrics.setdefault(str(key), value)
            name = backend.get("backend")
            if name:
                metrics.setdefault(f"{name}_{key}", value)
    return metrics


def build_factor_business_review(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Translate long-side performance into a factor-as-business lens."""
    mean_return = _first_metric(metrics, [
        "long_side_annual_return",
        "self_quant_analyzer_long_side_annual_return",
        "cost_adjusted_annual_return",
        "self_quant_analyzer_cost_adjusted_annual_return",
    ])
    volatility = _first_metric(metrics, [
        "long_side_annual_volatility",
        "self_quant_analyzer_long_side_annual_volatility",
        "cost_adjusted_annual_volatility",
        "self_quant_analyzer_cost_adjusted_annual_volatility",
    ])
    sharpe = _first_metric(metrics, [
        "long_side_sharpe",
        "self_quant_analyzer_long_side_sharpe",
        "cost_adjusted_long_side_sharpe",
        "self_quant_analyzer_cost_adjusted_long_side_sharpe",
    ])
    max_drawdown = _first_metric(metrics, [
        "long_side_max_drawdown",
        "top_decile_max_drawdown",
        "max_drawdown",
        "self_quant_analyzer_max_drawdown",
        "qlib_backtest_max_drawdown",
    ])
    recovery_days = _first_metric(metrics, [
        "long_side_recovery_days",
        "top_decile_recovery_days",
        "recovery_days",
        "drawdown_recovery_days",
    ])
    trading_cogs = _first_metric(metrics, [
        "trading_cogs_annual",
        "self_quant_analyzer_trading_cogs_annual",
    ])
    turnover = _first_metric(metrics, [
        "long_side_turnover_mean_daily",
        "self_quant_analyzer_long_side_turnover_mean_daily",
        "long_side_turnover",
        "turnover_mean",
        "self_quant_analyzer_turnover_mean",
    ])
    trading_cogs_source = "explicit" if trading_cogs is not None else "missing"
    if trading_cogs is None and turnover is not None:
        trading_cogs = abs(turnover) * DEFAULT_TURNOVER_COST_RATE * 252
        trading_cogs_source = "estimated_from_turnover_30bps"
    value_at_risk = _first_metric(metrics, [
        "value_at_risk",
        "var_95",
        "var_99",
        "long_side_var",
    ])
    expected_shortfall = _first_metric(metrics, [
        "expected_shortfall",
        "es_95",
        "es_99",
        "long_side_expected_shortfall",
    ])
    volatility_drag = None
    log_growth_proxy = None
    if mean_return is not None and volatility is not None:
        volatility_drag = -0.5 * volatility * volatility
        log_growth_proxy = mean_return + volatility_drag

    thresholds = LONG_SIDE_PERFORMANCE_THRESHOLDS
    net_revenue_after_cogs = mean_return - trading_cogs if mean_return is not None and trading_cogs is not None else None
    risk_capital_required = None
    if expected_shortfall is not None:
        risk_capital_required = abs(expected_shortfall)
    elif value_at_risk is not None:
        risk_capital_required = abs(value_at_risk)
    elif volatility is not None:
        risk_capital_required = 2.0 * abs(volatility)
    capital_charge = (
        risk_capital_required * thresholds["default_required_return_on_risk_capital"]
        if risk_capital_required is not None
        else None
    )
    drawdown_provision = (
        abs(max_drawdown) / thresholds["default_expected_drawdown_cycle_years"]
        if max_drawdown is not None
        else None
    )
    economic_net_alpha = None
    if mean_return is not None:
        economic_net_alpha = (
            mean_return
            - (trading_cogs or 0.0)
            + (volatility_drag or 0.0)
            - (capital_charge or 0.0)
            - (drawdown_provision or 0.0)
        )
    calmar = (
        mean_return / abs(max_drawdown)
        if mean_return is not None and max_drawdown not in {None, 0}
        else None
    )
    raroc = (
        economic_net_alpha / risk_capital_required
        if economic_net_alpha is not None and risk_capital_required not in {None, 0}
        else None
    )

    sharpe_status = "missing"
    if sharpe is not None:
        if sharpe >= thresholds["official_min_sharpe"]:
            sharpe_status = "official_ready"
        elif sharpe >= thresholds["candidate_min_sharpe"]:
            sharpe_status = "candidate"
        else:
            sharpe_status = "below_threshold"

    drawdown_status = "missing"
    if max_drawdown is not None:
        drawdown_status = "acceptable" if max_drawdown >= thresholds["max_drawdown_soft_limit"] else "too_deep"

    recovery_status = "missing"
    if recovery_days is not None:
        recovery_status = "acceptable" if recovery_days <= thresholds["recovery_days_soft_limit"] else "too_slow"

    return {
        "thresholds": thresholds,
        "metric_unit_policy": {
            "return_unit": "annualized",
            "volatility_unit": "annualized",
            "cost_unit": "annualized",
            "turnover_unit": "daily_mean",
            "source": "Step4 long_side_performance contract",
        },
        "factor_business_quality": {
            "gross_revenue": mean_return,
            "trading_cogs": trading_cogs,
            "trading_cogs_source": trading_cogs_source,
            "default_turnover_cost_rate": DEFAULT_TURNOVER_COST_RATE,
            "turnover_proxy": turnover,
            "net_revenue_after_cogs": net_revenue_after_cogs,
            "cogs_status": "explicit_or_estimated" if trading_cogs is not None else "missing_turnover_and_explicit_trading_cost",
            "volatility": volatility,
            "volatility_drag": volatility_drag,
            "geometric_profit_proxy": log_growth_proxy,
            "risk_capital_required": risk_capital_required,
            "capital_charge": capital_charge,
            "value_at_risk": value_at_risk,
            "expected_shortfall": expected_shortfall,
            "capital_impairment": max_drawdown,
            "drawdown_provision": drawdown_provision,
            "payback_days": recovery_days,
            "economic_net_alpha": economic_net_alpha,
            "calmar_ratio": calmar,
            "raroc": raroc,
            "cost_basis_status": (
                "complete_enough"
                if trading_cogs is not None and (value_at_risk is not None or expected_shortfall is not None)
                else "incomplete_cost_basis"
            ),
        },
        "revenue_proxy_mean_return": mean_return,
        "trading_cogs": trading_cogs,
        "net_revenue_after_cogs": net_revenue_after_cogs,
        "volatility_proxy": volatility,
        "volatility_drag": volatility_drag,
        "geometric_profit_proxy": log_growth_proxy,
        "risk_capital_required": risk_capital_required,
        "capital_charge": capital_charge,
        "drawdown_provision": drawdown_provision,
        "economic_net_alpha": economic_net_alpha,
        "sharpe_ratio": sharpe,
        "sharpe_status": sharpe_status,
        "capital_expenditure_proxy_max_drawdown": max_drawdown,
        "drawdown_status": drawdown_status,
        "depreciation_or_payback_proxy_recovery_days": recovery_days,
        "recovery_status": recovery_status,
        "risk_budget_note": (
            "Allocate risk budget from Sharpe, explicit trading COGS, volatility drag, risk capital, drawdown depth, "
            "and recovery time; a high-revenue factor with weak economic net alpha can still be unfinanceable."
        ),
    }


def build_long_side_review(evaluation: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _collect_backend_metrics(evaluation)
    top_return = _first_metric(metrics, [
        "long_side_annual_return",
        "self_quant_analyzer_long_side_annual_return",
    ])
    bottom_return = _safe_float(metrics.get("bottom_decile_mean_return"))
    rank_ic = _safe_float(metrics.get("rank_ic_mean"))
    business_review = build_factor_business_review(metrics)
    sharpe_status = business_review.get("sharpe_status")
    drawdown_status = business_review.get("drawdown_status")
    if top_return is None:
        status = "unknown"
        note = "Long-side highest-score group return is missing; Step6 must not promote from short-leg or long-short evidence."
    elif sharpe_status == "missing":
        status = "unknown"
        note = "Long-side return exists but Sharpe evidence is missing; do not promote until Step4 emits risk-adjusted long-side performance."
    elif top_return > 0 and sharpe_status == "official_ready" and drawdown_status != "too_deep" and (rank_ic is None or rank_ic > 0):
        status = "official_ready"
        note = "Highest-score long side has positive revenue, Sharpe clears the official threshold, and drawdown is not beyond the soft limit."
    elif top_return > 0 and sharpe_status in {"candidate", "official_ready"} and (rank_ic is None or rank_ic > 0):
        status = "supportive"
        note = "Highest-score long side is positive and risk-adjusted performance clears the candidate Sharpe threshold."
    elif top_return > 0 and sharpe_status == "below_threshold":
        status = "mixed"
        note = "Highest-score long side is positive, but risk-adjusted performance is below the candidate Sharpe threshold."
    elif top_return > 0 and (rank_ic is None or rank_ic > 0):
        status = "mixed"
        note = "Highest-score long side is positive, but the risk-adjusted evidence is incomplete."
    elif top_return > 0:
        status = "mixed"
        note = "Highest-score long-side group is positive, but rank evidence is not cleanly aligned."
    else:
        status = "failed"
        note = "Highest-score long-side group is not positive; do not adopt even if short-side or long-short diagnostics look good."
    if top_return is not None and bottom_return is not None:
        monotonicity = "top_group_above_bottom_group" if top_return > bottom_return else "top_group_not_above_bottom_group"
    else:
        monotonicity = "insufficient_group_evidence"
    return {
        "policy": LONG_ONLY_ADOPTION_CONSTRAINTS,
        "status": status,
        "note": note,
        "top_group_mean_return": top_return,
        "top_group_return_unit": "annualized_long_side_return",
        "bottom_group_mean_return": bottom_return,
        "rank_ic_mean": rank_ic,
        "factor_as_business_review": business_review,
        "monotonicity_diagnostic": monotonicity,
        "diagnostic_only": [
            "long_short_spread",
            "short_leg_return",
            "decile_portfolio_nav",
        ],
        "adoption_rule": (
            "Official admission requires long-side risk-adjusted performance, not raw return alone: "
            "positive long-side return, Sharpe above the official threshold, acceptable drawdown/recovery, "
            "and a defensible monotonic economic expression."
        ),
    }


def build_step5_math_discipline_review(bundle: Dict[str, Any], evaluation: Dict[str, Any]) -> Dict[str, Any]:
    """Build the Step5 research-gate fields consumed by Step6 and validators."""
    fsm = bundle["objects"].get("factor_spec_master") or {}
    frm = bundle["objects"].get("factor_run_master") or {}
    canonical = fsm.get("canonical_spec") or {}
    formula_text = str(canonical.get("formula_text") or "")
    operators = [str(item).lower() for item in _as_list(canonical.get("operators"))]
    preprocessing = [str(item).lower() for item in _as_list(canonical.get("preprocessing"))]
    ts_steps = [str(item).lower() for item in _as_list(canonical.get("time_series_steps"))]
    cs_steps = [str(item).lower() for item in _as_list(canonical.get("cross_sectional_steps"))]
    text_blob = " ".join([formula_text.lower(), *operators, *preprocessing, *ts_steps, *cs_steps])

    if any(token in text_blob for token in ["future", "lead", "lookahead", "forward return", "未来收益"]):
        information_set_legality = "illegal_potential_forward_reference"
    elif any(token in text_blob for token in ["lag", "shift", "delay", "ts_delay"]):
        information_set_legality = "explicit_lag_or_delay_documented"
    else:
        information_set_legality = "requires_researcher_confirmation_no_forward_leakage"

    boundary_sensitive = sorted({
        op
        for op in operators
        if op in {"rank", "ts_rank", "bucket", "quantile", "winsorize", "truncate", "argmax", "argmin"}
    })
    spec_stability = {
        "boundary_sensitive_operators": boundary_sensitive,
        "neutralization_declared": bool(canonical.get("neutralization")),
        "normalization_declared": bool(canonical.get("normalization")),
        "requires_regime_split": True,
        "requires_parameter_ablation": bool(boundary_sensitive),
        "status": "needs_review" if boundary_sensitive else "provisionally_stable",
    }

    metrics = _collect_backend_metrics(evaluation)
    rank_ic = _safe_float(metrics.get("rank_ic_mean"))
    rank_ic_ir = _safe_float(metrics.get("rank_ic_ir"))
    successful_backend_count = sum(1 for item in evaluation.get("backend_summary") or [] if item.get("status") == "success")
    long_side_review = build_long_side_review(evaluation)

    if rank_ic is not None and rank_ic > 0 and long_side_review.get("status") == "failed":
        signal_vs_portfolio_gap = "positive_signal_but_long_side_failed"
    elif rank_ic is not None and rank_ic > 0 and long_side_review.get("status") == "official_ready":
        signal_vs_portfolio_gap = "signal_and_risk_adjusted_long_side_align"
    elif rank_ic is not None and rank_ic > 0 and long_side_review.get("status") in {"supportive", "mixed"}:
        signal_vs_portfolio_gap = "signal_and_long_side_evidence_available_but_risk_adjustment_needs_review"
    elif rank_ic is not None and rank_ic <= 0:
        signal_vs_portfolio_gap = "signal_evidence_not_supportive"
    elif successful_backend_count == 0:
        signal_vs_portfolio_gap = "no_successful_backend_for_long_side_review"
    else:
        signal_vs_portfolio_gap = "not_enough_long_side_evidence"

    overfit_risk: List[str] = [
        "Single-run evidence must not be promoted without window, universe, and regime stability checks.",
    ]
    if rank_ic_ir is not None and 0 < rank_ic_ir < 0.3:
        overfit_risk.append("Weak positive IC IR can be sample noise; require out-of-sample or split-window confirmation.")
    if boundary_sensitive:
        overfit_risk.append("Boundary-sensitive transforms can improve one sample while degrading generalization.")
    if frm.get("run_status") != "success":
        overfit_risk.append("Partial or non-success run status increases implementation-selection risk.")

    return {
        "information_set_legality": information_set_legality,
        "spec_stability": spec_stability,
        "signal_vs_portfolio_gap": signal_vs_portfolio_gap,
        "long_side_objective": long_side_review,
        "monotonicity_objective": "Higher factor values should map to stronger expected long-side returns; decile spreads are diagnostics only.",
        "revision_scope_constraint": LONG_ONLY_ADOPTION_CONSTRAINTS["revision_scope"],
        "overfit_risk": overfit_risk,
    }


def derive_lessons(bundle: Dict[str, Any], evaluation: Dict[str, Any]) -> List[str]:
    frm = bundle["objects"].get("factor_run_master") or {}
    lessons: List[str] = []

    quality_gate = evaluation.get("step4_quality_gate") or {}
    for issue in quality_gate.get("issues") or []:
        if issue.get("severity") == "BLOCK":
            lessons.append(f"Step4 evidence rejected by Step5 quality gate: {issue.get('code')} - {issue.get('message')}")

    for warning in frm.get("key_warnings") or []:
        lessons.append(str(warning))

    for backend in evaluation.get("backend_summary") or []:
        metrics = backend.get("key_metrics") or {}
        rank_ic_ir = metrics.get("rank_ic_ir")
        if isinstance(rank_ic_ir, (int, float)) and rank_ic_ir < 0:
            lessons.append(
                f"Backend {backend.get('backend')} reported negative rank_ic_ir={rank_ic_ir}; signal direction or construction may need review."
            )

    if not lessons:
        lessons.append("Step 5 closed the case using only verified upstream artifacts.")

    deduped: List[str] = []
    seen = set()
    for item in lessons:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def derive_known_limits(bundle: Dict[str, Any], evaluation: Dict[str, Any]) -> List[str]:
    limits: List[str] = []
    quality_gate = evaluation.get("step4_quality_gate") or {}
    if quality_gate.get("verdict") == "BLOCK":
        limits.append("Step4 evidence is blocked by Step5 quality gate and must not be interpreted as alpha evidence.")
    for warning in evaluation.get("warnings") or []:
        limits.append(str(warning))
    if not evaluation.get("backend_summary"):
        limits.append("No evaluation backend payload was available at Step 5 aggregation time.")
    return list(dict.fromkeys(limits))


def derive_next_actions(bundle: Dict[str, Any], evaluation: Dict[str, Any], final_status: str) -> List[str]:
    next_actions = list(PLACEHOLDER_NEXT_ACTIONS.get(final_status, []))
    quality_gate = evaluation.get("step4_quality_gate") or {}
    if quality_gate.get("verdict") == "BLOCK":
        next_actions.insert(0, quality_gate.get("next_action") or "Fix Step4 and rerun before Step6.")
        for hypothesis in quality_gate.get("bug_hypotheses") or []:
            next_actions.append(f"Investigate suspected Step4 bug: {hypothesis}")
    backend_summary = evaluation.get("backend_summary") or []
    if final_status == "partial" and not backend_summary:
        next_actions.insert(0, "Add at least one successful evaluation backend before claiming validated.")
    return list(dict.fromkeys(next_actions))


def build_factor_case_master(
    bundle: Dict[str, Any],
    evaluation: Dict[str, Any],
    archive_paths: List[str],
    final_status: str,
    evaluation_path: str,
) -> Dict[str, Any]:
    frm = bundle["objects"].get("factor_run_master") or {}
    fsm = bundle["objects"].get("factor_spec_master") or {}
    dpm = bundle["objects"].get("data_prep_master") or {}

    case = {
        "report_id": bundle["report_id"],
        "factor_id": frm.get("factor_id"),
        "final_status": final_status,
        "case_stage": "step5_closed",
        "evaluation_summary": build_evaluation_summary(frm, evaluation),
        "factor_profile": {
            "factor_name": fsm.get("factor_name") or fsm.get("name"),
            "factor_family": fsm.get("factor_family") or fsm.get("family"),
            "thesis_summary": fsm.get("thesis_summary") or fsm.get("summary"),
        },
        "data_profile": {
            "sample_window": dpm.get("sample_window") or frm.get("sample_window_actual") or {},
            "universe": dpm.get("universe"),
            "data_sources": dpm.get("data_sources") or dpm.get("sources") or [],
        },
        "evidence": {
            "run_master_path": bundle["paths"].get("factor_run_master"),
            "evaluation_path": evaluation_path,
            "archive_paths": archive_paths,
        },
        "math_discipline_review": build_step5_math_discipline_review(bundle, evaluation),
        "adoption_constraints": LONG_ONLY_ADOPTION_CONSTRAINTS,
        "long_side_review": build_long_side_review(evaluation),
        "step4_quality_gate": evaluation.get("step4_quality_gate") or {},
        "lessons": derive_lessons(bundle, evaluation),
        "next_actions": derive_next_actions(bundle, evaluation, final_status),
        "known_limits": derive_known_limits(bundle, evaluation),
        "created_by_step": "step5",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return case
