#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    BLOCK_KNOWLEDGE_PROVENANCE_MISSING,
    BLOCK_KNOWLEDGE_WRITE_PATH_INVALID,
    BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT,
    BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN,
    default_workspace_root,
)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)


def expect(name: str, cmd: list[str], rc: int, token: str | None = None) -> dict:
    proc = run(cmd)
    output = (proc.stdout or '') + '\n' + (proc.stderr or '')
    if proc.returncode != rc or (token is not None and token not in output):
        raise AssertionError(f'{name} failed: rc={proc.returncode} expected={rc} token={token}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}')
    return {'name': name, 'rc': proc.returncode, 'token': token, 'status': 'PASS'}


def main() -> int:
    root = Path('/tmp/factorforge_knowledge_write_guard_smoke')
    if not str(root).startswith('/tmp/'):
        raise SystemExit('refusing non-/tmp smoke root')
    shutil.rmtree(root, ignore_errors=True)
    factorforge_root = root / 'factorforge'
    factor_id = 'knowledge_guard_factor'
    research_id = 'knowledge_guard_research'
    report_id = 'knowledge_guard_report'
    workspace = default_workspace_root(factorforge_root=factorforge_root, factor_id=factor_id, research_id=research_id)
    results = []

    results.append(expect('init_workspace', [
        sys.executable,
        'scripts/init_factor_research_workspace.py',
        '--factor-id', factor_id,
        '--research-id', research_id,
        '--report-id', report_id,
        '--factorforge-root', str(factorforge_root),
    ], 0))

    results.append(expect('repo_vault_blocks_without_explicit_export', [
        sys.executable,
        'scripts/export_factorforge_obsidian.py',
        '--workspace-root', str(workspace),
        '--output-root', str(REPO_ROOT / 'knowledge' / '因子工厂'),
    ], 1, BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT))
    results.append(expect('external_vault_export_requires_manifest', [
        sys.executable,
        'scripts/export_factorforge_obsidian.py',
        '--workspace-root', str(workspace),
        '--output-root', str(root / 'external_vault_without_manifest'),
        '--export-knowledge-vault',
    ], 1, BLOCK_KNOWLEDGE_PROVENANCE_MISSING))
    results.append(expect('external_vault_export_with_manifest_passes', [
        sys.executable,
        'scripts/export_factorforge_obsidian.py',
        '--workspace-root', str(workspace),
        '--output-root', str(root / 'external_vault_with_manifest'),
        '--export-knowledge-vault',
        '--write-export-manifest',
    ], 0))
    if not list((workspace / 'knowledge' / 'export_manifest').glob('knowledge_vault_export__*.json')):
        raise AssertionError('explicit external export did not write export manifest')

    results.append(expect('workspace_default_obsidian_export_passes', [
        sys.executable,
        'scripts/export_factorforge_obsidian.py',
        '--workspace-root', str(workspace),
    ], 0))
    if not (workspace / 'knowledge' / 'human_readable' / 'Home.md').exists():
        raise AssertionError('workspace default export did not write Home.md')

    results.append(expect('embedding_index_requires_workspace_or_legacy_flag', [
        sys.executable,
        'scripts/build_factorforge_embedding_index.py',
        '--endpoint', 'http://127.0.0.1:1/v1/embeddings',
    ], 1, BLOCK_KNOWLEDGE_WRITE_PATH_INVALID))

    retrieval = workspace / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'
    retrieval.parent.mkdir(parents=True, exist_ok=True)
    retrieval.write_text(json.dumps({'id': 'smoke', 'text': 'smoke'}, ensure_ascii=False) + '\n', encoding='utf-8')
    # Do not call the embedding service in smoke; path-policy coverage above is enough.

    results.append(expect('alpha101_batch_judge_blocks_without_workspace', [
        sys.executable,
        'scripts/run_alpha101_qlib_batch_judge.py',
    ], 1, BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN))
    results.append(expect('alpha101_queue_blocks_without_workspace', [
        sys.executable,
        'scripts/build_alpha101_research_queue.py',
    ], 1, BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN))
    results.append(expect('alpha101_queue_writes_inside_workspace', [
        sys.executable,
        'scripts/build_alpha101_research_queue.py',
        '--workspace-root', str(workspace),
    ], 0))

    summary = {
        'verdict': 'ACCEPT',
        'workspace_root': str(workspace),
        'worker_started': False,
        'production_research_started': False,
        'results': results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print('FACTORFORGE_KNOWLEDGE_WRITE_GUARD_SMOKE PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
