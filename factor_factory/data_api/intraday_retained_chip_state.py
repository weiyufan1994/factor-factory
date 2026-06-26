from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATASET_ID = 'intraday_retained_chip_state_v1'
SCHEMA_VERSION = 'intraday_retained_chip_state_v1_p0'
PRODUCER_VERSION = 'factorforge_data_api_intraday_retained_chip_state_20260618'
SOURCE_DATASETS = ['minute_bar', 'daily_basic']
UNIQUE_KEY = ['ts_code', 'trade_date']
PARTITION_COLUMN = 'trade_date'
DEFAULT_INTERVAL_ENDPOINTS = (
    '09:45:00',
    '10:00:00',
    '10:15:00',
    '10:30:00',
    '10:45:00',
    '11:00:00',
    '11:15:00',
    '11:30:00',
    '13:15:00',
    '13:30:00',
    '13:45:00',
    '14:00:00',
    '14:15:00',
    '14:30:00',
    '14:45:00',
    '15:00:00',
)
OUTPUT_COLUMNS = [
    'ts_code',
    'trade_date',
    'lcr_raw',
    'retained_amount_sum',
    'amount_sum_20d',
    'interval_turnover_sum_20d',
    'survival_weighted_interval_count',
    'interval_count',
    'valid_interval_count',
    'lookback_days',
    'interval_minutes',
    'turnover_denominator_source',
    'float_share',
    'float_share_unit',
    'amount_unit',
    'source_min_date',
    'source_max_date',
    'missing_interval_count',
    'turnover_clipped_count',
    'qa_status',
    'schema_version',
    'producer_version',
    'source_datasets',
    'no_future_data',
    'no_future_intraday_minutes',
    'research_window',
]


@dataclass(frozen=True)
class IntradayRetainedChipStateParams:
    lookback_days: int = 20
    interval_minutes: int = 15
    cutoff_time: str = '15:00:00'
    interval_endpoints: tuple[str, ...] = DEFAULT_INTERVAL_ENDPOINTS
    turnover_denominator_col: str = 'float_share'
    turnover_denominator_source: str = 'daily_basic.float_share'
    float_share_unit: str = '10k_shares'
    minute_volume_unit: str = 'lot_100_shares'
    amount_unit: str = 'minute_bar_amount_as_delivered'
    volume_to_share_multiplier: float = 100.0
    float_share_to_share_multiplier: float = 10000.0
    turnover_clip_min: float = 0.0
    turnover_clip_max: float = 1.0
    is_end_date: str = '20250711'


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '')
    text = re.sub(r'\s+00:00:00$', '', text)
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'invalid trade_date: {value!r}')
    return parsed.strftime('%Y%m%d')


def normalize_hhmmss(value: Any) -> str:
    raw = str(value).strip()
    token = raw.split()[-1].replace(':', '')
    match = re.search(r'(\d{3,6})$', token)
    digits = match.group(1) if match else '150000'
    if len(digits) <= 4:
        digits = digits.zfill(4) + '00'
    else:
        digits = digits.zfill(6)[:6]
    return f'{digits[:2]}:{digits[2:4]}:{digits[4:6]}'


def hhmmss_to_int(value: Any) -> int:
    return int(normalize_hhmmss(value).replace(':', ''))


def _prepare_minute(minute_df: pd.DataFrame, params: IntradayRetainedChipStateParams) -> pd.DataFrame:
    required = {'ts_code', 'trade_date', 'vol'}
    missing = sorted(required - set(minute_df.columns))
    if missing:
        raise ValueError(f'minute_df missing required columns: {missing}')
    minute = minute_df.copy()
    if 'trade_time' not in minute.columns:
        if 'bar_time' in minute.columns:
            minute['trade_time'] = minute['bar_time']
        elif 'hhmmss' in minute.columns:
            minute['trade_time'] = minute['hhmmss'].astype(str).str.zfill(6)
        else:
            minute['trade_time'] = params.cutoff_time
    if 'amount' not in minute.columns:
        if 'amount_abs' not in minute.columns:
            raise ValueError('minute_df missing required amount column; expected amount or amount_abs')
        minute['amount'] = minute['amount_abs']
    minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
    minute['hhmmss'] = minute['trade_time'].map(hhmmss_to_int)
    cutoff = hhmmss_to_int(params.cutoff_time)
    minute = minute[minute['hhmmss'] <= cutoff].copy()
    minute['vol'] = pd.to_numeric(minute['vol'], errors='coerce')
    minute['amount'] = pd.to_numeric(minute['amount'], errors='coerce')
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'hhmmss', 'vol', 'amount'])
    minute = minute[(minute['vol'] >= 0) & (minute['amount'] >= 0)].copy()
    return minute.sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)


