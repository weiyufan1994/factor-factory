"""Conservative information-time hints, not a proof of executable safety.

Canonical expressions/operators and explanatory prose have different roles.
Mentioning future data in prose (including a prohibition) requires review; it
cannot establish either a leak or its absence. Actual implementation/data timing
and mutation evidence remain the independent research reviewer's responsibility.
"""
from __future__ import annotations

import ast
import math
import re
from typing import Any


ILLEGAL = "illegal_potential_forward_reference"
UNCONFIRMED = "requires_researcher_confirmation_no_forward_leakage"
LAG_DOCUMENTED = "explicit_lag_or_delay_documented"
_FORWARD = re.compile(r"(?:\bfuture\b|\blead\b|\blookahead\b|forward\s+returns?|未来收益)", re.I)
_FORWARD_IDENTIFIER = re.compile(r"\b\w*(?:future|lookahead|forward_return)\w*\b|\b(?:ts_)?lead\b", re.I)
_LAG_NAMES = {'shift', 'lag', 'delay', 'ts_delay', 'ts_shift', 'ref'}
_LAG = re.compile(r"\b(?:shift|lag|delay|ts_delay|ts_shift|ref)\s*\(", re.I)


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(x) for x in (value if isinstance(value, (tuple, list)) else [value])]


def _number(node: ast.AST, depth: int = 0) -> float | int | None:
    if depth > 64:
        return None
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value if type(node.value) is int or math.isfinite(node.value) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _number(node.operand, depth + 1)
        return None if value is None else (-value if isinstance(node.op, ast.USub) else value)
    return None


def _lag_hint(text: str) -> str:
    """Inspect call syntax only; no imports/evaluation or dynamic period inference.

The parser handles nested arguments, method calls and literal keyword periods.
Unknown/dynamic periods or non-Python notation stay unconfirmed, never lag-safe.
Dollar-prefixed formula fields and the mathematical minus are normalized only
for this nonexecuting syntax inspection; source bytes are never changed.
    """
    if not _LAG.search(text):
        return 'absent'
    if len(text) > 65536:
        return 'unknown'
    try:
        source = re.sub(r'\$([A-Za-z_]\w*)', r'FF_FIELD_\1', text).replace('−', '-')
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return 'unknown'
    hints = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        name = call.func.id if isinstance(call.func, ast.Name) else (
            call.func.attr if isinstance(call.func, ast.Attribute) else '')
        if name.lower() not in _LAG_NAMES:
            continue
        offsets = [k.value for k in call.keywords if k.arg in {'periods', 'n', 'd', 'window'}]
        if not offsets:
            if isinstance(call.func, ast.Attribute):
                # A method's first argument is periods; a namespace function can
                # use the canonical (values, periods) convention. Do not miss a
                # literal negative under either interpretation.
                offsets = call.args[:2]
            elif len(call.args) >= 2:
                offsets = [call.args[1]]
            else:
                offsets = call.args
        values = [_number(node) for node in offsets]
        if any(value is not None and value < 0 for value in values):
            return 'negative'
        hints.append('documented' if values and all(v is not None and v >= 0 for v in values) else 'unknown')
    return 'unknown' if not hints or 'unknown' in hints else 'documented'


def classify_information_set(canonical: dict) -> str:
    """Produce the existing three-state hint without adjudicating natural language.

    Forward-marked canonical formula fields/operators and explicit negative
    shifts remain blocking. Narrative text is not executable evidence. A lag
    hint is only documentation; none of these outputs certifies code/PIT safety.
    """
    expressions = [str(canonical.get("formula_text") or ""), *_items(canonical.get("operators"))]
    narrative = [text for key in ("preprocessing", "time_series_steps", "cross_sectional_steps")
                 for text in _items(canonical.get(key))]
    if any(_FORWARD.search(text) or _FORWARD_IDENTIFIER.search(text) or _lag_hint(text) == 'negative'
           for text in expressions):
        return ILLEGAL
    # Do not let a lag elsewhere override unresolved narrative timing claims.
    if any(_FORWARD.search(text) or _FORWARD_IDENTIFIER.search(text) or _LAG.search(text)
           for text in narrative):
        return UNCONFIRMED
    lag_hints = [_lag_hint(text) for text in expressions]
    if 'unknown' in lag_hints:
        return UNCONFIRMED
    if 'documented' in lag_hints:
        return LAG_DOCUMENTED
    return UNCONFIRMED


def legacy_information_set(canonical: dict) -> str:
    """Exact old derivation, only to identify a maintenance repair's parent."""
    text = " ".join([str(canonical.get("formula_text") or ""), *[
        item for key in ("operators", "preprocessing", "time_series_steps", "cross_sectional_steps")
        for item in _items(canonical.get(key))
    ]]).lower()
    if any(token in text for token in ("future", "lead", "lookahead", "forward return", "未来收益")):
        return ILLEGAL
    if any(token in text for token in ("lag", "shift", "delay", "ts_delay")):
        return LAG_DOCUMENTED
    return UNCONFIRMED
