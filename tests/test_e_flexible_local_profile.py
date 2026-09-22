from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.measurement_program import (
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
    validate_measurement_program,
)
from factor_factory.research_conjecture import validate_research_conjecture
from factor_factory.knowledge_reference import (
    build_knowledge_reference_contract,
    build_legacy_knowledge_reference_contract,
)
from factor_factory.workspace_experience_export import export_workspace_knowledge_record
from scripts.run_factorforge_research_protocol_smoke import valid_conjecture

from tests.test_factorforge_measurement_program import _filled_program


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str, name: str):
    source = ROOT / path
    if str(source.parent) not in sys.path:
        sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flexible_program():
    program = _filled_program()
    program['compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    selection = program['model_selection']
    selection['candidate_models'] = selection['candidate_models'][:2]
    selection['candidate_models'][1]['candidate_role'] = 'null_alias'
    program['math_tool_selection']['candidate_tool_families'] = ['one_suitable_math_method']
    program['math_tool_selection']['selected_tool_families'] = ['one_suitable_math_method']
    program['math_tool_selection']['rejected_tool_families'] = []
    program['observation_and_estimation']['identification_assumptions'] = ['one explicit assumption']
    record = program['public_derivation_record']
    record['assumptions'] = ['one explicit assumption']
    record['key_derivation_steps'] = ['one auditable step']
    record['approximations'] = []
    return program


def test_profile_allows_one_method_primary_null_and_exact_computation():
    program = _flexible_program()
    assert validate_measurement_program(
        program,
        require_web_executable=False,
        compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        scope='local_is_only',
    ) == []

    for invalid in (None, 'wrong type'):
        candidate = deepcopy(program)
        candidate['math_tool_selection']['rejected_tool_families'] = invalid
        assert 'measurement_program.math_tool_selection.rejected_tool_families' in validate_measurement_program(
            candidate,
            require_web_executable=False,
            compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
            scope='local_is_only',
        )
    missing = deepcopy(program)
    del missing['math_tool_selection']['rejected_tool_families']
    assert 'measurement_program.math_tool_selection.rejected_tool_families' in validate_measurement_program(
        missing,
        require_web_executable=False,
        compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        scope='local_is_only',
    )


def test_profile_requires_object_binding_and_unknown_profile_stays_strict():
    program = _flexible_program()
    del program['compatibility_profile']
    reasons = validate_measurement_program(
        program,
        require_web_executable=False,
        compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        scope='local_is_only',
    )
    assert 'measurement_program.compatibility_profile_binding_invalid' in reasons
    strict = validate_measurement_program(program, require_web_executable=False)
    assert 'measurement_program.math_tool_selection.candidate_tool_families' in strict


def test_profile_validates_each_same_role_candidate_without_role_dict_overwrite():
    program = _flexible_program()
    base = deepcopy(program['model_selection']['candidate_models'][0])
    for index in range(4):
        candidate = deepcopy(base)
        candidate['candidate_id'] = f'alternative_{index}'
        candidate['candidate_role'] = 'mechanism_alternative'
        candidate['selected'] = False
        candidate['model_family'] = f'alternative_family_{index}'
        candidate['mathematical_object'] = f'alternative_object_{index}'
        candidate['mechanism_equation_or_functional'] = f'alt_mechanism_{index}(x)'
        candidate['target_functional'] = f'alt_target_{index}'
        candidate['market_outcome_projection'] = f'alt_projection_{index}'
        candidate['observation_mapping'] = f'alt_observation_{index}'
        program['model_selection']['candidate_models'].append(candidate)
    assert validate_measurement_program(
        program,
        require_web_executable=False,
        compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        scope='local_is_only',
    ) == []
    program['model_selection']['candidate_models'][-1].pop('decisive_test')
    reasons = validate_measurement_program(
        program,
        require_web_executable=False,
        compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        scope='local_is_only',
    )
    assert any('candidate_models[5].decisive_test' in item for item in reasons)


def test_step3_preserves_explicit_empty_without_fallback():
    module = _load('skills/factor-forge-step3/scripts/run_step3b.py', 'step3_context_e')
    context = module.build_step2_research_context(
        'E_REPORT',
        {
            'factor_id': 'E_FACTOR',
            'thesis': {'alpha_thesis': 'alpha', 'target_prediction': 'target', 'economic_mechanism': 'mechanism'},
            'math_discipline_review': {'mathematical_object': 'object', 'information_set_legality': 'IS', 'expected_failure_modes': ['failure']},
            'research_contract': {
                'target_statistic': 'target',
                'economic_mechanism': 'mechanism',
                'innovative_idea_seeds': [],
                'innovative_idea_seeds_absence_reason': 'No defensible neighboring idea was authored.',
                'similar_case_lessons_imported': [],
                'similar_case_lessons_absence_reason': 'No comparable case was retrieved.',
                'reuse_instruction_for_future_agents': ['preserve the thesis'],
                'research_compatibility_profile': ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
            },
        },
    )
    assert context['innovative_idea_seeds'] == []
    assert context['similar_case_lessons_imported'] == []
    assert context['research_compatibility_profile'] == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE


def test_step2_local_authored_producer_preserves_empty_lists_with_reasons(monkeypatch):
    module = _load('skills/factor-forge-step2/scripts/run_step2.py', 'step2_contract_e')
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    discipline = {
        'research_compatibility_profile': ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        'target_statistic_hint': 'target statistic',
        'step1_mathematical_object': 'mathematical object',
        'economic_mechanism': 'economic mechanism',
        'market_process_thesis': {'economic_hypothesis': 'economic mechanism'},
        'expected_failure_modes': ['failure mode'],
        'innovative_idea_seeds': [],
        'innovative_idea_seeds_absence_reason': 'No defensible neighboring idea was authored.',
        'reuse_instruction_for_future_agents': ['preserve the thesis'],
        'similar_case_lessons_imported': [],
        'similar_case_lessons_absence_reason': 'No comparable case was retrieved.',
        'factor_knowledge_context': {'schema_version': 'v1', 'nodes': []},
        'knowledge_reference_contract': {'contract_version': 'caller-authored'},
    }
    aim = {
        'local_agent_spec_inputs': {'declared': True},
        'research_discipline': discipline,
    }
    contract = module.build_step2_research_contract({}, {}, aim, {})
    assert contract['innovative_idea_seeds'] == []
    assert contract['similar_case_lessons_imported'] == []
    assert contract['research_compatibility_profile'] == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE


def test_research_conjecture_profile_relaxes_only_declared_quota():
    conjecture = valid_conjecture()
    conjecture['research_compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    conjecture['local_is_policy'] = {
        'scope': 'ordinary_local_is_only',
        'oos_allocation_allowed': False,
        'oos_access_allowed': False,
        'oos_finalization_allowed': False,
        'recovery_allowed': False,
        'child_revision_allowed': False,
        'official_promotion_allowed': False,
        'canonical_writeback_allowed': False,
    }
    for key in ('oos_start', 'oos_end', 'sealed_oos_token_hash'):
        conjecture['evidence_policy'].pop(key, None)
    conjecture['math_mechanism']['limiting_cases'] = conjecture['math_mechanism']['limiting_cases'][:1]
    conjecture['math_mechanism']['expected_metric_signatures'] = conjecture['math_mechanism']['expected_metric_signatures'][:1]
    conjecture['economic_game']['participants'] = conjecture['economic_game']['participants'][:1]
    conjecture['hypotheses'] = [
        item for item in conjecture['hypotheses'] if item.get('kind') != 'alternative'
    ]
    assert validate_research_conjecture(
        conjecture,
        scope='local_is_only',
        compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
    ) == []
    assert validate_research_conjecture(
        conjecture,
        scope='local_is_only',
    )
    missing_null = deepcopy(conjecture)
    missing_null['hypotheses'] = [
        item for item in missing_null['hypotheses'] if item.get('kind') != 'null'
    ]
    assert 'BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_DUAL_HYPOTHESIS_MISSING' in validate_research_conjecture(
        missing_null,
        scope='local_is_only',
        compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
    )


@pytest.mark.parametrize(
    ('spec_profile', 'top_profile', 'local_flag', 'expected_returncode'),
    [
        (ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE, ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE, True, 0),
        (None, None, True, 1),
        ('unknown_profile', 'unknown_profile', True, 1),
        (ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE, 'conflicting_profile', True, 1),
        (ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE, ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE, False, 1),
    ],
)
def test_research_protocol_cli_uses_report_bound_profile(
    tmp_path, spec_profile, top_profile, local_flag, expected_returncode
):
    from scripts.run_factorforge_research_protocol_smoke import valid_approaches, valid_state
    from tests.test_factorforge_research_protocol_local_is_scope import local_is_conjecture

    conjecture = local_is_conjecture()
    approaches = valid_approaches()
    report_id = conjecture['report_id']
    conjecture['research_compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    approaches['research_compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    inputs_dir = tmp_path / 'authored-inputs'
    inputs_dir.mkdir()
    input_paths = {}
    for name, payload in (
        ('state', valid_state()), ('conjecture', conjecture), ('approaches', approaches)
    ):
        path = inputs_dir / f'{name}.json'
        path.write_text(json.dumps(payload))
        input_paths[name] = path
    contract = {}
    if spec_profile is not None:
        contract['research_compatibility_profile'] = spec_profile
    spec = {'report_id': report_id, 'research_contract': contract}
    if top_profile is not None:
        spec['research_compatibility_profile'] = top_profile
    spec_path = (
        tmp_path / 'objects/factor_spec_master' / f'factor_spec_master__{report_id}.json'
    )
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec))
    writer_command = [
        sys.executable,
        str(ROOT / 'scripts/write_factorforge_research_protocol.py'),
        '--workspace-root', str(tmp_path),
        '--report-id', report_id,
        '--state', str(input_paths['state']),
        '--conjecture', str(input_paths['conjecture']),
        '--approaches', str(input_paths['approaches']),
    ]
    if local_flag:
        writer_command.append('--local-is-only')
    writer = subprocess.run(writer_command, cwd=ROOT, text=True, capture_output=True)
    assert writer.returncode == expected_returncode, writer.stdout + writer.stderr
    if expected_returncode:
        report = json.loads(writer.stderr)
        assert any('COMPATIBILITY_PROFILE' in reason for reason in report['block_reasons'])
        return

    validator_command = [
        sys.executable,
        str(ROOT / 'scripts/validate_factorforge_research_protocol.py'),
        '--workspace-root', str(tmp_path),
        '--report-id', report_id,
        '--stage', 'pre_council',
    ]
    if local_flag:
        validator_command.append('--local-is-only')
    validator = subprocess.run(validator_command, cwd=ROOT, text=True, capture_output=True)
    assert validator.returncode == 0, validator.stdout + validator.stderr


