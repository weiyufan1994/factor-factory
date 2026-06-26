from __future__ import annotations

import math
from typing import Mapping

import pandas as pd


STANDARD_MARKET_UNIVERSE_ID = 'standard_full_market'
STANDARD_MARKET_UNIVERSE_NAME = '标准全市场'
MICROCAP_SMALL10_UNIVERSE_ID = 'microcap_small10'
MICROCAP_SMALL20_UNIVERSE_ID = 'microcap_small20'
MICROCAP_SMALL10_UNIVERSE_NAME = '微盘Small10'
MICROCAP_SMALL20_UNIVERSE_NAME = '微盘Small20'
MIN_MARKET_CAP_WAN = 50_000.0

INDEX_UNIVERSE_IDS = {
    '000300.SH': 'csi300',
    '000510.SH': 'csi_a500',
    '000852.SH': 'csi1000',
    '000905.SH': 'csi500',
    '000906.SH': 'csi800',
    '000985.CSI': 'csi_all_share',
    '000985.SH': 'csi_all_share',
    '932000.CSI': 'csi2000',
}


def build_standard_market_universe(
    daily_basic: pd.DataFrame,
    *,
    top_fraction: float = 0.10,
    bottom_fraction: float = 0.10,
    top_cap: int = 300,
    min_market_cap_wan: float = MIN_MARKET_CAP_WAN,
) -> pd.DataFrame:
    required = {'ts_code', 'trade_date', 'circ_mv', 'total_mv'}
    missing = required - set(daily_basic.columns)
    if missing:
        raise ValueError(f'daily_basic missing columns: {sorted(missing)}')
    frame = daily_basic.copy()
    frame['trade_date'] = normalize_yyyymmdd(frame['trade_date'])
    frame['market_cap'] = pd.to_numeric(frame['circ_mv'], errors='coerce')
    total_mv = pd.to_numeric(frame['total_mv'], errors='coerce')
    frame['market_cap_source'] = 'circ_mv'
    fallback = frame['market_cap'].isna() & total_mv.notna()
    frame.loc[fallback, 'market_cap'] = total_mv.loc[fallback]
    frame.loc[fallback, 'market_cap_source'] = 'total_mv'
    frame['market_cap_source'] = frame['market_cap_source'].where(frame['market_cap'].notna(), 'missing')

    out = []
    for _, group in frame.groupby('trade_date', sort=True, observed=True):
        out.append(_mark_standard_market_date(group, top_fraction, bottom_fraction, top_cap, min_market_cap_wan))
    result = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=[
        'universe_id',
        'universe_name',
        'trade_date',
        'ts_code',
        'market_cap',
        'market_cap_source',
        'market_cap_rank_desc',
        'market_cap_rank_asc',
        'excluded_top_market_cap',
        'excluded_bottom_market_cap',
        'excluded_small_cap',
        'in_universe',
    ])
    return result.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)


