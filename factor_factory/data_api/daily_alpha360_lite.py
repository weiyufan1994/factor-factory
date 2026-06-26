from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


PRICE_FIELDS = ('close', 'open', 'high', 'low', 'vwap')
VOLUME_FIELDS = ('volume',)
FEATURE_PREFIX = {
    'close': 'CLOSE',
    'open': 'OPEN',
    'high': 'HIGH',
    'low': 'LOW',
    'vwap': 'VWAP',
    'volume': 'VOLUME',
}


@dataclass(frozen=True)
class DailyAlpha360LiteParams:
    lookback: int = 60
    eps: float = 1e-12
    symbol_col: str = 'ts_code'
    date_col: str = 'trade_date'
    volume_col: str = 'vol'
    amount_col: str = 'amount'


def _normalize_trade_date(values: pd.Series) -> pd.Series:
    return values.map(lambda x: pd.to_datetime(str(x)).strftime('%Y%m%d') if '-' in str(x) else str(x).replace('.0', '').zfill(8))


def _prepare_daily_frame(frame: pd.DataFrame, params: DailyAlpha360LiteParams) -> pd.DataFrame:
    required = {params.symbol_col, params.date_col, 'close', 'open', 'high', 'low'}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f'daily alpha360-lite source missing columns: {sorted(missing)}')
    if params.volume_col not in frame.columns and 'volume' not in frame.columns:
        raise ValueError(f'daily alpha360-lite source missing volume column: {params.volume_col}')

    out = frame.copy()
    out[params.date_col] = _normalize_trade_date(out[params.date_col])
    if params.volume_col != 'volume' and params.volume_col in out.columns:
        out['volume'] = out[params.volume_col]
    elif 'volume' not in out.columns and params.volume_col in out.columns:
        out['volume'] = out[params.volume_col]
    if 'vwap' not in out.columns:
        if params.amount_col in out.columns:
            amount = pd.to_numeric(out[params.amount_col], errors='coerce')
            volume = pd.to_numeric(out['volume'], errors='coerce')
            out['vwap'] = np.where(volume > 0.0, amount / volume, np.nan)
        else:
            out['vwap'] = out['close']
    return out.sort_values([params.symbol_col, params.date_col]).reset_index(drop=True)


def build_daily_alpha360_lite(
    daily: pd.DataFrame,
    *,
    params: DailyAlpha360LiteParams | None = None,
) -> pd.DataFrame:
    cfg = params or DailyAlpha360LiteParams()
    if cfg.lookback <= 0:
        raise ValueError('lookback must be positive')
    frame = _prepare_daily_frame(daily, cfg)
    grouped = frame.groupby(cfg.symbol_col, sort=False, group_keys=False)
    close_now = pd.to_numeric(frame['close'], errors='coerce')
    volume_now = pd.to_numeric(frame['volume'], errors='coerce')
    feature_series: dict[str, pd.Series] = {}

    for lag in range(cfg.lookback):
        for field in PRICE_FIELDS:
            shifted = grouped[field].shift(lag)
            feature_series[f'{FEATURE_PREFIX[field]}{lag}'] = pd.to_numeric(shifted, errors='coerce') / close_now
        shifted_volume = grouped['volume'].shift(lag)
        feature_series[f'VOLUME{lag}'] = pd.to_numeric(shifted_volume, errors='coerce') / (volume_now + float(cfg.eps))

    result = pd.concat([frame[[cfg.symbol_col, cfg.date_col]], pd.DataFrame(feature_series, index=frame.index)], axis=1)
    result.attrs['dataset_id'] = 'daily_alpha360_lite_v1'
    result.attrs['schema_version'] = 'daily_alpha360_lite_v1'
    result.attrs['lookback'] = int(cfg.lookback)
    result.attrs['source_dataset'] = 'clean_daily_bar'
    result.attrs['information_set'] = 'uses current and prior daily bars only; no future shifts'
    return result


def build_daily_alpha360_lite_qa(
    frame: pd.DataFrame,
    *,
    params: DailyAlpha360LiteParams | None = None,
) -> dict[str, Any]:
    cfg = params or DailyAlpha360LiteParams()
    feature_cols = [column for column in frame.columns if column not in {cfg.symbol_col, cfg.date_col}]
    key_cols = [cfg.symbol_col, cfg.date_col]
    duplicate_key_count = int(frame.duplicated(key_cols).sum()) if all(col in frame.columns for col in key_cols) else 0
    dates = frame[cfg.date_col].astype(str) if cfg.date_col in frame.columns and not frame.empty else pd.Series(dtype=str)
    tickers = frame[cfg.symbol_col].astype(str) if cfg.symbol_col in frame.columns and not frame.empty else pd.Series(dtype=str)
    null_ratio_by_field = {
        column: round(float(frame[column].isna().mean()), 6)
        for column in feature_cols
    }
    expected_feature_count = int(cfg.lookback) * (len(PRICE_FIELDS) + len(VOLUME_FIELDS))
    issues: list[str] = []
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if len(feature_cols) != expected_feature_count:
        issues.append('feature_count_mismatch')
    if frame.empty:
        issues.append('row_count_zero')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': 'daily_alpha360_lite_v1',
        'schema_version': 'daily_alpha360_lite_v1',
        'source_dataset': 'clean_daily_bar',
        'lookback': int(cfg.lookback),
        'unique_key': [cfg.symbol_col, cfg.date_col],
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if not dates.empty else 0,
        'ticker_count': int(tickers.nunique()) if not tickers.empty else 0,
        'start_date': str(dates.min()) if not dates.empty else None,
        'end_date': str(dates.max()) if not dates.empty else None,
        'feature_count': int(len(feature_cols)),
        'expected_feature_count': expected_feature_count,
        'duplicate_key_count': duplicate_key_count,
        'null_ratio_by_field': null_ratio_by_field,
        'issues': issues,
        'information_set_legality': {
            'uses_future_rows': False,
            'shift_direction': 'current_and_prior_rows_only',
            'normalization': 'price fields divided by current close; volume fields divided by current volume',
        },
    }
