from __future__ import annotations

import os
import time
from typing import Any

import numpy as np
import pandas as pd

from .fast_rolling import ts_rank_fast_numpy, ts_rank_reference

FORMULA_KERNEL_ENGINE_VALUES = {
    'pandas_reference',
    'pandas_optimized',
    'numpy_rolling_experimental',
    'numba_rolling_experimental',
}

EXPERIMENTAL_FORMULA_KERNEL_ENGINES = {
    'numpy_rolling_experimental',
    'numba_rolling_experimental',
}

NUMPY_ROLLING_SUPPORTED_OPERATORS = {
    'sum',
    'mean',
    'std',
    'stddev',
    'min',
    'max',
    'delta',
    'delay',
    'ts_rank',
}


def resolve_formula_kernel_engine(explicit_engine: str | None = None) -> dict[str, Any]:
    env_engine = os.getenv('FACTORFORGE_FORMULA_KERNEL_ENGINE')
    if explicit_engine is not None:
        raw = explicit_engine
        selection_source = 'cli'
    elif env_engine is not None:
        raw = env_engine
        selection_source = 'env'
    else:
        raw = 'pandas_optimized'
        selection_source = 'default'
    selected_engine = str(raw or 'pandas_optimized').strip()
    aliases = {
        'pandas': 'pandas_optimized',
        'optimized': 'pandas_optimized',
        'reference': 'pandas_reference',
        'numpy': 'numpy_rolling_experimental',
    }
    selected_engine = aliases.get(selected_engine, selected_engine)
    if selected_engine not in FORMULA_KERNEL_ENGINE_VALUES:
        raise ValueError(f'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_INVALID:{selected_engine}')
    experimental_enabled = os.getenv('FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL') == '1'
    if selected_engine in EXPERIMENTAL_FORMULA_KERNEL_ENGINES and not experimental_enabled:
        raise ValueError('BLOCK_EXPERIMENTAL_FORMULA_KERNEL_NOT_ENABLED')
    if selected_engine == 'numba_rolling_experimental':
        try:
            import numba  # noqa: F401
        except Exception as exc:
            raise ValueError('BLOCK_EXPERIMENTAL_FORMULA_KERNEL_DEPENDENCY_MISSING:numba') from exc
    guard_raw = os.getenv('FACTORFORGE_EXPERIMENTAL_FORMULA_KERNEL_MAX_SECONDS')
    runtime_guard_seconds = float(guard_raw) if guard_raw else None
    return {
        'selected_engine': selected_engine,
        'experimental_enabled': bool(selected_engine in EXPERIMENTAL_FORMULA_KERNEL_ENGINES and experimental_enabled),
        'selection_source': selection_source,
        'runtime_guard_seconds': runtime_guard_seconds,
        'blocked_reason': None,
    }


