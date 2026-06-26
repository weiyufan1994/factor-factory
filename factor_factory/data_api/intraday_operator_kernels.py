from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class KernelResult:
    values: np.ndarray
    backend: str


@dataclass(frozen=True)
class GroupOffsets:
    starts: np.ndarray
    ends: np.ndarray
    sizes: np.ndarray


def _as_float_array(values: np.ndarray | list[float]) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


def group_offsets_from_sorted_codes(codes: np.ndarray | list[Any]) -> GroupOffsets:
    values = np.asarray(codes)
    if values.ndim != 1:
        raise ValueError('codes must be one-dimensional')
    n = int(len(values))
    if n == 0:
        empty = np.array([], dtype=np.int64)
        return GroupOffsets(starts=empty, ends=empty, sizes=empty)
    starts = np.flatnonzero(np.r_[True, values[1:] != values[:-1]]).astype(np.int64)
    ends = np.r_[starts[1:], n].astype(np.int64)
    return GroupOffsets(starts=starts, ends=ends, sizes=(ends - starts).astype(np.int64))


def group_offsets_from_sorted_frame(frame: pd.DataFrame, group_cols: list[str]) -> GroupOffsets:
    if not group_cols:
        raise ValueError('group_cols must not be empty')
    missing = [col for col in group_cols if col not in frame.columns]
    if missing:
        raise ValueError(f'frame missing group columns: {missing}')
    if len(group_cols) == 1:
        return group_offsets_from_sorted_codes(frame[group_cols[0]].to_numpy())
    n = int(len(frame))
    if n == 0:
        empty = np.array([], dtype=np.int64)
        return GroupOffsets(starts=empty, ends=empty, sizes=empty)
    boundary = np.zeros(n, dtype=bool)
    boundary[0] = True
    for col in group_cols:
        values = frame[col].to_numpy()
        boundary[1:] |= values[1:] != values[:-1]
    starts = np.flatnonzero(boundary).astype(np.int64)
    ends = np.r_[starts[1:], n].astype(np.int64)
    return GroupOffsets(starts=starts, ends=ends, sizes=(ends - starts).astype(np.int64))


