from __future__ import annotations

import re
from typing import Any


DERIVATION_VERSION = "factorforge_formula_specific_derivation_v1"
CONSISTENCY_VERSION = "factorforge_mechanism_formula_consistency_v1"

BASELINE_MODEL_FAMILIES = {
    "stochastic_process",
    "valuation_identity",
    "state_space",
    "transient_impact",
    "cointegration",
    "copula_rank_dependence",
    "jump_threshold",
    "projection_residualization",
    "fourier_wavelet",
    "dimensional_scaling",
    "other",
}

MODEL_KEYWORDS = {
    "stochastic",
    "process",
    "state",
    "distribution",
    "conditional",
    "bayesian",
    "signal extraction",
    "cash flow",
    "discount",
    "valuation",
    "cointegration",
    "mean reversion",
    "transient impact",
    "order imbalance",
    "threshold",
    "stopping",
    "copula",
    "rank-dependence",
    "projection",
    "residual",
    "fourier",
    "wavelet",
    "filter",
    "scaling",
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _canonical(spec_like: dict[str, Any]) -> dict[str, Any]:
    return spec_like.get("canonical_spec") if isinstance(spec_like.get("canonical_spec"), dict) else spec_like


def _walk_formula_ir(node: Any, operators: set[str], fields: set[str], constants: list[float]) -> None:
    if not isinstance(node, dict):
        return
    typ = node.get("type")
    if typ == "operator":
        op = str(node.get("operator") or "").lower()
        if op:
            operators.add(op)
        for arg in node.get("args") or []:
            _walk_formula_ir(arg, operators, fields, constants)
    elif typ == "field":
        field = str(node.get("resolved_field") or node.get("field") or node.get("name") or "").lower()
        if field:
            fields.add(field)
    elif typ == "constant":
        try:
            constants.append(float(node.get("value")))
        except Exception:
            pass


def formula_features(spec_like: dict[str, Any], mechanism_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    canonical = _canonical(spec_like or {})
    operators = {str(item).lower() for item in _as_list(canonical.get("operators") or canonical.get("operator_set")) if str(item).strip()}
    fields: set[str] = set()
    for key in ("required_inputs", "required_fields", "observable_inputs"):
        fields.update(str(item).lower() for item in _as_list(canonical.get(key)) if str(item).strip())
    constants: list[float] = []
    formula_ir = canonical.get("formula_ir") or spec_like.get("formula_ir")
    if isinstance(formula_ir, dict):
        _walk_formula_ir(formula_ir.get("root") or formula_ir, operators, fields, constants)
    formula_text = str(canonical.get("formula_text") or canonical.get("raw_formula_text") or spec_like.get("formula_text") or "")
    text = formula_text.lower()
    for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text):
        lower = token.lower()
        if lower in {"open", "high", "low", "close", "volume", "amount", "turnover", "returns", "return", "pct_chg", "vwap"}:
            fields.add(lower)
        if lower in {"rank", "ts_rank", "sum", "mean", "std", "stddev", "delta", "delay", "sign", "where", "correlation", "corr", "covariance", "cov", "plus", "minus", "multiply", "mul", "divide", "div", "negate", "neg", "signedpower"}:
            operators.add(lower)
    for number in re.findall(r"(?<![A-Za-z_])(?:\d+)(?![A-Za-z_])", text):
        try:
            constants.append(float(number))
        except Exception:
            pass
    mechanism_contract = (mechanism_analysis or {}).get("mechanism_math_contract") if isinstance(mechanism_analysis, dict) else {}
    mechanism_observable_inputs: list[str] = []
    if isinstance(mechanism_contract, dict):
        mechanism_observable_inputs = sorted(
            {str(item).lower() for item in mechanism_contract.get("observable_inputs") or [] if str(item).strip()}
        )
    mechanism_inputs_not_in_formula = sorted(set(mechanism_observable_inputs) - fields)
    return {
        "formula_text": formula_text,
        "fields": sorted(fields),
        "mechanism_observable_inputs": mechanism_observable_inputs,
        "mechanism_inputs_not_in_formula": mechanism_inputs_not_in_formula,
        "formula_missing_mechanism_inputs": mechanism_inputs_not_in_formula,
        "operators": sorted(operators),
        "constants": constants,
        "has_volume": bool(fields & {"volume", "vol", "amount", "turnover"}),
        "has_high_low": bool(fields & {"high", "low"}),
        "has_sign_or_threshold": bool(operators & {"sign", "where"}) or "sign(" in text or "where(" in text,
        "has_long_window": any(value >= 120 for value in constants),
        "has_250_window": any(value >= 240 for value in constants) or "250" in text,
        "has_short_delay_or_delta": (bool(operators & {"delta", "delay"}) and any(1 <= value <= 20 for value in constants)) or bool(re.search(r"(delta|delay)\s*\([^)]*,\s*(?:7|5|10)", text)),
        "has_raw_additive": bool(operators & {"plus", "minus"}) or "+" in formula_text or "-" in formula_text,
        "has_open_close_position": bool(fields & {"open"}) and bool(fields & {"close"}) and (
            bool(operators & {"divide", "div", "minus", "negate", "signedpower"})
            or "open" in text and "close" in text and "/" in formula_text
        ),
    }


def build_formula_understanding(spec_like: dict[str, Any]) -> dict[str, Any]:
    features = formula_features(spec_like or {})
    operators = set(features.get("operators") or [])
    fields = set(features.get("fields") or [])
    components: list[dict[str, Any]] = []

    if features.get("has_250_window"):
        components.append({
            "component": "long_window_return_sum",
            "formula_feature": "sum(returns, 250) or equivalent long rolling return window",
            "economic_state": "slow winner / long-window trend state",
            "modelling_role": "persistent state M_i,t that conditions whether short-horizon moves are continuation or pullback opportunities",
        })
    elif features.get("has_long_window"):
        components.append({
            "component": "long_window_state",
            "formula_feature": "long rolling window",
            "economic_state": "slow-moving state",
            "modelling_role": "persistent component in the conditional return process",
        })
    if features.get("has_short_delay_or_delta"):
        components.append({
            "component": "short_horizon_price_change",
            "formula_feature": "close-delay(close,k), delta(close,k), or equivalent short horizon difference",
            "economic_state": "short-horizon pullback / reversal / temporary dislocation state",
            "modelling_role": "temporary shock or short-state I_i,t interacting with slow state",
        })
    if features.get("has_sign_or_threshold"):
        components.append({
            "component": "sign_threshold_boundary",
            "formula_feature": "sign/where threshold transform",
            "economic_state": "threshold migration / discontinuous state boundary",
            "modelling_role": "stopping-time or boundary-crossing mutation of the baseline process",
        })
    if features.get("has_open_close_position"):
        components.append({
            "component": "open_close_position_state",
            "formula_feature": "open/close relative position or equivalent intraday price-location transform",
            "economic_state": "overnight-to-intraday pressure, opening gap digestion, or close-location reversal state",
            "modelling_role": "short-horizon price-location state in the conditional return process",
        })
    if "rank" in operators:
        components.append({
            "component": "cross_sectional_rank_state",
            "formula_feature": "rank transform",
            "economic_state": "relative cross-sectional state / conditional rank position",
            "modelling_role": "maps raw state estimates into rank-state U_i,t for cross-sectional payoff testing",
        })
    if operators & {"multiply", "mul"} or "multiply(" in str(features.get("formula_text") or "").lower() or "*" in str(features.get("formula_text") or ""):
        components.append({
            "component": "state_interaction",
            "formula_feature": "multiplication / interaction",
            "economic_state": "interaction between state variables",
            "modelling_role": "tests conditional payoff from slow state times short-horizon state rather than either component alone",
        })
    if not components:
        components.append({
            "component": "primary_formula_state",
            "formula_feature": features.get("formula_text") or "formula_ir",
            "economic_state": "formula-defined latent state",
            "modelling_role": "requires researcher-specific state interpretation",
        })

    if features.get("has_250_window") and features.get("has_short_delay_or_delta") and features.get("has_sign_or_threshold"):
        interaction = "slow_state_x_short_horizon_threshold"
        latent = [
            "slow winner / long-window trend state",
            "short-horizon pullback / reversal / temporary dislocation state",
            "threshold migration around sign boundary",
            "cross-sectional rank-state if rank is present",
        ]
    elif features.get("has_open_close_position"):
        interaction = "open_close_intraday_position"
        latent = [
            "overnight-to-intraday pressure state",
            "opening gap digestion or close-location reversal state",
            "cross-sectional rank-state if rank is present",
        ]
    elif bool(fields & {"volume", "amount", "turnover"}) and any(op in operators for op in ["correlation", "corr", "covariance", "cov"]):
        interaction = "price_volume_dependence"
        latent = ["price-volume pressure / liquidity-flow state", "attention or transient-impact state"]
    elif any(field in fields for field in ["earnings", "profit", "revenue", "cashflow", "book", "roe", "roa"]):
        interaction = "valuation_ratio_state"
        latent = ["cash-flow / earnings / discount-rate valuation state"]
    elif any(op in operators for op in ["neutralize", "residualize", "regression"]):
        interaction = "projection_residual_state"
        latent = ["residualized signal state after nuisance exposure removal"]
    else:
        interaction = "formula_defined_state"
        latent = [item["economic_state"] for item in components if item.get("economic_state")]

    return {
        "formula_understanding_version": "factorforge_formula_understanding_v1",
        "formula_features": features,
        "component_interpretations": components,
        "interaction_structure": interaction,
        "latent_state_candidates": list(dict.fromkeys(latent)),
    }


def select_math_model_from_economic_hypothesis(
    economic_hypothesis: dict[str, Any] | None,
    math_hypothesis_candidates: list[dict[str, Any]] | None,
    formula_understanding: dict[str, Any] | None,
) -> dict[str, Any]:
    understanding = formula_understanding or {}
    interaction = understanding.get("interaction_structure")
    candidates = math_hypothesis_candidates or []
    credible_families = {str(item.get("model_family")) for item in candidates if isinstance(item, dict) and item.get("model_family")}
    if interaction == "slow_state_x_short_horizon_threshold":
        family = "stochastic_process"
        why = "Formula understanding identifies slow winner / long-window state interacting with short-horizon reversal/dislocation and sign-threshold boundary."
    elif candidates and next((item.get("model_family") for item in candidates if isinstance(item, dict) and item.get("model_family")), None):
        family = str(next(item.get("model_family") for item in candidates if isinstance(item, dict) and item.get("model_family")))
        why = "Selected from Step1 math_hypothesis_candidates because it is explicit and formula-specific."
    elif interaction == "price_volume_dependence":
        family = "price_volume_microstructure"
        why = "Formula understanding identifies explicit price-volume dependence."
    elif interaction == "valuation_ratio_state":
        family = "valuation_identity"
        why = "Formula understanding identifies valuation/accounting state."
    elif interaction == "projection_residual_state":
        family = "linear_factor_projection"
        why = "Formula understanding identifies projection/residualization state."
    elif "stochastic_process" in credible_families:
        family = "stochastic_process"
        why = "Step1 hypothesis selected stochastic_process and no stronger formula contradiction was found."
    else:
        family = "other"
        why = "No credible formula-specific math family selected; human review required."
    return {
        "selected_baseline_model": family,
        "model_family": family,
        "why_selected": why,
        "formula_interaction_structure": interaction,
        "source_candidate_families": sorted(credible_families),
    }


def build_formula_specific_headline(
    economic_hypothesis: dict[str, Any] | None,
    math_selection: dict[str, Any] | str | None,
    formula_understanding: dict[str, Any] | None,
) -> str:
    economic_hypothesis = economic_hypothesis if isinstance(economic_hypothesis, dict) else {}
    math_selection_obj = math_selection if isinstance(math_selection, dict) else {"model_family": str(math_selection or "")}
    formula_understanding = formula_understanding if isinstance(formula_understanding, dict) else {}
    second = economic_hypothesis.get("second_layer") if isinstance(economic_hypothesis.get("second_layer"), dict) else {}
    subtype = str(second.get("subtype") or "").strip()
    payer = str(second.get("expected_counterparty_or_payer") or "").strip()
    why_pay = str(second.get("why_they_may_pay") or "").strip()
    interaction = str(formula_understanding.get("interaction_structure") or "").strip()
    model_family = str(math_selection_obj.get("model_family") or math_selection_obj.get("selected_baseline_model") or "").strip()

    if interaction == "slow_state_x_short_horizon_threshold":
        return (
            "Formula estimates a slow winner state interacting with short-horizon pullback and sign-threshold migration; "
            f"expected payoff comes from {payer or 'trend extrapolators or delayed updaters'} because "
            f"{why_pay or 'they react late to conditional state migration'}; selected math model is "
            f"{model_family or 'stochastic_process'}."
        )
    if subtype and why_pay:
        return (
            f"Formula-specific thesis: {subtype}; payer: {payer or 'under-specified counterparty'}; "
            f"why they may pay: {why_pay}; selected math model: {model_family or 'under review'}."
        )
    return "Formula-specific thesis remains under-specified and must be resolved by Step1/Step2 mechanism modelling before promotion."


def _text_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            parts.append(_text_blob(*value.values()))
        elif isinstance(value, list):
            parts.append(_text_blob(*value))
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).lower()


