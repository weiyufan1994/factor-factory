#!/usr/bin/env python3
"""Alpha007 variants: A=volume_only, B=neutral_else, C=adv60"""
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

# ── load daily ─────────────────────────────────────────────────────────────────
daily_df = pd.read_csv(
    RUNS / 'ALPHA004_PAPER_20160101_20250711' / 'step3a_local_inputs' /
    f'daily_input__ALPHA004_PAPER_20160101_20250711.csv',
    parse_dates=['trade_date']
)
daily_df = daily_df.sort_values(['ts_code','trade_date']).reset_index(drop=True)
daily_df['td'] = daily_df['trade_date'].dt.strftime('%Y%m%d').astype(int)
print(f'Daily: {len(daily_df):,}')

n = len(daily_df)
close_arr = daily_df['close'].values.astype(float)
vol_arr   = daily_df['vol'].values.astype(float)
tickers   = daily_df['ts_code'].values
tc = np.concatenate([[0], np.where(tickers[:-1] != tickers[1:])[0] + 1, [n]])
n_tk = len(tc) - 1

# ── adv20 & adv60 ─────────────────────────────────────────────────────────────
print('Computing adv20 and adv60 ...')
adv20 = np.full(n, np.nan, dtype=float)
adv60 = np.full(n, np.nan, dtype=float)
for k in range(n_tk):
    s, e = tc[k], tc[k+1]
    v = vol_arr[s:e]
    r20 = np.full(len(v), np.nan, dtype=float)
    r60 = np.full(len(v), np.nan, dtype=float)
    for i in range(19, len(v)):
        r20[i] = v[i-19:i+1].mean()
    for i in range(59, len(v)):
        r60[i] = v[i-59:i+1].mean()
    adv20[s:e] = r20
    adv60[s:e] = r60

# ── delta(close, 7) ─────────────────────────────────────────────────────────────
print('Computing delta(close, 7) ...')
delta7 = np.full(n, np.nan, dtype=float)
for k in range(n_tk):
    s, e = tc[k], tc[k+1]
    c = close_arr[s:e]
    d = c - np.roll(c, 7)
    d[:7] = np.nan
    delta7[s:e] = d
abs_delta7 = np.abs(delta7)
sign_delta7 = np.sign(delta7)

# ── ts_rank(abs(delta7), 60) ────────────────────────────────────────────────────
print('Computing ts_rank(abs(delta7), 60) ...')
tsrank_res = np.full(n, np.nan, dtype=float)
for k in range(n_tk):
    s, e = tc[k], tc[k+1]
    vals = abs_delta7[s:e]
    res = np.full(len(vals), np.nan, dtype=float)
    for i in range(59, len(vals)):
        win = vals[i-59:i+1]
        if np.isnan(win).any(): continue
        res[i] = (win <= win[-1]).sum() / 60.0
    tsrank_res[s:e] = res

tsr = tsrank_res
sgn = sign_delta7

# ── Build raw signals ────────────────────────────────────────────────────────────
cond20 = (adv20 < vol_arr).astype(float)  # volume spike vs adv20
cond60 = (adv60 < vol_arr).astype(float)  # volume spike vs adv60

sigA_raw = cond20 * (-tsr * sgn)                      # vol spike only (0 else)
sigB_raw = np.where(cond20 == 1, -tsr * sgn, 0.0)  # neutral else
sigC_raw = np.where(cond60 == 1, -tsr * sgn, 0.0)  # adv60 + neutral else

# ── z-score cross-sectionally ──────────────────────────────────────────────────
print('Z-scoring signals ...')
# Add raw signals to df
daily_df['sigA_raw'] = sigA_raw
daily_df['sigB_raw'] = sigB_raw
daily_df['sigC_raw'] = sigC_raw
daily_df['cond20'] = cond20
daily_df['cond60'] = cond60

# Group by td and zscore
for col in ['sigA_raw', 'sigB_raw', 'sigC_raw']:
    zscore_col = col.replace('_raw', '_z')
    daily_df[zscore_col] = daily_df.groupby('td')[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9))

daily_df['sigA'] = daily_df['sigA_z']
daily_df['sigB'] = daily_df['sigB_z']
daily_df['sigC'] = daily_df['sigC_z']

print(f'  cond20 pct: {cond20.mean():.3%}')
print(f'  cond60 pct: {cond60.mean():.3%}')

# ── load returns ────────────────────────────────────────────────────────────────
daily_ret = load_daily_snapshot('ALPHA004_PAPER_20160101_20250711',
    columns=['ts_code','trade_date','close','pct_chg'])
daily_ret = build_forward_return_frame(
    daily_ret.rename(columns={'ts_code':'code'}),
    instrument_col='code', date_col='trade_date', price_col='close', horizon=1)
daily_ret['td'] = pd.to_datetime(daily_ret['trade_date']).dt.strftime('%Y%m%d').astype(int)

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

