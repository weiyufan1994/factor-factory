#!/usr/bin/env python3
"""Alpha007: ((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))"""
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

report_id = 'ALPHA007_PAPER_20160101_20250711'
FF = Path('/Users/humphrey/projects/factor-factory')
RUNS = FF / 'runs'
eval_dir = FF / 'evaluations' / report_id / 'self_quant_analyzer'
eval_dir.mkdir(parents=True, exist_ok=True)

daily_df = pd.read_csv(
    RUNS / 'ALPHA004_PAPER_20160101_20250711' / 'step3a_local_inputs' /
    f'daily_input__ALPHA004_PAPER_20160101_20250711.csv',
    parse_dates=['trade_date']
)
daily_df = daily_df.sort_values(['ts_code','trade_date']).reset_index(drop=True)
daily_df['td'] = daily_df['trade_date'].dt.strftime('%Y%m%d').astype(int)
print(f'Daily: {len(daily_df):,}')

# Build numpy arrays for speed
n = len(daily_df)
close_arr = daily_df['close'].values.astype(float)
vol_arr   = daily_df['vol'].values.astype(float)
tickers   = daily_df['ts_code'].values
ticker_changes = np.concatenate([[0], np.where(tickers[:-1] != tickers[1:])[0] + 1, [n]])
n_tk = len(ticker_changes) - 1

# ── adv20 ─────────────────────────────────────────────────────────────────────
print('Computing adv20 ...')
adv20 = np.full(n, np.nan, dtype=float)
for k in range(n_tk):
    s, e = ticker_changes[k], ticker_changes[k+1]
    v = vol_arr[s:e]
    res = np.full(len(v), np.nan, dtype=float)
    for i in range(19, len(v)):
        res[i] = v[i-19:i+1].mean()
    adv20[s:e] = res

# ── delta(close, 7) ─────────────────────────────────────────────────────────────
print('Computing delta(close, 7) ...')
delta7 = np.full(n, np.nan, dtype=float)
for k in range(n_tk):
    s, e = ticker_changes[k], ticker_changes[k+1]
    c = close_arr[s:e]
    d = c - np.roll(c, 7)
    d[:7] = np.nan
    delta7[s:e] = d

abs_delta7 = np.abs(delta7)
sign_delta7 = np.sign(delta7)

# ── ts_rank(abs(delta7), 60) per ticker ────────────────────────────────────────
print('Computing ts_rank(abs(delta7), 60) ...')
tsrank_res = np.full(n, np.nan, dtype=float)
for k in range(n_tk):
    s, e = ticker_changes[k], ticker_changes[k+1]
    vals = abs_delta7[s:e]
    res = np.full(len(vals), np.nan, dtype=float)
    for i in range(59, len(vals)):
        win = vals[i-59:i+1]
        if np.isnan(win).any(): continue
        last = win[-1]
        res[i] = (win <= last).sum() / 60.0
    tsrank_res[s:e] = res

# ── signal ──────────────────────────────────────────────────────────────────────
print('Building Alpha007 signal ...')
cond = (adv20 < vol_arr).astype(float)   # 1 if volume > adv20
signal = np.where(cond == 1, -tsrank_res * sign_delta7, -1.0)

# Add to df
daily_df['alpha007'] = signal
daily_df['alpha007_z'] = daily_df.groupby('td')['alpha007'].transform(
    lambda x: (x - x.mean()) / (x.std() + 1e-9))
daily_df['cond_volume'] = cond

print(f'  Volume spike pct: {cond.mean():.3%}')

# ── load returns ────────────────────────────────────────────────────────────────
daily_ret = load_daily_snapshot('ALPHA004_PAPER_20160101_20250711',
    columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1)
daily_ret['td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d').astype(int)

factor_df = daily_df[['ts_code','trade_date','td','alpha007_z','cond_volume']].dropna(subset=['alpha007_z']).copy()
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

sig = 'alpha007_z'
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

# Conditional IC: only when volume spike
cond_df = merged[merged['cond_volume'] == 1.0]
cond_ic = cond_df.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig].corr(df['future_return_1d'], method='spearman'), include_groups=False)
cond_ic.index = pd.to_datetime(cond_ic.index.astype(str), format='%Y%m%d')
cst = series_stats(cond_ic)
print(f'\nCond IC (vol spike only): mean={cst["mean"]:.5f}, ir={cst["ir"]:.4f}, n_days={len(cond_ic)}')

results = {
    'formula': '((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))',
    'rank_ic_mean': st['mean'], 'rank_ic_ir': st['ir'],
    'pearson_ic_mean': pst['mean'], 'pearson_ic_ir': pst['ir'],
    'ls_spread_mean': sf(ls_mean), 'ls_spread_ir': sf(ls_ir),
    'g01_mean': g01, 'g10_mean': g10,
    'cond_ic_mean': cst['mean'], 'cond_ic_ir': cst['ir'],
    'volume_spike_pct': float(cond.mean()),
}

print(f'\n=== Alpha007 Results ===')
print(f'  rank_ic={st["mean"]:.5f}, ir={st["ir"]:.4f}')
print(f'  LS spread={ls_mean*100:.4f}%/day, LS_IR={ls_ir:.4f}')
print(f'  G01={g01*100:.4f}%, G10={g10*100:.4f}%')

print('\nDecile means (%/day):')
cols = sorted([c for c in grp.columns], key=lambda x: int(x[1:]))
for i, c in enumerate(cols):
    print(f'  G{i+1:02d}: {grp[c].mean()*100:+.4f}%')

# Plots
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
ax = axes[0]
ax.plot(ic.index, ic.values, lw=0.8, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
ax.set_title(f'Alpha007 Rank IC  ir={st["ir"]:.4f}'); ax.grid(True, alpha=0.3)
ax.text(0.02, 0.95, f'mean={st["mean"]:.4f}  ir={st["ir"]:.4f}', transform=ax.transAxes, fontsize=8, va='top')
ax = axes[1]
for col in nav.columns: ax.plot(nav.index, nav[col], lw=1.0, label=col)
ax.set_title('Alpha007 Quantile NAV'); ax.axhline(1.0, color='black', lw=0.5, ls='--')
ax.grid(True, alpha=0.3); ax.legend(ncol=2, fontsize=7)
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig(eval_dir / 'quantile_nav__alpha007.png', dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(ic.index, ic.values, lw=0.8, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
ax.set_title(f'Alpha007 Rank IC  ir={st["ir"]:.4f}'); ax.grid(True, alpha=0.3)
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig(eval_dir / 'rank_ic__alpha007.png', dpi=150); plt.close(fig)

grp.to_csv(eval_dir / 'quantile_returns__alpha007.csv')
nav.to_csv(eval_dir / 'quantile_nav__alpha007.csv')

summary_path = eval_dir / 'factor_summary.json'
summary_path.write_text(json.dumps({'report_id': report_id, 'factor': 'Alpha007', 'results': results}, ensure_ascii=False, indent=2))
print(f'\n[WRITE] {summary_path}')
