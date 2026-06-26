from __future__ import annotations

import math
import os
import re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATASET_ID = 'intraday_flow_distribution_moments_v1'
SCHEMA_VERSION = 'intraday_flow_distribution_moments_v1_p0'
PRODUCER_VERSION = 'factorforge_data_api_flow_distribution_moments_20260616'
SOURCE_DATASET = 'minute_bar'
UNIQUE_KEY = ['ts_code', 'trade_date', 'cutoff_time']
SORT_KEYS = ['trade_date', 'ts_code', 'cutoff_time']
DEFAULT_CUTOFF_TIMES = ('10:30:00', '11:30:00', '14:00:00', '14:30:00', '14:50:00', '14:55:00')
P0_COLUMNS = [
    'ts_code',
    'trade_date',
    'cutoff_time',
    'minute_count',
    'amount_sum',
    'volume_sum',
    'ret_mean',
    'ret_std',
    'ret_skew',
    'ret_excess_kurtosis',
    'ret_tail_asymmetry',
    'amount_mean',
    'amount_std',
    'amount_skew',
    'amount_excess_kurtosis',
    'amount_hhi',
    'amount_entropy',
    'signed_amount_sum',
    'signed_amount_mean',
    'signed_amount_std',
    'signed_amount_skew',
    'signed_amount_excess_kurtosis',
    'signed_flow_hhi',
    'signed_flow_tail_asymmetry',
    'large_proxy_amount',
    'small_proxy_amount',
    'large_proxy_signed_amount',
    'small_proxy_signed_amount',
    'large_proxy_count',
    'small_proxy_count',
    'amount_threshold_stock_q75',
    'amount_threshold_market_q75',
    'threshold_source',
    'threshold_lookback_days',
    'schema_version',
    'producer_version',
    'source_dataset',
    'no_future_intraday_minutes',
    'research_window',
]
PREPARED_MINUTE_COLUMNS = [
    'ts_code',
    'trade_date',
    'hhmmss',
    'amount_abs',
    'minute_ret',
    'signed_amount',
    'vol',
]


@dataclass(frozen=True)
class FlowDistributionParams:
    cutoff_times: tuple[str, ...] = DEFAULT_CUTOFF_TIMES
    threshold_lookback_days: tuple[int, ...] = (20, 60)
    threshold_quantile: float = 0.75
    threshold_backend: str = 'pandas'
    min_minutes: int = 20
    research_window: str = 'IS'
    operator_backend: str = 'vectorized'


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '')
    text = re.sub(r'\s+00:00:00$', '', text)
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'invalid trade_date: {value!r}')
    return parsed.strftime('%Y%m%d')


def cutoff_to_hhmmss(value: str | int | None) -> int:
    raw = str(value or '14:50:00').strip()
    digits = re.sub(r'[^0-9]', '', raw)
    if len(digits) <= 4:
        return int(digits) * 100
    return int(digits[:6])


def normalize_cutoff_time(value: str | int | None) -> str:
    hhmmss = f'{cutoff_to_hhmmss(value):06d}'
    return f'{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}'


def time_key(series: pd.Series) -> pd.Series:
    token = series.astype(str).str.strip().str.split().str[-1].str.replace(':', '', regex=False)
    digits = token.str.extract(r'(\d{3,6})$', expand=False).fillna('145000')
    numeric = pd.to_numeric(digits, errors='coerce')
    short = numeric.where(digits.str.len() > 4, numeric * 100)
    return short.fillna(145000).astype(int)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _moment_stats(values: np.ndarray) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {'mean': 0.0, 'std': 0.0, 'skew': 0.0, 'excess_kurtosis': 0.0}
    mean = float(arr.mean())
    std = float(arr.std(ddof=0))
    if std <= 0:
        return {'mean': mean, 'std': 0.0, 'skew': 0.0, 'excess_kurtosis': 0.0}
    centered = arr - mean
    skew = float(np.mean(centered**3) / (std**3))
    excess_kurtosis = float(np.mean(centered**4) / (std**4) - 3.0)
    return {'mean': mean, 'std': std, 'skew': skew, 'excess_kurtosis': excess_kurtosis}


def _moment_stats_from_sums(n: int, s1: float, s2: float, s3: float, s4: float) -> dict[str, float]:
    if n <= 0:
        return {'mean': 0.0, 'std': 0.0, 'skew': 0.0, 'excess_kurtosis': 0.0}
    n_float = float(n)
    mean = s1 / n_float
    raw2 = s2 / n_float
    raw3 = s3 / n_float
    raw4 = s4 / n_float
    variance = max(raw2 - mean**2, 0.0)
    std = math.sqrt(variance)
    if std <= 0:
        return {'mean': mean, 'std': 0.0, 'skew': 0.0, 'excess_kurtosis': 0.0}
    m3 = raw3 - 3.0 * mean * raw2 + 2.0 * mean**3
    m4 = raw4 - 4.0 * mean * raw3 + 6.0 * mean**2 * raw2 - 3.0 * mean**4
    return {
        'mean': mean,
        'std': std,
        'skew': m3 / (std**3),
        'excess_kurtosis': m4 / (std**4) - 3.0,
    }


def _tail_asymmetry(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return 0.0
    upper = arr[arr >= np.quantile(arr, 0.9)]
    lower = arr[arr <= np.quantile(arr, 0.1)]
    upper_mass = float(np.abs(upper).sum())
    lower_mass = float(np.abs(lower).sum())
    denominator = upper_mass + lower_mass
    return float((upper_mass - lower_mass) / denominator) if denominator > 0 else 0.0


def _hhi(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = np.abs(arr[np.isfinite(arr)])
    total = float(arr.sum())
    if total <= 0:
        return 0.0
    weights = arr / total
    return float(np.sum(weights**2))


def _entropy(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = np.abs(arr[np.isfinite(arr)])
    total = float(arr.sum())
    if total <= 0 or arr.size <= 1:
        return 0.0
    weights = arr / total
    weights = weights[weights > 0]
    return float(-np.sum(weights * np.log(weights)) / math.log(arr.size))


def prepare_minute_frame(minute_df: pd.DataFrame) -> pd.DataFrame:
    minute = minute_df.copy()
    prepared_required = {'ts_code', 'trade_date', 'hhmmss', 'amount_abs', 'minute_ret', 'signed_amount'}
    if prepared_required.issubset(minute.columns):
        if 'vol' not in minute.columns:
            minute['vol'] = 0.0
        minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
        minute['hhmmss'] = pd.to_numeric(minute['hhmmss'], errors='coerce')
        for col in ['amount_abs', 'minute_ret', 'signed_amount', 'vol']:
            minute[col] = pd.to_numeric(minute[col], errors='coerce')
        minute = minute.dropna(subset=['ts_code', 'trade_date', 'hhmmss', 'amount_abs', 'minute_ret', 'signed_amount'])
        minute = minute[minute['amount_abs'].abs() > 0].copy()
        minute['hhmmss'] = minute['hhmmss'].astype(int)
        return minute[PREPARED_MINUTE_COLUMNS].sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)

    required = {'ts_code', 'trade_date', 'open', 'close'}
    missing = sorted(required - set(minute.columns))
    if missing:
        raise ValueError(f'minute_df missing required columns: {missing}')
    if 'trade_time' not in minute.columns:
        minute['trade_time'] = minute['bar_time'] if 'bar_time' in minute.columns else '14:50:00'
    if 'amount' not in minute.columns:
        if 'vol' not in minute.columns:
            raise ValueError('minute_df must include amount or vol')
        minute['amount'] = minute['vol']
    if 'vol' not in minute.columns:
        minute['vol'] = 0.0
    for col in ['open', 'close', 'amount', 'vol']:
        minute[col] = pd.to_numeric(minute[col], errors='coerce')
    minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
    minute['hhmmss'] = time_key(minute['trade_time'])
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'open', 'close', 'amount'])
    minute = minute[(minute['open'] > 0) & (minute['close'] > 0) & (minute['amount'].abs() > 0)].copy()
    minute['minute_ret'] = minute['close'] / minute['open'] - 1.0
    minute['signed_amount'] = np.sign(minute['close'] - minute['open']) * minute['amount'].abs()
    minute['amount_abs'] = minute['amount'].abs()
    return minute.sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)


def _prior_thresholds(stock: pd.DataFrame, trade_date: str, lookback_days: int, quantile: float) -> tuple[float, float]:
    dates = sorted(stock['trade_date'].unique().tolist())
    if trade_date not in dates:
        return 0.0, 0.0
    idx = dates.index(trade_date)
    prior_dates = dates[max(0, idx - lookback_days):idx]
    prior = stock[stock['trade_date'].isin(prior_dates)]
    stock_threshold = _safe_float(prior['amount_abs'].quantile(quantile)) if not prior.empty else 0.0
    market_threshold = stock_threshold
    return stock_threshold, market_threshold


def _market_prior_thresholds(minute: pd.DataFrame, trade_date: str, lookback_days: int, quantile: float) -> float:
    dates = sorted(minute['trade_date'].unique().tolist())
    if trade_date not in dates:
        return 0.0
    idx = dates.index(trade_date)
    prior_dates = dates[max(0, idx - lookback_days):idx]
    prior = minute[minute['trade_date'].isin(prior_dates)]
    return _safe_float(prior['amount_abs'].quantile(quantile)) if not prior.empty else 0.0


