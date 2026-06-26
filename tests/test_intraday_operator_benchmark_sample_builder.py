from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_builder_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_intraday_operator_benchmark_sample.py'
    spec = importlib.util.spec_from_file_location('build_intraday_operator_benchmark_sample', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_raw_partition(root: Path, trade_date: str) -> None:
    part = root / f'trade_date={trade_date}'
    part.mkdir(parents=True)
    pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ', '000002.SZ'],
        'trade_date': [trade_date] * 4,
        'trade_time': ['09:31:00', '09:32:00', '09:31:00', '09:32:00'],
        'open': [10.0, 10.1, 20.0, 20.2],
        'close': [10.1, 10.2, 20.2, 20.1],
        'vol': [100.0, 120.0, 200.0, 210.0],
        'amount': [1010.0, 1224.0, 4040.0, 4221.0],
    }).to_parquet(part / 'part.parquet', index=False)


def _write_prepared_partition(root: Path, trade_date: str) -> None:
    part = root / f'trade_date={trade_date}'
    part.mkdir(parents=True)
    pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ', '000002.SZ'],
        'trade_date': [trade_date] * 4,
        'hhmmss': [93100, 93200, 93100, 93200],
        'amount_abs': [1010.0, 1224.0, 4040.0, 4221.0],
        'minute_ret': [0.01, 0.0099, 0.01, -0.005],
        'signed_amount': [1010.0, 1224.0, 4040.0, -4221.0],
        'vol': [100.0, 120.0, 200.0, 210.0],
    }).to_parquet(part / 'part.parquet', index=False)


def test_benchmark_sample_builder_writes_raw_minute_sample_and_proof(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    minute_root = tmp_path / 'minute_bar'
    _write_raw_partition(minute_root, '20240104')
    _write_raw_partition(minute_root, '20240105')
    output_path = tmp_path / 'benchmark_sample.parquet'
    proof_path = tmp_path / 'benchmark_sample.proof.json'

    exit_code = builder.main([
        '--input-root',
        str(minute_root),
        '--input-format',
        'raw_minute_bar',
        '--output-parquet',
        str(output_path),
        '--proof-output',
        str(proof_path),
        '--start',
        '20240104',
        '--end',
        '20240105',
        '--row-limit',
        '6',
    ])

    out = pd.read_parquet(output_path)
    proof = json.loads(proof_path.read_text())
    assert exit_code == 0
    assert list(out.columns) == ['ts_code', 'trade_date', 'hhmmss', 'price', 'volume', 'amount']
    assert len(out) == 6
    assert proof['verdict'] == 'ACCEPT'
    assert proof['input_format'] == 'raw_minute_bar'
    assert proof['row_count'] == 6
    assert proof['duplicate_key_count'] == 0
    assert proof['price_source'] == 'close'
    assert proof['volume_source'] == 'vol'
    assert proof['safety']['writes_datamart'] is False
    assert proof['safety']['production_loop_side_effect'] is False


def test_benchmark_sample_builder_converts_prepared_minute_sample_with_proxy_label(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    _write_prepared_partition(prepared_root, '20240104')
    output_path = tmp_path / 'prepared_benchmark_sample.parquet'
    proof_path = tmp_path / 'prepared_benchmark_sample.proof.json'

    exit_code = builder.main([
        '--input-root',
        str(prepared_root),
        '--input-format',
        'prepared_minute_bar_v1',
        '--output-parquet',
        str(output_path),
        '--proof-output',
        str(proof_path),
        '--dates',
        '20240104',
    ])

    out = pd.read_parquet(output_path)
    proof = json.loads(proof_path.read_text())
    assert exit_code == 0
    assert out['price'].tolist() == [0.01, 0.0099, 0.01, -0.005]
    assert out['volume'].tolist() == [100.0, 120.0, 200.0, 210.0]
    assert out['amount'].tolist() == [1010.0, 1224.0, 4040.0, 4221.0]
    assert proof['input_format'] == 'prepared_minute_bar_v1'
    assert proof['price_source'] == 'minute_ret_proxy'
    assert proof['semantic_scope'] == 'operator_speed_benchmark_not_alpha_input'
    assert proof['safety']['writes_datamart'] is False


def test_benchmark_sample_builder_uses_hive_partition_trade_date_when_missing(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    minute_root = tmp_path / 'minute_bar'
    part = minute_root / 'trade_date=20240104'
    part.mkdir(parents=True)
    pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_time': ['09:31:00'],
        'open': [10.0],
        'close': [10.1],
        'vol': [100.0],
        'amount': [1010.0],
    }).to_parquet(part / 'part.parquet', index=False)
    output_path = tmp_path / 'benchmark_sample.parquet'
    proof_path = tmp_path / 'benchmark_sample.proof.json'

    exit_code = builder.main([
        '--input-root',
        str(minute_root),
        '--input-format',
        'raw_minute_bar',
        '--output-parquet',
        str(output_path),
        '--proof-output',
        str(proof_path),
        '--dates',
        '20240104',
    ])

    out = pd.read_parquet(output_path)
    proof = json.loads(proof_path.read_text())
    assert exit_code == 0
    assert out['trade_date'].tolist() == ['20240104']
    assert proof['verdict'] == 'ACCEPT'