def _generic_payer_actor_label(value: Any) -> str | None:
    """Return a generic actor label only when the actor field is itself generic."""
    words = re.findall(r"[a-z0-9]+", str(value or "").lower())
    connectors = {"a", "an", "and", "or", "the"}
    words = [word for word in words if word not in connectors]
    normalized = " ".join(words)
    generic_words = {
        "counterparties",
        "counterparty",
        "generic",
        "investors",
        "market",
        "participants",
        "payer",
        "traders",
    }
    if words and all(word in generic_words for word in words):
        return normalized
    return None


def _has_explicit_stochastic_model(process: str) -> bool:
    """Recognize compact model equations even when prose omits MODEL_KEYWORDS."""
    normalized = process.translate(
        str.maketrans({"β": "beta", "ε": "epsilon", "η": "eta", "λ": "lambda", "σ": "sigma"})
    )
    return_equation = re.search(
        r"(?:^|[;,.]\s*)(?:r(?:_[a-z0-9_{}]+)?|return(?:_[a-z0-9_{}]+)?|dp(?:_[a-z0-9]+)?/p(?:_[a-z0-9]+)?)\s*=\s*([^;]+)",
        normalized,
    )
    if return_equation is None:
        return False
    right_hand_side = return_equation.group(1)
    has_coefficient = any(
        marker in right_hand_side
        for marker in {"alpha", "beta", "lambda", "mu", "phi", "rho", "theta"}
    )
    has_residual = any(
        marker in right_hand_side
        for marker in {"epsilon", "innovation", "residual", "shock", "+u", "+ u"}
    )
    has_conditional_error_law = bool(
        re.search(
            r"(?:epsilon|innovation|residual|shock|u)\s*\|\s*f[a-z0-9_{}]*\s*~\s*"
            r"(?:n(?:ormal)?|gaussian)?\s*\(\s*0(?:\.0+)?\s*,[^)]*"
            r"(?:sigma(?:\s*(?:\^\s*2|²))|variance|var\(\s*[^)\s][^)]*\))",
            normalized,
        )
    )
    return has_coefficient and has_residual and has_conditional_error_law


