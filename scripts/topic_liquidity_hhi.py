#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


S3_BUCKET = "yufan-data-lake"
S3_PREFIX = "tushares"
TZ_BJ = timezone(timedelta(hours=8))
DEFAULT_OUT_ROOT = Path("/home/ubuntu/.openclaw/workspace/runs/topic-liquidity-hhi")

NOISE_MARKERS = (
    "全A",
    "全Ａ",
    "沪深全",
    "沪股通",
    "深股通",
    "陆股通",
    "QFII",
    "融资融券",
    "龙虎榜",
    "最近多板",
    "近期新高",
    "百日新高",
    "历史新高",
    "昨日",
    "高振幅",
    "小盘",
    "主板",
    "高贝塔",
    "低盈利",
    "激进投资",
    "减持",
    "样本股",
    "等权",
    "加权",
)


@dataclass
class LoadedFrame:
    name: str
    df: pd.DataFrame
    key: str | None
    status: str
    detail: str = ""


def run_text(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def aws_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def read_s3_csv(bucket: str, keys: list[str], name: str, *, required: bool = False) -> LoadedFrame:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"{name}_") as tmp:
        path = Path(tmp) / f"{name}.csv"
        for key in keys:
            proc = run_text(["aws", "s3", "cp", aws_uri(bucket, key), str(path), "--only-show-errors"], check=False)
            if proc.returncode != 0:
                errors.append(f"{key}: {proc.stderr.strip()[-220:]}")
                continue
            try:
                df = pd.read_csv(path)
                return LoadedFrame(name=name, df=df, key=key, status="ok")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{key}: read_csv failed: {exc}")
        if required:
            raise FileNotFoundError(f"unable to load {name}: " + " | ".join(errors[-3:]))
        return LoadedFrame(name=name, df=pd.DataFrame(), key=None, status="missing", detail=" | ".join(errors[-3:]))


def list_partition_dates(bucket: str, prefix: str) -> list[str]:
    proc = run_text(["aws", "s3", "ls", aws_uri(bucket, prefix.rstrip("/") + "/"), "--recursive"])
    dates: set[str] = set()
    for line in proc.stdout.splitlines():
        if "trade_date=" not in line:
            continue
        try:
            dates.add(line.split("trade_date=", 1)[1].split("/", 1)[0])
        except IndexError:
            continue
    return sorted(dates)


def latest_trade_date(bucket: str, prefix: str, today: str) -> str:
    dates = [d for d in list_partition_dates(bucket, prefix) if d <= today]
    if not dates:
        raise RuntimeError(f"no trade_date partitions under {prefix}")
    return dates[-1]


def recent_trade_dates(bucket: str, prefix: str, end_date: str, lookback: int) -> list[str]:
    dates = [d for d in list_partition_dates(bucket, prefix) if d <= end_date]
    if end_date not in dates:
        dates.append(end_date)
        dates = sorted(set(dates))
    idx = dates.index(end_date)
    return dates[max(0, idx - lookback) : idx + 1]


def normalize_ts_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper().replace(" ", "")
    if not text or text == "NAN":
        return None
    match = re.search(r"(\d{6})(?:\.(SH|SZ|BJ|KP|TI|DC))?", text)
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


def clean_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"": None, "None": None, "nan": None, "NaN": None}),
        errors="coerce",
    )


def is_noise_topic(topic: Any) -> bool:
    text = "" if topic is None else str(topic).strip()
    if not text or text.lower() == "nan":
        return True
    return any(marker in text for marker in NOISE_MARKERS)


def safe_div(num: float, den: float) -> float:
    if den is None or abs(den) < 1e-12 or math.isnan(den):
        return 0.0
    return float(num) / float(den)


