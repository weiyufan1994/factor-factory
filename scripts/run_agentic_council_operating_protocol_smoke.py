#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
REPORT_ALPHA013_LIKE = "STEP6_INTEL_ALPHA013_LIKE_ADVISORY_MECHANISM_CHALLENGE_BRANCH"
REPORT_MECHANISM_UNCLEAR = "STEP6_INTEL_MECHANISM_UNCLEAR_REVISION"
REPORT_COLD_START = "STEP6_INTEL_COLD_START_KNOWLEDGE_GAP"
REPORT_IDS = [REPORT_ALPHA013_LIKE, REPORT_MECHANISM_UNCLEAR, REPORT_COLD_START]
POLLUTION_MARKERS = ["factorforge_agentic_council_operating_protocol", "STEP6_INTEL"]


def is_tmp(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve())
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if root.exists():
            files.update(str(item.relative_to(REPO_ROOT)) for item in root.rglob("*") if item.is_file())
    return files


def pollution_matches(new_files: set[str]) -> list[str]:
    needles = sorted(set(REPORT_IDS + POLLUTION_MARKERS))
    return sorted(item for item in new_files if any(needle in item for needle in needles))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def run_cmd(root: Path, cmd: list[str]) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {"command": cmd, "rc": proc.returncode, "stdout_tail": proc.stdout[-16000:], "stderr_tail": proc.stderr[-16000:]}


def result(case: str, ok: bool, expected: str, actual: dict[str, Any]) -> dict[str, Any]:
    return {"case": case, "ok": bool(ok), "expected": expected, "actual": actual}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip_digest_path(path: Path) -> bool:
    name = path.name
    return name in {"__pycache__", ".DS_Store"} or name.endswith((".lock", ".tmp", ".swp", ".swx"))


def directory_digest(path: Path) -> str | None:
    if not path.exists() or not path.is_dir():
        return None
    entries: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        rel = item.relative_to(path)
        if any(should_skip_digest_path(part) for part in rel.parents):
            continue
        if should_skip_digest_path(item) or not item.is_file():
            continue
        stat = item.stat()
        entries.append({"relative_path": rel.as_posix(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(item)})
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def setup_fixtures(root: Path) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "scripts/run_step6_intelligence_smoke.py", "--fresh", "--root", str(root)])


def council_dir(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / rid


def dispatch_manifest_path(root: Path, rid: str) -> Path:
    return council_dir(root, rid) / f"dispatch_manifest__{rid}.json"


def collection_path(root: Path, rid: str) -> Path:
    return council_dir(root, rid) / f"agentic_result_collection__{rid}.json"


def clean_results(root: Path, rid: str) -> None:
    result_dir = council_dir(root, rid) / "agent_results"
    if result_dir.exists():
        shutil.rmtree(result_dir)
    coll = collection_path(root, rid)
    if coll.exists():
        coll.unlink()


def build_dispatch(root: Path, rid: str) -> list[dict[str, Any]]:
    return [
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid]),
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py", "--report-id", rid, "--executor", "dispatch_manifest", "--research-protocol", "off"]),
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py", "--report-id", rid]),
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py", "--report-id", rid]),
    ]


def manifest_tasks(root: Path, rid: str) -> list[dict[str, Any]]:
    return load_json(dispatch_manifest_path(root, rid)).get("agent_tasks") or []


