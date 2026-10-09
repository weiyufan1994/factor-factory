"""Frozen 6b877545 recognizer, synthetic regression only."""
from __future__ import annotations

import ast
import re
from fractions import Fraction
from typing import Any

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