def _derive_one(
    rows: pd.DataFrame,
    *,
    ts_code: str,
    trade_date: str,
    cutoff_time: str,
    params: FlowDistributionParams,
    stock_threshold: float,
    market_threshold: float,
) -> dict[str, Any] | None:
    cutoff_rows = rows[(rows['trade_date'] == trade_date) & (rows['hhmmss'] <= cutoff_to_hhmmss(cutoff_time))]
    if len(cutoff_rows) < params.min_minutes:
        return None
    amount = cutoff_rows['amount_abs'].to_numpy(dtype=float)
    minute_ret = cutoff_rows['minute_ret'].to_numpy(dtype=float)
    signed_amount = cutoff_rows['signed_amount'].to_numpy(dtype=float)
    ret_stats = _moment_stats(minute_ret)
    amount_stats = _moment_stats(amount)
    signed_stats = _moment_stats(signed_amount)
    threshold = stock_threshold if stock_threshold > 0 else market_threshold
    large_mask = amount >= threshold if threshold > 0 else np.zeros_like(amount, dtype=bool)
    small_mask = ~large_mask
    return {
        'ts_code': str(ts_code),
        'trade_date': trade_date,
        'cutoff_time': normalize_cutoff_time(cutoff_time),
        'minute_count': int(len(cutoff_rows)),
        'amount_sum': float(amount.sum()),
        'volume_sum': float(pd.to_numeric(cutoff_rows['vol'], errors='coerce').fillna(0.0).sum()),
        'ret_mean': ret_stats['mean'],
        'ret_std': ret_stats['std'],
        'ret_skew': ret_stats['skew'],
        'ret_excess_kurtosis': ret_stats['excess_kurtosis'],
        'ret_tail_asymmetry': _tail_asymmetry(minute_ret),
        'amount_mean': amount_stats['mean'],
        'amount_std': amount_stats['std'],
        'amount_skew': amount_stats['skew'],
        'amount_excess_kurtosis': amount_stats['excess_kurtosis'],
        'amount_hhi': _hhi(amount),
        'amount_entropy': _entropy(amount),
        'signed_amount_sum': float(signed_amount.sum()),
        'signed_amount_mean': signed_stats['mean'],
        'signed_amount_std': signed_stats['std'],
        'signed_amount_skew': signed_stats['skew'],
        'signed_amount_excess_kurtosis': signed_stats['excess_kurtosis'],
        'signed_flow_hhi': _hhi(signed_amount),
        'signed_flow_tail_asymmetry': _tail_asymmetry(signed_amount),
        'large_proxy_amount': float(amount[large_mask].sum()),
        'small_proxy_amount': float(amount[small_mask].sum()),
        'large_proxy_signed_amount': float(signed_amount[large_mask].sum()),
        'small_proxy_signed_amount': float(signed_amount[small_mask].sum()),
        'large_proxy_count': int(large_mask.sum()),
        'small_proxy_count': int(small_mask.sum()),
        'amount_threshold_stock_q75': float(stock_threshold),
        'amount_threshold_market_q75': float(market_threshold),
        'threshold_source': 'prior_dates',
        'threshold_lookback_days': int(params.threshold_lookback_days[0]),
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'no_future_intraday_minutes': True,
        'research_window': params.research_window,
    }


def _finalize_output(frame: pd.DataFrame, operator_backend: str) -> pd.DataFrame:
    if frame.empty:
        out = pd.DataFrame(columns=P0_COLUMNS)
    else:
        out = frame[P0_COLUMNS].sort_values(SORT_KEYS).reset_index(drop=True)
        out['no_future_intraday_minutes'] = pd.Series([True] * len(out), dtype=object)
    out.attrs['operator_backend'] = operator_backend
    return out


def _moment_columns(prefix: str, n: pd.Series, s1: pd.Series, s2: pd.Series, s3: pd.Series, s4: pd.Series) -> pd.DataFrame:
    n_float = n.astype(float).replace(0.0, np.nan)
    mean = s1 / n_float
    raw2 = s2 / n_float
    raw3 = s3 / n_float
    raw4 = s4 / n_float
    variance = (raw2 - mean**2).clip(lower=0.0)
    std = np.sqrt(variance)
    m3 = raw3 - 3.0 * mean * raw2 + 2.0 * mean**3
    m4 = raw4 - 4.0 * mean * raw3 + 6.0 * mean**2 * raw2 - 3.0 * mean**4
    skew = pd.Series(np.where(std > 0, m3 / (std**3), 0.0), index=n.index)
    kurt = pd.Series(np.where(std > 0, m4 / (std**4) - 3.0, 0.0), index=n.index)
    return pd.DataFrame({
        f'{prefix}_mean': mean.fillna(0.0),
        f'{prefix}_std': std.fillna(0.0),
        f'{prefix}_skew': skew.replace([np.inf, -np.inf], 0.0).fillna(0.0),
        f'{prefix}_excess_kurtosis': kurt.replace([np.inf, -np.inf], 0.0).fillna(0.0),
    })


def _build_threshold_frame_pandas(minute: pd.DataFrame, targets: set[str], lookback_days: int, quantile: float) -> pd.DataFrame:
    dates = sorted(minute['trade_date'].unique().tolist())
    rows: list[pd.DataFrame] = []
    for trade_date in sorted(targets):
        if trade_date not in dates:
            continue
        current_codes = minute.loc[minute['trade_date'] == trade_date, ['ts_code']].drop_duplicates()
        if current_codes.empty:
            continue
        idx = dates.index(trade_date)
        prior_dates = dates[max(0, idx - lookback_days):idx]
        prior = minute[minute['trade_date'].isin(prior_dates)]
        if prior.empty:
            current_codes['amount_threshold_stock_q75'] = 0.0
            current_codes['trade_date'] = trade_date
            current_codes['amount_threshold_market_q75'] = 0.0
            rows.append(current_codes)
            continue
        stock = prior.groupby('ts_code', sort=False)['amount_abs'].quantile(quantile).rename('amount_threshold_stock_q75').reset_index()
        current = current_codes.merge(stock, on='ts_code', how='left')
        current['amount_threshold_stock_q75'] = pd.to_numeric(current['amount_threshold_stock_q75'], errors='coerce').fillna(0.0)
        current['trade_date'] = trade_date
        current['amount_threshold_market_q75'] = _safe_float(prior['amount_abs'].quantile(quantile))
        rows.append(current)
    if not rows:
        return pd.DataFrame(columns=['ts_code', 'trade_date', 'amount_threshold_stock_q75', 'amount_threshold_market_q75'])
    return pd.concat(rows, ignore_index=True)


def _build_threshold_frame_polars(minute: pd.DataFrame, targets: set[str], lookback_days: int, quantile: float) -> pd.DataFrame:
    import polars as pl

    dates = sorted(minute['trade_date'].unique().tolist())
    if not dates:
        return pd.DataFrame(columns=['ts_code', 'trade_date', 'amount_threshold_stock_q75', 'amount_threshold_market_q75'])
    base = pl.from_pandas(minute[['ts_code', 'trade_date', 'amount_abs']])
    rows: list[pd.DataFrame] = []
    for trade_date in sorted(targets):
        if trade_date not in dates:
            continue
        current_codes = (
            base.filter(pl.col('trade_date') == trade_date)
            .select('ts_code')
            .unique()
        )
        if current_codes.is_empty():
            continue
        idx = dates.index(trade_date)
        prior_dates = dates[max(0, idx - lookback_days):idx]
        prior = base.filter(pl.col('trade_date').is_in(prior_dates))
        if prior.is_empty():
            rows.append(
                current_codes.with_columns(
                    pl.lit(0.0).alias('amount_threshold_stock_q75'),
                    pl.lit(trade_date).alias('trade_date'),
                    pl.lit(0.0).alias('amount_threshold_market_q75'),
                ).to_pandas()
            )
            continue
        stock = prior.group_by('ts_code').agg(
            pl.col('amount_abs').quantile(quantile, interpolation='linear').alias('amount_threshold_stock_q75')
        )
        market_threshold = float(
            prior.select(pl.col('amount_abs').quantile(quantile, interpolation='linear').alias('q')).item()
        )
        current = (
            current_codes.join(stock, on='ts_code', how='left')
            .with_columns(
                pl.col('amount_threshold_stock_q75').fill_null(0.0),
                pl.lit(trade_date).alias('trade_date'),
                pl.lit(market_threshold).alias('amount_threshold_market_q75'),
            )
        )
        rows.append(current.to_pandas())
    if not rows:
        return pd.DataFrame(columns=['ts_code', 'trade_date', 'amount_threshold_stock_q75', 'amount_threshold_market_q75'])
    return pd.concat(rows, ignore_index=True)


def _build_threshold_frame(
    minute: pd.DataFrame,
    targets: set[str],
    lookback_days: int,
    quantile: float,
    backend: str = 'pandas',
) -> pd.DataFrame:
    selected = str(backend or 'pandas').lower()
    if selected == 'polars':
        return _build_threshold_frame_polars(minute, targets, lookback_days, quantile)
    if selected != 'pandas':
        raise ValueError(f'unsupported threshold_backend: {backend}')
    return _build_threshold_frame_pandas(minute, targets, lookback_days, quantile)


def _tail_asymmetry_by_group(frame: pd.DataFrame, keys: list[str], value_col: str, output_col: str) -> pd.Series:
    quantiles = frame.groupby(keys, sort=False)[value_col].quantile([0.1, 0.9]).unstack()
    quantiles = quantiles.rename(columns={0.1: '_q10', 0.9: '_q90'})
    temp = frame.join(quantiles, on=keys)
    values = pd.to_numeric(temp[value_col], errors='coerce').fillna(0.0)
    temp['_upper_abs'] = np.where(values >= temp['_q90'], values.abs(), 0.0)
    temp['_lower_abs'] = np.where(values <= temp['_q10'], values.abs(), 0.0)
    sums = temp.groupby(keys, sort=False).agg(_upper_abs=('_upper_abs', 'sum'), _lower_abs=('_lower_abs', 'sum'))
    denominator = sums['_upper_abs'] + sums['_lower_abs']
    out = pd.Series(np.where(denominator > 0, (sums['_upper_abs'] - sums['_lower_abs']) / denominator, 0.0), index=sums.index, name=output_col)
    return out


