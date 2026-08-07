#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
REPORT_ALPHA013_LIKE = "STEP6_INTEL_ALPHA013_LIKE_ADVISORY_MECHANISM_CHALLENGE_BRANCH"
REPORT_COLD_START = "STEP6_INTEL_COLD_START_KNOWLEDGE_GAP"
REPORT_MECHANISM_UNCLEAR = "STEP6_INTEL_MECHANISM_UNCLEAR_REVISION"
REPORT_IDS = [REPORT_ALPHA013_LIKE, REPORT_COLD_START, REPORT_MECHANISM_UNCLEAR]
POLLUTION_MARKERS = ["factorforge_agentic_council_dispatch", "STEP6_INTEL"]


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


def run_cmd(root: Path, cmd: list[str], extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {"command": cmd, "rc": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:]}


def result(case: str, ok: bool, expected: str, actual: dict[str, Any]) -> dict[str, Any]:
    return {"case": case, "ok": bool(ok), "expected": expected, "actual": actual}


def setup_fixtures(root: Path) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "scripts/run_step6_intelligence_smoke.py", "--fresh", "--root", str(root)])


def council_dir(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / rid


def proof_path(root: Path, rid: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_run_report__{rid}.json"


def dispatch_manifest_path(root: Path, rid: str) -> Path:
    return council_dir(root, rid) / f"dispatch_manifest__{rid}.json"


def run_ultimate_dispatch(root: Path, rid: str, *, runtime: str | None = None, provider: str | None = None, model: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
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
        "--allow-legacy-global-runtime",
        "--council-mode",
        "agentic",
        "--agentic-council-executor",
        "dispatch_manifest",
        "--allow-legacy-research-protocol-smoke",
    ]
    if runtime:
        cmd.extend(["--runtime-dispatch", runtime])
    if provider:
        cmd.extend(["--subagent-provider", provider])
    if model:
        cmd.extend(["--subagent-model", model])
    proc = run_cmd(root, cmd)
    return proc, load_json(proof_path(root, rid))


def validate_dispatch(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py", "--report-id", rid])


def case_dispatch_happy(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    before_code = directory_digest(root / "generated_code" / rid)
    before_clean = directory_digest(root / "data" / "clean")
    proc, proof = run_ultimate_dispatch(root, rid)
    manifest = load_json(dispatch_manifest_path(root, rid))
    policy = manifest.get("runtime_dispatch_policy") or {}
    validate = validate_dispatch(root, rid)
    after_code = directory_digest(root / "generated_code" / rid)
    after_clean = directory_digest(root / "data" / "clean")
    summary_exists = (council_dir(root, rid) / f"revision_council_summary__{rid}.json").exists()
    iteration = load_json(root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json")
    ok = (
        proc["rc"] == 0
        and proof.get("status") == "PAUSED"
        and (proof.get("revision_council") or {}).get("status") == "awaiting_agent_results"
        and (proof.get("revision_council") or {}).get("effective_mode") == "agentic_dispatch_manifest"
        and manifest.get("agent_task_count") == 5
        and policy.get("runtime") == "unknown"
        and policy.get("provider_required_by_factor_forge") is False
        and len(manifest.get("agent_tasks") or []) == 5
        and validate["rc"] == 0
        and not summary_exists
        and not iteration.get("revision_council_ref")
        and not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists()
        and not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists()
        and before_code == after_code
        and before_clean == after_clean
    )
    return result(
        "dispatch_manifest_happy_path",
        ok,
        "dispatch package created and wrapper awaits agent results without merge/attach",
        {
            "run": proc,
            "revision_council": proof.get("revision_council"),
            "manifest_agent_task_count": manifest.get("agent_task_count"),
            "runtime_policy": policy,
            "validate_dispatch": validate,
            "summary_exists": summary_exists,
            "revision_council_ref_attached": bool(iteration.get("revision_council_ref")),
            "generated_code_unchanged": before_code == after_code,
            "data_clean_unchanged": before_clean == after_clean,
        },
    )


def case_dispatch_runtime_policy(root: Path, runtime: str, *, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    # Runtime-policy variants are fresh dispatches. Resume intentionally keeps
    # the original task packet and must not rewrite its bound policy.
    shutil.rmtree(council_dir(root, rid), ignore_errors=True)
    proof_path(root, rid).unlink(missing_ok=True)
    proc, proof = run_ultimate_dispatch(root, rid, runtime=runtime, provider=provider, model=model)
    manifest = load_json(dispatch_manifest_path(root, rid))
    validate = validate_dispatch(root, rid)
    policy = manifest.get("runtime_dispatch_policy") or {}
    tasks = manifest.get("agent_tasks") or []
    first_packet = load_json(root / tasks[0]["task_packet_path"]) if tasks else {}
    ok = (
        proc["rc"] == 0
        and proof.get("status") == "PAUSED"
        and validate["rc"] == 0
        and policy.get("runtime") == runtime
        and first_packet.get("runtime_dispatch_policy") == policy
    )
    if provider:
        ok = ok and ((policy.get("manual_provider_override") or {}).get("provider") == provider)
    if model:
        ok = ok and ((policy.get("model_override") or {}).get("model") == model)
    return result(f"dispatch_runtime_policy_{runtime}{'_override' if provider or model else ''}", ok, f"runtime={runtime} policy validates and propagates to task packet", {"run": proc, "validate": validate, "runtime_policy": policy, "task_policy": first_packet.get("runtime_dispatch_policy")})


def mutate_dispatch_manifest_policy_case(root: Path, case_name: str, mutate: Callable[[dict[str, Any]], None], expected_token: str) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    manifest_path = dispatch_manifest_path(root, rid)
    original = load_json(manifest_path)
    try:
        manifest = load_json(manifest_path)
        policy = manifest.get("runtime_dispatch_policy") or {}
        mutate(policy)
        manifest["runtime_dispatch_policy"] = policy
        write_json(manifest_path, manifest)
        proc = validate_dispatch(root, rid)
    finally:
        write_json(manifest_path, original)
    token_present = expected_token in (proc["stdout_tail"] + proc["stderr_tail"])
    return result(case_name, proc["rc"] == 1 and token_present, expected_token, {"validate": proc, "token_present": token_present})


def mutate_dispatch_case(root: Path, case_name: str, mutate: Callable[[dict[str, Any], Path], None], expected_token: str) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    manifest_path = dispatch_manifest_path(root, rid)
    manifest = load_json(manifest_path)
    task_path = root / (manifest.get("agent_tasks") or [{}])[0].get("task_packet_path")
    original_manifest = copy.deepcopy(manifest)
    original_task = load_json(task_path)
    try:
        target = load_json(task_path)
        mutate(target, task_path)
        if task_path.exists():
            write_json(task_path, target)
        proc = validate_dispatch(root, rid)
    finally:
        write_json(task_path, original_task)
        write_json(manifest_path, original_manifest)
    token_present = expected_token in (proc["stdout_tail"] + proc["stderr_tail"])
    return result(case_name, proc["rc"] == 1 and token_present, expected_token, {"validate": proc, "token_present": token_present})


def fake_real_agent_result(root: Path, rid: str, task: dict[str, Any], include_identifier: bool = True) -> dict[str, Any]:
    task_packet = load_json(root / task["task_packet_path"])
    task_id = task["task_id"]
    role = task["agent_role"]
    measurement_binding = (
        task_packet.get("measurement_program_binding")
        or task.get("measurement_program_binding")
        or {}
    )
    frozen_model = measurement_binding.get("mechanism_equation_or_functional")
    frozen_object = measurement_binding.get("mathematical_object")
    proof_obligation_ids = [
        str(item)
        for item in task_packet.get("proof_obligation_ids") or []
        if isinstance(item, str) and item
    ]
    payload = {
        "result_version": "factorforge_agentic_revision_council_result_v1",
        "status": "final",
        "report_id": rid,
        "task_id": task_id,
        "agent_role": role,
        "producer": "real_agent",
        "research_depth": "medium",
        "proposal_generation_mode": "agentic",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "measurement_program_binding": measurement_binding,
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
                "finding": "The obligation remains open in this dispatch smoke.",
                "evidence_refs": [],
            }
            for obligation_id in proof_obligation_ids
        ],
        "counterexamples": [
            {
                "attack_type": "null_mechanism",
                "construction_or_scenario": "The observed metric pattern is generated by noise rather than the assigned mechanism.",
                "predicted_failure": "The effect disappears out of sample or after costs.",
                "discriminating_test": "Run the preregistered OOS and after-cost checks before support is claimed.",
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
            "payer_or_counterparty_update": "Potential counterparties are only hypothesized through the public packet evidence.",
            "what_step4_metrics_changed_in_the_hypothesis": "Net evidence and turnover decide whether the estimator state is worth revising.",
        },
        "math_mechanism_derivation": {
            "selected_tool": "statistical_inference",
            "selected_tool_rationale": "The smoke result maps packet evidence into a falsifiable estimator-state claim.",
            "rejected_tools": [{"tool": "expression_wrapper_repair", "reason": "The Council task is expression-level research only."}],
            "baseline_model": frozen_model,
            "model_mutation": "challenge persistence, scale, and falsification requirements before any formula approval",
            "mathematical_objects": [frozen_object, "next_evidence"],
            "derivation_steps": ["Read packet evidence.", "Map it to a public estimator-state claim."],
            "derived_state_variables": ["agentic_state"],
            "observable_estimators": ["factor score", "net long-side evidence"],
            "expected_metric_signature": ["Net evidence should improve if the state is valid.", "Turnover should not worsen materially."],
            "falsification_tests": ["Net long-side Sharpe remains negative.", "Gross signal disappears under expression discipline."],
        },
        "model_to_formula_translation": {
            "candidate_formula": "rank(close)",
            "operator_support_status": "parseable",
            "mapping_from_model_terms_to_formula_components": ["agentic_state -> rank(close) smoke placeholder"],
            "information_set_legality": "legal",
        },
        "public_derivation_record": {
            "research_question": task_packet.get("research_question"),
            "assumptions": [{"assumption": "Step6 packet evidence is the input.", "status": "hypothesis", "why_needed": "No rerun is allowed.", "how_to_falsify": "Invalidate if packet provenance is blocked."}],
            "mathematical_objects": [{"name": frozen_object, "meaning": "The mathematical object frozen by the measurement program.", "unit_or_dimension": "mechanism-dependent", "information_set": "factor timestamp evidence only"}],
            "selected_tools": [{"tool": "statistical_inference", "why_selected": "It links public claims to metric signatures.", "what_it_can_answer": "Whether a hypothesis is testable.", "what_it_cannot_answer": "It cannot approve canonical code changes."}],
            "formula_claims": [{"claim": "The expression can be tested as an estimator state.", "formula_or_relation": "E[next_evidence | agentic_state]", "status": "hypothesis", "derivation_summary": "Public derivation summary for dispatch smoke."}],
            "derivation_steps_summary": [{"step_no": 1, "statement": "Map packet evidence to a testable estimator-state claim.", "depends_on": []}],
            "limiting_cases": [
                {"polarity": "positive", "case": "If the estimator state is valid, net long-side evidence improves without materially higher turnover."},
                {"polarity": "negative", "case": "If net evidence remains negative or gross evidence disappears, the estimator-state claim is falsified."},
            ],
            "falsification_tests": ["Net long-side Sharpe remains negative.", "Gross signal disappears under expression discipline."],
            "kill_criteria": ["High-score long side remains non-positive.", "Improvement exists only in diagnostic spread metrics."],
            "overclaim_guard": "This real-agent-shaped result is advisory-only and cannot authorize code writes.",
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
    if include_identifier:
        payload["agent_identifier"] = task.get("expected_agent_identifier") or f"agent_test_{task_id}"
    return payload


def case_fake_real_agent_result(root: Path, include_identifier: bool) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    manifest = load_json(dispatch_manifest_path(root, rid))
    task = (manifest.get("agent_tasks") or [])[0]
    payload = fake_real_agent_result(root, rid, task, include_identifier=include_identifier)
    result_path = root / task["expected_result_path"]
    write_json(result_path, payload)
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid, "--result-path", str(result_path)])
    if include_identifier:
        ok = proc["rc"] == 0
        name = "fake_real_agent_result_valid"
        expected = "validate result PASS"
    else:
        token = "BLOCK_REVISION_COUNCIL_AGENTIC_REAL_AGENT_IDENTIFIER_MISSING"
        ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"])
        name = "fake_real_agent_missing_identifier_block"
        expected = token
    return result(name, ok, expected, {"validate": proc, "result_path": str(result_path)})


def case_fake_real_agent_missing_math_derivation(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    manifest = load_json(dispatch_manifest_path(root, rid))
    task = (manifest.get("agent_tasks") or [])[0]
    payload = fake_real_agent_result(root, rid, task, include_identifier=True)
    payload.pop("math_mechanism_derivation", None)
    result_path = root / task["expected_result_path"]
    write_json(result_path, payload)
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid, "--result-path", str(result_path)])
    token = "BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION"
    ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"])
    return result("fake_real_agent_missing_math_derivation_block", ok, token, {"validate": proc, "result_path": str(result_path)})


def case_fake_real_agent_missing_public_question_or_limiting_cases(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    manifest = load_json(dispatch_manifest_path(root, rid))
    task = (manifest.get("agent_tasks") or [])[0]
    payload = fake_real_agent_result(root, rid, task, include_identifier=True)
    public = payload.setdefault("public_derivation_record", {})
    public.pop("research_question", None)
    public["limiting_cases"] = []
    result_path = root / task["expected_result_path"]
    write_json(result_path, payload)
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid, "--result-path", str(result_path)])
    token_question = "BLOCK_REVISION_COUNCIL_AGENTIC_RESEARCH_QUESTION_MISSING"
    token_limiting = "BLOCK_REVISION_COUNCIL_AGENTIC_LIMITING_CASES_MISSING"
    output = proc["stdout_tail"] + proc["stderr_tail"]
    ok = proc["rc"] == 1 and token_question in output and token_limiting in output
    return result(
        "fake_real_agent_missing_public_question_or_limiting_cases_block",
        ok,
        f"{token_question}+{token_limiting}",
        {"validate": proc, "result_path": str(result_path), "question_token": token_question in output, "limiting_token": token_limiting in output},
    )


def case_fake_real_agent_terminal_factor_scope_missing_authority(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    manifest = load_json(dispatch_manifest_path(root, rid))
    task = (manifest.get("agent_tasks") or [])[0]
    payload = fake_real_agent_result(root, rid, task, include_identifier=True)
    payload["revision_or_kill_recommendation"] = {
        "recommendation": "reject",
        "terminal_scope": "factor_instance",
        "reason": "This fake result tries to close the factor without authority.",
    }
    payload.pop("terminal_control", None)
    result_path = root / task["expected_result_path"]
    write_json(result_path, payload)
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid, "--result-path", str(result_path)])
    token = "BLOCK_COUNCIL_TERMINAL_AUTHORITY_MISSING"
    output = proc["stdout_tail"] + proc["stderr_tail"]
    ok = proc["rc"] == 1 and token in output
    return result("fake_real_agent_terminal_factor_scope_missing_authority_block", ok, token, {"validate": proc, "result_path": str(result_path), "token_present": token in output})


def build_dispatch(root: Path, rid: str, runtime: str = "unknown") -> list[dict[str, Any]]:
    return [
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid]),
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py", "--report-id", rid, "--executor", "dispatch_manifest", "--runtime-dispatch", runtime, "--research-protocol", "off"]),
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py", "--report-id", rid]),
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py", "--report-id", rid]),
    ]


