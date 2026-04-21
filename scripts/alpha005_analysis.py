#!/usr/bin/env python3
"""Alpha005 analysis — WorldQuant Alpha101 #5."""
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

report_id = 'ALPHA005_PAPER_20160101_20250711'
FF = Path('/Users/humphrey/projects/factor-factory')
RUNS = FF / 'runs'; OBJ = FF / 'objects'
eval_dir = FF / 'evaluations' / report_id / 'self_quant_analyzer'
eval_dir.mkdir(parents=True, exist_ok=True)

# ── load daily ─────────────────────────────────────────────────────────────────
daily_df = pd.read_csv(
    RUNS / 'ALPHA004_PAPER_20160101_20250711' / 'step3a_local_inputs' /
    f'daily_input__ALPHA004_PAPER_20160101_20250711.csv',
    parse_dates=['trade_date']
).sort_values(['trade_date','ts_code']).reset_index(drop=True)
daily_df['td'] = daily_df['trade_date'].dt.strftime('%Y%m%d').astype(int)
print(f'Daily: {len(daily_df):,}')

# ── Alpha005 formula: (-1 * Ts_Rank(rank(delta(Ts_Argmax(SM_9(), 8), 7)), 9)) ───
# SM_9() = close from 9 days ago
# Ts_ArgMax(SM_9, 8) = rolling argmax position over last 8 days of SM_9 values
# delta(Ts_ArgMax, 7) = 7-day change in argmax position
# rank(delta) = cross-sectional rank of delta
# Ts_Rank(rank(delta), 9) = 9-day rolling rank of cross-sectional rank
# Final = -1 * Ts_Rank

daily_df = daily_df.sort_values(['ts_code','td']).reset_index(drop=True)
tickers = daily_df['ts_code'].values
close_arr = daily_df['close'].values.astype(float)
n = len(daily_df)

# Find group boundaries
ticker_changes = np.concatenate([[0], np.where(tickers[:-1] != tickers[1:])[0] + 1, [n]])
n_tickers = len(ticker_changes) - 1
print(f'Tickers: {n_tickers}, Computing Alpha005 ...')

# Step 1: SM_9 = close shifted by 9
# We'll compute this per-ticker: close[t-9] for each valid t
sm9 = np.full(n, np.nan, dtype=float)
for k in range(n_tickers):
    s, e = ticker_changes[k], ticker_changes[k+1]
    c = close_arr[s:e]
    # sm9[t] = close[t-9]
    sm9[s+9:e] = c[:-9]   # shift by 9

print('  SM_9 computed.')

# Step 2: Ts_ArgMax(SM_9, 8) - rolling argmax position within last 8 SM_9 values
# For each day t, look at SM_9[t-7:t+1] (8 values), find argmax position
argmax_pos = np.full(n, np.nan, dtype=float)
window = 8
for k in range(n_tickers):
    s, e = ticker_changes[k], ticker_changes[k+1]
    vals = sm9[s:e]
    res = np.full(len(vals), np.nan, dtype=float)
    for i in range(window - 1, len(vals)):
        win = vals[i - window + 1:i + 1]
        argmax_pos[s + i] = np.argmax(win)   # 0-based position within window

print('  Ts_ArgMax computed.')

# Step 3: delta(argmax_pos, 7) = argmax_pos[t] - argmax_pos[t-7]
delta_argmax = np.full(n, np.nan, dtype=float)
for k in range(n_tickers):
    s, e = ticker_changes[k], ticker_changes[k+1]
    ap = argmax_pos[s:e]
    da = ap - np.roll(ap, 7)
    da[:7] = np.nan
    delta_argmax[s:e] = da

print('  delta(argmax) computed.')

# Step 4: Cross-sectional rank of delta at each date
daily_df['delta_argmax'] = delta_argmax
daily_df['r_delta'] = daily_df.groupby('td')['delta_argmax'].rank(pct=True, method='average')
r_delta = daily_df['r_delta'].values.copy()

print('  Cross-sectional rank computed.')

# Step 5: Ts_Rank(r_delta, 9) per ticker
tsrank_res = np.full(n, np.nan, dtype=float)
for k in range(n_tickers):
    s, e = ticker_changes[k], ticker_changes[k+1]
    vals = r_delta[s:e]
    res = np.full(len(vals), np.nan, dtype=float)
    for i in range(8, len(vals)):   # need at least 9 values for tsrank window 9
        win = vals[i - 8:i + 1]      # 9 values, indices 0-8
        last = win[-1]
        res[i] = (win <= last).sum() / 9.0
    tsrank_res[s:e] = res

