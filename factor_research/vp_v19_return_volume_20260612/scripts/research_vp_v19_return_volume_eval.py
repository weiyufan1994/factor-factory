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
import gc
import json
import math
import os
import re
import time
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays on \\.fillna")

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

INDEX_UNIVERSES = [
    "csi800",
    "csi800_csi1000",
    "csi2000",
    "csi_all_share",
]

INDEX_UNIVERSE_IDS = {
    "csi800": {"csi800"},
    "csi800_csi1000": {"csi800", "csi1000"},
    "csi2000": {"csi2000"},
    "csi_all_share": {"csi_all_share"},
}

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
    parser.add_argument("--index-universe-root", type=Path)
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
    parser.add_argument("--size-neutral-signals", default="v18_repair_drift_score,v19_rv_corr_repair,v19_upside_confirmed_repair")
    parser.add_argument("--size-neutral-universes", default="")
    parser.add_argument("--skip-flow-build", action="store_true")
    parser.add_argument("--available-minute-only", action="store_true", help="Restrict VP dates to dates with local minute partitions before max-dates sampling.")
    parser.add_argument("--stream-by-date", action="store_true", help="Evaluate one trade_date at a time to bound memory on full-window minute-state runs.")
    parser.add_argument("--write-merged-panel", action="store_true")
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


def partition_files(root: Path, trade_date: str) -> list[Path]:
    date = clean_date(trade_date)
    date_dir = root / f"trade_date={date}"
    if date_dir.exists():
        return sorted(date_dir.glob("*.parquet"))
    return sorted(root.glob(f"**/*{date}*.parquet"))


def partition_dates(root: Path, start_date: str, end_date: str, max_dates: int | None = None) -> list[str]:
    dates: list[str] = []
    for path in root.glob("trade_date=*"):
        if not path.is_dir():
            continue
        date = clean_date(path.name.split("=", 1)[-1])
        if start_date <= date <= end_date and list(path.glob("*.parquet")):
            dates.append(date)
    dates = sorted(set(dates))
    return evenly_spaced_dates(dates, max_dates)


