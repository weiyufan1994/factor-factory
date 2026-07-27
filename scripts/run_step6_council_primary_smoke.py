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
REPORT_COLD_START = "STEP6_INTEL_COLD_START_KNOWLEDGE_GAP"
REPORT_ALPHA013_LIKE = "STEP6_INTEL_ALPHA013_LIKE_ADVISORY_MECHANISM_CHALLENGE_BRANCH"
REPORT_HIGH_TURNOVER = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
REPORT_PROMOTE_NO_REVISION = "STEP6_INTEL_VALID_PROMOTE_NO_REVISION_NEEDED"
REPORT_MECHANISM_UNCLEAR = "STEP6_INTEL_MECHANISM_UNCLEAR_REVISION"
CASE_REPORT_IDS = [
    REPORT_COLD_START,
    REPORT_ALPHA013_LIKE,
    REPORT_HIGH_TURNOVER,
    REPORT_PROMOTE_NO_REVISION,
    REPORT_MECHANISM_UNCLEAR,
]
POLLUTION_MARKERS = ["STEP6_COUNCIL_PRIMARY", "factorforge_step6_council_primary", "STEP6_INTEL"]


def is_tmp(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve())
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if item.is_file():
                files.add(str(item.relative_to(REPO_ROOT)))
    return files


