from __future__ import annotations

import re
from typing import Any

from .schema import CONTRACT_VERSION, CONTRACT_VERSION_V2
from .equation_quality import score_research_equation
from .formula_specific import build_formula_understanding, select_math_model_from_economic_hypothesis


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


def _formula_supports_price_volume_model(formula_understanding: dict[str, Any]) -> bool:
    if not isinstance(formula_understanding, dict):
        return False
    if formula_understanding.get("interaction_structure") == "price_volume_dependence":
        return True
    features = formula_understanding.get("formula_features") if isinstance(formula_understanding.get("formula_features"), dict) else {}
    return features.get("has_volume") is True


def normalize_selected_model_family(model_family: str, formula_understanding: dict[str, Any]) -> str:
    raw = str(model_family or "").strip()
    if raw in {
        "stochastic_process",
        "valuation_identity",
        "linear_factor_projection",
        "functional_filter",
        "cross_sectional_statistics",
        "constraint_model",
    }:
        return raw
    if raw == "price_volume_microstructure":
        if _formula_supports_price_volume_model(formula_understanding):
            return "price_volume_microstructure"
        return "other"
    if raw in {"ranked_price_state_process", "canonical_formula_state_process"}:
        return "stochastic_process"
    if raw == "ranked_price_volume_state_process":
        if _formula_supports_price_volume_model(formula_understanding):
            return "price_volume_microstructure"
        return "stochastic_process"
    return "other"


def infer_model_family(spec_like: dict[str, Any]) -> tuple[str, list[str], str]:
    research_contract = spec_like.get("research_contract") if isinstance(spec_like.get("research_contract"), dict) else {}
    formula_understanding = (
        research_contract.get("formula_understanding")
        or spec_like.get("formula_understanding")
        or build_formula_understanding(spec_like)
    )
    text = _text_blob(spec_like)
    formula_operator_text = _formula_operator_blob(spec_like)
    formula_features = (formula_understanding or {}).get("formula_features") if isinstance(formula_understanding, dict) else {}
    formula_fields = {str(item).lower() for item in (formula_features or {}).get("fields", [])} if isinstance(formula_features, dict) else set()
    if not formula_fields:
        formula_fields = {item.lower() for item in _observable_inputs(spec_like)}
    has_price = bool(formula_fields & PRICE_INPUT_FIELDS)
    has_volume = bool(formula_fields & VOLUME_INPUT_FIELDS)
    if _has_true_projection_terms(formula_operator_text):
        evidence = ["projection_or_residualization_terms"]
        if _has_price_volume_dependence(text, has_price, has_volume):
            evidence.append("price_volume_dependence_inside_projection")
        return "linear_factor_projection", evidence, "low"
    selected = select_math_model_from_economic_hypothesis(
        research_contract.get("economic_hypothesis") if isinstance(research_contract, dict) else {},
        research_contract.get("math_hypothesis_candidates") if isinstance(research_contract, dict) else [],
        formula_understanding if isinstance(formula_understanding, dict) else {},
    )
    normalized = normalize_selected_model_family(
        str(selected.get("model_family") or selected.get("selected_baseline_model") or ""),
        formula_understanding if isinstance(formula_understanding, dict) else {},
    )
    if normalized != "other":
        interaction = (formula_understanding or {}).get("interaction_structure") if isinstance(formula_understanding, dict) else None
        evidence = [f"step1_economic_to_math_modelling:{normalized}"]
        if interaction:
            evidence.append(f"formula_understanding:{interaction}")
        return normalized, evidence, "low"
    evidence: list[str] = []
    text_mentions_volume = _contains_field_token(text, VOLUME_INPUT_FIELDS)
    if text_mentions_volume and not has_volume:
        evidence.append("text_mentions_volume_but_formula_field_absent")

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
    research_contract = spec_like.get("research_contract") if isinstance(spec_like.get("research_contract"), dict) else {}
    formula_understanding = (
        research_contract.get("formula_understanding")
        or spec_like.get("formula_understanding")
        or build_formula_understanding(spec_like)
    )
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

    template = dict(_family_template(model_family))
    if model_family == "stochastic_process" and isinstance(formula_understanding, dict) and formula_understanding.get("interaction_structure") == "slow_state_x_short_horizon_threshold":
        template.update({
            "mechanism": "Formula estimates a slow winner or long-window trend state interacting with short-horizon reversal/dislocation and sign-threshold migration.",
            "state": "slow winner state interacting with short-horizon reversal/dislocation threshold state",
            "estimator": "the formula estimates a cross-sectional conditional state formed by long-window return rank and short-horizon sign-threshold price movement",
            "target": "E[r_i,t+1 | F_t, slow_state_i,t, short_state_i,t, threshold_i,t]",
            "process": (
                "Returns follow a stochastic process with slow trend state M_i,t and short-horizon reversal/dislocation "
                "component I_i,t; sign transform creates threshold migration around the state boundary."
            ),
            "latent": "latent slow winner/trend state multiplied by short-horizon pullback or temporary dislocation state",
            "observable_estimator": "sum(returns,250), close-delay(close,7), delta(close,7), sign threshold, and cross-sectional rank",
            "conditional_distribution": "r_i,t+1 | F_t, slow_state_i,t, short_state_i,t, threshold_i,t",
            "relationship_shape": "threshold-like conditional payoff; long-window winner rank changes payoff sign and magnitude only through interaction with short-horizon state",
            "metric_match": "rank IC, long-side return, turnover, and component ablations must support slow-state x short-state interaction after costs",
            "mechanism_tests": [
                "Ablate the long-window return state and verify the signal weakens if slow winner state is required.",
                "Ablate or flip the short-horizon sign threshold and verify payoff direction is consistent with reversal/dislocation thesis.",
                "Check turnover around threshold migration does not consume expected payoff.",
            ],
            "revision_target": "threshold_boundary",
        })
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
        "formula_understanding": formula_understanding,
        "economic_to_math_model_selection": select_math_model_from_economic_hypothesis(
            research_contract.get("economic_hypothesis") if isinstance(research_contract, dict) else {},
            research_contract.get("math_hypothesis_candidates") if isinstance(research_contract, dict) else [],
            formula_understanding if isinstance(formula_understanding, dict) else {},
        ),
        "classification_evidence": {"matched_rules": evidence, "classification_uncertainty": uncertainty, "formula_text": formula},
    }


