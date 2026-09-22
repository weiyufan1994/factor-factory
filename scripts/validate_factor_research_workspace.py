#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    BLOCK_OUTPUT_OUTSIDE_WORKSPACE,
    BLOCK_WORKSPACE_MANIFEST_INVALID,
    assert_path_under_workspace,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)
from factor_factory.runtime_context import load_runtime_manifest
from factor_factory.research_org import (
    PLAN_RELATIVE_PATH,
    ResearchOrganizationError,
    validate_research_organization_bundle,
)


def _workspace_from_runtime_manifest(path: Path) -> tuple[Path, dict]:
    manifest = load_runtime_manifest(path)
    workspace = manifest.get("factor_workspace")
    if not workspace:
        raise SystemExit(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: runtime manifest missing factor_workspace")
    return Path(str(workspace)).expanduser(), manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a Factor Forge factor research workspace.")
    ap.add_argument("--workspace-root")
    ap.add_argument("--runtime-manifest")
    ap.add_argument("--assert-path", action="append", default=[], help="Extra LABEL=PATH assertion that PATH is under workspace.")
    ap.add_argument(
        "--require-research-org",
        action="store_true",
        help="Require and validate the Host-owned research-organization bundle.",
    )
    args = ap.parse_args()
    if not args.workspace_root and not args.runtime_manifest:
        print(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: pass --workspace-root or --runtime-manifest", file=sys.stderr)
        return 1

    runtime_manifest = None
    if args.runtime_manifest:
        workspace_root, runtime_manifest = _workspace_from_runtime_manifest(Path(args.runtime_manifest).expanduser())
    else:
        workspace_root = Path(args.workspace_root).expanduser()

    manifest_path = workspace_manifest_path(workspace_root)
    if not manifest_path.exists():
        print(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: missing {manifest_path}", file=sys.stderr)
        return 1
    workspace_manifest = load_workspace_manifest(manifest_path)
    failures = validate_workspace_manifest(workspace_manifest)
    if runtime_manifest:
        for key in ("factor_id", "research_id"):
            if str(runtime_manifest.get(key) or "") != str(workspace_manifest.get(key) or ""):
                failures.append(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: runtime {key} mismatch")
        for section in ("objects", "runs", "evaluations", "knowledge"):
            for item_key, raw in (runtime_manifest.get(section) or {}).items():
                if isinstance(raw, str):
                    try:
                        assert_path_under_workspace(Path(raw), workspace_root, label=f"{section}.{item_key}")
                    except ValueError as exc:
                        failures.append(str(exc))
        for item_key, raw in (runtime_manifest.get("branch") or {}).items():
            if isinstance(raw, str):
                try:
                    assert_path_under_workspace(Path(raw), workspace_root, label=f"branch.{item_key}")
                except ValueError as exc:
                    failures.append(str(exc))
    for raw in args.assert_path:
        if "=" not in raw:
            failures.append(f"{BLOCK_OUTPUT_OUTSIDE_WORKSPACE}: malformed assert-path {raw!r}")
            continue
        label, value = raw.split("=", 1)
        try:
            assert_path_under_workspace(Path(value), workspace_root, label=label)
        except ValueError as exc:
            failures.append(str(exc))
    research_org = None
    research_org_path = workspace_root / PLAN_RELATIVE_PATH
    if args.require_research_org or research_org_path.exists() or research_org_path.is_symlink():
        try:
            research_org = validate_research_organization_bundle(
                workspace=workspace_root
            )
        except ResearchOrganizationError as exc:
            failures.append(str(exc))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    payload = {
        "verdict": "PASS",
        "workspace_root": str(workspace_root),
        "workspace_manifest": str(manifest_path),
        "runtime_manifest": str(args.runtime_manifest) if args.runtime_manifest else None,
        "research_organization": research_org,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
