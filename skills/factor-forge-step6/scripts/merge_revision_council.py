#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.revision_council.guards import FORBIDDEN_TEXT_TOKEN, scan_forbidden_text
from factor_factory.revision_council.schema import (
    BRANCH_HARD_GUARDS,
    COUNCIL_AGENT_ROLES,
    COUNCIL_SUMMARY_VERSION,
)
from factor_factory.revision_council.validator import validate_revision_council_proposal
from validate_agentic_council_result import (
    expected_manifest_task,
    validate_agentic_result,
)

OBJ = FF / "objects"
TOKEN_FORBIDDEN_WRITEBACK = "BLOCK_REVISION_COUNCIL_FORBIDDEN_WRITEBACK_PRESENT"
TOKEN_AGENTIC_RESULTS_INVALID = "BLOCK_REVISION_COUNCIL_AGENTIC_RESULTS_INVALID"
BASELINE_VERSION = "factorforge_revision_council_forbidden_writeback_baseline_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(FF))
    except ValueError:
        return str(path)


def should_skip_digest_path(path: Path) -> bool:
    name = path.name
    return (
        name == "__pycache__"
        or name == ".DS_Store"
        or name.endswith(".lock")
        or name.endswith(".tmp")
        or name.endswith(".swp")
        or name.endswith(".swx")
        or name.startswith(".#")
        or name.startswith("~$")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_payload_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def directory_digest(path: Path) -> str:
    entries: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        if any(should_skip_digest_path(part) for part in item.relative_to(path).parents):
            continue
        if should_skip_digest_path(item):
            continue
        if not item.is_file():
            continue
        stat = item.stat()
        entries.append(
            {
                "relative_path": item.relative_to(path).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(item),
            }
        )
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_baseline_path(snapshot: dict[str, Any], report_id: str, key: str) -> Path:
    declared = snapshot.get("path")
    if isinstance(declared, str) and declared:
        candidate = Path(declared)
        return candidate if candidate.is_absolute() else FF / candidate
    defaults = {
        "handoff_to_step3b": OBJ / "handoff" / f"handoff_to_step3b__{report_id}.json",
        "generated_code": FF / "generated_code" / report_id,
        "official_library": OBJ / "factor_library_official" / f"factor_record__{report_id}.json",
        "data_clean": FF / "data" / "clean",
    }
    return defaults[key]


def snapshot_path(path: Path, kind: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "path": relpath(path),
        "exists": path.exists(),
        "kind": kind,
        "mtime_ns": None,
    }
    if not path.exists():
        if kind == "file":
            snapshot["sha256"] = None
        else:
            snapshot["digest"] = None
        return snapshot
    stat = path.stat()
    snapshot["mtime_ns"] = stat.st_mtime_ns
    if kind == "file":
        snapshot["sha256"] = sha256_file(path) if path.is_file() else None
    else:
        snapshot["digest"] = directory_digest(path) if path.is_dir() else None
    return snapshot


def compare_forbidden_writeback_baseline(report_id: str, packet: dict[str, Any]) -> list[dict[str, Any]]:
    baseline = packet.get("forbidden_writeback_baseline")
    if not isinstance(baseline, dict) or baseline.get("contract_version") != BASELINE_VERSION:
        return [
            {
                "reason": "forbidden_writeback_baseline_missing",
                "path_key": "forbidden_writeback_baseline",
                "path": str(OBJ / "research_iteration_master" / "revision_council" / report_id / f"revision_council_packet__{report_id}.json"),
                "baseline_exists": False,
                "current_exists": None,
            }
        ]
    paths = baseline.get("paths")
    if not isinstance(paths, dict):
        return [{"reason": "forbidden_writeback_baseline_paths_missing", "path_key": "paths", "path": "", "baseline_exists": False, "current_exists": None}]

    changes: list[dict[str, Any]] = []
    required_keys = {"handoff_to_step3b", "generated_code", "official_library", "data_clean"}
    for key in sorted(required_keys):
        base = paths.get(key)
        if not isinstance(base, dict):
            changes.append({"reason": "forbidden_writeback_baseline_entry_missing", "path_key": key, "path": "", "baseline_exists": None, "current_exists": None})
            continue
        kind = base.get("kind") if base.get("kind") in {"file", "directory"} else ("directory" if key in {"generated_code", "data_clean"} else "file")
        path = resolve_baseline_path(base, report_id, key)
        current = snapshot_path(path, kind)
        base_exists = bool(base.get("exists"))
        current_exists = bool(current.get("exists"))
        reason = ""
        if not base_exists and current_exists:
            reason = "forbidden_writeback_created_after_packet"
        elif base_exists and not current_exists:
            reason = "forbidden_writeback_deleted_after_packet"
        elif base_exists and current_exists:
            if kind == "file" and current.get("sha256") != base.get("sha256"):
                reason = "forbidden_writeback_changed_after_packet"
            if kind == "directory" and current.get("digest") != base.get("digest"):
                reason = "forbidden_writeback_changed_after_packet"
        if reason:
            changes.append(
                {
                    "reason": reason,
                    "path_key": key,
                    "path": str(path),
                    "baseline_exists": base_exists,
                    "current_exists": current_exists,
                    "baseline_sha256": base.get("sha256"),
                    "current_sha256": current.get("sha256"),
                    "baseline_digest": base.get("digest"),
                    "current_digest": current.get("digest"),
                    "baseline_mtime_ns": base.get("mtime_ns"),
                    "current_mtime_ns": current.get("mtime_ns"),
                }
            )
    return changes


def write_prewrite_block(report_id: str, packet: dict[str, Any], comparisons: list[dict[str, Any]]) -> Path:
    diagnostic = {
        "report_id": report_id,
        "block_reason": "forbidden_writeback_present",
        "merge_written": False,
        "comparisons": comparisons,
        "baseline": packet.get("forbidden_writeback_baseline") or {},
    }
    out = OBJ / "validation" / f"revision_council_merge_prewrite_block__{report_id}.json"
    write_json(out, diagnostic)
    return out


def branch_from_proposal(proposal: dict[str, Any]) -> dict[str, Any] | None:
    role = proposal.get("agent_role")
    revision_type = proposal.get("revision_type")
    signature = proposal.get("target_failure_signature")
    if revision_type in {"reject_advisory", "no_action"}:
        return None
    if revision_type == "audit" or signature in {"implementation_suspect", "same_factor_identity_mismatch"}:
        branch_role, search_mode, branch_id = "audit", "research_audit", "audit_council_evidence"
    elif signature == "cost_too_high" and revision_type == "expression_revision":
        branch_role, search_mode, branch_id = "exploit", "bayesian_search", "exploit_council_cost_turnover"
    elif signature == "non_monotonic" or role == "formula_engineer":
        branch_role, search_mode, branch_id = "explore", "genetic_algorithm", "explore_council_formula_structure"
    else:
        branch_role, search_mode, branch_id = "macro", "mechanism_challenge", "challenge_council_symbolic_law"
    branch = {
        "branch_id": branch_id,
        "status": "proposed",
        "branch_role": branch_role,
        "search_mode": search_mode,
        "research_question": proposal.get("market_phenomenon") or "Evaluate council proposal.",
        "hypothesis": (proposal.get("candidate_revision_laws") or [{}])[0].get("law_statement") if proposal.get("candidate_revision_laws") else proposal.get("risk_notes"),
        "mechanism_target": (
            (proposal.get("symbolic_model") or {}).get("mathematical_object")
            or (proposal.get("symbolic_model") or {}).get("state_or_object")
        ),
        "revision_hypothesis_id": proposal.get("proposal_id"),
        "success_criteria": ["Verified evidence improves under the declared expression-level hypothesis.", "No forbidden repair path is used."],
        "falsification_tests": (proposal.get("candidate_revision_laws") or [{}])[0].get("falsification_tests") if proposal.get("candidate_revision_laws") else ["Reject if evidence remains contradictory."],
        "hard_guards": list(BRANCH_HARD_GUARDS),
        "requires_human_approval_before_execution": True,
        "human_approval_required": True,
        "execution_allowed_by_default": False,
        "advisory_only": True,
        "source_proposal_id": proposal.get("proposal_id"),
        "source_agent_role": role,
        "source_producer": proposal.get("producer"),
        "source_research_depth": proposal.get("research_depth"),
        "not_sufficient_for_formal_revision": proposal.get("producer") != "agentic_research",
    }
    if proposal.get("producer") == "agentic_research" and proposal.get("research_depth") in {"medium", "high"}:
        branch["not_sufficient_for_formal_revision"] = False
    forbidden = scan_forbidden_text(branch)
    if forbidden:
        branch["blocked_reason"] = FORBIDDEN_TEXT_TOKEN + ":" + ",".join(f"{x['path']}={x['pattern']}" for x in forbidden)
    return branch


def proposal_like_from_agent_result(result: dict[str, Any]) -> dict[str, Any]:
    role = result.get("agent_role")
    laws = [item for item in (result.get("candidate_revision_laws") or []) if isinstance(item, dict)]
    law = laws[0] if laws else {}
    public = result.get("public_derivation_record") or {}
    formula_claims = [item for item in public.get("formula_claims") or [] if isinstance(item, dict)]
    claim = formula_claims[0] if formula_claims else {}
    revision_type = law.get("revision_type") or "mechanism_challenge"
    return {
        "report_id": result.get("report_id"),
        "agent_role": role,
        "proposal_id": result.get("task_id") or f"agent_{role}",
        "proposal_status": "proposed",
        "producer": "agentic_research" if result.get("producer") == "real_agent" else result.get("producer"),
        "research_depth": result.get("research_depth"),
        "proposal_generation_mode": result.get("proposal_generation_mode"),
        "revision_type": revision_type,
        "revision_model_layer": law.get("revision_model_layer") or "observable_estimator",
        "target_failure_signature": "cost_too_high" if role == "microstructure_cost_analyst" else "mechanism_unclear",
        "selected_math_tools": [item.get("tool") for item in public.get("selected_tools") or [] if isinstance(item, dict) and item.get("tool")],
        "market_phenomenon": public.get("research_question") or claim.get("claim") or "Agentic council result.",
        "symbolic_model": dict(
            result.get("measurement_program_binding") or {}
        ),
        "candidate_revision_laws": [
            {
                "law_statement": law.get("law_statement"),
                "formula_direction": law.get("expression_change_direction"),
                "revision_model_layer": law.get("revision_model_layer") or "observable_estimator",
                "expected_metric_change": law.get("expected_metric_change") or [],
                "falsification_tests": law.get("falsification_tests") or [],
                "kill_criteria": law.get("kill_criteria") or [],
            }
            for law in laws
        ],
        "expression_change": law.get("expression_change_direction") or "See agentic result.",
        "why_not_portfolio_fix": law.get("why_not_portfolio_fix") or "Expression-level research only.",
        "confidence": "medium" if result.get("research_depth") == "medium" else "low",
        "risk_notes": public.get("overclaim_guard") or "Agentic result is advisory-only.",
        "derivation_record": {
            "research_question": public.get("research_question") or "Agentic council research question.",
            "selected_tools": public.get("selected_tools") or [],
            "revision_hypotheses": [
                {
                    "hypothesis": law.get("law_statement"),
                    "expression_direction": law.get("expression_change_direction"),
                    "revision_model_layer": law.get("revision_model_layer") or "observable_estimator",
                    "expected_metric_change": law.get("expected_metric_change") or [],
                    "falsification_tests": law.get("falsification_tests") or [],
                    "kill_criteria": law.get("kill_criteria") or [],
                }
                for law in laws
            ],
            "public_derivation_record": public,
        },
        "source_agent_result": True,
        "source_task_id": result.get("task_id"),
    }


def branch_from_agent_result(result: dict[str, Any]) -> dict[str, Any] | None:
    proposal = proposal_like_from_agent_result(result)
    role = result.get("agent_role")
    if role == "microstructure_cost_analyst":
        branch_role, search_mode, branch_id = "macro", "mechanism_challenge", "agentic_challenge_cost_microstructure"
    elif role == "symbolic_law_discovery":
        branch_role, search_mode, branch_id = "macro", "mechanism_challenge", "agentic_symbolic_law_challenge"
    elif role == "statistical_falsification_agent":
        branch_role, search_mode, branch_id = "audit", "research_audit", "agentic_falsification_audit"
    else:
        branch_role, search_mode, branch_id = "macro", "mechanism_challenge", f"agentic_{role}"
    laws = [item for item in (result.get("candidate_revision_laws") or []) if isinstance(item, dict)]
    law = laws[0] if laws else {}
    public = result.get("public_derivation_record") or {}
    branch = {
        "branch_id": branch_id,
        "status": "proposed",
        "branch_role": branch_role,
        "search_mode": search_mode,
        "research_question": public.get("research_question") or "Evaluate agentic council result.",
        "hypothesis": law.get("law_statement") or "Agentic council hypothesis.",
        "mechanism_target": (((public.get("mathematical_objects") or [{}])[0] or {}).get("name") if isinstance(public.get("mathematical_objects"), list) else None) or "agentic_state",
        "revision_hypothesis_id": law.get("law_id"),
        "success_criteria": law.get("expected_metric_change") or ["Future evidence improves.", "No forbidden path is used."],
        "falsification_tests": law.get("falsification_tests") or [],
        "hard_guards": list(BRANCH_HARD_GUARDS),
        "requires_human_approval_before_execution": True,
        "human_approval_required": True,
        "execution_allowed_by_default": False,
        "advisory_only": True,
        "source_proposal_id": proposal.get("proposal_id"),
        "source_agent_role": role,
        "source_producer": result.get("producer"),
        "source_research_depth": result.get("research_depth"),
        "source_agent_result_path": result.get("_source_path"),
        "not_sufficient_for_formal_revision": result.get("producer") != "real_agent",
    }
    forbidden = scan_forbidden_text(branch)
    if forbidden:
        branch["blocked_reason"] = FORBIDDEN_TEXT_TOKEN + ":" + ",".join(f"{x['path']}={x['pattern']}" for x in forbidden)
    return branch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid

    packet_path = council_dir / f"revision_council_packet__{rid}.json"
    packet = load_json(packet_path) if packet_path.exists() else {}
    forbidden = compare_forbidden_writeback_baseline(rid, packet)
    if forbidden:
        diagnostic_path = write_prewrite_block(rid, packet, forbidden)
        print(
            TOKEN_FORBIDDEN_WRITEBACK
            + ": "
            + json.dumps({"diagnostic_path": str(diagnostic_path), "comparisons": forbidden}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(1)

    candidate_proposals = []
    blocked_proposals = []
    valid_agent_results = []
    blocked_agent_results = []
    branches = []
    research_routes = []
    candidate_law_index: list[dict[str, Any]] = []
    agent_result_paths = sorted((council_dir / "agent_results").glob(f"agent_result__{rid}__*.json"))
    for path in agent_result_paths:
        result = load_json(path)
        result["_source_path"] = str(path)
        expected = expected_manifest_task(rid, path)
        reasons = validate_agentic_result(
            result,
            expected_task=expected,
            expected_report_id=rid,
        )
        if reasons:
            blocked_agent_results.append({"path": str(path), "task_id": result.get("task_id"), "agent_role": result.get("agent_role"), "block_reasons": reasons})
            continue
        result_sha256 = sha256_file(path)
        valid_agent_results.append({
            "path": str(path),
            "task_id": result.get("task_id"),
            "agent_role": result.get("agent_role"),
            "producer": result.get("producer"),
            "research_depth": result.get("research_depth"),
            "proposal_generation_mode": result.get("proposal_generation_mode"),
            "route_id": (result.get("approach_route") or {}).get("route_id"),
            "route_family": (result.get("approach_route") or {}).get("route_family"),
            "route_status": result.get("route_status"),
            "result_sha256": result_sha256,
        })
        approach_route = result.get("approach_route")
        if isinstance(approach_route, dict) and approach_route:
            research_routes.append(
                {
                    "task_id": result.get("task_id"),
                    "agent_role": result.get("agent_role"),
                    "route_id": approach_route.get("route_id"),
                    "route_family": approach_route.get("route_family"),
                    "core_hypothesis": approach_route.get("core_hypothesis"),
                    "exact_gap_after_analysis": approach_route.get(
                        "exact_gap_after_analysis"
                    ),
                    "route_status": result.get("route_status"),
                    "source_result_path": str(path),
                    "source_result_sha256": result_sha256,
                    "proof_obligation_updates": result.get(
                        "proof_obligation_updates"
                    )
                    or [],
                    "counterexamples": result.get("counterexamples") or [],
                    "reopen_criteria": result.get("reopen_criteria") or [],
                    "source_path": str(path),
                }
            )
        for law in result.get("candidate_revision_laws") or []:
            if not isinstance(law, dict) or not law.get("law_id"):
                continue
            candidate_law_index.append(
                {
                    "law_id": law.get("law_id"),
                    "route_id": (result.get("approach_route") or {}).get("route_id"),
                    "source_result_sha256": result_sha256,
                    "law_hash": stable_payload_hash(law),
                }
            )
        branch = branch_from_agent_result(result)
        if branch:
            if branch.get("blocked_reason"):
                blocked_agent_results.append({"path": str(path), "task_id": result.get("task_id"), "agent_role": result.get("agent_role"), "block_reasons": [branch["blocked_reason"]]})
            elif not any(item.get("branch_id") == branch.get("branch_id") for item in branches):
                branches.append(branch)

    if agent_result_paths and not valid_agent_results:
        print(
            TOKEN_AGENTIC_RESULTS_INVALID
            + ": "
            + json.dumps({"report_id": rid, "blocked_agent_results": blocked_agent_results}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(1)

    proposal_paths = sorted(council_dir.glob(f"proposal__{rid}__*.json"))
    proposal_files = {path.name for path in proposal_paths}
    ignored_deterministic_proposals: list[str] = []
    ignored_deterministic_proposal_ids: list[str] = []
    if valid_agent_results:
        selection_source = "agentic_results"
        deterministic_fallback_used = False
        roles_to_scan: list[str] = []
        for path in proposal_paths:
            ignored_deterministic_proposals.append(relpath(path))
            try:
                proposal = load_json(path)
            except Exception:
                proposal = {}
            proposal_id = proposal.get("proposal_id")
            if isinstance(proposal_id, str) and proposal_id:
                ignored_deterministic_proposal_ids.append(proposal_id)
    else:
        selection_source = "deterministic_scaffold"
        deterministic_fallback_used = True
        roles_to_scan = sorted(COUNCIL_AGENT_ROLES) if proposal_files or not agent_result_paths else []
    for role in roles_to_scan:
        path = council_dir / f"proposal__{rid}__{role}.json"
        if not path.exists():
            blocked_proposals.append({"agent_role": role, "block_reasons": ["missing_proposal"], "path": str(path)})
            continue
        proposal = load_json(path)
        reasons = validate_revision_council_proposal(
            proposal,
            measurement_program=packet.get(
                "mechanism_conditioned_measurement_program"
            ),
        )
        if proposal.get("proposal_status") == "blocked":
            reasons = list(dict.fromkeys(reasons + (proposal.get("block_reasons") or [])))
        if reasons:
            blocked_proposals.append({"agent_role": role, "proposal_id": proposal.get("proposal_id"), "block_reasons": reasons, "path": str(path)})
            continue
        candidate_proposals.append({
            "agent_role": role,
            "proposal_id": proposal.get("proposal_id"),
            "revision_type": proposal.get("revision_type"),
            "producer": proposal.get("producer"),
            "research_depth": proposal.get("research_depth"),
            "proposal_generation_mode": proposal.get("proposal_generation_mode"),
        })
        branch = branch_from_proposal(proposal)
        if branch:
            if branch.get("blocked_reason"):
                blocked_proposals.append({"agent_role": role, "proposal_id": proposal.get("proposal_id"), "block_reasons": [branch["blocked_reason"]], "path": str(path)})
            elif not branch.get("execution_allowed_by_default") and branch.get("requires_human_approval_before_execution") is True:
                if not any(item.get("branch_id") == branch.get("branch_id") for item in branches):
                    branches.append(branch)

    taskbook_path = council_dir / f"agentic_taskbook__{rid}.json"
    taskbook = load_json(taskbook_path) if taskbook_path.exists() else {}
    route_families = {
        str(item.get("route_family"))
        for item in research_routes
        if item.get("route_family")
    }
    summary = {
        "contract_version": COUNCIL_SUMMARY_VERSION,
        "report_id": rid,
        "candidate_proposals": candidate_proposals,
        "blocked_proposals": blocked_proposals,
        "valid_agent_results": valid_agent_results,
        "blocked_agent_results": blocked_agent_results,
        "selection_source": selection_source,
        "research_protocol_version": taskbook.get("research_protocol_version"),
        "research_protocol_gate": taskbook.get("research_protocol_gate") or {},
        "research_route_summary": research_routes,
        "candidate_law_index": candidate_law_index,
        "root_synthesis_contract": {
            "required": bool(research_routes),
            "majority_vote_forbidden": True,
            "must_compare_every_route": bool(research_routes),
            "must_resolve_or_preserve_dissent": bool(research_routes),
            "must_list_open_proof_obligations": bool(research_routes),
            "route_family_count": len(route_families),
        },
        "deterministic_fallback_used": deterministic_fallback_used,
        "ignored_deterministic_proposals": ignored_deterministic_proposals,
        "ignored_deterministic_proposal_ids": ignored_deterministic_proposal_ids,
        "recommended_branch_templates": branches,
        "arbiter_notes": [
            "Revision council is proposal-only.",
            "Branch templates are advisory and require human approval before any execution.",
        ],
        "human_approval_required": True,
        "execution_allowed_by_default": False,
    }
    out = council_dir / f"revision_council_summary__{rid}.json"
    write_json(out, summary)
    print(json.dumps({"status": "written", "path": str(out), "branch_count": len(branches)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