def _return_source_family(research_contract: dict[str, Any]) -> str:
    economic = research_contract.get("economic_hypothesis") if isinstance(research_contract.get("economic_hypothesis"), dict) else {}
    value = str(economic.get("macro_return_source") or research_contract.get("initial_return_source_hypothesis") or "mixed")
    if value == "market_structure_arbitrage":
        return "market_structure_arbitrage"
    if value in {"risk_premium", "information_advantage", "constraint_driven_arbitrage", "mixed"}:
        return value
    return "mixed"


def _payer_from_research_contract(research_contract: dict[str, Any]) -> tuple[str, str]:
    economic = research_contract.get("economic_hypothesis") if isinstance(research_contract.get("economic_hypothesis"), dict) else {}
    second = economic.get("second_layer") if isinstance(economic.get("second_layer"), dict) else {}
    payer = str(
        second.get("expected_counterparty_or_payer")
        or economic.get("counterparty_loss_hypothesis")
        or "counterparty group implied by the report-specific economic hypothesis"
    )
    why = str(
        second.get("why_they_may_pay")
        or "they pay only if the report-specific behavior, constraint, or information lag creates a conditional return distribution shift"
    )
    return payer, why


def _primary_v2_family(v1_family: str) -> str:
    mapping = {
        "price_volume_microstructure": "microstructure_response_function",
        "constraint_model": "behavioral_constraint_model",
        "linear_factor_projection": "stochastic_process",
        "cross_sectional_statistics": "stochastic_process",
        "functional_filter": "stochastic_process",
        "valuation_identity": "stochastic_process",
        "stochastic_process": "stochastic_process",
    }
    return mapping.get(v1_family, v1_family or "stochastic_process")


def _projection_terms_for_family(v1_family: str) -> list[str]:
    if v1_family == "price_volume_microstructure":
        return ["friction", "drift"]
    if v1_family == "constraint_model":
        return ["regime_transition", "drift"]
    if v1_family == "valuation_identity":
        return ["drift", "observation_equation"]
    if v1_family == "linear_factor_projection":
        return ["observation_equation", "drift"]
    return ["drift", "observation_equation"]


def _t0_t1_terms_for_family(v1_family: str) -> list[str]:
    if v1_family in {"constraint_model"}:
        return ["drift", "friction", "regime_transition"]
    if v1_family in {"price_volume_microstructure"}:
        return ["friction", "observation_equation", "jump"]
    if v1_family in {"valuation_identity"}:
        return ["drift"]
    if v1_family in {"stochastic_process"}:
        return ["drift", "diffusion"]
    return ["drift", "friction"]


def _as_meaningful_text_list(value: Any, fallback: list[str]) -> list[str]:
    items = _as_list(value)
    out = [str(item).strip() for item in items if str(item).strip()]
    return out or fallback


