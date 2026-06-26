from __future__ import annotations

import json
import sys

import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.catalog import DataCatalog
from factor_factory.data_api.flow_distribution_moments import PREPARED_MINUTE_COLUMNS
from scripts import build_prepared_minute_bar
from scripts.run_prepared_cache_speed_proof import SourceNotReadyError, build_prepared_cache, main as speed_proof_main


def sample_raw_minute() -> pd.DataFrame:
    rows = []
    for ts_code in ['000001.SZ', '000002.SZ']:
        for trade_time, open_px, close_px, amount in [
            ('09:31:00', 10.0, 10.1, 100.0),
            ('10:00:00', 10.1, 10.1, 200.0),
            ('14:50:00', 10.1, 10.0, 300.0),
        ]:
            rows.append({
                'ts_code': ts_code,
                'trade_date': '20240104',
                'trade_time': trade_time,
                'open': open_px,
                'close': close_px,
                'vol': amount / 10.0,
                'amount': amount,
            })
    return pd.DataFrame(rows)


def test_prepared_minute_builder_writes_qa_and_loadable_catalog(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    raw_partition = minute_root / 'trade_date=20240104'
    raw_partition.mkdir(parents=True)
    sample_raw_minute().to_parquet(raw_partition / 'part.parquet', index=False)
    output_root = tmp_path / 'prepared_minute_bar_v1'
    qa_output = tmp_path / 'prepared_minute_bar_v1.qa.json'
    catalog_output = tmp_path / 'prepared_minute_bar_v1.catalog.json'

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'build_prepared_minute_bar.py',
            '--minute-root',
            str(minute_root),
            '--output-root',
            str(output_root),
            '--dates',
            '20240104',
            '--qa-output',
            str(qa_output),
            '--catalog-output',
            str(catalog_output),
        ],
    )

    assert build_prepared_minute_bar.main() == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed['verdict'] == 'ACCEPT'
    assert printed['qa_output'] == str(qa_output)
    assert printed['catalog_output'] == str(catalog_output)

    prepared = pd.read_parquet(output_root / 'trade_date=20240104')
    assert list(prepared.columns) == PREPARED_MINUTE_COLUMNS
    assert prepared.duplicated(['ts_code', 'trade_date', 'hhmmss']).sum() == 0

    qa = json.loads(qa_output.read_text(encoding='utf-8'))
    assert qa['verdict'] == 'ACCEPT'
    assert qa['dataset_id'] == 'prepared_minute_bar_v1'
    assert qa['source_dataset'] == 'minute_bar'
    assert qa['duplicate_key_count'] == 0
    assert qa['missing_dates'] == []
    assert qa['hard_checks']['duplicate_key_count_zero'] is True
    assert qa['hard_checks']['schema_columns_match'] is True

    catalog = DataCatalog.load(catalog_output)
    entry = catalog.datasets['prepared_minute_bar_v1']
    assert entry.uri == str(output_root)
    assert list(entry.columns) == PREPARED_MINUTE_COLUMNS
    assert list(entry.partition_columns) == ['trade_date']
    assert entry.metadata['unique_key'] == ['ts_code', 'trade_date', 'hhmmss']
    assert entry.metadata['source_dataset'] == 'minute_bar'
    assert entry.metadata['qa_summary_path'] == str(qa_output)

    result = DataApiClient.from_catalog(catalog_output).fetch(
        DataQuery(
            'prepared_minute_bar_v1',
            '20240104',
            '20240104',
            'a_share_all',
            ['ts_code', 'trade_date', 'hhmmss', 'amount_abs'],
        )
    )
    assert result.status == 'ready'
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.duplicated(['ts_code', 'trade_date', 'hhmmss']).sum() == 0


