from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import LocalTusharePaths, resolve_local_tushare_paths

DEFAULT_CALENDAR_COLUMNS = ['exchange', 'cal_date', 'is_open']


def _normalize_date(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def get_trade_calendar(
    start: str | int | None = None,
    end: str | int | None = None,
    exchange: str | None = None,
    open_only: bool = False,
    columns: list[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    resolved_paths = paths or resolve_local_tushare_paths()
    csv_path = Path(resolved_paths.trade_cal_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f'trade_cal.csv not found: {csv_path}')

    header = set(pd.read_csv(csv_path, nrows=0).columns)
    if not {'cal_date', 'is_open'}.issubset(header):
        raise ValueError(
            f'trade_cal.csv missing cal_date/is_open columns: {csv_path}'
        )
    bound_exchange = resolved_paths.trade_calendar_exchange
    if exchange is not None and 'exchange' not in header:
        if not bound_exchange or str(bound_exchange).upper() != str(exchange).upper():
            raise ValueError(
                'trade_cal.csv omits exchange and has no matching explicit '
                f'exchange binding: requested={exchange!r}, bound={bound_exchange!r}'
            )

    requested_columns = list(columns) if columns else list(DEFAULT_CALENDAR_COLUMNS)
    required_columns = ['cal_date']
    if exchange is not None and 'exchange' in header:
        required_columns.append('exchange')
    if open_only:
        required_columns.append('is_open')
    usecols = [
        column for column in dict.fromkeys(required_columns + requested_columns)
        if column in header
    ]

    frame = pd.read_csv(
        csv_path,
        usecols=usecols,
        dtype={'exchange': 'string', 'cal_date': 'string', 'is_open': 'string'},
    )
    frame['cal_date'] = frame['cal_date'].str.replace('.0', '', regex=False).str.zfill(8)

    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    if start_date:
        frame = frame[frame['cal_date'] >= start_date]
    if end_date:
        frame = frame[frame['cal_date'] <= end_date]
    if exchange and 'exchange' in frame.columns:
        frame = frame[frame['exchange'] == exchange]
    if open_only:
        frame = frame[frame['is_open'].astype(str) == '1']

    if 'exchange' in requested_columns and 'exchange' not in frame.columns:
        frame['exchange'] = bound_exchange
    return frame[requested_columns].reset_index(drop=True)


def list_open_trade_dates(
    start: str | int | None = None,
    end: str | int | None = None,
    exchange: str = 'SSE',
    paths: LocalTusharePaths | None = None,
) -> list[str]:
    calendar = get_trade_calendar(
        start=start,
        end=end,
        exchange=exchange,
        open_only=True,
        columns=['cal_date'],
        paths=paths,
    )
    return calendar['cal_date'].astype(str).tolist()
