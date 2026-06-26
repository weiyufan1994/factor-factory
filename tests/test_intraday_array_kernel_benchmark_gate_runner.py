from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_runner_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_intraday_array_kernel_benchmark_gate.py'
    spec = importlib.util.spec_from_file_location('run_intraday_array_kernel_benchmark_gate', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minute_sample(path: Path) -> None:
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
    pd.DataFrame(rows).sample(frac=1.0, random_state=17).to_parquet(path, index=False)


def test_intraday_array_kernel_benchmark_gate_accepts_real_bounded(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'real_direct_array',
        '--input-parquet',
        str(input_path),
        '--window',
        '4',
        '--require-real-bounded',
        '--min-row-count',
        '32',
    ])

    bundle = json.loads((output_dir / 'real_direct_array.bundle.json').read_text(encoding='utf-8'))
    profile = json.loads(Path(bundle['profile_path']).read_text(encoding='utf-8'))
    validation = json.loads(Path(bundle['validation_path']).read_text(encoding='utf-8'))
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert bundle['profile_summary']['benchmark_scope'] == 'real_bounded_direct_array'
    assert bundle['profile_summary']['direct_array_inputs'] is True
    assert bundle['profile_summary']['input_row_count'] == 32
    assert bundle['profile_summary']['input_group_count'] == 4
    assert bundle['validation_summary']['verdict'] == 'ACCEPT'
    assert bundle['safety']['writes_datamart'] is False
    assert bundle['safety']['production_loop_side_effect'] is False
    assert profile['comparison_issues'] == []
    assert validation['issues'] == []


def test_intraday_array_kernel_benchmark_gate_blocks_synthetic_when_real_required(tmp_path):
    runner = _load_runner_module()
    output_dir = tmp_path / 'gate'

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'synthetic_direct_array',
        '--groups',
        '4',
        '--rows-per-group',
        '16',
        '--window',
        '4',
        '--require-real-bounded',
    ])

    bundle = json.loads((output_dir / 'synthetic_direct_array.bundle.json').read_text(encoding='utf-8'))
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['profile_summary']['benchmark_scope'] == 'synthetic_bounded_direct_array'
    assert 'benchmark_scope_not_real_bounded_direct_array' in bundle['validation_summary']['issues']
    assert bundle['safety']['writes_datamart'] is False


def test_intraday_array_kernel_benchmark_gate_blocks_real_bounded_below_min_rows(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    input_path = tmp_path / 'minute_sample.parquet'
    output_dir = tmp_path / 'gate'
    _write_minute_sample(input_path)

    exit_code = runner.main([
        '--output-dir',
        str(output_dir),
        '--label',
        'small_real_direct_array',
        '--input-parquet',
        str(input_path),
        '--window',
        '4',
        '--require-real-bounded',
        '--min-row-count',
        '1000',
    ])

    bundle = json.loads((output_dir / 'small_real_direct_array.bundle.json').read_text(encoding='utf-8'))
    validation = json.loads(Path(bundle['validation_path']).read_text(encoding='utf-8'))
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['validation_summary']['verdict'] == 'BLOCK'
    assert 'input_row_count_below_minimum' in bundle['validation_summary']['issues']
    assert validation['input_row_count'] == 32
    assert validation['min_row_count'] == 1000
