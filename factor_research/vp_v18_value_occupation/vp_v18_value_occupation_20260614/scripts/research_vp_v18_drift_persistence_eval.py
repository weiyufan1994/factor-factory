#!/usr/bin/env python3
"""
Evaluate V18 value-occupation repair signals with drift and persistence gates.

This is a research-side script. It consumes the P0 state datamart and shared
daily clean layer, then builds composite signals downstream.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = next(
    (
        parent
        for parent in [SCRIPT_DIR, *SCRIPT_DIR.parents]
        if (parent / "factor_research").is_dir() and (parent / ".git").exists()
    ),
    SCRIPT_DIR.parents[2],
)
for path in [
    SCRIPT_DIR,
    REPO_ROOT / "factor_research" / "vp_p0_baseline_20260610" / "scripts",
]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from research_vp_p0_baseline_eval import (
    add_signals,
    add_universe_flags,
    clean_date,
    finite_float,
    load_vp_state,
)


DAILY_COLUMNS = [
    "ts_code",
    "trade_date",
    "close",
    "pre_close",
    "pct_chg",
    "amount",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "total_mv",
    "circ_mv",
    "ln_total_mv",
    "ln_circ_mv",
]

SIGNALS = [
    "v18_repair_base_z",
    "v18_repair_no_break_2d",
    "v18_repair_no_break_3d",
    "v18_repair_mild_drift",
    "v18_repair_persist_mild_drift",
    "v18_repair_drift_score",
    "v18_lower_support_persist_drift",
    "v18_below_cost_persist_drift",
    "v18_repair_downside_guard",
]

BASELINES = [
    "below_cost_depth_score_raw",
    "lower_support_mass",
    "support_minus_overhang",
]

UNIVERSES = ["full", "middle_20_90", "largest_10", "smallest_20"]
PERIODS = ["all", "2016_2020", "2021_2024_0923", "post_20240924"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vp-root", type=Path, required=True)
    parser.add_argument("--daily-clean", type=Path, default=Path("data/clean/daily_clean.parquet"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--min-date-rows", type=int, default=50)
    parser.add_argument("--max-dates", type=int, default=None)
    parser.add_argument("--signals", default=",".join(SIGNALS + BASELINES))
    parser.add_argument("--universes", default=",".join(UNIVERSES))
    return parser.parse_args()


def periods_for_date(date: str) -> list[str]:
    out = ["all"]
    if date <= "20201231":
        out.append("2016_2020")
    elif "20210101" <= date <= "20240923":
        out.append("2021_2024_0923")
    elif date >= "20240924":
        out.append("post_20240924")
    return out


def cs_z(df: pd.DataFrame, col: str) -> pd.Series:
    values = pd.to_numeric(df[col], errors="coerce")
    mean = values.groupby(df["trade_date"]).transform("mean")
    std = values.groupby(df["trade_date"]).transform("std")
    z = (values - mean) / std.replace(0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def load_daily(daily_clean: Path, horizons: list[int]) -> pd.DataFrame:
    pf = pq.ParquetFile(daily_clean)
    columns = [c for c in DAILY_COLUMNS if c in pf.schema_arrow.names]
    daily = pd.read_parquet(daily_clean, columns=columns)
    daily["trade_date"] = daily["trade_date"].map(clean_date)
    numeric_cols = [c for c in columns if c not in {"ts_code", "trade_date"}]
    for col in numeric_cols:
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    grouped_close = daily.groupby("ts_code", sort=False)["close"]
    for horizon in horizons:
        daily[f"fwd_{horizon}d"] = grouped_close.shift(-horizon) / daily["close"] - 1.0
    daily["close_lag1"] = grouped_close.shift(1)
    daily["close_lag3"] = grouped_close.shift(3)
    daily["close_lag5"] = grouped_close.shift(5)
    daily["close_lag20"] = grouped_close.shift(20)
    daily["ret_1d_close"] = daily["close"] / daily["close_lag1"] - 1.0
    daily["abs_ret_1d"] = daily["ret_1d_close"].abs()
    daily["vol_20d"] = daily.groupby("ts_code", sort=False)["ret_1d_close"].rolling(20, min_periods=5).std().reset_index(level=0, drop=True)
    return daily


def add_v18_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    df["below_cost_z"] = cs_z(df, "below_cost_depth_score_raw")
    df["lower_support_z"] = cs_z(df, "lower_support_mass")
    df["upper_overhang_z"] = cs_z(df, "upper_overhang_ratio")
    df["v18_repair_base_z"] = df["below_cost_z"] + df["lower_support_z"]

    for col in ["no_break_gate", "defended_support_gate", "reference_price", "close_lag1", "close_lag3", "close_lag5", "close_lag20"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    grouped = df.groupby("ts_code", sort=False)
    no_break = pd.to_numeric(df["no_break_gate"], errors="coerce").fillna(0.0).gt(0.5)
    df["no_break_bool"] = no_break
    df["no_break_2d_gate"] = grouped["no_break_bool"].transform(lambda s: s.rolling(2, min_periods=2).sum()).eq(2)
    df["no_break_3d_gate"] = grouped["no_break_bool"].transform(lambda s: s.rolling(3, min_periods=3).sum()).eq(3)

    ref = pd.to_numeric(df["reference_price"], errors="coerce")
    df["drift_1d_to_cutoff"] = ref / df["close_lag1"] - 1.0
    df["mom_3d_to_cutoff"] = ref / df["close_lag3"] - 1.0
    df["mom_5d_to_cutoff"] = ref / df["close_lag5"] - 1.0
    df["mom_20d_to_cutoff"] = ref / df["close_lag20"] - 1.0
    df["mom_3d_z"] = cs_z(df, "mom_3d_to_cutoff")
    df["mom_20d_z"] = cs_z(df, "mom_20d_to_cutoff")
    df["turnover_z"] = cs_z(df, "turnover_rate") if "turnover_rate" in df.columns else 0.0
    df["vol_20d_z"] = cs_z(df, "vol_20d") if "vol_20d" in df.columns else 0.0

    mild_drift = (
        df["mom_3d_to_cutoff"].gt(0.0)
        & df["drift_1d_to_cutoff"].gt(-0.02)
        & df["mom_20d_to_cutoff"].lt(0.30)
    )
    downside_guard = (
        df["mom_3d_to_cutoff"].gt(-0.08)
        & df["drift_1d_to_cutoff"].gt(-0.035)
        & pd.to_numeric(df.get("downside_lvn_gap", 0.0), errors="coerce").fillna(0.0).lt(0.08)
    )
    df["mild_drift_gate"] = mild_drift
    df["downside_guard_gate"] = downside_guard

    base = df["v18_repair_base_z"].fillna(0.0)
    df["v18_repair_no_break_2d"] = base.where(df["no_break_2d_gate"], -2.0)
    df["v18_repair_no_break_3d"] = base.where(df["no_break_3d_gate"], -2.0)
    df["v18_repair_mild_drift"] = base.where(df["mild_drift_gate"], -2.0)
    df["v18_repair_persist_mild_drift"] = base.where(df["no_break_2d_gate"] & df["mild_drift_gate"], -2.0)
    df["v18_repair_drift_score"] = base + 0.35 * df["mom_3d_z"].fillna(0.0) - 0.25 * df["vol_20d_z"].fillna(0.0)
    df["v18_lower_support_persist_drift"] = df["lower_support_z"].where(df["no_break_2d_gate"] & df["mild_drift_gate"], -2.0)
    df["v18_below_cost_persist_drift"] = df["below_cost_z"].where(df["no_break_2d_gate"] & df["mild_drift_gate"], -2.0)
    df["v18_repair_downside_guard"] = base.where(df["downside_guard_gate"], -2.0)
    return df


def spearman_fast(signal: pd.Series, ret: pd.Series) -> float:
    sub = pd.DataFrame({"signal": signal, "ret": ret}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(sub) < 20 or sub["signal"].nunique(dropna=True) < 2 or sub["ret"].nunique(dropna=True) < 2:
        return np.nan
    return float(sub["signal"].rank().corr(sub["ret"].rank()))


def residual_corr(group: pd.DataFrame, signal: str, ret_col: str, controls: list[str]) -> float:
    cols = [signal, ret_col] + controls
    sub = group[cols].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sub) < 60 or sub[signal].nunique(dropna=True) < 2 or sub[ret_col].nunique(dropna=True) < 2:
        return np.nan
    x = sub[controls].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    y_signal = sub[signal].to_numpy(dtype=float)
    y_ret = sub[ret_col].to_numpy(dtype=float)
    try:
        beta_s = np.linalg.lstsq(x, y_signal, rcond=None)[0]
        beta_r = np.linalg.lstsq(x, y_ret, rcond=None)[0]
    except np.linalg.LinAlgError:
        return np.nan
    rs = y_signal - x @ beta_s
    rr = y_ret - x @ beta_r
    if np.nanstd(rs) == 0 or np.nanstd(rr) == 0:
        return np.nan
    return float(np.corrcoef(rs, rr)[0, 1])


def top_stats(group: pd.DataFrame, signal: str, ret_col: str, controls: list[str]) -> tuple[dict[str, float], set[str]]:
    needed = [signal, ret_col, "ts_code"] + controls
    values = group[needed].replace([np.inf, -np.inf], np.nan).dropna(subset=[signal, ret_col, "ts_code"])
    if len(values) < 20:
        return {}, set()
    top_cutoff = values[signal].quantile(0.9)
    bottom_cutoff = values[signal].quantile(0.1)
    top = values[values[signal] >= top_cutoff]
    bottom = values[values[signal] <= bottom_cutoff]
    if top.empty or bottom.empty:
        return {}, set()
    universe_return = float(values[ret_col].mean())
    top_return = float(top[ret_col].mean())
    bottom_return = float(bottom[ret_col].mean())
    stats = {
        "row_count": float(len(values)),
        "rank_ic": spearman_fast(values[signal], values[ret_col]),
        "residual_ic": residual_corr(values, signal, ret_col, controls),
        "top_return": top_return,
        "universe_return": universe_return,
        "top_excess": top_return - universe_return,
        "top_bottom_spread": top_return - bottom_return,
        "top_hit": float(top_return > universe_return),
        "top_gate_rate": float((top[signal] > -1.999).mean()),
    }
    return stats, set(top["ts_code"].astype(str))


def mean_turnover(top_sets: dict[str, set[str]]) -> float | None:
    prev: set[str] | None = None
    turnovers: list[float] = []
    for _, cur in sorted(top_sets.items()):
        if prev:
            turnovers.append(1.0 - len(prev & cur) / len(prev))
        prev = cur
    return None if not turnovers else float(np.mean(turnovers))


def aggregate(daily_rows: list[dict[str, object]], top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]], cost_bps: float) -> pd.DataFrame:
    rows = pd.DataFrame(daily_rows)
    out: list[dict[str, object]] = []
    if rows.empty:
        return rows
    for key, group in rows.groupby(["signal", "universe", "horizon", "period"], sort=True):
        signal, universe, horizon, period = key
        ic = pd.to_numeric(group["rank_ic"], errors="coerce").dropna()
        ric = pd.to_numeric(group["residual_ic"], errors="coerce").dropna()
        turnover = mean_turnover(top_sets.get(key, {}))
        top_excess = float(group["top_excess"].mean())
        cost = None if turnover is None else turnover * cost_bps / 10000.0
        ic_mean = None if ic.empty else float(ic.mean())
        ic_std = None if len(ic) < 2 else float(ic.std(ddof=1))
        ric_mean = None if ric.empty else float(ric.mean())
        ric_std = None if len(ric) < 2 else float(ric.std(ddof=1))
        out.append(
            {
                "signal": signal,
                "universe": universe,
                "horizon": int(horizon),
                "period": period,
                "date_count": int(group["trade_date"].nunique()),
                "row_count": int(group["row_count"].sum()),
                "rank_ic_mean": finite_float(ic_mean),
                "rank_ic_ir": finite_float(None if ic_mean is None or not ic_std else ic_mean / ic_std),
                "rank_ic_positive_rate": finite_float(None if ic.empty else float((ic > 0).mean())),
                "residual_ic_mean": finite_float(ric_mean),
                "residual_ic_ir": finite_float(None if ric_mean is None or not ric_std else ric_mean / ric_std),
                "top_decile_excess_mean": finite_float(top_excess),
                "top_decile_return_mean": finite_float(group["top_return"].mean()),
                "universe_return_mean": finite_float(group["universe_return"].mean()),
                "top_bottom_spread_mean": finite_float(group["top_bottom_spread"].mean()),
                "top_decile_hit_rate": finite_float(group["top_hit"].mean()),
                "top_decile_turnover_mean": finite_float(turnover),
                "net_top_decile_excess_mean": finite_float(None if cost is None else top_excess - cost),
                "top_gate_rate_mean": finite_float(group["top_gate_rate"].mean()),
            }
        )
    return pd.DataFrame(out)


def write_simple_markdown(metrics: pd.DataFrame, path: Path) -> None:
    cols = [
        "signal",
        "universe",
        "horizon",
        "date_count",
        "rank_ic_mean",
        "residual_ic_mean",
        "top_decile_excess_mean",
        "top_decile_turnover_mean",
        "net_top_decile_excess_mean",
    ]
    sub = metrics[metrics["period"].eq("all")][cols].sort_values(["universe", "horizon", "rank_ic_mean"], ascending=[True, True, False])
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in sub.iterrows():
        vals = []
        for col in cols:
            value = row[col]
            if isinstance(value, float):
                vals.append(f"{value:.6f}")
            else:
                vals.append(str(value))
        lines.append("| " + " | ".join(vals) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip()]
    signals = [x.strip() for x in args.signals.split(",") if x.strip()]
    universes = [x.strip() for x in args.universes.split(",") if x.strip()]

    print(f"[LOAD] VP state from {args.vp_root}", flush=True)
    vp = load_vp_state(args.vp_root, args.start_date, args.end_date, args.max_dates)
    print(f"[LOAD] VP rows={len(vp):,} dates={vp['trade_date'].nunique():,}", flush=True)
    print(f"[LOAD] daily clean from {args.daily_clean}", flush=True)
    daily = load_daily(args.daily_clean, horizons)
    daily_cols = [
        "ts_code",
        "trade_date",
        "total_mv",
        "circ_mv",
        "ln_total_mv",
        "ln_circ_mv",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "amount",
        "vol_20d",
        "close_lag1",
        "close_lag3",
        "close_lag5",
        "close_lag20",
    ] + [f"fwd_{h}d" for h in horizons]
    daily_cols = [c for c in daily_cols if c in daily.columns]
    merged = vp.merge(daily[daily_cols], on=["ts_code", "trade_date"], how="inner")
    merged = add_universe_flags(add_signals(merged))
    merged = add_v18_features(merged)
    controls = [
        "ln_total_mv",
        "drift_1d_to_cutoff",
        "mom_5d_to_cutoff",
        "mom_20d_to_cutoff",
        "turnover_rate",
        "vol_20d",
    ]
    controls = [c for c in controls if c in merged.columns]
    print(
        f"[MERGE] rows={len(merged):,} dates={merged['trade_date'].nunique():,} "
        f"tickers={merged['ts_code'].nunique():,} controls={controls}",
        flush=True,
    )

    daily_rows: list[dict[str, object]] = []
    top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]] = defaultdict(dict)
    for idx, (date, day) in enumerate(merged.groupby("trade_date", sort=True), start=1):
        if idx % 250 == 0:
            print(f"[PROGRESS] processed_dates={idx}", flush=True)
        day_periods = periods_for_date(str(date))
        for universe in universes:
            universe_col = f"universe_{universe}"
            if universe_col not in day.columns:
                continue
            base = day[day[universe_col]]
            if len(base) < args.min_date_rows:
                continue
            for horizon in horizons:
                ret_col = f"fwd_{horizon}d"
                if ret_col not in base.columns:
                    continue
                ret_valid = base[base[ret_col].notna()]
                if len(ret_valid) < args.min_date_rows:
                    continue
                for signal in signals:
                    if signal not in ret_valid.columns:
                        continue
                    stats, top = top_stats(ret_valid, signal, ret_col, controls)
                    if not stats:
                        continue
                    for period in day_periods:
                        key = (signal, universe, horizon, period)
                        top_sets[key][str(date)] = top
                        daily_rows.append(
                            {
                                "trade_date": str(date),
                                "signal": signal,
                                "universe": universe,
                                "horizon": horizon,
                                "period": period,
                                **stats,
                            }
                        )

    metrics = aggregate(daily_rows, top_sets, args.cost_bps)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_csv = output_dir / "vp_v18_drift_persistence_metrics.csv"
    summary_json = output_dir / "vp_v18_drift_persistence_summary.json"
    metrics.to_csv(metrics_csv, index=False)
    meta = {
        "vp_root": str(args.vp_root),
        "daily_clean": str(args.daily_clean),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "horizons": horizons,
        "cost_bps": args.cost_bps,
        "signals": signals,
        "universes": universes,
        "controls": controls,
        "vp_rows": int(len(vp)),
        "merged_rows": int(len(merged)),
        "merged_date_count": int(merged["trade_date"].nunique()),
        "merged_ticker_count": int(merged["ts_code"].nunique()),
    }
    summary_json.write_text(json.dumps({"meta": meta, "metrics": metrics.where(pd.notna(metrics), None).to_dict(orient="records")}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_simple_markdown(metrics, output_dir / "vp_v18_drift_persistence_all_period.md")
    print(f"[OK] wrote {metrics_csv}", flush=True)
    print(f"[OK] wrote {summary_json}", flush=True)


if __name__ == "__main__":
    main()
