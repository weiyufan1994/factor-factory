from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_intraday_array_kernel_profile.py'
    spec = importlib.util.spec_from_file_location('validate_intraday_array_kernel_profile', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(*, mutate: str | None = None, scope: str = 'synthetic_bounded_direct_array') -> dict:
    profiles = []
    candidates = []
    for operator_id in [
        'rolling_corr_grouped_arrays',
        'terminal_corr_grouped_arrays',
        'occupation_location_grouped_arrays',
    ]:
        profiles.append({
            'operator_id': operator_id,
            'backend': 'reference_loop',
            'verdict': 'ACCEPT',
            'elapsed_seconds': 1.0,
            'row_count': 100,
            'result_hash': 'a' * 64,
            'issues': [],
        })
        profiles.append({
            'operator_id': operator_id,
            'backend': 'array_grouped',
            'verdict': 'ACCEPT',
            'elapsed_seconds': 0.5,
            'row_count': 100,
            'result_hash': 'b' * 64,
            'issues': [],
        })
        candidates.append({
            'operator_id': operator_id,
            'baseline_backend': 'reference_loop',
            'candidate_backend': 'array_grouped',
            'baseline_seconds': 1.0,
            'candidate_seconds': 0.5,
            'speedup': 2.0,
            'performance_verdict': 'PROMOTE',
            'reason': 'speedup_gate_met',
        })
    payload = {
        'verdict': 'ACCEPT',
        'profile_count': len(profiles),
        'input': {
            'synthetic': scope != 'real_bounded_direct_array',
            'groups': 10,
            'rows_per_group': 10,
            'row_count': 100,
            'window': 4,
            'direct_array_inputs': True,
        },
        'profiles': profiles,
        'comparison_issues': [],
        'performance_gate': {
            'benchmark_scope': scope,
            'production_default_allowed': False,
            'min_speedup_for_default': 1.2,
            'candidates': candidates,
        },
        'safety': {
            'uses_real_market_data': scope == 'real_bounded_direct_array',
            'starts_backfill': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }
    if mutate == 'scope':
        payload['performance_gate']['benchmark_scope'] = 'synthetic_bounded'
    elif mutate == 'unsafe':
        payload['safety']['writes_datamart'] = True
    elif mutate == 'not_direct':
        payload['input']['direct_array_inputs'] = False
    elif mutate == 'missing_reference':
        payload['profiles'] = [item for item in profiles if not (
            item['operator_id'] == 'terminal_corr_grouped_arrays'
            and item['backend'] == 'reference_loop'
        )]
    return payload


def test_array_kernel_profile_validator_accepts_complete_profile(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    profile_path.write_text(json.dumps(_profile()), encoding='utf-8')

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--output-path',
        str(output_path),
        '--min-row-count',
        '100',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['benchmark_scope'] == 'synthetic_bounded_direct_array'
    assert payload['direct_array_inputs'] is True
    assert payload['promotion_candidate_count'] == 3


def test_array_kernel_profile_validator_accepts_real_bounded_profile(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    profile_path.write_text(json.dumps(_profile(scope='real_bounded_direct_array')), encoding='utf-8')

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--output-path',
        str(output_path),
        '--require-real-bounded',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['benchmark_scope'] == 'real_bounded_direct_array'
    assert payload['safety']['uses_real_market_data'] is True


def test_array_kernel_profile_validator_blocks_synthetic_when_real_required(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    output_path = tmp_path / 'validation.json'
    profile_path.write_text(json.dumps(_profile()), encoding='utf-8')

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--output-path',
        str(output_path),
        '--require-real-bounded',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'benchmark_scope_not_real_bounded_direct_array' in payload['issues']


def test_array_kernel_profile_validator_blocks_wrong_scope_or_safety(tmp_path):
    validator = _load_validator_module()
    for mutate, issue in [
        ('scope', 'benchmark_scope_not_supported_direct_array_scope'),
        ('unsafe', 'safety_writes_datamart_must_be_false'),
        ('not_direct', 'direct_array_inputs_must_be_true'),
        ('missing_reference', 'reference_loop_profiles_missing:terminal_corr_grouped_arrays'),
    ]:
        profile_path = tmp_path / f'{mutate}.profile.json'
        output_path = tmp_path / f'{mutate}.validation.json'
        profile_path.write_text(json.dumps(_profile(mutate=mutate)), encoding='utf-8')

        exit_code = validator.main([
            '--profile-path',
            str(profile_path),
            '--output-path',
            str(output_path),
        ])

        payload = json.loads(output_path.read_text(encoding='utf-8'))
        assert exit_code == 1
        assert payload['verdict'] == 'BLOCK'
        assert issue in payload['issues']
