#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts


TOKEN_FILE = Path(
    "/home/ubuntu/.openclaw/media/inbound/"
    "tushares_token---f5492736-ee8f-4214-b0de-0422f0cfa0a3"
)
PROPOSAL_ROOTS = [
    Path("/home/ubuntu/.openclaw/workspace/research/trendradar-topic-pipeline/data/proposals"),
    Path("/home/ubuntu/research/trendradar-topic-pipeline/data/proposals"),
]
OUT_DIR = Path("/home/ubuntu/research/trendradar-latest-check/output/ai_interests")
TZ_BJ = timezone(timedelta(hours=8))
KPL_TAGS = ("涨停", "自然涨停", "炸板")


def bj_today() -> str:
    return datetime.now(TZ_BJ).strftime("%Y%m%d")


def read_token() -> str:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"empty tushare token: {TOKEN_FILE}")
    return token


def latest_proposal_file() -> Path:
    files: list[Path] = []
    for root in PROPOSAL_ROOTS:
        if root.exists():
            files.extend(root.glob("*.proposal.json"))
    files = [p for p in files if p.exists() and p.stat().st_size > 0]
    if not files:
        raise FileNotFoundError("no topic-pipeline proposal file found")
    return max(files, key=lambda p: (p.stat().st_mtime, str(p)))


def normalize_ts_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    match = re.search(r"(\d{6})(?:\.(SH|SZ|BJ|KP|TI|DC))?", text)
    if not match:
        return text or None
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
        if item and item.lower() != "nan":
            out.append(item[:32])
    return list(dict.fromkeys(out))