def _prepare_daily_basic(daily_basic_df: pd.DataFrame, params: IntradayRetainedChipStateParams) -> pd.DataFrame:
    required = {'ts_code', 'trade_date', params.turnover_denominator_col}
    missing = sorted(required - set(daily_basic_df.columns))
    if missing:
        raise ValueError(f'daily_basic_df missing required columns: {missing}')
    daily = daily_basic_df[['ts_code', 'trade_date', params.turnover_denominator_col]].copy()
    daily['trade_date'] = daily['trade_date'].map(normalize_trade_date)
    daily[params.turnover_denominator_col] = pd.to_numeric(daily[params.turnover_denominator_col], errors='coerce')
    daily = daily.dropna(subset=['ts_code', 'trade_date', params.turnover_denominator_col])
    daily = daily[daily[params.turnover_denominator_col] > 0].copy()
    return daily.rename(columns={params.turnover_denominator_col: 'float_share'})


def assign_interval_endpoints(minute: pd.DataFrame, endpoints: tuple[str, ...]) -> pd.Series:
    endpoint_values = np.array([hhmmss_to_int(value) for value in endpoints], dtype=np.int64)
    values = minute['hhmmss'].to_numpy(dtype=np.int64)
    positions = np.searchsorted(endpoint_values, values, side='left')
    valid = positions < len(endpoint_values)
    labels = np.full(len(minute), '', dtype=object)
    normalized = [normalize_hhmmss(value) for value in endpoints]
    for index, endpoint_index in enumerate(positions):
        if valid[index]:
            labels[index] = normalized[int(endpoint_index)]
    return pd.Series(labels, index=minute.index, dtype='string')


def build_interval_turnover_frame(
    minute_df: pd.DataFrame,
    daily_basic_df: pd.DataFrame,
    params: IntradayRetainedChipStateParams | None = None,
) -> pd.DataFrame:
    cfg = params or IntradayRetainedChipStateParams()
    minute = _prepare_minute(minute_df, cfg)
    daily = _prepare_daily_basic(daily_basic_df, cfg)
    minute['interval_end_time'] = assign_interval_endpoints(minute, tuple(cfg.interval_endpoints))
    minute = minute[minute['interval_end_time'].astype(str) != ''].copy()
    grouped = (
        minute.groupby(['ts_code', 'trade_date', 'interval_end_time'], sort=True, observed=True)
        .agg(interval_vol=('vol', 'sum'), interval_amount=('amount', 'sum'), minute_count=('amount', 'size'))
        .reset_index()
    )
    merged = grouped.merge(daily, on=['ts_code', 'trade_date'], how='left')
    denominator = merged['float_share'] * float(cfg.float_share_to_share_multiplier)
    numerator = merged['interval_vol'] * float(cfg.volume_to_share_multiplier)
    raw_turnover = numerator / denominator.replace(0, np.nan)
    clipped = raw_turnover.clip(lower=float(cfg.turnover_clip_min), upper=float(cfg.turnover_clip_max))
    merged['interval_turnover_rate_raw'] = raw_turnover
    merged['interval_turnover_rate'] = clipped
    merged['turnover_was_clipped'] = raw_turnover.notna() & (raw_turnover != clipped)
    merged['_interval_order'] = merged['trade_date'].astype(str) + '_' + merged['interval_end_time'].astype(str)
    return merged.sort_values(['ts_code', 'trade_date', 'interval_end_time']).reset_index(drop=True)


def derive_intraday_retained_chip_state(
    minute_df: pd.DataFrame,
    daily_basic_df: pd.DataFrame,
    trade_dates: list[str] | None = None,
    params: IntradayRetainedChipStateParams | None = None,
) -> pd.DataFrame:
    cfg = params or IntradayRetainedChipStateParams()
    if cfg.lookback_days <= 0:
        raise ValueError('lookback_days must be positive')
    intervals = build_interval_turnover_frame(minute_df, daily_basic_df, cfg)
    return derive_intraday_retained_chip_state_from_intervals(intervals, trade_dates=trade_dates, params=cfg)


