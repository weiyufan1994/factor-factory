from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .intraday_operator_kernels import terminal_rolling_corr_by_group


DATASET_ID = 'intraday_terminal_corr_state_v1'
SCHEMA_VERSION = 'intraday_terminal_corr_state_v1'
PRODUCER_VERSION = 'factorforge_data_api_intraday_terminal_corr_state_20260618'
SOURCE_DATASET = 'minute_bar'
UNIQUE_KEY = ['ts_code', 'trade_date', 'cutoff_time', 'window_id']
SORT_KEYS = ['trade_date', 'ts_code', 'cutoff_time', 'window_id']
DEFAULT_CUTOFF_TIMES = ('10:30:00', '11:30:00', '14:00:00', '14:30:00', '14:50:00', '14:55:00')
DEFAULT_WINDOWS = (20, 30, 60)
FEATURE_COLUMNS = [
    'window_minutes',
    'terminal_order',
    'bar_count',
    'close_amount_corr',
    'ret_amount_corr',
    'terminal_ret',
    'terminal_amount_sum',
    'terminal_volume_sum',
    'terminal_realized_vol',
    'schema_version',
    'producer_version',
    'source_dataset',
    'operator_backend',
    'no_future_intraday_minutes',
    'research_window',
]
OUTPUT_COLUMNS = ['ts_code', 'trade_date', 'cutoff_time', 'window_id', *FEATURE_COLUMNS]


@dataclass(frozen=True)
class IntradayTerminalCorrStateParams:
    cutoff_times: tuple[str, ...] = DEFAULT_CUTOFF_TIMES
    windows: tuple[int, ...] = DEFAULT_WINDOWS
    min_minutes: int = 20
    research_window: str = 'IS'
    operator_backend: str = 'array_grouped'
    max_workers: int | None = None
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


def prepare_minute_frame(minute_df: pd.DataFrame) -> pd.DataFrame:
    required = {'ts_code', 'trade_date', 'open', 'close'}
    missing = sorted(required - set(minute_df.columns))
    if missing:
        raise ValueError(f'minute_df missing required columns: {missing}')
    minute = minute_df.copy()
    if 'trade_time' not in minute.columns:
        minute['trade_time'] = minute['bar_time'] if 'bar_time' in minute.columns else '14:50:00'
    if 'amount' not in minute.columns:
        if 'vol' not in minute.columns:
            raise ValueError('minute_df must include amount or vol')
        minute['amount'] = minute['vol']
    if 'vol' not in minute.columns:
        minute['vol'] = 0.0
    for col in ['open', 'close', 'vol', 'amount']:
        minute[col] = pd.to_numeric(minute[col], errors='coerce')
    minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
    minute['hhmmss'] = time_key(minute['trade_time'])
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'open', 'close', 'amount'])
    minute = minute[(minute['open'] > 0) & (minute['close'] > 0)].copy()
    minute['amount_abs'] = minute['amount'].abs()
    minute['minute_ret'] = minute['close'] / minute['open'] - 1.0
    return minute.sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)


def _realized_vol(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors='coerce').dropna()
    if len(clean) < 2:
        return 0.0
    value = float(clean.std(ddof=0))
    return value if np.isfinite(value) else 0.0


def _window_stats(frame: pd.DataFrame, *, window: int, params: IntradayTerminalCorrStateParams) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, group in frame.groupby(['ts_code', 'trade_date', 'cutoff_time'], sort=False):
        ts_code, trade_date, cutoff_time = key
        ordered = group.sort_values('hhmmss')
        terminal = ordered.tail(int(window))
        first_open = float(terminal['open'].iloc[0]) if not terminal.empty else np.nan
        last_close = float(terminal['close'].iloc[-1]) if not terminal.empty else np.nan
        rows.append({
            'ts_code': str(ts_code),
            'trade_date': str(trade_date),
            'cutoff_time': str(cutoff_time),
            'window_id': f'{int(window)}m',
            'window_minutes': int(window),
            'terminal_ret': last_close / (first_open + params.eps) - 1.0 if np.isfinite(first_open) else np.nan,
            'terminal_amount_sum': float(terminal['amount_abs'].sum()) if not terminal.empty else 0.0,
            'terminal_volume_sum': float(terminal['vol'].sum()) if not terminal.empty else 0.0,
            'terminal_realized_vol': _realized_vol(terminal['minute_ret']) if not terminal.empty else 0.0,
        })
    return pd.DataFrame(rows)


def _derive_for_window(current: pd.DataFrame, *, window: int, params: IntradayTerminalCorrStateParams) -> pd.DataFrame:
    group_cols = ['ts_code', 'trade_date', 'cutoff_time']
    close_amount = terminal_rolling_corr_by_group(
        current,
        group_cols=group_cols,
        order_col='hhmmss',
        x_col='close',
        y_col='amount_abs',
        window=int(window),
        output_col='close_amount_corr',
        backend=params.operator_backend,
        max_workers=params.max_workers,
    )
    ret_amount = terminal_rolling_corr_by_group(
        current,
        group_cols=group_cols,
        order_col='hhmmss',
        x_col='minute_ret',
        y_col='amount_abs',
        window=int(window),
        output_col='ret_amount_corr',
        backend=params.operator_backend,
        max_workers=params.max_workers,
    )
    stats = _window_stats(current, window=int(window), params=params)
    out = close_amount.merge(
        ret_amount[[*group_cols, 'ret_amount_corr']],
        on=group_cols,
        how='left',
    ).merge(stats, on=group_cols, how='left')
    out['window_id'] = f'{int(window)}m'
    out['window_minutes'] = int(window)
    out['schema_version'] = SCHEMA_VERSION
    out['producer_version'] = PRODUCER_VERSION
    out['source_dataset'] = SOURCE_DATASET
    out['operator_backend'] = str(close_amount.attrs.get('operator_backend') or params.operator_backend)
    out['no_future_intraday_minutes'] = True
    out['research_window'] = params.research_window
    return out[OUTPUT_COLUMNS]


