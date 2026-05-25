#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OBJ = FF / "objects"
TOKEN_SUMMARY_MISSING = "BLOCK_REVISION_COUNCIL_SUMMARY_MISSING"
TOKEN_PACKET_MISSING = "BLOCK_REVISION_COUNCIL_PACKET_MISSING"
TOKEN_PACKET_MISMATCH = "BLOCK_REVISION_COUNCIL_PACKET_MISMATCH"
TOKEN_PACKET_SUMMARY_MISMATCH = "BLOCK_REVISION_COUNCIL_PACKET_SUMMARY_MISMATCH"
TOKEN_CANONICAL_WRITE = "revision_council_no_canonical_write_permission"
TOKEN_EXECUTION_DEFAULT = "revision_council_no_execution_by_default"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(FF))
    except ValueError:
        return str(path)


def proposal_paths(report_id: str) -> list[Path]:
    council_dir = OBJ / "research_iteration_master" / "revision_council" / report_id
    return sorted(council_dir.glob(f"proposal__{report_id}__*.json"))


def load_proposals(report_id: str) -> dict[str, dict[str, Any]]:
    proposals: dict[str, dict[str, Any]] = {}
    for path in proposal_paths(report_id):
        proposal = load_json(path)
        proposal_id = proposal.get("proposal_id")
        if isinstance(proposal_id, str) and proposal_id:
            proposals[proposal_id] = proposal
    for path in sorted((council_dir(report_id) / "agent_results").glob(f"agent_result__{report_id}__*.json")):
        result = load_json(path)
        proposal = proposal_from_agent_result(result, path)
        proposal_id = proposal.get("proposal_id")
        if isinstance(proposal_id, str) and proposal_id:
            proposals[proposal_id] = proposal
    return proposals


def council_dir(report_id: str) -> Path:
    return OBJ / "research_iteration_master" / "revision_council" / report_id


def packet_path_for(report_id: str) -> Path:
    return council_dir(report_id) / f"revision_council_packet__{report_id}.json"


def summary_path_for(report_id: str) -> Path:
    return council_dir(report_id) / f"revision_council_summary__{report_id}.json"


