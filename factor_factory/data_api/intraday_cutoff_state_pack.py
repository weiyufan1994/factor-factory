from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATASET_ID = 'intraday_cutoff_state_pack_v1'
SCHEMA_VERSION = 'intraday_cutoff_state_pack_v1'
PRODUCER_VERSION = 'factorforge_data_api_intraday_cutoff_state_pack_20260618'
SOURCE_DATASET = 'minute_bar'
UNIQUE_KEY = ['ts_code', 'trade_date', 'cutoff_time']
SORT_KEYS = ['trade_date', 'ts_code', 'cutoff_time']
DEFAULT_CUTOFF_TIMES = ('10:30:00', '11:30:00', '14:00:00', '14:30:00', '14:50:00', '14:55:00')
FEATURE_COLUMNS = [
    'minute_count',
    'first_open',
    'last_close',
    'cutoff_ret',
    'cutoff_vwap',
    'amount_sum',
    'volume_sum',
    'high_to_open',
    'low_to_open',
    'realized_vol',
    'mean_minute_ret',
    'positive_minute_share',
    'terminal_window_minutes',
    'terminal_ret_20m',
    'terminal_amount_share_20m',
    'terminal_volume_share_20m',
    'terminal_realized_vol_20m',
    'terminal_vwap_20m',
    'last_trade_time',
    'schema_version',
    'producer_version',
    'source_dataset',
    'no_future_intraday_minutes',
    'research_window',
]
OUTPUT_COLUMNS = ['ts_code', 'trade_date', 'cutoff_time', *FEATURE_COLUMNS]


@dataclass(frozen=True)
class IntradayCutoffStateParams:
    cutoff_times: tuple[str, ...] = DEFAULT_CUTOFF_TIMES
    min_minutes: int = 20
    terminal_window_minutes: int = 20
    research_window: str = 'IS'
    eps: float = 1e-12


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


def _hhmmss_to_text(value: int) -> str:
    text = f'{int(value):06d}'
    return f'{text[:2]}:{text[2:4]}:{text[4:6]}'


def prepare_minute_frame(minute_df: pd.DataFrame) -> pd.DataFrame:
    required = {'ts_code', 'trade_date', 'open', 'close'}
    missing = sorted(required - set(minute_df.columns))
    if missing:
        raise ValueError(f'minute_df missing required columns: {missing}')
    minute = minute_df.copy()
    if 'trade_time' not in minute.columns:
        minute['trade_time'] = minute['bar_time'] if 'bar_time' in minute.columns else '14:50:00'
    if 'high' not in minute.columns:
        minute['high'] = minute[['open', 'close']].max(axis=1)
    if 'low' not in minute.columns:
        minute['low'] = minute[['open', 'close']].min(axis=1)
    if 'amount' not in minute.columns:
        if 'vol' not in minute.columns:
            raise ValueError('minute_df must include amount or vol')
        minute['amount'] = minute['vol']
    if 'vol' not in minute.columns:
        minute['vol'] = 0.0
    for col in ['open', 'high', 'low', 'close', 'vol', 'amount']:
        minute[col] = pd.to_numeric(minute[col], errors='coerce')
    minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
    minute['hhmmss'] = time_key(minute['trade_time'])
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'amount'])
    minute = minute[(minute['open'] > 0) & (minute['close'] > 0)].copy()
    minute['amount_abs'] = minute['amount'].abs()
    minute['minute_ret'] = minute['close'] / minute['open'] - 1.0
    return minute.sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)


def _realized_vol(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors='coerce').dropna()
    if len(clean) < 2:
        return 0.0
    out = float(clean.std(ddof=0))
    return out if math.isfinite(out) else 0.0


def _derive_group_cutoff(
    rows: pd.DataFrame,
    *,
    ts_code: str,
    trade_date: str,
    cutoff_time: str,
    params: IntradayCutoffStateParams,
) -> dict[str, Any] | None:
    cutoff_hhmmss = cutoff_to_hhmmss(cutoff_time)
    current = rows[rows['hhmmss'] <= cutoff_hhmmss]
    if len(current) < params.min_minutes:
        return None
    current = current.sort_values('hhmmss')
    terminal = current.tail(int(params.terminal_window_minutes))
    first_open = float(current['open'].iloc[0])
    last_close = float(current['close'].iloc[-1])
    amount_sum = float(current['amount_abs'].sum())
    volume_sum = float(current['vol'].sum())
    terminal_amount = float(terminal['amount_abs'].sum())
    terminal_volume = float(terminal['vol'].sum())
    terminal_first_open = float(terminal['open'].iloc[0])
    terminal_last_close = float(terminal['close'].iloc[-1])
    terminal_vwap = terminal_amount / (terminal_volume + params.eps) if terminal_volume > 0 else np.nan
    return {
        'ts_code': str(ts_code),
        'trade_date': str(trade_date),
        'cutoff_time': normalize_cutoff_time(cutoff_time),
        'minute_count': int(len(current)),
        'first_open': first_open,
        'last_close': last_close,
        'cutoff_ret': last_close / (first_open + params.eps) - 1.0,
        'cutoff_vwap': amount_sum / (volume_sum + params.eps) if volume_sum > 0 else np.nan,
        'amount_sum': amount_sum,
        'volume_sum': volume_sum,
        'high_to_open': float(current['high'].max()) / (first_open + params.eps) - 1.0,
        'low_to_open': float(current['low'].min()) / (first_open + params.eps) - 1.0,
        'realized_vol': _realized_vol(current['minute_ret']),
        'mean_minute_ret': float(pd.to_numeric(current['minute_ret'], errors='coerce').mean()),
        'positive_minute_share': float((pd.to_numeric(current['minute_ret'], errors='coerce') > 0).mean()),
        'terminal_window_minutes': int(len(terminal)),
        'terminal_ret_20m': terminal_last_close / (terminal_first_open + params.eps) - 1.0,
        'terminal_amount_share_20m': terminal_amount / (amount_sum + params.eps),
        'terminal_volume_share_20m': terminal_volume / (volume_sum + params.eps),
        'terminal_realized_vol_20m': _realized_vol(terminal['minute_ret']),
        'terminal_vwap_20m': terminal_vwap,
        'last_trade_time': _hhmmss_to_text(int(current['hhmmss'].iloc[-1])),
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'no_future_intraday_minutes': True,
        'research_window': params.research_window,
    }


