"""Versioned, additive operators inspired by the QuantZone public manual.

These are Factor Forge long-table semantics, not a QuantZone compatibility layer.
Keep this metadata module free of numerical-library imports.
"""
from __future__ import annotations

import math


def _entry(name: str, arity: int, category: str, definition: str, **extra) -> dict:
    return {
        "name": name, "aliases": [name], "arity": arity, "category": category,
        "lookahead_safe": True, "requires_window": category == "time_series",
        "supports_pandas": True, "supports_qlib": False, "qlib_name": None,
        "semantic_contract_version": f"factorforge_{name}_v1",
        "semantic_definition": definition, **extra,
    }


EXTENSION_OPERATORS = {
    "minimum": _entry("minimum", 2, "elementwise", "Elementwise minimum; NaN propagates. Existing min remains a rolling operator."),
    "maximum": _entry("maximum", 2, "elementwise", "Elementwise maximum; NaN propagates. Existing max remains a rolling operator."),
    "sqrt_nonnegative": _entry("sqrt_nonnegative", 1, "elementwise", "Square root for x >= 0; negative values and NaN return NaN."),
    "clip": _entry("clip", 3, "elementwise", "Clip to finite literal lower/upper bounds, lower <= upper; NaN stays NaN."),
    "lt": _entry("lt", 2, "elementwise", "Elementwise a < b as 0/1; a NaN in either operand returns 0."),
    "where": _entry("where", 3, "elementwise", "Select a when condition is nonzero and not NaN, otherwise b; eager evaluation on the shared input grid."),
    "cs_demean": _entry("cs_demean", 1, "cross_sectional", "Subtract each date's finite-observation mean; nonfinite inputs become NaN."),
    "cs_winsor_quantile": _entry("cs_winsor_quantile", 3, "cross_sectional", "Per-date linear-interpolated quantile clipping estimated from finite observations; 0 <= lo < hi <= 1; NaN stays NaN, infinities clip when bounds exist."),
    "cs_winsor_mad": _entry("cs_winsor_mad", 2, "cross_sectional", "Per-date median +/- k * unscaled MAD of finite observations, k > 0; zero scale leaves original values unchanged."),
    "cs_winsor_std": _entry("cs_winsor_std", 2, "cross_sectional", "Per-date finite mean +/- k * population std, k > 0; zero scale or fewer than two observations leaves original values unchanged."),
    "cs_fillmean": _entry("cs_fillmean", 1, "cross_sectional", "Fill NaN from same-date finite mean; preserve infinities and leave NaN if no finite donor."),
    "cs_rank_group": _entry("cs_rank_group", 2, "cross_sectional", "Same-date, same-finite-numeric-group average percentile rank; x infinities participate, x NaN and invalid groups return NaN."),
    "ind_demean": _entry("ind_demean", 2, "cross_sectional", "Same-date finite-numeric-group demean using finite x; groups with fewer than two finite x return NaN; no global breadth cutoff."),
    "ind_fillmean": _entry("ind_fillmean", 2, "cross_sectional", "Fill x NaN using same-date, same-finite-numeric-group finite donors; preserve original nonmissing values; invalid groups do not fill."),
    "ts_decay_linear": _entry("ts_decay_linear", 2, "time_series", "Per-security trailing n observed rows, oldest-to-newest weights 1..n; full n-row warmup, finite weight >= half total required, renormalize valid weights; nonfinite numerical result becomes NaN.", lookback_arg_positions=[1]),
    "ts_product": _entry("ts_product", 2, "time_series", "Per-security product over n observed rows; all n values must be finite; full warmup; zero remains zero; overflow becomes NaN.", lookback_arg_positions=[1]),
    "ts_ffill": _entry("ts_ffill", 2, "time_series", "Fill NaN from past finite observations at most n observed rows old within a security; preserve infinities; n=0 is identity; no future or cross-security donor.", literal_integer_args=[1], minimum_integer_values={1: 0}, lookback_arg_positions=[1]),
}


def extension_output_unit(name: str, child_units: list[str]) -> str:
    """Share Step3 producer/validator annotations for the additive operators."""
    if name == "lt":
        return "boolean_indicator"
    if name == "cs_rank_group":
        return "rank_score"
    if name == "sqrt_nonnegative":
        return "source_unit_sqrt"
    if name == "ts_product":
        return "source_unit_product"
    if name in {"minimum", "maximum", "where"}:
        values = child_units[1:] if name == "where" else child_units
        units = set(values)
        return next(iter(units)) if len(units) == 1 else "numeric"
    return child_units[0] if child_units else "numeric"


def _literal_number(node: dict) -> float:
    if node.get("type") == "constant":
        value = node.get("value")
        if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    if node.get("type") == "operator" and node.get("operator") == "negate" and len(node.get("args", [])) == 1:
        return -_literal_number(node["args"][0])
    raise ValueError("BLOCK_OPERATOR_PARAMETER_NOT_FINITE_LITERAL")


def validate_extension_parameters(name: str, args: list[dict]) -> None:
    if name == "clip":
        lo, hi = _literal_number(args[1]), _literal_number(args[2])
        if lo > hi:
            raise ValueError("BLOCK_CLIP_BOUNDS_ORDER")
    elif name == "cs_winsor_quantile":
        lo, hi = _literal_number(args[1]), _literal_number(args[2])
        if not 0 <= lo < hi <= 1:
            raise ValueError("BLOCK_WINSOR_QUANTILE_BOUNDS")
    elif name in {"cs_winsor_mad", "cs_winsor_std"}:
        if _literal_number(args[1]) <= 0:
            raise ValueError("BLOCK_WINSOR_MULTIPLIER_NONPOSITIVE")
