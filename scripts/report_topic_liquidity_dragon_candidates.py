#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


TZ_BJ = timezone(timedelta(hours=8))
DEFAULT_ROOT = Path("/home/ubuntu/.openclaw/workspace/runs/topic-liquidity-hhi")
DEFAULT_OUT_ROOT = Path("/home/ubuntu/.openclaw/workspace/runs/topic-liquidity-dragon-report")

# Median thresholds from the dc_member backtest window 20250102-20260423.
FALLBACK_GLOBAL_HHI_NORM_MEDIAN = 0.015857
FALLBACK_HOT_TOPIC_SHARE_MEDIAN = 0.066596

# Strict tradable open backtest, 2025-01-02 to 2026-04-23.
# Event-day close signals are executed at next open; open limit-up buys and
# open limit-down sells are blocked; costs include 2bps commission each side,
# 5bps sell stamp duty, and 5bps slippage each side.
STRICT_STRATEGY = {
    "name": "top5 hot topic, min 3 trading days, RSI6<45 exit",
    "final_nav": 2.0907,
    "sharpe": 2.93,
    "max_drawdown": -0.1051,
    "avg_holding_days": 2.39,
    "buy_block_rate": 0.0953,
    "sell_block_rate": 0.0070,
}
STRICT_BASELINE = {
    "name": "top5 hot topic, 1-day rebalance",
    "final_nav": 0.9964,
    "sharpe": 0.08,
    "max_drawdown": -0.2129,
}


