from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_moneyflow_slow_state_operator_profile.py'
    spec = importlib.util.spec_from_file_location('validate_moneyflow_slow_state_operator_profile', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proof(*, synthetic: bool = False, row_count: int = 1000, production_default_allowed: bool = False) -> dict:
    scope = 'synthetic_bounded' if synthetic else 'real_bounded_read_only'
    return {
        'verdict': 'ACCEPT',
        'dataset_id': 'moneyflow_slow_state_v1',
        'source_dataset': 'intraday_flow_distribution_moments_v1',
        'benchmark_scope': scope,
        'production_default_allowed': production_default_allowed,
        'input': {
            'synthetic': synthetic,
            'row_count': row_count,
            'cutoff_times': ['14:50:00'],
            'lambdas': [0.7, 0.85, 0.93],
        },
        'profile_count': 2,
        'profiles': [
            {
                'profile_id': 'reference',
                'operator_backend': 'reference',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 1.0,
                'row_count': row_count * 3,
                'duplicate_key_count': 0,
                'result_hash': 'a' * 64,
                'issues': [],
            },
            {
                'profile_id': 'array_grouped',
                'operator_backend': 'array_grouped_ema_state',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 0.5,
                'row_count': row_count * 3,
                'duplicate_key_count': 0,
                'result_hash': 'a' * 64,
                'issues': [],
            },
        ],
        'baseline_profile_id': 'reference',
        'baseline_profile_accept': True,
        'accepted_profile_row_count_equal': True,
        'accepted_profile_duplicate_key_count_zero': True,
        'accepted_profile_key_hash_equal': True,
        'operator_replacement_verdict': 'ACCEPT',
        'operator_replacement_issues': [],
        'safety': {
            'uses_real_market_data': not synthetic,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def test_moneyflow_slow_state_profile_validator_accepts_safe_real_bounded_proof(tmp_path):
    validator = _load_validator_module()
    proof_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    proof_path.write_text(json.dumps(_proof()), encoding='utf-8')

    exit_code = validator.main([
        '--profile-path',
        str(proof_path),
        '--output-path',
        str(output_path),
        '--require-real-bounded',
        '--min-row-count',
        '1000',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issue_count'] == 0
    assert payload['benchmark_scope'] == 'real_bounded_read_only'
    assert payload['production_default_allowed'] is False


def test_moneyflow_slow_state_profile_validator_blocks_synthetic_when_real_required(tmp_path):
    validator = _load_validator_module()
    proof_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    proof_path.write_text(json.dumps(_proof(synthetic=True)), encoding='utf-8')

    exit_code = validator.main([
        '--profile-path',
        str(proof_path),
        '--output-path',
        str(output_path),
        '--require-real-bounded',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'benchmark_scope_not_real_bounded' in payload['issues']


def test_moneyflow_slow_state_profile_validator_blocks_production_default_permission(tmp_path):
    validator = _load_validator_module()
    proof_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    proof_path.write_text(json.dumps(_proof(production_default_allowed=True)), encoding='utf-8')

    exit_code = validator.main([
        '--profile-path',
        str(proof_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'production_default_allowed_must_be_false_for_pre_wiring_profiles' in payload['issues']
