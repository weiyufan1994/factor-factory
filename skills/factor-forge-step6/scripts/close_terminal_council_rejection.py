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
from validate_agentic_council_collection import validate_collection
from validate_agentic_council_result import validate_agentic_result

TERMINAL_REJECTION_VERSION = "factorforge_terminal_council_rejection_v1"
TOKEN_SUMMARY_MISSING = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_SUMMARY_MISSING"
TOKEN_COLLECTION_MISSING = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_COLLECTION_MISSING"
TOKEN_COLLECTION_INVALID = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_COLLECTION_INVALID"
TOKEN_RESULTS_INVALID = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_RESULTS_INVALID"
TOKEN_NOT_UNANIMOUS = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_NOT_UNANIMOUS"
TOKEN_ITERATION_MISSING = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_ITERATION_MISSING"
TOKEN_VALIDATION_FAILED = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_VALIDATION_FAILED"
TOKEN_HANDOFF_EXISTS = "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_APPROVED_HANDOFF_EXISTS"

TERMINAL_RECOMMENDATION_TERMS = {
    "reject",
    "kill",
    "stop",
    "terminal",
    "no_revision",
    "no successor",
    "do not continue",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
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


def handoff_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"


def terminal_rejection_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"terminal_council_rejection__{report_id}.json"


def resolve_under_root(root: Path, raw: Any) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else root / path


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


def terminal_recommendation_text(result: dict[str, Any]) -> str:
    rec = result.get("revision_or_kill_recommendation")
    pieces: list[str] = []
    if isinstance(rec, dict):
        for key in ("recommendation", "reason", "decision", "summary"):
            if isinstance(rec.get(key), str):
                pieces.append(rec[key])
    if isinstance(result.get("candidate_revision_laws"), list):
        for law in result["candidate_revision_laws"]:
            if isinstance(law, dict):
                for key in ("revision_type", "law_statement", "expression_change_direction"):
                    if isinstance(law.get(key), str):
                        pieces.append(law[key])
    return " ".join(pieces).lower()


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
        reasons = validate_agentic_result(payload)
        if reasons:
            invalid.append({"result_path": str(path), "block_reasons": reasons})
            continue
        text = terminal_recommendation_text(payload)
        is_terminal = any(term in text for term in TERMINAL_RECOMMENDATION_TERMS)
        if not is_terminal:
            non_terminal.append({"result_path": str(path), "task_id": payload.get("task_id"), "recommendation_text": text[:240]})
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
    parser.add_argument("--skip-validate-step6", action="store_true")
    args = parser.parse_args()

    ctx = resolve_factorforge_context(args.factorforge_root)
    root = ctx.factorforge_root
    rid = args.report_id
    cdir = council_dir(root, rid)
    summary_path = cdir / f"revision_council_summary__{rid}.json"
    collection_path = cdir / f"agentic_result_collection__{rid}.json"
    iter_path = iteration_path(root, rid)
    out_handoff = handoff_path(root, rid)
    artifact_path = terminal_rejection_path(root, rid)
    if not summary_path.exists():
        block(TOKEN_SUMMARY_MISSING, {"report_id": rid, "summary_path": str(summary_path)})
    if not collection_path.exists():
        block(TOKEN_COLLECTION_MISSING, {"report_id": rid, "collection_path": str(collection_path)})
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
    if collection_reasons:
        block(TOKEN_COLLECTION_INVALID, {"collection_path": str(collection_path), "block_reasons": collection_reasons})
    results, non_terminal = load_valid_terminal_results(root, collection)
    if non_terminal or not results:
        block(TOKEN_NOT_UNANIMOUS, {"non_terminal_results": non_terminal, "terminal_count": len(results)})

    iteration = load_json(iter_path)
    brief_json_path, brief_md_path = loop_brief_paths(root, iteration)
    rollback = {
        "iteration": read_text_if_exists(iter_path),
        "handoff": read_text_if_exists(out_handoff),
        "brief_json": read_text_if_exists(brief_json_path),
        "brief_md": read_text_if_exists(brief_md_path),
        "artifact": read_text_if_exists(artifact_path),
    }
    artifact = {
        "terminal_rejection_version": TERMINAL_REJECTION_VERSION,
        "created_at_utc": utc_now(),
        "report_id": rid,
        "summary_path": str(summary_path),
        "summary_sha256": sha256_file(summary_path),
        "collection_path": str(collection_path),
        "collection_sha256": sha256_file(collection_path),
        "selected_agent_result_ids": selected_ids(results),
        "agent_result_paths": [item["path"] for item in results],
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
            artifact["rolled_back_active_writes"] = True
            write_json(artifact_path, artifact)
            block(TOKEN_VALIDATION_FAILED, {"report_id": rid, "validate_step6": validate_result})
    if validate_result:
        write_json(artifact_path, artifact)
    print(json.dumps({"result": "PASS", "terminal_rejection": artifact}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
