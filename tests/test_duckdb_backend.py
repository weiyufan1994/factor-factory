from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from factor_factory.data_api import DataApiClient, DataQuery, validate_data_api_result


def write_catalog(path: Path, datasets: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'catalog_version': 'factorforge_data_catalog_v1', 'datasets': datasets}, indent=2), encoding='utf-8')


def test_duckdb_backend_reads_partitioned_parquet_with_projection_and_filters(tmp_path):
    for date, rows in {
        '20260102': [
            {'ts_code': '000001.SZ', 'close': 10.0, 'amount': 1000.0},
            {'ts_code': '000002.SZ', 'close': 20.0, 'amount': 2000.0},
        ],
        '20260103': [
            {'ts_code': '000001.SZ', 'close': 11.0, 'amount': 1100.0},
            {'ts_code': '000003.SZ', 'close': 30.0, 'amount': 3000.0},
        ],
    }.items():
        part = tmp_path / 'daily' / f'trade_date={date}'
        part.mkdir(parents=True)
        pd.DataFrame(rows).to_parquet(part / 'part.parquet', index=False)
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, {
        'clean_daily_bar': {
            'uri': str(tmp_path / 'daily'),
            'format': 'parquet',
            'storage': 'local',
            'columns': ['ts_code', 'trade_date', 'close', 'amount'],
            'partition_columns': ['trade_date'],
            'metadata': {
                'acceleration': {'default_backend': 'duckdb'},
                'unique_key': ['trade_date', 'ts_code'],
            },
        },
    })

    result = DataApiClient.from_catalog(catalog).fetch(
        DataQuery('clean_daily_bar', '20260103', '20260103', ['000001.SZ'], ['close'])
    )

    assert result.status == 'ready'
    assert result.source.backend == 'duckdb'
    assert result.coverage.row_count == 1
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.to_dict('records') == [
        {'trade_date': '20260103', 'ts_code': '000001.SZ', 'close': 11.0},
    ]
    assert validate_data_api_result(result).result == 'PASS'


def test_duckdb_backend_keeps_metadata_unique_key_for_long_form_universe(tmp_path):
    data_path = tmp_path / 'universe.parquet'
    pd.DataFrame([
        {'universe_id': 'small10', 'trade_date': '20260102', 'ts_code': '000001.SZ', 'in_universe': True},
        {'universe_id': 'small20', 'trade_date': '20260102', 'ts_code': '000001.SZ', 'in_universe': True},
    ]).to_parquet(data_path, index=False)
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, {
        'microcap_universe': {
            'uri': str(data_path),
            'format': 'parquet',
            'storage': 'local',
            'columns': ['universe_id', 'trade_date', 'ts_code', 'in_universe'],
            'metadata': {
                'acceleration': {'default_backend': 'duckdb'},
                'unique_key': ['universe_id', 'trade_date', 'ts_code'],
                'sort_keys': ['universe_id', 'trade_date', 'ts_code'],
            },
        },
    })

    result = DataApiClient.from_catalog(catalog).fetch(
        DataQuery('microcap_universe', '20260102', '20260102', 'a_share_all', ['in_universe'])
    )

    assert result.status == 'ready'
    assert result.source.backend == 'duckdb'
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == ['universe_id', 'trade_date', 'ts_code', 'in_universe']
    assert result.frame['universe_id'].tolist() == ['small10', 'small20']
