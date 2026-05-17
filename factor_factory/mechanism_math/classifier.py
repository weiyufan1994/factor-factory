from __future__ import annotations

import re
from typing import Any

from .schema import CONTRACT_VERSION


PRICE_INPUT_FIELDS = {"open", "high", "low", "close", "price", "return", "returns", "pct_chg", "vwap"}
VOLUME_INPUT_FIELDS = {"volume", "vol", "amount", "turnover", "money", "traded_value"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _text_blob(spec_like: dict[str, Any]) -> str:
    canonical = spec_like.get("canonical_spec") if isinstance(spec_like.get("canonical_spec"), dict) else spec_like
    parts = [
        canonical.get("formula_text"),
        canonical.get("raw_formula_text"),
        canonical.get("factor_description"),
        spec_like.get("factor_id"),
        spec_like.get("source_type"),
        (spec_like.get("thesis") or {}).get("economic_mechanism") if isinstance(spec_like.get("thesis"), dict) else None,
        (spec_like.get("research_contract") or {}).get("economic_mechanism") if isinstance(spec_like.get("research_contract"), dict) else None,
    ]
    parts.extend(_as_list(canonical.get("required_inputs") or canonical.get("required_fields")))
    parts.extend(_as_list(canonical.get("operators") or canonical.get("operator_set")))
    parts.extend(_as_list(canonical.get("preprocessing")))
    parts.extend(_as_list(canonical.get("normalization")))
    parts.extend(_as_list(canonical.get("neutralization")))
    return " ".join(str(item) for item in parts if item).lower()


def _formula_operator_blob(spec_like: dict[str, Any]) -> str:
    canonical = spec_like.get("canonical_spec") if isinstance(spec_like.get("canonical_spec"), dict) else spec_like
    parts = [
        canonical.get("formula_text"),
        canonical.get("raw_formula_text"),
    ]
    parts.extend(_as_list(canonical.get("operators") or canonical.get("operator_set")))
    for item in _as_list(canonical.get("neutralization")):
        text = str(item).lower()
        if any(neg in text for neg in ["no neutralization", "not implied", "none", "unless"]):
            continue
        parts.append(item)
    return " ".join(str(item) for item in parts if item).lower()


def _observable_inputs(spec_like: dict[str, Any]) -> list[str]:
    canonical = spec_like.get("canonical_spec") if isinstance(spec_like.get("canonical_spec"), dict) else spec_like
    fields = (
        canonical.get("required_inputs")
        or canonical.get("required_fields")
        or canonical.get("observable_inputs")
        or []
    )
    out = []
    for item in _as_list(fields):
        text = str(item).strip()
        if text:
            out.append(text)
    return list(dict.fromkeys(out))


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _contains_field_token(text: str, tokens: set[str]) -> bool:
    for token in tokens:
        if re.search(rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])", text):
            return True
    return False


def _contains_token(text: str, tokens: list[str]) -> bool:
    for token in tokens:
        if re.search(rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])", text):
            return True
    return False


def _has_price_volume_dependence(text: str, has_price: bool, has_volume: bool) -> bool:
    dependence_patterns = [
        "correlation",
        "corr",
        "covariance",
        " cov(",
        "cov(",
        "rolling_cov",
        "rolling_corr",
        "rank-dependence",
        "rank dependence",
        "co-movement",
        "comovement",
    ]
    return has_price and has_volume and _contains_any(text, dependence_patterns)


def _has_true_projection_terms(text: str) -> bool:
    projection_patterns = [
        "neutralize",
        "neutralization",
        "residualize",
        "residualization",
        "projection",
        "pca",
        "eigen",
        "orthogonal",
        "beta neutral",
        "factor neutral",
    ]
    return _contains_any(text, projection_patterns)


