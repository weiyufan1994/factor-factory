from __future__ import annotations

import json
import sys

import pandas as pd

from factor_factory.data_api.flow_distribution_moments import PREPARED_MINUTE_COLUMNS, prepare_minute_frame
from scripts import qa_prepared_minute_bar


def sample_raw_minute(trade_date: str) -> pd.DataFrame:
    rows = []
    for ts_code in ['000001.SZ', '000002.SZ']:
        for trade_time, open_px, close_px, amount in [
            ('09:31:00', 10.0, 10.1, 100.0),
            ('10:00:00', 10.1, 10.1, 200.0),
            ('14:50:00', 10.1, 10.0, 300.0),
        ]:
            rows.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'trade_time': trade_time,
                'open': open_px,
                'close': close_px,
                'vol': amount / 10.0,
                'amount': amount,
            })
    return pd.DataFrame(rows)


def write_partition(root, trade_date: str, frame: pd.DataFrame) -> None:
    partition = root / f'trade_date={trade_date}'
    partition.mkdir(parents=True)
    frame.to_parquet(partition / 'part.parquet', index=False)


def test_prepared_minute_qa_writes_catalog_and_data_api_read_smoke(tmp_path, monkeypatch, capsys):
    source_root = tmp_path / 'minute_bar'
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    for trade_date in ['20240104', '20240105']:
        raw = sample_raw_minute(trade_date)
        write_partition(source_root, trade_date, raw)
        prepared = prepare_minute_frame(raw)[PREPARED_MINUTE_COLUMNS]
        write_partition(prepared_root, trade_date, prepared)

    qa_output = tmp_path / 'prepared.qa.json'
    catalog_output = tmp_path / 'prepared.catalog.json'
    read_smoke_output = tmp_path / 'prepared.read_smoke.json'

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'qa_prepared_minute_bar.py',
            '--source-minute-root',
            str(source_root),
            '--prepared-root',
            str(prepared_root),
            '--start',
            '20240104',
            '--end',
            '20240105',
            '--qa-output',
            str(qa_output),
            '--catalog-output',
            str(catalog_output),
            '--read-smoke-output',
            str(read_smoke_output),
        ],
    )

    assert qa_prepared_minute_bar.main() == 0

    printed = json.loads(capsys.readouterr().out)
    qa = json.loads(qa_output.read_text(encoding='utf-8'))
    read_smoke = json.loads(read_smoke_output.read_text(encoding='utf-8'))
    assert printed['verdict'] == 'ACCEPT'
    assert qa['verdict'] == 'ACCEPT'
    assert qa['expected_dates'] == ['20240104', '20240105']
    assert qa['prepared_dates'] == ['20240104', '20240105']
    assert qa['missing_dates'] == []
    assert qa['duplicate_key_count'] == 0
    assert qa['hard_checks']['date_coverage_complete'] is True
    assert qa['hard_checks']['schema_columns_match'] is True
    assert read_smoke['verdict'] == 'ACCEPT'
    assert read_smoke['status'] == 'ready'
    assert read_smoke['coverage_duplicate_key_count'] == 0
    assert read_smoke['row_count'] == qa['row_count']


def test_prepared_minute_qa_can_use_source_ready_dates_only(tmp_path, monkeypatch, capsys):
    source_root = tmp_path / 'minute_bar'
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    for trade_date in ['20240104', '20240106']:
        raw = sample_raw_minute(trade_date)
        write_partition(source_root, trade_date, raw)
        write_partition(prepared_root, trade_date, prepare_minute_frame(raw)[PREPARED_MINUTE_COLUMNS])
    marker_partition = source_root / 'trade_date=20240105'
    marker_partition.mkdir(parents=True)
    (marker_partition / 'part-000.parquet.missing').write_text('source unavailable', encoding='utf-8')
    qa_output = tmp_path / 'prepared.qa.json'
    catalog_output = tmp_path / 'prepared.catalog.json'
    read_smoke_output = tmp_path / 'prepared.read_smoke.json'

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'qa_prepared_minute_bar.py',
            '--source-minute-root',
            str(source_root),
            '--prepared-root',
            str(prepared_root),
            '--start',
            '20240104',
            '--end',
            '20240106',
            '--source-ready-only',
            '--qa-output',
            str(qa_output),
            '--catalog-output',
            str(catalog_output),
            '--read-smoke-output',
            str(read_smoke_output),
        ],
    )

    assert qa_prepared_minute_bar.main() == 0

    printed = json.loads(capsys.readouterr().out)
    qa = json.loads(qa_output.read_text(encoding='utf-8'))
    read_smoke = json.loads(read_smoke_output.read_text(encoding='utf-8'))
    assert printed['verdict'] == 'ACCEPT'
    assert qa['expected_dates'] == ['20240104', '20240106']
    assert qa['source_not_ready_dates'] == ['20240105']
    assert qa['prepared_dates'] == ['20240104', '20240106']
    assert qa['missing_dates'] == []
    assert qa['hard_checks']['date_coverage_complete'] is True
    assert read_smoke['verdict'] == 'ACCEPT'
    assert read_smoke['expected_dates'] == ['20240104', '20240106']
    assert read_smoke['source_not_ready_dates'] == ['20240105']
    assert read_smoke['observed_dates'] == ['20240104', '20240106']
    assert read_smoke['missing_ready_dates'] == []
    assert read_smoke['unexpected_dates'] == []
