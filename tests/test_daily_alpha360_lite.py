from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.daily_alpha360_lite import (
    DailyAlpha360LiteParams,
    build_daily_alpha360_lite,
    build_daily_alpha360_lite_qa,
)


def _daily_sample() -> pd.DataFrame:
    rows = []
    for ts_code, base in [('000001.SZ', 10.0), ('000002.SZ', 20.0)]:
        for idx, trade_date in enumerate(['20240102', '20240103', '20240104']):
            close = base + idx
            rows.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'open': close - 0.2,
                'high': close + 0.5,
                'low': close - 0.5,
                'close': close,
                'vol': 1000.0 + 100.0 * idx,
                'amount': (close + 0.1) * (1000.0 + 100.0 * idx),
            })
    return pd.DataFrame(rows)


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_daily_alpha360_lite.py'
    spec = importlib.util.spec_from_file_location('build_daily_alpha360_lite', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_daily_alpha360_lite.py'
    spec = importlib.util.spec_from_file_location('validate_daily_alpha360_lite', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_alpha360_lite_builds_qlib_style_lag_features():
    params = DailyAlpha360LiteParams(lookback=3)
    result = build_daily_alpha360_lite(_daily_sample(), params=params)

    row = result[(result['ts_code'] == '000001.SZ') & (result['trade_date'] == '20240104')].iloc[0]
    assert row['CLOSE0'] == pytest.approx(1.0)
    assert row['CLOSE1'] == pytest.approx(11.0 / 12.0)
    assert row['OPEN2'] == pytest.approx(9.8 / 12.0)
    assert row['HIGH0'] == pytest.approx(12.5 / 12.0)
    assert row['LOW2'] == pytest.approx(9.5 / 12.0)
    assert row['VWAP0'] == pytest.approx(12.1 / 12.0)
    assert row['VOLUME1'] == pytest.approx(1100.0 / 1200.0)
    first = result[(result['ts_code'] == '000001.SZ') & (result['trade_date'] == '20240102')].iloc[0]
    assert pd.isna(first['CLOSE1'])
    assert pd.isna(first['VOLUME2'])


def test_daily_alpha360_lite_uses_no_future_rows():
    params = DailyAlpha360LiteParams(lookback=3)
    source = _daily_sample()
    baseline = build_daily_alpha360_lite(source, params=params)
    changed_future = source.copy()
    mask = (changed_future['ts_code'] == '000001.SZ') & (changed_future['trade_date'] == '20240104')
    changed_future.loc[mask, ['open', 'high', 'low', 'close', 'vol', 'amount']] = [99.0, 101.0, 98.0, 100.0, 9999.0, 999900.0]
    changed = build_daily_alpha360_lite(changed_future, params=params)

    cols = [column for column in baseline.columns if column not in {'ts_code', 'trade_date'}]
    before_future_baseline = baseline[(baseline['ts_code'] == '000001.SZ') & (baseline['trade_date'] == '20240103')][cols].reset_index(drop=True)
    before_future_changed = changed[(changed['ts_code'] == '000001.SZ') & (changed['trade_date'] == '20240103')][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(before_future_baseline, before_future_changed)


def test_daily_alpha360_lite_qa_reports_expected_contract():
    params = DailyAlpha360LiteParams(lookback=2)
    result = build_daily_alpha360_lite(_daily_sample(), params=params)
    qa = build_daily_alpha360_lite_qa(result, params=params)

    assert qa['verdict'] == 'ACCEPT'
    assert qa['dataset_id'] == 'daily_alpha360_lite_v1'
    assert qa['unique_key'] == ['ts_code', 'trade_date']
    assert qa['row_count'] == 6
    assert qa['date_count'] == 3
    assert qa['ticker_count'] == 2
    assert qa['feature_count'] == 12
    assert qa['expected_feature_count'] == 12
    assert qa['duplicate_key_count'] == 0
    assert qa['information_set_legality']['uses_future_rows'] is False


def test_daily_alpha360_lite_qa_blocks_duplicate_keys():
    params = DailyAlpha360LiteParams(lookback=1)
    result = build_daily_alpha360_lite(pd.concat([_daily_sample(), _daily_sample().head(1)], ignore_index=True), params=params)
    qa = build_daily_alpha360_lite_qa(result, params=params)

    assert qa['verdict'] == 'BLOCK'
    assert 'duplicate_key_count_nonzero' in qa['issues']


def test_build_daily_alpha360_lite_script_writes_parquet_and_qa(tmp_path):
    pytest.importorskip('pyarrow')
    script = _load_script_module()
    input_path = tmp_path / 'daily.parquet'
    output_path = tmp_path / 'daily_alpha360_lite.parquet'
    qa_path = tmp_path / 'daily_alpha360_lite.qa.json'
    _daily_sample().to_parquet(input_path, index=False)

    exit_code = script.main([
        '--input-parquet',
        str(input_path),
        '--output-parquet',
        str(output_path),
        '--qa-output',
        str(qa_path),
        '--lookback',
        '3',
    ])

    payload = json.loads(qa_path.read_text(encoding='utf-8'))
    written = pd.read_parquet(output_path)
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['safety']['writes_catalog'] is False
    assert payload['safety']['writes_datamart'] is False
    assert len(written) == 6
    assert 'CLOSE2' in written.columns
    assert 'VOLUME2' in written.columns


def test_build_daily_alpha360_lite_script_supports_bounded_output_with_lookback_buffer(tmp_path):
    pytest.importorskip('pyarrow')
    script = _load_script_module()
    input_path = tmp_path / 'daily.parquet'
    output_path = tmp_path / 'daily_alpha360_lite.parquet'
    qa_path = tmp_path / 'daily_alpha360_lite.qa.json'
    _daily_sample().to_parquet(input_path, index=False)

    exit_code = script.main([
        '--input-parquet',
        str(input_path),
        '--output-parquet',
        str(output_path),
        '--qa-output',
        str(qa_path),
        '--lookback',
        '3',
        '--start',
        '20240104',
        '--end',
        '20240104',
    ])

    written = pd.read_parquet(output_path)
    assert exit_code == 0
    assert written['trade_date'].unique().tolist() == ['20240104']
    assert len(written) == 2
    row = written[written['ts_code'] == '000001.SZ'].iloc[0]
    assert row['CLOSE2'] == pytest.approx(10.0 / 12.0)


def test_build_daily_alpha360_lite_script_writes_partitioned_output(tmp_path):
    pytest.importorskip('pyarrow')
    script = _load_script_module()
    input_path = tmp_path / 'daily.parquet'
    output_root = tmp_path / 'daily_alpha360_lite_v1'
    qa_path = tmp_path / 'daily_alpha360_lite.qa.json'
    _daily_sample().to_parquet(input_path, index=False)

    exit_code = script.main([
        '--input-parquet',
        str(input_path),
        '--output-root',
        str(output_root),
        '--partitioned',
        '--qa-output',
        str(qa_path),
        '--lookback',
        '2',
    ])

    payload = json.loads(qa_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['output_root'] == str(output_root)
    assert payload['partition_column'] == 'trade_date'
    assert payload['partition_count'] == 3
    assert (output_root / 'trade_date=20240102' / 'part.parquet').exists()
    assert (output_root / 'trade_date=20240104' / 'part.parquet').exists()


def test_build_daily_alpha360_lite_script_supports_resumable_partitioned_batches(tmp_path):
    pytest.importorskip('pyarrow')
    script = _load_script_module()
    input_path = tmp_path / 'daily.parquet'
    output_root = tmp_path / 'daily_alpha360_lite_v1'
    batch1_qa = tmp_path / 'batch1.qa.json'
    batch1_manifest = tmp_path / 'batch1.manifest.json'
    batch2_qa = tmp_path / 'batch2.qa.json'
    batch2_manifest = tmp_path / 'batch2.manifest.json'
    _daily_sample().to_parquet(input_path, index=False)

    assert script.main([
        '--input-parquet',
        str(input_path),
        '--output-root',
        str(output_root),
        '--partitioned',
        '--overwrite',
        '--qa-output',
        str(batch1_qa),
        '--manifest-output',
        str(batch1_manifest),
        '--lookback',
        '2',
        '--start',
        '20240102',
        '--end',
        '20240104',
        '--max-dates',
        '1',
    ]) == 0
    assert script.main([
        '--input-parquet',
        str(input_path),
        '--output-root',
        str(output_root),
        '--partitioned',
        '--skip-existing',
        '--qa-output',
        str(batch2_qa),
        '--manifest-output',
        str(batch2_manifest),
        '--lookback',
        '2',
        '--start',
        '20240102',
        '--end',
        '20240104',
    ]) == 0

    manifest1 = json.loads(batch1_manifest.read_text(encoding='utf-8'))
    manifest2 = json.loads(batch2_manifest.read_text(encoding='utf-8'))
    assert manifest1['processed_dates'] == ['20240102']
    assert manifest1['remaining_dates'] == ['20240103', '20240104']
    assert manifest2['skipped_dates'] == ['20240102']
    assert manifest2['processed_dates'] == ['20240103', '20240104']
    assert (output_root / 'trade_date=20240102' / 'part.parquet').exists()
    assert (output_root / 'trade_date=20240103' / 'part.parquet').exists()
    assert (output_root / 'trade_date=20240104' / 'part.parquet').exists()


def test_validate_daily_alpha360_lite_accepts_feature_parquet_and_warm_read(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_script_module()
    validator = _load_validator_module()
    input_path = tmp_path / 'daily.parquet'
    output_path = tmp_path / 'daily_alpha360_lite.parquet'
    qa_path = tmp_path / 'daily_alpha360_lite.qa.json'
    validation_path = tmp_path / 'daily_alpha360_lite.validation.json'
    _daily_sample().to_parquet(input_path, index=False)
    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-parquet', str(output_path),
        '--qa-output', str(qa_path),
        '--lookback', '3',
    ]) == 0

    exit_code = validator.main([
        '--feature-parquet', str(output_path),
        '--qa-path', str(qa_path),
        '--output-path', str(validation_path),
        '--lookback', '3',
        '--min-row-count', '6',
        '--max-warm-read-seconds', '10',
    ])

    payload = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['warm_read_seconds'] >= 0.0
    assert payload['catalog_candidate']['dataset_id'] == 'daily_alpha360_lite_v1'
    assert payload['catalog_candidate']['metadata']['unique_key'] == ['ts_code', 'trade_date']
    assert payload['safety']['writes_catalog'] is False
    assert payload['safety']['writes_datamart'] is False


def test_validate_daily_alpha360_lite_accepts_partitioned_output_and_data_api_projection(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_script_module()
    validator = _load_validator_module()
    input_path = tmp_path / 'daily.parquet'
    output_root = tmp_path / 'daily_alpha360_lite_v1'
    qa_path = tmp_path / 'daily_alpha360_lite.qa.json'
    validation_path = tmp_path / 'daily_alpha360_lite.validation.json'
    catalog_path = tmp_path / 'daily_alpha360_lite.catalog.json'
    _daily_sample().to_parquet(input_path, index=False)
    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-root', str(output_root),
        '--partitioned',
        '--qa-output', str(qa_path),
        '--lookback', '2',
    ]) == 0

    exit_code = validator.main([
        '--feature-parquet', str(output_root),
        '--qa-path', str(qa_path),
        '--output-path', str(validation_path),
        '--lookback', '2',
        '--min-row-count', '6',
    ])

    payload = json.loads(validation_path.read_text(encoding='utf-8'))
    catalog_path.write_text(json.dumps({
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            'daily_alpha360_lite_v1': payload['catalog_candidate'],
        },
    }), encoding='utf-8')
    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(
            'daily_alpha360_lite_v1',
            '20240104',
            '20240104',
            'a_share_all',
            ['CLOSE0', 'VOLUME1'],
        )
    )

    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['catalog_candidate']['partition_columns'] == ['trade_date']
    assert result.status == 'ready'
    assert result.coverage.row_count == 2
    assert result.coverage.date_count == 1
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == ['ts_code', 'trade_date', 'CLOSE0', 'VOLUME1']