def canonical_pollution_matches(new_files: set[str], report_ids: list[str]) -> list[str]:
    needles = sorted(set(report_ids + POLLUTION_MARKERS))
    return sorted(item for item in new_files if any(needle in item for needle in needles))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


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
        entries.append(
            {
                "relative_path": rel.as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(item),
            }
        )
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_cmd(root: Path, cmd: list[str], extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {
        "command": cmd,
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
    }


def proof_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_run_report__{report_id}.json"


def iteration_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"


def iteration(root: Path, report_id: str) -> dict[str, Any]:
    return load_json(iteration_path(root, report_id))


def final_strategy(root: Path, report_id: str) -> dict[str, Any]:
    return (((iteration(root, report_id).get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})


def run_ultimate(root: Path, report_id: str, mode: str, extra_env: dict[str, str] | None = None, extra_args: list[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    cmd = [
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--report-id",
        report_id,
        "--start-step",
        "6",
        "--end-step",
        "6",
        "--skip-researcher-packets",
        "--factorforge-root",
        str(root),
        "--allow-legacy-global-runtime",
        "--allow-legacy-research-protocol-smoke",
        "--council-mode",
        mode,
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = run_cmd(root, cmd, extra_env=extra_env)
    return result, load_json(proof_path(root, report_id))


def result(case: str, ok: bool, actual: dict[str, Any], expected: str) -> dict[str, Any]:
    return {"case": case, "ok": bool(ok), "expected": expected, "actual": actual}


def setup_step6_fixtures(root: Path) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "scripts/run_step6_intelligence_smoke.py", "--fresh", "--root", str(root)])


def case_off(root: Path) -> dict[str, Any]:
    rid = REPORT_COLD_START
    proc, proof = run_ultimate(root, rid, "off")
    rc = proof.get("revision_council") or {}
    attached = bool(iteration(root, rid).get("revision_council_ref"))
    ok = proc["rc"] == 0 and proof.get("status") == "PASS" and rc.get("status") == "skipped" and not attached
    return result("council_mode_off", ok, {"run": proc, "revision_council": rc, "revision_council_ref_attached": attached}, "off preserves old behavior")


def case_scaffold(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    before_code = directory_digest(root / "generated_code" / rid)
    before_clean = directory_digest(root / "data" / "clean")
    proc, proof = run_ultimate(root, rid, "scaffold")
    after_code = directory_digest(root / "generated_code" / rid)
    after_clean = directory_digest(root / "data" / "clean")
    rc = proof.get("revision_council") or {}
    strategy = final_strategy(root, rid)
    ok = (
        proc["rc"] == 0
        and proof.get("status") == "PASS"
        and rc.get("status") == "completed"
        and rc.get("attached") is True
        and strategy.get("source") == "revision_council"
        and strategy.get("loop_authorization") == "advisory_only"
        and not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists()
        and not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists()
        and before_code == after_code
        and before_clean == after_clean
    )
    return result("council_mode_scaffold", ok, {"run": proc, "revision_council": rc, "final_strategy": strategy, "generated_code_unchanged": before_code == after_code, "data_clean_unchanged": before_clean == after_clean}, "scaffold completes council chain")


def case_auto_revision_needed(root: Path) -> dict[str, Any]:
    rid = REPORT_HIGH_TURNOVER
    proc, proof = run_ultimate(root, rid, "auto", extra_args=["--auto-council-policy", "scaffold"])
    rc = proof.get("revision_council") or {}
    strategy = final_strategy(root, rid)
    ok = proc["rc"] == 0 and rc.get("status") == "completed" and strategy.get("source") == "revision_council"
    return result("council_mode_auto_revision_needed_scaffold_policy", ok, {"run": proc, "revision_council": rc, "final_strategy": strategy}, "auto may run scaffold only with explicit scaffold policy")


def case_auto_revision_needed_dispatch_default(root: Path) -> dict[str, Any]:
    rid = REPORT_MECHANISM_UNCLEAR
    proc, proof = run_ultimate(root, rid, "auto")
    rc = proof.get("revision_council") or {}
    strategy = final_strategy(root, rid)
    ok = (
        proc["rc"] == 0
        and proof.get("status") == "PASS"
        and rc.get("status") == "awaiting_agent_results"
        and rc.get("effective_mode") == "agentic_dispatch_manifest"
        and rc.get("formal_council_status") == "awaiting_agent_results"
        and rc.get("deterministic_scaffold_used") is False
        and rc.get("deterministic_scaffold_formal") is False
        and strategy.get("source") != "revision_council"
    )
    return result("council_mode_auto_revision_needed_dispatch_default", ok, {"run": proc, "revision_council": rc, "final_strategy": strategy}, "auto defaults to dispatch manifest and awaits agent results")


def case_auto_no_revision(root: Path) -> dict[str, Any]:
    rid = REPORT_PROMOTE_NO_REVISION
    proc, proof = run_ultimate(root, rid, "auto")
    rc = proof.get("revision_council") or {}
    ok = proc["rc"] == 0 and proof.get("status") == "PASS" and rc.get("status") == "not_triggered" and rc.get("reason") == "no_revision_needed"
    return result("council_mode_auto_no_revision_needed", ok, {"run": proc, "revision_council": rc}, "auto skips no-revision promote")


def case_agentic_block(root: Path) -> dict[str, Any]:
    rid = REPORT_COLD_START
    council_dir = root / "objects" / "research_iteration_master" / "revision_council" / rid
    if council_dir.exists():
        shutil.rmtree(council_dir)
    proc, proof = run_ultimate(root, rid, "agentic")
    token = "BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED"
    ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"]) and not council_dir.exists() and (proof.get("revision_council") or {}).get("status") == "blocked"
    return result("council_mode_agentic_requires_executor", ok, {"run": proc, "revision_council": proof.get("revision_council"), "council_dir_exists": council_dir.exists()}, token)


def case_command_failure(root: Path) -> dict[str, Any]:
    rid = REPORT_MECHANISM_UNCLEAR
    proc, proof = run_ultimate(root, rid, "scaffold", {"FACTORFORGE_ULTIMATE_TEST_FAIL_COUNCIL_COMMAND": "attach_revision_council_to_step6"})
    rc = proof.get("revision_council") or {}
    ok = proc["rc"] == 1 and rc.get("status") == "failed" and rc.get("failing_command") == "attach_revision_council_to_step6" and proof.get("status") == "FAIL"
    return result("council_command_failure_blocks_wrapper", ok, {"run": proc, "revision_council": rc}, "council subcommand failure fails wrapper")


def case_side_effect_guard(root: Path) -> dict[str, Any]:
    rid = REPORT_ALPHA013_LIKE
    proc, proof = run_ultimate(root, rid, "scaffold", {"FACTORFORGE_ULTIMATE_TEST_MUTATE_GENERATED_CODE_AFTER_COUNCIL": "1"})
    rc = proof.get("revision_council") or {}
    token = "BLOCK_REVISION_COUNCIL_WRAPPER_FORBIDDEN_SIDE_EFFECT"
    ok = proc["rc"] == 1 and token in (proc["stdout_tail"] + proc["stderr_tail"]) and rc.get("block_reason") == token and proof.get("status") == "FAIL"
    return result("council_forbidden_side_effect_block", ok, {"run": proc, "revision_council": rc}, token)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_step6_council_primary_{int(time.time())}")
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
    fixture = setup_step6_fixtures(root)
    cases.append(result("step6_intelligence_fixture", fixture["rc"] == 0, {"fixture": fixture}, "Step6 fixture setup"))
    if fixture["rc"] == 0:
        cases.extend(
            [
                case_off(root),
                case_scaffold(root),
                case_auto_revision_needed(root),
                case_auto_revision_needed_dispatch_default(root),
                case_auto_no_revision(root),
                case_agentic_block(root),
                case_command_failure(root),
                case_side_effect_guard(root),
            ]
        )

    after = file_snapshot()
    new_files = sorted(after - before)
    pollution = canonical_pollution_matches(set(new_files), CASE_REPORT_IDS)
    verdict = "ACCEPT" if all(item["ok"] for item in cases) and not pollution else "BLOCK"
    summary = {
        "verdict": verdict,
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution, "checked_report_ids": CASE_REPORT_IDS},
        "notes": ["Synthetic /tmp-only council-primary wrapper smoke.", "No real search worker, clean data processing, or Step3B code modification."],
    }
    summary_path = root / "step6_council_primary_smoke_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
