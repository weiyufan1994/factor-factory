from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from factor_factory.research_api import _dates, _index, _numeric

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
    """Reversible SH/SZ/BJ spelling only; other asset identifiers use raw."""
    if style not in {'legacy_qlib', 'qlib', 'ts_code', 'tushare', 'provider', 'raw'}:
        raise ValueError(f'unsupported qlib instrument style: {style}')
    if not isinstance(ts_code, str) or not ts_code or ts_code != ts_code.strip():
        raise ValueError('instrument must be a nonempty string without whitespace')
    if style == 'raw':
        return ts_code
    dotted = re.fullmatch(r'(\d{6})\.(SH|SZ|BJ)', ts_code, flags=re.IGNORECASE)
    prefixed = re.fullmatch(r'(SH|SZ|BJ)(\d{6})', ts_code, flags=re.IGNORECASE)
    if dotted:
        code, market = dotted.groups()
    elif prefixed:
        market, code = prefixed.groups()
    else:
        raise ValueError(f'unrecognized CN instrument: {ts_code}; use raw for other identifiers')
    market = market.upper()
    return f'{market}{code}' if style in {'legacy_qlib', 'qlib'} else f'{code}.{market}'


def _normalize_date_series(series: pd.Series) -> pd.Series:
    return pd.Series(_dates(series, name='qlib datetime'), index=series.index)


def to_qlib_frame(
    frame: pd.DataFrame,
    value_columns: Iterable[str],
    rename_fields: dict[str, str] | None = None,
    instrument_col: str = 'ts_code',
    date_col: str = 'trade_date',
    dropna_value_columns: bool = False,
    instrument_style: str = 'legacy_qlib',
) -> pd.DataFrame:
    """Format supplied values without shifting dates, imputing or inferring a pool.

    Both the standard datetime/instrument MultiIndex and explicit long keys are
    accepted. Invalid/duplicate keys fail before optional missing-value removal.
    Unit/basis conversion belongs to the explicit daily adapter below.
    """
    if not isinstance(frame, pd.DataFrame) or frame.columns.has_duplicates:
        raise ValueError('qlib conversion requires a DataFrame with unique columns')
    fields = list(value_columns)
    if not fields or len(set(fields)) != len(fields):
        raise ValueError('value_columns must be nonempty and unique')
    if set(fields) & {instrument_col, date_col, 'datetime', 'instrument'}:
        raise ValueError('value columns cannot alias key columns')
    indexed = isinstance(frame.index, pd.MultiIndex)
    required_columns = fields if indexed else [instrument_col, date_col, *fields]
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise KeyError(f'missing columns for qlib conversion: {missing}')
    if indexed:
        if set(frame.columns) & {instrument_col, date_col, 'datetime', 'instrument'}:
            raise ValueError('indexed frame must not also contain key columns')
        index = _index(frame.index)
    else:
        index = _index(pd.MultiIndex.from_arrays(
            [_dates(frame[date_col], name='qlib datetime'), frame[instrument_col]],
            names=['datetime', 'instrument']))
    # Validate the style even for an empty input.
    normalize_qlib_instrument('000001.SZ', style=instrument_style)
    source_codes = index.get_level_values('instrument')
    spellings = {x: normalize_qlib_instrument(x, style=instrument_style) for x in source_codes.unique()}
    codes = source_codes.map(spellings)
    index = _index(pd.MultiIndex.from_arrays(
        [index.get_level_values('datetime'), codes], names=['datetime', 'instrument']))
    names = [(rename_fields or {}).get(column, column) for column in fields]
    if (len(set(names)) != len(names) or set(names) & {'datetime', 'instrument'}
            or any(not isinstance(x, str) or not x for x in names)):
        raise ValueError('renamed value columns must be unique and distinct from keys')
    qlib_frame = pd.DataFrame(index=index)
    for source, target in zip(fields, names):
        qlib_frame[target] = _numeric(frame[source], source).to_numpy()
    if dropna_value_columns:
        qlib_frame = qlib_frame.dropna(subset=names)
    return qlib_frame.sort_index()


def to_qlib_signal_frame(
    frame: pd.DataFrame,
    signal_col: str = 'factor_value',
    instrument_col: str = 'ts_code',
    date_col: str = 'trade_date',
    instrument_style: str = 'legacy_qlib',
    *,
    dropna_value_columns: bool = True,
) -> pd.DataFrame:
    """One prediction column, never instruments metadata or a date-lag adapter.

    The historical default omits NaN signals; pass False for a lossless standard
    frame round trip. Zero is always retained. No Qlib import is required.
    """
    return to_qlib_frame(
        frame=frame,
        value_columns=[signal_col],
        rename_fields=None,
        instrument_col=instrument_col,
        date_col=date_col,
        dropna_value_columns=dropna_value_columns,
        instrument_style=instrument_style,
    )


