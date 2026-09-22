from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .paths import LocalTusharePaths, resolve_local_tushare_paths

DEFAULT_DAILY_COLUMNS = [
    'ts_code',
    'trade_date',
    'open',
    'high',
    'low',
    'close',
    'pre_close',
    'change',
    'pct_chg',
    'vol',
    'amount',
]


def _normalize_symbols(symbols: Iterable[str] | None) -> set[str] | None:
    if symbols is None:
        return None
    return {str(symbol).strip() for symbol in symbols if str(symbol).strip()}


def _normalize_date(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def get_daily(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    resolved_paths = paths or resolve_local_tushare_paths()
    csv_path = Path(resolved_paths.daily_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f'daily.csv not found: {csv_path}')

    requested_columns = list(columns) if columns else list(DEFAULT_DAILY_COLUMNS)
    required_columns = ['ts_code', 'trade_date']
    usecols = list(dict.fromkeys(required_columns + requested_columns))

    frame = pd.read_csv(
        csv_path,
        usecols=usecols,
        dtype={'ts_code': 'string', 'trade_date': 'string'},
    )
    frame['trade_date'] = frame['trade_date'].str.replace('.0', '', regex=False).str.zfill(8)

    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    if start_date:
        frame = frame[frame['trade_date'] >= start_date]
    if end_date:
        frame = frame[frame['trade_date'] <= end_date]

    symbol_set = _normalize_symbols(symbols)
    if symbol_set:
        frame = frame[frame['ts_code'].isin(symbol_set)]

    return frame[requested_columns].reset_index(drop=True)