def test_prepared_minute_builder_supports_bounded_resume_manifest(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    for trade_date in ['20240104', '20240105']:
        raw_partition = minute_root / f'trade_date={trade_date}'
        raw_partition.mkdir(parents=True)
        frame = sample_raw_minute().assign(trade_date=trade_date)
        frame.to_parquet(raw_partition / 'part.parquet', index=False)
    output_root = tmp_path / 'prepared_minute_bar_v1'
    qa_output = tmp_path / 'prepared_minute_bar_v1.qa.json'
    catalog_output = tmp_path / 'prepared_minute_bar_v1.catalog.json'
    manifest_output = tmp_path / 'prepared_minute_bar_v1.manifest.json'

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'build_prepared_minute_bar.py',
            '--minute-root',
            str(minute_root),
            '--output-root',
            str(output_root),
            '--start',
            '20240104',
            '--end',
            '20240105',
            '--max-dates',
            '1',
            '--qa-output',
            str(qa_output),
            '--catalog-output',
            str(catalog_output),
            '--manifest-output',
            str(manifest_output),
        ],
    )
    assert build_prepared_minute_bar.main() == 0
    first = json.loads(capsys.readouterr().out)
    assert first['dates'] == ['20240104']
    assert first['remaining_dates'] == ['20240105']
    first_mtime = (output_root / 'trade_date=20240104' / 'part.parquet').stat().st_mtime_ns

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'build_prepared_minute_bar.py',
            '--minute-root',
            str(minute_root),
            '--output-root',
            str(output_root),
            '--start',
            '20240104',
            '--end',
            '20240105',
            '--skip-existing',
            '--qa-output',
            str(qa_output),
            '--catalog-output',
            str(catalog_output),
            '--manifest-output',
            str(manifest_output),
        ],
    )
    assert build_prepared_minute_bar.main() == 0

    second = json.loads(capsys.readouterr().out)
    manifest = json.loads(manifest_output.read_text(encoding='utf-8'))
    assert second['skipped_date_count'] == 1
    assert second['processed_dates'] == ['20240105']
    assert second['skipped_dates'] == ['20240104']
    assert (output_root / 'trade_date=20240104' / 'part.parquet').stat().st_mtime_ns == first_mtime
    assert (output_root / 'trade_date=20240105' / 'part.parquet').exists()
    assert manifest['verdict'] == 'ACCEPT'
    assert manifest['resume_policy']['skip_existing'] is True
    assert manifest['resume_policy']['max_dates'] is None
    assert manifest['processed_dates'] == ['20240105']
    assert manifest['skipped_dates'] == ['20240104']


def test_prepared_minute_builder_can_select_source_ready_dates_only(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    for trade_date in ['20240104', '20240106']:
        raw_partition = minute_root / f'trade_date={trade_date}'
        raw_partition.mkdir(parents=True)
        sample_raw_minute().assign(trade_date=trade_date).to_parquet(raw_partition / 'part.parquet', index=False)
    marker_partition = minute_root / 'trade_date=20240105'
    marker_partition.mkdir(parents=True)
    (marker_partition / 'part-000.parquet.missing').write_text('source unavailable', encoding='utf-8')
    output_root = tmp_path / 'prepared_minute_bar_v1'
    manifest_output = tmp_path / 'prepared_minute_bar_v1.manifest.json'

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'build_prepared_minute_bar.py',
            '--minute-root',
            str(minute_root),
            '--output-root',
            str(output_root),
            '--start',
            '20240104',
            '--end',
            '20240106',
            '--source-ready-only',
            '--manifest-output',
            str(manifest_output),
        ],
    )

    assert build_prepared_minute_bar.main() == 0

    summary = json.loads(capsys.readouterr().out)
    manifest = json.loads(manifest_output.read_text(encoding='utf-8'))
    assert summary['processed_dates'] == ['20240104', '20240106']
    assert summary['source_not_ready_dates'] == ['20240105']
    assert summary['missing_dates'] == []
    assert manifest['source_ready_policy']['enabled'] is True
    assert manifest['source_ready_policy']['not_ready_dates'] == ['20240105']
    assert (output_root / 'trade_date=20240104' / 'part.parquet').exists()
    assert not (output_root / 'trade_date=20240105' / 'part.parquet').exists()
    assert (output_root / 'trade_date=20240106' / 'part.parquet').exists()


