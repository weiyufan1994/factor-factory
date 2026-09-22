from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .daily import DEFAULT_DAILY_COLUMNS, _normalize_date, _normalize_symbols
from .paths import LocalTusharePaths, resolve_local_tushare_paths


@dataclass(frozen=True)
class DailyFilterPolicy:
    adjust_mode: str = 'forward'
    drop_bj: bool = True
    drop_st: bool = True
    min_listing_days: int = 60
    drop_suspended: bool = True
    drop_limit_events: bool = True
    drop_abnormal_pct_move: bool = True
    limit_tolerance_ratio: float = 0.003


def _cache_key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime), stat.st_size)


@lru_cache(maxsize=8)
def _load_adj_factor_cached(cache_key: tuple[str, int, int]) -> pd.DataFrame:
    path = Path(cache_key[0])
    frame = pd.read_csv(
        path,
        usecols=['ts_code', 'trade_date', 'adj_factor'],
        dtype={'ts_code': 'string', 'trade_date': 'string'},
    )
    frame['trade_date'] = frame['trade_date'].str.replace('.0', '', regex=False).str.zfill(8)
    frame['adj_factor'] = pd.to_numeric(frame['adj_factor'], errors='coerce')
    latest = frame.groupby('ts_code', sort=False)['adj_factor'].transform('last')
    first = frame.groupby('ts_code', sort=False)['adj_factor'].transform('first')
    frame['forward_factor'] = frame['adj_factor'] / latest.replace(0, np.nan)
    frame['backward_factor'] = frame['adj_factor'] / first.replace(0, np.nan)
    return frame


@lru_cache(maxsize=8)
def _load_stock_basic_cached(cache_key: tuple[str, int, int]) -> pd.DataFrame:
    path = Path(cache_key[0])
    frame = pd.read_csv(
        path,
        usecols=['ts_code', 'name', 'market', 'list_status', 'list_date'],
        dtype={'ts_code': 'string', 'name': 'string', 'market': 'string', 'list_status': 'string', 'list_date': 'string'},
    )
    frame['list_date'] = frame['list_date'].str.replace('.0', '', regex=False).str.zfill(8)
    return frame


@lru_cache(maxsize=8)
def _load_trade_calendar_cached(cache_key: tuple[str, int, int]) -> pd.DataFrame:
    path = Path(cache_key[0])
    frame = pd.read_csv(
        path,
        usecols=['cal_date', 'is_open'],
        dtype={'cal_date': 'string'},
    )
    frame['cal_date'] = frame['cal_date'].str.replace('.0', '', regex=False).str.zfill(8)
    frame = frame[frame['is_open'] == 1].copy()
    frame = frame.sort_values('cal_date').reset_index(drop=True)
    frame['trade_rank'] = np.arange(len(frame), dtype=np.int64)
    return frame[['cal_date', 'trade_rank']]


@lru_cache(maxsize=8)
def _load_stock_st_cached(cache_key: tuple[str, int, int]) -> pd.DataFrame:
    path = Path(cache_key[0])
    frame = pd.read_csv(
        path,
        usecols=['ts_code', 'start_date', 'end_date', 'is_st'],
        dtype={'ts_code': 'string', 'start_date': 'string', 'end_date': 'string'},
    )
    frame['start_date'] = frame['start_date'].str.replace('.0', '', regex=False).str.zfill(8)
    frame['end_date'] = frame['end_date'].fillna('').astype(str).str.replace('.0', '', regex=False)
    frame['end_date'] = frame['end_date'].where(frame['end_date'].ne(''), pd.NA)
    frame['start_date_int'] = pd.to_numeric(frame['start_date'], errors='coerce')
    frame['end_date_int'] = pd.to_numeric(frame['end_date'], errors='coerce')
    frame = frame[frame['is_st'].fillna(False)].copy()
    frame = frame.dropna(subset=['start_date_int']).sort_values(['ts_code', 'start_date_int', 'end_date_int'])
    frame = frame.drop_duplicates(subset=['ts_code', 'start_date_int', 'end_date_int'])
    return frame[['ts_code', 'start_date_int', 'end_date_int']]


def _load_adj_factor(paths: LocalTusharePaths) -> pd.DataFrame:
    csv_path = Path(paths.adj_factor_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f'adj_factor.csv not found: {csv_path}')
    return _load_adj_factor_cached(_cache_key(csv_path))


def _load_stock_basic(paths: LocalTusharePaths) -> pd.DataFrame:
    csv_path = Path(paths.stock_basic_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f'stock_basic.csv not found: {csv_path}')
    return _load_stock_basic_cached(_cache_key(csv_path))


def _load_trade_calendar(paths: LocalTusharePaths) -> pd.DataFrame:
    csv_path = Path(paths.trade_cal_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f'trade_cal.csv not found: {csv_path}')
    return _load_trade_calendar_cached(_cache_key(csv_path))