def test_protocol_writer_and_validator_keep_unmarked_old_local_strict(tmp_path):
    from scripts.run_factorforge_research_protocol_smoke import valid_approaches, valid_state
    from tests.test_factorforge_research_protocol_local_is_scope import local_is_conjecture

    conjecture = local_is_conjecture()
    report_id = conjecture['report_id']
    inputs_dir = tmp_path / 'old-authored-inputs'
    inputs_dir.mkdir()
    paths = {}
    for name, payload in (
        ('state', valid_state()), ('conjecture', conjecture), ('approaches', valid_approaches())
    ):
        path = inputs_dir / f'{name}.json'
        path.write_text(json.dumps(payload))
        paths[name] = path
    writer = subprocess.run([
        sys.executable, str(ROOT / 'scripts/write_factorforge_research_protocol.py'),
        '--workspace-root', str(tmp_path), '--report-id', report_id,
        '--state', str(paths['state']), '--conjecture', str(paths['conjecture']),
        '--approaches', str(paths['approaches']), '--local-is-only',
    ], cwd=ROOT, text=True, capture_output=True)
    assert writer.returncode == 0, writer.stdout + writer.stderr
    validator = subprocess.run([
        sys.executable, str(ROOT / 'scripts/validate_factorforge_research_protocol.py'),
        '--workspace-root', str(tmp_path), '--report-id', report_id,
        '--stage', 'pre_council', '--local-is-only',
    ], cwd=ROOT, text=True, capture_output=True)
    assert validator.returncode == 0, validator.stdout + validator.stderr


