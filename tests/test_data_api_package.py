from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery, DataQueryInvalid, validate_data_api_result


def write_catalog(path: Path, datasets: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'catalog_version': 'factorforge_data_catalog_v1', 'datasets': datasets}, indent=2), encoding='utf-8')


def test_data_query_normalizes_dates_and_universe():
    q = DataQuery(
        dataset='clean_daily_bar',
        start_date='2026-01-02',
        end_date=pd.Timestamp('2026-01-05'),
        universe=['000001.SZ'],
        fields=['close'],
    )
    assert q.start_date == '20260102'
    assert q.end_date == '20260105'
    assert q.symbols == ('000001.SZ',)
    with pytest.raises(DataQueryInvalid):
        DataQuery('clean_daily_bar', 'bad-date', '20260105', 'a_share_all', ['close'])
    with pytest.raises(DataQueryInvalid):
        DataQuery('clean_daily_bar', '20260102', '20260105', 'csi500', ['close'])


def test_catalog_env_and_default_path(monkeypatch, tmp_path):
    root = tmp_path / 'factorforge'
    catalog = root / 'data' / 'catalog' / 'data_catalog.json'
    write_catalog(catalog, {})
    monkeypatch.setenv('FACTORFORGE_ROOT', str(root))
    monkeypatch.delenv('FACTORFORGE_DATA_CATALOG', raising=False)
    assert DataApiClient.from_default_catalog().catalog.path == catalog
    override = tmp_path / 'override.json'
    write_catalog(override, {})
    monkeypatch.setenv('FACTORFORGE_DATA_CATALOG', str(override))
    assert DataApiClient.from_env().catalog.path == override


def test_local_parquet_fetch_returns_schema_coverage_and_alias(tmp_path):
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame([
        {'ts_code': '000002.SZ', 'trade_date': '20260102', 'close': 20.0, 'vol': 200},
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0, 'vol': 100},
    ]).to_parquet(data_path, index=False)
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, {
        'clean_daily_bar': {
            'uri': str(data_path),
            'format': 'parquet',
            'columns': ['ts_code', 'trade_date', 'close', 'vol'],
            'date_column': 'trade_date',
            'symbol_column': 'ts_code',
            'qlib_field_map': {'$close': 'close', '$volume': 'vol'},
        }
    })
    result = DataApiClient.from_catalog(catalog).fetch(
        DataQuery('clean_daily_bar', '20260102', '20260102', 'a_share_all', ['close', 'volume'])
    )
    assert result.status == 'ready'
    assert result.resolved_fields['volume'] == 'vol'
    assert list(result.frame.columns) == ['ts_code', 'trade_date', 'close', 'vol']
    assert result.frame['ts_code'].tolist() == ['000001.SZ', '000002.SZ']
    assert result.coverage.row_count == 2
    assert result.coverage.date_count == 1
    assert result.schema.logical_fields['volume'] == 'vol'
    assert validate_data_api_result(result).result == 'PASS'


