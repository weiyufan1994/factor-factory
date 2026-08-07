#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_multibranch_materialization_smoke_module():
    path = REPO_ROOT / "scripts" / "run_factorforge_multibranch_materialization_smoke.py"
    spec = importlib.util.spec_from_file_location("run_factorforge_multibranch_materialization_smoke", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_ultimate_loop_module():
    path = REPO_ROOT / "scripts" / "run_factorforge_ultimate_loop.py"
    spec = importlib.util.spec_from_file_location("run_factorforge_ultimate_loop", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MULTIBRANCH_SMOKE = load_multibranch_materialization_smoke_module()
ULTIMATE_LOOP = load_ultimate_loop_module()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_tmp_root(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve()) if path.exists() else str(path)
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def tail(text: str, limit: int = 6000) -> str:
    return text[-limit:] if len(text) > limit else text


def run(command: list[str], *, root: Path, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    return {
        "command": command,
        "rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
    }


def snapshot_repo_canonical() -> set[str]:
    roots = [
        REPO_ROOT / "objects",
        REPO_ROOT / "runs",
        REPO_ROOT / "evaluations",
        REPO_ROOT / "generated_code",
        REPO_ROOT / "archive",
        REPO_ROOT / "factorforge",
        REPO_ROOT / "data" / "clean",
    ]
    files: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                files.add(str(path.relative_to(REPO_ROOT)))
    return files


def canonical_pollution(before: set[str]) -> dict[str, Any]:
    after = snapshot_repo_canonical()
    added = [
        item for item in sorted(after - before)
        if "ULTIMATE_LOOP_SMOKE" in item
        or "factorforge_ultimate_loop_phase_m" in item
        or "STEP6_INTEL_" in item
    ]
    return {"polluted": bool(added), "new_files": added}


def setup_step6_fixtures(root: Path) -> dict[str, Any]:
    return run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_step6_intelligence_smoke.py"),
            "--fresh",
            "--root",
            str(root),
        ],
        root=root,
    )


def loop_command(root: Path, report_id: str, *, start_step: str = "6", max_loops: int = 10, council_mode: str = "off", executor: str = "none", adapter: str = "none") -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_factorforge_ultimate_loop.py"),
        "--report-id",
        report_id,
        "--start-step",
        start_step,
        "--max-loops",
        str(max_loops),
        "--council-mode",
        council_mode,
        "--agentic-council-executor",
        executor,
        "--agentic-dispatch-adapter",
        adapter,
        "--allow-legacy-global-runtime",
        "--allow-legacy-research-protocol-smoke",
        "--factorforge-root",
        str(root),
    ]


def proof_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_loop_report__{report_id}.json"


def brief_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_loop_brief__{report_id}.md"


def load_proof(root: Path, report_id: str) -> dict[str, Any]:
    path = proof_path(root, report_id)
    return read_json(path) if path.exists() else {}


def run_loop_case(root: Path, name: str, report_id: str, expected_outcome: str, *, max_loops: int = 10, council_mode: str = "off", executor: str = "none", adapter: str = "none", extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    proc = run(
        loop_command(root, report_id, max_loops=max_loops, council_mode=council_mode, executor=executor, adapter=adapter),
        root=root,
        extra_env=extra_env,
    )
    proof = load_proof(root, report_id)
    p_path = proof_path(root, report_id)
    b_path = brief_path(root, report_id)
    ok = (
        p_path.exists()
        and b_path.exists()
        and proof.get("final_outcome") == expected_outcome
        and (proc["rc"] == 0 if proof.get("status") in {"PASS", "PAUSED"} else proc["rc"] != 0)
    )
    return {
        "case": name,
        "report_id": report_id,
        "rc": proc["rc"],
        "expected_outcome": expected_outcome,
        "final_outcome": proof.get("final_outcome"),
        "status": proof.get("status"),
        "stop_reason": proof.get("stop_reason"),
        "proof_path": str(p_path),
        "brief_path": str(b_path),
        "proof_exists": p_path.exists(),
        "brief_exists": b_path.exists(),
        "stdout_tail": proc["stdout_tail"],
        "stderr_tail": proc["stderr_tail"],
        "ok": ok,
    }


def run_wrapper_failure_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    proc = run(
        loop_command(root, report_id, council_mode="agentic", executor="none"),
        root=root,
    )
    proof = load_proof(root, report_id)
    output = proc["stdout_tail"] + proc["stderr_tail"]
    ok = proc["rc"] != 0 and proof.get("final_outcome") == "failed" and (
        "BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED" in output
        or proof.get("stop_reason") == "ultimate_wrapper_failed"
    )
    return {
        "case": "loop_wrapper_failure_blocks",
        "report_id": report_id,
        "rc": proc["rc"],
        "final_outcome": proof.get("final_outcome"),
        "stop_reason": proof.get("stop_reason"),
        "token_present": "BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED" in output,
        "ok": ok,
    }


def run_workspace_dry_run_isolation_case(root: Path) -> dict[str, Any]:
    report_id = "ULTIMATE_LOOP_WORKSPACE_DRY_RUN"
    factor_id = "ULTIMATE_LOOP_WORKSPACE_FACTOR"
    research_id = "ultimate_loop_workspace_research"
    init = run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "init_factor_research_workspace.py"),
            "--factor-id",
            factor_id,
            "--research-id",
            research_id,
            "--report-id",
            report_id,
            "--factorforge-root",
            str(root),
        ],
        root=root,
    )
    workspace = (
        root / "factor_research" / factor_id / research_id
    )
    command = loop_command(
        root,
        report_id,
        max_loops=1,
        council_mode="off",
    )
    command.extend(
        [
            "--factor-workspace",
            str(workspace),
            "--dry-run",
        ]
    )
    proc = run(command, root=root)
    workspace_proof = proof_path(workspace, report_id)
    workspace_brief = brief_path(workspace, report_id)
    global_proof = proof_path(root, report_id)
    global_brief = brief_path(root, report_id)
    proof = read_json(workspace_proof) if workspace_proof.exists() else {}
    command_rows = [
        row.get("wrapper_command", {}).get("command") or []
        for row in proof.get("iterations") or []
        if isinstance(row, dict)
    ]
    command_bound = bool(command_rows) and all(
        "--factor-workspace" in row
        and str(workspace) in row
        for row in command_rows
    )
    ok = (
        init["rc"] == 0
        and proc["rc"] == 0
        and workspace_proof.exists()
        and workspace_brief.exists()
        and not global_proof.exists()
        and not global_brief.exists()
        and command_bound
        and Path(str(proof.get("factorforge_root") or "")).resolve(
            strict=False
        )
        == workspace.resolve(strict=False)
        and proof.get("status") == "DRY_RUN"
        and proof.get("final_outcome") == "dry_run"
        and proof.get("formal_proof_eligible") is False
        and proof.get("proof_semantics") == "execution_plan_only"
    )
    return {
        "case": "ultimate_loop_workspace_dry_run_isolated",
        "init_rc": init["rc"],
        "loop_rc": proc["rc"],
        "workspace": str(workspace),
        "workspace_proof": str(workspace_proof),
        "workspace_brief": str(workspace_brief),
        "workspace_outputs_exist": (
            workspace_proof.exists() and workspace_brief.exists()
        ),
        "global_outputs_absent": (
            not global_proof.exists() and not global_brief.exists()
        ),
        "wrapper_command_bound_to_workspace": command_bound,
        "ok": ok,
    }


