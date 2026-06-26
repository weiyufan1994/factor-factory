from __future__ import annotations

from pathlib import Path

from factor_factory.data_api.catalog import CatalogDataset, DataCatalog
from factor_factory.data_api.datamart_contracts import (
    DATA_API_BLOCK_TOKENS,
    build_closeout_skeleton,
    build_datamart_inventory,
    build_shard_manifest_skeleton,
    validate_closeout,
    validate_shard_manifest,
)


def test_inventory_extracts_reusable_datamart_contract_fields(tmp_path: Path):
    catalog = DataCatalog(
        path=tmp_path / 'data_catalog.json',
        datasets={
            'intraday_flow_state_v2': CatalogDataset(
                dataset_id='intraday_flow_state_v2',
                uri='s3://bucket/factorforge/datamart/intraday_flow_state_v2_is/',
                format='parquet',
                storage='s3',
                version='v2',
                columns=('ts_code', 'trade_date', 'cutoff_time', 'flow_z'),
                partition_columns=('trade_date',),
                freshness={'trade_date_min': '20160104', 'trade_date_max': '20250711', 'rows': 100, 'trade_dates': 2, 'tickers': 50},
                metadata={
                    'schema_version': 'intraday_flow_state_v2_schema_v2',
                    'producer_version': 'flow_state_builder_20260610',
                    'source_datasets': ['minute_bar', 'daily_basic'],
                    'unique_key': ['ts_code', 'trade_date', 'cutoff_time'],
                    'supported_cutoff_times': ['14:50', '14:55'],
                    'qa_summary_path': 's3://bucket/proofs/qa.json',
                    'information_set_legality': 'trade_time <= cutoff_time only',
                    'latest_reviewer_verdict': 'ACCEPT',
                },
            )
        },
    )

    inventory = build_datamart_inventory(catalog)
    entry = inventory['datasets'][0]

    assert inventory['schema_version'] == 'datamart_inventory_v1'
    assert entry['dataset_id'] == 'intraday_flow_state_v2'
    assert entry['source_datasets'] == ['minute_bar', 'daily_basic']
    assert entry['unique_key'] == ['ts_code', 'trade_date', 'cutoff_time']
    assert entry['coverage']['end_date'] == '20250711'
    assert entry['deprecation_status'] == 'active'


def valid_accept_closeout() -> dict:
    payload = build_closeout_skeleton(
        dataset_id='moneyflow_v20_slow_state_v1',
        source_datasets=['intraday_flow_distribution_moments_v1', 'daily_basic_backtest_base'],
        unique_key=['ts_code', 'trade_date', 'cutoff_time', 'lambda'],
        producer_version='moneyflow_v20_slow_state_builder_20260616',
        schema_version='moneyflow_v20_slow_state_v1_schema_v1',
        verdict='ACCEPT',
    )
    payload['output_identity']['parameter_hash'] = 'abc123'
    payload['source_coverage'].update({'start': '20160104', 'end': '20250711'})
    payload['output_coverage'].update({'date_count': 2313, 'row_count': 30000000, 'ticker_count': 5200})
    payload['lookahead_contract']['notes'] = 'uses prior state and source datamarts that are cutoff-clean'
    payload['performance_profile'].update({
        'read_seconds': 10.0,
        'compute_seconds': 20.0,
        'write_seconds': 5.0,
        'qa_seconds': 1.0,
        'warm_read_seconds_representative': 0.3,
    })
    payload['catalog_path'] = 's3://bucket/factorforge/data/catalog/moneyflow_v20_slow_state_v1.catalog.json'
    payload['datamart_path'] = 's3://bucket/factorforge/datamart/moneyflow_v20_slow_state_v1/'
    payload['qa_path'] = 's3://bucket/factorforge/proofs/moneyflow_v20_slow_state_v1.qa.json'
    payload['worker_smoke_path'] = 's3://bucket/factorforge/proofs/moneyflow_v20_slow_state_v1.worker_smoke.json'
    payload['worker_read_smoke'].update({
        'instance_id': 'i-02cc0b6e93856fbb4',
        'command': 'python -m factor_factory.data_api.smoke moneyflow_v20_slow_state_v1',
        'warm_read_seconds': 0.3,
        'verdict': 'ACCEPT',
    })
    return payload


def test_accept_closeout_requires_catalog_qa_worker_smoke_and_perf():
    payload = valid_accept_closeout()

    assert validate_closeout(payload) == []


def test_accept_closeout_blocks_duplicate_keys_and_missing_smoke():
    payload = valid_accept_closeout()
    payload['output_coverage']['duplicate_key_count'] = 1
    payload['worker_read_smoke']['verdict'] = 'BLOCK'

    fields = {issue.field for issue in validate_closeout(payload)}

    assert 'output_coverage.duplicate_key_count' in fields
    assert 'worker_read_smoke.verdict' in fields


def test_block_closeout_requires_standard_block_token():
    payload = build_closeout_skeleton(
        dataset_id='intraday_flow_distribution_moments_v1',
        source_datasets=['minute_bar'],
        unique_key=['ts_code', 'trade_date', 'cutoff_time'],
        verdict='BLOCK',
    )
    payload['block_token'] = DATA_API_BLOCK_TOKENS[0]

    assert validate_closeout(payload) == []


def test_shard_manifest_is_resumable_and_validated():
    manifest = build_shard_manifest_skeleton(dataset_id='intraday_flow_distribution_moments_v1', shard_id='2020-01')
    manifest['shards'][0]['source_partitions'] = ['trade_date=20200102']

    assert validate_shard_manifest(manifest) == []

    manifest['resumable'] = False
    fields = {issue.field for issue in validate_shard_manifest(manifest)}
    assert 'resumable' in fields
