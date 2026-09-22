"""Additive long-table factor operators; see extension_registry for semantics.

Source inspiration: quantzone-因子计算引擎手册.md supplied on 2026-09-20.
No SDK dependency or remote access. Windows count existing rows per security;
the caller owns the complete input grid and PIT-safe group classifications.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _series(value, frame: pd.DataFrame) -> pd.Series:
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors="coerce").astype("float64")
    return pd.Series(value, index=frame.index, dtype="float64")


def _finite(values: pd.Series) -> pd.Series:
    return values.where(np.isfinite(values))


def minimum(a, b, *, frame):
    return np.minimum(_series(a, frame), _series(b, frame))


def maximum(a, b, *, frame):
    return np.maximum(_series(a, frame), _series(b, frame))


def sqrt_nonnegative(x, *, frame):
    values = _series(x, frame)
    return np.sqrt(values.where(values >= 0))


def clip(x, lo, hi, *, frame):
    return _series(x, frame).clip(lower=float(lo), upper=float(hi))


def lt(a, b, *, frame):
    return (_series(a, frame) < _series(b, frame)).astype("float64")


def where(condition, a, b, *, frame):
    condition = _series(condition, frame)
    mask = condition.notna() & condition.ne(0)
    return _series(a, frame).where(mask, _series(b, frame))


def cs_demean(x, *, frame):
    values = _finite(_series(x, frame))
    return values - values.groupby(frame["trade_date"], sort=False).transform("mean")


def cs_winsor_quantile(x, lo, hi, *, frame):
    values = _series(x, frame)
    grouped = _finite(values).groupby(frame["trade_date"], sort=False)
    lower = grouped.transform("quantile", q=float(lo), interpolation="linear")
    upper = grouped.transform("quantile", q=float(hi), interpolation="linear")
    return values.clip(lower=lower, upper=upper)


def cs_winsor_mad(x, k, *, frame):
    values = _series(x, frame)
    finite = _finite(values)
    dates = frame["trade_date"]
    center = finite.groupby(dates, sort=False).transform("median")
    mad = (finite - center).abs().groupby(dates, sort=False).transform("median")
    lower = (center - float(k) * mad).where(mad > 0)
    upper = (center + float(k) * mad).where(mad > 0)
    return values.clip(lower=lower, upper=upper)


def cs_winsor_std(x, k, *, frame):
    values = _series(x, frame)
    grouped = _finite(values).groupby(frame["trade_date"], sort=False)
    center = grouped.transform("mean")
    std = grouped.transform("std", ddof=0)
    valid = (std > 0) & (grouped.transform("count") >= 2)
    return values.clip(lower=(center - float(k) * std).where(valid), upper=(center + float(k) * std).where(valid))


def cs_fillmean(x, *, frame):
    values = _series(x, frame)
    donor = _finite(values).groupby(frame["trade_date"], sort=False).transform("mean")
    return values.fillna(donor)


def _group_keys(group, frame):
    return [frame["trade_date"], _finite(_series(group, frame))]


def cs_rank_group(x, group, *, frame):
    return _series(x, frame).groupby(_group_keys(group, frame), sort=False).rank(method="average", pct=True)


def ind_demean(x, group, *, frame):
    values = _finite(_series(x, frame))
    grouped = values.groupby(_group_keys(group, frame), sort=False)
    return (values - grouped.transform("mean")).where(grouped.transform("count") >= 2)


def ind_fillmean(x, group, *, frame):
    values = _series(x, frame)
    donor = _finite(values).groupby(_group_keys(group, frame), sort=False).transform("mean")
    return values.fillna(donor)


def ts_ffill(x, n, *, frame):
    values = _series(x, frame)
    if int(n) == 0:
        return values.copy()
    donor = _finite(values).groupby(frame["ts_code"], sort=False).ffill(limit=int(n))
    return values.fillna(donor)


def _rolling_arrays(x, n, frame, reducer):
    window = int(n)
    values = _series(x, frame).to_numpy(dtype="float64")
    result = np.full(len(frame), np.nan, dtype="float64")
    # One loop per security; NumPy performs each window reduction. No Python
    # row loop and no materialized N-by-window copy are needed.
    for raw_positions in frame.groupby("ts_code", sort=False, observed=True).indices.values():
        positions = np.asarray(raw_positions, dtype=np.intp)
        if len(positions) < window:
            continue
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            reduced = reducer(values[positions], window)
        result[positions[window - 1:]] = np.where(np.isfinite(reduced), reduced, np.nan)
    return pd.Series(result, index=frame.index)


def ts_decay_linear(x, n, *, frame):
    def reduce(values, window):
        finite = np.isfinite(values)
        weights = np.arange(window, 0, -1, dtype="float64")
        numerator = np.convolve(np.where(finite, values, 0.0), weights, mode="valid")
        denominator = np.convolve(finite.astype("float64"), weights, mode="valid")
        enough = denominator >= 0.5 * weights.sum()
        return np.divide(numerator, denominator, out=np.full_like(numerator, np.nan), where=enough)
    return _rolling_arrays(x, n, frame, reduce)


def ts_product(x, n, *, frame):
    def reduce(values, window):
        clean = np.where(np.isfinite(values), values, np.nan)
        windows = np.lib.stride_tricks.sliding_window_view(clean, window)
        return windows.prod(axis=1)
    return _rolling_arrays(x, n, frame, reduce)


EXTENSION_FUNCTIONS = {
    function.__name__: function for function in (
        minimum, maximum, sqrt_nonnegative, clip, lt, where,
        cs_demean, cs_winsor_quantile, cs_winsor_mad, cs_winsor_std, cs_fillmean,
        cs_rank_group, ind_demean, ind_fillmean, ts_decay_linear, ts_product, ts_ffill,
    )
}
