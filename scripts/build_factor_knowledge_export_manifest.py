#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PREFIX = "knowledge/因子工厂/"
EXPORT_MANIFEST_PREFIX = KNOWLEDGE_PREFIX + "export_manifest/"
CONTRACT_VERSION = "factorforge_repo_root_knowledge_export_manifest_v2"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "knowledge"
    / "因子工厂"
    / "export_manifest"
    / "repo_root_knowledge_export_20260809.json"
)


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


def is_payload_path(path: str) -> bool:
    return path.startswith(KNOWLEDGE_PREFIX) and not path.startswith(
        EXPORT_MANIFEST_PREFIX
    )


def changed_paths(base_commit: str) -> set[str]:
    outputs = [
        run_git(
            [
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "-z",
                f"{base_commit}...HEAD",
            ]
        ),
        run_git(
            ["diff", "--name-only", "--diff-filter=ACMR", "-z", "HEAD"]
        ),
        run_git(
            ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
        ),
    ]
    return {
        path
        for output in outputs
        for path in output.split("\0")
        if path
    }


def previous_manifest(output: Path) -> dict[str, Any] | None:
    candidates = sorted(
        path
        for path in output.parent.glob("*.json")
        if path.resolve() != output.resolve()
    )
    if not candidates:
        return None
    path = candidates[-1]
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic repo-root Factor Forge knowledge export manifest."
        )
    )
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--approval-context",
        default=(
            "Cumulative Factor Forge release closure approved by the user; "
            "repo-root knowledge remains an explicit audited export."
        ),
    )
    parser.add_argument(
        "--reason",
        default=(
            "Capture the exact cumulative repo-root knowledge payload after "
            "knowledge-network and math-mechanism integration."
        ),
    )
    args = parser.parse_args()

    base_commit = run_git(
        ["rev-parse", "--verify", f"{args.base_ref}^{{commit}}"]
    ).strip()
    output = Path(args.output).expanduser().resolve()
    output.relative_to(REPO_ROOT)
    payload_paths = sorted(
        path for path in changed_paths(base_commit) if is_payload_path(path)
    )
    if not payload_paths:
        raise SystemExit("No repo-root knowledge payload changes found.")
    files: list[dict[str, Any]] = []
    for relative_path in payload_paths:
        path = REPO_ROOT / relative_path
        if not path.is_file():
            raise SystemExit(f"Knowledge export payload is missing: {relative_path}")
        files.append(
            {
                "path": relative_path,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    manifest = {
        "contract_version": CONTRACT_VERSION,
        "approval_context": args.approval_context,
        "export_root": "knowledge/因子工厂",
        "export_target": "repo_root_knowledge_vault",
        "source_boundary": (
            "factor-workspace canonical knowledge exported to the repo-root "
            "vault for governed review and retrieval; default writes remain "
            "workspace-local"
        ),
        "reason": args.reason,
        "generation_policy": "deterministic_file_identity_no_wall_clock",
        "scope": {
            "mode": "git_diff_payload_exact",
            "base_commit": base_commit,
            "payload_count": len(files),
            "export_manifest_paths_excluded": True,
        },
        "previous_manifest": previous_manifest(output),
        "payload_snapshot_sha256": stable_hash(files),
        "files": files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "verdict": "WRITTEN",
                "path": output.relative_to(REPO_ROOT).as_posix(),
                "payload_count": len(files),
                "payload_snapshot_sha256": manifest[
                    "payload_snapshot_sha256"
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
