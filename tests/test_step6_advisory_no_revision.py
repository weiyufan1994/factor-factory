"""Synthetic consumer regressions; these fixtures are not research evidence."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from factor_factory.measurement_program import mathematical_object_present
from scripts.run_agentic_council_dispatch_smoke import fake_real_agent_result
from tests.test_step6_council_phase_visibility import (
    RID, SCRIPT, _cli, _dispatch, _write, cli_taskbook,
)
from tests.test_step6_local_terminal_protocol_gate import _terminal_iteration


def _load(name):
    spec = importlib.util.spec_from_file_location('advisory_' + name, SCRIPT.parent / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load('validate_agentic_council_result')
APPENDIX = _load('build_council_derivation_appendix')
ATTACH = _load('attach_revision_council_to_step6')


@pytest.fixture
def advisory_results(cli_taskbook, monkeypatch):
    root, council, packet = cli_taskbook
    _, manifest = _dispatch(root, council)
    results = []
    for task in manifest['agent_tasks']:
        value = fake_real_agent_result(root, RID, task)
        value.update(candidate_revision_laws=[], no_candidate_revision_law_reason='No identifiable new estimator follows from the observations.')
        value['revision_or_kill_recommendation'] = {
            'recommendation': 'no_revision', 'terminal_scope': 'revision_branch_only',
            'stop_authority': 'advisory_only', 'rationale': 'Keep the current branch on hold.'}
        value['terminal_control'] = {'terminal_scope': 'revision_branch_only', 'stop_authority': 'advisory_only'}
        value['model_to_formula_translation'].update(candidate_formula=None, disposition='research_hold')
        _write(root / task['expected_result_path'], value)
        results.append(value)
    monkeypatch.setattr(VALIDATOR, 'FF', root)
    monkeypatch.setattr(VALIDATOR, 'OBJ', root / 'objects')
    return root, council, packet, manifest, results


@pytest.mark.parametrize('recommendation', ['no_revision', 'no_derived_revision'])
def test_explicit_substantive_branch_hold_accepts_empty_laws(advisory_results, recommendation):
    root, _, _, manifest, results = advisory_results
    value = results[0]
    value['revision_or_kill_recommendation']['recommendation'] = recommendation
    assert VALIDATOR.validate_agentic_result(value, expected_task=manifest['agent_tasks'][0],
        expected_report_id=RID, workspace_root=root) == []


@pytest.mark.parametrize('mutation', [
    'missing_laws', 'null_laws', 'wrong_type_laws', 'nonempty_laws',
    'empty_derivation', 'missing_scope', 'factor_scope', 'mechanism_scope',
    'authority_upgrade', 'conflicting_scope', 'missing_authority',
    'iterate', 'candidate_formula', 'candidate_branch', 'missing_reason', 'wrong_frozen_object',
])
def test_empty_law_exception_does_not_bypass_existing_obligations(advisory_results, mutation):
    root, _, _, manifest, results = advisory_results
    value = deepcopy(results[0])
    rec = value['revision_or_kill_recommendation']
    control = value['terminal_control']
    if mutation == 'missing_laws': value.pop('candidate_revision_laws')
    elif mutation == 'null_laws': value['candidate_revision_laws'] = None
    elif mutation == 'wrong_type_laws': value['candidate_revision_laws'] = {}
    elif mutation == 'nonempty_laws': value['candidate_revision_laws'] = [{'law_id': 'contradiction'}]
    elif mutation == 'empty_derivation': value['math_mechanism_derivation'] = {}
    elif mutation == 'missing_scope':
        rec.pop('terminal_scope'); control.pop('terminal_scope')
    elif mutation in {'factor_scope', 'mechanism_scope'}:
        rec['terminal_scope'] = control['terminal_scope'] = ('factor_instance' if mutation == 'factor_scope' else 'mechanism_family')
    elif mutation == 'authority_upgrade': rec['stop_authority'] = control['stop_authority'] = 'validated_no_derived_revision'
    elif mutation == 'conflicting_scope': rec['terminal_scope'] = 'factor_instance'
    elif mutation == 'missing_authority':
        rec.pop('stop_authority'); control.pop('stop_authority')
    elif mutation == 'iterate': rec['recommendation'] = 'iterate'
    elif mutation == 'candidate_formula': value['model_to_formula_translation']['candidate_formula'] = 'rank(close)'
    elif mutation == 'candidate_branch': value['recommended_branch_templates'] = [{'branch_id': 'contradiction'}]
    elif mutation == 'missing_reason':
        value.pop('no_candidate_revision_law_reason'); rec.pop('rationale')
    elif mutation == 'wrong_frozen_object': value['public_derivation_record']['mathematical_objects'] = [{'object': 'a different object'}]
    assert VALIDATOR.validate_agentic_result(value, expected_task=manifest['agent_tasks'][0],
        expected_report_id=RID, workspace_root=root)


@pytest.mark.parametrize('object_key', ['name', 'object', 'mathematical_object', 'string'])
def test_shared_object_matcher_retains_exact_labels(object_key):
    frozen = 'Joint intensity of relative decline and activity contraction'
    item = frozen if object_key == 'string' else {object_key: frozen}
    assert mathematical_object_present([item], frozen)
    for wrong in (frozen + ' proxy', frozen[:-1], '', None, {}, []):
        item = wrong if object_key == 'string' else {object_key: wrong}
        assert not mathematical_object_present([item], frozen)
    assert not mathematical_object_present([frozen], '')


def test_public_derivation_still_requires_object_records(advisory_results):
    root, _, _, manifest, results = advisory_results
    value = results[0]
    value['public_derivation_record']['mathematical_objects'] = [value['measurement_program_binding']['mathematical_object']]
    reasons = VALIDATOR.validate_agentic_result(value, expected_task=manifest['agent_tasks'][0],
        expected_report_id=RID, workspace_root=root)
    assert 'BLOCK_REVISION_COUNCIL_AGENTIC_OBJECTS_MISSING' in reasons


@pytest.mark.parametrize('object_key', ['name', 'object', 'mathematical_object'])
def test_cli_collect_merge_appendix_attach_preserve_hold_without_synthesizing_a_branch(advisory_results, object_key):
    root, council, packet, manifest, results = advisory_results
    for task, value in zip(manifest['agent_tasks'], results):
        frozen = value['measurement_program_binding']['mathematical_object']
        value['public_derivation_record']['mathematical_objects'] = [{object_key: frozen}]
        _write(root / task['expected_result_path'], value)
        view = ATTACH.proposal_from_agent_result(value, root / task['expected_result_path'])
        assert view['proposal_status'] == 'no_revision' and view['revision_type'] is None
        assert view['expression_change'] is None and view['candidate_revision_laws'] == []
        assert view['terminal_control'] == value['terminal_control']
    # Existing forbidden-writeback contract: all protected paths are absent in
    # this synthetic workspace and must stay absent throughout the consumer chain.
    packet['forbidden_writeback_baseline'] = {
        'contract_version': 'factorforge_revision_council_forbidden_writeback_baseline_v1',
        'paths': {key: {'exists': False, 'path': path} for key, path in {
            'handoff_to_step3b': f'objects/handoff/handoff_to_step3b__{RID}.json',
            'generated_code': f'generated_code/{RID}', 'official_library': f'objects/factor_library_official/factor_record__{RID}.json',
            'data_clean': 'data/clean'}.items()}}
    _write(council / f'revision_council_packet__{RID}.json', packet)
    iteration_path = root / 'objects/research_iteration_master' / f'research_iteration_master__{RID}.json'
    iteration = {'report_id': RID, 'research_judgment': {'decision': 'reject', 'research_memo': {
        'revision_strategy': {'revision_needed': False, 'revision_hypotheses': [], 'loop_authorization': 'advisory_only'}}},
        'loop_research_brief': {'json_path': 'reports/brief.json', 'markdown_path': 'reports/brief.md'}}
    _write(iteration_path, iteration)
    for script in ('validate_agentic_council_result.py', 'collect_agentic_council_results.py',
                   'validate_agentic_council_collection.py', 'merge_revision_council.py',
                   'build_council_derivation_appendix.py', 'attach_revision_council_to_step6.py'):
        _cli(root, script)
    summary = json.loads((council / f'revision_council_summary__{RID}.json').read_text())
    assert len(summary['valid_agent_results']) == len(results)
    assert summary['candidate_law_index'] == summary['recommended_branch_templates'] == []
    assert not summary['deterministic_fallback_used']
    assert all(route['terminal_control']['terminal_scope'] == 'revision_branch_only'
               for route in summary['research_route_summary'])
    updated = json.loads(iteration_path.read_text())
    assert updated['research_judgment']['decision'] == 'reject'
    assert updated['research_judgment']['research_memo']['final_revision_strategy']['revision_hypotheses'] == []
    assert updated['loop_action']['loop_authorization'] == 'advisory_only'
    assert updated['loop_action']['should_modify_step3b'] is False
    assert not (root / 'generated_code').exists() and not (root / 'data/clean').exists()
    assert not (root / 'objects/handoff').exists() and not (root / 'objects/factor_library_official').exists()
    assert not list(root.rglob('factor_proof_certificate*'))


def test_appendix_does_not_resurrect_a_legacy_hypothesis_when_laws_are_explicitly_empty(tmp_path):
    path = tmp_path / 'advisory.json'
    _write(path, {'candidate_revision_laws': [], 'revision_hypotheses': [{'law_statement': 'stale'}]})
    assert APPENDIX.build_agent_section(path)['candidate_revision_laws'] == []


@pytest.mark.parametrize('mutation', [None, 'hosted', 'unauthenticated', 'branch', 'handoff', 'no_results', 'council_law'])
def test_attachment_preserves_only_existing_authenticated_local_stop(monkeypatch, tmp_path, mutation):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    iteration = _terminal_iteration()
    memo = iteration['research_judgment']['research_memo']
    memo['revision_strategy'] = {'revision_needed': False, 'revision_hypotheses': [], 'terminal_local_rejection': True}
    memo['search_policy_decision'] = {'branch_templates': [], 'human_approval_required': False}
    handoff = tmp_path / 'handoff.json'
    if mutation == 'hosted': monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    elif mutation == 'unauthenticated': memo.pop('decision_source')
    elif mutation == 'branch': memo['search_policy_decision']['branch_templates'] = [{'branch_id': 'future'}]
    elif mutation == 'handoff': handoff.write_text('{}')
    before = deepcopy(iteration)
    summary = {'candidate_law_index': [], 'recommended_branch_templates': []}
    proposals = {'hold': {'producer': 'real_agent', 'proposal_status': 'no_revision', 'candidate_revision_laws': []}}
    if mutation == 'no_results': proposals = {}
    elif mutation == 'council_law': summary['candidate_law_index'] = [{'law_id': 'future'}]
    strategy = ATTACH.build_council_revision_strategy(iteration, summary, proposals, step3b_handoff_path=handoff)
    ATTACH.synchronize_loop_action_with_final_strategy(iteration, strategy)
    if mutation is None:
        assert iteration == before
        assert strategy['revision_quality'] == 'not_needed'
        assert strategy['council_disposition'] == 'advisory_no_revision'
        assert strategy['no_valid_council_proposal'] is False
    else:
        assert strategy['revision_quality'] == 'blocked'
        assert iteration['loop_action']['requires_human_approval_before_code_change'] is True
        assert iteration['loop_action']['should_modify_step3b'] is False