def selected_proposal_ids(summary: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for branch in summary.get("recommended_branch_templates") or []:
        if not isinstance(branch, dict):
            continue
        proposal_id = branch.get("source_proposal_id")
        if isinstance(proposal_id, str) and proposal_id and proposal_id not in ids:
            ids.append(proposal_id)
    return ids


def proposal_from_agent_result(result: dict[str, Any], path: Path) -> dict[str, Any]:
    public = result.get("public_derivation_record") or {}
    laws = [item for item in (result.get("candidate_revision_laws") or []) if isinstance(item, dict)]
    law = laws[0] if laws else {}
    mathematical_objects = public.get("mathematical_objects") if isinstance(public.get("mathematical_objects"), list) else []
    first_object = mathematical_objects[0] if mathematical_objects and isinstance(mathematical_objects[0], dict) else {}
    return {
        "report_id": result.get("report_id"),
        "agent_role": result.get("agent_role"),
        "proposal_id": result.get("task_id"),
        "proposal_status": "proposed",
        "producer": result.get("producer"),
        "research_depth": result.get("research_depth"),
        "proposal_generation_mode": result.get("proposal_generation_mode"),
        "revision_type": law.get("revision_type") or "mechanism_challenge",
        "revision_model_layer": law.get("revision_model_layer") or "observable_estimator",
        "target_failure_signature": "cost_too_high" if result.get("agent_role") == "microstructure_cost_analyst" else "mechanism_unclear",
        "selected_math_tools": [item.get("tool") for item in public.get("selected_tools") or [] if isinstance(item, dict) and item.get("tool")],
        "market_phenomenon": public.get("research_question") or "Agentic Council research result.",
        "symbolic_model": {
            "state_or_object": first_object.get("name") or "agentic_state",
            "target_functional": ((public.get("formula_claims") or [{}])[0] or {}).get("formula_or_relation") if isinstance(public.get("formula_claims"), list) else "E[next evidence | state]",
        },
        "candidate_revision_laws": [
            {
                "law_statement": item.get("law_statement"),
                "formula_direction": item.get("expression_change_direction"),
                "revision_model_layer": item.get("revision_model_layer") or "observable_estimator",
                "expected_metric_change": item.get("expected_metric_change") or [],
                "falsification_tests": item.get("falsification_tests") or [],
                "kill_criteria": item.get("kill_criteria") or [],
            }
            for item in laws
        ],
        "expression_change": law.get("expression_change_direction") or "See agentic result.",
        "why_not_portfolio_fix": law.get("why_not_portfolio_fix") or "Expression-level research only.",
        "confidence": "medium" if result.get("research_depth") == "medium" else "low",
        "risk_notes": public.get("overclaim_guard") or "Agentic result is advisory-only.",
        "derivation_record": {
            "research_question": public.get("research_question") or "Agentic Council research question.",
            "selected_tools": public.get("selected_tools") or [],
            "revision_hypotheses": [
                {
                    "hypothesis": item.get("law_statement"),
                    "expression_direction": item.get("expression_change_direction"),
                    "revision_model_layer": item.get("revision_model_layer") or "observable_estimator",
                    "expected_metric_change": item.get("expected_metric_change") or [],
                    "falsification_tests": item.get("falsification_tests") or [],
                    "kill_criteria": item.get("kill_criteria") or [],
                }
                for item in laws
            ],
            "public_derivation_record": public,
        },
        "source_agent_result_path": str(path),
    }


def preflight_packet_summary_proposals(report_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    packet_path = packet_path_for(report_id)
    summary_path = summary_path_for(report_id)
    if not packet_path.exists():
        block(TOKEN_PACKET_MISSING, {"report_id": report_id, "packet_path": str(packet_path)})
    if not summary_path.exists():
        block(TOKEN_SUMMARY_MISSING, {"report_id": report_id, "summary_path": str(summary_path)})

    packet = load_json(packet_path)
    summary = load_json(summary_path)
    packet_report_id = packet.get("report_id")
    summary_report_id = summary.get("report_id")
    if packet_report_id != report_id:
        block(
            TOKEN_PACKET_MISMATCH,
            {"report_id": report_id, "packet_path": str(packet_path), "packet_report_id": packet_report_id},
        )
    if summary_report_id != report_id or packet_report_id != summary_report_id:
        block(
            TOKEN_PACKET_SUMMARY_MISMATCH,
            {
                "report_id": report_id,
                "packet_report_id": packet_report_id,
                "summary_report_id": summary_report_id,
            },
        )

    for field in ("mode", "status", "council_mode"):
        if field in packet and field in summary and packet.get(field) != summary.get(field):
            block(
                TOKEN_PACKET_SUMMARY_MISMATCH,
                {
                    "report_id": report_id,
                    "field": field,
                    "packet_value": packet.get(field),
                    "summary_value": summary.get(field),
                },
            )

    proposals = load_proposals(report_id)
    candidate = summary.get("candidate_proposals") or []
    blocked = summary.get("blocked_proposals") or []
    if isinstance(candidate, list) and isinstance(blocked, list):
        valid_agent = summary.get("valid_agent_results") or []
        blocked_agent = summary.get("blocked_agent_results") or []
        ignored_deterministic = summary.get("ignored_deterministic_proposals") or []
        summary_count = (
            len(candidate)
            + len(blocked)
            + (len(valid_agent) if isinstance(valid_agent, list) else 0)
            + (len(blocked_agent) if isinstance(blocked_agent, list) else 0)
            + (len(ignored_deterministic) if isinstance(ignored_deterministic, list) else 0)
        )
        if summary_count != len(proposals):
            block(
                TOKEN_PACKET_SUMMARY_MISMATCH,
                {
                    "report_id": report_id,
                    "reason": "proposal_count_mismatch",
                    "summary_proposal_count": summary_count,
                    "proposal_file_count": len(proposals),
                },
            )
    if "proposal_count" in packet and packet.get("proposal_count") != len(proposals):
        block(
            TOKEN_PACKET_SUMMARY_MISMATCH,
            {
                "report_id": report_id,
                "reason": "packet_proposal_count_mismatch",
                "packet_proposal_count": packet.get("proposal_count"),
                "proposal_file_count": len(proposals),
            },
        )
    if "proposal_count" in summary and summary.get("proposal_count") != len(proposals):
        block(
            TOKEN_PACKET_SUMMARY_MISMATCH,
            {
                "report_id": report_id,
                "reason": "summary_proposal_count_mismatch",
                "summary_proposal_count": summary.get("proposal_count"),
                "proposal_file_count": len(proposals),
            },
        )

    selected_ids = selected_proposal_ids(summary)
    missing_selected = [proposal_id for proposal_id in selected_ids if proposal_id not in proposals]
    if missing_selected:
        block(
            TOKEN_PACKET_SUMMARY_MISMATCH,
            {
                "report_id": report_id,
                "reason": "selected_proposal_file_missing",
                "missing_selected_proposal_ids": missing_selected,
            },
        )
    return packet, summary, proposals


def collect_math_tools(proposals: dict[str, dict[str, Any]], selected_ids: list[str]) -> list[str]:
    tools: list[str] = []
    for proposal_id in selected_ids:
        record = (proposals.get(proposal_id) or {}).get("derivation_record") or {}
        for item in record.get("selected_tools") or []:
            if isinstance(item, dict) and isinstance(item.get("tool"), str) and item["tool"] not in tools:
                tools.append(item["tool"])
    return tools


def hypothesis_from_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    laws = [item for item in (proposal.get("candidate_revision_laws") or []) if isinstance(item, dict)]
    law = laws[0] if laws else {}
    derivation_hypotheses = ((proposal.get("derivation_record") or {}).get("revision_hypotheses") or [])
    derivation_hypothesis = derivation_hypotheses[0] if derivation_hypotheses and isinstance(derivation_hypotheses[0], dict) else {}
    return {
        "hypothesis_id": proposal.get("proposal_id"),
        "hypothesis": law.get("law_statement") or derivation_hypothesis.get("hypothesis") or proposal.get("risk_notes") or "Council advisory hypothesis.",
        "mechanism_target": (proposal.get("symbolic_model") or {}).get("state_or_object") or "unknown",
        "revision_model_layer": proposal.get("revision_model_layer") or law.get("revision_model_layer") or derivation_hypothesis.get("revision_model_layer") or "observable_estimator",
        "expression_change": proposal.get("expression_change") or derivation_hypothesis.get("expression_direction") or "See council proposal.",
        "implementation_mode_preference": "unknown",
        "expected_metric_change": law.get("expected_metric_change") or derivation_hypothesis.get("expected_metric_change") or [],
        "falsification_tests": law.get("falsification_tests") or derivation_hypothesis.get("falsification_tests") or [],
        "kill_criteria": law.get("kill_criteria") or derivation_hypothesis.get("kill_criteria") or [],
        "risk_of_overfit": proposal.get("confidence") or "unknown",
        "why_not_portfolio_fix": proposal.get("why_not_portfolio_fix") or "Council proposals are expression-level and advisory-only; portfolio repair is forbidden.",
        "source_council_proposal_id": proposal.get("proposal_id"),
    }


def build_council_revision_strategy(iteration: dict[str, Any], council_summary: dict[str, Any], proposals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    research_memo = ((iteration.get("research_judgment") or {}).get("research_memo") or {})
    deterministic = research_memo.get("revision_strategy") or {}
    selected_ids = selected_proposal_ids(council_summary)
    selected_proposals = [proposals[item] for item in selected_ids if item in proposals]
    first_signature = next((item.get("target_failure_signature") for item in selected_proposals if item.get("target_failure_signature")), None)
    hypotheses = [hypothesis_from_proposal(item) for item in selected_proposals]
    return {
        "revision_needed": bool(hypotheses) or deterministic.get("revision_needed") is True,
        "primary_failure_signature": first_signature or deterministic.get("primary_failure_signature") or "none",
        "revision_hypotheses": hypotheses,
        "revision_quality": "actionable" if hypotheses else deterministic.get("revision_quality", "weak"),
        "loop_authorization": "advisory_only",
        "requires_human_approval_before_code_change": True,
        "source": "revision_council",
        "selected_council_proposal_ids": selected_ids,
        "derivation_records": [
            {
                "proposal_id": proposal.get("proposal_id"),
                "agent_role": proposal.get("agent_role"),
                "producer": proposal.get("producer"),
                "research_depth": proposal.get("research_depth"),
                "derivation_record": proposal.get("derivation_record") or {},
            }
            for proposal in selected_proposals
        ],
        "approval_required_before_step3b": True,
        "fallback_used": False,
        "why_selected": "Council recommended advisory branch templates from valid derivation-backed proposals.",
        "why_deterministic_fallback_not_used": "Council produced valid derivation-backed proposals.",
    }


def build_revision_council_ref(report_id: str, summary: dict[str, Any], proposals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate = summary.get("candidate_proposals") or []
    valid_agent = summary.get("valid_agent_results") or []
    blocked = summary.get("blocked_proposals") or []
    blocked_agent = summary.get("blocked_agent_results") or []
    branches = summary.get("recommended_branch_templates") or []
    candidate_sources = list(candidate) + list(valid_agent)
    producer_modes = sorted({str(item.get("producer")) for item in candidate_sources if isinstance(item, dict) and item.get("producer")})
    research_depths = sorted({str(item.get("research_depth")) for item in candidate_sources if isinstance(item, dict) and item.get("research_depth")})
    return {
        "enabled": True,
        "mode": "agentic_contract_mock" if "local_mock_agentic_contract" in producer_modes else ("scaffold" if producer_modes == ["deterministic_scaffold"] else "mixed"),
        "status": "completed",
        "packet_path": relpath(OBJ / "research_iteration_master" / "revision_council" / report_id / f"revision_council_packet__{report_id}.json"),
        "summary_path": relpath(OBJ / "research_iteration_master" / "revision_council" / report_id / f"revision_council_summary__{report_id}.json"),
        "proposal_count": len(proposals),
        "valid_proposal_count": len(candidate) + len(valid_agent),
        "blocked_proposal_count": len(blocked) + len(blocked_agent),
        "recommended_branch_count": len(branches),
        "producer_modes": producer_modes,
        "research_depths": research_depths,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": summary.get("human_approval_required") is True,
    }


def build_brief_council_summary(report_id: str, council_summary: dict[str, Any], proposals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    selected_ids = selected_proposal_ids(council_summary)
    branches = council_summary.get("recommended_branch_templates") or []
    return {
        "enabled": True,
        "mode": "agentic_contract_mock" if council_summary.get("valid_agent_results") else "scaffold",
        "status": "completed",
        "proposal_count": len(proposals),
        "selected_proposals": selected_ids,
        "mathematical_tools_used": collect_math_tools(proposals, selected_ids),
        "derivation_record_summary": [
            {
                "proposal_id": proposal_id,
                "research_question": ((proposals.get(proposal_id) or {}).get("derivation_record") or {}).get("research_question"),
                "producer": (proposals.get(proposal_id) or {}).get("producer"),
                "research_depth": (proposals.get(proposal_id) or {}).get("research_depth"),
            }
            for proposal_id in selected_ids
        ],
        "recommended_branches": branches,
        "why_no_automatic_step3b_handoff": "Council output is advisory-only until human approval.",
        "human_approval_required": True,
    }


def append_council_markdown(markdown: str, council_summary: dict[str, Any], proposals: dict[str, dict[str, Any]]) -> str:
    if "## Revision Council Summary" in markdown:
        markdown = markdown.split("## Revision Council Summary", 1)[0].rstrip() + "\n\n"
    selected_ids = selected_proposal_ids(council_summary)
    branches = council_summary.get("recommended_branch_templates") or []
    branch_lines = [
        f"- {branch.get('branch_id')}: {branch.get('branch_role')} / {branch.get('search_mode')}"
        for branch in branches
        if isinstance(branch, dict)
    ]
    tools = collect_math_tools(proposals, selected_ids)
    section = [
        "## Revision Council Summary",
        "",
        f"- Council mode: scaffold",
        f"- Proposal count: {len(proposals)}",
        f"- Selected proposal ids: {', '.join(selected_ids) if selected_ids else 'none'}",
        f"- Mathematical tools used: {', '.join(tools) if tools else 'none'}",
        "- Recommended branches:",
        *(branch_lines or ["  - none"]),
        "- Why no automatic Step3B handoff: Council output is advisory-only until human approval.",
        "- Human approval required: true",
        "",
    ]
    return markdown.rstrip() + "\n\n" + "\n".join(section)


def block(token: str, payload: dict[str, Any]) -> None:
    print(token + ": " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    report_id = args.report_id

    iteration_path = OBJ / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    if not iteration_path.exists():
        block("BLOCK_REVISION_COUNCIL_ITERATION_MISSING", {"report_id": report_id, "path": str(iteration_path)})

    packet, summary, proposals = preflight_packet_summary_proposals(report_id)
    iteration = load_json(iteration_path)
    if summary.get("canonical_write_permission") is True:
        block(TOKEN_CANONICAL_WRITE, {"report_id": report_id, "summary_path": str(summary_path_for(report_id))})
    if summary.get("execution_allowed_by_default") is True:
        block(TOKEN_EXECUTION_DEFAULT, {"report_id": report_id, "summary_path": str(summary_path_for(report_id))})

    updated = copy.deepcopy(iteration)
    research_judgment = updated.setdefault("research_judgment", {})
    research_memo = research_judgment.setdefault("research_memo", {})
    deterministic_revision = copy.deepcopy(research_memo.get("revision_strategy") or {})
    council_revision = build_council_revision_strategy(updated, summary, proposals)
    final_revision = copy.deepcopy(council_revision)
    final_revision.update(
        {
            "source": "revision_council",
            "fallback_used": False,
            "approval_required_before_step3b": True,
            "why_selected": council_revision.get("why_selected"),
            "why_deterministic_fallback_not_used": "Council produced valid derivation-backed proposals.",
        }
    )
    updated["revision_council_ref"] = build_revision_council_ref(report_id, summary, proposals)
    research_memo["deterministic_revision_strategy"] = deterministic_revision
    research_memo["council_revision_strategy"] = council_revision
    research_memo["final_revision_strategy"] = final_revision

    brief_ref = updated.get("loop_research_brief") or {}
    brief_json_path = Path(brief_ref.get("json_path") or "")
    brief_md_path = Path(brief_ref.get("markdown_path") or "")
    if not brief_json_path.is_absolute():
        brief_json_path = FF / brief_json_path
    if not brief_md_path.is_absolute():
        brief_md_path = FF / brief_md_path
    if brief_json_path.exists():
        brief = load_json(brief_json_path)
        brief["revision_council_summary"] = build_brief_council_summary(report_id, summary, proposals)
        write_json(brief_json_path, brief)
    if brief_md_path.exists():
        markdown = brief_md_path.read_text(encoding="utf-8")
        brief_md_path.write_text(append_council_markdown(markdown, summary, proposals), encoding="utf-8")

    write_json(iteration_path, updated)
    print(
        json.dumps(
            {
                "status": "attached",
                "report_id": report_id,
                "iteration_path": str(iteration_path),
                "packet_path": str(packet_path_for(report_id)),
                "summary_path": str(summary_path_for(report_id)),
                "selected_council_proposal_ids": council_revision.get("selected_council_proposal_ids"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
