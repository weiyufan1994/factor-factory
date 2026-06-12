#!/usr/bin/env python3
"""
Evaluate V19 value-occupation repair signals with return-volume covariation.

Research-side only. The script consumes:
- intraday_value_occupation_state_v1 P0 state variables
- daily clean bars for forward returns and controls
- minute_bar partitions for intraday return-volume state

It does not write composite scores back into any production datamart.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_vp_v18_drift_persistence_eval import (
    BASELINES,
    PERIODS,
    SIGNALS as V18_SIGNALS,
    UNIVERSES,
    add_v18_features,
    aggregate,
    clean_date,
    load_daily,
    load_vp_state,
    periods_for_date,
    top_stats,
)
from research_vp_p0_baseline_eval import add_signals, add_universe_flags


V19_SIGNALS = [
    "v19_rv_corr_repair",
    "v19_upside_confirmed_repair",
    "v19_absorption_repair",
    "v19_flow_confirmed_repair",
    "v19_flow_guarded_repair",
]

FLOW_FEATURE_COLUMNS = [
    "ts_code",
    "trade_date",
    "rv_corr",
    "rv_corr_pos",
    "up_down_amount_share_diff",
    "downside_amount_share",
    "upside_amount_share",
    "amount_weighted_return",
    "impact_efficiency",
    "downside_absorption",
    "high_volume_downside_break",
    "cutoff_return",
    "drawdown_recovery",
    "minute_count_flow",
    "flow_amount_total",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vp-root", type=Path, required=True)
    parser.add_argument("--daily-clean", type=Path, default=Path("data/clean/daily_clean.parquet"))
    parser.add_argument("--minute-root", type=Path)
    parser.add_argument("--flow-feature-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--cutoff-time", default="14:50:00")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--min-date-rows", type=int, default=50)
    parser.add_argument("--max-dates", type=int, default=None)
    parser.add_argument("--signals", default=",".join(V19_SIGNALS + ["v18_repair_drift_score", "v18_repair_base_z"] + BASELINES))
    parser.add_argument("--universes", default=",".join(UNIVERSES))
    parser.add_argument("--skip-flow-build", action="store_true")
    parser.add_argument("--available-minute-only", action="store_true", help="Restrict VP dates to dates with local minute partitions before max-dates sampling.")
    return parser.parse_args()


def cutoff_to_hhmmss(value: str) -> int:
    digits = re.sub(r"[^0-9]", "", str(value))
    if len(digits) <= 4:
        return int(digits) * 100
    return int(digits[:6])


def time_key(series: pd.Series) -> pd.Series:
    token = series.astype(str).str.strip().str.split().str[-1].str.replace(":", "", regex=False)
    digits = token.str.extract(r"(\d{3,6})$", expand=False).fillna("145000")
    numeric = pd.to_numeric(digits, errors="coerce")
    short = numeric.where(digits.str.len() > 4, numeric * 100)
    return short.fillna(145000).astype(int)


def candidate_minute_roots(explicit: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit.expanduser())
    if os.getenv("FACTORFORGE_LOCAL_MINUTE_ROOT"):
        candidates.append(Path(os.environ["FACTORFORGE_LOCAL_MINUTE_ROOT"]).expanduser())
    if os.getenv("FACTORFORGE_DATA_CACHE"):
        candidates.append(Path(os.environ["FACTORFORGE_DATA_CACHE"]).expanduser() / "s3_parquet" / "minute_bar-raw_v1-0b2b836c57d763c6")
    candidates.extend(
        [
            Path("/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6"),
            Path("/Users/humphrey/projects/factorforge-data-api-cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6"),
        ]
    )
    out: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            out.append(candidate)
            seen.add(key)
    return out


def minute_partition_files(root: Path, trade_date: str) -> list[Path]:
    date = clean_date(trade_date)
    date_dir = root / f"trade_date={date}"
    if date_dir.exists():
        parts = sorted(date_dir.glob("*.parquet"))
        if parts:
            return parts
    return sorted(root.glob(f"**/*{date}*.parquet"))


def available_minute_dates(roots: list[Path]) -> set[str]:
    dates: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("trade_date=*"):
            if not path.is_dir():
                continue
            date = path.name.split("=", 1)[-1]
            if len(date) >= 8 and date[:8].isdigit() and list(path.glob("*.parquet")):
                dates.add(date[:8])
    return dates


def evenly_spaced_dates(dates: list[str], max_dates: int | None) -> list[str]:
    if max_dates is None or max_dates <= 0 or len(dates) <= max_dates:
        return dates
    idx = np.linspace(0, len(dates) - 1, max_dates).round().astype(int)
    return [dates[i] for i in sorted(set(idx))]


def read_minute_day(roots: list[Path], trade_date: str) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    columns = ["ts_code", "trade_date", "trade_time", "bar_time", "datetime", "open", "close", "amount", "vol"]
    probes: list[dict[str, Any]] = []
    for root in roots:
        files = minute_partition_files(root, trade_date)
        probes.append({"root": str(root), "exists": root.exists(), "file_count": len(files)})
        if not files:
            continue
        frames = []
        for path in files:
            try:
                import pyarrow.parquet as pq

                physical = pq.ParquetFile(path).schema_arrow.names
                use_cols = [col for col in columns if col in physical]
                frames.append(pd.read_parquet(path, columns=use_cols))
            except Exception:
                frames.append(pd.read_parquet(path))
        return pd.concat(frames, ignore_index=True), {"source_root": str(root), "file_count": len(files), "probes": probes}
    return None, {"status": "missing_minute_partition", "probes": probes}


def corr_or_nan(x: pd.Series, y: pd.Series) -> float:
    if len(x) < 10:
        return np.nan
    sx = float(np.nanstd(x))
    sy = float(np.nanstd(y))
    if sx == 0.0 or sy == 0.0 or not math.isfinite(sx) or not math.isfinite(sy):
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def derive_return_volume_for_day(minute_df: pd.DataFrame, trade_date: str, cutoff_time: str) -> pd.DataFrame:
    cutoff = cutoff_to_hhmmss(cutoff_time)
    minute = minute_df.copy()
    if "trade_time" not in minute.columns and "bar_time" in minute.columns:
        minute["trade_time"] = minute["bar_time"]
    if "trade_time" not in minute.columns and "datetime" in minute.columns:
        minute["trade_time"] = minute["datetime"]
    if "trade_time" not in minute.columns:
        minute["trade_time"] = cutoff_time
    if "trade_date" not in minute.columns:
        minute["trade_date"] = trade_date
    if "open" not in minute.columns:
        minute["open"] = minute["close"]
    minute["trade_date"] = minute["trade_date"].map(clean_date)
    minute["hhmmss"] = time_key(minute["trade_time"])
    minute = minute[minute["hhmmss"] <= cutoff].copy()
    for col in ["open", "close", "amount", "vol"]:
        if col in minute.columns:
            minute[col] = pd.to_numeric(minute[col], errors="coerce")
    if "amount" not in minute.columns and "vol" in minute.columns:
        minute["amount"] = minute["vol"]
    minute = minute.dropna(subset=["ts_code", "trade_date", "open", "close", "amount"])
    minute = minute[(minute["open"] > 0) & (minute["close"] > 0) & (minute["amount"].abs() > 0)]
    if minute.empty:
        return pd.DataFrame(columns=FLOW_FEATURE_COLUMNS)

    minute = minute.sort_values(["ts_code", "trade_date", "hhmmss"]).reset_index(drop=True)
    grouped = minute.groupby(["ts_code", "trade_date"], sort=False)
    minute["prev_close"] = grouped["close"].shift(1)
    first_open = grouped["open"].transform("first")
    minute["ret"] = np.log(minute["close"] / minute["prev_close"])
    first_mask = minute["prev_close"].isna()
    minute.loc[first_mask, "ret"] = np.log(minute.loc[first_mask, "close"] / minute.loc[first_mask, "open"])
    minute["ret"] = minute["ret"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    minute["amount_abs"] = minute["amount"].abs()
    minute["log_amount"] = np.log1p(minute["amount_abs"])
    minute["pos_amount"] = np.where(minute["ret"] > 0, minute["amount_abs"], 0.0)
    minute["neg_amount"] = np.where(minute["ret"] < 0, minute["amount_abs"], 0.0)
    minute["ret_amount"] = minute["ret"] * minute["amount_abs"]
    minute["abs_ret_amount"] = minute["ret"].abs() * minute["amount_abs"]

    close_min = grouped["close"].transform("min")
    last_close = grouped["close"].transform("last")
    minute["first_open"] = first_open
    minute["last_close"] = last_close
    minute["min_close"] = close_min

    rows: list[dict[str, Any]] = []
    for (ts_code, date), group in minute.groupby(["ts_code", "trade_date"], sort=False):
        gross = float(group["amount_abs"].sum())
        if gross <= 0:
            continue
        ret = group["ret"]
        log_amount = group["log_amount"]
        pos_share = float(group["pos_amount"].sum() / gross)
        neg_share = float(group["neg_amount"].sum() / gross)
        cutoff_ret = float(group["last_close"].iloc[-1] / group["first_open"].iloc[0] - 1.0)
        max_drawdown = float(group["min_close"].iloc[0] / group["first_open"].iloc[0] - 1.0)
        recovery = max(0.0, cutoff_ret - max_drawdown)
        abs_ret_amount = float(group["abs_ret_amount"].sum())
        amount_weighted_return = float(group["ret_amount"].sum() / gross)
        impact_eff = float(cutoff_ret / (abs_ret_amount / gross + 1e-8))
        rv_corr = corr_or_nan(ret, log_amount)
        downside_absorption = neg_share * recovery
        high_volume_downside_break = neg_share * max(0.0, -cutoff_ret)
        rows.append(
            {
                "ts_code": str(ts_code),
                "trade_date": clean_date(date),
                "rv_corr": rv_corr,
                "rv_corr_pos": max(0.0, rv_corr) if math.isfinite(rv_corr) else 0.0,
                "up_down_amount_share_diff": pos_share - neg_share,
                "downside_amount_share": neg_share,
                "upside_amount_share": pos_share,
                "amount_weighted_return": amount_weighted_return,
                "impact_efficiency": impact_eff,
                "downside_absorption": downside_absorption,
                "high_volume_downside_break": high_volume_downside_break,
                "cutoff_return": cutoff_ret,
                "drawdown_recovery": recovery,
                "minute_count_flow": int(len(group)),
                "flow_amount_total": gross,
            }
        )
    return pd.DataFrame(rows, columns=FLOW_FEATURE_COLUMNS)


def build_or_load_flow_features(
    *,
    roots: list[Path],
    feature_root: Path,
    dates: list[str],
    cutoff_time: str,
    skip_build: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    feature_root.mkdir(parents=True, exist_ok=True)
    profiles: list[dict[str, Any]] = []
    frames: list[pd.DataFrame] = []
    started = time.perf_counter()
    for idx, date in enumerate(dates, start=1):
        out_path = feature_root / f"trade_date={date}" / "part-000.parquet"
        if out_path.exists():
            day = pd.read_parquet(out_path)
            frames.append(day)
            profiles.append({"trade_date": date, "status": "cached", "rows": int(len(day)), "path": str(out_path)})
        elif skip_build:
            profiles.append({"trade_date": date, "status": "missing_cached_feature", "path": str(out_path)})
        else:
            minute, source_profile = read_minute_day(roots, date)
            if minute is None or minute.empty:
                profiles.append({"trade_date": date, "status": "missing_minute", "source_profile": source_profile})
                continue
            day = derive_return_volume_for_day(minute, date, cutoff_time)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            day.to_parquet(out_path, index=False)
            frames.append(day)
            profiles.append(
                {
                    "trade_date": date,
                    "status": "built",
                    "rows": int(len(day)),
                    "minute_rows": int(len(minute)),
                    "path": str(out_path),
                    "source_profile": source_profile,
                }
            )
        if idx % 250 == 0:
            print(f"[FLOW_PROGRESS] dates={idx} built_or_loaded_rows={sum(len(x) for x in frames):,}", flush=True)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FLOW_FEATURE_COLUMNS)
    profile = {
        "date_count_requested": len(dates),
        "feature_rows": int(len(frame)),
        "feature_dates": int(frame["trade_date"].nunique()) if not frame.empty else 0,
        "seconds": time.perf_counter() - started,
        "profiles_head": profiles[:10],
        "profiles_tail": profiles[-10:],
        "missing_count": sum(1 for p in profiles if str(p.get("status", "")).startswith("missing")),
        "built_count": sum(1 for p in profiles if p.get("status") == "built"),
        "cached_count": sum(1 for p in profiles if p.get("status") == "cached"),
    }
    return frame, profile


def cs_z(df: pd.DataFrame, col: str) -> pd.Series:
    values = pd.to_numeric(df[col], errors="coerce")
    mean = values.groupby(df["trade_date"]).transform("mean")
    std = values.groupby(df["trade_date"]).transform("std")
    return ((values - mean) / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def add_v19_features(df: pd.DataFrame) -> pd.DataFrame:
    for col in FLOW_FEATURE_COLUMNS:
        if col not in {"ts_code", "trade_date"} and col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in [
        "rv_corr",
        "rv_corr_pos",
        "up_down_amount_share_diff",
        "downside_absorption",
        "high_volume_downside_break",
        "amount_weighted_return",
        "impact_efficiency",
    ]:
        if col in df.columns:
            df[f"{col}_z"] = cs_z(df, col)
        else:
            df[f"{col}_z"] = 0.0

    base = df["v18_repair_drift_score"].fillna(0.0)
    no_break = pd.to_numeric(df.get("no_break_gate", 0.0), errors="coerce").fillna(0.0)
    defended = pd.to_numeric(df.get("defended_support_gate", 0.0), errors="coerce").fillna(0.0)
    lower_support = pd.to_numeric(df.get("lower_support_ratio", 0.0), errors="coerce").fillna(0.0)
    support_state = (no_break * 0.5 + defended * 0.3 + lower_support.clip(0, 1) * 0.2).fillna(0.0)

    df["v19_rv_corr_repair"] = base + 0.30 * df["rv_corr_z"]
    df["v19_upside_confirmed_repair"] = base + 0.35 * df["up_down_amount_share_diff_z"] + 0.15 * df["amount_weighted_return_z"]
    df["v19_absorption_repair"] = base + 0.40 * df["downside_absorption_z"] * support_state - 0.25 * df["high_volume_downside_break_z"]
    df["v19_flow_confirmed_repair"] = (
        base
        + 0.25 * df["rv_corr_z"]
        + 0.30 * df["up_down_amount_share_diff_z"]
        + 0.20 * df["downside_absorption_z"] * support_state
        - 0.25 * df["high_volume_downside_break_z"]
    )
    df["v19_flow_guarded_repair"] = df["v19_flow_confirmed_repair"] - 0.15 * df["impact_efficiency_z"].clip(upper=0.0).abs()
    return df


def write_markdown_table(frame: pd.DataFrame, path: Path) -> None:
    if frame.empty:
        path.write_text("_empty_\n", encoding="utf-8")
        return
    display = frame.copy()
    for col in display.columns:
        if pd.api.types.is_float_dtype(display[col]):
            display[col] = display[col].map(lambda x: "" if pd.isna(x) else f"{float(x):.6f}")
    columns = list(display.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in display.astype(str).itertuples(index=False, name=None):
        lines.append("| " + " | ".join(row) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    signals = [x.strip() for x in args.signals.split(",") if x.strip()]
    universes = [x.strip() for x in args.universes.split(",") if x.strip()]

    print(f"[LOAD] VP state from {args.vp_root}", flush=True)
    initial_max_dates = None if args.available_minute_only else args.max_dates
    vp = load_vp_state(args.vp_root, args.start_date, args.end_date, initial_max_dates)
    print(f"[LOAD] VP rows={len(vp):,} dates={vp['trade_date'].nunique():,}", flush=True)
    vp = add_signals(vp)

    flow_root = args.flow_feature_root or (args.output_dir / "return_volume_features")
    roots = candidate_minute_roots(args.minute_root)
    print(f"[FLOW] roots={[str(r) for r in roots]}", flush=True)
    vp_dates = sorted(vp["trade_date"].unique())
    if args.available_minute_only:
        available_dates = available_minute_dates(roots)
        before = len(vp_dates)
        vp_dates = [date for date in vp_dates if date in available_dates]
        print(f"[FLOW] available_minute_only dates={len(vp_dates):,}/{before:,}", flush=True)
        vp = vp[vp["trade_date"].isin(vp_dates)].copy()
    if args.max_dates is not None and args.max_dates > 0:
        sampled_dates = evenly_spaced_dates(vp_dates, args.max_dates)
        print(f"[FLOW] sampled_dates={len(sampled_dates):,}/{len(vp_dates):,}", flush=True)
        vp_dates = sampled_dates
        vp = vp[vp["trade_date"].isin(vp_dates)].copy()
    flow, flow_profile = build_or_load_flow_features(
        roots=roots,
        feature_root=flow_root,
        dates=vp_dates,
        cutoff_time=args.cutoff_time,
        skip_build=args.skip_flow_build,
    )
    flow_profile_path = args.output_dir / "vp_v19_return_volume_feature_profile.json"
    flow_profile_path.write_text(json.dumps(flow_profile, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[FLOW] rows={len(flow):,} dates={flow['trade_date'].nunique() if not flow.empty else 0:,} profile={flow_profile_path}", flush=True)
    if flow.empty:
        raise SystemExit("no return-volume features were available")

    print(f"[LOAD] daily clean from {args.daily_clean}", flush=True)
    daily = load_daily(args.daily_clean, horizons)
    df = vp.merge(flow, on=["ts_code", "trade_date"], how="inner").merge(daily, on=["ts_code", "trade_date"], how="inner")
    df = add_universe_flags(df)
    df = add_v18_features(df)
    df = add_v19_features(df)
    print(f"[MERGE] rows={len(df):,} dates={df['trade_date'].nunique():,} tickers={df['ts_code'].nunique():,}", flush=True)

    controls = [
        col
        for col in ["ln_total_mv", "drift_1d_to_cutoff", "mom_5d_to_cutoff", "mom_20d_to_cutoff", "turnover_rate", "vol_20d"]
        if col in df.columns
    ]
    print(f"[CONTROLS] {controls}", flush=True)

    daily_rows: list[dict[str, object]] = []
    top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]] = defaultdict(dict)
    grouped_dates = list(df.groupby("trade_date", sort=True))
    for idx, (date, day) in enumerate(grouped_dates, start=1):
        if len(day) < args.min_date_rows:
            continue
        periods = periods_for_date(str(date))
        for universe in universes:
            flag = f"universe_{universe}"
            if flag not in day.columns:
                continue
            uday = day[day[flag]].copy()
            if len(uday) < args.min_date_rows:
                continue
            for horizon in horizons:
                ret_col = f"fwd_{horizon}d"
                if ret_col not in uday.columns:
                    continue
                for signal in signals:
                    if signal not in uday.columns:
                        continue
                    stats, top = top_stats(uday, signal, ret_col, controls)
                    if not stats:
                        continue
                    for period in periods:
                        key = (signal, universe, horizon, period)
                        daily_rows.append({"signal": signal, "universe": universe, "horizon": horizon, "period": period, "trade_date": date, **stats})
                        top_sets[key][str(date)] = top
        if idx % 250 == 0:
            print(f"[PROGRESS] processed_dates={idx}", flush=True)

    metrics = aggregate(daily_rows, top_sets, args.cost_bps)
    metrics_path = args.output_dir / "vp_v19_return_volume_metrics.csv"
    metrics.to_csv(metrics_path, index=False)

    all_period = metrics[metrics["period"].eq("all")].sort_values(
        ["universe", "horizon", "rank_ic_mean"], ascending=[True, True, False]
    )
    md_path = args.output_dir / "vp_v19_return_volume_all_period.md"
    write_markdown_table(all_period, md_path)

    summary = {
        "run": {
            "start_date": args.start_date,
            "end_date": args.end_date,
            "horizons": horizons,
            "signals": signals,
            "universes": universes,
            "cost_bps": args.cost_bps,
            "max_dates": args.max_dates,
            "cutoff_time": args.cutoff_time,
        },
        "inputs": {
            "vp_root": str(args.vp_root),
            "daily_clean": str(args.daily_clean),
            "minute_roots": [str(x) for x in roots],
            "flow_feature_root": str(flow_root),
            "flow_profile_path": str(flow_profile_path),
        },
        "coverage": {
            "vp_rows": int(len(vp)),
            "vp_dates": int(vp["trade_date"].nunique()),
            "flow_rows": int(len(flow)),
            "flow_dates": int(flow["trade_date"].nunique()),
            "merged_rows": int(len(df)),
            "merged_dates": int(df["trade_date"].nunique()),
            "merged_tickers": int(df["ts_code"].nunique()),
        },
        "flow_profile": flow_profile,
        "controls": controls,
        "metrics_rows": int(len(metrics)),
        "top_all_period": json.loads(all_period.head(80).to_json(orient="records")),
    }
    summary_path = args.output_dir / "vp_v19_return_volume_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] wrote {metrics_path}", flush=True)
    print(f"[OK] wrote {summary_path}", flush=True)


if __name__ == "__main__":
    main()
