#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.research_proof import (
    factor_proof_certificate_path,
    validate_factor_proof_certificate,
)
from validate_agentic_council_collection import validate_collection
from validate_agentic_council_result import (
    expected_manifest_task,
    validate_agentic_result,
)

TERMINAL_REJECTION_VERSION = "factorforge_terminal_council_rejection_v1"
TOKEN_SUMMARY_MISSING = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_SUMMARY_MISSING"
TOKEN_COLLECTION_MISSING = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_COLLECTION_MISSING"
TOKEN_COLLECTION_INVALID = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_COLLECTION_INVALID"
TOKEN_RESULTS_INVALID = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_RESULTS_INVALID"
TOKEN_NOT_UNANIMOUS = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_NOT_UNANIMOUS"
TOKEN_ITERATION_MISSING = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_ITERATION_MISSING"
TOKEN_VALIDATION_FAILED = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_VALIDATION_FAILED"
TOKEN_HANDOFF_EXISTS = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_APPROVED_HANDOFF_EXISTS"
TOKEN_PREMATURE_TERMINAL_REJECT = "BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS"
TOKEN_FACTOR_PROOF_NOT_REJECTED = (
    "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_FACTOR_PROOF_NOT_REJECTED"
)

TERMINAL_RECOMMENDATION_VALUES = {
    "reject",
    "kill",
    "stop",
    "terminal_reject",
    "no_revision",
    "no_derived_revision",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[WRITE] {path}")


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    print(f"[WRITE] {path}")


def read_text_if_exists(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def restore_text_snapshot(path: Path | None, text: str | None) -> None:
    if path is None:
        return
    if text is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def block(token: str, payload: dict[str, Any]) -> None:
    print(token + ": " + json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)


def nonempty_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def council_dir(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def iteration_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"


def factor_library_all_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "factor_library_all" / f"factor_record__{report_id}.json"


def research_knowledge_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_knowledge_base" / f"knowledge_record__{report_id}.json"


def handoff_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"


def terminal_rejection_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"terminal_council_rejection__{report_id}.json"


def branch_falsification_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"branch_falsification__{report_id}.json"


def next_derivation_questionnaire_paths(root: Path, report_id: str) -> tuple[Path, Path]:
    cdir = council_dir(root, report_id)
    return (
        cdir / f"next_derivation_questionnaire__{report_id}.json",
        cdir / f"next_derivation_questionnaire__{report_id}.md",
    )


def resolve_under_root(root: Path, raw: Any) -> Path:
    resolved_root = root.expanduser().resolve(strict=False)
    lexical = Path(str(raw)).expanduser()
    if not lexical.is_absolute():
        lexical = resolved_root / lexical
    try:
        lexical_relative = lexical.relative_to(resolved_root)
    except ValueError:
        block(
            TOKEN_VALIDATION_FAILED,
            {"reason": "workspace_path_escape_forbidden"},
        )
    cursor = resolved_root
    if any(
        (cursor := cursor / part).is_symlink()
        for part in lexical_relative.parts
    ):
        block(
            TOKEN_VALIDATION_FAILED,
            {"reason": "workspace_path_symlink_forbidden"},
        )
    path = lexical.resolve(strict=False)
    if path != resolved_root and resolved_root not in path.parents:
        block(
            TOKEN_VALIDATION_FAILED,
            {"reason": "workspace_path_escape_forbidden"},
        )
    return path


def loop_brief_paths(root: Path, iteration: dict[str, Any]) -> tuple[Path | None, Path | None]:
    ref = iteration.get("loop_research_brief") if isinstance(iteration.get("loop_research_brief"), dict) else {}
    json_path = resolve_under_root(root, ref.get("json_path")) if ref.get("json_path") else None
    md_path = resolve_under_root(root, ref.get("markdown_path")) if ref.get("markdown_path") else None
    return json_path, md_path


def result_paths_from_collection(root: Path, collection: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in collection.get("valid_results") or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("result_path")
        if isinstance(raw, str) and raw:
            paths.append(resolve_under_root(root, raw))
    return paths


def terminal_recommendation_value(result: dict[str, Any]) -> str:
    rec = result.get("revision_or_kill_recommendation")
    if not isinstance(rec, dict) or not isinstance(rec.get("recommendation"), str):
        return ""
    return str(rec["recommendation"]).strip().lower()


def prior_revision_review_present(result: dict[str, Any]) -> bool:
    review = result.get("prior_revision_outcome_review")
    guard = result.get("repeated_revision_guard")
    text = json.dumps({"review": review, "guard": guard}, ensure_ascii=False).lower()
    return isinstance(review, dict) and isinstance(guard, dict) and ("falsified" in text or "failed" in text)


def load_valid_terminal_results(root: Path, collection: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    non_terminal: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for path in result_paths_from_collection(root, collection):
        try:
            payload = load_json(path)
        except Exception as exc:
            invalid.append({"result_path": str(path), "block_reasons": [f"unreadable:{exc}"]})
            continue
        reasons = validate_agentic_result(
            payload,
            expected_task=expected_manifest_task(
                str(collection.get("report_id") or ""),
                path,
            ),
            expected_report_id=str(collection.get("report_id") or ""),
        )
        if reasons:
            invalid.append({"result_path": str(path), "block_reasons": reasons})
            continue
        recommendation = terminal_recommendation_value(payload)
        is_terminal = recommendation in TERMINAL_RECOMMENDATION_VALUES
        if not is_terminal:
            non_terminal.append({"result_path": str(path), "task_id": payload.get("task_id"), "recommendation": recommendation})
            continue
        results.append({"path": str(path), "payload": payload, "prior_review_present": prior_revision_review_present(payload)})
    if invalid:
        block(TOKEN_RESULTS_INVALID, {"invalid_results": invalid})
    return results, non_terminal


def selected_ids(results: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in results:
        task_id = item["payload"].get("task_id")
        if isinstance(task_id, str) and task_id and task_id not in ids:
            ids.append(task_id)
    return ids


def terminal_control(result: dict[str, Any]) -> dict[str, Any]:
    rec = result.get("revision_or_kill_recommendation")
    control = result.get("terminal_control")
    merged: dict[str, Any] = {}
    if isinstance(rec, dict):
        for key in (
            "terminal_scope",
            "stop_authority",
            "validated_no_derived_revision",
            "human_override",
            "evidence_block",
            "terminal_proof",
        ):
            if key in rec:
                merged[key] = rec[key]
    if isinstance(control, dict):
        merged.update(control)
    return merged


def result_has_terminal_authority(result: dict[str, Any]) -> bool:
    control = terminal_control(result)
    authority = str(control.get("stop_authority") or "").strip()
    scope = str(control.get("terminal_scope") or "").strip()
    proof = control.get("terminal_proof") or control.get("proof") or control.get("reason")
    has_proof = isinstance(proof, str) and bool(proof.strip()) or isinstance(proof, dict) and bool(proof)
    if scope not in {"factor_instance", "mechanism_family"}:
        return False
    if control.get("human_override") is True or authority == "human_override":
        return has_proof
    if control.get("evidence_block") is True or authority == "evidence_block":
        return has_proof
    if control.get("validated_no_derived_revision") is True or authority in {"block_with_proof", "validated_no_derived_revision"}:
        return scope in {"factor_instance", "mechanism_family"} and has_proof
    if authority == "max_loop_cap":
        return has_proof
    return False


def terminal_reject_authorized(results: list[dict[str, Any]], *, loop_index: int, max_loops: int) -> bool:
    if loop_index >= max_loops:
        return True
    return bool(results) and all(result_has_terminal_authority(item["payload"]) for item in results)


def render_next_derivation_questionnaire(payload: dict[str, Any]) -> str:
    answers = payload.get("required_main_agent_answers") if isinstance(payload.get("required_main_agent_answers"), list) else []
    laws = payload.get("falsified_revision_laws") if isinstance(payload.get("falsified_revision_laws"), list) else []
    hashes = payload.get("falsified_formula_hashes") if isinstance(payload.get("falsified_formula_hashes"), list) else []
    lines = [
        f"# Next Derivation Questionnaire: {payload['report_id']}",
        "",
        f"Status: `{payload['status']}`",
        f"Prior terminal scope: `{payload['prior_terminal_scope']}`",
        "",
        "The previous Council can falsify only the executed revision branch. The main agent must answer this questionnaire before any new executable synthesis.",
        "",
        "## Required Answers",
    ]
    lines.extend(f"- `{item}`" for item in answers)
    lines.extend(["", "## Falsified Revision Laws"])
    if laws:
        for law in laws:
            if isinstance(law, dict):
                lines.append(f"- `{law.get('law_id')}` {law.get('law_statement') or ''}".rstrip())
            else:
                lines.append(f"- {law}")
    else:
        lines.append("- none")
    lines.extend(["", "## Forbidden Formula Hashes"])
    lines.extend(f"- `{item}`" for item in hashes) if hashes else lines.append("- none")
    lines.extend(
        [
            "",
            "## Write Boundary",
            "- canonical_write_permission: false",
            "- execution_allowed_by_default: false",
            "- human_approval_required: true",
            "",
        ]
    )
    return "\n".join(lines)


def write_next_derivation_questionnaire(
    *,
    root: Path,
    report_id: str,
    branch_payload: dict[str, Any],
) -> tuple[Path, Path]:
    json_path, md_path = next_derivation_questionnaire_paths(root, report_id)
    payload = {
        "contract_version": "factorforge_next_derivation_questionnaire_v1",
        "created_at_utc": utc_now(),
        "report_id": report_id,
        "status": "awaiting_main_agent_next_derivation",
        "source_branch_falsification_path": str(branch_falsification_path(root, report_id)),
        "prior_terminal_scope": branch_payload.get("terminal_scope"),
        "prior_stop_authority": branch_payload.get("stop_authority"),
        "selected_agent_result_ids": branch_payload.get("selected_agent_result_ids") or [],
        "falsified_revision_laws": branch_payload.get("falsified_revision_laws") or [],
        "falsified_formula_hashes": branch_payload.get("falsified_formula_hashes") or [],
        "preserve_or_reject_economic_hypothesis_questions": [
            "Which part of the original economic hypothesis is still alive after this branch falsification?",
            "Which payoff, counterparty, horizon, or state-estimator assumption was specifically falsified?",
            "Does the next derivation preserve the broad economic source, mutate the mathematical model, or request terminal authority?",
        ],
        "required_main_agent_answers": [
            "falsified_model_components",
            "preserve_broad_economic_hypothesis",
            "next_distinct_math_mechanism",
            "model_mutation_from_prior_branch",
            "new_observable_estimator_mapping",
            "expected_metric_signature",
            "falsification_tests",
            "forbidden_repetition_acknowledgement",
            "terminal_authority_request_if_no_revision",
        ],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
    }
    write_json(json_path, payload)
    write_text(md_path, render_next_derivation_questionnaire(payload))
    return json_path, md_path


def write_branch_falsification_artifact(
    *,
    root: Path,
    report_id: str,
    summary_path: Path,
    collection_path: Path,
    results: list[dict[str, Any]],
    loop_index: int,
    max_loops: int,
) -> Path:
    path = branch_falsification_path(root, report_id)
    laws: list[dict[str, Any]] = []
    formula_hashes: list[str] = []
    for item in results:
        payload = item["payload"]
        for law in payload.get("candidate_revision_laws") or []:
            if isinstance(law, dict):
                laws.append({
                    "task_id": payload.get("task_id"),
                    "law_id": law.get("law_id"),
                    "revision_type": law.get("revision_type"),
                    "law_statement": law.get("law_statement"),
                })
                for key in ("formula_hash", "child_formula_hash", "falsified_formula_hash"):
                    if isinstance(law.get(key), str) and law[key] not in formula_hashes:
                        formula_hashes.append(law[key])
        guard = payload.get("repeated_revision_guard")
        if isinstance(guard, dict):
            for key in ("forbidden_formula_hashes", "forbidden_repeat_formula_hashes"):
                values = guard.get(key)
                if isinstance(values, list):
                    for value in values:
                        if isinstance(value, str) and value not in formula_hashes:
                            formula_hashes.append(value)
    artifact = {
        "branch_falsification_version": "factorforge_revision_branch_falsification_v1",
        "created_at_utc": utc_now(),
        "report_id": report_id,
        "summary_path": str(summary_path),
        "summary_sha256": sha256_file(summary_path),
        "collection_path": str(collection_path),
        "collection_sha256": sha256_file(collection_path),
        "loop_index": loop_index,
        "max_loops": max_loops,
        "terminal_scope": "revision_branch_only",
        "stop_authority": "advisory_only",
        "falsified_revision_laws": laws,
        "falsified_formula_hashes": formula_hashes,
        "selected_agent_result_ids": selected_ids(results),
        "next_required_action": "derive_distinct_math_mechanism",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
    }
    questionnaire_json, questionnaire_md = write_next_derivation_questionnaire(root=root, report_id=report_id, branch_payload=artifact)
    artifact["next_derivation_questionnaire_json_path"] = str(questionnaire_json)
    artifact["next_derivation_questionnaire_markdown_path"] = str(questionnaire_md)
    write_json(path, artifact)
    return path


def build_revision_council_ref(root: Path, report_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    valid_agent = summary.get("valid_agent_results") if isinstance(summary.get("valid_agent_results"), list) else []
    candidate = summary.get("candidate_proposals") if isinstance(summary.get("candidate_proposals"), list) else []
    blocked = summary.get("blocked_proposals") if isinstance(summary.get("blocked_proposals"), list) else []
    blocked_agent = summary.get("blocked_agent_results") if isinstance(summary.get("blocked_agent_results"), list) else []
    branches = summary.get("recommended_branch_templates") if isinstance(summary.get("recommended_branch_templates"), list) else []
    return {
        "enabled": True,
        "mode": "agentic",
        "status": "completed",
        "packet_path": str(council_dir(root, report_id) / f"revision_council_packet__{report_id}.json"),
        "summary_path": str(council_dir(root, report_id) / f"revision_council_summary__{report_id}.json"),
        "proposal_count": len(valid_agent) + len(candidate) + len(blocked) + len(blocked_agent),
        "valid_proposal_count": len(valid_agent) + len(candidate),
        "blocked_proposal_count": len(blocked) + len(blocked_agent),
        "recommended_branch_count": len(branches),
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
    }


def reject_reason(results: list[dict[str, Any]]) -> str:
    roles = [item["payload"].get("agent_role") for item in results if item["payload"].get("agent_role")]
    return (
        "Terminal agentic Council consensus rejected continuation after executed child evidence failed the research gates. "
        f"Participating roles: {', '.join(roles)}."
    )


def update_iteration_for_terminal_reject(
    *,
    root: Path,
    report_id: str,
    iteration: dict[str, Any],
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    artifact_path: Path,
) -> dict[str, Any]:
    updated = json.loads(json.dumps(iteration))
    reason = reject_reason(results)
    ids = selected_ids(results)
    updated["decision"] = "reject"
    updated["revision_council_ref"] = build_revision_council_ref(root, report_id, summary)
    research_judgment = updated.setdefault("research_judgment", {})
    research_judgment["decision"] = "reject"
    research_judgment["thesis"] = reason
    memo = research_judgment.setdefault("research_memo", {})
    revision_strategy = memo.setdefault("revision_strategy", {})
    revision_strategy.update(
        {
            "revision_needed": False,
            "primary_failure_signature": revision_strategy.get("primary_failure_signature") or "cost_too_high",
            "revision_quality": "not_needed",
            "loop_authorization": "advisory_only",
            "requires_human_approval_before_code_change": True,
            "revision_hypotheses": [],
            "reject_reason_if_no_revision": reason,
            "terminal_council_rejection_path": str(artifact_path),
        }
    )
    final_strategy = {
        "source": "revision_council",
        "revision_needed": False,
        "revision_quality": "not_needed",
        "loop_authorization": "advisory_only",
        "requires_human_approval_before_code_change": True,
        "approval_required_before_step3b": True,
        "selected_council_proposal_ids": ids,
        "reject_reason_if_no_revision": reason,
        "terminal_council_rejection_path": str(artifact_path),
    }
    memo["final_revision_strategy"] = final_strategy
    loop_action = updated.setdefault("loop_action", {})
    if isinstance(loop_action, dict):
        loop_action["should_modify_step3b"] = False
        loop_action["loop_authorization"] = "advisory_only"
        loop_action["stop_reason"] = "terminal_agentic_council_reject_consensus"
        loop_action["terminal_council_rejection_path"] = str(artifact_path)
    return updated


def update_loop_brief(root: Path, report_id: str, iteration: dict[str, Any], results: list[dict[str, Any]], artifact_path: Path) -> None:
    json_path, md_path = loop_brief_paths(root, iteration)
    ids = selected_ids(results)
    payload = {
        "enabled": True,
        "mode": "agentic",
        "status": "completed",
        "terminal_decision": "reject",
        "selected_proposals": ids,
        "why_no_automatic_step3b_handoff": "Terminal agentic Council consensus rejected continuation; no executable successor law is approved.",
        "human_approval_required": True,
        "terminal_council_rejection_path": str(artifact_path),
    }
    if json_path and json_path.exists():
        data = load_json(json_path)
        data.setdefault("decision_snapshot", {})
        if isinstance(data["decision_snapshot"], dict):
            data["decision_snapshot"]["decision"] = "reject"
            data["decision_snapshot"]["loop_authorization"] = "advisory_only"
        data["revision_council_summary"] = payload
        data.setdefault("final_loop_conclusion", {})
        if isinstance(data["final_loop_conclusion"], dict):
            data["final_loop_conclusion"]["current_conclusion"] = "Terminal agentic Council rejected continuation."
        write_json(json_path, data)
    if md_path and md_path.exists():
        text = md_path.read_text(encoding="utf-8")
        section = "\n".join(
            [
                "## Revision Council Summary",
                "",
                "- Status: completed",
                "- Terminal decision: reject",
                f"- Selected agent result ids: {', '.join(ids) if ids else 'none'}",
                "- Why no automatic Step3B handoff: Terminal agentic Council consensus rejected continuation; no executable successor law is approved.",
                "",
            ]
        )
        if "## Revision Council Summary" in text:
            text = text.split("## Revision Council Summary", 1)[0].rstrip() + "\n\n" + section
        else:
            text = text.rstrip() + "\n\n" + section
        md_path.write_text(text, encoding="utf-8")


def update_record_for_terminal_reject(
    record: dict[str, Any],
    *,
    updated_iteration: dict[str, Any],
    artifact_path: Path,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = json.loads(json.dumps(record))
    decision = "reject"
    reason = reject_reason(results)
    updated["decision"] = decision
    updated["terminal_council_rejection"] = {
        "terminal_rejection_version": TERMINAL_REJECTION_VERSION,
        "terminal_council_rejection_path": str(artifact_path),
        "selected_agent_result_ids": selected_ids(results),
        "reason": reason,
    }
    updated["decision_lineage"] = updated_iteration.get("decision_lineage") or updated.get("decision_lineage") or {}
    updated["knowledge_provenance"] = updated_iteration.get("knowledge_provenance") or updated.get("knowledge_provenance") or {}
    updated["research_memo"] = (updated_iteration.get("research_judgment") or {}).get("research_memo") or updated.get("research_memo")
    updated["learning_and_innovation"] = (updated_iteration.get("knowledge_writeback") or {}).get("learning_and_innovation", updated.get("learning_and_innovation"))
    updated["revision_taxonomy"] = (updated_iteration.get("knowledge_writeback") or {}).get("revision_taxonomy", updated.get("revision_taxonomy"))
    updated["program_search_policy"] = (updated_iteration.get("knowledge_writeback") or {}).get("program_search_policy", updated.get("program_search_policy"))
    updated["diversity_position"] = (updated_iteration.get("knowledge_writeback") or {}).get("diversity_position", updated.get("diversity_position"))
    chain = updated.get("experience_chain")
    if isinstance(chain, dict):
        attempt = chain.get("current_attempt")
        if isinstance(attempt, dict):
            attempt["decision"] = decision
            attempt["terminal_council_rejection_path"] = str(artifact_path)
            failures = attempt.setdefault("strongest_failure_signature", [])
            if isinstance(failures, list) and reason not in failures:
                failures.append(reason)
    updated["loop_action"] = updated_iteration.get("loop_action") or updated.get("loop_action") or {}
    updated["updated_at_utc"] = utc_now()
    return updated


def refresh_terminal_reject_library_records(
    *,
    root: Path,
    report_id: str,
    updated_iteration: dict[str, Any],
    results: list[dict[str, Any]],
    artifact_path: Path,
) -> list[Path]:
    refreshed: list[Path] = []
    for path in (factor_library_all_path(root, report_id), research_knowledge_path(root, report_id)):
        if not path.exists():
            continue
        record = load_json(path)
        write_json(
            path,
            update_record_for_terminal_reject(
                record,
                updated_iteration=updated_iteration,
                artifact_path=artifact_path,
                results=results,
            ),
        )
        refreshed.append(path)
    return refreshed


def run_validate_step6(root: Path, report_id: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(
        [sys.executable, "skills/factor-forge-step6/scripts/validate_step6.py", "--report-id", report_id],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    return {
        "command": [sys.executable, "skills/factor-forge-step6/scripts/validate_step6.py", "--report-id", report_id],
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Close a completed terminal agentic Council as a Step6 reject decision.")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--factorforge-root", default=None)
    parser.add_argument("--loop-index", type=int, default=None)
    parser.add_argument("--max-loops", type=int, default=10)
    parser.add_argument("--skip-validate-step6", action="store_true")
    args = parser.parse_args()

    ctx = resolve_factorforge_context(args.factorforge_root)
    root = ctx.factorforge_root
    rid = args.report_id
    cdir = council_dir(root, rid)
    summary_path = cdir / f"revision_council_summary__{rid}.json"
    collection_path = cdir / f"agentic_result_collection__{rid}.json"
    dispatch_path = cdir / f"dispatch_manifest__{rid}.json"
    iter_path = iteration_path(root, rid)
    out_handoff = handoff_path(root, rid)
    artifact_path = terminal_rejection_path(root, rid)
    if not summary_path.exists():
        block(TOKEN_SUMMARY_MISSING, {"report_id": rid, "summary_path": str(summary_path)})
    if not collection_path.exists():
        block(TOKEN_COLLECTION_MISSING, {"report_id": rid, "collection_path": str(collection_path)})
    if not dispatch_path.exists():
        block(
            TOKEN_COLLECTION_INVALID,
            {"report_id": rid, "reason": "dispatch_manifest_missing"},
        )
    if not iter_path.exists():
        block(TOKEN_ITERATION_MISSING, {"report_id": rid, "iteration_path": str(iter_path)})
    if out_handoff.exists():
        handoff = load_json(out_handoff)
        auth = handoff.get("loop_authorization") or handoff.get("authorization") or handoff.get("status")
        if auth == "approved_for_step3b_handoff":
            block(TOKEN_HANDOFF_EXISTS, {"report_id": rid, "handoff_path": str(out_handoff)})

    summary = load_json(summary_path)
    collection = load_json(collection_path)
    collection_reasons = validate_collection(rid, collection)
    dispatch = load_json(dispatch_path)
    required_tasks = [
        task
        for task in dispatch.get("agent_tasks") or []
        if isinstance(task, dict) and task.get("required") is True
    ]
    required_ids = [str(task.get("task_id") or "") for task in required_tasks]
    valid_results = collection.get("valid_results")
    valid_ids = [
        str(row.get("task_id") or "")
        for row in valid_results or []
        if isinstance(row, dict)
    ]
    if (
        dispatch.get("dispatch_manifest_version")
        != "factorforge_agentic_council_dispatch_manifest_v1"
        or dispatch.get("report_id") != rid
        or not required_ids
        or any(not task_id for task_id in required_ids)
        or len(set(required_ids)) != len(required_ids)
        or not isinstance(valid_results, list)
        or set(valid_ids) != set(required_ids)
        or len(valid_ids) != len(required_ids)
        or collection.get("required_result_count") != len(required_ids)
        or collection.get("present_result_count") != len(required_ids)
        or collection.get("valid_result_count") != len(required_ids)
    ):
        collection_reasons.append(
            "BLOCK_AGENTIC_COUNCIL_COLLECTION_DISPATCH_SET_MISMATCH"
        )
    required_paths = {
        str(task.get("task_id")): resolve_under_root(
            root,
            task.get("expected_result_path"),
        )
        for task in required_tasks
    }
    for row in valid_results or []:
        if not isinstance(row, dict):
            continue
        task_id = str(row.get("task_id") or "")
        if required_paths.get(task_id) != resolve_under_root(
            root,
            row.get("result_path"),
        ):
            collection_reasons.append(
                "BLOCK_AGENTIC_COUNCIL_COLLECTION_DISPATCH_PATH_MISMATCH"
            )
    if collection_reasons:
        block(TOKEN_COLLECTION_INVALID, {"collection_path": str(collection_path), "block_reasons": collection_reasons})
    results, non_terminal = load_valid_terminal_results(root, collection)
    if non_terminal or not results:
        block(TOKEN_NOT_UNANIMOUS, {"non_terminal_results": non_terminal, "terminal_count": len(results)})

    iteration = load_json(iter_path)
    loop_index = int(args.loop_index or iteration.get("loop_index") or iteration.get("iteration_no") or 1)
    max_loops = int(args.max_loops or 10)
    if not terminal_reject_authorized(results, loop_index=loop_index, max_loops=max_loops):
        branch_path = write_branch_falsification_artifact(
            root=root,
            report_id=rid,
            summary_path=summary_path,
            collection_path=collection_path,
            results=results,
            loop_index=loop_index,
            max_loops=max_loops,
        )
        block(
            TOKEN_PREMATURE_TERMINAL_REJECT,
            {
                "report_id": rid,
                "loop_index": loop_index,
                "max_loops": max_loops,
                "branch_falsification_path": str(branch_path),
                "required_next_action": "derive_distinct_math_mechanism",
            },
        )
    proof_path = factor_proof_certificate_path(root, rid)
    if not proof_path.is_file() or proof_path.is_symlink():
        block(
            TOKEN_FACTOR_PROOF_NOT_REJECTED,
            {"report_id": rid, "factor_proof_path": str(proof_path)},
        )
    factor_proof = load_json(proof_path)
    factor_proof_report = validate_factor_proof_certificate(
        factor_proof,
        workspace_root=root,
        expected_report_id=rid,
    )
    if (
        factor_proof_report.get("verdict") != "REJECT"
        or factor_proof_report.get("block_reasons")
    ):
        block(
            TOKEN_FACTOR_PROOF_NOT_REJECTED,
            {
                "report_id": rid,
                "factor_proof_path": str(proof_path),
                "factor_proof_verdict": factor_proof_report.get("verdict"),
                "block_reasons": factor_proof_report.get("block_reasons") or [],
            },
        )
    brief_json_path, brief_md_path = loop_brief_paths(root, iteration)
    rollback = {
        "iteration": read_text_if_exists(iter_path),
        "handoff": read_text_if_exists(out_handoff),
        "brief_json": read_text_if_exists(brief_json_path),
        "brief_md": read_text_if_exists(brief_md_path),
        "artifact": read_text_if_exists(artifact_path),
        "factor_library_all": read_text_if_exists(factor_library_all_path(root, rid)),
        "research_knowledge_base": read_text_if_exists(research_knowledge_path(root, rid)),
    }
    artifact = {
        "terminal_rejection_version": TERMINAL_REJECTION_VERSION,
        "created_at_utc": utc_now(),
        "report_id": rid,
        "summary_path": str(summary_path),
        "summary_sha256": sha256_file(summary_path),
        "collection_path": str(collection_path),
        "collection_sha256": sha256_file(collection_path),
        "dispatch_manifest_path": str(dispatch_path),
        "dispatch_manifest_sha256": sha256_file(dispatch_path),
        "factor_proof_path": str(proof_path),
        "factor_proof_sha256": sha256_file(proof_path),
        "factor_proof_verdict": "REJECT",
        "iteration_decision": "reject",
        "selected_agent_result_ids": selected_ids(results),
        "agent_result_paths": [item["path"] for item in results],
        "agent_result_bindings": [
            {
                "task_id": item["payload"].get("task_id"),
                "result_path": item["path"],
                "result_sha256": sha256_file(Path(item["path"])),
                "recommendation": terminal_recommendation_value(item["payload"]),
            }
            for item in results
        ],
        "terminal_recommendations": [
            {
                "task_id": item["payload"].get("task_id"),
                "agent_role": item["payload"].get("agent_role"),
                "recommendation": (item["payload"].get("revision_or_kill_recommendation") or {}).get("recommendation"),
                "prior_revision_outcome_review_present": item["prior_review_present"],
            }
            for item in results
        ],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
    }
    write_json(artifact_path, artifact)
    updated = update_iteration_for_terminal_reject(
        root=root,
        report_id=rid,
        iteration=iteration,
        summary=summary,
        results=results,
        artifact_path=artifact_path,
    )
    write_json(iter_path, updated)
    if out_handoff.exists():
        out_handoff.unlink()
    update_loop_brief(root, rid, updated, results, artifact_path)
    refreshed_records = refresh_terminal_reject_library_records(
        root=root,
        report_id=rid,
        updated_iteration=updated,
        results=results,
        artifact_path=artifact_path,
    )
    artifact["refreshed_terminal_reject_records"] = [str(path) for path in refreshed_records]

    validate_result: dict[str, Any] | None = None
    if not args.skip_validate_step6:
        validate_result = run_validate_step6(root, rid)
        artifact["validate_step6"] = validate_result
        if validate_result["rc"] != 0:
            restore_text_snapshot(iter_path, rollback["iteration"])
            restore_text_snapshot(out_handoff, rollback["handoff"])
            restore_text_snapshot(brief_json_path, rollback["brief_json"])
            restore_text_snapshot(brief_md_path, rollback["brief_md"])
            restore_text_snapshot(artifact_path, rollback["artifact"])
            restore_text_snapshot(factor_library_all_path(root, rid), rollback["factor_library_all"])
            restore_text_snapshot(research_knowledge_path(root, rid), rollback["research_knowledge_base"])
            artifact["rolled_back_active_writes"] = True
            write_json(artifact_path, artifact)
            block(TOKEN_VALIDATION_FAILED, {"report_id": rid, "validate_step6": validate_result})
    if validate_result:
        write_json(artifact_path, artifact)
    print(json.dumps({"result": "PASS", "terminal_rejection": artifact}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
