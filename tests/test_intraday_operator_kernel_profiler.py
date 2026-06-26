from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_profiler_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'profile_intraday_operator_kernels.py'
    spec = importlib.util.spec_from_file_location('profile_intraday_operator_kernels', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_intraday_operator_kernel_profiler_writes_baseline_proof(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
    ])

    proof = json.loads(output_path.read_text())
    assert exit_code == 0
    assert proof['verdict'] == 'ACCEPT'
    assert proof['profile_count'] == 2
    assert proof['performance_gate']['benchmark_scope'] == 'synthetic_bounded'
    assert proof['performance_gate']['production_default_allowed'] is False
    assert proof['performance_gate']['default_replacement_verdict'] == 'NO_CANDIDATE'
    assert proof['performance_gate']['candidates'] == []
    assert [profile['operator_id'] for profile in proof['profiles']] == ['rolling_corr_by_group', 'intraday_occupation_location_state']
    assert [profile['backend'] for profile in proof['profiles']] == ['numpy', 'pandas']
    assert proof['comparison_issues'] == []
    for profile in proof['profiles']:
        assert profile['verdict'] == 'ACCEPT'
        assert profile['row_count'] > 0
        assert profile['elapsed_seconds'] >= 0.0
        assert len(profile['result_hash']) == 64


def test_intraday_operator_kernel_profiler_blocks_unavailable_numba_grouped(tmp_path, monkeypatch):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    original_corr = profiler.rolling_corr_by_group
    original_occupation = profiler.intraday_occupation_location_state

    def fake_corr(*args, **kwargs):
        if kwargs.get('backend') == 'numba_grouped':
            raise ImportError('numba unavailable in test')
        return original_corr(*args, **kwargs)

    def fake_occupation(*args, **kwargs):
        if kwargs.get('backend') == 'numba_grouped':
            raise ImportError('numba unavailable in test')
        return original_occupation(*args, **kwargs)

    monkeypatch.setattr(profiler, 'rolling_corr_by_group', fake_corr)
    monkeypatch.setattr(profiler, 'intraday_occupation_location_state', fake_occupation)

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

    proof = json.loads(output_path.read_text())
    assert exit_code == 1
    assert proof['verdict'] == 'BLOCK'
    blocked_profiles = [
        profile for profile in proof['profiles']
        if profile['backend'] == 'numba_grouped'
    ]
    assert len(blocked_profiles) == 2
    for profile in blocked_profiles:
        assert profile['verdict'] == 'BLOCK'
        assert profile['result_hash'] is None
        assert profile['issues'][0]['code'] == 'operator_backend_unavailable'


def test_intraday_operator_kernel_profiler_accepts_threaded_grouped_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-threaded-grouped',
        '--max-workers',
        '2',
    ])

    proof = json.loads(output_path.read_text())
    assert exit_code == 0
    assert proof['verdict'] == 'ACCEPT'
    assert proof['profile_count'] == 4
    assert proof['comparison_issues'] == []
    assert proof['performance_gate']['min_speedup_for_default'] == 1.2
    assert proof['performance_gate']['benchmark_scope'] == 'synthetic_bounded'
    assert proof['performance_gate']['production_default_allowed'] is False
    assert proof['performance_gate']['default_replacement_verdict'] in {'PROMOTE', 'HOLD'}
    assert len(proof['performance_gate']['candidates']) == 2
    threaded_profiles = [
        profile for profile in proof['profiles']
        if profile['backend'] == 'threaded_grouped'
    ]
    assert len(threaded_profiles) == 2
    baseline_hash_by_operator = {
        profile['operator_id']: profile['result_hash']
        for profile in proof['profiles']
        if profile['backend'] in {'numpy', 'pandas'}
    }
    for profile in threaded_profiles:
        assert profile['verdict'] == 'ACCEPT'
        assert len(profile['result_hash']) == 64
        assert profile['result_hash'] == baseline_hash_by_operator[profile['operator_id']]


