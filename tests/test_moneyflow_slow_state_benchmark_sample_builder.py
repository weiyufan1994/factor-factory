from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load_builder_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_moneyflow_slow_state_benchmark_sample.py'
    spec = importlib.util.spec_from_file_location('build_moneyflow_slow_state_benchmark_sample', path)
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


def test_moneyflow_slow_state_sample_builder_writes_standard_input_and_proof(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    input_root = tmp_path / 'slow_state_input'
    _write_partition(input_root, '20240102')
    _write_partition(input_root, '20240103')
    output_path = tmp_path / 'slow_state_sample.parquet'
    proof_path = tmp_path / 'slow_state_sample.proof.json'

    exit_code = builder.main([
        '--input-root',
        str(input_root),
        '--output-parquet',
        str(output_path),
        '--proof-output',
        str(proof_path),
        '--start',
        '20240102',
        '--end',
        '20240103',
        '--row-limit',
        '3',
    ])

    out = pd.read_parquet(output_path)
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert list(out.columns) == ['ts_code', 'trade_date', 'cutoff_time', 'v18a_z', 'v18b_z', 'v19d_score']
    assert len(out) == 3
    assert proof['verdict'] == 'ACCEPT'
    assert proof['dataset_id'] == 'moneyflow_slow_state_benchmark_sample'
    assert proof['source_dataset'] == 'intraday_flow_distribution_moments_v1_or_derived_input'
    assert proof['duplicate_key_count'] == 0
    assert proof['safety']['read_only_input'] is True
    assert proof['safety']['writes_datamart'] is False
    assert proof['safety']['production_loop_side_effect'] is False


def test_moneyflow_slow_state_sample_builder_blocks_missing_required_fields(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    input_root = tmp_path / 'bad_slow_state_input'
    part = input_root / 'trade_date=20240102'
    part.mkdir(parents=True)
    pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['20240102'],
        'cutoff_time': ['14:50:00'],
        'v19d_score': [10.0],
    }).to_parquet(part / 'part.parquet', index=False)
    output_path = tmp_path / 'bad_sample.parquet'
    proof_path = tmp_path / 'bad_sample.proof.json'

    exit_code = builder.main([
        '--input-root',
        str(input_root),
        '--output-parquet',
        str(output_path),
        '--proof-output',
        str(proof_path),
        '--dates',
        '20240102',
    ])

    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert exit_code == 2
    assert proof['verdict'] == 'BLOCK'
    assert proof['row_count'] == 0
    assert proof['read_errors'][0]['status'] == 'read_or_normalize_error'
    assert 'missing required columns' in proof['read_errors'][0]['error']


def test_moneyflow_slow_state_sample_builder_uses_hive_partition_trade_date(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    input_root = tmp_path / 'partitioned_slow_state_input'
    part = input_root / 'trade_date=20240102'
    part.mkdir(parents=True)
    pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'cutoff_time': ['14:50:00'],
        'v18a_z': [0.1],
        'v18b_z': [1.0],
        'v19d_score': [10.0],
    }).to_parquet(part / 'part.parquet', index=False)
    output_path = tmp_path / 'sample.parquet'
    proof_path = tmp_path / 'sample.proof.json'

    exit_code = builder.main([
        '--input-root',
        str(input_root),
        '--output-parquet',
        str(output_path),
        '--proof-output',
        str(proof_path),
        '--dates',
        '20240102',
    ])

    out = pd.read_parquet(output_path)
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert out['trade_date'].tolist() == ['20240102']
    assert proof['verdict'] == 'ACCEPT'
