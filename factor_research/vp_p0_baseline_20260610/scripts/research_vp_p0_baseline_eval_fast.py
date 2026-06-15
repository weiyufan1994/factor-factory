#!/usr/bin/env python3
"""
Fast evaluator for P0 value-occupation baseline signals.

It keeps the same signal definitions as research_vp_p0_baseline_eval.py, but
computes daily slices in one pass to avoid repeated full-table groupby work.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
import sys
from typing import Iterable

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from research_vp_p0_baseline_eval import (
    add_signals,
    add_universe_flags,
    clean_date,
    finite_float,
    load_daily_with_forward_returns,
    load_vp_state,
)


SIGNALS = [
    "support_minus_overhang",
    "lower_support_mass",
    "upper_overhang_mass_neg",
    "below_cost_depth_raw",
    "below_cost_depth_score_raw",
    "below_cost_guarded_support_p0",
    "support_with_below_cost_cap_p0",
    "defended_support_minus_overhang_p0",
    "support_defense_gap_guard_p0",
    "support_overhang_vacuum_balance_p0",
]

UNIVERSES = ["full", "middle_20_90", "largest_10", "smallest_20"]


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
    return parser.parse_args()


def periods_for_date(date: str) -> list[str]:
    periods = ["all"]
    if date <= "20201231":
        periods.append("2016_2020")
    elif "20210101" <= date <= "20240923":
        periods.append("2021_2024_0923")
    elif date >= "20240924":
        periods.append("post_20240924")
    return periods


def spearman_fast(signal: pd.Series, ret: pd.Series) -> float:
    sub = pd.DataFrame({"signal": signal, "ret": ret}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(sub) < 20:
        return np.nan
    if sub["signal"].nunique(dropna=True) < 2 or sub["ret"].nunique(dropna=True) < 2:
        return np.nan
    return float(sub["signal"].rank().corr(sub["ret"].rank()))


def top_stats(group: pd.DataFrame, signal: str, ret_col: str) -> tuple[dict[str, float], set[str]]:
    values = group[[signal, ret_col, "ts_code"]].replace([np.inf, -np.inf], np.nan).dropna()
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
        "top_return": top_return,
        "universe_return": universe_return,
        "top_excess": top_return - universe_return,
        "top_bottom_spread": top_return - bottom_return,
        "top_hit": float(top_return > universe_return),
    }
    return stats, set(top["ts_code"].astype(str))


def mean_turnover(top_sets: dict[str, set[str]]) -> float | None:
    prev: set[str] | None = None
    turnovers: list[float] = []
    for _, cur in sorted(top_sets.items()):
        if prev:
            turnovers.append(1.0 - len(prev & cur) / len(prev))
        prev = cur
    if not turnovers:
        return None
    return float(np.mean(turnovers))


def aggregate_daily(daily_rows: list[dict[str, object]], top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]], cost_bps: float) -> pd.DataFrame:
    rows = pd.DataFrame(daily_rows)
    out: list[dict[str, object]] = []
    if rows.empty:
        return rows
    group_cols = ["signal", "universe", "horizon", "period"]
    for key, group in rows.groupby(group_cols, sort=True):
        signal, universe, horizon, period = key
        ic = pd.to_numeric(group["rank_ic"], errors="coerce").dropna()
        ic_mean = None if ic.empty else float(ic.mean())
        ic_std = None if len(ic) < 2 else float(ic.std(ddof=1))
        turnover = mean_turnover(top_sets.get(key, {}))
        top_excess = float(group["top_excess"].mean())
        cost = None if turnover is None else turnover * cost_bps / 10000.0
        out.append(
            {
                "signal": signal,
                "universe": universe,
                "horizon": int(horizon),
                "period": period,
                "date_count": int(group["trade_date"].nunique()),
                "row_count": int(group["row_count"].sum()),
                "rank_ic_mean": finite_float(ic_mean),
                "rank_ic_std": finite_float(ic_std),
                "rank_ic_ir": finite_float(None if ic_mean is None or not ic_std else ic_mean / ic_std),
                "rank_ic_positive_rate": finite_float(None if ic.empty else float((ic > 0).mean())),
                "top_decile_excess_mean": finite_float(top_excess),
                "top_decile_return_mean": finite_float(group["top_return"].mean()),
                "universe_return_mean": finite_float(group["universe_return"].mean()),
                "top_bottom_spread_mean": finite_float(group["top_bottom_spread"].mean()),
                "top_decile_hit_rate": finite_float(group["top_hit"].mean()),
                "top_decile_turnover_mean": finite_float(turnover),
                "net_top_decile_excess_mean": finite_float(None if cost is None else top_excess - cost),
            }
        )
    return pd.DataFrame(out)


def write_outputs(metrics_df: pd.DataFrame, output_dir: Path, meta: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_csv = output_dir / "vp_p0_baseline_metrics.csv"
    metrics_json = output_dir / "vp_p0_baseline_summary.json"
    metrics_df.to_csv(metrics_csv, index=False)
    payload = {"meta": meta, "metrics": metrics_df.where(pd.notna(metrics_df), None).to_dict(orient="records")}
    metrics_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact_cols = [
        "signal",
        "universe",
        "horizon",
        "date_count",
        "rank_ic_mean",
        "rank_ic_ir",
        "top_decile_excess_mean",
        "top_bottom_spread_mean",
        "top_decile_turnover_mean",
        "net_top_decile_excess_mean",
    ]
    compact = metrics_df[metrics_df["period"].eq("all")][compact_cols].sort_values(
        ["universe", "horizon", "rank_ic_mean"], ascending=[True, True, False]
    )
    markdown_path = output_dir / "vp_p0_baseline_all_period.md"
    try:
        compact.to_markdown(markdown_path, index=False, floatfmt=".6f")
    except ImportError as exc:
        warning_path = output_dir / "vp_p0_baseline_all_period.md.warning.txt"
        warning_path.write_text(f"optional markdown output skipped: {exc}\n", encoding="utf-8")
    print(f"[OK] wrote {metrics_csv}", flush=True)
    print(f"[OK] wrote {metrics_json}", flush=True)


def main() -> None:
    args = parse_args()
    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip()]
    print(f"[LOAD] VP state from {args.vp_root}", flush=True)
    vp = load_vp_state(args.vp_root, args.start_date, args.end_date, args.max_dates)
    print(f"[LOAD] VP rows={len(vp):,} dates={vp['trade_date'].nunique():,}", flush=True)
    print(f"[LOAD] daily clean from {args.daily_clean}", flush=True)
    daily = load_daily_with_forward_returns(args.daily_clean, horizons)
    daily_needed = ["ts_code", "trade_date", "total_mv", "circ_mv"] + [f"fwd_{h}d" for h in horizons]
    daily_needed = [c for c in daily_needed if c in daily.columns]
    merged = vp.merge(daily[daily_needed], on=["ts_code", "trade_date"], how="inner")
    merged = add_universe_flags(add_signals(merged))
    print(
        f"[MERGE] rows={len(merged):,} dates={merged['trade_date'].nunique():,} "
        f"tickers={merged['ts_code'].nunique():,}",
        flush=True,
    )

    daily_rows: list[dict[str, object]] = []
    top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]] = defaultdict(dict)
    for date, day in merged.groupby("trade_date", sort=True):
        day_periods = periods_for_date(str(date))
        for universe in UNIVERSES:
            universe_col = f"universe_{universe}"
            base = day[day[universe_col]].copy()
            if len(base) < args.min_date_rows:
                continue
            for horizon in horizons:
                ret_col = f"fwd_{horizon}d"
                if ret_col not in base.columns:
                    continue
                ret_valid = base[base[ret_col].notna()].copy()
                if len(ret_valid) < args.min_date_rows:
                    continue
                for signal in SIGNALS:
                    stats, top = top_stats(ret_valid, signal, ret_col)
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

    metrics = aggregate_daily(daily_rows, top_sets, args.cost_bps)
    meta = {
        "vp_root": str(args.vp_root),
        "daily_clean": str(args.daily_clean),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "horizons": horizons,
        "cost_bps": args.cost_bps,
        "max_dates": args.max_dates,
        "vp_rows": int(len(vp)),
        "merged_rows": int(len(merged)),
        "merged_date_count": int(merged["trade_date"].nunique()),
        "merged_ticker_count": int(merged["ts_code"].nunique()),
        "signals": SIGNALS,
        "universes": UNIVERSES,
    }
    write_outputs(metrics, args.output_dir, meta)


if __name__ == "__main__":
    main()