def test_intraday_operator_kernel_profiler_accepts_array_grouped_rolling_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-array-grouped',
    ])

    proof = json.loads(output_path.read_text())
    assert exit_code == 0
    assert proof['verdict'] == 'ACCEPT'
    assert proof['profile_count'] == 4
    assert proof['comparison_issues'] == []
    rolling_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'rolling_corr_by_group'
    ]
    occupation_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'intraday_occupation_location_state'
    ]
    assert {profile['backend'] for profile in rolling_profiles} == {'numpy', 'array_grouped'}
    baseline_hash = next(profile['result_hash'] for profile in rolling_profiles if profile['backend'] == 'numpy')
    candidate = next(profile for profile in rolling_profiles if profile['backend'] == 'array_grouped')
    assert candidate['verdict'] == 'ACCEPT'
    assert candidate['result_hash'] == baseline_hash
    assert {profile['backend'] for profile in occupation_profiles} == {'pandas', 'array_grouped_occupation'}
    occupation_hash = next(profile['result_hash'] for profile in occupation_profiles if profile['backend'] == 'pandas')
    occupation_candidate = next(profile for profile in occupation_profiles if profile['backend'] == 'array_grouped_occupation')
    assert occupation_candidate['verdict'] == 'ACCEPT'
    assert occupation_candidate['result_hash'] == occupation_hash
    candidate_backends = {candidate['candidate_backend'] for candidate in proof['performance_gate']['candidates']}
    assert {'array_grouped', 'array_grouped_occupation'}.issubset(candidate_backends)


def test_intraday_operator_kernel_profiler_profiles_ema_state_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-ema-state',
    ])

    proof = json.loads(output_path.read_text())
    ema_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'grouped_ema_state_by_group'
    ]
    assert exit_code == 0
    assert {profile['backend'] for profile in ema_profiles} == {'array_grouped_ema_state'}
    assert all(profile['verdict'] == 'ACCEPT' for profile in ema_profiles)
    assert proof['comparison_issues'] == []


def test_intraday_operator_kernel_profiler_profiles_process_sharded_ema_state_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-ema-state',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
    ])

    proof = json.loads(output_path.read_text())
    ema_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'grouped_ema_state_by_group'
    ]
    ema_candidates = [
        candidate for candidate in proof['performance_gate']['candidates']
        if candidate['operator_id'] == 'grouped_ema_state_by_group'
    ]
    assert exit_code == 0
    assert {profile['backend'] for profile in ema_profiles} == {'array_grouped_ema_state', 'process_sharded_array_grouped_ema_state'}
    assert len({profile['result_hash'] for profile in ema_profiles}) == 1
    assert len(ema_candidates) == 1
    assert ema_candidates[0]['baseline_backend'] == 'array_grouped_ema_state'
    assert ema_candidates[0]['candidate_backend'] == 'process_sharded_array_grouped_ema_state'
    assert proof['comparison_issues'] == []


def test_intraday_operator_kernel_profiler_accepts_process_sharded_array_grouped_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
    ])

    proof = json.loads(output_path.read_text())
    assert exit_code == 0
    assert proof['verdict'] == 'ACCEPT'
    assert proof['comparison_issues'] == []
    rolling_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'rolling_corr_by_group'
    ]
    occupation_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'intraday_occupation_location_state'
    ]
    assert {profile['backend'] for profile in rolling_profiles} == {'numpy', 'process_sharded_array_grouped'}
    baseline_hash = next(profile['result_hash'] for profile in rolling_profiles if profile['backend'] == 'numpy')
    candidate = next(profile for profile in rolling_profiles if profile['backend'] == 'process_sharded_array_grouped')
    assert candidate['verdict'] == 'ACCEPT'
    assert candidate['result_hash'] == baseline_hash
    assert {profile['backend'] for profile in occupation_profiles} == {'pandas', 'process_sharded_array_grouped_occupation'}
    occupation_hash = next(profile['result_hash'] for profile in occupation_profiles if profile['backend'] == 'pandas')
    occupation_candidate = next(profile for profile in occupation_profiles if profile['backend'] == 'process_sharded_array_grouped_occupation')
    assert occupation_candidate['verdict'] == 'ACCEPT'
    assert occupation_candidate['result_hash'] == occupation_hash


def test_intraday_operator_kernel_profiler_profiles_cpv_operator_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-cpv-operator',
        '--cpv-backend',
        'array_grouped',
    ])

    proof = json.loads(output_path.read_text())
    cpv_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'cpv_price_volume_corr_state'
    ]
    assert exit_code == 0
    assert len(cpv_profiles) == 1
    assert cpv_profiles[0]['backend'] == 'array_grouped'
    assert cpv_profiles[0]['verdict'] == 'ACCEPT'
    assert cpv_profiles[0]['terminal_only'] is False
    assert cpv_profiles[0]['row_count'] == 48
    assert len(cpv_profiles[0]['result_hash']) == 64


