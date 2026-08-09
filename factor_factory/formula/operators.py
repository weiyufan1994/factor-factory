from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd

from .fast_rolling import last_value_pct_rank_reference, ts_rank_fast_numpy, ts_rank_reference

TS_RANK_ENGINE_VALUES = {'pandas_reference', 'numpy_sliding_window_experimental'}


def resolve_ts_rank_engine(explicit_engine: str | None = None) -> dict:
    env_engine = os.getenv('FACTORFORGE_TS_RANK_ENGINE')
    legacy_fast_env_ignored = os.getenv('FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST') == '1'
    if explicit_engine is not None:
        raw = explicit_engine
        selection_source = 'cli'
    elif env_engine is not None:
        raw = env_engine
        selection_source = 'env'
    else:
        raw = 'pandas_reference'
        selection_source = 'default'
    selected_engine = str(raw or 'pandas_reference').strip()
    if selected_engine == 'numpy_sliding_window':
        selected_engine = 'numpy_sliding_window_experimental'
    explicit_experimental_gate = os.getenv('FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE') == '1'
    experimental_enabled = bool(explicit_experimental_gate and selected_engine != 'pandas_reference')
    if selected_engine not in TS_RANK_ENGINE_VALUES:
        raise ValueError(f'BLOCK_EXPERIMENTAL_TS_RANK_ENGINE_INVALID:{selected_engine}')
    if selected_engine != 'pandas_reference' and not experimental_enabled:
        raise ValueError('BLOCK_EXPERIMENTAL_TS_RANK_ENGINE_NOT_ENABLED')
    guard_raw = os.getenv('FACTORFORGE_EXPERIMENTAL_TS_RANK_MAX_SECONDS')
    runtime_guard_seconds = float(guard_raw) if guard_raw else None
    return {
        'selected_engine': selected_engine,
        'experimental_enabled': bool(experimental_enabled),
        'selection_source': selection_source,
        'blocked_reason': None,
        'runtime_guard_seconds': runtime_guard_seconds,
        'legacy_fast_env_ignored': bool(legacy_fast_env_ignored),
        'legacy_fast_env_name': 'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST' if legacy_fast_env_ignored else None,
    }


def default_ts_rank_engine_profile(config: dict | None = None) -> dict:
    cfg = config or {
        'selected_engine': 'pandas_reference',
        'experimental_enabled': False,
        'selection_source': 'default',
        'runtime_guard_seconds': None,
        'blocked_reason': None,
        'legacy_fast_env_ignored': False,
        'legacy_fast_env_name': None,
    }
    return {
        'version': 'factorforge_ts_rank_engine_profile_v1',
        'selected_engine': cfg.get('selected_engine') or 'pandas_reference',
        'experimental_enabled': bool(cfg.get('experimental_enabled')),
        'selection_source': cfg.get('selection_source') or 'default',
        'engine_call_count': 0,
        'engine_total_seconds': 0.0,
        'engine_max_seconds': 0.0,
        'parity_checked': False,
        'parity_sample_rows': 0,
        'parity_max_abs_diff': None,
        'parity_nan_mask_equal': None,
        'parity_key_order_equal': None,
        'runtime_guard_seconds': cfg.get('runtime_guard_seconds'),
        'runtime_guard_passed': True,
        'blocked_reason': cfg.get('blocked_reason'),
        'legacy_fast_env_ignored': bool(cfg.get('legacy_fast_env_ignored')),
        'legacy_fast_env_name': cfg.get('legacy_fast_env_name'),
    }


def _update_ts_rank_engine_profile(stats: dict | None, config: dict, seconds: float) -> None:
    if stats is None:
        return
    profile = stats.setdefault('ts_rank_engine_profile', default_ts_rank_engine_profile(config))
    profile['selected_engine'] = config.get('selected_engine') or profile.get('selected_engine')
    profile['experimental_enabled'] = bool(config.get('experimental_enabled'))
    profile['selection_source'] = config.get('selection_source') or profile.get('selection_source')
    profile['engine_call_count'] = int(profile.get('engine_call_count') or 0) + 1
    profile['engine_total_seconds'] = float(profile.get('engine_total_seconds') or 0.0) + float(seconds)
    profile['engine_max_seconds'] = max(float(profile.get('engine_max_seconds') or 0.0), float(seconds))
    profile['runtime_guard_seconds'] = config.get('runtime_guard_seconds')
    profile['legacy_fast_env_ignored'] = bool(config.get('legacy_fast_env_ignored'))
    profile['legacy_fast_env_name'] = config.get('legacy_fast_env_name')


