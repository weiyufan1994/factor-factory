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
    BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT,
    BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN,
    assert_path_under_workspace,
    is_repo_root_vault,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_workspace(root: Path) -> dict:
    manifest_path = workspace_manifest_path(root)
    if not manifest_path.exists():
        raise SystemExit(f'BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID: missing {manifest_path}')
    manifest = load_workspace_manifest(manifest_path)
    failures = validate_workspace_manifest(manifest)
    if failures:
        raise SystemExit('\n'.join(failures))
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description='Guarded Alpha101 qlib batch judge entrypoint.')
    ap.add_argument('--workspace-root')
    ap.add_argument('--output-root')
    ap.add_argument('--knowledge-root')
    ap.add_argument('--export-knowledge-vault', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not args.workspace_root and not args.output_root:
        print(BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN, file=sys.stderr)
        return 1

    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else None
    workspace_manifest = load_workspace(workspace_root) if workspace_root else {}
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else workspace_root / 'runs' / 'alpha101_qlib_batch_judge'
    knowledge_root = Path(args.knowledge_root).expanduser().resolve() if args.knowledge_root else (
        workspace_root / 'knowledge' / 'canonical' if workspace_root else None
    )

    if workspace_root:
        assert_path_under_workspace(output_root, workspace_root, label='alpha101_output_root')
        if knowledge_root:
            assert_path_under_workspace(knowledge_root, workspace_root, label='alpha101_knowledge_root')
    if knowledge_root and is_repo_root_vault(knowledge_root, REPO_ROOT) and not args.export_knowledge_vault:
        print(BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT, file=sys.stderr)
        return 1
    if args.dry_run:
        print('[DRY_RUN] guarded alpha101 qlib batch judge')
        return 0

    output_root.mkdir(parents=True, exist_ok=True)
    payload = {
        'contract_version': 'factorforge_alpha101_qlib_batch_judge_guard_v1',
        'created_at_utc': utc_now(),
        'workspace_root': str(workspace_root) if workspace_root else None,
        'factor_id': workspace_manifest.get('factor_id'),
        'research_id': workspace_manifest.get('research_id'),
        'output_root': str(output_root),
        'knowledge_root': str(knowledge_root) if knowledge_root else None,
        'status': 'guard_passed_no_batch_run',
        'production_research_started': False,
    }
    out = output_root / 'alpha101_qlib_batch_judge_manifest.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'[WRITE] {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