def read_partition_frame(root: Path, trade_date: str, columns: list[str] | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in partition_files(root, trade_date):
        physical = pq.ParquetFile(path).schema_arrow.names
        use_cols = [col for col in (columns or physical) if col in physical]
        part = pd.read_parquet(path, columns=use_cols or None)
        if "trade_date" not in part.columns:
            part["trade_date"] = clean_date(trade_date)
        frames.append(part)
    if not frames:
        return pd.DataFrame(columns=columns or [])
    frame = pd.concat(frames, ignore_index=True)
    frame["trade_date"] = frame["trade_date"].map(clean_date)
    return frame


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


def add_v18_features_stream_day(df: pd.DataFrame, no_break_history: dict[str, list[bool]]) -> pd.DataFrame:
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    df["below_cost_z"] = cs_z(df, "below_cost_depth_score_raw")
    df["lower_support_z"] = cs_z(df, "lower_support_mass")
    df["upper_overhang_z"] = cs_z(df, "upper_overhang_ratio")
    df["v18_repair_base_z"] = df["below_cost_z"] + df["lower_support_z"]

    for col in ["no_break_gate", "defended_support_gate", "reference_price", "close_lag1", "close_lag3", "close_lag5", "close_lag20"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    no_break = pd.to_numeric(df["no_break_gate"], errors="coerce").fillna(0.0).gt(0.5)
    prev1 = df["ts_code"].astype(str).map(lambda x: no_break_history.get(x, [False])[-1] if no_break_history.get(x) else False)
    prev2 = df["ts_code"].astype(str).map(lambda x: no_break_history.get(x, [False, False])[-2] if len(no_break_history.get(x, [])) >= 2 else False)
    df["no_break_bool"] = no_break
    df["no_break_2d_gate"] = no_break & prev1.astype(bool)
    df["no_break_3d_gate"] = no_break & prev1.astype(bool) & prev2.astype(bool)

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

    for ts_code, value in zip(df["ts_code"].astype(str), no_break.astype(bool)):
        history = no_break_history.setdefault(ts_code, [])
        history.append(bool(value))
        if len(history) > 3:
            del history[:-3]
    return df


def load_index_universe_flags(index_root: Path | None, dates: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = ["universe_id", "trade_date", "ts_code", "in_universe"]
    if index_root is None:
        return pd.DataFrame(columns=["ts_code", "trade_date"]), {"status": "not_requested"}
    index_root = index_root.expanduser()
    if not index_root.exists():
        return pd.DataFrame(columns=["ts_code", "trade_date"]), {"status": "missing_root", "root": str(index_root)}

    frames: list[pd.DataFrame] = []
    profiles: list[dict[str, Any]] = []
    target_ids = sorted({item for values in INDEX_UNIVERSE_IDS.values() for item in values})
    target_dates = {clean_date(date) for date in dates}
    for idx, date in enumerate(sorted(target_dates), start=1):
        files = partition_files(index_root, date)
        if not files:
            profiles.append({"trade_date": date, "status": "missing_partition"})
            continue
        day_parts = []
        for path in files:
            physical = pq.ParquetFile(path).schema_arrow.names
            use_cols = [col for col in columns if col in physical]
            part = pd.read_parquet(path, columns=use_cols)
            if "trade_date" not in part.columns:
                part["trade_date"] = date
            day_parts.append(part)
        day = pd.concat(day_parts, ignore_index=True)
        day["trade_date"] = day["trade_date"].map(clean_date)
        day = day[day["universe_id"].isin(target_ids)].copy()
        if "in_universe" in day.columns:
            day = day[day["in_universe"].fillna(False).astype(bool)]
        frames.append(day[["ts_code", "trade_date", "universe_id"]])
        profiles.append({"trade_date": date, "status": "loaded", "rows": int(len(day))})
        if idx % 250 == 0:
            print(f"[INDEX_PROGRESS] dates={idx} rows={sum(len(x) for x in frames):,}", flush=True)

    if not frames:
        return pd.DataFrame(columns=["ts_code", "trade_date"]), {
            "status": "empty",
            "root": str(index_root),
            "date_count_requested": len(target_dates),
            "profiles_head": profiles[:10],
            "profiles_tail": profiles[-10:],
        }
    memberships = pd.concat(frames, ignore_index=True).drop_duplicates()
    base = memberships[["ts_code", "trade_date"]].drop_duplicates().copy()
    for universe, ids in INDEX_UNIVERSE_IDS.items():
        keys = memberships[memberships["universe_id"].isin(ids)][["ts_code", "trade_date"]].drop_duplicates()
        keys[f"universe_{universe}"] = True
        base = base.merge(keys, on=["ts_code", "trade_date"], how="left")
        base[f"universe_{universe}"] = base[f"universe_{universe}"].fillna(False).astype(bool)
    profile = {
        "status": "loaded",
        "root": str(index_root),
        "date_count_requested": len(target_dates),
        "date_count_loaded": int(memberships["trade_date"].nunique()),
        "row_count": int(len(memberships)),
        "profiles_head": profiles[:10],
        "profiles_tail": profiles[-10:],
    }
    return base, profile


def load_index_universe_membership(index_root: Path | None, dates: list[str], universe: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = ["universe_id", "trade_date", "ts_code", "in_universe"]
    flag = f"universe_{universe}"
    if universe not in INDEX_UNIVERSE_IDS:
        return pd.DataFrame(columns=["ts_code", "trade_date", flag]), {"status": "not_index_universe", "universe": universe}
    if index_root is None:
        return pd.DataFrame(columns=["ts_code", "trade_date", flag]), {"status": "not_requested", "universe": universe}
    index_root = index_root.expanduser()
    if not index_root.exists():
        return pd.DataFrame(columns=["ts_code", "trade_date", flag]), {"status": "missing_root", "root": str(index_root), "universe": universe}

    frames: list[pd.DataFrame] = []
    profiles: list[dict[str, Any]] = []
    target_ids = INDEX_UNIVERSE_IDS[universe]
    target_dates = {clean_date(date) for date in dates}
    for idx, date in enumerate(sorted(target_dates), start=1):
        files = partition_files(index_root, date)
        if not files:
            profiles.append({"trade_date": date, "status": "missing_partition"})
            continue
        day_parts = []
        for path in files:
            physical = pq.ParquetFile(path).schema_arrow.names
            use_cols = [col for col in columns if col in physical]
            part = pd.read_parquet(path, columns=use_cols)
            if "trade_date" not in part.columns:
                part["trade_date"] = date
            day_parts.append(part)
        day = pd.concat(day_parts, ignore_index=True)
        day["trade_date"] = day["trade_date"].map(clean_date)
        day = day[day["universe_id"].isin(target_ids)].copy()
        if "in_universe" in day.columns:
            day = day[day["in_universe"].fillna(False).astype(bool)]
        keys = day[["ts_code", "trade_date"]].drop_duplicates()
        if not keys.empty:
            frames.append(keys)
        profiles.append({"trade_date": date, "status": "loaded", "rows": int(len(keys))})
        if idx % 250 == 0:
            print(f"[INDEX_PROGRESS] universe={universe} dates={idx} rows={sum(len(x) for x in frames):,}", flush=True)

    if not frames:
        return pd.DataFrame(columns=["ts_code", "trade_date", flag]), {
            "status": "empty",
            "root": str(index_root),
            "universe": universe,
            "date_count_requested": len(target_dates),
            "profiles_head": profiles[:10],
            "profiles_tail": profiles[-10:],
        }
    membership = pd.concat(frames, ignore_index=True).drop_duplicates()
    membership[flag] = True
    profile = {
        "status": "loaded",
        "root": str(index_root),
        "universe": universe,
        "date_count_requested": len(target_dates),
        "date_count_loaded": int(membership["trade_date"].nunique()),
        "row_count": int(len(membership)),
        "profiles_head": profiles[:10],
        "profiles_tail": profiles[-10:],
    }
    return membership, profile


def add_fixed_small_flag(df: pd.DataFrame) -> pd.DataFrame:
    circ = pd.to_numeric(df.get("circ_mv"), errors="coerce")
    total = pd.to_numeric(df.get("total_mv"), errors="coerce")
    market_cap = circ.where(circ.notna() & circ.gt(0), total)
    df["fixed_small_market_cap"] = market_cap
    eligible = market_cap.ge(50000.0)
    rank_pct_all = market_cap.groupby(df["trade_date"]).rank(pct=True)
    eligible = eligible & rank_pct_all.gt(0.10)

    df["fixed_small_eligible"] = eligible.fillna(False)
    eligible_rank = pd.Series(np.nan, index=df.index, dtype="float64")
    eligible_rank.loc[eligible] = market_cap.loc[eligible].groupby(df.loc[eligible, "trade_date"]).rank(pct=True)
    df["fixed_small_rank_pct"] = eligible_rank
    df["universe_fixed_small_20"] = eligible & eligible_rank.le(0.20)
    return df


def residualize_by_date(frame: pd.DataFrame, signal: str, control: str, flag: str) -> pd.Series:
    out = pd.Series(np.nan, index=frame.index, dtype="float64")
    if signal not in frame.columns or control not in frame.columns or flag not in frame.columns:
        return out
    work = frame[frame[flag]].copy()
    if work.empty:
        return out
    for _, group in work.groupby("trade_date", sort=False):
        sub = group[[signal, control]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(sub) < 30 or sub[signal].nunique(dropna=True) < 2 or sub[control].nunique(dropna=True) < 2:
            continue
        x = sub[[control]].to_numpy(dtype=float)
        x = np.column_stack([np.ones(len(x)), x])
        y = sub[signal].to_numpy(dtype=float)
        try:
            beta = np.linalg.lstsq(x, y, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        resid = y - x @ beta
        out.loc[sub.index] = resid
    return out


def add_size_neutral_signals(df: pd.DataFrame, signals: list[str], universes: list[str]) -> tuple[pd.DataFrame, list[str]]:
    control = "ln_circ_mv" if "ln_circ_mv" in df.columns else "ln_total_mv"
    created: list[str] = []
    for universe in universes:
        flag = f"universe_{universe}"
        if flag not in df.columns:
            continue
        for signal in signals:
            if signal not in df.columns:
                continue
            out_col = f"{signal}__sn_{universe}"
            df[out_col] = residualize_by_date(df, signal, control, flag)
            if df[out_col].notna().any():
                created.append(out_col)
    return df, created


def evaluate_universe_daily(
    *,
    frame: pd.DataFrame,
    universe: str,
    signals: list[str],
    horizons: list[int],
    controls: list[str],
    min_date_rows: int,
) -> tuple[list[dict[str, object]], dict[tuple[str, str, int, str], dict[str, set[str]]]]:
    rows: list[dict[str, object]] = []
    top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]] = defaultdict(dict)
    grouped_dates = list(frame.groupby("trade_date", sort=True))
    for idx, (date, day) in enumerate(grouped_dates, start=1):
        if len(day) < min_date_rows:
            continue
        periods = periods_for_date(str(date))
        for horizon in horizons:
            ret_col = f"fwd_{horizon}d"
            if ret_col not in day.columns:
                continue
            for signal in signals:
                if signal not in day.columns:
                    continue
                stats, top = top_stats(day, signal, ret_col, controls)
                if not stats:
                    continue
                for period in periods:
                    key = (signal, universe, horizon, period)
                    rows.append({"signal": signal, "universe": universe, "horizon": horizon, "period": period, "trade_date": date, **stats})
                    top_sets[key][str(date)] = top
        if idx % 250 == 0:
            print(f"[PROGRESS] universe={universe} processed_dates={idx}", flush=True)
    return rows, top_sets


def load_index_flags_for_day(index_root: Path | None, date: str, universes: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    index_universes = [universe for universe in universes if universe in INDEX_UNIVERSE_IDS]
    columns = ["universe_id", "trade_date", "ts_code", "in_universe"]
    out_cols = ["ts_code", "trade_date"] + [f"universe_{u}" for u in index_universes]
    if not index_universes or index_root is None or not index_root.exists():
        return pd.DataFrame(columns=out_cols), {"status": "not_available", "trade_date": date}
    files = partition_files(index_root, date)
    if not files:
        return pd.DataFrame(columns=out_cols), {"status": "missing_partition", "trade_date": date}
    parts = []
    for path in files:
        physical = pq.ParquetFile(path).schema_arrow.names
        use_cols = [col for col in columns if col in physical]
        part = pd.read_parquet(path, columns=use_cols)
        if "trade_date" not in part.columns:
            part["trade_date"] = date
        parts.append(part)
    raw = pd.concat(parts, ignore_index=True)
    raw["trade_date"] = raw["trade_date"].map(clean_date)
    if "in_universe" in raw.columns:
        raw = raw[raw["in_universe"].fillna(False).astype(bool)]
    base = raw[["ts_code", "trade_date"]].drop_duplicates().copy()
    row_counts: dict[str, int] = {}
    for universe in index_universes:
        keys = raw[raw["universe_id"].isin(INDEX_UNIVERSE_IDS[universe])][["ts_code", "trade_date"]].drop_duplicates()
        row_counts[universe] = int(len(keys))
        keys[f"universe_{universe}"] = True
        base = base.merge(keys, on=["ts_code", "trade_date"], how="left")
        base[f"universe_{universe}"] = base[f"universe_{universe}"].fillna(False).astype(bool)
    return base, {"status": "loaded", "trade_date": date, "row_counts": row_counts, "raw_rows": int(len(raw))}


def residualize_single_date(frame: pd.DataFrame, signal: str, control: str) -> pd.Series:
    out = pd.Series(np.nan, index=frame.index, dtype="float64")
    if signal not in frame.columns or control not in frame.columns:
        return out
    sub = frame[[signal, control]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sub) < 30 or sub[signal].nunique(dropna=True) < 2 or sub[control].nunique(dropna=True) < 2:
        return out
    x = sub[[control]].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    y = sub[signal].to_numpy(dtype=float)
    try:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return out
    out.loc[sub.index] = y - x @ beta
    return out


def main_stream_by_date(
    args: argparse.Namespace,
    horizons: list[int],
    signals: list[str],
    universes: list[str],
    size_neutral_base_signals: list[str],
) -> None:
    print("[MODE] stream_by_date", flush=True)
    flow_root = args.flow_feature_root or (args.output_dir / "return_volume_features")
    roots = candidate_minute_roots(args.minute_root)
    vp_dates = partition_dates(args.vp_root, args.start_date, args.end_date, None if args.available_minute_only else args.max_dates)
    if args.available_minute_only:
        available_dates = available_minute_dates(roots)
        before = len(vp_dates)
        vp_dates = [date for date in vp_dates if date in available_dates]
        print(f"[FLOW] available_minute_only dates={len(vp_dates):,}/{before:,}", flush=True)
    if args.max_dates is not None and args.max_dates > 0 and args.available_minute_only:
        before = len(vp_dates)
        vp_dates = evenly_spaced_dates(vp_dates, args.max_dates)
        print(f"[FLOW] sampled_dates={len(vp_dates):,}/{before:,}", flush=True)

    print(f"[LOAD] daily clean from {args.daily_clean}", flush=True)
    daily = load_daily(args.daily_clean, horizons)
    daily = daily[daily["trade_date"].isin(vp_dates)].copy()
    daily_grouped = daily.groupby("trade_date", sort=False)
    print(f"[DAILY] rows={len(daily):,} dates={daily['trade_date'].nunique():,}", flush=True)

    controls = [
        col
        for col in ["ln_total_mv", "drift_1d_to_cutoff", "mom_5d_to_cutoff", "mom_20d_to_cutoff", "turnover_rate", "vol_20d"]
        if col in set(daily.columns) | {"drift_1d_to_cutoff", "mom_5d_to_cutoff", "mom_20d_to_cutoff"}
    ]
    print(f"[CONTROLS] {controls}", flush=True)

    daily_rows: list[dict[str, object]] = []
    top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]] = defaultdict(dict)
    no_break_history: dict[str, list[bool]] = {}
    flow_profiles: list[dict[str, Any]] = []
    index_profiles: list[dict[str, Any]] = []
    universe_profiles: dict[str, dict[str, Any]] = defaultdict(lambda: {"dates": 0, "rows": 0, "daily_rows": 0})
    created_size_neutral: list[str] = []
    size_neutral_universes = [x.strip() for x in args.size_neutral_universes.split(",") if x.strip()] or universes
    base_signals = list(signals)

    for idx, date in enumerate(vp_dates, start=1):
        vp_day = read_partition_frame(args.vp_root, date)
        if vp_day.empty:
            continue
        if date not in daily_grouped.groups:
            continue
        flow_path = flow_root / f"trade_date={date}" / "part-000.parquet"
        if flow_path.exists():
            flow_day = read_partition_frame(flow_root, date, FLOW_FEATURE_COLUMNS)
            flow_profiles.append({"trade_date": date, "status": "cached", "rows": int(len(flow_day))})
        elif args.skip_flow_build:
            flow_profiles.append({"trade_date": date, "status": "missing_cached_feature"})
            continue
        else:
            minute, source_profile = read_minute_day(roots, date)
            if minute is None or minute.empty:
                flow_profiles.append({"trade_date": date, "status": "missing_minute", "source_profile": source_profile})
                continue
            flow_day = derive_return_volume_for_day(minute, date, args.cutoff_time)
            flow_path.parent.mkdir(parents=True, exist_ok=True)
            flow_day.to_parquet(flow_path, index=False)
            flow_profiles.append({"trade_date": date, "status": "built", "rows": int(len(flow_day)), "minute_rows": int(len(minute))})
        if flow_day.empty:
            continue

        day = add_signals(vp_day)
        day = day.merge(flow_day, on=["ts_code", "trade_date"], how="inner")
        day = day.merge(daily_grouped.get_group(date), on=["ts_code", "trade_date"], how="inner")
        if len(day) < args.min_date_rows:
            continue
        day = add_universe_flags(day)
        day = add_v18_features_stream_day(day, no_break_history)
        day = add_v19_features(day)
        day = add_fixed_small_flag(day)

        index_day, index_profile = load_index_flags_for_day(args.index_universe_root, date, universes)
        index_profiles.append(index_profile)
        if not index_day.empty:
            day = day.merge(index_day, on=["ts_code", "trade_date"], how="left")
        for universe in INDEX_UNIVERSES:
            col = f"universe_{universe}"
            if col in day.columns:
                day[col] = day[col].fillna(False).astype(bool)

        control = "ln_circ_mv" if "ln_circ_mv" in day.columns else "ln_total_mv"
        periods = periods_for_date(date)
        for universe in universes:
            flag = f"universe_{universe}"
            if flag not in day.columns:
                continue
            uday = day[day[flag]].copy()
            if len(uday) < args.min_date_rows:
                continue
            eval_signals = list(base_signals)
            created_for_date: list[str] = []
            if universe in size_neutral_universes:
                for signal in size_neutral_base_signals:
                    if signal not in uday.columns:
                        continue
                    out_col = f"{signal}__sn_{universe}"
                    uday[out_col] = residualize_single_date(uday, signal, control)
                    if uday[out_col].notna().any():
                        eval_signals.append(out_col)
                        created_for_date.append(out_col)
                        if out_col not in created_size_neutral:
                            created_size_neutral.append(out_col)
            for horizon in horizons:
                ret_col = f"fwd_{horizon}d"
                if ret_col not in uday.columns:
                    continue
                for signal in eval_signals:
                    if signal not in uday.columns:
                        continue
                    stats, top = top_stats(uday, signal, ret_col, controls)
                    if not stats:
                        continue
                    for period in periods:
                        key = (signal, universe, horizon, period)
                        daily_rows.append({"signal": signal, "universe": universe, "horizon": horizon, "period": period, "trade_date": date, **stats})
                        top_sets[key][date] = top
            universe_profiles[universe]["dates"] += 1
            universe_profiles[universe]["rows"] += int(len(uday))
            universe_profiles[universe]["daily_rows"] = len(daily_rows)
            if created_for_date:
                universe_profiles[universe]["has_size_neutral"] = True
            del uday

        if idx % 100 == 0:
            print(f"[STREAM_PROGRESS] dates={idx}/{len(vp_dates)} metric_rows={len(daily_rows):,}", flush=True)
        del vp_day, flow_day, day
        gc.collect()

    flow_profile = {
        "mode": "stream_by_date",
        "date_count_requested": len(vp_dates),
        "feature_dates": sum(1 for p in flow_profiles if p.get("status") in {"cached", "built"}),
        "profiles_head": flow_profiles[:10],
        "profiles_tail": flow_profiles[-10:],
        "missing_count": sum(1 for p in flow_profiles if str(p.get("status", "")).startswith("missing")),
        "built_count": sum(1 for p in flow_profiles if p.get("status") == "built"),
        "cached_count": sum(1 for p in flow_profiles if p.get("status") == "cached"),
    }
    flow_profile_path = args.output_dir / "vp_v19_return_volume_feature_profile.json"
    flow_profile_path.write_text(json.dumps(flow_profile, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

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
            "mode": "stream_by_date",
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
            "index_universe_root": str(args.index_universe_root) if args.index_universe_root else None,
        },
        "coverage": {
            "vp_dates": len(vp_dates),
            "daily_rows": int(len(daily)),
            "daily_dates": int(daily["trade_date"].nunique()),
        },
        "flow_profile": flow_profile,
        "index_universe_profile": {"mode": "stream_by_date", "profiles_head": index_profiles[:10], "profiles_tail": index_profiles[-10:]},
        "universe_profiles": dict(universe_profiles),
        "created_size_neutral_signals": created_size_neutral,
        "controls": controls,
        "metrics_rows": int(len(metrics)),
        "top_all_period": json.loads(all_period.head(80).to_json(orient="records")),
    }
    summary_path = args.output_dir / "vp_v19_return_volume_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] wrote {metrics_path}", flush=True)
    print(f"[OK] wrote {summary_path}", flush=True)


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
    size_neutral_base_signals = [x.strip() for x in args.size_neutral_signals.split(",") if x.strip()]
    if args.stream_by_date:
        main_stream_by_date(args, horizons, signals, universes, size_neutral_base_signals)
        return

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
    df = add_fixed_small_flag(df)
    size_neutral_universes = [x.strip() for x in args.size_neutral_universes.split(",") if x.strip()] or universes
    created_size_neutral: list[str] = []
    index_profile: dict[str, Any] = {"status": "batched_by_universe", "universes": {}}
    print(f"[MERGE] base_rows={len(df):,} dates={df['trade_date'].nunique():,} tickers={df['ts_code'].nunique():,}", flush=True)

    controls = [
        col
        for col in ["ln_total_mv", "drift_1d_to_cutoff", "mom_5d_to_cutoff", "mom_20d_to_cutoff", "turnover_rate", "vol_20d"]
        if col in df.columns
    ]
    print(f"[CONTROLS] {controls}", flush=True)

    daily_rows: list[dict[str, object]] = []
    top_sets: dict[tuple[str, str, int, str], dict[str, set[str]]] = defaultdict(dict)
    base_signals = list(signals)
    universe_profiles: dict[str, Any] = {}
    for universe in universes:
        flag = f"universe_{universe}"
        if universe in INDEX_UNIVERSES:
            membership, profile = load_index_universe_membership(args.index_universe_root, vp_dates, universe)
            index_profile["universes"][universe] = profile
            if membership.empty:
                universe_profiles[universe] = {"status": "empty_index_membership"}
                print(f"[UNIVERSE_SKIP] universe={universe} empty_index_membership", flush=True)
                continue
            u_df = df.merge(membership[["ts_code", "trade_date", flag]], on=["ts_code", "trade_date"], how="inner")
        else:
            if flag not in df.columns:
                universe_profiles[universe] = {"status": "missing_flag"}
                print(f"[UNIVERSE_SKIP] universe={universe} missing_flag={flag}", flush=True)
                continue
            u_df = df[df[flag]].copy()
            u_df[flag] = True
        if len(u_df) < args.min_date_rows:
            universe_profiles[universe] = {"status": "too_few_rows", "rows": int(len(u_df))}
            print(f"[UNIVERSE_SKIP] universe={universe} rows={len(u_df):,}", flush=True)
            del u_df
            gc.collect()
            continue

        eval_signals = list(base_signals)
        created_for_universe: list[str] = []
        if universe in size_neutral_universes:
            u_df, created_for_universe = add_size_neutral_signals(u_df, size_neutral_base_signals, [universe])
            for signal in created_for_universe:
                if signal not in eval_signals:
                    eval_signals.append(signal)
                if signal not in created_size_neutral:
                    created_size_neutral.append(signal)

        print(
            f"[UNIVERSE] universe={universe} rows={len(u_df):,} dates={u_df['trade_date'].nunique():,} "
            f"signals={len(eval_signals)} size_neutral={len(created_for_universe)}",
            flush=True,
        )
        rows, tops = evaluate_universe_daily(
            frame=u_df,
            universe=universe,
            signals=eval_signals,
            horizons=horizons,
            controls=controls,
            min_date_rows=args.min_date_rows,
        )
        daily_rows.extend(rows)
        top_sets.update(tops)
        universe_profiles[universe] = {
            "status": "evaluated",
            "rows": int(len(u_df)),
            "dates": int(u_df["trade_date"].nunique()),
            "signals": eval_signals,
            "created_size_neutral_signals": created_for_universe,
            "daily_rows": int(len(rows)),
        }
        del u_df
        gc.collect()

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
            "index_universe_root": str(args.index_universe_root) if args.index_universe_root else None,
        },
        "coverage": {
            "vp_rows": int(len(vp)),
            "vp_dates": int(vp["trade_date"].nunique()),
            "flow_rows": int(len(flow)),
            "flow_dates": int(flow["trade_date"].nunique()),
            "base_merged_rows": int(len(df)),
            "base_merged_dates": int(df["trade_date"].nunique()),
            "base_merged_tickers": int(df["ts_code"].nunique()),
        },
        "flow_profile": flow_profile,
        "index_universe_profile": index_profile,
        "universe_profiles": universe_profiles,
        "created_size_neutral_signals": created_size_neutral,
        "controls": controls,
        "metrics_rows": int(len(metrics)),
        "top_all_period": json.loads(all_period.head(80).to_json(orient="records")),
    }
    summary_path = args.output_dir / "vp_v19_return_volume_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if args.write_merged_panel:
        panel_cols = [
            col
            for col in ["ts_code", "trade_date", "total_mv", "circ_mv", "fixed_small_market_cap"]
            + signals
            + [f"universe_{u}" for u in universes]
            + [f"fwd_{h}d" for h in horizons]
            if col in df.columns
        ]
        panel_path = args.output_dir / "vp_v19_return_volume_merged_panel.parquet"
        df[panel_cols].to_parquet(panel_path, index=False)
        print(f"[OK] wrote {panel_path}", flush=True)
    print(f"[OK] wrote {metrics_path}", flush=True)
    print(f"[OK] wrote {summary_path}", flush=True)


if __name__ == "__main__":
    main()
