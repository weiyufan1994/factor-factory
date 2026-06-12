#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN,
    assert_path_under_workspace,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)

DEFAULT_REGISTRY = REPO_ROOT / "data" / "alpha101_registry" / "alpha101_registry.json"
DEFAULT_KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "alpha101_registry" / "alpha101_research_queue.json"


def load_workspace(root: Path) -> dict:
    manifest_path = workspace_manifest_path(root)
    if not manifest_path.exists():
        raise SystemExit(f"BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID: missing {manifest_path}")
    manifest = load_workspace_manifest(manifest_path)
    failures = validate_workspace_manifest(manifest)
    if failures:
        raise SystemExit("\n".join(failures))
    return manifest


def extract_decision(text: str) -> str | None:
    match = re.search(r"decision:\s*[\"']?([A-Za-z0-9_\-]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"- decision:\s*`([^`]+)`", text)
    if match:
        return match.group(1)
    return None


def scan_knowledge(knowledge_root: Path) -> dict[str, list[dict[str, str]]]:
    by_factor: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in sorted(knowledge_root.rglob("ALPHA*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        factor_match = re.search(r"factor_id:\s*[\"']?(Alpha\d{3}|Alpha\d{1,2})", text, flags=re.IGNORECASE)
        if factor_match:
            factor_id = factor_match.group(1)
        else:
            stem_match = re.search(r"ALPHA(\d{3})", path.name, flags=re.IGNORECASE)
            if not stem_match:
                continue
            factor_id = f"Alpha{int(stem_match.group(1)):03d}"
        number_match = re.search(r"\d+", factor_id)
        if not number_match:
            continue
        normalized = f"Alpha{int(number_match.group(0)):03d}"
        by_factor[normalized].append(
            {
                "path": str(path),
                "decision": extract_decision(text) or "unknown",
                "library": path.parent.name,
            }
        )
    return by_factor


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ordered Alpha101 research queue from registry and current knowledge files.")
    parser.add_argument("--workspace-root")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--knowledge-root")
    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.workspace_root:
        print(BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN, file=sys.stderr)
        return 1
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_manifest = load_workspace(workspace_root)
    registry_path = Path(args.registry).expanduser().resolve()
    knowledge_root = (
        Path(args.knowledge_root).expanduser().resolve()
        if args.knowledge_root
        else workspace_root / "knowledge" / "human_readable"
    )
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else workspace_root / "knowledge" / "canonical" / "alpha101_research_queue.json"
    )
    assert_path_under_workspace(knowledge_root, workspace_root, label="alpha101_knowledge_root")
    assert_path_under_workspace(output, workspace_root, label="alpha101_research_queue")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    knowledge = scan_knowledge(knowledge_root)

    queue = []
    for row in registry["records"]:
        factor_id = row["factor_id"]
        records = knowledge.get(factor_id, [])
        decisions = sorted({r["decision"] for r in records})
        queue.append(
            {
                "alpha_no": row["alpha_no"],
                "factor_id": factor_id,
                "report_id": row["report_id"],
                "status": "researched" if records else "pending",
                "decisions": decisions,
                "knowledge_records": records,
                "formula": row["formula"],
            }
        )

    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(workspace_root),
        "factor_id": workspace_manifest.get("factor_id"),
        "research_id": workspace_manifest.get("research_id"),
        "registry": str(registry_path),
        "knowledge_root": str(knowledge_root),
        "counts": {
            "total": len(queue),
            "researched": sum(1 for row in queue if row["status"] == "researched"),
            "pending": sum(1 for row in queue if row["status"] == "pending"),
        },
        "queue": queue,
    }
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote queue to {output}")
    print(json.dumps(payload["counts"], ensure_ascii=False, sort_keys=True))
    next_pending = next((row for row in queue if row["status"] == "pending"), None)
    if next_pending:
        print(f"next_pending={next_pending['factor_id']} report_id={next_pending['report_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