def build_microcap_universe(
    daily_basic: pd.DataFrame,
    *,
    stock_basic: pd.DataFrame | None = None,
    trade_calendar: pd.DataFrame | None = None,
    stock_st: pd.DataFrame | None = None,
    daily_tradability: pd.DataFrame | None = None,
    bottom_fraction: float = 0.10,
    microcap_fractions: tuple[float, ...] = (0.10, 0.20),
    min_market_cap_wan: float = MIN_MARKET_CAP_WAN,
    min_listing_days: int = 60,
) -> pd.DataFrame:
    """Build long-form microcap universes after liquidity/risk exclusions.

    The output has one row per universe_id/trade_date/ts_code. `in_universe`
    marks membership for that microcap bucket while exclusion columns explain
    why a stock was not eligible.
    """
    required = {'ts_code', 'trade_date', 'circ_mv', 'total_mv'}
    missing = required - set(daily_basic.columns)
    if missing:
        raise ValueError(f'daily_basic missing columns: {sorted(missing)}')
    if not microcap_fractions:
        raise ValueError('microcap_fractions must not be empty')

    base = _prepare_market_cap_frame(daily_basic)
    base = _attach_stock_basic_flags(base, stock_basic, trade_calendar, min_listing_days)
    base = _attach_stock_st_flags(base, stock_st)
    base = _attach_tradability_flags(base, daily_tradability)

    out: list[pd.DataFrame] = []
    for _, group in base.groupby('trade_date', sort=True, observed=True):
        out.append(_mark_microcap_date(group, bottom_fraction, microcap_fractions, min_market_cap_wan))
    marked = pd.concat(out, ignore_index=True) if out else _empty_microcap_base()

    long_frames: list[pd.DataFrame] = []
    id_map = {
        0.10: (MICROCAP_SMALL10_UNIVERSE_ID, MICROCAP_SMALL10_UNIVERSE_NAME),
        0.20: (MICROCAP_SMALL20_UNIVERSE_ID, MICROCAP_SMALL20_UNIVERSE_NAME),
    }
    for fraction in microcap_fractions:
        label = _microcap_fraction_label(fraction)
        universe_id, universe_name = id_map.get(fraction, (f'microcap_small{label}', f'微盘Small{label}'))
        flag = f'in_microcap_small{label}'
        temp = marked.copy()
        temp['universe_id'] = universe_id
        temp['universe_name'] = universe_name
        temp['microcap_fraction'] = float(fraction)
        temp['in_universe'] = temp[flag].fillna(False)
        long_frames.append(temp)

    result = pd.concat(long_frames, ignore_index=True, sort=False) if long_frames else _empty_microcap_base()
    columns = [
        'universe_id',
        'universe_name',
        'trade_date',
        'ts_code',
        'market_cap',
        'market_cap_source',
        'base_market_cap_rank_asc',
        'microcap_rank_asc_after_exclusion',
        'microcap_rank_pct_after_exclusion',
        'microcap_fraction',
        'excluded_small_cap',
        'excluded_bottom_market_cap',
        'excluded_st',
        'excluded_new_stock',
        'excluded_untradable',
        'excluded_major_risk',
        'is_eligible_after_exclusion',
        'in_universe',
    ]
    return result[columns].sort_values(['universe_id', 'trade_date', 'ts_code']).reset_index(drop=True)


