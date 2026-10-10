"""Typed expression trees for D0.5 expression search.

Numeric evaluation stays in the existing Formula engine.  This module only
checks the search-side semantic dimensions and renders supported Formula text.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Iterator

from factor_factory.formula.registry import SUPPORTED_OPERATORS

from .induction import InductionScope, SemanticType, Unit


class ASTTypeError(ValueError):
    pass


@dataclass(frozen=True)
class ASTNode:
    kind: str
    value: str | int | float | None = None
    children: tuple["ASTNode", ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"field", "constant", "window", "operator", "hole"}:
            raise ValueError("unsupported AST node kind")
        if self.kind in {"field", "operator", "hole"} and not isinstance(self.value, str):
            raise ValueError(f"{self.kind} requires a string value")
        if self.kind in {"constant", "window"} and (
            type(self.value) not in (int, float) or not math.isfinite(float(self.value))
        ):
            raise ValueError("constant requires a finite number")
        if self.kind != "operator" and self.children:
            raise ValueError("only operator nodes have children")

    @classmethod
    def field(cls, name: str) -> "ASTNode":
        return cls("field", name)

    @classmethod
    def constant(cls, value: int | float) -> "ASTNode":
        return cls("constant", value)

    @classmethod
    def window(cls, value: int) -> "ASTNode":
        if type(value) is not int:
            raise ValueError("window requires an integer")
        return cls("window", value)

    @classmethod
    def operator(cls, name: str, *children: "ASTNode") -> "ASTNode":
        return cls("operator", name, tuple(children))

    @classmethod
    def hole(cls, label: str = "_") -> "ASTNode":
        return cls("hole", label)

    def payload(self) -> dict[str, object]:
        if self.kind == "operator":
            return {"type": "operator", "operator": self.value,
                    "args": [child.payload() for child in self.children]}
        if self.kind == "field":
            return {"type": "field", "name": self.value}
        if self.kind == "constant":
            return {"type": "constant", "value": self.value}
        if self.kind == "window":
            return {"type": "window", "value": self.value}
        return {"type": "hole", "label": self.value}

    @property
    def node_hash(self) -> str:
        raw = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return sha256(raw.encode()).hexdigest()

    @property
    def depth(self) -> int:
        return 1 + (max((child.depth for child in self.children), default=0))

    @property
    def complexity(self) -> int:
        return 1 + sum(child.complexity for child in self.children)

    def expression(self) -> str:
        if self.kind == "field":
            return str(self.value)
        if self.kind in {"constant", "window"}:
            return repr(self.value)
        if self.kind == "hole":
            raise ASTTypeError("incomplete AST contains a typed hole")
        infix = {"plus": "+", "minus": "-", "multiply": "*", "divide": "/"}
        if self.value in infix and len(self.children) == 2:
            return f"({self.children[0].expression()} {infix[str(self.value)]} {self.children[1].expression()})"
        return f"{self.value}({', '.join(child.expression() for child in self.children)})"


@dataclass(frozen=True)
class TypedAST:
    root: ASTNode
    semantic_type: SemanticType


def require_response_family(node: ASTNode, scope: InductionScope) -> None:
    """Prove membership in the induction's response grammar.

    The first supported family is causal affine: fields may be added,
    subtracted, lagged, averaged, and scaled/divided only by field-free scalar
    expressions. Thus equal units alone cannot admit ``x*x`` or ``x/y``.
    """
    productions = set(scope.induction_record.grammar_productions)
    if "field" not in productions or "constant" not in productions:
        raise ASTTypeError("induction grammar lacks terminals")
    degree = _affine_degree(node, scope, productions)
    if degree != 1:
        raise ASTTypeError("expression is outside causal_affine response family")


def _affine_degree(node: ASTNode, scope: InductionScope, productions: set[str]) -> int:
    if node.kind == "field":
        if "field" not in productions:
            raise ASTTypeError("field production outside induction grammar")
        return 1
    if node.kind == "constant":
        if "constant" not in productions:
            raise ASTTypeError("constant production outside induction grammar")
        return 0
    if node.kind == "window":
        return 0
    if node.kind == "hole":
        raise ASTTypeError("incomplete AST contains a typed hole")
    operator = str(node.value)
    if operator not in productions:
        raise ASTTypeError(f"operator outside induction response grammar: {operator}")
    degrees = tuple(_affine_degree(child, scope, productions) for child in node.children)
    if operator in {"plus", "minus"}:
        return max(degrees)
    if operator in {"delay", "mean"}:
        if degrees[0] != 1:
            raise ASTTypeError("trailing transform must preserve a field-dependent response")
        return 1
    if operator == "multiply":
        if sum(value > 0 for value in degrees) > 1:
            raise ASTTypeError("field-by-field product is outside causal_affine response family")
        return max(degrees)
    if operator == "divide":
        if degrees[1] != 0:
            raise ASTTypeError("field-dependent denominator is outside causal_affine response family")
        return degrees[0]
    raise ASTTypeError(f"missing response-family rule for operator: {operator}")


def infer_type(node: ASTNode, scope: InductionScope) -> SemanticType:
    if node.depth > scope.max_depth:
        raise ASTTypeError("AST exceeds induction max_depth")
    return _infer(node, scope)


def _infer(node: ASTNode, scope: InductionScope) -> SemanticType:
    if node.kind == "hole":
        raise ASTTypeError("incomplete AST contains a typed hole")
    if node.kind == "field":
        try:
            return scope.field_map()[str(node.value)]
        except KeyError as exc:
            raise ASTTypeError(f"field outside induction scope: {node.value}") from exc
    if node.kind == "constant":
        if float(node.value) not in {float(value) for value in scope.allowed_constants}:
            raise ASTTypeError(f"constant outside induction scope: {node.value}")
        return SemanticType("scalar", "numeric", Unit.dimensionless(), "atemporal", "none", "constant")
    if node.kind == "window":
        if type(node.value) is not int or node.value not in scope.allowed_windows:
            raise ASTTypeError(f"window outside induction scope: {node.value}")
        return SemanticType("scalar", "numeric", Unit.dimensionless(), "atemporal", "none", "window_parameter")
    operator = str(node.value)
    if operator not in scope.allowed_operators:
        raise ASTTypeError(f"operator outside induction scope: {operator}")
    registered = SUPPORTED_OPERATORS.get(operator)
    if not registered or not registered.get("supports_pandas"):
        raise ASTTypeError(f"operator lacks existing pandas support: {operator}")
    if len(node.children) != registered["arity"]:
        raise ASTTypeError(f"operator arity mismatch: {operator}")
    args = tuple(_infer(child, scope) for child in node.children)
    if operator in {"plus", "minus"}:
        return _additive(args[0], args[1], operator)
    if operator in {"multiply", "divide"}:
        if operator == "divide" and _constant_expression_value(node.children[1]) == 0.0:
            raise ASTTypeError("known zero denominator")
        return _multiplicative(args[0], args[1], divide=operator == "divide")
    if operator in {"delay", "mean"}:
        series, window = args
        if series.shape != "panel" or series.value_type != "numeric" or series.grouping != "instrument_ts":
            raise ASTTypeError(f"{operator} requires numeric instrument time series")
        literal = node.children[1]
        if literal.kind != "window" or type(literal.value) is not int or literal.value not in scope.allowed_windows:
            raise ASTTypeError(f"{operator} requires an allowed integer window")
        if window.shape != "scalar" or window.unit != Unit.dimensionless():
            raise ASTTypeError(f"{operator} window must be dimensionless scalar")
        return series
    raise ASTTypeError(f"missing search type rule for operator: {operator}")


def _constant_expression_value(node: ASTNode) -> float | None:
    if node.kind == "constant":
        return float(node.value)
    if node.kind != "operator" or node.value not in {"plus", "minus", "multiply", "divide"}:
        return None
    values = tuple(_constant_expression_value(child) for child in node.children)
    if any(value is None for value in values):
        return None
    left, right = values
    if node.value == "plus":
        return left + right
    if node.value == "minus":
        return left - right
    if node.value == "multiply":
        return left * right
    if right == 0.0:
        raise ASTTypeError("known zero denominator")
    return left / right


def _additive(left: SemanticType, right: SemanticType, operator: str) -> SemanticType:
    if left.value_type != "numeric" or right.value_type != "numeric" or left.unit != right.unit:
        raise ASTTypeError(f"{operator} requires equal numeric units")
    if left == right:
        return left
    scalar, panel = (left, right) if left.shape == "scalar" else (right, left)
    if scalar.shape == "scalar" and panel.shape == "panel" and scalar.information_semantics == "constant":
        if scalar.unit == Unit.dimensionless() and panel.unit == Unit.dimensionless():
            return panel
    raise ASTTypeError(f"{operator} requires compatible shape/clock/grouping/information semantics")


def _multiplicative(left: SemanticType, right: SemanticType, *, divide: bool) -> SemanticType:
    if left.value_type != "numeric" or right.value_type != "numeric":
        raise ASTTypeError("multiplication/division requires numeric operands")
    if divide and right.shape == "panel" and left.shape == "scalar":
        raise ASTTypeError("scalar divided by panel changes the supported response object")
    if left.shape == "panel" and right.shape == "panel":
        if (left.clock, left.grouping, left.information_semantics) != (
            right.clock, right.grouping, right.information_semantics
        ):
            raise ASTTypeError("panel operands require equal clock/grouping/information semantics")
        basis = left
    elif left.shape == "panel" and right.shape == "scalar" and right.information_semantics == "constant":
        basis = left
    elif right.shape == "panel" and left.shape == "scalar" and left.information_semantics == "constant" and not divide:
        basis = right
    elif left.shape == right.shape == "scalar":
        basis = left
    else:
        raise ASTTypeError("unsupported scalar/panel multiplication or division")
    unit = left.unit.divide(right.unit) if divide else left.unit.multiply(right.unit)
    return SemanticType(basis.shape, "numeric", unit, basis.clock, basis.grouping, basis.information_semantics)


def iter_paths(node: ASTNode, path: tuple[int, ...] = ()) -> Iterator[tuple[tuple[int, ...], ASTNode]]:
    yield path, node
    for index, child in enumerate(node.children):
        yield from iter_paths(child, path + (index,))


def replace_path(node: ASTNode, path: tuple[int, ...], replacement: ASTNode) -> ASTNode:
    if not path:
        return replacement
    if node.kind != "operator" or path[0] >= len(node.children):
        raise ValueError("invalid AST path")
    children = list(node.children)
    children[path[0]] = replace_path(children[path[0]], path[1:], replacement)
    return ASTNode.operator(str(node.value), *children)
