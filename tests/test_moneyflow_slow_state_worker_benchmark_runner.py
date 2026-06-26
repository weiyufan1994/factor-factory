from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_runner_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_moneyflow_slow_state_worker_benchmark.py'
    spec = importlib.util.spec_from_file_location('run_moneyflow_slow_state_worker_benchmark', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_partition(root: Path, trade_date: str, *, missing_fields: bool = False) -> None:
    part = root / f'trade_date={trade_date}'
    part.mkdir(parents=True)
    payload = {
        'ts_code': ['000001.SZ', '000002.SZ'],
        'trade_date': [trade_date, trade_date],
        'cutoff_time': ['14:50:00', '14:50:00'],
        'v18a_z': [0.1, 0.2],
        'v18b_z': [1.0, -1.0],
        'v19d_score': [10.0, 20.0],
    }
    if missing_fields:
        payload.pop('v18a_z')
    pd.DataFrame(payload).to_parquet(part / 'part.parquet', index=False)


def test_moneyflow_slow_state_worker_benchmark_accepts_bounded_root(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_root = tmp_path / 'slow_state_input'
    _write_partition(input_root, '20240102')
    _write_partition(input_root, '20240103')
    output_dir = tmp_path / 'worker'

    exit_code = runner.main([
        '--input-root',
        str(input_root),
        '--output-dir',
        str(output_dir),
        '--label',
        'slow_worker',
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
    ])

    bundle = json.loads((output_dir / 'slow_worker.worker_benchmark.bundle.json').read_text(encoding='utf-8'))
    gate_bundle = json.loads(Path(bundle['gate_bundle_path']).read_text(encoding='utf-8'))
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert bundle['sample_summary']['row_count'] == 4
    assert bundle['gate_summary']['benchmark_scope'] == 'real_bounded_read_only'
    assert gate_bundle['validation_summary']['verdict'] == 'ACCEPT'
    assert bundle['safety']['read_only_input'] is True
    assert bundle['safety']['writes_datamart'] is False
    assert bundle['safety']['production_loop_side_effect'] is False


def test_moneyflow_slow_state_worker_benchmark_stops_when_sample_blocks(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_root = tmp_path / 'bad_slow_state_input'
    _write_partition(input_root, '20240102', missing_fields=True)
    output_dir = tmp_path / 'worker'

    exit_code = runner.main([
        '--input-root',
        str(input_root),
        '--output-dir',
        str(output_dir),
        '--label',
        'slow_worker_bad',
        '--dates',
        '20240102',
        '--min-row-count',
        '1',
    ])

    bundle = json.loads((output_dir / 'slow_worker_bad.worker_benchmark.bundle.json').read_text(encoding='utf-8'))
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['blocked_reason'] == 'sample_builder_not_accept'
    assert bundle['gate_bundle_path'] is None
    assert bundle['sample_summary']['row_count'] == 0
    assert bundle['safety']['writes_datamart'] is False
