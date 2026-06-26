from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_intraday_operator_kernel_profile.py'
    spec = importlib.util.spec_from_file_location('validate_intraday_operator_kernel_profile', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proof(*, scope: str = 'real_bounded_read_only', production_default_allowed: bool = False) -> dict:
    return {
        'verdict': 'ACCEPT',
        'profile_count': 4,
        'input': {
            'synthetic': scope == 'synthetic_bounded',
            'row_count': 100,
        },
        'profiles': [
            {
                'operator_id': 'rolling_corr_by_group',
                'backend': 'numpy',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 1.0,
                'row_count': 100,
                'result_hash': 'a' * 64,
                'issues': [],
            },
            {
                'operator_id': 'rolling_corr_by_group',
                'backend': 'threaded_grouped',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 0.5,
                'row_count': 100,
                'result_hash': 'a' * 64,
                'issues': [],
            },
        ],
        'comparison_issues': [],
        'performance_gate': {
            'benchmark_scope': scope,
            'production_default_allowed': production_default_allowed,
            'min_speedup_for_default': 1.2,
            'default_replacement_verdict': 'PROMOTE',
            'candidates': [
                {
                    'operator_id': 'rolling_corr_by_group',
                    'baseline_backend': 'numpy',
                    'candidate_backend': 'threaded_grouped',
                    'baseline_seconds': 1.0,
                    'candidate_seconds': 0.5,
                    'speedup': 2.0,
                    'performance_verdict': 'PROMOTE',
                    'reason': 'speedup_gate_met',
                },
            ],
        },
        'safety': {
            'uses_real_market_data': scope == 'real_bounded_read_only',
            'starts_backfill': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def test_operator_kernel_profile_validator_accepts_safe_real_bounded_proof(tmp_path):
    validator = _load_validator_module()
    proof_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    proof_path.write_text(json.dumps(_proof()))

    exit_code = validator.main([
        '--profile-path',
        str(proof_path),
        '--output-path',
        str(output_path),
        '--require-real-bounded',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issue_count'] == 0
    assert payload['promotion_candidate_count'] == 1
    assert payload['production_default_allowed'] is False


def test_operator_kernel_profile_validator_blocks_synthetic_when_real_bounded_required(tmp_path):
    validator = _load_validator_module()
    proof_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    proof_path.write_text(json.dumps(_proof(scope='synthetic_bounded')))

    exit_code = validator.main([
        '--profile-path',
        str(proof_path),
        '--output-path',
        str(output_path),
        '--require-real-bounded',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'benchmark_scope_not_real_bounded' in payload['issues']


def test_operator_kernel_profile_validator_blocks_insufficient_rows_when_minimum_required(tmp_path):
    validator = _load_validator_module()
    proof_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    proof_path.write_text(json.dumps(_proof(scope='real_bounded_read_only')))

    exit_code = validator.main([
        '--profile-path',
        str(proof_path),
        '--output-path',
        str(output_path),
        '--require-real-bounded',
        '--min-row-count',
        '1000',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'input_row_count_below_minimum' in payload['issues']
    assert payload['min_row_count'] == 1000
    assert payload['input_row_count'] == 100


def test_operator_kernel_profile_validator_blocks_production_default_permission(tmp_path):
    validator = _load_validator_module()
    proof_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    proof_path.write_text(json.dumps(_proof(production_default_allowed=True)))

    exit_code = validator.main([
        '--profile-path',
        str(proof_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'production_default_allowed_must_be_false_for_pre_wiring_profiles' in payload['issues']