def _maybe_fault_inject_ts_rank(result: pd.Series) -> pd.Series:
    if os.getenv('FACTORFORGE_TS_RANK_ENGINE_FAULT_INJECTION') != '1':
        return result
    root = os.getenv('FACTORFORGE_ROOT') or ''
    if not (root.startswith('/tmp/') or root.startswith('/private/tmp/')):
        return result
    mutated = result.copy()
    valid = mutated.notna()
    if valid.any():
        first_idx = valid[valid].index[0]
        mutated.loc[first_idx] = float(mutated.loc[first_idx]) + 1.0
    return mutated


def cs_rank(series: pd.Series, frame: pd.DataFrame) -> pd.Series:
    if 'trade_date' in frame.columns:
        return series.groupby(frame['trade_date']).rank(method='average', pct=True)
    return series.rank(method='average', pct=True)


def ts_sum(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).sum())


def ts_mean(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean())


def ts_std(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).std())


def cs_regression(y: pd.Series, x: pd.Series, out_type: int, frame: pd.DataFrame) -> pd.Series:
    """Daily cross-sectional OLS y ~ 1 + x.

    out_type follows the CS_REGRESSION source contract:
    0 = residual, 1 = fitted y, 2 = beta on x.
    """
    out = pd.Series(np.nan, index=frame.index, dtype='float64')
    if 'trade_date' not in frame.columns:
        return out
    y_num = pd.to_numeric(y, errors='coerce')
    x_num = pd.to_numeric(x, errors='coerce')
    mode = int(out_type)
    for _, idx in frame.groupby('trade_date', sort=False).groups.items():
        group_idx = pd.Index(idx)
        yy = y_num.loc[group_idx]
        xx = x_num.loc[group_idx]
        valid = yy.notna() & xx.notna()
        if int(valid.sum()) < 2:
            continue
        x_valid = xx.loc[valid].astype(float)
        y_valid = yy.loc[valid].astype(float)
        x_var = float(x_valid.var(ddof=0))
        if not np.isfinite(x_var) or abs(x_var) < 1e-18:
            alpha = float(y_valid.mean())
            beta = 0.0
        else:
            cov = float(((x_valid - x_valid.mean()) * (y_valid - y_valid.mean())).mean())
            beta = cov / x_var
            alpha = float(y_valid.mean() - beta * x_valid.mean())
        fitted = alpha + beta * x_valid
        if mode == 0:
            values = y_valid - fitted
        elif mode == 1:
            values = fitted
        elif mode == 2:
            values = pd.Series(beta, index=x_valid.index, dtype='float64')
        else:
            raise ValueError(f'BLOCK_UNSUPPORTED_CS_REGRESSION_OUT_TYPE:{mode}')
        out.loc[values.index] = values
    return out


def _last_value_pct_rank(values: np.ndarray) -> float:
    return last_value_pct_rank_reference(values)


