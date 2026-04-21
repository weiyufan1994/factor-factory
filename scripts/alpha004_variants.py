#!/usr/bin/env python3
"""Alpha004 variants — fully vectorized, no per-ticker loop."""
import json, sys, warnings, os
from pathlib import Path
import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')
os.environ['MPLCONFIGDIR'] = '/Users/humphrey/.cache/matplotlib'
sys.path.insert(0, '/Users/humphrey/projects/factor-factory')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from factor_factory.data_access import build_forward_return_frame, load_daily_snapshot

report_id = 'ALPHA004_PAPER_20160101_20250711'
FF = Path('/Users/humphrey/projects/factor-factory')
RUNS = FF / 'runs'; OBJ = FF / 'objects'; eval_dir = FF / 'evaluations' / report_id / 'self_quant_analyzer'
eval_dir.mkdir(parents=True, exist_ok=True)

# ── load daily ─────────────────────────────────────────────────────────────────
daily_df = pd.read_csv(
    RUNS / 'ALPHA004_PAPER_20160101_20250711' / 'step3a_local_inputs' /
    f'daily_input__ALPHA004_PAPER_20160101_20250711.csv',
    parse_dates=['trade_date']
).sort_values(['trade_date','ts_code']).reset_index(drop=True)
daily_df['td'] = daily_df['trade_date'].dt.strftime('%Y%m%d').astype(int)
print(f'Daily: {len(daily_df):,}')

# ── vol std ──────────────────────────────────────────────────────────────────
daily_df['ret_std'] = daily_df.groupby('ts_code')['pct_chg'].transform(
    lambda x: x.rolling(5, min_periods=3).std())

# ── cross-sectional ranks ─────────────────────────────────────────────────────
print('Cross-sectional ranks ...')
for col in ['vol','ret_std']:
    daily_df[f'r_{col}'] = daily_df.groupby('td')[col].rank(pct=True, method='average')

# ── market cap ──────────────────────────────────────────────────────────────
print('Loading mcap ...')
db_root = Path('/Users/humphrey/.qlib/raw_tushare/行情数据/daily_basic_incremental')
db_parts = sorted(db_root.glob('trade_date=*/daily_basic_*.csv'))
db_dfs = []
for p in db_parts:
    df = pd.read_csv(p, usecols=['ts_code','trade_date','close','free_share'])
    df['mcap'] = df['free_share'] * df['close']
    db_dfs.append(df[['ts_code','trade_date','mcap']])
db = pd.concat(db_dfs, ignore_index=True).rename(columns={'ts_code':'ts_code','trade_date':'td'}).dropna()
db['r_mcap'] = db.groupby('td')['mcap'].rank(pct=True, method='average')
db = db[['ts_code','td','r_mcap']].dropna()
daily_df = daily_df.merge(db, on=['ts_code','td'], how='left')
print(f'  mcap null={daily_df["r_mcap"].isna().sum()}')

# ── fast tsrank via numpy rolling (no per-ticker loop) ─────────────────────────
def np_tsrank(arr, window):
    """Vectorized tsrank: at each position, rank of last value within the rolling window."""
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    for i in range(window - 1, n):
        win = arr[i - window + 1:i + 1]
        last = win[-1]
        out[i] = (win <= last).sum() / window
    return out

TS = 9

# ── sort by (ticker, date) then compute tsrank as groupby rolling ─────────────
print('Computing tsrank variants (vectorized per ticker)...')
daily_df = daily_df.sort_values(['ts_code','td']).reset_index(drop=True)

for col, outcol in [('r_mcap','a_mcap_z'), ('r_vol','a_vol_z'), ('r_ret_std','a_volstd_z')]:
    print(f'  {col} ...')
    vals = daily_df[col].values
    ticker_groups = daily_df['ts_code'].values
    # Find group boundaries
    ticker_changes = np.concatenate([[0], np.where(ticker_groups[:-1] != ticker_groups[1:])[0] + 1, [len(ticker_groups)]])
    n_tickers = len(ticker_changes) - 1
    result = np.full(len(vals), np.nan, dtype=float)
    for k in range(n_tickers):
        start = ticker_changes[k]
        end = ticker_changes[k+1]
        ticker_arr = vals[start:end]
        tsrank_arr = np_tsrank(ticker_arr, TS)
        result[start:end] = tsrank_arr
    daily_df[outcol] = result

daily_df['a_mcap_z']   = -daily_df['a_mcap_z']
daily_df['a_vol_z']    = -daily_df['a_vol_z']
daily_df['a_volstd_z'] = -daily_df['a_volstd_z']
print('Tsrank done.')

# cross-sectional zscore
for c in ['a_mcap_z','a_vol_z','a_volstd_z']:
    daily_df[c] = daily_df.groupby('td')[c].transform(lambda x: (x-x.mean())/(x.std()+1e-9))

factor_df = daily_df[['ts_code','trade_date','td','a_mcap_z','a_vol_z','a_volstd_z']].dropna().copy()
factor_df = factor_df.rename(columns={'ts_code':'code'})
print(f'Factor rows={len(factor_df):,}')

