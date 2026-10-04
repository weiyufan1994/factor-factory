"""Pure statistical kernels shared by manual research and the formal verifier.

These functions compute statistics, not evidence admission or portfolio returns.
"""
from __future__ import annotations

import math
from numbers import Integral

import numpy as np
import pandas as pd


def zero_variation_at_float_precision(values) -> bool:
    """Relative float64 guard shared by mean inference, independent of units."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError('precision check requires a finite one-dimensional sequence')
    if len(values) < 2:
        return False
    scale = float(np.abs(values).max())
    scaled = values / scale if scale else values
    return float(np.ptp(scaled)) <= 16 * np.finfo(float).eps


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
    if zero_variation_at_float_precision(scaled):
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


def fama_macbeth_periods(frame, *, date_col, signal_col, return_col, controls,
                         min_observations: int | None = None, rcond=None) -> list[dict]:
    """OLS with intercept at each date; signal and controls are not standardized.

    Missing observations are explicitly counted. Rank-deficient/undersized
    periods carry a reason rather than an invented zero coefficient.
    """
    if min_observations is not None and (isinstance(min_observations, bool)
            or not isinstance(min_observations, Integral) or min_observations < 3):
        raise ValueError('min_observations must be an integer >= 3')
    if rcond is not None and (isinstance(rcond, bool) or not math.isfinite(rcond) or rcond <= 0 or rcond >= 1):
        raise ValueError('rcond must be a finite relative tolerance between 0 and 1')
    result = []
    regressors = [signal_col, *controls]
    for date, group in frame.groupby(date_col, sort=True):
        clean = group[[return_col, *regressors]].dropna()
        row = {'date': str(date), 'n': len(clean), 'input_n': len(group),
               'lambda': None, 'reason': None}
        if len(clean) <= len(regressors) + 1 or len(clean) < (min_observations or 0):
            row['reason'] = 'cross_section_insufficient'
        else:
            x = clean[regressors].to_numpy(dtype=float)
            x = np.column_stack([np.ones(len(x)), x])
            y = clean[return_col].to_numpy(dtype=float)
            if not np.isfinite(x).all() or not np.isfinite(y).all():
                raise ValueError('OLS inputs must be finite after explicit missing-value exclusion')
            beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=rcond)
            if rank != x.shape[1]:
                row['reason'] = 'rank_deficient'
            elif not np.isfinite(beta).all():
                row['reason'] = 'numeric_overflow'
            else:
                row['lambda'] = float(beta[1])
        result.append(row)
    return result


def partial_rank_ic_periods(frame, *, date_col, signal_col, return_col, controls,
                            min_observations: int = 100) -> list[dict]:
    """Corr(M_Z midrank(signal), M_Z midrank(return)) on complete cases.

    Z contains an intercept and every supplied control, without ranking controls
    or re-ranking residuals. Column centering/scaling preserves span([1, C]) and
    avoids a control's measurement unit deciding numerical rank. No control is
    dropped. SVD rank and residual-zero tolerances use eps * max(N, columns).
    Undefined periods remain explicit rows; this function performs no inference.
    """
    if (isinstance(min_observations, bool) or not isinstance(min_observations, Integral)
            or min_observations < 3):
        raise ValueError('min_observations must be an integer >= 3')
    if not controls or len(set(controls)) != len(controls):
        raise ValueError('partial Rank IC requires distinct, explicitly supplied controls')
    result = []
    for date, group in frame.groupby(date_col, sort=True):
        clean = group[[signal_col, return_col, *controls]].dropna()
        n, p = len(clean), len(controls) + 1
        row = {'date': str(date), 'input_n': len(group), 'n': n,
               'excluded_n': len(group) - n, 'design_columns': p, 'design_rank': None,
               'partial_rank_ic': None, 'same_support_rank_ic': None,
               'same_support_pearson_ic': None, 'reason': None}
        values = clean.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError('partial Rank IC inputs must be finite after missing-value exclusion')
        ranks = clean[[signal_col, return_col]].rank(method='average').to_numpy(dtype=float)
        if n >= 2 and all(clean[c].nunique() > 1 for c in (signal_col, return_col)):
            row['same_support_rank_ic'] = float(np.corrcoef(ranks.T)[0, 1])
            raw = values[:, :2]
            raw = raw / np.max(np.abs(raw), axis=0)
            raw_ic = float(np.corrcoef(raw.T)[0, 1])
            row['same_support_pearson_ic'] = raw_ic if math.isfinite(raw_ic) else None
        if n < min_observations or n <= p:
            row['reason'] = 'cross_section_insufficient'
        else:
            c = values[:, 2:]
            scales = np.max(np.abs(c), axis=0)
            # A zero/constant column is collinear with the intercept, not a
            # reason to remove that declared control and fit a different model.
            scaled = c / np.where(scales > 0, scales, 1.)
            centered = scaled - scaled.mean(axis=0)
            norms = np.linalg.norm(centered, axis=0)
            z = np.column_stack([np.ones(n) / math.sqrt(n),
                                 centered / np.where(norms > 0, norms, 1.)])
            tolerance = np.finfo(float).eps * max(n, p)
            try:
                basis, singular, _ = np.linalg.svd(z, full_matrices=False)
            except np.linalg.LinAlgError:
                row['reason'] = 'numerical_decomposition_failed'
            else:
                rank = int(np.count_nonzero(singular > tolerance * singular[0]))
                row['design_rank'] = rank
                if rank != p:
                    row['reason'] = 'rank_deficient'
                else:
                    centered_ranks = ranks - ranks.mean(axis=0)
                    residuals = centered_ranks - basis @ (basis.T @ centered_ranks)
                    # Correlation includes centering; eliminate residual roundoff
                    # in the intercept direction before measuring its variance.
                    residuals -= residuals.mean(axis=0)
                    residual_norms = np.linalg.norm(residuals, axis=0)
                    original_norms = np.linalg.norm(centered_ranks, axis=0)
                    if np.any(residual_norms <= tolerance * original_norms):
                        row['reason'] = 'zero_residual_variance'
                    else:
                        unit_residuals = residuals / residual_norms
                        value = float(np.dot(unit_residuals[:, 0], unit_residuals[:, 1]))
                        if not math.isfinite(value):
                            row['reason'] = 'numeric_overflow'
                        else:
                            row['partial_rank_ic'] = float(np.clip(value, -1., 1.))
        result.append(row)
    return result
