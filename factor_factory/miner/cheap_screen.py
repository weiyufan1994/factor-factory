from __future__ import annotations

import csv
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import pandas as pd

from factor_factory.miner.common import read_json, utc_now, workspace_path, write_json, write_markdown


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(a) != len(b):
        return None
    ma = mean(a)
    mb = mean(b)
    da = [x - ma for x in a]
    db = [y - mb for y in b]
    denom = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if denom == 0:
        return None
    return sum(x * y for x, y in zip(da, db)) / denom


def _load_panel(path: Path) -> list[dict[str, Any]]:
    with Path(path).expanduser().open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _rank_ic_by_date(rows: list[dict[str, Any]], factor_col: str) -> list[float]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(str(row["trade_date"]), []).append(row)
    out: list[float] = []
    for group in by_date.values():
        try:
            factor = [float(row[factor_col]) for row in group]
            ret = [float(row["forward_return"]) for row in group]
        except (KeyError, ValueError):
            continue
        value = _corr(_rank(factor), _rank(ret))
        if value is not None:
            out.append(value)
    return out


def _endpoint_metrics(rows: list[dict[str, Any]], factor_col: str) -> tuple[float | None, float | None, float | None, float | None]:
    if len(rows) < 4:
        return None, None, None, None
    ordered = sorted(rows, key=lambda row: float(row[factor_col]))
    n = max(1, len(ordered) // 4)
    low = ordered[:n]
    high = ordered[-n:]
    low_ret = mean(float(row["forward_return"]) for row in low)
    high_ret = mean(float(row["forward_return"]) for row in high)
    spread = high_ret - low_ret
    buckets = []
    for idx in range(4):
        start = idx * len(ordered) // 4
        end = (idx + 1) * len(ordered) // 4
        if end > start:
            buckets.append(ordered[start:end])
    bucket_rets = [mean(float(row["forward_return"]) for row in bucket) for bucket in buckets if bucket]
    mono = None
    if len(bucket_rets) >= 2:
        signs = [1 if bucket_rets[i + 1] >= bucket_rets[i] else -1 for i in range(len(bucket_rets) - 1)]
        mono = sum(signs) / len(signs)
    return high_ret, low_ret, spread, mono


def _turnover(rows: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row["turnover"]))
        except (KeyError, ValueError):
            continue
    return mean(values) if values else None


def _screen_ready_candidate(packet: dict[str, Any], rows: list[dict[str, Any]], screen_window: str, universe: str) -> dict[str, Any]:
    factor_col = "factor_ready_signal"
    ics = _rank_ic_by_date(rows, factor_col)
    rank_ic_mean = mean(ics) if ics else None
    rank_ic_ir = None
    if ics:
        std = pstdev(ics)
        rank_ic_ir = None if std == 0 else rank_ic_mean / std
    long_ret, short_ret, spread, mono = _endpoint_metrics(rows, factor_col)
    coverage = len(rows)
    decision = "discard"
    if rank_ic_mean is not None and spread is not None:
        if abs(rank_ic_mean) >= 0.05 and abs(spread) >= 0.5:
            decision = "send_to_formal_research"
        elif abs(rank_ic_mean) >= 0.02 or abs(spread) >= 0.2:
            decision = "keep_as_feature"
    return {
        "candidate_id": packet["candidate_id"],
        "template_id": packet["template_id"],
        "screen_window": screen_window,
        "universe": universe,
        "data_source": "cheap_screen_panel",
        "rank_ic_mean": rank_ic_mean,
        "rank_ic_ir": rank_ic_ir,
        "ic_hit_rate": (sum(1 for x in ics if x > 0) / len(ics)) if ics else None,
        "group_spread_gross": spread,
        "long_end_gross": long_ret,
        "short_end_gross": short_ret,
        "monotonicity_score": mono,
        "turnover_estimate": _turnover(rows),
        "coverage": coverage,
        "failure_reason": None,
        "decision": decision,
        "evidence_role": "exploratory_evidence",
        "promotion_forbidden_until_formal": True,
    }


def run_cheap_screen(
    *,
    campaign_id: str,
    workspace_root: Path,
    candidate_manifest_path: Path,
    panel_path: Path,
    screen_window: str,
    universe: str,
) -> dict[str, Any]:
    manifest = read_json(candidate_manifest_path)
    rows = _load_panel(panel_path)
    results: list[dict[str, Any]] = []
    for packet in manifest.get("candidates", []):
        if packet.get("cheap_screen_status") not in {"not_run", "ready"} and packet.get("dependency_status") != "ready":
            results.append(
                {
                    "candidate_id": packet["candidate_id"],
                    "template_id": packet["template_id"],
                    "screen_window": screen_window,
                    "universe": universe,
                    "data_source": "cheap_screen_panel",
                    "rank_ic_mean": None,
                    "rank_ic_ir": None,
                    "ic_hit_rate": None,
                    "group_spread_gross": None,
                    "long_end_gross": None,
                    "short_end_gross": None,
                    "monotonicity_score": None,
                    "turnover_estimate": None,
                    "coverage": 0,
                    "failure_reason": packet.get("dependency_status"),
                    "decision": packet.get("dependency_status", "needs_data"),
                    "evidence_role": "exploratory_evidence",
                    "promotion_forbidden_until_formal": True,
                }
            )
            continue
        results.append(_screen_ready_candidate(packet, rows, screen_window, universe))
    summary = {
        "version": "factorforge_miner_cheap_screen_summary_v1",
        "campaign_id": campaign_id,
        "generated_at_utc": utc_now(),
        "screen_window": screen_window,
        "universe": universe,
        "evidence_role": "exploratory_evidence",
        "promotion_forbidden_until_formal": True,
        "results": results,
    }
    write_json(workspace_path(workspace_root, "objects", "cheap_screen", "cheap_screen_summary.json", campaign_id=campaign_id), summary)
    result_path = workspace_path(workspace_root, "objects", "cheap_screen", "cheap_screen_results.parquet", campaign_id=campaign_id)
    pd.DataFrame(results).to_parquet(result_path, index=False)
    lines = ["# Miner Cheap Screen Report", "", f"campaign_id: `{campaign_id}`", "", "| candidate | decision | rank_ic_mean | group_spread |", "|---|---|---:|---:|"]
    for row in results:
        lines.append(f"| `{row['candidate_id']}` | `{row['decision']}` | `{row['rank_ic_mean']}` | `{row['group_spread_gross']}` |")
    write_markdown(workspace_path(workspace_root, "docs", "cheap_screen_report.md", campaign_id=campaign_id), "\n".join(lines))
    return summary