def infer_model_family(spec_like: dict[str, Any]) -> tuple[str, list[str], str]:
    text = _text_blob(spec_like)
    formula_operator_text = _formula_operator_blob(spec_like)
    inputs = {item.lower() for item in _observable_inputs(spec_like)}
    has_price = bool(inputs & PRICE_INPUT_FIELDS) or _contains_field_token(text, PRICE_INPUT_FIELDS)
    has_volume = bool(inputs & VOLUME_INPUT_FIELDS) or _contains_field_token(text, VOLUME_INPUT_FIELDS)
    evidence: list[str] = []

    if _has_true_projection_terms(formula_operator_text):
        evidence.append("projection_or_residualization_terms")
        if _has_price_volume_dependence(text, has_price, has_volume):
            evidence.append("price_volume_dependence_inside_projection")
        return "linear_factor_projection", evidence, "low"
    if _has_price_volume_dependence(text, has_price, has_volume):
        evidence.append("price_volume_dependence_terms")
        return "price_volume_microstructure", evidence, "low"
    if has_price and has_volume and _contains_any(text, ["rank", "delta", "shock", "liquidity", "pressure"]):
        evidence.append("price_volume_pressure_terms")
        return "price_volume_microstructure", evidence, "medium"
    if _contains_token(text, ["pb", "p/b", "book", "roe", "roa", "ep", "earnings", "profit", "cashflow", "equity", "assets"]) or "residual income" in text:
        evidence.append("valuation_or_accounting_terms")
        return "valuation_identity", evidence, "low"
    if _contains_any(text, ["momentum", "reversal", "delta", "return", "trend", "volatility", "stddev", "variance", "moving average", "ma(", "delay"]):
        evidence.append("price_process_or_time_series_terms")
        return "stochastic_process", evidence, "medium"
    if _contains_any(text, ["decay", "smooth", "smoothing", "ema", "rolling", "window", "kernel", "sum(", "mean("]):
        evidence.append("filter_or_kernel_terms")
        return "functional_filter", evidence, "medium"
    if _contains_any(text, ["rank", "zscore", "z-score", "quantile", "standardize", "winsor"]):
        evidence.append("cross_sectional_statistic_terms")
        return "cross_sectional_statistics", evidence, "medium"
    if _contains_any(text, ["index inclusion", "mandate", "constraint", "rebalance pressure", "fund flow", "transfer board", "event"]):
        evidence.append("institutional_constraint_terms")
        return "constraint_model", evidence, "medium"
    return "other", ["no_specific_math_family_rule_matched"], "high"