def _has_stochastic_process_prose(process: str) -> bool:
    words = re.findall(r"[a-z0-9]+", process)
    if len(words) < 8:
        return False
    stochastic_objects = {
        "conditional",
        "distribution",
        "innovation",
        "process",
        "residual",
        "shock",
        "state",
        "stochastic",
    }
    dynamics = {
        "bayesian",
        "decay",
        "drift",
        "jump",
        "regime",
        "reversal",
        "reverse",
        "transition",
        "volatility",
    }
    return bool(stochastic_objects.intersection(words)) and bool(
        dynamics.intersection(words)
    )


def _economic_text(spec_like: dict[str, Any], mechanism_analysis: dict[str, Any]) -> str:
    spec_like = spec_like or {}
    canonical = _canonical(spec_like)
    return _text_blob(
        spec_like.get("economic_hypothesis"),
        spec_like.get("thesis"),
        spec_like.get("research_contract"),
        canonical.get("economic_hypothesis"),
        canonical.get("economic_mechanism"),
        mechanism_analysis.get("mechanism_hypothesis"),
        mechanism_analysis.get("return_source"),
        mechanism_analysis.get("factor_family"),
    )


def _select_baseline_model(economic_text: str, features: dict[str, Any]) -> str:
    text = economic_text.lower()
    if any(token in text for token in ["earnings", "growth", "cash flow", "fcf", "dcf", "peg", "valuation", "profit", "book"]):
        return "valuation_identity"
    if any(token in text for token in ["information", "underreaction", "delayed", "diffusion", "attention", "signal extraction"]):
        return "state_space"
    if any(token in text for token in ["liquidity", "impact", "order imbalance", "rebalance", "inventory", "constraint", "market-structure", "market structure"]):
        return "transient_impact"
    if any(op in features.get("operators", []) for op in ["correlation", "corr", "covariance", "cov"]) or "rank" in features.get("operators", []):
        return "copula_rank_dependence"
    if features.get("has_sign_or_threshold"):
        return "jump_threshold"
    if features.get("has_long_window") or features.get("has_short_delay_or_delta"):
        return "stochastic_process"
    return "other"


