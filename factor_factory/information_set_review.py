"""Conservative information-time hints, not a proof of executable safety.

Canonical expressions/operators and explanatory prose have different roles.
Mentioning future data in prose (including a prohibition) requires review; it
cannot establish either a leak or its absence. Actual implementation/data timing
and mutation evidence remain the independent research reviewer's responsibility.
"""
from __future__ import annotations

import re
from typing import Any


ILLEGAL = "illegal_potential_forward_reference"
UNCONFIRMED = "requires_researcher_confirmation_no_forward_leakage"
LAG_DOCUMENTED = "explicit_lag_or_delay_documented"
_FORWARD = re.compile(r"(?:\bfuture\b|\blead\b|\blookahead\b|forward\s+returns?|未来收益)", re.I)
_FORWARD_IDENTIFIER = re.compile(r"\b\w*(?:future|lookahead|forward_return)\w*\b|\b(?:ts_)?lead\b", re.I)
_NEGATIVE_PERIOD = re.compile(
    r"\b(?:shift|lag|delay|ts_delay|ts_shift|ref)\s*\("
    r"(?:[^();]*?,\s*)?(?:(?:periods|n|d|window)\s*=\s*)?-\s*(?:[1-9]\d*|0\.\d*[1-9])",
    re.I,
)
_LAG = re.compile(r"\b(?:lag|shift|delay|ts_delay)\s*\(", re.I)


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(x) for x in (value if isinstance(value, (tuple, list)) else [value])]


def classify_information_set(canonical: dict) -> str:
    """Produce the existing three-state hint without adjudicating natural language.

Forward-marked canonical formula fields/operators and explicit negative shifts
remain blocking. Narrative text is never treated as executable evidence. A lag
mention is only documentation; none of these outputs certifies code/PIT safety.
    """
    expressions = [str(canonical.get("formula_text") or ""), *_items(canonical.get("operators"))]
    narrative = [text for key in ("preprocessing", "time_series_steps", "cross_sectional_steps")
                 for text in _items(canonical.get(key))]
    if any(_FORWARD.search(text) or _FORWARD_IDENTIFIER.search(text) or _NEGATIVE_PERIOD.search(text)
           for text in expressions):
        return ILLEGAL
    # Do not let a lag elsewhere override unresolved narrative timing claims.
    if any(_FORWARD.search(text) or _FORWARD_IDENTIFIER.search(text) or _NEGATIVE_PERIOD.search(text)
           for text in narrative):
        return UNCONFIRMED
    if any(_LAG.search(text) for text in [*expressions, *narrative]):
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