def _derive_vectorized_for_cutoff(
    minute: pd.DataFrame,
    *,
    targets: set[str],
    cutoff_time: str,
    params: FlowDistributionParams,
    thresholds: pd.DataFrame,
) -> pd.DataFrame:
    cutoff = normalize_cutoff_time(cutoff_time)
    current = minute[(minute['trade_date'].isin(targets)) & (minute['hhmmss'] <= cutoff_to_hhmmss(cutoff))].copy()
    if current.empty:
        return pd.DataFrame(columns=P0_COLUMNS)
    current = current.merge(thresholds, on=['ts_code', 'trade_date'], how='left')
    current['amount_threshold_market_q75'] = pd.to_numeric(current['amount_threshold_market_q75'], errors='coerce').fillna(0.0)
    current['amount_threshold_stock_q75'] = pd.to_numeric(current['amount_threshold_stock_q75'], errors='coerce').fillna(0.0)
    current['_threshold'] = current['amount_threshold_stock_q75'].where(current['amount_threshold_stock_q75'] > 0, current['amount_threshold_market_q75'])
    current['_large'] = (current['_threshold'] > 0) & (current['amount_abs'] >= current['_threshold'])
    current['_small'] = ~current['_large']
    current['_large_amount'] = np.where(current['_large'], current['amount_abs'], 0.0)
    current['_small_amount'] = np.where(current['_small'], current['amount_abs'], 0.0)
    current['_large_signed'] = np.where(current['_large'], current['signed_amount'], 0.0)
    current['_small_signed'] = np.where(current['_small'], current['signed_amount'], 0.0)
    current['_signed_abs'] = current['signed_amount'].abs()
    for col in ('minute_ret', 'amount_abs', 'signed_amount'):
        current[f'_{col}_2'] = current[col] ** 2
        current[f'_{col}_3'] = current[col] ** 3
        current[f'_{col}_4'] = current[col] ** 4
    current['_amount_log_amount'] = current['amount_abs'] * np.log(current['amount_abs'].clip(lower=1e-300))
    keys = ['ts_code', 'trade_date']
    grouped = current.groupby(keys, sort=False)
    base = grouped.agg(
        minute_count=('minute_ret', 'size'),
        amount_sum=('amount_abs', 'sum'),
        amount_sq_sum=('_amount_abs_2', 'sum'),
        amount_log_amount_sum=('_amount_log_amount', 'sum'),
        volume_sum=('vol', 'sum'),
        signed_amount_sum=('signed_amount', 'sum'),
        signed_abs_sum=('_signed_abs', 'sum'),
        signed_abs_sq_sum=('_signed_amount_2', 'sum'),
        large_proxy_amount=('_large_amount', 'sum'),
        small_proxy_amount=('_small_amount', 'sum'),
        large_proxy_signed_amount=('_large_signed', 'sum'),
        small_proxy_signed_amount=('_small_signed', 'sum'),
        large_proxy_count=('_large', 'sum'),
        small_proxy_count=('_small', 'sum'),
        amount_threshold_stock_q75=('amount_threshold_stock_q75', 'first'),
        amount_threshold_market_q75=('amount_threshold_market_q75', 'first'),
        ret_sum=('minute_ret', 'sum'),
        ret2_sum=('_minute_ret_2', 'sum'),
        ret3_sum=('_minute_ret_3', 'sum'),
        ret4_sum=('_minute_ret_4', 'sum'),
        amount1_sum=('amount_abs', 'sum'),
        amount2_sum=('_amount_abs_2', 'sum'),
        amount3_sum=('_amount_abs_3', 'sum'),
        amount4_sum=('_amount_abs_4', 'sum'),
        signed1_sum=('signed_amount', 'sum'),
        signed2_sum=('_signed_amount_2', 'sum'),
        signed3_sum=('_signed_amount_3', 'sum'),
        signed4_sum=('_signed_amount_4', 'sum'),
    )
    base = base[base['minute_count'] >= params.min_minutes].copy()
    if base.empty:
        return pd.DataFrame(columns=P0_COLUMNS)
    ret = _moment_columns('ret', base['minute_count'], base['ret_sum'], base['ret2_sum'], base['ret3_sum'], base['ret4_sum'])
    amount = _moment_columns('amount', base['minute_count'], base['amount1_sum'], base['amount2_sum'], base['amount3_sum'], base['amount4_sum'])
    signed = _moment_columns('signed_amount', base['minute_count'], base['signed1_sum'], base['signed2_sum'], base['signed3_sum'], base['signed4_sum'])
    out = pd.concat([base, ret, amount, signed], axis=1)
    out['amount_hhi'] = np.where(out['amount_sum'] > 0, out['amount_sq_sum'] / (out['amount_sum'] ** 2), 0.0)
    out['signed_flow_hhi'] = np.where(out['signed_abs_sum'] > 0, out['signed_abs_sq_sum'] / (out['signed_abs_sum'] ** 2), 0.0)
    entropy_denominator = np.log(out['minute_count'].astype(float))
    entropy = -((out['amount_log_amount_sum'] / out['amount_sum']) - np.log(out['amount_sum'])) / entropy_denominator.replace(0.0, np.nan)
    out['amount_entropy'] = entropy.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    out['ret_tail_asymmetry'] = _tail_asymmetry_by_group(current, keys, 'minute_ret', 'ret_tail_asymmetry')
    out['signed_flow_tail_asymmetry'] = _tail_asymmetry_by_group(current, keys, 'signed_amount', 'signed_flow_tail_asymmetry')
    out = out.reset_index()
    out['cutoff_time'] = cutoff
    out['threshold_source'] = 'prior_dates'
    out['threshold_lookback_days'] = int(params.threshold_lookback_days[0])
    out['schema_version'] = SCHEMA_VERSION
    out['producer_version'] = PRODUCER_VERSION
    out['source_dataset'] = SOURCE_DATASET
    out['no_future_intraday_minutes'] = True
    out['research_window'] = params.research_window
    return out[P0_COLUMNS]


def _polars_moment_exprs(prefix: str, n_col: str, s1_col: str, s2_col: str, s3_col: str, s4_col: str) -> list[Any]:
    import polars as pl

    n = pl.col(n_col).cast(pl.Float64)
    mean = pl.col(s1_col) / n
    raw2 = pl.col(s2_col) / n
    raw3 = pl.col(s3_col) / n
    raw4 = pl.col(s4_col) / n
    variance = (raw2 - mean.pow(2)).clip(lower_bound=0.0)
    std = variance.sqrt()
    m3 = raw3 - (3.0 * mean * raw2) + (2.0 * mean.pow(3))
    m4 = raw4 - (4.0 * mean * raw3) + (6.0 * mean.pow(2) * raw2) - (3.0 * mean.pow(4))
    return [
        mean.fill_nan(0.0).fill_null(0.0).alias(f'{prefix}_mean'),
        std.fill_nan(0.0).fill_null(0.0).alias(f'{prefix}_std'),
        pl.when(std > 0).then(m3 / std.pow(3)).otherwise(0.0).fill_nan(0.0).fill_null(0.0).alias(f'{prefix}_skew'),
        pl.when(std > 0).then((m4 / std.pow(4)) - 3.0).otherwise(0.0).fill_nan(0.0).fill_null(0.0).alias(f'{prefix}_excess_kurtosis'),
    ]


def _polars_tail_asymmetry(frame: Any, keys: list[str], value_col: str, output_col: str) -> Any:
    import polars as pl

    quantiles = frame.group_by(keys).agg(
        pl.col(value_col).quantile(0.1).alias('_q10'),
        pl.col(value_col).quantile(0.9).alias('_q90'),
    )
    tails = (
        frame.join(quantiles, on=keys, how='left')
        .with_columns(
            pl.when(pl.col(value_col) <= pl.col('_q10')).then(pl.col(value_col).abs()).otherwise(0.0).alias('_lower_abs'),
            pl.when(pl.col(value_col) >= pl.col('_q90')).then(pl.col(value_col).abs()).otherwise(0.0).alias('_upper_abs'),
        )
        .group_by(keys)
        .agg(
            pl.col('_lower_abs').sum().alias('_lower_abs_sum'),
            pl.col('_upper_abs').sum().alias('_upper_abs_sum'),
        )
        .with_columns(
            pl.when((pl.col('_lower_abs_sum') + pl.col('_upper_abs_sum')) > 0)
            .then((pl.col('_upper_abs_sum') - pl.col('_lower_abs_sum')) / (pl.col('_upper_abs_sum') + pl.col('_lower_abs_sum')))
            .otherwise(0.0)
            .alias(output_col)
        )
        .select([*keys, output_col])
    )
    return tails