def _research_equation(v1: dict[str, Any], research_contract: dict[str, Any], formula_estimator: str) -> dict[str, Any]:
    family = str(v1.get("model_family") or "")
    if family == "valuation_identity":
        status = "strict_identity"
        symmetry = "cash-flow or valuation identity"
    elif family == "price_volume_microstructure":
        status = "empirical_invariance"
        symmetry = "market-impact or liquidity response relation"
    elif family == "constraint_model":
        status = "institutional_constraint"
        symmetry = "participant or institutional constraint"
    else:
        status = "research_conjecture" if family == "other" else "empirical_invariance"
        symmetry = "report-specific conditional return relation"

    assumptions = _as_meaningful_text_list(
        research_contract.get("assumptions"),
        ["The estimated latent state changes the conditional distribution of next-horizon returns."],
    )
    metric_signature = _as_meaningful_text_list(
        v1.get("expected_metric_signature"),
        ["rank IC and long-side return should match the declared sign"],
    )
    equation = {
        "equation_text": str(
            v1.get("process_hypothesis")
            or "observable_factor_t = estimator(latent_state_t, F_t) + measurement_noise_t"
        ),
        "equation_status": status,
        "assumptions": assumptions,
        "validity_scope": {
            "market": str(research_contract.get("market") or "report_scope"),
            "frequency": str(research_contract.get("frequency") or "report_horizon"),
            "regime": str(research_contract.get("regime") or "under_research_review"),
            "participant_structure": str(research_contract.get("participant_structure") or "report_specific_counterparty_structure"),
        },
        "symmetry_or_constraint": symmetry,
        "symmetry_breaking_mechanism": str(v1.get("economic_mechanism") or "report-specific mechanism"),
        "latent_state": str(v1.get("latent_state") or v1.get("state_or_object") or "latent return-process state"),
        "observable_estimator": formula_estimator,
        "expected_metric_signature": metric_signature,
        "falsification_tests": _as_meaningful_text_list(
            v1.get("falsification_tests"),
            ["Falsify if metrics do not support the estimated latent state."],
        ),
        "kill_criteria": _as_meaningful_text_list(
            v1.get("kill_criteria"),
            ["Kill if no formula-mappable latent state remains."],
        ),
        "evidence_tier": (
            "logical_identity"
            if status == "strict_identity"
            else "institutional_rule"
            if status == "institutional_constraint"
            else "report_specific_hypothesis"
            if status == "research_conjecture"
            else "single_market_empirical_regular"
        ),
        "audit_basis": _as_meaningful_text_list(
            research_contract.get("audit_basis"),
            ["Report text, formula structure, and Step4 metric signature must support this equation."],
        ),
        "participant_constraint_loop": {
            "payer": str(research_contract.get("payer") or "report-specific constrained counterparty"),
            "constraint": str(research_contract.get("constraint") or "cannot immediately eliminate the market relation"),
            "repeat_mechanism": str(research_contract.get("repeat_mechanism") or "similar constraints regenerate across rebalance horizons"),
            "failure_condition": str(research_contract.get("failure_condition") or "participant structure, liquidity regime, or metric signature changes"),
        },
        "demotion_triggers": _as_meaningful_text_list(
            research_contract.get("demotion_triggers"),
            ["participant_structure_change", "metric_signature_mismatch", "cross_sample_failure"],
        ),
    }
    equation["quality_score"] = score_research_equation(equation).quality_score
    return equation


def _t0_t1_stochastic_benchmark(v1: dict[str, Any], formula_estimator: str, conditional: str) -> dict[str, Any]:
    family = str(v1.get("model_family") or "")
    return {
        "benchmark_required": True,
        "horizon": "T+0/T+1 or report_horizon",
        "affected_terms": _t0_t1_terms_for_family(family),
        "conditional_distribution_claim": conditional,
        "benchmark_implication": (
            "The estimated state must shift next-horizon return distribution enough to survive "
            "turnover, volatility drag, drawdown capital cost, and implementation frictions."
        ),
        "when_primary_model_cannot_infer": "Use this stochastic projection as a benchmark diagnostic, not as the primary model.",
        "falsification_tests": [
            f"Falsify if {formula_estimator} does not change T+0/T+1 or report-horizon conditional return distribution after implementation and turnover controls."
        ],
    }


