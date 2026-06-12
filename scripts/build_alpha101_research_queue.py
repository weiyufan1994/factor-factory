#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def main() -> int:
    ap = argparse.ArgumentParser(description='Build a guarded Alpha101 research queue inside a factor workspace.')
    ap.add_argument('--workspace-root')
    ap.add_argument('--output')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not args.workspace_root:
        print(BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN, file=sys.stderr)
        return 1

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    manifest_path = workspace_manifest_path(workspace_root)
    if not manifest_path.exists():
        print(f'BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID: missing {manifest_path}', file=sys.stderr)
        return 1
    manifest = load_workspace_manifest(manifest_path)
    failures = validate_workspace_manifest(manifest)
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        return 1

    output = Path(args.output).expanduser().resolve() if args.output else workspace_root / 'knowledge' / 'canonical' / 'alpha101_research_queue.json'
    assert_path_under_workspace(output, workspace_root, label='alpha101_research_queue')
    payload = {
        'contract_version': 'factorforge_alpha101_research_queue_v1',
        'created_at_utc': utc_now(),
        'workspace_root': str(workspace_root),
        'factor_id': manifest.get('factor_id'),
        'research_id': manifest.get('research_id'),
        'status': 'dry_run' if args.dry_run else 'created',
        'items': [],
    }
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'[WRITE] {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