def fake_real_agent_result(root: Path, rid: str, task: dict[str, Any], valid: bool = True) -> dict[str, Any]:
    packet = load_json(root / task["task_packet_path"])
    task_id = task["task_id"]
    proof_obligation_ids = [
        str(item)
        for item in packet.get("proof_obligation_ids") or []
        if isinstance(item, str) and item
    ]
    payload = {
        "result_version": "factorforge_agentic_revision_council_result_v1",
        "status": "final",
        "report_id": rid,
        "task_id": task_id,
        "agent_role": task["agent_role"],
        "producer": "real_agent",
        "agent_identifier": task.get("expected_agent_identifier") or f"agent_test_{task_id}",
        "research_depth": "medium",
        "proposal_generation_mode": "agentic",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "approach_route": {
            "route_id": task.get("route_id"),
            "route_family": task.get("route_family"),
            "core_hypothesis": "The assigned route may explain a distinct part of the factor mechanism.",
            "distinct_from_other_routes": "This result uses only the assigned route and its visible task packet.",
            "exact_gap_after_analysis": "The route remains inconclusive until empirical evidence is attached.",
        },
        "dispatch_identity": {
            "source_task_packet_sha256": task.get("task_packet_sha256"),
            "route_fingerprint": task.get("route_fingerprint"),
            "blind_context_hash": task.get("blind_context_hash"),
        },
        "proof_obligation_updates": [
            {
                "obligation_id": obligation_id,
                "status": "open",
                "finding": "The obligation remains open in this operating-protocol smoke.",
                "evidence_refs": [],
            }
            for obligation_id in proof_obligation_ids
        ],
        "counterexamples": [
            {
                "attack_type": "null_mechanism",
                "construction_or_scenario": "The observed metric pattern is noise rather than the assigned mechanism.",
                "predicted_failure": "The effect disappears out of sample or after costs.",
                "discriminating_test": "Run preregistered OOS and after-cost checks before support is claimed.",
            }
        ],
        "route_status": "inconclusive",
        "reopen_criteria": [],
        "independence_attestation": {
            "favored_thesis_seen_before_submission": False,
            "derived_from_visible_facts_only": True,
        },
        "economic_hypothesis_review": {
            "preserve_broad_direction": True,
            "refined_second_layer_mechanism": "The packet mechanism is reviewed as a testable estimator-state hypothesis.",
            "payer_or_counterparty_update": "Potential counterparties are inferred only from packet evidence and must be falsified by metrics.",
            "what_step4_metrics_changed_in_the_hypothesis": "Net evidence and turnover decide whether the estimator state deserves revision.",
        },
        "math_mechanism_derivation": {
            "selected_tool": "statistical_inference",
            "selected_tool_rationale": "It links public estimator claims to metric signatures without approving writeback.",
            "rejected_tools": [{"tool": "expression_wrapper_repair", "reason": "The task is expression-level research only."}],
            "baseline_model": "E[next evidence | estimator state]",
            "model_mutation": "challenge persistence and falsification requirements at expression level",
            "mathematical_objects": ["agent_state", "next_evidence"],
            "derivation_steps": ["Read packet evidence.", "Map evidence to a public estimator-state claim."],
            "derived_state_variables": ["agent_state"],
            "observable_estimators": ["factor score", "net long-side evidence"],
            "expected_metric_signature": ["Net evidence should improve if the state is valid.", "Turnover should not worsen materially."],
            "falsification_tests": ["Net long-side Sharpe remains negative.", "Gross signal disappears under expression discipline."],
        },
        "model_to_formula_translation": {
            "candidate_formula": "rank(close)",
            "operator_support_status": "parseable",
            "mapping_from_model_terms_to_formula_components": ["agent_state -> rank(close) smoke placeholder"],
            "information_set_legality": "legal",
        },
        "public_derivation_record": {
            "research_question": packet.get("research_question"),
            "assumptions": [{"assumption": "Step6 packet evidence is fixed.", "status": "hypothesis", "why_needed": "No rerun is allowed.", "how_to_falsify": "Block if packet provenance is invalid."}],
            "mathematical_objects": [{"name": "agent_state", "meaning": "Agent-specific estimator state.", "unit_or_dimension": "dimensionless", "information_set": "factor timestamp evidence only"}],
            "selected_tools": [{"tool": "statistical_inference", "why_selected": "It links claims to metric signatures.", "what_it_can_answer": "Whether the hypothesis is testable.", "what_it_cannot_answer": "It cannot approve canonical writes."}],
            "formula_claims": [{"claim": "The expression can be tested as an estimator state.", "formula_or_relation": "E[next_evidence | agent_state]", "status": "hypothesis", "derivation_summary": "Public derivation summary for operating protocol smoke."}],
            "derivation_steps_summary": [{"step_no": 1, "statement": "Map packet evidence to a public estimator-state claim.", "depends_on": []}],
            "limiting_cases": [
                {"polarity": "positive", "case": "If the estimator state is valid, net long-side evidence improves without materially higher turnover."},
                {"polarity": "negative", "case": "If net evidence remains negative or gross evidence disappears, the estimator-state claim is falsified."},
            ],
            "falsification_tests": ["Net long-side Sharpe remains negative.", "Gross signal disappears under expression discipline."],
            "kill_criteria": ["High-score long side remains non-positive.", "Only diagnostic spread metrics improve."],
            "overclaim_guard": "This result is advisory-only and cannot authorize code writes.",
        },
        "candidate_revision_laws": [
            {
                "law_id": f"{task_id}_real_law_001",
                "revision_kind": "estimator_repair",
                "revision_type": "mechanism_challenge",
                "law_statement": "Test the estimator-state mechanism before any revision approval.",
                "expression_change_direction": "Challenge persistence, scale, and falsification requirements at expression level.",
                "expected_metric_change": ["Net long-side evidence should improve if the state is valid.", "Turnover or estimator variance should not worsen materially."],
                "falsification_tests": ["Net long-side Sharpe remains negative.", "Gross signal disappears under the expression hypothesis."],
                "kill_criteria": ["High-score long side remains non-positive.", "Only diagnostic spread metrics improve."],
                "why_not_portfolio_fix": "This is an expression and mechanism test, not a trading wrapper change.",
            }
        ],
        "recommended_branch_templates": [],
        "blocked_reason": None,
    }
    if not valid:
        payload["public_derivation_record"].pop("overclaim_guard", None)
    return payload


