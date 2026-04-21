#!/usr/bin/env python3
"""Alpha004 second-wave variants: turnover, mcap+vol combo, low PB."""
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
db = db[['ts_code','td','mcap','r_mcap']].dropna()
daily_df = daily_df.merge(db, on=['ts_code','td'], how='left')

print(f'  mcap null={daily_df["r_mcap"].isna().sum()}')

# ── turnover rate (amount / mcap) ─────────────────────────────────────────────────
# amount in 元, mcap in 元 -> dimensionless ratio
daily_df['turnover'] = daily_df['amount'] / (daily_df['mcap'] + 1e-9)
daily_df['r_turnover'] = daily_df.groupby('td')['turnover'].rank(pct=True, method='average')
print(f'  turnover null={daily_df["r_turnover"].isna().sum()}')

# ── PB from daily_basic ──────────────────────────────────────────────────────
print('Loading PB ...')
pb_dfs = []
for p in db_parts:
    df = pd.read_csv(p, usecols=['ts_code','trade_date','pb'])
    pb_dfs.append(df)
pb = pd.concat(pb_dfs, ignore_index=True).rename(columns={'ts_code':'ts_code','trade_date':'td'}).dropna(subset=['pb'])
pb['r_pb'] = pb.groupby('td')['pb'].rank(pct=True, method='average')
pb = pb[['ts_code','td','r_pb']].dropna()
daily_df = daily_df.merge(pb, on=['ts_code','td'], how='left')
print(f'  pb null={daily_df["r_pb"].isna().sum()}')

# ── fast tsrank via numpy rolling ─────────────────────────────────────────────
def np_tsrank(arr, window):
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    for i in range(window - 1, n):
        win = arr[i - window + 1:i + 1]
        last = win[-1]
        out[i] = (win <= last).sum() / window
    return out

TS = 9

print('Computing tsrank variants ...')
daily_df = daily_df.sort_values(['ts_code','td']).reset_index(drop=True)

for col, outcol in [
    ('r_mcap',    'a_mcap_z'),
    ('r_vol',     'a_vol_z'),
    ('r_turnover','a_turnover_z'),
    ('r_pb',      'a_pb_z'),
]:
    print(f'  {col} -> {outcol} ...')
    vals = daily_df[col].values
    ticker_groups = daily_df['ts_code'].values
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

# Sign: we want to SHORT the "bad" end, so signal is positive when that end is high
# short_low_vol -> high signal = low vol (want low vol)
# So a_vol_z = -tsrank(r_vol) -> high a_vol_z = low vol
for c in ['a_mcap_z','a_vol_z','a_turnover_z','a_pb_z']:
    daily_df[c] = -daily_df[c]
    daily_df[c] = daily_df.groupby('td')[c].transform(lambda x: (x-x.mean())/(x.std()+1e-9))

print('Tsrank done.')

# ── combo: mcap + vol ──────────────────────────────────────────────────────────
# Equal-weight combo of a_mcap_z and a_vol_z
# high combo = small mcap AND/OR low vol
daily_df['a_combo_mcap_vol'] = (daily_df['a_mcap_z'] + daily_df['a_vol_z']) / 2.0
daily_df['a_combo_mcap_vol'] = daily_df.groupby('td')['a_combo_mcap_vol'].transform(
    lambda x: (x-x.mean())/(x.std()+1e-9))

factor_df = daily_df[['ts_code','trade_date','td',
    'a_mcap_z','a_vol_z','a_turnover_z','a_pb_z','a_combo_mcap_vol']].dropna().copy()
factor_df = factor_df.rename(columns={'ts_code':'code'})
print(f'Factor rows={len(factor_df):,}')

# ── load returns + merge ────────────────────────────────────────────────────────
daily_ret = load_daily_snapshot(report_id, columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1
)
daily_ret['td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d').astype(int)

merged = factor_df.merge(
    daily_ret[['code','td','future_return_1d']],
    on=['code','td'], how='left'
).dropna(subset=['future_return_1d'])
print(f'Merged rows={len(merged)}')