def run_wrapper_proof_eligibility_attack_case(root: Path) -> dict[str, Any]:
    def proof_path_for(report_id: str) -> Path:
        return (
            root
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{report_id}.json"
        )

    def passed_command(name: str) -> dict[str, Any]:
        return {
            "name": name,
            "status": "PASS",
            "returncode": 0,
        }

    dry_report_id = "ULTIMATE_LOOP_DRY_RUN_PROOF_ATTACK"
    dry_commands = [
        {
            "name": "run_step6",
            "status": "DRY_RUN",
            "returncode": 0,
        }
    ]
    write_json(
        proof_path_for(dry_report_id),
        {
            "status": "PASS",
            "dry_run": True,
            "contract_smoke_only": False,
            "formal_proof_eligible": False,
            "requested_steps": ["6"],
            "commands": dry_commands,
            "formal_command_contract": {
                "required_command_names": ["run_step6"],
                "research_protocol_verifier_required": True,
                "research_protocol_verifier_name": (
                    "validate_research_protocol_pre_council"
                ),
                "satisfied": False,
            },
        },
    )
    dry_state = ULTIMATE_LOOP.classify_loop_state(
        root,
        dry_report_id,
        0,
    )

    missing_protocol_report_id = "ULTIMATE_LOOP_MISSING_PROTOCOL_ATTACK"
    missing_protocol_commands = [
        passed_command("run_step6"),
        passed_command("validate_step6"),
    ]
    write_json(
        proof_path_for(missing_protocol_report_id),
        {
            "status": "PASS",
            "dry_run": False,
            "contract_smoke_only": False,
            "formal_proof_eligible": True,
            "requested_steps": ["6"],
            "commands": missing_protocol_commands,
            "formal_command_contract": {
                "required_command_names": [
                    row["name"] for row in missing_protocol_commands
                ],
                "research_protocol_verifier_required": False,
                "research_protocol_verifier_name": (
                    "validate_research_protocol_pre_council"
                ),
                "satisfied": True,
            },
        },
    )
    missing_protocol_state = ULTIMATE_LOOP.classify_loop_state(
        root,
        missing_protocol_report_id,
        0,
    )

    valid_report_id = "ULTIMATE_LOOP_FORMAL_PROOF_CONTROL"
    valid_commands = [
        passed_command("validate_research_protocol_pre_council"),
        passed_command("run_step6"),
        passed_command("validate_step6"),
    ]
    write_json(
        proof_path_for(valid_report_id),
        {
            "status": "PASS",
            "dry_run": False,
            "contract_smoke_only": False,
            "formal_proof_eligible": True,
            "requested_steps": ["6"],
            "commands": valid_commands,
            "formal_command_contract": {
                "required_command_names": [
                    row["name"] for row in valid_commands
                ],
                "research_protocol_verifier_required": True,
                "research_protocol_verifier_name": (
                    "validate_research_protocol_pre_council"
                ),
                "satisfied": True,
            },
        },
    )
    valid_state = ULTIMATE_LOOP.classify_loop_state(
        root,
        valid_report_id,
        0,
    )
    ok = (
        dry_state.get("proof_status") == "DRY_RUN"
        and dry_state.get("outcome") == "dry_run"
        and "DRY_RUN_NOT_FORMAL" in str(dry_state.get("stop_reason"))
        and missing_protocol_state.get("proof_status") == "FAIL"
        and missing_protocol_state.get("outcome") == "blocked"
        and "research_protocol_verifier_missing"
        in str(missing_protocol_state.get("stop_reason"))
        and valid_state.get("proof_status") == "PASS"
        and valid_state.get("outcome") == "exhausted"
    )
    return {
        "case": "wrapper_proof_eligibility_attack_blocks",
        "dry_run_state": dry_state,
        "missing_protocol_state": missing_protocol_state,
        "valid_formal_state": valid_state,
        "ok": ok,
    }


def run_child_missing_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    proc = run(
        loop_command(root, report_id, max_loops=10, council_mode="off"),
        root=root,
        extra_env={"FACTORFORGE_ULTIMATE_LOOP_TEST_DELETE_HANDOFF_AFTER_WRAPPER": "1"},
    )
    proof = load_proof(root, report_id)
    ok = proc["rc"] != 0 and proof.get("stop_reason") == "BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING"
    return {
        "case": "loop_child_revision_missing_blocks",
        "report_id": report_id,
        "rc": proc["rc"],
        "final_outcome": proof.get("final_outcome"),
        "stop_reason": proof.get("stop_reason"),
        "ok": ok,
    }


def main_agent_council_synthesis_path(root: Path, report_id: str) -> Path:
    return (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"main_agent_council_synthesis__{report_id}.json"
    )


def write_main_agent_council_synthesis_fixture(
    root: Path,
    report_id: str,
    *,
    child_formula: str = "rank(close)",
    law_id: str = "smoke_explicit_smoothing_law_001",
) -> Path:
    path = main_agent_council_synthesis_path(root, report_id)
    summary_path = path.parent / f"revision_council_summary__{report_id}.json"
    summary = read_json(summary_path) if summary_path.exists() else {}
    routes = [
        item
        for item in summary.get("research_route_summary") or []
        if isinstance(item, dict) and item.get("route_id")
    ]
    if not routes:
        routes = [
            {
                "route_id": "economic_game_payer",
                "exact_gap_after_analysis": "payer and persistence identification",
                "proof_obligation_updates": [],
            },
            {
                "route_id": "mechanism_object_measurement",
                "exact_gap_after_analysis": "mathematical-object identifiability and formula-component mapping",
                "proof_obligation_updates": [],
            },
            {
                "route_id": "microstructure_cost",
                "exact_gap_after_analysis": "after-cost persistence",
                "proof_obligation_updates": [],
            },
            {
                "route_id": "null_alias_counterexample",
                "exact_gap_after_analysis": "strongest alias counterexample",
                "proof_obligation_updates": [],
            },
            {
                "route_id": "symbolic_law",
                "exact_gap_after_analysis": "formula-mappable derivation",
                "proof_obligation_updates": [],
            },
        ]
    route_ids = [str(item["route_id"]) for item in routes]
    selected_route_ids = (
        ["symbolic_law"]
        if "symbolic_law" in route_ids
        else route_ids[:1]
    )
    open_obligation_ids = sorted(
        {
            str(update["obligation_id"])
            for route in routes
            for update in route.get("proof_obligation_updates") or []
            if isinstance(update, dict)
            and update.get("obligation_id")
            and update.get("status") != "passed"
        }
    )
    payload = {
        "contract_version": "factorforge_main_agent_council_synthesis_v1",
        "created_at_utc": utc_now(),
        "report_id": report_id,
        "producer": "ultimate_loop_smoke_current_main_agent_orchestrator",
        "agent_authorship": {
            "authoring_mode": "current_agent_freeform",
            "answered_without_deterministic_template": True,
        },
        "council_result_refs": [
            {
                "agent_role": "formula_engineer",
                "proposal_id": law_id,
                "path": f"objects/research_iteration_master/revision_council/{report_id}/agent_results/{law_id}.json",
            }
        ],
        "consensus_summary": "Council proposals converge on replacing the noisy parent estimator with a single explicit formula mutation.",
        "disagreement_summary": "No conflicting executable law is selected for this smoke fixture.",
        "selection_rule": "proof_obligation_and_falsification_quality",
        "route_comparison": [
            {
                "route_id": route_id,
                "disposition": (
                    "selected" if route_id in selected_route_ids else "carry_forward"
                ),
                "reason": (
                    "Selected as the explicit formula-mappable smoke route."
                    if route_id in selected_route_ids
                    else "Retained as an open alternative; agent count is not a verdict."
                ),
                "exact_gap_or_closed_obligation": next(
                    (
                        str(item.get("exact_gap_after_analysis"))
                        for item in routes
                        if str(item.get("route_id")) == route_id
                    ),
                    "route-specific evidence remains open",
                ),
            }
            for route_id in route_ids
        ],
        "dissent_resolution": (
            "The smoke selects an executable symbolic route without treating "
            "majority agreement as proof; unresolved routes remain open."
        ),
        "rejected_revision_laws": [
            {
                "law_id": "generic_sign_challenge",
                "reason": "A sign inversion is not selected by the orchestrator and must not be inferred by materializer fallback.",
            }
        ],
        "selected_revision": {
            "law_id": law_id,
            "source_route_ids": selected_route_ids,
            "open_proof_obligation_ids": open_obligation_ids,
            "source_agent_roles": ["formula_engineer", "statistical_falsification_agent"],
            "why_selected": "It is the only explicit executable law in this fixture and changes the observable estimator rather than the execution wrapper.",
            "economic_mechanism_link": "Tests whether a cleaner current-price state preserves signal while reducing turnover and drawdown.",
            "math_model_link": "Maps the selected state estimator into a cross-sectional rank target for next-period return.",
            "child_formula": child_formula,
            "formula_mutation_description": "Replace the parent expression with the explicitly selected child formula from main-agent synthesis.",
            "expected_metric_signature": {
                "rank_ic_mean": "should not collapse relative to parent",
                "turnover_mean": "should not increase materially",
                "cost_adjusted_annual_return": "should improve relative to parent",
            },
            "falsification_tests": [
                "rank_ic_mean flips negative",
                "cost_adjusted_annual_return remains non-positive after the formula mutation",
            ],
            "kill_criteria": [
                "child formula hash equals parent formula hash",
                "turnover rises without cost-adjusted improvement",
            ],
        },
        "no_revision_reason": None,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
    }
    write_json(path, payload)
    md_path = path.with_suffix(".md")
    md_path.write_text(
        "\n".join(
            [
                f"# Main Agent Council Synthesis: {report_id}",
                "",
                f"Selected law: `{law_id}`",
                f"Child formula: `{child_formula}`",
                "",
                "The materializer must consume this explicit synthesis and must not infer a generic sign challenge.",
            ]
        ),
        encoding="utf-8",
    )
    return path


def run_materialize_child_revision(root: Path, report_id: str, child_id: str) -> dict[str, Any]:
    return run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
            "--parent-report-id",
            report_id,
            "--child-report-id",
            child_id,
            "--factorforge-root",
            str(root),
        ],
        root=root,
        extra_env={"FACTORFORGE_ULTIMATE_RUN": "1"},
    )


def run_child_orchestrator_synthesis_missing_case(root: Path) -> dict[str, Any]:
    from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff

    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    child = approved_child_revision_from_handoff(root, report_id, 1)
    child_id = str(child.get("child_report_id") or f"{report_id}__LOOP01__MAIN_ITER_002")
    proc = run_materialize_child_revision(root, report_id, child_id)
    output = proc["stdout_tail"] + proc["stderr_tail"]
    spec_path = root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child_id}.json"
    ok = (
        proc["rc"] == 1
        and "BLOCK_FACTORFORGE_MAIN_AGENT_COUNCIL_SYNTHESIS_MISSING" in output
        and not spec_path.exists()
    )
    return {
        "case": "loop_child_orchestrator_synthesis_missing_blocks",
        "report_id": report_id,
        "child_report_id": child_id,
        "rc": proc["rc"],
        "token_present": "BLOCK_FACTORFORGE_MAIN_AGENT_COUNCIL_SYNTHESIS_MISSING" in output,
        "executable_revision_spec_absent": not spec_path.exists(),
        "stdout_tail": proc["stdout_tail"],
        "stderr_tail": proc["stderr_tail"],
        "ok": ok,
    }