def _derive_polars_for_cutoff(
    minute: pd.DataFrame,
    *,
    targets: set[str],
    cutoff_time: str,
    params: FlowDistributionParams,
    thresholds: pd.DataFrame,
) -> pd.DataFrame:
    import polars as pl

    cutoff = normalize_cutoff_time(cutoff_time)
    current = pl.from_pandas(minute)
    current = current.filter(
        pl.col('trade_date').is_in(sorted(targets))
        & (pl.col('hhmmss') <= cutoff_to_hhmmss(cutoff))
    )
    if current.is_empty():
        return pd.DataFrame(columns=P0_COLUMNS)

    thresholds_pl = pl.from_pandas(thresholds) if not thresholds.empty else pl.DataFrame({
        'ts_code': [],
        'trade_date': [],
        'amount_threshold_stock_q75': [],
        'amount_threshold_market_q75': [],
    })
    current = (
        current.join(thresholds_pl, on=['ts_code', 'trade_date'], how='left')
        .with_columns(
            pl.col('amount_threshold_stock_q75').fill_null(0.0).alias('amount_threshold_stock_q75'),
            pl.col('amount_threshold_market_q75').fill_null(0.0).alias('amount_threshold_market_q75'),
        )
        .with_columns(
            pl.when(pl.col('amount_threshold_stock_q75') > 0)
            .then(pl.col('amount_threshold_stock_q75'))
            .otherwise(pl.col('amount_threshold_market_q75'))
            .alias('_threshold')
        )
        .with_columns(
            ((pl.col('_threshold') > 0) & (pl.col('amount_abs') >= pl.col('_threshold'))).alias('_large')
        )
        .with_columns(
            pl.when(pl.col('_large')).then(pl.col('amount_abs')).otherwise(0.0).alias('_large_amount'),
            pl.when(~pl.col('_large')).then(pl.col('amount_abs')).otherwise(0.0).alias('_small_amount'),
            pl.when(pl.col('_large')).then(pl.col('signed_amount')).otherwise(0.0).alias('_large_signed'),
            pl.when(~pl.col('_large')).then(pl.col('signed_amount')).otherwise(0.0).alias('_small_signed'),
            pl.col('signed_amount').abs().alias('_signed_abs'),
            (pl.col('minute_ret') ** 2).alias('_minute_ret_2'),
            (pl.col('minute_ret') ** 3).alias('_minute_ret_3'),
            (pl.col('minute_ret') ** 4).alias('_minute_ret_4'),
            (pl.col('amount_abs') ** 2).alias('_amount_abs_2'),
            (pl.col('amount_abs') ** 3).alias('_amount_abs_3'),
            (pl.col('amount_abs') ** 4).alias('_amount_abs_4'),
            (pl.col('signed_amount') ** 2).alias('_signed_amount_2'),
            (pl.col('signed_amount') ** 3).alias('_signed_amount_3'),
            (pl.col('signed_amount') ** 4).alias('_signed_amount_4'),
            (pl.col('amount_abs') * pl.col('amount_abs').clip(lower_bound=1e-300).log()).alias('_amount_log_amount'),
        )
    )
    keys = ['ts_code', 'trade_date']
    base = (
        current.group_by(keys)
        .agg(
            pl.len().alias('minute_count'),
            pl.col('amount_abs').sum().alias('amount_sum'),
            pl.col('_amount_abs_2').sum().alias('amount_sq_sum'),
            pl.col('_amount_log_amount').sum().alias('amount_log_amount_sum'),
            pl.col('vol').sum().alias('volume_sum'),
            pl.col('signed_amount').sum().alias('signed_amount_sum'),
            pl.col('_signed_abs').sum().alias('signed_abs_sum'),
            pl.col('_signed_amount_2').sum().alias('signed_abs_sq_sum'),
            pl.col('_large_amount').sum().alias('large_proxy_amount'),
            pl.col('_small_amount').sum().alias('small_proxy_amount'),
            pl.col('_large_signed').sum().alias('large_proxy_signed_amount'),
            pl.col('_small_signed').sum().alias('small_proxy_signed_amount'),
            pl.col('_large').sum().alias('large_proxy_count'),
            (~pl.col('_large')).sum().alias('small_proxy_count'),
            pl.col('amount_threshold_stock_q75').first().alias('amount_threshold_stock_q75'),
            pl.col('amount_threshold_market_q75').first().alias('amount_threshold_market_q75'),
            pl.col('minute_ret').sum().alias('ret_sum'),
            pl.col('_minute_ret_2').sum().alias('ret2_sum'),
            pl.col('_minute_ret_3').sum().alias('ret3_sum'),
            pl.col('_minute_ret_4').sum().alias('ret4_sum'),
            pl.col('amount_abs').sum().alias('amount1_sum'),
            pl.col('_amount_abs_2').sum().alias('amount2_sum'),
            pl.col('_amount_abs_3').sum().alias('amount3_sum'),
            pl.col('_amount_abs_4').sum().alias('amount4_sum'),
            pl.col('signed_amount').sum().alias('signed1_sum'),
            pl.col('_signed_amount_2').sum().alias('signed2_sum'),
            pl.col('_signed_amount_3').sum().alias('signed3_sum'),
            pl.col('_signed_amount_4').sum().alias('signed4_sum'),
        )
        .filter(pl.col('minute_count') >= params.min_minutes)
    )
    if base.is_empty():
        return pd.DataFrame(columns=P0_COLUMNS)

    ret_tail = _polars_tail_asymmetry(current, keys, 'minute_ret', 'ret_tail_asymmetry')
    signed_tail = _polars_tail_asymmetry(current, keys, 'signed_amount', 'signed_flow_tail_asymmetry')
    out = (
        base.with_columns(
            *_polars_moment_exprs('ret', 'minute_count', 'ret_sum', 'ret2_sum', 'ret3_sum', 'ret4_sum'),
            *_polars_moment_exprs('amount', 'minute_count', 'amount1_sum', 'amount2_sum', 'amount3_sum', 'amount4_sum'),
            *_polars_moment_exprs('signed_amount', 'minute_count', 'signed1_sum', 'signed2_sum', 'signed3_sum', 'signed4_sum'),
            pl.when(pl.col('amount_sum') > 0).then(pl.col('amount_sq_sum') / (pl.col('amount_sum') ** 2)).otherwise(0.0).alias('amount_hhi'),
            pl.when(pl.col('signed_abs_sum') > 0).then(pl.col('signed_abs_sq_sum') / (pl.col('signed_abs_sum') ** 2)).otherwise(0.0).alias('signed_flow_hhi'),
            pl.when((pl.col('amount_sum') > 0) & (pl.col('minute_count') > 1))
            .then(-((pl.col('amount_log_amount_sum') / pl.col('amount_sum')) - pl.col('amount_sum').log()) / pl.col('minute_count').cast(pl.Float64).log())
            .otherwise(0.0)
            .fill_nan(0.0)
            .fill_null(0.0)
            .alias('amount_entropy'),
        )
        .join(ret_tail, on=keys, how='left')
        .join(signed_tail, on=keys, how='left')
        .with_columns(
            pl.lit(cutoff).alias('cutoff_time'),
            pl.lit('prior_dates').alias('threshold_source'),
            pl.lit(int(params.threshold_lookback_days[0])).alias('threshold_lookback_days'),
            pl.lit(SCHEMA_VERSION).alias('schema_version'),
            pl.lit(PRODUCER_VERSION).alias('producer_version'),
            pl.lit(SOURCE_DATASET).alias('source_dataset'),
            pl.lit(True).alias('no_future_intraday_minutes'),
            pl.lit(params.research_window).alias('research_window'),
        )
        .select(P0_COLUMNS)
    )
    return out.to_pandas()


def _cumsum(values: np.ndarray) -> np.ndarray:
    return np.cumsum(np.asarray(values, dtype=float))


def _prefix_sum(cumulative: np.ndarray, end: int) -> float:
    return float(cumulative[end - 1]) if end > 0 else 0.0


