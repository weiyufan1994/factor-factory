"""New local content rules, including real CLI consumers; synthetic inputs only."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from factor_factory.measurement_program import validate_measurement_program
from factor_factory.research_profiles import (
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE as V1,
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE_V2 as V2,
    research_compatibility_profile_from_spec,
    revision_evidence_minimum,
)
from factor_factory.revision_council.agentic_result import validate_agentic_result
from factor_factory.revision_council.validator import validate_revision_council_proposal
from scripts.run_agentic_council_dispatch_smoke import fake_real_agent_result
from tests import test_e_flexible_local_profile as legacy
from tests.test_factorforge_measurement_program_pipeline import COUNCIL_RUN
from tests.test_step6_council_phase_visibility import (
    RID, SCRIPT, _cli, _dispatch, _write, cli_taskbook,
)


def spec(profile=V2):
    return {'research_compatibility_profile': profile,
            'research_contract': {'research_compatibility_profile': profile}}


def write_spec(root, profile=V2, report_id=RID):
    _write(root / 'objects/factor_spec_master' / f'factor_spec_master__{report_id}.json', spec(profile))


def test_new_profile_is_explicit_and_does_not_relabel_v1():
    assert V1.endswith('_v1') and V2.endswith('_v2')
    for profile in (None, 'unknown', V1, {}, []):
        assert revision_evidence_minimum(profile, 'local_is_only') == 2
    assert revision_evidence_minimum(V2, 'hosted_formal') == 2
    assert revision_evidence_minimum(V2, 'local_is_only') == 1
    mismatched = spec()
    mismatched['research_compatibility_profile'] = V1
    assert revision_evidence_minimum(research_compatibility_profile_from_spec(mismatched), 'local_is_only') == 2


def test_primary_null_and_one_derivation_are_accepted_but_missing_null_is_not():
    program = legacy._flexible_program()
    program['compatibility_profile'] = V2
    options = dict(require_web_executable=False, compatibility_profile=V2, scope='local_is_only')
    assert validate_measurement_program(program, **options) == []
    program['model_selection']['candidate_models'].pop()
    assert validate_measurement_program(program, **options)
    options['scope'] = 'hosted_formal'
    assert 'measurement_program.compatibility_profile_invalid' in validate_measurement_program(program, **options)


@pytest.mark.parametrize('empty_learning', [True, False])
def test_v2_real_step1_step2_cli_and_step3_step5_step6_knowledge_consumers(tmp_path, monkeypatch, empty_learning):
    # Reuse the exact V1 consumer inputs; vary only their declared version.
    # This includes real Step1/2 CLIs and targeted Step3/5/6 consumers, not a factor backtest.
    monkeypatch.setattr(legacy, 'ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE', V2)
    legacy.test_bounded_local_step1_to_consumer_chain_uses_real_producers_and_validators(
        tmp_path, monkeypatch, empty_learning,
    )


def proposal(root):
    program = legacy._flexible_program()
    program['compatibility_profile'] = V2
    packet = {'report_id': RID, 'factor_formula': 'rank(close)',
              'mechanism_conditioned_measurement_program': program,
              'research_memo': {'revision_strategy': {'primary_failure_signature': 'mechanism_unclear'},
                                'mechanism_analysis': {'return_source': 'information_advantage'}}}
    value = COUNCIL_RUN.symbolic_law(packet)
    value['derivation_record'] = COUNCIL_RUN.build_derivation_record(packet, value)
    for item in value['derivation_record']['derived_implications']:
        item['expected_metric_signature'] = item['expected_metric_signature'][:1]
    for item in value['derivation_record']['revision_hypotheses'] + value['candidate_revision_laws']:
        for field in ('expected_metric_change', 'falsification_tests', 'kill_criteria'):
            item[field] = item[field][:1]
    write_spec(root)
    return value, program


def test_council_proposal_v2_uses_declared_workspace_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    value, program = proposal(tmp_path)
    validate = lambda: validate_revision_council_proposal(value, measurement_program=program, workspace_root=tmp_path)
    assert validate() == []
    write_spec(tmp_path, V1)
    assert any('DERIVATION' in reason for reason in validate())
    write_spec(tmp_path)
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    assert any('DERIVATION' in reason for reason in validate())


def test_no_action_requires_explicit_empty_and_reason_not_a_dummy_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    value, program = proposal(tmp_path)
    value.update(revision_type='no_action', candidate_revision_laws=[], research_equation_revision=None)
    record = value['derivation_record']
    record['revision_hypotheses'] = []
    record['revision_absence_reason'] = 'The observations do not distinguish a new estimator from the null.'
    validate = lambda v: validate_revision_council_proposal(v, measurement_program=program, workspace_root=tmp_path)
    assert validate(value) == []
    for field, invalid in [('revision_hypotheses', None), ('revision_hypotheses', {}), ('revision_absence_reason', '')]:
        bad = deepcopy(value)
        bad['derivation_record'][field] = invalid
        assert validate(bad)
    bad = deepcopy(value)
    bad['revision_type'] = 'expression_revision'
    assert validate(bad)


@pytest.fixture
def v2_dispatch(cli_taskbook, monkeypatch):
    root, council, packet = cli_taskbook
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    # Bind a new ordinary study before dispatch/results, then use real builders.
    write_spec(root)
    packet['mechanism_conditioned_measurement_program']['compatibility_profile'] = V2
    _write(council / f'revision_council_packet__{RID}.json', packet)
    _cli(root, SCRIPT.name, '--executor', 'dispatch_manifest', '--runtime-dispatch', 'codex', '--research-protocol', 'off')
    _, manifest = _dispatch(root, council)
    task = manifest['agent_tasks'][0]
    value = fake_real_agent_result(root, RID, task)  # Synthetic validator fixture, not an executed reviewer.
    value.update(research_compatibility_profile=V2, research_protocol_scope='local_is_only')
    for field in ('limiting_cases', 'falsification_tests', 'kill_criteria'):
        value['public_derivation_record'][field] = value['public_derivation_record'][field][:1]
    for law in value['candidate_revision_laws']:
        for field in ('expected_metric_change', 'falsification_tests', 'kill_criteria'):
            law[field] = law[field][:1]
    return root, council, manifest, task, value


def test_real_dispatch_template_and_validator_share_content_selection(v2_dispatch):
    root, council, _, task, value = v2_dispatch
    assert validate_agentic_result(value, expected_task=task, expected_report_id=RID, workspace_root=root) == []
    template = council / 'draft.json'
    _cli(root, 'write_agentic_council_result_template.py', '--task-id', task['task_id'], '--output', str(template))
    draft = json.loads(template.read_text())
    assert draft['status'] == 'draft' and draft['candidate_revision_laws'] == []
    assert draft['research_compatibility_profile'] == V2
    assert draft['research_protocol_scope'] == 'local_is_only'
    assert validate_agentic_result(draft, expected_task=task, expected_report_id=RID, workspace_root=root)
    _write(root / task['expected_result_path'], value)
    _cli(root, 'validate_agentic_council_result.py')


@pytest.mark.parametrize('mutation', ['no_task', 'task_v1', 'result_v1', 'spec_v1', 'hosted', 'empty_test', 'missing_test', 'wrong_object', 'fake_stop'])
def test_single_item_profile_keeps_identity_and_evidence_checks(v2_dispatch, monkeypatch, mutation):
    root, _, _, task, value = v2_dispatch
    if mutation == 'no_task': task = None
    elif mutation == 'task_v1': task['research_compatibility_profile'] = V1
    elif mutation == 'result_v1': value['research_compatibility_profile'] = V1
    elif mutation == 'spec_v1': write_spec(root, V1)
    elif mutation == 'hosted': monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    elif mutation == 'empty_test': value['public_derivation_record']['falsification_tests'] = []
    elif mutation == 'missing_test': value['public_derivation_record'].pop('falsification_tests')
    elif mutation == 'wrong_object': value['math_mechanism_derivation']['baseline_model'] = 'unrelated'
    elif mutation == 'fake_stop': value['candidate_revision_laws'] = []
    assert validate_agentic_result(value, expected_task=task, expected_report_id=RID, workspace_root=root)


def test_one_item_can_reach_approval_builder_without_padding():
    approval = legacy._load('skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py', 'approval_local_v2')
    selected = {'law_id': 'decay-estimator', 'expected_metric_signature': {'rank_ic': 'preserves sign outside the fitting window'},
                'falsification_tests': ['Frozen null has the same conditional spread.'],
                'kill_criteria': ['The predicted decay is absent.'], 'math_model_link': 'estimate decay using the observation equation'}
    hypothesis = approval.synthesis_revision_hypothesis(selected, 'direct_code')
    original = deepcopy(hypothesis)
    assert approval.revision_hypothesis_contract_ok(hypothesis, compatibility_profile=V2, scope='local_is_only')
    assert not approval.revision_hypothesis_contract_ok(hypothesis, compatibility_profile=V1, scope='local_is_only')
    assert not approval.revision_hypothesis_contract_ok(hypothesis, compatibility_profile=V2, scope='hosted_formal')
    assert hypothesis == original
    for invalid in ([], [''], [None], {'not': 'a list'}):
        bad = deepcopy(hypothesis)
        bad['falsification_tests'] = invalid
        assert not approval.revision_hypothesis_contract_ok(bad, compatibility_profile=V2, scope='local_is_only')


def test_main_memo_and_formula_projection_preserve_single_authored_test(monkeypatch):
    from tests.test_main_agent_memo_v1_direct_code_projection import _program, _spec, _complete_public_memo
    from factor_factory.mechanism_math.main_agent_memo import (
        formula_specific_derivation_from_main_agent_memo, validate_main_agent_mechanism_memo,
    )
    from factor_factory.mechanism_math.formula_specific import validate_formula_specific_derivation

    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    program = _program()
    program['compatibility_profile'] = V2
    source = {**_spec(program), **spec()}
    memo = _complete_public_memo(program)
    memo['math_hypothesis']['mechanism_equation_or_functional'] = (
        'price_t=value_t+pressure_t; E[pressure_{t+1}|F_t]=rho*pressure_t; '
        '0<rho<1 gives mean reversion of temporary pressure; '
        'measured_object_{i,t}=score_{i,t}'
    )
    memo['math_model_selection']['mechanism_equation_or_functional'] = (
        memo['math_hypothesis']['mechanism_equation_or_functional']
    )
    memo['expected_metric_signature'] = {'rank_ic': 'Frozen positive direction.'}
    memo['math_hypothesis']['expected_metric_signature'] = deepcopy(memo['expected_metric_signature'])
    memo['falsification_tests'] = ['Reject if the frozen conditional return is zero.']
    memo['kill_criteria'] = ['Stop this branch if the null reproduces the conditional spread.']
    memo['mechanism_qa']['falsification_answer'] = memo['falsification_tests'][0]
    original = deepcopy(memo)
    assert validate_main_agent_mechanism_memo(memo, source) == []
    projected = formula_specific_derivation_from_main_agent_memo(memo, source)
    assert projected['falsification_tests'] == memo['falsification_tests']
    assert projected['kill_criteria'] == memo['kill_criteria']
    assert validate_formula_specific_derivation(projected, source) == []
    assert memo == original
    for field in ('falsification_tests', 'kill_criteria'):
        for invalid in (None, [], [''], [None]):
            bad = deepcopy(memo)
            bad[field] = invalid
            assert validate_main_agent_mechanism_memo(bad, source)
            derived = formula_specific_derivation_from_main_agent_memo(bad, source)
            assert derived[field] == invalid  # No synthetic fallback test or kill rule.
            assert validate_formula_specific_derivation(derived, source)
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    assert validate_main_agent_mechanism_memo(memo, source)
