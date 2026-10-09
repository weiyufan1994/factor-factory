"""Recognize explicit transient-impact declarations without scoring returns.

Symbol links, dynamics and polarity are separate from expression parsing.
Recognition does not establish empirical validity or economic identification.
"""
from __future__ import annotations

import re
from typing import Any

from .transient_impact_math import (
    COEFFICIENT_TERMS,
    RESIDUAL_TERMS,
    SYMBOL_PATTERN,
    canonical_symbol,
    has_independent_residual,
    has_stable_rho_constraint,
    has_time_index,
    is_ar1_transition,
    parse_equations,
    polynomial_contains,
    polynomial_symbols,
    raw_rho_symbols,
    select_payoff_equations,
    symbols,
    transition_rho_symbol,
)


IMPACT_TERMS = frozenset({
    "impact",
    "imbalance",
    "order flow",
    "temporary",
    "transient",
    "冲击",
    "不平衡",
    "订单流",
    "超调",
})


DECOMPOSITION_TERMS = frozenset({
    "decay",
    "persistent",
    "temporary",
    "transitory",
    "持久",
    "瞬时",
    "临时",
    "衰减",
})


PAYOFF_TERMS = frozenset({
    "e[",
    "return",
    "r_",
    "收益",
})


TRANSLATION = str.maketrans(
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


FORMULA_MARKERS = frozenset({
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
})


FORMULA_LINK_TERMS = frozenset({
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
})


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


def has_formula_state_link(state: str, *, formula_role_text: str) -> bool:
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
            FORMULA_MARKERS.intersection(clause_symbols)
        ) or any(marker in clause for marker in {"信号", "公式", "因子"})
        if not has_formula_marker:
            continue
        positive_link = False
        negative_link = False
        for term in sorted(FORMULA_LINK_TERMS, key=len, reverse=True):
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
                        FORMULA_MARKERS.intersection(tail_symbols)
                    ) or any(
                        marker in tail for marker in {"信号", "公式", "因子"}
                    )
                    passive_formula_marker = passive_formula_marker or bool(
                        FORMULA_MARKERS.intersection(symbols(state_to_link))
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


TRANSIENT_ROLE_TERMS = frozenset({"temporary", "transitory", "transient", "瞬时", "临时"})


def has_transient_state_role(state: str, *, canonical_role_text: str) -> bool:
    escaped = re.escape(state)
    positive = False
    negative = False
    for role in TRANSIENT_ROLE_TERMS:
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


PERSISTENT_TERMS = frozenset({"persistent", "持久"})


TRANSIENT_TERMS = frozenset({"temporary", "transitory", "transient", "瞬时", "临时"})


def symbol_has_role(symbol: str, role_terms: set[str], *, canonical_role_text: str) -> bool:
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


def contains_negated_term(terms: set[str], *, process_lower: str) -> bool:
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


def has_explicit_transient_impact_model(
    process: str,
    formula_tokens: set[str],
    semantic_context: str = "",
    formula_context: str = "",
) -> bool:
    """Recognize bounded structural/reduced-form transient-impact models."""
    normalized = process.translate(TRANSLATION)
    semantic_text = f"{process}; {semantic_context}".translate(TRANSLATION)
    process_lower = semantic_text.lower()

    canonical_role_text = SYMBOL_PATTERN.sub(
        lambda match: canonical_symbol(match.group(0)),
        semantic_text,
    ).lower()

    equations = parse_equations(normalized)

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
    payoff_equations = select_payoff_equations(equations)

    formula_role_text = SYMBOL_PATTERN.sub(
        lambda match: canonical_symbol(match.group(0)),
        formula_context.translate(TRANSLATION),
    ).lower()

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
            and has_transient_state_role(state, canonical_role_text=canonical_role_text)
        ):
            dynamic_states.add(state)

    decomposed_dynamic_states = {
        state
        for state in dynamic_states
        if any(
            state in polynomial_symbols(equation)
            and bool(
                polynomial_symbols(equation)
                - COEFFICIENT_TERMS
                - RESIDUAL_TERMS
                - {state}
            )
            and state not in set(equation["left_symbols"])
            and has_formula_state_link(state, formula_role_text=formula_role_text)
            for equation in equations
        )
    }
    semantic_states.update(decomposed_dynamic_states)

    reduced_form_bound = any(
        equation.get("direct_return_lhs") is True
        and polynomial_contains(equation, (COEFFICIENT_TERMS, semantic_states))
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
        meaningful_right = right_symbols - COEFFICIENT_TERMS - RESIDUAL_TERMS
        if meaningful_right or RESIDUAL_TERMS.intersection(right_symbols):
            defined_impact_states.add(state)

    structural_state_bound = any(
        polynomial_contains(equation, (COEFFICIENT_TERMS, defined_impact_states))
        and (
            equation.get("direct_return_lhs") is not True
            or has_independent_residual(equation)
        )
        for equation in payoff_equations
    )

    normalized_formula_tokens = {
        canonical_symbol(token) for token in formula_tokens
    }

    formula_decomposition_bound = False
    formula_state_payoff = any(
        polynomial_contains(
            equation,
            (COEFFICIENT_TERMS, {"f", "formula_state"}),
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
                - COEFFICIENT_TERMS
                - RESIDUAL_TERMS
                - normalized_formula_tokens
            )
            persistent_components = {
                symbol for symbol in components if symbol_has_role(symbol, PERSISTENT_TERMS, canonical_role_text=canonical_role_text)
            }
            transient_components = {
                symbol for symbol in components if symbol_has_role(symbol, TRANSIENT_TERMS, canonical_role_text=canonical_role_text)
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

    negatable_mechanism_terms = IMPACT_TERMS | (
        DECOMPOSITION_TERMS - {"persistent", "持久"}
    )
    mechanism_claim_negated = contains_negated_term(negatable_mechanism_terms, process_lower=process_lower)

    return (
        bound_model
        and not mechanism_claim_negated
        and any(term in process_lower for term in IMPACT_TERMS)
        and any(term in process_lower for term in DECOMPOSITION_TERMS)
        and any(term in process_lower for term in PAYOFF_TERMS)
    )
