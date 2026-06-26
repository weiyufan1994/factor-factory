from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from factor_factory.miner import BLOCK_CANDIDATE_PACKET_INVALID
from factor_factory.miner.common import utc_now, workspace_path, write_json
from factor_factory.miner.template_registry import template_by_id


def _candidate_id(campaign_id: str, template_id: str, parameters: dict[str, Any] | None = None) -> str:
    payload = json.dumps({"campaign_id": campaign_id, "template_id": template_id, "parameters": parameters or {}}, sort_keys=True)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"miner_{template_id}__{digest}"


def _support_for(inventory: dict[str, Any], template_id: str) -> dict[str, Any]:
    for row in inventory.get("template_support", []):
        if row.get("template_id") == template_id:
            return row
    return {"template_id": template_id, "support_status": "needs_data", "missing_datasets": [], "missing_fields": [], "missing_operators": []}


def _formula_recipe(template: dict[str, Any]) -> str:
    return f"{template['template_id']}({','.join(template.get('required_fields', []))})"


def validate_candidate_packet(packet: dict[str, Any]) -> None:
    required = (
        "candidate_id",
        "template_id",
        "family",
        "formula_or_recipe",
        "input_datasets",
        "operator_dependencies",
        "information_set",
        "economic_prior",
        "return_source_prior",
        "payer_hypothesis",
        "math_object",
        "expected_metric_signature",
        "falsification_tests",
        "promotion_forbidden_until_formal",
        "template_lineage",
    )
    missing = [key for key in required if key not in packet]
    if missing or packet.get("promotion_forbidden_until_formal") is not True:
        raise ValueError(f"{BLOCK_CANDIDATE_PACKET_INVALID}: missing={missing}")


def build_candidate_packets(
    *,
    campaign_id: str,
    workspace_root: Path,
    template_ids: list[str],
    inventory: dict[str, Any],
    parameter_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    parameter_overrides = parameter_overrides or {}
    for template_id in template_ids:
        template = template_by_id(template_id)
        support = _support_for(inventory, template_id)
        status = str(support.get("support_status") or "needs_data")
        parameters = parameter_overrides.get(template_id, {})
        packet = {
            "candidate_version": "factorforge_miner_candidate_packet_v1",
            "candidate_id": _candidate_id(campaign_id, template_id, parameters),
            "campaign_id": campaign_id,
            "template_id": template_id,
            "family": template["family"],
            "formula_or_recipe": _formula_recipe(template),
            "input_datasets": list(template.get("required_datasets", [])),
            "required_datamarts": [ds for ds in template.get("required_datasets", []) if str(ds).startswith("intraday_")],
            "operator_dependencies": list(template.get("operator_dependencies", [])),
            "parameters": parameters,
            "information_set": "pre-close cross-sectional information set; OOS holdout not used for selection",
            "economic_prior": template["economic_prior"],
            "return_source_prior": "information_advantage",
            "payer_hypothesis": "slower information processors, liquidity demanders, or constrained participants may pay the premium; cheap screen cannot validate this",
            "math_object": template["math_object"],
            "expected_metric_signature": template.get("expected_metric_signature", {}),
            "falsification_tests": template.get("falsification_tests", []),
            "what_information_is_preserved": f"Preserves {template['math_object']} through {template_id}.",
            "what_information_is_deleted": "Deletes full path micro-events not represented by the selected template fields.",
            "template_lineage": {
                "template_id": template_id,
                "family": template["family"],
                "required_datasets": list(template.get("required_datasets", [])),
                "required_fields": list(template.get("required_fields", [])),
                "operator_dependencies": list(template.get("operator_dependencies", [])),
            },
            "dependency_status": status,
            "missing_datasets": support.get("missing_datasets", []),
            "missing_fields": support.get("missing_fields", []),
            "missing_operators": support.get("missing_operators", []),
            "dataset_quality_issues": support.get("dataset_quality_issues", []),
            "cheap_screen_status": "not_run" if status == "ready" else status,
            "formal_research_status": "not_started",
            "promotion_forbidden_until_formal": True,
            "created_at_utc": utc_now(),
        }
        validate_candidate_packet(packet)
        packets.append(packet)
        write_json(
            workspace_path(
                workspace_root,
                "objects",
                "candidates",
                f"candidate_packet__{packet['candidate_id']}.json",
                campaign_id=campaign_id,
            ),
            packet,
        )
    manifest = {
        "version": "factorforge_miner_candidate_manifest_v1",
        "campaign_id": campaign_id,
        "created_at_utc": utc_now(),
        "candidates": packets,
    }
    write_json(workspace_path(workspace_root, "objects", "candidates", "candidate_manifest.json", campaign_id=campaign_id), manifest)
    return packets
