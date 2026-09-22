"""Pure numerical PF/VV source-reconstruction baseline.

This module has no data access, persistence, execution, neutralization, or
backtest logic.  It implements only the conventions frozen in
``pfvv_reconstruction.json`` beside this module.  Inputs are one
stock-day wide matrix at a time; rolling functions consume date-by-ticker
panels.  Structural errors raise ``ValueError``; invalid observations remain
``NaN`` and are never converted to zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from numbers import Integral

import numpy as np
import pandas as pd


def _require_int(value: int, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _require_ordered_unique(index: pd.Index, name: str) -> None:
    if index.has_duplicates:
        raise ValueError(f"{name} contains duplicate labels")
    if index.hasnans:
        raise ValueError(f"{name} contains missing labels")
    if not index.is_monotonic_increasing:
        raise ValueError(f"{name} must be increasing")


def _expected_minute_clock(first: pd.Timestamp) -> pd.DatetimeIndex:
    day = first.normalize()
    morning = pd.date_range(day + pd.Timedelta(hours=9, minutes=31), periods=120, freq="min")
    afternoon = pd.date_range(day + pd.Timedelta(hours=13, minutes=1), periods=120, freq="min")
    return morning.append(afternoon)


def _validate_slot_index(index: pd.Index, expected_slots: int) -> None:
    _require_ordered_unique(index, "slot index")
    if len(index) != expected_slots:
        raise ValueError(f"expected exactly {expected_slots} slots, received {len(index)}")
    if isinstance(index, pd.DatetimeIndex):
        if expected_slots == 240 and not index.equals(_expected_minute_clock(index[0])):
            raise ValueError("datetime slots must be the complete 09:31-11:30, 13:01-15:00 trading clock")
    elif isinstance(index, pd.RangeIndex):
        if index.step != 1:
            raise ValueError("RangeIndex slots must have step 1")
    elif pd.api.types.is_numeric_dtype(index):
        if len(index) > 1 and not np.all(np.diff(index.to_numpy()) == 1):
            raise ValueError("numeric slots must be consecutive")
    else:
        raise ValueError("slot index must be a DatetimeIndex, RangeIndex, or consecutive numeric index")


def _frame(frame: pd.DataFrame, name: str, expected_slots: int | None = None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    if frame.shape[1] == 0:
        raise ValueError(f"{name} must contain at least one ticker")
    _require_ordered_unique(frame.index, f"{name} index")
    if frame.columns.has_duplicates or frame.columns.hasnans:
        raise ValueError(f"{name} ticker columns must be unique and nonmissing")
    if expected_slots is not None:
        _validate_slot_index(frame.index, expected_slots)
    try:
        values = frame.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} values must be numeric") from exc
    return values


def _same_shape(left: pd.DataFrame, right: pd.DataFrame, left_name: str, right_name: str) -> None:
    if not left.index.equals(right.index) or not left.columns.equals(right.columns):
        raise ValueError(f"{left_name} and {right_name} must have identical ordered indexes and ticker columns")


def minute_returns(close: pd.DataFrame, opening_prices: pd.Series) -> pd.DataFrame:
    """Return simple within-day minute returns (first close/open, then close/close).

    Invalid prices (nonfinite or nonpositive) yield NaN only where their return
    cannot be formed.  PF/VV apply their own stock-day invalidity rules.
    """
    prices = _frame(close, "close")
    if len(prices) == 0:
        raise ValueError("close must contain at least one slot")
    if not isinstance(opening_prices, pd.Series):
        raise TypeError("opening_prices must be a pandas Series")
    if opening_prices.index.has_duplicates or opening_prices.index.hasnans:
        raise ValueError("opening_prices index must be unique and nonmissing")
    if not opening_prices.index.equals(prices.columns):
        raise ValueError("opening_prices index must exactly match close columns and order")
    try:
        opened = opening_prices.astype(float).to_numpy()
    except (TypeError, ValueError) as exc:
        raise ValueError("opening_prices must be numeric") from exc
    values = prices.to_numpy(copy=True)
    output = np.full(values.shape, np.nan, dtype=float)
    valid_close = np.isfinite(values) & (values > 0.0)
    valid_open = np.isfinite(opened) & (opened > 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        output[0] = np.where(valid_close[0] & valid_open, values[0] / opened - 1.0, np.nan)
        if len(prices) > 1:
            valid_pair = valid_close[1:] & valid_close[:-1]
            output[1:] = np.where(valid_pair, values[1:] / values[:-1] - 1.0, np.nan)
    return pd.DataFrame(output, index=prices.index.copy(), columns=prices.columns.copy())


def _population_skew(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size < 3:
        return np.nan
    centered = finite - finite.mean()
    m2 = float(np.mean(centered * centered))
    if m2 == 0.0:
        return 0.0
    return float(np.mean(centered**3) / m2**1.5)


def pf_daily(
    returns: pd.DataFrame, log_mode: str = "log1p_deviation", expected_slots: int = 240
) -> dict[str, object]:
    """Calculate source PF daily sums before their 20-day standard deviation.

    ``log_mode='log1p_deviation'`` is the frozen primary convention;
    ``'log_return_difference'`` is the declared non-selected sensitivity.
    The selected-minute gate requires at least three finite stocks at *every*
    expected slot.  Failure makes the full PF day unavailable, not a zero.
    """
    expected_slots = _require_int(expected_slots, "expected_slots", 1)
    if log_mode not in {"log1p_deviation", "log_return_difference"}:
        raise ValueError("log_mode must be 'log1p_deviation' or 'log_return_difference'")
    panel = _frame(returns, "returns", expected_slots)
    raw = panel.to_numpy(copy=True)
    deviations = np.full(raw.shape, np.nan, dtype=float)
    sign_means = np.full(raw.shape, np.nan, dtype=float)
    # A simple return <= -1 is impossible for the valid positive-price path.
    # Treat it as unavailable before constructing either same-sign benchmark.
    usable_input = np.isfinite(raw) & (raw > -1.0)
    finite_counts = usable_input.sum(axis=1)
    for row in range(raw.shape[0]):
        values = raw[row]
        usable = usable_input[row]
        deviations[row, usable] = 0.0  # source zero-return rule
        for mask in ((values > 0.0) & usable, (values < 0.0) & usable):
            if mask.any():
                mean = float(values[mask].mean())
                sign_means[row, mask] = mean
                deviations[row, mask] = values[mask] - mean
        sign_means[row, usable & (values == 0.0)] = 0.0
    skewness = pd.Series(
        [_population_skew(deviations[row]) for row in range(raw.shape[0])], index=panel.index, name="pf_skewness"
    )
    gate_available = bool(np.all(finite_counts >= 3))
    selected = pd.Series(gate_available & (skewness.to_numpy() > 0.0), index=panel.index, name="pf_selected")
    transformed = np.full(raw.shape, np.nan, dtype=float)
    for row in np.flatnonzero(selected.to_numpy()):
        if log_mode == "log1p_deviation":
            argument = deviations[row]
            legal = np.isfinite(argument) & (argument > -1.0)
            transformed[row, legal] = np.log1p(argument[legal])
        else:
            own, benchmark = raw[row], sign_means[row]
            legal = np.isfinite(own) & np.isfinite(benchmark) & (own > -1.0) & (benchmark > -1.0)
            transformed[row, legal] = np.log1p(own[legal]) - np.log1p(benchmark[legal])
    stock_complete = usable_input.all(axis=0)
    daily_values = np.full(panel.shape[1], np.nan, dtype=float)
    log_domain_valid = np.ones(panel.shape[1], dtype=bool)
    if gate_available:
        selected_rows = selected.to_numpy()
        if selected_rows.any():
            log_domain_valid = np.isfinite(transformed[selected_rows]).all(axis=0)
            valid = stock_complete & log_domain_valid
            daily_values[valid] = transformed[selected_rows][:, valid].sum(axis=0)
        else:
            daily_values[stock_complete] = 0.0
    daily = pd.Series(daily_values, index=panel.columns, name="pf_daily")
    return {
        "daily": daily,
        "deviations": pd.DataFrame(deviations, index=panel.index, columns=panel.columns),
        "skewness": skewness,
        "selected_minutes": selected,
        "diagnostics": {
            "slot_finite_count": pd.Series(finite_counts, index=panel.index, name="finite_stock_count"),
            "cross_section_gate_available": gate_available,
            "stock_complete": pd.Series(stock_complete, index=panel.columns, name="stock_complete"),
            "log_domain_valid": pd.Series(log_domain_valid, index=panel.columns, name="log_domain_valid"),
            "selected_minute_count": int(selected.sum()),
        },
    }


def vv_segments(volume1d: Sequence[float] | np.ndarray, rounds: int = 6, skip_open: int = 10) -> list[tuple[int, int]]:
    """Return terminal half-open segments indexed against the original array."""
    rounds = _require_int(rounds, "rounds", 0)
    skip_open = _require_int(skip_open, "skip_open", 0)
    values = np.asarray(volume1d, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("volume1d must be a nonempty one-dimensional array")
    if skip_open >= values.size:
        raise ValueError("skip_open must leave at least one retained slot")
    retained = values[skip_open:]
    if not np.isfinite(retained).all() or (retained < 0.0).any():
        raise ValueError("retained volume1d values must be finite and nonnegative")
    terminals: list[tuple[int, int]] = []
    stack = [(skip_open, int(values.size), 0)]
    while stack:
        left, right, depth = stack.pop()
        length = right - left
        if length <= 1 or depth >= rounds:
            terminals.append((left, right))
        elif length == 2:
            terminals.extend(((left, left + 1), (left + 1, right)))
        else:
            # np.argmax deterministically selects the first chronological peak.
            peak = left + 1 + int(np.argmax(values[left + 1 : right - 1]))
            stack.append((peak + 1, right, depth + 1))
            stack.append((left, peak + 1, depth + 1))
    return sorted(terminals)


def vv_daily(
    returns: pd.DataFrame,
    volume: pd.DataFrame,
    rounds: int = 6,
    skip_open: int = 10,
    expected_slots: int = 240,
) -> dict[str, object]:
    """Calculate unstandardized daily VV segment-return sample standard deviations."""
    expected_slots = _require_int(expected_slots, "expected_slots", 1)
    return_panel = _frame(returns, "returns", expected_slots)
    volume_panel = _frame(volume, "volume", expected_slots)
    _same_shape(return_panel, volume_panel, "returns", "volume")
    segment_std = np.full(return_panel.shape[1], np.nan, dtype=float)
    segment_counts = np.full(return_panel.shape[1], np.nan, dtype=float)
    raw_returns, raw_volumes = return_panel.to_numpy(), volume_panel.to_numpy()
    retained_returns, retained_volumes = raw_returns[skip_open:], raw_volumes[skip_open:]
    volume_valid = np.isfinite(retained_volumes).all(axis=0) & (retained_volumes >= 0.0).all(axis=0)
    return_valid = np.isfinite(retained_returns).all(axis=0) & (retained_returns >= -1.0).all(axis=0)
    for column in range(return_panel.shape[1]):
        if not volume_valid[column]:
            continue
        ranges = vv_segments(raw_volumes[:, column], rounds=rounds, skip_open=skip_open)
        segment_counts[column] = len(ranges)
        if not return_valid[column] or len(ranges) < 2:
            continue
        segment_returns = np.asarray(
            [np.prod(1.0 + raw_returns[left:right, column]) - 1.0 for left, right in ranges], dtype=float
        )
        if np.isfinite(segment_returns).all():
            segment_std[column] = float(np.std(segment_returns, ddof=1))
    daily = pd.Series(segment_std, index=return_panel.columns, name="vv_daily")
    return {
        "daily": daily,
        "segment_std": daily,
        "segment_counts": pd.Series(segment_counts, index=return_panel.columns, name="vv_segment_count"),
        "diagnostics": {
            "volume_valid": pd.Series(volume_valid, index=return_panel.columns, name="volume_valid"),
            "returns_valid": pd.Series(return_valid, index=return_panel.columns, name="returns_valid"),
            "skip_open": skip_open,
            "rounds": rounds,
        },
    }


def daily_cross_section_zscore(values: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Sample-z-score finite observations; constants are zero, <2 values unavailable."""
    if isinstance(values, pd.DataFrame):
        _frame(values, "values")
        return values.apply(lambda row: daily_cross_section_zscore(row), axis=1)
    if not isinstance(values, pd.Series):
        raise TypeError("values must be a pandas Series or DataFrame")
    # This index denotes a cross-section, not a time axis: preserve caller
    # order (which need not be alphabetical), while still rejecting ambiguity.
    if values.index.has_duplicates or values.index.hasnans:
        raise ValueError("values index must be unique and nonmissing")
    try:
        source = values.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("values must be numeric") from exc
    result = pd.Series(np.nan, index=source.index, name=source.name, dtype=float)
    finite = source.notna() & np.isfinite(source)
    if int(finite.sum()) < 2:
        return result
    sample = source.loc[finite]
    scale = float(sample.std(ddof=1))
    result.loc[finite] = 0.0 if scale == 0.0 else (sample - float(sample.mean())) / scale
    return result