def run_child_explicit_orchestrator_synthesis_materializes_case(root: Path) -> dict[str, Any]:
    from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff

    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    child_formula = "rank(close)"
    law_id = "smoke_explicit_smoothing_law_001"
    write_step3_input_fixture(root, report_id)
    synthesis = write_main_agent_council_synthesis_fixture(root, report_id, child_formula=child_formula, law_id=law_id)
    child = approved_child_revision_from_handoff(root, report_id, 1)
    child_id = str(child.get("child_report_id") or f"{report_id}__LOOP01__MAIN_ITER_002")
    proc = run_materialize_child_revision(root, report_id, child_id)
    spec_path = root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child_id}.json"
    spec = read_json(spec_path) if spec_path.exists() else {}
    ok = (
        proc["rc"] == 0
        and Path(str(spec.get("source_orchestrator_synthesis_path") or "")).resolve()
        == synthesis.resolve()
        and spec.get("child_formula") == child_formula
        and spec.get("derivation_rule") == law_id
        and spec.get("selected_revision_law_ids") == [law_id]
        and bool(spec.get("expected_metric_signature"))
        and bool(spec.get("falsification_tests"))
        and bool(spec.get("kill_criteria"))
        and spec.get("parent_formula_hash")
        and spec.get("child_formula_hash")
        and spec.get("parent_formula_hash") != spec.get("child_formula_hash")
    )
    return {
        "case": "loop_child_explicit_orchestrator_synthesis_materializes",
        "report_id": report_id,
        "child_report_id": child_id,
        "rc": proc["rc"],
        "synthesis_path": str(synthesis),
        "executable_revision_spec_path": str(spec_path),
        "executable_revision_spec_exists": spec_path.exists(),
        "child_formula": spec.get("child_formula"),
        "derivation_rule": spec.get("derivation_rule"),
        "selected_revision_law_ids": spec.get("selected_revision_law_ids"),
        "expected_metric_signature_present": bool(spec.get("expected_metric_signature")),
        "falsification_tests_present": bool(spec.get("falsification_tests")),
        "kill_criteria_present": bool(spec.get("kill_criteria")),
        "child_formula_changed": bool(spec.get("parent_formula_hash") and spec.get("child_formula_hash") and spec.get("parent_formula_hash") != spec.get("child_formula_hash")),
        "ok": ok,
    }


def approve_main_agent_synthesis_command(report_id: str, root: Path) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "approve_main_agent_council_synthesis.py"),
        "--report-id",
        report_id,
        "--factorforge-root",
        str(root),
        "--approval-source",
        "ultimate_loop_smoke_default_approval",
    ]


def terminal_reject_result_for_task(report_id: str, task: dict[str, Any]) -> dict[str, Any]:
    role = task.get("agent_role") or "unknown_agent"
    task_id = task.get("task_id") or f"agent_{role}"
    law_id = f"{task_id}_terminal_reject_law"
    return {
        "result_version": "factorforge_agentic_revision_council_result_v1",
        "status": "final",
        "report_id": report_id,
        "task_id": task_id,
        "agent_role": role,
        "producer": "real_agent",
        "agent_identifier": f"terminal_reject_smoke_{role}",
        "research_depth": "high",
        "proposal_generation_mode": "agentic",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "approach_route": {
            "route_id": task.get("route_id"),
            "route_family": task.get("route_family"),
            "core_hypothesis": (
                "The assigned route is falsified for this executed branch, "
                "without closing unrelated mechanism routes."
            ),
            "distinct_from_other_routes": (
                "This result only terminates the route bound to this task packet."
            ),
            "exact_gap_after_analysis": task.get("exact_gap")
            or "A distinct law and new evidence are required to reopen the route.",
        },
        "dispatch_identity": {
            "source_task_packet_sha256": task.get("task_packet_sha256"),
            "route_fingerprint": task.get("route_fingerprint"),
            "blind_context_hash": task.get("blind_context_hash"),
        },
        "proof_obligation_updates": [
            {
                "obligation_id": obligation_id,
                "status": "failed",
                "finding": (
                    "The executed branch did not discharge this route-bound "
                    "obligation under the observed net evidence."
                ),
                "evidence_refs": [],
            }
            for obligation_id in task.get("proof_obligation_ids") or []
            if isinstance(obligation_id, str) and obligation_id
        ],
        "counterexamples": [
            {
                "attack_type": "executed_branch_failure",
                "construction_or_scenario": (
                    "The route's selected estimator fails after costs or repeats "
                    "a previously falsified revision law."
                ),
                "predicted_failure": (
                    "Net long-side evidence remains non-positive and the route "
                    "cannot support another automatic run."
                ),
                "discriminating_test": (
                    "Require a distinct formula/law hash and preregistered positive "
                    "net evidence before reopening."
                ),
            }
        ],
        "route_status": "falsified",
        "reopen_criteria": [
            "A distinct route-bound law with a new hash passes preregistered net evidence."
        ],
        "independence_attestation": {
            "favored_thesis_seen_before_submission": False,
            "derived_from_visible_facts_only": True,
        },
        "economic_hypothesis_review": {
            "preserve_broad_direction": True,
            "refined_second_layer_mechanism": "The executed branch is falsified, but this only proves the tested revision law failed.",
            "payer_or_counterparty_update": "The counterparty hypothesis remains unresolved because no distinct model term has been tested.",
            "what_step4_metrics_changed_in_the_hypothesis": "Negative net evidence falsifies the branch payoff, not the full mechanism family.",
        },
        "math_mechanism_derivation": {
            "selected_tool": "statistical_falsification",
            "selected_tool_rationale": "Executed child evidence can reject a branch while preserving the need for a distinct derivation.",
            "rejected_tools": [{"tool": "terminal_factor_reject", "reason": "One branch failure is insufficient before max loop cap."}],
            "baseline_model": "branch payoff succeeds only if its estimator improves net evidence without repeating known failures",
            "model_mutation": "mark the branch as falsified and require a distinct mathematical mechanism before further execution",
            "mathematical_objects": ["branch_net_evidence", "revision_law_identity", "forbidden_repeat_hash"],
            "derivation_steps": ["Compare child net evidence to parent.", "Classify the failed law as branch-level falsification."],
            "derived_state_variables": ["falsified_revision_branch_state"],
            "observable_estimators": ["child cost-adjusted return", "child drawdown", "child formula hash"],
            "expected_metric_signature": ["No repeated hash or law should be run.", "A distinct law must specify expected net improvement."],
            "falsification_tests": ["Reject branch if net annual return remains negative.", "Reject branch if drawdown remains beyond threshold."],
        },
        "model_to_formula_translation": {
            "candidate_formula": "",
            "disposition": "research_hold",
            "operator_support_status": "parseable",
            "mapping_from_model_terms_to_formula_components": ["No new executable formula is selected by this terminal advisory result."],
            "information_set_legality": "legal",
        },
        "terminal_control": {
            "terminal_scope": "revision_branch_only",
            "stop_authority": "advisory_only",
            "terminal_proof": "This result can falsify the branch but cannot close the factor before max loops.",
        },
        "prior_revision_outcome_review": {
            "prior_revision_outcome": "falsified",
            "review": "Prior child revision failed the net evidence and should not be repeated.",
        },
        "repeated_revision_guard": {
            "guard_status": "active",
            "guard_statement": "Do not repeat the falsified child formula hash or derivation rule.",
        },
        "revision_or_kill_recommendation": {
            "recommendation": "reject",
            "reason": "Council terminal consensus is to reject because the child revision failed net evidence and no executable successor law is selected.",
        },
        "public_derivation_record": {
            "research_question": "Should this child branch continue after the prior executable revision failed?",
            "assumptions": [
                {
                    "assumption": "The child revision evidence is the current decision boundary.",
                    "status": "accepted_for_review",
                    "why_needed": "Terminal decision must use executed child evidence, not a new unrun hypothesis.",
                    "how_to_falsify": "A genuinely different executable law with positive net evidence would be required.",
                }
            ],
            "mathematical_objects": [
                {
                    "name": "net_long_side_evidence",
                    "meaning": "Cost-adjusted long-side evidence after the child revision.",
                    "unit_or_dimension": "annualized return or ratio",
                    "information_set": "post child Step4/5 evidence",
                }
            ],
            "selected_tools": [
                {
                    "tool": "statistical_falsification",
                    "why_selected": "The previous executable law has run and can be falsified by observed child metrics.",
                    "what_it_can_answer": "Whether the current branch should stop.",
                    "what_it_cannot_answer": "It does not authorize another formula without a separate synthesis.",
                }
            ],
            "formula_claims": [
                {
                    "claim": "The child revision did not satisfy net evidence gates.",
                    "formula_or_relation": "accepted_branch iff child_net_evidence > required_threshold and no kill criteria fire",
                    "status": "falsified",
                    "derivation_summary": "Terminal decision follows from failed net evidence and repeated-revision guard.",
                }
            ],
            "derivation_steps_summary": [
                {"step_no": 1, "statement": "Read child evidence and prior revision memory.", "depends_on": []},
                {"step_no": 2, "statement": "Apply kill criteria to the executed child law.", "depends_on": [1]},
            ],
            "limiting_cases": [
                {"polarity": "positive", "case": "If a distinct executable law later produces positive net evidence, this branch-level reject is superseded."},
                {"polarity": "negative", "case": "If the next proposal repeats the same formula hash or derivation rule, continuation is blocked."},
            ],
            "falsification_tests": [
                "Reject continuation if net annual return remains negative.",
                "Reject continuation if drawdown remains beyond the admission threshold.",
            ],
            "kill_criteria": [
                "Prior child revision failed net evidence.",
                "Any next law repeats the falsified derivation rule.",
            ],
            "overclaim_guard": "This result is terminal research advice only and does not authorize execution or writeback.",
        },
        "candidate_revision_laws": [
            {
                "law_id": law_id,
                "revision_type": "reject_advisory",
                "revision_kind": "parameter_repair",
                "law_statement": "Reject the branch after the executed child revision failed the net evidence gates.",
                "expression_change_direction": "No successor expression is selected.",
                "expected_metric_change": [
                    "No further automatic run is expected to rescue net evidence.",
                    "Terminal rejection prevents repeating a failed derivation rule.",
                ],
                "falsification_tests": [
                    "Reject this terminal view only if a distinct approved law has positive net evidence.",
                    "Reject any continuation that repeats the failed child hash.",
                ],
                "kill_criteria": [
                    "Net evidence remains negative.",
                    "Drawdown remains beyond the admission threshold.",
                ],
                "why_not_portfolio_fix": "The recommendation concerns factor research termination, not wrapper repair.",
            }
        ],
    }


