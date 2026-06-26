from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_smoke_module():
    path = REPO_ROOT / 'scripts' / 'run_data_api_read_smoke.py'
    spec = importlib.util.spec_from_file_location('run_data_api_read_smoke', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_daily_catalog(tmp_path: Path, rows: list[dict]) -> Path:
    root = tmp_path / 'daily_technical_state_v1'
    frame = pd.DataFrame(rows)
    for trade_date, part in frame.groupby('trade_date', sort=True):
        part_dir = root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True, exist_ok=True)
        part.drop(columns=['trade_date']).to_parquet(part_dir / 'part.parquet', index=False)
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            'daily_technical_state_v1': {
                'dataset_id': 'daily_technical_state_v1',
                'uri': str(root),
                'format': 'parquet',
                'storage': 'local',
                'columns': ['ts_code', 'trade_date', 'ret_1d', 'volatility_20d'],
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'clean_daily_bar',
                    'schema_version': 'daily_technical_state_v1',
                    'producer_version': 'daily_technical_state_builder_v1',
                    'unique_key': ['ts_code', 'trade_date'],
                    'sort_keys': ['ts_code', 'trade_date'],
                },
            }
        },
    }
    catalog_path = tmp_path / 'catalog.json'
    catalog_path.write_text(json.dumps(catalog), encoding='utf-8')
    return catalog_path


def test_data_api_read_smoke_accepts_ready_dataset(tmp_path: Path):
    pytest.importorskip('pyarrow')
    module = _load_smoke_module()
    catalog = _write_daily_catalog(
        tmp_path,
        [
            {'ts_code': '000001.SZ', 'trade_date': '20240110', 'ret_1d': 0.01, 'volatility_20d': 0.2},
            {'ts_code': '000002.SZ', 'trade_date': '20240110', 'ret_1d': -0.01, 'volatility_20d': 0.3},
        ],
    )
    output = tmp_path / 'read_smoke.json'

    exit_code = module.main([
        '--catalog', str(catalog),
        '--dataset-id', 'daily_technical_state_v1',
        '--start-date', '20240110',
        '--end-date', '20240110',
        '--fields', 'ret_1d,volatility_20d',
        '--output-path', str(output),
    ])

    payload = json.loads(output.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['status'] == 'ready'
    assert payload['validation_result'] == 'PASS'
    assert payload['row_count'] == 2
    assert payload['duplicate_key_count'] == 0
    assert payload['returned_columns'] == ['ts_code', 'trade_date', 'ret_1d', 'volatility_20d']
    assert payload['safety']['writes_active_catalog'] is False


def test_data_api_read_smoke_blocks_duplicate_keys(tmp_path: Path):
    pytest.importorskip('pyarrow')
    module = _load_smoke_module()
    catalog = _write_daily_catalog(
        tmp_path,
        [
            {'ts_code': '000001.SZ', 'trade_date': '20240110', 'ret_1d': 0.01, 'volatility_20d': 0.2},
            {'ts_code': '000001.SZ', 'trade_date': '20240110', 'ret_1d': 0.02, 'volatility_20d': 0.4},
        ],
    )
    output = tmp_path / 'read_smoke.json'

    exit_code = module.main([
        '--catalog', str(catalog),
        '--dataset-id', 'daily_technical_state_v1',
        '--start-date', '20240110',
        '--end-date', '20240110',
        '--fields', 'ret_1d',
        '--output-path', str(output),
    ])

    payload = json.loads(output.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['status'] == 'blocked'
    assert payload['duplicate_key_count'] == 1
    assert 'duplicate_key_count_nonzero' in payload['issues']