# Step 6: Final = -1 * Ts_Rank
daily_df['alpha005_raw'] = -tsrank_res

# z-score cross-sectionally
daily_df['alpha005_z'] = daily_df.groupby('td')['alpha005_raw'].transform(
    lambda x: (x - x.mean()) / (x.std() + 1e-9))

print('  Alpha005 signal built.')

# ── load returns ────────────────────────────────────────────────────────────────
daily_ret = load_daily_snapshot('ALPHA004_PAPER_20160101_20250711',
    columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1)
daily_ret['td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d').astype(int)

factor_df = daily_df[['ts_code','trade_date','td','alpha005_z']].dropna(subset=['alpha005_z']).copy()
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

sig = 'alpha005_z'
ic = merged.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig].corr(df['future_return_1d'], method='spearman'), include_groups=False)
ic.index = pd.to_datetime(ic.index.astype(str), format='%Y%m%d')
st = series_stats(ic)

# Pearson IC
pic = merged.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
    lambda df: df[sig].corr(df['future_return_1d'], method='pearson'), include_groups=False)
pic.index = pd.to_datetime(pic.index.astype(str), format='%Y%m%d')
pst = series_stats(pic)

grp, nav, ls = quantile_nav(merged, sig)
g01 = grp.iloc[:,0].mean(); g10 = grp.iloc[:,-1].mean()
ls_mean = ls.mean(); ls_ir = ls_mean / ls.std() if ls.std() > 0 else 0

results = {
    'rank_ic_mean': st['mean'], 'rank_ic_ir': st['ir'],
    'pearson_ic_mean': pst['mean'], 'pearson_ic_ir': pst['ir'],
    'ls_spread_mean': sf(ls_mean), 'ls_spread_ir': sf(ls_ir),
    'g01_mean': g01, 'g10_mean': g10,
}

print(f'\n=== Alpha005 Results ===')
print(f'  Formula: (-1 * Ts_Rank(rank(delta(Ts_ArgMax(close_9d, 8), 7)), 9))')
print(f'  rank_ic={st["mean"]:.5f}, ir={st["ir"]:.4f}')
print(f'  pearson_ic={pst["mean"]:.5f}, ir={pst["ir"]:.4f}')
print(f'  LS spread mean={ls_mean*100:.4f}%/day, LS_IR={ls_ir:.4f}')
print(f'  G01={g01*100:.4f}%, G10={g10*100:.4f}%')

# ── plots ──────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
ax = axes[0]
ax.plot(ic.index, ic.values, lw=0.8, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
ax.set_title(f'Alpha005 Rank IC  ir={st["ir"]:.4f}'); ax.grid(True, alpha=0.3)
ax.text(0.02, 0.95, f'mean={st["mean"]:.4f}  ir={st["ir"]:.4f}', transform=ax.transAxes, fontsize=8, va='top')

ax = axes[1]
for col in nav.columns: ax.plot(nav.index, nav[col], lw=1.0, label=col)
ax.set_title('Alpha005 Quantile NAV'); ax.axhline(1.0, color='black', lw=0.5, ls='--')
ax.grid(True, alpha=0.3); ax.legend(ncol=2, fontsize=7)
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig(eval_dir / 'quantile_nav__alpha005.png', dpi=150); plt.close(fig)

# IC time series
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(ic.index, ic.values, lw=0.8, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
ax.set_title(f'Alpha005 Rank IC  ir={st["ir"]:.4f}'); ax.grid(True, alpha=0.3)
ax.text(0.02, 0.95, f'mean={st["mean"]:.4f}  ir={st["ir"]:.4f}', transform=ax.transAxes, fontsize=8, va='top')
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig(eval_dir / 'rank_ic__alpha005.png', dpi=150); plt.close(fig)

grp.to_csv(eval_dir / 'quantile_returns__alpha005.csv')
nav.to_csv(eval_dir / 'quantile_nav__alpha005.csv')

# ── write summary ────────────────────────────────────────────────────────────────
summary_path = eval_dir / 'factor_summary.json'
summary_path.write_text(json.dumps({'report_id': report_id, 'factor': 'Alpha005', 'results': results}, ensure_ascii=False, indent=2))
print(f'\n[WRITE] {summary_path}')
print(f'[WRITE] {eval_dir}/quantile_nav__alpha005.png')
