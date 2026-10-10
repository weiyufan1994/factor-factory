"""Compile an induction-bound AST through the existing FormulaFactor path."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from factor_factory.factors import FormulaFactor
from factor_factory.formula.parser import parse_formula

from .generator import ExpressionCandidate
from .induction import InductionScope
from .typed_ast import infer_type, require_response_family


@dataclass(frozen=True)
class CompiledExpression:
    candidate: ExpressionCandidate
    expression: str
    formula_ir: dict
    factor: FormulaFactor


def compile_candidate(
    candidate: ExpressionCandidate,
    scope: InductionScope,
    *,
    available_columns: list[str],
    factor_name: str | None = None,
) -> CompiledExpression:
    from .generator import _require_candidate

    _require_candidate(candidate, scope)
    if infer_type(candidate.root, scope) != scope.output_type:
        raise ValueError("candidate output differs from induction target")
    require_response_family(candidate.root, scope)
    expression = candidate.expression
    formula_ir = parse_formula(expression, available_columns=available_columns, raise_on_error=True)
    if formula_ir["parse_status"] != "success":
        raise ValueError("existing Formula parser rejected generated expression")
    escaped = set(formula_ir["operator_set"]) - set(scope.allowed_operators)
    if escaped == {"negate"} and _negation_is_only_negative_literal(formula_ir["root"]):
        escaped.clear()
    if escaped:
        raise ValueError("compiled expression escaped induction operator scope")
    factor = FormulaFactor(expression, name=factor_name or candidate.candidate_id)
    return CompiledExpression(candidate, expression, formula_ir, factor)


def compute_candidate(
    compiled: CompiledExpression,
    inputs: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    return compiled.factor(inputs)


def _negation_is_only_negative_literal(node: dict) -> bool:
    """Accept parser normalization of ``-1.0`` while rejecting free negate."""
    if node.get("type") != "operator":
        return True
    children = node.get("args") or []
    if node.get("operator") == "negate":
        if len(children) != 1 or children[0].get("type") != "constant":
            return False
    return all(_negation_is_only_negative_literal(child) for child in children)
