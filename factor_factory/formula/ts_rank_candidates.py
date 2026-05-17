from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .fast_rolling import _ts_rank_one_array, last_value_pct_rank_reference, ts_rank_fast_numpy, ts_rank_reference


@dataclass(frozen=True)
class CandidateResult:
    name: str
    status: str
    values: pd.Series | None
    skip_reason: str | None = None
    failure_reason: str | None = None
    experimental: bool = False


def prepare_ts_rank_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {'ts_code', 'trade_date'}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f'BLOCK_TS_RANK_BENCHMARK_MISSING_KEYS:{sorted(missing)}')
    return frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)


def ts_rank_pandas_reference(frame: pd.DataFrame, value_col: str, window: int) -> CandidateResult:
    values = pd.to_numeric(frame[value_col], errors='coerce')
    return CandidateResult(
        name='pandas_reference',
        status='PASS',
        values=ts_rank_reference(values, window, frame),
        experimental=False,
    )


def ts_rank_numpy_sliding_window_experimental(frame: pd.DataFrame, value_col: str, window: int) -> CandidateResult:
    stats: dict = {}
    values = pd.to_numeric(frame[value_col], errors='coerce')
    return CandidateResult(
        name='numpy_sliding_window_experimental',
        status='PASS',
        values=ts_rank_fast_numpy(values, window, frame, stats=stats),
        experimental=True,
    )


def _rank_last_value_average_pct(values: np.ndarray) -> float:
    return last_value_pct_rank_reference(values)


def _per_ticker_loop_array(values: np.ndarray, window: int) -> np.ndarray:
    # Candidate is intentionally per ticker: it never builds one global
    # cross-security window matrix. The inner ticker path can still vectorize.
    return _ts_rank_one_array(values, window)


def ts_rank_numpy_per_ticker_loop(frame: pd.DataFrame, value_col: str, window: int) -> CandidateResult:
    values = pd.to_numeric(frame[value_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    codes = frame['ts_code'].to_numpy()
    out = np.full(len(frame), np.nan, dtype='float64')
    for code in pd.unique(frame['ts_code']):
        positions = np.flatnonzero(codes == code)
        if len(positions):
            out[positions] = _per_ticker_loop_array(values[positions], window)
    return CandidateResult(
        name='numpy_per_ticker_loop',
        status='PASS',
        values=pd.Series(out, index=frame.index, name=value_col),
        experimental=True,
    )


def ts_rank_scipy_rankdata(frame: pd.DataFrame, value_col: str, window: int) -> CandidateResult:
    if len(frame) > 100_000:
        return CandidateResult(
            name='scipy_rankdata',
            status='SKIP',
            values=None,
            skip_reason='optional_candidate_size_guard',
            experimental=True,
        )
    try:
        from scipy.stats import rankdata
    except Exception as exc:
        return CandidateResult(
            name='scipy_rankdata',
            status='SKIP',
            values=None,
            skip_reason=f'dependency_missing:{type(exc).__name__}',
            experimental=True,
        )

    values = pd.to_numeric(frame[value_col], errors='coerce').to_numpy(dtype='float64', copy=False)
    codes = frame['ts_code'].to_numpy()
    out = np.full(len(frame), np.nan, dtype='float64')
    for code in pd.unique(frame['ts_code']):
        positions = np.flatnonzero(codes == code)
        ticker_values = values[positions]
        ticker_out = np.full(len(ticker_values), np.nan, dtype='float64')
        for idx in range(window - 1, len(ticker_values)):
            chunk = ticker_values[idx - window + 1 : idx + 1]
            if np.isnan(chunk).any():
                continue
            ticker_out[idx] = float(rankdata(chunk, method='average')[-1] / float(window))
        out[positions] = ticker_out
    return CandidateResult(
        name='scipy_rankdata',
        status='PASS',
        values=pd.Series(out, index=frame.index, name=value_col),
        experimental=True,
    )


def available_candidates() -> dict[str, Callable[[pd.DataFrame, str, int], CandidateResult]]:
    return {
        'pandas_reference': ts_rank_pandas_reference,
        'numpy_sliding_window_experimental': ts_rank_numpy_sliding_window_experimental,
        'numpy_per_ticker_loop': ts_rank_numpy_per_ticker_loop,
        'scipy_rankdata': ts_rank_scipy_rankdata,
    }


def compare_candidate_to_reference(
    frame: pd.DataFrame,
    reference: pd.Series,
    candidate: pd.Series,
    *,
    tolerance: float = 1e-12,
) -> dict:
    ref = pd.to_numeric(reference, errors='coerce').reset_index(drop=True)
    cand = pd.to_numeric(candidate, errors='coerce').reset_index(drop=True)
    nan_mask_equal = bool(ref.isna().equals(cand.isna()))
    valid = ref.notna() & cand.notna()
    if int(valid.sum()) > 0:
        max_abs_diff = float((ref[valid] - cand[valid]).abs().max())
    else:
        max_abs_diff = 0.0
    if int(valid.sum()) >= 2:
        rank_corr_raw = ref[valid].rank(method='average').corr(cand[valid].rank(method='average'), method='pearson')
        rank_corr = float(rank_corr_raw) if pd.notna(rank_corr_raw) else None
    else:
        rank_corr = None
    allclose = bool(nan_mask_equal and max_abs_diff <= tolerance)
    rank_corr_ok = rank_corr is None or rank_corr >= 0.999999
    return {
        'row_count_equal': int(len(ref)) == int(len(cand)),
        'key_order_equal': bool(
            frame[['ts_code', 'trade_date']].reset_index(drop=True).equals(
                frame[['ts_code', 'trade_date']].sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
            )
        ),
        'nan_mask_equal': nan_mask_equal,
        'max_abs_diff': max_abs_diff,
        'rank_corr': rank_corr,
        'parity_pass': bool(allclose and rank_corr_ok),
    }
