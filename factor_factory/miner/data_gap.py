from __future__ import annotations

from pathlib import Path
from typing import Any

from factor_factory.miner.common import utc_now, workspace_path, write_json, write_markdown


def build_data_gap_report(
    *,
    campaign_id: str,
    workspace_root: Path,
    candidates: list[dict[str, Any]],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = []
    data_requests: list[dict[str, Any]] = []
    for packet in candidates:
        for dataset in packet.get("missing_datasets", []):
            request_id = None
            if str(dataset).startswith("intraday_"):
                request_id = f"data_request__{campaign_id}__{packet['template_id']}__{dataset}"
                data_requests.append(
                    {
                        "contract_version": "factorforge_data_request_v1",
                        "request_id": request_id,
                        "request_type": "state_datamart_missing",
                        "campaign_id": campaign_id,
                        "candidate_id": packet["candidate_id"],
                        "template_id": packet["template_id"],
                        "dataset_id": dataset,
                        "required_fields": list(packet.get("template_lineage", {}).get("required_fields", [])),
                        "reason": "Miner template requires reusable state datamart; raw-minute full-window fallback is forbidden.",
                        "raw_minute_full_window_fallback_allowed": False,
                    }
                )
            gaps.append(
                {
                    "candidate_id": packet["candidate_id"],
                    "template_id": packet["template_id"],
                    "gap_type": "missing_state_datamart" if str(dataset).startswith("intraday_") else "missing_dataset",
                    "dataset_id": dataset,
                    "action": "data_request_v1" if str(dataset).startswith("intraday_") else "catalog_or_fixture_required",
                    "data_request_id": request_id,
                    "notes": "Miner must not raw-minute full-window fallback.",
                }
            )
        for field in packet.get("missing_fields", []):
            gaps.append(
                {
                    "candidate_id": packet["candidate_id"],
                    "template_id": packet["template_id"],
                    "gap_type": "missing_field",
                    "field": field,
                    "action": "catalog_schema_or_template_adjustment_required",
                    "notes": "Existing dataset is present but does not satisfy template fields.",
                }
            )
        for issue in packet.get("dataset_quality_issues", []):
            gaps.append(
                {
                    "candidate_id": packet["candidate_id"],
                    "template_id": packet["template_id"],
                    "gap_type": "dataset_quality",
                    "issue": issue,
                    "action": "catalog_qa_coverage_or_lookahead_fix_required",
                    "notes": "Miner cannot mark a template ready when QA, coverage, or lookahead evidence is incomplete.",
                }
            )
        for operator in packet.get("missing_operators", []):
            gaps.append(
                {
                    "candidate_id": packet["candidate_id"],
                    "template_id": packet["template_id"],
                    "gap_type": "missing_operator",
                    "operator_id": operator,
                    "action": "operator_request",
                    "notes": "Do not emulate via unreviewed ad-hoc code in Miner.",
                }
            )
    report = {
        "version": "factorforge_miner_data_gap_report_v1",
        "campaign_id": campaign_id,
        "generated_at_utc": utc_now(),
        "gaps": gaps,
        "data_request_ids": [row["request_id"] for row in data_requests],
        "inventory_version": inventory.get("version"),
        "raw_minute_full_window_fallback_allowed": False,
    }
    write_json(workspace_path(workspace_root, "objects", "data_gap_report.json", campaign_id=campaign_id), report)
    for request in data_requests:
        write_json(
            workspace_path(workspace_root, "objects", "data_requests", f"{request['request_id']}.json", campaign_id=campaign_id),
            request,
        )
    lines = ["# Miner Data Gap Report", "", f"campaign_id: `{campaign_id}`", "", "| candidate | type | missing | action |", "|---|---|---|---|"]
    for gap in gaps:
        missing = gap.get("dataset_id") or gap.get("field") or gap.get("operator_id") or ""
        lines.append(f"| `{gap.get('candidate_id')}` | `{gap.get('gap_type')}` | `{missing}` | `{gap.get('action')}` |")
    if not gaps:
        lines.append("| none | none | none | none |")
    write_markdown(workspace_path(workspace_root, "docs", "data_gap_report.md", campaign_id=campaign_id), "\n".join(lines))
    return report
