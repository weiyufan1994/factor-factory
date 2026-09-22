from __future__ import annotations

from .classifier import build_mechanism_math_contract


def valuation_identity_example() -> dict:
    return build_mechanism_math_contract({
        "formula_text": "roe / pb",
        "required_inputs": ["roe", "pb"],
        "operators": ["divide"],
        "thesis": {"economic_mechanism": "profitability relative to valuation"},
    })


def price_volume_microstructure_example() -> dict:
    return build_mechanism_math_contract({
        "formula_text": "correlation(rank(high), rank(volume), 3)",
        "required_inputs": ["high", "volume"],
        "operators": ["correlation", "rank"],
    })
