from __future__ import annotations

from factor_factory.data_api.operator_backend_policy import decide_operator_backend


def _profile(*, production_default_allowed: bool = False, candidate_verdict: str = 'PROMOTE') -> dict:
    return {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': production_default_allowed,
            'default_replacement_verdict': candidate_verdict,
            'candidates': [
                {
                    'operator_id': 'rolling_corr_by_group',
                    'candidate_backend': 'threaded_grouped',
                    'performance_verdict': candidate_verdict,
                    'speedup': 2.0,
                },
            ],
        },
    }


def _validation(*, verdict: str = 'ACCEPT') -> dict:
    return {
        'verdict': verdict,
        'issue_count': 0 if verdict == 'ACCEPT' else 1,
        'issues': [] if verdict == 'ACCEPT' else ['blocked_for_test'],
    }


def test_backend_policy_keeps_default_when_production_permission_is_false():
    decision = decide_operator_backend(
        profile=_profile(production_default_allowed=False),
        validation=_validation(),
        operator_id='rolling_corr_by_group',
        default_backend='numpy',
    )

    assert decision['selected_backend'] == 'numpy'
    assert decision['candidate_backend'] == 'threaded_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'production_approval_required'


def test_backend_policy_keeps_default_when_validation_blocks():
    decision = decide_operator_backend(
        profile=_profile(production_default_allowed=True),
        validation=_validation(verdict='BLOCK'),
        operator_id='rolling_corr_by_group',
        default_backend='numpy',
    )

    assert decision['selected_backend'] == 'numpy'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'validation_not_accept'


def test_backend_policy_requires_separate_production_approval_even_when_profile_gate_allows():
    decision = decide_operator_backend(
        profile=_profile(production_default_allowed=True),
        validation=_validation(),
        operator_id='rolling_corr_by_group',
        default_backend='numpy',
    )

    assert decision['selected_backend'] == 'numpy'
    assert decision['candidate_backend'] == 'threaded_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'production_approval_required'


def test_backend_policy_keeps_default_when_no_promoted_candidate_matches_operator():
    decision = decide_operator_backend(
        profile=_profile(production_default_allowed=True, candidate_verdict='HOLD'),
        validation=_validation(),
        operator_id='rolling_corr_by_group',
        default_backend='numpy',
    )

    assert decision['selected_backend'] == 'numpy'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'no_promoted_candidate_for_operator'


def test_backend_policy_identifies_promoted_candidate_but_requires_approval_when_first_candidate_holds():
    profile = {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': True,
            'default_replacement_verdict': 'HOLD',
            'candidates': [
                {
                    'operator_id': 'cpv_price_volume_corr_state',
                    'candidate_backend': 'array_grouped',
                    'performance_verdict': 'HOLD',
                    'speedup': 1.05,
                },
                {
                    'operator_id': 'cpv_price_volume_corr_state',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 2.5,
                },
            ],
        },
    }

    decision = decide_operator_backend(
        profile=profile,
        validation=_validation(),
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['candidate_backend'] == 'process_sharded_array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'production_approval_required'


def test_backend_policy_allows_candidate_with_matching_production_approval_artifact():
    profile = {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': False,
            'default_replacement_verdict': 'HOLD',
            'candidates': [
                {
                    'operator_id': 'cpv_price_volume_corr_state',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 2.5,
                },
            ],
        },
    }
    approval = {
        'verdict': 'ACCEPT',
        'operator_id': 'cpv_price_volume_corr_state',
        'approved_backend': 'process_sharded_array_grouped',
        'production_default_allowed': True,
        'approval_scope': 'production_default_backend',
        'evidence_scope': 'production_scale',
    }

    decision = decide_operator_backend(
        profile=profile,
        validation=_validation(),
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        production_approval=approval,
    )

    assert decision['selected_backend'] == 'process_sharded_array_grouped'
    assert decision['candidate_backend'] == 'process_sharded_array_grouped'
    assert decision['replacement_allowed'] is True
    assert decision['reason'] == 'approved_candidate_promoted_by_production_approval'


def test_backend_policy_rejects_production_approval_for_different_backend():
    profile = {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': False,
            'default_replacement_verdict': 'HOLD',
            'candidates': [
                {
                    'operator_id': 'cpv_price_volume_corr_state',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 2.5,
                },
            ],
        },
    }
    approval = {
        'verdict': 'ACCEPT',
        'operator_id': 'cpv_price_volume_corr_state',
        'approved_backend': 'array_grouped',
        'production_default_allowed': True,
        'approval_scope': 'production_default_backend',
        'evidence_scope': 'production_scale',
    }

    decision = decide_operator_backend(
        profile=profile,
        validation=_validation(),
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        production_approval=approval,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['candidate_backend'] == 'process_sharded_array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'production_approval_not_valid_for_candidate'


def test_backend_policy_rejects_production_approval_without_production_evidence_scope():
    profile = {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': False,
            'default_replacement_verdict': 'HOLD',
            'candidates': [
                {
                    'operator_id': 'cpv_price_volume_corr_state',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 2.5,
                },
            ],
        },
    }
    approval = {
        'verdict': 'ACCEPT',
        'operator_id': 'cpv_price_volume_corr_state',
        'approved_backend': 'process_sharded_array_grouped',
        'production_default_allowed': True,
        'approval_scope': 'production_default_backend',
        'evidence_scope': 'bounded_worker',
    }

    decision = decide_operator_backend(
        profile=profile,
        validation=_validation(),
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        production_approval=approval,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['candidate_backend'] == 'process_sharded_array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'production_approval_not_valid_for_candidate'


def test_backend_policy_rejects_legacy_production_approval_without_evidence_scope_field():
    profile = {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': False,
            'default_replacement_verdict': 'HOLD',
            'candidates': [
                {
                    'operator_id': 'cpv_price_volume_corr_state',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 2.5,
                },
            ],
        },
    }
    approval = {
        'verdict': 'ACCEPT',
        'operator_id': 'cpv_price_volume_corr_state',
        'approved_backend': 'process_sharded_array_grouped',
        'production_default_allowed': True,
        'approval_scope': 'production_default_backend',
    }

    decision = decide_operator_backend(
        profile=profile,
        validation=_validation(),
        operator_id='cpv_price_volume_corr_state',
        default_backend='array_grouped',
        production_approval=approval,
    )

    assert decision['selected_backend'] == 'array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'production_approval_not_valid_for_candidate'


def test_backend_policy_understands_moneyflow_slow_state_performance_gate():
    profile = {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': False,
            'default_replacement_verdict': 'PROMOTE',
            'candidates': [
                {
                    'operator_id': 'moneyflow_slow_state_v1',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 1.4,
                },
            ],
        },
    }

    decision = decide_operator_backend(
        profile=profile,
        validation=_validation(),
        operator_id='moneyflow_slow_state_v1',
        default_backend='reference',
    )

    assert decision['selected_backend'] == 'reference'
    assert decision['candidate_backend'] == 'process_sharded_array_grouped'
    assert decision['replacement_allowed'] is False
    assert decision['reason'] == 'production_approval_required'