def sf(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def pct(value: Any, digits: int = 1) -> str:
    return f"{sf(value) * 100:.{digits}f}%"


def wan(value: Any) -> str:
    v = sf(value)
    if abs(v) >= 10000:
        return f"{v / 10000:.2f}亿"
    return f"{v:.0f}万"


def run_builder(builder: Path, root: Path) -> None:
    cmd = ["python3", str(builder), "--out-root", str(root)]
    subprocess.run(cmd, check=True)


def read_latest(root: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    latest_json = root / "latest.json"
    latest_topics = root / "latest_topics.csv"
    latest_leaders = root / "latest_leaders.csv"
    latest_signals = root / "latest_stock_signals.csv"
    missing = [str(p) for p in (latest_json, latest_topics, latest_leaders, latest_signals) if not p.exists()]
    if missing:
        raise FileNotFoundError("missing latest topic-liquidity outputs: " + ", ".join(missing))
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    topics = pd.read_csv(latest_topics)
    leaders = pd.read_csv(latest_leaders)
    signals = pd.read_csv(latest_signals)
    return payload, topics, leaders, signals


def historical_gate_thresholds(root: Path) -> dict[str, Any]:
    rows: list[pd.DataFrame] = []
    for path in sorted(root.glob("20??-??-??/topic_liquidity_topics_*.csv")):
        try:
            df = pd.read_csv(path, usecols=lambda c: c in {"trade_date", "flow_share", "global_flow_hhi_norm"})
        except Exception:  # noqa: BLE001
            continue
        if df.empty:
            continue
        if "trade_date" not in df.columns:
            trade_date = path.stem.rsplit("_", 1)[-1]
            df["trade_date"] = trade_date
        if "global_flow_hhi_norm" not in df.columns:
            df["global_flow_hhi_norm"] = pd.NA
        if "flow_share" not in df.columns:
            df["flow_share"] = pd.NA
        rows.append(df)
    if not rows:
        return {
            "source": "fallback_backtest_median",
            "date_count": 0,
            "global_hhi_norm_median": FALLBACK_GLOBAL_HHI_NORM_MEDIAN,
            "hot_topic_share_median": FALLBACK_HOT_TOPIC_SHARE_MEDIAN,
        }
    hist = pd.concat(rows, ignore_index=True, sort=False)
    hist["global_flow_hhi_norm"] = pd.to_numeric(hist["global_flow_hhi_norm"], errors="coerce")
    hist["flow_share"] = pd.to_numeric(hist["flow_share"], errors="coerce")
    hist["trade_date_key"] = hist["trade_date"].astype(str)
    day = (
        hist.groupby("trade_date_key", as_index=False)
        .agg(
            global_hhi_norm=("global_flow_hhi_norm", "max"),
            hot_topic_share=("flow_share", "max"),
        )
    )
    day = day.dropna(subset=["global_hhi_norm", "hot_topic_share"], how="all")
    if len(day) < 20:
        return {
            "source": "fallback_backtest_median_until_local_history_ge_20",
            "date_count": int(len(day)),
            "global_hhi_norm_median": FALLBACK_GLOBAL_HHI_NORM_MEDIAN,
            "hot_topic_share_median": FALLBACK_HOT_TOPIC_SHARE_MEDIAN,
        }
    return {
        "source": "local_rolling_history_median",
        "date_count": int(len(day)),
        "global_hhi_norm_median": sf(day["global_hhi_norm"].median()),
        "hot_topic_share_median": sf(day["hot_topic_share"].median()),
    }


def candidate_table(signals: pd.DataFrame, topics: pd.DataFrame, top_n: int) -> pd.DataFrame:
    frame = signals.copy()
    for col in (
        "topic_flow_hhi",
        "leader_flow_hhi",
        "dragon_score",
        "positive_net_amount_wan",
        "net_amount_wan",
        "pct_chg",
        "turnover_rate",
        "open_times",
        "strongest_topic_flow_share",
    ):
        frame[col] = pd.to_numeric(frame.get(col, pd.Series(index=frame.index)), errors="coerce").fillna(0.0)
    hot_topics = set(
        topics.sort_values(["liquidity_heat_score", "positive_flow_wan"], ascending=False)
        .head(12)["topic"]
        .astype(str)
    )
    frame["in_hot_topic"] = frame.get("strongest_topic", "").astype(str).isin(hot_topics)
    frame["limit_up"] = frame.get("limit_flag", "").astype(str).eq("U")
    frame["report_score"] = (
        0.82 * frame["topic_flow_hhi"].rank(pct=True)
        + 0.08 * frame["positive_net_amount_wan"].rank(pct=True)
        + 0.02 * frame["leader_flow_hhi"].rank(pct=True)
        + 0.05 * frame["in_hot_topic"].astype(float)
        + 0.03 * frame["limit_up"].astype(float)
    )
    return frame.sort_values(["report_score", "topic_flow_hhi"], ascending=False).head(top_n).reset_index(drop=True)


def render_report(payload: dict[str, Any], topics: pd.DataFrame, candidates: pd.DataFrame, gate: dict[str, Any]) -> str:
    trade_date = str(payload.get("trade_date", ""))
    generated_at = datetime.now(TZ_BJ).isoformat()
    flow = payload.get("flow_summary", {})
    market = payload.get("market", {})
    gate_on = bool(gate["hot_share"])
    mode = "允许新开/加仓" if gate_on else "不开新仓/仅观察"
    global_mode = "强" if gate["global_hhi"] else "弱"
    lines = [
        "宏观一处｜题材资金龙头交易日报",
        f"- 信号日期：{trade_date}；推送时间：{generated_at}",
        f"- 策略状态：{mode}；执行规则=次日开盘，涨停买不进，跌停卖不出",
        (
            "- Gate："
            f"hot_topic_share={pct(gate['hot_topic_share'])} "
            f"(开仓阈值{pct(gate['hot_threshold'])}, {'开' if gate['hot_share'] else '关'})；"
            f"global_HHI_norm={gate['global_hhi_norm']:.4f} "
            f"(市场资金垄断观察={global_mode})"
        ),
        (
            "- 资金池："
            f"外部新增={wan(market.get('external_increment_wan'))}；"
            f"板块轮动释放={wan(flow.get('rotation_release_wan'))}；"
            f"可竞争新增资金={wan(flow.get('available_incremental_pool_wan'))}；"
            f"Top3题材占比={pct(flow.get('top3_share'))}"
        ),
        (
            "- 严格回测口径：无未来函数；信号日收盘后生成，次日开盘执行；"
            "开盘涨停不买、开盘跌停不卖；买入成本7bps、卖出成本12bps。"
        ),
        (
            "- 当前推荐策略："
            f"{STRICT_STRATEGY['name']}；NAV={STRICT_STRATEGY['final_nav']:.3f}，"
            f"Sharpe={STRICT_STRATEGY['sharpe']:.2f}，"
            f"最大回撤={pct(STRICT_STRATEGY['max_drawdown'])}，"
            f"平均持仓={STRICT_STRATEGY['avg_holding_days']:.2f}个交易日。"
        ),
    ]
    top_topics = topics.sort_values(["liquidity_heat_score", "positive_flow_wan"], ascending=False).head(5)
    if not top_topics.empty:
        lines.append("- 资金热流入题材Top5：")
        for i, row in enumerate(top_topics.itertuples(index=False), 1):
            lines.append(
                f"  {i}. {getattr(row, 'topic', '')} "
                f"share={pct(getattr(row, 'flow_share', 0))} "
                f"heat={sf(getattr(row, 'liquidity_heat_score', 0)):.3f} "
                f"limit={int(sf(getattr(row, 'limit_up_count', 0)))}/{int(sf(getattr(row, 'stock_count', 0)))}"
            )
    if gate_on:
        lines.append("- 明日执行：开盘不涨停才买；等权分散买入候选Top，已有持仓未满3个交易日优先持有。")
        lines.append("- 明日龙头候选Top：")
        for i, row in enumerate(candidates.itertuples(index=False), 1):
            name = getattr(row, "name", "") or ""
            first_time = getattr(row, "first_time", "") or ""
            limit_flag = "涨停" if bool(getattr(row, "limit_up", False)) else str(getattr(row, "limit_flag", "") or "-")
            lines.append(
                f"  {i}. {name} {getattr(row, 'ts_code', '')} "
                f"score={sf(getattr(row, 'report_score', 0)):.3f} "
                f"topic={getattr(row, 'strongest_topic', '')} "
                f"topicHHI={sf(getattr(row, 'topic_flow_hhi', 0)):.5f} "
                f"net={wan(getattr(row, 'positive_net_amount_wan', 0))} "
                f"pct={sf(getattr(row, 'pct_chg', 0)):.2f}% "
                f"{limit_flag} first={first_time}"
            )
    else:
        lines.append("- 明日执行：hot_topic_share gate未开，不新增龙头仓；已有仓位按3日持有/RSI退出纪律处理。")
        lines.append("- 观察名单：")
        for i, row in enumerate(candidates.head(8).itertuples(index=False), 1):
            lines.append(
                f"  {i}. 观察 {getattr(row, 'name', '')} {getattr(row, 'ts_code', '')} "
                f"topic={getattr(row, 'strongest_topic', '')} "
                f"score={sf(getattr(row, 'report_score', 0)):.3f}"
            )
    lines.extend(
        [
            "- 交易纪律：新仓只在gate开启时做；开盘涨停不追；单票未满3个交易日不因排名短期波动卖出；满3日后若掉出候选/题材退潮则退出。",
            "- 风控纪律：若RSI6<45，优先退出；若开盘跌停卖不出，则冻结到下一个可卖开盘；不因为盘中情绪临时扩大仓位。",
            (
                "- 对照回测：1天换仓版本在严格成本后NAV="
                f"{STRICT_BASELINE['final_nav']:.3f}、Sharpe={STRICT_BASELINE['sharpe']:.2f}，"
                "说明不要日内频繁追换。"
            ),
            "- 数据纪律：这是收盘后生成的次日候选，不使用未来数据；真实财务/公告类数据仍以实际公告日后可见为准。",
            "- 研究口径：主信号用topic_flow_hhi；正资金流、涨停、leader_flow_hhi只做轻量tie-break/overlay；TrendRadar/舆情只做后续确认层。",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).expanduser()
    out_root = Path(args.out_root).expanduser()
    if args.run_builder:
        run_builder(Path(args.builder).expanduser(), root)
    payload, topics, leaders, signals = read_latest(root)
    thresholds = historical_gate_thresholds(root)
    flow = payload.get("flow_summary", {})
    global_hhi_norm = sf(flow.get("hhi_norm", topics.get("global_flow_hhi_norm", pd.Series([0])).max()))
    hot_topic_share = sf(flow.get("top1_share", topics.get("flow_share", pd.Series([0])).max()))
    gate = {
        "global_hhi_norm": global_hhi_norm,
        "hot_topic_share": hot_topic_share,
        "global_threshold": thresholds["global_hhi_norm_median"],
        "hot_threshold": thresholds["hot_topic_share_median"],
        "global_hhi": global_hhi_norm >= thresholds["global_hhi_norm_median"],
        "hot_share": hot_topic_share >= thresholds["hot_topic_share_median"],
        "threshold_source": thresholds["source"],
        "threshold_date_count": thresholds["date_count"],
    }
    gate["global_or_hot"] = bool(gate["global_hhi"] or gate["hot_share"])
    gate["global_and_hot"] = bool(gate["global_hhi"] and gate["hot_share"])
    candidates = candidate_table(signals, topics, args.top_n)
    report = render_report(payload, topics, candidates, gate)

    trade_date = str(payload.get("trade_date", datetime.now(TZ_BJ).strftime("%Y%m%d")))
    out_dir = out_root / f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"topic_liquidity_dragon_candidates_{trade_date}.json"
    md_path = out_dir / f"topic_liquidity_dragon_candidates_{trade_date}.md"
    latest_json = out_root / "latest.json"
    latest_md = out_root / "latest.md"
    result = {
        "trade_date": trade_date,
        "generated_at_bj": datetime.now(TZ_BJ).isoformat(),
        "gate": gate,
        "thresholds": thresholds,
        "top_candidates": candidates.to_dict(orient="records"),
        "source_paths": payload.get("paths", {}),
        "report_md": str(md_path),
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report, encoding="utf-8")
    latest_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_md.write_text(report, encoding="utf-8")
    print(report)
    print(f"JSON: {json_path}")
    print(f"MD: {md_path}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the daily topic-liquidity dragon candidate report.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--run-builder", action="store_true", help="Run topic_liquidity_hhi.py before rendering the report.")
    parser.add_argument(
        "--builder",
        default="/home/ubuntu/.openclaw/workspace/scripts/topic_liquidity_hhi.py",
        help="Path to topic_liquidity_hhi.py when --run-builder is used.",
    )
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
