from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .paths import LocalTusharePaths, inspect_trade_date_csv_root, resolve_local_tushare_paths

DEFAULT_DAILY_BASIC_COLUMNS = [
    'ts_code',
    'trade_date',
    'turnover_rate',
    'turnover_rate_f',
    'volume_ratio',
    'pe',
    'pe_ttm',
    'pb',
    'ps',
    'ps_ttm',
    'dv_ratio',
    'dv_ttm',
    'total_share',
    'float_share',
    'free_share',
    'total_mv',
    'circ_mv',
]


def _normalize_date(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize_symbols(symbols: Iterable[str] | None) -> set[str] | None:
    if symbols is None:
        return None
    return {str(symbol).strip() for symbol in symbols if str(symbol).strip()}


def list_daily_basic_trade_dates(paths: LocalTusharePaths | None = None) -> list[str]:
    resolved_paths = paths or resolve_local_tushare_paths()
    meta = inspect_trade_date_csv_root(Path(resolved_paths.daily_basic_dir))
    return list(meta['trade_dates']) if meta else []


def _iter_daily_basic_csvs(root: Path, start: str | None, end: str | None) -> list[Path]:
    csv_paths: list[Path] = []
    for part_dir in sorted(root.glob('trade_date=*')):
        if not part_dir.is_dir():
            continue
        trade_date = part_dir.name.replace('trade_date=', '')
        if start and trade_date < start:
            continue
        if end and trade_date > end:
            continue
        csv_paths.extend(sorted(part_dir.glob('*.csv')))
    return csv_paths


def get_daily_basic(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    resolved_paths = paths or resolve_local_tushare_paths()
    root = Path(resolved_paths.daily_basic_dir)
    if not root.exists():
        raise FileNotFoundError(f'daily_basic_incremental not found: {root}')

    requested_columns = list(columns) if columns else list(DEFAULT_DAILY_BASIC_COLUMNS)
    required_columns = ['ts_code', 'trade_date']
    usecols = list(dict.fromkeys(required_columns + requested_columns))

    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    csv_paths = _iter_daily_basic_csvs(root, start_date, end_date)
    if not csv_paths:
        return pd.DataFrame(columns=requested_columns)

    frames: list[pd.DataFrame] = []
    symbol_set = _normalize_symbols(symbols)
    for csv_path in csv_paths:
        frame = pd.read_csv(
            csv_path,
            usecols=lambda column: column in usecols,
            dtype={'ts_code': 'string', 'trade_date': 'string'},
        )
        if 'trade_date' in frame.columns:
            frame['trade_date'] = frame['trade_date'].str.replace('.0', '', regex=False).str.zfill(8)
        if symbol_set:
            frame = frame[frame['ts_code'].isin(symbol_set)]
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=requested_columns)
    merged = pd.concat(frames, ignore_index=True)
    return merged[requested_columns].reset_index(drop=True)