def test_intraday_operator_kernel_profiler_profiles_terminal_cpv_operator_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-cpv-operator',
        '--cpv-backend',
        'array_grouped',
        '--cpv-terminal-only',
    ])

    proof = json.loads(output_path.read_text())
    cpv_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'cpv_price_volume_corr_state'
    ]
    assert exit_code == 0
    assert len(cpv_profiles) == 1
    assert cpv_profiles[0]['backend'] == 'array_grouped_terminal'
    assert cpv_profiles[0]['verdict'] == 'ACCEPT'
    assert cpv_profiles[0]['terminal_only'] is True
    assert cpv_profiles[0]['row_count'] == 4
    assert cpv_profiles[0]['comparison_row_count'] == 48
    assert cpv_profiles[0]['row_reduction_ratio'] < 1.0


def test_intraday_operator_kernel_profiler_profiles_terminal_cpv_process_candidate_with_terminal_baseline(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-cpv-operator',
        '--cpv-backend',
        'process_sharded_array_grouped',
        '--cpv-terminal-only',
        '--max-workers',
        '1',
    ])

    proof = json.loads(output_path.read_text())
    cpv_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'cpv_price_volume_corr_state'
    ]
    cpv_backends = {profile['backend'] for profile in cpv_profiles}
    cpv_candidates = [
        candidate for candidate in proof['performance_gate']['candidates']
        if candidate['operator_id'] == 'cpv_price_volume_corr_state'
    ]
    assert exit_code == 0
    assert cpv_backends == {'array_grouped_terminal', 'process_sharded_array_grouped_terminal'}
    assert len(cpv_candidates) == 1
    assert cpv_candidates[0]['baseline_backend'] == 'array_grouped_terminal'
    assert cpv_candidates[0]['candidate_backend'] == 'process_sharded_array_grouped_terminal'
    assert cpv_candidates[0]['performance_verdict'] in {'PROMOTE', 'HOLD'}
    assert proof['performance_gate']['production_default_allowed'] is False
    assert proof['comparison_issues'] == []


def test_intraday_operator_kernel_profiler_rolling_compare_allows_grouped_cumsum_roundoff():
    profiler = _load_profiler_module()
    baseline = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['20240104'],
        'hhmmss': [93300],
        'cpv_corr': [0.987654321123],
    })
    candidate = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['20240104'],
        'hhmmss': [93300],
        'cpv_corr': [0.987654201123],
    })

    issues = profiler._compare_rolling_corr(baseline, candidate, backend='array_grouped')

    assert issues == []


def test_intraday_operator_kernel_profiler_rolling_compare_allows_large_grouped_cumsum_roundoff():
    profiler = _load_profiler_module()
    baseline = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['20240104'],
        'hhmmss': [145700],
        'cpv_corr': [0.123456789],
    })
    candidate = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['20240104'],
        'hhmmss': [145700],
        'cpv_corr': [0.123470956],
    })

    issues = profiler._compare_rolling_corr(baseline, candidate, backend='array_grouped')

    assert issues == []


def test_intraday_operator_kernel_profiler_terminal_compare_allows_grouped_cumsum_roundoff():
    profiler = _load_profiler_module()
    reference = pd.DataFrame({
        'trade_date': ['20240104'],
        'ts_code': ['000001.SZ'],
        'terminal_order': [145700],
        'cpv_terminal_corr': [0.39850835370699417],
    })
    candidate = pd.DataFrame({
        'trade_date': ['20240104'],
        'ts_code': ['000001.SZ'],
        'terminal_order': [145700],
        'cpv_terminal_corr': [0.3985084111976355],
    })

    issues = profiler._compare_cpv_terminal(reference, candidate, backend='array_grouped_terminal')

    assert issues == []


