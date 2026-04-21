#!/usr/bin/env python3
"""Alpha004 iterate tests: mcap neutralization + sign-flip."""
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

from factor_factory.data_access import (
    build_forward_return_frame,
    load_daily_snapshot,
)

report_id = 'ALPHA004_PAPER_20160101_20250711'
FF = Path('/Users/humphrey/projects/factor-factory')
RUNS = FF / 'runs'; OBJ = FF / 'objects'; WORKSPACE = FF
eval_dir = FF / 'evaluations' / report_id / 'self_quant_analyzer'
eval_dir.mkdir(parents=True, exist_ok=True)

# ── load factor values + daily returns ────────────────────────────────────────
factor_df, signal_col, factor_id = (None,)*3
from factor_factory.data_access import load_factor_values_with_signal
factor_df, signal_col, factor_id = load_factor_values_with_signal(report_id)
factor_df = factor_df.rename(columns={'ts_code':'code'}).copy()
factor_df['td'] = factor_df['trade_date'].dt.strftime('%Y%m%d')

daily_ret = load_daily_snapshot(report_id, columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1
)
daily_ret['_td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d')

merged = factor_df[['code','trade_date','td',signal_col]].merge(
    daily_ret[['code','_td','future_return_1d']],
    left_on=['code','td'], right_on=['code','_td'], how='left'
)
merged = merged.rename(columns={'trade_date_x':'trade_date'})
merged = merged.dropna(subset=[signal_col,'future_return_1d'])
print(f'Merged rows={len(merged)}')

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
    r = v.rank(method='first')
    return pd.qcut(r, q=n, labels=False, duplicates='drop') + 1

def quantile_nav_stats(merged_df, sig):
    work = merged_df[['td', sig, 'future_return_1d']].copy()
    work['g'] = work.groupby('td')[sig].transform(lambda s: assign_labels(s, groups=10))
    src = work.dropna(subset=['g','future_return_1d']).assign(g=lambda df: df['g'].astype(int))
    grp = src.groupby(['td','g'])['future_return_1d'].mean().unstack('g').sort_index()
    grp.index = pd.to_datetime(grp.index.astype(str), format='%Y%m%d'); grp.index.name = 'datetime'
    grp = grp.sort_index()
    grp.columns = [f'G{int(c):02d}' for c in grp.columns]
    nav = (1.0 + grp.fillna(0.0)).cumprod()
    top_g = grp.iloc[:,-1]; bot_g = grp.iloc[:,0]
    ls = (top_g - bot_g).dropna()
    return grp, nav, top_g, bot_g, ls

# ═══════════════════════════════════════════════════════════════════
# TEST 1: Sign-flip — remove -1 sign
# ═══════════════════════════════════════════════════════════════════
print('\n=== TEST 1: Sign-Flip ===')
sig_raw = signal_col
sig_flip = 'alpha004_flip_zscore'
merged[sig_flip] = -merged[sig_raw]   # flip the sign

grp_flip, nav_flip, top_flip, bot_flip, ls_flip = quantile_nav_stats(merged, sig_flip)
ic_flip = merged.dropna(subset=[sig_flip,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig_flip].corr(df['future_return_1d'], method='spearman'), include_groups=False)
ic_flip.index = pd.to_datetime(ic_flip.index.astype(str), format='%Y%m%d')
flip_stats = series_stats(ic_flip)
print(f'Sign-flip: rank_ic_mean={flip_stats["mean"]}  ir={flip_stats["ir"]}')
print(f'  top_decile={sf(top_flip.mean())}  bottom_decile={sf(bot_flip.mean())}')

# ═══════════════════════════════════════════════════════════════════
# TEST 2: Mcap Neutralization
# ═══════════════════════════════════════════════════════════════════
print('\n=== TEST 2: Mcap Neutralization ===')
db_root = Path('/Users/humphrey/.qlib/raw_tushare/行情数据/daily_basic_incremental')
db_parts = sorted(db_root.glob('trade_date=*/daily_basic_*.csv'))
db_dfs = [pd.read_csv(p, usecols=['ts_code','trade_date','close','free_share']) for p in db_parts]
db = pd.concat(db_dfs, ignore_index=True)
db = db.rename(columns={'ts_code':'code','close':'close_db'})
db['mcap'] = db['free_share'] * db['close_db']
db['ln_mcap'] = np.log(db['mcap'].clip(lower=1))
db = db[['code','trade_date','ln_mcap']].dropna(subset=['ln_mcap'])
db['_td'] = pd.to_datetime(db['trade_date']).dt.strftime('%Y%m%d')
print(f'  daily_basic rows={len(db)}')