def derive_intraday_retained_chip_state_from_intervals(
    intervals_df: pd.DataFrame,
    trade_dates: list[str] | None = None,
    params: IntradayRetainedChipStateParams | None = None,
) -> pd.DataFrame:
    cfg = params or IntradayRetainedChipStateParams()
    required = {
        'ts_code',
        'trade_date',
        'interval_end_time',
        'interval_amount',
        'interval_turnover_rate',
        'float_share',
        'turnover_was_clipped',
    }
    missing = sorted(required - set(intervals_df.columns))
    if missing:
        raise ValueError(f'intervals_df missing required columns: {missing}')
    intervals = intervals_df.copy()
    intervals['trade_date'] = intervals['trade_date'].map(normalize_trade_date)
    intervals['interval_end_time'] = intervals['interval_end_time'].map(normalize_hhmmss)
    all_dates = sorted({normalize_trade_date(date) for date in (trade_dates or intervals['trade_date'].unique().tolist())})
    by_date = {date: index for index, date in enumerate(all_dates)}
    endpoint_count = len(cfg.interval_endpoints)
    rows: list[dict[str, Any]] = []
    is_end = normalize_trade_date(cfg.is_end_date)
    for target_date in all_dates:
        end_index = by_date[target_date]
        window_dates = all_dates[max(0, end_index - int(cfg.lookback_days) + 1): end_index + 1]
        window_set = set(window_dates)
        window = intervals[intervals['trade_date'].isin(window_set)].copy()
        if window.empty:
            continue
        for ts_code, stock in window.groupby('ts_code', sort=True):
            stock = stock.sort_values(['trade_date', 'interval_end_time']).reset_index(drop=True)
            valid = stock.dropna(subset=['interval_amount', 'interval_turnover_rate', 'float_share']).copy()
            interval_count = int(len(stock))
            valid_interval_count = int(len(valid))
            expected_intervals = len(window_dates) * endpoint_count
            missing_interval_count = max(0, expected_intervals - valid_interval_count)
            if valid.empty:
                retained_amount_sum = np.nan
                amount_sum = 0.0
                lcr_raw = np.nan
                survival_weighted_count = 0
                turnover_sum = 0.0
                clipped_count = 0
                float_share = np.nan
                source_min = None
                source_max = None
            else:
                turnover = valid['interval_turnover_rate'].to_numpy(dtype=np.float64)
                amount = valid['interval_amount'].to_numpy(dtype=np.float64)
                survival_after = np.ones(len(valid), dtype=np.float64)
                running = 1.0
                for pos in range(len(valid) - 1, -1, -1):
                    survival_after[pos] = running
                    running *= max(0.0, 1.0 - float(turnover[pos]))
                retained = amount * survival_after
                amount_sum = float(np.nansum(amount))
                retained_amount_sum = float(np.nansum(retained))
                lcr_raw = retained_amount_sum / amount_sum if amount_sum > 0 else np.nan
                survival_weighted_count = int(np.isfinite(survival_after).sum())
                turnover_sum = float(np.nansum(turnover))
                clipped_count = int(valid['turnover_was_clipped'].sum())
                target_float = valid[valid['trade_date'] == target_date]['float_share']
                float_share = float(target_float.iloc[-1]) if not target_float.empty else float(valid['float_share'].iloc[-1])
                source_min = str(valid['trade_date'].min())
                source_max = str(valid['trade_date'].max())
            qa_flags: list[str] = []
            if amount_sum <= 0:
                qa_flags.append('amount_sum_20d_nonpositive')
            if missing_interval_count:
                qa_flags.append('missing_intervals')
            if clipped_count:
                qa_flags.append('turnover_clipped')
            rows.append({
                'ts_code': str(ts_code),
                'trade_date': target_date,
                'lcr_raw': lcr_raw,
                'retained_amount_sum': retained_amount_sum,
                'amount_sum_20d': amount_sum,
                'interval_turnover_sum_20d': turnover_sum,
                'survival_weighted_interval_count': survival_weighted_count,
                'interval_count': interval_count,
                'valid_interval_count': valid_interval_count,
                'lookback_days': int(cfg.lookback_days),
                'interval_minutes': int(cfg.interval_minutes),
                'turnover_denominator_source': cfg.turnover_denominator_source,
                'float_share': float_share,
                'float_share_unit': cfg.float_share_unit,
                'amount_unit': cfg.amount_unit,
                'source_min_date': source_min,
                'source_max_date': source_max,
                'missing_interval_count': int(missing_interval_count),
                'turnover_clipped_count': int(clipped_count),
                'qa_status': 'WARN:' + ','.join(qa_flags) if qa_flags else 'OK',
                'schema_version': SCHEMA_VERSION,
                'producer_version': PRODUCER_VERSION,
                'source_datasets': ','.join(SOURCE_DATASETS),
                'no_future_data': True,
                'no_future_intraday_minutes': True,
                'research_window': 'IS' if target_date <= is_end else 'OOS',
            })
    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if not out.empty:
        out = out.sort_values(UNIQUE_KEY).reset_index(drop=True)
    out.attrs['dataset_id'] = DATASET_ID
    out.attrs['schema_version'] = SCHEMA_VERSION
    out.attrs['producer_version'] = PRODUCER_VERSION
    out.attrs['unique_key'] = UNIQUE_KEY
    return out


