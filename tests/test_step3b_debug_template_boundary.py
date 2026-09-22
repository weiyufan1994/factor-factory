"""Actual subprocess coverage for direct-debug validation before template writes."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'skills/factor-forge-step3/scripts/run_step3b.py'


def _invoke(tmp_path, *, allowed=True, same_root=False, wrong_manifest=False):
    canonical, debug = tmp_path / 'canonical', tmp_path / 'debug'
    canonical.mkdir(); debug.mkdir()
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('FACTORFORGE_'):
            del env[key]
    env.update(PYTHONPATH=str(REPO), FACTORFORGE_REPO_ROOT=str(REPO),
        FACTORFORGE_ROOT=str(canonical), FACTORFORGE_DEBUG_ROOT=str(canonical if same_root else debug),
        PYTHONDONTWRITEBYTECODE='1')
    if allowed:
        env['FACTORFORGE_ALLOW_DIRECT_STEP'] = '1'
    command = [sys.executable, str(SCRIPT), '--report-id', 'DEBUG_BOUNDARY']
    if wrong_manifest:
        from factor_factory.runtime_context import resolve_factorforge_context
        other = tmp_path / 'other'
        other.mkdir()
        manifest = resolve_factorforge_context(other).build_manifest('DEBUG_BOUNDARY')
        path = tmp_path / 'manifest.json'
        path.write_text(json.dumps(manifest))
        command += ['--manifest', str(path)]
    result = subprocess.run(command, env=env, cwd=REPO, capture_output=True, text=True, timeout=30)
    return result, canonical, debug


@pytest.mark.parametrize('kwargs', [dict(allowed=False), dict(same_root=True), dict(wrong_manifest=True)])
def test_invalid_direct_call_writes_no_runtime_copy_or_meta(tmp_path, kwargs):
    result, canonical, debug = _invoke(tmp_path, **kwargs)
    assert result.returncode != 0
    assert 'BLOCKED_DIRECT_STEP:' in result.stderr
    assert not list(tmp_path.rglob('run_step3b__*.py'))
    assert not list(tmp_path.rglob('*.meta.json'))


def test_valid_debug_reexec_reaches_input_resolution_in_private_copy(tmp_path):
    result, canonical, debug = _invoke(tmp_path)
    assert result.returncode != 0  # No scientific input fixture was supplied.
    assert 'BLOCKED_DIRECT_STEP:' not in result.stderr
    assert 'data_prep_master__DEBUG_BOUNDARY.json' in result.stderr
    copies = list(debug.rglob('run_step3b__DEBUG_BOUNDARY.py'))
    assert len(copies) == 1
    meta = json.loads(copies[0].with_suffix('.meta.json').read_text())
    assert meta['runtime_copy_hash'] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert str(copies[0]) in result.stderr
    assert not list(canonical.rglob('run_step3b__*.py'))
