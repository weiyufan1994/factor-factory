"""Offline main-entry orchestration tests, not research/agent acceptance.

Only command producers and external authority are synthetic. Candidate main,
proof finalization, episode/export/index writers and readback run against tmp.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CANDIDATE = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('FACTORFORGE_KB01_REVIEW_SOURCE_ROOT', str(CANDIDATE))).expanduser().resolve()


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ultimate = _load('kb01_candidate_ultimate', CANDIDATE / 'scripts/run_factorforge_ultimate.py')
fixtures = _load('kb01_source_fixtures', SOURCE / 'tests/test_factorforge_ultimate_local_is_scope.py')
records = _load('kb01_source_records', SOURCE / 'tests/test_factorforge_ultimate_knowledge_refresh.py')


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import factor_factory.research_knowledge_maintenance as maintenance
    import factor_factory.workspace_experience_export as exports
    import scripts.build_factorforge_retrieval_index as indexer

    monkeypatch.setattr(fixtures, 'ultimate', ultimate)
    for key in fixtures.HOST_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL', '1')
    workspace = fixtures._workspace(tmp_path)
    repo = tmp_path / 'project'
    repo.mkdir()
    episode_hook = ultimate.record_research_knowledge_maintenance_nonblocking
    step6_hook = ultimate.run_post_step6_knowledge_refresh_nonblocking
    calls = fixtures._install_local_runtime_stubs(monkeypatch)
    monkeypatch.setattr(ultimate, 'record_research_knowledge_maintenance_nonblocking', episode_hook)
    monkeypatch.setattr(ultimate, 'run_post_step6_knowledge_refresh_nonblocking', step6_hook)
    monkeypatch.setattr(ultimate, 'REPO_ROOT', repo)
    monkeypatch.setattr(indexer, 'REPO_ROOT', repo)
    counts = {'episode': 0, 'episode_refresh': 0, 'step6_export': 0}
    for module, name, key in (
        (maintenance, 'record_local_research_episode', 'episode'),
        (maintenance, 'refresh_episode_maintenance', 'episode_refresh'),
        (exports, 'export_workspace_knowledge_record', 'step6_export'),
    ):
        original = getattr(module, name)
        def spy(*args, _original=original, _key=key, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, spy)

    def run(*extra, local=True):
        fixtures._args(monkeypatch, workspace,
                       *(['--local-is-only'] if local else []), *extra)
        return ultimate.main()

    def commands(*, fail=None, code=7, output='', status=None):
        original = ultimate.run_command
        def fake(name, command, *, cwd, env, dry_run=False):
            result = original(name, command, cwd=cwd, env=env, dry_run=False)
            if name == fail:
                result.returncode, result.status, result.stdout_tail = code, 'FAIL', output
            if status:
                result.status = status
            return result
        monkeypatch.setattr(ultimate, 'run_command', fake)

    return SimpleNamespace(workspace=workspace, repo=repo, calls=calls, counts=counts,
                           run=run, commands=commands, proof=lambda: fixtures._proof(workspace))


def _recorded(runtime, status, returncode, actual):
    assert actual == returncode
    proof = runtime.proof()
    assert proof['status'] == status
    assert proof['research_knowledge_maintenance']['status'] == 'RECORDED'
    assert runtime.counts == {'episode': 1, 'episode_refresh': 1, 'step6_export': 0}
    files = list((runtime.workspace / 'knowledge/research_episodes').glob('*.json'))
    assert len(files) == 1
    episode = json.loads(files[0].read_text())
    assert episode['formal_step6_completed'] is False
    assert episode['lessons_status'] == 'NEEDS_RESEARCHER_REVIEW'
    assert 'economic_cause' not in episode
    assert proof['research_knowledge_maintenance']['index_maintenance']['default_readback'] is True
    return proof, episode


@pytest.mark.parametrize('failure', ['before', 'save'])
def test_main_review_early_failure_retains_actual_facts(runtime, monkeypatch, failure):
    class Review:
        def __init__(self, *args):
            pass
        def before_command(self, *args, **kwargs):
            if failure == 'before':
                raise ValueError('synthetic review blocker')
            return {'status': 'RUN'}
        def record_command(self, result):
            raise ValueError('synthetic continuation failure')
    monkeypatch.setattr(ultimate, 'CodeReviewHandoff', Review)
    proof, episode = _recorded(runtime, 'FAIL', 1,
        runtime.run('--start-step', '4', '--end-step', '4'))
    assert proof['failure']['command'] == ('code_review_handoff' if failure == 'before' else 'save_code_review_continuation')
    assert bool(any(row['command'] == 'run_step4' for row in episode['observations'])) == (failure == 'save')


def test_main_council_wait_results_records_once(runtime):
    proof, _ = _recorded(runtime, 'PAUSED', 0, runtime.run(
        '--start-step', '6', '--end-step', '6', '--council-mode', 'agentic',
        '--agentic-council-executor', 'dispatch_manifest'))
    assert proof['revision_council']['status'] == 'awaiting_agent_results'
    assert proof['failure'] is None


def test_main_council_failure_preserves_code(runtime):
    runtime.commands(fail='build_revision_council_packet', code=9)
    proof, _ = _recorded(runtime, 'FAIL', 9, runtime.run(
        '--start-step', '6', '--end-step', '6', '--council-mode', 'agentic',
        '--agentic-council-executor', 'dispatch_manifest'))
    assert proof['failure'] == {'command': 'build_revision_council_packet', 'returncode': 9}


@pytest.mark.parametrize('mechanism', [False, True])
def test_main_existing_failure_and_mechanism_pause_are_not_duplicated(runtime, mechanism):
    runtime.commands(fail='run_step6' if mechanism else 'run_step4', code=7,
                     output='AWAITING_MAIN_AGENT_MECHANISM_MEMO' if mechanism else '')
    proof, _ = _recorded(runtime, 'PAUSED' if mechanism else 'FAIL', 0 if mechanism else 7,
                         runtime.run())
    if mechanism:
        assert proof['failure'] is None
    else:
        assert proof['failure']['returncode'] == 7


@pytest.mark.parametrize('mode', ['dry_run', 'planned_only', 'no_commands'])
def test_main_non_execution_is_visible_skip_without_experience(runtime, monkeypatch, mode):
    if mode == 'no_commands':
        def blocked(**kwargs):
            raise ultimate.StateReuseBlock('SYNTHETIC_STATE_BLOCK', 'not executed')
        monkeypatch.setattr(ultimate, 'run_state_reuse_gate', blocked)
    else:
        runtime.commands(status='DRY_RUN')
    rc = runtime.run(*(['--dry-run'] if mode == 'dry_run' else []))
    assert rc == (0 if mode == 'dry_run' else 1)
    proof = runtime.proof()
    assert proof['research_knowledge_maintenance'] == {
        'status': 'SKIPPED', 'reason': 'no_executed_local_is_wrapper'}
    assert runtime.counts == {'episode': 0, 'episode_refresh': 0, 'step6_export': 0}
    assert not any(path.is_file() for path in (runtime.workspace / 'knowledge').rglob('*'))
    assert not (runtime.repo / 'knowledge').exists()


def test_main_mixed_plan_rows_are_not_exported_as_facts(runtime, monkeypatch):
    original = ultimate.run_command
    def fake(name, command, **kwargs):
        result = original(name, command, **kwargs)
        if name == 'validate_step2_code_review':
            result.returncode, result.status = 6, 'FAIL'
        else:
            result.status = 'PLANNED'
        return result
    monkeypatch.setattr(ultimate, 'run_command', fake)
    _, episode = _recorded(runtime, 'FAIL', 6, runtime.run('--start-step', '4', '--end-step', '4'))
    assert episode['observations'] == [
        {'command': 'validate_step2_code_review', 'status': 'FAIL', 'returncode': 6}]


def test_main_maintenance_error_preserves_original_result_and_old_index(runtime, monkeypatch):
    import factor_factory.research_knowledge_maintenance as maintenance
    index = runtime.workspace / 'knowledge/retrieval/factorforge_retrieval_index.jsonl'
    index.parent.mkdir(parents=True)
    index.write_bytes(b'old usable index\n')
    def failed(**kwargs):
        raise OSError('synthetic cache failure')
    monkeypatch.setattr(maintenance, 'refresh_episode_maintenance', failed)
    runtime.commands(fail='validate_step2_code_review', code=8)
    assert runtime.run('--start-step', '4', '--end-step', '4') == 8
    proof = runtime.proof()
    assert proof['status'] == 'FAIL'
    assert proof['failure'] == {'command': 'validate_step2_code_review', 'returncode': 8}
    assert proof['research_knowledge_maintenance'] == {'status': 'MAINTENANCE_FAILED', 'error_type': 'OSError'}
    assert index.read_bytes() == b'old usable index\n'


def test_main_completed_step6_exports_once_without_episode(runtime):
    records._write_record(runtime.workspace, fixtures.REPORT_ID)
    assert runtime.run('--start-step', '6', '--end-step', '6') == 0
    proof = runtime.proof()
    assert proof['status'] == 'PASS'
    assert proof['research_knowledge_maintenance']['reason'] == 'completed_step6_uses_knowledge_record'
    assert proof['post_step6_knowledge_refresh']['workspace_experience_export']['status'] == 'EXPORTED'
    assert proof['post_step6_knowledge_refresh']['default_readback'] is True
    assert runtime.counts == {'episode': 1, 'episode_refresh': 0, 'step6_export': 1}
    assert not (runtime.workspace / 'knowledge/research_episodes').exists()


def _hosted(runtime, monkeypatch):
    monkeypatch.setenv(ultimate.OOS_HOST_TRUST_ROOT_ENV, str(runtime.repo))
    monkeypatch.setenv(ultimate.OOS_HOST_INSTALLATION_ID_ENV, 'synthetic-installation')
    monkeypatch.setattr(ultimate, 'formal_oos_incident_reasons', lambda **kwargs: [])


def test_main_nonlocal_wait_has_no_added_maintenance_or_write(runtime, monkeypatch):
    _hosted(runtime, monkeypatch)
    assert runtime.run('--start-step', '6', '--end-step', '6', '--council-mode', 'agentic',
                       '--agentic-council-executor', 'dispatch_manifest', local=False) == 0
    proof = runtime.proof()
    assert proof['status'] == 'PAUSED'
    assert 'research_knowledge_maintenance' not in proof
    assert runtime.counts == {'episode': 0, 'episode_refresh': 0, 'step6_export': 0}
    assert not any(path.is_file() for path in (runtime.workspace / 'knowledge').rglob('*'))
    assert not (runtime.repo / 'knowledge').exists()


@pytest.mark.parametrize('state,token', [
    ('awaiting_next_derivation', 'BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS'),
    ('awaiting_main_agent_council_synthesis', 'BLOCK_FACTORFORGE_TERMINAL_COUNCIL_NOT_UNANIMOUS'),
])
def test_main_hosted_derivation_synthesis_exits_remain_unchanged(runtime, monkeypatch, state, token):
    # These exits require web materialization and cannot be reached in ordinary
    # local IS (its earlier scope guard rejects that input). Test the real
    # hosted branches with explicit synthetic authority; never weaken the guard.
    _hosted(runtime, monkeypatch)
    marker = runtime.workspace / 'identity/data_catalog_summary.json'
    marker.parent.mkdir(exist_ok=True)
    marker.write_text('{}')
    monkeypatch.setattr(ultimate, 'resolve_workspace_approved_catalog', lambda *a, **k: (marker, 'synthetic'))
    monkeypatch.setattr(ultimate, 'resolve_report_scoped_web_research_plan', lambda *a, **k: {
        'plan_path': str(marker), 'plan': {}, 'is_evo_child': False})
    monkeypatch.setattr(ultimate, 'validate_materialized_web_research', lambda *a, **k: {'synthetic': 'test'})
    monkeypatch.setattr(ultimate, 'resolve_web_evo_execution_gate', lambda **k: {'enabled': False})
    monkeypatch.setattr(ultimate, 'required_web_resume_start_step', lambda *a, **k: '6')
    monkeypatch.setattr(ultimate, 'resolve_research_organization_runtime_gate', lambda **k: {
        'status': 'off', 'formal_independence_verified': True})
    council = runtime.workspace / 'objects/research_iteration_master/revision_council' / fixtures.REPORT_ID
    council.mkdir(parents=True)
    (council / f'dispatch_manifest__{fixtures.REPORT_ID}.json').write_text('{}')
    (council / f'branch_falsification__{fixtures.REPORT_ID}.json').write_text('{}')
    monkeypatch.setattr(ultimate, 'agentic_dispatch_required_results_present', lambda *a: True)
    runtime.commands(fail='close_terminal_council_rejection', code=2, output=token)
    assert runtime.run('--start-step', '6', '--end-step', '6', '--council-mode', 'agentic',
                       '--agentic-council-executor', 'dispatch_manifest',
                       '--research-org-runtime-mode', 'formal-complete', local=False) == 0
    proof = runtime.proof()
    assert proof['status'] == 'PAUSED' and proof['proof_semantics'] == state
    assert 'research_knowledge_maintenance' not in proof
    assert runtime.counts == {'episode': 0, 'episode_refresh': 0, 'step6_export': 0}
    assert not any(path.is_file() for path in (runtime.workspace / 'knowledge').rglob('*'))
    assert not (runtime.repo / 'knowledge').exists()


@pytest.mark.parametrize('failure', ['maintenance_hook', 'proof_update'])
def test_main_new_exit_maintenance_errors_do_not_replace_pause(runtime, monkeypatch, capsys, failure):
    if failure == 'maintenance_hook':
        def failed(**kwargs):
            raise RuntimeError('synthetic unexpected maintenance error')
        monkeypatch.setattr(ultimate, 'record_research_knowledge_maintenance_nonblocking', failed)
    else:
        original = ultimate.write_json_atomic
        def failed(path, proof):
            if 'research_knowledge_maintenance' in proof:
                raise OSError('synthetic proof-update failure')
            return original(path, proof)
        monkeypatch.setattr(ultimate, 'write_json_atomic', failed)
    assert runtime.run('--start-step', '6', '--end-step', '6', '--council-mode', 'agentic',
                       '--agentic-council-executor', 'dispatch_manifest') == 0
    proof = runtime.proof()
    assert proof['status'] == 'PAUSED' and proof['failure'] is None
    assert '[KNOWLEDGE_WARNING]' in capsys.readouterr().out
    if failure == 'maintenance_hook':
        assert proof['research_knowledge_maintenance'] == {
            'status': 'MAINTENANCE_FAILED', 'error_type': 'RuntimeError'}
    else:
        # Last original proof remains valid; the stdout warning is the only
        # possible maintenance signal when the report itself cannot be written.
        assert 'research_knowledge_maintenance' not in proof
