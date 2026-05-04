from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from factor_factory.data_access.api import build_data_requirement, load_dataset
from factor_factory.data_access.catalog import CATALOG_SCHEMA_FIELDS, DatasetEntry, default_catalog_path, load_catalog, upsert_dataset


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_catalog_loads_local_parquet_slice(tmp_path):
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame(
        [
            {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0, 'vol': 100},
            {'ts_code': '000002.SZ', 'trade_date': '20260102', 'close': 20.0, 'vol': 200},
            {'ts_code': '000001.SZ', 'trade_date': '20260105', 'close': 11.0, 'vol': 120},
        ]
    ).to_parquet(data_path, index=False)

    catalog_path = tmp_path / 'catalog.json'
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri=str(data_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'close', 'vol'),
            date_column='trade_date',
            symbol_column='ts_code',
        ),
        catalog_path,
    )

    loaded = load_catalog(catalog_path)
    assert 'clean_daily_bar' in loaded

    frame = load_dataset(
        'clean_daily_bar',
        start='20260105',
        symbols=['000001.SZ'],
        columns=['ts_code', 'trade_date', 'close'],
        catalog_path=catalog_path,
    )
    assert frame.to_dict(orient='records') == [
        {'ts_code': '000001.SZ', 'trade_date': '20260105', 'close': 11.0}
    ]


def test_catalog_default_path_and_env_override(monkeypatch, tmp_path):
    root = tmp_path / 'factorforge'
    override = tmp_path / 'custom_catalog.json'

    monkeypatch.delenv('FACTORFORGE_DATA_CATALOG', raising=False)
    monkeypatch.setenv('FACTORFORGE_ROOT', str(root))
    assert default_catalog_path() == root / 'data' / 'catalog' / 'data_catalog.json'

    monkeypatch.setenv('FACTORFORGE_DATA_CATALOG', str(override))
    assert default_catalog_path() == override


def test_catalog_write_exposes_stable_schema_fields(tmp_path):
    catalog_path = tmp_path / 'catalog.json'
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri='s3://bucket/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet',
            format='parquet',
            storage='s3',
            columns=('ts_code', 'trade_date', 'close', 'vol'),
            date_column='trade_date',
            symbol_column='ts_code',
            qlib_field_map={'$close': 'close', '$volume': 'vol'},
            freshness={'trade_date_max': '20260105'},
            metadata={'producer': 'test'},
        ),
        catalog_path,
    )
    payload = json.loads(catalog_path.read_text(encoding='utf-8'))
    assert payload['schema_fields'] == list(CATALOG_SCHEMA_FIELDS)
    entry = payload['datasets'][0]
    for field in CATALOG_SCHEMA_FIELDS:
        assert field in entry


def test_data_requirement_contract_is_agent_consumable(tmp_path):
    requirement = build_data_requirement(
        'minute_bar',
        reason='factor needs intraday liquidity imbalance',
        start='20260101',
        end='20260131',
        symbols=['000001.SZ'],
        columns=['ts_code', 'trade_time', 'close', 'vol'],
        frequency='1min',
        required_transform='clean and align Tushare stk_mins to qlib fields',
    )
    assert requirement['type'] == 'factorforge_data_requirement'
    assert requirement['producer_contract']['preferred_storage'] == 's3'
    assert requirement['request']['dataset_id'] == 'minute_bar'

    path = tmp_path / 'requirement.json'
    path.write_text(json.dumps(requirement, ensure_ascii=False), encoding='utf-8')
    assert json.loads(path.read_text(encoding='utf-8'))['frequency'] == '1min'


def test_cli_request_writes_manual_resolution(tmp_path):
    catalog_path = tmp_path / 'catalog.json'
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri=str(tmp_path / 'daily.parquet'),
            format='parquet',
            columns=('ts_code', 'trade_date', 'close'),
        ),
        catalog_path,
    )
    output = tmp_path / 'minute_requirement.json'
    env = os.environ.copy()
    env['FACTORFORGE_DATA_CATALOG'] = str(catalog_path)
    proc = subprocess.run(
        [
            sys.executable,
            'scripts/factorforge_data_api.py',
            'request',
            'minute_bar',
            '--reason',
            'needs intraday bars',
            '--columns',
            'ts_code,trade_time,close,vol',
            '--output',
            str(output),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert payload['resolution']['status'] == 'manual_request'
    assert payload['resolution']['dataset_id'] == 'minute_bar'
    assert payload['resolution']['missing_fields'] == ['ts_code', 'trade_time', 'close', 'vol']
    assert payload['resolution']['resolved_fields'] == {}
    assert payload['resolution']['available_datasets'] == ['clean_daily_bar']
