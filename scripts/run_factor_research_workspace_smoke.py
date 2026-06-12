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
    BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT,
    BLOCK_OUTPUT_OUTSIDE_WORKSPACE,
    BLOCK_WORKSPACE_IDENTITY_INVALID,
    BLOCK_WORKSPACE_MISSING,
    default_workspace_root,
)
from factor_factory.step3.template_runtime import runtime_copy_path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)


def expect_rc(name: str, proc: subprocess.CompletedProcess[str], rc: int, token: str | None = None) -> dict:
    output = (proc.stdout or '') + '\n' + (proc.stderr or '')
    ok = proc.returncode == rc and (token is None or token in output)
    if not ok:
        raise AssertionError(f'{name} failed: rc={proc.returncode} expected={rc} token={token}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}')
    return {'name': name, 'rc': proc.returncode, 'token': token, 'status': 'PASS'}


def main() -> int:
    root = Path('/tmp/factorforge_factor_research_workspace_smoke')
    if not str(root).startswith('/tmp/'):
        raise SystemExit('refusing non-/tmp smoke root')
    shutil.rmtree(root, ignore_errors=True)
    factorforge_root = root / 'factorforge'
    factor_id = 'smoke_factor'
    research_id = 'smoke_research'
    report_id = 'smoke_report'
    workspace = default_workspace_root(factorforge_root=factorforge_root, factor_id=factor_id, research_id=research_id)
    results = []

    results.append(expect_rc('init_workspace', run([
        sys.executable,
        'scripts/init_factor_research_workspace.py',
        '--factor-id', factor_id,
        '--research-id', research_id,
        '--report-id', report_id,
        '--factorforge-root', str(factorforge_root),
        '--implementation-mode', 'direct_code',
    ]), 0))
    mismatch_build = run([
        sys.executable,
        'scripts/build_factorforge_runtime_context.py',
        '--report-id', report_id,
        '--factor-id', 'ID_B',
        '--research-id', research_id,
        '--factor-workspace', str(workspace),
        '--factorforge-root', str(factorforge_root),
        '--write',
    ])
    results.append(expect_rc('build_runtime_context_identity_mismatch_blocks', mismatch_build, 1, BLOCK_WORKSPACE_IDENTITY_INVALID))
    if 'ID_B' in (mismatch_build.stdout or ''):
        raise AssertionError('mismatched build runtime stdout exposed a manifest with CLI factor_id')
    results.append(expect_rc('build_runtime_context_v2', run([
        sys.executable,
        'scripts/build_factorforge_runtime_context.py',
        '--report-id', report_id,
        '--factor-id', factor_id,
        '--research-id', research_id,
        '--factor-workspace', str(workspace),
        '--factorforge-root', str(factorforge_root),
        '--write',
    ]), 0))
    runtime_manifest = workspace / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'
    if not runtime_manifest.exists():
        raise AssertionError(f'runtime manifest missing: {runtime_manifest}')
    manifest_payload = json.loads(runtime_manifest.read_text(encoding='utf-8'))
    if manifest_payload.get('contract_version') != 'factorforge_runtime_context_v2':
        raise AssertionError('runtime context was not v2')
    workspace_resolved = workspace.resolve()
    objects_root_resolved = Path(str(manifest_payload.get('objects_root', ''))).resolve()
    if objects_root_resolved != workspace_resolved / 'objects':
        raise AssertionError('objects_root is not workspace scoped')

    results.append(expect_rc('validate_workspace', run([
        sys.executable,
        'scripts/validate_factor_research_workspace.py',
        '--workspace-root', str(workspace),
        '--runtime-manifest', str(runtime_manifest),
    ]), 0))
    results.append(expect_rc('outside_path_blocks', run([
        sys.executable,
        'scripts/validate_factor_research_workspace.py',
        '--workspace-root', str(workspace),
        '--assert-path', f'bad={root.parent / "outside_workspace.parquet"}',
    ]), 1, BLOCK_OUTPUT_OUTSIDE_WORKSPACE))

    step3_copy = runtime_copy_path(factorforge_root, report_id, script_stem='run_step3', workspace_root=workspace)
    if step3_copy.resolve(strict=False).parent.parent != (workspace / 'step3_runtime').resolve(strict=False):
        raise AssertionError(f'step3 runtime copy outside workspace: {step3_copy}')

    repo_vault = REPO_ROOT / 'knowledge' / '因子工厂'
    results.append(expect_rc('repo_vault_export_requires_flag', run([
        sys.executable,
        'scripts/export_factorforge_obsidian.py',
        '--workspace-root', str(workspace),
        '--output-root', str(repo_vault),
    ]), 1, BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT))

    explicit_vault = root / 'external_vault'
    results.append(expect_rc('explicit_vault_export_passes', run([
        sys.executable,
        'scripts/export_factorforge_obsidian.py',
        '--workspace-root', str(workspace),
        '--output-root', str(explicit_vault),
        '--export-knowledge-vault',
        '--write-export-manifest',
    ]), 0))
    export_manifests = list((workspace / 'knowledge' / 'export_manifest').glob('knowledge_vault_export__*.json'))
    if not export_manifests:
        raise AssertionError('explicit export did not write export manifest')

    results.append(expect_rc('ultimate_formal_without_workspace_blocks', run([
        sys.executable,
        'scripts/run_factorforge_ultimate.py',
        '--report-id', report_id,
        '--start-step', '3',
        '--end-step', '3',
        '--factorforge-root', str(root / 'legacy_factorforge'),
        '--dry-run',
    ]), 1, BLOCK_WORKSPACE_MISSING))
    results.append(expect_rc('ultimate_workspace_identity_mismatch_blocks', run([
        sys.executable,
        'scripts/run_factorforge_ultimate.py',
        '--report-id', report_id,
        '--start-step', '3',
        '--end-step', '3',
        '--factorforge-root', str(factorforge_root),
        '--factor-workspace', str(workspace),
        '--factor-id', 'ID_B',
        '--research-id', research_id,
        '--dry-run',
    ]), 1, BLOCK_WORKSPACE_IDENTITY_INVALID))

    summary = {
        'verdict': 'ACCEPT',
        'workspace_root': str(workspace),
        'runtime_manifest': str(runtime_manifest),
        'worker_started': False,
        'production_research_started': False,
        'results': results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print('FACTOR_RESEARCH_WORKSPACE_SMOKE PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
