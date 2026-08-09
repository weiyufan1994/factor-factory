#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
KNOWLEDGE_PREFIX = "knowledge/因子工厂/"
EXPORT_MANIFEST_PREFIX = KNOWLEDGE_PREFIX + "export_manifest/"
EXPORT_MANIFEST_VERSION = "factorforge_repo_root_knowledge_export_manifest_v2"

STATIC_ALLOWED_PATHS = {
    "docs/architecture/factor-knowledge-network-v1.zh-CN.md",
    "docs/operations/factor-knowledge-network-v1-commit-scope-20260618.zh-CN.md",
    "factor_factory/knowledge_context.py",
    "scripts/build_factor_knowledge_export_manifest.py",
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def is_knowledge_payload_path(path: str) -> bool:
    candidate = Path(path)
    return (
        not candidate.is_absolute()
        and ".." not in candidate.parts
        and candidate.as_posix() == path
        and path.startswith(KNOWLEDGE_PREFIX)
        and not path.startswith(EXPORT_MANIFEST_PREFIX)
    )


def changed_paths_since(base_ref: str) -> set[str]:
    base_commit = run_git(["rev-parse", "--verify", f"{base_ref}^{{commit}}"])
    base_commit = base_commit.strip()
    committed = run_git(
        ["diff", "--name-only", "--diff-filter=ACMR", "-z", f"{base_commit}...HEAD"]
    )
    working = run_git(
        ["diff", "--name-only", "--diff-filter=ACMR", "-z", "HEAD"]
    )
    staged = run_git(
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    )
    return {
        item
        for raw in (committed, working, staged)
        for item in raw.split("\0")
        if item
    }


def validate_export_manifest(manifest_path: Path) -> dict[str, Any]:
    failures: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "verdict": "BLOCK",
            "manifest_path": str(manifest_path),
            "failures": [f"manifest_unreadable:{exc}"],
        }
    if manifest.get("contract_version") != EXPORT_MANIFEST_VERSION:
        failures.append("manifest_contract_version_invalid")
    if manifest.get("export_root") != "knowledge/因子工厂":
        failures.append("manifest_export_root_invalid")
    if manifest.get("export_target") != "repo_root_knowledge_vault":
        failures.append("manifest_export_target_invalid")

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        failures.append("manifest_files_missing")
        entries = []
    entry_paths: list[str] = []
    duplicate_paths: set[str] = set()
    seen_paths: set[str] = set()
    entry_failures: list[str] = []
    normalized_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            entry_failures.append(f"files[{index}]:not_object")
            continue
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not is_knowledge_payload_path(raw_path):
            entry_failures.append(f"files[{index}]:path_invalid")
            continue
        if raw_path in seen_paths:
            duplicate_paths.add(raw_path)
        seen_paths.add(raw_path)
        entry_paths.append(raw_path)
        path = REPO_ROOT / raw_path
        if not path.is_file():
            entry_failures.append(f"{raw_path}:missing")
            continue
        if path.is_symlink():
            entry_failures.append(f"{raw_path}:symlink_forbidden")
            continue
        try:
            path.resolve().relative_to(
                (REPO_ROOT / "knowledge" / "因子工厂").resolve()
            )
        except ValueError:
            entry_failures.append(f"{raw_path}:path_escape")
            continue
        if entry.get("bytes") != path.stat().st_size:
            entry_failures.append(f"{raw_path}:bytes_mismatch")
        if entry.get("sha256") != sha256_file(path):
            entry_failures.append(f"{raw_path}:sha256_mismatch")
        normalized_entries.append(
            {
                "path": raw_path,
                "bytes": entry.get("bytes"),
                "sha256": entry.get("sha256"),
            }
        )
    if duplicate_paths:
        failures.append(
            "manifest_duplicate_paths:" + ",".join(sorted(duplicate_paths))
        )
    failures.extend(entry_failures)
    if manifest.get("payload_snapshot_sha256") != stable_hash(
        normalized_entries
    ):
        failures.append("manifest_payload_snapshot_sha256_mismatch")

    scope = manifest.get("scope")
    required_payload_paths: set[str] = set()
    scope_resolved = False
    if not isinstance(scope, dict):
        failures.append("manifest_scope_missing")
    elif scope.get("mode") != "git_diff_payload_exact":
        failures.append("manifest_scope_mode_invalid")
    else:
        base_commit = scope.get("base_commit")
        if (
            not isinstance(base_commit, str)
            or len(base_commit) != 40
            or any(character not in "0123456789abcdef" for character in base_commit)
        ):
            failures.append("manifest_scope_base_commit_invalid")
        else:
            try:
                required_payload_paths = {
                    path
                    for path in changed_paths_since(base_commit)
                    if is_knowledge_payload_path(path)
                }
                scope_resolved = True
            except Exception as exc:
                failures.append(f"manifest_scope_git_diff_failed:{exc}")
        if scope.get("payload_count") != len(entries):
            failures.append("manifest_scope_payload_count_mismatch")
        if scope_resolved and scope.get("payload_count") != len(
            required_payload_paths
        ):
            failures.append("manifest_scope_required_payload_count_mismatch")
    if scope_resolved:
        missing = sorted(required_payload_paths - set(entry_paths))
        unexpected = sorted(set(entry_paths) - required_payload_paths)
        if missing:
            failures.append("manifest_scope_paths_missing:" + ",".join(missing))
        if unexpected:
            failures.append(
                "manifest_scope_paths_unexpected:" + ",".join(unexpected)
            )

    previous = manifest.get("previous_manifest")
    if previous is not None:
        if not isinstance(previous, dict):
            failures.append("manifest_previous_manifest_invalid")
        else:
            previous_path_raw = previous.get("path")
            previous_path = Path(str(previous_path_raw or ""))
            if (
                not isinstance(previous_path_raw, str)
                or previous_path.is_absolute()
                or ".." in previous_path.parts
                or not previous_path_raw.startswith(EXPORT_MANIFEST_PREFIX)
            ):
                failures.append("manifest_previous_manifest_path_invalid")
            else:
                resolved_previous = REPO_ROOT / previous_path
                if not resolved_previous.is_file() or resolved_previous.is_symlink():
                    failures.append("manifest_previous_manifest_missing")
                else:
                    if previous.get("bytes") != resolved_previous.stat().st_size:
                        failures.append("manifest_previous_manifest_bytes_mismatch")
                    if previous.get("sha256") != sha256_file(resolved_previous):
                        failures.append("manifest_previous_manifest_sha256_mismatch")

    return {
        "verdict": "ACCEPT" if not failures else "BLOCK",
        "manifest_path": repo_relative(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "entry_count": len(entries),
        "required_payload_count": len(required_payload_paths),
        "failures": failures,
    }


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


def build_payload(
    check_complete: bool,
    staged_override: set[str] | None = None,
    *,
    export_manifest: Path | None = None,
    export_only: bool = False,
) -> dict[str, Any]:
    force_add_paths = sorted(dynamic_force_add_paths())
    allowed_paths = sorted(existing_allowed_paths())
    staged = sorted(staged_override if staged_override is not None else staged_paths())
    staged_set = set(staged)
    allowed_set = set(allowed_paths)
    unexpected = [] if export_only else sorted(staged_set - allowed_set)
    missing_required = (
        []
        if export_only or not check_complete
        else sorted(allowed_set - staged_set)
    )
    changed_knowledge_payloads = sorted(
        path for path in staged_set if is_knowledge_payload_path(path)
    )
    staged_export_manifests = sorted(
        path
        for path in staged_set
        if path.startswith(EXPORT_MANIFEST_PREFIX) and path.endswith(".json")
    )
    provenance_failures: list[str] = []
    selected_manifest = export_manifest
    if selected_manifest is None and changed_knowledge_payloads:
        if len(staged_export_manifests) != 1:
            provenance_failures.append(
                "exactly_one_current_export_manifest_required"
            )
        else:
            selected_manifest = REPO_ROOT / staged_export_manifests[0]
    export_validation = None
    if selected_manifest is not None:
        export_validation = validate_export_manifest(selected_manifest)
        provenance_failures.extend(export_validation.get("failures") or [])
    verdict = (
        "ACCEPT"
        if not unexpected and not missing_required and not provenance_failures
        else "BLOCK"
    )
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
        "changed_knowledge_payload_paths": changed_knowledge_payloads,
        "staged_export_manifest_paths": staged_export_manifests,
        "export_manifest_validation": export_validation,
        "export_provenance_failures": provenance_failures,
        "export_only": export_only,
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
    parser.add_argument(
        "--export-manifest",
        help="Validate one current repo-root knowledge export manifest, including file bytes, SHA-256, and exact git-diff coverage.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Run only export provenance checks; do not apply the Factor Knowledge Network commit allowlist.",
    )
    args = parser.parse_args()

    staged_override = set(args.paths) if args.paths is not None else None
    payload = build_payload(
        check_complete=args.require_complete,
        staged_override=staged_override,
        export_manifest=(
            Path(args.export_manifest).expanduser().resolve()
            if args.export_manifest
            else None
        ),
        export_only=args.export_only,
    )
    if args.print_force_add:
        print(payload["force_add_command"])
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if payload["verdict"] != "ACCEPT":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