def run_variant(name, sig_col, merged_df, formula_desc):
    ic = merged_df.dropna(subset=[sig_col,'future_return_1d']).groupby('td', sort=True).apply(
        lambda df: df[sig_col].corr(df['future_return_1d'], method='spearman'), include_groups=False)
    ic.index = pd.to_datetime(ic.index.astype(str), format='%Y%m%d')
    st = series_stats(ic)
    pic = merged_df.dropna(subset=[sig_col,'future_return_1d']).groupby('td', sort=True).apply(
        lambda df: df[sig_col].corr(df['future_return_1d'], method='pearson'), include_groups=False)
    pic.index = pd.to_datetime(pic.index.astype(str), format='%Y%m%d')
    pst = series_stats(pic)
    grp, nav, ls = quantile_nav(merged_df, sig_col)
    g01 = grp.iloc[:,0].mean(); g10 = grp.iloc[:,-1].mean()
    ls_mean = ls.mean(); ls_ir = ls_mean / ls.std() if ls.std() > 0 else 0

    print(f'\n  === {name} ===')
    print(f'    Formula: {formula_desc}')
    print(f'    rank_ic={st["mean"]:.5f}, ir={st["ir"]:.4f}')
    print(f'    LS spread={ls_mean*100:.4f}%/day, LS_IR={ls_ir:.4f}')
    print(f'    G01={g01*100:.4f}%, G10={g10*100:.4f}%')

    # Decile means
    cols = sorted([c for c in grp.columns], key=lambda x: int(x[1:]))
    print('    Decile:', ' '.join([f'G{i+1:02d}' for i in range(10)]))
    print('    Mean:  ', ' '.join([f'{grp[c].mean()*100:+.3f}%' for c in cols]))

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

    return {
        'formula': formula_desc,
        'rank_ic_mean': st['mean'], 'rank_ic_ir': st['ir'],
        'pearson_ic_mean': pst['mean'], 'pearson_ic_ir': pst['ir'],
        'ls_spread_mean': sf(ls_mean), 'ls_spread_ir': sf(ls_ir),
        'g01_mean': g01, 'g10_mean': g10,
    }

def conditional_ic(merged_df, sig_col, cond_col):
    """Compute IC only when cond_col==1."""
    c = merged_df[cond_col].values
    mask = merged_df[sig_col].notna() & merged_df['future_return_1d'].notna() & (c == 1)
    sub = merged_df.loc[mask]
    if len(sub) < 100:
        return None, None
    ic2 = sub.groupby('td', sort=True).apply(
        lambda df: df[sig_col].corr(df['future_return_1d'], method='spearman'), include_groups=False)
    ic2.index = pd.to_datetime(ic2.index.astype(str), format='%Y%m%d')
    st2 = series_stats(ic2)
    return st2['mean'], st2['ir'], len(ic2)

# ── Run variants ─────────────────────────────────────────────────────────────────
results = {}

variants = [
    ('alpha007_varA_vol_only',      'sigA', 'cond20 * (-tsrank * sign)', 'cond20'),
    ('alpha007_varB_neutral_else',  'sigB', 'where(cond20, -tsrank*sign, 0)', 'cond20'),
    ('alpha007_varC_adv60',         'sigC', 'where(cond60, -tsrank*sign, 0)', 'cond60'),
]

for name, sig_col, formula, cond_col in variants:
    factor_df = daily_df[['ts_code','trade_date','td',sig_col,cond_col]].dropna(subset=[sig_col]).copy()
    factor_df = factor_df.rename(columns={'ts_code':'code'})
    merged = factor_df.merge(
        daily_ret[['code','td','future_return_1d']], on=['code','td'], how='left').dropna()
    print(f'\nVariant {name}: merged rows={len(merged):,}')
    r = run_variant(name, sig_col, merged, formula)
    c_ic, c_ir, c_n = conditional_ic(merged, sig_col, cond_col)
    if c_ic is not None:
        print(f'  Cond IC (vol spike only): IC={c_ic:.5f}, IR={c_ir:.4f}, n_days={c_n}')
        r['cond_ic_mean'] = c_ic
        r['cond_ic_ir'] = c_ir
        r['cond_n_days'] = c_n
    results[name] = r

# ── Summary ─────────────────────────────────────────────────────────────────────
print('\n=== Summary ===')
print(f'{"Variant":<30} {"IC":>8} {"IC IR":>8} {"Cond IC":>10} {"LS IR":>8}')
for name, r in results.items():
    ic = f'{r["rank_ic_mean"]:.5f}'[:8]
    ir = f'{r["rank_ic_ir"]:.4f}'
    cond = f'{r.get("cond_ic_mean","N/A")}'[:10]
    ls = f'{r["ls_spread_ir"]:.4f}'
    print(f'{name:<30} {ic:>8} {ir:>8} {cond:>10} {ls:>8}')

with open(eval_dir / 'variant_summary.json', 'w') as f:
    json.dump({'report_id': report_id, 'results': results}, f, ensure_ascii=False, indent=2)
print(f'\n[WRITE] variant_summary.json')
