from __future__ import annotations

CLEAN_DAILY_BAR = 'clean_daily_bar'
DAILY_BASIC = 'daily_basic'
MINUTE_BAR = 'minute_bar'

DEFAULT_DATASET_FREQUENCY = {
    CLEAN_DAILY_BAR: 'daily',
    DAILY_BASIC: 'daily',
    MINUTE_BAR: '1min',
}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    'instrument': ('ts_code', 'instrument'),
    'symbol': ('ts_code', 'instrument'),
    'date': ('trade_date', 'datetime'),
    'datetime': ('trade_date', 'datetime'),
    'open': ('open', '$open'),
    'high': ('high', '$high'),
    'low': ('low', '$low'),
    'close': ('close', '$close'),
    'volume': ('vol', 'volume', '$volume'),
    'vol': ('vol', 'volume', '$volume'),
    'amount': ('amount', '$amount'),
    'return': ('pct_chg', 'ret', 'return_daily', '$ret'),
    'return_daily': ('pct_chg', 'ret', 'return_daily', '$ret'),
    'pct_chg': ('pct_chg', 'ret', '$ret'),
    'turnover': ('turnover_rate', 'turnover_rate_f', 'turnover'),
    'turnover_rate': ('turnover_rate', 'turnover_rate_f'),
    'float_market_cap': ('circ_mv', 'float_market_cap'),
    'market_cap': ('market_cap',),
    'total_mv': ('total_mv',),
    'circ_mv': ('circ_mv',),
    'pe': ('pe', 'pe_ttm'),
    'pb': ('pb',),
    'ps': ('ps', 'ps_ttm'),
    'time': ('trade_time', 'datetime', 'time'),
    'trade_time': ('trade_time', 'datetime'),
    'bar_time': ('bar_time', 'time'),
    'minute_index': ('minute_index',),
}

BASE_LOGICAL_FIELDS = {
    'instrument': 'ts_code',
    'symbol': 'ts_code',
    'datetime': 'trade_date',
    'date': 'trade_date',
    'open': 'open',
    'high': 'high',
    'low': 'low',
    'close': 'close',
    'volume': 'vol',
    'vol': 'vol',
    'amount': 'amount',
    'return_daily': 'pct_chg',
    'pct_chg': 'pct_chg',
}

HELPER_FIELDS = {
    CLEAN_DAILY_BAR: ('ts_code', 'trade_date'),
    DAILY_BASIC: ('ts_code', 'trade_date'),
    MINUTE_BAR: ('ts_code', 'trade_date', 'trade_time'),
}

SORT_KEYS = {
    CLEAN_DAILY_BAR: ('ts_code', 'trade_date'),
    DAILY_BASIC: ('ts_code', 'trade_date'),
    MINUTE_BAR: ('ts_code', 'trade_date', 'trade_time'),
}
