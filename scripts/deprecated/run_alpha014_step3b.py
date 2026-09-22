#!/usr/bin/env python3
"""
Step3B for ALPHA014_SOURCE_101
Formula: -rank(delta(pct_chg, 3)) * rolling_corr(open, volume, 10)
Paper: Kakushadze "101 Formulaic Alphas" (2016), Alpha#14

Run: python3 run_alpha014_step3b.py
"""

import os, sys, warnings, json, datetime
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

RUN_DIR  = "/Users/humphrey/projects/factor-factory/factorforge/runs/ALPHA014_SOURCE_101"
OBJ_DIR  = "/Users/humphrey/projects/factor-factory/factorforge/objects"
os.makedirs(RUN_DIR, exist_ok=True)

DATA_PATH = "/Users/humphrey/projects/factor-factory/data/clean/daily_clean.parquet"
FWD_PATH  = "/Users/humphrey/projects/factor-factory/data/clean/daily_forward_returns.parquet"

T_START  = "2016-01-01"
T_END    = "2025-07-11"
CORR_WIN = 10   # rolling correlation window
RET_WIN  = 3    # delta on returns

# ── load ─────────────────────────────────────────────────────────────────────
print("[DATA] Loading daily_clean.parquet …")
df = pd.read_parquet(DATA_PATH, columns=["ts_code","trade_date","open","close","vol","pct_chg"])
df = df.sort_values(["ts_code","trade_date"]).reset_index(drop=True)
df["trade_date"] = pd.to_datetime(df["trade_date"])
df = df[(df["trade_date"] >= T_START) & (df["trade_date"] <= T_END)].copy()

print(f"  rows={len(df):,}  dates={df['trade_date'].nunique()}  stocks={df['ts_code'].nunique()}")

# ── components ───────────────────────────────────────────────────────────────
print("[SIGNAL] Computing alpha components …")

# rolling correlation open vs volume (per stock, 10-day)
def rolling_corr_series(x, y, w):
    return x.rolling(w, min_periods=5).corr(y)

df = df.sort_values(["ts_code","trade_date"])
df["corr_ov10"] = df.groupby("ts_code", group_keys=False).apply(
    lambda g: rolling_corr_series(g["open"], g["vol"], CORR_WIN)
).reset_index(level=0, drop=True)

# delta(pct_chg, 3) = pct_chg_t - pct_chg_{t-3}  (ts_delta, not cross-sectional)
df["delta_ret3"] = df.groupby("ts_code")["pct_chg"].transform(lambda x: x - x.shift(RET_WIN))

# cross-sectional rank of delta_ret3 each date
df["rank_delta_ret3"] = df.groupby("trade_date")["delta_ret3"].rank(pct=True, method="average")

# signal = -rank(delta_ret3) * corr(open, volume, 10)
df["alpha014_factor"] = -df["rank_delta_ret3"] * df["corr_ov10"]

# ── forward returns ─────────────────────────────────────────────────────────
print("[RETURNS] Loading / computing forward returns …")
try:
    fwd = pd.read_parquet(FWD_PATH, columns=["ts_code","trade_date","fwd_ret_1d"])
    print("  forward returns loaded from precomputed parquet")
except Exception:
    print("  computing forward returns on the fly …")
    fwd = (df[["ts_code","trade_date","pct_chg"]]
           .copy()
           .sort_values(["ts_code","trade_date"]))
    fwd["fwd_ret_1d"] = fwd.groupby("ts_code")["pct_chg"].shift(-1)
    fwd = fwd[["ts_code","trade_date","fwd_ret_1d"]]

# ── merge ───────────────────────────────────────────────────────────────────
data = df.merge(fwd, on=["ts_code","trade_date"], how="inner")
# Drop rows with NaN in signal components or forward returns
data = data.dropna(subset=["alpha014_factor","fwd_ret_1d"])
# Also drop inf values (can arise from rank/corr edge cases)
data = data[np.isfinite(data["alpha014_factor"])]
data = data[np.isfinite(data["fwd_ret_1d"])]
data = data[data["fwd_ret_1d"].abs() < 0.30]   # cap extreme returns (avoid 涨跌停板 extremes)
print(f"  signal rows (clean) = {len(data):,}")

# ── IC ──────────────────────────────────────────────────────────────────────
print("[IC] Computing cross-sectional rank IC …")
dates = sorted(data["trade_date"].unique())
rics  = []
for d in dates:
    sub = data[data["trade_date"] == d]
    if len(sub) < 50:
        continue
    r_ic = sub["alpha014_factor"].corr(sub["fwd_ret_1d"], method="spearman")
    p_ic = sub["alpha014_factor"].corr(sub["fwd_ret_1d"], method="pearson")
    rics.append({"trade_date": d, "rank_ic": r_ic, "pearson_ic": p_ic})