def write_terminal_agent_results_fixture(root: Path, report_id: str) -> list[str]:
    manifest_path = root / "objects" / "research_iteration_master" / "revision_council" / report_id / f"dispatch_manifest__{report_id}.json"
    manifest = read_json(manifest_path)
    paths: list[str] = []
    for task in manifest.get("agent_tasks") or []:
        if not isinstance(task, dict):
            continue
        packet_path = Path(str(task.get("task_packet_path") or ""))
        if not packet_path.is_absolute():
            packet_path = root / packet_path
        packet = read_json(packet_path) if packet_path.exists() else {}
        bound_task = {**packet, **task}
        result = terminal_reject_result_for_task(report_id, bound_task)
        raw_path = task.get("expected_result_path")
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = root / path
        write_json(path, result)
        paths.append(str(path))
    return paths


def prepare_terminal_council_fixture(root: Path, report_id: str) -> dict[str, Any]:
    dispatch = run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
            "--report-id",
            report_id,
            "--start-step",
            "6",
            "--end-step",
            "6",
            "--council-mode",
            "agentic",
            "--agentic-council-executor",
            "dispatch_manifest",
            "--allow-legacy-global-runtime",
            "--allow-legacy-research-protocol-smoke",
            "--factorforge-root",
            str(root),
        ],
        root=root,
    )
    result_paths = write_terminal_agent_results_fixture(root, report_id)
    collect = run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "collect_agentic_council_results.py"),
            "--report-id",
            report_id,
        ],
        root=root,
    )
    merge = run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "merge_revision_council.py"),
            "--report-id",
            report_id,
        ],
        root=root,
    )
    return {"dispatch": dispatch, "result_paths": result_paths, "collect": collect, "merge": merge}


def run_council_synthesis_approval_bridge_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    child_formula = "rank(close)"
    law_id = "smoke_explicit_smoothing_law_001"
    write_step3_input_fixture(root, report_id)
    council = run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
            "--report-id",
            report_id,
            "--start-step",
            "6",
            "--end-step",
            "6",
            "--council-mode",
            "agentic",
            "--agentic-council-executor",
            "local_mock",
            "--allow-legacy-global-runtime",
            "--allow-legacy-research-protocol-smoke",
            "--factorforge-root",
            str(root),
        ],
        root=root,
    )
    synthesis = write_main_agent_council_synthesis_fixture(root, report_id, child_formula=child_formula, law_id=law_id)
    approval = run(approve_main_agent_synthesis_command(report_id, root), root=root)
    iteration_path = root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"
    iteration = read_json(iteration_path) if iteration_path.exists() else {}
    handoff = read_json(handoff_path) if handoff_path.exists() else {}
    final_strategy = (((iteration.get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})
    validate = run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "validate_step6.py"),
            "--report-id",
            report_id,
        ],
        root=root,
    )
    ok = (
        council["rc"] == 0
        and approval["rc"] == 0
        and validate["rc"] == 0
        and handoff_path.exists()
        and final_strategy.get("loop_authorization") == "approved_for_step3b_handoff"
        and handoff.get("loop_authorization") == "approved_for_step3b_handoff"
        and Path(str(handoff.get("orchestrator_synthesis_path") or "")).resolve()
        == synthesis.resolve()
        and ((handoff.get("selected_revision") or {}).get("child_formula") == child_formula)
    )
    return {
        "case": "loop_council_synthesis_approval_bridge_activates_handoff",
        "report_id": report_id,
        "council_rc": council["rc"],
        "approval_rc": approval["rc"],
        "validate_step6_rc": validate["rc"],
        "handoff_exists": handoff_path.exists(),
        "final_loop_authorization": final_strategy.get("loop_authorization"),
        "handoff_loop_authorization": handoff.get("loop_authorization"),
        "handoff_synthesis_path": handoff.get("orchestrator_synthesis_path"),
        "selected_child_formula": ((handoff.get("selected_revision") or {}).get("child_formula")),
        "stdout_tail": approval["stdout_tail"],
        "stderr_tail": approval["stderr_tail"],
        "ok": ok,
    }