def test_intraday_operator_kernel_profiler_occupation_compare_allows_cumsum_roundoff():
    profiler = _load_profiler_module()
    baseline = pd.DataFrame({
        'trade_date': ['20240104'],
        'ts_code': ['000001.SZ'],
        'bar_count': [240],
        'amount_sum': [123456789.123456],
        'volume_sum': [987654.0],
        'twap': [12.345678901234],
        'vwap': [12.345678902234],
        'vwap_minus_twap': [0.000000001],
    })
    candidate = pd.DataFrame({
        'trade_date': ['20240104'],
        'ts_code': ['000001.SZ'],
        'bar_count': [240],
        'amount_sum': [123456789.12360983],
        'volume_sum': [987654.0],
        'twap': [12.345678901334],
        'vwap': [12.345678902434],
        'vwap_minus_twap': [0.0000000011],
    })

    issues = profiler._compare_occupation(baseline, candidate, backend='array_grouped_occupation')

    assert issues == []


def test_intraday_operator_kernel_profiler_profiles_terminal_rolling_corr(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-terminal-rolling-corr',
        '--include-threaded-grouped',
        '--max-workers',
        '2',
    ])

    proof = json.loads(output_path.read_text())
    assert exit_code == 0
    terminal_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'terminal_rolling_corr_by_group'
    ]
    assert len(terminal_profiles) == 3
    assert {profile['backend'] for profile in terminal_profiles} == {
        'numpy_terminal',
        'threaded_grouped_terminal',
        'array_grouped_terminal',
    }
    for profile in terminal_profiles:
        assert profile['verdict'] == 'ACCEPT'
        assert profile['row_count'] == 4
        assert profile['comparison_row_count'] == 48
        assert profile['row_reduction_ratio'] < 1.0
        assert len(profile['result_hash']) == 64
    assert proof['terminal_rolling_corr_summary']['full_row_count'] == 48
    assert proof['terminal_rolling_corr_summary']['terminal_row_count'] == 4
    assert proof['terminal_rolling_corr_summary']['row_reduction_ratio'] < 1.0
    assert proof['comparison_issues'] == []


def test_intraday_operator_kernel_profiler_profiles_terminal_process_sharded_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-terminal-rolling-corr',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
    ])

    proof = json.loads(output_path.read_text())
    terminal_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'terminal_rolling_corr_by_group'
    ]
    terminal_backends = {profile['backend'] for profile in terminal_profiles}
    assert exit_code == 0
    assert 'process_sharded_array_grouped_terminal' in terminal_backends
    assert proof['comparison_issues'] == []
    candidate = next(profile for profile in terminal_profiles if profile['backend'] == 'process_sharded_array_grouped_terminal')
    assert candidate['verdict'] == 'ACCEPT'
    assert candidate['row_count'] == 4
    assert candidate['comparison_row_count'] == 48
    assert candidate['row_reduction_ratio'] < 1.0
    assert proof['performance_gate']['production_default_allowed'] is False


def test_intraday_operator_kernel_profiler_profiles_terminal_ema_state_candidate(tmp_path):
    profiler = _load_profiler_module()
    output_path = tmp_path / 'kernel_profile.json'

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-terminal-ema-state',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
    ])

    proof = json.loads(output_path.read_text())
    terminal_ema_profiles = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'terminal_ema_state_by_group'
    ]
    assert exit_code == 0
    assert {profile['backend'] for profile in terminal_ema_profiles} == {
        'array_grouped_ema_terminal',
        'process_sharded_array_grouped_ema_terminal',
    }
    for profile in terminal_ema_profiles:
        assert profile['verdict'] == 'ACCEPT'
        assert profile['row_count'] == 4
        assert profile['comparison_row_count'] == 48
        assert profile['row_reduction_ratio'] < 1.0
        assert len(profile['result_hash']) == 64
    assert proof['comparison_issues'] == []


def test_intraday_operator_kernel_profiler_terminal_compare_allows_direct_formula_roundoff():
    profiler = _load_profiler_module()
    reference = pd.DataFrame({
        'trade_date': ['20240104'],
        'ts_code': ['000001.SZ'],
        'terminal_order': [95300],
        'terminal_corr': [0.123456789123],
    })
    candidate = pd.DataFrame({
        'trade_date': ['20240104'],
        'ts_code': ['000001.SZ'],
        'terminal_order': [95300],
        'bar_count': [240],
        'terminal_corr': [0.123456789001],
    })

    issues = profiler._compare_terminal_corr(reference, candidate, backend='array_grouped_terminal')

    assert issues == []


