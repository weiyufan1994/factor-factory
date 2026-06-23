#!/usr/bin/env python3
"""Research-side evaluation for moneyflow V9/V11/V15/V17 datamart laws.

This script is intentionally outside the formal Factor Forge production loop.
It consumes Data API delivered datamarts and writes research metrics only.
It does not write factor library, official promotion, clean data, or Step objects.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.types as pat
import pyarrow.parquet as pq

from factor_factory.factor_laws.moneyflow.derived_state import _minute_derived_flow_state_adapter


DEFAULT_LAWS = [
    "miller_flow_fisher_quality_cost_boundary_v9a",
    "miller_flow_v9a_hot_money_preposition_filter_v1",
    "miller_flow_v11_repair_absorption_full_v1",
    "miller_flow_v11_repair_absorption_mid_core_v1",
    "miller_flow_v11_first_passage_lite_v1",
    "miller_flow_v15_repair_confirmed_absorption_fp_v1",
    "miller_flow_v17_benchmark_relative_repaired_absorption_v1",
    "miller_flow_v18a_absolute_long_edge_gate_v1",
    "miller_flow_v18b_first_passage_repair_edge_v1",
    "miller_flow_v18c_crowding_filtered_repair_v1",
]

MOMENT_LAWS = {
    "miller_flow_v11_repair_absorption_full_v1",
    "miller_flow_v11_repair_absorption_mid_core_v1",
    "miller_flow_v11_first_passage_lite_v1",
    "miller_flow_v15_repair_confirmed_absorption_fp_v1",
    "miller_flow_v17_benchmark_relative_repaired_absorption_v1",
    "miller_flow_v18a_absolute_long_edge_gate_v1",
    "miller_flow_v18b_first_passage_repair_edge_v1",
    "miller_flow_v18c_crowding_filtered_repair_v1",
}

FLOW_LAWS = {
    "miller_flow_fisher_quality_cost_boundary_v9a",
    "miller_flow_v9a_hot_money_preposition_filter_v1",
}

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

DEFAULT_POLICIES = [
    "daily_top10_equal",
    "rebalance5_top10_equal",
    "top10_dropout30_equal",
    "top10_dropout30_rebalance5_equal",
    "top10_dropout30_confirm2_equal",
    "top10_dropout30_signal_cap",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moments-root", type=Path, required=True)
    parser.add_argument("--flow-root", type=Path, required=True)
    parser.add_argument("--daily-basic-root", type=Path, required=True)
    parser.add_argument("--daily-clean", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--cutoff-time", default="14:50")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--portfolio-horizons", default="1")
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--laws", default=",".join(DEFAULT_LAWS))
    parser.add_argument("--universes", default="full,middle_10_80,middle_20_90,fixed_small_10,fixed_small_20,largest_10,smallest_20,csi800,csi800_csi1000,csi2000,csi_all_share")
    parser.add_argument("--index-universe-root", type=Path)
    parser.add_argument("--portfolio-policies", default=",".join(DEFAULT_POLICIES))
    parser.add_argument("--max-dates", type=int, default=None)
    parser.add_argument("--chunk-by-year", action="store_true")
    return parser.parse_args()


def clean_date(value: Any) -> str:
    return str(value).replace("-", "")[:8]


def cutoff_variants(value: str) -> set[str]:
    raw = str(value).strip()
    if raw.count(":") == 1:
        return {raw, f"{raw}:00"}
    if raw.count(":") == 2 and raw.endswith(":00"):
        return {raw, raw[:-3]}
    return {raw}


def read_partitioned(
    root: Path,
    columns: list[str],
    start: str,
    end: str,
    cutoff_time: str | None = None,
    date_whitelist: set[str] | None = None,
) -> pd.DataFrame:
    if date_whitelist is not None:
        cutoff_set = cutoff_variants(cutoff_time) if cutoff_time else set()
        frames = []
        for date in sorted(date_whitelist):
            date_dir = root / f"trade_date={date}"
            for part in sorted(date_dir.glob("*.parquet")):
                physical = pq.ParquetFile(part).schema_arrow.names
                use_cols = [col for col in columns if col in physical]
                frame = pd.read_parquet(part, columns=use_cols)
                if "trade_date" not in frame.columns:
                    frame["trade_date"] = date
                if cutoff_time and "cutoff_time" in frame.columns:
                    frame = frame[frame["cutoff_time"].astype(str).isin(cutoff_set)]
                frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=columns)
        out = pd.concat(frames, ignore_index=True)
        out["trade_date"] = out["trade_date"].map(clean_date)
        return out

    dataset = ds.dataset(str(root), format="parquet", partitioning="hive")
    names = set(dataset.schema.names)
    trade_date_type = dataset.schema.field("trade_date").type if "trade_date" in names else None
    if trade_date_type is not None and pat.is_integer(trade_date_type):
        filt = (pc.field("trade_date") >= int(start)) & (pc.field("trade_date") <= int(end))
    else:
        filt = (pc.field("trade_date") >= start) & (pc.field("trade_date") <= end)
    if cutoff_time and "cutoff_time" in names:
        cutoff_filter = None
        for item in cutoff_variants(cutoff_time):
            current = pc.field("cutoff_time") == item
            cutoff_filter = current if cutoff_filter is None else (cutoff_filter | current)
        filt = filt & cutoff_filter
    use_cols = [col for col in columns if col in names]
    for key in ("ts_code", "trade_date"):
        if key in names and key not in use_cols:
            use_cols.append(key)
    table = dataset.to_table(columns=use_cols, filter=filt)
    out = table.to_pandas()
    if "trade_date" in out.columns:
        out["trade_date"] = out["trade_date"].map(clean_date)
    return out


def partition_files(root: Path, trade_date: str) -> list[Path]:
    date = clean_date(trade_date)
    date_dir = root / f"trade_date={date}"
    if date_dir.exists():
        return sorted(date_dir.glob("*.parquet"))
    return sorted(root.glob(f"**/*{date}*.parquet"))


def load_index_universe_flags(index_root: Path | None, dates: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = ["universe_id", "trade_date", "ts_code", "in_universe"]
    if index_root is None:
        return pd.DataFrame(columns=["ts_code", "trade_date"]), {"status": "not_requested"}
    index_root = index_root.expanduser()
    if not index_root.exists():
        return pd.DataFrame(columns=["ts_code", "trade_date"]), {"status": "missing_root", "root": str(index_root)}

    frames: list[pd.DataFrame] = []
    missing_dates: list[str] = []
    target_ids = sorted({item for values in INDEX_UNIVERSE_IDS.values() for item in values})
    for date in sorted({clean_date(date) for date in dates}):
        files = partition_files(index_root, date)
        if not files:
            missing_dates.append(date)
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

    if not frames:
        return pd.DataFrame(columns=["ts_code", "trade_date"]), {
            "status": "empty",
            "root": str(index_root),
            "date_count_requested": len(set(dates)),
            "missing_dates_head": missing_dates[:10],
            "missing_dates_tail": missing_dates[-10:],
        }
    memberships = pd.concat(frames, ignore_index=True).drop_duplicates()
    base = memberships[["ts_code", "trade_date"]].drop_duplicates().copy()
    for universe, ids in INDEX_UNIVERSE_IDS.items():
        keys = memberships[memberships["universe_id"].isin(ids)][["ts_code", "trade_date"]].drop_duplicates()
        keys[f"univ_{universe}"] = True
        base = base.merge(keys, on=["ts_code", "trade_date"], how="left")
        base[f"univ_{universe}"] = base[f"univ_{universe}"].fillna(False).astype(bool)
    profile = {
        "status": "loaded",
        "root": str(index_root),
        "date_count_requested": len(set(dates)),
        "date_count_loaded": int(memberships["trade_date"].nunique()),
        "row_count": int(len(memberships)),
        "missing_dates_count": len(missing_dates),
        "missing_dates_head": missing_dates[:10],
        "missing_dates_tail": missing_dates[-10:],
    }
    return base, profile


def load_daily_clean(path: Path, start: str, end: str) -> pd.DataFrame:
    cols = ["ts_code", "trade_date", "close", "pct_chg"]
    frame = pd.read_parquet(path, columns=cols)
    frame["trade_date"] = frame["trade_date"].map(clean_date)
    frame = frame[(frame["trade_date"] >= start) & (frame["trade_date"] <= end)].copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["pct_chg"] = pd.to_numeric(frame["pct_chg"], errors="coerce")
    return frame.dropna(subset=["ts_code", "trade_date", "close"])


def load_daily_controls(root: Path, clean: pd.DataFrame, start: str, end: str, date_whitelist: set[str] | None = None) -> pd.DataFrame:
    columns = [
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "total_mv",
        "circ_mv",
        "float_mv",
        "fixed_small_universe_flag",
        "fixed_small_rank_pct",
    ]
    basic = read_partitioned(root, columns, start, end, date_whitelist=date_whitelist)
    basic["trade_date"] = basic["trade_date"].map(clean_date)
    for col in columns:
        if col not in {"ts_code", "trade_date"} and col in basic.columns:
            basic[col] = pd.to_numeric(basic[col], errors="coerce")
    merged = basic.merge(
        clean[["ts_code", "trade_date", "close", "pct_chg"]],
        on=["ts_code", "trade_date"],
        how="left",
        suffixes=("_basic", ""),
    )
    if "close" not in merged.columns and "close_basic" in merged.columns:
        merged["close"] = merged["close_basic"]
    return merged


def add_forward_returns(clean: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    out = clean.sort_values(["ts_code", "trade_date"]).copy()
    group = out.groupby("ts_code", sort=False)
    for h in horizons:
        out[f"fwd_{h}d"] = group["close"].shift(-h) / out["close"] - 1.0
    return out[["ts_code", "trade_date"] + [f"fwd_{h}d" for h in horizons]]


def add_universes(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    cap = pd.to_numeric(out.get("total_mv"), errors="coerce")
    out["size_rank_pct"] = cap.groupby(out["trade_date"], sort=False).rank(pct=True)
    out["univ_full"] = True
    out["univ_middle_10_80"] = (out["size_rank_pct"] > 0.10) & (out["size_rank_pct"] <= 0.80)
    out["univ_middle_20_90"] = (out["size_rank_pct"] > 0.20) & (out["size_rank_pct"] <= 0.90)
    out["univ_largest_10"] = out["size_rank_pct"] > 0.90
    out["univ_smallest_20"] = out["size_rank_pct"] <= 0.20
    circ = pd.to_numeric(out.get("circ_mv"), errors="coerce")
    fixed_cap = circ.where(circ.notna() & circ.gt(0), cap)
    fixed_eligible = fixed_cap.ge(50000.0)
    fixed_rank_all = fixed_cap.groupby(out["trade_date"], sort=False).rank(pct=True)
    fixed_eligible = fixed_eligible & fixed_rank_all.gt(0.10)
    fixed_rank = pd.Series(np.nan, index=out.index, dtype="float64")
    fixed_rank.loc[fixed_eligible] = fixed_cap.loc[fixed_eligible].groupby(
        out.loc[fixed_eligible, "trade_date"],
        sort=False,
    ).rank(pct=True)
    out["fixed_small_research_rank_pct"] = fixed_rank
    out["univ_fixed_small_10"] = fixed_eligible.fillna(False) & fixed_rank.le(0.10)
    out["univ_fixed_small_20"] = fixed_eligible.fillna(False) & fixed_rank.le(0.20)
    return out


def add_index_universes(frame: pd.DataFrame, index_root: Path | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = frame.copy()
    flags, profile = load_index_universe_flags(index_root, sorted(out["trade_date"].dropna().unique()))
    if not flags.empty:
        out = out.merge(flags, on=["ts_code", "trade_date"], how="left")
    for universe in INDEX_UNIVERSES:
        col = f"univ_{universe}"
        if col not in out.columns:
            out[col] = False
        out[col] = out[col].fillna(False).astype(bool)
    return out, profile


def compute_law(law_id: str, daily: pd.DataFrame, derived: pd.DataFrame) -> pd.DataFrame:
    source = _minute_derived_flow_state_adapter(law_id)
    ns: dict[str, Any] = {}
    exec(source, ns)
    result = ns["compute_factor_from_derived_state"](daily_df=daily, derived_state_df=derived)
    result["law_id"] = law_id
    return result


def spearman_by_date(frame: pd.DataFrame, signal: str, ret_col: str) -> pd.Series:
    values: list[tuple[str, float]] = []
    for date, group in frame.groupby("trade_date", sort=False):
        sub = group[[signal, ret_col]].dropna()
        if len(sub) < 20:
            values.append((str(date), np.nan))
        else:
            values.append((str(date), float(sub[signal].rank().corr(sub[ret_col].rank()))))
    return pd.Series({date: value for date, value in values}, dtype="float64")


def pearson_by_date(frame: pd.DataFrame, signal: str, ret_col: str) -> pd.Series:
    values: list[tuple[str, float]] = []
    for date, group in frame.groupby("trade_date", sort=False):
        sub = group[[signal, ret_col]].dropna()
        if len(sub) < 20:
            values.append((str(date), np.nan))
        else:
            values.append((str(date), float(sub[signal].corr(sub[ret_col]))))
    return pd.Series({date: value for date, value in values}, dtype="float64")


def top_members(group: pd.DataFrame, signal: str, q: float = 0.9) -> set[str]:
    sub = group[["ts_code", signal]].dropna()
    if len(sub) < 20:
        return set()
    threshold = sub[signal].quantile(q)
    return set(sub.loc[sub[signal] >= threshold, "ts_code"].astype(str))


def turnover_rate(frame: pd.DataFrame, signal: str) -> float:
    memberships = []
    for _, group in frame.groupby("trade_date", sort=True):
        members = top_members(group, signal)
        if members:
            memberships.append(members)
    if len(memberships) < 2:
        return np.nan
    vals = []
    prev = memberships[0]
    for cur in memberships[1:]:
        if not prev:
            vals.append(np.nan)
        else:
            vals.append(len(cur.symmetric_difference(prev)) / max(len(prev) + len(cur), 1))
        prev = cur
    return float(np.nanmean(vals))


def evaluate(panel: pd.DataFrame, law_id: str, universes: list[str], horizons: list[int], cost_bps: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    signal = "factor_value"
    for universe in universes:
        flag = f"univ_{universe}"
        if flag not in panel.columns:
            continue
        scoped = panel[panel[flag].fillna(False)].copy()
        if len(scoped) < 1000:
            continue
        scoped["date_n"] = scoped.groupby("trade_date")["ts_code"].transform("count")
        scoped = scoped[scoped["date_n"] >= 50]
        turn = turnover_rate(scoped, signal)
        for h in horizons:
            ret_col = f"fwd_{h}d"
            ic = spearman_by_date(scoped, signal, ret_col)
            pearson_ic = pearson_by_date(scoped, signal, ret_col)
            top_daily = []
            all_daily = []
            for _, group in scoped.groupby("trade_date", sort=False):
                sub = group[[signal, ret_col]].dropna()
                if len(sub) < 50:
                    continue
                threshold = sub[signal].quantile(0.9)
                top = sub[sub[signal] >= threshold][ret_col].mean()
                all_ret = sub[ret_col].mean()
                top_daily.append(top)
                all_daily.append(all_ret)
            top_mean = float(np.nanmean(top_daily)) if top_daily else np.nan
            all_mean = float(np.nanmean(all_daily)) if all_daily else np.nan
            cost = (cost_bps / 10000.0) * (turn if math.isfinite(turn) else np.nan)
            rows.append(
                {
                    "law_id": law_id,
                    "universe": universe,
                    "horizon": h,
                    "row_count": int(len(scoped)),
                    "date_count": int(scoped["trade_date"].nunique()),
                    "pearson_ic_mean": float(pearson_ic.mean()),
                    "pearson_ic_tstat": float(pearson_ic.mean() / (pearson_ic.std(ddof=1) / math.sqrt(pearson_ic.count()))) if pearson_ic.count() > 2 and pearson_ic.std(ddof=1) else np.nan,
                    "rank_ic_mean": float(ic.mean()),
                    "rank_ic_tstat": float(ic.mean() / (ic.std(ddof=1) / math.sqrt(ic.count()))) if ic.count() > 2 and ic.std(ddof=1) else np.nan,
                    "top_decile_return": top_mean,
                    "universe_mean_return": all_mean,
                    "top_decile_excess": top_mean - all_mean,
                    "turnover": turn,
                    "cost_estimate": cost,
                    "net_top_decile_excess": (top_mean - all_mean - cost) if math.isfinite(cost) else np.nan,
                }
            )
    return rows


def policy_config(policy: str) -> dict[str, Any]:
    configs = {
        "daily_top10_equal": {"buy_pct": 0.10, "drop_pct": 0.10, "rebalance_every": 1, "confirm_days": 0, "weighting": "equal"},
        "rebalance5_top10_equal": {"buy_pct": 0.10, "drop_pct": 0.10, "rebalance_every": 5, "confirm_days": 0, "weighting": "equal"},
        "top10_dropout30_equal": {"buy_pct": 0.10, "drop_pct": 0.30, "rebalance_every": 1, "confirm_days": 0, "weighting": "equal"},
        "top10_dropout30_rebalance5_equal": {"buy_pct": 0.10, "drop_pct": 0.30, "rebalance_every": 5, "confirm_days": 0, "weighting": "equal"},
        "top10_dropout30_confirm2_equal": {"buy_pct": 0.10, "drop_pct": 0.30, "rebalance_every": 1, "confirm_days": 2, "weighting": "equal"},
        "top10_dropout30_signal_cap": {"buy_pct": 0.10, "drop_pct": 0.30, "rebalance_every": 1, "confirm_days": 0, "weighting": "signal_cap"},
    }
    return configs[policy]


def assign_weights(selected: pd.DataFrame, weighting: str, cap: float = 0.02) -> pd.Series:
    if selected.empty:
        return pd.Series(dtype="float64")
    if weighting == "signal_cap":
        signal = pd.to_numeric(selected["factor_value"], errors="coerce")
        raw = (signal - signal.min()).clip(lower=0.0) + 1e-9
        weights = raw / raw.sum() if raw.sum() > 0 else pd.Series(1.0 / len(selected), index=selected.index)
        weights = weights.clip(upper=cap)
        if weights.sum() > 0:
            weights = weights / weights.sum()
        return weights
    return pd.Series(1.0 / len(selected), index=selected.index)


def simulate_policy(
    panel: pd.DataFrame,
    law_id: str,
    universe: str,
    horizon: int,
    policy: str,
    cost_bps: float,
) -> dict[str, Any] | None:
    flag = f"univ_{universe}"
    ret_col = f"fwd_{horizon}d"
    if flag not in panel.columns or ret_col not in panel.columns:
        return None
    cfg = policy_config(policy)
    scoped = panel[panel[flag].fillna(False)].dropna(subset=["factor_value", ret_col]).copy()
    if scoped.empty:
        return None
    scoped["rank_pct_desc"] = scoped.groupby("trade_date")["factor_value"].rank(ascending=False, pct=True)
    dates = sorted(scoped["trade_date"].unique())
    if len(dates) < 20:
        return None
    day_groups = [(str(date), group.sort_values("rank_pct_desc").copy()) for date, group in scoped.groupby("trade_date", sort=True)]
    return simulate_policy_prepared(day_groups, law_id, universe, horizon, policy, cost_bps)


def simulate_policy_prepared(
    day_groups: list[tuple[str, pd.DataFrame]],
    law_id: str,
    universe: str,
    horizon: int,
    policy: str,
    cost_bps: float,
) -> dict[str, Any] | None:
    cfg = policy_config(policy)
    if len(day_groups) < 20:
        return None

    holdings: set[str] = set()
    prev_buy_zone: set[str] = set()
    rows: list[dict[str, Any]] = []
    target_n_history: list[int] = []
    ret_col = f"fwd_{horizon}d"
    for idx, (date, day) in enumerate(day_groups):
        if len(day) < 50:
            continue
        target_n = max(1, int(math.ceil(len(day) * cfg["buy_pct"])))
        target_n_history.append(target_n)
        current_ranks = dict(zip(day["ts_code"].astype(str), day["rank_pct_desc"], strict=False))
        buy_zone = set(day.loc[day["rank_pct_desc"] <= cfg["buy_pct"], "ts_code"].astype(str))
        do_rebalance = (idx % int(cfg["rebalance_every"])) == 0
        if do_rebalance:
            keep = {code for code in holdings if current_ranks.get(code, 1.0) <= cfg["drop_pct"]}
            eligible = day
            if cfg["confirm_days"] > 0:
                eligible = eligible[eligible["ts_code"].astype(str).isin(prev_buy_zone)]
            ordered = eligible["ts_code"].astype(str).tolist()
            new_holdings = list(keep)
            seen = set(new_holdings)
            for code in ordered:
                if code in seen:
                    continue
                new_holdings.append(code)
                seen.add(code)
                if len(new_holdings) >= target_n:
                    break
            holdings_next = set(new_holdings[:target_n])
        else:
            holdings_next = {code for code in holdings if code in current_ranks}
        selected = day[day["ts_code"].astype(str).isin(holdings_next)].copy()
        if selected.empty:
            holdings = holdings_next
            prev_buy_zone = buy_zone
            continue
        weights = assign_weights(selected, cfg["weighting"])
        gross_return = float((pd.to_numeric(selected[ret_col], errors="coerce") * weights).sum())
        sold = holdings - holdings_next
        bought = holdings_next - holdings
        turnover = (len(sold) + len(bought)) / max(len(holdings) + len(holdings_next), 1)
        cost = (cost_bps / 10000.0) * turnover
        rows.append(
            {
                "trade_date": date,
                "gross_return": gross_return,
                "turnover": turnover,
                "cost": cost,
                "net_return": gross_return - cost,
                "holding_count": len(holdings_next),
                "target_count": target_n,
            }
        )
        holdings = holdings_next
        prev_buy_zone = buy_zone
    if len(rows) < 20:
        return None
    daily = pd.DataFrame(rows)
    net = pd.to_numeric(daily["net_return"], errors="coerce")
    gross = pd.to_numeric(daily["gross_return"], errors="coerce")
    nav = (1.0 + net.fillna(0.0)).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    return {
        "law_id": law_id,
        "universe": universe,
        "horizon": horizon,
        "policy": policy,
        "date_count": int(len(daily)),
        "avg_holding_count": float(daily["holding_count"].mean()),
        "avg_target_count": float(np.mean(target_n_history)) if target_n_history else np.nan,
        "gross_return_mean": float(gross.mean()),
        "net_return_mean": float(net.mean()),
        "turnover": float(daily["turnover"].mean()),
        "cost_mean": float(daily["cost"].mean()),
        "net_hit_rate": float((net > 0).mean()),
        "gross_hit_rate": float((gross > 0).mean()),
        "net_sharpe_proxy": float(net.mean() / net.std(ddof=1) * math.sqrt(252 / max(horizon, 1))) if net.std(ddof=1) else np.nan,
        "max_drawdown_proxy": float(drawdown.min()),
        "nav_final_proxy": float(nav.iloc[-1]),
    }


def evaluate_portfolio_policies(
    panel: pd.DataFrame,
    law_id: str,
    universes: list[str],
    horizons: list[int],
    policies: list[str],
    cost_bps: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for universe in universes:
        flag = f"univ_{universe}"
        if flag not in panel.columns:
            continue
        for horizon in horizons:
            ret_col = f"fwd_{horizon}d"
            if ret_col not in panel.columns:
                continue
            scoped = panel[panel[flag].fillna(False)].dropna(subset=["factor_value", ret_col]).copy()
            if scoped.empty:
                continue
            scoped["rank_pct_desc"] = scoped.groupby("trade_date")["factor_value"].rank(ascending=False, pct=True)
            day_groups = [(str(date), group.sort_values("rank_pct_desc").copy()) for date, group in scoped.groupby("trade_date", sort=True)]
            for policy in policies:
                result = simulate_policy_prepared(day_groups, law_id, universe, horizon, policy, cost_bps)
                if result:
                    rows.append(result)
    return rows


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    text = frame.copy()
    for col in text.columns:
        if pd.api.types.is_float_dtype(text[col]):
            text[col] = text[col].map(lambda x: "" if pd.isna(x) else f"{x:.6g}")
    headers = [str(col) for col in text.columns]
    rows = [[str(value) for value in row] for row in text.to_numpy().tolist()]
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)) + " |"
    lines = [fmt(headers), "| " + " | ".join("-" * width for width in widths) + " |"]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def year_chunks(start: str, end: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        chunk_start = max(start, f"{year}0101")
        chunk_end = min(end, f"{year}1231")
        if chunk_start <= chunk_end:
            chunks.append((chunk_start, chunk_end))
    return chunks


def evaluate_window(
    args: argparse.Namespace,
    clean_all: pd.DataFrame,
    start: str,
    end: str,
    horizons: list[int],
    laws: list[str],
    universes: list[str],
    policies: list[str],
    sampled: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    clean = clean_all[(clean_all["trade_date"] >= start) & (clean_all["trade_date"] <= end)].copy()
    if sampled:
        clean = clean[clean["trade_date"].isin(sampled)].copy()
    if clean.empty:
        return [], {"start_date": start, "end_date": end, "daily_clean_rows": 0}
    daily = load_daily_controls(args.daily_basic_root, clean, start, end, date_whitelist=sampled)
    forward = add_forward_returns(clean, horizons)
    daily = daily.merge(forward, on=["ts_code", "trade_date"], how="left")
    daily = add_universes(daily)
    daily, index_profile = add_index_universes(daily, args.index_universe_root)

    moment_cols = [
        "ts_code", "trade_date", "cutoff_time", "signed_flow_imbalance", "signed_amount_skew",
        "signed_amount_excess_kurtosis", "signed_flow_tail_asymmetry", "large_small_signed_spread",
        "amount_hhi", "amount_top5_share", "amount_entropy", "ret_skew", "ret_excess_kurtosis",
        "ret_tail_asymmetry", "realized_vol", "realized_vol_of_vol", "positive_signed_amount_share",
        "negative_signed_amount_share",
    ]
    flow_cols = [
        "ts_code", "trade_date", "cutoff_time", "signed_amount_sum", "gross_amount_sum",
        "net_flow_ratio", "large_net_flow_ratio_abs", "large_net_flow_ratio_rel",
        "small_net_flow_ratio_abs", "small_net_flow_ratio_rel", "amount_hhi", "flow_hhi",
        "intraday_ret_std", "intraday_abs_ret_sum", "intraday_noise", "minute_count",
        "impact_proxy", "elasticity_proxy", "amount_to_own_history", "amount_to_market_history",
        "amount_zscore_ewma",
    ]
    need_moments = any(law in MOMENT_LAWS for law in laws)
    need_flow = any(law in FLOW_LAWS for law in laws)
    moments = read_partitioned(args.moments_root, moment_cols, start, end, args.cutoff_time, date_whitelist=sampled) if need_moments else pd.DataFrame()
    flow = read_partitioned(args.flow_root, flow_cols, start, end, args.cutoff_time, date_whitelist=sampled) if need_flow else pd.DataFrame()

    metrics: list[dict[str, Any]] = []
    portfolio_metrics: list[dict[str, Any]] = []
    portfolio_horizons = [int(x) for x in str(getattr(args, "portfolio_horizons", "1")).split(",") if x.strip()]
    window_summary: dict[str, Any] = {
        "start_date": start,
        "end_date": end,
        "daily_rows": int(len(daily)),
        "moment_rows": int(len(moments)),
        "flow_rows": int(len(flow)),
        "index_universe_profile": index_profile,
    }
    for law_id in laws:
        print(f"[{start}-{end}] computing law {law_id}", flush=True)
        if law_id in MOMENT_LAWS:
            derived = moments
        elif law_id in FLOW_LAWS:
            derived = flow
        else:
            window_summary.setdefault("skipped_laws", []).append({"law_id": law_id, "reason": "unknown_source_datamart"})
            continue
        factor = compute_law(law_id, daily, derived)
        panel = factor.merge(daily, on=["ts_code", "trade_date"], how="left")
        panel = panel.dropna(subset=["factor_value"])
        window_summary[law_id] = {
            "factor_rows": int(len(panel)),
            "factor_dates": int(panel["trade_date"].nunique()) if len(panel) else 0,
            "factor_non_null": int(panel["factor_value"].notna().sum()) if len(panel) else 0,
        }
        metrics.extend(evaluate(panel, law_id, universes, horizons, args.cost_bps))
        print(f"[{start}-{end}] portfolio policies for {law_id}", flush=True)
        portfolio_metrics.extend(evaluate_portfolio_policies(panel, law_id, universes, portfolio_horizons, policies, args.cost_bps))
    return metrics, portfolio_metrics, window_summary


def aggregate_chunk_metrics(metrics_df: pd.DataFrame) -> pd.DataFrame:
    if metrics_df.empty or "chunk_start" not in metrics_df.columns:
        return metrics_df
    grouped: list[dict[str, Any]] = []
    keys = ["law_id", "universe", "horizon"]
    value_cols = [
        "rank_ic_mean",
        "pearson_ic_mean",
        "top_decile_return",
        "universe_mean_return",
        "top_decile_excess",
        "turnover",
        "cost_estimate",
        "net_top_decile_excess",
    ]
    for key, group in metrics_df.groupby(keys, sort=False):
        weights = pd.to_numeric(group["date_count"], errors="coerce").fillna(0.0)
        row = dict(zip(keys, key, strict=True))
        row["row_count"] = int(pd.to_numeric(group["row_count"], errors="coerce").fillna(0).sum())
        row["date_count"] = int(weights.sum())
        for col in value_cols:
            vals = pd.to_numeric(group[col], errors="coerce")
            valid = vals.notna() & (weights > 0)
            row[col] = float(np.average(vals[valid], weights=weights[valid])) if valid.any() else np.nan
        ic_values = pd.to_numeric(group["rank_ic_mean"], errors="coerce")
        row["rank_ic_tstat"] = (
            float(ic_values.mean() / (ic_values.std(ddof=1) / math.sqrt(ic_values.count())))
            if ic_values.count() > 2 and ic_values.std(ddof=1)
            else np.nan
        )
        pearson_values = pd.to_numeric(group["pearson_ic_mean"], errors="coerce")
        row["pearson_ic_tstat"] = (
            float(pearson_values.mean() / (pearson_values.std(ddof=1) / math.sqrt(pearson_values.count())))
            if pearson_values.count() > 2 and pearson_values.std(ddof=1)
            else np.nan
        )
        grouped.append(row)
    return pd.DataFrame(grouped)


def aggregate_chunk_portfolio_metrics(portfolio_df: pd.DataFrame) -> pd.DataFrame:
    if portfolio_df.empty or "chunk_start" not in portfolio_df.columns:
        return portfolio_df
    grouped: list[dict[str, Any]] = []
    keys = ["law_id", "universe", "horizon", "policy"]
    value_cols = [
        "avg_holding_count",
        "avg_target_count",
        "gross_return_mean",
        "net_return_mean",
        "turnover",
        "cost_mean",
        "net_hit_rate",
        "gross_hit_rate",
        "net_sharpe_proxy",
        "max_drawdown_proxy",
        "nav_final_proxy",
    ]
    for key, group in portfolio_df.groupby(keys, sort=False):
        weights = pd.to_numeric(group["date_count"], errors="coerce").fillna(0.0)
        row = dict(zip(keys, key, strict=True))
        row["date_count"] = int(weights.sum())
        for col in value_cols:
            vals = pd.to_numeric(group[col], errors="coerce")
            valid = vals.notna() & (weights > 0)
            if col in {"max_drawdown_proxy"}:
                row[col] = float(vals.min()) if vals.notna().any() else np.nan
            elif col in {"nav_final_proxy"}:
                row[col] = float(vals.prod()) if vals.notna().any() else np.nan
            else:
                row[col] = float(np.average(vals[valid], weights=weights[valid])) if valid.any() else np.nan
        grouped.append(row)
    return pd.DataFrame(grouped)


def main() -> int:
    args = parse_args()
    started = time.time()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    start = clean_date(args.start_date)
    end = clean_date(args.end_date)
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    laws = [x.strip() for x in args.laws.split(",") if x.strip()]
    universes = [x.strip() for x in args.universes.split(",") if x.strip()]
    policies = [x.strip() for x in args.portfolio_policies.split(",") if x.strip()]
    portfolio_horizons = [int(x) for x in args.portfolio_horizons.split(",") if x.strip()]

    clean_all = load_daily_clean(args.daily_clean, start, end)
    sampled: set[str] | None = None
    if args.max_dates:
        dates = sorted(clean_all["trade_date"].unique())
        sampled_idx = np.linspace(0, len(dates) - 1, args.max_dates).round().astype(int)
        sampled = {dates[int(i)] for i in sampled_idx}
        start = min(sampled)
        end = max(sampled)

    metrics: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {
        "started_at": started,
        "start_date": start,
        "end_date": end,
        "horizons": horizons,
        "portfolio_horizons": portfolio_horizons,
        "laws": laws,
        "universes": universes,
        "portfolio_policies": policies,
        "daily_clean_rows": int(len(clean_all)),
        "chunk_by_year": bool(args.chunk_by_year),
        "side_effects": {
            "clean_data_started": False,
            "search_worker_started": False,
            "official_promotion_started": False,
            "factor_forge_artifacts_written": False,
        },
    }
    portfolio_metrics: list[dict[str, Any]] = []
    if args.chunk_by_year:
        chunk_summaries = []
        for chunk_start, chunk_end in year_chunks(start, end):
            print(f"chunk_start={chunk_start} chunk_end={chunk_end}", flush=True)
            chunk_metrics, chunk_portfolio_metrics, chunk_summary = evaluate_window(
                args, clean_all, chunk_start, chunk_end, horizons, laws, universes, policies, sampled=sampled
            )
            for row in chunk_metrics:
                row["chunk_start"] = chunk_start
                row["chunk_end"] = chunk_end
            for row in chunk_portfolio_metrics:
                row["chunk_start"] = chunk_start
                row["chunk_end"] = chunk_end
            metrics.extend(chunk_metrics)
            portfolio_metrics.extend(chunk_portfolio_metrics)
            chunk_summaries.append(chunk_summary)
        summaries["chunks"] = chunk_summaries
    else:
        metrics, portfolio_metrics, window_summary = evaluate_window(
            args, clean_all, start, end, horizons, laws, universes, policies, sampled=sampled
        )
        summaries.update(window_summary)

    metrics_df = pd.DataFrame(metrics)
    portfolio_df = pd.DataFrame(portfolio_metrics)
    chunk_metrics_path = args.output_dir / "moneyflow_v11_datamart_chunk_metrics.csv"
    if args.chunk_by_year and not metrics_df.empty:
        metrics_df.to_csv(chunk_metrics_path, index=False)
        metrics_df = aggregate_chunk_metrics(metrics_df)
        summaries["chunk_metrics"] = str(chunk_metrics_path)
    chunk_portfolio_path = args.output_dir / "moneyflow_v11_portfolio_policy_chunk_metrics.csv"
    if args.chunk_by_year and not portfolio_df.empty:
        portfolio_df.to_csv(chunk_portfolio_path, index=False)
        portfolio_df = aggregate_chunk_portfolio_metrics(portfolio_df)
        summaries["chunk_portfolio_metrics"] = str(chunk_portfolio_path)
    metrics_path = args.output_dir / "moneyflow_v11_datamart_metrics.csv"
    portfolio_path = args.output_dir / "moneyflow_v11_portfolio_policy_metrics.csv"
    summary_path = args.output_dir / "moneyflow_v11_datamart_summary.json"
    md_path = args.output_dir / "moneyflow_v11_datamart_report.md"
    metrics_df.to_csv(metrics_path, index=False)
    portfolio_df.to_csv(portfolio_path, index=False)
    summaries["elapsed_seconds"] = time.time() - started
    summaries["metric_rows"] = int(len(metrics_df))
    summaries["portfolio_metric_rows"] = int(len(portfolio_df))
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    if not metrics_df.empty:
        top = metrics_df.sort_values(["net_top_decile_excess", "rank_ic_mean"], ascending=False).head(30)
        md = [
            "# Moneyflow V11 Datamart Research",
            "",
            "Research-side evaluation only. No official promotion, clean data, search worker, or Factor Forge formal artifacts.",
            "",
            "## Top Rows",
            "",
            dataframe_to_markdown(top),
            "",
        ]
        if not portfolio_df.empty:
            policy_top = portfolio_df.sort_values(["net_return_mean", "net_sharpe_proxy"], ascending=False).head(40)
            md.extend([
                "## Portfolio Policy Top Rows",
                "",
                dataframe_to_markdown(policy_top),
                "",
            ])
    else:
        md = ["# Moneyflow V11 Datamart Research", "", "No metrics produced."]
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({
        "verdict": "ACCEPT" if metrics else "BLOCK",
        "summary": str(summary_path),
        "metrics": str(metrics_path),
        "portfolio_metrics": str(portfolio_path),
    }, indent=2))
    return 0 if metrics else 1


if __name__ == "__main__":
    raise SystemExit(main())