def _alternative_return_source_tests(primary_source: str, payer: str) -> list[dict[str, str]]:
    candidates = [
        "risk_premium",
        "information_advantage",
        "market_structure_arbitrage",
        "constraint_driven_arbitrage",
    ]
    alternatives = [item for item in candidates if item != primary_source]
    if primary_source == "mixed":
        alternatives = candidates
    out: list[dict[str, str]] = []
    for alt in alternatives[:2]:
        if alt == "risk_premium":
            out.append(
                {
                    "alternative_source": alt,
                    "why_not_primary": "Risk premium is not primary unless the signal earns compensation for bearing a persistent systematic risk exposure rather than exploiting mispricing or delayed adjustment.",
                    "discriminating_test": "Control for volatility, beta, size, turnover, and downside-risk exposures; a risk-premium story should retain compensation through higher realized risk rather than reversal or payer losses.",
                    "expected_signature_if_alternative_true": "High-score portfolios should show higher compensated risk exposure and not merely subsequent price correction from the named counterparty.",
                }
            )
        elif alt == "information_advantage":
            out.append(
                {
                    "alternative_source": alt,
                    "why_not_primary": "Information advantage is secondary unless the signal timing is tied to slow information diffusion or informed-flow proxies.",
                    "discriminating_test": "Test whether the effect strengthens around disclosure, attention, or informed-flow regimes and decays as information is incorporated.",
                    "expected_signature_if_alternative_true": f"Losses should concentrate among slower processors rather than the declared payer group: {payer}.",
                }
            )
        elif alt == "market_structure_arbitrage":
            out.append(
                {
                    "alternative_source": alt,
                    "why_not_primary": "Market-structure arbitrage is secondary unless institutional rules, liquidity frictions, or execution constraints mechanically create the return.",
                    "discriminating_test": "Condition on liquidity, limits, trading constraints, and rebalance/event windows; the effect should concentrate where the structural friction binds.",
                    "expected_signature_if_alternative_true": "Returns should cluster around friction or event states rather than broadly follow the formula-implied process state.",
                }
            )
        elif alt == "constraint_driven_arbitrage":
            out.append(
                {
                    "alternative_source": alt,
                    "why_not_primary": "Constraint-driven arbitrage is secondary unless forced demand/supply, mandates, or capacity constraints explain the payer behavior.",
                    "discriminating_test": "Split by constrained ownership, rebalance pressure, capacity, and forced-flow proxies.",
                    "expected_signature_if_alternative_true": "Signal strength should be state/event dependent and weaken outside the constrained participant set.",
                }
            )
    return out


def _formula_implied_information(
    inputs: list[str],
    formula: str,
    v1: dict[str, Any],
    formula_estimator: str,
    conditional: str,
) -> dict[str, Any]:
    structural_constraints = []
    if formula:
        structural_constraints.append(f"Formula expression constrains the estimator to the observable transformation: {formula}")
    if inputs:
        structural_constraints.append(f"Observable inputs constrain the latent state estimate to information in: {', '.join(inputs)}")
    structural_constraints.append("The inferred state must explain a conditional return-distribution change rather than restate a raw field.")
    latent_state = str(v1.get("latent_state") or v1.get("state_or_object") or "latent return-process state")
    return {
        "structural_constraints": structural_constraints,
        "latent_state_inferred_by_formula": latent_state,
        "estimator_interpretation": formula_estimator,
        "why_not_raw_field_restatement": "The formula is treated as an observable estimator of the declared latent/model state; raw fields are only measurements, not the mechanism state itself.",
        "price_process_connection": conditional,
    }


def _formula_implied_information_review() -> dict[str, Any]:
    return {
        "reviewer_task": "formula_implied_information_reviewer",
        "review_status": "no_unexpected_implication_detected",
        "benchmark_tools": [
            "primary_model_projection",
            "stochastic_price_process_projection",
            "information_set_check",
            "dimensional_or_scale_check",
        ],
        "negative_solution_policy": "do_not_discard_until_classified",
        "unexpected_implications": [],
        "classification_schema": [
            "bug",
            "data_artifact",
            "implementation_artifact",
            "benign_model_implication",
            "tradable_anomaly",
            "new_factor_seed",
        ],
    }


def _component_mapping_from_inputs(inputs: list[str], contract: dict[str, Any]) -> list[dict[str, Any]]:
    role = "state_variable"
    projection_role = "drift"
    family = contract.get("model_family")
    if family == "price_volume_microstructure":
        role = "conditioning_variable"
        projection_role = "friction"
    elif family == "linear_factor_projection":
        role = "conditioning_variable"
        projection_role = "observation"
    mapping = []
    for item in inputs or ["formula_expression"]:
        mapping.append(
            {
                "formula_component": str(item),
                "observable_proxy_for": str(contract.get("state_or_object") or contract.get("latent_state") or "latent return-process state"),
                "model_role": role,
                "price_process_projection_role": projection_role,
            }
        )
    return mapping