def test_step6_empty_authored_reflection_does_not_get_template_reason():
    module = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_learning_e')
    result = module.build_learning_and_innovation(
        {'monetization_model': 'mixed', 'factor_family': 'other'},
        'reject',
        [],
        [],
        [],
        {'similar_cases': []},
        authored_learning={
            'transferable_patterns': [],
            'anti_patterns': [],
            'similar_case_lessons_imported': [],
            'innovative_idea_seeds': [],
            'reuse_instruction_for_future_agents': [],
        },
        flexible_local=True,
    )
    assert result['innovative_idea_seeds'] == []
    assert 'innovative_idea_seeds_absence_reason' not in result


def test_step6_invalid_or_partial_authored_reflection_is_preserved_for_block():
    module = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_invalid_learning_e')
    result = module.build_learning_and_innovation(
        {'monetization_model': 'mixed', 'factor_family': 'other'},
        'iterate',
        ['generated strength must not replace the author'],
        [],
        [],
        {'similar_cases': []},
        authored_learning={'innovative_idea_seeds': 'invalid string'},
        flexible_local=True,
    )
    assert result['innovative_idea_seeds'] == 'invalid string'
    assert 'reuse_instruction_for_future_agents' not in result
    assert 'similar_case_lessons_imported' not in result


@pytest.mark.parametrize(
    ('authored', 'expected_present', 'expected_valid'),
    [
        ({'innovative_idea_seeds_absence_reason': 'Reason without a declaration.'}, False, False),
        ({'innovative_idea_seeds': 'invalid string', 'innovative_idea_seeds_absence_reason': 'Reason.'}, True, False),
        ({'innovative_idea_seeds': [], 'innovative_idea_seeds_absence_reason': 'No defensible idea.'}, True, True),
        ({'innovative_idea_seeds': ['authored idea']}, True, True),
    ],
)
def test_step6_learning_four_states_reach_validator_without_synthesis(authored, expected_present, expected_valid):
    producer = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_learning_states_e')
    validator = _load('skills/factor-forge-step6/scripts/validate_step6.py', 'step6_learning_validator_e')
    result = producer.build_learning_and_innovation(
        {'monetization_model': 'mixed', 'factor_family': 'other'},
        'reject', [], [], [], {'similar_cases': []},
        authored_learning=authored, flexible_local=True,
    )
    assert ('innovative_idea_seeds' in result) is expected_present
    assert validator.learning_list_state_valid(result, 'innovative_idea_seeds', True) is expected_valid