def ts_rank(series: pd.Series, window: int, frame: pd.DataFrame, stats: dict | None = None, engine_config: dict | None = None) -> pd.Series:
    try:
        config = engine_config or resolve_ts_rank_engine()
    except ValueError as exc:
        if stats is not None:
            stats['ts_rank_engine_profile'] = default_ts_rank_engine_profile({'blocked_reason': str(exc)})
        raise
    selected_engine = config.get('selected_engine') or 'pandas_reference'
    if selected_engine == 'numpy_sliding_window_experimental':
        start = time.perf_counter()
        try:
            result = ts_rank_fast_numpy(series, window, frame, stats=stats)
            result = _maybe_fault_inject_ts_rank(result)
        except Exception as exc:
            if stats is not None:
                profile = stats.setdefault('ts_rank_engine_profile', default_ts_rank_engine_profile(config))
                profile['blocked_reason'] = f'BLOCK_EXPERIMENTAL_TS_RANK_ENGINE_FAILED:{type(exc).__name__}:{exc}'
            raise RuntimeError(f'BLOCK_EXPERIMENTAL_TS_RANK_ENGINE_FAILED:{type(exc).__name__}:{exc}') from exc
        seconds = time.perf_counter() - start
        _update_ts_rank_engine_profile(stats, config, seconds)
        if stats is not None:
            stats['ts_rank_engine'] = 'numpy_sliding_window_experimental'
            stats['ts_rank_fast_path_enabled'] = True
        guard = config.get('runtime_guard_seconds')
        if guard is not None and float(seconds) > float(guard):
            if stats is not None:
                profile = stats.setdefault('ts_rank_engine_profile', default_ts_rank_engine_profile(config))
                profile['runtime_guard_passed'] = False
                profile['blocked_reason'] = 'BLOCK_EXPERIMENTAL_TS_RANK_RUNTIME_GUARD'
            raise RuntimeError(
                f'BLOCK_EXPERIMENTAL_TS_RANK_RUNTIME_GUARD: seconds={seconds:.9f} limit={float(guard):.9f}'
            )
        return result
    if stats is not None:
        stats['ts_rank_engine'] = 'pandas_reference'
        stats['ts_rank_fast_path_enabled'] = False
        stats['ts_rank_fast_path_count'] = int(stats.get('ts_rank_fast_path_count', 0))
        stats['ts_rank_fallback_count'] = int(stats.get('ts_rank_fallback_count', 0)) + 1
        stats.setdefault('ts_rank_fallback_reasons', []).append('experimental_fast_path_disabled')
        stats['ts_rank_window_max'] = max(int(stats.get('ts_rank_window_max', 0)), int(window))
    start = time.perf_counter()
    result = ts_rank_reference(series, window, frame)
    _update_ts_rank_engine_profile(stats, config, time.perf_counter() - start)
    return result


def ts_min(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).min())


def ts_max(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).max())


def ts_argmin(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(lambda values: float(np.argmin(values)) + 1.0, raw=True)
    )


def ts_argmax(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(lambda values: float(np.argmax(values)) + 1.0, raw=True)
    )


def ts_delta(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).diff(window)


def ts_delay(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).shift(window)


def _rolling_pairwise_aligned(left: pd.Series, right: pd.Series, window: int, frame: pd.DataFrame, mode: str) -> pd.Series:
    left_values = pd.to_numeric(left, errors='coerce').to_numpy(dtype='float64', copy=False)
    right_values = pd.to_numeric(right, errors='coerce').to_numpy(dtype='float64', copy=False)
    result = np.full(len(frame), np.nan, dtype='float64')
    for positions in frame.groupby('ts_code', sort=False, observed=True).indices.values():
        pos = np.asarray(positions, dtype=np.intp)
        left_s = pd.Series(left_values[pos])
        right_s = pd.Series(right_values[pos])
        if mode == 'corr':
            values = left_s.rolling(window, min_periods=window).corr(right_s)
        elif mode == 'cov':
            values = left_s.rolling(window, min_periods=window).cov(right_s)
        else:
            raise ValueError(f'unsupported pairwise mode: {mode}')
        result[pos] = values.to_numpy(dtype='float64', copy=False)
    return pd.Series(result, index=frame.index, name=getattr(left, 'name', None))


