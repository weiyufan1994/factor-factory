from __future__ import annotations

import importlib.util
from pathlib import Path
from copy import deepcopy


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEP2 = _load('factorforge_step2_source_subject_routing', 'skills/factor-forge-step2/scripts/run_step2.py')
VALIDATOR = _load('factorforge_step2_source_subject_routing_validator', 'skills/factor-forge-step2/scripts/validate_step2.py')


def _validator_master(routing: dict | None, construction_id: str) -> dict:
    master = {
        'contract_version': VALIDATOR.STEP2_SOURCE_CONTRACT_VERSION,
        'source_subject_routing_required': True,
        'selected_construction_id': construction_id,
        'canonical_spec': {'construction_id': construction_id},
    }
    if routing is not None:
        master['source_subject_routing'] = routing
    return master


def _validator_handoff(routing: dict | None) -> dict:
    handoff = {'source_subject_routing_required': True}
    if routing is not None:
        handoff['source_subject_routing'] = routing
    return handoff


def _spec(route: str, factor_id: str = 'selected_pf_vv') -> dict:
    return {
        'factor_id': factor_id,
        'report_id': 'RPT_SOURCE_SUBJECT',
        'route': route,
        'required_inputs': ['high', 'volume'],
        'rebalance_frequency': 'monthly',
        'raw_formula_text': 'PF + VV',
        'operators': ['rank'],
    }


def _review(status: str = 'match') -> dict:
    return {
        'status': status,
        'reviewer_basis': 'Compared the source-described PF/VV construction with the selected construction.',
        'compared_source_components': ['PF', 'VV', 'equal_weight_monthly_combination'],
        'compared_selected_components': ['PF', 'VV', 'equal_weight_monthly_combination'],
        'material_deviations': [],
    }


def _reference(selected_id: str, relation: str) -> dict:
    return {
        'source_construction_id': 'source_pf_vv_equal_weight',
        'selected_construction_id': selected_id,
        'relation': relation,
    }


def _aim(mode: str | None, selected_id: str = 'selected_pf_vv') -> dict:
    aim = {'final_factor': {'construction_id': selected_id}}
    if mode is not None:
        aim['research_subject_mode'] = mode
    return aim


def _score(aim: dict, factor_id: str = 'selected_pf_vv') -> dict:
    return STEP2.score_consistency(
        _spec('primary', factor_id),
        _spec('challenger', factor_id),
        aim,
    )


def test_report_replication_requires_structured_source_comparison_not_score() -> None:
    aim = _aim('report_replication')
    aim['source_baseline_reference'] = _reference('selected_pf_vv', 'selected_baseline')
    aim['source_semantic_review'] = _review('match')

    result = _score(aim)

    assert result['consistency_score'] == 0.82
    assert result['mechanical_consistency_passed'] is True
    assert result['matches_core_driver'] is True
    assert result['recommendation'] == 'proceed'
    assert result['source_subject_routing']['paper_replication_status'] == 'source_baseline_selected_not_yet_evaluated'


def test_source_extension_can_proceed_but_never_claims_report_replication() -> None:
    aim = _aim('source_extension', selected_id='event_u_extension')
    aim['source_baseline_reference'] = _reference('event_u_extension', 'source_extension')
    review = _review('mismatch')
    review['compared_selected_components'] = ['EVENT_U']
    review['material_deviations'] = ['EVENT_U is a different selected mathematical object.']
    aim['source_semantic_review'] = review

    result = _score(aim, factor_id='event_u_extension')

    assert result['mechanical_consistency_passed'] is True
    assert result['recommendation'] == 'proceed'
    assert result['matches_core_driver'] is False
    assert result['source_subject_routing']['paper_replication_status'] == 'not_reproduced'
    checks = VALIDATOR.source_subject_routing_checks(
        _validator_master(result['source_subject_routing'], 'event_u_extension'),
        _validator_handoff(result['source_subject_routing']),
    )
    assert all(row['ok'] for row in checks)


