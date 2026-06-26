from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_profiler_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'profile_moneyflow_slow_state_operator.py'
    spec = importlib.util.spec_from_file_location('profile_moneyflow_slow_state_operator', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_moneyflow_slow_state_profiler_compares_reference_and_optimized_backends(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'slow_state_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--tickers',
        '4',
        '--dates',
        '6',
        '--lambdas',
        '0.5,0.8',
        '--operator-backends',
        'reference,array_grouped,process_sharded_array_grouped',
        '--max-workers',
        '1',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['profile_count'] == 3
    assert payload['baseline_profile_id'] == 'reference'
    assert payload['operator_replacement_verdict'] in {'PROMOTE', 'ACCEPT', 'HOLD'}
    assert payload['performance_gate']['operator_id'] == 'moneyflow_slow_state_v1'
    assert payload['performance_gate']['production_default_allowed'] is False
    assert payload['performance_gate']['default_replacement_verdict'] in {'PROMOTE', 'HOLD'}
    assert [item['operator_id'] for item in payload['performance_gate']['candidates']] == [
        'moneyflow_slow_state_v1',
        'moneyflow_slow_state_v1',
    ]
    assert {item['candidate_backend'] for item in payload['performance_gate']['candidates']} == {
        'array_grouped',
        'process_sharded_array_grouped',
    }
    assert payload['accepted_profile_row_count_equal'] is True
    assert payload['accepted_profile_duplicate_key_count_zero'] is True
    assert payload['accepted_profile_key_hash_equal'] is True
    assert {item['operator_backend'] for item in payload['profiles']} == {
        'reference',
        'array_grouped_ema_state',
        'process_sharded_array_grouped_ema_state',
    }