def test_step6_explicit_empty_reuse_instruction_requires_its_own_reason():
    producer = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_reuse_state_e')
    validator = _load('skills/factor-forge-step6/scripts/validate_step6.py', 'step6_reuse_validator_e')
    result = producer.build_learning_and_innovation(
        {'monetization_model': 'mixed', 'factor_family': 'other'},
        'reject', [], [], [], {},
        authored_learning={
            'reuse_instruction_for_future_agents': [],
            'reuse_instruction_for_future_agents_absence_reason': 'No safe reuse instruction was established.',
        },
        flexible_local=True,
    )
    assert validator.learning_list_state_valid(
        result, 'reuse_instruction_for_future_agents', True
    )


def test_step6_search_policy_four_states_and_author_text_are_preserved():
    module = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_policy_e')
    validator = _load('skills/factor-forge-step6/scripts/validate_step6.py', 'step6_policy_validator_e')
    missing = module.build_program_search_policy({}, {}, {}, 'reject', [], {}, flexible_local=True)
    invalid = module.build_program_search_policy(
        {}, {}, {}, 'reject', [], {'authored_program_search_policy': ['wrong type']}, flexible_local=True
    )
    explicit_empty = {
        'method_library': {},
        'method_library_absence_reason': 'The stopped study authored no search method.',
        'warnings': ['OOS evidence is unavailable and must not be used.'],
    }
    populated = {
        'method_library': {'boosted_choice': {'selection_objective': 'Choose boosted IS controls'}},
        'recommended_next_search': {'branches': [{'branch_id': 'authored'}]},
    }
    for authored, expected in ((explicit_empty, True), (populated, True)):
        result = module.build_program_search_policy(
            {}, {}, {}, 'reject', [], {'authored_program_search_policy': authored}, flexible_local=True
        )
        assert result == authored
        assert validator.program_search_methods_valid(result, 'reject', True) is expected
        assert validator.illegal_local_search_targets(result) == []
    assert missing == {}
    assert validator.program_search_methods_valid(missing, 'reject', True) is False
    assert invalid == {'authored_program_search_policy_invalid': ['wrong type']}
    assert validator.program_search_methods_valid(invalid, 'reject', True) is False
    assert validator.illegal_local_search_targets({
        'method_library': {'bad': {'selection_objective': 'out_of_sample_rank_ic_ir'}}
    }) == ['program_search_policy.method_library.bad.selection_objective']
    assert validator.illegal_local_search_targets({
        'method_library': {'bad': {'objective': 'maximize OOS Sharpe without increasing complexity'}}
    }) == ['program_search_policy.method_library.bad.objective']
    assert validator.illegal_local_search_targets({
        'method_library': {'bad': {'reward': 'improve out_of_sample_rank_ic_ir, not turnover'}}
    }) == ['program_search_policy.method_library.bad.reward']
    assert validator.illegal_local_search_targets({
        'warnings': ['OOS evidence is unavailable and must not be used.'],
    }) == []


def test_step6_state_gates_reject_non_string_items_and_non_object_methods():
    validator = _load('skills/factor-forge-step6/scripts/validate_step6.py', 'step6_typed_state_validator_e')
    assert not validator.learning_list_state_valid(
        {'innovative_idea_seeds': [None]}, 'innovative_idea_seeds', True
    )
    assert not validator.next_research_tests_state_valid(
        {'next_research_tests': [{}]}, True
    )
    assert not validator.program_search_methods_valid(
        {'method_library': {'m': None}}, 'reject', True
    )
    assert validator.learning_list_state_valid(
        {'innovative_idea_seeds': ['authored idea']}, 'innovative_idea_seeds', True
    )
    assert validator.next_research_tests_state_valid(
        {'next_research_tests': ['authored next test']}, True
    )
    assert validator.program_search_methods_valid(
        {'method_library': {'m': {'objective': 'IS control'}}}, 'reject', True
    )