def _derive_mapreduce_group(
    rows: pd.DataFrame,
    *,
    ts_code: str,
    trade_date: str,
    params: FlowDistributionParams,
    stock_threshold: float,
    market_threshold: float,
) -> list[dict[str, Any]]:
    ordered = rows.sort_values('hhmmss')
    times = ordered['hhmmss'].to_numpy(dtype=int)
    amount = ordered['amount_abs'].to_numpy(dtype=float)
    volume = pd.to_numeric(ordered['vol'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    minute_ret = ordered['minute_ret'].to_numpy(dtype=float)
    signed_amount = ordered['signed_amount'].to_numpy(dtype=float)
    threshold = stock_threshold if stock_threshold > 0 else market_threshold
    large_mask = amount >= threshold if threshold > 0 else np.zeros_like(amount, dtype=bool)
    small_mask = ~large_mask

    amount2 = amount**2
    amount3 = amount**3
    amount4 = amount**4
    signed_abs = np.abs(signed_amount)
    ret2 = minute_ret**2
    ret3 = minute_ret**3
    ret4 = minute_ret**4
    signed2 = signed_amount**2
    signed3 = signed_amount**3
    signed4 = signed_amount**4
    amount_log_amount = amount * np.log(np.clip(amount, 1e-300, None))

    cumulative = {
        'amount': _cumsum(amount),
        'amount2': _cumsum(amount2),
        'amount3': _cumsum(amount3),
        'amount4': _cumsum(amount4),
        'amount_log_amount': _cumsum(amount_log_amount),
        'volume': _cumsum(volume),
        'ret': _cumsum(minute_ret),
        'ret2': _cumsum(ret2),
        'ret3': _cumsum(ret3),
        'ret4': _cumsum(ret4),
        'signed': _cumsum(signed_amount),
        'signed_abs': _cumsum(signed_abs),
        'signed2': _cumsum(signed2),
        'signed3': _cumsum(signed3),
        'signed4': _cumsum(signed4),
        'large_amount': _cumsum(np.where(large_mask, amount, 0.0)),
        'small_amount': _cumsum(np.where(small_mask, amount, 0.0)),
        'large_signed': _cumsum(np.where(large_mask, signed_amount, 0.0)),
        'small_signed': _cumsum(np.where(small_mask, signed_amount, 0.0)),
        'large_count': np.cumsum(large_mask.astype(int)),
        'small_count': np.cumsum(small_mask.astype(int)),
    }

    out: list[dict[str, Any]] = []
    for cutoff_time in [normalize_cutoff_time(item) for item in params.cutoff_times]:
        end = int(np.searchsorted(times, cutoff_to_hhmmss(cutoff_time), side='right'))
        if end < params.min_minutes:
            continue
        amount_sum = _prefix_sum(cumulative['amount'], end)
        amount_sq_sum = _prefix_sum(cumulative['amount2'], end)
        amount_log_sum = _prefix_sum(cumulative['amount_log_amount'], end)
        ret_stats = _moment_stats_from_sums(
            end,
            _prefix_sum(cumulative['ret'], end),
            _prefix_sum(cumulative['ret2'], end),
            _prefix_sum(cumulative['ret3'], end),
            _prefix_sum(cumulative['ret4'], end),
        )
        amount_stats = _moment_stats_from_sums(
            end,
            amount_sum,
            amount_sq_sum,
            _prefix_sum(cumulative['amount3'], end),
            _prefix_sum(cumulative['amount4'], end),
        )
        signed_abs_sum = _prefix_sum(cumulative['signed_abs'], end)
        signed_stats = _moment_stats_from_sums(
            end,
            _prefix_sum(cumulative['signed'], end),
            _prefix_sum(cumulative['signed2'], end),
            _prefix_sum(cumulative['signed3'], end),
            _prefix_sum(cumulative['signed4'], end),
        )
        amount_entropy = 0.0
        if amount_sum > 0 and end > 1:
            amount_entropy = -((amount_log_sum / amount_sum) - math.log(amount_sum)) / math.log(end)
            amount_entropy = amount_entropy if math.isfinite(amount_entropy) else 0.0
        prefix_ret = minute_ret[:end]
        prefix_signed = signed_amount[:end]
        out.append({
            'ts_code': str(ts_code),
            'trade_date': trade_date,
            'cutoff_time': cutoff_time,
            'minute_count': end,
            'amount_sum': amount_sum,
            'volume_sum': _prefix_sum(cumulative['volume'], end),
            'ret_mean': ret_stats['mean'],
            'ret_std': ret_stats['std'],
            'ret_skew': ret_stats['skew'],
            'ret_excess_kurtosis': ret_stats['excess_kurtosis'],
            'ret_tail_asymmetry': _tail_asymmetry(prefix_ret),
            'amount_mean': amount_stats['mean'],
            'amount_std': amount_stats['std'],
            'amount_skew': amount_stats['skew'],
            'amount_excess_kurtosis': amount_stats['excess_kurtosis'],
            'amount_hhi': amount_sq_sum / (amount_sum**2) if amount_sum > 0 else 0.0,
            'amount_entropy': amount_entropy,
            'signed_amount_sum': _prefix_sum(cumulative['signed'], end),
            'signed_amount_mean': signed_stats['mean'],
            'signed_amount_std': signed_stats['std'],
            'signed_amount_skew': signed_stats['skew'],
            'signed_amount_excess_kurtosis': signed_stats['excess_kurtosis'],
            'signed_flow_hhi': _prefix_sum(cumulative['signed2'], end) / (signed_abs_sum**2) if signed_abs_sum > 0 else 0.0,
            'signed_flow_tail_asymmetry': _tail_asymmetry(prefix_signed),
            'large_proxy_amount': _prefix_sum(cumulative['large_amount'], end),
            'small_proxy_amount': _prefix_sum(cumulative['small_amount'], end),
            'large_proxy_signed_amount': _prefix_sum(cumulative['large_signed'], end),
            'small_proxy_signed_amount': _prefix_sum(cumulative['small_signed'], end),
            'large_proxy_count': int(cumulative['large_count'][end - 1]),
            'small_proxy_count': int(cumulative['small_count'][end - 1]),
            'amount_threshold_stock_q75': float(stock_threshold),
            'amount_threshold_market_q75': float(market_threshold),
            'threshold_source': 'prior_dates',
            'threshold_lookback_days': int(params.threshold_lookback_days[0]),
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'source_dataset': SOURCE_DATASET,
            'no_future_intraday_minutes': True,
            'research_window': params.research_window,
        })
    return out


@lru_cache(maxsize=1)
def _numba_cutoff_kernel() -> Any:
    from numba import njit

    @njit
    def _quantile_sorted(values: np.ndarray, n: int, q: float) -> float:
        if n <= 0:
            return 0.0
        copied = np.empty(n, dtype=np.float64)
        for i in range(n):
            copied[i] = values[i]
        copied.sort()
        h = (n - 1) * q
        lo = int(math.floor(h))
        hi = int(math.ceil(h))
        if lo == hi:
            return copied[lo]
        frac = h - lo
        return copied[lo] * (1.0 - frac) + copied[hi] * frac

    @njit
    def _tail(values: np.ndarray, n: int) -> float:
        if n < 2:
            return 0.0
        q10 = _quantile_sorted(values, n, 0.1)
        q90 = _quantile_sorted(values, n, 0.9)
        upper = 0.0
        lower = 0.0
        for i in range(n):
            v = values[i]
            av = abs(v)
            if v >= q90:
                upper += av
            if v <= q10:
                lower += av
        denom = upper + lower
        if denom <= 0:
            return 0.0
        return (upper - lower) / denom

    @njit
    def _moments(n: int, s1: float, s2: float, s3: float, s4: float) -> tuple[float, float, float, float]:
        if n <= 0:
            return 0.0, 0.0, 0.0, 0.0
        nf = float(n)
        mean = s1 / nf
        raw2 = s2 / nf
        raw3 = s3 / nf
        raw4 = s4 / nf
        variance = raw2 - mean * mean
        if variance < 0.0:
            variance = 0.0
        std = math.sqrt(variance)
        if std <= 0.0:
            return mean, 0.0, 0.0, 0.0
        m3 = raw3 - 3.0 * mean * raw2 + 2.0 * mean * mean * mean
        m4 = raw4 - 4.0 * mean * raw3 + 6.0 * mean * mean * raw2 - 3.0 * mean * mean * mean * mean
        return mean, std, m3 / (std * std * std), m4 / (std * std * std * std) - 3.0

    @njit
    def kernel(
        times: np.ndarray,
        amount: np.ndarray,
        volume: np.ndarray,
        minute_ret: np.ndarray,
        signed_amount: np.ndarray,
        cutoff_keys: np.ndarray,
        threshold: float,
        min_minutes: int,
    ) -> np.ndarray:
        out = np.empty((len(cutoff_keys), 29), dtype=np.float64)
        out[:, :] = np.nan
        n_rows = len(times)
        for c in range(len(cutoff_keys)):
            cutoff = cutoff_keys[c]
            end = 0
            while end < n_rows and times[end] <= cutoff:
                end += 1
            if end < min_minutes:
                continue

            amount_sum = 0.0
            amount2_sum = 0.0
            amount3_sum = 0.0
            amount4_sum = 0.0
            amount_log_sum = 0.0
            volume_sum = 0.0
            ret_sum = 0.0
            ret2_sum = 0.0
            ret3_sum = 0.0
            ret4_sum = 0.0
            signed_sum = 0.0
            signed_abs_sum = 0.0
            signed2_sum = 0.0
            signed3_sum = 0.0
            signed4_sum = 0.0
            large_amount = 0.0
            small_amount = 0.0
            large_signed = 0.0
            small_signed = 0.0
            large_count = 0.0
            small_count = 0.0
            prefix_ret = np.empty(end, dtype=np.float64)
            prefix_signed = np.empty(end, dtype=np.float64)

            for i in range(end):
                a = amount[i]
                r = minute_ret[i]
                s = signed_amount[i]
                amount_sum += a
                amount2_sum += a * a
                amount3_sum += a * a * a
                amount4_sum += a * a * a * a
                if a > 0:
                    amount_log_sum += a * math.log(a)
                volume_sum += volume[i]
                ret_sum += r
                ret2_sum += r * r
                ret3_sum += r * r * r
                ret4_sum += r * r * r * r
                signed_sum += s
                signed_abs_sum += abs(s)
                signed2_sum += s * s
                signed3_sum += s * s * s
                signed4_sum += s * s * s * s
                if threshold > 0.0 and a >= threshold:
                    large_amount += a
                    large_signed += s
                    large_count += 1.0
                else:
                    small_amount += a
                    small_signed += s
                    small_count += 1.0
                prefix_ret[i] = r
                prefix_signed[i] = s

            ret_mean, ret_std, ret_skew, ret_kurt = _moments(end, ret_sum, ret2_sum, ret3_sum, ret4_sum)
            amount_mean, amount_std, amount_skew, amount_kurt = _moments(end, amount_sum, amount2_sum, amount3_sum, amount4_sum)
            signed_mean, signed_std, signed_skew, signed_kurt = _moments(end, signed_sum, signed2_sum, signed3_sum, signed4_sum)
            amount_hhi = 0.0
            signed_hhi = 0.0
            entropy = 0.0
            if amount_sum > 0.0:
                amount_hhi = amount2_sum / (amount_sum * amount_sum)
                if end > 1:
                    entropy = -((amount_log_sum / amount_sum) - math.log(amount_sum)) / math.log(float(end))
                    if not math.isfinite(entropy):
                        entropy = 0.0
            if signed_abs_sum > 0.0:
                signed_hhi = signed2_sum / (signed_abs_sum * signed_abs_sum)

            out[c, 0] = float(end)
            out[c, 1] = amount_sum
            out[c, 2] = volume_sum
            out[c, 3] = ret_mean
            out[c, 4] = ret_std
            out[c, 5] = ret_skew
            out[c, 6] = ret_kurt
            out[c, 7] = _tail(prefix_ret, end)
            out[c, 8] = amount_mean
            out[c, 9] = amount_std
            out[c, 10] = amount_skew
            out[c, 11] = amount_kurt
            out[c, 12] = amount_hhi
            out[c, 13] = entropy
            out[c, 14] = signed_sum
            out[c, 15] = signed_mean
            out[c, 16] = signed_std
            out[c, 17] = signed_skew
            out[c, 18] = signed_kurt
            out[c, 19] = signed_hhi
            out[c, 20] = _tail(prefix_signed, end)
            out[c, 21] = large_amount
            out[c, 22] = small_amount
            out[c, 23] = large_signed
            out[c, 24] = small_signed
            out[c, 25] = large_count
            out[c, 26] = small_count
            out[c, 27] = threshold
            out[c, 28] = cutoff
        return out

    return kernel


def _derive_numba_group(
    rows: pd.DataFrame,
    *,
    ts_code: str,
    trade_date: str,
    params: FlowDistributionParams,
    stock_threshold: float,
    market_threshold: float,
) -> list[dict[str, Any]]:
    ordered = rows.sort_values('hhmmss')
    cutoff_times = [normalize_cutoff_time(item) for item in params.cutoff_times]
    cutoff_keys = np.asarray([cutoff_to_hhmmss(item) for item in cutoff_times], dtype=np.int64)
    threshold = stock_threshold if stock_threshold > 0 else market_threshold
    result = _numba_cutoff_kernel()(
        ordered['hhmmss'].to_numpy(dtype=np.int64),
        ordered['amount_abs'].to_numpy(dtype=np.float64),
        pd.to_numeric(ordered['vol'], errors='coerce').fillna(0.0).to_numpy(dtype=np.float64),
        ordered['minute_ret'].to_numpy(dtype=np.float64),
        ordered['signed_amount'].to_numpy(dtype=np.float64),
        cutoff_keys,
        float(threshold),
        int(params.min_minutes),
    )
    out: list[dict[str, Any]] = []
    for idx, values in enumerate(result):
        if not np.isfinite(values[0]):
            continue
        out.append({
            'ts_code': str(ts_code),
            'trade_date': trade_date,
            'cutoff_time': cutoff_times[idx],
            'minute_count': int(values[0]),
            'amount_sum': float(values[1]),
            'volume_sum': float(values[2]),
            'ret_mean': float(values[3]),
            'ret_std': float(values[4]),
            'ret_skew': float(values[5]),
            'ret_excess_kurtosis': float(values[6]),
            'ret_tail_asymmetry': float(values[7]),
            'amount_mean': float(values[8]),
            'amount_std': float(values[9]),
            'amount_skew': float(values[10]),
            'amount_excess_kurtosis': float(values[11]),
            'amount_hhi': float(values[12]),
            'amount_entropy': float(values[13]),
            'signed_amount_sum': float(values[14]),
            'signed_amount_mean': float(values[15]),
            'signed_amount_std': float(values[16]),
            'signed_amount_skew': float(values[17]),
            'signed_amount_excess_kurtosis': float(values[18]),
            'signed_flow_hhi': float(values[19]),
            'signed_flow_tail_asymmetry': float(values[20]),
            'large_proxy_amount': float(values[21]),
            'small_proxy_amount': float(values[22]),
            'large_proxy_signed_amount': float(values[23]),
            'small_proxy_signed_amount': float(values[24]),
            'large_proxy_count': int(values[25]),
            'small_proxy_count': int(values[26]),
            'amount_threshold_stock_q75': float(stock_threshold),
            'amount_threshold_market_q75': float(market_threshold),
            'threshold_source': 'prior_dates',
            'threshold_lookback_days': int(params.threshold_lookback_days[0]),
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'source_dataset': SOURCE_DATASET,
            'no_future_intraday_minutes': True,
            'research_window': params.research_window,
        })
    return out


@lru_cache(maxsize=1)
def _numba_sorted_cutoff_kernel() -> Any:
    from numba import njit, prange

    @njit
    def _quantile_slice(values: np.ndarray, start: int, end: int, q: float) -> float:
        n = end - start
        if n <= 0:
            return 0.0
        copied = np.empty(n, dtype=np.float64)
        for i in range(n):
            copied[i] = values[start + i]
        copied.sort()
        h = (n - 1) * q
        lo = int(math.floor(h))
        hi = int(math.ceil(h))
        if lo == hi:
            return copied[lo]
        frac = h - lo
        return copied[lo] * (1.0 - frac) + copied[hi] * frac

    @njit
    def _tail_slice(values: np.ndarray, start: int, end: int) -> float:
        n = end - start
        if n < 2:
            return 0.0
        q10 = _quantile_slice(values, start, end, 0.1)
        q90 = _quantile_slice(values, start, end, 0.9)
        upper = 0.0
        lower = 0.0
        for i in range(start, end):
            v = values[i]
            av = abs(v)
            if v >= q90:
                upper += av
            if v <= q10:
                lower += av
        denom = upper + lower
        if denom <= 0.0:
            return 0.0
        return (upper - lower) / denom

    @njit
    def _moments(n: int, s1: float, s2: float, s3: float, s4: float) -> tuple[float, float, float, float]:
        if n <= 0:
            return 0.0, 0.0, 0.0, 0.0
        nf = float(n)
        mean = s1 / nf
        raw2 = s2 / nf
        raw3 = s3 / nf
        raw4 = s4 / nf
        variance = raw2 - mean * mean
        if variance < 0.0:
            variance = 0.0
        std = math.sqrt(variance)
        if std <= 0.0:
            return mean, 0.0, 0.0, 0.0
        m3 = raw3 - 3.0 * mean * raw2 + 2.0 * mean * mean * mean
        m4 = raw4 - 4.0 * mean * raw3 + 6.0 * mean * mean * raw2 - 3.0 * mean * mean * mean * mean
        return mean, std, m3 / (std * std * std), m4 / (std * std * std * std) - 3.0

    @njit(parallel=True)
    def kernel(
        starts: np.ndarray,
        ends: np.ndarray,
        times: np.ndarray,
        amount: np.ndarray,
        volume: np.ndarray,
        minute_ret: np.ndarray,
        signed_amount: np.ndarray,
        cutoff_keys: np.ndarray,
        stock_thresholds: np.ndarray,
        market_thresholds: np.ndarray,
        min_minutes: int,
    ) -> np.ndarray:
        n_groups = len(starts)
        n_cutoffs = len(cutoff_keys)
        out = np.empty((n_groups * n_cutoffs, 31), dtype=np.float64)
        out[:, :] = np.nan
        for g in prange(n_groups):
            group_start = starts[g]
            group_end = ends[g]
            threshold = stock_thresholds[g]
            if threshold <= 0.0:
                threshold = market_thresholds[g]
            for c in range(n_cutoffs):
                cutoff = cutoff_keys[c]
                prefix_end = group_start
                while prefix_end < group_end and times[prefix_end] <= cutoff:
                    prefix_end += 1
                n = prefix_end - group_start
                row_idx = g * n_cutoffs + c
                if n < min_minutes:
                    continue

                amount_sum = 0.0
                amount2_sum = 0.0
                amount3_sum = 0.0
                amount4_sum = 0.0
                amount_log_sum = 0.0
                volume_sum = 0.0
                ret_sum = 0.0
                ret2_sum = 0.0
                ret3_sum = 0.0
                ret4_sum = 0.0
                signed_sum = 0.0
                signed_abs_sum = 0.0
                signed2_sum = 0.0
                signed3_sum = 0.0
                signed4_sum = 0.0
                large_amount = 0.0
                small_amount = 0.0
                large_signed = 0.0
                small_signed = 0.0
                large_count = 0.0
                small_count = 0.0

                for i in range(group_start, prefix_end):
                    a = amount[i]
                    r = minute_ret[i]
                    s = signed_amount[i]
                    amount_sum += a
                    amount2_sum += a * a
                    amount3_sum += a * a * a
                    amount4_sum += a * a * a * a
                    if a > 0.0:
                        amount_log_sum += a * math.log(a)
                    volume_sum += volume[i]
                    ret_sum += r
                    ret2_sum += r * r
                    ret3_sum += r * r * r
                    ret4_sum += r * r * r * r
                    signed_sum += s
                    signed_abs_sum += abs(s)
                    signed2_sum += s * s
                    signed3_sum += s * s * s
                    signed4_sum += s * s * s * s
                    if threshold > 0.0 and a >= threshold:
                        large_amount += a
                        large_signed += s
                        large_count += 1.0
                    else:
                        small_amount += a
                        small_signed += s
                        small_count += 1.0

                ret_mean, ret_std, ret_skew, ret_kurt = _moments(n, ret_sum, ret2_sum, ret3_sum, ret4_sum)
                amount_mean, amount_std, amount_skew, amount_kurt = _moments(n, amount_sum, amount2_sum, amount3_sum, amount4_sum)
                signed_mean, signed_std, signed_skew, signed_kurt = _moments(n, signed_sum, signed2_sum, signed3_sum, signed4_sum)
                amount_hhi = 0.0
                signed_hhi = 0.0
                entropy = 0.0
                if amount_sum > 0.0:
                    amount_hhi = amount2_sum / (amount_sum * amount_sum)
                    if n > 1:
                        entropy = -((amount_log_sum / amount_sum) - math.log(amount_sum)) / math.log(float(n))
                        if not math.isfinite(entropy):
                            entropy = 0.0
                if signed_abs_sum > 0.0:
                    signed_hhi = signed2_sum / (signed_abs_sum * signed_abs_sum)

                out[row_idx, 0] = float(g)
                out[row_idx, 1] = float(c)
                out[row_idx, 2] = float(n)
                out[row_idx, 3] = amount_sum
                out[row_idx, 4] = volume_sum
                out[row_idx, 5] = ret_mean
                out[row_idx, 6] = ret_std
                out[row_idx, 7] = ret_skew
                out[row_idx, 8] = ret_kurt
                out[row_idx, 9] = _tail_slice(minute_ret, group_start, prefix_end)
                out[row_idx, 10] = amount_mean
                out[row_idx, 11] = amount_std
                out[row_idx, 12] = amount_skew
                out[row_idx, 13] = amount_kurt
                out[row_idx, 14] = amount_hhi
                out[row_idx, 15] = entropy
                out[row_idx, 16] = signed_sum
                out[row_idx, 17] = signed_mean
                out[row_idx, 18] = signed_std
                out[row_idx, 19] = signed_skew
                out[row_idx, 20] = signed_kurt
                out[row_idx, 21] = signed_hhi
                out[row_idx, 22] = _tail_slice(signed_amount, group_start, prefix_end)
                out[row_idx, 23] = large_amount
                out[row_idx, 24] = small_amount
                out[row_idx, 25] = large_signed
                out[row_idx, 26] = small_signed
                out[row_idx, 27] = large_count
                out[row_idx, 28] = small_count
                out[row_idx, 29] = stock_thresholds[g]
                out[row_idx, 30] = market_thresholds[g]
        return out

    return kernel


def derive_intraday_flow_distribution_moments_numba_sorted(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    return derive_intraday_flow_distribution_moments_numba_sorted_prepared(
        minute,
        params,
        targets=targets,
        thresholds=thresholds,
    )


def derive_intraday_flow_distribution_moments_numba_sorted_prepared(
    minute: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    targets: set[str],
    thresholds: pd.DataFrame,
) -> pd.DataFrame:
    threshold_lookup = {
        (str(row.ts_code), str(row.trade_date)): (
            _safe_float(row.amount_threshold_stock_q75),
            _safe_float(row.amount_threshold_market_q75),
        )
        for row in thresholds.itertuples(index=False)
    }
    current = minute[minute['trade_date'].isin(targets)].sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)
    if current.empty:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'numba_sorted')

    group_sizes = current.groupby(['ts_code', 'trade_date'], sort=False).size().reset_index(name='_rows')
    lengths = group_sizes['_rows'].to_numpy(dtype=np.int64)
    ends = np.cumsum(lengths, dtype=np.int64)
    starts = ends - lengths
    stock_thresholds = np.empty(len(group_sizes), dtype=np.float64)
    market_thresholds = np.empty(len(group_sizes), dtype=np.float64)
    group_keys: list[tuple[str, str]] = []
    for idx, row in enumerate(group_sizes.itertuples(index=False)):
        ts_code = str(row.ts_code)
        trade_date = str(row.trade_date)
        stock_threshold, market_threshold = threshold_lookup.get(
            (ts_code, trade_date),
            (0.0, 0.0),
        )
        stock_thresholds[idx] = stock_threshold
        market_thresholds[idx] = market_threshold
        group_keys.append((ts_code, trade_date))

    cutoff_times = [normalize_cutoff_time(item) for item in params.cutoff_times]
    cutoff_keys = np.asarray([cutoff_to_hhmmss(item) for item in cutoff_times], dtype=np.int64)
    result = _numba_sorted_cutoff_kernel()(
        starts,
        ends,
        current['hhmmss'].to_numpy(dtype=np.int64),
        current['amount_abs'].to_numpy(dtype=np.float64),
        pd.to_numeric(current['vol'], errors='coerce').fillna(0.0).to_numpy(dtype=np.float64),
        current['minute_ret'].to_numpy(dtype=np.float64),
        current['signed_amount'].to_numpy(dtype=np.float64),
        cutoff_keys,
        stock_thresholds,
        market_thresholds,
        int(params.min_minutes),
    )

    rows: list[dict[str, Any]] = []
    for values in result:
        if not np.isfinite(values[0]):
            continue
        group_idx = int(values[0])
        cutoff_idx = int(values[1])
        ts_code, trade_date = group_keys[group_idx]
        rows.append({
            'ts_code': ts_code,
            'trade_date': trade_date,
            'cutoff_time': cutoff_times[cutoff_idx],
            'minute_count': int(values[2]),
            'amount_sum': float(values[3]),
            'volume_sum': float(values[4]),
            'ret_mean': float(values[5]),
            'ret_std': float(values[6]),
            'ret_skew': float(values[7]),
            'ret_excess_kurtosis': float(values[8]),
            'ret_tail_asymmetry': float(values[9]),
            'amount_mean': float(values[10]),
            'amount_std': float(values[11]),
            'amount_skew': float(values[12]),
            'amount_excess_kurtosis': float(values[13]),
            'amount_hhi': float(values[14]),
            'amount_entropy': float(values[15]),
            'signed_amount_sum': float(values[16]),
            'signed_amount_mean': float(values[17]),
            'signed_amount_std': float(values[18]),
            'signed_amount_skew': float(values[19]),
            'signed_amount_excess_kurtosis': float(values[20]),
            'signed_flow_hhi': float(values[21]),
            'signed_flow_tail_asymmetry': float(values[22]),
            'large_proxy_amount': float(values[23]),
            'small_proxy_amount': float(values[24]),
            'large_proxy_signed_amount': float(values[25]),
            'small_proxy_signed_amount': float(values[26]),
            'large_proxy_count': int(values[27]),
            'small_proxy_count': int(values[28]),
            'amount_threshold_stock_q75': float(values[29]),
            'amount_threshold_market_q75': float(values[30]),
            'threshold_source': 'prior_dates',
            'threshold_lookback_days': int(params.threshold_lookback_days[0]),
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'source_dataset': SOURCE_DATASET,
            'no_future_intraday_minutes': True,
            'research_window': params.research_window,
        })
    if not rows:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'numba_sorted')
    return _finalize_output(pd.DataFrame(rows), 'numba_sorted')