def test_intraday_operator_kernel_profiler_profiles_terminal_numba_candidate_when_requested(monkeypatch):
    profiler = _load_profiler_module()
    original_terminal = profiler.terminal_rolling_corr_by_group
    original_profile_rolling = profiler._profile_rolling_corr
    original_profile_occupation = profiler._profile_occupation
    calls = {'numba_terminal': 0}

    def fake_profile_rolling(frame, *, backend, window, max_workers=None):
        if backend == 'numba_grouped':
            return {
                'operator_id': 'rolling_corr_by_group',
                'backend': 'numba_grouped',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 0.001,
                'row_count': len(frame),
                'result_hash': 'a' * 64,
                'issues': [],
            }, None
        return original_profile_rolling(frame, backend=backend, window=window, max_workers=max_workers)

    def fake_profile_occupation(frame, *, backend, max_workers=None):
        if backend == 'numba_grouped':
            return {
                'operator_id': 'intraday_occupation_location_state',
                'backend': 'numba_grouped',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 0.001,
                'row_count': 4,
                'result_hash': 'b' * 64,
                'issues': [],
            }, None
        return original_profile_occupation(frame, backend=backend, max_workers=max_workers)

    def fake_terminal(*args, **kwargs):
        if kwargs.get('backend') == 'numba_grouped':
            calls['numba_terminal'] += 1
            patched_kwargs = {**kwargs, 'backend': 'array_grouped'}
            out = original_terminal(*args, **patched_kwargs)
            out.attrs['operator_backend'] = 'numba_grouped_terminal'
            return out
        return original_terminal(*args, **kwargs)

    monkeypatch.setattr(profiler, 'terminal_rolling_corr_by_group', fake_terminal)
    monkeypatch.setattr(profiler, '_profile_rolling_corr', fake_profile_rolling)
    monkeypatch.setattr(profiler, '_profile_occupation', fake_profile_occupation)

    proof = profiler.run_profile(
        groups=4,
        rows_per_group=12,
        window=4,
        include_numba_grouped=True,
        include_threaded_grouped=False,
        include_terminal_rolling_corr=True,
        max_workers=1,
        seed=20260616,
    )
    terminal_backends = {
        profile['backend']
        for profile in proof['profiles']
        if profile['operator_id'] == 'terminal_rolling_corr_by_group'
    }
    assert calls['numba_terminal'] == 1
    assert 'numba_grouped_terminal' in terminal_backends
    assert proof['comparison_issues'] == []


def test_intraday_operator_kernel_profiler_names_blocked_terminal_numba_candidate(monkeypatch):
    profiler = _load_profiler_module()
    original_terminal = profiler.terminal_rolling_corr_by_group
    original_profile_rolling = profiler._profile_rolling_corr
    original_profile_occupation = profiler._profile_occupation

    def fake_profile_rolling(frame, *, backend, window, max_workers=None):
        if backend == 'numba_grouped':
            return {
                'operator_id': 'rolling_corr_by_group',
                'backend': 'numba_grouped',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 0.001,
                'row_count': len(frame),
                'result_hash': 'a' * 64,
                'issues': [],
            }, None
        return original_profile_rolling(frame, backend=backend, window=window, max_workers=max_workers)

    def fake_profile_occupation(frame, *, backend, max_workers=None):
        if backend == 'numba_grouped':
            return {
                'operator_id': 'intraday_occupation_location_state',
                'backend': 'numba_grouped',
                'verdict': 'ACCEPT',
                'elapsed_seconds': 0.001,
                'row_count': 4,
                'result_hash': 'b' * 64,
                'issues': [],
            }, None
        return original_profile_occupation(frame, backend=backend, max_workers=max_workers)

    def fake_terminal(*args, **kwargs):
        if kwargs.get('backend') == 'numba_grouped':
            raise ImportError('numba unavailable in test')
        return original_terminal(*args, **kwargs)

    monkeypatch.setattr(profiler, 'terminal_rolling_corr_by_group', fake_terminal)
    monkeypatch.setattr(profiler, '_profile_rolling_corr', fake_profile_rolling)
    monkeypatch.setattr(profiler, '_profile_occupation', fake_profile_occupation)

    proof = profiler.run_profile(
        groups=4,
        rows_per_group=12,
        window=4,
        include_numba_grouped=True,
        include_threaded_grouped=False,
        include_terminal_rolling_corr=True,
        max_workers=1,
        seed=20260616,
    )
    blocked_terminal = [
        profile for profile in proof['profiles']
        if profile['operator_id'] == 'terminal_rolling_corr_by_group' and profile['verdict'] == 'BLOCK'
    ]

    assert len(blocked_terminal) == 1
    assert blocked_terminal[0]['backend'] == 'numba_grouped_terminal'
    assert blocked_terminal[0]['issues'][0]['code'] == 'operator_backend_unavailable'