def is_noise_topic(topic: str) -> bool:
    text = str(topic).strip()
    if not text:
        return True
    markers = (
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
    return any(marker in text for marker in markers)


def fetch_paged(pro: Any, fetcher: str, page_size: int, **kwargs: Any) -> pd.DataFrame:
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
        time.sleep(0.3)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def latest_trade_date_with_limit(pro: Any, end_date: str, lookback_days: int) -> tuple[str, pd.DataFrame]:
    end = datetime.strptime(end_date, "%Y%m%d").replace(tzinfo=TZ_BJ)
    for i in range(lookback_days):
        day = (end - timedelta(days=i)).strftime("%Y%m%d")
        df = fetch_paged(pro, "limit_list_d", 2500, trade_date=day)
        if df is None or df.empty:
            continue
        if "limit" in df.columns:
            up = df[df["limit"].astype(str).str.upper().eq("U")].copy()
        else:
            up = df.copy()
        if not up.empty:
            return day, up
    return end_date, pd.DataFrame()


def load_kpl_list(pro: Any, day: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for tag in KPL_TAGS:
        df = fetch_paged(pro, "kpl_list", 8000, trade_date=day, tag=tag)
        if not df.empty:
            if "tag" not in df.columns:
                df["tag"] = tag
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def row_value(row: pd.Series, *cols: str) -> Any:
    for col in cols:
        if col in row.index and pd.notna(row[col]):
            return row[col]
    return None


def add_event(
    events: list[dict[str, Any]],
    strong_codes: set[str],
    stock_names: dict[str, str],
    ts_code: Any,
    topic: Any,
    source: str,
    reason: Any = None,
) -> None:
    code = normalize_ts_code(ts_code)
    if not code or code not in strong_codes:
        return
    topic_text = str(topic).strip() if topic is not None and not pd.isna(topic) else ""
    if not topic_text or is_noise_topic(topic_text):
        return
    events.append(
        {
            "topic": topic_text,
            "source": source,
            "ts_code": code,
            "stock_name": stock_names.get(code, code),
            "reason": "" if reason is None or pd.isna(reason) else str(reason)[:180],
        }
    )


def build_limitup_topic_candidates(pro: Any, day: str, limit_df: pd.DataFrame) -> list[dict[str, Any]]:
    if limit_df.empty:
        return []
    limit_df = limit_df.copy()
    limit_df["ts_code"] = limit_df["ts_code"].map(normalize_ts_code)
    limit_df = limit_df[limit_df["ts_code"].notna()].copy()
    strong_codes = set(limit_df["ts_code"])
    stock_names = {
        str(row["ts_code"]): str(row.get("name") or row["ts_code"])
        for _, row in limit_df.iterrows()
    }

    kpl = load_kpl_list(pro, day)
    kpl_cons = fetch_paged(pro, "kpl_concept_cons", 3000, trade_date=day)
    dc_concept = fetch_paged(pro, "dc_concept", 5000, trade_date=day)
    dc_cons = fetch_paged(pro, "dc_concept_cons", 3000, trade_date=day)
    dc_index = fetch_paged(pro, "dc_index", 5000, trade_date=day)
    dc_member = fetch_paged(pro, "dc_member", 5000, trade_date=day)

    theme_name: dict[str, str] = {}
    if not dc_concept.empty and {"theme_code", "name"}.issubset(dc_concept.columns):
        theme_name = {
            str(row["theme_code"]): str(row["name"])
            for _, row in dc_concept[["theme_code", "name"]].dropna().drop_duplicates().iterrows()
        }
    index_name: dict[str, str] = {}
    if not dc_index.empty and {"ts_code", "name"}.issubset(dc_index.columns):
        index_name = {
            str(row["ts_code"]): str(row["name"])
            for _, row in dc_index[["ts_code", "name"]].dropna().drop_duplicates().iterrows()
        }

    events: list[dict[str, Any]] = []
    for _, row in kpl.iterrows():
        for topic in split_topics(row_value(row, "theme", "tag")):
            add_event(events, strong_codes, stock_names, row_value(row, "ts_code"), topic, "kpl_list", row_value(row, "lu_desc"))
    for _, row in kpl_cons.iterrows():
        add_event(events, strong_codes, stock_names, row_value(row, "con_code"), row_value(row, "name"), "kpl_concept_cons", row_value(row, "desc"))
    for _, row in dc_cons.iterrows():
        theme_code = row_value(row, "theme_code")
        add_event(events, strong_codes, stock_names, row_value(row, "ts_code"), theme_name.get(str(theme_code), ""), "dc_concept_cons", row_value(row, "reason"))
        add_event(events, strong_codes, stock_names, row_value(row, "ts_code"), row_value(row, "industry"), "dc_concept_cons:industry", row_value(row, "reason"))
    for _, row in dc_member.iterrows():
        concept_code = row_value(row, "ts_code")
        add_event(events, strong_codes, stock_names, row_value(row, "con_code"), index_name.get(str(concept_code), ""), "dc_member")

    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        topic = event["topic"]
        if topic not in grouped:
            grouped[topic] = {"events": [], "codes": set(), "sources": set(), "reasons": []}
        group = grouped[topic]
        group["events"].append(event)
        group["codes"].add(event["ts_code"])
        group["sources"].add(event["source"])
        if event["reason"] and event["reason"] not in group["reasons"]:
            group["reasons"].append(event["reason"])

    rows: list[dict[str, Any]] = []
    for topic, group in grouped.items():
        codes = sorted(group["codes"])
        sources = sorted(group["sources"])
        if len(codes) < 2 and not any(src.startswith("kpl") for src in sources):
            continue
        score = min(10, 4 + len(codes) + len(sources))
        tier = "P1_core_resonating" if len(codes) >= 4 or len(sources) >= 3 else "P2_core_single_anchor"
        samples = []
        for event in group["events"]:
            label = f"{event['stock_name']}({event['ts_code']})"
            if label not in samples:
                samples.append(label)
            if len(samples) >= 8:
                break
        rows.append(
            {
                "topic": topic,
                "canonical_topic": topic,
                "topic_class": "limitup_board_topic",
                "priority_tier": tier,
                "cluster_strength": "post_close_limitup_resonance",
                "cluster_bonus": len(sources),
                "lifecycle_state": "candidate",
                "action": "candidate_append_to_interest_review",
                "reason": "limit_list_d_post_close: " + "、".join(sources),
                "today_score": score,
                "heat_gradient": 0,
                "long_term_score": 0,
                "source_count": len(sources),
                "history_days": 1,
                "anchor_stock_code": codes[0] if codes else "",
                "related_stock_count": len(codes),
                "hot_rank_overlap_count": len(codes),
                "signal_types": sorted(set(["limit_list_d"] + sources)),
                "hot_rank_overlap_codes": codes[:30],
                "hot_rank_overlap_names": [stock_names.get(code, code) for code in codes[:30]],
                "related_stock_codes": codes[:80],
                "sample_titles": [f"{day} 涨停题材共振：{topic}，样本：" + "、".join(samples[:6])] + group["reasons"][:3],
                "limitup_trade_date": day,
                "limitup_injected_by": "append_limitup_topics_to_latest_topic_proposal.py",
            }
        )
    rows.sort(key=lambda x: (x["priority_tier"], x["today_score"], x["related_stock_count"]), reverse=True)
    return rows[:80]


def merge_into_proposal(proposal: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    doc = json.loads(proposal.read_text(encoding="utf-8"))
    core = doc.setdefault("core_candidates", [])
    existing = {str(item.get("canonical_topic") or item.get("topic")): item for item in core if isinstance(item, dict)}
    appended = 0
    updated = 0
    for row in rows:
        key = str(row.get("canonical_topic") or row.get("topic"))
        if key in existing:
            item = existing[key]
            item["priority_tier"] = max(str(item.get("priority_tier", "")), str(row["priority_tier"]))
            item["today_score"] = max(float(item.get("today_score") or 0), float(row["today_score"]))
            item["related_stock_count"] = max(int(float(item.get("related_stock_count") or 0)), int(row["related_stock_count"]))
            item["hot_rank_overlap_count"] = max(int(float(item.get("hot_rank_overlap_count") or 0)), int(row["hot_rank_overlap_count"]))
            for field in ("signal_types", "hot_rank_overlap_codes", "hot_rank_overlap_names", "related_stock_codes", "sample_titles"):
                current = item.get(field) or []
                if not isinstance(current, list):
                    current = [str(current)]
                merged = list(dict.fromkeys(current + list(row.get(field) or [])))
                item[field] = merged
            item["reason"] = (str(item.get("reason") or "") + " | " + row["reason"]).strip(" |")
            item["limitup_trade_date"] = row["limitup_trade_date"]
            item["limitup_injected_by"] = row["limitup_injected_by"]
            updated += 1
        else:
            core.append(row)
            existing[key] = row
            appended += 1
    doc["limitup_topic_injection"] = {
        "updated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "row_count": len(rows),
        "appended": appended,
        "updated": updated,
        "source": "post_close_limit_list_d_kpl_dc",
    }
    backup = proposal.with_suffix(proposal.suffix + f".bak_limitup_{int(time.time())}")
    backup.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    proposal.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc["limitup_topic_injection"] | {"proposal": str(proposal), "backup": str(backup)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Append post-close limit-up topics into latest TrendRadar topic proposal.")
    parser.add_argument("--trade-date", default=bj_today())
    parser.add_argument("--lookback-days", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = read_token()
    ts.set_token(token)
    pro = ts.pro_api(token)

    day, limit_df = latest_trade_date_with_limit(pro, args.trade_date, args.lookback_days)
    rows = build_limitup_topic_candidates(pro, day, limit_df)
    proposal = latest_proposal_file()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sidecar = OUT_DIR / "limitup_topic_candidates.latest.json"
    sidecar.write_text(json.dumps({"trade_date": day, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        result = {"proposal": str(proposal), "trade_date": day, "row_count": len(rows), "dry_run": True}
    else:
        result = merge_into_proposal(proposal, rows)
        result["trade_date"] = day
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