def run_terminal_council_reject_bridge_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    setup = prepare_terminal_council_fixture(root, report_id)
    proc = run(
        loop_command(
            root,
            report_id,
            start_step="6",
            max_loops=2,
            council_mode="agentic",
            executor="dispatch_manifest",
            adapter="none",
        ),
        root=root,
    )
    proof = load_proof(root, report_id)
    iterations = proof.get("iterations") or []
    first = iterations[0] if iterations else {}
    iteration_path = root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    iteration = read_json(iteration_path) if iteration_path.exists() else {}
    final_strategy = (((iteration.get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"
    branch_path = root / "objects" / "research_iteration_master" / "revision_council" / report_id / f"branch_falsification__{report_id}.json"
    questionnaire_json_path = root / "objects" / "research_iteration_master" / "revision_council" / report_id / f"next_derivation_questionnaire__{report_id}.json"
    questionnaire_md_path = root / "objects" / "research_iteration_master" / "revision_council" / report_id / f"next_derivation_questionnaire__{report_id}.md"
    branch = read_json(branch_path) if branch_path.exists() else {}
    questionnaire = read_json(questionnaire_json_path) if questionnaire_json_path.exists() else {}
    ok = (
        setup["dispatch"]["rc"] == 0
        and setup["collect"]["rc"] == 0
        and setup["merge"]["rc"] == 0
        and proc["rc"] == 0
        and proof.get("status") == "PAUSED"
        and proof.get("final_outcome") == "awaiting_next_derivation"
        and first.get("terminal_reject_bridge_rc") == 1
        and Path(str(first.get("branch_falsification_path") or "")).resolve()
        == branch_path.resolve()
        and branch.get("terminal_scope") == "revision_branch_only"
        and branch.get("next_required_action") == "derive_distinct_math_mechanism"
        and Path(
            str(first.get("next_derivation_questionnaire_path") or "")
        ).resolve()
        == questionnaire_json_path.resolve()
        and Path(
            str(branch.get("next_derivation_questionnaire_json_path") or "")
        ).resolve()
        == questionnaire_json_path.resolve()
        and questionnaire_json_path.exists()
        and questionnaire_md_path.exists()
        and questionnaire.get("contract_version") == "factorforge_next_derivation_questionnaire_v1"
        and questionnaire.get("prior_terminal_scope") == "revision_branch_only"
        and "falsified_model_components" in (questionnaire.get("required_main_agent_answers") or [])
        and iteration.get("decision") != "reject"
        and ((iteration.get("research_judgment") or {}).get("decision") != "reject")
        and not handoff_path.exists()
    )
    return {
        "case": "loop_terminal_council_reject_before_max_loops_pauses_for_derivation",
        "report_id": report_id,
        "rc": proc["rc"],
        "proof_status": proof.get("status"),
        "final_outcome": proof.get("final_outcome"),
        "terminal_reject_bridge_rc": first.get("terminal_reject_bridge_rc"),
        "branch_falsification_path": str(branch_path),
        "branch_falsification_exists": branch_path.exists(),
        "next_derivation_questionnaire_path": str(questionnaire_json_path),
        "next_derivation_questionnaire_exists": questionnaire_json_path.exists(),
        "next_derivation_questionnaire_md_exists": questionnaire_md_path.exists(),
        "branch_terminal_scope": branch.get("terminal_scope"),
        "branch_next_required_action": branch.get("next_required_action"),
        "iteration_decision": iteration.get("decision"),
        "research_judgment_decision": ((iteration.get("research_judgment") or {}).get("decision")),
        "final_loop_authorization": final_strategy.get("loop_authorization"),
        "handoff_absent": not handoff_path.exists(),
        "setup": {k: v for k, v in setup.items() if k != "result_paths"},
        "ok": ok,
    }


def run_existing_child_materialization_noop_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    write_main_agent_council_synthesis_fixture(root, report_id, child_formula="rank(close)")
    first = run(
        loop_command(
            root,
            report_id,
            start_step="6",
            max_loops=2,
            council_mode="agentic",
            executor="local_mock",
            adapter="none",
        ),
        root=root,
    )
    first_proof = load_proof(root, report_id)
    first_iter = (first_proof.get("iterations") or [{}])[0]
    second = run(
        loop_command(
            root,
            report_id,
            start_step="6",
            max_loops=2,
            council_mode="agentic",
            executor="local_mock",
            adapter="none",
        ),
        root=root,
    )
    second_proof = load_proof(root, report_id)
    second_iter = (second_proof.get("iterations") or [{}])[0]
    ok = (
        first["rc"] == 0
        and first_iter.get("materialization_rc") == 0
        and second["rc"] == 0
        and second_proof.get("stop_reason") != "BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED"
        and second_iter.get("materialization_reused") is True
    )
    return {
        "case": "loop_existing_child_materialization_noop",
        "report_id": report_id,
        "first_rc": first["rc"],
        "first_materialization_rc": first_iter.get("materialization_rc"),
        "second_rc": second["rc"],
        "second_status": second_proof.get("status"),
        "second_final_outcome": second_proof.get("final_outcome"),
        "second_stop_reason": second_proof.get("stop_reason"),
        "second_materialization_reused": second_iter.get("materialization_reused"),
        "ok": ok,
    }


def run_council_synthesis_approval_validation_failure_rolls_back_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    council = run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
            "--report-id",
            report_id,
            "--start-step",
            "6",
            "--end-step",
            "6",
            "--council-mode",
            "agentic",
            "--agentic-council-executor",
            "local_mock",
            "--allow-legacy-global-runtime",
            "--allow-legacy-research-protocol-smoke",
            "--factorforge-root",
            str(root),
        ],
        root=root,
    )
    write_main_agent_council_synthesis_fixture(root, report_id, child_formula="rank(close)")
    iteration_path = root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    iteration_before = iteration_path.read_text(encoding="utf-8") if iteration_path.exists() else None
    iteration = read_json(iteration_path) if iteration_path.exists() else {}
    brief_ref = iteration.get("loop_research_brief") if isinstance(iteration.get("loop_research_brief"), dict) else {}
    md_path = Path(str(brief_ref.get("markdown_path") or ""))
    if not md_path.is_absolute():
        md_path = root / md_path
    if md_path.exists():
        md_path.unlink()
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"
    approval = run(approve_main_agent_synthesis_command(report_id, root), root=root)
    iteration_after = iteration_path.read_text(encoding="utf-8") if iteration_path.exists() else None
    approval_artifact = (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"main_agent_council_synthesis_approval__{report_id}.json"
    )
    approval_payload = read_json(approval_artifact) if approval_artifact.exists() else {}
    ok = (
        council["rc"] == 0
        and approval["rc"] != 0
        and not handoff_path.exists()
        and iteration_after == iteration_before
        and approval_artifact.exists()
        and approval_payload.get("rolled_back_active_writes") is True
    )
    return {
        "case": "loop_council_synthesis_approval_validation_failure_rolls_back",
        "report_id": report_id,
        "council_rc": council["rc"],
        "approval_rc": approval["rc"],
        "handoff_absent_after_failure": not handoff_path.exists(),
        "iteration_restored": iteration_after == iteration_before,
        "approval_artifact_exists": approval_artifact.exists(),
        "rollback_recorded": approval_payload.get("rolled_back_active_writes") is True,
        "stdout_tail": approval["stdout_tail"],
        "stderr_tail": approval["stderr_tail"],
        "ok": ok,
    }


def run_loop_consumes_completed_council_synthesis_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    council = run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
            "--report-id",
            report_id,
            "--start-step",
            "6",
            "--end-step",
            "6",
            "--council-mode",
            "agentic",
            "--agentic-council-executor",
            "local_mock",
            "--allow-legacy-global-runtime",
            "--allow-legacy-research-protocol-smoke",
            "--factorforge-root",
            str(root),
        ],
        root=root,
    )
    synthesis = write_main_agent_council_synthesis_fixture(root, report_id, child_formula="rank(close)")
    proc = run(
        loop_command(
            root,
            report_id,
            start_step="6",
            max_loops=2,
            council_mode="agentic",
            executor="dispatch_manifest",
            adapter="none",
        ),
        root=root,
    )
    proof = load_proof(root, report_id)
    iterations = proof.get("iterations") or []
    first = iterations[0] if iterations else {}
    child_id = first.get("child_report_id")
    revision_spec_path = root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child_id}.json"
    revision_spec = read_json(revision_spec_path) if revision_spec_path.exists() else {}
    ok = (
        council["rc"] == 0
        and proc["rc"] == 0
        and first.get("approval_bridge_rc") == 0
        and first.get("materialization_rc") == 0
        and Path(
            str(revision_spec.get("source_orchestrator_synthesis_path") or "")
        ).resolve()
        == synthesis.resolve()
        and revision_spec.get("child_formula") == "rank(close)"
        and proof.get("status") in {"PASS", "PAUSED"}
    )
    return {
        "case": "loop_consumes_completed_council_synthesis_and_materializes_child",
        "report_id": report_id,
        "rc": proc["rc"],
        "council_rc": council["rc"],
        "proof_status": proof.get("status"),
        "final_outcome": proof.get("final_outcome"),
        "approval_bridge_rc": first.get("approval_bridge_rc"),
        "materialization_rc": first.get("materialization_rc"),
        "child_report_id": child_id,
        "revision_spec_exists": revision_spec_path.exists(),
        "revision_spec_uses_synthesis": Path(
            str(revision_spec.get("source_orchestrator_synthesis_path") or "")
        ).resolve()
        == synthesis.resolve(),
        "child_formula": revision_spec.get("child_formula"),
        "ok": ok,
    }


def run_loop_consumes_completed_council_multibranch_synthesis_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    council = run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
            "--report-id",
            report_id,
            "--start-step",
            "6",
            "--end-step",
            "6",
            "--council-mode",
            "agentic",
            "--agentic-council-executor",
            "local_mock",
            "--allow-legacy-global-runtime",
            "--allow-legacy-research-protocol-smoke",
            "--factorforge-root",
            str(root),
        ],
        root=root,
    )
    synthesis = MULTIBRANCH_SMOKE.valid_synthesis(report_id)
    synthesis["selected_branches"][0]["law_id"] = "exploit_close_state"
    synthesis["selected_branches"][0]["child_formula"] = "rank(close)"
    synthesis["selected_branches"][0]["why_selected"] = "Tests a cleaner close-price state that should retain the synthetic fixture payoff."
    synthesis["selected_branches"][1]["law_id"] = "explore_volume_state"
    synthesis["selected_branches"][1]["child_formula"] = "rank(volume)"
    MULTIBRANCH_SMOKE.write_synthesis(root, synthesis, report_id)
    proc = run(
        loop_command(
            root,
            report_id,
            start_step="6",
            max_loops=2,
            council_mode="agentic",
            executor="dispatch_manifest",
            adapter="none",
        ),
        root=root,
    )
    proof = load_proof(root, report_id)
    iterations = proof.get("iterations") or []
    first = iterations[0] if iterations else {}
    second = iterations[1] if len(iterations) > 1 else {}
    child_runs = first.get("multibranch_child_wrapper_runs") if isinstance(first.get("multibranch_child_wrapper_runs"), list) else []
    selected_child = first.get("selected_next_parent_child_report_id")
    comparison_raw = str(first.get("branch_comparison_path") or "")
    comparison_path = Path(comparison_raw) if comparison_raw else Path("/nonexistent/factorforge_branch_comparison_missing.json")
    comparison = read_json(comparison_path) if comparison_path.exists() and comparison_path.is_file() else {}
    selected_packet = (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / str(selected_child)
        / f"revision_council_packet__{selected_child}.json"
    )
    packet = read_json(selected_packet) if selected_packet.exists() else {}
    sibling_memory = packet.get("sibling_branch_memory")
    child_ids = [
        str(run_item.get("child_report_id") or "")
        for run_item in child_runs
        if isinstance(run_item, dict) and run_item.get("child_report_id")
    ]
    non_selected_child_handoffs_absent = all(
        not (root / "objects" / "handoff" / f"handoff_to_step3b__{child_id}.json").exists()
        for child_id in child_ids
        if child_id != selected_child
    )
    child_official_records_absent = all(
        not (root / "objects" / "factor_library_official" / f"factor_record__{child_id}.json").exists()
        for child_id in child_ids
    )
    if selected_packet.exists():
        selected_child_packet_memory_status = "present"
    elif second.get("outcome") == "awaiting_main_agent_mechanism_memo":
        selected_child_packet_memory_status = "not_reached_awaiting_main_agent_mechanism_memo"
    else:
        selected_child_packet_memory_status = "missing_unexpected"
    ok = (
        council["rc"] == 0
        and proc["rc"] == 0
        and first.get("multibranch_approval_rc") == 0
        and first.get("multibranch_materialization_rc") == 0
        and len(child_runs) >= 2
        and all((run_item.get("wrapper_command") or {}).get("rc") == 0 for run_item in child_runs if isinstance(run_item, dict))
        and first.get("branch_comparison_rc") == 0
        and comparison_path.exists()
        and selected_child
        and comparison.get("main_agent_selection", {}).get("selected_next_parent_child_report_id") == selected_child
        and second.get("report_id") == selected_child
        and second.get("start_step") == "6"
        and non_selected_child_handoffs_absent
        and child_official_records_absent
        and selected_child_packet_memory_status != "missing_unexpected"
    )
    return {
        "case": "loop_consumes_completed_council_multibranch_synthesis_executes_children_and_compares",
        "report_id": report_id,
        "rc": proc["rc"],
        "council_rc": council["rc"],
        "proof_status": proof.get("status"),
        "final_outcome": proof.get("final_outcome"),
        "multibranch_approval_rc": first.get("multibranch_approval_rc"),
        "multibranch_materialization_rc": first.get("multibranch_materialization_rc"),
        "multibranch_child_wrapper_count": len(child_runs),
        "multibranch_child_wrapper_rcs": [
            (run_item.get("wrapper_command") or {}).get("rc")
            for run_item in child_runs
            if isinstance(run_item, dict)
        ],
        "branch_comparison_rc": first.get("branch_comparison_rc"),
        "branch_comparison_path": str(comparison_path),
        "branch_comparison_exists": comparison_path.exists(),
        "selected_next_parent_child_report_id": selected_child,
        "second_iteration_report_id": second.get("report_id"),
        "second_iteration_start_step": second.get("start_step"),
        "selected_child_packet_path": str(selected_packet),
        "selected_child_packet_exists": selected_packet.exists(),
        "sibling_branch_memory_present": isinstance(sibling_memory, dict),
        "sibling_branch_memory_source": sibling_memory.get("source_branch_comparison_path") if isinstance(sibling_memory, dict) else None,
        "selected_child_packet_memory_status": selected_child_packet_memory_status,
        "non_selected_child_handoffs_absent": non_selected_child_handoffs_absent,
        "child_official_records_absent": child_official_records_absent,
        "ok": ok,
    }