def derive_intraday_cutoff_state_pack(
    minute_df: pd.DataFrame,
    *,
    params: IntradayCutoffStateParams | None = None,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    cfg = params or IntradayCutoffStateParams()
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in (target_dates or sorted(minute['trade_date'].unique().tolist()))}
    rows: list[dict[str, Any]] = []
    for (ts_code, trade_date), group in minute[minute['trade_date'].isin(targets)].groupby(['ts_code', 'trade_date'], sort=False):
        for cutoff in cfg.cutoff_times:
            item = _derive_group_cutoff(group, ts_code=str(ts_code), trade_date=str(trade_date), cutoff_time=cutoff, params=cfg)
            if item is not None:
                rows.append(item)
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = pd.DataFrame(rows)[OUTPUT_COLUMNS].sort_values(SORT_KEYS).reset_index(drop=True)
    out['no_future_intraday_minutes'] = pd.Series([True] * len(out), dtype=object)
    out.attrs['dataset_id'] = DATASET_ID
    out.attrs['schema_version'] = SCHEMA_VERSION
    return out


def build_qa_summary(
    frame: pd.DataFrame,
    *,
    params: IntradayCutoffStateParams | None = None,
    missing_dates: list[str] | None = None,
    output_path: str | Path | None = None,
    runtime_seconds: float | None = None,
    input_minute_row_count: int | None = None,
) -> dict[str, Any]:
    cfg = params or IntradayCutoffStateParams()
    dates = frame['trade_date'].astype(str) if 'trade_date' in frame.columns and not frame.empty else pd.Series(dtype=str)
    tickers = frame['ts_code'].astype(str) if 'ts_code' in frame.columns and not frame.empty else pd.Series(dtype=str)
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if all(col in frame.columns for col in UNIQUE_KEY) else 0
    missing_features = [column for column in FEATURE_COLUMNS if column not in frame.columns]
    issues: list[str] = []
    if frame.empty:
        issues.append('row_count_zero')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if missing_features:
        issues.append('missing_expected_features')
    if missing_dates:
        issues.append('missing_dates_nonempty')
    if 'no_future_intraday_minutes' in frame.columns and not frame.empty:
        if not bool(frame['no_future_intraday_minutes'].all()):
            issues.append('no_future_intraday_minutes_not_true')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'unique_key': UNIQUE_KEY,
        'partition_column': 'trade_date',
        'supported_cutoff_times': list(cfg.cutoff_times),
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if not dates.empty else 0,
        'ticker_count': int(tickers.nunique()) if not tickers.empty else 0,
        'start_date': str(dates.min()) if not dates.empty else None,
        'end_date': str(dates.max()) if not dates.empty else None,
        'feature_count': len([column for column in frame.columns if column not in {'ts_code', 'trade_date', 'cutoff_time'}]),
        'expected_feature_count': len(FEATURE_COLUMNS),
        'duplicate_key_count': duplicate_key_count,
        'missing_features': missing_features,
        'missing_dates': list(missing_dates or []),
        'output_path': str(output_path) if output_path is not None else '',
        'runtime_seconds': runtime_seconds,
        'input_minute_row_count': input_minute_row_count,
        'issues': issues,
        'information_set_legality': {
            'no_future_intraday_minutes': True,
            'cutoff_rule': 'uses only minute rows with trade_time <= cutoff_time',
            'terminal_window_rule': 'terminal window is selected inside cutoff rows only',
            'uses_full_day_denominator': False,
        },
    }


def build_catalog_entry(
    uri: str | Path,
    qa_path: str | Path,
    start: str,
    end: str,
    *,
    cutoff_times: tuple[str, ...] = DEFAULT_CUTOFF_TIMES,
    research_window: str = 'IS',
) -> dict[str, Any]:
    return {
        'dataset_id': DATASET_ID,
        'uri': str(uri),
        'format': 'parquet',
        'version': 'v1',
        'storage': 'local',
        'description': 'Reusable cutoff-time intraday return, amount, volatility, and terminal-window state pack from minute_bar.',
        'columns': OUTPUT_COLUMNS,
        'partition_columns': ['trade_date'],
        'date_column': 'trade_date',
        'symbol_column': 'ts_code',
        'metadata': {
            'source_dataset': SOURCE_DATASET,
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'partition_column': 'trade_date',
            'unique_key': UNIQUE_KEY,
            'sort_keys': SORT_KEYS,
            'supported_cutoff_times': [normalize_cutoff_time(value) for value in cutoff_times],
            'qa_summary_path': str(qa_path),
            'information_set_legality': 'each row uses only minute rows with trade_time <= cutoff_time',
            'no_future_intraday_minutes': True,
            'research_window': str(research_window),
        },
        'freshness': {
            'trade_date_min': str(start),
            'trade_date_max': str(end),
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
