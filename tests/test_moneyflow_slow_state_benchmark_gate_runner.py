from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_runner_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_moneyflow_slow_state_operator_benchmark_gate.py'
    spec = importlib.util.spec_from_file_location('run_moneyflow_slow_state_operator_benchmark_gate', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_slow_state_input(path: Path) -> None:
    rows = []
    for ticker in ['000001.SZ', '000002.SZ']:
        for idx, trade_date in enumerate(['20240102', '20240103', '20240104', '20240105']):
            rows.append({
                'ts_code': ticker,
                'trade_date': trade_date,
                'cutoff_time': '14:50:00',
                'v18a_z': float(idx),
                'v18b_z': 1.0 if idx % 2 == 0 else -1.0,
                'v19d_score': float(idx + 1),
            })
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_moneyflow_slow_state_benchmark_gate_accepts_real_bounded(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'flow_distribution_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_slow_state_input(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'slow_state_real',
        '--input-parquet',
        str(input_path),
        '--lambdas',
        '0.5,0.8',
        '--operator-backends',
        'reference,array_grouped,process_sharded_array_grouped',
        '--max-workers',
        '1',
        '--require-real-bounded',
        '--min-row-count',
        '8',
    ])

    bundle = json.loads((output_dir / 'slow_state_real.bundle.json').read_text(encoding='utf-8'))
    profile = json.loads(Path(bundle['profile_path']).read_text(encoding='utf-8'))
    validation = json.loads(Path(bundle['validation_path']).read_text(encoding='utf-8'))
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert profile['benchmark_scope'] == 'real_bounded_read_only'
    assert validation['verdict'] == 'ACCEPT'
    assert bundle['profile_summary']['production_default_allowed'] is False
    assert bundle['safety']['uses_real_market_data'] is True
    assert bundle['safety']['writes_datamart'] is False
    assert bundle['safety']['production_loop_side_effect'] is False


def test_moneyflow_slow_state_benchmark_gate_blocks_synthetic_when_real_required(tmp_path):
    runner = _load_runner_module()
    output_dir = tmp_path / 'gate'

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'slow_state_synthetic',
        '--tickers',
        '2',
        '--dates',
        '4',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'slow_state_synthetic.bundle.json').read_text(encoding='utf-8'))
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['validation_summary']['verdict'] == 'BLOCK'
    assert 'benchmark_scope_not_real_bounded' in bundle['validation_summary']['issues']