def daily_to_qlib_features(
    daily_df: pd.DataFrame,
    value_columns: Iterable[str] | None = None,
    rename_fields: dict[str, str] | None = None,
    instrument_style: str = 'legacy_qlib',
    *,
    volume_unit: str = 'source',
    amount_unit: str = 'source',
    return_unit: str = 'source',
    price_basis: str | None = None,
    adjustment_factor_col: str | None = None,
) -> pd.DataFrame:
    """Explicit units for supplied daily bars; never infer corporate actions.

    Source units preserve the legacy rename-only behavior and remain UNKNOWN
    in metadata. Opt in with lot100/share, cny_thousand/cny, percent/decimal.
    Raw prices use factor=1. Adjusted prices require the actual positive scale
    adjusted_price/raw_price; physical share volume is divided by that scale.
    OHLC/pre_close are already in the declared basis and are never readjusted.
    This does not certify that the caller's price basis/provenance is correct.
    """
    fields = list(value_columns) if value_columns is not None else list(DEFAULT_DAILY_QLIB_RENAME_MAP)
    rename = DEFAULT_DAILY_QLIB_RENAME_MAP if rename_fields is None else rename_fields
    scales = {'vol': ({'source': 1., 'lot100': 100., 'share': 1.}, volume_unit),
              'amount': ({'source': 1., 'cny_thousand': 1000., 'cny': 1.}, amount_unit),
              'pct_chg': ({'source': 1., 'percent': .01, 'decimal': 1.}, return_unit)}
    out = to_qlib_frame(
        frame=daily_df,
        value_columns=fields,
        rename_fields=rename,
        instrument_style=instrument_style,
    )
    for field, (units, unit) in scales.items():
        if unit not in units:
            raise ValueError(f'unsupported {field} unit: {unit}')
        if field in fields:
            target = rename.get(field, field)
            if field != 'pct_chg' and out[target].lt(0).any():
                raise ValueError(f'{field} must be nonnegative or missing')
            out[target] *= units[unit]
    if price_basis not in {None, 'raw', 'adjusted'}:
        raise ValueError('price_basis must be raw, adjusted or None')
    prices = [rename.get(x, x) for x in fields if x in {'open', 'high', 'low', 'close', 'pre_close'}]
    if price_basis is not None:
        if '$factor' in out:
            raise ValueError('explicit price basis owns $factor; do not also select it')
        if not prices:
            raise ValueError('explicit price basis requires at least one price field')
        if out[prices].le(0).any().any():
            raise ValueError('observed prices must be positive')
        if 'vol' in fields and volume_unit == 'source':
            raise ValueError('explicit price basis requires physical volume units')
        if price_basis == 'adjusted':
            if not adjustment_factor_col:
                raise ValueError('adjusted prices require adjustment_factor_col')
            scale = to_qlib_frame(daily_df, [adjustment_factor_col],
                                  instrument_style=instrument_style).iloc[:, 0]
            if scale.le(0).any() or (out[prices].notna().any(axis=1) & scale.isna()).any():
                raise ValueError('observed adjusted prices require a positive known scale')
            if 'vol' in fields:
                out[rename.get('vol', 'vol')] /= scale
        else:
            if adjustment_factor_col is not None:
                raise ValueError('raw prices use unit scale; do not supply an adjustment factor')
            scale = pd.Series(1., index=out.index)
        out['$factor'] = scale
    elif adjustment_factor_col is not None:
        raise ValueError('adjustment_factor_col requires explicit adjusted price basis')
    if np.isinf(out.to_numpy()).any():
        raise ValueError('unit conversion overflow')
    out.attrs['qlib_semantics'] = {
        'price_basis': price_basis or 'unspecified',
        'volume_unit': ('adjusted_price_units' if price_basis == 'adjusted' else 'share')
                       if volume_unit != 'source' else 'unspecified',
        'amount_unit': 'cny' if amount_unit != 'source' else 'unspecified',
        'return_unit': 'decimal' if return_unit != 'source' else 'unspecified',
        'factor_definition': 'adjusted_price/raw_price' if price_basis == 'adjusted'
                             else 'identity_raw_price' if price_basis == 'raw' else 'unspecified',
        'native_execution_equivalence': 'not_verified',
    }
    return out


def daily_basic_to_qlib_features(
    daily_basic_df: pd.DataFrame,
    value_columns: Iterable[str] | None = None,
    rename_fields: dict[str, str] | None = None,
    instrument_style: str = 'legacy_qlib',
) -> pd.DataFrame:
    fields = list(value_columns) if value_columns is not None else list(DEFAULT_DAILY_BASIC_QLIB_RENAME_MAP)
    return to_qlib_frame(
        frame=daily_basic_df,
        value_columns=fields,
        rename_fields=DEFAULT_DAILY_BASIC_QLIB_RENAME_MAP if rename_fields is None else rename_fields,
        instrument_style=instrument_style,
    )
