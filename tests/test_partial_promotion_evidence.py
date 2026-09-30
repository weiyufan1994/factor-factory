"""Complete diagnostic metrics must not imply promotion evidence."""
import pytest

from factor_factory.provenance import (
    LONG_SIDE_REQUIRED_METRICS,
    build_evidence_quality,
    classify_long_side_evidence,
)


@pytest.mark.parametrize('claim', [None, False, 'true', 1])
def test_complete_metrics_without_explicit_tradability_remain_diagnostic(claim):
    metrics = dict.fromkeys(LONG_SIDE_REQUIRED_METRICS, 0.1)
    metrics['tradable_net_alpha_evidence'] = claim
    result = classify_long_side_evidence(metrics)
    assert result['complete'] is True
    assert result['promotion_eligible'] is False


@pytest.mark.parametrize('status,identity,mode,backend,expected', [
    ('partial', True, True, True, False),
    ('failed', True, True, True, False),
    ('validated', False, True, True, False),
    ('validated', True, False, True, False),
    ('validated', True, True, False, False),
    ('validated', True, True, True, True),
])
def test_evidence_gate_requires_more_than_populated_metrics(status, identity, mode, backend, expected):
    metrics = dict.fromkeys(LONG_SIDE_REQUIRED_METRICS, 0.1)
    metrics['tradable_net_alpha_evidence'] = True
    result = build_evidence_quality(
        factor_run_master={},
        factor_evaluation={
            'evaluation_status': status,
            'backend_summary': [{
                'backend': 'self_quant_analyzer' if backend else 'unrelated',
                'status': 'success',
                'key_metrics': metrics,
            }],
        },
        evidence_identity={'implementation_mode_decision': {'implementation_mode': 'direct_code'} if mode else {}},
        identity_chain_verified=identity,
    )
    assert result['long_side_metrics_present'] is True
    assert result['promotion_eligible'] is expected