def default_kernel_profile(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {
        'selected_engine': 'pandas_optimized',
        'experimental_enabled': False,
        'selection_source': 'default',
        'runtime_guard_seconds': None,
        'blocked_reason': None,
    }
    return {
        'version': 'factorforge_formula_kernel_profile_v1',
        'selected_engine': cfg.get('selected_engine') or 'pandas_optimized',
        'experimental_enabled': bool(cfg.get('experimental_enabled')),
        'selection_source': cfg.get('selection_source') or 'default',
        'operator_call_count': 0,
        'operator_total_seconds': 0.0,
        'operator_max_seconds': 0.0,
        'by_operator': {},
        'fallback_reasons': [],
        'parity_checked': False,
        'parity_sample_rows': 0,
        'parity_max_abs_diff': None,
        'parity_nan_mask_equal': None,
        'parity_key_order_equal': None,
        'runtime_guard_seconds': cfg.get('runtime_guard_seconds'),
        'runtime_guard_passed': True,
        'blocked_reason': cfg.get('blocked_reason'),
        'safe_to_make_default': False,
    }


def _profile(stats: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any] | None:
    if stats is None:
        return None
    profile = stats.setdefault('kernel_profile', default_kernel_profile(config))
    profile['selected_engine'] = config.get('selected_engine') or profile.get('selected_engine')
    profile['experimental_enabled'] = bool(config.get('experimental_enabled'))
    profile['selection_source'] = config.get('selection_source') or profile.get('selection_source')
    profile['runtime_guard_seconds'] = config.get('runtime_guard_seconds')
    profile['safe_to_make_default'] = False
    return profile


def _record_call(
    stats: dict[str, Any] | None,
    config: dict[str, Any],
    *,
    operator: str,
    seconds: float,
    optimized: bool,
    fallback_reason: str | None = None,
) -> None:
    profile = _profile(stats, config)
    if profile is None:
        return
    profile['operator_call_count'] = int(profile.get('operator_call_count') or 0) + 1
    profile['operator_total_seconds'] = float(profile.get('operator_total_seconds') or 0.0) + float(seconds)
    profile['operator_max_seconds'] = max(float(profile.get('operator_max_seconds') or 0.0), float(seconds))
    bucket = profile.setdefault('by_operator', {}).setdefault(operator, {
        'count': 0,
        'optimized_call_count': 0,
        'fallback_count': 0,
        'total_seconds': 0.0,
        'max_seconds': 0.0,
    })
    bucket['count'] = int(bucket.get('count') or 0) + 1
    bucket['total_seconds'] = float(bucket.get('total_seconds') or 0.0) + float(seconds)
    bucket['max_seconds'] = max(float(bucket.get('max_seconds') or 0.0), float(seconds))
    if optimized:
        bucket['optimized_call_count'] = int(bucket.get('optimized_call_count') or 0) + 1
    else:
        bucket['fallback_count'] = int(bucket.get('fallback_count') or 0) + 1
    if fallback_reason:
        reasons = profile.setdefault('fallback_reasons', [])
        if fallback_reason not in reasons:
            reasons.append(fallback_reason)
    guard = config.get('runtime_guard_seconds')
    if config.get('experimental_enabled') and guard is not None and float(profile.get('operator_total_seconds') or 0.0) > float(guard):
        profile['runtime_guard_passed'] = False
        profile['blocked_reason'] = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD'
        raise RuntimeError(
            'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD: '
            f"seconds={float(profile.get('operator_total_seconds') or 0.0):.9f} limit={float(guard):.9f}"
        )


def _group_positions(frame: pd.DataFrame) -> list[np.ndarray]:
    codes = frame['ts_code'].to_numpy()
    return [np.flatnonzero(codes == code) for code in pd.unique(frame['ts_code'])]


def _rolling_numpy_one(values: np.ndarray, window: int, op: str) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype='float64')
    if window <= 0 or len(values) < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values, window_shape=window)
    valid = ~np.isnan(windows).any(axis=1)
    if not valid.any():
        return out
    valid_windows = windows[valid]
    if op == 'sum':
        vals = valid_windows.sum(axis=1)
    elif op == 'mean':
        vals = valid_windows.mean(axis=1)
    elif op in {'std', 'stddev'}:
        vals = valid_windows.std(axis=1, ddof=1)
    elif op == 'min':
        vals = valid_windows.min(axis=1)
    elif op == 'max':
        vals = valid_windows.max(axis=1)
    else:
        raise ValueError(f'unsupported numpy rolling op: {op}')
    out[np.flatnonzero(valid) + window - 1] = vals.astype('float64', copy=False)
    return out


def _numpy_rolling(series: pd.Series, window: int, frame: pd.DataFrame, op: str) -> pd.Series:
    values = pd.to_numeric(series, errors='coerce').to_numpy(dtype='float64', copy=False)
    result = np.full(len(values), np.nan, dtype='float64')
    for positions in _group_positions(frame):
        if len(positions) == 0:
            continue
        result[positions] = _rolling_numpy_one(values[positions], window, op)
    return pd.Series(result, index=series.index, name=series.name)