def test_validator_rejects_tampered_reference_not_equal_to_canonical_identity() -> None:
    aim = _aim('source_extension', selected_id='event_u_extension')
    aim['source_baseline_reference'] = _reference('event_u_extension', 'source_extension')
    result = _score(aim, factor_id='event_u_extension')
    routing = deepcopy(result['source_subject_routing'])
    routing['source_baseline_reference']['selected_construction_id'] = 'other_formula'
    checks = VALIDATOR.source_subject_routing_checks(
        _validator_master(routing, 'event_u_extension'),
        _validator_handoff(routing),
    )
    assert any(
        row['name'] == 'source_extension_reference_canonical_identity_match'
        and row['ok'] is False
        for row in checks
    )


def test_validator_rechecks_tampered_report_match_with_material_deviation() -> None:
    aim = _aim('report_replication')
    aim['source_baseline_reference'] = _reference('selected_pf_vv', 'selected_baseline')
    aim['source_semantic_review'] = _review('match')
    result = _score(aim)
    routing = deepcopy(result['source_subject_routing'])
    routing['source_semantic_review']['material_deviations'] = ['Changed the PF/VV combination.']
    checks = VALIDATOR.source_subject_routing_checks(
        _validator_master(routing, 'selected_pf_vv'),
        _validator_handoff(routing),
    )
    assert any(
        row['name'] == 'report_replication_review_declared_match'
        and row['ok'] is False
        for row in checks
    )


def test_validator_rejects_extension_with_tampered_relation() -> None:
    aim = _aim('source_extension', selected_id='event_u_extension')
    aim['source_baseline_reference'] = _reference('event_u_extension', 'source_extension')
    result = _score(aim, factor_id='event_u_extension')
    routing = deepcopy(result['source_subject_routing'])
    routing['source_baseline_reference']['relation'] = 'selected_baseline'
    checks = VALIDATOR.source_subject_routing_checks(
        _validator_master(routing, 'event_u_extension'),
        _validator_handoff(routing),
    )
    assert any(
        row['name'] == 'source_extension_reference_relation'
        and row['ok'] is False
        for row in checks
    )


def test_independent_hypothesis_needs_no_report_baseline() -> None:
    result = _score(
        _aim('independent_hypothesis', selected_id='user_signal'),
        factor_id='user_signal',
    )

    assert result['mechanical_consistency_passed'] is True
    assert result['recommendation'] == 'proceed'
    assert result['matches_core_driver'] is False
    assert result['source_subject_routing']['paper_replication_status'] == 'not_applicable'


def test_mechanical_pass_with_unassessed_report_semantics_must_revise() -> None:
    aim = _aim('report_replication')
    aim['source_baseline_reference'] = _reference('selected_pf_vv', 'selected_baseline')
    aim['source_semantic_review'] = _review('unassessed')

    result = _score(aim)

    assert result['consistency_score'] == 0.82
    assert result['mechanical_consistency_passed'] is True
    assert result['matches_core_driver'] is False
    assert result['recommendation'] == 'revise'


def test_new_scoring_without_mode_cannot_treat_default_score_as_semantic_match() -> None:
    result = _score(_aim(None))

    assert result['consistency_score'] == 0.82
    assert result['mechanical_consistency_passed'] is True
    assert result['matches_core_driver'] is False
    assert result['recommendation'] == 'revise'
    assert result['source_subject_routing']['source_semantic_status'] == 'unassessed'


def test_report_reference_must_bind_the_actual_primary_construction() -> None:
    aim = _aim('report_replication')
    aim['source_baseline_reference'] = _reference('event_u_extension', 'selected_baseline')
    aim['source_semantic_review'] = _review('match')

    result = _score(aim, factor_id='selected_pf_vv')

    assert result['matches_core_driver'] is False
    assert result['recommendation'] == 'revise'
    assert any('bind the primary canonical construction' in item for item in result['source_subject_routing']['diagnostics'])


