from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_runner_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_intraday_operator_kernel_benchmark_gate.py'
    spec = importlib.util.spec_from_file_location('run_intraday_operator_kernel_benchmark_gate', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minute_sample(path: Path) -> None:
    pd.DataFrame({
        'ts_code': ['000001.SZ'] * 6 + ['000002.SZ'] * 6,
        'trade_date': ['20240104'] * 12,
        'hhmmss': [93100, 93200, 93300, 93400, 93500, 93600] * 2,
        'price': [10.0, 10.1, 10.2, 10.3, 10.1, 10.0, 20.0, 20.2, 20.1, 20.4, 20.3, 20.5],
        'volume': [100.0, 120.0, 130.0, 125.0, 110.0, 140.0, 200.0, 210.0, 205.0, 220.0, 215.0, 225.0],
        'amount': [1000.0, 1212.0, 1326.0, 1287.5, 1111.0, 1400.0, 4000.0, 4242.0, 4120.5, 4488.0, 4364.5, 4612.5],
    }).to_parquet(path, index=False)


def test_intraday_operator_kernel_benchmark_gate_runner_accepts_real_bounded(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'real_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '10',
        '--window',
        '3',
        '--include-threaded-grouped',
        '--max-workers',
        '2',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'real_test.bundle.json').read_text())
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert Path(bundle['profile_path']).name == 'real_test.profile.json'
    assert Path(bundle['validation_path']).name == 'real_test.validation.json'
    assert bundle['profile_summary']['benchmark_scope'] == 'real_bounded_read_only'
    assert bundle['validation_summary']['verdict'] == 'ACCEPT'
    assert bundle['safety']['writes_datamart'] is False
    assert bundle['safety']['production_loop_side_effect'] is False


def test_intraday_operator_kernel_benchmark_gate_runner_includes_terminal_summary(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'terminal_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-terminal-rolling-corr',
        '--include-threaded-grouped',
        '--max-workers',
        '2',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'terminal_test.bundle.json').read_text())
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert bundle['profile_summary']['terminal_rolling_corr_summary']['full_row_count'] == 12
    assert bundle['profile_summary']['terminal_rolling_corr_summary']['terminal_row_count'] == 2
    assert bundle['profile_summary']['terminal_rolling_corr_summary']['row_reduction_ratio'] < 1.0


def test_intraday_operator_kernel_benchmark_gate_runner_summarizes_terminal_process_sharded_candidate(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'terminal_process_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-terminal-rolling-corr',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'terminal_process_test.bundle.json').read_text())
    profile = json.loads(Path(bundle['profile_path']).read_text())
    terminal_backends = {
        item['backend']
        for item in profile['profiles']
        if item['operator_id'] == 'terminal_rolling_corr_by_group'
    }
    candidate_backends = {
        item['candidate_backend']
        for item in bundle['profile_summary']['performance_candidates']
        if item['operator_id'] == 'terminal_rolling_corr_by_group'
    }
    assert exit_code == 0
    assert 'process_sharded_array_grouped_terminal' in terminal_backends
    assert 'process_sharded_array_grouped_terminal' in candidate_backends
    assert bundle['profile_summary']['production_default_allowed'] is False


def test_intraday_operator_kernel_benchmark_gate_runner_passes_array_grouped_candidate(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'array_grouped_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-array-grouped',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'array_grouped_test.bundle.json').read_text())
    profile = json.loads(Path(bundle['profile_path']).read_text())
    rolling_backends = {
        item['backend']
        for item in profile['profiles']
        if item['operator_id'] == 'rolling_corr_by_group'
    }
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert 'array_grouped' in rolling_backends
    assert profile['comparison_issues'] == []


def test_intraday_operator_kernel_benchmark_gate_runner_passes_ema_state_profile(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'ema_state_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-ema-state',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'ema_state_test.bundle.json').read_text())
    profile = json.loads(Path(bundle['profile_path']).read_text())
    ema_profiles = [
        item for item in profile['profiles']
        if item['operator_id'] == 'grouped_ema_state_by_group'
    ]
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert len(ema_profiles) == 1
    assert ema_profiles[0]['backend'] == 'array_grouped_ema_state'
    assert ema_profiles[0]['verdict'] == 'ACCEPT'