def run_multibranch_child_control_artifact_guard_case(root: Path) -> dict[str, Any]:
    selected_child = "MULTIBRANCH_CONTROL_GUARD__LOOP01__EXPLOIT"
    non_selected_child = "MULTIBRANCH_CONTROL_GUARD__LOOP01__EXPLORATION"
    children = [selected_child, non_selected_child]
    before = ULTIMATE_LOOP.child_control_artifact_snapshots(root, children)
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3b__{non_selected_child}.json"
    official_path = root / "objects" / "factor_library_official" / f"factor_record__{selected_child}.json"
    write_json(handoff_path, {"report_id": non_selected_child, "status": "approved_for_step3b_handoff"})
    write_json(official_path, {"report_id": selected_child, "promotion_status": "official"})
    changes = ULTIMATE_LOOP.changed_child_control_artifacts(root, before, selected_child)
    kinds = {item.get("kind") for item in changes}
    reports = {item.get("report_id") for item in changes}
    ok = (
        "non_selected_child_handoff_active" in kinds
        and "child_official_record_written" in kinds
        and selected_child in reports
        and non_selected_child in reports
    )
    return {
        "case": "multibranch_child_control_artifact_guard_detects_non_selected_handoff_and_official",
        "selected_child_report_id": selected_child,
        "non_selected_child_report_id": non_selected_child,
        "change_kinds": sorted(kinds),
        "change_reports": sorted(reports),
        "ok": ok,
    }


def run_child_isolation_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    synthesis = write_main_agent_council_synthesis_fixture(root, report_id, child_formula="rank(close)")
    parent_code = root / "generated_code" / report_id
    parent_code.mkdir(parents=True, exist_ok=True)
    marker = parent_code / "parent_marker.py"
    marker.write_text("# parent marker\n", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")
    parent_handoff = root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"
    parent_official = root / "objects" / "factor_library_official" / f"factor_record__{report_id}.json"
    proc = run(loop_command(root, report_id, max_loops=2, council_mode="off"), root=root)
    proof = load_proof(root, report_id)
    iterations = proof.get("iterations") or []
    first = iterations[0] if iterations else {}
    child_iter = iterations[1] if len(iterations) > 1 else {}
    child_id = first.get("child_report_id")
    child_code = root / "generated_code" / str(child_id)
    child_spec_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{child_id}.json"
    parent_spec_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"
    child_prep_path = root / "objects" / "data_prep_master" / f"data_prep_master__{child_id}.json"
    revision_spec_path = root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child_id}.json"
    child_daily_csv = root / "runs" / str(child_id) / "step3a_local_inputs" / f"daily_input__{child_id}.csv"
    child_daily_parquet = root / "runs" / str(child_id) / "step3a_local_inputs" / f"daily_input__{child_id}.parquet"
    child_wrapper_rc = ((child_iter.get("wrapper_command") or {}).get("rc"))
    child_wrapper_proof = Path(str(child_iter.get("wrapper_proof_path") or ""))
    materialization_rc = first.get("materialization_rc")
    after = marker.read_text(encoding="utf-8") if marker.exists() else ""
    parent_handoff_payload = read_json(parent_handoff) if parent_handoff.exists() else {}
    child_spec = read_json(child_spec_path) if child_spec_path.exists() else {}
    parent_spec = read_json(parent_spec_path) if parent_spec_path.exists() else {}
    child_formula_hash = (
        child_spec.get("formula_hash")
        or ((child_spec.get("canonical_spec") or {}).get("formula_ir") or {}).get("formula_hash")
    )
    parent_formula_hash = (
        parent_spec.get("formula_hash")
        or ((parent_spec.get("canonical_spec") or {}).get("formula_ir") or {}).get("formula_hash")
    )
    revision_spec = read_json(revision_spec_path) if revision_spec_path.exists() else {}
    child_prep = read_json(child_prep_path) if child_prep_path.exists() else {}
    child_local_inputs = child_prep.get("local_input_paths") if isinstance(child_prep.get("local_input_paths"), dict) else {}
    child_daily_paths = [
        str(child_local_inputs.get("daily_df_parquet") or ""),
        str(child_local_inputs.get("daily_df_csv") or ""),
        str(child_local_inputs.get("daily_input_meta_json") or ""),
        str((child_local_inputs.get("daily_io_contract") or {}).get("csv_path") or "") if isinstance(child_local_inputs.get("daily_io_contract"), dict) else "",
    ]
    child_paths_reference_child_files = all(
        (not raw) or f"daily_input" in raw and str(child_id) in Path(raw).name
        for raw in child_daily_paths
    )
    parent_not_overwritten_by_child = (
        (not parent_handoff.exists() or parent_handoff_payload.get("report_id") == report_id)
        and not parent_official.exists()
        and (not child_id or not any(parent_code.rglob(f"*{child_id}*")))
    )
    ok = (
        proc["rc"] == 0
        and proof.get("status") != "FAIL"
        and isinstance(child_id, str)
        and child_id.startswith(f"{report_id}__LOOP01__")
        and child_id != report_id
        and materialization_rc == 0
        and child_wrapper_rc == 0
        and child_wrapper_proof.exists()
        and child_code.exists()
        and before == after
        and parent_not_overwritten_by_child
        and revision_spec_path.exists()
        and child_daily_csv.exists()
        and child_daily_parquet.exists()
        and child_paths_reference_child_files
        and child_formula_hash
        and parent_formula_hash
        and child_formula_hash != parent_formula_hash
        and revision_spec.get("child_formula_hash") == child_formula_hash
        and Path(
            str(revision_spec.get("source_orchestrator_synthesis_path") or "")
        ).resolve()
        == synthesis.resolve()
    )
    return {
        "case": "loop_child_report_id_isolation",
        "report_id": report_id,
        "rc": proc["rc"],
        "proof_status": proof.get("status"),
        "child_report_id": child_id,
        "materialization_rc": materialization_rc,
        "materialized_artifact_paths": first.get("materialized_artifact_paths"),
        "child_wrapper_rc": child_wrapper_rc,
        "child_wrapper_proof_path": str(child_wrapper_proof),
        "child_wrapper_proof_exists": child_wrapper_proof.exists(),
        "child_generated_code_exists": child_code.exists(),
        "parent_generated_code_unchanged": before == after,
        "parent_not_overwritten_by_child": parent_not_overwritten_by_child,
        "executable_revision_spec_exists": revision_spec_path.exists(),
        "orchestrator_synthesis_path": str(synthesis),
        "revision_spec_uses_orchestrator_synthesis": Path(
            str(revision_spec.get("source_orchestrator_synthesis_path") or "")
        ).resolve()
        == synthesis.resolve(),
        "child_daily_snapshot_exists": child_daily_csv.exists() and child_daily_parquet.exists(),
        "child_daily_csv_exists": child_daily_csv.exists(),
        "child_daily_parquet_exists": child_daily_parquet.exists(),
        "child_paths_reference_child_files": child_paths_reference_child_files,
        "child_daily_paths": child_daily_paths,
        "parent_formula_hash": parent_formula_hash,
        "child_formula_hash": child_formula_hash,
        "child_formula_changed": bool(child_formula_hash and parent_formula_hash and child_formula_hash != parent_formula_hash),
        "revision_spec_hash_matches_child": revision_spec.get("child_formula_hash") == child_formula_hash,
        "final_outcome": proof.get("final_outcome"),
        "ok": ok,
    }