def _numpy_delta(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    values = pd.to_numeric(series, errors='coerce').to_numpy(dtype='float64', copy=False)
    result = np.full(len(values), np.nan, dtype='float64')
    for positions in _group_positions(frame):
        group_values = values[positions]
        if window <= 0:
            result[positions] = group_values - group_values
        elif len(positions) > window:
            result[positions[window:]] = group_values[window:] - group_values[:-window]
    return pd.Series(result, index=series.index, name=series.name)


def _numpy_delay(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    values = pd.to_numeric(series, errors='coerce').to_numpy(dtype='float64', copy=False)
    result = np.full(len(values), np.nan, dtype='float64')
    for positions in _group_positions(frame):
        group_values = values[positions]
        if window <= 0:
            result[positions] = group_values
        elif len(positions) > window:
            result[positions[window:]] = group_values[:-window]
    return pd.Series(result, index=series.index, name=series.name)


def _pandas_operator(op: str, args: list[Any], window: int, frame: pd.DataFrame) -> pd.Series:
    series = args[0]
    if op == 'sum':
        return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).sum())
    if op == 'mean':
        return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean())
    if op in {'std', 'stddev'}:
        return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).std())
    if op == 'min':
        return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).min())
    if op == 'max':
        return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).max())
    if op == 'delta':
        return series.groupby(frame['ts_code'], sort=False).diff(window)
    if op == 'delay':
        return series.groupby(frame['ts_code'], sort=False).shift(window)
    if op == 'ts_rank':
        return ts_rank_reference(series, window, frame)
    raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_KERNEL_OPERATOR:{op}')


def apply_kernel_operator(
    op: str,
    args: list[Any],
    window: int,
    frame: pd.DataFrame,
    *,
    stats: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> pd.Series:
    cfg = config or resolve_formula_kernel_engine()
    selected = cfg.get('selected_engine') or 'pandas_optimized'
    start = time.perf_counter()
    optimized = False
    fallback_reason = None
    try:
        if selected == 'numpy_rolling_experimental':
            if op not in NUMPY_ROLLING_SUPPORTED_OPERATORS:
                fallback_reason = f'unsupported_operator:{op}'
                result = _pandas_operator(op, args, window, frame)
            elif op in {'sum', 'mean', 'std', 'stddev', 'min', 'max'}:
                result = _numpy_rolling(args[0], window, frame, op)
                optimized = True
            elif op == 'delta':
                result = _numpy_delta(args[0], window, frame)
                optimized = True
            elif op == 'delay':
                result = _numpy_delay(args[0], window, frame)
                optimized = True
            elif op == 'ts_rank':
                result = ts_rank_fast_numpy(args[0], window, frame, stats=None)
                optimized = True
            else:
                fallback_reason = f'unsupported_operator:{op}'
                result = _pandas_operator(op, args, window, frame)
            if optimized and os.getenv('FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION') == '1':
                root = os.getenv('FACTORFORGE_ROOT') or ''
                if root.startswith('/tmp/') or root.startswith('/private/tmp/'):
                    result = result.copy()
                    valid = result.notna()
                    if valid.any():
                        result.loc[valid[valid].index[0]] = float(result.loc[valid[valid].index[0]]) + 1.0
        else:
            result = _pandas_operator(op, args, window, frame)
    except Exception as exc:
        profile = _profile(stats, cfg)
        if profile is not None:
            profile['blocked_reason'] = f'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_FAILED:{type(exc).__name__}:{exc}'
        if selected in EXPERIMENTAL_FORMULA_KERNEL_ENGINES:
            raise RuntimeError(f'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_FAILED:{type(exc).__name__}:{exc}') from exc
        raise
    seconds = time.perf_counter() - start
    _record_call(stats, cfg, operator=op, seconds=seconds, optimized=optimized, fallback_reason=fallback_reason)
    return result
