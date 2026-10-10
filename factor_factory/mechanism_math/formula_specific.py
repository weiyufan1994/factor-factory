from __future__ import annotations

import math
import os
import re
from typing import Any

from .transient_impact import has_explicit_transient_impact_model as _has_explicit_transient_impact_model

from factor_factory.formula import parse_formula
from factor_factory.formula.registry import canonical_operator_name, validate_operator_call
from factor_factory.formula.semantics import operator_lookback
from factor_factory.research_profiles import (
    research_compatibility_profile_from_spec,
    revision_evidence_minimum,
)


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
    "fcf",
    "wacc",
    "intrinsic value",
    "residual income",
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


def _recognized_formula_root(formula_ir: Any) -> dict[str, Any] | None:
    """Recognize typed formula structure using the existing operator contract."""
    if not isinstance(formula_ir, dict) or formula_ir.get("parse_status") not in (None, "success"):
        return None

    def recognize(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            raise ValueError("unrecognized formula node")
        kind = node.get("type")
        if kind == "field":
            field = node.get("resolved_field") or node.get("name") or node.get("field")
            if not isinstance(field, str) or not field.strip():
                raise ValueError("missing field name")
            return node
        if kind == "constant":
            value = node.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("invalid constant")
            return node
        if kind == "operator" and isinstance(node.get("args"), list):
            op = canonical_operator_name(node.get("operator"))
            args = [recognize(arg) for arg in node["args"]]
            validate_operator_call(op, args)
            return {**node, "operator": op, "args": args}
        raise ValueError("unrecognized formula node")

    try:
        return recognize(formula_ir.get("root") or formula_ir)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def formula_features(spec_like: dict[str, Any], mechanism_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    canonical = _canonical(spec_like or {})
    operators = {str(item).lower() for item in _as_list(canonical.get("operators") or canonical.get("operator_set")) if str(item).strip()}
    fields: set[str] = set()
    for key in ("required_inputs", "required_fields", "observable_inputs"):
        fields.update(str(item).lower() for item in _as_list(canonical.get(key)) if str(item).strip())
    constants: list[float] = []
    formula_ir = canonical.get("formula_ir") or spec_like.get("formula_ir")
    formula_text = str(canonical.get("formula_text") or canonical.get("raw_formula_text") or spec_like.get("formula_text") or "")
    # Only registered operator argument positions establish temporal windows.
    # Unit scales, thresholds, code digits and free-text prose are not windows.
    temporal_root = _recognized_formula_root(formula_ir)
    temporal_source = "formula"
    if temporal_root is None:
        temporal_root = _recognized_formula_root(parse_formula(formula_text))
    if temporal_root is None:
        program = (canonical.get('mechanism_conditioned_measurement_program')
                   or spec_like.get('mechanism_conditioned_measurement_program')
                   or (mechanism_analysis or {}).get('mechanism_conditioned_measurement_program'))
        observation = program.get('observation_and_estimation') if isinstance(program, dict) else None
        projection = observation.get('executable_formula_projection') if isinstance(observation, dict) else None
        if isinstance(projection, str) and projection.strip():
            temporal_root = _recognized_formula_root(parse_formula(projection))
            temporal_source = "measurement_program.executable_formula_projection"
    windows: list[dict[str, Any]] = []
    has_long_return_short_temporal_product = False
    has_multiplication = False

    def visit(node: Any) -> tuple[bool, bool]:
        nonlocal has_long_return_short_temporal_product, has_multiplication
        if not isinstance(node, dict) or node.get('type') != 'operator':
            return False, False
        op = str(node.get('operator') or '').lower()
        args = node.get('args') or []
        children = [visit(arg) for arg in args]
        window = operator_lookback(node)
        if window is not None:
            windows.append({'operator': op, 'window': window, 'source': temporal_source})
        operand = args[0] if args and isinstance(args[0], dict) else {}
        is_return = (operand.get('type') == 'field' and str(operand.get('resolved_field') or operand.get('name')
                      or operand.get('field') or '').lower() in {'returns', 'return', 'pct_chg'})
        long_return = op == 'sum' and is_return and window is not None and window >= 120
        short_change = op in {'delay', 'delta'} and window is not None and 1 <= window <= 20
        if op in {'multiply', 'mul'}:
            has_multiplication = True
            has_long_return_short_temporal_product |= any(a != b and left[0] and right[1]
                for a, left in enumerate(children) for b, right in enumerate(children))
        return long_return or any(child[0] for child in children), short_change or any(child[1] for child in children)

    temporal_known = temporal_root is not None
    if temporal_known:
        _walk_formula_ir(temporal_root, operators, fields, constants)
    long_return, short_change = visit(temporal_root) if temporal_known else (False, False)
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
        "window_analysis_status": 'known' if temporal_known else 'unknown',
        "window_evidence": windows,
        "has_long_window": any(item['window'] >= 120 for item in windows),
        "has_250_window": any(item['window'] == 250 for item in windows),
        "has_long_return_window": long_return,
        "has_short_delay_or_delta": short_change,
        "has_multiplication": has_multiplication,
        "has_long_return_short_temporal_product": has_long_return_short_temporal_product,
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

    if features.get("has_long_return_window"):
        components.append({
            "component": "long_window_return_sum",
            "formula_feature": "sum(returns, declared long window)",
            "economic_state": "long-window return aggregate; economic interpretation requires the selected model",
            "modelling_role": "aggregates observed returns over a declared window; does not establish a predictive mechanism",
        })
    elif features.get("has_long_window"):
        components.append({
            "component": "long_window_state",
            "formula_feature": "declared long temporal window or lag",
            "economic_state": "long-history observable; economic interpretation requires the selected model",
            "modelling_role": "declared temporal dependency, without inferring a return-trend mechanism",
        })
    if features.get("has_short_delay_or_delta"):
        components.append({
            "component": "short_horizon_lag_or_difference",
            "formula_feature": "delay(input,k) or delta(input,k) at a declared short horizon",
            "economic_state": "short-horizon lag or difference of the declared input; economic interpretation requires the selected model",
            "modelling_role": "short temporal change or lag; its interaction with other states requires explicit evidence",
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
    if features.get('has_multiplication'):
        components.append({
            "component": "state_interaction",
            "formula_feature": "multiplication / interaction",
            "economic_state": "product of declared operands, including possible unit scaling",
            "modelling_role": "multiplication alone does not identify economic states or their time horizons",
        })
    if not components:
        components.append({
            "component": "primary_formula_state",
            "formula_feature": features.get("formula_text") or "formula_ir",
            "economic_state": "unresolved formula interpretation; use the declared mathematical object or measurement program",
            "modelling_role": "requires researcher-specific interpretation without assuming a latent state",
        })

    if features.get("has_long_return_short_temporal_product"):
        interaction = "long_return_aggregate_x_short_lag_or_difference"
        latent = [
            "product with a long-window return aggregate and a short-horizon lag or difference in distinct operands",
            "economic mechanism, payoff direction, and payer remain researcher-defined",
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
        "mathematical_object_candidates": list(dict.fromkeys(latent)),
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
    if candidates and next((item.get("model_family") for item in candidates if isinstance(item, dict) and item.get("model_family")), None):
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
    model_family = str(math_selection_obj.get("model_family") or math_selection_obj.get("selected_baseline_model") or "").strip()

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
    return " ; ".join(parts).lower()


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


def _has_explicit_conditional_mean_regression(process: str) -> bool:
    """Recognize a signed conditional-mean cross-sectional model."""
    normalized = process.lower().translate(
        str.maketrans({"β": "beta", "α": "alpha", "γ": "gamma"})
    )
    return bool(
        re.search(r"e\s*\[[^\]]+\|[^\]]+\]\s*=", normalized)
        and "alpha" in normalized
        and re.search(r"beta(?:_[a-z0-9]+)?\s*\*", normalized)
        and re.search(r"measured_object|x[0-9]+|factor|score|state", normalized)
        and re.search(r"beta(?:_[a-z0-9]+)?\s*(?:>|<)\s*0", normalized)
    )




def _has_explicit_jump_threshold_model(process: str) -> bool:
    jump_terms = {
        "boundary",
        "discontinuity",
        "jump",
        "stopping",
        "threshold",
        "不连续",
        "停止时",
        "边界",
        "跳跃",
        "隔夜跳",
        "阈值",
    }
    state_assignment = re.search(
        r"(?:^|;)\s*(?P<state>s(?:_[a-z0-9_{},]+)?)\s*=\s*(?P<definition>[^;]+)",
        process,
    )
    state_name = state_assignment.group("state") if state_assignment else ""
    state_definition = state_assignment.group("definition") if state_assignment else ""
    has_threshold_gate = any(
        marker in state_definition
        for marker in {"1{", "indicator", "sign(", "threshold", "不连续", "边界", "阈值"}
    ) or bool(re.search(r"(?:<=|>=|<|>)", state_definition))
    has_jump_price_link = bool(
        re.search(
            r"(?:^|;)\s*(?:o|open|p|price)(?:_[a-z0-9_{}]+)?\s*=\s*[^;]*"
            r"(?:j(?:_[a-z0-9_{}]+)?|jump|跳)",
            process,
        )
        or re.search(r"(?:^|;)\s*j(?:_[a-z0-9_{}]+)?\s*=\s*[^;]+", process)
    )
    payoff_equation = re.search(r"e\[[^]]+\]\s*=\s*(?P<payoff>[^;]+)", process)
    payoff_expression = payoff_equation.group("payoff") if payoff_equation else ""
    has_payoff_state_link = bool(
        state_name
        and re.search(
            rf"(?<![a-z0-9_]){re.escape(state_name)}(?![a-z0-9_])",
            payoff_expression,
        )
    )
    return (
        process.count("=") >= 3
        and any(term in process for term in jump_terms)
        and has_jump_price_link
        and has_threshold_gate
        and has_payoff_state_link
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
    if any(
        token in text
        for token in [
            "dcf",
            "discounted cash flow",
            "intrinsic value",
            "present value",
            "residual-income valuation",
            "residual income valuation",
            "valuation gap",
            "valuation identity",
        ]
    ):
        return "valuation_identity"
    if any(
        token in text
        for token in [
            "earnings",
            "growth",
            "cash flow",
            "fcf",
            "profit",
            "book",
            "accrual",
            "capital allocation",
            "financing constraint",
            "unit economics",
        ]
    ):
        # Fundamental evidence selects the domain, not a universal valuation
        # model. The research hypothesis or measurement program must opt into
        # DCF/residual-income valuation explicitly.
        return "other"
    if any(token in text for token in ["information", "underreaction", "delayed", "diffusion", "attention", "signal extraction"]):
        return "state_space"
    if any(token in text for token in ["liquidity", "impact", "order imbalance", "rebalance", "inventory", "constraint", "market-structure", "market structure"]):
        return "transient_impact"
    if any(op in features.get("operators", []) for op in ["correlation", "corr", "covariance", "cov"]) or "rank" in features.get("operators", []):
        return "copula_rank_dependence"
    if features.get("has_sign_or_threshold"):
        return "jump_threshold"
    return "other"


def _normalize_baseline_model_family(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    aliases = {
        "discounted cash-flow valuation": "valuation_identity",
        "discounted_cash_flow": "valuation_identity",
        "dcf": "valuation_identity",
        "residual-income valuation": "valuation_identity",
        "residual_income": "valuation_identity",
        "accounting identity": "other",
        "accounting quality": "other",
        "unit economics": "other",
        "structural causal model": "other",
        "linear factor projection": "projection_residualization",
        "price_volume_microstructure": "transient_impact",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in BASELINE_MODEL_FAMILIES else None


def _selected_model_from_measurement_program(
    spec_like: dict[str, Any],
    mechanism_analysis: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    canonical = _canonical(spec_like or {})
    candidates = [
        mechanism_analysis.get("mechanism_conditioned_measurement_program"),
        spec_like.get("mechanism_conditioned_measurement_program"),
        canonical.get("mechanism_conditioned_measurement_program"),
    ]
    for program in candidates:
        if not isinstance(program, dict):
            continue
        selection = program.get("model_selection")
        if not isinstance(selection, dict):
            continue
        models = selection.get("candidate_models")
        if not isinstance(models, list):
            continue
        selected = [
            item
            for item in models
            if isinstance(item, dict) and item.get("selected") is True
        ]
        if len(selected) != 1:
            continue
        return program, selected[0]
    return None


def _selected_baseline_from_measurement_program(
    spec_like: dict[str, Any],
    mechanism_analysis: dict[str, Any],
) -> str | None:
    selected = _selected_model_from_measurement_program(
        spec_like,
        mechanism_analysis,
    )
    if selected is None:
        return None
    _, model = selected
    raw = str(model.get("model_family") or "").strip()
    return _normalize_baseline_model_family(raw) or raw or None


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
    formula_state_link = _component_summary(components) or "primary formula transform estimates the selected mathematical object"
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
    selected_baseline = _selected_baseline_from_measurement_program(
        spec_like,
        mechanism_analysis,
    )
    selected_program_model = _selected_model_from_measurement_program(
        spec_like,
        mechanism_analysis,
    )
    if interaction_structure == "open_close_intraday_position":
        economic = (
            "Formula-specific hypothesis: an open/close relative-position transform estimates overnight-to-intraday "
            "pressure, opening-gap digestion, or close-location reversal. Overnight extrapolators, opening auction "
            "liquidity demanders, or close-location chasers may pay when the next-horizon return corrects that "
            "short-horizon price-location state."
        )
    baseline = selected_baseline or _select_baseline_model(economic, features)
    components: list[dict[str, Any]] = []
    if features["has_long_return_window"]:
        components.append({
            "component": "long_window_return_sum",
            "formula_feature": "sum(returns, long window)",
            "state_interpretation": "long-window aggregate of observed returns",
            "mechanism_requirement": "justify the aggregate and window using the selected model and evidence",
        })
    if features["has_short_delay_or_delta"]:
        components.append({
            "component": "short_horizon_lag_or_difference",
            "formula_feature": "delta/delay over short horizon",
            "state_interpretation": "short-horizon lag or difference of the declared input",
            "mechanism_requirement": "justify this input and temporal transform using the selected model and evidence",
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
            "state_interpretation": "observable estimator for the selected mathematical object",
            "mechanism_requirement": "connect this transform to the selected object, payer behavior, and expected return horizon",
        })

    metric_feedback = "Observed metrics must be compared with the expected signature; contradiction should trigger model challenge, formula mutation, or kill criteria."
    if metrics:
        metric_feedback = (
            "Metric evidence is mixed or incomplete unless long-side, cost-adjusted, monotonicity, and horizon evidence all match; "
            "contradiction feeds back into baseline model choice, estimator definition, sign/horizon, or kill criteria."
        )

    payer_derivation = _profit_payer_for_baseline(baseline, components, economic, mechanism_analysis)
    selected_program = selected_program_model[0] if selected_program_model else {}
    selected_model = selected_program_model[1] if selected_program_model else {}
    selected_observation = (
        selected_program.get("observation_and_estimation")
        if isinstance(selected_program.get("observation_and_estimation"), dict)
        else {}
    )
    selected_projection = (
        selected_program.get("market_outcome_projection")
        if isinstance(selected_program.get("market_outcome_projection"), dict)
        else {}
    )
    return {
        "version": DERIVATION_VERSION,
        "economic_to_math_model_selection": {
            "baseline_model_family": baseline,
            "why_selected_from_economic_hypothesis": (
                "Selected from the economic hypothesis and formula structure, not from a fixed factor-family template: "
                f"{economic[:400] or 'economic hypothesis under-specified'}"
            ),
            "why_not_generic_template": "The model must explain payer behavior, the selected mathematical object, its mechanism equation or functional, the observation mapping, and the metric signature for this specific formula.",
            "model_mutations_for_this_formula": [
                item["mechanism_requirement"] for item in components
            ],
        },
        "profit_payer_derivation": payer_derivation,
        "formula_components": components,
        "mathematical_object_mapping": [
            {
                "observable_component": item["component"],
                "mathematical_object_claim": item["state_interpretation"],
                "observation_mapping": item["mechanism_requirement"],
            }
            for item in components
        ],
        "selected_model_family": baseline,
        "why_this_model_not_generic_template": "It is tied to economic payer behavior, formula components, horizon, sign convention, and metric falsification.",
        "mathematical_object": str(
            selected_model.get("mathematical_object")
            or _mathematical_object_for_baseline(baseline, features)
        ),
        "mechanism_equation_or_functional": str(
            selected_model.get("mechanism_equation_or_functional")
            or _mechanism_for_baseline(baseline, features)
        ),
        "target_functional": str(
            selected_observation.get("estimand")
            or _target_functional_for_baseline(baseline)
        ),
        "market_outcome_projection": str(
            selected_projection.get("projection_equation_or_map")
            or _market_outcome_projection_for_baseline(baseline)
        ),
        "observation_mapping": str(
            selected_observation.get("observation_map")
            or selected_observation.get("estimator")
            or "the formula maps legal-time observables into the selected mathematical object; each transform must have a payer, model-term, and horizon interpretation"
        ),
        "expected_metric_signature": "rank IC, long-side return, cost-adjusted return, monotonicity, and turnover must match the declared sign and horizon",
        "observed_metric_comparison": metric_feedback,
        "metric_feedback_to_model": "Unsupported metrics must revise the baseline model, mutate the estimator/sign/horizon, or activate kill criteria.",
        "falsification_tests": [
            "Block promotion if long-side cost-adjusted evidence contradicts the expected payoff direction.",
            "Block or mutate if formula component behavior does not match the selected mathematical object's declared horizon.",
        ],
        "kill_criteria": [
            "Kill if no identifiable payer or constraint remains after evidence review.",
            "Kill if metrics only support short-leg or diagnostic long-short behavior under a long-only mandate.",
        ],
        "revision_implication": "Use model/formula mutation only after evidence contradicts a specific derivation step; do not repair through portfolio construction.",
    }


def _mathematical_object_for_baseline(
    baseline: str,
    features: dict[str, Any],
) -> str:
    if baseline == "valuation_identity":
        return "discounted forecast cash-flow or residual-income functional and its intrinsic-value-to-price gap"
    if baseline == "state_space":
        return "latent information object together with its legal-time observation map"
    if baseline == "transient_impact":
        return "signed temporary order-flow or inventory-pressure component"
    if baseline == "cointegration":
        return "cointegrating residual and equilibrium-deviation functional"
    if baseline == "copula_rank_dependence":
        return "conditional rank-dependence functional or copula section"
    if baseline == "jump_threshold":
        return "threshold-crossing event, stopping time, and boundary direction"
    if baseline == "projection_residualization":
        return "orthogonal projection residual after declared nuisance exposure removal"
    if baseline == "fourier_wavelet":
        return "localized spectral coefficient or multiscale signal component"
    if baseline == "dimensional_scaling":
        return "scale-invariant ratio or scaling-law residual"
    if baseline == "stochastic_process":
        return "mechanism-specific return, event, occupation, or path functional under the legal information set"
    return "researcher-selected mathematical object justified by the economic hypothesis"


def _mechanism_for_baseline(baseline: str, features: dict[str, Any]) -> str:
    if baseline == "valuation_identity":
        return (
            "V_t=sum_{k=1}^T FCF_{t+k}/(1+WACC_t)^k "
            "+ TV_t/(1+WACC_t)^T; valuation_gap_t=V_t/P_t-1"
        )
    if baseline == "state_space":
        return "latent information state with delayed Bayesian updating or signal extraction under F_t"
    if baseline == "transient_impact":
        return (
            "transient order-flow impact state: I_{t+1}=rho*I_t+eta_t with |rho|<1; "
            "impact_t=lambda*I_t; E[r_{t+1}|F_t,I_t]=-lambda*(1-rho)*I_t after "
            "the temporary imbalance decays"
        )
    if baseline == "copula_rank_dependence":
        return "rank-dependence or copula model linking monotone transforms to an economic latent state"
    if baseline == "jump_threshold":
        return "threshold or stopping-time state transition process with discontinuity and turnover implications"
    if baseline == "stochastic_process":
        if features.get("has_open_close_position"):
            return "stochastic intraday-to-next-horizon return process with an opening-gap or close-location state that may drift, reverse, or decay after the observed session"
        return "stochastic return process with drift, reversal, volatility, or jump components estimated from legal history"
    if baseline == "cointegration":
        return "z_t=y_t-beta*x_t with stationary equilibrium error z_t; the estimator measures economically justified displacement from the equilibrium relation"
    if baseline == "projection_residualization":
        return "f_res=(I-P_X)f, where X contains only declared nuisance exposures and the residual preserves the economic estimand"
    if baseline == "fourier_wavelet":
        return "the selected localized basis decomposes the observable path into economically interpretable scale-frequency components before reconstruction of the target feature"
    if baseline == "dimensional_scaling":
        return "the selected scale-free functional is invariant to the justified unit transformation and changes only with the economic quantity of interest"
    return "an explicit model equation or functional must be supplied by the researcher; formula restatement is insufficient"


def _target_functional_for_baseline(baseline: str) -> str:
    if baseline == "valuation_identity":
        return "valuation_gap_t=intrinsic_value_t/market_price_t-1"
    if baseline == "cointegration":
        return "equilibrium_deviation_t=y_t-beta*x_t"
    if baseline == "projection_residualization":
        return "orthogonal_residual_t=(I-P_X)f_t"
    if baseline == "fourier_wavelet":
        return "mechanism_selected_scale_frequency_component_t"
    if baseline == "dimensional_scaling":
        return "mechanism_selected_scale_invariant_functional_t"
    return "E[r_{t+1:t+h} | F_t, measured_mathematical_object_t]"


def _market_outcome_projection_for_baseline(baseline: str) -> str:
    if baseline == "valuation_identity":
        return "E[r_{t+1:t+h}|F_t] is increasing in valuation_gap_t when the declared convergence mechanism holds after costs"
    if baseline == "cointegration":
        return "E[r_{t+1:t+h}|F_t] follows the declared sign of equilibrium-error correction after costs"
    return "E[r_{t+1:t+h}|F_t] follows the declared sign and horizon of the selected mathematical object after costs"


def validate_formula_specific_derivation(derivation: Any, spec_like: dict[str, Any], mechanism_analysis: dict[str, Any] | None = None) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if not isinstance(derivation, dict) or not derivation:
        return [{"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "formula_specific_derivation missing"}]
    if derivation.get("version") != DERIVATION_VERSION:
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "formula_specific_derivation version invalid"})
    selection = derivation.get("economic_to_math_model_selection") if isinstance(derivation.get("economic_to_math_model_selection"), dict) else {}
    baseline = selection.get("baseline_model_family") or derivation.get("selected_model_family")
    selected_program_model = _selected_model_from_measurement_program(
        spec_like or {},
        mechanism_analysis or {},
    )
    selected_program_family = str(
        (selected_program_model[1] if selected_program_model else {}).get(
            "model_family"
        )
        or ""
    ).strip()
    open_family_matches_program = (
        bool(selected_program_family)
        and str(baseline or "").strip().casefold()
        in {
            selected_program_family.casefold(),
            str(
                _normalize_baseline_model_family(selected_program_family) or ""
            ).casefold(),
        }
    )
    if baseline not in BASELINE_MODEL_FAMILIES and not open_family_matches_program:
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": f"baseline_model_family invalid: {baseline}"})
    mathematical_object = (
        derivation.get("mathematical_object")
        or derivation.get("latent_state")
        or derivation.get("random_object")
    )
    mechanism_equation = (
        derivation.get("mechanism_equation_or_functional")
        or derivation.get("process_or_distribution")
    )
    observation_mapping = (
        derivation.get("observation_mapping")
        or derivation.get("formula_as_estimator")
    )
    current_generic_contract = (
        "mechanism_equation_or_functional" in derivation
        or "mathematical_object" in derivation
        or "observation_mapping" in derivation
    )
    required_text_fields = [
        ("economic_to_math_model_selection.why_selected_from_economic_hypothesis", selection.get("why_selected_from_economic_hypothesis")),
        ("economic_to_math_model_selection.why_not_generic_template", selection.get("why_not_generic_template")),
        ("profit_payer_derivation.payer_or_counterparty", (derivation.get("profit_payer_derivation") or {}).get("payer_or_counterparty") if isinstance(derivation.get("profit_payer_derivation"), dict) else None),
        ("profit_payer_derivation.why_they_pay", (derivation.get("profit_payer_derivation") or {}).get("why_they_pay") if isinstance(derivation.get("profit_payer_derivation"), dict) else None),
        ("mechanism_equation_or_functional", mechanism_equation),
        ("observation_mapping", observation_mapping),
        ("metric_feedback_to_model", derivation.get("metric_feedback_to_model")),
        ("revision_implication", derivation.get("revision_implication")),
    ]
    if current_generic_contract:
        required_text_fields.append(("mathematical_object", mathematical_object))
    for path, value in required_text_fields:
        if not isinstance(value, str) or not value.strip():
            failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": f"{path} missing"})
    if current_generic_contract and not str(
        derivation.get("market_outcome_projection") or ""
    ).strip():
        failures.append({
            "code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING",
            "message": "market_outcome_projection missing",
        })
    if not isinstance(derivation.get("formula_components"), list) or not derivation.get("formula_components"):
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "formula_components missing"})
    minimum = revision_evidence_minimum(
        research_compatibility_profile_from_spec(spec_like),
        "local_is_only" if os.getenv("FACTORFORGE_LOCAL_IS_ONLY") == "1" else None,
    )
    for field in ("falsification_tests", "kill_criteria"):
        values = derivation.get(field)
        if not isinstance(values, list) or len(values) < minimum or (
            minimum == 1 and any(not isinstance(item, str) or not item.strip() for item in values)
        ):
            failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": f"{field} requires {minimum} substantive item(s) for the bound profile"})
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
        "valuation_identity": ["fcf", "cash-flow", "cash flow", "discount", "growth", "valuation", "现金流", "折现", "估值", "盈利增长", "剩余收益"],
        "state_space": ["latent", "bayesian", "signal", "update", "observation", "filtered", "潜在", "贝叶斯", "信号", "更新", "观测", "滤波", "状态空间"],
        "transient_impact": ["impact", "imbalance", "inventory", "liquidity", "rho", "decay", "冲击", "不平衡", "库存", "流动性", "衰减"],
        "copula_rank_dependence": ["copula", "conditional rank", "rank state", "dependence", "条件秩", "秩状态", "依赖", "联结函数"],
        "jump_threshold": ["threshold", "stopping", "boundary", "discontinu", "tau", "阈值", "停止时", "边界", "不连续", "跳跃", "隔夜跳"],
        "stochastic_process": ["drift", "reversal", "jump", "volatility", "process", "regime", "漂移", "反转", "跳跃", "波动率", "过程", "状态转换"],
    }
    expected_terms = model_specific_terms.get(str(baseline))
    if expected_terms and not any(term in payer_blob for term in expected_terms):
        generic_hits.append(f"missing model-specific payer terms for {baseline}")
    if generic_hits:
        failures.append({
            "code": "BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC",
            "message": f"profit payer derivation is generic or incomplete: {sorted(set(generic_hits))}",
        })
    mechanism_text = str(mechanism_equation or "")
    mechanism = mechanism_text.lower()
    features = formula_features(spec_like or {}, mechanism_analysis or {})
    formula_tokens = {token for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", str(features.get("formula_text") or "").lower()) if len(token) > 2}
    model_hits = [token for token in MODEL_KEYWORDS if token in mechanism]
    formula_hits = [token for token in formula_tokens if token in mechanism]
    compact_stochastic_model = _has_explicit_stochastic_model(mechanism)
    if baseline == "stochastic_process":
        missing_model_assumption = not (
            compact_stochastic_model or _has_stochastic_process_prose(mechanism)
        )
    elif baseline == "transient_impact":
        missing_model_assumption = not _has_explicit_transient_impact_model(
            mechanism_text,
            formula_tokens,
            semantic_context=_text_blob(
                mathematical_object,
                observation_mapping,
                derivation.get("profit_payer_derivation"),
                derivation.get("economic_to_math_model_selection"),
            ),
            formula_context=_text_blob(
                observation_mapping,
                derivation.get("mathematical_object_mapping")
                or derivation.get("formula_state_estimator"),
                derivation.get("operator_consistency_discussion"),
                payer.get("formula_state_link"),
            ),
        )
    elif baseline == "jump_threshold":
        missing_model_assumption = not _has_explicit_jump_threshold_model(mechanism)
    elif baseline == "valuation_identity":
        has_value_term = any(
            term in mechanism
            for term in [
                "fcf",
                "cash flow",
                "residual income",
                "book value",
                "intrinsic_value",
                "intrinsic value",
            ]
        )
        has_discount_term = any(
            term in mechanism
            for term in ["wacc", "discount", "cost of equity", "1+", "1 +"]
        )
        missing_model_assumption = not (
            "=" in mechanism and has_value_term and has_discount_term
        )
    else:
        missing_model_assumption = not (
            model_hits or _has_explicit_conditional_mean_regression(mechanism_text)
        )
    if missing_model_assumption and (
        formula_hits
        or baseline in {
            "jump_threshold",
            "stochastic_process",
            "transient_impact",
            "valuation_identity",
        }
    ):
        failures.append({"code": "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING", "message": "mechanism_equation_or_functional merely restates formula tokens without a model assumption"})
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
    return {
        "version": CONSISTENCY_VERSION,
        "features": features,
        "mechanism_inputs_not_in_formula": mechanism_inputs_not_in_formula,
        "status": "PASS" if not failures else "BLOCK",
        "failures": failures,
    }
