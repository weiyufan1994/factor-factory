from __future__ import annotations

from pathlib import Path

from factor_factory.data_api.feature_family_registry import (
    feature_family_summary,
    read_feature_family_registry,
    validate_feature_family_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json'


def test_default_feature_family_registry_is_valid():
    payload = read_feature_family_registry(REGISTRY_PATH)

    issues = validate_feature_family_registry(payload)

    assert issues == []
    summary = feature_family_summary(payload)
    assert summary['family_count'] >= 8
    assert 'daily_technical_state' in summary['precompute_now']
    assert 'daily_alpha360_lag_tensor' in summary['alpha360_related']


def test_feature_family_registry_rejects_duplicate_family_ids():
    payload = read_feature_family_registry(REGISTRY_PATH)
    payload['feature_families'] = [payload['feature_families'][0], dict(payload['feature_families'][0])]

    fields = {issue.field for issue in validate_feature_family_registry(payload)}

    assert 'feature_families[1].family_id' in fields


def test_feature_family_registry_rejects_precompute_now_for_very_high_cost():
    payload = read_feature_family_registry(REGISTRY_PATH)
    entry = dict(payload['feature_families'][0])
    entry['cost_tier'] = 'very_high'
    entry['precompute_policy'] = 'precompute_now'
    payload['feature_families'] = [entry]

    fields = {issue.field for issue in validate_feature_family_registry(payload)}

    assert 'feature_families[0].precompute_policy' in fields


def test_feature_family_registry_requires_state_legality_for_stateful_features():
    payload = read_feature_family_registry(REGISTRY_PATH)
    entry = dict(payload['feature_families'][0])
    entry['requires_state_continuity'] = True
    entry['information_set_legality'] = 'Uses prior rows.'
    payload['feature_families'] = [entry]

    fields = {issue.field for issue in validate_feature_family_registry(payload)}

    assert 'feature_families[0].information_set_legality' in fields
