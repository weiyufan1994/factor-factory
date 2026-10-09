"""Bounded symbolic parsing for declared impact models, not a theorem prover."""
from __future__ import annotations

import ast
import re
from fractions import Fraction
from typing import Any


SYMBOL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*(?:\{[^}]*\})?")


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
    for match in SYMBOL_PATTERN.finditer(value):
        tail = value[match.end() :].lstrip()
        if tail.startswith("("):
            continue
        symbol = canonical_symbol(match.group(0))
        if symbol not in {"i", "j", "k", "n", "t"}:
            result.add(symbol)
    return result


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
    return SYMBOL_PATTERN.sub(
        lambda match: canonical_symbol(match.group(0)),
        value,
    ).replace("^", "**")


ALLOWED_CALLS = frozenset({"abs", "exp", "log", "mean", "mu", "sigma", "sign", "sqrt"})


ALLOWED_BINARY_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)


ALLOWED_UNARY_OPS = (ast.UAdd, ast.USub)


def valid_ast(node: ast.AST) -> bool:
    if isinstance(node, ast.Expression):
        return valid_ast(node.body)
    if isinstance(node, ast.Name):
        return bool(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", node.id))
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, ALLOWED_UNARY_OPS) and valid_ast(node.operand)
    if isinstance(node, ast.BinOp):
        return (
            isinstance(node.op, ALLOWED_BINARY_OPS)
            and valid_ast(node.left)
            and valid_ast(node.right)
        )
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Name)
            and node.func.id in ALLOWED_CALLS
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


COEFFICIENT_TERMS = frozenset({
    "alpha",
    "beta",
    "lambda",
    "lambda_coef",
    "rho",
    "theta",
    "mu",
})


RESIDUAL_TERMS = frozenset({"eps", "epsilon", "eta", "innovation", "residual", "shock"})


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
        residual_count = sum(symbol in RESIDUAL_TERMS for symbol in monomial)
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
        (term,) for term in RESIDUAL_TERMS
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


def parse_equations(normalized: str) -> list[dict[str, Any]]:
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
    return equations


def select_payoff_equations(equations: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
            and bool(COEFFICIENT_TERMS.intersection(right_symbols))
        ):
            equation["direct_return_lhs"] = (
                direct_return_lhs or chinese_direct_return_lhs
            )
            payoff_equations.append(equation)
    return payoff_equations
