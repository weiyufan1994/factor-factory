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
    BLOCK_WORKSPACE_IDENTITY_INVALID,
    BLOCK_WORKSPACE_MANIFEST_INVALID,
    build_workspace_manifest,
    default_workspace_root,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
    write_workspace_manifest,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize a Factor Forge factor research workspace.")
    ap.add_argument("--factor-id", required=True)
    ap.add_argument("--research-id", required=True)
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--factorforge-root", required=True)
    ap.add_argument("--implementation-mode", default="unknown", choices=["operator", "direct_code", "hybrid", "unknown"])
    ap.add_argument("--reuse-existing", action="store_true")
    args = ap.parse_args()

    factorforge_root = Path(args.factorforge_root).expanduser().resolve()
    workspace_root = default_workspace_root(
        factorforge_root=factorforge_root,
        factor_id=args.factor_id,
        research_id=args.research_id,
    )
    manifest_path = workspace_manifest_path(workspace_root)
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=factorforge_root,
        factor_id=args.factor_id,
        research_id=args.research_id,
        root_report_id=args.report_id,
        implementation_mode=args.implementation_mode,
    )
    if manifest_path.exists():
        if not args.reuse_existing:
            print(f"{BLOCK_WORKSPACE_IDENTITY_INVALID}: workspace exists; pass --reuse-existing", file=sys.stderr)
            return 1
        existing = load_workspace_manifest(manifest_path)
        for key in ("factor_id", "research_id", "root_report_id", "workspace_root"):
            if str(existing.get(key) or "") != str(manifest.get(key) or ""):
                print(f"{BLOCK_WORKSPACE_IDENTITY_INVALID}: {key} mismatch", file=sys.stderr)
                return 1
        failures = validate_workspace_manifest(existing)
        if failures:
            print("; ".join(failures), file=sys.stderr)
            return 1
        print(json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"[WORKSPACE_MANIFEST] {manifest_path}")
        return 0

    write_workspace_manifest(manifest_path, manifest)
    failures = validate_workspace_manifest(load_workspace_manifest(manifest_path))
    if failures:
        print(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: {'; '.join(failures)}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"[WORKSPACE_MANIFEST] {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
