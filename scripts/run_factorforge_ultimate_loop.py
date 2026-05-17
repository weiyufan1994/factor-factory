#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import load_json, resolve_factorforge_context, utc_now
from factor_factory.ultimate_loop.proof import (
    append_note,
    load_json_if_exists,
    make_initial_proof,
    path_snapshot,
    snapshots_differ,
    tail,
    write_json_atomic,
)
from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff, classify_loop_state


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Factor Forge Ultimate in a bounded revision loop.")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--start-step", default="3")
    ap.add_argument("--max-loops", type=int, default=10)
    ap.add_argument("--council-mode", default="auto", choices=["off", "auto", "scaffold", "agentic"])
    ap.add_argument("--agentic-council-executor", default="none", choices=["none", "local_mock", "dispatch_manifest", "real_agent"])
    ap.add_argument("--agentic-dispatch-adapter", default="none", choices=["none", "manual_file", "openclaw", "codex", "remote_api"])
    ap.add_argument("--runtime-dispatch", default=None, choices=["codex", "openclaw", "manual_file", "unknown"])
    ap.add_argument("--subagent-provider", default=None)
    ap.add_argument("--subagent-model", default=None)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--runtime-manifest", default=None)
    ap.add_argument("--proof-path", default=None)
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def run_command(command: list[str], *, env: dict[str, str], dry_run: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "command": command,
        "cwd": str(REPO_ROOT),
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "rc": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "status": "RUNNING",
    }
    if dry_run:
        item.update({"finished_at_utc": utc_now(), "rc": 0, "status": "DRY_RUN"})
        return item
    proc = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    item.update(
        {
            "finished_at_utc": utc_now(),
            "rc": proc.returncode,
            "stdout_tail": tail(proc.stdout),
            "stderr_tail": tail(proc.stderr),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
        }
    )
    return item


def ultimate_command(args: argparse.Namespace, report_id: str, start_step: str, factorforge_root: Path) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
        "--report-id",
        report_id,
        "--start-step",
        start_step,
        "--end-step",
        "6",
        "--council-mode",
        args.council_mode,
        "--agentic-council-executor",
        args.agentic_council_executor,
        "--agentic-dispatch-adapter",
        args.agentic_dispatch_adapter,
        "--factorforge-root",
        str(factorforge_root),
    ]
    if args.runtime_dispatch:
        command.extend(["--runtime-dispatch", args.runtime_dispatch])
    if args.subagent_provider:
        command.extend(["--subagent-provider", args.subagent_provider])
    if args.subagent_model:
        command.extend(["--subagent-model", args.subagent_model])
    if args.dry_run:
        command.append("--dry-run")
    return command


def materialization_command(parent_report_id: str, child_report_id: str, factorforge_root: Path) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
        "--parent-report-id",
        parent_report_id,
        "--child-report-id",
        child_report_id,
        "--factorforge-root",
        str(factorforge_root),
    ]


def materialization_report_path(factorforge_root: Path, parent_report_id: str, child_report_id: str) -> Path:
    return factorforge_root / "objects" / "runtime_context" / f"child_revision_materialization__{parent_report_id}__{child_report_id}.json"


def brief_ref(factorforge_root: Path, report_id: str) -> dict[str, Any]:
    iteration_path = factorforge_root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    iteration = load_json_if_exists(iteration_path)
    ref = iteration.get("loop_research_brief") if isinstance(iteration, dict) else None
    return ref if isinstance(ref, dict) else {}


def read_brief_json(factorforge_root: Path, report_id: str) -> dict[str, Any]:
    ref = brief_ref(factorforge_root, report_id)
    path = ref.get("json_path")
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = factorforge_root / candidate
    return load_json_if_exists(candidate)