def percentile_rank(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    return series.rank(method="average", pct=True).fillna(0.0)


def positive_hhi(values: pd.Series) -> dict[str, float | int]:
    positive = pd.to_numeric(values, errors="coerce").fillna(0.0).clip(lower=0.0)
    positive = positive[positive > 0]
    total = float(positive.sum())
    n = int(len(positive))
    if total <= 0 or n == 0:
        return {
            "hhi": 0.0,
            "hhi_norm": 0.0,
            "top1_share": 0.0,
            "top3_share": 0.0,
            "positive_count": 0,
        }
    shares = (positive / total).sort_values(ascending=False)
    hhi = float((shares * shares).sum())
    hhi_norm = 1.0 if n == 1 else (hhi - 1.0 / n) / (1.0 - 1.0 / n)
    return {
        "hhi": hhi,
        "hhi_norm": hhi_norm,
        "top1_share": float(shares.iloc[0]),
        "top3_share": float(shares.head(3).sum()),
        "positive_count": n,
    }


def dataset_keys(day: str) -> dict[str, list[str]]:
    return {
        "daily": [f"{S3_PREFIX}/行情数据/daily_incremental/trade_date={day}/daily_{day}.csv"],
        "daily_basic": [f"{S3_PREFIX}/行情数据/daily_basic_incremental/trade_date={day}/daily_basic_{day}.csv"],
        "moneyflow_dc": [f"{S3_PREFIX}/资金流向数据/个股资金流向_DC/trade_date={day}/moneyflow_dc_{day}.csv"],
        "moneyflow_ths": [f"{S3_PREFIX}/资金流向数据/个股资金流向_THS/trade_date={day}/moneyflow_ths_{day}.csv"],
        "moneyflow": [f"{S3_PREFIX}/资金流向数据/个股资金流向/trade_date={day}/moneyflow_{day}.csv"],
        "limit_list_d": [f"{S3_PREFIX}/打板专题数据/涨跌停数据/trade_date={day}/limit_list_d_{day}.csv"],
        "kpl_concept_cons": [
            f"{S3_PREFIX}/打板专题数据/开盘啦题材成分/trade_date={day}/kpl_concept_cons_{day}.csv",
            f"{S3_PREFIX}/特色数据/开盘啦题材成分/trade_date={day}/kpl_concept_cons_{day}.csv",
        ],
        "dc_concept_cons": [
            f"{S3_PREFIX}/打板专题数据/东方财富题材成分/trade_date={day}/dc_concept_cons_{day}.csv",
            f"{S3_PREFIX}/特色数据/东方财富题材成分/trade_date={day}/dc_concept_cons_{day}.csv",
        ],
        "dc_concept": [
            f"{S3_PREFIX}/打板专题数据/题材数据/trade_date={day}/dc_concept_{day}.csv",
            f"{S3_PREFIX}/特色数据/东方财富概念板块/trade_date={day}/dc_concept_{day}.csv",
        ],
        "dc_index": [
            f"{S3_PREFIX}/打板专题数据/东方财富概念板块/trade_date={day}/dc_index_{day}.csv",
            f"{S3_PREFIX}/特色数据/东方财富概念板块/trade_date={day}/dc_index_{day}.csv",
        ],
        "dc_member": [
            f"{S3_PREFIX}/打板专题数据/东方财富概念成分/trade_date={day}/dc_member_{day}.csv",
            f"{S3_PREFIX}/特色数据/东方财富概念成分/trade_date={day}/dc_member_{day}.csv",
        ],
    }


def load_daily_amount(bucket: str, day: str) -> tuple[pd.DataFrame, float]:
    loaded = read_s3_csv(bucket, dataset_keys(day)["daily"], "daily", required=True)
    df = loaded.df.copy()
    if "amount" not in df.columns:
        raise RuntimeError(f"daily has no amount column: {loaded.key}")
    df["ts_code"] = df["ts_code"].map(normalize_ts_code)
    df["amount_wan"] = clean_num(df["amount"]) / 10.0
    df["pct_chg"] = clean_num(df.get("pct_chg", pd.Series(index=df.index)))
    return df, float(df["amount_wan"].sum(skipna=True))


def load_market_turnover_baseline(bucket: str, day: str, baseline_days: int) -> dict[str, Any]:
    dates = recent_trade_dates(bucket, f"{S3_PREFIX}/行情数据/daily_incremental", day, baseline_days)
    totals: list[dict[str, Any]] = []
    for d in dates:
        try:
            _, total = load_daily_amount(bucket, d)
            totals.append({"trade_date": d, "market_amount_wan": total})
        except Exception as exc:  # noqa: BLE001
            totals.append({"trade_date": d, "market_amount_wan": None, "error": str(exc)})
    today_total = next((x["market_amount_wan"] for x in totals if x["trade_date"] == day), 0.0) or 0.0
    history = [x["market_amount_wan"] for x in totals if x["trade_date"] < day and x["market_amount_wan"] is not None]
    baseline = float(pd.Series(history[-baseline_days:]).mean()) if history else 0.0
    delta = today_total - baseline
    return {
        "trade_dates": dates,
        "market_amount_wan": today_total,
        "baseline_amount_wan": baseline,
        "external_increment_wan": max(delta, 0.0),
        "raw_market_amount_delta_wan": delta,
        "history": totals,
    }


def load_moneyflow(bucket: str, day: str) -> LoadedFrame:
    keys = dataset_keys(day)
    for name in ("moneyflow_dc", "moneyflow_ths", "moneyflow"):
        loaded = read_s3_csv(bucket, keys[name], name)
        if loaded.df.empty:
            continue
        df = loaded.df.copy()
        if "ts_code" not in df.columns:
            continue
        df["ts_code"] = df["ts_code"].map(normalize_ts_code)
        if "net_amount" in df.columns:
            df["net_amount_wan"] = clean_num(df["net_amount"])
        elif "net_mf_amount" in df.columns:
            df["net_amount_wan"] = clean_num(df["net_mf_amount"])
        else:
            buy_cols = [c for c in ("buy_elg_amount", "buy_lg_amount") if c in df.columns]
            sell_cols = [c for c in ("sell_elg_amount", "sell_lg_amount") if c in df.columns]
            if buy_cols and sell_cols:
                df["net_amount_wan"] = sum(clean_num(df[c]) for c in buy_cols) - sum(clean_num(df[c]) for c in sell_cols)
            else:
                continue
        df["main_net_amount_wan"] = 0.0
        for col in ("buy_elg_amount", "buy_lg_amount"):
            if col in df.columns:
                df["main_net_amount_wan"] += clean_num(df[col]).fillna(0.0)
        df = df.dropna(subset=["ts_code"]).drop_duplicates("ts_code", keep="first")
        return LoadedFrame(name=name, df=df, key=loaded.key, status="ok")
    raise RuntimeError(f"no usable moneyflow data for {day}")


def load_stock_frame(bucket: str, day: str) -> tuple[pd.DataFrame, dict[str, LoadedFrame]]:
    keys = dataset_keys(day)
    loaded_daily = read_s3_csv(bucket, keys["daily"], "daily", required=True)
    loaded_basic = read_s3_csv(bucket, keys["daily_basic"], "daily_basic", required=True)
    loaded_money = load_moneyflow(bucket, day)
    loaded_limit = read_s3_csv(bucket, keys["limit_list_d"], "limit_list_d")

    daily = loaded_daily.df.copy()
    daily["ts_code"] = daily["ts_code"].map(normalize_ts_code)
    daily["amount_wan"] = clean_num(daily.get("amount", pd.Series(index=daily.index))) / 10.0
    daily["pct_chg_daily"] = clean_num(daily.get("pct_chg", pd.Series(index=daily.index)))
    daily = daily[["ts_code", "amount_wan", "pct_chg_daily"]].dropna(subset=["ts_code"]).drop_duplicates("ts_code")

    basic = loaded_basic.df.copy()
    basic["ts_code"] = basic["ts_code"].map(normalize_ts_code)
    basic["circ_mv_wan"] = clean_num(basic.get("circ_mv", pd.Series(index=basic.index)))
    basic["turnover_rate"] = clean_num(basic.get("turnover_rate", pd.Series(index=basic.index)))
    basic["turnover_rate_f"] = clean_num(basic.get("turnover_rate_f", pd.Series(index=basic.index)))
    basic = basic[["ts_code", "circ_mv_wan", "turnover_rate", "turnover_rate_f"]].dropna(subset=["ts_code"]).drop_duplicates("ts_code")

    money = loaded_money.df.copy()
    keep_cols = ["ts_code", "net_amount_wan", "main_net_amount_wan"]
    for col in ("name", "pct_change", "close"):
        if col in money.columns:
            keep_cols.append(col)
    money = money[keep_cols].copy()
    if "pct_change" in money.columns:
        money["pct_chg_moneyflow"] = clean_num(money["pct_change"])
        money = money.drop(columns=["pct_change"])

    stock = money.merge(daily, on="ts_code", how="left").merge(basic, on="ts_code", how="left")
    if "pct_chg_moneyflow" in stock.columns:
        stock["pct_chg"] = stock["pct_chg_moneyflow"].fillna(stock["pct_chg_daily"])
    else:
        stock["pct_chg"] = stock["pct_chg_daily"]

    if not loaded_limit.df.empty:
        lim = loaded_limit.df.copy()
        lim["ts_code"] = lim["ts_code"].map(normalize_ts_code)
        lim["limit_flag"] = lim.get("limit", "")
        lim["first_time"] = lim.get("first_time", "")
        lim["last_time"] = lim.get("last_time", "")
        lim["open_times"] = clean_num(lim.get("open_times", pd.Series(index=lim.index))).fillna(0.0)
        lim["limit_times"] = clean_num(lim.get("limit_times", pd.Series(index=lim.index))).fillna(0.0)
        lim = lim[["ts_code", "limit_flag", "first_time", "last_time", "open_times", "limit_times"]].dropna(subset=["ts_code"])
        stock = stock.merge(lim.drop_duplicates("ts_code"), on="ts_code", how="left")
    else:
        stock["limit_flag"] = ""
        stock["first_time"] = ""
        stock["last_time"] = ""
        stock["open_times"] = 0.0
        stock["limit_times"] = 0.0

    stock["amount_wan"] = stock["amount_wan"].fillna(0.0)
    stock["circ_mv_wan"] = stock["circ_mv_wan"].fillna(0.0)
    stock["turnover_rate"] = stock["turnover_rate"].fillna(0.0)
    stock["open_times"] = stock["open_times"].fillna(0.0)
    stock["trade_date"] = day
    return stock, {
        "daily": loaded_daily,
        "daily_basic": loaded_basic,
        "moneyflow": loaded_money,
        "limit_list_d": loaded_limit,
    }


def add_topic_rows(rows: list[dict[str, Any]], source: str, df: pd.DataFrame, stock_col: str, topic_col: str, weight: float) -> None:
    if df.empty or stock_col not in df.columns or topic_col not in df.columns:
        return
    for _, row in df[[stock_col, topic_col]].dropna().iterrows():
        code = normalize_ts_code(row[stock_col])
        topic = str(row[topic_col]).strip()
        if not code or is_noise_topic(topic):
            continue
        rows.append({"ts_code": code, "topic": topic[:40], "source": source, "source_weight": weight})


def load_topic_map(bucket: str, day: str) -> tuple[pd.DataFrame, dict[str, LoadedFrame]]:
    keys = dataset_keys(day)
    loaded: dict[str, LoadedFrame] = {
        name: read_s3_csv(bucket, keys[name], name)
        for name in ("kpl_concept_cons", "dc_concept_cons", "dc_concept", "dc_index", "dc_member", "limit_list_d")
    }
    rows: list[dict[str, Any]] = []

    kpl = loaded["kpl_concept_cons"].df
    add_topic_rows(rows, "kpl_concept_cons", kpl, "con_code", "name", 1.25)

    dc_theme = loaded["dc_concept"].df
    theme_name: dict[str, str] = {}
    if not dc_theme.empty and {"theme_code", "name"}.issubset(dc_theme.columns):
        theme_name = {
            str(r["theme_code"]).strip(): str(r["name"]).strip()
            for _, r in dc_theme[["theme_code", "name"]].dropna().drop_duplicates().iterrows()
        }

    dc_cons = loaded["dc_concept_cons"].df
    if not dc_cons.empty:
        if {"ts_code", "theme_code"}.issubset(dc_cons.columns):
            temp = dc_cons[["ts_code", "theme_code"]].copy()
            temp["topic"] = temp["theme_code"].map(lambda x: theme_name.get(str(x).strip(), ""))
            add_topic_rows(rows, "dc_concept_cons", temp, "ts_code", "topic", 1.0)
        add_topic_rows(rows, "dc_industry", dc_cons, "ts_code", "industry", 0.35)

    dc_index = loaded["dc_index"].df
    index_name: dict[str, str] = {}
    if not dc_index.empty and {"ts_code", "name"}.issubset(dc_index.columns):
        index_name = {
            str(r["ts_code"]).strip(): str(r["name"]).strip()
            for _, r in dc_index[["ts_code", "name"]].dropna().drop_duplicates().iterrows()
        }
    dc_member = loaded["dc_member"].df
    if not dc_member.empty and {"ts_code", "con_code"}.issubset(dc_member.columns):
        temp = dc_member[["ts_code", "con_code"]].copy()
        temp["topic"] = temp["ts_code"].map(lambda x: index_name.get(str(x).strip(), ""))
        add_topic_rows(rows, "dc_member", temp, "con_code", "topic", 0.90)

    limits = loaded["limit_list_d"].df
    add_topic_rows(rows, "limit_list_d_industry", limits, "ts_code", "industry", 0.25)

    topic_map = pd.DataFrame(rows)
    if topic_map.empty:
        return topic_map, loaded
    topic_map = (
        topic_map.groupby(["ts_code", "topic", "source"], as_index=False)["source_weight"].max()
        .groupby(["ts_code", "topic"], as_index=False)
        .agg(source_weight=("source_weight", "sum"), sources=("source", lambda x: ",".join(sorted(set(x)))))
    )
    stock_weight_sum = topic_map.groupby("ts_code")["source_weight"].transform("sum")
    topic_map["alloc_weight"] = topic_map["source_weight"] / stock_weight_sum.replace(0, pd.NA)
    topic_map["alloc_weight"] = topic_map["alloc_weight"].fillna(0.0)
    return topic_map, loaded


def build_topic_liquidity(
    stock: pd.DataFrame,
    topic_map: pd.DataFrame,
    market: dict[str, Any],
    rotation_lambda: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if topic_map.empty:
        raise RuntimeError("empty topic map; cannot build liquidity HHI")
    alloc = topic_map.merge(stock, on="ts_code", how="inner")
    if alloc.empty:
        raise RuntimeError("topic map and moneyflow stocks have no overlap")

    for col in ("net_amount_wan", "main_net_amount_wan", "amount_wan", "circ_mv_wan", "pct_chg", "turnover_rate"):
        alloc[col] = clean_num(alloc[col]).fillna(0.0)

    alloc["alloc_net_amount_wan"] = alloc["net_amount_wan"] * alloc["alloc_weight"]
    alloc["alloc_main_net_amount_wan"] = alloc["main_net_amount_wan"] * alloc["alloc_weight"]
    alloc["alloc_amount_wan"] = alloc["amount_wan"] * alloc["alloc_weight"]
    alloc["alloc_circ_mv_wan"] = alloc["circ_mv_wan"] * alloc["alloc_weight"]
    alloc["limit_up_stock"] = alloc.get("limit_flag", "").astype(str).eq("U")
    alloc["limit_down_stock"] = alloc.get("limit_flag", "").astype(str).eq("D")

    topic = (
        alloc.groupby("topic", as_index=False)
        .agg(
            stock_count=("ts_code", "nunique"),
            topic_net_amount_wan=("alloc_net_amount_wan", "sum"),
            topic_main_net_amount_wan=("alloc_main_net_amount_wan", "sum"),
            topic_turnover_wan=("alloc_amount_wan", "sum"),
            topic_circ_mv_wan=("alloc_circ_mv_wan", "sum"),
            avg_pct_chg=("pct_chg", "mean"),
            avg_turnover_rate=("turnover_rate", "mean"),
            limit_up_count=("limit_up_stock", "sum"),
            limit_down_count=("limit_down_stock", "sum"),
            avg_open_times=("open_times", "mean"),
            sources=("sources", lambda x: ",".join(sorted(set(",".join(x).split(","))))),
        )
        .sort_values("topic_net_amount_wan", ascending=False)
        .reset_index(drop=True)
    )
    leader_hhi_rows: list[dict[str, Any]] = []
    for topic_name, group in alloc.groupby("topic", sort=False):
        by_stock = group.groupby("ts_code")["alloc_net_amount_wan"].sum()
        metrics = positive_hhi(by_stock)
        leader_hhi_rows.append(
            {
                "topic": topic_name,
                "leader_flow_hhi": metrics["hhi"],
                "leader_flow_hhi_norm": metrics["hhi_norm"],
                "leader_top1_flow_share": metrics["top1_share"],
                "leader_top3_flow_share": metrics["top3_share"],
                "positive_leader_count": metrics["positive_count"],
            }
        )
    if leader_hhi_rows:
        topic = topic.merge(pd.DataFrame(leader_hhi_rows), on="topic", how="left")
    else:
        topic["leader_flow_hhi"] = 0.0
        topic["leader_flow_hhi_norm"] = 0.0
        topic["leader_top1_flow_share"] = 0.0
        topic["leader_top3_flow_share"] = 0.0
        topic["positive_leader_count"] = 0
    topic["positive_flow_wan"] = topic["topic_net_amount_wan"].clip(lower=0.0)
    topic["negative_flow_wan"] = (-topic["topic_net_amount_wan"]).clip(lower=0.0)
    positive_sum = float(topic["positive_flow_wan"].sum())
    rotation_release = float(topic["negative_flow_wan"].sum())
    external_increment = float(market["external_increment_wan"])
    available_pool = external_increment + rotation_lambda * rotation_release
    n_positive = int((topic["positive_flow_wan"] > 0).sum())

    topic["flow_share"] = topic["positive_flow_wan"].map(lambda x: safe_div(float(x), positive_sum))
    hhi = float((topic["flow_share"] ** 2).sum())
    hhi_norm = safe_div(hhi - safe_div(1.0, n_positive), 1.0 - safe_div(1.0, n_positive)) if n_positive > 1 else 1.0

    market_amount = float(market["market_amount_wan"])
    topic["market_turnover_share"] = topic["topic_turnover_wan"].map(lambda x: safe_div(float(x), market_amount))
    topic["external_capture"] = topic["positive_flow_wan"].map(lambda x: safe_div(float(x), available_pool))
    topic["positive_pool_capture"] = topic["flow_share"]
    topic["demand_pressure"] = topic.apply(
        lambda r: safe_div(float(r["positive_flow_wan"]), float(r["topic_circ_mv_wan"])), axis=1
    )
    topic["turnover_supply"] = topic.apply(
        lambda r: safe_div(float(r["topic_turnover_wan"]), float(r["topic_circ_mv_wan"])), axis=1
    )
    topic["supply_pressure"] = topic["turnover_supply"] + 0.0025 * topic["avg_open_times"].fillna(0.0)
    topic["demand_supply_ratio"] = topic.apply(
        lambda r: safe_div(float(r["demand_pressure"]), float(r["supply_pressure"]) + 1e-9), axis=1
    )
    topic["limit_breadth"] = topic.apply(lambda r: safe_div(float(r["limit_up_count"]), float(r["stock_count"])), axis=1)

    topic["rank_flow_share"] = percentile_rank(topic["flow_share"])
    topic["rank_external_capture"] = percentile_rank(topic["external_capture"])
    topic["rank_demand_supply"] = percentile_rank(topic["demand_supply_ratio"])
    topic["rank_limit_breadth"] = percentile_rank(topic["limit_breadth"])
    topic["liquidity_heat_score"] = (
        0.35 * topic["rank_flow_share"]
        + 0.25 * topic["rank_external_capture"]
        + 0.25 * topic["rank_demand_supply"]
        + 0.15 * topic["rank_limit_breadth"]
    )
    topic = topic.sort_values(["liquidity_heat_score", "positive_flow_wan"], ascending=False).reset_index(drop=True)

    leader = alloc.merge(
        topic[["topic", "flow_share", "external_capture", "demand_supply_ratio", "liquidity_heat_score"]],
        on="topic",
        how="left",
    )
    leader["stock_demand_pressure"] = leader.apply(
        lambda r: safe_div(float(r["net_amount_wan"]), float(r["circ_mv_wan"])), axis=1
    )
    leader["stock_turnover_supply"] = leader.apply(
        lambda r: safe_div(float(r["amount_wan"]), float(r["circ_mv_wan"])), axis=1
    )
    leader["rank_stock_demand"] = percentile_rank(leader["stock_demand_pressure"])
    leader["rank_price"] = percentile_rank(leader["pct_chg"])
    leader["rank_topic_heat"] = percentile_rank(leader["liquidity_heat_score"])
    leader["limit_bonus"] = leader["limit_up_stock"].astype(float)
    leader["open_penalty"] = clean_num(leader.get("open_times", pd.Series(index=leader.index))).fillna(0.0).clip(lower=0.0) / 10.0
    leader["leader_demand_supply_score"] = (
        0.34 * leader["rank_stock_demand"]
        + 0.22 * leader["rank_price"]
        + 0.20 * leader["rank_topic_heat"]
        + 0.16 * leader["limit_bonus"]
        - 0.08 * percentile_rank(leader["stock_turnover_supply"])
        - 0.08 * leader["open_penalty"]
    )
    leader_cols = [
        "trade_date",
        "topic",
        "ts_code",
        "name",
        "sources",
        "leader_demand_supply_score",
        "stock_demand_pressure",
        "stock_turnover_supply",
        "net_amount_wan",
        "amount_wan",
        "circ_mv_wan",
        "pct_chg",
        "limit_flag",
        "first_time",
        "open_times",
        "flow_share",
        "liquidity_heat_score",
    ]
    if "trade_date" not in leader.columns:
        leader["trade_date"] = ""
    if "name" not in leader.columns:
        leader["name"] = ""
    leaders = (
        leader[leader_cols]
        .sort_values(["topic", "leader_demand_supply_score"], ascending=[True, False])
        .groupby("topic", as_index=False, group_keys=False)
        .head(8)
        .sort_values("leader_demand_supply_score", ascending=False)
        .reset_index(drop=True)
    )

    summary = {
        "positive_flow_sum_wan": positive_sum,
        "rotation_release_wan": rotation_release,
        "external_increment_wan": external_increment,
        "available_incremental_pool_wan": available_pool,
        "hhi": hhi,
        "hhi_norm": hhi_norm,
        "positive_topic_count": n_positive,
        "top1_share": float(topic["flow_share"].max()) if not topic.empty else 0.0,
        "top3_share": float(topic["flow_share"].head(3).sum()) if not topic.empty else 0.0,
    }
    return topic, leaders, summary


def build_stock_signals(stock: pd.DataFrame, topic_map: pd.DataFrame, topic: pd.DataFrame) -> pd.DataFrame:
    """Build stock-level scores using the same formulas as the research backtest."""
    alloc = topic_map.merge(stock, on="ts_code", how="inner").merge(
        topic[
            [
                "topic",
                "flow_share",
                "external_capture",
                "liquidity_heat_score",
                "leader_flow_hhi_norm",
                "positive_flow_wan",
            ]
        ],
        on="topic",
        how="left",
    )
    if alloc.empty:
        return pd.DataFrame()
    for col in (
        "net_amount_wan",
        "alloc_weight",
        "flow_share",
        "external_capture",
        "liquidity_heat_score",
        "leader_flow_hhi_norm",
        "positive_flow_wan",
        "pct_chg",
        "amount_wan",
        "circ_mv_wan",
        "turnover_rate",
        "open_times",
    ):
        alloc[col] = clean_num(alloc.get(col, pd.Series(index=alloc.index))).fillna(0.0)
    alloc["alloc_net_amount_wan"] = alloc["net_amount_wan"] * alloc["alloc_weight"]
    alloc["stock_positive_share_in_topic"] = alloc.apply(
        lambda r: safe_div(max(float(r["alloc_net_amount_wan"]), 0.0), float(r["positive_flow_wan"])),
        axis=1,
    )
    alloc["topic_flow_hhi"] = alloc["alloc_weight"] * alloc["flow_share"]
    alloc["leader_flow_hhi"] = (
        alloc["alloc_weight"]
        * alloc["flow_share"]
        * alloc["leader_flow_hhi_norm"]
        * alloc["stock_positive_share_in_topic"]
    )
    alloc["topic_demand_contribution"] = alloc["alloc_weight"] * alloc["liquidity_heat_score"]
    signal = (
        alloc.groupby("ts_code", as_index=False)
        .agg(
            name=("name", lambda x: next((str(v) for v in x if pd.notna(v) and str(v).strip()), "")),
            topic_flow_hhi=("topic_flow_hhi", "sum"),
            leader_flow_hhi=("leader_flow_hhi", "sum"),
            topic_demand_contribution=("topic_demand_contribution", "sum"),
            topic_count=("topic", "nunique"),
            positive_net_amount_wan=("net_amount_wan", lambda x: float(pd.to_numeric(x, errors="coerce").clip(lower=0).sum())),
            net_amount_wan=("net_amount_wan", "first"),
            amount_wan=("amount_wan", "first"),
            circ_mv_wan=("circ_mv_wan", "first"),
            pct_chg=("pct_chg", "first"),
            turnover_rate=("turnover_rate", "first"),
            limit_flag=("limit_flag", "first"),
            first_time=("first_time", "first"),
            open_times=("open_times", "first"),
            strongest_topic=("topic", lambda x: next(iter(x), "")),
            strongest_topic_heat=("liquidity_heat_score", "max"),
            strongest_topic_flow_share=("flow_share", "max"),
        )
    )
    signal["trade_date"] = str(stock["trade_date"].iloc[0]) if "trade_date" in stock.columns and not stock.empty else ""
    signal["dragon_score"] = (
        0.78 * percentile_rank(signal["topic_flow_hhi"])
        + 0.10 * percentile_rank(signal["positive_net_amount_wan"])
        + 0.05 * percentile_rank(signal["leader_flow_hhi"])
        + 0.05 * signal["limit_flag"].astype(str).eq("U").astype(float)
        - 0.02 * percentile_rank(signal["open_times"])
    )
    return signal.sort_values(["dragon_score", "topic_flow_hhi"], ascending=False).reset_index(drop=True)


def write_outputs(
    out_root: Path,
    day: str,
    payload: dict[str, Any],
    topic: pd.DataFrame,
    leaders: pd.DataFrame,
    stock_signals: pd.DataFrame | None = None,
) -> dict[str, str]:
    out_dir = out_root / f"{day[:4]}-{day[4:6]}-{day[6:]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"topic_liquidity_hhi_{day}.json"
    topic_path = out_dir / f"topic_liquidity_topics_{day}.csv"
    leader_path = out_dir / f"topic_liquidity_leaders_{day}.csv"
    signals_path = out_dir / f"topic_liquidity_stock_signals_{day}.csv"
    latest_json = out_root / "latest.json"
    latest_topics = out_root / "latest_topics.csv"
    latest_leaders = out_root / "latest_leaders.csv"
    latest_signals = out_root / "latest_stock_signals.csv"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    topic.to_csv(topic_path, index=False)
    leaders.to_csv(leader_path, index=False)
    if stock_signals is not None and not stock_signals.empty:
        stock_signals.to_csv(signals_path, index=False)
        stock_signals.to_csv(latest_signals, index=False)
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    topic.to_csv(latest_topics, index=False)
    leaders.to_csv(latest_leaders, index=False)
    paths = {
        "json": str(json_path),
        "topics_csv": str(topic_path),
        "leaders_csv": str(leader_path),
        "latest_json": str(latest_json),
        "latest_topics_csv": str(latest_topics),
        "latest_leaders_csv": str(latest_leaders),
    }
    if stock_signals is not None and not stock_signals.empty:
        paths["stock_signals_csv"] = str(signals_path)
        paths["latest_stock_signals_csv"] = str(latest_signals)
    return paths


def run(args: argparse.Namespace) -> dict[str, Any]:
    today = datetime.now(TZ_BJ).strftime("%Y%m%d")
    day = args.trade_date or latest_trade_date(args.bucket, f"{S3_PREFIX}/行情数据/daily_incremental", today)
    market = load_market_turnover_baseline(args.bucket, day, args.baseline_days)
    stock, stock_sources = load_stock_frame(args.bucket, day)
    topic_map, topic_sources = load_topic_map(args.bucket, day)
    topic, leaders, flow_summary = build_topic_liquidity(stock, topic_map, market, args.rotation_lambda)
    stock_signals = build_stock_signals(stock, topic_map, topic)
    if "trade_date" not in topic.columns:
        topic.insert(0, "trade_date", day)
    topic["global_flow_hhi"] = flow_summary["hhi"]
    topic["global_flow_hhi_norm"] = flow_summary["hhi_norm"]
    payload = {
        "trade_date": day,
        "generated_at_bj": datetime.now(TZ_BJ).isoformat(),
        "method": {
            "version": "topic_liquidity_hhi_v1",
            "external_increment": "max(today_market_turnover_wan - rolling_baseline_turnover_wan, 0)",
            "rotation_release": "sum(max(-topic_net_flow_wan, 0))",
            "available_pool": "external_increment + rotation_lambda * rotation_release",
            "hhi": "sum((positive_topic_flow / sum_positive_topic_flow)^2)",
            "overlap_control": "stock-topic source weights are normalized within each stock before aggregation",
            "unit_note": "daily.amount is converted from thousand yuan to wan yuan; moneyflow_dc/net_amount and daily_basic/circ_mv are treated as wan yuan",
        },
        "params": {
            "baseline_days": args.baseline_days,
            "rotation_lambda": args.rotation_lambda,
            "bucket": args.bucket,
        },
        "market": market,
        "flow_summary": flow_summary,
        "source_status": {
            k: {"status": v.status, "key": v.key, "rows": int(len(v.df)), "detail": v.detail}
            for k, v in {**stock_sources, **topic_sources}.items()
        },
        "top_topics": topic.head(args.top_n).to_dict(orient="records"),
        "top_leaders": leaders.head(args.top_n * 3).to_dict(orient="records"),
        "top_stock_signals": stock_signals.head(args.top_n * 3).to_dict(orient="records"),
    }
    paths = write_outputs(Path(args.out_root), day, payload, topic, leaders, stock_signals)
    payload["paths"] = paths
    Path(paths["json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(paths["latest_json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build topic liquidity HHI and demand/supply leader tables from Tushare S3 raw data.")
    parser.add_argument("--trade-date", default="", help="YYYYMMDD. Default: latest daily_incremental partition <= Beijing today.")
    parser.add_argument("--bucket", default=S3_BUCKET)
    parser.add_argument("--baseline-days", type=int, default=20)
    parser.add_argument("--rotation-lambda", type=float, default=1.0)
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--top-n", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    payload = run(parse_args())
    summary = payload["flow_summary"]
    print(
        "TOPIC_LIQUIDITY_HHI_OK "
        f"trade_date={payload['trade_date']} "
        f"hhi={summary['hhi']:.4f} "
        f"hhi_norm={summary['hhi_norm']:.4f} "
        f"top1={summary['top1_share']:.2%} "
        f"top3={summary['top3_share']:.2%}"
    )
    print(f"JSON: {payload['paths']['json']}")
    print(f"TOPICS: {payload['paths']['topics_csv']}")
    print(f"LEADERS: {payload['paths']['leaders_csv']}")
    for row in payload["top_topics"][:5]:
        print(
            f"- {row['topic']} score={row['liquidity_heat_score']:.3f} "
            f"flow_share={row['flow_share']:.2%} net_wan={row['topic_net_amount_wan']:.0f} "
            f"leaders={int(row['limit_up_count'])}/{int(row['stock_count'])}"
        )


if __name__ == "__main__":
    main()
