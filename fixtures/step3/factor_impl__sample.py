from __future__ import annotations

import pandas as pd


def compute_factor(minute_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    required_minute = ['ts_code', 'trade_date', 'close', 'vol', 'amount']
    required_daily = ['ts_code', 'trade_date', 'pct_chg', 'vol', 'amount']
    for c in required_minute:
        if c not in minute_df.columns:
            raise KeyError(f'missing minute column: {c}')
    for c in required_daily:
        if c not in daily_df.columns:
            raise KeyError(f'missing daily column: {c}')

    minute_group = minute_df.groupby(['ts_code', 'trade_date'], as_index=False).agg(
        minute_close_mean=('close', 'mean'),
        minute_vol_mean=('vol', 'mean'),
        minute_amount_mean=('amount', 'mean')
    )
    out = minute_group.merge(
        daily_df[['ts_code', 'trade_date', 'pct_chg', 'amount']].rename(columns={'amount': 'daily_amount'}),
        on=['ts_code', 'trade_date'],
        how='left'
    )
    out['cpv_factor'] = (
        out['minute_close_mean'] * 0.3 +
        out['minute_vol_mean'] * 0.0001 +
        out['minute_amount_mean'] * 0.00001 -
        out['pct_chg'].fillna(0) * 0.2
    )
    return out[['ts_code', 'trade_date', 'cpv_factor']]
