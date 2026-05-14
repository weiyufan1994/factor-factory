from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FORMULA_IR_VERSION = 'factorforge_formula_ir_v1'


@dataclass(frozen=True)
class FormulaNode:
    type: str
    value: Any


@dataclass(frozen=True)
class FormulaField:
    name: str
    resolved_field: str | None = None


@dataclass(frozen=True)
class FormulaLiteral:
    value: int | float


@dataclass(frozen=True)
class FormulaParameter:
    name: str
    value: Any


@dataclass(frozen=True)
class FormulaIR:
    formula_text: str
    root: dict[str, Any]
    formula_hash: str
    required_fields: list[str]
    operator_set: list[str]
    field_aliases: dict[str, list[str]]
    resolved_fields: dict[str, str]
    parse_status: str
    parse_errors: list[str]
