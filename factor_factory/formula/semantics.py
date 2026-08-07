from __future__ import annotations

import hashlib
import json
from typing import Any

from .registry import operator_meta


def _literal_positive_integer(node: dict[str, Any]) -> int | None:
    if not isinstance(node, dict) or node.get("type") != "constant":
        return None
    value = node.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if float(value) != int(value) or int(value) <= 0:
        return None
    return int(value)


def operator_lookback(node: dict[str, Any]) -> int | None:
    if not isinstance(node, dict) or node.get("type") != "operator":
        return None
    try:
        metadata = operator_meta(str(node.get("operator") or ""))
    except KeyError:
        return None
    positions = list(metadata.get("lookback_arg_positions") or [])
    if metadata.get("requires_window") and not positions:
        positions = [len(node.get("args") or []) - 1]
    values = [
        _literal_positive_integer((node.get("args") or [])[position])
        for position in positions
        if 0 <= position < len(node.get("args") or [])
    ]
    valid = [value for value in values if value is not None]
    return max(valid) if valid else None


def max_formula_ir_lookback(formula_ir: dict[str, Any] | None) -> int:
    if not isinstance(formula_ir, dict):
        return 0
    lookbacks: list[int] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        lookback = operator_lookback(node)
        if lookback is not None:
            lookbacks.append(lookback)
        for child in node.get("args") or []:
            visit(child)

    visit(formula_ir.get("root"))
    return max(lookbacks) if lookbacks else 0


def requires_cross_sectional_sample(formula_ir: dict[str, Any] | None) -> bool:
    if not isinstance(formula_ir, dict):
        return False

    def visit(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        if node.get("type") == "operator":
            try:
                if operator_meta(str(node.get("operator") or "")).get("category") == "cross_sectional":
                    return True
            except KeyError:
                pass
        return any(visit(child) for child in node.get("args") or [])

    return visit(formula_ir.get("root"))


def operator_semantic_contract(operator_names: list[str] | set[str]) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for name in sorted(set(str(item) for item in operator_names)):
        metadata = operator_meta(name)
        version = metadata.get("semantic_contract_version")
        if not version:
            continue
        contracts[name] = {
            "semantic_contract_version": version,
            "definition": metadata.get("semantic_definition"),
            "lookback_arg_positions": list(metadata.get("lookback_arg_positions") or []),
            "category": metadata.get("category"),
        }
    return contracts


def operator_semantic_hash(operator_names: list[str] | set[str]) -> str:
    payload = operator_semantic_contract(operator_names)
    if not payload:
        return ""
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