def _economic_hypothesis_summary(spec_like: dict[str, Any], mechanism_analysis: dict[str, Any], economic: str) -> str:
    return (
        f"return_source={mechanism_analysis.get('return_source') or 'unknown'}; "
        f"factor_family={mechanism_analysis.get('factor_family') or 'unknown'}; "
        f"hypothesis={economic[:240] or 'under-specified'}"
    )


def _component_summary(components: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{item.get('component')} estimates {item.get('state_interpretation')}"
        for item in components
        if item.get("component")
    )


def _profit_payer_for_baseline(
    baseline: str,
    components: list[dict[str, Any]],
    economic: str,
    mechanism_analysis: dict[str, Any],
) -> dict[str, Any]:
    hypothesis_source = _economic_hypothesis_summary({}, mechanism_analysis, economic)
    formula_state_link = _component_summary(components) or "primary formula transform estimates the declared latent state"
    if baseline == "valuation_identity":
        return {
            "payer_or_counterparty": "valuation-error counterparties absorbing earnings-growth or discount-rate repricing",
            "why_they_pay": "they hold or sell against stale cash-flow, growth, or discount-rate beliefs until valuation error is revised by fundamentals",
            "mechanism_generating_profit": "a valuation identity maps price to expected cash flows and discount rates; profit transfer appears when the formula estimates the sign or magnitude of valuation-error correction before it is fully priced",
            "expected_payoff_expression_or_argument": "P_t = E_t[FCF_{t+1:}]/(r_t-g_t); expected return is positive when the formula state predicts upward cash-flow revision, lower discount-rate shock, or closing of a negative valuation gap.",
            "economic_hypothesis_source": hypothesis_source,
            "math_model_link": "valuation_identity models payer behavior as delayed correction of cash-flow, growth, or discount-rate beliefs",
            "formula_state_link": formula_state_link,
        }
    if baseline == "state_space":
        return {
            "payer_or_counterparty": "information-disadvantaged delayed updaters with attention constraints",
            "why_they_pay": "they revise beliefs slowly after public signals, so the signal extractor earns from delayed Bayesian updating before the latent information state is fully reflected",
            "mechanism_generating_profit": "latent state x_t evolves with noisy observations y_t; the formula estimates E[x_t|F_t], and payoff comes from subsequent belief updates that move prices toward that state",
            "expected_payoff_expression_or_argument": "x_{t+1}=A x_t+epsilon_t, y_t=H x_t+eta_t; E[r_{t+1}|F_t] is monotone in the formula's filtered latent-information state minus the market-implied state.",
            "economic_hypothesis_source": hypothesis_source,
            "math_model_link": "state_space links payer behavior to delayed signal extraction and forecast-error correction",
            "formula_state_link": formula_state_link,
        }
    if baseline == "transient_impact":
        return {
            "payer_or_counterparty": "liquidity demanders or inventory-constrained flow absorbers",
            "why_they_pay": "urgent flow pays temporary impact or liquidity concession that mean-reverts as inventory pressure and order imbalance decay",
            "mechanism_generating_profit": "order-imbalance state I_t creates temporary impact; formula components estimate the signed pressure or its relaxation horizon",
            "expected_payoff_expression_or_argument": "I_{t+1}=rho I_t+eta_t with |rho|<1; expected reversal or continuation payoff follows the sign of impact decay lambda*(I_t-I_{t+1}) after costs.",
            "economic_hypothesis_source": hypothesis_source,
            "math_model_link": "transient_impact models payer behavior as costly immediacy demand and inventory-risk transfer",
            "formula_state_link": formula_state_link,
        }
    if baseline == "copula_rank_dependence":
        return {
            "payer_or_counterparty": "crowding and rank-dependence mispricers at conditional distribution extremes",
            "why_they_pay": "their correlated positioning or rank-based extrapolation leaves predictable conditional dependence that unwinds when the latent rank state normalizes",
            "mechanism_generating_profit": "a copula state C(u,v) captures nonlinear dependence between formula-ranked observables and future returns; profit exists only if conditional rank dependence changes expected payoff monotonically",
            "expected_payoff_expression_or_argument": "For rank state U_t=F(signal_t), E[r_{t+1}|U_t in tail, Z_t] differs from unconditional E[r] through conditional copula dependence, with sign verified by long-side metrics.",
            "economic_hypothesis_source": hypothesis_source,
            "math_model_link": "copula_rank_dependence models payer behavior as conditional rank-state mispricing, not rank mechanically by itself",
            "formula_state_link": formula_state_link,
        }
    if baseline == "jump_threshold":
        return {
            "payer_or_counterparty": "threshold-boundary migrators facing discontinuous state changes and turnover costs",
            "why_they_pay": "they react around discrete state boundaries after the signal crosses a threshold, paying through delayed boundary migration, slippage, or forced repositioning",
            "mechanism_generating_profit": "a stopping-time boundary tau defines when observed state crosses a discontinuity; formula sign/threshold components estimate crossing direction and instability risk",
            "expected_payoff_expression_or_argument": "tau = inf{t: S_t crosses b}; payoff requires E[r_{t+1}|tau=t, direction] to dominate turnover and bucket-migration costs.",
            "economic_hypothesis_source": hypothesis_source,
            "math_model_link": "jump_threshold models payer behavior as discontinuous boundary adjustment with explicit migration costs",
            "formula_state_link": formula_state_link,
        }
    if baseline == "stochastic_process":
        return {
            "payer_or_counterparty": "trend or reversal-state counterparties exposed to drift, jump, or temporary dislocation regimes",
            "why_they_pay": "they underprice persistence or overreact to short-horizon shocks, creating conditional drift/reversal payoff when the formula identifies the current regime",
            "mechanism_generating_profit": "the price process combines drift, reversal, jump, or volatility states; formula components estimate the regime and expected sign of next-horizon return",
            "expected_payoff_expression_or_argument": "dP_t/P_t = mu(S_t)dt + sigma(S_t)dW_t + J_t dN_t; expected payoff is E[r_{t+1}|estimated S_t] with sign/horizon specified by formula components.",
            "economic_hypothesis_source": hypothesis_source,
            "math_model_link": "stochastic_process models payer behavior as compensation for regime-specific drift or correction after temporary dislocation",
            "formula_state_link": formula_state_link,
        }
    return {
        "payer_or_counterparty": "under-specified economic counterparty requiring human review",
        "why_they_pay": "the current artifact does not identify a concrete constraint, belief error, or risk transfer source strongly enough for formal acceptance",
        "mechanism_generating_profit": "no complete baseline model is declared; a researcher must provide a specific state equation, valuation relation, dependence structure, or impact process before this can authorize a revision",
        "expected_payoff_expression_or_argument": "BLOCK until a model-specific expected-payoff argument links formula state, payer constraint, and observable metric signature.",
        "economic_hypothesis_source": hypothesis_source,
        "math_model_link": "other is under-specified and should remain advisory or blocked until sharpened",
        "formula_state_link": formula_state_link,
        "needs_human_review": True,
    }