def _rolling_corr_numpy(x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    if window <= 0:
        raise ValueError('window must be positive')
    if len(x) != len(y):
        raise ValueError('x and y must have the same length')
    n = len(x)
    out = np.zeros(n, dtype=np.float64)
    if n == 0 or window > n:
        return out

    valid = np.isfinite(x) & np.isfinite(y)
    clean_x = np.where(valid, x, 0.0)
    clean_y = np.where(valid, y, 0.0)
    count = np.cumsum(valid.astype(np.int64))
    sx = np.cumsum(clean_x)
    sy = np.cumsum(clean_y)
    sxx = np.cumsum(clean_x * clean_x)
    syy = np.cumsum(clean_y * clean_y)
    sxy = np.cumsum(clean_x * clean_y)

    for end in range(window - 1, n):
        start = end - window
        cnt = count[end] - (count[start] if start >= 0 else 0)
        if cnt != window:
            continue
        sum_x = sx[end] - (sx[start] if start >= 0 else 0.0)
        sum_y = sy[end] - (sy[start] if start >= 0 else 0.0)
        sum_xx = sxx[end] - (sxx[start] if start >= 0 else 0.0)
        sum_yy = syy[end] - (syy[start] if start >= 0 else 0.0)
        sum_xy = sxy[end] - (sxy[start] if start >= 0 else 0.0)
        cov = sum_xy - (sum_x * sum_y / float(window))
        var_x = sum_xx - (sum_x * sum_x / float(window))
        var_y = sum_yy - (sum_y * sum_y / float(window))
        denom = var_x * var_y
        out[end] = cov / np.sqrt(denom) if denom > 0.0 else 0.0
    return out


def _rolling_corr_group_vectorized_numpy(group_x: np.ndarray, group_y: np.ndarray, window: int) -> np.ndarray:
    size = int(window)
    if size <= 0:
        raise ValueError('window must be positive')
    if len(group_x) != len(group_y):
        raise ValueError('x and y must have the same length')
    n = len(group_x)
    out = np.zeros(n, dtype=np.float64)
    if n == 0 or size > n:
        return out

    valid = np.isfinite(group_x) & np.isfinite(group_y)
    clean_x = np.where(valid, group_x, 0.0)
    clean_y = np.where(valid, group_y, 0.0)
    count = np.concatenate(([0], np.cumsum(valid.astype(np.int64))))
    sx = np.concatenate(([0.0], np.cumsum(clean_x)))
    sy = np.concatenate(([0.0], np.cumsum(clean_y)))
    sxx = np.concatenate(([0.0], np.cumsum(clean_x * clean_x)))
    syy = np.concatenate(([0.0], np.cumsum(clean_y * clean_y)))
    sxy = np.concatenate(([0.0], np.cumsum(clean_x * clean_y)))

    cnt = count[size:] - count[:-size]
    sum_x = sx[size:] - sx[:-size]
    sum_y = sy[size:] - sy[:-size]
    sum_xx = sxx[size:] - sxx[:-size]
    sum_yy = syy[size:] - syy[:-size]
    sum_xy = sxy[size:] - sxy[:-size]
    cov = sum_xy - (sum_x * sum_y / float(size))
    var_x = sum_xx - (sum_x * sum_x / float(size))
    var_y = sum_yy - (sum_y * sum_y / float(size))
    denom = var_x * var_y
    good = (cnt == size) & (denom > 0.0)
    values = np.zeros_like(cov, dtype=np.float64)
    values[good] = cov[good] / np.sqrt(denom[good])
    out[size - 1:] = values
    return out


def _rolling_corr_grouped_vectorized_numpy(starts: np.ndarray, ends: np.ndarray, x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    size = int(window)
    if size <= 0:
        raise ValueError('window must be positive')
    if len(x) != len(y):
        raise ValueError('x and y must have the same length')
    n = len(x)
    out = np.zeros(n, dtype=np.float64)
    if n == 0:
        return out

    group_sizes = ends - starts
    if len(group_sizes) == 0:
        return out
    group_start_for_row = np.repeat(starts, group_sizes.astype(np.int64))
    if len(group_start_for_row) != n:
        raise ValueError('group offsets must cover x/y arrays exactly')

    valid = np.isfinite(x) & np.isfinite(y)
    clean_x = np.where(valid, x, 0.0)
    clean_y = np.where(valid, y, 0.0)
    count = np.concatenate(([0], np.cumsum(valid.astype(np.int64))))
    sx = np.concatenate(([0.0], np.cumsum(clean_x)))
    sy = np.concatenate(([0.0], np.cumsum(clean_y)))
    sxx = np.concatenate(([0.0], np.cumsum(clean_x * clean_x)))
    syy = np.concatenate(([0.0], np.cumsum(clean_y * clean_y)))
    sxy = np.concatenate(([0.0], np.cumsum(clean_x * clean_y)))

    row_idx = np.arange(n, dtype=np.int64)
    window_start = row_idx - size + 1
    eligible = window_start >= group_start_for_row
    if not bool(np.any(eligible)):
        return out
    end_plus = row_idx[eligible] + 1
    start_idx = window_start[eligible]
    cnt = count[end_plus] - count[start_idx]
    sum_x = sx[end_plus] - sx[start_idx]
    sum_y = sy[end_plus] - sy[start_idx]
    sum_xx = sxx[end_plus] - sxx[start_idx]
    sum_yy = syy[end_plus] - syy[start_idx]
    sum_xy = sxy[end_plus] - sxy[start_idx]
    cov = sum_xy - (sum_x * sum_y / float(size))
    var_x = sum_xx - (sum_x * sum_x / float(size))
    var_y = sum_yy - (sum_y * sum_y / float(size))
    denom = var_x * var_y
    good = (cnt == size) & (denom > 0.0)
    target_idx = row_idx[eligible]
    values = np.zeros_like(cov, dtype=np.float64)
    values[good] = cov[good] / np.sqrt(denom[good])
    out[target_idx] = values
    return out


def _rolling_corr_grouped_numpy(starts: np.ndarray, ends: np.ndarray, x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    size = int(window)
    if size <= 0:
        raise ValueError('window must be positive')
    if len(x) != len(y):
        raise ValueError('x and y must have the same length')
    n = len(x)
    out = np.zeros(n, dtype=np.float64)
    if n == 0:
        return out

    return _rolling_corr_grouped_vectorized_numpy(starts, ends, x, y, size)


def _rolling_corr_array_grouped_shard(payload: dict[str, Any]) -> tuple[pd.Index, np.ndarray]:
    frame = payload['frame']
    output_col = payload['output_col']
    result = rolling_corr_by_group(
        frame,
        group_col=payload['group_col'],
        order_col=payload['order_col'],
        x_col=payload['x_col'],
        y_col=payload['y_col'],
        window=int(payload['window']),
        output_col=output_col,
        backend='array_grouped',
    )
    return result.index, result[output_col].to_numpy(dtype=np.float64)


def _terminal_corr_array_grouped_shard(payload: dict[str, Any]) -> pd.DataFrame:
    return terminal_rolling_corr_by_group(
        payload['frame'],
        group_cols=list(payload['group_cols']),
        order_col=payload['order_col'],
        x_col=payload['x_col'],
        y_col=payload['y_col'],
        window=int(payload['window']),
        output_col=payload['output_col'],
        backend='array_grouped',
    )


def _build_coarse_group_shards(frame: pd.DataFrame, group_cols: list[str], shard_count: int) -> list[pd.DataFrame]:
    workers = int(shard_count)
    if workers <= 0 or frame.empty:
        return []
    if workers == 1:
        return [frame]
    if len(group_cols) == 1:
        codes, _ = pd.factorize(frame[group_cols[0]], sort=False)
    else:
        codes, _ = pd.factorize(pd.MultiIndex.from_frame(frame[group_cols]), sort=False)
    shard_ids = np.asarray(codes, dtype=np.int64) % workers
    return [
        frame.iloc[np.flatnonzero(shard_ids == shard_id)]
        for shard_id in range(workers)
        if bool(np.any(shard_ids == shard_id))
    ]


@lru_cache(maxsize=1)
def _numba_rolling_corr_kernel() -> Any:
    from numba import njit

    @njit
    def kernel(x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
        n = len(x)
        out = np.zeros(n, dtype=np.float64)
        if window <= 0:
            return out
        if n == 0 or window > n:
            return out
        for end in range(window - 1, n):
            start = end - window + 1
            sum_x = 0.0
            sum_y = 0.0
            sum_xx = 0.0
            sum_yy = 0.0
            sum_xy = 0.0
            valid_count = 0
            for i in range(start, end + 1):
                xi = x[i]
                yi = y[i]
                if np.isfinite(xi) and np.isfinite(yi):
                    valid_count += 1
                    sum_x += xi
                    sum_y += yi
                    sum_xx += xi * xi
                    sum_yy += yi * yi
                    sum_xy += xi * yi
            if valid_count != window:
                continue
            cov = sum_xy - (sum_x * sum_y / float(window))
            var_x = sum_xx - (sum_x * sum_x / float(window))
            var_y = sum_yy - (sum_y * sum_y / float(window))
            denom = var_x * var_y
            if denom > 0.0:
                out[end] = cov / np.sqrt(denom)
        return out

    return kernel


@lru_cache(maxsize=1)
def _numba_grouped_rolling_corr_kernel() -> Any:
    from numba import njit, prange

    @njit(parallel=True)
    def kernel(starts: np.ndarray, ends: np.ndarray, x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
        n = len(x)
        out = np.zeros(n, dtype=np.float64)
        if window <= 0:
            return out
        for group_idx in prange(len(starts)):
            group_start = starts[group_idx]
            group_end = ends[group_idx]
            if group_end - group_start < window:
                continue
            for end in range(group_start + window - 1, group_end):
                start = end - window + 1
                sum_x = 0.0
                sum_y = 0.0
                sum_xx = 0.0
                sum_yy = 0.0
                sum_xy = 0.0
                valid_count = 0
                for i in range(start, end + 1):
                    xi = x[i]
                    yi = y[i]
                    if np.isfinite(xi) and np.isfinite(yi):
                        valid_count += 1
                        sum_x += xi
                        sum_y += yi
                        sum_xx += xi * xi
                        sum_yy += yi * yi
                        sum_xy += xi * yi
                if valid_count != window:
                    continue
                cov = sum_xy - (sum_x * sum_y / float(window))
                var_x = sum_xx - (sum_x * sum_x / float(window))
                var_y = sum_yy - (sum_y * sum_y / float(window))
                denom = var_x * var_y
                if denom > 0.0:
                    out[end] = cov / np.sqrt(denom)
        return out

    return kernel


@lru_cache(maxsize=1)
def _numba_grouped_terminal_corr_kernel() -> Any:
    from numba import njit, prange

    @njit(parallel=True)
    def kernel(starts: np.ndarray, ends: np.ndarray, x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
        out = np.zeros(len(starts), dtype=np.float64)
        if window <= 0:
            return out
        for group_idx in prange(len(starts)):
            group_start = starts[group_idx]
            group_end = ends[group_idx]
            if group_end - group_start < window:
                continue
            start = group_end - window
            sum_x = 0.0
            sum_y = 0.0
            sum_xx = 0.0
            sum_yy = 0.0
            sum_xy = 0.0
            valid_count = 0
            for i in range(start, group_end):
                xi = x[i]
                yi = y[i]
                if np.isfinite(xi) and np.isfinite(yi):
                    valid_count += 1
                    sum_x += xi
                    sum_y += yi
                    sum_xx += xi * xi
                    sum_yy += yi * yi
                    sum_xy += xi * yi
            if valid_count != window:
                continue
            cov = sum_xy - (sum_x * sum_y / float(window))
            var_x = sum_xx - (sum_x * sum_x / float(window))
            var_y = sum_yy - (sum_y * sum_y / float(window))
            denom = var_x * var_y
            if denom > 0.0:
                out[group_idx] = cov / np.sqrt(denom)
        return out

    return kernel


def rolling_corr_1d(x: np.ndarray | list[float], y: np.ndarray | list[float], *, window: int, backend: str = 'auto') -> KernelResult:
    left = _as_float_array(x)
    right = _as_float_array(y)
    selected = str(backend or 'auto').lower()
    if selected == 'auto':
        try:
            return KernelResult(_numba_rolling_corr_kernel()(left, right, int(window)), 'numba')
        except Exception:
            return KernelResult(_rolling_corr_numpy(left, right, int(window)), 'numpy')
    if selected == 'numba':
        return KernelResult(_numba_rolling_corr_kernel()(left, right, int(window)), 'numba')
    if selected == 'numpy':
        return KernelResult(_rolling_corr_numpy(left, right, int(window)), 'numpy')
    raise ValueError(f'unsupported rolling_corr backend: {backend}')


def rolling_corr_grouped_arrays(
    starts: np.ndarray | list[int],
    ends: np.ndarray | list[int],
    x: np.ndarray | list[float],
    y: np.ndarray | list[float],
    *,
    window: int,
    backend: str = 'array_grouped',
) -> KernelResult:
    starts_arr = np.asarray(starts, dtype=np.int64)
    ends_arr = np.asarray(ends, dtype=np.int64)
    left = _as_float_array(x)
    right = _as_float_array(y)
    selected = str(backend or 'array_grouped').lower()
    if selected == 'array_grouped':
        return KernelResult(
            _rolling_corr_grouped_vectorized_numpy(starts_arr, ends_arr, left, right, int(window)),
            'array_grouped',
        )
    if selected == 'numba_grouped':
        return KernelResult(
            _numba_grouped_rolling_corr_kernel()(starts_arr, ends_arr, left, right, int(window)),
            'numba_grouped',
        )
    raise ValueError(f'unsupported grouped rolling corr backend: {backend}')


def terminal_corr_grouped_arrays(
    starts: np.ndarray | list[int],
    ends: np.ndarray | list[int],
    x: np.ndarray | list[float],
    y: np.ndarray | list[float],
    *,
    window: int,
    backend: str = 'array_grouped',
) -> KernelResult:
    starts_arr = np.asarray(starts, dtype=np.int64)
    ends_arr = np.asarray(ends, dtype=np.int64)
    left = _as_float_array(x)
    right = _as_float_array(y)
    selected = str(backend or 'array_grouped').lower()
    if selected == 'array_grouped':
        return KernelResult(
            _terminal_corr_grouped_numpy(starts_arr, ends_arr, left, right, int(window)),
            'array_grouped_terminal',
        )
    if selected == 'numba_grouped':
        return KernelResult(
            _numba_grouped_terminal_corr_kernel()(starts_arr, ends_arr, left, right, int(window)),
            'numba_grouped_terminal',
        )
    raise ValueError(f'unsupported grouped terminal corr backend: {backend}')


def _grouped_ema_state_numpy(starts: np.ndarray, ends: np.ndarray, signal: np.ndarray, decay: float) -> np.ndarray:
    if len(starts) != len(ends):
        raise ValueError('starts and ends must have the same length')
    if decay < 0.0 or decay > 1.0:
        raise ValueError('decay must be between 0 and 1')
    out = np.zeros(len(signal), dtype=np.float64)
    carry_weight = float(decay)
    update_weight = 1.0 - carry_weight
    for start, end in zip(starts, ends, strict=True):
        state = 0.0
        initialized = False
        for idx in range(int(start), int(end)):
            value = signal[idx]
            if np.isfinite(value):
                state = float(value) if not initialized else carry_weight * state + update_weight * float(value)
                initialized = True
            out[idx] = state if initialized else 0.0
    return out


def _terminal_ema_state_grouped_numpy(starts: np.ndarray, ends: np.ndarray, signal: np.ndarray, decay: float) -> np.ndarray:
    if len(starts) != len(ends):
        raise ValueError('starts and ends must have the same length')
    if decay < 0.0 or decay > 1.0:
        raise ValueError('decay must be between 0 and 1')
    out = np.zeros(len(starts), dtype=np.float64)
    carry_weight = float(decay)
    update_weight = 1.0 - carry_weight
    for group_idx, (start, end) in enumerate(zip(starts, ends, strict=True)):
        state = 0.0
        initialized = False
        for idx in range(int(start), int(end)):
            value = signal[idx]
            if np.isfinite(value):
                state = float(value) if not initialized else carry_weight * state + update_weight * float(value)
                initialized = True
        out[group_idx] = state if initialized else 0.0
    return out


@lru_cache(maxsize=1)
def _numba_grouped_ema_state_kernel() -> Any:
    from numba import njit, prange

    @njit(parallel=True)
    def kernel(starts: np.ndarray, ends: np.ndarray, signal: np.ndarray, decay: float) -> np.ndarray:
        out = np.zeros(len(signal), dtype=np.float64)
        update_weight = 1.0 - decay
        for group_idx in prange(len(starts)):
            state = 0.0
            initialized = False
            start = starts[group_idx]
            end = ends[group_idx]
            for idx in range(start, end):
                value = signal[idx]
                if np.isfinite(value):
                    if initialized:
                        state = decay * state + update_weight * value
                    else:
                        state = value
                        initialized = True
                out[idx] = state if initialized else 0.0
        return out

    return kernel


@lru_cache(maxsize=1)
def _numba_grouped_terminal_ema_state_kernel() -> Any:
    from numba import njit, prange

    @njit(parallel=True)
    def kernel(starts: np.ndarray, ends: np.ndarray, signal: np.ndarray, decay: float) -> np.ndarray:
        out = np.zeros(len(starts), dtype=np.float64)
        update_weight = 1.0 - decay
        for group_idx in prange(len(starts)):
            state = 0.0
            initialized = False
            start = starts[group_idx]
            end = ends[group_idx]
            for idx in range(start, end):
                value = signal[idx]
                if np.isfinite(value):
                    if initialized:
                        state = decay * state + update_weight * value
                    else:
                        state = value
                        initialized = True
            out[group_idx] = state if initialized else 0.0
        return out

    return kernel


def grouped_ema_state_arrays(
    starts: np.ndarray | list[int],
    ends: np.ndarray | list[int],
    signal: np.ndarray | list[float],
    *,
    decay: float,
    backend: str = 'array_grouped',
) -> KernelResult:
    starts_arr = np.asarray(starts, dtype=np.int64)
    ends_arr = np.asarray(ends, dtype=np.int64)
    signal_arr = _as_float_array(signal)
    selected = str(backend or 'array_grouped').lower()
    if selected == 'array_grouped':
        return KernelResult(
            _grouped_ema_state_numpy(starts_arr, ends_arr, signal_arr, float(decay)),
            'array_grouped_ema_state',
        )
    if selected == 'numba_grouped':
        if float(decay) < 0.0 or float(decay) > 1.0:
            raise ValueError('decay must be between 0 and 1')
        return KernelResult(
            _numba_grouped_ema_state_kernel()(starts_arr, ends_arr, signal_arr, float(decay)),
            'numba_grouped_ema_state',
        )
    raise ValueError(f'unsupported grouped ema state arrays backend: {backend}')


def terminal_ema_state_arrays(
    starts: np.ndarray | list[int],
    ends: np.ndarray | list[int],
    signal: np.ndarray | list[float],
    *,
    decay: float,
    backend: str = 'array_grouped',
) -> KernelResult:
    starts_arr = np.asarray(starts, dtype=np.int64)
    ends_arr = np.asarray(ends, dtype=np.int64)
    signal_arr = _as_float_array(signal)
    selected = str(backend or 'array_grouped').lower()
    if selected == 'array_grouped':
        return KernelResult(
            _terminal_ema_state_grouped_numpy(starts_arr, ends_arr, signal_arr, float(decay)),
            'array_grouped_ema_terminal',
        )
    if selected == 'numba_grouped':
        if float(decay) < 0.0 or float(decay) > 1.0:
            raise ValueError('decay must be between 0 and 1')
        return KernelResult(
            _numba_grouped_terminal_ema_state_kernel()(starts_arr, ends_arr, signal_arr, float(decay)),
            'numba_grouped_ema_terminal',
        )
    raise ValueError(f'unsupported terminal ema state arrays backend: {backend}')


def _ema_state_array_grouped_shard(payload: dict[str, Any]) -> tuple[pd.Index, np.ndarray]:
    frame = payload['frame']
    result = grouped_ema_state_by_group(
        frame,
        group_col=payload['group_col'],
        order_col=payload['order_col'],
        signal_col=payload['signal_col'],
        decay=float(payload['decay']),
        output_col=payload['output_col'],
        backend='array_grouped',
    )
    return frame.index, result[payload['output_col']].to_numpy(dtype=np.float64)


def _terminal_ema_state_array_grouped_shard(payload: dict[str, Any]) -> pd.DataFrame:
    return terminal_ema_state_by_group(
        payload['frame'],
        group_cols=list(payload['group_cols']),
        order_col=payload['order_col'],
        signal_col=payload['signal_col'],
        decay=float(payload['decay']),
        output_col=payload['output_col'],
        backend='array_grouped',
    )


def grouped_ema_state_by_group(
    frame: pd.DataFrame,
    *,
    group_col: str,
    order_col: str,
    signal_col: str,
    decay: float,
    output_col: str = 'ema_state',
    backend: str = 'array_grouped',
    max_workers: int | None = None,
) -> pd.DataFrame:
    required = [group_col, order_col, signal_col]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f'frame missing required columns: {missing}')
    selected = str(backend or 'array_grouped').lower()
    if selected not in {'array_grouped', 'numba_grouped', 'process_sharded_array_grouped'}:
        raise ValueError(f'unsupported grouped ema state backend: {backend}')
    if frame.empty:
        out = frame.copy()
        out[output_col] = np.array([], dtype=np.float64)
        out.attrs['operator_backend'] = f'{selected}_ema_state'
        return out
    work = frame.copy()
    work['_signal'] = pd.to_numeric(work[signal_col], errors='coerce')
    work['_original_pos'] = np.arange(len(work), dtype=np.int64)
    if selected == 'process_sharded_array_grouped':
        out = work.drop(columns=['_signal']).copy()
        out[output_col] = 0.0
        workers = max(1, int(max_workers or 1))
        shards = _build_coarse_group_shards(out, [group_col], workers)
        if not shards:
            out.attrs['operator_backend'] = 'process_sharded_array_grouped_ema_state'
            return out.drop(columns=['_original_pos']).reset_index(drop=True)
        payloads = [
            {
                'frame': shard,
                'group_col': group_col,
                'order_col': order_col,
                'signal_col': signal_col,
                'decay': float(decay),
                'output_col': output_col,
            }
            for shard in shards
        ]
        if workers == 1 or len(payloads) == 1:
            pieces = [_ema_state_array_grouped_shard(payload) for payload in payloads]
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                pieces = list(executor.map(_ema_state_array_grouped_shard, payloads))
        for shard_index, values in pieces:
            out.loc[shard_index, output_col] = values
        out = out.sort_values('_original_pos').drop(columns=['_original_pos']).reset_index(drop=True)
        out.attrs['operator_backend'] = 'process_sharded_array_grouped_ema_state'
        return out
    ordered = work.sort_values([group_col, order_col, '_original_pos']).reset_index(drop=True)
    offsets = group_offsets_from_sorted_frame(ordered, [group_col])
    result = grouped_ema_state_arrays(
        offsets.starts,
        offsets.ends,
        ordered['_signal'].to_numpy(dtype=np.float64),
        decay=float(decay),
        backend=selected,
    )
    ordered[output_col] = result.values
    restored = ordered.sort_values('_original_pos').drop(columns=['_signal', '_original_pos']).reset_index(drop=True)
    restored.attrs['operator_backend'] = result.backend
    return restored


def terminal_ema_state_by_group(
    frame: pd.DataFrame,
    *,
    group_cols: list[str],
    order_col: str,
    signal_col: str,
    decay: float,
    output_col: str = 'terminal_ema_state',
    backend: str = 'array_grouped',
    max_workers: int | None = None,
) -> pd.DataFrame:
    if not group_cols:
        raise ValueError('group_cols must not be empty')
    required = [*group_cols, order_col, signal_col]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f'frame missing required columns: {missing}')
    selected = str(backend or 'array_grouped').lower()
    if selected not in {'array_grouped', 'numba_grouped', 'process_sharded_array_grouped'}:
        raise ValueError(f'unsupported terminal ema state backend: {backend}')
    ordered_cols = [*group_cols, 'terminal_order', 'bar_count', output_col]
    work = frame.copy()
    work['_signal'] = pd.to_numeric(work[signal_col], errors='coerce')
    ordered = work.sort_values([*group_cols, order_col]).reset_index(drop=True)
    if selected == 'process_sharded_array_grouped':
        workers = max(1, int(max_workers or 1))
        group_count = int(ordered[group_cols].drop_duplicates().shape[0])
        shard_count = min(workers, group_count) if group_count else 0
        shards = _build_coarse_group_shards(ordered, list(group_cols), shard_count)
        if not shards:
            out = pd.DataFrame(columns=ordered_cols)
            out.attrs['operator_backend'] = 'process_sharded_array_grouped_ema_terminal'
            return out
        payloads = [
            {
                'frame': shard,
                'group_cols': list(group_cols),
                'order_col': order_col,
                'signal_col': signal_col,
                'decay': float(decay),
                'output_col': output_col,
            }
            for shard in shards
        ]
        if workers == 1 or len(payloads) <= 1:
            shard_results = [_terminal_ema_state_array_grouped_shard(payload) for payload in payloads]
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                shard_results = list(executor.map(_terminal_ema_state_array_grouped_shard, payloads))
        out = pd.concat(shard_results, axis=0) if shard_results else pd.DataFrame(columns=ordered_cols)
        out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
        out.attrs['operator_backend'] = 'process_sharded_array_grouped_ema_terminal'
        return out

    offsets = group_offsets_from_sorted_frame(ordered, group_cols)
    if len(offsets.starts) == 0:
        out = pd.DataFrame(columns=ordered_cols)
        out.attrs['operator_backend'] = 'numba_grouped_ema_terminal' if selected == 'numba_grouped' else 'array_grouped_ema_terminal'
        return out
    order_values = ordered[order_col].to_numpy()
    terminal_orders = order_values[offsets.ends - 1]
    result = terminal_ema_state_arrays(
        offsets.starts,
        offsets.ends,
        ordered['_signal'].to_numpy(dtype=np.float64),
        decay=float(decay),
        backend=selected,
    )
    out = ordered.iloc[offsets.starts][group_cols].reset_index(drop=True)
    out['terminal_order'] = terminal_orders
    out['bar_count'] = offsets.sizes
    out[output_col] = result.values
    out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
    out.attrs['operator_backend'] = result.backend
    return out


def rolling_corr_by_group(
    frame: pd.DataFrame,
    *,
    group_col: str,
    order_col: str,
    x_col: str,
    y_col: str,
    window: int,
    output_col: str,
    backend: str = 'auto',
    max_workers: int | None = None,
) -> pd.DataFrame:
    missing = [col for col in [group_col, order_col, x_col, y_col] if col not in frame.columns]
    if missing:
        raise ValueError(f'frame missing required columns: {missing}')
    out = frame.copy()
    out[output_col] = 0.0
    selected = str(backend or 'auto').lower()
    if selected == 'array_grouped':
        ordered = out.sort_values([group_col, order_col]).copy()
        offsets = group_offsets_from_sorted_frame(ordered, [group_col])
        values = _rolling_corr_grouped_numpy(
            offsets.starts,
            offsets.ends,
            ordered[x_col].to_numpy(dtype=np.float64),
            ordered[y_col].to_numpy(dtype=np.float64),
            int(window),
        )
        out.loc[ordered.index, output_col] = values
        out.attrs['operator_backend'] = 'array_grouped'
        return out
    if selected == 'process_sharded_array_grouped':
        workers = max(1, int(max_workers or 1))
        group_count = int(out[group_col].nunique(dropna=False))
        shard_count = min(workers, group_count) if group_count else 0
        shards = _build_coarse_group_shards(out, [group_col], shard_count)
        if not shards:
            out.attrs['operator_backend'] = 'process_sharded_array_grouped'
            return out
        payloads = [
            {
                'frame': shard,
                'group_col': group_col,
                'order_col': order_col,
                'x_col': x_col,
                'y_col': y_col,
                'window': int(window),
                'output_col': output_col,
            }
            for shard in shards
        ]
        if workers == 1 or len(payloads) <= 1:
            shard_results = [_rolling_corr_array_grouped_shard(payload) for payload in payloads]
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                shard_results = list(executor.map(_rolling_corr_array_grouped_shard, payloads))
        for shard_index, values in shard_results:
            out.loc[shard_index, output_col] = values
        out.attrs['operator_backend'] = 'process_sharded_array_grouped'
        return out
    if selected == 'numba_grouped':
        ordered = out.sort_values([group_col, order_col]).copy()
        offsets = group_offsets_from_sorted_frame(ordered, [group_col])
        values = _numba_grouped_rolling_corr_kernel()(
            offsets.starts,
            offsets.ends,
            ordered[x_col].to_numpy(dtype=np.float64),
            ordered[y_col].to_numpy(dtype=np.float64),
            int(window),
        )
        out.loc[ordered.index, output_col] = values
        out.attrs['operator_backend'] = 'numba_grouped'
        return out
    if selected == 'threaded_grouped':
        ordered = out.sort_values([group_col, order_col]).copy()
        groups = [
            group for _, group in ordered.groupby(group_col, sort=False)
        ]

        def compute_group(group: pd.DataFrame) -> tuple[pd.Index, np.ndarray]:
            result = rolling_corr_1d(
                group[x_col].to_numpy(dtype=np.float64),
                group[y_col].to_numpy(dtype=np.float64),
                window=window,
                backend='numpy',
            )
            return group.index, result.values

        workers = max(1, int(max_workers or 1))
        if workers == 1 or len(groups) <= 1:
            group_results = [compute_group(group) for group in groups]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                group_results = list(executor.map(compute_group, groups))
        for group_index, values in group_results:
            out.loc[group_index, output_col] = values
        out.attrs['operator_backend'] = 'threaded_grouped'
        return out
    realized_backend = ''
    for _, group in out.sort_values([group_col, order_col]).groupby(group_col, sort=False):
        result = rolling_corr_1d(
            group[x_col].to_numpy(dtype=np.float64),
            group[y_col].to_numpy(dtype=np.float64),
            window=window,
            backend=backend,
        )
        realized_backend = result.backend
        out.loc[group.index, output_col] = result.values
    out.attrs['operator_backend'] = realized_backend or str(backend)
    return out


def cpv_price_volume_corr_state(
    frame: pd.DataFrame,
    *,
    window: int,
    backend: str = 'array_grouped',
    max_workers: int | None = None,
    trade_date_col: str = 'trade_date',
    ts_code_col: str = 'ts_code',
    order_col: str = 'hhmmss',
    price_col: str = 'price',
    volume_col: str = 'volume',
    output_col: str = 'cpv_corr',
    terminal_only: bool = False,
) -> pd.DataFrame:
    if terminal_only:
        out = terminal_rolling_corr_by_group(
            frame,
            group_cols=[trade_date_col, ts_code_col],
            order_col=order_col,
            x_col=price_col,
            y_col=volume_col,
            window=window,
            output_col=output_col,
            backend=backend,
            max_workers=max_workers,
        )
        out.attrs['operator_id'] = 'cpv_price_volume_corr_state'
        out.attrs['source_operator'] = 'terminal_rolling_corr_by_group'
        out.attrs['terminal_only'] = True
        out.attrs['window'] = int(window)
        return out

    out = rolling_corr_by_group(
        frame,
        group_col=ts_code_col,
        order_col=order_col,
        x_col=price_col,
        y_col=volume_col,
        window=window,
        output_col=output_col,
        backend=backend,
        max_workers=max_workers,
    )
    out.attrs['operator_id'] = 'cpv_price_volume_corr_state'
    out.attrs['source_operator'] = 'rolling_corr_by_group'
    out.attrs['terminal_only'] = False
    out.attrs['window'] = int(window)
    return out


def _terminal_corr_from_arrays(x_values: np.ndarray, y_values: np.ndarray, window: int) -> float:
    size = int(window)
    x = x_values[-size:].astype(np.float64, copy=False)
    y = y_values[-size:].astype(np.float64, copy=False)
    if len(x) < size or len(y) < size:
        return 0.0
    valid = np.isfinite(x) & np.isfinite(y)
    if int(valid.sum()) != size:
        return 0.0
    sum_x = float(x.sum())
    sum_y = float(y.sum())
    sum_xx = float((x * x).sum())
    sum_yy = float((y * y).sum())
    sum_xy = float((x * y).sum())
    cov = sum_xy - (sum_x * sum_y / float(size))
    var_x = sum_xx - (sum_x * sum_x / float(size))
    var_y = sum_yy - (sum_y * sum_y / float(size))
    denom = var_x * var_y
    return float(cov / np.sqrt(denom)) if denom > 0.0 else 0.0


def _terminal_corr_grouped_numpy(starts: np.ndarray, ends: np.ndarray, x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    size = int(window)
    if size <= 0:
        raise ValueError('window must be positive')
    out = np.zeros(len(starts), dtype=np.float64)
    if len(x) != len(y):
        raise ValueError('x and y must have the same length')
    if len(starts) != len(ends):
        raise ValueError('starts and ends must have the same length')
    if len(starts) == 0:
        return out

    valid = np.isfinite(x) & np.isfinite(y)
    clean_x = np.where(valid, x, 0.0)
    clean_y = np.where(valid, y, 0.0)
    count = np.concatenate(([0], np.cumsum(valid.astype(np.int64))))
    sx = np.concatenate(([0.0], np.cumsum(clean_x)))
    sy = np.concatenate(([0.0], np.cumsum(clean_y)))
    sxx = np.concatenate(([0.0], np.cumsum(clean_x * clean_x)))
    syy = np.concatenate(([0.0], np.cumsum(clean_y * clean_y)))
    sxy = np.concatenate(([0.0], np.cumsum(clean_x * clean_y)))

    group_sizes = ends - starts
    eligible = group_sizes >= size
    if not bool(np.any(eligible)):
        return out
    end_plus = ends[eligible]
    start_idx = end_plus - size
    cnt = count[end_plus] - count[start_idx]
    sum_x = sx[end_plus] - sx[start_idx]
    sum_y = sy[end_plus] - sy[start_idx]
    sum_xx = sxx[end_plus] - sxx[start_idx]
    sum_yy = syy[end_plus] - syy[start_idx]
    sum_xy = sxy[end_plus] - sxy[start_idx]
    cov = sum_xy - (sum_x * sum_y / float(size))
    var_x = sum_xx - (sum_x * sum_x / float(size))
    var_y = sum_yy - (sum_y * sum_y / float(size))
    denom = var_x * var_y
    good = (cnt == size) & (denom > 0.0)
    values = np.zeros_like(cov, dtype=np.float64)
    values[good] = cov[good] / np.sqrt(denom[good])
    out[np.flatnonzero(eligible)] = values
    return out


def _terminal_corr_for_group(group: pd.DataFrame, *, x_col: str, y_col: str, window: int) -> float:
    return _terminal_corr_from_arrays(
        group[x_col].to_numpy(dtype=np.float64),
        group[y_col].to_numpy(dtype=np.float64),
        window,
    )


def terminal_rolling_corr_by_group(
    frame: pd.DataFrame,
    *,
    group_cols: list[str],
    order_col: str,
    x_col: str,
    y_col: str,
    window: int,
    output_col: str,
    backend: str = 'numpy',
    max_workers: int | None = None,
) -> pd.DataFrame:
    required = [*group_cols, order_col, x_col, y_col]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f'frame missing required columns: {missing}')
    selected = str(backend or 'numpy').lower()
    if selected not in {'numpy', 'threaded_grouped', 'array_grouped', 'numba_grouped', 'process_sharded_array_grouped'}:
        raise ValueError(f'unsupported terminal rolling corr backend: {backend}')
    ordered = frame.sort_values([*group_cols, order_col]).copy()
    ordered_cols = [*group_cols, 'terminal_order', 'bar_count', output_col]
    if selected == 'process_sharded_array_grouped':
        workers = max(1, int(max_workers or 1))
        group_count = int(ordered[group_cols].drop_duplicates().shape[0])
        shard_count = min(workers, group_count) if group_count else 0
        shards = _build_coarse_group_shards(ordered, list(group_cols), shard_count)
        if not shards:
            out = pd.DataFrame(columns=ordered_cols)
            out.attrs['operator_backend'] = 'process_sharded_array_grouped_terminal'
            return out
        payloads = [
            {
                'frame': shard,
                'group_cols': list(group_cols),
                'order_col': order_col,
                'x_col': x_col,
                'y_col': y_col,
                'window': int(window),
                'output_col': output_col,
            }
            for shard in shards
        ]
        if workers == 1 or len(payloads) <= 1:
            shard_results = [_terminal_corr_array_grouped_shard(payload) for payload in payloads]
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                shard_results = list(executor.map(_terminal_corr_array_grouped_shard, payloads))
        out = pd.concat(shard_results, axis=0) if shard_results else pd.DataFrame(columns=ordered_cols)
        out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
        out.attrs['operator_backend'] = 'process_sharded_array_grouped_terminal'
        return out
    if selected in {'array_grouped', 'numba_grouped'}:
        offsets = group_offsets_from_sorted_frame(ordered, group_cols)
        if len(offsets.starts) == 0:
            out = pd.DataFrame(columns=ordered_cols)
            out.attrs['operator_backend'] = 'numba_grouped_terminal' if selected == 'numba_grouped' else 'array_grouped_terminal'
            return out
        x_values = ordered[x_col].to_numpy(dtype=np.float64)
        y_values = ordered[y_col].to_numpy(dtype=np.float64)
        order_values = ordered[order_col].to_numpy()
        terminal_orders = order_values[offsets.ends - 1]
        if selected == 'numba_grouped':
            terminal_corrs = _numba_grouped_terminal_corr_kernel()(offsets.starts, offsets.ends, x_values, y_values, int(window))
        else:
            terminal_corrs = _terminal_corr_grouped_numpy(offsets.starts, offsets.ends, x_values, y_values, int(window))
        out = ordered.iloc[offsets.starts][group_cols].reset_index(drop=True)
        out['terminal_order'] = terminal_orders
        out['bar_count'] = offsets.sizes
        out[output_col] = terminal_corrs
        out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
        out.attrs['operator_backend'] = 'numba_grouped_terminal' if selected == 'numba_grouped' else 'array_grouped_terminal'
        return out

    groups = [
        (key, group)
        for key, group in ordered.groupby(group_cols, sort=True)
    ]

    def compute_group(item: tuple[Any, pd.DataFrame]) -> dict[str, Any]:
        key, group = item
        if not isinstance(key, tuple):
            key = (key,)
        row: dict[str, Any] = {col: key[idx] for idx, col in enumerate(group_cols)}
        row['terminal_order'] = group[order_col].iloc[-1] if len(group) else None
        row['bar_count'] = int(len(group))
        row[output_col] = _terminal_corr_for_group(group, x_col=x_col, y_col=y_col, window=window)
        return row

    workers = max(1, int(max_workers or 1))
    if selected == 'threaded_grouped' and workers > 1 and len(groups) > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            rows = list(executor.map(compute_group, groups))
    else:
        rows = [compute_group(group) for group in groups]
    out = pd.DataFrame(rows)
    if out.empty:
        out = pd.DataFrame(columns=ordered_cols)
    else:
        out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
    out.attrs['operator_backend'] = 'threaded_grouped_terminal' if selected == 'threaded_grouped' else 'numpy_terminal'
    return out


def _occupation_location_grouped_numpy(
    starts: np.ndarray,
    ends: np.ndarray,
    price: np.ndarray,
    volume: np.ndarray,
    amount: np.ndarray,
) -> np.ndarray:
    if len(price) != len(volume) or len(price) != len(amount):
        raise ValueError('price, volume, and amount must have the same length')
    if len(starts) != len(ends):
        raise ValueError('starts and ends must have the same length')
    out = np.zeros((len(starts), 6), dtype=np.float64)
    if len(starts) == 0:
        return out
    valid_price = np.isfinite(price)
    clean_price = np.where(valid_price, price, 0.0)
    clean_amount = np.where(valid_price & np.isfinite(amount), amount, 0.0)
    clean_volume = np.where(valid_price & np.isfinite(volume), volume, 0.0)
    count_prefix = np.concatenate(([0.0], np.cumsum(valid_price.astype(np.float64))))
    price_prefix = np.concatenate(([0.0], np.cumsum(clean_price)))
    amount_prefix = np.concatenate(([0.0], np.cumsum(clean_amount)))
    volume_prefix = np.concatenate(([0.0], np.cumsum(clean_volume)))

    counts = count_prefix[ends] - count_prefix[starts]
    price_sums = price_prefix[ends] - price_prefix[starts]
    amount_sums = amount_prefix[ends] - amount_prefix[starts]
    volume_sums = volume_prefix[ends] - volume_prefix[starts]
    twap = np.zeros(len(starts), dtype=np.float64)
    np.divide(price_sums, counts, out=twap, where=counts > 0.0)
    vwap = np.zeros(len(starts), dtype=np.float64)
    np.divide(amount_sums, volume_sums, out=vwap, where=volume_sums > 0.0)
    out[:, 0] = counts
    out[:, 1] = amount_sums
    out[:, 2] = volume_sums
    out[:, 3] = twap
    out[:, 4] = vwap
    out[:, 5] = vwap - twap
    return out


def occupation_location_grouped_arrays(
    starts: np.ndarray | list[int],
    ends: np.ndarray | list[int],
    price: np.ndarray | list[float],
    volume: np.ndarray | list[float],
    *,
    amount: np.ndarray | list[float] | None = None,
    backend: str = 'array_grouped',
) -> KernelResult:
    starts_arr = np.asarray(starts, dtype=np.int64)
    ends_arr = np.asarray(ends, dtype=np.int64)
    price_arr = _as_float_array(price)
    volume_arr = _as_float_array(volume)
    amount_arr = price_arr * volume_arr if amount is None else _as_float_array(amount)
    selected = str(backend or 'array_grouped').lower()
    if selected == 'array_grouped':
        return KernelResult(
            _occupation_location_grouped_numpy(starts_arr, ends_arr, price_arr, volume_arr, amount_arr),
            'array_grouped_occupation',
        )
    if selected == 'numba_grouped':
        return KernelResult(
            _numba_grouped_occupation_location_kernel()(starts_arr, ends_arr, price_arr, volume_arr, amount_arr),
            'numba_grouped_occupation',
        )
    raise ValueError(f'unsupported occupation location grouped arrays backend: {backend}')


def _occupation_location_array_grouped_frame(work: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    ordered_cols = [*group_cols, 'bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap']
    if work.empty:
        out = pd.DataFrame(columns=ordered_cols)
        out.attrs['operator_backend'] = 'array_grouped_occupation'
        return out
    ordered = work.sort_values(group_cols).reset_index(drop=True)
    offsets = group_offsets_from_sorted_frame(ordered, group_cols)
    values = occupation_location_grouped_arrays(
        offsets.starts,
        offsets.ends,
        ordered['_price'].to_numpy(dtype=np.float64),
        ordered['_volume'].to_numpy(dtype=np.float64),
        amount=ordered['_amount'].to_numpy(dtype=np.float64),
        backend='array_grouped',
    ).values
    out = ordered.iloc[offsets.starts][group_cols].reset_index(drop=True)
    out['bar_count'] = values[:, 0].astype(int)
    out['amount_sum'] = values[:, 1]
    out['volume_sum'] = values[:, 2]
    out['twap'] = values[:, 3]
    out['vwap'] = values[:, 4]
    out['vwap_minus_twap'] = values[:, 5]
    out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
    out.attrs['operator_backend'] = 'array_grouped_occupation'
    return out


def _occupation_array_grouped_shard(payload: dict[str, Any]) -> pd.DataFrame:
    return _occupation_location_array_grouped_frame(
        payload['frame'],
        list(payload['group_cols']),
    )


@lru_cache(maxsize=1)
def _numba_grouped_occupation_location_kernel() -> Any:
    from numba import njit, prange

    @njit(parallel=True)
    def kernel(starts: np.ndarray, ends: np.ndarray, price: np.ndarray, volume: np.ndarray, amount: np.ndarray) -> np.ndarray:
        out = np.zeros((len(starts), 6), dtype=np.float64)
        for group_idx in prange(len(starts)):
            start = starts[group_idx]
            end = ends[group_idx]
            count = 0.0
            price_sum = 0.0
            amount_sum = 0.0
            volume_sum = 0.0
            for i in range(start, end):
                p = price[i]
                if np.isfinite(p):
                    count += 1.0
                    price_sum += p
                    amount_sum += amount[i] if np.isfinite(amount[i]) else 0.0
                    volume_sum += volume[i] if np.isfinite(volume[i]) else 0.0
            twap = price_sum / count if count > 0.0 else 0.0
            vwap = amount_sum / volume_sum if volume_sum > 0.0 else 0.0
            out[group_idx, 0] = count
            out[group_idx, 1] = amount_sum
            out[group_idx, 2] = volume_sum
            out[group_idx, 3] = twap
            out[group_idx, 4] = vwap
            out[group_idx, 5] = vwap - twap
        return out

    return kernel


def intraday_occupation_location_state(
    frame: pd.DataFrame,
    *,
    group_cols: list[str],
    price_col: str,
    volume_col: str,
    amount_col: str | None = None,
    backend: str = 'pandas',
    max_workers: int | None = None,
) -> pd.DataFrame:
    required = [*group_cols, price_col, volume_col]
    if amount_col:
        required.append(amount_col)
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f'frame missing required columns: {missing}')
    work = frame.copy()
    work['_price'] = pd.to_numeric(work[price_col], errors='coerce')
    work['_volume'] = pd.to_numeric(work[volume_col], errors='coerce').fillna(0.0)
    if amount_col:
        work['_amount'] = pd.to_numeric(work[amount_col], errors='coerce').fillna(0.0)
    else:
        work['_amount'] = work['_price'] * work['_volume']
    work = work.dropna(subset=['_price'])
    selected = str(backend or 'pandas').lower()
    if selected == 'process_sharded_array_grouped':
        ordered_cols = [*group_cols, 'bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap']
        workers = max(1, int(max_workers or 1))
        shards = _build_coarse_group_shards(work, group_cols, workers)
        if not shards:
            out = pd.DataFrame(columns=ordered_cols)
            out.attrs['operator_backend'] = 'process_sharded_array_grouped_occupation'
            return out
        if workers == 1 or len(shards) == 1:
            pieces = [_occupation_location_array_grouped_frame(shard, group_cols) for shard in shards]
        else:
            payloads = [
                {
                    'frame': shard,
                    'group_cols': group_cols,
                }
                for shard in shards
            ]
            with ProcessPoolExecutor(max_workers=workers) as executor:
                pieces = list(executor.map(_occupation_array_grouped_shard, payloads))
        out = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=ordered_cols)
        out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
        out.attrs['operator_backend'] = 'process_sharded_array_grouped_occupation'
        return out
    if selected == 'array_grouped':
        return _occupation_location_array_grouped_frame(work, group_cols)
    if selected == 'threaded_grouped':
        groups = [
            (key, group)
            for key, group in work.sort_values(group_cols).groupby(group_cols, sort=True)
        ]

        def compute_group(item: tuple[Any, pd.DataFrame]) -> dict[str, Any]:
            key, group = item
            if not isinstance(key, tuple):
                key = (key,)
            bar_count = int(group['_price'].size)
            volume_sum = float(group['_volume'].sum())
            amount_sum = float(group['_amount'].sum())
            twap = float(group['_price'].mean()) if bar_count else 0.0
            vwap = amount_sum / volume_sum if volume_sum > 0.0 else 0.0
            row: dict[str, Any] = {col: key[idx] for idx, col in enumerate(group_cols)}
            row.update({
                'bar_count': bar_count,
                'amount_sum': amount_sum,
                'volume_sum': volume_sum,
                'twap': twap,
                'vwap': vwap,
                'vwap_minus_twap': vwap - twap,
            })
            return row

        workers = max(1, int(max_workers or 1))
        if workers == 1 or len(groups) <= 1:
            rows = [compute_group(group) for group in groups]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                rows = list(executor.map(compute_group, groups))
        out = pd.DataFrame(rows)
        ordered_cols = [*group_cols, 'bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap']
        if out.empty:
            out = pd.DataFrame(columns=ordered_cols)
        else:
            out = out[ordered_cols].sort_values(group_cols).reset_index(drop=True)
        out.attrs['operator_backend'] = 'threaded_grouped'
        return out
    if selected == 'numba_grouped':
        group_keys = work[group_cols].drop_duplicates().sort_values(group_cols).reset_index(drop=True)
        ordered = work.sort_values(group_cols).copy()
        group_sizes = ordered.groupby(group_cols, sort=True).size().to_numpy(dtype=np.int64)
        ends = np.cumsum(group_sizes, dtype=np.int64)
        starts = ends - group_sizes
        values = _numba_grouped_occupation_location_kernel()(
            starts,
            ends,
            ordered['_price'].to_numpy(dtype=np.float64),
            ordered['_volume'].to_numpy(dtype=np.float64),
            ordered['_amount'].to_numpy(dtype=np.float64),
        )
        out = group_keys.copy()
        out['bar_count'] = values[:, 0].astype(int)
        out['amount_sum'] = values[:, 1]
        out['volume_sum'] = values[:, 2]
        out['twap'] = values[:, 3]
        out['vwap'] = values[:, 4]
        out['vwap_minus_twap'] = values[:, 5]
        out.attrs['operator_backend'] = 'numba_grouped'
        return out[[*group_cols, 'bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap']]
    if selected != 'pandas':
        raise ValueError(f'unsupported occupation location backend: {backend}')
    grouped = work.groupby(group_cols, sort=True)
    out = grouped.agg(
        bar_count=('_price', 'size'),
        twap=('_price', 'mean'),
        amount_sum=('_amount', 'sum'),
        volume_sum=('_volume', 'sum'),
    ).reset_index()
    out['vwap'] = np.where(out['volume_sum'] > 0, out['amount_sum'] / out['volume_sum'], 0.0)
    out['vwap_minus_twap'] = out['vwap'] - out['twap']
    ordered_cols = [*group_cols, 'bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap']
    out = out[ordered_cols]
    out.attrs['operator_backend'] = 'pandas_grouped'
    return out
