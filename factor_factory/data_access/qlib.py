from __future__ import annotations

from typing import Iterable

import pandas as pd

DEFAULT_DAILY_QLIB_RENAME_MAP = {
    'open': '$open',
    'high': '$high',
    'low': '$low',
    'close': '$close',
    'vol': '$volume',
    'amount': '$amount',
    'pct_chg': '$ret',
}

DEFAULT_DAILY_BASIC_QLIB_RENAME_MAP = {
    'turnover_rate': '$turnover_rate',
    'turnover_rate_f': '$turnover_rate_f',
    'volume_ratio': '$volume_ratio',
    'pe': '$pe',
    'pe_ttm': '$pe_ttm',
    'pb': '$pb',
    'ps': '$ps',
    'ps_ttm': '$ps_ttm',
    'total_mv': '$total_mv',
    'circ_mv': '$circ_mv',
}


def normalize_qlib_instrument(ts_code: str, style: str = 'legacy_qlib') -> str:
    if not isinstance(ts_code, str) or '.' not in ts_code:
        return ts_code
    code, market = ts_code.split('.', 1)
    market = market.upper()
    if style in {'legacy_qlib', 'qlib'}:
        return f'{market}{code}'
    if style in {'ts_code', 'tushare', 'provider'}:
        return f'{code}.{market}'
    if style in {'raw'}:
        return ts_code
    raise ValueError(f'unsupported qlib instrument style: {style}')


def _normalize_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str).str.replace('.0', '', regex=False), format='%Y%m%d', errors='coerce')


def to_qlib_frame(
    frame: pd.DataFrame,
    value_columns: Iterable[str],
    rename_fields: dict[str, str] | None = None,
    instrument_col: str = 'ts_code',
    date_col: str = 'trade_date',
    dropna_value_columns: bool = False,
    instrument_style: str = 'legacy_qlib',
) -> pd.DataFrame:
    required_columns = [instrument_col, date_col, *list(value_columns)]
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise KeyError(f'missing columns for qlib conversion: {missing}')

    qlib_frame = frame[required_columns].copy()
    qlib_frame['datetime'] = _normalize_date_series(qlib_frame[date_col])
    qlib_frame['instrument'] = qlib_frame[instrument_col].map(
        lambda value: normalize_qlib_instrument(value, style=instrument_style)
    )
    if dropna_value_columns:
        qlib_frame = qlib_frame.dropna(subset=list(value_columns))
    qlib_frame = qlib_frame.dropna(subset=['datetime', 'instrument'])

    renamed_value_columns = [rename_fields.get(column, column) for column in value_columns] if rename_fields else list(value_columns)
    if rename_fields:
        qlib_frame = qlib_frame.rename(columns=rename_fields)

    ordered_columns = ['datetime', 'instrument', *renamed_value_columns]
    qlib_frame = qlib_frame[ordered_columns]
    qlib_frame = qlib_frame.set_index(['datetime', 'instrument']).sort_index()
    qlib_frame.index = qlib_frame.index.set_names(['datetime', 'instrument'])
    return qlib_frame


def to_qlib_signal_frame(
    frame: pd.DataFrame,
    signal_col: str = 'cpv_factor',
    instrument_col: str = 'ts_code',
    date_col: str = 'trade_date',
    instrument_style: str = 'legacy_qlib',
) -> pd.DataFrame:
    return to_qlib_frame(
        frame=frame,
        value_columns=[signal_col],
        rename_fields=None,
        instrument_col=instrument_col,
        date_col=date_col,
        dropna_value_columns=True,
        instrument_style=instrument_style,
    )


def daily_to_qlib_features(
    daily_df: pd.DataFrame,
    value_columns: Iterable[str] | None = None,
    rename_fields: dict[str, str] | None = None,
    instrument_style: str = 'legacy_qlib',
) -> pd.DataFrame:
    fields = list(value_columns) if value_columns else list(DEFAULT_DAILY_QLIB_RENAME_MAP)
    return to_qlib_frame(
        frame=daily_df,
        value_columns=fields,
        rename_fields=rename_fields or DEFAULT_DAILY_QLIB_RENAME_MAP,
        instrument_style=instrument_style,
    )


def daily_basic_to_qlib_features(
    daily_basic_df: pd.DataFrame,
    value_columns: Iterable[str] | None = None,
    rename_fields: dict[str, str] | None = None,
    instrument_style: str = 'legacy_qlib',
) -> pd.DataFrame:
    fields = list(value_columns) if value_columns else list(DEFAULT_DAILY_BASIC_QLIB_RENAME_MAP)
    return to_qlib_frame(
        frame=daily_basic_df,
        value_columns=fields,
        rename_fields=rename_fields or DEFAULT_DAILY_BASIC_QLIB_RENAME_MAP,
        instrument_style=instrument_style,
    )
