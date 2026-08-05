from __future__ import annotations

import ast
import re
from fractions import Fraction
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


def _has_explicit_transient_impact_model(
    process: str,
    formula_tokens: set[str],
    semantic_context: str = "",
    formula_context: str = "",
) -> bool:
    """Recognize bounded structural/reduced-form transient-impact models."""
    impact_terms = {
        "impact",
        "imbalance",
        "order flow",
        "temporary",
        "transient",
        "冲击",
        "不平衡",
        "订单流",
        "超调",
    }
    decomposition_terms = {
        "decay",
        "persistent",
        "temporary",
        "transitory",
        "持久",
        "瞬时",
        "临时",
        "衰减",
    }
    payoff_terms = {
        "e[",
        "return",
        "r_",
        "收益",
    }
    translation = str.maketrans(
        {
            "；": ";",
            "。": ";",
            "α": "alpha",
            "β": "beta",
            "θ": "theta",
            "λ": "lambda",
            "ρ": "rho",
            "μ": "mu",
            "ε": "epsilon",
            "η": "eta",
        }
    )
    normalized = process.translate(translation)
    semantic_text = f"{process}; {semantic_context}".translate(translation)
    process_lower = semantic_text.lower()

    symbol_pattern = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*(?:\{[^}]*\})?")

    def canonical_symbol(token: str) -> str:
        if re.fullmatch(r"I_(?:\{[^}]*\}|[a-zA-Z0-9]+)", token):
            return "impact_state"
        if re.fullmatch(r"F_(?:\{[^}]*\}|[a-zA-Z0-9]+)", token):
            return "formula_state"
        lower = token.lower()
        if "_{" in lower:
            lower = lower.split("_{", 1)[0]
        else:
            match = re.fullmatch(r"(.+)_([ijknt]|t\d+)", lower)
            if match:
                lower = match.group(1)
        coefficient = re.fullmatch(
            r"(alpha|beta|lambda|rho|theta|mu)_[a-zA-Z0-9]+",
            lower,
        )
        if coefficient:
            lower = coefficient.group(1)
        return "lambda_coef" if lower == "lambda" else lower

    def symbols(value: str) -> set[str]:
        result: set[str] = set()
        for match in symbol_pattern.finditer(value):
            tail = value[match.end() :].lstrip()
            if tail.startswith("("):
                continue
            symbol = canonical_symbol(match.group(0))
            if symbol not in {"i", "j", "k", "n", "t"}:
                result.add(symbol)
        return result

    canonical_role_text = symbol_pattern.sub(
        lambda match: canonical_symbol(match.group(0)),
        semantic_text,
    ).lower()

    def formula_rhs(value: str) -> str:
        depth = 0
        for index, character in enumerate(value):
            if character in "([{":
                depth += 1
            elif character in ")]}" and depth:
                depth -= 1
            elif depth == 0 and character in ",，：":
                value = value[:index]
                break
        return re.split(
            r"(?:即|其中|假设|观测|依据|基于)|"
            r"\s+(?:is|where|with|after|because|under|given|using|alongside|via)\b",
            value,
            maxsplit=1,
        )[0].strip()

    def canonical_expression(value: str) -> str:
        return symbol_pattern.sub(
            lambda match: canonical_symbol(match.group(0)),
            value,
        ).replace("^", "**")

    allowed_calls = {"abs", "exp", "log", "mean", "mu", "sigma", "sign", "sqrt"}
    allowed_binary_ops = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
    allowed_unary_ops = (ast.UAdd, ast.USub)

    def valid_ast(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return valid_ast(node.body)
        if isinstance(node, ast.Name):
            return bool(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", node.id))
        if isinstance(node, ast.Constant):
            return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        if isinstance(node, ast.UnaryOp):
            return isinstance(node.op, allowed_unary_ops) and valid_ast(node.operand)
        if isinstance(node, ast.BinOp):
            return (
                isinstance(node.op, allowed_binary_ops)
                and valid_ast(node.left)
                and valid_ast(node.right)
            )
        if isinstance(node, ast.Call):
            return (
                isinstance(node.func, ast.Name)
                and node.func.id in allowed_calls
                and not node.keywords
                and bool(node.args)
                and all(valid_ast(arg) for arg in node.args)
            )
        return False

    def ast_names(node: ast.AST) -> set[str]:
        function_names = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        return {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name) and child.id not in function_names
        }

    def add_polynomials(
        left: dict[tuple[str, ...], Fraction],
        right: dict[tuple[str, ...], Fraction],
        *,
        right_sign: int = 1,
    ) -> dict[tuple[str, ...], Fraction]:
        result = dict(left)
        for monomial, coefficient in right.items():
            result[monomial] = result.get(monomial, Fraction(0)) + right_sign * coefficient
            if result[monomial] == 0:
                del result[monomial]
        return result

    def multiply_polynomials(
        left: dict[tuple[str, ...], Fraction],
        right: dict[tuple[str, ...], Fraction],
    ) -> dict[tuple[str, ...], Fraction] | None:
        if len(left) * len(right) > 64:
            return None
        result: dict[tuple[str, ...], Fraction] = {}
        for left_monomial, left_coefficient in left.items():
            for right_monomial, right_coefficient in right.items():
                monomial = tuple(sorted(left_monomial + right_monomial))
                result[monomial] = result.get(monomial, Fraction(0)) + (
                    left_coefficient * right_coefficient
                )
                if result[monomial] == 0:
                    del result[monomial]
        return result

    def polynomial(node: ast.AST) -> dict[tuple[str, ...], Fraction] | None:
        if isinstance(node, ast.Expression):
            return polynomial(node.body)
        if isinstance(node, ast.Name):
            return {(node.id,): Fraction(1)}
        if isinstance(node, ast.Constant):
            try:
                return {(): Fraction(str(node.value))}
            except (ValueError, ZeroDivisionError):
                return None
        if isinstance(node, ast.UnaryOp):
            value = polynomial(node.operand)
            if value is None:
                return None
            if isinstance(node.op, ast.USub):
                return {monomial: -coefficient for monomial, coefficient in value.items()}
            return value
        if isinstance(node, ast.BinOp):
            left = polynomial(node.left)
            right = polynomial(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return add_polynomials(left, right)
            if isinstance(node.op, ast.Sub):
                return add_polynomials(left, right, right_sign=-1)
            if isinstance(node.op, ast.Mult):
                return multiply_polynomials(left, right)
            if isinstance(node.op, ast.Div):
                if set(right) != {()} or right[()] == 0:
                    return None
                return {
                    monomial: coefficient / right[()]
                    for monomial, coefficient in left.items()
                }
            if isinstance(node.op, ast.Pow):
                if set(right) != {()} or right[()].denominator != 1:
                    return None
                exponent = int(right[()])
                if exponent < 0 or exponent > 3:
                    return None
                result: dict[tuple[str, ...], Fraction] = {(): Fraction(1)}
                for _ in range(exponent):
                    product = multiply_polynomials(result, left)
                    if product is None:
                        return None
                    result = product
                return result
        if isinstance(node, ast.Call):
            opaque = "call:" + ast.dump(node, annotate_fields=False, include_attributes=False)
            return {(opaque,): Fraction(1)}
        return None

    def parse_math(value: str) -> dict[str, Any] | None:
        if re.search(r"[\u3400-\u9fff]", value):
            return None
        source = canonical_expression(value)
        try:
            tree = ast.parse(source, mode="eval")
        except (SyntaxError, ValueError):
            return None
        if not valid_ast(tree):
            return None
        return {
            "tree": tree,
            "names": ast_names(tree),
            "polynomial": polynomial(tree),
        }

    equations: list[dict[str, Any]] = []
    for clause in normalized.split(";"):
        equality_parts = [
            part.strip()
            for part in re.split(r"(?<![<>=!])=(?!=)", clause)
            if part.strip()
        ]
        if len(equality_parts) < 2:
            continue
        left = re.split(r"[:：]", equality_parts[0])[-1].strip()
        left_math = parse_math(left)
        parsed_rights: list[tuple[str, str, dict[str, Any] | None]] = []
        for candidate_right in equality_parts[1:]:
            raw_right = candidate_right.strip()
            right = raw_right if len(equality_parts) > 2 else formula_rhs(raw_right)
            parsed_rights.append((raw_right, right, parse_math(right)))
        if any(right_math is None for _, _, right_math in parsed_rights):
            continue
        for raw_right, right, right_math in parsed_rights:
            if (
                left
                and right
                and re.sub(r"\s+", "", left) != re.sub(r"\s+", "", right)
                and right_math is not None
                and not (
                    left_math is not None
                    and left_math["polynomial"] is not None
                    and left_math["polynomial"] == right_math["polynomial"]
                )
            ):
                equations.append(
                    {
                        "left": left,
                        "right": right,
                        "raw_right": raw_right,
                        "clause": clause.strip(),
                        "left_symbols": symbols(left),
                        "right_symbols": set(right_math["names"]),
                        "right_polynomial": right_math["polynomial"],
                    }
                )

    coefficient_terms = {
        "alpha",
        "beta",
        "lambda",
        "lambda_coef",
        "rho",
        "theta",
        "mu",
    }
    residual_terms = {"eps", "epsilon", "eta", "innovation", "residual", "shock"}
    semantic_states = {
        "dislocation",
        "dislocation_state",
        "flow",
        "flow_state",
        "i",
        "imbalance",
        "imbalance_state",
        "impact",
        "impact_state",
        "inventory",
        "inventory_state",
        "order_flow",
        "order_flow_state",
        "pressure",
        "pressure_state",
    }
    payoff_equations: list[dict[str, Any]] = []
    for equation in equations:
        left_lower = str(equation["left"]).lower()
        expectation_lhs = bool(
            re.search(r"e\[[^\]]*(?:r(?:[_({]|$)|return(?:[_({]|$))", left_lower)
        )
        direct_return_lhs = bool(
            re.match(r"^(?:r(?:[_({]|$)|return(?:[_({]|$))", left_lower)
        )
        chinese_direct_return_lhs = bool(
            re.fullmatch(r"收益(?:率)?", left_lower.strip())
        )
        chinese_expected_return_lhs = bool(
            re.fullmatch(
                r"(?:(?:条件)?(?:预期|期望)收益(?:率)?|条件收益(?:率)?)",
                left_lower.strip(),
            )
        )
        right_symbols = set(equation["right_symbols"])
        if (
            (
                expectation_lhs
                or direct_return_lhs
                or chinese_direct_return_lhs
                or chinese_expected_return_lhs
            )
            and bool(coefficient_terms.intersection(right_symbols))
        ):
            equation["direct_return_lhs"] = (
                direct_return_lhs or chinese_direct_return_lhs
            )
            payoff_equations.append(equation)

    def polynomial_contains(
        equation: dict[str, Any],
        required_groups: tuple[set[str], ...],
    ) -> bool:
        expression = equation.get("right_polynomial")
        if not isinstance(expression, dict):
            return False
        return any(
            coefficient != 0
            and all(group.intersection(monomial) for group in required_groups)
            for monomial, coefficient in expression.items()
        )

    def polynomial_symbols(equation: dict[str, Any]) -> set[str]:
        expression = equation.get("right_polynomial")
        if not isinstance(expression, dict):
            return set()
        return {
            symbol
            for monomial, coefficient in expression.items()
            if coefficient != 0
            for symbol in monomial
            if not symbol.startswith("call:")
        }

    def has_independent_residual(equation: dict[str, Any]) -> bool:
        expression = equation.get("right_polynomial")
        if not isinstance(expression, dict):
            return False
        for monomial, coefficient in expression.items():
            if coefficient == 0:
                continue
            residual_count = sum(symbol in residual_terms for symbol in monomial)
            if residual_count == 1 and len(monomial) == 1:
                return True
        return False

    def has_time_index(value: str, state: str, *, future: bool) -> bool:
        compact = re.sub(r"\s+", "", value.lower())
        pattern = re.compile(
            rf"(?<![a-zA-Z0-9_]){re.escape(state)}"
            rf"(?:_\{{(?P<braced>[^}}]+)\}}|_(?P<plain>[a-zA-Z0-9]+))"
        )
        for match in pattern.finditer(compact):
            index = str(match.group("braced") or match.group("plain") or "")
            if future and (
                index == "t1"
                or bool(re.search(r"(?:^|,)t\+1(?:$|,)", index))
            ):
                return True
            if not future and (
                index == "t"
                or bool(re.search(r"(?:^|,)t(?:$|,)", index))
            ):
                return True
        return False

    def transition_rho_symbol(value: str, state: str) -> str | None:
        compact = re.sub(r"\s+", "", value.lower())
        rho = r"rho(?:_(?:\{[^}]+\}|[a-zA-Z0-9]+))?"
        state_ref = rf"{re.escape(state)}(?:_(?:\{{[^}}]+\}}|[a-zA-Z0-9]+))?"
        for pattern in (
            rf"(?P<rho>{rho})\*{state_ref}(?![a-zA-Z0-9_])",
            rf"(?<![a-zA-Z0-9_]){state_ref}\*(?P<rho>{rho})",
        ):
            match = re.search(pattern, compact)
            if match:
                return str(match.group("rho"))
        return None

    def has_stable_rho_constraint(value: str, rho_symbol: str) -> bool:
        compact = re.sub(r"\s+", "", value.lower())
        escaped = re.escape(rho_symbol.lower())
        boundary = r"(?=$|,|;|\)|\]|\}|(?:and|or|where|with|under|given|且|并))"
        one = rf"1(?:\.0+)?{boundary}"
        positive_patterns = (
            rf"\|{escaped}\|<{one}",
            rf"abs\({escaped}\)<{one}",
            rf"-1(?:\.0+)?<{escaped}<{one}",
        )
        number = r"(?P<bound>(?:\d+(?:\.\d*)?|\.\d+)(?:e[+\-]?\d+)?)"
        contradiction_patterns = (
            rf"\|{escaped}\|(?:>=|>){number}",
            rf"abs\({escaped}\)(?:>=|>){number}",
            rf"(?<![a-zA-Z0-9_]){escaped}(?:>=|>){number}",
            rf"(?<![a-zA-Z0-9_]){escaped}(?:<=|<)-{number}",
        )
        for pattern in contradiction_patterns:
            for match in re.finditer(pattern, compact):
                try:
                    if float(match.group("bound")) >= 1.0:
                        return False
                except (TypeError, ValueError):
                    return False
        equality_patterns = (
            rf"\|{escaped}\|=(?P<bound>(?:\d+(?:\.\d*)?|\.\d+)(?:e[+\-]?\d+)?)",
            rf"abs\({escaped}\)=(?P<bound>(?:\d+(?:\.\d*)?|\.\d+)(?:e[+\-]?\d+)?)",
            rf"(?<![a-zA-Z0-9_]){escaped}=(?P<bound>[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+\-]?\d+)?)",
        )
        for pattern in equality_patterns:
            for match in re.finditer(pattern, compact):
                try:
                    if abs(float(match.group("bound"))) >= 1.0:
                        return False
                except (TypeError, ValueError):
                    return False
        positive_assertion_found = False
        for assertion in re.split(r"[,;，；]", value.lower()):
            compact_assertion = re.sub(r"\s+", "", assertion)
            if not any(
                re.search(pattern, compact_assertion)
                for pattern in positive_patterns
            ):
                continue
            constraint_start = re.search(
                rf"\|\s*{escaped}\s*\||abs\s*\(\s*{escaped}\s*\)|"
                rf"-\s*1(?:\.0+)?\s*<\s*{escaped}",
                assertion,
            )
            prefix = assertion[: constraint_start.start()] if constraint_start else assertion
            suffix = assertion[constraint_start.start() :] if constraint_start else ""
            prefix_negated = bool(
                re.search(
                    r"(?:\bnot\b|\bno\b|\bnever\b|\bwithout\b|\bcannot\b|"
                    r"\bfalse\b|\b(?:do|does|did|is|are|was|were|can|could|"
                    r"should|would)n['’]?t\b|\bfail(?:s|ed)?\s+to\b|"
                    r"\bunable\s+to\b|并非|不是|不为|没有|"
                    r"无(?:法|须|需)|未(?:曾|能|予|被|假设|满足)|"
                    r"不(?:会|能|应|可|予|作|做|假设|满足|要求|成立|声明)|"
                    r"(?:不|未|无)\s*$)",
                    prefix,
                )
            )
            suffix_negated = bool(
                re.search(
                    r"(?:\b(?:is|was|does|did)\s+not\s+(?:assumed|satisfied|"
                    r"required|imposed|valid|true)|不成立|不满足|"
                    r"并非假设|未被假设)",
                    suffix,
                )
            )
            if prefix_negated or suffix_negated:
                return False
            positive_assertion_found = True
        return positive_assertion_found

    def is_ar1_transition(equation: dict[str, Any], state: str) -> bool:
        expression = equation.get("right_polynomial")
        if not isinstance(expression, dict):
            return False
        transition_term = tuple(sorted(("rho", state)))
        residual_monomials = {
            (term,) for term in residual_terms
        }
        active_terms = {
            monomial for monomial, coefficient in expression.items() if coefficient != 0
        }
        return (
            transition_term in active_terms
            and abs(expression[transition_term]) == 1
            and len(active_terms.intersection(residual_monomials)) == 1
            and active_terms <= ({transition_term} | residual_monomials)
        )

    def raw_rho_symbols(value: str) -> set[str]:
        return {
            match.group(0).lower()
            for match in re.finditer(
                r"(?<![a-zA-Z0-9_])rho(?:_(?:\{[^}]+\}|[a-zA-Z0-9]+))?"
                r"(?![a-zA-Z0-9_])",
                value,
            )
        }

    formula_role_text = symbol_pattern.sub(
        lambda match: canonical_symbol(match.group(0)),
        formula_context.translate(translation),
    ).lower()
    formula_markers = {
        "estimator",
        "expression",
        "factor",
        "factor_state",
        "formula",
        "formula_state",
        "signal",
        "信号",
        "公式",
        "因子",
    }
    formula_link_terms = {
        "capture",
        "captures",
        "estimate",
        "estimated",
        "estimates",
        "identify",
        "identifies",
        "map",
        "maps",
        "measure",
        "measures",
        "proxy",
        "proxies",
        "represent",
        "represents",
        "target",
        "targets",
        "代理",
        "估计",
        "刻画",
        "捕捉",
        "映射",
        "测度",
        "识别",
    }

    def semantic_clauses(value: str) -> list[str]:
        clauses: list[str] = []
        start = 0
        depth = 0
        for index, character in enumerate(value):
            if character in "([{":
                depth += 1
            elif character in ")]}" and depth:
                depth -= 1
            elif depth == 0 and (
                character in ";；,，。"
                or (
                    character == "."
                    and not (
                        index > 0
                        and index + 1 < len(value)
                        and value[index - 1].isdigit()
                        and value[index + 1].isdigit()
                    )
                )
            ):
                clauses.append(value[start:index].strip())
                start = index + 1
        clauses.append(value[start:].strip())
        return [clause for clause in clauses if clause]

    def has_formula_state_link(state: str) -> bool:
        state_pattern = rf"(?<![a-zA-Z0-9_]){re.escape(state)}(?![a-zA-Z0-9_])"
        contrast_pattern = (
            r"\b(?:apart\s+from|but|except|however|instead|other\s+than|"
            r"rather\s+than|save\s+for|whereas)\b|"
            r"但|却|而非|与其|不如|除(?:了)?|排除|剔除|"
            r"以外|之外"
        )
        formula_link_found = False
        formula_link_negated = False
        for clause in semantic_clauses(formula_role_text):
            clause_symbols = symbols(clause)
            has_formula_marker = bool(
                formula_markers.intersection(clause_symbols)
            ) or any(marker in clause for marker in {"信号", "公式", "因子"})
            if not has_formula_marker:
                continue
            positive_link = False
            negative_link = False
            for term in sorted(formula_link_terms, key=len, reverse=True):
                term_pattern = (
                    rf"(?<![a-zA-Z]){re.escape(term)}(?![a-zA-Z])"
                    if term.isascii()
                    else re.escape(term)
                )
                for match in re.finditer(term_pattern, clause):
                    prefix = clause[max(0, match.start() - 32) : match.start()]
                    polarity_prefix = re.split(contrast_pattern, prefix)[-1]
                    negated = bool(
                        re.search(
                            r"(?:\bnot\b|\bnever\b|\bcannot\b|\bno\b|"
                            r"\b(?:do|does|did|is|are|was|were|can|could|"
                            r"should|would)n['’]?t\b|\bfail(?:s|ed)?\s+to\b|"
                            r"\bunable\s+to\b|"
                            r"并非|没有|无(?:法|须|需)|"
                            r"未(?:曾|能|予|被|估计|识别|表示)|"
                            r"不(?:会|能|可|应|再|予|作|做|估计|识别|表示|代表)|"
                            r"(?:不|未|无)\s*$)",
                            polarity_prefix,
                        )
                    )
                    tail = clause[match.end() :]
                    tail = re.split(contrast_pattern, tail, maxsplit=1)[0]
                    if re.search(state_pattern, tail):
                        state_prefix = re.split(state_pattern, tail, maxsplit=1)[0]
                        state_negated = bool(
                            re.search(
                                r"(?:\b(?:not|never|no|neither|without|cannot)\s*$|"
                                r"\bno\s+(?:exposure|reference|relation|link|"
                                r"dependence)\s+(?:to|on)\s*$|"
                                r"\bwithout\s+(?:any\s+)?(?:exposure|reference|"
                                r"relation|link|dependence)\s+(?:to|on)\s*$|"
                                r"\b(?:apart\s+from|except|excluding|independent\s+of|"
                                r"other\s+than|orthogonal\s+to|save\s+for|"
                                r"unrelated\s+to)\s*$|"
                                r"不(?:了|到|出|成|清|住|得|能|会|可|"
                                r"由|被)(?:与|和|跟)?\s*$|"
                                r"(?:不是|不为|并非|而非|非|除(?:了)?|"
                                r"排除|剔除|以外|之外|无关|不相关|"
                                r"独立于|正交于)\s*$)",
                                state_prefix,
                            )
                        )
                        if negated or state_negated:
                            negative_link = True
                        else:
                            positive_link = True
                    state_matches = list(re.finditer(state_pattern, prefix))
                    if state_matches:
                        state_match = state_matches[-1]
                        state_to_link = prefix[state_match.end() :]
                        passive_cue = bool(
                            re.search(
                                r"\b(?:is|was|be|been|being|gets?|got)\b|由|被",
                                state_to_link,
                            )
                        )
                        tail_symbols = symbols(tail)
                        passive_formula_marker = bool(
                            formula_markers.intersection(tail_symbols)
                        ) or any(
                            marker in tail for marker in {"信号", "公式", "因子"}
                        )
                        passive_formula_marker = passive_formula_marker or bool(
                            formula_markers.intersection(symbols(state_to_link))
                        ) or any(
                            marker in state_to_link
                            for marker in {"信号", "公式", "因子"}
                        )
                        if passive_cue and passive_formula_marker:
                            if negated:
                                negative_link = True
                            else:
                                positive_link = True
            formula_link_found = formula_link_found or positive_link
            formula_link_negated = formula_link_negated or negative_link
        return formula_link_found and not formula_link_negated

    transient_role_terms = {"temporary", "transitory", "transient", "瞬时", "临时"}

    def has_transient_state_role(state: str) -> bool:
        escaped = re.escape(state)
        positive = False
        negative = False
        for role in transient_role_terms:
            role_pattern = (
                rf"(?<![a-zA-Z]){re.escape(role)}(?![a-zA-Z])"
                if role.isascii()
                else re.escape(role)
            )
            for pattern in (
                rf"(?<![a-zA-Z0-9_]){escaped}(?![a-zA-Z0-9_])"
                rf"(?P<qualifier>[^,.，。;:：]{{0,56}}){role_pattern}",
                rf"{role_pattern}(?:\s+(?:component|state|分量|状态))?"
                rf"(?P<qualifier>[^,.，。;:：]{{0,24}})"
                rf"(?<![a-zA-Z0-9_]){escaped}(?![a-zA-Z0-9_])",
            ):
                for match in re.finditer(pattern, canonical_role_text):
                    qualifier = str(match.group("qualifier") or "")
                    if re.search(
                        r"(?:\bnot\b|\bnon(?:[- ]|$)|\bnever\b|\bno\b|"
                        r"\bwithout\b|不是|不为|并非|不存在|"
                        r"没有|不具备|非|无)",
                        qualifier,
                    ):
                        negative = True
                    else:
                        positive = True
        return positive and not negative

    dynamic_states: set[str] = set()
    for equation in equations:
        left_symbols = set(equation["left_symbols"])
        if len(left_symbols) != 1:
            continue
        state = next(iter(left_symbols))
        rho_symbol = transition_rho_symbol(str(equation["raw_right"]), state)
        transition_rho_symbols = raw_rho_symbols(str(equation["right"]))
        if (
            state not in {"r", "return"}
            and rho_symbol is not None
            and transition_rho_symbols == {rho_symbol}
            and has_time_index(str(equation["left"]), state, future=True)
            and has_time_index(str(equation["raw_right"]), state, future=False)
            and has_stable_rho_constraint(normalized, rho_symbol)
            and is_ar1_transition(equation, state)
            and has_transient_state_role(state)
        ):
            dynamic_states.add(state)

    decomposed_dynamic_states = {
        state
        for state in dynamic_states
        if any(
            state in polynomial_symbols(equation)
            and bool(
                polynomial_symbols(equation)
                - coefficient_terms
                - residual_terms
                - {state}
            )
            and state not in set(equation["left_symbols"])
            and has_formula_state_link(state)
            for equation in equations
        )
    }
    semantic_states.update(decomposed_dynamic_states)

    reduced_form_bound = any(
        equation.get("direct_return_lhs") is True
        and polynomial_contains(equation, (coefficient_terms, semantic_states))
        and has_independent_residual(equation)
        for equation in payoff_equations
    )

    defined_impact_states: set[str] = set()
    for equation in equations:
        left_symbols = set(equation["left_symbols"])
        right_symbols = polynomial_symbols(equation)
        if (
            len(left_symbols) != 1
            or not re.search(r"[+\-*/]", str(equation["right"]))
            or not equation.get("right_polynomial")
        ):
            continue
        state = next(iter(left_symbols))
        if state not in semantic_states:
            continue
        meaningful_right = right_symbols - coefficient_terms - residual_terms
        if meaningful_right or residual_terms.intersection(right_symbols):
            defined_impact_states.add(state)

    structural_state_bound = any(
        polynomial_contains(equation, (coefficient_terms, defined_impact_states))
        and (
            equation.get("direct_return_lhs") is not True
            or has_independent_residual(equation)
        )
        for equation in payoff_equations
    )

    normalized_formula_tokens = {
        canonical_symbol(token) for token in formula_tokens
    }
    persistent_terms = {"persistent", "持久"}
    transient_terms = {"temporary", "transitory", "transient", "瞬时", "临时"}

    def symbol_has_role(symbol: str, role_terms: set[str]) -> bool:
        escaped = re.escape(symbol)
        positive = False
        negative = False
        for role in role_terms:
            role_pattern = (
                rf"(?<![a-zA-Z]){re.escape(role)}(?![a-zA-Z])"
                if role.isascii()
                else re.escape(role)
            )
            for match in re.finditer(
                rf"(?<![a-zA-Z0-9_]){escaped}(?![a-zA-Z0-9_])\s*"
                rf"(?:为|is|denotes|represents)\s*"
                rf"(?P<qualifier>[^,，;]{{0,24}}){role_pattern}",
                canonical_role_text,
            ):
                qualifier = match.group("qualifier")
                if not re.search(
                    r"(?:\bnot\b|\bnon(?:[- ]|$)|\bnever\b|\bno\b|\bwithout\b|"
                    r"不是|不为|并非|不存在|没有|不具备|非|无)",
                    qualifier,
                ):
                    positive = True
                else:
                    negative = True
            if re.search(
                rf"(?<![a-zA-Z0-9_]){escaped}(?![a-zA-Z0-9_])\s*"
                rf"(?:不为|不是|并非|不具备|没有|无)\s*[^,，;]{{0,16}}{role_pattern}",
                canonical_role_text,
            ):
                negative = True
            for match in re.finditer(
                rf"{role_pattern}\s*(?:component|state|分量|状态)?\s*"
                rf"(?<![a-zA-Z0-9_]){escaped}(?![a-zA-Z0-9_])",
                canonical_role_text,
            ):
                prefix = canonical_role_text[max(0, match.start() - 12) : match.start()]
                if not re.search(
                    r"(?:\bnot\s*|\bnon(?:[- ]|$)|\bnever\s*|\bno\s*|"
                    r"\bwithout\s*|不是|不为|并非|不存在|"
                    r"没有|不具备|非|无)\s*$",
                    prefix,
                ):
                    positive = True
                else:
                    negative = True
        return positive and not negative

    formula_decomposition_bound = False
    formula_state_payoff = any(
        polynomial_contains(
            equation,
            (coefficient_terms, {"f", "formula_state"}),
        )
        for equation in payoff_equations
    )
    if formula_state_payoff:
        for equation in equations:
            if not equation.get("right_polynomial"):
                continue
            left_symbols = set(equation["left_symbols"])
            components = (
                polynomial_symbols(equation)
                - coefficient_terms
                - residual_terms
                - normalized_formula_tokens
            )
            persistent_components = {
                symbol for symbol in components if symbol_has_role(symbol, persistent_terms)
            }
            transient_components = {
                symbol for symbol in components if symbol_has_role(symbol, transient_terms)
            }
            if (
                left_symbols.intersection(normalized_formula_tokens)
                and persistent_components
                and transient_components
                and bool(persistent_components - transient_components)
                and bool(transient_components - persistent_components)
            ):
                formula_decomposition_bound = True
                break

    bound_model = (
        reduced_form_bound
        or structural_state_bound
        or formula_decomposition_bound
    )

    def contains_negated_term(terms: set[str]) -> bool:
        for term in terms:
            term_pattern = (
                rf"(?<![a-zA-Z]){re.escape(term)}(?![a-zA-Z])"
                if term.isascii()
                else re.escape(term)
            )
            if term.isascii():
                raw_term_pattern = rf"{re.escape(term)}(?![a-zA-Z])"
                english_negations = (
                    rf"\bnot\s+(?!only\b)(?:(?:a|an|the|any)\s+)?{term_pattern}",
                    rf"\bno\s+(?!arbitrage\b)(?:(?:evidence|sign|presence)\s+of\s+)?"
                    rf"{term_pattern}",
                    rf"\bnever\s+(?:(?:shows|has|exhibits)\s+)?{term_pattern}",
                    rf"\bwithout\s+(?!(?:loss\s+of\s+generality|arbitrage\s+capital)\b)"
                    rf"(?:(?:a|an|the|any)\s+)?{term_pattern}",
                    rf"\bnon[- ]?{raw_term_pattern}",
                    rf"{term_pattern}\s+(?:does|do|did)\s+not\s+"
                    rf"(?:exist|hold|occur|apply)",
                    rf"{term_pattern}\s+(?:is|are)\s+"
                    rf"(?:absent|false|invalid|not\s+present)",
                )
                if any(re.search(pattern, process_lower) for pattern in english_negations):
                    return True
                continue
            if re.search(
                rf"(?:不存在|没有(?:任何)?|并非|不是|不为|不具备|缺乏|无(?!套利))"
                rf"(?:明显|可见|任何)?\s*"
                rf"(?:瞬时|临时|暂时|持久)?\s*{term_pattern}",
                process_lower,
            ):
                return True
            if re.search(
                rf"{term_pattern}\s*(?:并)?(?:不存在|没有(?:出现|发生|成立)?|"
                rf"不成立|缺失|无效)",
                process_lower,
            ):
                return True
        return False

    negatable_mechanism_terms = impact_terms | (
        decomposition_terms - {"persistent", "持久"}
    )
    mechanism_claim_negated = contains_negated_term(negatable_mechanism_terms)

    return (
        bound_model
        and not mechanism_claim_negated
        and any(term in process_lower for term in impact_terms)
        and any(term in process_lower for term in decomposition_terms)
        and any(term in process_lower for term in payoff_terms)
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
    process_text = str(derivation.get("process_or_distribution") or "")
    process = process_text.lower()
    features = formula_features(spec_like or {}, mechanism_analysis or {})
    formula_tokens = {token for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", str(features.get("formula_text") or "").lower()) if len(token) > 2}
    model_hits = [token for token in MODEL_KEYWORDS if token in process]
    formula_hits = [token for token in formula_tokens if token in process]
    compact_stochastic_model = _has_explicit_stochastic_model(process)
    if baseline == "stochastic_process":
        missing_model_assumption = not (
            compact_stochastic_model or _has_stochastic_process_prose(process)
        )
    elif baseline == "transient_impact":
        missing_model_assumption = not _has_explicit_transient_impact_model(
            process_text,
            formula_tokens,
            semantic_context=_text_blob(
                derivation.get("latent_state"),
                derivation.get("formula_as_estimator"),
                derivation.get("profit_payer_derivation"),
                derivation.get("economic_to_math_model_selection"),
            ),
            formula_context=_text_blob(
                derivation.get("formula_as_estimator"),
                payer.get("formula_state_link"),
            ),
        )
    elif baseline == "jump_threshold":
        missing_model_assumption = not _has_explicit_jump_threshold_model(process)
    else:
        missing_model_assumption = not model_hits
    if missing_model_assumption and (
        formula_hits
        or baseline in {"jump_threshold", "stochastic_process", "transient_impact"}
    ):
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
