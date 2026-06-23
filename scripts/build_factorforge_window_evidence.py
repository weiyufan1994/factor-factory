#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.parser import parse_formula, resolve_formula_fields_for_schema


REQUIRED_INTERVALS = [
    ("2018_2020", "2018-01-01", "2020-12-31"),
    ("2021", "2021-01-01", "2021-12-31"),
    ("2022_04_2022_12", "2022-04-01", "2022-12-31"),
    ("2023_08_13_2024_03", "2023-08-13", "2024-03-31"),
    ("2024_03_2024_12", "2024-03-01", "2024-12-31"),
]

DEFAULT_SUBSAMPLES = [
    ("is_sample_2016_2017", "2016-01-01", "2017-12-31"),
    ("is_sample_2018_2020", "2018-01-01", "2020-12-31"),
    ("is_sample_2021", "2021-01-01", "2021-12-31"),
    ("is_sample_2022", "2022-01-01", "2022-12-31"),
    ("is_sample_2023_to_2024q1", "2023-01-01", "2024-03-31"),
    ("is_sample_2024q1_to_2025_holdout_edge", "2024-03-01", "2025-07-11"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Factor Forge full IS / IS subsample / OOS evidence.")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--factor-id", required=True)
    parser.add_argument("--formula", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--daily-clean", type=Path, default=Path("/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet"))
    parser.add_argument("--full-is-start", default="2016-01-01")
    parser.add_argument("--full-is-end", default="2025-07-11")
    parser.add_argument("--oos-start", default="2025-07-11")
    parser.add_argument("--group-count", type=int, default=10)
    return parser.parse_args()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str), errors="coerce")


def parquet_columns(path: Path) -> list[str]:
    return list(pq.read_schema(path).names)


def load_daily(path: Path, start: str, formula_ir: dict[str, Any]) -> pd.DataFrame:
    available = set(parquet_columns(path))
    resolved_fields = {
        str(field)
        for field in (formula_ir.get("resolved_fields") or {}).values()
        if field
    }
    columns = ["ts_code", "trade_date", "close", "pct_chg", *sorted(resolved_fields)]
    columns = [column for column in dict.fromkeys(columns) if column in available]
    missing_required = {"ts_code", "trade_date", "close", "pct_chg"} - set(columns)
    if missing_required:
        raise SystemExit(f"BLOCK_WINDOW_EVIDENCE_MISSING_DAILY_COLUMNS:{sorted(missing_required)}")
    frame = pd.read_parquet(path, columns=columns)
    frame["trade_date"] = clean_dates(frame["trade_date"])
    frame = frame.loc[frame["trade_date"] >= pd.Timestamp(start)].copy()
    frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    for col in [column for column in frame.columns if column not in {"ts_code", "trade_date"}]:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def add_forward_returns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[["ts_code", "trade_date", "close", "pct_chg"]].copy()
    out["future_return_1d"] = out.groupby("ts_code", sort=False)["close"].shift(-1) / out["close"] - 1.0
    out["future_return_5d"] = out.groupby("ts_code", sort=False)["close"].shift(-5) / out["close"] - 1.0
    return out


def date_ic(frame: pd.DataFrame, label: str, method: str) -> pd.Series:
    rows: list[tuple[pd.Timestamp, float]] = []
    for dt, group in frame.groupby("trade_date", sort=True):
        work = group[["factor_value", label]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) < 20:
            rows.append((dt, np.nan))
            continue
        rows.append((dt, float(work["factor_value"].corr(work[label], method=method))))
    return pd.Series(dict(rows)).sort_index()


def ir(series: pd.Series) -> float | None:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 2:
        return None
    std = clean.std()
    if not np.isfinite(std) or std == 0:
        return None
    return float(clean.mean() / std)


def max_drawdown(nav: pd.Series) -> float | None:
    clean = nav.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return None
    dd = clean / clean.cummax() - 1.0
    return float(dd.min())


def annualized_sharpe(ret: pd.Series, periods: float = 252.0) -> float | None:
    clean = ret.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 2:
        return None
    std = clean.std()
    if not np.isfinite(std) or std == 0:
        return None
    return float(clean.mean() / std * math.sqrt(periods))


def sign_changes(values: list[float | None]) -> int | None:
    clean = [float(v) for v in values if v is not None and np.isfinite(float(v))]
    if len(clean) < 3:
        return None
    diffs = np.diff(clean)
    signs = np.sign(diffs[diffs != 0])
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] != signs[:-1]))


