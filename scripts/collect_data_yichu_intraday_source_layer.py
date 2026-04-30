#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts


ROOT = Path("/home/ubuntu/.openclaw/workspace")
OUT_ROOT = ROOT / "runs" / "data-yichu-source-layer-intraday"
CACHE_ROOT = ROOT / "cache" / "data-yichu-intraday-tushare"
TOKEN_FILE = Path(
    "/home/ubuntu/.openclaw/media/inbound/"
    "tushares_token---f5492736-ee8f-4214-b0de-0422f0cfa0a3"
)

S3_BUCKET = "yufan-data-lake"
S3_PREFIX = "tushares/打板专题数据"
KPL_TAGS = ("涨停", "自然涨停", "炸板", "竞价")
TZ_BJ = timezone(timedelta(hours=8))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def bj_now(dt: datetime) -> datetime:
    return dt.astimezone(TZ_BJ)


def compact_dt(dt: datetime) -> str:
    return dt.strftime("%H%M%S")


def trade_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def read_token() -> str | None:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        return token
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        return token or None
    return None


def init_tushare() -> Any | None:
    token = read_token()
    if not token:
        return None
    ts.set_token(token)
    return ts.pro_api(token)


def clean_num(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    return pd.to_numeric(
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"": None, "None": None, "nan": None}),
        errors="coerce",
    )


def normalize_ts_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    text = text.replace(" ", "")
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


def bare_code(ts_code: str | None) -> str:
    if not ts_code:
        return ""
    return str(ts_code).split(".", 1)[0]


