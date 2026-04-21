#!/usr/bin/env python3
"""Alpha004 Wave 3: SIZE+PB blend, combo neutralized, turnover+PB combo."""
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
RUNS = FF / 'runs'
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

# ── mcap, pb from daily_basic ──────────────────────────────────────────────────
db_root = Path('/Users/humphrey/.qlib/raw_tushare/行情数据/daily_basic_incremental')
db_parts = sorted(db_root.glob('trade_date=*/daily_basic_*.csv'))
mcap_list, pb_list = [], []
for p in db_parts:
    df = pd.read_csv(p, usecols=['ts_code','trade_date','close','free_share','pb'])
    df['mcap'] = df['free_share'] * df['close']
    mcap_list.append(df[['ts_code','trade_date','mcap']])
    pb_list.append(df[['ts_code','trade_date','pb']])

mcap = pd.concat(mcap_list, ignore_index=True).rename(columns={'ts_code':'ts_code','trade_date':'td'}).dropna()
pb   = pd.concat(pb_list,   ignore_index=True).rename(columns={'ts_code':'ts_code','trade_date':'td'}).dropna()
daily_df = daily_df.merge(mcap, on=['ts_code','td'], how='left')
daily_df = daily_df.merge(pb,   on=['ts_code','td'], how='left')

# turnover
daily_df['turnover'] = daily_df['amount'] / (daily_df['mcap'] + 1e-9)

# cross-sectional percentile ranks
for col in ['mcap','pb','vol','turnover']:
    daily_df[f'r_{col}'] = daily_df.groupby('td')[col].rank(pct=True, method='average')

# tsrank helper
def np_tsrank(arr, window=9):
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    for i in range(window - 1, n):
        out[i] = (arr[i - window + 1:i + 1] <= arr[i]).sum() / window
    return out

daily_df = daily_df.sort_values(['ts_code','td']).reset_index(drop=True)
tickers = daily_df['ts_code'].values
bdry = np.concatenate([[0], np.where(tickers[:-1] != tickers[1:])[0] + 1, [len(tickers)]])
n_tk = len(bdry) - 1

# tsrank of cross-sectional ranks (for Alpha004-style mutations)
for src_col, out_col in [('r_mcap','ts_mcap'),('r_vol','ts_vol'),('r_turnover','ts_turnover'),('r_pb','ts_pb')]:
    vals = daily_df[src_col].values.astype(float)
    res = np.full(len(vals), np.nan)
    for k in range(n_tk):
        s, e = bdry[k], bdry[k+1]
        if e - s >= 9:
            res[s:e] = np_tsrank(vals[s:e], 9)
    daily_df[out_col] = res

# ── Build signals ───────────────────────────────────────────────────────────────
# Wave3-A: SIZE + PB blend (raw rank, no tsrank)
# small mcap (high r_mcap negated) + low pb (high r_pb negated)
daily_df['sig_SIZE_PB_blend'] = (-daily_df['r_mcap'] + -daily_df['r_pb']) / 2.0

# Wave3-B: combo_mcap_vol neutralized by mcap -> pure vol after removing size effect
daily_df['sig_combo_mv'] = (-daily_df['ts_mcap'] + -daily_df['ts_vol']) / 2.0

# Neutralize sig_combo_mv by r_mcap within each day
def neutralize_col(df, sig_col, neu_col):
    """Day-wise OLS residual: sig ~ neu, return residuals."""
    res = np.full(len(df), np.nan)
    for td, idx in df.groupby('td').groups.items():
        x = df.loc[idx, neu_col].values.astype(float)
        y = df.loc[idx, sig_col].values.astype(float)
        mask = ~(np.isnan(x) | np.isnan(y))
        if mask.sum() < 10:
            continue
        x_m, y_m = x[mask].mean(), y[mask].mean()
        x_c, y_c = x[mask] - x_m, y[mask] - y_m
        b = (x_c * y_c).sum() / ((x_c * x_c).sum() + 1e-9)
        res[idx] = y - b * x
    df_out = df.copy()
    df_out[f'{sig_col}_neu'] = res
    return df_out

print('  Computing combo neutralized by mcap ...')
daily_df = neutralize_col(daily_df, 'sig_combo_mv', 'r_mcap')
daily_df.rename(columns={f'sig_combo_mv_neu': 'sig_combo_mv_neu'}, inplace=True)

# Wave3-C: turnover + PB combo (Alpha004-style)
daily_df['sig_turnover_pb'] = (-daily_df['ts_turnover'] + -daily_df['ts_pb']) / 2.0

