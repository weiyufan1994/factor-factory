from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_runner_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_intraday_operator_worker_benchmark.py'
    spec = importlib.util.spec_from_file_location('run_intraday_operator_worker_benchmark', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_raw_partition(root: Path, trade_date: str, rows_per_symbol: int = 4) -> None:
    part = root / f'trade_date={trade_date}'
    part.mkdir(parents=True)
    rows = []
    for ts_code, base in [('000001.SZ', 10.0), ('000002.SZ', 20.0)]:
        for idx in range(rows_per_symbol):
            close = base + idx * 0.1
            rows.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'trade_time': f'09:{31 + idx:02d}:00',
                'open': close - 0.02,
                'close': close,
                'vol': 100.0 + idx,
                'amount': close * (100.0 + idx),
            })
    pd.DataFrame(rows).to_parquet(part / 'part.parquet', index=False)


def test_worker_benchmark_runner_builds_sample_runs_gate_and_writes_bundle(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    minute_root = tmp_path / 'minute_bar'
    _write_raw_partition(minute_root, '20240104')
    output_dir = tmp_path / 'worker_gate'

    exit_code = runner.main([
        '--input-root',
        str(minute_root),
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        str(output_dir),
        '--label',
        'worker_smoke',
        '--dates',
        '20240104',
        '--window',
        '3',
        '--row-limit',
        '8',
        '--min-row-count',
        '8',
        '--include-array-grouped',
        '--include-process-sharded-array-grouped',
        '--max-workers',
        '1',
    ])

    bundle = json.loads((output_dir / 'worker_smoke.worker_benchmark.bundle.json').read_text())
    sample = json.loads(Path(bundle['sample_proof_path']).read_text())
    gate = json.loads(Path(bundle['gate_bundle_path']).read_text())
    assert exit_code == 0
    assert bundle['verdict'] == 'ACCEPT'
    assert bundle['evidence_scope'] == 'bounded_worker'
    assert bundle['sample_summary']['row_count'] == 8
    assert bundle['gate_summary']['benchmark_scope'] == 'real_bounded_read_only'
    assert sample['safety']['writes_datamart'] is False
    assert sample['safety']['writes_catalog'] is False
    assert gate['safety']['writes_datamart'] is False
    assert gate['safety']['production_loop_side_effect'] is False
    assert bundle['safety']['writes_datamart'] is False
    assert bundle['safety']['production_loop_side_effect'] is False


def test_worker_benchmark_runner_blocks_when_min_rows_not_met(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_runner_module()
    minute_root = tmp_path / 'minute_bar'
    _write_raw_partition(minute_root, '20240104')
    output_dir = tmp_path / 'worker_gate'

    exit_code = runner.main([
        '--input-root',
        str(minute_root),
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        str(output_dir),
        '--label',
        'worker_small',
        '--evidence-scope',
        'production_scale',
        '--dates',
        '20240104',
        '--window',
        '3',
        '--row-limit',
        '8',
        '--min-row-count',
        '1000',
        '--include-array-grouped',
        '--max-workers',
        '1',
    ])

    bundle = json.loads((output_dir / 'worker_small.worker_benchmark.bundle.json').read_text())
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['evidence_scope'] == 'production_scale'
    assert bundle['gate_summary']['validation_verdict'] == 'BLOCK'
    assert 'input_row_count_below_minimum' in bundle['gate_summary']['validation_issues']


def test_worker_benchmark_runner_stops_when_preflight_blocks(tmp_path):
    runner = _load_runner_module()
    output_dir = tmp_path / 'worker_gate'
    preflight_path = tmp_path / 'preflight.json'
    preflight_path.write_text(json.dumps({
        'verdict': 'BLOCK',
        'issues': ['protected_process_active:factorforge'],
        'metrics': {'load1_per_cpu': 0.1},
        'safety': {
            'starts_backfill': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }))

    exit_code = runner.main([
        '--input-root',
        str(tmp_path / 'missing_minute_root'),
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        str(output_dir),
        '--label',
        'worker_busy',
        '--dates',
        '20240104',
        '--window',
        '3',
        '--row-limit',
        '8',
        '--min-row-count',
        '8',
        '--preflight-path',
        str(preflight_path),
        '--include-array-grouped',
    ])

    bundle_path = output_dir / 'worker_busy.worker_benchmark.bundle.json'
    bundle = json.loads(bundle_path.read_text())
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['evidence_scope'] == 'bounded_worker'
    assert bundle['preflight_path'] == str(preflight_path)
    assert bundle['preflight_summary']['verdict'] == 'BLOCK'
    assert 'protected_process_active:factorforge' in bundle['preflight_summary']['issues']
    assert not (output_dir / 'worker_busy.sample.parquet').exists()


def test_worker_benchmark_runner_stops_when_sample_builder_blocks(tmp_path):
    runner = _load_runner_module()
    output_dir = tmp_path / 'worker_gate'

    exit_code = runner.main([
        '--input-root',
        str(tmp_path / 'missing_minute_root'),
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        str(output_dir),
        '--label',
        'worker_no_sample',
        '--dates',
        '20240104',
        '--window',
        '3',
        '--row-limit',
        '8',
        '--min-row-count',
        '8',
        '--include-array-grouped',
    ])

    bundle = json.loads((output_dir / 'worker_no_sample.worker_benchmark.bundle.json').read_text())
    assert exit_code == 1
    assert bundle['verdict'] == 'BLOCK'
    assert bundle['evidence_scope'] == 'bounded_worker'
    assert bundle['blocked_reason'] == 'sample_builder_not_accept'
    assert bundle['sample_summary']['verdict'] == 'BLOCK'
    assert bundle['gate_bundle_path'] is None
    assert not (output_dir / 'worker_no_sample.gate').exists()
