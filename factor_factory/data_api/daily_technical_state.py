from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    'ret_1d',
    'ret_5d',
    'ret_20d',
    'range_pct',
    'open_close_ret',
    'vwap_close_spread',
    'ma5_close_ratio',
    'ma20_close_ratio',
    'volatility_20d',
    'downside_volatility_20d',
    'ret_skew_20d',
    'ret_excess_kurtosis_20d',
    'ret_tail_asymmetry_20d',
    'amount_mean_20d',
    'volume_ratio_20d',
    'amihud_20d',
]


@dataclass(frozen=True)
class DailyTechnicalStateParams:
    symbol_col: str = 'ts_code'
    date_col: str = 'trade_date'
    volume_col: str = 'vol'
    amount_col: str = 'amount'
    eps: float = 1e-12


def normalize_trade_date(values: pd.Series) -> pd.Series:
    return values.map(lambda x: pd.to_datetime(str(x)).strftime('%Y%m%d') if '-' in str(x) else str(x).replace('.0', '').zfill(8))


def _prepare_daily_frame(frame: pd.DataFrame, params: DailyTechnicalStateParams) -> pd.DataFrame:
    required = {params.symbol_col, params.date_col, 'open', 'high', 'low', 'close'}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f'daily technical state source missing columns: {sorted(missing)}')
    if params.volume_col not in frame.columns and 'volume' not in frame.columns:
        raise ValueError(f'daily technical state source missing volume column: {params.volume_col}')
    if params.amount_col not in frame.columns:
        raise ValueError(f'daily technical state source missing amount column: {params.amount_col}')
    out = frame.copy()
    out[params.date_col] = normalize_trade_date(out[params.date_col])
    if params.volume_col != 'volume' and params.volume_col in out.columns:
        out['volume'] = out[params.volume_col]
    elif 'volume' not in out.columns:
        out['volume'] = out[params.volume_col]
    if 'vwap' not in out.columns:
        amount = pd.to_numeric(out[params.amount_col], errors='coerce')
        volume = pd.to_numeric(out['volume'], errors='coerce')
        out['vwap'] = np.where(volume > 0.0, amount / volume, np.nan)
    return out.sort_values([params.symbol_col, params.date_col]).reset_index(drop=True)


def _tail_asymmetry(values: pd.Series) -> float:
    clean = values.dropna()
    if clean.empty:
        return np.nan
    positive = clean[clean > 0.0].sum()
    negative = -clean[clean < 0.0].sum()
    denom = positive + negative
    if denom <= 0.0:
        return 0.0
    return float((positive - negative) / denom)