# ── helpers ────────────────────────────────────────────────────────────────────
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

# ═══════════════════════════════════════════════════════════════════
variants = [
    ('short_low_turnover',        'a_turnover_z'),
    ('short_low_pb',             'a_pb_z'),
    ('combo_mcap_vol',            'a_combo_mcap_vol'),
]

# Also add the three from first wave for comparison
results_first = {
    'short_low_mcap':    {'rank_ic_mean':0.06938,'rank_ic_ir':0.5203,'ls_spread_ir':0.4575,'top_decile_mean':-4.31e-05,'bottom_decile_mean':-0.00240},
    'short_low_vol':     {'rank_ic_mean':0.05360,'rank_ic_ir':0.6094,'ls_spread_ir':0.4788,'top_decile_mean':0.000321,'bottom_decile_mean':-0.002511},
    'short_low_volstd':  {'rank_ic_mean':0.01443,'rank_ic_ir':0.1783,'ls_spread_ir':0.1305,'top_decile_mean':-0.000300,'bottom_decile_mean':-0.001036},
}
results = {}

for name, sig in variants:
    ic = merged.dropna(subset=[sig,'future_return_1d']).groupby('td', sort=True).apply(
        lambda df: df[sig].corr(df['future_return_1d'], method='spearman'), include_groups=False)
    ic.index = pd.to_datetime(ic.index.astype(str), format='%Y%m%d')
    st = series_stats(ic)
    grp, nav, top_g, bot_g, ls = quantile_nav(merged, sig)

    g01 = grp.iloc[:,0].mean()
    g10 = grp.iloc[:,-1].mean()

    results[name] = {
        'rank_ic_mean': st['mean'], 'rank_ic_ir': st['ir'],
        'ls_spread_mean': sf(ls.mean()),
        'ls_spread_ir': sf(ls.mean()/ls.std()) if not ls.empty else None,
        'top_decile_mean': sf(top_g.mean()),
        'bottom_decile_mean': sf(bot_g.mean()),
        'g01_mean': g01, 'g10_mean': g10,
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
    print(f'  {name}: IC={st["mean"]:.5f}, IR={st["ir"]:.4f}, LS_IR={results[name]["ls_spread_ir"]:.4f}, G01={g01*100:.4f}%, G10={g10*100:.4f}%')

# Merge first wave into results for final table
for k,v in results_first.items():
    results[k] = v

print('\n=== All Variants Comparison (sorted by IC IR) ===')
sorted_results = sorted(results.items(), key=lambda x: x[1]['rank_ic_ir'] if x[1].get('rank_ic_ir') else 0, reverse=True)
print(f'{"Variant":<22} {"Rank IC":>10} {"IC IR":>10} {"LS IR":>10} {"G01%/day":>12} {"G10%/day":>12}')
print('-'*78)
for name, r in sorted_results:
    ic = r.get('rank_ic_mean', 'N/A')
    ir = r.get('rank_ic_ir', 'N/A')
    ls = r.get('ls_spread_ir', 'N/A')
    g01 = r.get('g01_mean', r.get('bottom_decile_mean','N/A'))
    g10 = r.get('g10_mean', r.get('top_decile_mean','N/A'))
    ic_s = f'{ic:.5f}' if isinstance(ic, float) else str(ic)[:10]
    ir_s = f'{ir:.4f}' if isinstance(ir, float) else str(ir)[:10]
    ls_s = f'{ls:.4f}' if isinstance(ls, float) else str(ls)[:10]
    g01_s = f'{g01*100:.4f}' if isinstance(g01, float) else str(g01)[:12]
    g10_s = f'{g10*100:.4f}' if isinstance(g10, float) else str(g10)[:12]
    print(f'{name:<22} {ic_s:>10} {ir_s:>10} {ls_s:>10} {g01_s:>12} {g10_s:>12}')

res_path = eval_dir / 'variant_tests_wave2_summary.json'
res_path.write_text(json.dumps({'variants': results}, ensure_ascii=False, indent=2))
print(f'\n[WRITE] {res_path}')
