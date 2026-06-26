from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_profiler_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'profile_intraday_array_kernels.py'
    spec = importlib.util.spec_from_file_location('profile_intraday_array_kernels', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_intraday_array_kernel_profiler_accepts_direct_array_candidates(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'array_kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '16',
        '--rows-per-group',
        '32',
        '--window',
        '8',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['input']['direct_array_inputs'] is True
    assert payload['comparison_issues'] == []
    assert payload['performance_gate']['benchmark_scope'] == 'synthetic_bounded_direct_array'
    assert payload['performance_gate']['production_default_allowed'] is False
    operator_backends = {
        (profile['operator_id'], profile['backend'])
        for profile in payload['profiles']
    }
    for operator_id in [
        'rolling_corr_grouped_arrays',
        'terminal_corr_grouped_arrays',
        'occupation_location_grouped_arrays',
    ]:
        assert (operator_id, 'reference_loop') in operator_backends
        assert (operator_id, 'array_grouped') in operator_backends
    assert len(payload['performance_gate']['candidates']) == 3
    assert payload['safety']['starts_backfill'] is False
    assert payload['safety']['writes_datamart'] is False
    assert payload['safety']['production_loop_side_effect'] is False


def test_intraday_array_kernel_profiler_profiles_optional_numba_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'array_kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-numba-grouped',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    numba_profiles = [
        profile for profile in payload['profiles']
        if profile['backend'] == 'numba_grouped'
    ]
    assert exit_code in {0, 1}
    assert len(numba_profiles) == 3
    assert payload['safety']['writes_datamart'] is False
    if exit_code == 0:
        assert payload['verdict'] == 'ACCEPT'
        assert all(profile['verdict'] == 'ACCEPT' for profile in numba_profiles)
    else:
        assert payload['verdict'] == 'BLOCK'
        assert any(profile['verdict'] == 'BLOCK' for profile in numba_profiles)


def test_intraday_array_kernel_profiler_reads_bounded_parquet(tmp_path):
    pytest.importorskip('pyarrow')
    profiler = _load_profiler_module()
    input_path = tmp_path / 'minute_sample.parquet'
    rows = []
    for trade_date in ['20240104', '20240105']:
        for ts_code, base in [('000001.SZ', 10.0), ('000002.SZ', 20.0)]:
            for idx in range(8):
                price = base + float(idx) * 0.1
                volume = 100.0 + float(idx)
                rows.append({
                    'trade_date': trade_date,
                    'ts_code': ts_code,
                    'hhmmss': 93100 + idx * 100,
                    'price': price,
                    'volume': volume,
                    'amount': price * volume,
                })
    pd.DataFrame(rows).sample(frac=1.0, random_state=7).to_parquet(input_path, index=False)
    output_path = tmp_path / 'array_kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--input-parquet',
        str(input_path),
        '--window',
        '4',
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['performance_gate']['benchmark_scope'] == 'real_bounded_direct_array'
    assert payload['input']['synthetic'] is False
    assert payload['input']['source_path'] == str(input_path)
    assert payload['input']['row_count'] == 32
    assert payload['input']['group_count'] == 4
    assert payload['safety']['uses_real_market_data'] is True
    assert payload['safety']['writes_datamart'] is False