def build_formula_specific_derivation(
    spec_like: dict[str, Any],
    mechanism_analysis: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = formula_features(spec_like, mechanism_analysis)
    understanding = build_formula_understanding(spec_like)
    interaction_structure = str(understanding.get("interaction_structure") or "")
    economic = _economic_text(spec_like, mechanism_analysis)
    if interaction_structure == "slow_state_x_short_horizon_threshold":
        economic = (
            "Formula-specific hypothesis: a slow winner or long-window trend state interacts with a "
            "short-horizon reversal, pullback, temporary dislocation, or sign-threshold boundary. "
            "Delayed updaters, trend extrapolators, or liquidity-demand accounts may pay when the "
            "short-state boundary misprices the next-horizon payoff conditional on the slow state."
        )
        baseline = "stochastic_process"
    elif interaction_structure == "open_close_intraday_position":
        economic = (
            "Formula-specific hypothesis: an open/close relative-position transform estimates overnight-to-intraday "
            "pressure, opening-gap digestion, or close-location reversal. Overnight extrapolators, opening auction "
            "liquidity demanders, or close-location chasers may pay when the next-horizon return corrects that "
            "short-horizon price-location state."
        )
        baseline = "stochastic_process"
    else:
        baseline = _select_baseline_model(economic, features)
    components: list[dict[str, Any]] = []
    if features["has_250_window"]:
        components.append({
            "component": "long_window_return_sum",
            "formula_feature": "sum(returns, long window)",
            "state_interpretation": "slow winner or trend state over a long information horizon",
            "mechanism_requirement": "explain why a persistent winner state remains compensated rather than fully arbitraged",
        })
    if features["has_short_delay_or_delta"]:
        components.append({
            "component": "short_horizon_price_change",
            "formula_feature": "delta/delay over short horizon",
            "state_interpretation": "short-horizon reversal, pullback, or temporary dislocation state",
            "mechanism_requirement": "explain why recent move reverses or interacts with the slow state",
        })
    if features["has_sign_or_threshold"]:
        components.append({
            "component": "sign_or_threshold_transform",
            "formula_feature": "sign/where threshold transform",
            "state_interpretation": "discontinuous state boundary",
            "mechanism_requirement": "discuss discontinuity, threshold instability, turnover, and bucket migration",
        })
    if features.get("has_open_close_position"):
        components.append({
            "component": "open_close_position_state",
            "formula_feature": "open/close relative position or equivalent intraday price-location transform",
            "state_interpretation": "overnight-to-intraday pressure, opening gap digestion, or close-location reversal state",
            "mechanism_requirement": "explain why open-to-close location predicts next-horizon drift or reversal rather than only contemporaneous noise",
        })
    if not components:
        components.append({
            "component": "primary_formula_transform",
            "formula_feature": features.get("formula_text") or "formula_ir",
            "state_interpretation": "observable estimator for the declared latent state",
            "mechanism_requirement": "connect this transform to the payer behavior and expected return horizon",
        })

    metric_feedback = "Observed metrics must be compared with the expected signature; contradiction should trigger model challenge, formula mutation, or kill criteria."
    if metrics:
        metric_feedback = (
            "Metric evidence is mixed or incomplete unless long-side, cost-adjusted, monotonicity, and horizon evidence all match; "
            "contradiction feeds back into baseline model choice, estimator definition, sign/horizon, or kill criteria."
        )

    payer_derivation = _profit_payer_for_baseline(baseline, components, economic, mechanism_analysis)
    return {
        "version": DERIVATION_VERSION,
        "economic_to_math_model_selection": {
            "baseline_model_family": baseline,
            "why_selected_from_economic_hypothesis": (
                "Selected from the economic hypothesis and formula structure, not from a fixed factor-family template: "
                f"{economic[:400] or 'economic hypothesis under-specified'}"
            ),
            "why_not_generic_template": "The model must explain payer behavior, state dynamics, estimator mapping, and metric signature for this specific formula.",
            "model_mutations_for_this_formula": [
                item["mechanism_requirement"] for item in components
            ],
        },
        "profit_payer_derivation": payer_derivation,
        "formula_components": components,
        "latent_state_mapping": [
            {
                "observable_component": item["component"],
                "latent_state_claim": item["state_interpretation"],
                "estimator_mapping": item["mechanism_requirement"],
            }
            for item in components
        ],
        "selected_model_family": baseline,
        "why_this_model_not_generic_template": "It is tied to economic payer behavior, formula components, horizon, sign convention, and metric falsification.",
        "random_object": "panel of observable factor inputs and next-period returns under the legal information set F_t",
        "latent_state": "formula-specific latent state implied by the economic hypothesis",
        "process_or_distribution": _process_for_baseline(baseline, features),
        "target_functional": "E[r_{t+1:t+h} | F_t, estimated_state_t]",
        "formula_as_estimator": "the formula maps observable inputs into the declared latent state; each transform must have a payer/horizon interpretation",
        "expected_metric_signature": "rank IC, long-side return, cost-adjusted return, monotonicity, and turnover must match the declared sign and horizon",
        "observed_metric_comparison": metric_feedback,
        "metric_feedback_to_model": "Unsupported metrics must revise the baseline model, mutate the estimator/sign/horizon, or activate kill criteria.",
        "falsification_tests": [
            "Block promotion if long-side cost-adjusted evidence contradicts the expected payoff direction.",
            "Block or mutate if formula component behavior does not match the declared latent state horizon.",
        ],
        "kill_criteria": [
            "Kill if no identifiable payer or constraint remains after evidence review.",
            "Kill if metrics only support short-leg or diagnostic long-short behavior under a long-only mandate.",
        ],
        "revision_implication": "Use model/formula mutation only after evidence contradicts a specific derivation step; do not repair through portfolio construction.",
    }


def _process_for_baseline(baseline: str, features: dict[str, Any]) -> str:
    if baseline == "valuation_identity":
        return "cash-flow, earnings-growth, or residual-income valuation process with discount-rate or revision shocks"
    if baseline == "state_space":
        return "latent information state with delayed Bayesian updating or signal extraction under F_t"
    if baseline == "transient_impact":
        return "transient price impact or order-imbalance state process with constrained liquidity demand"
    if baseline == "copula_rank_dependence":
        return "rank-dependence or copula model linking monotone transforms to an economic latent state"
    if baseline == "jump_threshold":
        return "threshold or stopping-time state transition process with discontinuity and turnover implications"
    if baseline == "stochastic_process":
        if features.get("has_open_close_position"):
            return "stochastic intraday-to-next-horizon return process with an opening-gap or close-location state that may drift, reverse, or decay after the observed session"
        if features.get("has_250_window") and features.get("has_short_delay_or_delta"):
            return "price return process combining a slow winner/trend state with a short-horizon reversal or dislocation state"
        return "stochastic return process with drift, reversal, volatility, or jump components estimated from legal history"
    return "explicit conditional distribution must be supplied by the researcher; formula restatement is insufficient"


def validate_formula_specific_derivation(derivation: Any, spec_like: dict[str, Any], mechanism_analysis: dict[str, Any] | None = None) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if not isinstance(derivation, dict) or not derivation:
        return [{"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "formula_specific_derivation missing"}]
    if derivation.get("version") != DERIVATION_VERSION:
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "formula_specific_derivation version invalid"})
    selection = derivation.get("economic_to_math_model_selection") if isinstance(derivation.get("economic_to_math_model_selection"), dict) else {}
    baseline = selection.get("baseline_model_family") or derivation.get("selected_model_family")
    if baseline not in BASELINE_MODEL_FAMILIES:
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": f"baseline_model_family invalid: {baseline}"})
    for path, value in [
        ("economic_to_math_model_selection.why_selected_from_economic_hypothesis", selection.get("why_selected_from_economic_hypothesis")),
        ("economic_to_math_model_selection.why_not_generic_template", selection.get("why_not_generic_template")),
        ("profit_payer_derivation.payer_or_counterparty", (derivation.get("profit_payer_derivation") or {}).get("payer_or_counterparty") if isinstance(derivation.get("profit_payer_derivation"), dict) else None),
        ("profit_payer_derivation.why_they_pay", (derivation.get("profit_payer_derivation") or {}).get("why_they_pay") if isinstance(derivation.get("profit_payer_derivation"), dict) else None),
        ("process_or_distribution", derivation.get("process_or_distribution")),
        ("formula_as_estimator", derivation.get("formula_as_estimator")),
        ("metric_feedback_to_model", derivation.get("metric_feedback_to_model")),
        ("revision_implication", derivation.get("revision_implication")),
    ]:
        if not isinstance(value, str) or not value.strip():
            failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": f"{path} missing"})
    if not isinstance(derivation.get("formula_components"), list) or not derivation.get("formula_components"):
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "formula_components missing"})
    if not isinstance(derivation.get("falsification_tests"), list) or len(derivation.get("falsification_tests") or []) < 2:
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "falsification_tests must include at least two items"})
    if not isinstance(derivation.get("kill_criteria"), list) or len(derivation.get("kill_criteria") or []) < 2:
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "kill_criteria must include at least two items"})
    payer = derivation.get("profit_payer_derivation") if isinstance(derivation.get("profit_payer_derivation"), dict) else {}
    required_payer_fields = [
        "payer_or_counterparty",
        "why_they_pay",
        "mechanism_generating_profit",
        "expected_payoff_expression_or_argument",
        "economic_hypothesis_source",
        "math_model_link",
        "formula_state_link",
    ]
    for field in required_payer_fields:
        if not isinstance(payer.get(field), str) or not payer.get(field, "").strip():
            failures.append({
                "code": "BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC",
                "message": f"profit_payer_derivation.{field} missing",
            })
    payer_blob = _text_blob(payer)
    generic_phrases = [
        "the counterparty implied by the economic hypothesis",
        "counterparty implied",
        "generic payer",
        "they pay only if",
        "constrained behavior, delayed information diffusion, risk transfer, or liquidity demand",
        "formula estimates the state",
        "estimated_state_t",
    ]
    generic_hits = [phrase for phrase in generic_phrases if phrase in payer_blob]
    generic_actor = _generic_payer_actor_label(payer.get("payer_or_counterparty"))
    if generic_actor:
        generic_hits.append(generic_actor)
    expression = str(payer.get("expected_payoff_expression_or_argument") or "").strip().lower()
    if expression in {
        "e[r_{t+1:t+h} | f_t, estimated_state_t] must be monotone in the declared direction after costs.",
        "e[r_{t+1:t+h} | f_t, estimated_state_t]",
    } or re.fullmatch(r"e\[r_\{?t\+1(?::t\+h)?\}?\s*\|\s*f_t,\s*estimated_state_t\].*", expression):
        generic_hits.append("generic expected payoff template")
    model_specific_terms = {
        "valuation_identity": ["fcf", "cash-flow", "cash flow", "discount", "growth", "valuation"],
        "state_space": ["latent", "bayesian", "signal", "update", "observation", "filtered"],
        "transient_impact": ["impact", "imbalance", "inventory", "liquidity", "rho", "decay"],
        "copula_rank_dependence": ["copula", "conditional rank", "rank state", "dependence"],
        "jump_threshold": ["threshold", "stopping", "boundary", "discontinu", "tau"],
        "stochastic_process": ["drift", "reversal", "jump", "volatility", "process", "regime"],
    }
    expected_terms = model_specific_terms.get(str(baseline))
    if expected_terms and not any(term in payer_blob for term in expected_terms):
        generic_hits.append(f"missing model-specific payer terms for {baseline}")
    if generic_hits:
        failures.append({
            "code": "BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC",
            "message": f"profit payer derivation is generic or incomplete: {sorted(set(generic_hits))}",
        })
    process = str(derivation.get("process_or_distribution") or "").lower()
    features = formula_features(spec_like or {}, mechanism_analysis or {})
    formula_tokens = {token for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", str(features.get("formula_text") or "").lower()) if len(token) > 2}
    model_hits = [token for token in MODEL_KEYWORDS if token in process]
    formula_hits = [token for token in formula_tokens if token in process]
    compact_stochastic_model = _has_explicit_stochastic_model(process)
    if baseline == "stochastic_process":
        missing_model_assumption = not (
            compact_stochastic_model or _has_stochastic_process_prose(process)
        )
    else:
        missing_model_assumption = not model_hits
    if missing_model_assumption and (formula_hits or baseline == "stochastic_process"):
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "process_or_distribution merely restates formula tokens without model assumption"})
    return failures


