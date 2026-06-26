from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from factor_factory.miner.common import utc_now, workspace_path, write_json, write_markdown


def _priority(row: dict[str, Any]) -> str:
    value = row.get("rank_ic_mean")
    spread = row.get("group_spread_gross")
    if value is not None and spread is not None and abs(float(value)) >= 0.2 and abs(float(spread)) >= 1.0:
        return "high"
    return "medium"


def build_research_queue(*, campaign_id: str, workspace_root: Path, cheap_screen_summary: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for row in cheap_screen_summary.get("results", []):
        if row.get("decision") != "send_to_formal_research":
            continue
        items.append(
            {
                "queue_item_version": "factorforge_miner_research_queue_item_v1",
                "candidate_id": row["candidate_id"],
                "priority": _priority(row),
                "recommended_formal_route": "new_factor",
                "formal_question": "Does the candidate survive formal Factor Forge Step1-6 research-quality validation?",
                "required_datamarts": [],
                "missing_data_requests": [],
                "cheap_screen_artifacts": ["objects/cheap_screen/cheap_screen_summary.json"],
                "overclaim_guard": "Cheap screen is exploratory and cannot support promotion.",
            }
        )
    queue = {
        "version": "factorforge_miner_research_queue_v1",
        "campaign_id": campaign_id,
        "generated_at_utc": utc_now(),
        "items": items,
    }
    write_json(workspace_path(workspace_root, "objects", "research_queue", "research_queue.json", campaign_id=campaign_id), queue)
    jsonl_path = workspace_path(workspace_root, "objects", "research_queue", "research_queue.jsonl", campaign_id=campaign_id)
    jsonl_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items), encoding="utf-8")
    lines = ["# Miner Research Queue", "", f"campaign_id: `{campaign_id}`", "", "| candidate | priority | route |", "|---|---|---|"]
    for item in items:
        lines.append(f"| `{item['candidate_id']}` | `{item['priority']}` | `{item['recommended_formal_route']}` |")
    if not items:
        lines.append("| none | none | none |")
    write_markdown(workspace_path(workspace_root, "docs", "research_queue.md", campaign_id=campaign_id), "\n".join(lines))
    return queue
