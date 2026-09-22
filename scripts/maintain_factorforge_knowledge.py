#!/usr/bin/env python3
"""Record bounded local-IS maintenance facts without re-running research."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from factor_factory.research_knowledge_maintenance import (
    record_local_research_episode, refresh_episode_maintenance, write_latest_maintenance_report,
)


def _safe_proof(workspace: Path, report_id: str, supplied: str | None) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,191}", report_id):
        raise ValueError("invalid_report_id")
    workspace = workspace.resolve(strict=True)
    default = workspace / "objects" / "runtime_context" / f"ultimate_run_report__{report_id}.json"
    lexical = Path(supplied) if supplied else default
    if lexical.is_symlink() or lexical != default or not lexical.is_file():
        raise ValueError("proof_path_invalid")
    resolved = lexical.resolve(strict=True)
    if not resolved.is_relative_to(workspace):
        raise ValueError("proof_path_outside_workspace")
    return resolved


def _maintenance_projection(raw: dict[str, Any]) -> dict[str, Any]:
    commands = raw.get("commands") if isinstance(raw.get("commands"), list) else []
    return {
        "factor_id": raw.get("factor_id"), "status": raw.get("status"),
        "failure": raw.get("failure"),
        "formal_command_contract": raw.get("formal_command_contract"),
        "contract_smoke_only": raw.get("contract_smoke_only") is True,
        "commands": [{key: row.get(key) for key in ("name", "status", "returncode")}
                     for row in commands if isinstance(row, dict)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--proof", default=None)
    args = parser.parse_args()
    workspace = Path(args.workspace_root)
    proof_path = _safe_proof(workspace, args.report_id, args.proof)
    # The source proof is parsed only to the small, fixed maintenance projection;
    # command stdout/stderr tails and other large proof payloads are never copied.
    with proof_path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict) or raw.get("execution_scope") != "local_is_only":
        raise SystemExit("BLOCK_FACTORFORGE_MAINTENANCE_LOCAL_IS_PROOF_REQUIRED")
    proof = _maintenance_projection(raw)
    result = record_local_research_episode(
        proof=proof, workspace=workspace, repo_root=ROOT, report_id=args.report_id,
        dry_run=bool(raw.get("dry_run")), local_is_only=True,
    )
    if result.get("status") == "RECORDED":
        result["index_maintenance"] = refresh_episode_maintenance(
            workspace=workspace, repo_root=ROOT, report_id=args.report_id,
        )
    elif result.get("reason") == "completed_step6_uses_knowledge_record":
        from scripts.run_factorforge_ultimate import run_post_step6_knowledge_refresh_nonblocking
        result["completed_step6_maintenance"] = run_post_step6_knowledge_refresh_nonblocking(
            args=argparse.Namespace(report_id=args.report_id, dry_run=bool(raw.get("dry_run"))),
            proof=proof, factor_workspace=workspace,
        )
    result["maintenance_report"] = write_latest_maintenance_report(
        repo_root=ROOT, payload={"report_id": args.report_id, "proof": str(proof_path), "result": result},
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
