from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from factor_factory.console.models import CampaignSummary


REQUIRED_ARTIFACTS = {
    "inventory": "objects/miner_capability_inventory.json",
    "candidate_manifest": "objects/candidates/candidate_manifest.json",
    "data_gap": "objects/data_gap_report.json",
    "cheap_screen": "objects/cheap_screen/cheap_screen_summary.json",
    "research_queue": "objects/research_queue/research_queue.json",
}

OPTIONAL_DOC_ARTIFACTS = {
    "inventory_doc": "docs/miner_capability_inventory.md",
    "data_gap_doc": "docs/data_gap_report.md",
    "cheap_screen_doc": "docs/cheap_screen_report.md",
    "research_queue_doc": "docs/research_queue.md",
}

BOUNDARY_STATEMENT = (
    "Console is read-only for research artifacts: no production research, worker, "
    "formal Step3B/Step4/Step6, clean data mutation, or repo-root knowledge write."
)


def read_miner_campaign(workspace_root: str | Path) -> CampaignSummary:
    workspace = Path(workspace_root)
    campaign_id = workspace.name
    artifact_paths = _artifact_paths(workspace)
    missing = [name for name, rel in REQUIRED_ARTIFACTS.items() if not (workspace / rel).exists()]
    if missing:
        return _summary(
            campaign_id=campaign_id,
            workspace=workspace,
            verdict="BLOCK",
            artifact_paths=artifact_paths,
            blockers=[f"missing required artifact: {name}" for name in missing],
            next_actions=["rerun or repair Miner campaign artifacts before Console handoff"],
        )

    inventory = _read_json(workspace / REQUIRED_ARTIFACTS["inventory"])
    candidates_payload = _read_json(workspace / REQUIRED_ARTIFACTS["candidate_manifest"])
    data_gap_payload = _read_json(workspace / REQUIRED_ARTIFACTS["data_gap"])
    cheap_screen_payload = _read_json(workspace / REQUIRED_ARTIFACTS["cheap_screen"])
    queue_payload = _read_json(workspace / REQUIRED_ARTIFACTS["research_queue"])

    candidates = _as_list(candidates_payload.get("candidates"))
    gaps = _as_list(data_gap_payload.get("gaps"))
    queue_items = _queue_items(queue_payload)
    cheap_results = _as_list(cheap_screen_payload.get("results"))
    statuses = _template_status_counts(candidates, cheap_results)
    data_requests = data_gap_payload.get("data_request_ids", data_gap_payload.get("data_requests", []))

    blockers: list[str] = []
    next_actions: list[str] = []
    if cheap_screen_payload.get("promotion_forbidden_until_formal") is not True:
        blockers.append("cheap-screen promotion guard missing: promotion_forbidden_until_formal must be true")
        next_actions.append("restore cheap-screen promotion guard before displaying candidates")
    if not candidates:
        blockers.append("candidate manifest has no candidates")
        next_actions.append("run Miner candidate generation before Console handoff")
    if candidates and not queue_items and gaps:
        blockers.append("candidates exist but research queue is empty while data gaps remain")
        next_actions.append("resolve Data/API and operator gaps before Ultimate handoff")
    if gaps:
        next_actions.append("review Data Gap panel for catalog, data request, and operator fixes")

    if blockers:
        verdict = "BLOCK"
    elif queue_items and not gaps:
        verdict = "ACCEPT"
    elif queue_items:
        verdict = "PARTIAL"
    else:
        verdict = "UNKNOWN"

    return _summary(
        campaign_id=str(inventory.get("campaign_id") or campaign_id),
        workspace=workspace,
        verdict=verdict,
        candidate_count=len(candidates),
        cheap_screen_passed=_cheap_screen_passed(cheap_screen_payload),
        research_queue_count=len(queue_items),
        data_gap_count=len(gaps),
        data_request_count=len(_as_list(data_requests)),
        template_status_counts=dict(statuses),
        artifact_paths=artifact_paths,
        blockers=blockers,
        next_actions=_dedupe(next_actions),
    )


def _summary(
    *,
    campaign_id: str,
    workspace: Path,
    verdict: str,
    artifact_paths: dict[str, str],
    blockers: list[str],
    next_actions: list[str],
    candidate_count: int = 0,
    cheap_screen_passed: int = 0,
    research_queue_count: int = 0,
    data_gap_count: int = 0,
    data_request_count: int = 0,
    template_status_counts: dict[str, int] | None = None,
) -> CampaignSummary:
    return CampaignSummary(
        campaign_id=campaign_id,
        workspace_root=str(workspace),
        verdict=verdict,
        candidate_count=candidate_count,
        cheap_screen_passed=cheap_screen_passed,
        research_queue_count=research_queue_count,
        data_gap_count=data_gap_count,
        data_request_count=data_request_count,
        template_status_counts=template_status_counts or {},
        artifact_paths=artifact_paths,
        blockers=blockers,
        next_actions=next_actions,
        boundary_statement=BOUNDARY_STATEMENT,
    )


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _artifact_paths(workspace: Path) -> dict[str, str]:
    paths = dict(REQUIRED_ARTIFACTS)
    paths.update({key: rel for key, rel in OPTIONAL_DOC_ARTIFACTS.items() if (workspace / rel).exists()})
    return paths


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _queue_items(payload: dict[str, Any]) -> list[Any]:
    if "items" in payload:
        return _as_list(payload.get("items"))
    return _as_list(payload.get("queue"))


def _template_status_counts(candidates: list[Any], cheap_results: list[Any]) -> dict[str, int]:
    statuses: Counter[str] = Counter()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        status = item.get("template_status") or item.get("cheap_screen_status") or item.get("dependency_status")
        if status:
            statuses[str(status)] += 1
    if statuses:
        return dict(statuses)
    for item in cheap_results:
        if not isinstance(item, dict):
            continue
        status = item.get("decision") or item.get("failure_reason")
        if status:
            statuses[str(status)] += 1
    return dict(statuses)


def _cheap_screen_passed(payload: dict[str, Any]) -> int:
    if "passed_count" in payload:
        return int(payload.get("passed_count") or 0)
    count = 0
    for item in _as_list(payload.get("results")):
        if isinstance(item, dict) and str(item.get("decision", "")).lower() in {"pass", "passed", "ready"}:
            count += 1
    return count


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