def write_aggregate_brief(path: Path, proof: dict[str, Any], factorforge_root: Path) -> None:
    lines = [
        f"# Factor Forge Ultimate Loop Brief: {proof['root_report_id']}",
        "",
        f"- Status: {proof.get('status')}",
        f"- Final outcome: {proof.get('final_outcome')}",
        f"- Stop reason: {proof.get('stop_reason')}",
        f"- Iterations: {len(proof.get('iterations') or [])}",
        "",
    ]
    for item in proof.get("iterations") or []:
        report_id = item.get("report_id")
        brief = read_brief_json(factorforge_root, str(report_id))
        decision = (brief.get("decision_snapshot") or {}).get("decision") or item.get("decision")
        economic = brief.get("economic_interpretation") or {}
        metrics = brief.get("metrics") or {}
        math_summary = brief.get("mechanism_math_summary") or {}
        council = brief.get("revision_council_summary") or {}
        next_direction = brief.get("next_research_direction") or {}
        lines.extend(
            [
                f"## Loop {item.get('loop_index')}: {report_id}",
                "",
                "### Economic Interpretation",
                f"- Formula: {economic.get('formula', 'missing')}",
                f"- Mechanism: {economic.get('mechanism_hypothesis', 'missing')}",
                "",
                "### Mechanism Math",
                f"- Status: {math_summary.get('math_model_status', 'missing')}",
                f"- Model family: {math_summary.get('model_family', 'missing')}",
                "",
                "### Metrics",
                f"- Rank IC mean: {metrics.get('rank_ic_mean', 'missing')}",
                f"- Long-side Sharpe: {metrics.get('long_side_sharpe', 'missing')}",
                f"- Cost-adjusted annual return: {metrics.get('cost_adjusted_annual_return', 'missing')}",
                "",
                "### Council",
                f"- Status: {item.get('council_status') or council.get('status', 'not_attached')}",
                f"- Selected proposals: {council.get('selected_proposals', [])}",
                "",
                "### Decision",
                f"- Decision: {decision}",
                f"- Loop authorization: {item.get('loop_authorization')}",
                "",
                "### Next Action",
                f"- Outcome: {item.get('outcome')}",
                f"- Child report: {item.get('child_report_id') or 'none'}",
                f"- Revision direction: {next_direction.get('revision_hypothesis', 'none')}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def ancestor_generated_code_snapshots(factorforge_root: Path, ancestors: list[str]) -> dict[str, dict[str, Any]]:
    return {
        report_id: path_snapshot(factorforge_root / "generated_code" / report_id)
        for report_id in ancestors
    }


def changed_ancestor_snapshots(factorforge_root: Path, before: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for report_id, old in before.items():
        new = path_snapshot(factorforge_root / "generated_code" / report_id)
        if snapshots_differ(old, new):
            changes.append({"report_id": report_id, "before": old, "after": new})
    return changes


def main() -> int:
    args = parse_args()
    if not (1 <= args.max_loops <= 10):
        print("BLOCK_FACTORFORGE_LOOP_MAX_LOOPS_OUT_OF_RANGE")
        return 1

    explicit_root = args.factorforge_root
    if not explicit_root and args.runtime_manifest:
        manifest = load_json(Path(args.runtime_manifest).expanduser())
        explicit_root = manifest.get("factorforge_root")
    ctx = resolve_factorforge_context(explicit_root)
    proof_path = Path(args.proof_path) if args.proof_path else ctx.runtime_context_root / f"ultimate_loop_report__{args.report_id}.json"
    brief_path = ctx.runtime_context_root / f"ultimate_loop_brief__{args.report_id}.md"

    proof = make_initial_proof(
        root_report_id=args.report_id,
        factorforge_root=ctx.factorforge_root,
        max_loops=args.max_loops,
        args=vars(args),
    )
    proof["brief_path"] = str(brief_path)
    write_json_atomic(proof_path, proof)

    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(ctx.factorforge_root)
    env["FACTORFORGE_ULTIMATE_RUN"] = "1"
    if args.runtime_manifest:
        env["FACTORFORGE_RUNTIME_MANIFEST"] = str(Path(args.runtime_manifest).expanduser())

    current_report_id = args.report_id
    current_start_step = args.start_step
    current_parent_report_id: str | None = None
    ancestor_report_ids: list[str] = []
    data_clean_before = path_snapshot(ctx.clean_data_root)

    for loop_index in range(1, args.max_loops + 1):
        ancestor_before = ancestor_generated_code_snapshots(ctx.factorforge_root, ancestor_report_ids)
        command = ultimate_command(args, current_report_id, current_start_step, ctx.factorforge_root)
        command_result = run_command(command, env=env, dry_run=args.dry_run)

        if (
            env.get("FACTORFORGE_ULTIMATE_LOOP_TEST_DELETE_HANDOFF_AFTER_WRAPPER") == "1"
            and str(ctx.factorforge_root.resolve()).startswith(("/tmp/", "/private/tmp/"))
        ):
            handoff = ctx.factorforge_root / "objects" / "handoff" / f"handoff_to_step3b__{current_report_id}.json"
            if handoff.exists():
                handoff.unlink()

        ancestor_changes = changed_ancestor_snapshots(ctx.factorforge_root, ancestor_before)
        data_clean_after = path_snapshot(ctx.clean_data_root)
        forbidden_changes = []
        if ancestor_changes:
            forbidden_changes.append({"kind": "parent_generated_code_mutation", "changes": ancestor_changes})
        if snapshots_differ(data_clean_before, data_clean_after):
            forbidden_changes.append({"kind": "data_clean_mutation", "before": data_clean_before, "after": data_clean_after})

        state = classify_loop_state(
            ctx.factorforge_root,
            current_report_id,
            int(command_result.get("rc") or 0),
            max_reached=loop_index >= args.max_loops,
        )
        iteration = {
            "loop_index": loop_index,
            "report_id": current_report_id,
            "parent_report_id": current_parent_report_id,
            "start_step": current_start_step,
            "wrapper_command": command_result,
            "wrapper_proof_path": str(ctx.runtime_context_root / f"ultimate_run_report__{current_report_id}.json"),
            **state,
            "forbidden_side_effects": forbidden_changes,
        }
        proof.setdefault("iterations", []).append(iteration)
        proof["updated_at_utc"] = utc_now()
        write_json_atomic(proof_path, proof)

        if forbidden_changes:
            proof["status"] = "FAIL"
            proof["final_outcome"] = "blocked"
            proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_FORBIDDEN_SIDE_EFFECT"
            proof.setdefault("canonical_side_effects", []).extend(forbidden_changes)
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, ctx.factorforge_root)
            print("BLOCK_FACTORFORGE_LOOP_FORBIDDEN_SIDE_EFFECT")
            return 1

        if not state.get("can_continue"):
            proof["status"] = state.get("proof_status")
            proof["final_outcome"] = state.get("outcome")
            proof["stop_reason"] = state.get("stop_reason")
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, ctx.factorforge_root)
            print(proof["final_outcome"])
            return 0 if proof["status"] in {"PASS", "PAUSED"} else 1

        child = approved_child_revision_from_handoff(ctx.factorforge_root, current_report_id, loop_index)
        if not child.get("ok"):
            iteration["child_revision_error"] = child
            proof["status"] = "FAIL"
            proof["final_outcome"] = "blocked"
            proof["stop_reason"] = child.get("block_reason")
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, ctx.factorforge_root)
            print(child.get("block_reason"))
            return 1

        iteration["child_revision_source"] = "handoff_to_step3b"
        iteration["selected_revision_id"] = child.get("revision_id")
        iteration["child_report_id"] = child.get("child_report_id")
        materialize_cmd = materialization_command(current_report_id, str(child["child_report_id"]), ctx.factorforge_root)
        materialize_result = run_command(materialize_cmd, env=env, dry_run=args.dry_run)
        report_path = materialization_report_path(ctx.factorforge_root, current_report_id, str(child["child_report_id"]))
        materialization_report = load_json_if_exists(report_path)
        iteration["materialization_command"] = materialize_result
        iteration["materialization_rc"] = materialize_result.get("rc")
        iteration["materialization_report_path"] = str(report_path)
        iteration["materialized_artifact_paths"] = materialization_report.get("materialized_artifacts") or {}
        if materialize_result.get("rc") != 0:
            proof["status"] = "FAIL"
            proof["final_outcome"] = "blocked"
            proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED"
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, ctx.factorforge_root)
            print("BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED")
            return 1
        append_note(proof, f"Continuing to child loop report {child.get('child_report_id')}")
        write_json_atomic(proof_path, proof)

        ancestor_report_ids.append(current_report_id)
        current_parent_report_id = current_report_id
        current_report_id = str(child["child_report_id"])
        current_start_step = "3b"

    proof["status"] = "PASS"
    proof["final_outcome"] = "max_loops_reached"
    proof["stop_reason"] = "max_loops_reached"
    write_json_atomic(proof_path, proof)
    write_aggregate_brief(brief_path, proof, ctx.factorforge_root)
    print("max_loops_reached")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