def derive_intraday_flow_distribution_moments_mapreduce(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    threshold_lookup = {
        (str(row.ts_code), str(row.trade_date)): (
            _safe_float(row.amount_threshold_stock_q75),
            _safe_float(row.amount_threshold_market_q75),
        )
        for row in thresholds.itertuples(index=False)
    }
    current = minute[minute['trade_date'].isin(targets)]
    rows: list[dict[str, Any]] = []
    for (ts_code, trade_date), group in current.groupby(['ts_code', 'trade_date'], sort=False):
        stock_threshold, market_threshold = threshold_lookup.get(
            (str(ts_code), str(trade_date)),
            (0.0, 0.0),
        )
        rows.extend(
            _derive_mapreduce_group(
                group,
                ts_code=str(ts_code),
                trade_date=str(trade_date),
                params=params,
                stock_threshold=stock_threshold,
                market_threshold=market_threshold,
            )
        )
    if not rows:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'mapreduce')
    return _finalize_output(pd.DataFrame(rows), 'mapreduce')


def derive_intraday_flow_distribution_moments_numba(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    threshold_lookup = {
        (str(row.ts_code), str(row.trade_date)): (
            _safe_float(row.amount_threshold_stock_q75),
            _safe_float(row.amount_threshold_market_q75),
        )
        for row in thresholds.itertuples(index=False)
    }
    current = minute[minute['trade_date'].isin(targets)]
    rows: list[dict[str, Any]] = []
    for (ts_code, trade_date), group in current.groupby(['ts_code', 'trade_date'], sort=False):
        stock_threshold, market_threshold = threshold_lookup.get(
            (str(ts_code), str(trade_date)),
            (0.0, 0.0),
        )
        rows.extend(
            _derive_numba_group(
                group,
                ts_code=str(ts_code),
                trade_date=str(trade_date),
                params=params,
                stock_threshold=stock_threshold,
                market_threshold=market_threshold,
            )
        )
    if not rows:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'numba')
    return _finalize_output(pd.DataFrame(rows), 'numba')