def _calendar_index(calendar: pd.Index | Sequence[object]) -> pd.Index:
    if isinstance(calendar, pd.Series):
        index = pd.Index(calendar.to_numpy())
    elif isinstance(calendar, pd.Index):
        index = calendar.copy()
    else:
        index = pd.Index(calendar)
    _require_ordered_unique(index, "calendar")
    return index


def rolling_components(
    pf_daily_panel: pd.DataFrame,
    vv_daily_panel: pd.DataFrame,
    calendar: pd.Index | Sequence[object],
    window: int = 20,
) -> dict[str, object]:
    """Build source raw panels, their rolling components, and preferred composite.

    PF is the sample std over raw PF daily sums.  VV first receives a same-date
    sample cross-sectional z-score, then its sample rolling std.  Both final
    component z-scores use only stocks finite in *both* components that date.
    ``score`` is the same object as ``composite`` and equals ``-(pf_z+vv_z)/2``.
    """
    window = _require_int(window, "window", 2)
    pf_input, vv_input = _frame(pf_daily_panel, "pf_daily_panel"), _frame(vv_daily_panel, "vv_daily_panel")
    # Whole unavailable stock-days may legitimately be absent from one input.
    # The explicit calendar below restores them as NaN rather than silently
    # intersecting dates (which would compress the rolling window).
    if not pf_input.columns.equals(vv_input.columns):
        raise ValueError("pf_daily_panel and vv_daily_panel must have identical ordered ticker columns")
    dates = _calendar_index(calendar)
    if not pf_input.index.isin(dates).all():
        raise ValueError("daily panels contain dates absent from calendar")
    pf_raw, vv_raw = pf_input.reindex(dates), vv_input.reindex(dates)
    pf_std20 = pf_raw.rolling(window=window, min_periods=window).std(ddof=1)
    vv_daily_z = daily_cross_section_zscore(vv_raw)
    vv_std20 = vv_daily_z.rolling(window=window, min_periods=window).std(ddof=1)
    common = pf_std20.notna() & vv_std20.notna()
    pf_z = daily_cross_section_zscore(pf_std20.where(common))
    vv_z = daily_cross_section_zscore(vv_std20.where(common))
    pf_preferred, vv_preferred = -pf_z, -vv_z
    composite = (pf_preferred + vv_preferred) / 2.0
    composite.name = "pfvv_preferred_composite"
    return {
        "pf_daily": pf_raw,
        "vv_daily": vv_raw,
        # Raw factor components, ready for same-date orientation: PF's rolling
        # daily-sum standard deviation and VV's rolling std of daily CS-z.
        "pf_raw": pf_std20,
        "vv_raw": vv_std20,
        "pf_std20": pf_std20,
        "vv_daily_z": vv_daily_z,
        "vv_std20": vv_std20,
        "pf_z": pf_z,
        "vv_z": vv_z,
        "pf_preferred": pf_preferred,
        "vv_preferred": vv_preferred,
        "score": composite,
        "composite": composite,
        "diagnostics": {
            "common_finite": common,
            "common_finite_count": common.sum(axis=1).rename("common_finite_count"),
            "calendar": dates,
            "window": window,
        },
    }
