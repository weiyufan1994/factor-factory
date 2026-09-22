#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FACTOR_RESEARCH_ROOT = REPO_ROOT / "factor_research"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "operations" / "factorforge-workspace-migration-plan-20260623.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_id(value: Any) -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value or "")).strip("._-")
    return text or "unknown"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_count(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file())


def classify(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    two_level: list[dict[str, Any]] = []
    legacy_one_level: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    if not root.exists():
        return {
            "root": str(root),
            "exists": False,
            "two_level": [],
            "legacy_one_level": [],
            "quarantine": [],
            "invalid": [],
            "proposed_moves": [],
        }

    for child in sorted(item for item in root.iterdir() if item.is_dir()):
        if child.name.startswith("__") or child.name == "_quarantine":
            continue
        top_manifest = child / "manifest.json"
        child_manifests = sorted(child.glob("*/manifest.json"))
        if top_manifest.exists():
            try:
                manifest = load_json(top_manifest)
            except Exception as exc:
                invalid.append({"path": str(child), "reason": f"manifest_json_invalid: {exc}"})
                continue
            factor_id = safe_id(manifest.get("factor_id") or manifest.get("factor") or child.name)
            research_id = safe_id(manifest.get("research_id") or manifest.get("research") or child.name)
            target = root / factor_id / research_id
            legacy_one_level.append(
                {
                    "source": str(child),
                    "target": str(target),
                    "factor_id": factor_id,
                    "research_id": research_id,
                    "file_count": file_count(child),
                    "target_exists": target.exists(),
                    "status": "BLOCK_TARGET_EXISTS" if target.exists() else "MOVE_CANDIDATE",
                }
            )
        elif child_manifests:
            for manifest_path in child_manifests:
                try:
                    manifest = load_json(manifest_path)
                except Exception as exc:
                    invalid.append({"path": str(manifest_path), "reason": f"manifest_json_invalid: {exc}"})
                    continue
                two_level.append(
                    {
                        "workspace": str(manifest_path.parent),
                        "relative_manifest": str(manifest_path.relative_to(root)),
                        "factor_id": manifest.get("factor_id"),
                        "research_id": manifest.get("research_id"),
                        "file_count": file_count(manifest_path.parent),
                        "status": "OK_TWO_LEVEL" if manifest.get("factor_id") and manifest.get("research_id") else "WARN_IDENTITY_INCOMPLETE",
                    }
                )
        else:
            quarantine_root = root / "_quarantine"
            target = quarantine_root / ("generated_cache" if child.name == ".cache" else "legacy_unmanifested") / child.name
            quarantine.append(
                {
                    "source": str(child),
                    "target": str(target),
                    "file_count": file_count(child),
                    "target_exists": target.exists(),
                    "status": "BLOCK_TARGET_EXISTS" if target.exists() else "QUARANTINE_CANDIDATE",
                    "reason": "generated_cache" if child.name == ".cache" else "missing_manifest",
                }
            )

    return {
        "root": str(root),
        "exists": True,
        "two_level": two_level,
        "legacy_one_level": legacy_one_level,
        "quarantine": quarantine,
        "invalid": invalid,
        "proposed_moves": legacy_one_level + quarantine,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan Factor Forge factor_research workspace migration without moving files.")
    parser.add_argument("--factor-research-root", default=str(DEFAULT_FACTOR_RESEARCH_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.factor_research_root)
    plan = {
        "contract_version": "factorforge_workspace_migration_plan_v1",
        "created_at_utc": utc_now(),
        "dry_run_only": True,
        "destructive_actions": False,
        "root": str(root.expanduser().resolve()),
        "classification": classify(root),
        "execution_policy": {
            "no_git_add_dot": True,
            "manual_review_required_before_move": True,
            "block_on_existing_target": True,
            "do_not_touch_global_factorforge_objects_or_runs": True,
        },
    }
    output = Path(args.output).expanduser()
    if not args.no_write:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    if not args.no_write:
        print(f"[WRITE] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