def run_child_revision_spec_missing_case(root: Path) -> dict[str, Any]:
    from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff

    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    write_main_agent_council_synthesis_fixture(root, report_id, child_formula="rank(close)")
    child = approved_child_revision_from_handoff(root, report_id, 1)
    child_id = str(child.get("child_report_id") or f"{report_id}__LOOP01__MAIN_ITER_002")
    materialize = run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
            "--parent-report-id",
            report_id,
            "--child-report-id",
            child_id,
            "--factorforge-root",
            str(root),
        ],
        root=root,
        extra_env={"FACTORFORGE_ULTIMATE_RUN": "1"},
    )
    spec_path = root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child_id}.json"
    if spec_path.exists():
        spec_path.unlink()
    proc = run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
            "--report-id",
            child_id,
            "--start-step",
            "3b",
            "--end-step",
            "3b",
            "--allow-legacy-global-runtime",
            "--allow-legacy-research-protocol-smoke",
            "--factorforge-root",
            str(root),
        ],
        root=root,
    )
    proof = root / "objects" / "runtime_context" / f"ultimate_run_report__{child_id}.json"
    proof_payload = read_json(proof) if proof.exists() else {}
    command_tails = "\n".join(
        str(cmd.get("stdout_tail", "")) + "\n" + str(cmd.get("stderr_tail", ""))
        for cmd in (proof_payload.get("commands") or [])
        if isinstance(cmd, dict)
    )
    output = proc["stdout_tail"] + proc["stderr_tail"] + command_tails
    ok = materialize["rc"] == 0 and proc["rc"] != 0 and "BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_MISSING" in output
    return {
        "case": "loop_child_revision_spec_missing_blocks_step3b",
        "report_id": report_id,
        "child_report_id": child_id,
        "materialization_rc": materialize["rc"],
        "rc": proc["rc"],
        "token_present": "BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_MISSING" in output,
        "proof_path": str(proof),
        "proof_exists": proof.exists(),
        "ok": ok,
    }


def run_child_materialization_target_exists_case(root: Path) -> dict[str, Any]:
    from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff

    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    child = approved_child_revision_from_handoff(root, report_id, 1)
    child_id = str(child.get("child_report_id") or f"{report_id}__LOOP01__MAIN_ITER_002")
    existing_target = root / "objects" / "factor_spec_master" / f"factor_spec_master__{child_id}.json"
    existing_target.parent.mkdir(parents=True, exist_ok=True)
    sentinel = {
        "report_id": child_id,
        "sentinel": "preexisting_child_target_must_not_be_clobbered",
    }
    write_json(existing_target, sentinel)
    before = existing_target.read_text(encoding="utf-8")
    proc = run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
            "--parent-report-id",
            report_id,
            "--child-report-id",
            child_id,
            "--factorforge-root",
            str(root),
        ],
        root=root,
        extra_env={"FACTORFORGE_ULTIMATE_RUN": "1"},
    )
    after = existing_target.read_text(encoding="utf-8")
    output = proc["stdout_tail"] + proc["stderr_tail"]
    materialization_report = root / "objects" / "runtime_context" / f"child_revision_materialization__{report_id}__{child_id}.json"
    ok = (
        proc["rc"] == 1
        and "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_TARGET_EXISTS" in output
        and before == after
        and not materialization_report.exists()
    )
    return {
        "case": "loop_child_materialization_target_exists_blocks",
        "report_id": report_id,
        "child_report_id": child_id,
        "rc": proc["rc"],
        "token_present": "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_TARGET_EXISTS" in output,
        "existing_artifact_unchanged": before == after,
        "materialization_report_absent": not materialization_report.exists(),
        "ok": ok,
    }


def write_step3_input_fixture(root: Path, report_id: str) -> None:
    from factor_factory.formula.parser import parse_formula
    from factor_factory.mechanism_math.classifier import build_mechanism_math_contract

    spec_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"
    if spec_path.exists():
        spec = read_json(spec_path)
        formula = ((spec.get("canonical_spec") or {}).get("formula_text")) or "rank(close + volume)"
        formula_ir = parse_formula(formula)
        spec.setdefault("canonical_spec", {})
        spec["canonical_spec"]["formula_ir"] = formula_ir
        spec["canonical_spec"]["required_inputs"] = formula_ir.get("required_fields") or spec["canonical_spec"].get("required_inputs") or []
        spec["canonical_spec"]["operators"] = formula_ir.get("operator_set") or spec["canonical_spec"].get("operators") or []
        spec["implementation_mode"] = (spec.get("artifact_identity") or {}).get("implementation_mode") or "operator"
        spec["source_type"] = (spec.get("artifact_identity") or {}).get("source_type") or "natural_language_hypothesis"
        spec["implementation_contract"] = {
            "mode": "operator",
            "formula_ir": formula_ir,
            "formula_hash": formula_ir.get("formula_hash"),
            "operator_set": formula_ir.get("operator_set") or [],
            "required_fields": formula_ir.get("required_fields") or [],
        }
        spec["research_contract"] = {
            "target_statistic": "next-period long-side expected return conditional on a price-volume pressure signal",
            "economic_mechanism": "price and volume co-movement proxies persistent buying pressure that may survive costs if slow enough",
            "expected_failure_modes": [
                "turnover too high relative to gross signal",
                "signal disappears after smoothing",
            ],
            "reuse_instruction_for_future_agents": [
                "Preserve the long-side thesis and test cost-adjusted evidence after expression revisions.",
            ],
        }
        spec["learning_and_innovation"] = {
            "reuse_instruction_for_future_agents": [
                "Do not repair this factor through portfolio, short-leg, or decile trading changes.",
            ],
            "innovative_idea_seeds": ["test smoothing as an estimator-kernel revision"],
        }
        spec["math_discipline_review"] = {
            "target_statistic": "E[r_{t+1} | F_t, price_volume_pressure_t]",
            "step1_random_object": "cross-sectional equity return",
            "information_set_legality": "uses current and historical price-volume fields only",
            "expected_failure_modes": ["cost drag", "non-persistent pressure state"],
        }
        spec["mechanism_math_contract"] = build_mechanism_math_contract(
            {
                "formula_text": formula,
                "required_inputs": formula_ir.get("required_fields") or spec["canonical_spec"].get("required_inputs") or [],
                "operators": formula_ir.get("operator_set") or spec["canonical_spec"].get("operators") or [],
            }
        )
        write_json(spec_path, spec)

    daily = root / "runs" / report_id / "step3a_local_inputs" / f"daily_input__{report_id}.csv"
    daily_parquet = root / "runs" / report_id / "step3a_local_inputs" / f"daily_input__{report_id}.parquet"
    daily_meta = root / "runs" / report_id / "step3a_local_inputs" / f"daily_input_meta__{report_id}.json"
    daily.parent.mkdir(parents=True, exist_ok=True)
    dates = [
        "2020-01-02",
        "2020-01-03",
        "2020-01-06",
        "2020-01-07",
        "2020-01-08",
        "2020-01-09",
        "2020-01-10",
        "2020-01-13",
    ]
    tickers = [f"{idx:06d}.SZ" for idx in range(1, 21)]
    with daily.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "vol",
                "volume",
                "amount",
                "pct_chg",
                "returns",
            ],
        )
        writer.writeheader()
        for d_idx, date in enumerate(dates):
            for t_idx, ticker in enumerate(tickers):
                score = t_idx - 9.5
                close = 10.0 + d_idx * 0.18 + t_idx * 0.08 + (d_idx % 3) * 0.03
                volume = 1200 + d_idx * 37 + t_idx * 23
                rank_perturbation = 0.0018 * (((t_idx + d_idx * 3) % 5) - 2)
                returns = 0.0014 * score + rank_perturbation + 0.0006 * d_idx
                writer.writerow(
                    {
                        "ts_code": ticker,
                        "trade_date": date,
                        "open": close - 0.1,
                        "high": close + 0.2,
                        "low": close - 0.3,
                        "close": close,
                        "vol": volume,
                        "volume": volume,
                        "amount": close * volume,
                        "pct_chg": returns * 100,
                        "returns": returns,
                    }
                )
    try:
        import pandas as pd

        pd.read_csv(daily).to_parquet(daily_parquet, index=False)
    except Exception:
        # Parquet support is available in normal Factor Forge environments; if
        # not, the CSV path still keeps older loop smoke coverage meaningful.
        pass
    write_json(
        daily_meta,
        {
            "report_id": report_id,
            "row_count": len(dates) * len(tickers),
            "format": "csv_and_parquet_smoke_fixture",
        },
    )
    daily_csv_ref = str(Path(root.name) / "runs" / report_id / "step3a_local_inputs" / daily.name)
    daily_parquet_ref = str(Path(root.name) / "runs" / report_id / "step3a_local_inputs" / daily_parquet.name)
    daily_meta_ref = str(Path(root.name) / "runs" / report_id / "step3a_local_inputs" / daily_meta.name)
    prep = {
        "report_id": report_id,
        "factor_id": "SMOKE_PRICE_VOLUME",
        "producer": "ultimate_loop_smoke_fixture",
        "feasibility": "ready",
        "available_columns": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "volume", "amount", "pct_chg", "returns"],
        "field_mappings": {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "vol": "vol",
            "amount": "amount",
            "pct_chg": "pct_chg",
            "returns": "returns",
        },
        "field_mapping": {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
            "returns": "returns",
        },
        "local_input_paths": {
            "input_mode": "daily_only",
            "daily_df_csv": daily_csv_ref,
            "daily_df_parquet": daily_parquet_ref if daily_parquet.exists() else None,
            "daily_input_meta_json": daily_meta_ref,
            "preferred_daily_format": "parquet" if daily_parquet.exists() else "csv",
            "audit_daily_format": "csv",
            "daily_io_contract": {
                "version": "factorforge_step3a_daily_io_contract_v1",
                "performance_path": "parquet" if daily_parquet.exists() else "csv",
                "audit_path": "csv",
                "csv_output_policy": "full_csv",
                "csv_path": daily_csv_ref,
                "csv_sample_path": None,
                "parquet_required_for_performance": bool(daily_parquet.exists()),
                "csv_required_for_audit": True,
            },
        },
        "sample_window": {"start": "2020-01-02", "end": "2020-01-13"},
        "data_sources": ["synthetic_ultimate_loop_fixture"],
    }
    write_json(root / "objects" / "data_prep_master" / f"data_prep_master__{report_id}.json", prep)
    write_json(root / "objects" / "data_prep_master" / f"qlib_adapter_config__{report_id}.json", {"report_id": report_id, "adapter_ready": True})


