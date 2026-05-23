from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from factor_factory.formula import operators
from factor_factory.formula.ts_rank_candidates import (
    CandidateResult,
    available_candidates as available_ts_rank_candidates,
    compare_candidate_to_reference,
    prepare_ts_rank_frame,
)


@dataclass(frozen=True)
class OperatorCandidateResult:
    operator: str
    candidate: str
    status: str
    values: pd.Series | None
    skip_reason: str | None = None
    failure_reason: str | None = None
    experimental: bool = True
    safe_to_wire_into_step3b: bool = False


def reference_argmin(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult:
    values = pd.to_numeric(frame[value_col], errors='coerce')
    return OperatorCandidateResult('ts_argmin', 'pandas_reference', 'PASS', operators.ts_argmin(values, window, frame), experimental=False)


def reference_argmax(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult:
    values = pd.to_numeric(frame[value_col], errors='coerce')
    return OperatorCandidateResult('ts_argmax', 'pandas_reference', 'PASS', operators.ts_argmax(values, window, frame), experimental=False)


def reference_corr(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult:
    left = pd.to_numeric(frame[left_col], errors='coerce')
    right = pd.to_numeric(frame[right_col], errors='coerce')
    return OperatorCandidateResult('rolling_corr', 'pandas_reference', 'PASS', operators.rolling_corr(left, right, window, frame), experimental=False)


def reference_cov(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult:
    left = pd.to_numeric(frame[left_col], errors='coerce')
    right = pd.to_numeric(frame[right_col], errors='coerce')
    return OperatorCandidateResult('rolling_cov', 'pandas_reference', 'PASS', operators.rolling_cov(left, right, window, frame), experimental=False)


def _rolling_arg_one(values: np.ndarray, window: int, mode: str) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype='float64')
    if window <= 0 or len(values) < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values, window_shape=window)
    valid = ~np.isnan(windows).any(axis=1)
    if not valid.any():
        return out
    if mode == 'argmin':
        raw = np.argmin(windows[valid], axis=1)
    elif mode == 'argmax':
        raw = np.argmax(windows[valid], axis=1)
    else:
        raise ValueError(f'unsupported arg mode: {mode}')
    out[np.flatnonzero(valid) + window - 1] = raw.astype('float64') + 1.0
    return out


def _group_positions(frame: pd.DataFrame) -> list[np.ndarray]:
    codes = frame['ts_code'].to_numpy()
    return [np.flatnonzero(codes == code) for code in pd.unique(frame['ts_code'])]


def numpy_argmin_per_ticker(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult:
    values = pd.to_numeric(frame[value_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    out = np.full(len(frame), np.nan, dtype='float64')
    for positions in _group_positions(frame):
        if len(positions):
            out[positions] = _rolling_arg_one(values[positions], window, 'argmin')
    return OperatorCandidateResult('ts_argmin', 'numpy_argmin_per_ticker', 'PASS', pd.Series(out, index=frame.index, name=value_col))


def numpy_argmax_per_ticker(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult:
    values = pd.to_numeric(frame[value_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    out = np.full(len(frame), np.nan, dtype='float64')
    for positions in _group_positions(frame):
        if len(positions):
            out[positions] = _rolling_arg_one(values[positions], window, 'argmax')
    return OperatorCandidateResult('ts_argmax', 'numpy_argmax_per_ticker', 'PASS', pd.Series(out, index=frame.index, name=value_col))


def _rolling_pairwise_one(left: np.ndarray, right: np.ndarray, window: int, mode: str) -> np.ndarray:
    out = np.full(len(left), np.nan, dtype='float64')
    if window <= 1 or len(left) < window:
        return out
    lw = np.lib.stride_tricks.sliding_window_view(left, window_shape=window)
    rw = np.lib.stride_tricks.sliding_window_view(right, window_shape=window)
    valid = (~np.isnan(lw).any(axis=1)) & (~np.isnan(rw).any(axis=1))
    if not valid.any():
        return out
    lx = lw[valid]
    ry = rw[valid]
    lx_mean = lx.mean(axis=1)
    ry_mean = ry.mean(axis=1)
    lx_centered = lx - lx_mean[:, None]
    ry_centered = ry - ry_mean[:, None]
    cov = (lx_centered * ry_centered).sum(axis=1) / float(window - 1)
    if mode == 'cov':
        values = cov
    elif mode == 'corr':
        var_l = (lx_centered * lx_centered).sum(axis=1) / float(window - 1)
        var_r = (ry_centered * ry_centered).sum(axis=1) / float(window - 1)
        denom = np.sqrt(var_l * var_r)
        values = np.full(len(cov), np.nan, dtype='float64')
        nonzero = denom != 0.0
        values[nonzero] = cov[nonzero] / denom[nonzero]
    else:
        raise ValueError(f'unsupported pairwise mode: {mode}')
    out[np.flatnonzero(valid) + window - 1] = values
    return out


def numpy_corr_formula_per_ticker(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult:
    left = pd.to_numeric(frame[left_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    right = pd.to_numeric(frame[right_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    out = np.full(len(frame), np.nan, dtype='float64')
    ordered_positions: list[np.ndarray] = []
    for positions in _group_positions(frame):
        if len(positions):
            out[positions] = _rolling_pairwise_one(left[positions], right[positions], window, 'corr')
            ordered_positions.append(positions)
    order = np.concatenate(ordered_positions) if ordered_positions else np.array([], dtype=int)
    return OperatorCandidateResult('rolling_corr', 'numpy_corr_formula_per_ticker', 'PASS', pd.Series(out[order], index=frame.index[order], name=left_col))


def numpy_cov_formula_per_ticker(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult:
    left = pd.to_numeric(frame[left_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    right = pd.to_numeric(frame[right_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    out = np.full(len(frame), np.nan, dtype='float64')
    ordered_positions: list[np.ndarray] = []
    for positions in _group_positions(frame):
        if len(positions):
            out[positions] = _rolling_pairwise_one(left[positions], right[positions], window, 'cov')
            ordered_positions.append(positions)
    order = np.concatenate(ordered_positions) if ordered_positions else np.array([], dtype=int)
    return OperatorCandidateResult('rolling_cov', 'numpy_cov_formula_per_ticker', 'PASS', pd.Series(out[order], index=frame.index[order], name=left_col))


def compare_series_to_reference(
    frame: pd.DataFrame,
    reference: pd.Series,
    candidate: pd.Series,
    *,
    tolerance: float,
) -> dict:
    ref = pd.to_numeric(reference, errors='coerce')
    cand = pd.to_numeric(candidate, errors='coerce')
    row_count_equal = int(len(ref)) == int(len(cand)) == int(len(frame))
    key_order_equal = bool(row_count_equal and ref.index.equals(cand.index))
    nan_mask_equal = bool(ref.isna().equals(cand.isna()))
    valid = ref.notna() & cand.notna()
    max_abs_diff = float((ref[valid] - cand[valid]).abs().max()) if int(valid.sum()) else 0.0
    if int(valid.sum()) >= 2:
        rank_corr_raw = ref[valid].rank(method='average').corr(cand[valid].rank(method='average'), method='pearson')
        rank_corr = float(rank_corr_raw) if pd.notna(rank_corr_raw) else None
    else:
        rank_corr = None
    return {
        'row_count_equal': row_count_equal,
        'key_order_equal': key_order_equal,
        'nan_mask_equal': nan_mask_equal,
        'max_abs_diff': max_abs_diff,
        'rank_corr': rank_corr,
        'parity_pass': bool(row_count_equal and key_order_equal and nan_mask_equal and max_abs_diff <= tolerance),
    }


def available_operator_candidates() -> dict[str, dict[str, Callable]]:
    return {
        'ts_argmin': {
            'pandas_reference': reference_argmin,
            'numpy_argmin_per_ticker': numpy_argmin_per_ticker,
        },
        'ts_argmax': {
            'pandas_reference': reference_argmax,
            'numpy_argmax_per_ticker': numpy_argmax_per_ticker,
        },
        'rolling_corr': {
            'pandas_reference': reference_corr,
            'numpy_corr_formula_per_ticker': numpy_corr_formula_per_ticker,
        },
        'rolling_cov': {
            'pandas_reference': reference_cov,
            'numpy_cov_formula_per_ticker': numpy_cov_formula_per_ticker,
        },
    }


def available_all_candidates(include_ts_rank: bool = False) -> dict[str, dict[str, Callable]]:
    candidates = available_operator_candidates()
    if include_ts_rank:
        candidates['ts_rank'] = available_ts_rank_candidates()
    return candidates


__all__ = [
    'CandidateResult',
    'OperatorCandidateResult',
    'available_all_candidates',
    'available_operator_candidates',
    'available_ts_rank_candidates',
    'compare_candidate_to_reference',
    'compare_series_to_reference',
    'prepare_ts_rank_frame',
]