def rolling_corr(left: pd.Series, right: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return _rolling_pairwise_aligned(left, right, window, frame, 'corr')


def rolling_cov(left: pd.Series, right: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return _rolling_pairwise_aligned(left, right, window, frame, 'cov')


def cs_scale(series: pd.Series, frame: pd.DataFrame) -> pd.Series:
    denom = series.abs().groupby(frame['trade_date']).transform('sum')
    return series / denom.replace(0, np.nan)


def cs_zscore(series: pd.Series, ddof: int, frame: pd.DataFrame) -> pd.Series:
    values = pd.to_numeric(series, errors='coerce')
    grouped = values.groupby(frame['trade_date'], sort=False)
    mean = grouped.transform('mean')
    std = grouped.transform(lambda item: item.std(ddof=int(ddof)))
    return (values - mean) / std.replace(0, np.nan)


def signed_log1p(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors='coerce')
    return np.sign(values) * np.log1p(np.abs(values))


def rolling_kurtosis(
    series: pd.Series,
    window: int,
    frame: pd.DataFrame,
    *,
    pearson: bool,
) -> pd.Series:
    result = series.groupby(frame['ts_code'], sort=False).transform(
        lambda item: pd.to_numeric(item, errors='coerce').rolling(
            int(window), min_periods=int(window)
        ).kurt()
    )
    return result + 3.0 if pearson else result


def _unbiased_sample_skew(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype='float64')
    finite = finite[np.isfinite(finite)]
    count = int(finite.size)
    if count < 3:
        return np.nan
    centered = finite - float(finite.mean())
    second = float(np.mean(centered ** 2))
    if not np.isfinite(second) or second <= 0:
        return np.nan
    third = float(np.mean(centered ** 3))
    raw_skew = third / (second ** 1.5)
    return float(np.sqrt(count * (count - 1)) / (count - 2) * raw_skew)


def _rolling_order_statistic_skew(
    series: pd.Series,
    window: int,
    subset: int,
    frame: pd.DataFrame,
    *,
    largest: bool,
) -> pd.Series:
    window = int(window)
    subset = int(subset)

    def calculate(values: np.ndarray) -> float:
        ordered = np.sort(np.asarray(values, dtype='float64'))
        selected = ordered[-subset:] if largest else ordered[:subset]
        return _unbiased_sample_skew(selected)

    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda item: pd.to_numeric(item, errors='coerce').rolling(
            window, min_periods=window
        ).apply(calculate, raw=True)
    )


def rolling_topk_skew(series: pd.Series, window: int, subset: int, frame: pd.DataFrame) -> pd.Series:
    return _rolling_order_statistic_skew(series, window, subset, frame, largest=True)


def rolling_bottomk_skew(series: pd.Series, window: int, subset: int, frame: pd.DataFrame) -> pd.Series:
    return _rolling_order_statistic_skew(series, window, subset, frame, largest=False)


def _rolling_inner_skew_extreme(
    series: pd.Series,
    outer_window: int,
    inner_window: int,
    frame: pd.DataFrame,
    *,
    mode: str,
) -> pd.Series:
    outer_window = int(outer_window)
    inner_window = int(inner_window)
    extreme_window = outer_window - inner_window + 1

    def calculate(item: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(item, errors='coerce')
        inner = numeric.rolling(inner_window, min_periods=inner_window).skew()
        rolling = inner.rolling(extreme_window, min_periods=extreme_window)
        return rolling.max() if mode == 'max' else rolling.min()

    return series.groupby(frame['ts_code'], sort=False).transform(calculate)


def rolling_max_inner_skew(series: pd.Series, outer_window: int, inner_window: int, frame: pd.DataFrame) -> pd.Series:
    return _rolling_inner_skew_extreme(series, outer_window, inner_window, frame, mode='max')


def rolling_min_inner_skew(series: pd.Series, outer_window: int, inner_window: int, frame: pd.DataFrame) -> pd.Series:
    return _rolling_inner_skew_extreme(series, outer_window, inner_window, frame, mode='min')


def rolling_max_subwindow_sum(
    series: pd.Series,
    outer_window: int,
    inner_window: int,
    frame: pd.DataFrame,
) -> pd.Series:
    outer_window = int(outer_window)
    inner_window = int(inner_window)
    extreme_window = outer_window - inner_window + 1

    def calculate(item: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(item, errors='coerce')
        inner_sum = numeric.rolling(inner_window, min_periods=inner_window).sum()
        return inner_sum.rolling(extreme_window, min_periods=extreme_window).max()

    return series.groupby(frame['ts_code'], sort=False).transform(calculate)


def rolling_topk_sum(series: pd.Series, window: int, subset: int, frame: pd.DataFrame) -> pd.Series:
    window = int(window)
    subset = int(subset)

    def calculate(values: np.ndarray) -> float:
        numeric = np.asarray(values, dtype='float64')
        if not np.isfinite(numeric).all():
            return np.nan
        partitioned = np.partition(numeric, len(numeric) - subset)
        return float(partitioned[-subset:].sum())

    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda item: pd.to_numeric(item, errors='coerce').rolling(
            window, min_periods=window
        ).apply(calculate, raw=True)
    )


def signed_power(left: pd.Series, right) -> pd.Series:
    return np.sign(left) * (np.abs(left) ** right)
