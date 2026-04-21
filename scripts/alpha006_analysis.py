#!/usr/bin/env python3
"""Alpha006: (-1 * correlation(open, volume, 10))"""
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

report_id = 'ALPHA006_PAPER_20160101_20250711'
FF = Path('/Users/humphrey/projects/factor-factory')
RUNS = FF / 'runs'
eval_dir = FF / 'evaluations' / report_id / 'self_quant_analyzer'
eval_dir.mkdir(parents=True, exist_ok=True)

daily_df = pd.read_csv(
    RUNS / 'ALPHA004_PAPER_20160101_20250711' / 'step3a_local_inputs' /
    f'daily_input__ALPHA004_PAPER_20160101_20250711.csv',
    parse_dates=['trade_date']
).sort_values(['trade_date','ts_code']).reset_index(drop=True)
daily_df['td'] = daily_df['trade_date'].dt.strftime('%Y%m%d').astype(int)
print(f'Daily: {len(daily_df):,}')

daily_df = daily_df.sort_values(['ts_code','td']).reset_index(drop=True)
tickers = daily_df['ts_code'].values
ticker_changes = np.concatenate([[0], np.where(tickers[:-1] != tickers[1:])[0] + 1, [len(tickers)]])
n_tk = len(ticker_changes) - 1

# ── Alpha006: -corr(open, volume, 10) ──────────────────────────────────────────
# Rolling 10-day Pearson correlation between open and volume per ticker
open_arr = daily_df['open'].values.astype(float)
vol_arr  = daily_df['vol'].values.astype(float)

print('Computing rolling corr(open, volume, 10) ...')
corr_res = np.full(len(daily_df), np.nan, dtype=float)
for k in range(n_tk):
    s, e = ticker_changes[k], ticker_changes[k+1]
    o = open_arr[s:e]
    v = vol_arr[s:e]
    n = len(o)
    res = np.full(n, np.nan, dtype=float)
    win = 10
    for i in range(win - 1, n):
        o_win = o[i - win + 1:i + 1]
        v_win = v[i - win + 1:i + 1]
        if np.isnan(o_win).any() or np.isnan(v_win).any():
            continue
        o_m, v_m = o_win.mean(), v_win.mean()
        o_c = o_win - o_m; v_c = v_win - v_m
        num = (o_c * v_c).sum()
        den = np.sqrt((o_c * o_c).sum() * (v_c * v_c).sum())
        res[i] = num / den if den != 0 else 0.0
    corr_res[s:e] = res

daily_df['corr_open_vol'] = corr_res
daily_df['alpha006_z'] = -daily_df['corr_open_vol']   # negative so high = low correlation
daily_df['alpha006_z'] = daily_df.groupby('td')['alpha006_z'].transform(
    lambda x: (x - x.mean()) / (x.std() + 1e-9))

print('Signal built.')

# Load returns
daily_ret = load_daily_snapshot('ALPHA004_PAPER_20160101_20250711',
    columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1)
daily_ret['td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d').astype(int)

factor_df = daily_df[['ts_code','trade_date','td','alpha006_z']].dropna(subset=['alpha006_z']).copy()
factor_df = factor_df.rename(columns={'ts_code':'code'})
merged = factor_df.merge(
    daily_ret[['code','td','future_return_1d']], on=['code','td'], how='left').dropna()
print(f'Merged rows={len(merged):,}')

# ── helpers ─────────────────────────────────────────────────────────────────────
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
    ls = (grp.iloc[:,-1] - grp.iloc[:,0]).dropna()
    return grp, nav, ls

sig = 'alpha006_z'
ic = merged.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig].corr(df['future_return_1d'], method='spearman'), include_groups=False)
ic.index = pd.to_datetime(ic.index.astype(str), format='%Y%m%d')
st = series_stats(ic)

pic = merged.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig].corr(df['future_return_1d'], method='pearson'), include_groups=False)
pic.index = pd.to_datetime(pic.index.astype(str), format='%Y%m%d')
pst = series_stats(pic)

grp, nav, ls = quantile_nav(merged, sig)
g01 = grp.iloc[:,0].mean(); g10 = grp.iloc[:,-1].mean()
ls_mean = ls.mean(); ls_ir = ls_mean / ls.std() if ls.std() > 0 else 0

results = {
    'formula': '(-1 * correlation(open, volume, 10))',
    'rank_ic_mean': st['mean'], 'rank_ic_ir': st['ir'],
    'pearson_ic_mean': pst['mean'], 'pearson_ic_ir': pst['ir'],
    'ls_spread_mean': sf(ls_mean), 'ls_spread_ir': sf(ls_ir),
    'g01_mean': g01, 'g10_mean': g10,
}

print(f'\n=== Alpha006 Results ===')
print(f'  Formula: (-1 * corr(open, volume, 10))')
print(f'  rank_ic={st["mean"]:.5f}, ir={st["ir"]:.4f}')
print(f'  pearson_ic={pst["mean"]:.5f}, ir={pst["ir"]:.4f}')
print(f'  LS spread={ls_mean*100:.4f}%/day, LS_IR={ls_ir:.4f}')
print(f'  G01={g01*100:.4f}%, G10={g10*100:.4f}%')

# Plots
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
ax = axes[0]
ax.plot(ic.index, ic.values, lw=0.8, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
ax.set_title(f'Alpha006 Rank IC  ir={st["ir"]:.4f}'); ax.grid(True, alpha=0.3)
ax.text(0.02, 0.95, f'mean={st["mean"]:.4f}  ir={st["ir"]:.4f}', transform=ax.transAxes, fontsize=8, va='top')
ax = axes[1]
for col in nav.columns: ax.plot(nav.index, nav[col], lw=1.0, label=col)
ax.set_title('Alpha006 Quantile NAV'); ax.axhline(1.0, color='black', lw=0.5, ls='--')
ax.grid(True, alpha=0.3); ax.legend(ncol=2, fontsize=7)
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig(eval_dir / 'quantile_nav__alpha006.png', dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(ic.index, ic.values, lw=0.8, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
ax.set_title(f'Alpha006 Rank IC  ir={st["ir"]:.4f}'); ax.grid(True, alpha=0.3)
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig(eval_dir / 'rank_ic__alpha006.png', dpi=150); plt.close(fig)

grp.to_csv(eval_dir / 'quantile_returns__alpha006.csv')
nav.to_csv(eval_dir / 'quantile_nav__alpha006.csv')

summary_path = eval_dir / 'factor_summary.json'
summary_path.write_text(json.dumps({'report_id': report_id, 'factor': 'Alpha006', 'results': results}, ensure_ascii=False, indent=2))
print(f'\n[WRITE] {summary_path}')