def formula_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def with_backend_metrics(payload: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    clone = copy.deepcopy(payload)
    clone["backend_summary"] = [{"backend": "self_quant_analyzer", "status": "success", "key_metrics": metrics}]
    clone["key_metrics"] = metrics
    return clone


def copy_report_artifact(root: Path, parent: str, child: str, rel_dir: str, stem: str) -> dict[str, Any]:
    src = root / "objects" / rel_dir / f"{stem}__{parent}.json"
    dst = root / "objects" / rel_dir / f"{stem}__{child}.json"
    payload = load_json(src)
    payload = json.loads(json.dumps(payload, ensure_ascii=False).replace(parent, child))
    write_json(dst, payload)
    return payload


def prepare_prior_revision_child_fixture(root: Path) -> str:
    stale_root_parent = REPORT_COLD_START
    parent = f"{stale_root_parent}__LOOP00__IMMEDIATE_PARENT"
    child = f"{stale_root_parent}__LOOP01__REVISION_MEMORY_SMOKE"
    parent_formula = "rank(negate(signedpower(minus(1, divide(open, close)), 1)))"
    child_formula = "rank(minus(divide(close, open), 1))"
    stale_root_metrics = {
        "rank_ic_mean": 0.99,
        "rank_ic_ir": 0.99,
        "pearson_ic_mean": 0.99,
        "long_side_annual_return": 0.99,
        "cost_adjusted_annual_return": 0.99,
        "long_side_sharpe": 0.99,
        "turnover": 0.99,
        "trading_cogs_annual": 0.99,
        "long_side_max_drawdown": -0.01,
        "long_side_recovery_days": 1,
    }
    parent_metrics = {
        "rank_ic_mean": 0.05,
        "rank_ic_ir": 0.30,
        "pearson_ic_mean": 0.03,
        "long_side_annual_return": -0.20,
        "cost_adjusted_annual_return": -0.90,
        "long_side_sharpe": -0.40,
        "turnover_mean": 0.80,
        "trading_cogs_annual": 0.24,
        "long_side_max_drawdown": -0.50,
        "long_side_recovery_days": 520,
    }
    child_metrics = {
        "rank_ic_mean": -0.05,
        "rank_ic_ir": -0.30,
        "pearson_ic_mean": -0.03,
        "long_side_annual_return": -0.80,
        "cost_adjusted_annual_return": -1.40,
        "long_side_sharpe": -1.20,
        "long_side_turnover_mean_daily": 0.85,
        "annual_cogs": 0.255,
        "max_drawdown": -0.70,
        "recovery_days": 820,
    }
    stale_eval_path = root / "objects" / "validation" / f"factor_evaluation__{stale_root_parent}.json"
    write_json(stale_eval_path, with_backend_metrics(load_json(stale_eval_path), stale_root_metrics))
    parent_eval = copy_report_artifact(root, stale_root_parent, parent, "validation", "factor_evaluation")
    write_json(root / "objects" / "validation" / f"factor_evaluation__{parent}.json", with_backend_metrics(parent_eval, parent_metrics))
    child_eval = copy_report_artifact(root, stale_root_parent, child, "validation", "factor_evaluation")
    write_json(root / "objects" / "validation" / f"factor_evaluation__{child}.json", with_backend_metrics(child_eval, child_metrics))
    copy_report_artifact(root, stale_root_parent, parent, "research_iteration_master", "research_iteration_master")
    copy_report_artifact(root, stale_root_parent, parent, "factor_case_master", "factor_case_master")
    copy_report_artifact(root, stale_root_parent, parent, "factor_run_master", "factor_run_master")
    copy_report_artifact(root, stale_root_parent, parent, "research_iteration_master", "main_agent_mechanism_memo")
    copy_report_artifact(root, stale_root_parent, parent, "factor_spec_master", "factor_spec_master")
    copy_report_artifact(root, stale_root_parent, child, "research_iteration_master", "research_iteration_master")
    copy_report_artifact(root, stale_root_parent, child, "factor_case_master", "factor_case_master")
    copy_report_artifact(root, stale_root_parent, child, "factor_run_master", "factor_run_master")
    copy_report_artifact(root, stale_root_parent, child, "research_iteration_master", "main_agent_mechanism_memo")
    spec = copy_report_artifact(root, stale_root_parent, child, "factor_spec_master", "factor_spec_master")
    parent_hash = formula_hash(parent_formula)
    child_hash = formula_hash(child_formula)
    revision_spec_rel = f"objects/research_iteration_master/executable_revision_spec__{child}.json"
    revision_spec = {
        "contract_version": "factorforge_executable_revision_spec_v1",
        "parent_report_id": parent,
        "child_report_id": child,
        "revision_type": "formula_mutation",
        "derivation_rule": "open_close_sign_orientation_challenge",
        "parent_formula": parent_formula,
        "child_formula": child_formula,
        "parent_formula_hash": parent_hash,
        "child_formula_hash": child_hash,
        "selected_revision_law_ids": ["agent_symbolic_law_discovery_real_law_001"],
    }
    write_json(root / revision_spec_rel, revision_spec)
    spec.setdefault("canonical_spec", {})
    spec["canonical_spec"]["formula_text"] = child_formula
    spec["canonical_spec"]["formula_hash"] = child_hash
    # Regression guard: some real child specs kept a stale root parent here.
    # Prior revision memory must still use the executable spec's immediate parent.
    spec["parent_report_id"] = stale_root_parent
    spec["executable_revision_spec_ref"] = revision_spec_rel
    spec["revision_identity"] = {
        "contract_version": "factorforge_child_revision_identity_v1",
        "parent_report_id": parent,
        "child_report_id": child,
        "revision_spec_path": revision_spec_rel,
        "parent_formula_hash": parent_hash,
        "child_formula_hash": child_hash,
        "revision_noop": False,
        "revision_identity_status": "changed",
    }
    write_json(root / "objects" / "factor_spec_master" / f"factor_spec_master__{child}.json", spec)
    return child


def case_prior_revision_memory_dispatch_contract(root: Path) -> dict[str, Any]:
    rid = prepare_prior_revision_child_fixture(root)
    runs = build_dispatch(root, rid)
    packet = load_json(council_dir(root, rid) / f"revision_council_packet__{rid}.json")
    taskbook = load_json(council_dir(root, rid) / f"agentic_taskbook__{rid}.json")
    manifest = load_json(dispatch_manifest_path(root, rid))
    task_path = root / (manifest.get("agent_tasks") or [{}])[0].get("task_packet_path")
    task_packet = load_json(task_path)
    prior = packet.get("prior_revision_memory") or {}
    task_prior = ((task_packet.get("shared_context") or {}).get("prior_revision_memory") or {})
    required_outputs = set(task_packet.get("required_outputs") or [])
    forbidden_changes = set(task_packet.get("forbidden_changes") or [])
    original_task = copy.deepcopy(task_packet)
    mutated = copy.deepcopy(task_packet)
    mutated["required_outputs"] = [item for item in mutated.get("required_outputs") or [] if item not in {"prior_revision_outcome_review", "repeated_revision_guard"}]
    write_json(task_path, mutated)
    negative = validate_dispatch(root, rid)
    write_json(task_path, original_task)
    token = "BLOCK_AGENTIC_COUNCIL_DISPATCH_PRIOR_REVISION_REQUIRED_OUTPUTS_MISSING"
    ok = (
        all(item["rc"] == 0 for item in runs)
        and prior.get("is_child_revision") is True
        and prior.get("required_for_next_council") is True
        and prior.get("parent_report_id") == f"{REPORT_COLD_START}__LOOP00__IMMEDIATE_PARENT"
        and prior.get("prior_revision_outcome") == "falsified"
        and prior.get("falsified_revision") is True
        and "open_close_sign_orientation_challenge" in (prior.get("forbidden_repeat_revision_rules") or [])
        and (prior.get("metric_delta") or {}).get("rank_ic_mean", {}).get("delta", 0) < 0
        and (prior.get("metric_delta") or {}).get("turnover", {}).get("parent") == 0.80
        and (prior.get("metric_delta") or {}).get("turnover", {}).get("child") == 0.85
        and (prior.get("metric_delta") or {}).get("trading_cogs_annual", {}).get("parent") == 0.24
        and (prior.get("metric_delta") or {}).get("trading_cogs_annual", {}).get("child") == 0.255
        and (prior.get("metric_delta") or {}).get("long_side_max_drawdown", {}).get("parent") == -0.50
        and (prior.get("metric_delta") or {}).get("long_side_max_drawdown", {}).get("child") == -0.70
        and (prior.get("metric_delta") or {}).get("long_side_recovery_days", {}).get("parent") == 520.0
        and (prior.get("metric_delta") or {}).get("long_side_recovery_days", {}).get("child") == 820.0
        and (taskbook.get("shared_context") or {}).get("prior_revision_memory") == prior
        and task_prior == prior
        and {"prior_revision_outcome_review", "repeated_revision_guard"}.issubset(required_outputs)
        and "repeat a falsified executable revision rule" in forbidden_changes
        and negative["rc"] == 1
        and token in (negative["stdout_tail"] + negative["stderr_tail"])
    )
    return result(
        "prior_revision_memory_dispatch_contract",
        ok,
        "child Council dispatch carries prior failed revision memory and blocks task packets that omit the review outputs",
        {
            "setup_runs": runs,
            "prior_revision_memory": prior,
            "task_prior_revision_memory": task_prior,
            "required_outputs": sorted(required_outputs),
            "forbidden_changes": sorted(forbidden_changes),
            "negative_validate": negative,
        },
    )


def case_finalize_missing_result(root: Path) -> dict[str, Any]:
    rid = REPORT_MECHANISM_UNCLEAR
    runs = build_dispatch(root, rid)
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/finalize_agentic_council_dispatch.py", "--report-id", rid])
    token = "BLOCK_AGENTIC_COUNCIL_COLLECTION_MISSING"
    ok = all(item["rc"] == 0 for item in runs) and proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"])
    return result("finalize_missing_required_result_block", ok, token, {"setup_runs": runs, "finalize": proc})


def case_finalize_all_real_agent_results(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    runs = build_dispatch(root, rid)
    manifest = load_json(dispatch_manifest_path(root, rid))
    for task in manifest.get("agent_tasks") or []:
        payload = fake_real_agent_result(root, rid, task, include_identifier=True)
        write_json(root / task["expected_result_path"], payload)
    before_code = directory_digest(root / "generated_code" / rid)
    before_clean = directory_digest(root / "data" / "clean")
    proc, proof = run_ultimate_dispatch(root, rid)
    after_code = directory_digest(root / "generated_code" / rid)
    after_clean = directory_digest(root / "data" / "clean")
    summary = load_json(council_dir(root, rid) / f"revision_council_summary__{rid}.json")
    iteration = load_json(root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json")
    final = (((iteration.get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})
    selected_ids = final.get("selected_council_proposal_ids") or []
    expected_selected_ids = {
        str(task.get("task_id"))
        for task in manifest.get("agent_tasks") or []
        if isinstance(task, dict) and task.get("task_id")
    }
    ok = (
        all(item["rc"] == 0 for item in runs)
        and proc["rc"] == 0
        and proof.get("status") == "PASS"
        and (proof.get("revision_council") or {}).get("status") == "completed"
        and (proof.get("revision_council") or {}).get("formal_council_status")
        == "agentic_results_completed"
        and summary.get("selection_source") == "agentic_results"
        and len(summary.get("valid_agent_results") or []) == 5
        and final.get("source") == "revision_council"
        and set(selected_ids) == expected_selected_ids
        and not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists()
        and not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists()
        and before_code == after_code
        and before_clean == after_clean
    )
    return result(
        "finalize_all_fake_real_agent_results_pass",
        ok,
        "finalize validates, merges, attaches, and preserves canonical write boundaries",
        {
            "setup_runs": runs,
            "wrapper_finalize": proc,
            "revision_council": proof.get("revision_council"),
            "selection_source": summary.get("selection_source"),
            "valid_agent_results": len(summary.get("valid_agent_results") or []),
            "selected_ids": selected_ids,
            "generated_code_unchanged": before_code == after_code,
            "data_clean_unchanged": before_clean == after_clean,
        },
    )


def case_attach_blocks_agent_result_tampered_after_merge(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    summary_path = council_dir(root, rid) / f"revision_council_summary__{rid}.json"
    summary = load_json(summary_path)
    valid_results = summary.get("valid_agent_results") or []
    if not valid_results:
        return result(
            "attach_blocks_agent_result_tampered_after_merge",
            False,
            "valid agent result required",
            {"summary_path": str(summary_path)},
        )
    result_path = Path(str(valid_results[0].get("path") or ""))
    if not result_path.is_absolute():
        result_path = root / result_path
    iteration_path = root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json"
    before_iteration = sha256_file(iteration_path)
    payload = load_json(result_path)
    payload.setdefault("math_mechanism_derivation", {})["baseline_model"] = (
        "dP_t=mu_t*dt+sigma_t*dW_t"
    )
    write_json(result_path, payload)
    attach = run_cmd(
        root,
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py",
            "--report-id",
            rid,
        ],
    )
    after_iteration = sha256_file(iteration_path)
    token = "BLOCK_REVISION_COUNCIL_AGENT_RESULT_HASH_MISMATCH"
    ok = (
        attach["rc"] == 1
        and token in (attach["stdout_tail"] + attach["stderr_tail"])
        and before_iteration == after_iteration
    )
    return result(
        "attach_blocks_agent_result_tampered_after_merge",
        ok,
        token,
        {
            "attach": attach,
            "result_path": str(result_path),
            "iteration_unchanged": before_iteration == after_iteration,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_agentic_council_dispatch_{int(time.time())}")
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
        cases.append(case_dispatch_happy(root))
        cases.append(case_dispatch_runtime_policy(root, "codex"))
        cases.append(case_dispatch_runtime_policy(root, "openclaw"))
        cases.append(case_dispatch_runtime_policy(root, "unknown", provider="minimax", model="MiniMax-M2.7"))
        run_ultimate_dispatch(root, REPORT_ALPHA013_LIKE)
        cases.append(
            mutate_dispatch_manifest_policy_case(
                root,
                "dispatch_invalid_runtime_block",
                lambda policy: policy.update({"runtime": "invalid_runtime"}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_RUNTIME_INVALID",
            )
        )
        cases.append(
            mutate_dispatch_manifest_policy_case(
                root,
                "dispatch_provider_required_block",
                lambda policy: policy.update({"provider_required_by_factor_forge": True}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_PROVIDER_REQUIRED_BY_FACTOR_FORGE",
            )
        )
        cases.append(
            mutate_dispatch_manifest_policy_case(
                root,
                "dispatch_external_provider_without_override_block",
                lambda policy: policy.update({"external_provider_selection_allowed": True, "manual_provider_override": None}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_EXTERNAL_PROVIDER_SELECTION_WITHOUT_OVERRIDE",
            )
        )
        cases.append(
            mutate_dispatch_manifest_policy_case(
                root,
                "dispatch_override_missing_reason_block",
                lambda policy: policy.update({"manual_provider_override": {"provider": "minimax"}}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_MANUAL_PROVIDER_OVERRIDE_REASON_INVALID",
            )
        )
        cases.append(
            mutate_dispatch_case(
                root,
                "dispatch_missing_task_packet_block",
                lambda packet, path: path.unlink(),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_PACKET_MISSING",
            )
        )
        cases.append(
            mutate_dispatch_case(
                root,
                "dispatch_result_path_outside_scope_block",
                lambda packet, path: packet.update({"expected_result_path": "objects/research_iteration_master/bad_result.json"}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_RESULT_PATH_OUTSIDE_SCOPE",
            )
        )
        cases.append(
            mutate_dispatch_case(
                root,
                "dispatch_task_canonical_write_permission_block",
                lambda packet, path: packet.update({"canonical_write_permission": True}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_CANONICAL_WRITE_PERMISSION",
            )
        )
        cases.append(
            mutate_dispatch_case(
                root,
                "dispatch_task_execution_allowed_block",
                lambda packet, path: packet.update({"execution_allowed_by_default": True}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_EXECUTION_ALLOWED_BY_DEFAULT",
            )
        )
        cases.append(
            mutate_dispatch_case(
                root,
                "dispatch_missing_required_output_block",
                lambda packet, path: packet.update({"required_outputs": ["public_derivation_record"]}),
                "BLOCK_AGENTIC_COUNCIL_DISPATCH_REQUIRED_OUTPUTS_MISSING",
            )
        )
        cases.append(case_fake_real_agent_result(root, include_identifier=True))
        cases.append(case_fake_real_agent_result(root, include_identifier=False))
        cases.append(case_fake_real_agent_missing_math_derivation(root))
        cases.append(case_fake_real_agent_missing_public_question_or_limiting_cases(root))
        cases.append(case_fake_real_agent_terminal_factor_scope_missing_authority(root))
        cases.append(case_finalize_missing_result(root))
        cases.append(case_finalize_all_real_agent_results(root))
        cases.append(case_attach_blocks_agent_result_tampered_after_merge(root))
        cases.append(case_prior_revision_memory_dispatch_contract(root))
    after = file_snapshot()
    polluted = pollution_matches(after - before)
    summary = {
        "verdict": "ACCEPT" if all(item["ok"] for item in cases) and not polluted else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(polluted), "new_files": polluted},
        "notes": [
            "Synthetic /tmp-only agentic Council dispatch contract smoke.",
            "No real external subagents, search workers, clean-data processing, Step3B handoff, or official promotion.",
        ],
    }
    out = root / "agentic_council_dispatch_smoke_summary.json"
    write_json(out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {out}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