def build_mechanism_math_contract_v2(spec_like: dict[str, Any]) -> dict[str, Any]:
    """Build the v2 positive mechanism model contract from the current v1 classifier.

    This is intentionally conservative: v1 remains the compatibility contract,
    while v2 adds the explicit market-process -> primary model -> stochastic
    projection -> estimator chain.
    """
    canonical = spec_like.get("canonical_spec") if isinstance(spec_like.get("canonical_spec"), dict) else spec_like
    research_contract = spec_like.get("research_contract") if isinstance(spec_like.get("research_contract"), dict) else {}
    v1 = build_mechanism_math_contract(spec_like)
    inputs = _observable_inputs(spec_like)
    formula = str(canonical.get("formula_text") or canonical.get("raw_formula_text") or "").strip()
    payer, why_pay = _payer_from_research_contract(research_contract)
    family = str(v1.get("model_family") or "stochastic_process")
    projection_terms = _projection_terms_for_family(family)
    formula_estimator = str(v1.get("observable_estimator") or v1.get("factor_as_estimator") or "formula observable estimator")
    conditional = str(v1.get("conditional_distribution_hypothesis") or "r_{t+1} | F_t, estimated_state_t")
    return_source = _return_source_family(research_contract)
    return {
        "contract_version": CONTRACT_VERSION_V2,
        "market_process_thesis": {
            "market_phenomenon": str(v1.get("economic_mechanism") or research_contract.get("economic_mechanism") or "report-specific market behavior"),
            "economic_hypothesis": str(research_contract.get("economic_mechanism") or v1.get("economic_mechanism") or "report-specific economic hypothesis"),
            "return_source_family": return_source,
            "payer_or_counterparty": payer,
            "why_they_pay": why_pay,
            "alternative_return_source_tests": _alternative_return_source_tests(return_source, payer),
            "what_must_be_true": research_contract.get("what_must_be_true") or [
                "The formula must estimate a state that changes the conditional distribution of next-horizon return."
            ],
            "what_would_break_it": research_contract.get("what_would_break_it") or [
                "The thesis breaks if observed metrics contradict the declared state, projection, or estimator mapping."
            ],
        },
        "primary_mechanism_model": {
            "selected_model_family": _primary_v2_family(family),
            "selected_model_reason": str(v1.get("classification_evidence", {}).get("matched_rules") or v1.get("economic_mechanism") or "selected from formula and economic hypothesis"),
            "why_alternatives_are_less_suitable": [
                "Alternative models remain secondary unless they explain the same payer, state variable, and observed estimator mapping more directly."
            ],
            "state_variables": [str(v1.get("state_or_object") or v1.get("latent_state") or "latent return-process state")],
            "observable_proxies": inputs or [formula or "formula expression"],
            "target_functional": str(v1.get("target_functional") or "E[r_{t+1} | F_t, estimated_state_t]"),
        },
        "stochastic_price_process_projection": {
            "projection_required": True,
            "price_process_form": str(v1.get("process_hypothesis") or "conditional return process with state-dependent distribution terms"),
            "affected_price_process_terms": projection_terms,
            "conditional_distribution_claim": conditional,
            "formula_should_estimate": formula_estimator,
            "expected_return_distribution_change": str(v1.get("metric_signature_match") or "metrics should reveal whether the estimated state shifts next-horizon return distribution in the claimed direction"),
        },
        "research_equation": _research_equation(v1, research_contract, formula_estimator),
        "t0_t1_stochastic_benchmark": _t0_t1_stochastic_benchmark(v1, formula_estimator, conditional),
        "formula_implied_information": _formula_implied_information(inputs, formula, v1, formula_estimator, conditional),
        "formula_implied_information_review": _formula_implied_information_review(),
        "formula_component_mapping": _component_mapping_from_inputs(inputs, v1),
        "expected_metric_signature": v1.get("expected_metric_signature") or {
            "rank_ic": "positive after sign convention",
            "long_side_return": "positive after costs",
            "turnover": "consistent with estimator horizon",
        },
        "falsification_tests": v1.get("mechanism_falsification_tests") or v1.get("falsification_tests") or [
            "Reject if the formula cannot be tied to a conditional distribution shift under F_t."
        ],
        "revision_operators": v1.get("revision_operators") or [],
        "kill_criteria": v1.get("kill_criteria") or [
            "Kill or redesign if the factor remains a formula transform without a falsifiable market-process model."
        ],
        "source_mechanism_math_contract_v1": v1,
    }
