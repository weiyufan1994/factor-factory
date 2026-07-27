from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from factor_factory.miner.cheap_screen import (
    validate_cheap_screen_summary,
    validate_search_control,
)
from factor_factory.miner.common import utc_now, workspace_path, write_json, write_markdown
from factor_factory.research_evidence import sha256_file


def _priority(row: dict[str, Any]) -> str:
    value = row.get("rank_ic_mean")
    spread = row.get("group_spread_gross")
    if value is not None and spread is not None and abs(float(value)) >= 0.2 and abs(float(spread)) >= 1.0:
        return "high"
    return "medium"


def build_research_queue(*, campaign_id: str, workspace_root: Path, cheap_screen_summary: dict[str, Any]) -> dict[str, Any]:
    replay_reasons = validate_cheap_screen_summary(
        cheap_screen_summary,
        workspace_root=workspace_root,
        expected_campaign_id=campaign_id,
    )
    if replay_reasons:
        raise ValueError(";".join(replay_reasons))
    if cheap_screen_summary.get("campaign_id") != campaign_id:
        raise ValueError(
            "BLOCK_FACTORFORGE_MINER_RESEARCH_QUEUE_CAMPAIGN_MISMATCH"
        )
    if (
        cheap_screen_summary.get("evidence_role") != "exploratory_evidence"
        or cheap_screen_summary.get("promotion_forbidden_until_formal")
        is not True
        or cheap_screen_summary.get("search_control_verdict") != "PASS"
        or cheap_screen_summary.get("fixture_shared_signal_used") is True
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_MINER_RESEARCH_QUEUE_EVIDENCE_BOUNDARY_INVALID"
        )
    multiplicity = cheap_screen_summary.get("multiplicity")
    control = cheap_screen_summary.get("search_control")
    if (
        not isinstance(multiplicity, dict)
        or not isinstance(control, dict)
        or multiplicity.get("policy") != control.get("multiple_testing_policy")
        or multiplicity.get("alpha") != control.get("multiplicity_alpha")
        or multiplicity.get("family_size") != control.get("trials_used")
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_MINER_RESEARCH_QUEUE_MULTIPLICITY_INVALID"
        )
    workspace = workspace_root.expanduser().resolve(strict=False)
    candidate_manifest_path = Path(
        str(cheap_screen_summary.get("candidate_manifest_path") or "")
    ).expanduser().resolve(strict=False)
    candidate_manifest = json.loads(
        candidate_manifest_path.read_text(encoding="utf-8")
    )
    candidate_packets = {
        str(packet.get("candidate_id")): packet
        for packet in candidate_manifest.get("candidates") or []
        if isinstance(packet, dict) and packet.get("candidate_id")
    }
    execution_report_path = Path(
        str(cheap_screen_summary.get("program_execution_report_path") or "")
    ).expanduser().resolve(strict=False)
    if (
        not execution_report_path.is_file()
        or (
            execution_report_path != workspace
            and workspace not in execution_report_path.parents
        )
        or sha256_file(execution_report_path)
        != cheap_screen_summary.get("program_execution_report_sha256")
        or cheap_screen_summary.get("program_execution_output_sha256")
        != cheap_screen_summary.get("source_panel_sha256")
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_MINER_RESEARCH_QUEUE_EXECUTION_LINEAGE_INVALID"
        )
    tested_result_hashes = {
        str(row.get("program_hash"))
        for row in cheap_screen_summary.get("results") or []
        if isinstance(row, dict)
        and row.get("signal_source") == "candidate_specific"
        and row.get("program_hash")
    }
    control_reasons = validate_search_control(
        cheap_screen_summary.get("search_control"),
        required_trial_count=len(tested_result_hashes),
        required_program_hashes=tested_result_hashes,
        workspace_root=workspace_root,
        expected_generation=cheap_screen_summary.get("generation"),
        expected_campaign_id=campaign_id,
        expected_data_snapshot_hash=cheap_screen_summary.get("source_panel_sha256"),
        expected_is_source_hash=cheap_screen_summary.get(
            "program_execution_source_sha256"
        ),
        expected_selection_window_id=cheap_screen_summary.get("screen_window"),
        expected_universe_id=cheap_screen_summary.get("universe"),
    )
    if control_reasons:
        raise ValueError(";".join(control_reasons))
    items: list[dict[str, Any]] = []
    for row in cheap_screen_summary.get("results", []):
        if (
            row.get("decision") != "send_to_formal_research"
            or row.get("eligible_for_research_queue") is not True
            or row.get("signal_source") != "candidate_specific"
            or not row.get("program_hash")
            or row.get("multiplicity_pass") is not True
        ):
            continue
        candidate_id = str(row["candidate_id"])
        packet = candidate_packets.get(candidate_id)
        if not isinstance(packet, dict):
            raise ValueError(
                "BLOCK_FACTORFORGE_MINER_RESEARCH_QUEUE_CANDIDATE_LINEAGE_INVALID"
            )
        research_id = f"miner_{campaign_id}__formal"
        items.append(
            {
                "queue_item_version": "factorforge_miner_research_queue_item_v1",
                "candidate_id": candidate_id,
                "program_hash": row.get("program_hash"),
                "priority": _priority(row),
                "recommended_formal_route": "new_factor",
                "formal_question": "Does the candidate survive formal Factor Forge Step1-6 research-quality validation?",
                "mechanism_hypothesis": {
                    "family": packet.get("family"),
                    "economic_prior": packet.get("economic_prior"),
                    "return_source_prior": packet.get(
                        "return_source_prior"
                    ),
                    "payer_hypothesis": packet.get("payer_hypothesis"),
                    "math_object": packet.get("math_object"),
                    "expected_metric_signature": packet.get(
                        "expected_metric_signature"
                    ),
                },
                "data_requirements": {
                    "input_datasets": packet.get("input_datasets") or [],
                    "required_datamarts": (
                        packet.get("required_datamarts") or []
                    ),
                    "operator_dependencies": (
                        packet.get("operator_dependencies") or []
                    ),
                    "missing_datasets": packet.get("missing_datasets") or [],
                    "missing_fields": packet.get("missing_fields") or [],
                    "missing_operators": packet.get("missing_operators") or [],
                },
                "required_datamarts": (
                    packet.get("required_datamarts") or []
                ),
                "missing_data_requests": (
                    packet.get("data_request_ids") or []
                ),
                "known_failure_modes": {
                    "falsification_tests": (
                        packet.get("falsification_tests") or []
                    ),
                    "dataset_quality_issues": (
                        packet.get("dataset_quality_issues") or []
                    ),
                    "cheap_screen_failure_reason": row.get(
                        "failure_reason"
                    ),
                },
                "trial_lineage": {
                    "generation": cheap_screen_summary.get("generation"),
                    "trial_index": (
                        list(
                            (
                                cheap_screen_summary.get("search_control")
                                or {}
                            ).get("tested_program_hashes")
                            or []
                        ).index(row.get("program_hash"))
                        + 1
                    ),
                    "trials_used": (
                        cheap_screen_summary.get("search_control") or {}
                    ).get("trials_used"),
                    "previous_search_control_ref": (
                        cheap_screen_summary.get("search_control") or {}
                    ).get("previous_search_control_ref"),
                    "previous_search_control_sha256": (
                        cheap_screen_summary.get("search_control") or {}
                    ).get("previous_search_control_sha256"),
                    "template_lineage": packet.get("template_lineage"),
                    "mutation_lineage": packet.get("mutation_lineage"),
                    "data_split_manifest_ref": cheap_screen_summary.get(
                        "data_split_manifest_ref"
                    ),
                    "data_split_manifest_sha256": cheap_screen_summary.get(
                        "data_split_manifest_sha256"
                    ),
                },
                "factor_workspace_plan": {
                    "factor_id": candidate_id,
                    "research_id": research_id,
                    "relative_path": (
                        f"factor_research/{candidate_id}/{research_id}"
                    ),
                    "creation_required_before_ultimate": True,
                },
                "cheap_screen_artifacts": ["objects/cheap_screen/cheap_screen_summary.json"],
                "candidate_specific_signal": row.get("factor_column"),
                "signal_source": row.get("signal_source"),
                "raw_p_value": row.get("raw_p_value"),
                "adjusted_p_value": row.get("adjusted_p_value"),
                "multiplicity_policy": row.get("multiplicity_policy"),
                "multiplicity_alpha": row.get("multiplicity_alpha"),
                "multiplicity_family_size": row.get(
                    "multiplicity_family_size"
                ),
                "overclaim_guard": "Cheap screen is exploratory and cannot support promotion.",
                "search_control_ref": cheap_screen_summary.get(
                    "search_control_ref"
                ),
                "search_control_sha256": cheap_screen_summary.get(
                    "search_control_sha256"
                ),
                "candidate_manifest_sha256": cheap_screen_summary.get(
                    "candidate_manifest_sha256"
                ),
                "data_snapshot_hash": cheap_screen_summary.get(
                    "source_panel_sha256"
                ),
                "is_source_panel_hash": cheap_screen_summary.get(
                    "program_execution_source_sha256"
                ),
                "data_split_manifest_ref": cheap_screen_summary.get(
                    "data_split_manifest_ref"
                ),
                "data_split_manifest_sha256": cheap_screen_summary.get(
                    "data_split_manifest_sha256"
                ),
                "selection_window_id": cheap_screen_summary.get("screen_window"),
                "universe_id": cheap_screen_summary.get("universe"),
                "promotion_forbidden_until_formal": True,
                "program_execution_report_path": cheap_screen_summary.get(
                    "program_execution_report_path"
                ),
                "program_execution_report_sha256": cheap_screen_summary.get(
                    "program_execution_report_sha256"
                ),
            }
        )
    queue = {
        "version": "factorforge_miner_research_queue_v1",
        "campaign_id": campaign_id,
        "generation": cheap_screen_summary.get("generation"),
        "generated_at_utc": utc_now(),
        "search_control": cheap_screen_summary.get("search_control"),
        "search_control_ref": cheap_screen_summary.get(
            "search_control_ref"
        ),
        "search_control_sha256": cheap_screen_summary.get(
            "search_control_sha256"
        ),
        "source_panel_sha256": cheap_screen_summary.get("source_panel_sha256"),
        "is_source_panel_sha256": cheap_screen_summary.get(
            "program_execution_source_sha256"
        ),
        "data_split_manifest_ref": cheap_screen_summary.get(
            "data_split_manifest_ref"
        ),
        "data_split_manifest_sha256": cheap_screen_summary.get(
            "data_split_manifest_sha256"
        ),
        "candidate_manifest_sha256": cheap_screen_summary.get(
            "candidate_manifest_sha256"
        ),
        "promotion_forbidden_until_formal": True,
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
