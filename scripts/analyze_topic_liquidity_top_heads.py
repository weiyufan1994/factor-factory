#!/usr/bin/env python3
from __future__ import annotations

raise SystemExit(
    "BLOCKED_CANONICAL_EVALUATION_WRITER: scripts/analyze_topic_liquidity_top_heads.py previously defaulted to canonical evaluations/<report_id>/self_quant_analyzer output. "
    "Keep it blocked until it requires --output-dir and rejects canonical evaluations paths outside Step4 backend manifest scheduling."
)

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_EVAL_DIR = Path(
    "/Users/humphrey/projects/factor-factory/evaluations/"
    "TOPIC_LIQUIDITY_DCMEMBER_20250102_20260423/self_quant_analyzer"
)


def sf(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def max_drawdown(nav: pd.Series) -> float | None:
    if nav.empty:
        return None
    peak = nav.cummax()
    dd = nav / peak - 1.0
    return sf(dd.min())


def ann_return(mean_daily: float) -> float:
    return float((1.0 + mean_daily) ** 252 - 1.0) if mean_daily > -1 else -1.0


def nav_from_returns(series: pd.Series) -> pd.Series:
    ret = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return (1.0 + ret).cumprod()


def summarize_returns(series: pd.Series) -> dict[str, Any]:
    ret = pd.to_numeric(series, errors="coerce").dropna()
    if ret.empty:
        return {
            "date_count": 0,
            "mean_daily": None,
            "ann_return_approx": None,
            "daily_vol": None,
            "sharpe_approx": None,
            "win_rate": None,
            "max_drawdown": None,
        }
    nav = (1.0 + ret).cumprod()
    vol = float(ret.std())
    return {
        "date_count": int(len(ret)),
        "mean_daily": sf(ret.mean()),
        "ann_return_approx": sf(ann_return(float(ret.mean()))),
        "daily_vol": sf(vol),
        "sharpe_approx": sf(float(ret.mean()) / vol * math.sqrt(252)) if vol > 0 else None,
        "win_rate": sf((ret > 0).mean()),
        "max_drawdown": max_drawdown(nav),
        "final_nav": sf(nav.iloc[-1]),
    }


def top_fraction_frame(df: pd.DataFrame, signal: str, frac: float) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for _, day in df.dropna(subset=[signal, "future_return_1d"]).groupby("trade_date", sort=True):
        n = max(1, int(math.ceil(len(day) * frac)))
        rows.append(day.sort_values(signal, ascending=False).head(n))
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def daily_long_returns(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64")
    return frame.groupby("trade_date", sort=True)["future_return_1d"].mean()


def add_environment_columns(merged: pd.DataFrame, topics: pd.DataFrame) -> pd.DataFrame:
    topic_day = (
        topics.groupby("available_date", as_index=False)
        .agg(
            active_topic_count=("topic", "nunique"),
            positive_topic_count=("positive_flow_wan", lambda x: int((pd.to_numeric(x, errors="coerce") > 0).sum())),
            total_positive_flow_wan=("positive_flow_wan", "sum"),
            global_flow_hhi=("global_flow_hhi", "max"),
            global_flow_hhi_norm=("global_flow_hhi_norm", "max"),
            hot_topic_share=("flow_share", "max"),
            avg_liquidity_heat=("liquidity_heat_score", "mean"),
            limit_up_topics=("limit_up_count", lambda x: int((pd.to_numeric(x, errors="coerce") > 0).sum())),
        )
        .rename(columns={"available_date": "trade_date"})
    )
    out = merged.merge(topic_day, on="trade_date", how="left")
    env_cols = [
        "total_positive_flow_wan",
        "positive_topic_count",
        "global_flow_hhi_norm",
        "hot_topic_share",
        "limit_up_topics",
    ]
    for col in env_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
        med = out.groupby("trade_date")[col].first().median()
        out[f"{col}_high_env"] = out[col] >= med
    return out


def add_dragon_score_v2(merged: pd.DataFrame) -> pd.DataFrame:
    out = merged.copy()
    components = {
        "rank_topic_flow_hhi": "topic_flow_hhi",
        "rank_positive_net_amount": "positive_net_amount_wan",
        "rank_leader_flow_hhi": "leader_flow_hhi",
    }
    for rank_col, source_col in components.items():
        values = pd.to_numeric(out.get(source_col, pd.Series(index=out.index)), errors="coerce")
        out[rank_col] = values.groupby(out["trade_date"]).rank(method="average", pct=True).fillna(0.0)
    out["dragon_score_v2"] = (
        0.70 * out["rank_topic_flow_hhi"]
        + 0.20 * out["rank_positive_net_amount"]
        + 0.10 * out["rank_leader_flow_hhi"]
    )
    return out


def evaluate_top_heads(df: pd.DataFrame, signal: str, fractions: list[float]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    all_ret = df.dropna(subset=["future_return_1d"]).groupby("trade_date", sort=True)["future_return_1d"].mean()
    result["all_universe"] = summarize_returns(all_ret)
    for frac in fractions:
        top = top_fraction_frame(df, signal, frac)
        long_ret = daily_long_returns(top)
        key = f"top_{int(frac * 10000):04d}bp"
        result[key] = {
            **summarize_returns(long_ret),
            "avg_names": sf(top.groupby("trade_date")["ts_code"].nunique().mean()) if not top.empty else None,
            "excess_vs_universe_mean_daily": sf((long_ret - all_ret.reindex(long_ret.index)).mean()) if not long_ret.empty else None,
            "excess_win_rate": sf(((long_ret - all_ret.reindex(long_ret.index)) > 0).mean()) if not long_ret.empty else None,
        }
    return result


def write_nav_artifacts(
    eval_dir: Path,
    name: str,
    strategy_return: pd.Series,
    benchmark_return: pd.Series,
    gate: pd.Series | None = None,
    active_return: pd.Series | None = None,
) -> dict[str, str]:
    nav_dir = eval_dir / "top_head_nav"
    nav_dir.mkdir(parents=True, exist_ok=True)
    dates = sorted(set(strategy_return.index).union(set(benchmark_return.index)))
    frame = pd.DataFrame(index=pd.Index(dates, name="trade_date"))
    frame["strategy_return"] = strategy_return.reindex(frame.index).fillna(0.0)
    frame["benchmark_return"] = benchmark_return.reindex(frame.index).fillna(0.0)
    if active_return is not None:
        frame["active_return_before_gate"] = active_return.reindex(frame.index)
    if gate is not None:
        frame["gate"] = gate.reindex(frame.index).fillna(False).astype(bool)
    frame["strategy_nav"] = nav_from_returns(frame["strategy_return"])
    frame["benchmark_nav"] = nav_from_returns(frame["benchmark_return"])
    frame["excess_nav"] = nav_from_returns(frame["strategy_return"] - frame["benchmark_return"])

    csv_path = nav_dir / f"{name}.csv"
    png_path = nav_dir / f"{name}.png"
    frame.reset_index().to_csv(csv_path, index=False)

    fig, ax = plt.subplots(figsize=(10, 4))
    x = pd.to_datetime(frame.index.astype(str), format="%Y%m%d")
    ax.plot(x, frame["strategy_nav"], label="strategy", lw=1.4)
    ax.plot(x, frame["benchmark_nav"], label="all_universe", lw=1.1, alpha=0.75)
    ax.plot(x, frame["excess_nav"], label="excess", lw=1.0, alpha=0.75)
    if gate is not None and "gate" in frame.columns:
        active = frame["gate"].astype(bool)
        if active.any():
            ymin, ymax = ax.get_ylim()
            ax.fill_between(x, ymin, ymax, where=active.to_numpy(), color="#d9ead3", alpha=0.18, label="gate on")
    ax.axhline(1.0, color="black", lw=0.5, ls="--")
    ax.set_title(name)
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, ncol=4)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    return {"csv": str(csv_path), "png": str(png_path)}


def evaluate_environment(df: pd.DataFrame, signal: str, frac: float, env_col: str) -> dict[str, Any]:
    top = top_fraction_frame(df, signal, frac)
    if top.empty or env_col not in top.columns:
        return {}
    long_ret = daily_long_returns(top)
    env = top.groupby("trade_date", sort=True)[env_col].first().astype(bool)
    high_dates = env[env].index
    low_dates = env[~env].index
    return {
        "env_col": env_col,
        "top_fraction": frac,
        "high_env": summarize_returns(long_ret.reindex(high_dates)),
        "low_env": summarize_returns(long_ret.reindex(low_dates)),
        "high_minus_low_mean_daily": sf(long_ret.reindex(high_dates).mean() - long_ret.reindex(low_dates).mean()),
    }


def gate_series_for_dates(df: pd.DataFrame, trade_dates: pd.Index, gate_name: str) -> pd.Series:
    day_env = df.groupby("trade_date", sort=True).first()
    if gate_name == "global_hhi":
        return day_env["global_flow_hhi_norm_high_env"].reindex(trade_dates).fillna(False).astype(bool)
    if gate_name == "hot_share":
        return day_env["hot_topic_share_high_env"].reindex(trade_dates).fillna(False).astype(bool)
    if gate_name == "global_or_hot":
        return (
            day_env["global_flow_hhi_norm_high_env"].reindex(trade_dates).fillna(False).astype(bool)
            | day_env["hot_topic_share_high_env"].reindex(trade_dates).fillna(False).astype(bool)
        )
    if gate_name == "global_and_hot":
        return (
            day_env["global_flow_hhi_norm_high_env"].reindex(trade_dates).fillna(False).astype(bool)
            & day_env["hot_topic_share_high_env"].reindex(trade_dates).fillna(False).astype(bool)
        )
    raise KeyError(f"unknown gate: {gate_name}")


def evaluate_explicit_gates(
    df: pd.DataFrame,
    signal: str,
    fractions: list[float],
    gates: list[str],
    eval_dir: Path,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    benchmark = df.dropna(subset=["future_return_1d"]).groupby("trade_date", sort=True)["future_return_1d"].mean()
    for frac in fractions:
        top = top_fraction_frame(df, signal, frac)
        active_ret = daily_long_returns(top)
        top_key = f"top_{int(frac * 10000):04d}bp"
        out[f"{top_key}__ungated"] = {
            **summarize_returns(active_ret),
            "avg_names": sf(top.groupby("trade_date")["ts_code"].nunique().mean()) if not top.empty else None,
            "nav_artifacts": write_nav_artifacts(eval_dir, f"{signal}__{top_key}__ungated", active_ret, benchmark),
        }
        for gate_name in gates:
            gate = gate_series_for_dates(df, benchmark.index, gate_name)
            strategy_ret = active_ret.reindex(benchmark.index).where(gate, 0.0).fillna(0.0)
            active_dates = gate[gate].index
            active_top = top[top["trade_date"].isin(active_dates)] if not top.empty else top
            key = f"{top_key}__gate_{gate_name}"
            out[key] = {
                **summarize_returns(strategy_ret),
                "active_day_count": int(gate.sum()),
                "active_day_ratio": sf(gate.mean()),
                "active_only": summarize_returns(active_ret.reindex(active_dates)),
                "avg_names_when_active": sf(active_top.groupby("trade_date")["ts_code"].nunique().mean())
                if not active_top.empty
                else None,
                "nav_artifacts": write_nav_artifacts(
                    eval_dir,
                    f"{signal}__{top_key}__gate_{gate_name}",
                    strategy_ret,
                    benchmark,
                    gate=gate,
                    active_return=active_ret,
                ),
            }
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    eval_dir = Path(args.eval_dir).expanduser()
    merged = pd.read_csv(eval_dir / "topic_liquidity_merged_returns.csv", dtype={"trade_date": "string", "event_trade_date": "string"})
    topics = pd.read_csv(eval_dir / "topic_liquidity_topic_panel.csv", dtype={"available_date": "string", "event_trade_date": "string"})
    merged["trade_date"] = merged["trade_date"].astype("string").str.zfill(8)
    topics["available_date"] = topics["available_date"].astype("string").str.zfill(8)
    merged = add_environment_columns(merged, topics)
    merged = add_dragon_score_v2(merged)

    fractions = [0.01, 0.02, 0.05, 0.10]
    gate_fractions = [0.01, 0.02, 0.05]
    explicit_gates = ["global_hhi", "hot_share", "global_or_hot", "global_and_hot"]
    env_cols = [
        "total_positive_flow_wan_high_env",
        "positive_topic_count_high_env",
        "global_flow_hhi_norm_high_env",
        "hot_topic_share_high_env",
        "limit_up_topics_high_env",
    ]
    results: dict[str, Any] = {}
    for signal in ["topic_flow_hhi", "leader_flow_hhi", "dragon_score_v2"]:
        results[signal] = {
            "top_heads": evaluate_top_heads(merged, signal, fractions),
            "environment_top_2pct": {
                env_col: evaluate_environment(merged, signal, 0.02, env_col)
                for env_col in env_cols
            },
            "environment_top_5pct": {
                env_col: evaluate_environment(merged, signal, 0.05, env_col)
                for env_col in env_cols
            },
            "explicit_gate_strategies": evaluate_explicit_gates(
                merged,
                signal,
                gate_fractions,
                explicit_gates,
                eval_dir,
            ),
        }

    out = {
        "eval_dir": str(eval_dir),
        "method": {
            "focus": "top-bucket profitability and environment-conditioned leader payoff",
            "fractions": fractions,
            "gate_fractions": gate_fractions,
            "explicit_gates": {
                "global_hhi": "trade date is above-median by global_flow_hhi_norm",
                "hot_share": "trade date is above-median by hottest topic flow_share",
                "global_or_hot": "global_hhi or hot_share gate is on",
                "global_and_hot": "global_hhi and hot_share gates are both on",
            },
            "dragon_score_v2": "within-date rank blend: 70% topic_flow_hhi + 20% positive_net_amount_wan + 10% leader_flow_hhi",
            "environment": "high/low split by date-level median of topic liquidity/activity variables",
            "nav": "CSV/PNG files are written under top_head_nav; gated strategies hold cash with 0 return when the gate is off",
        },
        "results": results,
    }
    out_path = eval_dir / "topic_liquidity_top_head_diagnostics.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["results"], ensure_ascii=False, indent=2))
    print(f"[WRITE] {out_path}")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze top-head profitability for topic liquidity HHI signals.")
    parser.add_argument("--eval-dir", default=str(DEFAULT_EVAL_DIR))
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