# z-score all signals cross-sectionally
for c in ['sig_SIZE_PB_blend','sig_combo_mv','sig_combo_mv_neu','sig_turnover_pb']:
    daily_df[c] = daily_df.groupby('td')[c].transform(lambda x: (x-x.mean())/(x.std()+1e-9))

print('Signals built.')

# ── load returns ────────────────────────────────────────────────────────────────
daily_ret = load_daily_snapshot(report_id, columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1)
daily_ret['td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d').astype(int)

sig_cols = ['sig_SIZE_PB_blend','sig_combo_mv','sig_combo_mv_neu','sig_turnover_pb']
factor_df = daily_df[['ts_code','trade_date','td'] + sig_cols].dropna(subset=sig_cols).copy()
factor_df = factor_df.rename(columns={'ts_code':'code'})
merged = factor_df.merge(
    daily_ret[['code','td','future_return_1d']], on=['code','td'], how='left')
merged = merged.dropna(subset=['future_return_1d'])
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

variants = [
    ('wave3_SIZE_PB_blend',        'sig_SIZE_PB_blend',    '(rank(mcap) + rank(pb)) / 2  [no tsrank]'),
    ('wave3_combo_mv_neutralized', 'sig_combo_mv_neu',     'neutralized((-TsRank(rank(mcap)) + -TsRank(rank(vol))) / 2, rank(mcap))'),
    ('wave3_turnover_pb_combo',     'sig_turnover_pb',      '(-TsRank(rank(turnover)) + -TsRank(rank(pb))) / 2'),
]

results = {}
for name, sig, formula in variants:
    ic = merged.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
        lambda df: df[sig].corr(df['future_return_1d'], method='spearman'), include_groups=False)
    ic.index = pd.to_datetime(ic.index.astype(str), format='%Y%m%d')
    st = series_stats(ic)
    grp, nav, ls = quantile_nav(merged, sig)
    g01 = grp.iloc[:,0].mean(); g10 = grp.iloc[:,-1].mean()
    ls_mean = ls.mean(); ls_ir = ls_mean / ls.std() if ls.std() > 0 else 0
    results[name] = {
        'formula': formula,
        'rank_ic_mean': st['mean'], 'rank_ic_ir': st['ir'],
        'ls_spread_mean': sf(ls_mean), 'ls_spread_ir': sf(ls_ir),
        'g01_mean': g01, 'g10_mean': g10,
    }
    print(f'\n  === {name} ===')
    print(f'    Formula: {formula}')
    print(f'    IC={st["mean"]:.5f}, IR={st["ir"]:.4f}, LS_IR={ls_ir:.4f}')
    print(f'    G01={g01*100:.4f}%, G10={g10*100:.4f}%, Spread={ls_mean*100:.4f}%')

    fig, axes = plt.subplots(1, 2, figsize=(14, 4))
    ax = axes[0]
    ax.plot(ic.index, ic.values, lw=0.8, alpha=0.7); ax.axhline(0, color='black', lw=0.5)
    ax.set_title(f'{name}  ir={st["ir"]:.4f}'); ax.grid(True, alpha=0.3)
    ax.text(0.02, 0.95, f'mean={st["mean"]:.4f}  ir={st["ir"]:.4f}', transform=ax.transAxes, fontsize=8, va='top')
    ax = axes[1]
    for col in nav.columns: ax.plot(nav.index, nav[col], lw=1.0, label=col)
    ax.set_title(f'{name} Quantile NAV'); ax.axhline(1.0, color='black', lw=0.5, ls='--')
    ax.grid(True, alpha=0.3); ax.legend(ncol=2, fontsize=7)
    fig.autofmt_xdate(); fig.tight_layout()
    fig.savefig(eval_dir / f'quantile_nav__{name}.png', dpi=150); plt.close(fig)
    grp.to_csv(eval_dir / f'quantile_returns__{name}.csv')
    nav.to_csv(eval_dir / f'quantile_nav__{name}.csv')

print('\n=== Wave 3 Summary ===')
print(f'{"Variant":<30} {"Formula":<65} {"IC":>8} {"IC IR":>8} {"LS IR":>8}')
for name, r in results.items():
    print(f'{name:<30} {r["formula"]:<65} {r["rank_ic_mean"]:.5f} {r["rank_ic_ir"]:.4f} {r["ls_spread_ir"]:.4f}')

with open(eval_dir / 'variant_tests_wave3_summary.json', 'w') as f:
    json.dump({'variants': results}, f, ensure_ascii=False, indent=2)
print('\n[WRITE] variant_tests_wave3_summary.json')
