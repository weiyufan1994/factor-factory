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
REPORT_HIGH_TURNOVER = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
REPORT_MECHANISM_UNCLEAR = "STEP6_INTEL_MECHANISM_UNCLEAR_REVISION"
REPORT_COLD_START = "STEP6_INTEL_COLD_START_KNOWLEDGE_GAP"
REPORT_IDS = [REPORT_ALPHA013_LIKE, REPORT_HIGH_TURNOVER, REPORT_MECHANISM_UNCLEAR, REPORT_COLD_START]
POLLUTION_MARKERS = ["factorforge_agentic_council", "STEP6_INTEL"]


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


def proof_path(root: Path, rid: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_run_report__{rid}.json"


def council_dir(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / rid


def result_paths(root: Path, rid: str) -> list[Path]:
    return sorted((council_dir(root, rid) / "agent_results").glob(f"agent_result__{rid}__*.json"))


def run_ultimate(root: Path, rid: str, executor: str, extra_env: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
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
        executor,
        "--allow-legacy-research-protocol-smoke",
    ]
    proc = run_cmd(root, cmd, extra_env=extra_env)
    return proc, load_json(proof_path(root, rid))


def case_happy_path(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    before_code = directory_digest(root / "generated_code" / rid)
    before_clean = directory_digest(root / "data" / "clean")
    proc, proof = run_ultimate(root, rid, "local_mock")
    rc = proof.get("revision_council") or {}
    after_code = directory_digest(root / "generated_code" / rid)
    after_clean = directory_digest(root / "data" / "clean")
    summary = load_json(council_dir(root, rid) / f"revision_council_summary__{rid}.json")
    ok = (
        proc["rc"] == 0
        and proof.get("status") == "PASS"
        and rc.get("status") == "completed"
        and rc.get("effective_mode") == "agentic_contract_mock"
        and (council_dir(root, rid) / f"agentic_taskbook__{rid}.json").exists()
        and len(result_paths(root, rid)) == 5
        and len(summary.get("valid_agent_results") or []) == 5
        and rc.get("final_revision_strategy_source") == "revision_council"
        and rc.get("loop_authorization") == "advisory_only"
        and not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists()
        and not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists()
        and before_code == after_code
        and before_clean == after_clean
    )
    return result("agentic_local_mock_happy_path", ok, "agentic local_mock completes and stays advisory-only", {"run": proc, "revision_council": rc, "valid_agent_results": len(summary.get("valid_agent_results") or []), "generated_code_unchanged": before_code == after_code, "data_clean_unchanged": before_clean == after_clean})


def case_ignores_stale_scaffold(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    setup_runs = [
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid]),
        run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/run_revision_council.py", "--report-id", rid]),
    ]
    stale_paths = sorted(council_dir(root, rid).glob(f"proposal__{rid}__*.json"))
    stale_ids = []
    for path in stale_paths:
        stale_ids.append(load_json(path).get("proposal_id"))
    proc, proof = run_ultimate(root, rid, "local_mock")
    summary = load_json(council_dir(root, rid) / f"revision_council_summary__{rid}.json")
    iteration = load_json(root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json")
    final_strategy = (((iteration.get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})
    selected_ids = final_strategy.get("selected_council_proposal_ids") or []
    branches = summary.get("recommended_branch_templates") or []
    deterministic_ids = {"cost_turnover_001", "economic_mechanism_001"}
    branch_source_ids = [branch.get("source_proposal_id") for branch in branches if isinstance(branch, dict)]
    agentic_ids = {
        str(item.get("task_id"))
        for item in summary.get("valid_agent_results") or []
        if isinstance(item, dict) and item.get("task_id")
    }
    ok = (
        all(item["rc"] == 0 for item in setup_runs)
        and bool(stale_paths)
        and proc["rc"] == 0
        and summary.get("selection_source") == "agentic_results"
        and summary.get("deterministic_fallback_used") is False
        and len(summary.get("valid_agent_results") or []) == 5
        and bool(summary.get("ignored_deterministic_proposals"))
        and set(selected_ids) == agentic_ids
        and not (deterministic_ids & set(selected_ids))
        and set(branch_source_ids).issubset(agentic_ids)
        and not (deterministic_ids & set(branch_source_ids))
        and final_strategy.get("source") == "revision_council"
    )
    return result(
        "agentic_ignores_stale_scaffold_proposals",
        ok,
        "valid agentic results are the only selected source; stale deterministic proposals ignored",
        {
            "setup_runs": setup_runs,
            "run": proc,
            "proof_revision_council": proof.get("revision_council"),
            "stale_proposal_ids": stale_ids,
            "selection_source": summary.get("selection_source"),
            "deterministic_fallback_used": summary.get("deterministic_fallback_used"),
            "valid_agent_result_count": len(summary.get("valid_agent_results") or []),
            "ignored_deterministic_proposals": summary.get("ignored_deterministic_proposals"),
            "selected_ids": selected_ids,
            "branch_source_ids": branch_source_ids,
        },
    )


def case_executor_required(root: Path) -> dict[str, Any]:
    proc, proof = run_ultimate(root, REPORT_COLD_START, "none")
    token = "BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED"
    ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"]) and (proof.get("revision_council") or {}).get("block_reason") == token
    return result("agentic_without_executor_block", ok, token, {"run": proc, "revision_council": proof.get("revision_council")})


def case_real_agent_block(root: Path) -> dict[str, Any]:
    proc, proof = run_ultimate(root, REPORT_COLD_START, "real_agent")
    token = "BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED"
    ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"]) and (proof.get("revision_council") or {}).get("block_reason") == token
    return result("real_agent_not_implemented_block", ok, token, {"run": proc, "revision_council": proof.get("revision_council")})


def mutate_result_case(root: Path, case_name: str, mutate) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    source = result_paths(root, rid)[0]
    payload = load_json(source)
    mutate(payload)
    mutation_path = root / "mutations" / f"{case_name}.json"
    write_json(mutation_path, payload)
    proc = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid, "--result-path", str(mutation_path)])
    ok = proc["rc"] == 1
    return result(case_name, ok, "validate_agentic_council_result BLOCK", {"run": proc, "mutation_path": str(mutation_path)})


def case_all_invalid_merge(root: Path) -> dict[str, Any]:
    rid = REPORT_MECHANISM_UNCLEAR
    env = {"FACTORFORGE_ROOT": str(root)}
    cmds = [
        [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid],
        [sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py", "--report-id", rid, "--research-protocol", "off"],
        [sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py", "--report-id", rid],
        [sys.executable, "skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py", "--report-id", rid],
        [sys.executable, "skills/factor-forge-step6/scripts/run_agentic_council_local_mock.py", "--report-id", rid],
    ]
    runs = [run_cmd(root, cmd, env) for cmd in cmds]
    for path in result_paths(root, rid):
        payload = load_json(path)
        payload.pop("public_derivation_record", None)
        write_json(path, payload)
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    token = "BLOCK_REVISION_COUNCIL_AGENTIC_RESULTS_INVALID"
    ok = all(item["rc"] == 0 for item in runs) and merge["rc"] == 1 and token in (merge["stdout_tail"] + merge["stderr_tail"])
    return result("all_agent_results_invalid_block", ok, token, {"setup_runs": runs, "merge": merge})


def case_side_effect(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    proc, proof = run_ultimate(root, rid, "local_mock", {"FACTORFORGE_ULTIMATE_TEST_MUTATE_GENERATED_CODE_AFTER_COUNCIL": "1"})
    token = "BLOCK_REVISION_COUNCIL_WRAPPER_FORBIDDEN_SIDE_EFFECT"
    ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"]) and (proof.get("revision_council") or {}).get("block_reason") == token
    return result("agentic_forbidden_side_effect_block", ok, token, {"run": proc, "revision_council": proof.get("revision_council")})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_agentic_council_contract_{int(time.time())}")
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
        cases.append(case_ignores_stale_scaffold(root))
        cases.append(case_happy_path(root))
        cases.append(case_executor_required(root))
        cases.append(case_real_agent_block(root))
        cases.append(mutate_result_case(root, "agentic_missing_derivation_record_block", lambda p: p.pop("public_derivation_record", None)))
        cases.append(mutate_result_case(root, "agentic_forbidden_repair_text_block", lambda p: p["candidate_revision_laws"][0].update({"law_statement": "Use rebalance and long-short repair."})))
        cases.append(mutate_result_case(root, "agentic_execution_allowed_by_default_block", lambda p: p.update({"execution_allowed_by_default": True})))
        cases.append(mutate_result_case(root, "agentic_canonical_write_permission_block", lambda p: p.update({"canonical_write_permission": True})))
        cases.append(case_all_invalid_merge(root))
        cases.append(case_side_effect(root))
    after = file_snapshot()
    polluted = pollution_matches(after - before)
    summary = {
        "verdict": "ACCEPT" if all(item["ok"] for item in cases) and not polluted else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(polluted), "new_files": polluted},
        "notes": ["Synthetic /tmp-only agentic Council contract smoke.", "No real subagents, search workers, clean-data processing, or Step3B mutation."],
    }
    out = root / "agentic_council_contract_smoke_summary.json"
    write_json(out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {out}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
