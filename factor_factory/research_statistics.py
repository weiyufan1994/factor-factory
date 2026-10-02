"""Pure statistical kernels shared by manual research and the formal verifier.

These functions compute statistics, not evidence admission or portfolio returns.
"""
from __future__ import annotations

import math
from numbers import Integral

import numpy as np
import pandas as pd


def newey_west_mean(values, lags: int) -> dict:
    """Bartlett HAC variance of a mean; covariance denominator is T, no ddof.

    p_value is a two-sided asymptotic normal approximation, not a finite-sample
    Student t probability. A zero variance has no defined t statistic.
    """
    if isinstance(lags, bool) or not isinstance(lags, Integral) or lags < 0:
        raise ValueError('newey_west_lags must be a non-negative integer')
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError('HAC input must be a finite one-dimensional sequence')
    count = len(values)
    scale = float(np.abs(values).max()) if count else 0.
    scaled = values / scale if scale else values
    scaled_mean = float(scaled.mean()) if count else 0.
    result = {'n': count, 'mean': scaled_mean * scale if count else None,
              'standard_error': None, 'tstat': None, 'p_value': None,
              'reason': 'insufficient_periods', 'effective_lags': min(int(lags), max(0, count - 1))}
    if count < 2:
        return result
    # An OLS coefficient which is mathematically constant can vary by a few
    # ulps across periods. Such roundoff is not evidence of a tiny standard
    # error and enormous significance. This tolerance is RELATIVE to the
    # coefficient scale, so changing factor/return units does not erase real
    # variation in small coefficients. Scale before squaring to avoid underflow.
    if float(np.ptp(scaled)) <= 16 * np.finfo(float).eps:
        result['reason'] = 'zero_variation_at_float_precision'
        return result
    centered = scaled - scaled_mean
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, min(lags, count - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / count)
        long_run_variance += 2.0 * weight * covariance
    variance_of_mean = max(long_run_variance, 0.0) / count
    if variance_of_mean <= 0:
        result['reason'] = 'zero_hac_variance'
        return result
    scaled_se = math.sqrt(variance_of_mean)
    standard_error = scaled_se * scale
    tstat = float(scaled_mean / scaled_se)
    if standard_error == 0:
        result['reason'] = 'standard_error_underflow'
        return result
    if not all(math.isfinite(x) for x in (standard_error, tstat)):
        result['reason'] = 'numeric_overflow'
        return result
    result.update(standard_error=standard_error, tstat=tstat,
                  p_value=math.erfc(abs(tstat) / math.sqrt(2)), reason=None)
    return result


def fama_macbeth_periods(frame, *, date_col, signal_col, return_col, controls) -> list[dict]:
    """OLS with intercept at each date; signal and controls are not standardized.

    Missing observations are explicitly counted. Rank-deficient/undersized
    periods carry a reason rather than an invented zero coefficient.
    """
    result = []
    regressors = [signal_col, *controls]
    for date, group in frame.groupby(date_col, sort=True):
        clean = group[[return_col, *regressors]].dropna()
        row = {'date': str(date), 'n': len(clean), 'input_n': len(group),
               'lambda': None, 'reason': None}
        if len(clean) <= len(regressors) + 1:
            row['reason'] = 'cross_section_insufficient'
        else:
            x = clean[regressors].to_numpy(dtype=float)
            x = np.column_stack([np.ones(len(x)), x])
            y = clean[return_col].to_numpy(dtype=float)
            if not np.isfinite(x).all() or not np.isfinite(y).all():
                raise ValueError('OLS inputs must be finite after explicit missing-value exclusion')
            beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
            if rank != x.shape[1]:
                row['reason'] = 'rank_deficient'
            elif not np.isfinite(beta).all():
                row['reason'] = 'numeric_overflow'
            else:
                row['lambda'] = float(beta[1])
        result.append(row)
    return result
