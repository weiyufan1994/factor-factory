from __future__ import annotations

from factor_factory.data_api.operator_backend_registry import resolve_operator_backend


def _approval_validation(*, verdict: str = 'ACCEPT', operator_id: str = 'cpv_price_volume_corr_state') -> dict:
    return {
        'verdict': verdict,
        'operator_id': operator_id,
        'approval_evidence_scope': 'production_scale',
        'safe_worker_validation_evidence_scope': 'production_scale',
        'decision': {
            'operator_id': operator_id,
            'default_backend': 'array_grouped',
            'selected_backend': 'process_sharded_array_grouped',
            'candidate_backend': 'process_sharded_array_grouped',
            'replacement_allowed': verdict == 'ACCEPT',
            'reason': 'approved_candidate_promoted_by_production_approval' if verdict == 'ACCEPT' else 'blocked_for_test',
        },
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def test_backend_registry_keeps_default_without_approval_validation():
    decision = resolve_operator_backend(
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        configured_backend='process_sharded_array_grouped',
        approval_validation=None,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['configured_backend'] == 'process_sharded_array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'approval_validation_required'


def test_backend_registry_keeps_default_when_approval_validation_blocks():
    decision = resolve_operator_backend(
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        configured_backend='process_sharded_array_grouped',
        approval_validation=_approval_validation(verdict='BLOCK'),
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'approval_validation_not_accept'


def test_backend_registry_keeps_default_when_operator_mismatches():
    decision = resolve_operator_backend(
        operator_id='rolling_corr_by_group',
        default_backend='numpy',
        configured_backend='process_sharded_array_grouped',
        approval_validation=_approval_validation(operator_id='cpv_price_volume_corr_state'),
    )

    assert decision['selected_backend'] == 'numpy'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'approval_validation_operator_mismatch'


def test_backend_registry_keeps_default_when_approval_validation_lacks_evidence_scope():
    approval_validation = _approval_validation()
    approval_validation.pop('approval_evidence_scope')
    approval_validation.pop('safe_worker_validation_evidence_scope')

    decision = resolve_operator_backend(
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        configured_backend='process_sharded_array_grouped',
        approval_validation=approval_validation,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'approval_validation_evidence_scope_invalid'


def test_backend_registry_keeps_default_when_approval_validation_scope_is_bounded():
    approval_validation = _approval_validation()
    approval_validation['approval_evidence_scope'] = 'bounded_worker'
    approval_validation['safe_worker_validation_evidence_scope'] = 'bounded_worker'

    decision = resolve_operator_backend(
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        configured_backend='process_sharded_array_grouped',
        approval_validation=approval_validation,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'approval_validation_evidence_scope_invalid'


def test_backend_registry_keeps_default_when_approval_validation_scope_mismatches():
    approval_validation = _approval_validation()
    approval_validation['approval_evidence_scope'] = 'production_scale'
    approval_validation['safe_worker_validation_evidence_scope'] = 'full_is'

    decision = resolve_operator_backend(
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        configured_backend='process_sharded_array_grouped',
        approval_validation=approval_validation,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'approval_validation_evidence_scope_invalid'


def test_backend_registry_allows_exact_approved_configured_backend():
    decision = resolve_operator_backend(
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        configured_backend='process_sharded_array_grouped',
        approval_validation=_approval_validation(),
    )

    assert decision['selected_backend'] == 'process_sharded_array_grouped'
    assert decision['replacement_allowed'] is True
    assert decision['reason'] == 'approval_validation_accept'
    assert decision['safety']['writes_backend_config'] is False


def test_backend_registry_keeps_moneyflow_reference_default_without_approval():
    decision = resolve_operator_backend(
        operator_id='moneyflow_slow_state_v1',
        default_backend='reference',
        configured_backend='array_grouped',
        approval_validation=None,
    )

    assert decision['selected_backend'] == 'reference'
    assert decision['configured_backend'] == 'array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'approval_validation_required'


def test_backend_registry_allows_moneyflow_array_backend_after_exact_approval_validation():
    approval_validation = {
        'verdict': 'ACCEPT',
        'operator_id': 'moneyflow_slow_state_v1',
        'approval_evidence_scope': 'full_is',
        'safe_worker_validation_evidence_scope': 'full_is',
        'decision': {
            'operator_id': 'moneyflow_slow_state_v1',
            'default_backend': 'reference',
            'selected_backend': 'array_grouped',
            'candidate_backend': 'array_grouped',
            'replacement_allowed': True,
            'reason': 'approved_candidate_promoted_by_production_approval',
        },
    }

    decision = resolve_operator_backend(
        operator_id='moneyflow_slow_state_v1',
        default_backend='reference',
        configured_backend='array_grouped',
        approval_validation=approval_validation,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['replacement_allowed'] is True
    assert decision['reason'] == 'approval_validation_accept'
