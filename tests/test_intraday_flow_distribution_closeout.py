from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from factor_factory.data_api.flow_distribution_moments import (
    DATASET_ID,
    P0_COLUMNS,
    PRODUCER_VERSION,
    SCHEMA_VERSION,
    UNIQUE_KEY,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_closeout_module():
    path = REPO_ROOT / 'scripts' / 'closeout_intraday_flow_distribution_moments.py'
    spec = importlib.util.spec_from_file_location('closeout_intraday_flow_distribution_moments', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def _qa() -> dict:
    return {
        'verdict': 'ACCEPT',
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_min_trade_date': '20160104',
        'source_max_trade_date': '20250711',
        'output_min_trade_date': '20160104',
        'output_max_trade_date': '20250711',
        'row_count': 1200000,
        'date_count': 2200,
        'ticker_count': 5200,
        'duplicate_key_count': 0,
        'missing_dates': [],
        'threshold_source': 'prior_dates',
        'threshold_lookback_days': [20, 60],
        'no_future_intraday_minutes': True,
        'hard_checks': {
            'duplicate_key_count_zero': True,
            'no_future_intraday_minutes_true': True,
            'threshold_source_prior_dates': True,
            'minute_count': True,
            'amount_sum': True,
            'amount_hhi': True,
            'signed_flow_hhi': True,
            'large_proxy_amount': True,
            'small_proxy_amount': True,
        },
        'performance_profile': {
            'read_seconds': 1.0,
            'compute_seconds': 2.0,
            'write_seconds': 0.5,
            'qa_seconds': 0.1,
        },
        'output_path': '/cache/datamarts/intraday_flow_distribution_moments_v1_is',
    }


def _catalog() -> dict:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: {
                'uri': '/cache/datamarts/intraday_flow_distribution_moments_v1_is',
                'format': 'parquet',
                'storage': 'local',
                'columns': P0_COLUMNS,
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'minute_bar',
                    'schema_version': SCHEMA_VERSION,
                    'producer_version': PRODUCER_VERSION,
                    'unique_key': UNIQUE_KEY,
                    'threshold_source': 'prior_dates',
                    'no_future_intraday_minutes': True,
                    'information_set_legality': 'trade_time <= cutoff_time; thresholds from prior dates',
                },
                'freshness': {
                    'trade_date_min': '20160104',
                    'trade_date_max': '20250711',
                },
            }
        },
    }


def _read_smoke() -> dict:
    return {
        'verdict': 'ACCEPT',
        'status': 'ready',
        'warm_read_seconds': 0.25,
        'row_count': 5000,
        'date_count': 1,
        'ticker_count': 5000,
        'duplicate_key_count': 0,
    }


def _manifest(remaining_dates: list[str] | None = None) -> dict:
    return {
        'verdict': 'ACCEPT',
        'dataset_id': DATASET_ID,
        'processed_dates': ['20160104'],
        'skipped_existing_dates': [],
        'remaining_dates': list(remaining_dates or []),
    }


def _run(tmp_path: Path, *, qa: dict | None = None, read_smoke: dict | None = None, required_end: str = '20250711') -> tuple[int, dict]:
    closeout = _load_closeout_module()
    qa_path = _write(tmp_path / 'qa.json', qa or _qa())
    catalog_path = _write(tmp_path / 'catalog.json', _catalog())
    smoke_path = _write(tmp_path / 'read_smoke.json', read_smoke or _read_smoke())
    batch1_path = _write(tmp_path / 'batch1.manifest.json', _manifest())
    batch2_path = _write(tmp_path / 'batch2.manifest.json', _manifest())
    output_path = tmp_path / 'closeout.json'
    exit_code = closeout.main([
        '--qa-path',
        str(qa_path),
        '--catalog-path',
        str(catalog_path),
        '--read-smoke-path',
        str(smoke_path),
        '--batch1-manifest-path',
        str(batch1_path),
        '--batch2-manifest-path',
        str(batch2_path),
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--worker-command',
        'PYTHONPATH=. python3 scripts/build_intraday_flow_distribution_moments.py ...',
        '--required-start',
        '20160104',
        '--required-end',
        required_end,
        '--min-row-count',
        '1000000',
        '--min-date-count',
        '2000',
        '--output-path',
        str(output_path),
    ])
    return exit_code, json.loads(output_path.read_text(encoding='utf-8'))


def test_flow_distribution_closeout_accepts_complete_contract(tmp_path: Path):
    exit_code, payload = _run(tmp_path)

    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['dataset_id'] == DATASET_ID
    assert payload['output_coverage']['duplicate_key_count'] == 0
    assert payload['output_coverage']['unique_key'] == UNIQUE_KEY
    assert payload['worker_read_smoke']['verdict'] == 'ACCEPT'
    assert payload['contract_issues'] == []
    assert payload['validation_issues'] == []


def test_flow_distribution_closeout_blocks_missing_worker_smoke(tmp_path: Path):
    smoke = _read_smoke()
    smoke['verdict'] = 'BLOCK'

    exit_code, payload = _run(tmp_path, read_smoke=smoke)

    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['block_token'] == 'BLOCK_DATA_API_WORKER_READ_SMOKE_MISSING'
    assert 'read_smoke_not_accept' in payload['validation_issues']


def test_flow_distribution_closeout_blocks_coverage_mismatch(tmp_path: Path):
    qa = _qa()
    qa['output_max_trade_date'] = '20240131'

    exit_code, payload = _run(tmp_path, qa=qa)

    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['block_token'] == 'BLOCK_DATA_API_SOURCE_COVERAGE_INCOMPLETE'
    assert 'coverage_end_mismatch' in payload['validation_issues']
