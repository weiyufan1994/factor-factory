#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPO_ROOT / "docs" / "operations" / "factorforge-workspace-migration-plan-20260623.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_count(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file())


def migration_manifest(source: Path, target: Path, item: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "contract_version": "factorforge_workspace_migration_record_v1",
        "moved_at_utc": utc_now(),
        "source_path": str(source),
        "target_path": str(target),
        "factor_id": item.get("factor_id"),
        "research_id": item.get("research_id"),
        "file_count_after_move": file_count(target),
        "migration_reason": item.get("reason") or mode,
        "migration_mode": mode,
        "destructive_actions": False,
        "overwrite": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply reviewed Factor Forge legacy workspace migration plan.")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument(
        "--mode",
        choices=("legacy", "quarantine"),
        default="legacy",
        help="Move reviewed legacy workspaces or quarantine candidates from the plan.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually move directories. Without this flag, only dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan_path = Path(args.plan).expanduser()
    plan = load_json(plan_path)
    if plan.get("contract_version") != "factorforge_workspace_migration_plan_v1":
        raise SystemExit(f"unsupported plan contract: {plan.get('contract_version')}")
    if plan.get("dry_run_only") is not True or plan.get("destructive_actions") is not False:
        raise SystemExit("refusing plan without dry_run_only=true and destructive_actions=false")

    moves = []
    if args.mode == "legacy":
        plan_items = plan.get("classification", {}).get("legacy_one_level", [])
        expected_status = "MOVE_CANDIDATE"
    else:
        plan_items = plan.get("classification", {}).get("quarantine", [])
        expected_status = "QUARANTINE_CANDIDATE"

    for item in plan_items:
        if item.get("status") != expected_status:
            continue
        source = Path(str(item.get("source") or "")).expanduser()
        target = Path(str(item.get("target") or "")).expanduser()
        if not source.exists():
            raise SystemExit(f"source missing: {source}")
        if not source.is_dir():
            raise SystemExit(f"source is not directory: {source}")
        if target.exists():
            raise SystemExit(f"target already exists: {target}")
        if target in source.parents or source in target.parents:
            raise SystemExit(f"refusing nested source/target move: {source} -> {target}")
        moves.append((source, target, item))

    result = {
        "contract_version": "factorforge_workspace_migration_apply_report_v1",
        "created_at_utc": utc_now(),
        "plan_path": str(plan_path),
        "apply": bool(args.apply),
        "mode": args.mode,
        "move_count": len(moves),
        "moves": [
            {
                "source": str(source),
                "target": str(target),
                "factor_id": item.get("factor_id"),
                "research_id": item.get("research_id"),
                "reason": item.get("reason"),
                "file_count_before": file_count(source),
                "status": "DRY_RUN" if not args.apply else "PENDING",
            }
            for source, target, item in moves
        ],
    }

    if args.apply:
        for row, (source, target, item) in zip(result["moves"], moves):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            record = migration_manifest(source, target, item, args.mode)
            write_json(target / "migration_manifest.json", record)
            row["status"] = "MOVED"
            row["migration_manifest"] = str(target / "migration_manifest.json")
            row["file_count_after"] = file_count(target)

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
