from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def last_value_pct_rank_reference(values: np.ndarray) -> float:
    if len(values) == 0 or np.isnan(values).any():
        return np.nan
    last = values[-1]
    less = np.sum(values < last)
    equal = np.sum(values == last)
    average_rank = less + (equal + 1.0) / 2.0
    return float(average_rank / len(values))


def ts_rank_reference(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(last_value_pct_rank_reference, raw=True)
    )


def _ts_rank_one_array(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype='float64')
    if window <= 0 or len(values) < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values, window_shape=window)
    valid = ~np.isnan(windows).any(axis=1)
    if not valid.any():
        return out
    valid_windows = windows[valid]
    last = valid_windows[:, -1]
    less = (valid_windows < last[:, None]).sum(axis=1)
    equal = (valid_windows == last[:, None]).sum(axis=1)
    ranks = (less + (equal + 1.0) / 2.0) / float(window)
    target_positions = np.flatnonzero(valid) + window - 1
    out[target_positions] = ranks.astype('float64', copy=False)
    return out


def ts_rank_fast_numpy(
    series: pd.Series,
    window: int,
    frame: pd.DataFrame,
    stats: dict[str, Any] | None = None,
) -> pd.Series:
    if window <= 0:
        if stats is not None:
            stats['ts_rank_fallback_count'] = int(stats.get('ts_rank_fallback_count', 0)) + 1
            stats.setdefault('ts_rank_fallback_reasons', []).append('non_positive_window')
        return ts_rank_reference(series, window, frame)

    values = pd.to_numeric(series, errors='coerce').to_numpy(dtype='float64', copy=False)
    result = np.full(len(values), np.nan, dtype='float64')
    grouped_positions = frame.groupby('ts_code', sort=False, observed=True).indices
    for raw_positions in grouped_positions.values():
        positions = np.asarray(raw_positions, dtype=np.intp)
        if len(positions) == 0:
            continue
        result[positions] = _ts_rank_one_array(values[positions], window)

    if stats is not None:
        stats['ts_rank_fast_path_count'] = int(stats.get('ts_rank_fast_path_count', 0)) + 1
        stats['ts_rank_engine'] = 'numpy_sliding_window'
        stats['ts_rank_fast_path_enabled'] = True
        stats['ts_rank_window_max'] = max(int(stats.get('ts_rank_window_max', 0)), int(window))
    return pd.Series(result, index=series.index, name=series.name)