def test_intraday_operator_kernel_benchmark_gate_runner_passes_terminal_ema_state_profile(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'terminal_ema_state_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-terminal-ema-state',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'terminal_ema_state_test.bundle.json').read_text())
    profile = json.loads(Path(bundle['profile_path']).read_text())
    terminal_ema_profiles = [
        item for item in profile['profiles']
        if item['operator_id'] == 'terminal_ema_state_by_group'
    ]
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert {item['backend'] for item in terminal_ema_profiles} == {
        'array_grouped_ema_terminal',
        'process_sharded_array_grouped_ema_terminal',
    }


def test_intraday_operator_kernel_benchmark_gate_runner_passes_process_sharded_candidate(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'process_sharded_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'process_sharded_test.bundle.json').read_text())
    profile = json.loads(Path(bundle['profile_path']).read_text())
    rolling_backends = {
        item['backend']
        for item in profile['profiles']
        if item['operator_id'] == 'rolling_corr_by_group'
    }
    occupation_backends = {
        item['backend']
        for item in profile['profiles']
        if item['operator_id'] == 'intraday_occupation_location_state'
    }
    candidate_backends = {
        (item['operator_id'], item['candidate_backend'])
        for item in bundle['profile_summary']['performance_candidates']
    }
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert 'process_sharded_array_grouped' in rolling_backends
    assert 'process_sharded_array_grouped_occupation' in occupation_backends
    assert ('intraday_occupation_location_state', 'process_sharded_array_grouped_occupation') in candidate_backends
    assert profile['comparison_issues'] == []


def test_intraday_operator_kernel_benchmark_gate_runner_passes_cpv_operator_candidate(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'cpv_operator_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-cpv-operator',
        '--cpv-backend',
        'array_grouped',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'cpv_operator_test.bundle.json').read_text())
    profile = json.loads(Path(bundle['profile_path']).read_text())
    cpv_profiles = [
        item for item in profile['profiles']
        if item['operator_id'] == 'cpv_price_volume_corr_state'
    ]
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert len(cpv_profiles) == 1
    assert cpv_profiles[0]['backend'] == 'array_grouped'
    assert cpv_profiles[0]['terminal_only'] is False


def test_intraday_operator_kernel_benchmark_gate_runner_passes_terminal_cpv_process_candidate(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'cpv_terminal_process_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-cpv-operator',
        '--cpv-backend',
        'process_sharded_array_grouped',
        '--cpv-terminal-only',
        '--max-workers',
        '1',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'cpv_terminal_process_test.bundle.json').read_text())
    profile = json.loads(Path(bundle['profile_path']).read_text())
    cpv_profiles = [
        item for item in profile['profiles']
        if item['operator_id'] == 'cpv_price_volume_corr_state'
    ]
    cpv_candidates = [
        item for item in bundle['profile_summary']['performance_candidates']
        if item['operator_id'] == 'cpv_price_volume_corr_state'
    ]
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert {item['backend'] for item in cpv_profiles} == {'array_grouped_terminal', 'process_sharded_array_grouped_terminal'}
    assert len(cpv_candidates) == 1
    assert cpv_candidates[0]['baseline_backend'] == 'array_grouped_terminal'
    assert cpv_candidates[0]['candidate_backend'] == 'process_sharded_array_grouped_terminal'
    assert bundle['profile_summary']['production_default_allowed'] is False
    assert bundle['safety']['writes_datamart'] is False


def test_intraday_operator_kernel_benchmark_gate_runner_blocks_synthetic_when_real_required(tmp_path):
    runner = _load_runner_module()
    output_dir = tmp_path / 'gate'

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'synthetic_test',
        '--groups',
        '4',
        '--rows-per-group',
        '12',
        '--window',
        '4',
        '--include-threaded-grouped',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'synthetic_test.bundle.json').read_text())
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['profile_summary']['benchmark_scope'] == 'synthetic_bounded'
    assert bundle['validation_summary']['verdict'] == 'BLOCK'
    assert 'benchmark_scope_not_real_bounded' in bundle['validation_summary']['issues']


def test_intraday_operator_kernel_benchmark_gate_runner_blocks_real_bounded_below_min_rows(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'small_real_test',
        '--input-parquet',
        str(input_path),
        '--row-limit',
        '12',
        '--window',
        '3',
        '--include-array-grouped',
        '--require-real-bounded',
        '--min-row-count',
        '1000',
    ])

    bundle = json.loads((output_dir / 'small_real_test.bundle.json').read_text())
    validation = json.loads(Path(bundle['validation_path']).read_text())
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['validation_summary']['verdict'] == 'BLOCK'
    assert 'input_row_count_below_minimum' in bundle['validation_summary']['issues']
    assert validation['input_row_count'] == 12
    assert validation['min_row_count'] == 1000