def quantile_evidence(split: pd.DataFrame, group_count: int) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    ret_rows: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    turnover_rows: list[dict[str, Any]] = []
    nav = {f"Q{i}": 1.0 for i in range(1, group_count + 1)}
    nav["LS_QTOP_QBOT"] = 1.0
    prev_sets: dict[str, set[str]] = {}
    for dt, group in split.groupby("trade_date", sort=True):
        work = group[["ts_code", "factor_value", "future_return_1d"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) < group_count * 20:
            continue
        ranks = work["factor_value"].rank(method="first")
        buckets = pd.qcut(ranks, group_count, labels=False, duplicates="drop")
        if buckets.nunique() < group_count:
            continue
        ret_row: dict[str, Any] = {"trade_date": pd.Timestamp(dt).strftime("%Y-%m-%d")}
        sets: dict[str, set[str]] = {}
        rets: dict[str, float] = {}
        for i in range(group_count):
            key = f"Q{i + 1}"
            members = work.index[buckets == i]
            codes = set(work.loc[members, "ts_code"].astype(str))
            sets[key] = codes
            value = float(work.loc[members, "future_return_1d"].mean())
            rets[key] = value
            ret_row[f"{key}_ret_1d"] = value
            nav[key] *= 1.0 + (0.0 if not np.isfinite(value) else value)
        top = f"Q{group_count}"
        bottom = "Q1"
        ls_ret = rets[top] - rets[bottom]
        ret_row["LS_QTOP_QBOT_ret_1d"] = ls_ret
        nav["LS_QTOP_QBOT"] *= 1.0 + (0.0 if not np.isfinite(ls_ret) else ls_ret)
        ret_rows.append(ret_row)
        nav_rows.append({"trade_date": ret_row["trade_date"], **nav})
        trow: dict[str, Any] = {"trade_date": ret_row["trade_date"]}
        for key in [bottom, top]:
            prev = prev_sets.get(key)
            if prev:
                cur = sets[key]
                trow[f"{key}_turnover"] = 1.0 - len(prev & cur) / max(len(cur), 1)
        cur_ls = sets[bottom] | sets[top]
        prev_ls = prev_sets.get("LS")
        if prev_ls:
            trow["LS_turnover"] = 1.0 - len(prev_ls & cur_ls) / max(len(cur_ls), 1)
        turnover_rows.append(trow)
        prev_sets = {**sets, "LS": cur_ls}
    returns = pd.DataFrame(ret_rows)
    navs = pd.DataFrame(nav_rows)
    turnover = pd.DataFrame(turnover_rows)
    means: dict[str, float | None] = {}
    for i in range(1, group_count + 1):
        col = f"Q{i}_ret_1d"
        means[f"Q{i}"] = float(returns[col].mean()) if col in returns and len(returns) else None
    top_key = f"Q{group_count}"
    spread = None
    if means.get(top_key) is not None and means.get("Q1") is not None:
        spread = float(means[top_key] - means["Q1"])  # type: ignore[operator]
    ls_col = "LS_QTOP_QBOT_ret_1d"
    ls_ret = returns[ls_col] if ls_col in returns else pd.Series(dtype="float64")
    top_ret = returns[f"{top_key}_ret_1d"] if f"{top_key}_ret_1d" in returns else pd.Series(dtype="float64")
    top_nav = navs[top_key] if top_key in navs else pd.Series(dtype="float64")
    ls_nav = navs["LS_QTOP_QBOT"] if "LS_QTOP_QBOT" in navs else pd.Series(dtype="float64")
    summary = {
        "group_count": group_count,
        "rebalance_points": int(len(returns)),
        "top_group": top_key,
        "bottom_group": "Q1",
        "quantile_mean_1d": means,
        "top_minus_bottom_mean_1d": spread,
        "top_minus_bottom_bps_1d": None if spread is None else spread * 10000.0,
        "top_group_mean_1d": means.get(top_key),
        "bottom_group_mean_1d": means.get("Q1"),
        "top_group_annual_return": None if means.get(top_key) is None else float(means[top_key] * 252.0),  # type: ignore[index,operator]
        "top_group_sharpe": annualized_sharpe(top_ret),
        "top_group_max_drawdown": max_drawdown(top_nav),
        "ls_sharpe": annualized_sharpe(ls_ret),
        "ls_final_nav": float(ls_nav.iloc[-1]) if len(ls_nav) else None,
        "top_group_final_nav": float(top_nav.iloc[-1]) if len(top_nav) else None,
        "top_turnover_mean": float(turnover[f"{top_key}_turnover"].mean()) if f"{top_key}_turnover" in turnover else None,
        "bottom_turnover_mean": float(turnover["Q1_turnover"].mean()) if "Q1_turnover" in turnover else None,
        "ls_turnover_mean": float(turnover["LS_turnover"].mean()) if "LS_turnover" in turnover else None,
        "monotonicity_sign_changes": sign_changes([means.get(f"Q{i}") for i in range(1, group_count + 1)]),
    }
    return summary, {"returns": returns, "nav": navs, "turnover": turnover}


def split_frame(merged: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    mask = (merged["trade_date"] >= pd.Timestamp(start)) & (merged["trade_date"] <= pd.Timestamp(end))
    return merged.loc[mask].copy()


def summarize_split(merged: pd.DataFrame, label: str, start: str, end: str, group_count: int, out_dir: Path) -> dict[str, Any]:
    split = split_frame(merged, start, end)
    date_count = int(split["trade_date"].nunique()) if len(split) else 0
    ticker_count = int(split["ts_code"].nunique()) if len(split) else 0
    factor_non_null = int(split["factor_value"].notna().sum())
    total_rows = int(len(split))
    pearson_1d = date_ic(split, "future_return_1d", "pearson")
    rank_1d = date_ic(split, "future_return_1d", "spearman")
    pearson_5d = date_ic(split, "future_return_5d", "pearson")
    rank_5d = date_ic(split, "future_return_5d", "spearman")
    q_summary, frames = quantile_evidence(split, group_count)
    frame_paths: dict[str, str] = {}
    for name, frame in frames.items():
        path = out_dir / f"{label}_{name}.csv"
        frame.to_csv(path, index=False)
        frame_paths[name] = str(path)
    return {
        "label": label,
        "start": start,
        "end": end,
        "actual_start": split["trade_date"].min().strftime("%Y-%m-%d") if len(split) else None,
        "actual_end": split["trade_date"].max().strftime("%Y-%m-%d") if len(split) else None,
        "row_count": total_rows,
        "date_count": date_count,
        "ticker_count": ticker_count,
        "factor_non_null": factor_non_null,
        "factor_coverage": factor_non_null / total_rows if total_rows else None,
        "active_date_count": int((split.groupby("trade_date")["factor_value"].apply(lambda s: s.notna().sum()) >= 20).sum()) if len(split) else 0,
        "pearson_ic_mean_1d": float(pearson_1d.mean()) if len(pearson_1d.dropna()) else None,
        "pearson_ic_ir_1d": ir(pearson_1d),
        "rank_ic_mean_1d": float(rank_1d.mean()) if len(rank_1d.dropna()) else None,
        "rank_ic_ir_1d": ir(rank_1d),
        "pearson_ic_mean_5d": float(pearson_5d.mean()) if len(pearson_5d.dropna()) else None,
        "pearson_ic_ir_5d": ir(pearson_5d),
        "rank_ic_mean_5d": float(rank_5d.mean()) if len(rank_5d.dropna()) else None,
        "rank_ic_ir_5d": ir(rank_5d),
        "ic_obs_1d": int(rank_1d.dropna().shape[0]),
        "ic_obs_5d": int(rank_5d.dropna().shape[0]),
        "quantile": q_summary,
        "artifact_paths": frame_paths,
    }


def coverage_proof(trading_dates: pd.Series, full_start: str, full_end: str, samples: list[tuple[str, str, str]]) -> dict[str, Any]:
    full_dates = pd.Series(pd.to_datetime(sorted(set(trading_dates))))
    full_dates = full_dates[(full_dates >= pd.Timestamp(full_start)) & (full_dates <= pd.Timestamp(full_end))]
    covered = pd.Series(False, index=full_dates.index)
    sample_items = []
    for label, start, end in samples:
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        mask = (full_dates >= pd.Timestamp(start)) & (full_dates <= pd.Timestamp(end))
        covered = covered | mask
        sample_dates = full_dates[mask]
        sample_items.append({
            "label": label,
            "start": start,
            "end": end,
            "trading_day_count": int(mask.sum()),
            "at_least_one_calendar_year": end_ts >= start_ts + pd.DateOffset(years=1) - pd.DateOffset(days=1),
            "actual_start": sample_dates.min().strftime("%Y-%m-%d") if len(sample_dates) else None,
            "actual_end": sample_dates.max().strftime("%Y-%m-%d") if len(sample_dates) else None,
        })
    uncovered_dates = full_dates[~covered]
    interval_hits = []
    for label, start, end in REQUIRED_INTERVALS:
        target = full_dates[(full_dates >= pd.Timestamp(start)) & (full_dates <= pd.Timestamp(end))]
        target_covered = covered.loc[target.index] if len(target) else pd.Series(dtype=bool)
        interval_hits.append({
            "label": label,
            "start": start,
            "end": end,
            "target_trading_day_count": int(len(target)),
            "covered_trading_day_count": int(target_covered.sum()) if len(target_covered) else 0,
            "hit": bool(len(target) > 0 and target_covered.all()),
        })
    return {
        "version": "factorforge_window_sampling_coverage_v1",
        "full_is": {"start": full_start, "end": full_end, "trading_day_count": int(len(full_dates))},
        "sampled_covered_trading_day_count": int(covered.sum()),
        "coverage_ratio": float(covered.sum() / len(full_dates)) if len(full_dates) else None,
        "uncovered_trading_day_count": int((~covered).sum()),
        "uncovered_gaps_sample": [dt.strftime("%Y-%m-%d") for dt in uncovered_dates.head(20)],
        "required_interval_hits": interval_hits,
        "is_subsamples": sample_items,
        "all_subsamples_at_least_one_year": all(item["at_least_one_calendar_year"] for item in sample_items),
        "all_required_intervals_hit": all(item["hit"] for item in interval_hits),
        "full_is_union_covered": bool(len(full_dates) > 0 and covered.all()),
    }


def main() -> int:
    args = parse_args()
    out_dir = args.workspace / "objects" / "window_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    schema_columns = parquet_columns(args.daily_clean)
    formula_ir = resolve_formula_fields_for_schema(parse_formula(args.formula, schema_columns, raise_on_error=True), schema_columns)
    raw = load_daily(args.daily_clean, args.full_is_start, formula_ir)
    latest_clean = raw["trade_date"].max().strftime("%Y-%m-%d")
    factor_frame = evaluate_formula_frame(formula_ir, raw, engine="optimized")
    raw = raw.merge(factor_frame, on=["ts_code", "trade_date"], how="left")
    labels = add_forward_returns(raw)
    merged = raw[["ts_code", "trade_date", "factor_value"]].merge(
        labels[["ts_code", "trade_date", "future_return_1d", "future_return_5d"]],
        on=["ts_code", "trade_date"],
        how="inner",
    )
    full_is = summarize_split(merged, "full_is", args.full_is_start, args.full_is_end, args.group_count, out_dir)
    subsample_results = [
        summarize_split(merged, label, start, end, args.group_count, out_dir)
        for label, start, end in DEFAULT_SUBSAMPLES
    ]
    oos = summarize_split(merged, "oos", args.oos_start, latest_clean, args.group_count, out_dir)
    coverage = coverage_proof(raw["trade_date"], args.full_is_start, args.full_is_end, DEFAULT_SUBSAMPLES)
    payload = {
        "version": "factorforge_window_evidence_v1",
        "report_id": args.report_id,
        "factor_id": args.factor_id,
        "formula": args.formula,
        "formula_ir": formula_ir,
        "producer": "scripts/build_factorforge_window_evidence.py",
        "daily_clean_path": str(args.daily_clean),
        "daily_clean_sha256": sha256_file(args.daily_clean),
        "latest_clean_date": latest_clean,
        "data_boundary": {
            "input_start": args.full_is_start,
            "input_end": latest_clean,
            "row_count": int(len(raw)),
            "date_count": int(raw["trade_date"].nunique()),
            "ticker_count": int(raw["ts_code"].nunique()),
        },
        "full_is": full_is,
        "is_subsamples": subsample_results,
        "oos": oos,
        "sampling_coverage_proof": coverage,
        "oos_policy": {
            "start": args.oos_start,
            "end": latest_clean,
            "actual_oos_end_date_reported": latest_clean,
            "holdout_only": True,
            "revision_fitting_allowed": False,
        },
    }
    out_path = out_dir / f"window_evidence__{args.report_id}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    print(json.dumps({
        "full_is_rank_ic_1d": full_is.get("rank_ic_mean_1d"),
        "full_is_rank_ic_5d": full_is.get("rank_ic_mean_5d"),
        "oos_rank_ic_1d": oos.get("rank_ic_mean_1d"),
        "oos_rank_ic_5d": oos.get("rank_ic_mean_5d"),
        "sampling_coverage_ratio": coverage.get("coverage_ratio"),
        "all_required_intervals_hit": coverage.get("all_required_intervals_hit"),
        "latest_clean_date": latest_clean,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