def build_daily_technical_state(
    daily: pd.DataFrame,
    *,
    params: DailyTechnicalStateParams | None = None,
) -> pd.DataFrame:
    cfg = params or DailyTechnicalStateParams()
    frame = _prepare_daily_frame(daily, cfg)
    grouped = frame.groupby(cfg.symbol_col, sort=False, group_keys=False)
    close = pd.to_numeric(frame['close'], errors='coerce')
    open_px = pd.to_numeric(frame['open'], errors='coerce')
    high = pd.to_numeric(frame['high'], errors='coerce')
    low = pd.to_numeric(frame['low'], errors='coerce')
    vwap = pd.to_numeric(frame['vwap'], errors='coerce')
    amount = pd.to_numeric(frame[cfg.amount_col], errors='coerce')
    volume = pd.to_numeric(frame['volume'], errors='coerce')
    ret = grouped['close'].pct_change()
    abs_ret = ret.abs()

    ma5 = grouped['close'].transform(lambda s: pd.to_numeric(s, errors='coerce').rolling(5, min_periods=1).mean())
    ma20 = grouped['close'].transform(lambda s: pd.to_numeric(s, errors='coerce').rolling(20, min_periods=1).mean())
    amount_mean_20 = grouped[cfg.amount_col].transform(lambda s: pd.to_numeric(s, errors='coerce').rolling(20, min_periods=1).mean())
    volume_mean_20 = grouped['volume'].transform(lambda s: pd.to_numeric(s, errors='coerce').rolling(20, min_periods=1).mean())
    volatility_20 = ret.groupby(frame[cfg.symbol_col], sort=False).transform(lambda s: s.rolling(20, min_periods=2).std())
    downside_volatility_20 = ret.where(ret < 0.0).groupby(frame[cfg.symbol_col], sort=False).transform(lambda s: s.rolling(20, min_periods=2).std())
    skew_20 = ret.groupby(frame[cfg.symbol_col], sort=False).transform(lambda s: s.rolling(20, min_periods=3).skew())
    kurt_20 = ret.groupby(frame[cfg.symbol_col], sort=False).transform(lambda s: s.rolling(20, min_periods=4).kurt())
    tail_asym_20 = ret.groupby(frame[cfg.symbol_col], sort=False).transform(lambda s: s.rolling(20, min_periods=2).apply(_tail_asymmetry, raw=False))
    amihud_20 = (abs_ret / (amount + float(cfg.eps))).groupby(frame[cfg.symbol_col], sort=False).transform(lambda s: s.rolling(20, min_periods=1).mean())

    out = pd.DataFrame({
        cfg.symbol_col: frame[cfg.symbol_col],
        cfg.date_col: frame[cfg.date_col],
        'ret_1d': ret,
        'ret_5d': close / grouped['close'].shift(5) - 1.0,
        'ret_20d': close / grouped['close'].shift(20) - 1.0,
        'range_pct': (high - low) / (close + float(cfg.eps)),
        'open_close_ret': close / (open_px + float(cfg.eps)) - 1.0,
        'vwap_close_spread': vwap / (close + float(cfg.eps)) - 1.0,
        'ma5_close_ratio': ma5 / (close + float(cfg.eps)),
        'ma20_close_ratio': ma20 / (close + float(cfg.eps)),
        'volatility_20d': volatility_20,
        'downside_volatility_20d': downside_volatility_20,
        'ret_skew_20d': skew_20,
        'ret_excess_kurtosis_20d': kurt_20,
        'ret_tail_asymmetry_20d': tail_asym_20,
        'amount_mean_20d': amount_mean_20,
        'volume_ratio_20d': volume / (volume_mean_20 + float(cfg.eps)),
        'amihud_20d': amihud_20,
    })
    out.attrs['dataset_id'] = 'daily_technical_state_v1'
    out.attrs['schema_version'] = 'daily_technical_state_v1'
    out.attrs['source_dataset'] = 'clean_daily_bar'
    out.attrs['information_set'] = 'uses current and prior daily bars only; no future shifts'
    return out


def build_daily_technical_state_qa(
    frame: pd.DataFrame,
    *,
    params: DailyTechnicalStateParams | None = None,
) -> dict[str, Any]:
    cfg = params or DailyTechnicalStateParams()
    key_cols = [cfg.symbol_col, cfg.date_col]
    feature_cols = [column for column in frame.columns if column not in set(key_cols)]
    dates = frame[cfg.date_col].astype(str) if cfg.date_col in frame.columns and not frame.empty else pd.Series(dtype=str)
    tickers = frame[cfg.symbol_col].astype(str) if cfg.symbol_col in frame.columns and not frame.empty else pd.Series(dtype=str)
    duplicate_key_count = int(frame.duplicated(key_cols).sum()) if all(col in frame.columns for col in key_cols) else 0
    missing_features = [column for column in FEATURE_COLUMNS if column not in frame.columns]
    unexpected_features = [column for column in feature_cols if column not in FEATURE_COLUMNS]
    issues: list[str] = []
    if frame.empty:
        issues.append('row_count_zero')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if missing_features:
        issues.append('missing_expected_features')
    if unexpected_features:
        issues.append('unexpected_features')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': 'daily_technical_state_v1',
        'schema_version': 'daily_technical_state_v1',
        'source_dataset': 'clean_daily_bar',
        'unique_key': key_cols,
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if not dates.empty else 0,
        'ticker_count': int(tickers.nunique()) if not tickers.empty else 0,
        'start_date': str(dates.min()) if not dates.empty else None,
        'end_date': str(dates.max()) if not dates.empty else None,
        'feature_count': len(feature_cols),
        'expected_feature_count': len(FEATURE_COLUMNS),
        'missing_features': missing_features,
        'unexpected_features': unexpected_features,
        'duplicate_key_count': duplicate_key_count,
        'null_ratio_by_field': {
            column: round(float(frame[column].isna().mean()), 6)
            for column in feature_cols
        },
        'issues': issues,
        'information_set_legality': {
            'uses_future_rows': False,
            'shift_direction': 'current_and_prior_rows_only',
            'rolling_windows': 'per stock trailing windows including current row',
        },
    }
