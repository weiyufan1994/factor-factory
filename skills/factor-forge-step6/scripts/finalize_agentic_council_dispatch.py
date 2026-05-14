#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validate_agentic_council_result import validate_agentic_result

OBJ = FF / "objects"
TOKEN_REQUIRED_RESULT_MISSING = "BLOCK_AGENTIC_COUNCIL_REQUIRED_RESULT_MISSING"
TOKEN_RESULT_INVALID = "BLOCK_AGENTIC_COUNCIL_RESULT_INVALID"
TOKEN_FORBIDDEN_SIDE_EFFECT = "BLOCK_AGENTIC_COUNCIL_FINALIZE_FORBIDDEN_SIDE_EFFECT"
TOKEN_COLLECTION_MISSING = "BLOCK_AGENTIC_COUNCIL_COLLECTION_MISSING"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip_digest_path(path: Path) -> bool:
    name = path.name
    return name in {"__pycache__", ".DS_Store"} or name.endswith((".lock", ".tmp", ".swp", ".swx"))


def directory_digest(path: Path) -> str:
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
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def path_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "kind": None, "sha256": None, "digest": None}
    if path.is_file():
        return {"path": str(path), "exists": True, "kind": "file", "sha256": sha256_file(path), "digest": None}
    if path.is_dir():
        return {"path": str(path), "exists": True, "kind": "directory", "sha256": None, "digest": directory_digest(path)}
    return {"path": str(path), "exists": True, "kind": "other", "sha256": None, "digest": None}


def side_effect_snapshot(report_id: str) -> dict[str, dict[str, Any]]:
    return {
        "step3b_handoff": path_snapshot(OBJ / "handoff" / f"handoff_to_step3b__{report_id}.json"),
        "generated_code": path_snapshot(FF / "generated_code" / report_id),
        "official_record": path_snapshot(OBJ / "factor_library_official" / f"factor_record__{report_id}.json"),
        "data_clean": path_snapshot(FF / "data" / "clean"),
    }


def side_effect_changes(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key, old in before.items():
        new = after.get(key) or {}
        if (
            old.get("exists") != new.get("exists")
            or old.get("kind") != new.get("kind")
            or old.get("sha256") != new.get("sha256")
            or old.get("digest") != new.get("digest")
        ):
            changes.append({"path_key": key, "before": old, "after": new})
    return changes


def run_step(name: str, command: list[str], env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {
        "name": name,
        "command": command,
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def block(token: str, payload: dict[str, Any]) -> None:
    print(token + ": " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    manifest_path = council_dir / f"dispatch_manifest__{rid}.json"
    collection_path = council_dir / f"agentic_result_collection__{rid}.json"
    if not manifest_path.exists():
        block("BLOCK_AGENTIC_COUNCIL_DISPATCH_MANIFEST_MISSING", {"report_id": rid, "manifest_path": str(manifest_path)})
    if not collection_path.exists():
        block(TOKEN_COLLECTION_MISSING, {"report_id": rid, "collection_path": str(collection_path)})
    manifest = load_json(manifest_path)
    missing: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    result_paths: list[str] = []
    for task in manifest.get("agent_tasks") or []:
        if not isinstance(task, dict) or task.get("required") is not True:
            continue
        raw_path = task.get("expected_result_path")
        path = Path(raw_path) if isinstance(raw_path, str) else Path()
        path = path if path.is_absolute() else FF / path
        if not path.exists():
            missing.append({"task_id": task.get("task_id"), "expected_result_path": str(path)})
            continue
        result_paths.append(str(path))
        try:
            reasons = validate_agentic_result(load_json(path))
        except Exception as exc:
            reasons = [f"agentic_result_unreadable:{exc}"]
        if reasons:
            invalid.append({"task_id": task.get("task_id"), "result_path": str(path), "block_reasons": reasons})
    if missing:
        block(TOKEN_REQUIRED_RESULT_MISSING, {"report_id": rid, "missing_results": missing})
    if invalid:
        block(TOKEN_RESULT_INVALID, {"report_id": rid, "invalid_results": invalid})

    before = side_effect_snapshot(rid)
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(FF)
    py = sys.executable
    steps = [
        ("validate_agentic_council_dispatch", [py, "skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py", "--report-id", rid]),
        ("validate_agentic_council_collection", [py, "skills/factor-forge-step6/scripts/validate_agentic_council_collection.py", "--report-id", rid]),
        ("validate_agentic_council_result", [py, "skills/factor-forge-step6/scripts/validate_agentic_council_result.py", "--report-id", rid]),
        ("merge_revision_council", [py, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid]),
        ("build_council_derivation_appendix", [py, "skills/factor-forge-step6/scripts/build_council_derivation_appendix.py", "--report-id", rid]),
        ("attach_revision_council_to_step6", [py, "skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py", "--report-id", rid]),
        ("validate_step6", [py, "skills/factor-forge-step6/scripts/validate_step6.py", "--report-id", rid]),
    ]
    runs = []
    for name, command in steps:
        run = run_step(name, command, env)
        runs.append(run)
        if run["rc"] != 0:
            print(json.dumps({"report_id": rid, "result": "BLOCK", "failing_step": name, "runs": runs}, ensure_ascii=False, indent=2))
            return int(run["rc"] or 1)
    after = side_effect_snapshot(rid)
    changes = side_effect_changes(before, after)
    if changes:
        block(TOKEN_FORBIDDEN_SIDE_EFFECT, {"report_id": rid, "side_effect_changes": changes})
    print(
        json.dumps(
            {
                "report_id": rid,
                "result": "PASS",
                "required_result_count": len(result_paths),
                "result_paths": result_paths,
                "runs": runs,
                "side_effects_unchanged": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