def _derive_mapreduce_group_item(item: tuple[Any, pd.DataFrame, FlowDistributionParams, dict[tuple[str, str], tuple[float, float]]]) -> list[dict[str, Any]]:
    key, group, params, threshold_lookup = item
    ts_code, trade_date = key
    stock_threshold, market_threshold = threshold_lookup.get(
        (str(ts_code), str(trade_date)),
        (0.0, 0.0),
    )
    return _derive_mapreduce_group(
        group,
        ts_code=str(ts_code),
        trade_date=str(trade_date),
        params=params,
        stock_threshold=stock_threshold,
        market_threshold=market_threshold,
    )


def _derive_mapreduce_shard_item(item: tuple[pd.DataFrame, FlowDistributionParams, dict[tuple[str, str], tuple[float, float]]]) -> list[dict[str, Any]]:
    shard, params, threshold_lookup = item
    rows: list[dict[str, Any]] = []
    for (ts_code, trade_date), group in shard.groupby(['ts_code', 'trade_date'], sort=False):
        stock_threshold, market_threshold = threshold_lookup.get(
            (str(ts_code), str(trade_date)),
            (0.0, 0.0),
        )
        rows.extend(
            _derive_mapreduce_group(
                group,
                ts_code=str(ts_code),
                trade_date=str(trade_date),
                params=params,
                stock_threshold=stock_threshold,
                market_threshold=market_threshold,
            )
        )
    return rows


def derive_intraday_flow_distribution_moments_mapreduce_threaded(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    threshold_lookup = {
        (str(row.ts_code), str(row.trade_date)): (
            _safe_float(row.amount_threshold_stock_q75),
            _safe_float(row.amount_threshold_market_q75),
        )
        for row in thresholds.itertuples(index=False)
    }
    current = minute[minute['trade_date'].isin(targets)]
    items = [
        (key, group, params, threshold_lookup)
        for key, group in current.groupby(['ts_code', 'trade_date'], sort=False)
    ]
    if not items:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'mapreduce_threaded')
    max_workers = min(32, max(1, os.cpu_count() or 1), len(items))
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for chunk in executor.map(_derive_mapreduce_group_item, items):
            rows.extend(chunk)
    if not rows:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'mapreduce_threaded')
    return _finalize_output(pd.DataFrame(rows), 'mapreduce_threaded')


def derive_intraday_flow_distribution_moments_process_sharded_mapreduce(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    threshold_lookup = {
        (str(row.ts_code), str(row.trade_date)): (
            _safe_float(row.amount_threshold_stock_q75),
            _safe_float(row.amount_threshold_market_q75),
        )
        for row in thresholds.itertuples(index=False)
    }
    current = minute[minute['trade_date'].isin(targets)].copy()
    if current.empty:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_mapreduce')

    workers = min(max(1, os.cpu_count() or 1), 8, int(current['ts_code'].nunique()))
    current['_shard_id'] = pd.util.hash_pandas_object(current['ts_code'], index=False).to_numpy() % workers
    shards = [
        shard.drop(columns=['_shard_id']).copy()
        for _, shard in current.groupby('_shard_id', sort=False)
        if not shard.empty
    ]
    if not shards:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_mapreduce')

    items = [(shard, params, threshold_lookup) for shard in shards]
    rows: list[dict[str, Any]] = []
    if len(items) == 1:
        rows.extend(_derive_mapreduce_shard_item(items[0]))
    else:
        with ProcessPoolExecutor(max_workers=len(items)) as executor:
            for chunk in executor.map(_derive_mapreduce_shard_item, items):
                rows.extend(chunk)
    if not rows:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_mapreduce')
    return _finalize_output(pd.DataFrame(rows), 'process_sharded_mapreduce')


def _derive_vectorized_shard_item(item: tuple[pd.DataFrame, FlowDistributionParams, set[str], pd.DataFrame]) -> pd.DataFrame:
    shard, params, targets, thresholds = item
    frames = [
        _derive_vectorized_for_cutoff(
            shard,
            targets=targets,
            cutoff_time=cutoff_time,
            params=params,
            thresholds=thresholds,
        )
        for cutoff_time in params.cutoff_times
    ]
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return pd.DataFrame(columns=P0_COLUMNS)
    return pd.concat(non_empty, ignore_index=True)


def derive_intraday_flow_distribution_moments_process_sharded_vectorized(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    current = minute[minute['trade_date'].isin(targets)].copy()
    if current.empty:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_vectorized')

    workers = min(max(1, os.cpu_count() or 1), 8, int(current['ts_code'].nunique()))
    current['_shard_id'] = pd.util.hash_pandas_object(current['ts_code'], index=False).to_numpy() % workers
    shards: list[pd.DataFrame] = []
    for _, shard in current.groupby('_shard_id', sort=False):
        if shard.empty:
            continue
        shards.append(shard.drop(columns=['_shard_id']).copy())
    if not shards:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_vectorized')

    items = [(shard, params, targets, thresholds) for shard in shards]
    frames: list[pd.DataFrame] = []
    if len(items) == 1:
        frames.append(_derive_vectorized_shard_item(items[0]))
    else:
        with ProcessPoolExecutor(max_workers=len(items)) as executor:
            for frame in executor.map(_derive_vectorized_shard_item, items):
                if not frame.empty:
                    frames.append(frame)
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_vectorized')
    return _finalize_output(pd.concat(non_empty, ignore_index=True), 'process_sharded_vectorized')


def derive_intraday_flow_distribution_moments_reference(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    market_threshold_by_date = {
        trade_date: _market_prior_thresholds(minute, trade_date, lookback_days, params.threshold_quantile)
        for trade_date in sorted(targets)
    }
    rows: list[dict[str, Any]] = []
    cutoff_times = [normalize_cutoff_time(item) for item in params.cutoff_times]
    for ts_code, stock in minute.groupby('ts_code', sort=True):
        for trade_date in sorted(targets):
            stock_threshold, _ = _prior_thresholds(stock, trade_date, lookback_days, params.threshold_quantile)
            market_threshold = market_threshold_by_date.get(trade_date, 0.0)
            for cutoff_time in cutoff_times:
                row = _derive_one(
                    stock,
                    ts_code=str(ts_code),
                    trade_date=trade_date,
                    cutoff_time=cutoff_time,
                    params=params,
                    stock_threshold=stock_threshold,
                    market_threshold=market_threshold,
                )
                if row is not None:
                    rows.append(row)
    if not rows:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'reference')
    return _finalize_output(pd.DataFrame(rows), 'reference')


def derive_intraday_flow_distribution_moments_vectorized(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    frames = [
        _derive_vectorized_for_cutoff(
            minute,
            targets=targets,
            cutoff_time=cutoff_time,
            params=params,
            thresholds=thresholds,
        )
        for cutoff_time in params.cutoff_times
    ]
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'vectorized')
    return _finalize_output(pd.concat(non_empty, ignore_index=True), 'vectorized')


def derive_intraday_flow_distribution_moments_polars(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    frames = [
        _derive_polars_for_cutoff(
            minute,
            targets=targets,
            cutoff_time=cutoff_time,
            params=params,
            thresholds=thresholds,
        )
        for cutoff_time in params.cutoff_times
    ]
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'polars')
    return _finalize_output(pd.concat(non_empty, ignore_index=True), 'polars')


def _coerce_prepared_minute_frame(prepared_minute_df: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(PREPARED_MINUTE_COLUMNS) - set(prepared_minute_df.columns))
    if missing:
        raise ValueError(f'prepared_minute_df missing required columns: {missing}')
    minute = prepared_minute_df[PREPARED_MINUTE_COLUMNS].copy()
    minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
    minute['hhmmss'] = pd.to_numeric(minute['hhmmss'], errors='coerce')
    for col in ['amount_abs', 'minute_ret', 'signed_amount', 'vol']:
        minute[col] = pd.to_numeric(minute[col], errors='coerce')
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'hhmmss', 'amount_abs', 'minute_ret', 'signed_amount'])
    minute = minute[minute['amount_abs'].abs() > 0].copy()
    minute['hhmmss'] = minute['hhmmss'].astype(int)
    return minute.sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)


