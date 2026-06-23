#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
GRAPH_ROOT = KNOWLEDGE_ROOT / "graph"
NODES_DIR = GRAPH_ROOT / "nodes"
TEMPLATES_DIR = GRAPH_ROOT / "templates"
EXPORT_MANIFEST_DIR = KNOWLEDGE_ROOT / "export_manifest"

STATIC_ALLOWED_PATHS = {
    "docs/architecture/factor-knowledge-network-v1.zh-CN.md",
    "docs/operations/factor-knowledge-network-v1-commit-scope-20260618.zh-CN.md",
    "factor_factory/knowledge_context.py",
    "scripts/build_factor_knowledge_graph.py",
    "scripts/query_factor_knowledge_graph.py",
    "scripts/report_factor_knowledge_graph_coverage.py",
    "scripts/retrieve_factor_knowledge_context.py",
    "scripts/run_factor_knowledge_graph_smoke.py",
    "scripts/run_factor_knowledge_network_readiness.py",
    "scripts/run_factor_knowledge_step1_context_smoke.py",
    "scripts/run_factor_knowledge_step2_context_smoke.py",
    "scripts/run_factor_knowledge_step6_context_smoke.py",
    "scripts/validate_factor_knowledge_commit_scope.py",
    "scripts/validate_factor_knowledge_node.py",
    "skills/factor-forge-researcher/SKILL.md",
    "skills/factor-forge-step1/SKILL.md",
    "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py",
    "skills/factor-forge-step1/scripts/validate_step1.py",
    "skills/factor-forge-step2/SKILL.md",
    "skills/factor-forge-step2/scripts/run_step2.py",
    "skills/factor-forge-step2/scripts/validate_step2.py",
    "skills/factor-forge-step6/SKILL.md",
    "skills/factor-forge-step6/scripts/run_step6.py",
}


def run_git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def dynamic_force_add_paths() -> set[str]:
    paths = {
        repo_relative(KNOWLEDGE_ROOT / "taxonomy" / "factor_taxonomy_v1.json"),
        repo_relative(GRAPH_ROOT / "factor_knowledge_nodes.jsonl"),
        repo_relative(GRAPH_ROOT / "factor_knowledge_edges.jsonl"),
        repo_relative(GRAPH_ROOT / "factor_knowledge_graph_manifest.json"),
        repo_relative(GRAPH_ROOT / "factor_knowledge_coverage.json"),
        repo_relative(KNOWLEDGE_ROOT / "仪表盘" / "知识网络.md"),
        repo_relative(KNOWLEDGE_ROOT / "仪表盘" / "知识网络覆盖率.md"),
    }
    paths.update(repo_relative(path) for path in sorted(NODES_DIR.glob("*.json")))
    paths.update(repo_relative(path) for path in sorted(TEMPLATES_DIR.glob("*")) if path.is_file())
    paths.update(repo_relative(path) for path in sorted(EXPORT_MANIFEST_DIR.glob("*.json")) if path.is_file())
    return paths


def staged_paths() -> set[str]:
    stdout = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    return {part for part in stdout.split("\0") if part}


def existing_allowed_paths() -> set[str]:
    force_add_paths = dynamic_force_add_paths()
    all_paths = STATIC_ALLOWED_PATHS | force_add_paths
    return {path for path in all_paths if (REPO_ROOT / path).exists()}


def build_payload(check_complete: bool, staged_override: set[str] | None = None) -> dict[str, Any]:
    force_add_paths = sorted(dynamic_force_add_paths())
    allowed_paths = sorted(existing_allowed_paths())
    staged = sorted(staged_override if staged_override is not None else staged_paths())
    staged_set = set(staged)
    allowed_set = set(allowed_paths)
    unexpected = sorted(staged_set - allowed_set)
    missing_required = sorted(allowed_set - staged_set) if check_complete else []
    verdict = "ACCEPT" if not unexpected and not missing_required else "BLOCK"
    return {
        "schema_version": "factor_knowledge_commit_scope_v1",
        "verdict": verdict,
        "staged_count": len(staged),
        "staged_paths": staged,
        "staged_source": "argument" if staged_override is not None else "git_index",
        "allowed_count": len(allowed_paths),
        "allowed_paths": allowed_paths,
        "unexpected_staged_paths": unexpected,
        "check_complete": check_complete,
        "missing_required_paths": missing_required,
        "force_add_required": True,
        "force_add_paths": force_add_paths,
        "force_add_command": "git add -f " + " ".join(force_add_paths),
        "notes": [
            "This validator is scoped to Factor Knowledge Network v1 only.",
            "Do not use git add knowledge/因子工厂; force-add only force_add_paths.",
            "Unrelated research workspaces, objects, output, data, and Data API feedback docs are outside this commit scope.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate staged files for Factor Knowledge Network v1 commits.")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Require every currently existing knowledge-network file in the allowlist to be staged.",
    )
    parser.add_argument(
        "--print-force-add",
        action="store_true",
        help="Print only the exact git add -f command for ignored graph/taxonomy/dashboard files.",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        help="Validate an explicit path list instead of the current git index. Used for side-effect-free positive/negative tests.",
    )
    args = parser.parse_args()

    staged_override = set(args.paths) if args.paths is not None else None
    payload = build_payload(check_complete=args.require_complete, staged_override=staged_override)
    if args.print_force_add:
        print(payload["force_add_command"])
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if payload["verdict"] != "ACCEPT":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
