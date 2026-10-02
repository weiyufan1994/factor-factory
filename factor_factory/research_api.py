"""Small, offline, explicit factor-frame and preliminary-analysis interface.

No data fetching, canonical writeback, inference of signal columns, or account
simulation occurs here. A valid NaN is retained and counted; an infinity, bad
key, nonnumeric dtype or duplicate key is rejected. Prices and forward returns
are separate inputs and must not be supplied to a factor implementation as
future information.
"""
from __future__ import annotations

import json
from numbers import Integral
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype

from factor_factory.research_statistics import fama_macbeth_periods, newey_west_mean


def _dates(values, *, name: str) -> pd.DatetimeIndex:
    values = pd.Series(values)
    if values.isna().any():
        raise ValueError(f'{name}: missing dates are forbidden')
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        raise ValueError(f'{name}: timezone-aware dates are unsupported; provide session dates')
    if pd.api.types.is_datetime64_any_dtype(values):
        result = pd.DatetimeIndex(values)
    else:
        # Do not let pandas interpret YYYYMMDD integers as epoch nanoseconds,
        # accept float-like dates, or guess ambiguous day/month order.
        text = values.astype(str)
        compact = text.str.fullmatch(r'\d{8}')
        iso = text.str.fullmatch(r'\d{4}-\d{2}-\d{2}')
        if not (compact | iso).all():
            raise ValueError(f'{name}: expected YYYYMMDD, YYYY-MM-DD or naive datetime64')
        result = pd.DatetimeIndex(pd.to_datetime(text.str.replace('-', '', regex=False), format='%Y%m%d', errors='raise'))
    if result.isna().any() or not result.equals(result.normalize()):
        raise ValueError(f'{name}: expected nonmissing midnight session dates')
    return result


def _index(index: pd.MultiIndex) -> pd.MultiIndex:
    if not isinstance(index, pd.MultiIndex) or list(index.names) != ['datetime', 'instrument']:
        raise ValueError('index must be a datetime/instrument MultiIndex in that order')
    dates = _dates(index.get_level_values('datetime'), name='datetime')
    codes = pd.Series(index.get_level_values('instrument'), dtype=object)
    if not codes.drop_duplicates().map(lambda x: isinstance(x, str) and bool(x) and x == x.strip()).all():
        raise ValueError('instrument keys must be nonempty strings without surrounding whitespace')
    result = pd.MultiIndex.from_arrays([dates, codes], names=['datetime', 'instrument'])
    if result.has_duplicates:
        raise ValueError('duplicate datetime/instrument keys are forbidden')
    return result


def _numeric(series: pd.Series, name: str) -> pd.Series:
    if (not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype)
            or is_complex_dtype(series.dtype)):
        raise TypeError(f'{name}: numeric real dtype required; strings/bools are not coerced')
    values = series.astype('float64')
    if np.isinf(values.to_numpy()).any():
        raise ValueError(f'{name}: Infinity is forbidden; use NaN only for missing observations')
    return values


def _frame(frame: pd.DataFrame, columns: list[str], *, allow_extra: bool = False, allow_empty: bool = False) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError('expected a pandas DataFrame')
    if frame.columns.has_duplicates:
        raise ValueError('duplicate column names are forbidden')
    if frame.empty and not allow_empty:
        raise ValueError('empty input frame')
    if isinstance(frame.index, pd.MultiIndex):
        index = _index(frame.index)
        keys = set()
    else:
        keys = {'ts_code', 'trade_date'}
        if not keys.issubset(frame.columns):
            raise ValueError('expected ts_code/trade_date columns or datetime/instrument MultiIndex')
        index = _index(pd.MultiIndex.from_arrays(
            [_dates(frame['trade_date'], name='trade_date'), frame['ts_code']],
            names=['datetime', 'instrument']))
    if not set(columns).issubset(frame.columns):
        raise ValueError('missing explicitly named value columns: ' + ','.join(sorted(set(columns) - set(frame.columns))))
    if not allow_extra and set(frame.columns) != keys | set(columns):
        raise ValueError('unexpected columns; select the intended values explicitly before analysis')
    output = pd.DataFrame(index=index)
    for column in columns:
        output[column] = _numeric(frame[column], column).to_numpy()
    return output if output.index.is_monotonic_increasing else output.sort_index()