def derive_intraday_flow_distribution_moments_from_prepared(
    prepared_minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = _coerce_prepared_minute_frame(prepared_minute_df)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else set(minute['trade_date'].unique())
    lookback_days = int(params.threshold_lookback_days[0])
    thresholds = _build_threshold_frame(minute, targets, lookback_days, params.threshold_quantile, params.threshold_backend)
    backend = str(params.operator_backend or 'vectorized').lower()

    if backend == 'numba_sorted':
        out = derive_intraday_flow_distribution_moments_numba_sorted_prepared(
            minute,
            params,
            targets=targets,
            thresholds=thresholds,
        )
        out.attrs['operator_backend'] = 'numba_sorted_prepared'
        return out
    if backend == 'polars':
        frames = [
            _derive_polars_for_cutoff(
                minute,
                targets=targets,
                cutoff_time=cutoff_time,
                params=params,
                thresholds=thresholds,
            )
            for cutoff_time in params.cutoff_times
        ]
        non_empty = [frame for frame in frames if not frame.empty]
        if not non_empty:
            return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'polars_prepared')
        return _finalize_output(pd.concat(non_empty, ignore_index=True), 'polars_prepared')
    if backend == 'process_sharded_vectorized':
        current = minute[minute['trade_date'].isin(targets)].copy()
        if current.empty:
            return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_vectorized_prepared')
        workers = min(max(1, os.cpu_count() or 1), 8, int(current['ts_code'].nunique()))
        current['_shard_id'] = pd.util.hash_pandas_object(current['ts_code'], index=False).to_numpy() % workers
        shards = [
            shard.drop(columns=['_shard_id']).copy()
            for _, shard in current.groupby('_shard_id', sort=False)
            if not shard.empty
        ]
        items = [(shard, params, targets, thresholds) for shard in shards]
        frames: list[pd.DataFrame] = []
        if len(items) == 1:
            frames.append(_derive_vectorized_shard_item(items[0]))
        else:
            with ProcessPoolExecutor(max_workers=len(items)) as executor:
                for frame in executor.map(_derive_vectorized_shard_item, items):
                    if not frame.empty:
                        frames.append(frame)
        non_empty = [frame for frame in frames if not frame.empty]
        if not non_empty:
            return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'process_sharded_vectorized_prepared')
        return _finalize_output(pd.concat(non_empty, ignore_index=True), 'process_sharded_vectorized_prepared')
    if backend not in {'vectorized', 'reference'}:
        raise ValueError(f'unsupported prepared operator_backend: {params.operator_backend}')
    frames = [
        _derive_vectorized_for_cutoff(
            minute,
            targets=targets,
            cutoff_time=cutoff_time,
            params=params,
            thresholds=thresholds,
        )
        for cutoff_time in params.cutoff_times
    ]
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'vectorized_prepared')
    return _finalize_output(pd.concat(non_empty, ignore_index=True), 'vectorized_prepared')


def derive_intraday_flow_distribution_moments(
    minute_df: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    backend = str(params.operator_backend or 'vectorized').lower()
    if backend == 'reference':
        return derive_intraday_flow_distribution_moments_reference(minute_df, params, target_dates=target_dates)
    if backend == 'numba':
        return derive_intraday_flow_distribution_moments_numba(minute_df, params, target_dates=target_dates)
    if backend == 'numba_sorted':
        return derive_intraday_flow_distribution_moments_numba_sorted(minute_df, params, target_dates=target_dates)
    if backend == 'mapreduce':
        return derive_intraday_flow_distribution_moments_mapreduce(minute_df, params, target_dates=target_dates)
    if backend == 'mapreduce_threaded':
        return derive_intraday_flow_distribution_moments_mapreduce_threaded(minute_df, params, target_dates=target_dates)
    if backend == 'process_sharded_mapreduce':
        return derive_intraday_flow_distribution_moments_process_sharded_mapreduce(minute_df, params, target_dates=target_dates)
    if backend == 'process_sharded_vectorized':
        return derive_intraday_flow_distribution_moments_process_sharded_vectorized(minute_df, params, target_dates=target_dates)
    if backend == 'polars':
        return derive_intraday_flow_distribution_moments_polars(minute_df, params, target_dates=target_dates)
    if backend != 'vectorized':
        raise ValueError(f'unsupported operator_backend: {params.operator_backend}')
    return derive_intraday_flow_distribution_moments_vectorized(minute_df, params, target_dates=target_dates)


def write_partitioned_datamart(frame: pd.DataFrame, output_root: str | Path) -> Path:
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(root, partition_cols=['trade_date'], index=False)
    return root


def build_catalog_entry(
    output_root: str | Path,
    qa_output: str | Path,
    start_date: str,
    end_date: str,
    *,
    storage: str | None = None,
    operator_backend: str = 'vectorized',
    threshold_lookback_days: tuple[int, ...] | list[int] = (20, 60),
    threshold_quantile: float = 0.75,
    threshold_backend: str = 'pandas',
    research_window: str = 'IS',
) -> dict[str, Any]:
    uri = str(output_root) if str(output_root).startswith('s3://') else str(Path(output_root).expanduser())
    return {
        'uri': uri,
        'format': 'parquet',
        'storage': storage or ('s3' if uri.startswith('s3://') else 'local'),
        'description': 'Intraday return, amount, and signed-flow distribution moments from minute_bar.',
        'columns': P0_COLUMNS,
        'partition_columns': ['trade_date'],
        'date_column': 'trade_date',
        'symbol_column': 'ts_code',
        'metadata': {
            'source_dataset': SOURCE_DATASET,
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'unique_key': UNIQUE_KEY,
            'sort_keys': SORT_KEYS,
            'supported_cutoff_times': list(DEFAULT_CUTOFF_TIMES),
            'threshold_source': 'prior_dates',
            'threshold_lookback_days': [int(item) for item in threshold_lookback_days],
            'threshold_quantile': float(threshold_quantile),
            'threshold_backend': threshold_backend,
            'operator_backend': operator_backend,
            'tail_asymmetry_method': 'exact_group_quantile_10_90_abs_mass',
            'no_future_intraday_minutes': True,
            'research_window': research_window,
            'missing_date_policy': 'source_ready_trade_dates_only',
            'oos_holdout_policy': 'post_20250711_marked_holdout_not_used_for_fitting',
            'field_boundary': 'state_variables_only_no_alpha_scores',
            'signed_flow_proxy': 'sign(close-open)*amount from 1m bars; not true order flow',
            'information_set_legality': 'all rows use trade_time <= cutoff_time and prior-date thresholds only',
            'qa_summary_path': str(Path(qa_output).expanduser()),
        },
        'freshness': {
            'trade_date_min': normalize_trade_date(start_date),
            'trade_date_max': normalize_trade_date(end_date),
        },
    }


def build_qa_summary(
    frame: pd.DataFrame,
    *,
    params: FlowDistributionParams,
    source_min_trade_date: str | None,
    source_max_trade_date: str | None,
    missing_dates: list[str],
    output_path: str | Path,
    catalog_path: str | Path,
    runtime_seconds: float,
    input_minute_row_count: int,
    performance_profile: dict[str, float] | None = None,
    source_profile: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    numeric = frame.select_dtypes(include=['number']).columns.tolist() if not frame.empty else []
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if not frame.empty else 0
    null_ratio = {col: float(frame[col].isna().mean()) for col in frame.columns} if not frame.empty else {}
    finite_ratio = {
        col: float(np.isfinite(pd.to_numeric(frame[col], errors='coerce')).mean())
        for col in numeric
    } if not frame.empty else {}
    non_negative_fields = ['minute_count', 'amount_sum', 'amount_hhi', 'signed_flow_hhi', 'large_proxy_amount', 'small_proxy_amount']
    non_negative_checks = {
        col: bool((pd.to_numeric(frame[col], errors='coerce') >= 0).all()) if col in frame.columns and not frame.empty else False
        for col in non_negative_fields
    }
    hhi_checks = {
        col: bool(((pd.to_numeric(frame[col], errors='coerce') >= 0) & (pd.to_numeric(frame[col], errors='coerce') <= 1)).all())
        if col in frame.columns and not frame.empty else False
        for col in ['amount_hhi', 'signed_flow_hhi']
    }
    no_future_ok = bool(frame['no_future_intraday_minutes'].eq(True).all()) if 'no_future_intraday_minutes' in frame.columns and not frame.empty else False
    prior_threshold_ok = bool(frame['threshold_source'].eq('prior_dates').all()) if 'threshold_source' in frame.columns and not frame.empty else False
    hard_checks = {
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'no_future_intraday_minutes_true': no_future_ok,
        'threshold_source_prior_dates': prior_threshold_ok,
        **non_negative_checks,
        **hhi_checks,
    }
    verdict = 'ACCEPT' if frame is not None and not frame.empty and all(hard_checks.values()) and not missing_dates else 'BLOCK'
    profile = {
        'read_seconds': 0.0,
        'compute_seconds': 0.0,
        'write_seconds': 0.0,
        **(performance_profile or {}),
    }
    return {
        'verdict': verdict,
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'operator_backend': str(params.operator_backend or 'vectorized').lower(),
        'realized_operator_backend': str(frame.attrs.get('operator_backend') or params.operator_backend or 'vectorized').lower(),
        'params': asdict(params),
        'source_min_trade_date': source_min_trade_date,
        'source_max_trade_date': source_max_trade_date,
        'output_min_trade_date': str(frame['trade_date'].min()) if 'trade_date' in frame.columns and not frame.empty else None,
        'output_max_trade_date': str(frame['trade_date'].max()) if 'trade_date' in frame.columns and not frame.empty else None,
        'row_count': int(len(frame)),
        'date_count': int(frame['trade_date'].nunique()) if 'trade_date' in frame.columns and not frame.empty else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'duplicate_key_count': duplicate_key_count,
        'missing_dates': list(missing_dates),
        'cutoff_times': sorted(frame['cutoff_time'].dropna().unique().tolist()) if 'cutoff_time' in frame.columns and not frame.empty else [],
        'threshold_source': 'prior_dates',
        'threshold_lookback_days': list(params.threshold_lookback_days),
        'no_future_intraday_minutes': True,
        'null_ratio_by_field': null_ratio,
        'finite_ratio_by_numeric_field': finite_ratio,
        'hard_checks': hard_checks,
        'coverage_by_date': frame.groupby('trade_date')['ts_code'].nunique().astype(int).to_dict() if not frame.empty else {},
        'runtime_seconds': float(runtime_seconds),
        'performance_profile': profile,
        'input_minute_row_count': int(input_minute_row_count),
        'output_path': str(Path(output_path).expanduser()),
        'catalog_path': str(Path(catalog_path).expanduser()),
        'source_profile': source_profile or [],
        'generated_at_utc': utc_now(),
    }
