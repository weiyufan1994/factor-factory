from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_safe_runner_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_moneyflow_slow_state_safe_worker_benchmark.py'
    spec = importlib.util.spec_from_file_location('run_moneyflow_slow_state_safe_worker_benchmark', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_partition(root: Path, trade_date: str) -> None:
    part = root / f'trade_date={trade_date}'
    part.mkdir(parents=True)
    pd.DataFrame({
        'ts_code': ['000001.SZ', '000002.SZ'],
        'trade_date': [trade_date, trade_date],
        'cutoff_time': ['14:50:00', '14:50:00'],
        'v18a_z': [0.1, 0.2],
        'v18b_z': [1.0, -1.0],
        'v19d_score': [10.0, 20.0],
    }).to_parquet(part / 'part.parquet', index=False)


def test_moneyflow_slow_state_safe_worker_stops_before_input_read_when_preflight_blocks(tmp_path):
    runner = _load_safe_runner_module()
    output_dir = tmp_path / 'safe_worker'

    exit_code = runner.main([
        '--input-root',
        str(tmp_path / 'missing_slow_state_input'),
        '--output-dir',
        str(output_dir),
        '--label',
        'slow_busy',
        '--dates',
        '20240102',
        '--row-limit',
        '4',
        '--min-row-count',
        '4',
        '--preflight-load1',
        '32',
        '--preflight-cpu-count',
        '4',
        '--preflight-available-memory-gb',
        '64',
        '--preflight-process-snapshot-json',
        '[]',
    ])

    payload = json.loads((output_dir / 'slow_busy.safe_worker_benchmark.bundle.json').read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['blocked_stage'] == 'preflight'
    assert payload['preflight_summary']['verdict'] == 'BLOCK'
    assert 'load1_per_cpu_above_limit' in payload['preflight_summary']['issues']
    assert payload['worker_benchmark_bundle_path'] is None
    assert not (output_dir / 'slow_busy.sample.parquet').exists()
    assert payload['safety']['writes_datamart'] is False
    assert payload['safety']['production_loop_side_effect'] is False


def test_moneyflow_slow_state_safe_worker_runs_preflight_and_worker_gate(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_safe_runner_module()
    input_root = tmp_path / 'slow_state_input'
    _write_partition(input_root, '20240102')
    _write_partition(input_root, '20240103')
    output_dir = tmp_path / 'safe_worker'

    exit_code = runner.main([
        '--input-root',
        str(input_root),
        '--output-dir',
        str(output_dir),
        '--label',
        'slow_safe',
        '--dates',
        '20240102,20240103',
        '--row-limit',
        '4',
        '--min-row-count',
        '4',
        '--lambdas',
        '0.5,0.8',
        '--operator-backends',
        'reference,array_grouped,process_sharded_array_grouped',
        '--max-workers',
        '1',
        '--preflight-load1',
        '1',
        '--preflight-cpu-count',
        '8',
        '--preflight-available-memory-gb',
        '64',
        '--preflight-process-snapshot-json',
        '[]',
    ])

    payload = json.loads((output_dir / 'slow_safe.safe_worker_benchmark.bundle.json').read_text(encoding='utf-8'))
    worker_bundle = json.loads(Path(payload['worker_benchmark_bundle_path']).read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['blocked_stage'] is None
    assert payload['preflight_summary']['verdict'] == 'ACCEPT'
    assert payload['worker_benchmark_summary']['verdict'] == 'ACCEPT'
    assert payload['worker_benchmark_summary']['sample_row_count'] == 4
    assert worker_bundle['gate_summary']['benchmark_scope'] == 'real_bounded_read_only'
    assert payload['safety']['read_only_input'] is True
    assert payload['safety']['writes_datamart'] is False
    assert payload['safety']['writes_catalog'] is False
    assert payload['safety']['production_loop_side_effect'] is False
