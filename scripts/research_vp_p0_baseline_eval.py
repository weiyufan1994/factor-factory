#!/usr/bin/env python3
"""
Evaluate P0 value-occupation state variables as baseline alpha candidates.

This script intentionally stays at the research layer: it reads the delivered
intraday_value_occupation_state_v1 state datamart and builds simple composite
signals locally. The datamart must remain state-only.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


VP_COLUMNS = [
    "ts_code",
    "trade_date",
    "cutoff_time",
    "lookback_days",
    "reference_price",
    "vwap_cost",
    "lower_support_ratio",
    "upper_overhang_ratio",
    "below_mass_ratio",
    "above_mass_ratio",
    "below_cost_depth",
    "below_cost_depth_score",
    "downside_lvn_gap",
    "upside_lvn_vacuum",
    "no_break_gate",
    "defended_support_gate",
    "amount_total",
    "minute_count",
]

DAILY_COLUMNS = [
    "ts_code",
    "trade_date",
    "close",
    "pct_chg",
    "total_mv",
    "circ_mv",
    "turnover_rate",
    "volume_ratio",
]


@dataclass(frozen=True)
class MetricRow:
    signal: str
    universe: str
    horizon: int
    period: str
    date_count: int
    row_count: int
    rank_ic_mean: float | None
    rank_ic_std: float | None
    rank_ic_ir: float | None
    rank_ic_positive_rate: float | None
    top_decile_excess_mean: float | None
    top_decile_return_mean: float | None
    universe_return_mean: float | None
    top_bottom_spread_mean: float | None
    top_decile_hit_rate: float | None
    top_decile_turnover_mean: float | None
    net_top_decile_excess_mean: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vp-root", type=Path, required=True, help="Local Hive-partitioned VP datamart root.")
    parser.add_argument("--daily-clean", type=Path, default=Path("data/clean/daily_clean.parquet"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--min-date-rows", type=int, default=50)
    parser.add_argument("--max-dates", type=int, default=None, help="Optional evenly-spaced date cap for smoke runs.")
    return parser.parse_args()


def clean_date(value: object) -> str:
    text = str(value)
    return text[:10].replace("-", "")


def finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def summarize_float(series: pd.Series) -> tuple[float | None, float | None]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None, None
    mean = float(values.mean())
    std = float(values.std(ddof=1)) if len(values) > 1 else None
    return mean, std


def existing_vp_columns(vp_root: Path) -> list[str]:
    parquet_files = sorted(vp_root.glob("trade_date=*/part-*.parquet"))
    if not parquet_files:
        parquet_files = sorted(vp_root.rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"no parquet files found under {vp_root}")
    physical = set(pq.ParquetFile(parquet_files[0]).schema_arrow.names)
    cols = [c for c in VP_COLUMNS if c in physical or c == "trade_date"]
    missing = [c for c in VP_COLUMNS if c not in cols]
    if missing:
        print(f"[WARN] VP columns missing and will be skipped: {missing}")
    return cols


def load_vp_state(vp_root: Path, start_date: str, end_date: str, max_dates: int | None) -> pd.DataFrame:
    columns = existing_vp_columns(vp_root)
    dataset = ds.dataset(vp_root, format="parquet", partitioning="hive")
    field = ds.field("trade_date")
    filter_expr = (field >= int(start_date)) & (field <= int(end_date))
    table = dataset.to_table(columns=columns, filter=filter_expr)
    df = table.to_pandas()
    if "trade_date" not in df.columns:
        raise ValueError("trade_date is absent; expected Hive partition column or physical field")
    df["trade_date"] = df["trade_date"].map(clean_date)
    if max_dates is not None and max_dates > 0:
        dates = sorted(df["trade_date"].unique())
        if len(dates) > max_dates:
            idx = np.linspace(0, len(dates) - 1, max_dates).round().astype(int)
            keep_dates = {dates[i] for i in sorted(set(idx))}
            df = df[df["trade_date"].isin(keep_dates)].copy()
    return df


def load_daily_with_forward_returns(daily_clean: Path, horizons: Iterable[int]) -> pd.DataFrame:
    pf = pq.ParquetFile(daily_clean)
    columns = [c for c in DAILY_COLUMNS if c in pf.schema_arrow.names]
    missing = [c for c in DAILY_COLUMNS if c not in columns]
    if missing:
        print(f"[WARN] daily columns missing and will be skipped: {missing}")
    daily = pd.read_parquet(daily_clean, columns=columns)
    daily["trade_date"] = daily["trade_date"].map(clean_date)
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    grouped = daily.groupby("ts_code", sort=False)["close"]
    for horizon in horizons:
        daily[f"fwd_{horizon}d"] = grouped.shift(-horizon) / daily["close"] - 1.0
    return daily


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "lower_support_ratio",
        "upper_overhang_ratio",
        "below_mass_ratio",
        "above_mass_ratio",
        "below_cost_depth",
        "below_cost_depth_score",
        "downside_lvn_gap",
        "upside_lvn_vacuum",
        "no_break_gate",
        "defended_support_gate",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    lower = df.get("lower_support_ratio", 0.0).fillna(0.0)
    upper = df.get("upper_overhang_ratio", 0.0).fillna(0.0)
    below_score = df.get("below_cost_depth_score", 0.0).fillna(0.0)
    no_break = df.get("no_break_gate", 0.0).fillna(0.0)
    defended = df.get("defended_support_gate", 0.0).fillna(0.0)
    downside_gap = df.get("downside_lvn_gap", 0.0).fillna(0.0)
    upper_vacuum = df.get("upside_lvn_vacuum", 0.0).fillna(0.0)

    df["support_minus_overhang"] = lower - upper
    df["lower_support_mass"] = lower
    df["upper_overhang_mass_neg"] = -upper
    df["below_cost_depth_raw"] = df.get("below_cost_depth", np.nan)
    df["below_cost_depth_score_raw"] = below_score
    df["below_cost_guarded_support_p0"] = below_score * lower * no_break - upper
    df["support_with_below_cost_cap_p0"] = lower * (1.0 + below_score.clip(lower=0.0, upper=2.0)) * no_break - upper
    df["defended_support_minus_overhang_p0"] = lower * no_break * defended - upper
    df["support_defense_gap_guard_p0"] = lower * no_break * defended - upper - downside_gap
    df["support_overhang_vacuum_balance_p0"] = lower + upper_vacuum - upper - downside_gap
    return df


def add_universe_flags(df: pd.DataFrame) -> pd.DataFrame:
    df["total_mv"] = pd.to_numeric(df["total_mv"], errors="coerce")
    df["mcap_pct"] = df.groupby("trade_date")["total_mv"].rank(pct=True)
    df["universe_full"] = df["total_mv"].notna()
    df["universe_middle_20_90"] = df["mcap_pct"].gt(0.20) & df["mcap_pct"].lt(0.90)
    df["universe_largest_10"] = df["mcap_pct"].ge(0.90)
    df["universe_smallest_20"] = df["mcap_pct"].le(0.20)
    return df


def period_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    dates = df["trade_date"]
    return {
        "all": pd.Series(True, index=df.index),
        "2016_2020": dates.le("20201231"),
        "2021_2024_0923": dates.ge("20210101") & dates.le("20240923"),
        "post_20240924": dates.ge("20240924"),
    }


def safe_spearman(group: pd.DataFrame, signal: str, ret_col: str) -> float:
    sub = group[[signal, ret_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sub) < 20:
        return np.nan
    if sub[signal].nunique(dropna=True) < 2 or sub[ret_col].nunique(dropna=True) < 2:
        return np.nan
    return float(sub[signal].rank().corr(sub[ret_col].rank()))


def top_sets_by_date(df: pd.DataFrame, signal: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for date, group in df.groupby("trade_date", sort=True):
        signal_values = group[signal].replace([np.inf, -np.inf], np.nan)
        valid = group[signal_values.notna()]
        if len(valid) < 20:
            continue
        cutoff = valid[signal].quantile(0.9)
        out[date] = set(valid.loc[valid[signal] >= cutoff, "ts_code"].astype(str))
    return out


def mean_top_turnover(top_sets: dict[str, set[str]]) -> float | None:
    turnovers: list[float] = []
    prev: set[str] | None = None
    for _, cur in sorted(top_sets.items()):
        if prev is not None and prev:
            overlap = len(prev & cur)
            turnovers.append(1.0 - overlap / len(prev))
        prev = cur
    if not turnovers:
        return None
    return float(np.mean(turnovers))


def evaluate_one(
    df: pd.DataFrame,
    signal: str,
    universe: str,
    horizon: int,
    period: str,
    cost_bps: float,
    min_date_rows: int,
) -> MetricRow:
    ret_col = f"fwd_{horizon}d"
    universe_col = f"universe_{universe}"
    sub = df.loc[df[universe_col] & df[signal].notna() & df[ret_col].notna(), ["trade_date", "ts_code", signal, ret_col]].copy()
    counts = sub.groupby("trade_date").size()
    valid_dates = counts[counts >= min_date_rows].index
    sub = sub[sub["trade_date"].isin(valid_dates)]
    if sub.empty:
        return MetricRow(signal, universe, horizon, period, 0, 0, *([None] * 10))

    ic_by_date = sub.groupby("trade_date", sort=True).apply(lambda g: safe_spearman(g, signal, ret_col), include_groups=False)
    ic_mean, ic_std = summarize_float(ic_by_date)
    ic_ir = None if ic_mean is None or not ic_std else ic_mean / ic_std
    ic_pos = None if ic_by_date.dropna().empty else float((ic_by_date.dropna() > 0).mean())

    daily_rows = []
    for date, group in sub.groupby("trade_date", sort=True):
        sig = group[signal].replace([np.inf, -np.inf], np.nan)
        group = group[sig.notna()]
        if len(group) < min_date_rows:
            continue
        top_cutoff = group[signal].quantile(0.9)
        bottom_cutoff = group[signal].quantile(0.1)
        top = group[group[signal] >= top_cutoff]
        bottom = group[group[signal] <= bottom_cutoff]
        if top.empty or bottom.empty:
            continue
        uni_ret = float(group[ret_col].mean())
        top_ret = float(top[ret_col].mean())
        bottom_ret = float(bottom[ret_col].mean())
        daily_rows.append(
            {
                "trade_date": date,
                "top_return": top_ret,
                "universe_return": uni_ret,
                "top_excess": top_ret - uni_ret,
                "top_bottom_spread": top_ret - bottom_ret,
                "top_hit": top_ret > uni_ret,
            }
        )
    daily = pd.DataFrame(daily_rows)
    top_turnover = mean_top_turnover(top_sets_by_date(sub, signal))
    cost = None if top_turnover is None else top_turnover * cost_bps / 10000.0

    top_excess = None if daily.empty else float(daily["top_excess"].mean())
    net_excess = None if top_excess is None or cost is None else top_excess - cost
    return MetricRow(
        signal=signal,
        universe=universe,
        horizon=horizon,
        period=period,
        date_count=int(sub["trade_date"].nunique()),
        row_count=int(len(sub)),
        rank_ic_mean=finite_float(ic_mean),
        rank_ic_std=finite_float(ic_std),
        rank_ic_ir=finite_float(ic_ir),
        rank_ic_positive_rate=finite_float(ic_pos),
        top_decile_excess_mean=finite_float(top_excess),
        top_decile_return_mean=None if daily.empty else finite_float(daily["top_return"].mean()),
        universe_return_mean=None if daily.empty else finite_float(daily["universe_return"].mean()),
        top_bottom_spread_mean=None if daily.empty else finite_float(daily["top_bottom_spread"].mean()),
        top_decile_hit_rate=None if daily.empty else finite_float(daily["top_hit"].mean()),
        top_decile_turnover_mean=finite_float(top_turnover),
        net_top_decile_excess_mean=finite_float(net_excess),
    )


def write_outputs(metrics: list[MetricRow], output_dir: Path, meta: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_df = pd.DataFrame([row.__dict__ for row in metrics])
    metrics_csv = output_dir / "vp_p0_baseline_metrics.csv"
    metrics_json = output_dir / "vp_p0_baseline_summary.json"
    metrics_df.to_csv(metrics_csv, index=False)
    payload = {"meta": meta, "metrics": metrics_df.where(pd.notna(metrics_df), None).to_dict(orient="records")}
    metrics_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    all_metrics = metrics_df[metrics_df["period"].eq("all")].copy()
    all_metrics["rank_ic_mean_bps"] = all_metrics["rank_ic_mean"] * 10000
    all_metrics["top_decile_excess_bps"] = all_metrics["top_decile_excess_mean"] * 10000
    all_metrics["net_top_decile_excess_bps"] = all_metrics["net_top_decile_excess_mean"] * 10000
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
    compact = all_metrics[compact_cols].sort_values(["universe", "horizon", "rank_ic_mean"], ascending=[True, True, False])
    markdown_path = output_dir / "vp_p0_baseline_all_period.md"
    try:
        compact.to_markdown(markdown_path, index=False, floatfmt=".6f")
    except ImportError as exc:
        warning_path = output_dir / "vp_p0_baseline_all_period.md.warning.txt"
        warning_path.write_text(f"optional markdown output skipped: {exc}\n", encoding="utf-8")
    print(f"[OK] wrote {metrics_csv}")
    print(f"[OK] wrote {metrics_json}")


def main() -> None:
    args = parse_args()
    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip()]
    print(f"[LOAD] VP state from {args.vp_root}")
    vp = load_vp_state(args.vp_root, args.start_date, args.end_date, args.max_dates)
    print(f"[LOAD] VP rows={len(vp):,} dates={vp['trade_date'].nunique():,}")
    print(f"[LOAD] daily clean from {args.daily_clean}")
    daily = load_daily_with_forward_returns(args.daily_clean, horizons)
    daily_needed = ["ts_code", "trade_date", "total_mv", "circ_mv"] + [f"fwd_{h}d" for h in horizons]
    daily_needed = [c for c in daily_needed if c in daily.columns]
    merged = vp.merge(daily[daily_needed], on=["ts_code", "trade_date"], how="inner")
    merged = add_universe_flags(add_signals(merged))
    print(f"[MERGE] rows={len(merged):,} dates={merged['trade_date'].nunique():,} tickers={merged['ts_code'].nunique():,}")

    signals = [
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
    universes = ["full", "middle_20_90", "largest_10", "smallest_20"]

    metrics: list[MetricRow] = []
    masks = period_masks(merged)
    for period, mask in masks.items():
        period_df = merged[mask].copy()
        if period_df.empty:
            continue
        for signal in signals:
            if signal not in period_df.columns:
                continue
            for universe in universes:
                for horizon in horizons:
                    metrics.append(
                        evaluate_one(
                            period_df,
                            signal=signal,
                            universe=universe,
                            horizon=horizon,
                            period=period,
                            cost_bps=args.cost_bps,
                            min_date_rows=args.min_date_rows,
                        )
                    )

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
        "signals": signals,
        "universes": universes,
        "periods": list(masks.keys()),
    }
    write_outputs(metrics, args.output_dir, meta)


if __name__ == "__main__":
    main()