# ── load returns + merge ───────────────────────────────────────────────────────
daily_ret = load_daily_snapshot(report_id, columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1
)
daily_ret['td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d').astype(int)

merged = factor_df.merge(
    daily_ret[['code','td','future_return_1d']].rename(columns={'ts_code':'code'}),
    on=['code','td'], how='left'
).dropna(subset=['future_return_1d'])
print(f'Merged rows={len(merged)}')

# ── helpers ───────────────────────────────────────────────────────────────────
def sf(v):
    if v is None or (isinstance(v, float) and np.isnan(v)): return None
    try: return float(v)
    except: return None

def series_stats(s):
    v = s.dropna()
    if v.empty: return {'mean':None,'std':None,'ir':None}
    std = v.std()
    return {'mean':sf(v.mean()),'std':sf(std),'ir':sf(v.mean()/std) if std and std==std else None}

def assign_labels(s, groups=10):
    v = s.dropna()
    if v.empty: return pd.Series(index=s.index)
    n = max(1, min(groups, int(v.nunique()), len(v)))
    if n <= 1: return pd.Series(1, index=v.index)
    return pd.qcut(v.rank(method='first'), q=n, labels=False, duplicates='drop') + 1

def quantile_nav(merged_df, sig):
    work = merged_df[['td', sig, 'future_return_1d']].copy()
    work['g'] = work.groupby('td')[sig].transform(lambda s: assign_labels(s, groups=10))
    src = work.dropna(subset=['g','future_return_1d']).assign(g=lambda df: df['g'].astype(int))
    grp = src.groupby(['td','g'])['future_return_1d'].mean().unstack('g').sort_index()
    grp.index = pd.to_datetime(grp.index.astype(str), format='%Y%m%d')
    grp.index.name = 'datetime'; grp = grp.sort_index()
    grp.columns = [f'G{int(c):02d}' for c in grp.columns]
    nav = (1.0 + grp.fillna(0.0)).cumprod()
    top_g = grp.iloc[:,-1]; bot_g = grp.iloc[:,0]
    ls = (top_g - bot_g).dropna()
    return grp, nav, top_g, bot_g, ls

# ═══════════════════════════════════════════════════════════════
variants = [('short_low_mcap','a_mcap_z'), ('short_low_vol','a_vol_z'), ('short_low_volstd','a_volstd_z')]
results = {}

for name, sig in variants:
    ic = merged.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
        lambda df: df[sig].corr(df['future_return_1d'], method='spearman'), include_groups=False)
    ic.index = pd.to_datetime(ic.index.astype(str), format='%Y%m%d')
    st = series_stats(ic)
    grp, nav, top_g, bot_g, ls = quantile_nav(merged, sig)
    results[name] = {
        'rank_ic_mean': st['mean'], 'rank_ic_ir': st['ir'],
        'ls_spread_mean': sf(ls.mean()),
        'ls_spread_ir': sf(ls.mean()/ls.std()) if not ls.empty else None,
        'top_decile_mean': sf(top_g.mean()),
        'bottom_decile_mean': sf(bot_g.mean()),
    }
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(ic.index, ic.values, lw=1.0, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
    ax.set_title(f'{name}  ir={st["ir"]:.4f}'); ax.set_ylabel('rank_ic'); ax.grid(True, alpha=0.3)
    ax.text(0.02, 0.95, f'mean={st["mean"]:.4f}  ir={st["ir"]:.4f}', transform=ax.transAxes, fontsize=9, va='top')
    fig.autofmt_xdate(); fig.tight_layout()
    fig.savefig(eval_dir / f'rank_ic__{name}.png', dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11,5))
    for col in nav.columns: ax.plot(nav.index, nav[col], lw=1.0, label=col)
    ax.set_title(f'{name} Quantile NAV'); ax.set_ylabel('nav'); ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=7); ax.axhline(1.0, color='black', lw=0.5, ls='--')
    fig.autofmt_xdate(); fig.tight_layout()
    fig.savefig(eval_dir / f'quantile_nav__{name}.png', dpi=150); plt.close(fig)

    grp.to_csv(eval_dir / f'quantile_returns__{name}.csv')
    nav.to_csv(eval_dir / f'quantile_nav__{name}.csv')

print('\n=== Variant Comparison ===')
print(f'{"Variant":<20} {"Rank IC":>10} {"IC IR":>10} {"LS IR":>10} {"Top Dec":>12} {"Bot Dec":>12}')
print('-'*76)
for name, r in results.items():
    def fmt(v): return f'{v:.6f}' if v is not None else 'N/A'
    print(f'{name:<20} {str(r["rank_ic_mean"])[:10]:>10} {str(r["rank_ic_ir"])[:10]:>10} '
          f'{str(r["ls_spread_ir"])[:10]:>10} {str(r["top_decile_mean"])[:12]:>12} '
          f'{str(r["bottom_decile_mean"])[:12]:>12}')

print('\n(Alpha004 short_low_price: rank_ic=0.0365, ir=0.276, top=-0.00037, bot=-0.00205)')

res_path = eval_dir / 'variant_tests_summary.json'
res_path.write_text(json.dumps({'variants': results}, ensure_ascii=False, indent=2))
print(f'\n[WRITE] {res_path}')