def run_aggregate_brief_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_VALID_PROMOTE_NO_REVISION_NEEDED"
    path = brief_path(root, report_id)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    required = [
        "### Economic Interpretation",
        "### Mechanism Math",
        "### Metrics",
        "### Council",
        "### Decision",
        "### Next Action",
    ]
    ok = path.exists() and all(token in text for token in required)
    return {
        "case": "loop_aggregate_brief_written",
        "report_id": report_id,
        "brief_path": str(path),
        "brief_exists": path.exists(),
        "required_sections_present": all(token in text for token in required),
        "ok": ok,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Phase M Factor Forge Ultimate loop smoke.")
    ap.add_argument("--root", default=None)
    ap.add_argument("--fresh", action="store_true")
    return ap.parse_args()


def case_root(base: Path, name: str) -> Path:
    return base / name


def run_with_fresh_fixture(base: Path, name: str, runner) -> dict[str, Any]:
    root = case_root(base, name)
    setup = setup_step6_fixtures(root)
    if setup["rc"] != 0:
        return {
            "case": name,
            "case_root": str(root),
            "fixture_setup": setup,
            "ok": False,
        }
    result = runner(root)
    result["case_root"] = str(root)
    result["fixture_setup_rc"] = setup["rc"]
    return result


def run_without_fixture(base: Path, name: str, runner) -> dict[str, Any]:
    root = case_root(base, name)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    result = runner(root)
    result["case_root"] = str(root)
    return result


def referenced_artifacts_exist(cases: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[str] = []
    for case in cases:
        for key in ("proof_path", "brief_path", "child_wrapper_proof_path"):
            raw = case.get(key)
            if raw and not Path(str(raw)).exists():
                missing.append(str(raw))
    return {"ok": not missing, "missing": missing}


def main() -> int:
    args = parse_args()
    root = Path(args.root or (Path("/tmp") / f"factorforge_ultimate_loop_phase_m_{datetime.now().strftime('%Y%m%d_%H%M%S')}")).expanduser()
    if not is_tmp_root(root):
        print(f"BLOCK_NON_TMP_FACTORFORGE_ROOT: {root}")
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    before = snapshot_repo_canonical()
    cases: list[dict[str, Any]] = [
        run_with_fresh_fixture(
            root,
            "loop_promote_stops",
            lambda r: run_loop_case(r, "loop_promote_stops", "STEP6_INTEL_VALID_PROMOTE_NO_REVISION_NEEDED", "promoted", max_loops=10, council_mode="off"),
        ),
        run_with_fresh_fixture(
            root,
            "loop_reject_stops",
            lambda r: run_loop_case(r, "loop_reject_stops", "STEP6_INTEL_LONG_SIDE_NEGATIVE_REVISION", "rejected", max_loops=10, council_mode="off"),
        ),
        run_with_fresh_fixture(
            root,
            "loop_awaiting_agent_results_pauses",
            lambda r: run_loop_case(
                r,
                "loop_awaiting_agent_results_pauses",
                "STEP6_INTEL_ALPHA013_LIKE_ADVISORY_MECHANISM_CHALLENGE_BRANCH",
                "awaiting_agent_results",
                max_loops=10,
                council_mode="agentic",
                executor="dispatch_manifest",
                adapter="manual_file",
            ),
        ),
        run_with_fresh_fixture(
            root,
            "loop_awaiting_main_agent_mechanism_memo_pauses",
            lambda r: run_loop_case(
                r,
                "loop_awaiting_main_agent_mechanism_memo_pauses",
                "STEP6_INTEL_MAIN_AGENT_MEMO_MISSING_PAUSES_BEFORE_HANDOFF",
                "awaiting_main_agent_mechanism_memo",
                max_loops=10,
                council_mode="off",
            ),
        ),
        run_with_fresh_fixture(
            root,
            "loop_max_10_stops",
            lambda r: run_loop_case(r, "loop_max_10_stops", "STEP6_INTEL_HIGH_TURNOVER_REVISION", "max_loops_reached", max_loops=1, council_mode="off"),
        ),
        run_with_fresh_fixture(root, "loop_wrapper_failure_blocks", run_wrapper_failure_case),
        run_without_fixture(
            root,
            "ultimate_loop_workspace_dry_run_isolated",
            run_workspace_dry_run_isolation_case,
        ),
        run_without_fixture(
            root,
            "wrapper_proof_eligibility_attack_blocks",
            run_wrapper_proof_eligibility_attack_case,
        ),
        run_with_fresh_fixture(root, "loop_child_orchestrator_synthesis_missing_blocks", run_child_orchestrator_synthesis_missing_case),
        run_with_fresh_fixture(root, "loop_child_explicit_orchestrator_synthesis_materializes", run_child_explicit_orchestrator_synthesis_materializes_case),
        run_with_fresh_fixture(root, "loop_council_synthesis_approval_bridge_activates_handoff", run_council_synthesis_approval_bridge_case),
        run_with_fresh_fixture(root, "loop_council_synthesis_approval_validation_failure_rolls_back", run_council_synthesis_approval_validation_failure_rolls_back_case),
        run_with_fresh_fixture(root, "loop_consumes_completed_council_synthesis_and_materializes_child", run_loop_consumes_completed_council_synthesis_case),
        run_with_fresh_fixture(root, "loop_consumes_completed_council_multibranch_synthesis_executes_children_and_compares", run_loop_consumes_completed_council_multibranch_synthesis_case),
        run_without_fixture(root, "multibranch_child_control_artifact_guard_detects_non_selected_handoff_and_official", run_multibranch_child_control_artifact_guard_case),
        run_with_fresh_fixture(root, "loop_terminal_council_reject_bridge_stops", run_terminal_council_reject_bridge_case),
        run_with_fresh_fixture(root, "loop_existing_child_materialization_noop", run_existing_child_materialization_noop_case),
        run_with_fresh_fixture(root, "loop_child_report_id_isolation", run_child_isolation_case),
        run_with_fresh_fixture(root, "loop_child_materialization_target_exists_blocks", run_child_materialization_target_exists_case),
        run_with_fresh_fixture(root, "loop_child_revision_spec_missing_blocks_step3b", run_child_revision_spec_missing_case),
        run_with_fresh_fixture(root, "loop_child_revision_missing_blocks", run_child_missing_case),
    ]
    cases.append(run_aggregate_brief_case(case_root(root, "loop_promote_stops")))

    pollution = canonical_pollution(before)
    referenced = referenced_artifacts_exist(cases)
    verdict = "ACCEPT" if all(case.get("ok") for case in cases) and referenced["ok"] and not pollution["polluted"] else "BLOCK"
    summary = {
        "contract_version": "factorforge_ultimate_loop_smoke_v1",
        "created_at_utc": utc_now(),
        "factorforge_root": str(root),
        "root_is_tmp": True,
        "verdict": verdict,
        "cases": cases,
        "referenced_artifacts": referenced,
        "canonical_pollution": pollution,
    }
    summary_path = root / "objects" / "runtime_context" / "ultimate_loop_smoke_summary.json"
    write_json(summary_path, summary)
    print(f"verdict={verdict}")
    print(f"summary={summary_path}")
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
