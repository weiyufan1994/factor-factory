#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


TZ_BJ = timezone(timedelta(hours=8))
DEFAULT_ROOT = Path("/home/ubuntu/.openclaw/workspace/runs/topic-liquidity-hhi")
DEFAULT_OUT_ROOT = Path("/home/ubuntu/.openclaw/workspace/runs/topic-liquidity-dragon-report")
DEFAULT_HOLDINGS_STATE = DEFAULT_OUT_ROOT / "holdings_state.csv"
S3_BUCKET = "yufan-data-lake"
DAILY_INCREMENTAL_PREFIX = "tushares/行情数据/daily_incremental"

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


def display_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:  # noqa: BLE001
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return default
    return text


def trade_date_age_days(trade_date: str, now_bj: datetime) -> int | None:
    try:
        signal_day = datetime.strptime(str(trade_date), "%Y%m%d").date()
    except ValueError:
        return None
    return (now_bj.date() - signal_day).days


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except Exception:  # noqa: BLE001
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return value
    return value


def run_text(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def normalize_ts_code(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().upper().replace(" ", "")
    if not text or text == "NAN":
        return ""
    match = re.search(r"(\d{6})(?:\.(SH|SZ|BJ))?", text)
    if not match:
        return text
    code, suffix = match.group(1), match.group(2)
    if suffix:
        return f"{code}.{suffix}"
    if code.startswith(("60", "68", "90")):
        return f"{code}.SH"
    if code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    if code.startswith(("43", "83", "87", "92")):
        return f"{code}.BJ"
    return code


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
    if "ts_code" in frame.columns:
        frame["ts_code"] = frame["ts_code"].map(normalize_ts_code)
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


def list_s3_trade_dates(bucket: str, prefix: str, end_date: str) -> list[str]:
    proc = run_text(["aws", "s3", "ls", f"s3://{bucket}/{prefix.rstrip('/')}/"])
    dates: set[str] = set()
    for line in proc.stdout.splitlines():
        if "trade_date=" not in line:
            continue
        try:
            day = line.split("trade_date=", 1)[1].split("/", 1)[0].strip()
        except IndexError:
            continue
        if day <= end_date:
            dates.add(day)
    return sorted(dates)


def load_close_history_from_s3(bucket: str, end_date: str, codes: set[str], lookback: int = 16) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not codes:
        return pd.DataFrame(), {"status": "skipped", "reason": "no_codes"}
    try:
        dates = list_s3_trade_dates(bucket, DAILY_INCREMENTAL_PREFIX, end_date)[-lookback:]
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), {"status": "failed", "reason": f"list_s3_trade_dates_failed: {exc}"}
    if len(dates) < 7:
        return pd.DataFrame(), {"status": "insufficient_history", "date_count": len(dates)}

    rows: list[pd.DataFrame] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="dragon_rsi6_") as tmp:
        tmp_path = Path(tmp)
        for day in dates:
            path = tmp_path / f"daily_{day}.csv"
            key = f"s3://{bucket}/{DAILY_INCREMENTAL_PREFIX}/trade_date={day}/daily_{day}.csv"
            proc = run_text(["aws", "s3", "cp", key, str(path), "--only-show-errors"], check=False)
            if proc.returncode != 0:
                errors.append(f"{day}: {proc.stderr.strip()[-160:]}")
                continue
            try:
                df = pd.read_csv(path, usecols=lambda c: c in {"ts_code", "trade_date", "close"})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{day}: read_csv failed {exc}")
                continue
            if df.empty or not {"ts_code", "trade_date", "close"}.issubset(df.columns):
                continue
            df["ts_code"] = df["ts_code"].map(normalize_ts_code)
            df = df[df["ts_code"].isin(codes)].copy()
            if df.empty:
                continue
            df["trade_date"] = df["trade_date"].astype(str)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            rows.append(df.dropna(subset=["ts_code", "trade_date", "close"]))
    if not rows:
        return pd.DataFrame(), {"status": "failed", "reason": "no_close_rows", "errors": errors[-3:]}
    hist = pd.concat(rows, ignore_index=True, sort=False).drop_duplicates(["ts_code", "trade_date"])
    return hist, {
        "status": "ok",
        "date_count": len(dates),
        "loaded_dates": sorted(hist["trade_date"].unique().tolist()),
        "errors": errors[-3:],
    }