@pytest.mark.parametrize(
    ('authored_body', 'expected_tests', 'expected_reason'),
    [
        ({}, [], None),
        ({'next_research_tests': 'wrong', 'next_research_tests_absence_reason': 'Reason.'}, [], None),
        ({'next_research_tests': [], 'next_research_tests_absence_reason': 'No next test after stop.'}, [], 'No next test after stop.'),
        ({'next_research_tests': ['authored next test']}, ['authored next test'], None),
    ],
)
def test_build_research_memo_preserves_next_test_four_states(monkeypatch, authored_body, expected_tests, expected_reason):
    module = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_real_memo_states_e')
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    monkeypatch.setattr(module, 'build_formula_understanding', lambda _: {})
    monkeypatch.setattr(module, 'build_metric_interpretation', lambda *_: {
        'verdict': 'inconclusive', 'long_side_adoption_review': {},
    })
    monkeypatch.setattr(module, 'build_math_discipline_review', lambda *_: {})
    bundle = {
        'factor_run_master': {'evaluation_results': {'backend_runs': []}},
        'factor_spec_master': {'research_contract': {
            'research_compatibility_profile': ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        }},
    }
    memo = module.build_research_memo(bundle, {}, {}, {}, 'reject', authored_memo=authored_body)
    assert memo['next_research_tests'] == expected_tests
    assert memo['next_research_tests_absence_reason'] == expected_reason
    validator = _load('skills/factor-forge-step6/scripts/validate_step6.py', 'step6_next_tests_validator_e')
    expected_valid = bool(expected_tests) or bool(expected_reason)
    assert validator.next_research_tests_state_valid(memo, True) is expected_valid


def test_legacy_local_window_loader_returns_before_touching_window_file(tmp_path, monkeypatch):
    module = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_legacy_window_guard_e')
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    monkeypatch.setattr(module, 'OBJ', tmp_path / 'objects')
    path = tmp_path / 'objects/window_evidence/window_evidence__LEGACY.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"old_oos_payload": true}')
    monkeypatch.setattr(
        module, 'load_json',
        lambda *_: (_ for _ in ()).throw(AssertionError('legacy local path read window evidence')),
    )
    assert module.load_window_evidence('LEGACY') == {}


