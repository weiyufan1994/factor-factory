#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.research_workspace import (
    BLOCK_WORKSPACE_MANIFEST_INVALID,
    load_workspace_manifest,
    validate_workspace_cli_identity,
    workspace_manifest_path,
)


def main() -> None:
    parser = argparse.ArgumentParser(description='Build the standard Factor Forge runtime context manifest.')
    parser.add_argument('--report-id', required=True)
    parser.add_argument('--branch-id')
    parser.add_argument('--factor-id')
    parser.add_argument('--research-id')
    parser.add_argument('--factor-workspace')
    parser.add_argument('--factorforge-root')
    parser.add_argument('--allow-legacy-global-runtime', action='store_true')
    parser.add_argument('--write', action='store_true', help='Write manifest under objects/runtime_context/.')
    args = parser.parse_args()

    workspace_requested = bool(args.factor_workspace or args.factor_id or args.research_id)
    if workspace_requested and not (args.factor_workspace and args.factor_id and args.research_id):
        raise SystemExit(f'{BLOCK_WORKSPACE_MANIFEST_INVALID}: --factor-workspace, --factor-id, and --research-id are required together')
    if not workspace_requested and not args.allow_legacy_global_runtime:
        # Keep historical CLI usable only when callers intentionally request the legacy global layout.
        raise SystemExit('BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MISSING: pass --factor-workspace or --allow-legacy-global-runtime')
    ctx = resolve_factorforge_context(args.factorforge_root, factor_workspace=args.factor_workspace)
    if args.factor_workspace:
        workspace_manifest = load_workspace_manifest(workspace_manifest_path(Path(args.factor_workspace).expanduser()))
        failures = validate_workspace_cli_identity(
            workspace_manifest,
            factor_id=args.factor_id,
            research_id=args.research_id,
        )
        if failures:
            raise SystemExit('\n'.join(failures))
    manifest = ctx.build_manifest(args.report_id, branch_id=args.branch_id)
    if args.write:
        out = ctx.write_manifest(args.report_id, branch_id=args.branch_id)
        print(f'[WRITE] {out}')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
