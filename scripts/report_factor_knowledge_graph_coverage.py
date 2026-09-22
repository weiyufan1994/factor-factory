#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
GRAPH_NODES_DIR = KNOWLEDGE_ROOT / "graph" / "nodes"

LIBRARY_DIRS = {
    "ordinary_factor_library": KNOWLEDGE_ROOT / "普通因子库",
    "official_factor_library": KNOWLEDGE_ROOT / "正式因子库",
    "research_knowledge_base": KNOWLEDGE_ROOT / "知识库",
    "research_iterations": KNOWLEDGE_ROOT / "研究迭代",
}

HIGH_PRIORITY_PATTERNS = [
    "MONEYFLOW",
    "VP_",
    "CS_RESIDUAL",
    "CPV",
    "ALPHA007",
    "ALPHA013",
    "ALPHA014",
    "ALPHA015",
    "ALPHA036",
    "ALPHA038",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_md_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.glob("*.md") if p.is_file())


def normalize_rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def node_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(GRAPH_NODES_DIR.glob("*.json")):
        node = load_json(path)
        rows.append(
            {
                "id": node.get("id"),
                "node_type": node.get("node_type"),
                "title": node.get("title"),
                "research_status": (node.get("taxonomy") or {}).get("research_status") or [],
                "source_paths": node.get("source_paths") or [],
                "source_node_path": normalize_rel(path),
            }
        )
    return rows


def build_coverage() -> dict[str, Any]:
    nodes = node_records()
    covered_paths = {path for node in nodes for path in node.get("source_paths") or []}
    covered_basenames = {Path(path).name for path in covered_paths}

    libraries: dict[str, Any] = {}
    missing_high_priority: list[dict[str, Any]] = []
    for library_name, library_dir in LIBRARY_DIRS.items():
        files = list_md_files(library_dir)
        records = []
        covered_count = 0
        for path in files:
            rel = normalize_rel(path)
            basename = path.name
            covered = rel in covered_paths or basename in covered_basenames
            if covered:
                covered_count += 1
            high_priority = any(pattern in basename.upper() for pattern in HIGH_PRIORITY_PATTERNS)
            if high_priority and not covered:
                missing_high_priority.append(
                    {
                        "library": library_name,
                        "path": rel,
                        "reason": "matches high-priority migration pattern but has no graph node source_path",
                    }
                )
            records.append({"path": rel, "covered_by_graph": covered, "high_priority": high_priority})
        libraries[library_name] = {
            "path": normalize_rel(library_dir),
            "record_count": len(files),
            "covered_count": covered_count,
            "coverage_ratio": round(covered_count / len(files), 4) if files else None,
            "high_priority_missing_count": sum(1 for record in records if record["high_priority"] and not record["covered_by_graph"]),
            "records": records,
        }

    node_status_counts = Counter(status for node in nodes for status in node.get("research_status") or [])
    return {
        "schema_version": "factor_knowledge_graph_coverage_v1",
        "created_at_utc": utc_now(),
        "graph_node_count": len(nodes),
        "graph_nodes": nodes,
        "node_status_counts": dict(sorted(node_status_counts.items())),
        "libraries": libraries,
        "missing_high_priority": missing_high_priority,
        "migration_guidance": [
            "Coverage ratio is informational, not a blocker; the historical vault is large and should be migrated gradually.",
            "Prioritize records with strong reusable mechanisms, official/candidate status, or repeated failure modes.",
            "Each migrated record must pass run_factor_knowledge_network_readiness.py node quality checks.",
        ],
    }


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# Factor Knowledge Graph Coverage",
        "",
        f"Generated: `{payload['created_at_utc']}`",
        "",
        f"Graph nodes: `{payload['graph_node_count']}`",
        "",
        "## Library Coverage",
        "",
        "| Library | Records | Covered | Ratio | High-priority missing |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, stats in payload["libraries"].items():
        ratio = stats["coverage_ratio"]
        ratio_text = "" if ratio is None else f"{ratio:.2%}"
        lines.append(
            f"| `{name}` | {stats['record_count']} | {stats['covered_count']} | {ratio_text} | {stats['high_priority_missing_count']} |"
        )
    lines.extend(["", "## Graph Nodes", ""])
    for node in payload["graph_nodes"]:
        lines.append(f"- `{node['id']}` ({', '.join(node.get('research_status') or [])})")
    lines.extend(["", "## High-Priority Missing", ""])
    if payload["missing_high_priority"]:
        for item in payload["missing_high_priority"][:100]:
            lines.append(f"- `{item['path']}` - {item['reason']}")
    else:
        lines.append("None.")
    lines.extend(["", "## Guidance", ""])
    for item in payload["migration_guidance"]:
        lines.append(f"- {item}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compact_summary(payload: dict[str, Any]) -> dict[str, Any]:
    libraries = payload.get("libraries") or {}
    return {
        "schema_version": payload.get("schema_version"),
        "created_at_utc": payload.get("created_at_utc"),
        "graph_node_count": payload.get("graph_node_count"),
        "node_status_counts": payload.get("node_status_counts") or {},
        "library_coverage": {
            name: {
                "record_count": stats.get("record_count"),
                "covered_count": stats.get("covered_count"),
                "coverage_ratio": stats.get("coverage_ratio"),
                "high_priority_missing_count": stats.get("high_priority_missing_count"),
            }
            for name, stats in libraries.items()
        },
        "missing_high_priority_count": len(payload.get("missing_high_priority") or []),
        "missing_high_priority_preview": payload.get("missing_high_priority", [])[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report Factor Knowledge Graph coverage over the human-readable vault.")
    parser.add_argument("--json-output", help="Optional path to write JSON coverage payload.")
    parser.add_argument("--markdown-output", help="Optional path to write Markdown coverage summary.")
    parser.add_argument("--full-stdout", action="store_true", help="Print the full coverage payload instead of compact summary.")
    args = parser.parse_args()

    payload = build_coverage()
    if args.json_output:
        out = Path(args.json_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_output:
        write_markdown(payload, Path(args.markdown_output))
    stdout_payload = payload if args.full_stdout else compact_summary(payload)
    print(json.dumps(stdout_payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