def write_results(root: Path, rid: str, count: int, valid: bool = True) -> None:
    for task in manifest_tasks(root, rid)[:count]:
        write_json(root / task["expected_result_path"], fake_real_agent_result(root, rid, task, valid=valid))


def collect(root: Path, rid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/collect_agentic_council_results.py", "--report-id", rid])
    return proc, load_json(collection_path(root, rid))


def validate_collection(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_collection.py", "--report-id", rid])


def case_print_assignment(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    task_id = manifest_tasks(root, rid)[0]["task_id"]
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/print_agentic_council_assignment.py", "--report-id", rid, "--task-id", task_id])
    text = proc["stdout_tail"] + proc["stderr_tail"]
    required_fragments = [
        "Task packet path",
        "Expected result path",
        "Canonical write prohibition",
        "public derivation record",
        "economic_hypothesis_review",
        "math_mechanism_derivation",
        "model_to_formula_translation",
        "terminal_scope_and_stop_authority_if_recommending_stop",
    ]
    missing = [item for item in required_fragments if item.lower() not in text.lower()]
    ok = proc["rc"] == 0 and not missing
    return result("print_assignment", ok, "assignment text contains paths, write prohibition, public derivation requirement, and derivation-engine fields", {"run": proc, "missing": missing})


def case_write_draft_template(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    clean_results(root, rid)
    task_id = manifest_tasks(root, rid)[0]["task_id"]
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/write_agentic_council_result_template.py", "--report-id", rid, "--task-id", task_id])
    path = root / manifest_tasks(root, rid)[0]["expected_result_path"]
    validate = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid, "--result-path", str(path)])
    token = "BLOCK_REVISION_COUNCIL_AGENTIC_RESULT_NOT_FINAL"
    payload = load_json(path)
    ok = proc["rc"] == 0 and payload.get("status") == "draft" and validate["rc"] == 1 and token in (validate["stdout_tail"] + validate["stderr_tail"])
    clean_results(root, rid)
    return result("write_draft_template", ok, token, {"template": proc, "validate": validate, "path": str(path), "status": payload.get("status")})


def case_collect_all_missing(root: Path) -> dict[str, Any]:
    rid = REPORT_MECHANISM_UNCLEAR
    clean_results(root, rid)
    proc, report = collect(root, rid)
    validate = validate_collection(root, rid)
    ok = proc["rc"] == 0 and report.get("missing_result_count") == 5 and report.get("ready_for_finalize") is False and validate["rc"] == 1
    return result("collect_all_missing", ok, "missing=5 and collection validation BLOCK", {"collect": proc, "collection": report, "validate": validate})


def case_collect_partial(root: Path) -> dict[str, Any]:
    rid = REPORT_COLD_START
    clean_results(root, rid)
    write_results(root, rid, 3, valid=True)
    proc, report = collect(root, rid)
    validate = validate_collection(root, rid)
    ok = proc["rc"] == 0 and report.get("present_result_count") == 3 and report.get("missing_result_count") == 2 and report.get("ready_for_finalize") is False and validate["rc"] == 1
    return result("collect_partial", ok, "present=3 missing=2 validation BLOCK", {"collect": proc, "collection": report, "validate": validate})


def case_collect_invalid(root: Path) -> dict[str, Any]:
    rid = REPORT_MECHANISM_UNCLEAR
    clean_results(root, rid)
    write_results(root, rid, 1, valid=False)
    proc, report = collect(root, rid)
    validate = validate_collection(root, rid)
    ok = proc["rc"] == 0 and report.get("invalid_result_count") == 1 and validate["rc"] == 1
    return result("collect_invalid_result", ok, "invalid_result_count=1 validation BLOCK", {"collect": proc, "collection": report, "validate": validate})


def case_collect_complete_valid(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    clean_results(root, rid)
    write_results(root, rid, 5, valid=True)
    proc, report = collect(root, rid)
    validate = validate_collection(root, rid)
    ok = proc["rc"] == 0 and report.get("status") == "complete" and report.get("valid_result_count") == 5 and report.get("ready_for_finalize") is True and validate["rc"] == 0
    return result("collect_complete_valid", ok, "complete valid collection PASS", {"collect": proc, "collection": report, "validate": validate})


def case_collection_permission_mutation(root: Path, case_name: str, field: str, token: str) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    clean_results(root, rid)
    write_results(root, rid, 5, valid=True)
    collect_proc, report = collect(root, rid)
    path = collection_path(root, rid)
    report[field] = True
    write_json(path, report)
    validate = validate_collection(root, rid)
    text = validate["stdout_tail"] + validate["stderr_tail"]
    ok = collect_proc["rc"] == 0 and validate["rc"] == 1 and token in text
    return result(case_name, ok, token, {"collect": collect_proc, "validate": validate, "token_present": token in text})


def case_finalize_requires_collection(root: Path) -> dict[str, Any]:
    rid = REPORT_COLD_START
    clean_results(root, rid)
    write_results(root, rid, 5, valid=True)
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/finalize_agentic_council_dispatch.py", "--report-id", rid])
    token = "BLOCK_AGENTIC_COUNCIL_COLLECTION_MISSING"
    ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"])
    return result("finalize_requires_collection", ok, token, {"finalize": proc})


def case_finalize_complete_valid(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    clean_results(root, rid)
    write_results(root, rid, 5, valid=True)
    collect_proc, collection = collect(root, rid)
    before_code = directory_digest(root / "generated_code" / rid)
    before_clean = directory_digest(root / "data" / "clean")
    finalize = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/finalize_agentic_council_dispatch.py", "--report-id", rid])
    after_code = directory_digest(root / "generated_code" / rid)
    after_clean = directory_digest(root / "data" / "clean")
    iteration = load_json(root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json")
    final = (((iteration.get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})
    selected_ids = final.get("selected_council_proposal_ids") or []
    expected_selected_ids = {
        str(task.get("task_id"))
        for task in manifest_tasks(root, rid)
        if isinstance(task, dict) and task.get("task_id")
    }
    ok = (
        collect_proc["rc"] == 0
        and collection.get("ready_for_finalize") is True
        and finalize["rc"] == 0
        and final.get("source") == "revision_council"
        and set(selected_ids) == expected_selected_ids
        and not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists()
        and not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists()
        and before_code == after_code
        and before_clean == after_clean
    )
    return result("finalize_complete_valid", ok, "complete collection finalizes advisory council result", {"collect": collect_proc, "finalize": finalize, "selected_ids": selected_ids, "generated_code_unchanged": before_code == after_code, "data_clean_unchanged": before_clean == after_clean})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_agentic_council_operating_protocol_{int(time.time())}")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not is_tmp(root):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT")
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = file_snapshot()
    cases: list[dict[str, Any]] = []
    fixture = setup_fixtures(root)
    cases.append(result("step6_intelligence_fixture", fixture["rc"] == 0, "fixture setup", {"fixture": fixture}))
    if fixture["rc"] == 0:
        for rid in REPORT_IDS:
            cases.append(result(f"dispatch_setup_{rid}", all(item["rc"] == 0 for item in build_dispatch(root, rid)), "dispatch setup", {}))
        if all(item["ok"] for item in cases):
            cases.extend(
                [
                    case_print_assignment(root),
                    case_write_draft_template(root),
                    case_collect_all_missing(root),
                    case_collect_partial(root),
                    case_collect_invalid(root),
                    case_collect_complete_valid(root),
                    case_collection_permission_mutation(
                        root,
                        "collection_canonical_write_permission_block",
                        "canonical_write_permission",
                        "BLOCK_AGENTIC_COUNCIL_COLLECTION_CANONICAL_WRITE_PERMISSION",
                    ),
                    case_collection_permission_mutation(
                        root,
                        "collection_execution_allowed_by_default_block",
                        "execution_allowed_by_default",
                        "BLOCK_AGENTIC_COUNCIL_COLLECTION_EXECUTION_ALLOWED_BY_DEFAULT",
                    ),
                    case_finalize_requires_collection(root),
                    case_finalize_complete_valid(root),
                ]
            )
    after = file_snapshot()
    polluted = pollution_matches(after - before)
    summary = {
        "verdict": "ACCEPT" if all(item["ok"] for item in cases) and not polluted else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(polluted), "new_files": polluted},
        "notes": [
            "Synthetic /tmp-only agentic Council operating protocol smoke.",
            "No real external subagents, search workers, clean-data processing, Step3B handoff, or official promotion.",
        ],
    }
    out = root / "agentic_council_operating_protocol_smoke_summary.json"
    write_json(out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {out}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