def validate_mechanism_formula_consistency(
    spec_like: dict[str, Any],
    mechanism_analysis: dict[str, Any],
    derivation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    takeover = {}
    if isinstance(mechanism_analysis, dict):
        raw_takeover = mechanism_analysis.get("main_agent_mechanism_memo_takeover")
        takeover = raw_takeover if isinstance(raw_takeover, dict) else {}
    use_memo_takeover_scope = takeover.get("enabled") is True
    feature_scope = {} if use_memo_takeover_scope else (mechanism_analysis or {})
    takeover_scope = {
        "enabled": True,
        "validation_scope": takeover.get("validation_scope"),
    }
    text_scope = (derivation or {}, takeover_scope) if use_memo_takeover_scope else (mechanism_analysis, derivation)
    features = formula_features(spec_like or {}, feature_scope)
    text = _text_blob(*text_scope)
    failures: list[dict[str, str]] = []
    mechanism_inputs_not_in_formula = features.get("mechanism_inputs_not_in_formula") or []
    if not features["has_volume"]:
        forbidden = [
            "price-volume",
            "price volume",
            "volume covariance",
            "volume correlation",
            "volume liquidity",
            "rolling_cov",
            "rolling_corr",
        ]
        hits = [term for term in forbidden if term in text]
        if hits:
            failures.append({
                "code": "BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION",
                "message": f"formula has no volume input but mechanism text claims volume dependence: {hits}",
            })
    if mechanism_inputs_not_in_formula:
        volume_like_inputs = sorted(set(mechanism_inputs_not_in_formula) & {"volume", "vol", "amount", "turnover"})
        if volume_like_inputs and any(term in text for term in ["price-volume", "price volume", "volume", "liquidity", "covariance", "correlation"]):
            failures.append({
                "code": "BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION",
                "message": f"mechanism observable inputs are not present in formula fields: {volume_like_inputs}",
            })
    if not features["has_high_low"]:
        forbidden = ["high-low", "high low", "intraday range", "range estimator"]
        hits = [term for term in forbidden if term in text]
        if hits:
            failures.append({
                "code": "BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION",
                "message": f"formula has no high/low input but mechanism text claims range estimator: {hits}",
            })
    if features["has_sign_or_threshold"] and not any(term in text for term in ["discontinu", "threshold", "turnover", "bucket instability", "state boundary"]):
        failures.append({
            "code": "BLOCK_MECHANISM_FORMULA_OPERATOR_OMISSION",
            "message": "formula uses sign/threshold but derivation does not discuss discontinuity, threshold, turnover, or bucket instability",
        })
    if features["has_250_window"] and not any(term in text for term in ["slow", "trend", "winner", "long horizon", "long-window", "persistent"]):
        failures.append({
            "code": "BLOCK_MECHANISM_FORMULA_OPERATOR_OMISSION",
            "message": "formula uses long return window but derivation does not discuss slow state, trend, winner state, or long horizon",
        })
    if features["has_short_delay_or_delta"] and not any(term in text for term in ["reversal", "dislocation", "temporary", "short-horizon", "short horizon", "pullback"]):
        failures.append({
            "code": "BLOCK_MECHANISM_FORMULA_OPERATOR_OMISSION",
            "message": "formula uses short delta/delay but derivation does not discuss reversal, dislocation, temporary state, or short horizon",
        })
    return {
        "version": CONSISTENCY_VERSION,
        "features": features,
        "mechanism_inputs_not_in_formula": mechanism_inputs_not_in_formula,
        "status": "PASS" if not failures else "BLOCK",
        "failures": failures,
    }