def _load_stock_st(paths: LocalTusharePaths) -> pd.DataFrame:
    csv_path = Path(paths.stock_st_csv)
    if not csv_path.exists():
        return pd.DataFrame(columns=['ts_code', 'start_date_int', 'end_date_int'])
    return _load_stock_st_cached(_cache_key(csv_path))


def _trading_age_series(trade_dates: pd.Series, list_dates: pd.Series, calendar: pd.DataFrame) -> pd.Series:
    trade_rank_map = calendar.set_index('cal_date')['trade_rank']
    trade_rank = trade_dates.map(trade_rank_map)
    open_dates = calendar['cal_date'].to_numpy(dtype='U8')
    list_date_values = list_dates.fillna('99999999').astype(str).to_numpy(dtype='U8')
    list_rank = np.searchsorted(open_dates, list_date_values, side='left')
    result = trade_rank.to_numpy(dtype='float64') - list_rank.astype('float64') + 1.0
    result[np.isnan(trade_rank.to_numpy(dtype='float64'))] = np.nan
    result[list_date_values == '99999999'] = np.nan
    return pd.Series(result, index=trade_dates.index)


def _merge_st_flags(frame: pd.DataFrame, st_intervals: pd.DataFrame) -> pd.Series:
    if frame.empty or st_intervals.empty:
        return pd.Series(False, index=frame.index)

    result = np.zeros(len(frame), dtype=bool)
    st_groups = {
        ts_code: (
            group['start_date_int'].to_numpy(dtype='int64'),
            group['end_date_int'].to_numpy(dtype='float64'),
        )
        for ts_code, group in st_intervals.groupby('ts_code', sort=False)
    }

    for ts_code, group in frame[['ts_code', 'trade_date_int']].groupby('ts_code', sort=False):
        if ts_code not in st_groups:
            continue
        trade_dates = pd.to_numeric(group['trade_date_int'], errors='coerce').to_numpy(dtype='float64')
        valid_dates = ~np.isnan(trade_dates)
        if not valid_dates.any():
            continue
        starts, ends = st_groups[ts_code]
        lookup_dates = trade_dates[valid_dates].astype('int64')
        pos = np.searchsorted(starts, lookup_dates, side='right') - 1
        mask = pos >= 0
        if not mask.any():
            continue
        end_values = ends[np.clip(pos, 0, len(ends) - 1)]
        active = mask & (np.isnan(end_values) | (lookup_dates <= end_values))
        group_result = np.zeros(len(group), dtype=bool)
        group_result[np.flatnonzero(valid_dates)] = active
        result[group.index.to_numpy()] = group_result

    return pd.Series(result, index=frame.index)


def _price_limit_ratio(frame: pd.DataFrame) -> pd.Series:
    market = frame['market'].fillna('')
    trade_date_int = frame['trade_date_int'].fillna(0).astype(int)

    is_chinext_new_regime = market.eq('创业板') & (trade_date_int >= 20200824)
    is_kcb = market.eq('科创板')
    is_bj = market.eq('北交所') | frame['ts_code'].astype(str).str.endswith('.BJ')

    limit = np.full(len(frame), 0.10, dtype='float64')
    limit[is_chinext_new_regime.to_numpy()] = 0.20
    limit[is_kcb.to_numpy()] = 0.20
    limit[is_bj.to_numpy()] = 0.30
    limit[frame['is_st'].fillna(False).to_numpy()] = 0.05
    return pd.Series(limit, index=frame.index)