def _family_template(model_family: str) -> dict[str, Any]:
    templates = {
        "valuation_identity": {
            "toolkits": ["accounting_or_valuation_identity", "real_analysis", "statistics"],
            "mechanism": "Valuation and profitability observables estimate a mispricing or persistence state implied by accounting and residual-income identities.",
            "state": "valuation-implied profitability persistence or mispricing state",
            "estimator": "the factor estimates the distance between observable profitability/valuation inputs and the target valuation identity",
            "target": "E[r_{t+1:t+h} | F_t, valuation_state_t]",
            "process": "Firm value follows a valuation identity linking cash-flow/profitability state and market price; returns arise when price adjusts toward the identity-implied value.",
            "latent": "latent intrinsic-value gap or profitability persistence state",
            "observable_estimator": "accounting and valuation ratios estimate the sign and magnitude of the latent valuation gap",
            "conditional_distribution": "r_{i,t+1:t+h} | F_t, valuation_gap_{i,t}",
            "relationship_shape": "monotone after sign convention if the valuation gap is correctly measured and not a distress proxy",
            "metric_match": "top-score long side should be positive after costs; monotonic groups should not rely on short-side distress only",
            "mechanism_tests": [
                "Check whether top-score return survives excluding distress or balance-sheet-quality traps.",
                "Check whether return is stronger when accounting persistence assumptions are satisfied.",
            ],
            "revision_target": "state_variable",
        },
        "stochastic_process": {
            "toolkits": ["probability_theory", "stochastic_process_calculus", "time_series_and_filtering", "statistics"],
            "mechanism": "Price-history transforms estimate a latent drift, reversal, volatility, or persistence state in the return process.",
            "state": "latent return-process state",
            "estimator": "the factor is an estimator of drift, reversal, volatility, or persistence under the current information set",
            "target": "E[r_{t+1:t+h} | F_t, process_state_t]",
            "process": "Returns follow a stochastic process with latent drift, reversal, volatility, or jump components that can be estimated from the observed price path.",
            "latent": "latent drift, reversal, volatility, or jump-risk state",
            "observable_estimator": "rolling price-path transforms estimate the latent process state without using future information",
            "conditional_distribution": "r_{i,t+1:t+h} | F_t, process_state_{i,t}",
            "relationship_shape": "monotone or threshold-like depending on whether the estimator targets continuation, reversal, or volatility compensation",
            "metric_match": "rank IC, group monotonicity, long-side return, and turnover horizon should match the declared process horizon",
            "mechanism_tests": [
                "Check whether signal half-life and turnover match the stated process horizon.",
                "Check whether extreme-score behavior is consistent with continuation versus reversal rather than portfolio-side diagnostics.",
            ],
            "revision_target": "estimator_kernel",
        },
        "price_volume_microstructure": {
            "toolkits": ["probability_theory", "statistics", "microstructure_model", "time_series_and_filtering"],
            "mechanism": "Price-volume dependence estimates whether price pressure is confirmed by liquidity, attention, or noisy trading pressure.",
            "state": "latent price-volume pressure or liquidity-shock state",
            "estimator": "rank and rolling dependence transforms estimate price-volume co-movement as an observable microstructure state",
            "target": "E[r_{t+1:t+h} | F_t, pressure_state_t]",
            "process": "P_{i,t}=F_{i,t}+I_{i,t}+epsilon_{i,t}, where transient impact I may decay as I_{i,t+1}=rho I_{i,t}+eta_{i,t+1}. Price-volume rank dependence estimates the current impact or crowded-attention state.",
            "latent": "latent transient impact, crowded-attention, liquidity-demand, or informed-flow state",
            "observable_estimator": "rolling rank covariance/correlation/dependence between price-level or return ranks and volume/liquidity ranks",
            "conditional_distribution": "r_{i,t+1:t+h} | F_t, C_{i,t}, where C is the price-volume dependence estimator",
            "relationship_shape": "unknown until evidence separates high-covariance bad-state detection from low-covariance long-only selection",
            "metric_match": "promotion requires high-score long-side strength; G9 > G10, short-side dominance, or cost-destroyed spread contradict a clean monotone long-only story",
            "mechanism_tests": [
                "Test whether high price-volume dependence predicts subsequent impact decay or reversal.",
                "Test whether low-dependence names truly outperform, rather than the factor only identifying high-dependence bad states.",
                "Compare G9 versus G10 and long-side metrics before using long-short spread as support.",
            ],
            "revision_target": "estimator_kernel",
        },
        "cross_sectional_statistics": {
            "toolkits": ["probability_theory", "statistics", "real_analysis"],
            "mechanism": "Cross-sectional transforms estimate relative standing in the declared economic state.",
            "state": "cross-sectional relative state",
            "estimator": "rank, z-score, or robust transforms estimate an order statistic or standardized state",
            "target": "E[r_{i,t+1:t+h} | F_t, cross_sectional_state_{i,t}]",
            "process": "Cross-sectional observations are treated as samples from a distribution whose relative ranks or standardized deviations proxy a latent economic state.",
            "latent": "latent relative economic state in the cross section",
            "observable_estimator": "rank, z-score, quantile, or robust scaling estimator",
            "conditional_distribution": "r_{i,t+1:t+h} | F_t, relative_state_{i,t}",
            "relationship_shape": "monotone, U-shaped, or threshold-like depending on the declared economic state",
            "metric_match": "group returns and IC must match the declared cross-sectional ordering, not only the long-short diagnostic",
            "mechanism_tests": [
                "Check whether the score ordering is stable across regimes and universes.",
                "Check whether the top group earns positive return without depending on bottom-group losses.",
            ],
            "revision_target": "projection_operator",
        },
        "linear_factor_projection": {
            "toolkits": ["linear_algebra", "statistics", "probability_theory"],
            "mechanism": "Projection or residualization isolates a target signal from declared nuisance exposures.",
            "state": "orthogonalized residual signal state",
            "estimator": "the factor applies projection or residualization to estimate signal orthogonal to nuisance exposures",
            "target": "E[r_{t+1:t+h} | F_t, residual_signal_t]",
            "process": "Observed returns or features are decomposed into nuisance exposure components plus a residual target state using an explicit projection operator.",
            "latent": "latent residual signal state after removing declared nuisance exposures",
            "observable_estimator": "projection, neutralization, residualization, PCA, or beta-adjusted estimator",
            "conditional_distribution": "r_{i,t+1:t+h} | F_t, residual_signal_{i,t}",
            "relationship_shape": "monotone only if the residualized signal retains the intended mechanism after projection",
            "metric_match": "post-projection long-side return and IC must improve without hidden portfolio or universe repairs",
            "mechanism_tests": [
                "Check whether the residual signal remains predictive after exposure removal.",
                "Check whether performance disappears when nuisance exposures are controlled explicitly.",
            ],
            "revision_target": "projection_operator",
        },
        "functional_filter": {
            "toolkits": ["functional_analysis", "time_series_and_filtering", "statistics"],
            "mechanism": "A kernel/filter transform estimates a smoothed functional of the underlying state.",
            "state": "filtered latent signal state",
            "estimator": "the factor is a kernel or rolling-window estimator of a latent signal",
            "target": "E[r_{t+1:t+h} | F_t, filtered_state_t]",
            "process": "The observed series contains signal plus noise; a functional kernel estimates the latent state at the relevant horizon.",
            "latent": "filtered latent signal state",
            "observable_estimator": "rolling window, decay kernel, smoothing, or functional transform",
            "conditional_distribution": "r_{i,t+1:t+h} | F_t, filtered_state_{i,t}",
            "relationship_shape": "depends on kernel horizon and whether smoothing preserves or lags the economic state",
            "metric_match": "turnover, signal half-life, and cost-adjusted return should improve consistently with the smoothing claim",
            "mechanism_tests": [
                "Check whether smoothing reduces turnover without destroying gross signal.",
                "Check whether the estimator horizon matches the measured return horizon.",
            ],
            "revision_target": "estimator_kernel",
        },
        "constraint_model": {
            "toolkits": ["optimization_and_control", "constraint_model", "probability_theory"],
            "mechanism": "Objective constraints or mandates create repeated behavior that can be estimated from observable states.",
            "state": "constraint-induced demand or supply pressure state",
            "estimator": "the factor estimates the state induced by rules, mandates, capacity, or event constraints",
            "target": "E[r_{t+1:t+h} | F_t, constraint_state_t]",
            "process": "Constrained agents respond to rules, mandates, or capacity limits, creating predictable demand or supply pressure states.",
            "latent": "constraint-induced demand, supply, or flow-pressure state",
            "observable_estimator": "event, membership, capacity, flow, or rule-state estimator",
            "conditional_distribution": "r_{i,t+1:t+h} | F_t, constraint_state_{i,t}",
            "relationship_shape": "event-window or threshold-like unless evidence supports a persistent monotone relation",
            "metric_match": "return timing should align with the constraint event and not depend on unrelated portfolio repairs",
            "mechanism_tests": [
                "Check whether returns cluster around the predicted constraint window.",
                "Check whether the effect disappears outside the constrained universe or event state.",
            ],
            "revision_target": "state_variable",
        },
    }
    return templates.get(model_family, {})


