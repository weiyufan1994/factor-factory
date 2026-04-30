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


def main() -> None:
    parser = argparse.ArgumentParser(description='Build the standard Factor Forge runtime context manifest.')
    parser.add_argument('--report-id', required=True)
    parser.add_argument('--branch-id')
    parser.add_argument('--factorforge-root')
    parser.add_argument('--write', action='store_true', help='Write manifest under objects/runtime_context/.')
    args = parser.parse_args()

    ctx = resolve_factorforge_context(args.factorforge_root)
    manifest = ctx.build_manifest(args.report_id, branch_id=args.branch_id)
    if args.write:
        out = ctx.write_manifest(args.report_id, branch_id=args.branch_id)
        print(f'[WRITE] {out}')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