def test_validate_daily_alpha360_lite_blocks_source_qa_mismatch(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_script_module()
    validator = _load_validator_module()
    input_path = tmp_path / 'daily.parquet'
    output_path = tmp_path / 'daily_alpha360_lite.parquet'
    qa_path = tmp_path / 'daily_alpha360_lite.qa.json'
    validation_path = tmp_path / 'daily_alpha360_lite.validation.json'
    _daily_sample().to_parquet(input_path, index=False)
    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-parquet', str(output_path),
        '--qa-output', str(qa_path),
        '--lookback', '2',
    ]) == 0
    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    qa['row_count'] = 999
    qa_path.write_text(json.dumps(qa), encoding='utf-8')

    exit_code = validator.main([
        '--feature-parquet', str(output_path),
        '--qa-path', str(qa_path),
        '--output-path', str(validation_path),
        '--lookback', '2',
    ])

    payload = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'source_qa_mismatch:row_count' in payload['issues']


def test_validate_daily_alpha360_lite_blocks_missing_feature_column(tmp_path):
    pytest.importorskip('pyarrow')
    validator = _load_validator_module()
    params = DailyAlpha360LiteParams(lookback=2)
    frame = build_daily_alpha360_lite(_daily_sample(), params=params).drop(columns=['CLOSE1'])
    feature_path = tmp_path / 'daily_alpha360_lite.parquet'
    validation_path = tmp_path / 'daily_alpha360_lite.validation.json'
    frame.to_parquet(feature_path, index=False)

    exit_code = validator.main([
        '--feature-parquet', str(feature_path),
        '--output-path', str(validation_path),
        '--lookback', '2',
    ])

    payload = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'missing_expected_columns' in payload['issues']
    assert 'CLOSE1' in payload['missing_columns']
