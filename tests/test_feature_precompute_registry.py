from __future__ import annotations

from pathlib import Path

from factor_factory.data_api.feature_precompute_registry import (
    read_feature_registry,
    registry_summary,
    validate_feature_precompute_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / 'docs' / 'operations' / 'feature-precompute-registry.v1.json'


def test_default_feature_precompute_registry_is_valid():
    payload = read_feature_registry(REGISTRY_PATH)

    issues = validate_feature_precompute_registry(payload, repo_root=REPO_ROOT)

    assert issues == []
    summary = registry_summary(payload)
    assert summary['dataset_count'] >= 6
    assert summary['recommended_first_production'] == ['daily_technical_state_v1']


def test_registry_rejects_duplicate_dataset_ids():
    payload = read_feature_registry(REGISTRY_PATH)
    payload['datasets'] = [payload['datasets'][0], dict(payload['datasets'][0])]

    fields = {issue.field for issue in validate_feature_precompute_registry(payload, repo_root=REPO_ROOT)}

    assert 'datasets[1].dataset_id' in fields


def test_registry_rejects_production_ready_without_worker_full_window_proof():
    payload = read_feature_registry(REGISTRY_PATH)
    entry = dict(payload['datasets'][0])
    entry['status'] = 'production_ready'
    entry['production_readiness'] = 'production_ready'
    entry['registration_blockers'] = []
    entry['proof_paths'] = {
        'qa': '/tmp/qa.json',
        'catalog': '/tmp/catalog.json',
        'worker_read_smoke': '/tmp/smoke.json',
    }
    payload['datasets'] = [entry]

    fields = {issue.field for issue in validate_feature_precompute_registry(payload, repo_root=REPO_ROOT)}

    assert 'datasets[0].proof_paths.worker_full_window' in fields


def test_registry_requires_existing_scripts_for_builder_backed_status():
    payload = read_feature_registry(REGISTRY_PATH)
    entry = dict(payload['datasets'][0])
    entry['builder_script'] = 'scripts/does_not_exist.py'
    payload['datasets'] = [entry]

    fields = {issue.field for issue in validate_feature_precompute_registry(payload, repo_root=REPO_ROOT)}

    assert 'datasets[0].builder_script' in fields
