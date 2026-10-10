"""Full-source hosted compatibility; not a dependency of ordinary knowledge tests."""
import pytest
from factor_factory.console import web_research_plan as web_plan
from factor_factory.ultimate_loop import hosted as hosted_execution
from tests.test_kb01_main_exit_maintenance import fixtures, runtime, ultimate


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
    monkeypatch.setattr(web_plan, "resolve_workspace_approved_catalog", lambda *a, **k: (marker, 'synthetic'))
    monkeypatch.setattr(hosted_execution, "resolve_report_scoped_web_research_plan", lambda *a, **k: {
        'plan_path': str(marker), 'plan': {}, 'is_evo_child': False})
    monkeypatch.setattr(hosted_execution, "validate_materialized_web_research", lambda *a, **k: {'synthetic': 'test'})
    monkeypatch.setattr(hosted_execution, "resolve_web_evo_execution_gate", lambda **k: {'enabled': False})
    monkeypatch.setattr(hosted_execution, "required_web_resume_start_step", lambda *a, **k: '6')
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
