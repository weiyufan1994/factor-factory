from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

from factor_factory.data_api.smart_money_intraday_state import OUTPUT_COLUMNS
from scripts.closeout_smart_money_intraday_state import build_catalog, validate_frame


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_closeout_module():
    path = REPO_ROOT / 'scripts' / 'closeout_smart_money_intraday_state.py'
    spec = importlib.util.spec_from_file_location('closeout_smart_money_intraday_state', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_closeout_catalog_declares_smart_money_contract():
    catalog = build_catalog(
        root='s3://bucket/factorforge/datamart/smart_money_intraday_state/v1/',
        qa_path='s3://bucket/proofs/qa.json',
        start='20160104',
        end='20250711',
        row_count=10,
        date_count=2,
        ticker_count=5,
        research_window='IS+OOS',
    )
    entry = catalog['datasets']['smart_money_intraday_state_v1']
    assert entry['storage'] == 's3'
    assert entry['partition_columns'] == ['trade_date']
    assert entry['metadata']['unique_key'] == ['ts_code', 'trade_date']
    assert entry['metadata']['no_future_data'] is True
    assert entry['metadata']['no_future_intraday_minutes'] is True
    assert 'q_log_volume' in entry['metadata']['variants']


def test_validate_frame_blocks_duplicate_key_and_future_flag():
    row = {column: 1 for column in OUTPUT_COLUMNS}
    row.update({
        'ts_code': '000001.SZ',
        'trade_date': '20200102',
        'qa_status': 'pass',
        'no_future_data': True,
        'no_future_intraday_minutes': False,
        'research_window': 'SMOKE',
    })
    frame = pd.DataFrame([row, row])
    result = validate_frame(frame, '20200102')
    assert result['verdict'] == 'BLOCK'
    assert 'duplicate_key_count_nonzero' in result['issues']
    assert 'no_future_intraday_minutes_not_true' in result['issues']


def test_closeout_representative_scan_blocks_production_accept(tmp_path: Path):
    closeout = _load_closeout_module()
    part = tmp_path / 'datamart' / 'trade_date=20200102'
    part.mkdir(parents=True)
    row = {column: 1 for column in OUTPUT_COLUMNS}
    row.update({
        'ts_code': '000001.SZ',
        'trade_date': '20200102',
        'qa_status': 'pass',
        'no_future_data': True,
        'no_future_intraday_minutes': True,
        'research_window': 'SMOKE',
    })
    pd.DataFrame([row]).drop(columns=['trade_date']).to_parquet(part / 'part.parquet', index=False)
    dates_file = tmp_path / 'dates.txt'
    dates_file.write_text('20200102\n', encoding='utf-8')
    qa_path = tmp_path / 'qa.json'
    catalog_path = tmp_path / 'catalog.json'
    smoke_path = tmp_path / 'read_smoke.json'
    closeout_path = tmp_path / 'closeout.json'

    exit_code = closeout.main([
        '--datamart-root',
        str(tmp_path / 'datamart'),
        '--expected-dates-file',
        str(dates_file),
        '--start',
        '20200102',
        '--end',
        '20200102',
        '--representative-dates',
        '20200102',
        '--scan-mode',
        'representative',
        '--qa-output',
        str(qa_path),
        '--catalog-output',
        str(catalog_path),
        '--read-smoke-output',
        str(smoke_path),
        '--closeout-output',
        str(closeout_path),
        '--research-window',
        'SMOKE',
    ])
    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    read_smoke = json.loads(smoke_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert read_smoke['verdict'] == 'ACCEPT'
    assert 'representative_scan_only_not_production_accept' in qa['issues']