def test_iteration_producer_preserves_current_author_and_never_loads_local_oos(monkeypatch):
    module = _load('skills/factor-forge-step6/scripts/run_step6.py', 'step6_iteration_e')
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    authored_learning = {
        'transferable_patterns': ['authored pattern'],
        'anti_patterns': ['authored anti-pattern'],
        'similar_case_lessons_imported': [],
        'similar_case_lessons_absence_reason': 'No comparable case was retrieved.',
        'innovative_idea_seeds': [],
        'innovative_idea_seeds_absence_reason': 'No defensible neighboring idea was authored.',
        'reuse_instruction_for_future_agents': ['authored reuse'],
    }
    authored_policy = {
        'method_library': {'declared_method': {'objective': 'IS-only'}},
        'recommended_next_search': {
            'branches': [{'branch_id': 'authored_branch'}],
            'requires_human_approval_before_code_change': True,
        },
    }
    authored_memo = {
        'learning_and_innovation': authored_learning,
        'program_search_policy': authored_policy,
        'next_research_tests': ['authored next test'],
    }
    monkeypatch.setattr(module, 'load_window_evidence', lambda _: (_ for _ in ()).throw(AssertionError('local path read OOS')))
    monkeypatch.setattr(module, 'load_researcher_journal', lambda _: {})
    monkeypatch.setattr(module, 'load_researcher_agent_memo', lambda _: authored_memo)
    monkeypatch.setattr(module, 'decide', lambda *_: 'reject')
    monkeypatch.setattr(module, 'local_reviewers_agree_to_reject', lambda *_: False)
    monkeypatch.setattr(module, 'derive_strengths_weaknesses', lambda *_: ([], [], [], []))
    monkeypatch.setattr(module, 'extract_headline_metrics', lambda *_: {})
    monkeypatch.setattr(module, 'summarize_window_evidence', lambda value: ([], []))
    monkeypatch.setattr(module, 'build_retrieval_context', lambda *_: {'similar_cases': []})
    monkeypatch.setattr(module, 'build_evidence_status', lambda **_: {})
    monkeypatch.setattr(module, 'infer_research_framework', lambda *_: {
        'factor_family': 'other', 'monetization_model': 'mixed', 'bias_type': 'other',
        'return_source_hypothesis': 'authored source', 'expected_failure_regimes': [],
        'objective_constraint_dependency': 'none', 'constraint_sources': [],
        'crowding_risk': 'unknown', 'capacity_constraints': 'unknown',
        'implementation_risk': 'unknown', 'improvement_frontier': [],
        'program_search_axes': [], 'review_checklist': [], 'research_commentary': [],
        'revision_principles': [],
    })
    monkeypatch.setattr(module, 'build_formula_understanding', lambda _: {})
    monkeypatch.setattr(module, 'build_metric_interpretation', lambda *_: {
        'verdict': 'inconclusive', 'long_side_adoption_review': {},
    })
    monkeypatch.setattr(module, 'build_math_discipline_review', lambda *_: {})
    monkeypatch.setattr(module, 'build_experience_chain', lambda *args: {})
    monkeypatch.setattr(module, 'build_revision_taxonomy', lambda *args: {'macro_revision': {}, 'micro_revision': {}, 'expression_revision': {}, 'portfolio_revision': {'forbidden': True}})
    monkeypatch.setattr(module, 'build_diversity_position', lambda *args: {})
    monkeypatch.setattr(module, 'build_evidence_audit', lambda *args: {})
    monkeypatch.setattr(module, 'build_mechanism_analysis', lambda *args: {})
    monkeypatch.setattr(module, 'build_formula_specific_derivation', lambda *args: {})
    monkeypatch.setattr(module, 'validate_mechanism_formula_consistency', lambda *args: {})
    monkeypatch.setattr(module, 'build_case_comparison', lambda *args: {})
    monkeypatch.setattr(module, 'build_revision_strategy', lambda *args: {'revision_needed': False, 'loop_authorization': 'advisory_only', 'revision_quality': 'not_needed', 'primary_failure_signature': 'none'})
    monkeypatch.setattr(module, 'build_search_policy_decision', lambda *args: {'branch_templates': [], 'recommended_mode': 'kill', 'human_approval_required': False, 'selection_rationale': []})
    monkeypatch.setattr(module, 'should_write_step3b_handoff', lambda *args: False)
    monkeypatch.setattr(module, '_project_authored_failure_regimes', lambda memo, _: memo)

    bundle = {
        'factor_run_master': {
            'report_id': 'E_ITERATION', 'factor_id': 'E_FACTOR', 'run_status': 'complete',
            'evaluation_results': {'backend_runs': []}, 'evaluation_plan': {}, 'artifact_identity': {},
        },
        'factor_case_master': {'factor_id': 'E_FACTOR', 'final_status': 'rejected'},
        'factor_evaluation': {}, 'handoff_to_step6': {},
        'factor_spec_master': {'research_contract': {
            'research_compatibility_profile': ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
        }},
        'paths': {'handoff_to_step6': 'handoff.json'},
    }
    result = module.build_iteration_payload(bundle, {})
    memo = result['research_judgment']['research_memo']
    for key, value in authored_learning.items():
        assert memo['learning_and_innovation'].get(key) == value
    assert memo['program_search_policy']['method_library'] == authored_policy['method_library']
    assert memo['program_search_policy']['recommended_next_search'] == authored_policy['recommended_next_search']
    assert memo['next_research_tests'] == ['authored next test']