def test_intraday_operator_kernel_profiler_reads_bounded_parquet_without_production_permission(tmp_path):
    pytest.importorskip('pyarrow')
    profiler = _load_profiler_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_path = tmp_path / 'kernel_profile.json'
    pd.DataFrame({
        'ts_code': ['000001.SZ'] * 6 + ['000002.SZ'] * 6,
        'trade_date': ['20240104'] * 12,
        'hhmmss': [93100, 93200, 93300, 93400, 93500, 93600] * 2,
        'price': [10.0, 10.1, 10.2, 10.3, 10.1, 10.0, 20.0, 20.2, 20.1, 20.4, 20.3, 20.5],
        'volume': [100.0, 120.0, 130.0, 125.0, 110.0, 140.0, 200.0, 210.0, 205.0, 220.0, 215.0, 225.0],
        'amount': [1000.0, 1212.0, 1326.0, 1287.5, 1111.0, 1400.0, 4000.0, 4242.0, 4120.5, 4488.0, 4364.5, 4612.5],
    }).to_parquet(input_path, index=False)

    exit_code = profiler.main([
        '--output-path',
        str(output_path),
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '10',
        '--window',
        '3',
        '--include-threaded-grouped',
        '--max-workers',
        '2',
    ])

    proof = json.loads(output_path.read_text())
    assert exit_code == 0
    assert proof['verdict'] == 'ACCEPT'
    assert proof['input']['synthetic'] is False
    assert proof['input']['source_format'] == 'parquet'
    assert proof['input']['source_path'] == str(input_path)
    assert proof['input']['row_count'] == 10
    assert proof['performance_gate']['benchmark_scope'] == 'real_bounded_read_only'
    assert proof['performance_gate']['production_default_allowed'] is False
    assert proof['safety']['uses_real_market_data'] is True
    assert proof['safety']['starts_backfill'] is False
    assert proof['safety']['writes_datamart'] is False
    assert proof['safety']['production_loop_side_effect'] is False


def test_intraday_operator_kernel_performance_gate_separates_parity_from_promotion():
    profiler = _load_profiler_module()
    profiles = [
        {
            'operator_id': 'rolling_corr_by_group',
            'backend': 'numpy',
            'verdict': 'ACCEPT',
            'elapsed_seconds': 2.0,
            'result_hash': 'a',
        },
        {
            'operator_id': 'rolling_corr_by_group',
            'backend': 'threaded_grouped',
            'verdict': 'ACCEPT',
            'elapsed_seconds': 1.0,
            'result_hash': 'a',
        },
        {
            'operator_id': 'intraday_occupation_location_state',
            'backend': 'pandas',
            'verdict': 'ACCEPT',
            'elapsed_seconds': 2.0,
            'result_hash': 'b',
        },
        {
            'operator_id': 'intraday_occupation_location_state',
            'backend': 'threaded_grouped',
            'verdict': 'ACCEPT',
            'elapsed_seconds': 1.8,
            'result_hash': 'b',
        },
        {
            'operator_id': 'rolling_corr_by_group',
            'backend': 'numba_grouped',
            'verdict': 'BLOCK',
            'elapsed_seconds': 0.0,
            'result_hash': None,
        },
    ]

    gate = profiler._build_performance_gate(profiles, min_speedup_for_default=1.2)

    assert gate['benchmark_scope'] == 'synthetic_bounded'
    assert gate['production_default_allowed'] is False
    by_backend = {
        item['candidate_backend']: item
        for item in gate['candidates']
        if item['operator_id'] == 'rolling_corr_by_group'
    }
    assert by_backend['threaded_grouped']['performance_verdict'] == 'PROMOTE'
    assert by_backend['numba_grouped']['performance_verdict'] == 'BLOCK'
    occupation = [
        item for item in gate['candidates']
        if item['operator_id'] == 'intraday_occupation_location_state'
    ][0]
    assert occupation['performance_verdict'] == 'HOLD'
    assert gate['default_replacement_verdict'] == 'HOLD'