def test_missing_field_and_unknown_dataset_block(tmp_path):
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0}]).to_parquet(data_path, index=False)
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, {'clean_daily_bar': {'uri': str(data_path), 'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'close']}})
    client = DataApiClient.from_catalog(catalog)
    missing = client.fetch(DataQuery('clean_daily_bar', '20260102', '20260102', 'a_share_all', ['industry_code']))
    assert missing.status == 'blocked'
    assert missing.coverage.missing_fields == ['industry_code']
    unknown = client.fetch(DataQuery('daily_basic', '20260102', '20260102', 'a_share_all', ['pe']))
    assert unknown.status == 'blocked'
    assert 'dataset_not_found' in (unknown.blocked_reason or '')


def test_market_cap_proxy_ready_only_when_configured(tmp_path):
    data_path = tmp_path / 'basic.parquet'
    pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20260102', 'total_mv': 100.0, 'circ_mv': 80.0}]).to_parquet(data_path, index=False)
    catalog = tmp_path / 'catalog.json'
    base = {'uri': str(data_path), 'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'total_mv', 'circ_mv']}
    write_catalog(catalog, {'daily_basic': base})
    client = DataApiClient.from_catalog(catalog)
    blocked = client.fetch(DataQuery('daily_basic', '20260102', '20260102', 'a_share_all', ['market_cap']))
    assert blocked.status == 'blocked'

    write_catalog(catalog, {'daily_basic': {**base, 'proxy_fields': {'market_cap': {'field': 'total_mv', 'rationale': 'catalog_configured_proxy'}}}})
    proxy = DataApiClient.from_catalog(catalog).fetch(DataQuery('daily_basic', '20260102', '20260102', 'a_share_all', ['market_cap']))
    assert proxy.status == 'proxy_ready'
    assert proxy.proxy_rules[0].requested == 'market_cap'
    assert proxy.proxy_rules[0].resolved == 'total_mv'
    assert list(proxy.frame.columns) == ['ts_code', 'trade_date', 'total_mv']


def test_universe_filter_and_duplicate_detection(tmp_path):
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame([
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0},
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 11.0},
        {'ts_code': '000002.SZ', 'trade_date': '20260102', 'close': 20.0},
    ]).to_parquet(data_path, index=False)
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, {'clean_daily_bar': {'uri': str(data_path), 'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'close']}})
    result = DataApiClient.from_catalog(catalog).fetch(
        DataQuery('clean_daily_bar', '20260102', '20260102', ['000001.SZ'], ['close'])
    )
    assert result.coverage.universe_matched_count == 1
    assert result.coverage.duplicate_key_count == 1
    assert result.status == 'blocked'
    assert validate_data_api_result(result).result == 'BLOCK'

    allowed = DataApiClient.from_catalog(catalog).fetch(
        DataQuery('clean_daily_bar', '20260102', '20260102', ['000001.SZ'], ['close'], allow_duplicate_keys=True)
    )
    assert allowed.coverage.duplicate_key_count == 1
    assert allowed.status == 'ready'
    assert validate_data_api_result(allowed).result == 'PASS'


def test_allow_duplicate_keys_does_not_mask_zero_row_block(tmp_path):
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame([
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0},
    ]).to_parquet(data_path, index=False)
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, {'clean_daily_bar': {'uri': str(data_path), 'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'close']}})

    result = DataApiClient.from_catalog(catalog).fetch(
        DataQuery('clean_daily_bar', '20260103', '20260103', 'a_share_all', ['close'], allow_duplicate_keys=True)
    )

    assert result.coverage.duplicate_key_count == 0
    assert result.coverage.row_count == 0
    assert result.status == 'blocked'
    assert 'row_count_nonzero_or_blocked' in (result.blocked_reason or '')
    assert validate_data_api_result(result).result == 'BLOCK'


def test_partitioned_minute_parquet_uses_string_partition_schema(tmp_path):
    part = tmp_path / 'minute' / 'trade_date=20260102'
    part.mkdir(parents=True)
    pd.DataFrame([
        {'ts_code': '000001.SZ', 'trade_time': pd.Timestamp('2026-01-02 09:30:00'), 'trade_date': '20260102', 'open': 10.0, 'close': 10.1, 'vol': 100},
    ]).to_parquet(part / 'part-000.parquet', index=False)
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, {
        'minute_bar': {
            'uri': str(tmp_path / 'minute'),
            'format': 'parquet',
            'columns': ['ts_code', 'trade_time', 'trade_date', 'open', 'close', 'vol'],
            'partition_columns': ['trade_date'],
            'date_column': 'trade_date',
            'symbol_column': 'ts_code',
        }
    })
    result = DataApiClient.from_catalog(catalog).fetch(
        DataQuery('minute_bar', '20260102', '20260102', ['000001.SZ'], ['open', 'close', 'vol'], frequency='1min')
    )
    assert result.status == 'ready'
    assert result.frame['trade_date'].tolist() == ['20260102']