def test_prepared_cache_speed_proof_builder_can_use_source_ready_dates_only(tmp_path):
    minute_root = tmp_path / 'minute_bar'
    for trade_date in ['20240104', '20240106']:
        raw_partition = minute_root / f'trade_date={trade_date}'
        raw_partition.mkdir(parents=True)
        sample_raw_minute().assign(trade_date=trade_date).to_parquet(raw_partition / 'part.parquet', index=False)
    marker_partition = minute_root / 'trade_date=20240105'
    marker_partition.mkdir(parents=True)
    (marker_partition / 'part-000.parquet.missing').write_text('source unavailable', encoding='utf-8')
    prepared_root = tmp_path / 'prepared_speed_proof'

    summary = build_prepared_cache(
        minute_root,
        prepared_root,
        '20240106',
        lookback_days=2,
        source_ready_only=True,
    )

    assert summary['prepared_cache_dates'] == ['20240104', '20240106']
    assert summary['prepared_cache_source_not_ready_dates'] == ['20240105']
    assert summary['prepared_cache_date_count'] == 2
    assert summary['prepared_cache_skipped_partitions'] == []
    assert (prepared_root / 'trade_date=20240104' / 'part.parquet').exists()
    assert not (prepared_root / 'trade_date=20240105' / 'part.parquet').exists()
    assert (prepared_root / 'trade_date=20240106' / 'part.parquet').exists()


def test_prepared_cache_speed_proof_blocks_when_target_date_is_not_source_ready(tmp_path):
    minute_root = tmp_path / 'minute_bar'
    raw_partition = minute_root / 'trade_date=20240104'
    raw_partition.mkdir(parents=True)
    sample_raw_minute().to_parquet(raw_partition / 'part.parquet', index=False)
    marker_partition = minute_root / 'trade_date=20240105'
    marker_partition.mkdir(parents=True)
    (marker_partition / 'part-000.parquet.missing').write_text('source unavailable', encoding='utf-8')
    prepared_root = tmp_path / 'prepared_speed_proof'

    with pytest.raises(SourceNotReadyError) as exc_info:
        build_prepared_cache(
            minute_root,
            prepared_root,
            '20240105',
            lookback_days=2,
            source_ready_only=True,
        )

    payload = exc_info.value.payload
    assert payload['verdict'] == 'BLOCK'
    assert payload['issues'] == ['target_date_not_source_ready']
    assert payload['date'] == '20240105'
    assert payload['prepared_cache_source_not_ready_dates'] == ['20240105']
    assert payload['prepared_cache_source_ready_policy']['enabled'] is True
    assert payload['prepared_cache_dates'] == []
    assert payload['prepared_cache_date_count'] == 0
    assert payload['prepared_cache_row_count'] == 0
    assert not prepared_root.exists()


def test_prepared_cache_speed_proof_main_writes_block_proof_for_not_source_ready_target(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    raw_partition = minute_root / 'trade_date=20240104'
    raw_partition.mkdir(parents=True)
    sample_raw_minute().to_parquet(raw_partition / 'part.parquet', index=False)
    marker_partition = minute_root / 'trade_date=20240105'
    marker_partition.mkdir(parents=True)
    (marker_partition / 'part-000.parquet.missing').write_text('source unavailable', encoding='utf-8')
    prepared_root = tmp_path / 'prepared_speed_proof'
    output_path = tmp_path / 'speed_proof.json'

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'run_prepared_cache_speed_proof.py',
            '--raw-minute-root',
            str(minute_root),
            '--prepared-root',
            str(prepared_root),
            '--date',
            '20240105',
            '--output-path',
            str(output_path),
            '--source-ready-only',
        ],
    )

    assert speed_proof_main() == 2

    printed = json.loads(capsys.readouterr().out)
    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert printed == payload
    assert payload['verdict'] == 'BLOCK'
    assert payload['issues'] == ['target_date_not_source_ready']
    assert payload['date'] == '20240105'
    assert payload['prepared_cache_root'] == str(prepared_root)
    assert payload['prepared_cache_size_bytes'] == 0
