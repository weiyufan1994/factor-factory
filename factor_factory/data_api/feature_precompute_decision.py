from __future__ import annotations

from typing import Any


DECISION_SCHEMA_VERSION = 'feature_precompute_decision_report_v1'


def _decision_for_family(entry: dict[str, Any]) -> tuple[str, list[str]]:
    policy = str(entry.get('precompute_policy') or '')
    reuse = str(entry.get('reuse_tier') or '')
    cost = str(entry.get('cost_tier') or '')
    domain = str(entry.get('domain') or '')
    alpha360 = entry.get('alpha360_related') is True
    stateful = entry.get('requires_state_continuity') is True
    reasons: list[str] = []

    if policy == 'precompute_now':
        reasons.append('registry_policy_precompute_now')
        if reuse == 'broad':
            reasons.append('broad_reuse')
        if cost == 'low':
            reasons.append('low_cost')
        return 'productionize_first', reasons

    if policy == 'precompute_after_source_ready':
        reasons.append('source_datamart_required')
        if domain == 'intraday':
            reasons.append('raw_minute_scan_avoidance')
        if reuse in {'broad', 'medium'}:
            reasons.append(f'{reuse}_reuse')
        if stateful:
            reasons.append('requires_state_continuity_proof')
        return 'productionize_after_source_ready', reasons

    if policy == 'model_specific_only':
        reasons.append('model_specific')
        if alpha360:
            reasons.append('alpha360_temporal_context')
        if cost in {'high', 'very_high'}:
            reasons.append('wide_or_expensive')
        return 'bounded_proof_then_model_specific', reasons

    if policy == 'on_demand_only':
        reasons.append('universe_or_research_split_dependent')
        return 'keep_on_research_side', reasons

    if policy == 'do_not_precompute':
        reasons.append('registry_policy_do_not_precompute')
        return 'do_not_precompute', reasons

    reasons.append('unknown_policy')
    return 'review_required', reasons


def build_feature_precompute_decision_report(feature_family: dict[str, Any]) -> dict[str, Any]:
    families = [entry for entry in (feature_family.get('feature_families') or []) if isinstance(entry, dict)]
    decisions: list[dict[str, Any]] = []
    by_decision: dict[str, int] = {}
    for entry in families:
        decision, reasons = _decision_for_family(entry)
        by_decision[decision] = by_decision.get(decision, 0) + 1
        decisions.append({
            'family_id': entry.get('family_id'),
            'domain': entry.get('domain'),
            'recommended_dataset': entry.get('recommended_dataset'),
            'precompute_policy': entry.get('precompute_policy'),
            'reuse_tier': entry.get('reuse_tier'),
            'cost_tier': entry.get('cost_tier'),
            'alpha360_related': entry.get('alpha360_related') is True,
            'requires_state_continuity': entry.get('requires_state_continuity') is True,
            'decision': decision,
            'reason_tags': reasons,
            'example_features': entry.get('example_features') or [],
            'information_set_legality': entry.get('information_set_legality'),
            'not_for': entry.get('not_for') or [],
        })
    return {
        'schema_version': DECISION_SCHEMA_VERSION,
        'family_count': len(decisions),
        'by_decision': by_decision,
        'decisions': sorted(decisions, key=lambda item: (str(item['decision']), str(item['family_id']))),
        'interpretation': {
            'productionize_first': 'low-cost, broad-reuse feature states should be made production datamarts first',
            'productionize_after_source_ready': 'high-reuse intraday/stateful families should wait for source datamart and legality proof',
            'bounded_proof_then_model_specific': 'wide or model-specific tensors such as Alpha360 should be projected and adopted only when the model pipeline needs them',
            'keep_on_research_side': 'universe-dependent transforms should be computed after research-side universe and tradability filters',
        },
    }


def recommended_precompute_sequence(report: dict[str, Any]) -> list[dict[str, Any]]:
    order = {
        'productionize_first': 0,
        'productionize_after_source_ready': 1,
        'bounded_proof_then_model_specific': 2,
        'keep_on_research_side': 3,
        'do_not_precompute': 4,
        'review_required': 5,
    }
    decisions = [entry for entry in report.get('decisions') or [] if isinstance(entry, dict)]
    return sorted(
        decisions,
        key=lambda item: (
            order.get(str(item.get('decision')), 99),
            str(item.get('domain')),
            str(item.get('family_id')),
        ),
    )
