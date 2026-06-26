from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_safe_runner_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_intraday_operator_safe_worker_benchmark.py'
    spec = importlib.util.spec_from_file_location('run_intraday_operator_safe_worker_benchmark', path)
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


def test_safe_worker_benchmark_stops_before_input_read_when_preflight_blocks(tmp_path):
    runner = _load_safe_runner_module()
    output_dir = tmp_path / 'safe_worker'

    exit_code = runner.main([
        '--input-root',
        str(tmp_path / 'missing_minute_root'),
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        str(output_dir),
        '--label',
        'safe_busy',
        '--dates',
        '20240104',
        '--row-limit',
        '8',
        '--min-row-count',
        '8',
        '--preflight-load1',
        '32',
        '--preflight-cpu-count',
        '4',
        '--preflight-available-memory-gb',
        '64',
        '--preflight-process-snapshot-json',
        '[]',
    ])

    payload = json.loads((output_dir / 'safe_busy.safe_worker_benchmark.bundle.json').read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['evidence_scope'] == 'bounded_worker'
    assert payload['blocked_stage'] == 'preflight'
    assert payload['preflight_summary']['verdict'] == 'BLOCK'
    assert 'load1_per_cpu_above_limit' in payload['preflight_summary']['issues']
    assert payload['worker_benchmark_bundle_path'] is None
    assert payload['worker_validation_path'] is None
    assert not (output_dir / 'safe_busy.sample.parquet').exists()


def test_safe_worker_benchmark_runs_preflight_benchmark_and_validation(tmp_path):
    pytest.importorskip('pyarrow')
    runner = _load_safe_runner_module()
    minute_root = tmp_path / 'minute_bar'
    _write_raw_partition(minute_root, '20240104')
    output_dir = tmp_path / 'safe_worker'

    exit_code = runner.main([
        '--input-root',
        str(minute_root),
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        str(output_dir),
        '--label',
        'safe_smoke',
        '--dates',
        '20240104',
        '--window',
        '3',
        '--row-limit',
        '8',
        '--min-row-count',
        '8',
        '--include-array-grouped',
        '--include-ema-state',
        '--include-terminal-ema-state',
        '--include-process-sharded-array-grouped',
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

    payload = json.loads((output_dir / 'safe_smoke.safe_worker_benchmark.bundle.json').read_text())
    validation = json.loads(Path(payload['worker_validation_path']).read_text())
    worker_bundle = json.loads(Path(payload['worker_benchmark_bundle_path']).read_text())
    gate_profile = json.loads(Path(worker_bundle['gate_profile_path']).read_text())
    ema_profiles = [
        item for item in gate_profile['profiles']
        if item['operator_id'] == 'grouped_ema_state_by_group'
    ]
    terminal_ema_profiles = [
        item for item in gate_profile['profiles']
        if item['operator_id'] == 'terminal_ema_state_by_group'
    ]
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['evidence_scope'] == 'bounded_worker'
    assert payload['preflight_summary']['verdict'] == 'ACCEPT'
    assert payload['worker_benchmark_summary']['verdict'] == 'ACCEPT'
    assert payload['worker_validation_summary']['verdict'] == 'ACCEPT'
    assert payload['worker_validation_summary']['evidence_scope'] == 'bounded_worker'
    assert validation['evidence_scope'] == 'bounded_worker'
    assert worker_bundle['evidence_scope'] == 'bounded_worker'
    assert validation['input_row_count'] == 8
    assert {item['backend'] for item in ema_profiles} == {
        'array_grouped_ema_state',
        'process_sharded_array_grouped_ema_state',
    }
    assert {item['backend'] for item in terminal_ema_profiles} == {
        'array_grouped_ema_terminal',
        'process_sharded_array_grouped_ema_terminal',
    }
    assert payload['safety']['writes_datamart'] is False
    assert payload['safety']['production_loop_side_effect'] is False