def compute_rsi6(close_history: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    if close_history.empty:
        return pd.DataFrame(columns=["ts_code", "rsi6", "rsi6_close_count"])
    frame = close_history.copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "trade_date", "close"]).sort_values(["ts_code", "trade_date"])
    delta = frame.groupby("ts_code")["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.groupby(frame["ts_code"]).rolling(6, min_periods=6).mean().reset_index(level=0, drop=True)
    avg_loss = loss.groupby(frame["ts_code"]).rolling(6, min_periods=6).mean().reset_index(level=0, drop=True)
    rsi = 100 - 100 / (1 + (avg_gain / avg_loss.replace(0, pd.NA)))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    frame["rsi6"] = pd.to_numeric(rsi, errors="coerce")
    frame["rsi6_close_count"] = frame.groupby("ts_code")["close"].transform("count")
    latest = frame[frame["trade_date"].eq(str(trade_date))].copy()
    return latest[["ts_code", "rsi6", "rsi6_close_count"]].drop_duplicates("ts_code")


def enrich_with_rsi6(candidates: pd.DataFrame, holdings: pd.DataFrame, trade_date: str, bucket: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    codes = set(candidates.get("ts_code", pd.Series(dtype=str)).map(normalize_ts_code).dropna())
    if not holdings.empty and "ts_code" in holdings.columns:
        codes |= set(holdings["ts_code"].map(normalize_ts_code).dropna())
    codes = {c for c in codes if c}
    close_history, meta = load_close_history_from_s3(bucket, trade_date, codes)
    rsi = compute_rsi6(close_history, trade_date)
    if rsi.empty:
        return candidates, holdings, {**meta, "rsi6_status": "missing"}
    c2 = candidates.merge(rsi, on="ts_code", how="left") if not candidates.empty else candidates
    h2 = holdings.merge(rsi, on="ts_code", how="left") if not holdings.empty else holdings
    return c2, h2, {**meta, "rsi6_status": "ok", "covered_codes": int(rsi["rsi6"].notna().sum())}


def load_holdings_state(path: Path, *, require: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not path.exists():
        meta = {
            "status": "missing",
            "path": str(path),
            "required_columns": ["ts_code", "entry_date or holding_trade_days"],
        }
        if require:
            raise FileNotFoundError("BLOCK_HOLDINGS_STATE_MISSING: " + str(path))
        return pd.DataFrame(), meta
    try:
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw.get("holdings", raw) if isinstance(raw, dict) else raw
            holdings = pd.DataFrame(rows)
        else:
            holdings = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        if require:
            raise RuntimeError(f"BLOCK_HOLDINGS_STATE_UNREADABLE: {path}: {exc}") from exc
        return pd.DataFrame(), {"status": "unreadable", "path": str(path), "error": str(exc)}
    if holdings.empty:
        return holdings, {"status": "empty", "path": str(path)}
    if "ts_code" not in holdings.columns:
        if require:
            raise ValueError("BLOCK_HOLDINGS_STATE_SCHEMA: holdings_state must include ts_code")
        return pd.DataFrame(), {"status": "invalid_schema", "path": str(path), "missing": ["ts_code"]}
    holdings = holdings.copy()
    holdings["ts_code"] = holdings["ts_code"].map(normalize_ts_code)
    holdings = holdings[holdings["ts_code"].astype(bool)].copy()
    for col in ("holding_trade_days", "weight", "shares", "cost_price"):
        if col in holdings.columns:
            holdings[col] = pd.to_numeric(holdings[col], errors="coerce")
    if "entry_date" in holdings.columns:
        holdings["entry_date"] = holdings["entry_date"].astype(str).str.replace("-", "", regex=False)
    return holdings.reset_index(drop=True), {"status": "ok", "path": str(path), "count": int(len(holdings))}


def build_position_plan(holdings: pd.DataFrame, candidates: pd.DataFrame, gate: dict[str, Any]) -> pd.DataFrame:
    if holdings.empty:
        return pd.DataFrame()
    candidate_cols = [
        "ts_code",
        "name",
        "strongest_topic",
        "report_score",
        "topic_flow_hhi",
        "positive_net_amount_wan",
        "pct_chg",
        "limit_flag",
        "rsi6",
    ]
    available = [c for c in candidate_cols if c in candidates.columns]
    candidate_map = candidates[available].drop_duplicates("ts_code").copy() if available else pd.DataFrame({"ts_code": []})
    merged = holdings.merge(candidate_map, on="ts_code", how="left", suffixes=("_holding", ""))
    if "name" in merged.columns and "name_holding" in merged.columns:
        merged["name"] = merged["name"].combine_first(merged["name_holding"])
    elif "name" not in merged.columns and "name_holding" in merged.columns:
        merged["name"] = merged["name_holding"]
    if "rsi6" in merged.columns and "rsi6_holding" in merged.columns:
        merged["rsi6"] = merged["rsi6"].combine_first(merged["rsi6_holding"])
    elif "rsi6" not in merged.columns and "rsi6_holding" in merged.columns:
        merged["rsi6"] = merged["rsi6_holding"]
    if "holding_trade_days" not in merged.columns:
        merged["holding_trade_days"] = pd.NA
    merged["holding_trade_days"] = pd.to_numeric(merged["holding_trade_days"], errors="coerce")
    merged["in_tomorrow_top"] = merged["report_score"].notna()
    merged["rsi6"] = pd.to_numeric(merged.get("rsi6", pd.Series(index=merged.index)), errors="coerce")

    actions: list[str] = []
    reasons: list[str] = []
    for row in merged.itertuples(index=False):
        days = sf(getattr(row, "holding_trade_days", math.nan), math.nan)
        rsi6 = sf(getattr(row, "rsi6", math.nan), math.nan)
        in_top = bool(getattr(row, "in_tomorrow_top", False))
        if not math.isnan(rsi6) and rsi6 < 45:
            actions.append("计划卖出")
            reasons.append(f"RSI6={rsi6:.1f}<45，优先风控退出；若明日开盘跌停则冻结")
        elif math.isnan(days):
            actions.append("待确认")
            reasons.append("缺holding_trade_days/entry_date，不能判定3日保护；先不要自动卖出，需补录成交日或持仓天数")
        elif not math.isnan(days) and days < 3:
            actions.append("继续持有")
            reasons.append(f"持仓{days:.0f}个交易日，未满3日，不因新龙头/排名变化卖出")
        elif not gate.get("hot_share", False):
            actions.append("计划卖出")
            reasons.append("hot_topic_share gate关闭；满3日持仓按退潮纪律退出，若开盘跌停则冻结")
        elif not in_top:
            actions.append("计划卖出")
            reasons.append("不在明日候选Top内；满3日后按掉出候选退出，若开盘跌停则冻结")
        else:
            actions.append("继续持有")
            reasons.append("仍在明日候选Top内，且未触发RSI<45")
    merged["tomorrow_action"] = actions
    merged["action_reason"] = reasons
    return merged


def build_buy_plan(candidates: pd.DataFrame, holdings: pd.DataFrame, gate: dict[str, Any]) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    frame = candidates.copy()
    held_codes = set(holdings.get("ts_code", pd.Series(dtype=str)).map(normalize_ts_code).dropna()) if not holdings.empty else set()
    frame["already_held"] = frame["ts_code"].map(normalize_ts_code).isin(held_codes)
    frame["tomorrow_buy_status"] = "计划买入" if gate.get("hot_share", False) else "仅观察"
    frame.loc[frame["already_held"], "tomorrow_buy_status"] = "已持有"
    if not gate.get("hot_share", False):
        frame["buy_note"] = "gate未开，不新增"
    else:
        frame["buy_note"] = "明日开盘不涨停才买；若涨停买不进则现金保留"
        frame.loc[frame["already_held"], "buy_note"] = "已有仓位，先按持仓纪律判断是否继续持有"
    return frame


def render_report(
    payload: dict[str, Any],
    topics: pd.DataFrame,
    candidates: pd.DataFrame,
    gate: dict[str, Any],
    holdings: pd.DataFrame,
    holdings_meta: dict[str, Any],
    position_plan: pd.DataFrame,
    rsi_meta: dict[str, Any],
) -> str:
    trade_date = str(payload.get("trade_date", ""))
    generated_dt = datetime.now(TZ_BJ)
    generated_at = generated_dt.isoformat()
    signal_age_days = trade_date_age_days(trade_date, generated_dt)
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
        (
            "- 数据完整性："
            f"题材/候选=OK；RSI6={rsi_meta.get('rsi6_status', rsi_meta.get('status', 'unknown'))}"
            f"({int(sf(rsi_meta.get('covered_codes'), 0))}只覆盖)；"
            f"持仓状态={holdings_meta.get('status')}；"
            f"信号距推送={signal_age_days if signal_age_days is not None else '-'}自然日。"
        ),
    ]
    if signal_age_days is not None and signal_age_days > 1:
        lines.append(
            "- DATA_FRESHNESS_WARN：信号日不是最近自然日；如果推送日是交易日收盘后，"
            "应先确认当日daily_incremental/资金流/题材数据已入库，否则这份日报是旧信号延迟发送。"
        )
    if holdings_meta.get("status") != "ok":
        lines.append(
            "- BLOCK_HOLDINGS_STATE_MISSING：当前未读取到真实持仓文件，不能确认已有仓位、持仓天数、"
            "是否已满3日或是否该执行RSI卖出；下面只给候选和规则，不把它当成完整交易指令。"
        )
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
        if holdings_meta.get("status") == "ok":
            lines.append("- 明日执行摘要：先处理已有持仓；未满3日优先持有，RSI6<45优先卖出；剩余现金等权买入候选Top。")
        else:
            lines.append("- 明日执行摘要：开盘不涨停才买；但因缺少持仓状态，无法扣除已有持仓或判断卖出/换仓。")
        lines.append("- 明日可买/候选Top：")
        for i, row in enumerate(candidates.itertuples(index=False), 1):
            code = display_text(getattr(row, "ts_code", ""))
            name = display_text(getattr(row, "name", ""), code)
            label = code if name == code else f"{name} {code}"
            first_time = display_text(getattr(row, "first_time", ""))
            limit_flag = "涨停" if bool(getattr(row, "limit_up", False)) else str(getattr(row, "limit_flag", "") or "-")
            rsi6 = getattr(row, "rsi6", math.nan)
            rsi_text = "-" if pd.isna(rsi6) else f"{sf(rsi6):.1f}"
            buy_status = getattr(row, "tomorrow_buy_status", "计划买入")
            lines.append(
                f"  {i}. {buy_status} {label} "
                f"score={sf(getattr(row, 'report_score', 0)):.3f} "
                f"topic={display_text(getattr(row, 'strongest_topic', ''))} "
                f"topicHHI={sf(getattr(row, 'topic_flow_hhi', 0)):.5f} "
                f"net={wan(getattr(row, 'positive_net_amount_wan', 0))} "
                f"pct={sf(getattr(row, 'pct_chg', 0)):.2f}% "
                f"RSI6={rsi_text} {limit_flag} first={first_time}"
            )
    else:
        lines.append("- 明日执行：hot_topic_share gate未开，不新增龙头仓；已有仓位按3日持有/RSI退出纪律处理。")
        lines.append("- 观察名单：")
        for i, row in enumerate(candidates.head(8).itertuples(index=False), 1):
            code = display_text(getattr(row, "ts_code", ""))
            name = display_text(getattr(row, "name", ""), code)
            label = code if name == code else f"{name} {code}"
            lines.append(
                f"  {i}. 观察 {label} "
                f"topic={display_text(getattr(row, 'strongest_topic', ''))} "
                f"score={sf(getattr(row, 'report_score', 0)):.3f}"
            )
    if holdings_meta.get("status") == "ok":
        if position_plan.empty:
            lines.append("- 已有持仓：持仓文件为空，明日只按新增候选处理。")
        else:
            lines.append("- 已有持仓处理：")
            for i, row in enumerate(position_plan.itertuples(index=False), 1):
                code = display_text(getattr(row, "ts_code", ""))
                name = display_text(getattr(row, "name", ""), display_text(getattr(row, "name_holding", ""), code))
                label = code if name == code else f"{name} {code}"
                days = getattr(row, "holding_trade_days", math.nan)
                rsi6 = getattr(row, "rsi6", math.nan)
                days_text = "-" if pd.isna(days) else f"{sf(days):.0f}"
                rsi_text = "-" if pd.isna(rsi6) else f"{sf(rsi6):.1f}"
                lines.append(
                    f"  {i}. {getattr(row, 'tomorrow_action', '')} {label} "
                    f"持仓天数={days_text} RSI6={rsi_text} inTop={bool(getattr(row, 'in_tomorrow_top', False))}；"
                    f"{getattr(row, 'action_reason', '')}"
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
    holdings, holdings_meta = load_holdings_state(Path(args.holdings_state).expanduser(), require=args.require_holdings)
    candidates, holdings, rsi_meta = enrich_with_rsi6(candidates, holdings, str(payload.get("trade_date", "")), args.s3_bucket)
    candidates = build_buy_plan(candidates, holdings, gate)
    position_plan = build_position_plan(holdings, candidates, gate)
    report = render_report(payload, topics, candidates, gate, holdings, holdings_meta, position_plan, rsi_meta)

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
        "data_readiness": {
            "topic_liquidity_outputs": "ok",
            "rsi6": rsi_meta,
            "holdings_state": holdings_meta,
            "signal_age_calendar_days": trade_date_age_days(trade_date, datetime.now(TZ_BJ)),
            "complete_trade_instruction": holdings_meta.get("status") == "ok",
        },
        "top_candidates": candidates.to_dict(orient="records"),
        "existing_positions": position_plan.to_dict(orient="records") if not position_plan.empty else [],
        "source_paths": payload.get("paths", {}),
        "report_md": str(md_path),
    }
    safe_result = json_safe(result)
    json_path.write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report, encoding="utf-8")
    latest_json.write_text(json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8")
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
    parser.add_argument("--holdings-state", default=str(DEFAULT_HOLDINGS_STATE))
    parser.add_argument("--require-holdings", action="store_true", help="Fail instead of rendering a candidate-only report when holdings_state is missing.")
    parser.add_argument("--s3-bucket", default=S3_BUCKET)
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