def split_topics(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    parts = re.split(r"[、,，/;；|｜]+", text)
    out: list[str] = []
    for part in parts:
        item = part.strip()
        if not item or item.lower() == "nan":
            continue
        if len(item) > 32:
            item = item[:32]
        out.append(item)
    return list(dict.fromkeys(out))


def is_broad_market_topic(topic: str) -> bool:
    text = str(topic).strip()
    if not text:
        return True
    broad_markers = (
        "全A",
        "全Ａ",
        "沪深全",
        "沪深300",
        "中证",
        "上证指数",
        "深证成指",
        "创业板指",
        "科创50",
        "北证50",
        "样本股",
        "等权",
        "加权",
        "除金融",
        "除科创板",
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
    )
    return any(marker in text for marker in broad_markers)


def run_cmd(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def s3_uri(key: str) -> str:
    return f"s3://{S3_BUCKET}/{key}"


def s3_read_csv(key: str, status: dict[str, Any], label: str) -> pd.DataFrame:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="tushare_intraday_", suffix=".csv") as tmp:
        proc = run_cmd(["aws", "s3", "cp", s3_uri(key), tmp.name, "--only-show-errors"], timeout=120)
        if proc.returncode != 0:
            status[label] = {"status": "missing", "key": key, "detail": proc.stderr[-300:]}
            return pd.DataFrame()
        try:
            df = pd.read_csv(tmp.name)
        except Exception as exc:  # noqa: BLE001
            status[label] = {"status": "failed", "key": key, "detail": str(exc)}
            return pd.DataFrame()
    status[label] = {"status": "ok", "key": key, "rows": int(len(df))}
    return df


def s3_list_keys(prefix: str) -> list[str]:
    proc = run_cmd(["aws", "s3", "ls", s3_uri(prefix), "--recursive"], timeout=240)
    if proc.returncode != 0:
        return []
    keys: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[3].endswith(".csv"):
            keys.append(parts[3])
    return keys


def latest_partition_key(prefix: str, file_prefix: str, max_trade_date: str) -> str | None:
    keys = s3_list_keys(prefix)
    best: tuple[str, str] | None = None
    for key in keys:
        if f"/{file_prefix}_" not in key and not key.endswith(f"/{file_prefix}.csv"):
            continue
        match = re.search(r"trade_date=(\d{8})", key)
        if not match:
            continue
        dt = match.group(1)
        if dt > max_trade_date:
            continue
        if best is None or dt > best[0] or (dt == best[0] and key > best[1]):
            best = (dt, key)
    return best[1] if best else None


def fetch_paged(pro: Any | None, fetcher: str, page_size: int, **kwargs: Any) -> pd.DataFrame:
    if pro is None or not hasattr(pro, fetcher):
        return pd.DataFrame()
    func = getattr(pro, fetcher)
    frames: list[pd.DataFrame] = []
    offset = 0
    while True:
        call_kwargs = dict(kwargs)
        call_kwargs["limit"] = page_size
        call_kwargs["offset"] = offset
        try:
            df = func(**call_kwargs)
        except Exception:
            return pd.DataFrame()
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < page_size:
            break
        offset += page_size
        time.sleep(0.4)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def load_trade_date_dataset(
    pro: Any | None,
    name: str,
    dataset_dir: str,
    file_prefix: str,
    day: str,
    page_size: int,
    status: dict[str, Any],
    extra: dict[str, Any] | None = None,
    variant_label: str | None = None,
) -> pd.DataFrame:
    label = variant_label or name
    extra = extra or {}
    df = fetch_paged(pro, name, page_size, trade_date=day, **extra)
    if not df.empty:
        status[label] = {
            "status": "ok",
            "source": "tushare_pro",
            "trade_date": day,
            "rows": int(len(df)),
        }
        return df

    variant_bits = []
    if "tag" in extra:
        variant_bits.append(f"tag={extra['tag']}")
    base = f"{S3_PREFIX}/{dataset_dir}/" + ("/".join(variant_bits) + "/" if variant_bits else "")
    direct_key = f"{base}trade_date={day}/{file_prefix}_{day}.csv"
    df = s3_read_csv(direct_key, status, label)
    if not df.empty:
        status[label]["source"] = "s3_direct"
        return df

    key = latest_partition_key(base, file_prefix, day)
    if key:
        df = s3_read_csv(key, status, label)
        if not df.empty:
            status[label]["source"] = "s3_latest_fallback"
            status[label]["requested_trade_date"] = day
            return df
    status[label] = {
        "status": "missing",
        "source": "tushare_pro_then_s3",
        "requested_trade_date": day,
    }
    return pd.DataFrame()


def load_direct_snapshot(dataset_dir: str, filename: str, status: dict[str, Any], label: str) -> pd.DataFrame:
    return s3_read_csv(f"{S3_PREFIX}/{dataset_dir}/{filename}", status, label)


def load_kpl_list(pro: Any | None, day: str, status: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for tag in KPL_TAGS:
        df = load_trade_date_dataset(
            pro,
            "kpl_list",
            "开盘啦榜单数据",
            "kpl_list",
            day,
            8000,
            status,
            extra={"tag": tag},
            variant_label=f"kpl_list:{tag}",
        )
        if not df.empty:
            if "tag" not in df.columns:
                df["tag"] = tag
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def load_ths_member_flat(status: dict[str, Any]) -> pd.DataFrame:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    flat = CACHE_ROOT / "ths_member_flat.csv"
    if flat.exists() and time.time() - flat.stat().st_mtime < 7 * 86400:
        try:
            df = pd.read_csv(flat)
            status["ths_member"] = {"status": "ok", "source": "cache", "rows": int(len(df)), "path": str(flat)}
            return df
        except Exception as exc:  # noqa: BLE001
            status["ths_member"] = {"status": "cache_failed", "detail": str(exc), "path": str(flat)}

    sync_dir = CACHE_ROOT / "ths_member_s3"
    sync_dir.mkdir(parents=True, exist_ok=True)
    proc = run_cmd(
        [
            "aws",
            "s3",
            "sync",
            s3_uri(f"{S3_PREFIX}/同花顺行业概念成分/"),
            str(sync_dir),
            "--exclude",
            "*",
            "--include",
            "*/ths_member.csv",
            "--only-show-errors",
        ],
        timeout=900,
    )
    if proc.returncode != 0:
        status["ths_member"] = {"status": "failed", "source": "s3_sync", "detail": proc.stderr[-500:]}
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for path in sync_dir.glob("**/ths_member.csv"):
        try:
            df = pd.read_csv(path, usecols=lambda c: c in {"ts_code", "con_code", "con_name"})
        except Exception:
            continue
        frames.append(df)
    if not frames:
        status["ths_member"] = {"status": "missing", "source": "s3_sync"}
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True).drop_duplicates()
    out.to_csv(flat, index=False)
    status["ths_member"] = {"status": "ok", "source": "s3_sync", "rows": int(len(out)), "path": str(flat)}
    return out


def fetch_realtime(status: dict[str, Any]) -> pd.DataFrame:
    try:
        df = ts.realtime_list(src="dc")
    except Exception as exc:  # noqa: BLE001
        status["realtime_list"] = {"status": "failed", "detail": str(exc)}
        return pd.DataFrame()
    if df is None or df.empty:
        status["realtime_list"] = {"status": "empty"}
        return pd.DataFrame()
    df = df.copy()
    df.columns = [str(col).strip().lower() for col in df.columns]
    status["realtime_list"] = {"status": "ok", "source": "tushare.realtime_list(src='dc')", "rows": int(len(df))}
    return df


def build_strong_pool(realtime: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    if realtime.empty:
        return pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame()

    df = realtime.copy()
    if "ts_code" not in df.columns:
        return pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame()
    df["ts_code"] = df["ts_code"].map(normalize_ts_code)
    df = df[df["ts_code"].notna()].copy()
    for col in ("pct_change", "rise", "5min", "price", "amount", "turnover_rate", "total_mv", "float_mv"):
        if col in df.columns:
            df[col] = clean_num(df[col])
        else:
            df[col] = pd.NA

    df["code_prefix"] = df["ts_code"].map(bare_code)
    df["limit_threshold"] = df["code_prefix"].map(lambda c: 9.94 if c.startswith(("60", "00")) else 13.0)
    df["limit_up_threshold"] = df["pct_change"] > df["limit_threshold"]
    df["rise_rank"] = df["rise"].rank(method="first", ascending=False, na_option="bottom")
    df["five_min_rank"] = df["5min"].rank(method="first", ascending=False, na_option="bottom")
    df["rise_top100"] = df["rise_rank"] <= 100
    df["five_min_top100"] = df["five_min_rank"] <= 100
    df["strong_pool"] = df["limit_up_threshold"] | df["rise_top100"] | df["five_min_top100"]
    pool = df[df["strong_pool"]].copy()
    pool["trigger_flags"] = pool.apply(
        lambda row: ",".join(
            flag
            for flag, active in (
                ("limit_up_threshold", bool(row["limit_up_threshold"])),
                ("rise_top100", bool(row["rise_top100"])),
                ("five_min_top100", bool(row["five_min_top100"])),
            )
            if active
        ),
        axis=1,
    )
    pool = pool.sort_values(["limit_up_threshold", "pct_change", "rise", "5min"], ascending=[False, False, False, False])
    pool = pool.drop_duplicates(subset=["ts_code"], keep="first").reset_index(drop=True)
    top_rise = df.sort_values("rise", ascending=False).head(100).copy()
    top_five = df.sort_values("5min", ascending=False).head(100).copy()
    summary = {
        "realtime_rows": int(len(df)),
        "strong_pool_count": int(len(pool)),
        "limit_up_threshold_count": int(pool["limit_up_threshold"].sum()),
        "rise_top100_count": int(pool["rise_top100"].sum()),
        "five_min_top100_count": int(pool["five_min_top100"].sum()),
        "threshold_rule": "60/00开头 pct_change > 9.94；其他股票 pct_change > 13；并集包含涨速Top100与5分钟涨幅Top100。",
    }
    return pool, summary, top_rise, top_five


def row_value(row: pd.Series, *cols: str) -> Any:
    for col in cols:
        if col in row.index and pd.notna(row[col]):
            return row[col]
    return None


def build_topic_events(
    strong_pool: pd.DataFrame,
    kpl_list: pd.DataFrame,
    kpl_cons: pd.DataFrame,
    dc_concept: pd.DataFrame,
    dc_concept_cons: pd.DataFrame,
    dc_index: pd.DataFrame,
    dc_member: pd.DataFrame,
    ths_index: pd.DataFrame,
    ths_member: pd.DataFrame,
) -> list[dict[str, Any]]:
    if strong_pool.empty:
        return []

    strong = strong_pool.copy()
    strong["ts_code"] = strong["ts_code"].map(normalize_ts_code)
    strong = (
        strong.sort_values(["limit_up_threshold", "pct_change", "rise", "5min"], ascending=[False, False, False, False])
        .drop_duplicates(subset=["ts_code"], keep="first")
        .reset_index(drop=True)
    )
    stock_meta = strong.set_index("ts_code").to_dict(orient="index")
    strong_codes = set(stock_meta)
    events: list[dict[str, Any]] = []

    def add_event(ts_code: str | None, topic: str | None, source: str, reason: Any = None, topic_code: Any = None) -> None:
        norm = normalize_ts_code(ts_code)
        if not norm or norm not in strong_codes:
            return
        topic_text = str(topic).strip() if topic is not None and not pd.isna(topic) else ""
        if not topic_text or topic_text.lower() == "nan" or is_broad_market_topic(topic_text):
            return
        meta = stock_meta.get(norm, {})
        events.append(
            {
                "topic": topic_text,
                "source": source,
                "topic_code": None if topic_code is None or pd.isna(topic_code) else str(topic_code),
                "ts_code": norm,
                "stock_name": meta.get("name"),
                "pct_change": meta.get("pct_change"),
                "rise": meta.get("rise"),
                "five_min": meta.get("5min"),
                "limit_up_threshold": bool(meta.get("limit_up_threshold")),
                "rise_top100": bool(meta.get("rise_top100")),
                "five_min_top100": bool(meta.get("five_min_top100")),
                "trigger_flags": meta.get("trigger_flags"),
                "reason": None if reason is None or pd.isna(reason) else str(reason)[:220],
            }
        )

    if not kpl_list.empty and "ts_code" in kpl_list.columns:
        for _, row in kpl_list.iterrows():
            code = row_value(row, "ts_code", "code")
            reason = row_value(row, "lu_desc", "reason", "desc")
            for topic in split_topics(row_value(row, "theme", "concept", "tag")):
                add_event(code, topic, "kpl_list", reason=reason)

    if not kpl_cons.empty:
        for _, row in kpl_cons.iterrows():
            add_event(
                row_value(row, "con_code", "ts_code"),
                row_value(row, "name", "con_name"),
                "kpl_concept_cons",
                reason=row_value(row, "desc", "reason"),
                topic_code=row_value(row, "ts_code"),
            )

    dc_theme_name: dict[str, str] = {}
    if not dc_concept.empty and {"theme_code", "name"}.issubset(dc_concept.columns):
        dc_theme_name = {
            str(row["theme_code"]): str(row["name"])
            for _, row in dc_concept[["theme_code", "name"]].dropna().drop_duplicates().iterrows()
        }
    if not dc_concept_cons.empty:
        for _, row in dc_concept_cons.iterrows():
            theme_code = row_value(row, "theme_code")
            add_event(
                row_value(row, "ts_code", "con_code"),
                dc_theme_name.get(str(theme_code), None),
                "dc_concept_cons",
                reason=row_value(row, "reason", "desc"),
                topic_code=theme_code,
            )
            add_event(
                row_value(row, "ts_code", "con_code"),
                row_value(row, "industry"),
                "dc_concept_cons:industry",
                reason=row_value(row, "reason", "desc"),
                topic_code=row_value(row, "industry_code"),
            )

    dc_index_name: dict[str, str] = {}
    if not dc_index.empty and {"ts_code", "name"}.issubset(dc_index.columns):
        dc_index_name = {
            str(row["ts_code"]): str(row["name"])
            for _, row in dc_index[["ts_code", "name"]].dropna().drop_duplicates().iterrows()
        }
    if not dc_member.empty:
        for _, row in dc_member.iterrows():
            concept_code = row_value(row, "ts_code")
            add_event(
                row_value(row, "con_code"),
                dc_index_name.get(str(concept_code), None),
                "dc_member",
                topic_code=concept_code,
            )

    ths_index_name: dict[str, str] = {}
    if not ths_index.empty and {"ts_code", "name"}.issubset(ths_index.columns):
        ths_index_name = {
            str(row["ts_code"]): str(row["name"])
            for _, row in ths_index[["ts_code", "name"]].dropna().drop_duplicates().iterrows()
        }
    if not ths_member.empty:
        for _, row in ths_member.iterrows():
            concept_code = row_value(row, "ts_code")
            add_event(
                row_value(row, "con_code"),
                ths_index_name.get(str(concept_code), None),
                "ths_member",
                topic_code=concept_code,
            )

    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        key = (event["topic"], event["source"], event["ts_code"])
        dedup[key] = event
    return list(dedup.values())


def summarize_resonance(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event["topic"]].append(event)

    rows: list[dict[str, Any]] = []
    for topic, items in grouped.items():
        stock_codes = sorted({item["ts_code"] for item in items})
        sources = sorted({item["source"] for item in items})
        source_set = set(sources)
        has_topic_source = any(src.startswith("kpl") or src.startswith("dc_concept_cons") for src in source_set)
        if len(source_set) < 2 and not has_topic_source:
            continue
        by_stock = {code: [item for item in items if item["ts_code"] == code] for code in stock_codes}
        limit_count = sum(any(x["limit_up_threshold"] for x in vals) for vals in by_stock.values())
        rise_count = sum(any(x["rise_top100"] for x in vals) for vals in by_stock.values())
        five_count = sum(any(x["five_min_top100"] for x in vals) for vals in by_stock.values())
        kpl_count = sum(any(x["source"].startswith("kpl") for x in vals) for vals in by_stock.values())
        if len(stock_codes) > 60 and kpl_count == 0:
            continue
        pct_values = []
        stock_samples = []
        for code, vals in by_stock.items():
            sample = vals[0]
            pct = sample.get("pct_change")
            if pd.notna(pct):
                pct_values.append(float(pct))
            stock_samples.append(
                {
                    "ts_code": code,
                    "name": sample.get("stock_name"),
                    "pct_change": None if pd.isna(pct) else round(float(pct), 2),
                    "trigger_flags": sample.get("trigger_flags"),
                }
            )
        stock_samples.sort(key=lambda x: (x["pct_change"] is not None, x["pct_change"] or -999), reverse=True)
        reason_samples = []
        for item in items:
            reason = item.get("reason")
            if reason and reason not in reason_samples:
                reason_samples.append(reason)
            if len(reason_samples) >= 3:
                break

        score = (
            min(len(stock_codes), 24)
            + 4 * min(limit_count, 18)
            + 2 * min(rise_count, 18)
            + 2 * min(five_count, 18)
            + 3 * min(kpl_count, 18)
            + 2 * len(sources)
            + (max(pct_values) / 5 if pct_values else 0)
        )
        rows.append(
            {
                "topic": topic,
                "score": round(float(score), 2),
                "stock_count": int(len(stock_codes)),
                "limit_up_threshold_count": int(limit_count),
                "rise_top100_count": int(rise_count),
                "five_min_top100_count": int(five_count),
                "kpl_overlap_count": int(kpl_count),
                "source_count": int(len(sources)),
                "sources": sources,
                "avg_pct_change": round(float(sum(pct_values) / len(pct_values)), 2) if pct_values else None,
                "max_pct_change": round(float(max(pct_values)), 2) if pct_values else None,
                "sample_stocks": stock_samples[:8],
                "sample_reasons": reason_samples,
                "resonance_level": "P1" if score >= 24 else ("P2" if score >= 14 else "P3"),
            }
        )
    rows.sort(key=lambda x: (x["score"], x["stock_count"], x["limit_up_threshold_count"]), reverse=True)
    return rows


def hhi_level(hhi_norm: float) -> str:
    if hhi_norm >= 0.35:
        return "高垄断"
    if hhi_norm >= 0.18:
        return "中高垄断"
    if hhi_norm >= 0.08:
        return "中等集中"
    return "分散"


def compute_hhi_from_weights(weights: dict[str, float]) -> dict[str, Any]:
    positive = {k: float(v) for k, v in weights.items() if float(v) > 0}
    total = sum(positive.values())
    n = len(positive)
    if total <= 0 or n == 0:
        return {
            "hhi": 0.0,
            "hhi_norm": 0.0,
            "topic_count": 0,
            "top1_share": 0.0,
            "top3_share": 0.0,
            "level": "无有效样本",
            "top_topics": [],
        }
    shares = {topic: value / total for topic, value in positive.items()}
    hhi = sum(share * share for share in shares.values())
    hhi_norm = 1.0 if n == 1 else (hhi - 1.0 / n) / (1.0 - 1.0 / n)
    ranked = sorted(shares.items(), key=lambda x: x[1], reverse=True)
    return {
        "hhi": round(float(hhi), 6),
        "hhi_norm": round(float(hhi_norm), 6),
        "topic_count": int(n),
        "top1_share": round(float(ranked[0][1]), 6) if ranked else 0.0,
        "top3_share": round(float(sum(share for _, share in ranked[:3])), 6),
        "level": hhi_level(float(hhi_norm)),
        "top_topics": [{"topic": topic, "share": round(float(share), 6)} for topic, share in ranked[:8]],
    }


def summarize_intraday_hhi(events: list[dict[str, Any]], resonance: list[dict[str, Any]]) -> dict[str, Any]:
    resonance_topics = {item["topic"] for item in resonance}
    topic_by_stock: dict[str, set[str]] = defaultdict(set)
    for event in events:
        topic = event.get("topic")
        code = event.get("ts_code")
        if not topic or not code or topic not in resonance_topics:
            continue
        topic_by_stock[str(code)].add(str(topic))

    exposure_weights: dict[str, float] = defaultdict(float)
    for topics in topic_by_stock.values():
        if not topics:
            continue
        alloc = 1.0 / len(topics)
        for topic in topics:
            exposure_weights[topic] += alloc

    score_weights = {str(item["topic"]): float(item.get("score") or 0.0) for item in resonance}
    exposure_hhi = compute_hhi_from_weights(dict(exposure_weights))
    score_hhi = compute_hhi_from_weights(score_weights)
    return {
        "method": "intraday strong-stock topic exposure; each strong stock is fractionally allocated across confirmed resonance topics",
        "scope_note": "盘中 HHI 衡量强势股/共振得分集中度，不等同于日终资金流 HHI。",
        "exposure_hhi": exposure_hhi,
        "score_hhi": score_hhi,
    }


def frame_records(df: pd.DataFrame, limit: int = 30) -> list[dict[str, Any]]:
    cols = [
        "ts_code",
        "name",
        "price",
        "pct_change",
        "rise",
        "5min",
        "trigger_flags",
        "limit_up_threshold",
        "rise_rank",
        "five_min_rank",
    ]
    keep = [col for col in cols if col in df.columns]
    out = df[keep].head(limit).copy()
    for col in ("pct_change", "rise", "5min", "price"):
        if col in out.columns:
            out[col] = out[col].map(lambda x: None if pd.isna(x) else round(float(x), 4))
    for col in ("rise_rank", "five_min_rank"):
        if col in out.columns:
            out[col] = out[col].map(lambda x: None if pd.isna(x) else int(x))
    return out.to_dict(orient="records")


def write_outputs(payload: OrderedDict[str, Any], out_json: Path, out_md: Path) -> None:
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = payload.get("strong_pool_summary", {})
    hhi = payload.get("intraday_hhi", {})
    exposure_hhi = hhi.get("exposure_hhi", {})
    score_hhi = hhi.get("score_hhi", {})
    topics = payload.get("topic_resonance", [])[:10]

    lines = [
        "# 数据一处｜盘中题材共振快照",
        "",
        f"- 采集时间（UTC）：{payload.get('collected_at_utc')}",
        f"- 采集时间（北京时间）：{payload.get('collected_at_beijing')}",
        f"- JSON 结构化档案：`{out_json}`",
        "",
        "## 一、强势股池",
        f"- 强势股池：{summary.get('strong_pool_count', 0)} 只",
        f"- 涨停阈值触发：{summary.get('limit_up_threshold_count', 0)} 只",
        f"- 涨速 Top100 覆盖：{summary.get('rise_top100_count', 0)} 只",
        f"- 5分钟涨幅 Top100 覆盖：{summary.get('five_min_top100_count', 0)} 只",
        f"- 规则：{summary.get('threshold_rule', '')}",
        "",
        "## 二、盘中题材垄断度",
        (
            f"- 强势股题材暴露 HHI：{exposure_hhi.get('hhi', 0)}；"
            f"归一化={exposure_hhi.get('hhi_norm', 0)}；"
            f"级别={exposure_hhi.get('level', '未知')}；"
            f"Top1={float(exposure_hhi.get('top1_share', 0)):.1%}；"
            f"Top3={float(exposure_hhi.get('top3_share', 0)):.1%}"
        ),
        (
            f"- 共振得分 HHI：{score_hhi.get('hhi', 0)}；"
            f"归一化={score_hhi.get('hhi_norm', 0)}；"
            f"级别={score_hhi.get('level', '未知')}"
        ),
        f"- 口径：{hhi.get('scope_note', '')}",
        "",
        "## 三、题材共振 Top 10",
    ]
    if not topics:
        lines.append("- 暂无可确认的题材共振。")
    for idx, item in enumerate(topics, 1):
        samples = "、".join(
            f"{s.get('name') or s.get('ts_code')}({s.get('pct_change')})"
            for s in item.get("sample_stocks", [])[:5]
        )
        lines.append(
            f"- {idx}. {item['topic']} | score={item['score']} | "
            f"stocks={item['stock_count']} | limit={item['limit_up_threshold_count']} | "
            f"rise100={item['rise_top100_count']} | 5min100={item['five_min_top100_count']} | "
            f"sources={','.join(item['sources'])} | samples={samples}"
        )
    lines.extend(
        [
            "",
            "## 四、边界",
            "- 盘中 workflow 只使用 `tushare.realtime_list(src='dc')` 做实时强势股池，不再调用 iFinD/Eastmoney MCP。",
            "- ai-interest-topic-pipeline 不接入盘中实时数据；日终仍以后处理的 `limit_list_d` 为准。",
            "- 题材映射使用 Tushare 开盘啦、东方财富、同花顺概念/题材数据；若当天分区未出，会回退到不晚于当天的最新可用分区。",
        ]
    )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    now = utc_now()
    bj = bj_now(now)
    day = trade_date(bj)
    out_dir = OUT_ROOT / bj.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"intraday-topic-resonance-{compact_dt(bj)}.json"
    out_md = out_dir / f"intraday-topic-resonance-{compact_dt(bj)}.md"

    status: dict[str, Any] = OrderedDict()
    pro = init_tushare()
    status["tushare_token"] = {"status": "ok" if pro is not None else "missing"}

    realtime = fetch_realtime(status)
    strong_pool, strong_summary, top_rise, top_five = build_strong_pool(realtime)

    kpl_list = load_kpl_list(pro, day, status)
    kpl_cons = load_trade_date_dataset(
        pro, "kpl_concept_cons", "开盘啦题材成分", "kpl_concept_cons", day, 3000, status
    )
    dc_concept = load_trade_date_dataset(pro, "dc_concept", "题材数据", "dc_concept", day, 5000, status)
    dc_concept_cons = load_trade_date_dataset(
        pro, "dc_concept_cons", "东方财富题材成分", "dc_concept_cons", day, 3000, status
    )
    dc_index = load_trade_date_dataset(pro, "dc_index", "东方财富概念板块", "dc_index", day, 5000, status)
    dc_member = load_trade_date_dataset(pro, "dc_member", "东方财富概念成分", "dc_member", day, 5000, status)
    ths_index = load_direct_snapshot("同花顺行业概念板块", "snapshot.csv", status, "ths_index")
    ths_member = load_ths_member_flat(status)

    topic_events = build_topic_events(
        strong_pool,
        kpl_list,
        kpl_cons,
        dc_concept,
        dc_concept_cons,
        dc_index,
        dc_member,
        ths_index,
        ths_member,
    )
    resonance = summarize_resonance(topic_events)
    intraday_hhi = summarize_intraday_hhi(topic_events, resonance)

    payload: OrderedDict[str, Any] = OrderedDict()
    payload["collected_at_utc"] = now.isoformat()
    payload["collected_at_beijing"] = bj.isoformat()
    payload["trade_date_beijing"] = day
    payload["scope"] = "数据一处｜盘中题材共振"
    payload["source_status"] = status
    payload["strong_pool_summary"] = strong_summary
    payload["topic_event_count"] = int(len(topic_events))
    payload["topic_resonance"] = resonance[:50]
    payload["intraday_hhi"] = intraday_hhi
    payload["strong_stocks"] = frame_records(strong_pool, limit=80)
    payload["top_rise"] = frame_records(top_rise, limit=30)
    payload["top_five_min"] = frame_records(top_five, limit=30)
    payload["boundary_note"] = (
        "盘中 realtime 数据只用于 intraday workflow；"
        "ai-interest-topic-pipeline 继续使用每日收盘后的 limit_list_d。"
    )

    write_outputs(payload, out_json, out_md)
    print(f"JSON: {out_json}")
    print(f"MD: {out_md}")


if __name__ == "__main__":
    main()