def build_tradability_risk_flags_daily(
    daily: pd.DataFrame,
    *,
    daily_basic: pd.DataFrame | None = None,
    stock_basic: pd.DataFrame | None = None,
    trade_calendar: pd.DataFrame | None = None,
    stock_st: pd.DataFrame | None = None,
    min_market_cap_wan: float = MIN_MARKET_CAP_WAN,
    min_listing_days: int = 60,
) -> pd.DataFrame:
    """Build reusable daily investability flags for raw universes.

    `is_investable_core` excludes ST, new listings, untradable rows, and major
    risk statuses. `is_investable_500m` additionally excludes sub-500m CNY
    market-cap rows, allowing downstream universes to choose the stricter
    policy without mutating their raw membership.
    """
    required = {'ts_code', 'trade_date'}
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f'daily missing columns: {sorted(missing)}')

    frame = daily.copy()
    frame['ts_code'] = frame['ts_code'].astype(str).str.strip()
    frame['trade_date'] = normalize_yyyymmdd(frame['trade_date'])
    frame = frame.drop_duplicates(['ts_code', 'trade_date'], keep='last')

    if daily_basic is not None and not daily_basic.empty:
        required_basic = {'ts_code', 'trade_date', 'circ_mv', 'total_mv'}
        missing_basic = required_basic - set(daily_basic.columns)
        if missing_basic:
            raise ValueError(f'daily_basic missing columns: {sorted(missing_basic)}')
        cap = _prepare_market_cap_frame(daily_basic)[[
            'ts_code',
            'trade_date',
            'market_cap',
            'market_cap_source',
        ]].drop_duplicates(['ts_code', 'trade_date'], keep='last')
        frame = frame.merge(cap, on=['ts_code', 'trade_date'], how='left')
    else:
        frame['market_cap'] = pd.NA
        frame['market_cap_source'] = 'missing'

    frame = _attach_stock_basic_flags(frame, stock_basic, trade_calendar, min_listing_days)
    frame = _attach_stock_st_flags(frame, stock_st)
    frame = _attach_tradability_flags(frame, daily)
    frame['excluded_small_cap'] = pd.to_numeric(frame['market_cap'], errors='coerce').lt(float(min_market_cap_wan)).fillna(True)

    for column in ['excluded_st', 'excluded_new_stock', 'excluded_untradable', 'excluded_major_risk', 'excluded_small_cap']:
        if column not in frame.columns:
            frame[column] = False
        frame[column] = frame[column].fillna(False).astype(bool)

    frame['is_investable_core'] = ~(
        frame['excluded_st']
        | frame['excluded_new_stock']
        | frame['excluded_untradable']
        | frame['excluded_major_risk']
    )
    frame['is_investable_500m'] = frame['is_investable_core'] & ~frame['excluded_small_cap']

    columns = [
        'trade_date',
        'ts_code',
        'market_cap',
        'market_cap_source',
        'excluded_small_cap',
        'excluded_st',
        'excluded_new_stock',
        'excluded_untradable',
        'excluded_major_risk',
        'is_investable_core',
        'is_investable_500m',
    ]
    return frame[columns].sort_values(['trade_date', 'ts_code']).reset_index(drop=True)