merged_m = merged.merge(db[['code','_td','ln_mcap']], on=['code','_td'], how='left')
print(f'  merged with mcap rows={len(merged_m)}  ln_mcap null={merged_m["ln_mcap"].isna().sum()}')

def neutralize_cs(group, sig):
    valid = group.dropna(subset=[sig,'ln_mcap'])
    if len(valid) < 10: return group[sig]
    X = np.column_stack([np.ones(len(valid)), valid['ln_mcap'].values])
    y = valid[sig].values
    try:
        XtX = X.T @ X
        beta = np.linalg.inv(XtX + np.eye(2)*1e-8) @ (X.T @ y)
        resid = y - X @ beta
        group[sig + '_raw'] = group[sig]
        group.loc[valid.index, sig] = resid
    except:
        group[sig + '_raw'] = group[sig]
    return group[sig]

merged_m = merged_m.sort_values(['td','code'])
merged_m[sig_raw + '_raw'] = merged_m[sig_raw].copy()
merged_m[sig_raw] = merged_m.groupby('td', sort=False).apply(
    lambda g: neutralize_cs(g.copy(), sig_raw), include_groups=False).droplevel(0).reindex(merged_m.index)

grp_neu, nav_neu, top_neu, bot_neu, ls_neu = quantile_nav_stats(merged_m, sig_raw)
ic_neu = merged_m.dropna(subset=[sig_raw,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig_raw].corr(df['future_return_1d'], method='spearman'), include_groups=False)
ic_neu.index = pd.to_datetime(ic_neu.index.astype(str), format='%Y%m%d')
neu_stats = series_stats(ic_neu)
print(f'Mcap neutral: rank_ic_mean={neu_stats["mean"]}  ir={neu_stats["ir"]}')
print(f'  top_decile={sf(top_neu.mean())}  bottom_decile={sf(bot_neu.mean())}')

# ═══════════════════════════════════════════════════════════════════
# Compare all three
# ═══════════════════════════════════════════════════════════════════
grp_raw, nav_raw, top_raw, bot_raw, ls_raw = quantile_nav_stats(merged, sig_raw)
ic_raw = merged.dropna(subset=[sig_raw,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig_raw].corr(df['future_return_1d'], method='spearman'), include_groups=False)
ic_raw.index = pd.to_datetime(ic_raw.index.astype(str), format='%Y%m%d')
raw_stats = series_stats(ic_raw)

print('\n=== Comparison: Raw vs Sign-Flip vs Mcap-Neutral ===')
print(f'{"Metric":<28} {"Raw":>12} {"SignFlip":>12} {"McapNeut":>12}')
print('-'*66)
for k,label in [('rank_ic_mean','Rank IC'),('rank_ic_ir','Rank IC IR'),
                ('ls_spread_mean','LS Mean'),('ls_spread_ir','LS IR'),
                ('top_decile_mean','Top Dec ret'),('bottom_decile_mean','Bot Dec ret')]:
    r = {'rank_ic_mean': raw_stats['mean'], 'rank_ic_ir': raw_stats['ir'],
         'ls_spread_mean': sf(ls_raw.mean()), 'ls_spread_ir': sf(ls_raw.mean()/ls_raw.std()) if not ls_raw.empty else None,
         'top_decile_mean': sf(top_raw.mean()), 'bottom_decile_mean': sf(bot_raw.mean())}[k]
    f = {'rank_ic_mean': flip_stats['mean'], 'rank_ic_ir': flip_stats['ir'],
         'ls_spread_mean': sf(ls_flip.mean()), 'ls_spread_ir': sf(ls_flip.mean()/ls_flip.std()) if not ls_flip.empty else None,
         'top_decile_mean': sf(top_flip.mean()), 'bottom_decile_mean': sf(bot_flip.mean())}[k]
    n = {'rank_ic_mean': neu_stats['mean'], 'rank_ic_ir': neu_stats['ir'],
         'ls_spread_mean': sf(ls_neu.mean()), 'ls_spread_ir': sf(ls_neu.mean()/ls_neu.std()) if not ls_neu.empty else None,
         'top_decile_mean': sf(top_neu.mean()), 'bottom_decile_mean': sf(bot_neu.mean())}[k]
    def fmt(v): return f'{v:.6f}' if v is not None else 'N/A'
    print(f'{label:<28} {fmt(r):>12} {fmt(f):>12} {fmt(n):>12}')