def build_intraday_retained_chip_state_qa(
    frame: pd.DataFrame,
    *,
    expected_dates: list[str] | None = None,
    output_path: str | Path | None = None,
    runtime_seconds: float | None = None,
) -> dict[str, Any]:
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if not missing_columns else 0
    dates = frame['trade_date'].astype(str) if 'trade_date' in frame.columns and not frame.empty else pd.Series(dtype=str)
    covered_dates = sorted(dates.unique().tolist()) if not dates.empty else []
    expected = sorted({normalize_trade_date(date) for date in (expected_dates or covered_dates)})
    missing_dates = sorted(set(expected).difference(covered_dates))
    issues: list[str] = []
    if frame.empty:
        issues.append('row_count_zero')
    if missing_columns:
        issues.append('missing_expected_columns')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if missing_dates:
        issues.append('missing_dates')
    if 'no_future_data' in frame.columns and not frame.empty and not bool(frame['no_future_data'].all()):
        issues.append('no_future_data_not_true')
    if 'no_future_intraday_minutes' in frame.columns and not frame.empty and not bool(frame['no_future_intraday_minutes'].all()):
        issues.append('no_future_intraday_minutes_not_true')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_datasets': SOURCE_DATASETS,
        'unique_key': UNIQUE_KEY,
        'partition_column': PARTITION_COLUMN,
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if not dates.empty else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'start_date': str(dates.min()) if not dates.empty else None,
        'end_date': str(dates.max()) if not dates.empty else None,
        'expected_dates': expected,
        'covered_dates': covered_dates,
        'missing_dates': missing_dates,
        'duplicate_key_count': duplicate_key_count,
        'missing_columns': missing_columns,
        'missing_interval_count_sum': int(frame['missing_interval_count'].sum()) if 'missing_interval_count' in frame.columns and not frame.empty else 0,
        'turnover_clipped_count_sum': int(frame['turnover_clipped_count'].sum()) if 'turnover_clipped_count' in frame.columns and not frame.empty else 0,
        'qa_status_counts': frame['qa_status'].value_counts(dropna=False).to_dict() if 'qa_status' in frame.columns and not frame.empty else {},
        'research_windows': sorted(frame['research_window'].dropna().unique().tolist()) if 'research_window' in frame.columns and not frame.empty else [],
        'output_path': str(output_path) if output_path is not None else '',
        'runtime_seconds': runtime_seconds,
        'issues': issues,
        'information_set_legality': {
            'lookback_days': 20,
            'interval_minutes': 15,
            'cutoff_time': '15:00:00',
            'no_future_data': True,
            'no_future_intraday_minutes': True,
            'state_asof': 'selection trade_date close',
        },
    }


def write_partitioned_datamart(frame: pd.DataFrame, output_root: str | Path) -> Path:
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    for trade_date, part in frame.groupby('trade_date', sort=True):
        part_dir = root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True, exist_ok=True)
        part.drop(columns=['trade_date']).to_parquet(part_dir / 'part.parquet', index=False)
    return root