def build_index_weight_universe(
    index_weight: pd.DataFrame,
    *,
    index_names: Mapping[str, str] | None = None,
    universe_ids: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    required = {'index_code', 'con_code', 'trade_date', 'weight'}
    missing = required - set(index_weight.columns)
    if missing:
        raise ValueError(f'index_weight missing columns: {sorted(missing)}')
    names = dict(index_names or {})
    ids = dict(INDEX_UNIVERSE_IDS)
    ids.update(universe_ids or {})
    frame = index_weight.copy()
    frame['index_code'] = frame['index_code'].astype(str).str.strip()
    frame['ts_code'] = frame['con_code'].astype(str).str.strip()
    frame['trade_date'] = normalize_yyyymmdd(frame['trade_date'])
    frame['weight'] = pd.to_numeric(frame['weight'], errors='coerce')
    frame = frame[frame['index_code'].ne('') & frame['ts_code'].ne('') & frame['trade_date'].ne('')]
    frame = frame.sort_values(['index_code', 'trade_date', 'ts_code'])
    frame = frame.drop_duplicates(['index_code', 'trade_date', 'ts_code'], keep='last')
    frame['universe_id'] = frame['index_code'].map(ids).fillna(frame['index_code'].str.lower().str.replace('.', '_', regex=False))
    frame['index_name'] = frame['index_code'].map(names).fillna(frame['index_code'])
    frame['in_universe'] = True
    return frame[[
        'universe_id',
        'index_code',
        'index_name',
        'trade_date',
        'ts_code',
        'weight',
        'in_universe',
    ]].sort_values(['universe_id', 'trade_date', 'ts_code']).reset_index(drop=True)


def expand_index_weight_universe_daily(
    index_weight: pd.DataFrame,
    *,
    trade_dates: list[str] | tuple[str, ...] | pd.Series,
    index_names: Mapping[str, str] | None = None,
    universe_ids: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    snapshots = build_index_weight_universe(index_weight, index_names=index_names, universe_ids=universe_ids)
    if snapshots.empty:
        return pd.DataFrame(columns=[
            'universe_id',
            'index_code',
            'index_name',
            'trade_date',
            'source_weight_date',
            'ts_code',
            'weight',
            'in_universe',
        ])
    calendar = sorted(set(normalize_yyyymmdd(trade_dates)))
    if not calendar:
        return snapshots.assign(source_weight_date=snapshots['trade_date'])[[
            'universe_id',
            'index_code',
            'index_name',
            'trade_date',
            'source_weight_date',
            'ts_code',
            'weight',
            'in_universe',
        ]]

    expanded: list[pd.DataFrame] = []
    for _, index_frame in snapshots.groupby('index_code', sort=True, observed=True):
        weight_dates = sorted(index_frame['trade_date'].dropna().astype(str).unique())
        for pos, weight_date in enumerate(weight_dates):
            next_weight_date = weight_dates[pos + 1] if pos + 1 < len(weight_dates) else None
            active_dates = [
                date for date in calendar
                if date >= weight_date and (next_weight_date is None or date < next_weight_date)
            ]
            if not active_dates:
                continue
            membership = index_frame[index_frame['trade_date'].astype(str) == weight_date].copy()
            for trade_date in active_dates:
                daily = membership.copy()
                daily['source_weight_date'] = weight_date
                daily['trade_date'] = trade_date
                expanded.append(daily)
    if not expanded:
        return pd.DataFrame(columns=[
            'universe_id',
            'index_code',
            'index_name',
            'trade_date',
            'source_weight_date',
            'ts_code',
            'weight',
            'in_universe',
        ])
    out = pd.concat(expanded, ignore_index=True, sort=False)
    return out[[
        'universe_id',
        'index_code',
        'index_name',
        'trade_date',
        'source_weight_date',
        'ts_code',
        'weight',
        'in_universe',
    ]].sort_values(['universe_id', 'trade_date', 'ts_code']).reset_index(drop=True)


def normalize_yyyymmdd(values) -> pd.Series:
    series = pd.Series(values).astype(str).str.strip()
    series = series.str.replace('-', '', regex=False).str.replace('.0', '', regex=False)
    return series.str.zfill(8)


def _prepare_market_cap_frame(daily_basic: pd.DataFrame) -> pd.DataFrame:
    frame = daily_basic.copy()
    frame['ts_code'] = frame['ts_code'].astype(str).str.strip()
    frame['trade_date'] = normalize_yyyymmdd(frame['trade_date'])
    frame['market_cap'] = pd.to_numeric(frame['circ_mv'], errors='coerce')
    total_mv = pd.to_numeric(frame['total_mv'], errors='coerce')
    frame['market_cap_source'] = 'circ_mv'
    fallback = frame['market_cap'].isna() & total_mv.notna()
    frame.loc[fallback, 'market_cap'] = total_mv.loc[fallback]
    frame.loc[fallback, 'market_cap_source'] = 'total_mv'
    frame['market_cap_source'] = frame['market_cap_source'].where(frame['market_cap'].notna(), 'missing')
    return frame


def _attach_stock_basic_flags(
    frame: pd.DataFrame,
    stock_basic: pd.DataFrame | None,
    trade_calendar: pd.DataFrame | None,
    min_listing_days: int,
) -> pd.DataFrame:
    out = frame.copy()
    out['excluded_new_stock'] = False
    out['excluded_major_risk'] = False
    if stock_basic is None or stock_basic.empty:
        return out

    columns = [column for column in ['ts_code', 'name', 'list_status', 'list_date'] if column in stock_basic.columns]
    if 'ts_code' not in columns:
        return out
    basic = stock_basic[columns].copy()
    basic['ts_code'] = basic['ts_code'].astype(str).str.strip()
    if 'list_date' in basic.columns:
        basic['list_date'] = normalize_yyyymmdd(basic['list_date'])
    basic = basic.drop_duplicates('ts_code', keep='last')
    out = out.merge(basic, on='ts_code', how='left')

    if 'list_date' in out.columns and min_listing_days > 0:
        listing_days = _listing_days(out['trade_date'], out['list_date'], trade_calendar)
        out['listing_days'] = listing_days
        out['excluded_new_stock'] = listing_days.lt(float(min_listing_days)) | listing_days.isna()
    if 'list_status' in out.columns:
        out['excluded_major_risk'] = out['excluded_major_risk'] | out['list_status'].fillna('').astype(str).ne('L')
    if 'name' in out.columns:
        name = out['name'].fillna('').astype(str).str.upper()
        out['excluded_st'] = name.str.contains('ST', regex=False)
        out['excluded_major_risk'] = out['excluded_major_risk'] | name.str.contains('退', regex=False)
    return out


def _attach_stock_st_flags(frame: pd.DataFrame, stock_st: pd.DataFrame | None) -> pd.DataFrame:
    out = frame.copy()
    if 'excluded_st' not in out.columns:
        out['excluded_st'] = False
    if stock_st is None or stock_st.empty or 'ts_code' not in stock_st.columns:
        return out
    st = stock_st.copy()
    st['ts_code'] = st['ts_code'].astype(str).str.strip()
    if {'trade_date', 'is_st'}.issubset(st.columns):
        st['trade_date'] = normalize_yyyymmdd(st['trade_date'])
        st['is_st'] = st['is_st'].fillna(False).astype(bool)
        flags = st[['ts_code', 'trade_date', 'is_st']].drop_duplicates(['ts_code', 'trade_date'], keep='last')
        out = out.merge(flags, on=['ts_code', 'trade_date'], how='left')
        out['excluded_st'] = out['excluded_st'] | out['is_st'].fillna(False)
        return out
    if {'start_date', 'end_date'}.issubset(st.columns):
        st['start_date'] = normalize_yyyymmdd(st['start_date'])
        end_date = st['end_date'].astype('string').str.strip()
        end_date = end_date.mask(end_date.isna() | end_date.eq('') | end_date.str.lower().isin(['nan', 'nat', 'none']), '99991231')
        st['end_date'] = normalize_yyyymmdd(end_date)
        if 'is_st' in st.columns:
            st = st[st['is_st'].fillna(False).astype(bool)].copy()
        out['excluded_st'] = out['excluded_st'] | _interval_membership(out, st, 'start_date', 'end_date')
    return out


def _attach_tradability_flags(frame: pd.DataFrame, daily_tradability: pd.DataFrame | None) -> pd.DataFrame:
    out = frame.copy()
    out['excluded_untradable'] = False
    if daily_tradability is None or daily_tradability.empty:
        return out
    columns = [column for column in ['ts_code', 'trade_date', 'vol', 'amount', 'close'] if column in daily_tradability.columns]
    if not {'ts_code', 'trade_date'}.issubset(columns):
        return out
    daily = daily_tradability[columns].copy()
    daily['ts_code'] = daily['ts_code'].astype(str).str.strip()
    daily['trade_date'] = normalize_yyyymmdd(daily['trade_date'])
    daily = daily.drop_duplicates(['ts_code', 'trade_date'], keep='last')
    out = out.merge(daily, on=['ts_code', 'trade_date'], how='left', suffixes=('', '_daily'))
    if 'vol' in out.columns:
        out['excluded_untradable'] = out['excluded_untradable'] | pd.to_numeric(out['vol'], errors='coerce').fillna(0).le(0)
    if 'amount' in out.columns:
        out['excluded_untradable'] = out['excluded_untradable'] | pd.to_numeric(out['amount'], errors='coerce').fillna(0).le(0)
    if 'close' in out.columns:
        out['excluded_untradable'] = out['excluded_untradable'] | pd.to_numeric(out['close'], errors='coerce').isna()
    return out


def _mark_standard_market_date(
    group: pd.DataFrame,
    top_fraction: float,
    bottom_fraction: float,
    top_cap: int,
    min_market_cap_wan: float,
) -> pd.DataFrame:
    work = group.copy()
    valid = work['market_cap'].notna()
    n = int(valid.sum())
    top_count = min(top_cap, _ceil_fraction(n, top_fraction))
    bottom_count = _ceil_fraction(n, bottom_fraction)

    ranked_desc = work.loc[valid, 'market_cap'].rank(method='first', ascending=False)
    ranked_asc = work.loc[valid, 'market_cap'].rank(method='first', ascending=True)
    work['market_cap_rank_desc'] = pd.NA
    work['market_cap_rank_asc'] = pd.NA
    work.loc[ranked_desc.index, 'market_cap_rank_desc'] = ranked_desc.astype('Int64')
    work.loc[ranked_asc.index, 'market_cap_rank_asc'] = ranked_asc.astype('Int64')
    work['excluded_top_market_cap'] = work['market_cap_rank_desc'].le(top_count).fillna(False)
    work['excluded_bottom_market_cap'] = work['market_cap_rank_asc'].le(bottom_count).fillna(False)
    work['excluded_small_cap'] = work['market_cap'].lt(float(min_market_cap_wan)).fillna(True)
    work['in_universe'] = ~(
        work['excluded_top_market_cap']
        | work['excluded_bottom_market_cap']
        | work['excluded_small_cap']
    )
    work['universe_id'] = STANDARD_MARKET_UNIVERSE_ID
    work['universe_name'] = STANDARD_MARKET_UNIVERSE_NAME
    return work[[
        'universe_id',
        'universe_name',
        'trade_date',
        'ts_code',
        'market_cap',
        'market_cap_source',
        'market_cap_rank_desc',
        'market_cap_rank_asc',
        'excluded_top_market_cap',
        'excluded_bottom_market_cap',
        'excluded_small_cap',
        'in_universe',
    ]]


def _mark_microcap_date(
    group: pd.DataFrame,
    bottom_fraction: float,
    microcap_fractions: tuple[float, ...],
    min_market_cap_wan: float,
) -> pd.DataFrame:
    work = group.copy()
    valid = work['market_cap'].notna()
    n = int(valid.sum())
    bottom_count = _ceil_fraction(n, bottom_fraction)
    ranked_asc = work.loc[valid, 'market_cap'].rank(method='first', ascending=True)
    work['base_market_cap_rank_asc'] = pd.NA
    work.loc[ranked_asc.index, 'base_market_cap_rank_asc'] = ranked_asc.astype('Int64')
    work['excluded_small_cap'] = work['market_cap'].lt(float(min_market_cap_wan)).fillna(True)
    work['excluded_bottom_market_cap'] = work['base_market_cap_rank_asc'].le(bottom_count).fillna(False)
    for column in ['excluded_st', 'excluded_new_stock', 'excluded_untradable', 'excluded_major_risk']:
        if column not in work.columns:
            work[column] = False
        work[column] = work[column].fillna(False).astype(bool)
    work['is_eligible_after_exclusion'] = ~(
        work['excluded_small_cap']
        | work['excluded_bottom_market_cap']
        | work['excluded_st']
        | work['excluded_new_stock']
        | work['excluded_untradable']
        | work['excluded_major_risk']
    )
    eligible = work['is_eligible_after_exclusion']
    eligible_rank = work.loc[eligible, 'market_cap'].rank(method='first', ascending=True)
    eligible_count = int(eligible.sum())
    work['microcap_rank_asc_after_exclusion'] = pd.NA
    work.loc[eligible_rank.index, 'microcap_rank_asc_after_exclusion'] = eligible_rank.astype('Int64')
    if eligible_count:
        work['microcap_rank_pct_after_exclusion'] = (
            pd.to_numeric(work['microcap_rank_asc_after_exclusion'], errors='coerce') / float(eligible_count)
        )
    else:
        work['microcap_rank_pct_after_exclusion'] = pd.NA
    for fraction in microcap_fractions:
        label = _microcap_fraction_label(fraction)
        count = _ceil_fraction(eligible_count, fraction)
        work[f'in_microcap_small{label}'] = (
            work['is_eligible_after_exclusion']
            & pd.to_numeric(work['microcap_rank_asc_after_exclusion'], errors='coerce').le(count)
        )
    return work


def _ceil_fraction(n: int, fraction: float) -> int:
    if n <= 0 or fraction <= 0:
        return 0
    return int(math.ceil(n * fraction))


def _microcap_fraction_label(fraction: float) -> str:
    return str(int(round(float(fraction) * 100)))


def _listing_days(trade_dates: pd.Series, list_dates: pd.Series, trade_calendar: pd.DataFrame | None) -> pd.Series:
    trade = normalize_yyyymmdd(trade_dates)
    listed = normalize_yyyymmdd(list_dates)
    if trade_calendar is not None and not trade_calendar.empty:
        cal_col = 'cal_date' if 'cal_date' in trade_calendar.columns else 'trade_date'
        calendar = pd.DataFrame({'cal_date': normalize_yyyymmdd(trade_calendar[cal_col])})
        if 'is_open' in trade_calendar.columns:
            calendar = calendar[trade_calendar['is_open'].astype(str).isin(['1', 'True', 'true'])]
        open_dates = sorted(calendar['cal_date'].dropna().astype(str).unique())
        ranks = {date: idx for idx, date in enumerate(open_dates)}
        trade_rank = trade.map(ranks)
        list_rank = listed.map(lambda value: _first_open_rank(str(value), open_dates))
        return trade_rank.astype('float64') - list_rank.astype('float64') + 1.0
    trade_dt = pd.to_datetime(trade, format='%Y%m%d', errors='coerce')
    list_dt = pd.to_datetime(listed, format='%Y%m%d', errors='coerce')
    return (trade_dt - list_dt).dt.days.astype('float64') + 1.0


def _first_open_rank(value: str, open_dates: list[str]) -> float:
    if not value or value == '00000000' or not value.isdigit():
        return math.nan
    pos = 0
    lo, hi = 0, len(open_dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if open_dates[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    pos = lo
    return float(pos) if pos < len(open_dates) else math.nan


def _interval_membership(frame: pd.DataFrame, intervals: pd.DataFrame, start_col: str, end_col: str) -> pd.Series:
    result = pd.Series(False, index=frame.index)
    if intervals.empty:
        return result
    lookup = intervals.copy()
    lookup['start_int'] = pd.to_numeric(lookup[start_col], errors='coerce')
    lookup['end_int'] = pd.to_numeric(lookup[end_col], errors='coerce').fillna(99991231)
    lookup = lookup.dropna(subset=['start_int']).sort_values(['ts_code', 'start_int'])
    frame_dates = pd.to_numeric(frame['trade_date'], errors='coerce')
    for ts_code, group in lookup.groupby('ts_code', sort=False):
        idx = frame.index[frame['ts_code'].astype(str).eq(str(ts_code))]
        if len(idx) == 0:
            continue
        dates = frame_dates.loc[idx]
        active = pd.Series(False, index=idx)
        for _, interval in group.iterrows():
            active = active | dates.between(float(interval['start_int']), float(interval['end_int']))
        result.loc[idx] = active
    return result


def _empty_microcap_base() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        'universe_id',
        'universe_name',
        'trade_date',
        'ts_code',
        'market_cap',
        'market_cap_source',
        'base_market_cap_rank_asc',
        'microcap_rank_asc_after_exclusion',
        'microcap_rank_pct_after_exclusion',
        'microcap_fraction',
        'excluded_small_cap',
        'excluded_bottom_market_cap',
        'excluded_st',
        'excluded_new_stock',
        'excluded_untradable',
        'excluded_major_risk',
        'is_eligible_after_exclusion',
        'in_universe',
    ])