# ── plots ──────────────────────────────────────────────────────────────────────
def plot_nav(nav, path, title):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 5))
    for col in nav.columns: ax.plot(nav.index, nav[col], lw=1.0, label=col)
    ax.set_title(title); ax.set_xlabel('datetime'); ax.set_ylabel('cumulative nav')
    ax.grid(True, alpha=0.3); ax.legend(ncol=2, fontsize=7)
    ax.axhline(1.0, color='black', lw=0.5, ls='--')
    fig.autofmt_xdate(); fig.tight_layout()
    fig.savefig(path, dpi=150); plt.close(fig)

def plot_ic(series, path, title):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(series.index, series.values, lw=1.0, alpha=0.7)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_title(title); ax.set_ylabel('rank_ic'); ax.grid(True, alpha=0.3)
    m = series.mean(); ir = m/series.std() if series.std() else 0
    ax.text(0.02, 0.95, f'mean={m:.4f}  ir={ir:.4f}', transform=ax.transAxes, fontsize=9, va='top')
    fig.autofmt_xdate(); fig.tight_layout()
    fig.savefig(path, dpi=150); plt.close(fig)

plot_nav(nav_raw,  eval_dir/'quantile_nav_10groups__raw.png',         'Alpha004 Raw Quantile NAV')
plot_nav(nav_flip, eval_dir/'quantile_nav_10groups__sign_flip.png',   'Alpha004 Sign-Flip Quantile NAV')
plot_nav(nav_neu,  eval_dir/'quantile_nav_10groups__mcap_neutral.png','Alpha004 Mcap-Neutral Quantile NAV')
plot_ic(ic_raw,  eval_dir/'ic_timeseries__raw.png',         'Alpha004 Raw Rank IC')
plot_ic(ic_flip, eval_dir/'ic_timeseries__sign_flip.png',    'Alpha004 Sign-Flip Rank IC')
plot_ic(ic_neu,  eval_dir/'ic_timeseries__mcap_neutral.png', 'Alpha004 Mcap-Neutral Rank IC')

# ── save summary ───────────────────────────────────────────────────────────────
result = {
    'report_id': report_id,
    'formula': '(-1*Ts_Rank(rank(low),9))',
    'formula_flip': '(+1*Ts_Rank(rank(low),9))',
    'raw': {
        'rank_ic_mean': raw_stats['mean'], 'rank_ic_ir': raw_stats['ir'],
        'ls_spread_mean': sf(ls_raw.mean()), 'ls_spread_ir': sf(ls_raw.mean()/ls_raw.std()) if not ls_raw.empty else None,
        'top_decile_mean': sf(top_raw.mean()), 'bottom_decile_mean': sf(bot_raw.mean()),
    },
    'sign_flip': {
        'rank_ic_mean': flip_stats['mean'], 'rank_ic_ir': flip_stats['ir'],
        'ls_spread_mean': sf(ls_flip.mean()), 'ls_spread_ir': sf(ls_flip.mean()/ls_flip.std()) if not ls_flip.empty else None,
        'top_decile_mean': sf(top_flip.mean()), 'bottom_decile_mean': sf(bot_flip.mean()),
    },
    'mcap_neutral': {
        'rank_ic_mean': neu_stats['mean'], 'rank_ic_ir': neu_stats['ir'],
        'ls_spread_mean': sf(ls_neu.mean()), 'ls_spread_ir': sf(ls_neu.mean()/ls_neu.std()) if not ls_neu.empty else None,
        'top_decile_mean': sf(top_neu.mean()), 'bottom_decile_mean': sf(bot_neu.mean()),
    }
}
res_path = eval_dir / 'iterate_tests_summary.json'
res_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(f'\n[WRITE] {res_path}')
print('\nPlots written to:', eval_dir)
