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
REPORT_MANUAL_DISPATCH = "STEP6_INTEL_LONG_SIDE_NEGATIVE_REVISION"
REPORT_IDS = [REPORT_MANUAL_DISPATCH]
POLLUTION_MARKERS = ["factorforge_agentic_council_manual_dispatch", "STEP6_INTEL"]


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
    return {"command": cmd, "rc": proc.returncode, "stdout_tail": proc.stdout[-5000:], "stderr_tail": proc.stderr[-5000:]}


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


def proof_path(root: Path, rid: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_run_report__{rid}.json"


def manual_manifest_path(root: Path, rid: str) -> Path:
    return council_dir(root, rid) / "manual_dispatch" / f"manual_dispatch_manifest__{rid}.json"


def dispatch_manifest_path(root: Path, rid: str) -> Path:
    return council_dir(root, rid) / f"dispatch_manifest__{rid}.json"


def dispatch_status_path(root: Path, rid: str) -> Path:
    return council_dir(root, rid) / f"agentic_dispatch_status__{rid}.json"


def collection_path(root: Path, rid: str) -> Path:
    return council_dir(root, rid) / f"agentic_result_collection__{rid}.json"


def run_ultimate_manual(root: Path, rid: str, *, runtime: str | None = None, provider: str | None = None, model: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    cmd = [
            sys.executable,
            "scripts/run_factorforge_ultimate.py",
            "--report-id",
            rid,
            "--start-step",
            "6",
            "--end-step",
            "6",
            "--skip-researcher-packets",
            "--factorforge-root",
            str(root),
            "--council-mode",
            "agentic",
            "--agentic-council-executor",
            "dispatch_manifest",
            "--agentic-dispatch-adapter",
            "manual_file",
    ]
    if runtime:
        cmd.extend(["--runtime-dispatch", runtime])
    if provider:
        cmd.extend(["--subagent-provider", provider])
    if model:
        cmd.extend(["--subagent-model", model])
    proc = run_cmd(root, cmd)
    return proc, load_json(proof_path(root, rid))


def validate_manual(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_manual_dispatch.py", "--report-id", rid])


def import_manual(root: Path, rid: str, *extra: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/import_agentic_council_manual_results.py", "--report-id", rid, *extra])


def update_status(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/update_agentic_council_dispatch_status.py", "--report-id", rid])


def collect(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/collect_agentic_council_results.py", "--report-id", rid])


def validate_collection(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_collection.py", "--report-id", rid])


def finalize(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/finalize_agentic_council_dispatch.py", "--report-id", rid])


def manifest_assignments(root: Path, rid: str) -> list[dict[str, Any]]:
    return load_json(manual_manifest_path(root, rid)).get("assignments") or []


def clean_results(root: Path, rid: str) -> None:
    result_dir = council_dir(root, rid) / "agent_results"
    if result_dir.exists():
        shutil.rmtree(result_dir)
    for path in [
        collection_path(root, rid),
        dispatch_status_path(root, rid),
        council_dir(root, rid) / f"revision_council_summary__{rid}.json",
    ]:
        if path.exists():
            path.unlink()


def fake_result(root: Path, rid: str, assignment: dict[str, Any], *, valid: bool = True, suffix: str = "") -> dict[str, Any]:
    task_id = assignment["task_id"]
    role = assignment["agent_role"]
    payload = {
        "result_version": "factorforge_agentic_revision_council_result_v1",
        "status": "final",
        "report_id": rid,
        "task_id": task_id,
        "agent_role": role,
        "producer": "real_agent",
        "agent_identifier": f"manual_agent_{role}{suffix}",
        "research_depth": "medium",
        "proposal_generation_mode": "agentic",
        "expected_result_path": assignment.get("expected_result_path"),
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "economic_hypothesis_review": {
            "preserve_broad_direction": True,
            "refined_second_layer_mechanism": "The manual result reviews the packet mechanism as a testable estimator-state hypothesis.",
            "payer_or_counterparty_update": "Potential counterparties are inferred from packet evidence and remain metric-falsifiable.",
            "what_step4_metrics_changed_in_the_hypothesis": "Net evidence and turnover determine whether the estimator state warrants revision.",
        },
        "math_mechanism_derivation": {
            "selected_tool": "statistical_inference",
            "selected_tool_rationale": "It links public claims to metric signatures without approving canonical writes.",
            "rejected_tools": [{"tool": "expression_wrapper_repair", "reason": "The manual assignment is expression-level research only."}],
            "baseline_model": "E[next evidence | manual agent state]",
            "model_mutation": "challenge persistence and falsification requirements at expression level",
            "mathematical_objects": ["manual_agent_state", "next_evidence"],
            "derivation_steps": ["Read manual assignment evidence.", "Map evidence to a public estimator-state claim."],
            "derived_state_variables": ["manual_agent_state"],
            "observable_estimators": ["factor score", "net long-side evidence"],
            "expected_metric_signature": ["Net evidence should improve if the state is valid.", "Turnover should not worsen materially."],
            "falsification_tests": ["Net long-side Sharpe remains negative.", "Gross signal disappears under expression discipline."],
        },
        "model_to_formula_translation": {
            "candidate_formula": "rank(close)",
            "operator_support_status": "parseable",
            "mapping_from_model_terms_to_formula_components": ["manual_agent_state -> rank(close) smoke placeholder"],
            "information_set_legality": "legal",
        },
        "public_derivation_record": {
            "research_question": "Manual dispatch smoke public research question.",
            "assumptions": [{"assumption": "Step6 packet evidence is fixed.", "status": "hypothesis", "why_needed": "No rerun is allowed.", "how_to_falsify": "Block if packet provenance is invalid."}],
            "mathematical_objects": [{"name": "manual_agent_state", "meaning": "Agent-specific estimator state.", "unit_or_dimension": "dimensionless", "information_set": "factor timestamp evidence only"}],
            "selected_tools": [{"tool": "statistical_inference", "why_selected": "It links claims to metric signatures.", "what_it_can_answer": "Whether the hypothesis is testable.", "what_it_cannot_answer": "It cannot approve canonical writes."}],
            "formula_claims": [{"claim": "The expression can be tested as an estimator state.", "formula_or_relation": "E[next_evidence | manual_agent_state]", "status": "hypothesis", "derivation_summary": "Public derivation summary for manual dispatch smoke."}],
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
                "law_id": f"{task_id}_manual_law_001{suffix}",
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


def write_dropbox(root: Path, assignment: dict[str, Any], payload: dict[str, Any]) -> None:
    write_json(root / assignment["result_dropbox_path"], payload)


def write_expected(root: Path, assignment: dict[str, Any], payload: dict[str, Any]) -> None:
    write_json(root / assignment["expected_result_path"], payload)


def case_manual_dispatch_happy(root: Path) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    before_code = directory_digest(root / "generated_code" / rid)
    before_clean = directory_digest(root / "data" / "clean")
    proc, proof = run_ultimate_manual(root, rid)
    manual = load_json(manual_manifest_path(root, rid))
    policy = manual.get("runtime_dispatch_policy") or {}
    validate = validate_manual(root, rid)
    ledger = load_json(dispatch_status_path(root, rid))
    assignments = manual.get("assignments") or []
    after_code = directory_digest(root / "generated_code" / rid)
    after_clean = directory_digest(root / "data" / "clean")
    ok = (
        proc["rc"] == 0
        and proof.get("status") == "PASS"
        and (proof.get("revision_council") or {}).get("status") == "awaiting_agent_results"
        and manual.get("adapter") == "manual_file"
        and policy.get("runtime") == "manual_file"
        and policy.get("provider_required_by_factor_forge") is False
        and policy.get("manual_provider_override") is None
        and policy.get("model_override") is None
        and len(assignments) == 5
        and validate["rc"] == 0
        and ledger.get("ready_for_collection") is False
        and all((root / item["assignment_markdown_path"]).exists() for item in assignments)
        and all((root / item["result_dropbox_path"]).exists() for item in assignments)
        and not (council_dir(root, rid) / f"revision_council_summary__{rid}.json").exists()
        and not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists()
        and not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists()
        and before_code == after_code
        and before_clean == after_clean
    )
    return result("manual_dispatch_happy_path", ok, "manual bundle exists, validates, awaits results, no merge/attach, runtime=manual_file by default", {"run": proc, "revision_council": proof.get("revision_council"), "runtime_policy": policy, "validate": validate, "ledger": ledger, "assignment_count": len(assignments), "generated_code_unchanged": before_code == after_code, "data_clean_unchanged": before_clean == after_clean})


def first_assignment_markdown(root: Path, rid: str) -> str:
    assignments = manifest_assignments(root, rid)
    if not assignments:
        return ""
    return (root / assignments[0]["assignment_markdown_path"]).read_text(encoding="utf-8")


def case_runtime_policy(root: Path, runtime: str, expected_phrases: list[str], *, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    proc, proof = run_ultimate_manual(root, rid, runtime=runtime, provider=provider, model=model)
    manual = load_json(manual_manifest_path(root, rid))
    dispatch = load_json(dispatch_manifest_path(root, rid))
    validate = validate_manual(root, rid)
    policy = manual.get("runtime_dispatch_policy") or {}
    text = first_assignment_markdown(root, rid)
    ok = (
        proc["rc"] == 0
        and proof.get("status") == "PASS"
        and validate["rc"] == 0
        and policy.get("runtime") == runtime
        and policy == dispatch.get("runtime_dispatch_policy")
        and all(phrase in text for phrase in expected_phrases)
    )
    if provider:
        ok = ok and ((policy.get("manual_provider_override") or {}).get("provider") == provider) and "explicit_user_request" in text
    if model:
        ok = ok and ((policy.get("model_override") or {}).get("model") == model) and "explicit_user_request" in text
    return result(f"manual_dispatch_runtime_policy_{runtime}{'_override' if provider or model else ''}", ok, f"runtime={runtime} policy validates and markdown contains runtime text", {"run": proc, "validate": validate, "runtime_policy": policy, "markdown_excerpt": text[:1000]})


def mutate_runtime_policy_case(root: Path, case_name: str, mutate: Any, expected_token: str) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    path = manual_manifest_path(root, rid)
    original = load_json(path)
    try:
        manifest = load_json(path)
        policy = manifest.get("runtime_dispatch_policy") or {}
        mutate(policy)
        manifest["runtime_dispatch_policy"] = policy
        write_json(path, manifest)
        proc = validate_manual(root, rid)
    finally:
        write_json(path, original)
    text = proc["stdout_tail"] + proc["stderr_tail"]
    return result(case_name, proc["rc"] == 1 and expected_token in text, expected_token, {"validate": proc, "token_present": expected_token in text})


def mutate_manual_manifest_case(root: Path, case_name: str, mutate: Any, expected_token: str) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    path = manual_manifest_path(root, rid)
    manifest = load_json(path)
    originals: dict[str, str] = {}
    try:
        mutate(manifest, originals)
        write_json(path, manifest)
        proc = validate_manual(root, rid)
    finally:
        write_json(path, load_json(path) | {})
        write_json(path, load_json(path))
        # restore from a fresh rebuild to avoid carrying mutated file paths.
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_manual_dispatch_bundle.py", "--report-id", rid])
        for file_path, content in originals.items():
            Path(file_path).write_text(content, encoding="utf-8")
    text = proc["stdout_tail"] + proc["stderr_tail"]
    return result(case_name, proc["rc"] == 1 and expected_token in text, expected_token, {"validate": proc, "token_present": expected_token in text})


def case_missing_assignment(root: Path) -> dict[str, Any]:
    def mutate(manifest: dict[str, Any], originals: dict[str, str]) -> None:
        first = manifest["assignments"][0]
        path = root / first["assignment_markdown_path"]
        originals[str(path)] = path.read_text(encoding="utf-8")
        path.unlink()

    return mutate_manual_manifest_case(root, "manual_dispatch_missing_assignment_block", mutate, "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_ASSIGNMENT_MISSING")


def case_markdown_missing_prohibition(root: Path) -> dict[str, Any]:
    def mutate(manifest: dict[str, Any], originals: dict[str, str]) -> None:
        first = manifest["assignments"][0]
        path = root / first["assignment_markdown_path"]
        text = path.read_text(encoding="utf-8")
        originals[str(path)] = text
        path.write_text(text.replace("Do not edit generated_code.", ""), encoding="utf-8")

    return mutate_manual_manifest_case(root, "manual_dispatch_markdown_missing_prohibition_block", mutate, "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_MARKDOWN_PROHIBITION_MISSING")


def case_dropbox_outside_scope(root: Path) -> dict[str, Any]:
    def mutate(manifest: dict[str, Any], originals: dict[str, str]) -> None:
        manifest["assignments"][0]["result_dropbox_path"] = "objects/research_iteration_master/bad_dropbox.json"

    return mutate_manual_manifest_case(root, "manual_dispatch_dropbox_outside_scope_block", mutate, "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_DROPBOX_PATH_OUTSIDE_SCOPE")


def case_import_draft(root: Path) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    clean_results(root, rid)
    proc = import_manual(root, rid)
    report = load_json(council_dir(root, rid) / "manual_dispatch" / f"manual_result_import__{rid}.json")
    agent_results = list((council_dir(root, rid) / "agent_results").glob("*.json"))
    ok = proc["rc"] == 0 and report.get("imported_count") == 0 and report.get("awaiting_count") == 5 and not agent_results
    return result("manual_import_draft_results", ok, "draft dropboxes skipped and no agent_results written", {"import": proc, "report": report, "agent_result_count": len(agent_results)})


def case_import_one_valid(root: Path) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    clean_results(root, rid)
    assignment = manifest_assignments(root, rid)[0]
    write_dropbox(root, assignment, fake_result(root, rid, assignment, suffix="_one"))
    proc = import_manual(root, rid)
    ledger = load_json(dispatch_status_path(root, rid))
    expected_path = root / assignment["expected_result_path"]
    valid_count = len([item for item in ledger.get("tasks") or [] if item.get("status") == "received_valid"])
    ok = proc["rc"] == 0 and expected_path.exists() and valid_count == 1 and ledger.get("ready_for_collection") is False
    return result("manual_import_one_valid_result", ok, "one valid result imported and status ledger remains partial", {"import": proc, "ledger": ledger, "expected_exists": expected_path.exists()})


def case_import_invalid(root: Path) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    clean_results(root, rid)
    assignment = manifest_assignments(root, rid)[0]
    write_dropbox(root, assignment, fake_result(root, rid, assignment, valid=False))
    proc = import_manual(root, rid)
    report = load_json(council_dir(root, rid) / "manual_dispatch" / f"manual_result_import__{rid}.json")
    expected_path = root / assignment["expected_result_path"]
    ok = proc["rc"] == 0 and report.get("imported_count") == 0 and report.get("invalid_count") == 1 and not expected_path.exists()
    return result("manual_import_invalid_final_result", ok, "invalid final dropbox not imported", {"import": proc, "report": report, "expected_exists": expected_path.exists()})


def case_no_overwrite_existing_valid(root: Path) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    clean_results(root, rid)
    assignment = manifest_assignments(root, rid)[0]
    existing = fake_result(root, rid, assignment, suffix="_existing")
    write_expected(root, assignment, existing)
    expected_path = root / assignment["expected_result_path"]
    before = sha256_file(expected_path)
    write_dropbox(root, assignment, fake_result(root, rid, assignment, suffix="_new"))
    proc = import_manual(root, rid)
    after = sha256_file(expected_path)
    report = load_json(council_dir(root, rid) / "manual_dispatch" / f"manual_result_import__{rid}.json")
    ok = proc["rc"] == 0 and before == after and report.get("skipped_count") == 1 and report.get("imported_count") == 0
    return result("manual_import_no_overwrite_existing_valid", ok, "existing valid result unchanged", {"import": proc, "report": report, "unchanged": before == after})


def case_overwrite_invalid_allowed(root: Path) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    clean_results(root, rid)
    assignment = manifest_assignments(root, rid)[0]
    write_expected(root, assignment, fake_result(root, rid, assignment, valid=False, suffix="_bad"))
    write_dropbox(root, assignment, fake_result(root, rid, assignment, suffix="_replacement"))
    proc = import_manual(root, rid, "--overwrite-invalid")
    validate = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid, "--result-path", str(root / assignment["expected_result_path"])])
    report = load_json(council_dir(root, rid) / "manual_dispatch" / f"manual_result_import__{rid}.json")
    ok = proc["rc"] == 0 and report.get("imported_count") == 1 and validate["rc"] == 0
    return result("manual_import_overwrite_invalid_allowed", ok, "existing invalid result replaced with --overwrite-invalid", {"import": proc, "validate": validate, "report": report})


def case_complete_manual_results_finalize(root: Path) -> dict[str, Any]:
    rid = REPORT_MANUAL_DISPATCH
    clean_results(root, rid)
    before_code = directory_digest(root / "generated_code" / rid)
    before_clean = directory_digest(root / "data" / "clean")
    for assignment in manifest_assignments(root, rid):
        write_dropbox(root, assignment, fake_result(root, rid, assignment, suffix="_complete"))
    import_proc = import_manual(root, rid)
    ledger = load_json(dispatch_status_path(root, rid))
    collect_proc = collect(root, rid)
    validate_proc = validate_collection(root, rid)
    finalize_proc = finalize(root, rid)
    after_code = directory_digest(root / "generated_code" / rid)
    after_clean = directory_digest(root / "data" / "clean")
    iteration = load_json(root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json")
    final = (((iteration.get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})
    selected_ids = final.get("selected_council_proposal_ids") or []
    ok = (
        import_proc["rc"] == 0
        and ledger.get("ready_for_collection") is True
        and collect_proc["rc"] == 0
        and validate_proc["rc"] == 0
        and finalize_proc["rc"] == 0
        and final.get("source") == "revision_council"
        and selected_ids
        and all(isinstance(item, str) and item.startswith("agent_") for item in selected_ids)
        and not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists()
        and not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists()
        and before_code == after_code
        and before_clean == after_clean
    )
    return result("manual_complete_results_collect_finalize", ok, "complete manual results import, collect, validate, finalize", {"import": import_proc, "ledger": ledger, "collect": collect_proc, "validate_collection": validate_proc, "finalize": finalize_proc, "selected_ids": selected_ids, "generated_code_unchanged": before_code == after_code, "data_clean_unchanged": before_clean == after_clean})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_agentic_council_manual_dispatch_{int(time.time())}")
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
        cases.append(case_manual_dispatch_happy(root))
        if cases[-1]["ok"]:
            cases.extend(
                [
                    case_runtime_policy(
                        root,
                        "codex",
                        [
                            "Runtime dispatch policy: Codex.",
                            "Subagents inherit the current Codex model by default.",
                            "Do not choose or invoke external LLM providers.",
                        ],
                    ),
                    case_runtime_policy(
                        root,
                        "openclaw",
                        [
                            "Runtime dispatch policy: OpenClaw.",
                            "Subagents inherit the main agent provider/model by default.",
                            "Factor Forge does not require any specific provider.",
                        ],
                    ),
                    case_runtime_policy(
                        root,
                        "manual_file",
                        [
                            "Runtime dispatch policy: manual_file.",
                            "Provider/model identity is not sufficient for acceptance.",
                        ],
                        provider="minimax",
                        model="MiniMax-M2.7",
                    ),
                ]
            )
            run_ultimate_manual(root, REPORT_MANUAL_DISPATCH, runtime="manual_file")
            cases.extend(
                [
                    mutate_runtime_policy_case(
                        root,
                        "manual_dispatch_invalid_runtime_block",
                        lambda policy: policy.update({"runtime": "invalid_runtime"}),
                        "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_RUNTIME_INVALID",
                    ),
                    mutate_runtime_policy_case(
                        root,
                        "manual_dispatch_provider_required_block",
                        lambda policy: policy.update({"provider_required_by_factor_forge": True}),
                        "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_PROVIDER_REQUIRED_BY_FACTOR_FORGE",
                    ),
                    mutate_runtime_policy_case(
                        root,
                        "manual_dispatch_external_provider_without_override_block",
                        lambda policy: policy.update({"external_provider_selection_allowed": True, "manual_provider_override": None}),
                        "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_EXTERNAL_PROVIDER_SELECTION_WITHOUT_OVERRIDE",
                    ),
                    mutate_runtime_policy_case(
                        root,
                        "manual_dispatch_override_missing_reason_block",
                        lambda policy: policy.update({"manual_provider_override": {"provider": "minimax"}}),
                        "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_MANUAL_PROVIDER_OVERRIDE_REASON_INVALID",
                    ),
                    case_missing_assignment(root),
                    case_markdown_missing_prohibition(root),
                    case_dropbox_outside_scope(root),
                    case_import_draft(root),
                    case_import_one_valid(root),
                    case_import_invalid(root),
                    case_no_overwrite_existing_valid(root),
                    case_overwrite_invalid_allowed(root),
                    case_complete_manual_results_finalize(root),
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
            "Synthetic /tmp-only manual_file adapter smoke.",
            "No real external subagents, search workers, clean-data processing, Step3B handoff, generated_code writes, or official promotion.",
        ],
    }
    out = root / "agentic_council_manual_dispatch_smoke_summary.json"
    write_json(out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {out}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