def build_mechanism_math_contract(spec_like: dict[str, Any]) -> dict[str, Any]:
    canonical = spec_like.get("canonical_spec") if isinstance(spec_like.get("canonical_spec"), dict) else spec_like
    model_family, evidence, uncertainty = infer_model_family(spec_like)
    inputs = _observable_inputs(spec_like)
    formula = str(canonical.get("formula_text") or canonical.get("raw_formula_text") or "").strip()
    if model_family == "other":
        return {
            "contract_version": CONTRACT_VERSION,
            "math_model_status": "under_specified",
            "model_family": "other",
            "math_toolkits": ["statistics"],
            "economic_mechanism": "under_specified",
            "state_or_object": "under_specified",
            "observable_inputs": inputs,
            "factor_as_estimator": "under_specified",
            "target_functional": "under_specified",
            "process_hypothesis": "under_specified",
            "latent_state": "under_specified",
            "observable_estimator": "under_specified",
            "conditional_distribution_hypothesis": "under_specified",
            "relationship_shape": "under_specified",
            "monotonicity_claim": "under_specified",
            "information_set": {
                "filtration": "F_t",
                "uses_future_information": False,
                "lag_or_delay_required": False,
                "notes": "Information set cannot be fully formalized until the mechanism is specified.",
            },
            "necessary_conditions": ["human researcher must specify the economic state before promotion"],
            "expected_metric_signature": {"status": "under_specified"},
            "metric_signature_match": "under_specified",
            "revision_operators": [],
            "falsification_tests": ["Reject promotion if no testable state, estimator, or target functional can be stated."],
            "mechanism_falsification_tests": ["Reject promotion if no testable process, estimator, or conditional distribution can be stated."],
            "kill_criteria": ["Kill or redesign if the factor remains a data transform without a testable mechanism."],
            "under_specified_reason": "No general mechanism math family matched the current formula, inputs, operators, or thesis.",
            "next_human_research_question": "What economic state does this factor estimate, and why should that state predict long-side return?",
            "classification_evidence": {"matched_rules": evidence, "classification_uncertainty": uncertainty, "formula_text": formula},
        }

    template = _family_template(model_family)
    return {
        "contract_version": CONTRACT_VERSION,
        "math_model_status": "specified",
        "model_family": model_family,
        "math_toolkits": template["toolkits"],
        "economic_mechanism": template["mechanism"],
        "state_or_object": template["state"],
        "observable_inputs": inputs,
        "factor_as_estimator": template["estimator"],
        "target_functional": template["target"],
        "process_hypothesis": template["process"],
        "latent_state": template["latent"],
        "observable_estimator": template["observable_estimator"],
        "conditional_distribution_hypothesis": template["conditional_distribution"],
        "relationship_shape": template["relationship_shape"],
        "monotonicity_claim": "Higher factor values should map to higher long-side expected risk-adjusted return after the declared sign convention.",
        "information_set": {
            "filtration": "F_t",
            "uses_future_information": bool(re.search(r"future|next_return|shift\s*\(\s*-", formula.lower())),
            "lag_or_delay_required": "announcement" in formula.lower() or "lag" in formula.lower(),
            "notes": "The contract describes the intended estimator information set; Step3/4 evidence and leakage scans remain authoritative.",
        },
        "necessary_conditions": [
            "the estimated state must be persistent enough to survive turnover and explicit costs",
            "the high-score long side must earn positive risk-adjusted return",
            "the signal must not be adopted from short-side or long-short diagnostics alone",
        ],
        "expected_metric_signature": {
            "rank_ic": "positive after sign convention",
            "long_side_annual_return": "positive",
            "cost_adjusted_annual_return": "positive for promotion",
            "turnover": "consistent with estimator horizon",
            "monotonicity": "top group should outperform lower groups without short-side dependence",
        },
        "metric_signature_match": template["metric_match"],
        "revision_operators": [
            {
                "operator_name": "increase_estimator_smoothing",
                "revision_target_math_object": template["revision_target"],
                "math_change": "increase smoothing bandwidth, rolling window, or persistence confirmation inside the factor expression",
                "expected_effects": [
                    "lower estimator variance",
                    "lower turnover",
                    "more lag",
                    "possible gross signal decay if the state is too short-lived",
                ],
                "forbidden_interpretation": "not a portfolio rebalance repair",
            },
            {
                "operator_name": "challenge_model_family",
                "revision_target_math_object": "model_family_challenge",
                "math_change": "test whether the declared state is the wrong economic object and should be replaced by a better estimator",
                "expected_effects": [
                    "clearer monotonicity if the state is correct",
                    "rejection if evidence only survives through diagnostics",
                ],
                "forbidden_interpretation": "not a short-leg or decile-trading adoption path",
            },
        ],
        "falsification_tests": [
            "If high-score long-side return is non-positive after costs, the estimator does not support promotion.",
            "If improvements come only from bottom-decile losses or long-short diagnostics, reject adoption.",
        ],
        "mechanism_falsification_tests": template["mechanism_tests"],
        "kill_criteria": [
            "Kill if the factor cannot state a testable state, estimator, and target functional.",
            "Kill if the high-score long side remains non-positive after expression-level revisions.",
        ],
        "classification_evidence": {"matched_rules": evidence, "classification_uncertainty": uncertainty, "formula_text": formula},
    }
