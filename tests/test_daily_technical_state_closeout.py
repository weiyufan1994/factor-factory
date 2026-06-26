from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from factor_factory.data_api.daily_technical_state import FEATURE_COLUMNS


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_closeout_module():
    path = REPO_ROOT / 'scripts' / 'closeout_daily_technical_state.py'
    spec = importlib.util.spec_from_file_location('closeout_daily_technical_state', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def _validation() -> dict:
    return {
        'verdict': 'ACCEPT',
        'dataset_id': 'daily_technical_state_v1',
        'schema_version': 'daily_technical_state_v1',
        'feature_parquet': '/cache/datamarts/daily_technical_state_v1',
        'warm_read_seconds': 0.8,
        'row_count': 1100000,
        'date_count': 2200,
        'ticker_count': 5200,
        'feature_count': len(FEATURE_COLUMNS),
        'duplicate_key_count': 0,
        'missing_columns': [],
        'unexpected_columns': [],
        'rebuilt_qa': {
            'verdict': 'ACCEPT',
            'dataset_id': 'daily_technical_state_v1',
            'start_date': '20160104',
            'end_date': '20250711',
            'row_count': 1100000,
            'date_count': 2200,
            'ticker_count': 5200,
            'feature_count': len(FEATURE_COLUMNS),
            'duplicate_key_count': 0,
            'information_set_legality': {
                'uses_future_rows': False,
            },
        },
    }


def _catalog() -> dict:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            'daily_technical_state_v1': {
                'dataset_id': 'daily_technical_state_v1',
                'uri': '/cache/datamarts/daily_technical_state_v1',
                'format': 'parquet',
                'storage': 'local',
                'columns': ['ts_code', 'trade_date', *FEATURE_COLUMNS],
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'clean_daily_bar',
                    'schema_version': 'daily_technical_state_v1',
                    'producer_version': 'daily_technical_state_builder_v1',
                    'unique_key': ['ts_code', 'trade_date'],
                    'information_set_legality': 'current and prior daily bars only; no future shifts',
                },
            }
        },
    }


def _read_smoke() -> dict:
    return {
        'verdict': 'ACCEPT',
        'status': 'ready',
        'warm_read_seconds': 0.2,
        'row_count': 5000,
        'date_count': 1,
        'ticker_count': 5000,
        'duplicate_key_count': 0,
    }


def _manifest(remaining_dates: list[str] | None = None) -> dict:
    return {
        'verdict': 'ACCEPT',
        'dataset_id': 'daily_technical_state_v1',
        'processed_dates': ['20160104'],
        'skipped_dates': [],
        'remaining_dates': list(remaining_dates or []),
    }


def _run(tmp_path: Path, *, validation: dict | None = None, read_smoke: dict | None = None) -> tuple[int, dict]:
    closeout = _load_closeout_module()
    validation_path = _write(tmp_path / 'validation.json', validation or _validation())
    catalog_path = _write(tmp_path / 'catalog.json', _catalog())
    smoke_path = _write(tmp_path / 'read_smoke.json', read_smoke or _read_smoke())
    batch1_path = _write(tmp_path / 'batch1.manifest.json', _manifest())
    batch2_path = _write(tmp_path / 'batch2.manifest.json', _manifest())
    output_path = tmp_path / 'closeout.json'
    exit_code = closeout.main([
        '--validation-path',
        str(validation_path),
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
        'PYTHONPATH=. python3 scripts/build_daily_technical_state.py ...',
        '--required-start',
        '20160104',
        '--required-end',
        '20250711',
        '--min-row-count',
        '1000000',
        '--min-date-count',
        '2000',
        '--output-path',
        str(output_path),
    ])
    return exit_code, json.loads(output_path.read_text(encoding='utf-8'))


def test_daily_technical_state_closeout_accepts_complete_contract(tmp_path: Path):
    exit_code, payload = _run(tmp_path)

    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['dataset_id'] == 'daily_technical_state_v1'
    assert payload['output_coverage']['duplicate_key_count'] == 0
    assert payload['output_coverage']['feature_count'] == len(FEATURE_COLUMNS)
    assert payload['worker_read_smoke']['verdict'] == 'ACCEPT'
    assert payload['contract_issues'] == []
    assert payload['validation_issues'] == []


def test_daily_technical_state_closeout_blocks_missing_worker_smoke(tmp_path: Path):
    smoke = _read_smoke()
    smoke['verdict'] = 'BLOCK'

    exit_code, payload = _run(tmp_path, read_smoke=smoke)

    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['block_token'] == 'BLOCK_DATA_API_WORKER_READ_SMOKE_MISSING'
    assert 'read_smoke_not_accept' in payload['validation_issues']


def test_daily_technical_state_closeout_blocks_coverage_mismatch(tmp_path: Path):
    validation = _validation()
    validation['rebuilt_qa']['end_date'] = '20240131'

    exit_code, payload = _run(tmp_path, validation=validation)

    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['block_token'] == 'BLOCK_DATA_API_SOURCE_COVERAGE_INCOMPLETE'
    assert 'coverage_end_mismatch' in payload['validation_issues']