ric_df = pd.DataFrame(rics).set_index("trade_date")

rank_ic_mean  = ric_df["rank_ic"].mean()
rank_ic_std   = ric_df["rank_ic"].std()
rank_ic_ir    = rank_ic_mean / rank_ic_std if rank_ic_std > 0 else 0.0
pearson_mean  = ric_df["pearson_ic"].mean()

print(f"  rank_ic_mean  = {rank_ic_mean:.6f}")
print(f"  rank_ic_ir    = {rank_ic_ir:.4f}")
print(f"  pearson_ic    = {pearson_mean:.6f}")

# ── quantile analysis ─────────────────────────────────────────────────────────
print("[QUANTILES] Decile IC & forward returns …")
data["decile"] = data.groupby("trade_date")["alpha014_factor"].transform(
    lambda x: pd.qcut(x, q=10, labels=False, duplicates="drop")
)

grp = (data.groupby(["trade_date","decile"])["fwd_ret_1d"]
       .mean()
       .groupby("decile")
       .agg(["mean","std"])
       .reset_index())
grp.columns = ["decile","avg_ret","std_ret"]
grp["t_stat"] = grp["avg_ret"] / grp["std_ret"] * np.sqrt(grp.index.map(lambda i: dates.__len__()))

# NAV simulation
grp_nav = {}
for d in range(10):
    sub_d = data[data["decile"]==d].copy()
    nav = (1 + sub_d.groupby("trade_date")["fwd_ret_1d"].mean()).cumprod()
    grp_nav[d] = nav.iloc[-1] if len(nav) > 0 else 1.0

print("\n  Decile  Ret(bps/day)   NAV")
for _, row in grp.iterrows():
    d = int(row["decile"])
    print(f"  Q{d+1:02d}    {row['avg_ret']*10000:+.2f}       {grp_nav[d]:.4f}")

# ── save factor values ────────────────────────────────────────────────────────
out = data[["ts_code","trade_date","alpha014_factor","decile","fwd_ret_1d",
            "delta_ret3","rank_delta_ret3","corr_ov10"]].copy()
out["trade_date"] = out["trade_date"].astype(str)
out_path = f"{RUN_DIR}/factor_values__ALPHA014_SOURCE_101.parquet"
out.to_parquet(out_path, index=False)
print(f"\n[SIGNAL] Saved → {out_path}")

# ── summary dict ──────────────────────────────────────────────────────────────
summary = {
    "report_id": "ALPHA014_SOURCE_101",
    "step3b_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    "formula": "-rank(delta(pct_chg, 3)) * rolling_corr(open, volume, 10)",
    "rank_ic_mean": float(rank_ic_mean),
    "rank_ic_ir":   float(rank_ic_ir),
    "pearson_ic_mean": float(pearson_mean),
    "quantile_returns_bps": {f"Q{int(r.decile)+1}": float(r["avg_ret"]*10000) for _, r in grp.iterrows()},
    "quantile_nav": {f"Q{int(k)+1}": float(v) for k, v in grp_nav.items()},
    "n_dates": len(dates),
    "n_stocks_avg": int(len(data)/len(dates)),
    "date_range": [str(dates[0]), str(dates[-1])],
}
with open(f"{RUN_DIR}/step3b_summary__ALPHA014_SOURCE_101.json", "w") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)
print(f"[SUMMARY] Saved → {RUN_DIR}/step3b_summary__ALPHA014_SOURCE_101.json")

# ── handoff ──────────────────────────────────────────────────────────────────
handoff = {
    "report_id": "ALPHA014_SOURCE_101",
    "step3b_completed": True,
    "signal_path": out_path,
    "summary_path": f"{RUN_DIR}/step3b_summary__ALPHA014_SOURCE_101.json",
    "rank_ic_mean": float(rank_ic_mean),
    "rank_ic_ir":   float(rank_ic_ir),
    "pearson_ic_mean": float(pearson_mean),
    "key_findings": "See step3b_summary JSON",
}
with open(f"{OBJ_DIR}/handoff/handoff_to_step4__ALPHA014_SOURCE_101.json", "w") as f:
    json.dump(handoff, f, indent=2, ensure_ascii=False)
print(f"[HANDOFF] → {OBJ_DIR}/handoff/handoff_to_step4__ALPHA014_SOURCE_101.json")
print("\n[DONE] Step3B ALPHA014 complete.")