def derive_intraday_terminal_corr_state(
    minute_df: pd.DataFrame,
    *,
    params: IntradayTerminalCorrStateParams | None = None,
    target_dates: list[str] | None = None,
) -> pd.DataFrame:
    cfg = params or IntradayTerminalCorrStateParams()
    minute = prepare_minute_frame(minute_df)
    targets = {normalize_trade_date(date) for date in (target_dates or sorted(minute['trade_date'].unique().tolist()))}
    minute = minute[minute['trade_date'].isin(targets)].copy()
    rows: list[pd.DataFrame] = []
    for cutoff in cfg.cutoff_times:
        cutoff_time = normalize_cutoff_time(cutoff)
        cutoff_hhmmss = cutoff_to_hhmmss(cutoff)
        current = minute[minute['hhmmss'] <= cutoff_hhmmss].copy()
        if current.empty:
            continue
        current['cutoff_time'] = cutoff_time
        counts = current.groupby(['ts_code', 'trade_date', 'cutoff_time'], sort=False)['hhmmss'].transform('count')
        current = current[counts >= int(cfg.min_minutes)].copy()
        if current.empty:
            continue
        for window in cfg.windows:
            rows.append(_derive_for_window(current, window=int(window), params=cfg))
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = pd.concat(rows, ignore_index=True)
    out = out[OUTPUT_COLUMNS].sort_values(SORT_KEYS).reset_index(drop=True)
    out['no_future_intraday_minutes'] = pd.Series([True] * len(out), dtype=object)
    out.attrs['dataset_id'] = DATASET_ID
    out.attrs['schema_version'] = SCHEMA_VERSION
    out.attrs['operator_backend'] = str(out['operator_backend'].dropna().iloc[0]) if not out.empty else cfg.operator_backend
    return out


def build_intraday_terminal_corr_state_qa(
    frame: pd.DataFrame,
    *,
    params: IntradayTerminalCorrStateParams | None = None,
    missing_dates: list[str] | None = None,
    output_path: str | Path | None = None,
    runtime_seconds: float | None = None,
    input_minute_row_count: int | None = None,
) -> dict[str, Any]:
    cfg = params or IntradayTerminalCorrStateParams()
    dates = frame['trade_date'].astype(str) if 'trade_date' in frame.columns and not frame.empty else pd.Series(dtype=str)
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if all(col in frame.columns for col in UNIQUE_KEY) else 0
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    issues: list[str] = []
    if frame.empty:
        issues.append('row_count_zero')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if missing_columns:
        issues.append('missing_expected_columns')
    if missing_dates:
        issues.append('missing_dates_nonempty')
    if 'no_future_intraday_minutes' in frame.columns and not frame.empty and not bool(frame['no_future_intraday_minutes'].all()):
        issues.append('no_future_intraday_minutes_not_true')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'unique_key': UNIQUE_KEY,
        'partition_column': 'trade_date',
        'supported_cutoff_times': [normalize_cutoff_time(value) for value in cfg.cutoff_times],
        'windows': [int(value) for value in cfg.windows],
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if not dates.empty else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'start_date': str(dates.min()) if not dates.empty else None,
        'end_date': str(dates.max()) if not dates.empty else None,
        'duplicate_key_count': duplicate_key_count,
        'missing_columns': missing_columns,
        'missing_dates': list(missing_dates or []),
        'output_path': str(output_path) if output_path is not None else '',
        'runtime_seconds': runtime_seconds,
        'input_minute_row_count': input_minute_row_count,
        'operator_backend': str(frame['operator_backend'].dropna().iloc[0]) if 'operator_backend' in frame.columns and not frame.empty else cfg.operator_backend,
        'issues': issues,
        'information_set_legality': {
            'no_future_intraday_minutes': True,
            'cutoff_rule': 'uses only minute rows with trade_time <= cutoff_time',
            'terminal_only': True,
            'does_not_materialize_full_rolling_vector': True,
        },
    }


def build_catalog_entry(
    uri: str | Path,
    qa_path: str | Path,
    start: str,
    end: str,
    *,
    params: IntradayTerminalCorrStateParams | None = None,
) -> dict[str, Any]:
    cfg = params or IntradayTerminalCorrStateParams()
    return {
        'dataset_id': DATASET_ID,
        'uri': str(uri),
        'format': 'parquet',
        'version': 'v1',
        'storage': 'local',
        'description': 'Reusable terminal rolling correlation state by intraday cutoff from minute_bar.',
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
            'supported_cutoff_times': [normalize_cutoff_time(value) for value in cfg.cutoff_times],
            'windows': [int(value) for value in cfg.windows],
            'qa_summary_path': str(qa_path),
            'information_set_legality': 'each row uses only minute rows with trade_time <= cutoff_time',
            'no_future_intraday_minutes': True,
            'terminal_only': True,
            'research_window': str(cfg.research_window),
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