def test_report_match_cannot_hide_a_material_deviation() -> None:
    aim = _aim('report_replication')
    aim['source_baseline_reference'] = _reference('selected_pf_vv', 'selected_baseline')
    review = _review('match')
    review['material_deviations'] = ['Changed the source combination rule.']
    aim['source_semantic_review'] = review

    result = _score(aim)

    assert result['matches_core_driver'] is False
    assert result['recommendation'] == 'revise'
    assert any('cannot retain material_deviations' in item for item in result['source_subject_routing']['diagnostics'])


def test_current_marker_blocks_missing_null_empty_or_deleted_routing() -> None:
    result = _score(_aim('independent_hypothesis', selected_id='user_signal'), factor_id='user_signal')
    valid_routing = result['source_subject_routing']
    missing_master = _validator_master(None, 'user_signal')
    null_master = _validator_master(valid_routing, 'user_signal')
    null_master['source_subject_routing'] = None
    empty_master = _validator_master({}, 'user_signal')
    for master in (missing_master, null_master, empty_master):
        checks = VALIDATOR.source_subject_routing_checks(
            master,
            _validator_handoff(valid_routing),
        )
        assert any(
            row['name'] == 'source_subject_routing_required' and row['ok'] is False
            for row in checks
        )

    deleted_master = _validator_master(valid_routing, 'user_signal')
    del deleted_master['source_subject_routing']
    checks = VALIDATOR.source_subject_routing_checks(
        deleted_master,
        _validator_handoff(valid_routing),
    )
    assert any(
        row['name'] == 'source_subject_routing_required' and row['ok'] is False
        for row in checks
    )


def test_current_marker_blocks_missing_null_empty_or_deleted_handoff_routing() -> None:
    result = _score(_aim('independent_hypothesis', selected_id='user_signal'), factor_id='user_signal')
    routing = result['source_subject_routing']
    master = _validator_master(routing, 'user_signal')
    missing_handoff = {'source_subject_routing_required': True}
    empty_handoff_object = {}
    null_handoff = _validator_handoff(routing)
    null_handoff['source_subject_routing'] = None
    empty_handoff = _validator_handoff({})
    for handoff in (missing_handoff, empty_handoff_object, null_handoff, empty_handoff):
        checks = VALIDATOR.source_subject_routing_checks(
            master,
            handoff,
        )
        assert any(
            row['name'] == 'source_subject_routing_handoff_match' and row['ok'] is False
            for row in checks
        )

    deleted_handoff = _validator_handoff(routing)
    del deleted_handoff['source_subject_routing']
    checks = VALIDATOR.source_subject_routing_checks(master, deleted_handoff)
    assert any(
        row['name'] == 'source_subject_routing_handoff_match' and row['ok'] is False
        for row in checks
    )


def test_legacy_omission_requires_explicit_validator_switch() -> None:
    legacy_master = {
        'contract_version': VALIDATOR.STEP2_SOURCE_CONTRACT_VERSION,
        'selected_construction_id': 'old_signal',
        'canonical_spec': {'construction_id': 'old_signal'},
    }
    legacy_handoff = {}

    blocked = VALIDATOR.source_subject_routing_checks(legacy_master, legacy_handoff)
    assert any(
        row['name'] == 'source_subject_routing_required' and row['ok'] is False
        for row in blocked
    )

    allowed = VALIDATOR.source_subject_routing_checks(
        legacy_master,
        legacy_handoff,
        allow_legacy_source_subject_routing_omission=True,
    )
    assert allowed == [
        {
            'name': 'source_subject_routing_legacy_omission_explicit',
            'ok': True,
            'status': 'PASS',
            'severity': 'BLOCK',
            'error': None,
        }
    ]

    marked_current = dict(legacy_master, source_subject_routing_required=False)
    checks = VALIDATOR.source_subject_routing_checks(
        marked_current,
        legacy_handoff,
        allow_legacy_source_subject_routing_omission=True,
    )
    assert any(
        row['name'] == 'source_subject_routing_required' and row['ok'] is False
        for row in checks
    )