def test_bounded_local_step1_to_consumer_chain_uses_real_producers_and_validators(tmp_path, monkeypatch):
    import scripts.build_factorforge_retrieval_index as indexer
    from tests.test_run_factorforge_local_step1 import (
        REPORT_ID, inputs, invoke, make_workspace,
    )
    from tests.test_step2_local_agent_spec_inputs import STEP2, _raw_spec

    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    workspace = make_workspace(tmp_path)
    files = inputs(tmp_path)
    factor_id = 'DISTINCT_CHIEF_FACTOR_ID'
    refs = {}
    raw_specs = {}
    for route, role in (
        ('primary', 'local_agent_primary_spec'),
        ('challenger', 'local_agent_challenger_spec'),
    ):
        raw = _raw_spec(route)
        raw.update(report_id=REPORT_ID, factor_id=factor_id)
        raw_specs[route] = raw
        relative = f'objects/local_agent_specs/{route}.json'
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
        target.write_bytes(content)
        refs[route] = {
            'relative_path': relative,
            'sha256': hashlib.sha256(content).hexdigest(),
            'role': role,
            'identity': {'report_id': REPORT_ID, 'factor_id': factor_id, 'route': route},
        }
    refs['chief_canonical_core'] = {
        key: raw_specs['primary'][key]
        for key in STEP2.LOCAL_AGENT_SPEC_CANONICAL_CORE_FIELDS
    }
    chief = json.loads(files['chief'].read_text())
    merge = chief['chief_merge']
    merge['source_type'] = 'pdf_report'
    merge['local_agent_spec_inputs'] = refs
    merge['final_factor']['construction_id'] = factor_id
    merge['source_baseline_reference'] = {
        'source_construction_id': factor_id,
        'selected_construction_id': factor_id,
        'relation': 'selected_baseline',
    }
    merge['source_semantic_review'] = {
        'status': 'match',
        'reviewer_basis': 'Authored source and selected components match.',
        'compared_source_components': ['PF', 'VV'],
        'compared_selected_components': ['PF', 'VV'],
        'material_deviations': [],
    }
    discipline = merge['research_discipline']
    discipline['research_compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    discipline['mechanism_conditioned_measurement_program']['compatibility_profile'] = (
        ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    )
    discipline['economic_hypothesis'] = {
        'macro_return_source': 'mixed',
        'second_layer': {
            'subtype': 'local state pricing',
            'expected_counterparty_or_payer': 'constrained liquidity demand',
            'why_they_may_pay': 'execution timing constraint',
        },
        'counterparty_loss_hypothesis': 'The payer loses through adverse timing.',
    }
    discipline['math_hypothesis_candidates'] = [{
        'hypothesis_id': 'H1',
        'linked_economic_hypothesis': 'local state pricing',
        'model_family': 'conditional moment',
        'math_tools': ['conditional expectation'],
        'observable_estimator': 'cross sectional score',
        'target_functional': 'conditional mean return',
        'why_suitable': 'Maps an observed state to a payoff.',
        'falsification_tests': ['The conditional spread is zero.'],
        'mathematical_object': 'conditional occupation state',
        'mechanism_equation_or_functional': 'E[r|state]-E[r]',
    }]
    discipline['knowledge_reference_contract'] = build_legacy_knowledge_reference_contract(
        similar_case_lessons=discipline['similar_case_lessons_imported'],
        producer='bounded_chain_step1',
    )
    files['chief'].write_text(json.dumps(chief, ensure_ascii=False))

    step1 = invoke(workspace, files)
    assert step1.returncode == 0, step1.stderr

    env = os.environ.copy()
    env.update({
        'FACTORFORGE_ROOT': str(workspace),
        'FACTORFORGE_LOCAL_IS_ONLY': '1',
        'FACTORFORGE_ULTIMATE_RUN': '1',
        'FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL': '1',
        'FACTORFORGE_DISABLE_GRAPH_KNOWLEDGE_CONTEXT': '1',
    })
    for script in (
        'skills/factor-forge-step2/scripts/run_step2.py',
        'skills/factor-forge-step2/scripts/validate_step2.py',
    ):
        completed = subprocess.run(
            [sys.executable, str(ROOT / script), '--report-id', REPORT_ID],
            cwd=ROOT, env=env, text=True, capture_output=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    spec = json.loads((
        workspace / 'objects/factor_spec_master' / f'factor_spec_master__{REPORT_ID}.json'
    ).read_text())
    handoff = json.loads((
        workspace / 'objects/handoff' / f'handoff_to_step3__{REPORT_ID}.json'
    ).read_text())
    step3_actual = _load('skills/factor-forge-step3/scripts/run_step3.py', 'bounded_chain_step3_actual_e')
    validated_program = step3_actual.validated_measurement_program_for_step3(
        spec,
        handoff,
        implementation_mode=spec['implementation_mode'],
    )
    assert validated_program == spec['mechanism_conditioned_measurement_program']

    main_memo = _load(
        'factor_factory/mechanism_math/main_agent_memo.py',
        'factor_factory.mechanism_math.bounded_chain_main_memo_e',
    )
    memo_program, memo_failures = main_memo._validated_measurement_program_from_factor_spec(spec)
    assert memo_failures == []
    assert memo_program == validated_program

    step5 = _load('skills/factor-forge-step5/scripts/validate_step5.py', 'bounded_chain_step5_e')
    assert step5.measurement_program_failures_for_step5(
        {'mechanism_conditioned_measurement_program': validated_program}, spec
    ) == []

    council_packet = _load(
        'skills/factor-forge-step6/scripts/build_revision_council_packet.py',
        'bounded_chain_council_packet_e',
    )
    assert council_packet.measurement_program_for_packet(
        spec,
        {'mechanism_conditioned_measurement_program': validated_program},
        handoff,
        {},
    ) == validated_program

    conflicting_spec = deepcopy(spec)
    conflicting_spec['research_compatibility_profile'] = 'conflicting_profile'
    with pytest.raises(SystemExit, match='MEASUREMENT_PROGRAM_INVALID'):
        step3_actual.validated_measurement_program_for_step3(
            conflicting_spec,
            handoff,
            implementation_mode=spec['implementation_mode'],
        )

    step3 = _load('skills/factor-forge-step3/scripts/run_step3b.py', 'bounded_chain_step3_e')
    step3_context = step3.build_step2_research_context(REPORT_ID, spec, handoff)
    assert step3_context['research_compatibility_profile'] == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE

    step6 = _load('skills/factor-forge-step6/scripts/run_step6.py', 'bounded_chain_step6_e')
    validator = _load('skills/factor-forge-step6/scripts/validate_step6.py', 'bounded_chain_step6_validator_e')
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    monkeypatch.setattr(step6, 'build_formula_understanding', lambda _: {})
    monkeypatch.setattr(step6, 'build_metric_interpretation', lambda *_: {
        'verdict': 'inconclusive', 'long_side_adoption_review': {},
    })
    monkeypatch.setattr(step6, 'build_math_discipline_review', lambda *_: {})
    memo = step6.build_research_memo(
        {
            'factor_run_master': {'evaluation_results': {'backend_runs': []}},
            'factor_spec_master': spec,
        },
        {}, {}, {}, 'reject',
        authored_memo={
            'next_research_tests': [],
            'next_research_tests_absence_reason': 'The stopped study has no next test.',
        },
    )
    learning = step6.build_learning_and_innovation(
        {'factor_family': 'other', 'monetization_model': 'mixed'},
        'reject', [], [], [], {},
        authored_learning={
            'transferable_patterns': [],
            'transferable_patterns_absence_reason': 'No transferable pattern was established.',
            'anti_patterns': ['Do not optimize on unavailable evidence.'],
            'similar_case_lessons_imported': [],
            'similar_case_lessons_absence_reason': 'No comparable case was imported.',
            'innovative_idea_seeds': [],
            'innovative_idea_seeds_absence_reason': 'No defensible neighboring idea was authored.',
            'reuse_instruction_for_future_agents': ['Reuse only as a bounded local example.'],
        },
        flexible_local=True,
    )
    learning['research_compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    assert validator.learning_list_state_valid(learning, 'innovative_idea_seeds', True)
    policy = {
        'method_library': {},
        'method_library_absence_reason': 'The stopped study authored no search method.',
        'warnings': ['OOS evidence is unavailable and must not be used.'],
    }
    assert validator.program_search_methods_valid(policy, 'reject', True)
    assert validator.illegal_local_search_targets(policy) == []

    memo['research_compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    iteration = {
        'report_id': REPORT_ID,
        'factor_id': factor_id,
        'research_judgment': {'decision': 'reject', 'research_memo': memo},
        'knowledge_writeback': {
            'success_patterns': [], 'failure_patterns': ['bounded failure'],
            'modification_hypotheses': [], 'factor_family': 'other',
            'monetization_model': 'mixed', 'bias_type': 'unidentified',
            'return_source_hypothesis': 'authored bounded hypothesis',
            'expected_failure_regimes': ['timing constraint absent'],
            'objective_constraint_dependency': 'unknown', 'constraint_sources': [],
            'crowding_risk': 'unknown', 'capacity_constraints': 'unknown',
            'implementation_risk': 'unknown', 'improvement_frontier': [],
            'program_search_axes': [], 'review_checklist': [],
            'revision_principles': [], 'research_commentary': [],
            'learning_and_innovation': learning, 'experience_chain': {},
            'revision_taxonomy': {}, 'program_search_policy': policy,
            'diversity_position': {},
        },
        'created_at_utc': '2026-09-22T00:00:00Z',
    }
    knowledge = step6.build_knowledge_record(iteration)
    knowledge_path = workspace / 'objects/research_knowledge_base' / f'knowledge_record__{REPORT_ID}.json'
    knowledge_path.parent.mkdir(parents=True, exist_ok=True)
    knowledge_path.write_text(json.dumps(knowledge, ensure_ascii=False))

    consumer_root = tmp_path / 'consumer'
    (consumer_root / 'objects').mkdir(parents=True)
    export_workspace_knowledge_record(
        workspace=workspace, repo_root=consumer_root, report_id=REPORT_ID,
    )
    monkeypatch.setattr(indexer, 'REPO_ROOT', consumer_root)
    indexer.refresh_retrieval_index(consumer_root)
    consumed = build_knowledge_reference_contract(
        repo_root=consumer_root,
        knowledge_root=consumer_root / 'knowledge',
        query_text='authored bounded hypothesis bounded failure',
        producer='bounded_chain_consumer', top_k=1, retrieval_required=True,
    )['retrieved_cases'][0]
    assert consumed['learning_and_innovation'] == learning
    assert consumed['research_compatibility_profile'] == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    assert consumed['next_research_tests_absence_reason'] == 'The stopped study has no next test.'