def get_clean_daily(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
    policy: DailyFilterPolicy | None = None,
    return_metadata: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict]:
    resolved_paths = paths or resolve_local_tushare_paths()
    active_policy = policy or DailyFilterPolicy()

    requested_columns = list(columns) if columns else list(DEFAULT_DAILY_COLUMNS)
    helper_columns = {
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
    }
    usecols = list(dict.fromkeys([*requested_columns, *helper_columns]))

    frame = pd.read_csv(
        resolved_paths.daily_csv,
        usecols=usecols,
        dtype={'ts_code': 'string', 'trade_date': 'string'},
    )
    frame['trade_date'] = frame['trade_date'].str.replace('.0', '', regex=False).str.zfill(8)

    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    if start_date:
        frame = frame[frame['trade_date'] >= start_date]
    if end_date and end_date != 'current':
        frame = frame[frame['trade_date'] <= end_date]

    symbol_set = _normalize_symbols(symbols)
    if symbol_set:
        frame = frame[frame['ts_code'].isin(symbol_set)]

    frame = frame.reset_index(drop=True)
    metadata = {
        'policy': asdict(active_policy),
        'counts': {'raw_rows': int(len(frame))},
        'drop_counts': {},
        'filter_point_in_time': True,
        'pit_guarantees': {
            'listing_days': 'computed from stock_basic.list_date + trade_cal using the row trade_date only',
            'st_windows': 'row is dropped only when row trade_date falls inside the stock_st interval',
            'suspension': 'uses same-day vol/amount/close availability only',
            'limit_events': 'uses same-day pct_chg and same-day close/high/low only',
            'abnormal_pct_move': 'compares same-day pct_chg against same-day market-board limit regime only',
        },
    }

    stock_basic = _load_stock_basic(resolved_paths)
    frame = frame.merge(stock_basic, on='ts_code', how='left')
    frame['trade_date_int'] = pd.to_numeric(frame['trade_date'], errors='coerce')
    frame['is_bj'] = frame['market'].fillna('').eq('北交所') | frame['ts_code'].astype(str).str.endswith('.BJ')

    calendar = _load_trade_calendar(resolved_paths)
    frame['listing_days'] = _trading_age_series(frame['trade_date'], frame['list_date'], calendar)

    st_intervals = _load_stock_st(resolved_paths)
    frame['is_st'] = _merge_st_flags(frame, st_intervals)

    frame['is_suspended'] = (
        pd.to_numeric(frame['vol'], errors='coerce').fillna(0).le(0)
        | pd.to_numeric(frame['amount'], errors='coerce').fillna(0).le(0)
        | frame['close'].isna()
    )

    limit_ratio = _price_limit_ratio(frame)
    pct_ratio = pd.to_numeric(frame['pct_chg'], errors='coerce') / 100.0
    close_high = np.isclose(pd.to_numeric(frame['close'], errors='coerce'), pd.to_numeric(frame['high'], errors='coerce'), rtol=1e-6, atol=1e-8)
    close_low = np.isclose(pd.to_numeric(frame['close'], errors='coerce'), pd.to_numeric(frame['low'], errors='coerce'), rtol=1e-6, atol=1e-8)
    frame['is_limit_up'] = (pct_ratio >= (limit_ratio - active_policy.limit_tolerance_ratio)) & close_high
    frame['is_limit_down'] = (pct_ratio <= (-limit_ratio + active_policy.limit_tolerance_ratio)) & close_low
    frame['is_limit_event'] = frame['is_limit_up'] | frame['is_limit_down']
    frame['is_abnormal_pct_move'] = pct_ratio.abs() > (limit_ratio + active_policy.limit_tolerance_ratio)

    if active_policy.adjust_mode != 'none':
        adj = _load_adj_factor(resolved_paths)
        factor_col = 'forward_factor' if active_policy.adjust_mode == 'forward' else 'backward_factor'
        frame = frame.merge(adj[['ts_code', 'trade_date', factor_col]], on=['ts_code', 'trade_date'], how='left')
        frame['adj_multiplier'] = pd.to_numeric(frame[factor_col], errors='coerce').fillna(1.0)
        for column in ['open', 'high', 'low', 'close', 'pre_close']:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors='coerce') * frame['adj_multiplier']
        if 'change' in frame.columns and {'close', 'pre_close'}.issubset(frame.columns):
            frame['change'] = frame['close'] - frame['pre_close']
        metadata['adjusted_price_columns'] = ['open', 'high', 'low', 'close', 'pre_close']
    else:
        frame['adj_multiplier'] = 1.0
        metadata['adjusted_price_columns'] = []

    filter_masks: list[tuple[str, pd.Series]] = []
    if active_policy.drop_bj:
        filter_masks.append(('bj_rows', frame['is_bj']))
    if active_policy.drop_st:
        filter_masks.append(('st_rows', frame['is_st'].fillna(False)))
    if active_policy.min_listing_days > 0:
        filter_masks.append(('new_listing_rows', frame['listing_days'].lt(active_policy.min_listing_days) | frame['listing_days'].isna()))
    if active_policy.drop_suspended:
        filter_masks.append(('suspended_rows', frame['is_suspended']))
    if active_policy.drop_limit_events:
        filter_masks.append(('limit_event_rows', frame['is_limit_event']))
    if active_policy.drop_abnormal_pct_move:
        filter_masks.append(('abnormal_pct_move_rows', frame['is_abnormal_pct_move']))

    combined_drop = pd.Series(False, index=frame.index)
    for label, mask in filter_masks:
        clean_mask = mask.fillna(False)
        metadata['drop_counts'][label] = int(clean_mask.sum())
        combined_drop = combined_drop | clean_mask

    metadata['counts']['kept_rows'] = int((~combined_drop).sum())
    metadata['counts']['dropped_rows'] = int(combined_drop.sum())

    frame = frame.loc[~combined_drop].copy().reset_index(drop=True)
    metadata['counts']['kept_tickers'] = int(frame['ts_code'].nunique())
    metadata['counts']['kept_dates'] = int(frame['trade_date'].nunique())

    output_columns = requested_columns.copy()
    for required in ['ts_code', 'trade_date']:
        if required not in output_columns:
            output_columns.insert(0, required)
    frame = frame[output_columns]

    if return_metadata:
        return frame.reset_index(drop=True), metadata
    return frame.reset_index(drop=True)