def normalize_factor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize exactly three long columns or one indexed factor_value column.

    Returns a sorted, unique, naive daily datetime/instrument MultiIndex with
    float64 factor_value. Instrument identifiers are preserved, not renamed.
    NaNs (including warmup) and genuine zeros are preserved.
    """
    return _frame(frame, ['factor_value'])


def validate_factor_output(frame: pd.DataFrame) -> pd.DataFrame:
    """Stage compatibility adapter: validate signal/keys, preserve audit columns.

    Class instances can return the canonical MultiIndex. Legacy implementations
    return long frames, possibly with research diagnostics in additional columns.
    Neither route may infer which value column is the factor.
    """
    _frame(frame, ['factor_value'], allow_extra=True)
    if isinstance(frame.index, pd.MultiIndex):
        result = frame.copy()
        result.index = _index(frame.index)
        result['factor_value'] = _numeric(frame['factor_value'], 'factor_value').to_numpy()
        result = result.reset_index().rename(columns={'datetime': 'trade_date', 'instrument': 'ts_code'})
        result['trade_date'] = result['trade_date'].dt.strftime('%Y%m%d')
        return result[['ts_code', 'trade_date', 'factor_value', *[c for c in result.columns if c not in {'ts_code', 'trade_date', 'factor_value'}]]]
    # Preserve legacy row order/index and date representation; downstream writers
    # already own their explicit long-format serialization.
    result = frame.copy()
    result['factor_value'] = _numeric(frame['factor_value'], 'factor_value')
    return result


def factor_coverage(frame: pd.DataFrame, *, expected_index: pd.MultiIndex | None = None) -> dict:
    """Expected keys must come from an independent calendar/universe membership.

    Without them the ratio describes only returned rows, never completeness.
    Missing rows and present-but-NaN rows are counted separately.
    """
    return _factor_coverage(normalize_factor_frame(frame), expected_index=expected_index)


def _factor_coverage(factor: pd.DataFrame, *, expected_index=None) -> dict:
    """Internal normalized-frame path; avoid re-sorting large factor panels."""
    valid = factor['factor_value'].notna()
    result = {'scope': 'observed', 'observed_rows': len(factor), 'valid_rows': int(valid.sum()),
              'nan_rows': int((~valid).sum()), 'observed_valid_ratio': float(valid.mean()),
              'expected_rows': None, 'missing_rows': None, 'unexpected_rows': None,
              'expected_valid_ratio': None, 'completeness_verified': False, 'by_date': []}
    expected = None if expected_index is None else _index(expected_index)
    expected_counts = None
    if expected is not None:
        if len(expected) == 0:
            raise ValueError('expected_index must not be empty')
        result.update(scope='expected', expected_rows=len(expected),
                      missing_rows=len(expected.difference(factor.index)),
                      unexpected_rows=len(factor.index.difference(expected)),
                      expected_valid_ratio=float(factor.reindex(expected)['factor_value'].notna().mean()))
        result['completeness_verified'] = result['missing_rows'] == 0 and result['unexpected_rows'] == 0
        audit = factor.reindex(expected)
        audit['present'] = expected.isin(factor.index)
        expected_counts = audit.groupby(level='datetime').agg(
            expected_rows=('present', 'size'), present_rows=('present', 'sum'), valid_rows=('factor_value', 'count'))
    dates = factor.index.get_level_values('datetime').unique()
    if expected is not None:
        dates = dates.union(expected.get_level_values('datetime').unique())
    observed_counts = factor.groupby(level='datetime')['factor_value'].agg(['size', 'count'])
    for date in sorted(dates):
        observed = int(observed_counts.loc[date, 'size']) if date in observed_counts.index else 0
        nonnull = int(observed_counts.loc[date, 'count']) if date in observed_counts.index else 0
        row = {'date': date.strftime('%Y-%m-%d'), 'observed_rows': observed, 'valid_rows': nonnull,
               'expected_rows': None, 'missing_rows': None, 'expected_valid_ratio': None}
        if expected is not None:
            count = int(expected_counts.loc[date, 'expected_rows']) if date in expected_counts.index else 0
            present = int(expected_counts.loc[date, 'present_rows']) if count else 0
            finite = int(expected_counts.loc[date, 'valid_rows']) if count else 0
            row.update(expected_rows=count, missing_rows=count-present,
                       expected_valid_ratio=finite/count if count else None)
        result['by_date'].append(row)
    return result


def build_forward_returns(prices: pd.DataFrame, *, calendar, entry_offset: int = 1, horizon: int = 1) -> pd.DataFrame:
    """Exact-session close(t+entry+horizon)/close(t+entry)-1, in decimal units.

    calendar must be independent, sorted and unique. Missing price/session
    endpoints remain NaN: the next observed quote never substitutes for the
    requested trading session. No price adjustment or tradability is inferred.
    """
    for name, value, minimum in [('entry_offset', entry_offset, 0), ('horizon', horizon, 1)]:
        if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    frame = _frame(prices, ['close'])
    if (frame['close'].dropna() <= 0).any():
        raise ValueError('close prices must be positive where observed')
    sessions = _dates(calendar, name='calendar')
    if sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError('calendar must be nonempty, sorted and unique')
    dates = frame.index.get_level_values('datetime')
    positions = sessions.get_indexer(dates)
    if (positions < 0).any():
        raise ValueError('price date lies outside the supplied calendar')
    def endpoint(offset):
        target = positions + offset
        dates_array = sessions.to_numpy()[np.minimum(target, len(sessions) - 1)].copy()
        dates_array[target >= len(sessions)] = np.datetime64('NaT')
        target_dates = pd.DatetimeIndex(dates_array)
        keys = pd.MultiIndex.from_arrays([target_dates, frame.index.get_level_values('instrument')], names=frame.index.names)
        return frame['close'].reindex(keys).to_numpy()
    with np.errstate(invalid='ignore', divide='ignore', over='ignore'):
        values = endpoint(entry_offset + horizon) / endpoint(entry_offset) - 1.0
    if np.isinf(values).any():
        raise ValueError('forward return overflow')
    result = pd.DataFrame({'forward_return': values}, index=frame.index)
    result.attrs['timing'] = {'price': 'caller_supplied_close', 'entry_offset': int(entry_offset),
                              'horizon_sessions': int(horizon), 'calendar_sessions': len(sessions)}
    return result


def _metric(value, unit, n, reason=None):
    if value is not None and not np.isfinite(value):
        value, reason = None, 'numeric_overflow'
    return {'value': None if value is None else float(value), 'unit': unit, 'n': int(n),
            'reason': reason if value is None else None}


def _stats(values, *, prefix, unit):
    values = np.asarray(values, dtype=float)
    n = len(values)
    mean = float(values.mean()) if n else None
    std = float(values.std(ddof=1)) if n > 1 else None
    return {
        prefix + '_mean': _metric(mean, unit, n, 'no_valid_observations'),
        prefix + '_std': _metric(std, unit, n, 'insufficient_observations'),
        prefix + '_ir': _metric(mean / std if std is not None and std > 0 else None, 'ratio_unannualized', n,
                               'zero_variance' if std == 0 else 'insufficient_observations'),
    }


def evaluate_factor(factor_values: pd.DataFrame, forward_returns: pd.DataFrame | None = None, *,
                    analysis: str = 'ic', controls: pd.DataFrame | None = None,
                    expected_index: pd.MultiIndex | None = None, newey_west_lags: int = 0) -> dict[str, Any]:
    """Analyze caller-supplied, time-aligned decimal returns; never fetch data.

    IC: within-date Pearson and average-tie Spearman; mean/std/IR across dates.
    Event study: equal-weight returns of every nonmissing factor event, with
    both event-weighted and date-weighted means. Factor sign/size does not select
    or weight events. FMB: within-date OLS with intercept and optional controls,
    then equal-date coefficient mean and Bartlett HAC inference. No annualizing.
    Portfolio replay has its own explicit inputs: use portfolio_api.backtest.
    """
    if analysis == 'portfolio':
        raise ValueError('Use factor_factory.portfolio_api.backtest for account replay')
    if analysis not in {'ic', 'event_study', 'fama_macbeth'}:
        raise ValueError('unknown analysis')
    if controls is not None and analysis != 'fama_macbeth':
        raise ValueError('controls are only supported for fama_macbeth')
    factor = normalize_factor_frame(factor_values)
    coverage = _factor_coverage(factor, expected_index=expected_index)
    if coverage['unexpected_rows']:
        raise ValueError('factor keys lie outside expected_index')
    result = {'api_version': 'factorforge_research_api_v1', 'analysis': analysis, 'status': 'ok', 'evaluation_scope': 'preliminary_signal_diagnostic',
              'account_simulation': False, 'tradable_net_alpha_evidence': False,
              'metrics': {}, 'periods': [], 'coverage': coverage, 'warnings': []}
    if forward_returns is None:
        raise ValueError('forward_returns must be supplied explicitly')
    labels = _frame(forward_returns, ['forward_return'], allow_empty=True)
    if (labels['forward_return'].dropna() < -1).any():
        raise ValueError('simple forward returns cannot be below -1')
    work = factor.join(labels, how='left', validate='one_to_one')
    result['label_timing'] = forward_returns.attrs.get('timing', {'source': 'caller_supplied; timing_not_verified'})
    result['alignment'] = {'factor_rows': len(factor),
                           'label_key_missing_rows': len(factor.index.difference(labels.index)),
                           'unused_label_rows': len(labels.index.difference(factor.index)),
                           'paired_rows': int(work.notna().all(axis=1).sum())}
    control_columns = []
    if controls is not None:
        control_columns = [c for c in controls.columns if c not in {'ts_code', 'trade_date'}]
        if not control_columns or any(not isinstance(c, str) or not c.strip() or c in {'factor_value', 'forward_return', 'datetime', 'instrument'} for c in control_columns):
            raise ValueError('controls must have nonempty, distinct numeric column names')
        work = work.join(_frame(controls, control_columns), how='left', validate='one_to_one')
    if analysis == 'fama_macbeth':
        # Validate lag type even when there are no estimable cross sections.
        newey_west_mean([], newey_west_lags)
        period_frame = work.reset_index()
        period_frame['datetime'] = period_frame['datetime'].dt.strftime('%Y-%m-%d')
        rows = fama_macbeth_periods(period_frame, date_col='datetime', signal_col='factor_value',
                                   return_col='forward_return', controls=control_columns)
        result['periods'] = rows
        slopes = [row['lambda'] for row in rows if row['lambda'] is not None]
        hac = newey_west_mean(slopes, newey_west_lags)
        result['metrics'] = {
            'lambda_mean': _metric(hac['mean'], 'decimal_return_per_factor_unit', len(slopes), 'no_estimable_periods'),
            'lambda_standard_error': _metric(hac['standard_error'], 'decimal_return_per_factor_unit', len(slopes), hac['reason']),
            'lambda_tstat': _metric(hac['tstat'], 'ratio', len(slopes), hac['reason']),
            'lambda_pvalue_normal': _metric(hac['p_value'], 'probability_two_sided_asymptotic_normal', len(slopes), hac['reason']),
        }
        result['inference'] = {'intercept': True, 'controls': control_columns, 'standardization': 'none',
                               'newey_west_lags': int(newey_west_lags), 'effective_lags': hac['effective_lags'],
                               'kernel': 'Bartlett', 'covariance_denominator': 'T', 'period_weighting': 'equal'}
        if any(row['reason'] is not None for row in rows):
            # Do not close gaps between failed regressions for HAC inference.
            for key in ('lambda_standard_error', 'lambda_tstat', 'lambda_pvalue_normal'):
                result['metrics'][key] = _metric(None, result['metrics'][key]['unit'], len(slopes), 'invalid_periods_in_coefficient_path')
            result['warnings'].append('Coefficient mean uses estimable periods; HAC inference withheld because some periods were invalid.')
    else:
        event_returns = []
        for date, group in work.groupby(level='datetime', sort=True):
            clean = group[['factor_value', 'forward_return']].dropna()
            row = {'date': date.strftime('%Y-%m-%d'), 'input_n': len(group), 'n': len(clean)}
            if analysis == 'ic':
                reason = ('cross_section_insufficient' if len(clean) < 2 else
                          'constant_signal' if clean['factor_value'].nunique() < 2 else
                          'constant_return' if clean['forward_return'].nunique() < 2 else None)
                for method, key in [('pearson', 'pearson_ic'), ('spearman', 'rank_ic')]:
                    value = clean['factor_value'].corr(clean['forward_return'], method=method) if reason is None else None
                    row[key] = None if value is None or not np.isfinite(value) else float(value)
                row['reason'] = reason or ('numeric_overflow' if row['pearson_ic'] is None or row['rank_ic'] is None else None)
            else:
                value = clean['forward_return'].mean() if len(clean) else None
                row['mean_return'] = None if value is None or not np.isfinite(value) else float(value)
                row['reason'] = ('no_paired_events' if len(clean) == 0 else
                                 'numeric_overflow' if row['mean_return'] is None else None)
                event_returns.extend(clean['forward_return'].tolist())
            result['periods'].append(row)
        if analysis == 'ic':
            for key in ('rank_ic', 'pearson_ic'):
                result['metrics'].update(_stats([row[key] for row in result['periods'] if row[key] is not None], prefix=key, unit='correlation'))
        else:
            result['metrics'].update(_stats(event_returns, prefix='event_return', unit='decimal_return'))
            result['metrics'].update(_stats([row['mean_return'] for row in result['periods'] if row['mean_return'] is not None], prefix='date_mean_return', unit='decimal_return'))
            result['warnings'].append('Descriptive event returns only: overlapping events are not independent; no portfolio NAV, costs or annualization.')
    if any(metric['value'] is None for metric in result['metrics'].values()) or any(row.get('reason') for row in result['periods']):
        result['status'] = 'partial'
    if result['alignment']['paired_rows'] < len(factor):
        result['warnings'].append('Missing factor/label pairs excluded from statistics and retained in the input and coverage counts.')
    json.dumps(result, allow_nan=False)
    return result
