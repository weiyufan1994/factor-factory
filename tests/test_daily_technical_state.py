from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.daily_technical_state import (
    DailyTechnicalStateParams,
    build_daily_technical_state,
    build_daily_technical_state_qa,
)


def _daily_sample(days: int = 25) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range('2024-01-02', periods=days).strftime('%Y%m%d').tolist()
    for ts_code, base in [('000001.SZ', 10.0), ('000002.SZ', 20.0)]:
        for idx, trade_date in enumerate(dates):
            close = base + idx * 0.2
            volume = 1000.0 + idx * 10.0
            rows.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'open': close - 0.1,
                'high': close + 0.3,
                'low': close - 0.4,
                'close': close,
                'vol': volume,
                'amount': (close + 0.05) * volume,
            })
    return pd.DataFrame(rows)


def _load_builder_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_daily_technical_state.py'
    spec = importlib.util.spec_from_file_location('build_daily_technical_state', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_daily_technical_state.py'
    spec = importlib.util.spec_from_file_location('validate_daily_technical_state', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_technical_state_builds_reusable_fields():
    result = build_daily_technical_state(_daily_sample(days=25), params=DailyTechnicalStateParams())
    row = result[(result['ts_code'] == '000001.SZ') & (result['trade_date'] == '20240109')].iloc[0]

    assert row['ret_1d'] == pytest.approx(11.0 / 10.8 - 1.0)
    assert row['ret_5d'] == pytest.approx(11.0 / 10.0 - 1.0)
    assert row['range_pct'] == pytest.approx(0.7 / 11.0)
    assert row['open_close_ret'] == pytest.approx(11.0 / 10.9 - 1.0)
    assert row['vwap_close_spread'] == pytest.approx(11.05 / 11.0 - 1.0)
    assert row['volume_ratio_20d'] > 0.0
    assert row['amount_mean_20d'] > 0.0


def test_daily_technical_state_uses_no_future_rows():
    source = _daily_sample(days=25)
    baseline = build_daily_technical_state(source)
    changed_future = source.copy()
    mask = (changed_future['ts_code'] == '000001.SZ') & (changed_future['trade_date'] == source['trade_date'].max())
    changed_future.loc[mask, ['open', 'high', 'low', 'close', 'vol', 'amount']] = [99.0, 101.0, 98.0, 100.0, 9999.0, 999900.0]
    changed = build_daily_technical_state(changed_future)

    cols = [column for column in baseline.columns if column not in {'ts_code', 'trade_date'}]
    target_date = source[source['trade_date'] < source['trade_date'].max()]['trade_date'].max()
    base_row = baseline[(baseline['ts_code'] == '000001.SZ') & (baseline['trade_date'] == target_date)][cols].reset_index(drop=True)
    changed_row = changed[(changed['ts_code'] == '000001.SZ') & (changed['trade_date'] == target_date)][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(base_row, changed_row)


def test_daily_technical_state_qa_contract():
    result = build_daily_technical_state(_daily_sample(days=25))
    qa = build_daily_technical_state_qa(result)

    assert qa['verdict'] == 'ACCEPT'
    assert qa['dataset_id'] == 'daily_technical_state_v1'
    assert qa['feature_count'] == qa['expected_feature_count']
    assert qa['duplicate_key_count'] == 0
    assert qa['information_set_legality']['uses_future_rows'] is False


def test_daily_technical_state_partitioned_build_validate_and_data_api_projection(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    validator = _load_validator_module()
    input_path = tmp_path / 'daily.parquet'
    output_root = tmp_path / 'daily_technical_state_v1'
    qa_path = tmp_path / 'daily_technical_state.qa.json'
    validation_path = tmp_path / 'daily_technical_state.validation.json'
    catalog_path = tmp_path / 'daily_technical_state.catalog.json'
    _daily_sample(days=25).to_parquet(input_path, index=False)

    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-root', str(output_root),
        '--partitioned',
        '--qa-output', str(qa_path),
        '--start', '20240109',
        '--end', '20240112',
    ]) == 0
    assert validator.main([
        '--feature-parquet', str(output_root),
        '--qa-path', str(qa_path),
        '--output-path', str(validation_path),
        '--min-row-count', '8',
    ]) == 0

    payload = json.loads(validation_path.read_text(encoding='utf-8'))
    catalog_path.write_text(json.dumps({
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {'daily_technical_state_v1': payload['catalog_candidate']},
    }), encoding='utf-8')
    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery('daily_technical_state_v1', '20240110', '20240110', 'a_share_all', ['ret_1d', 'volatility_20d'])
    )

    assert payload['verdict'] == 'ACCEPT'
    assert payload['catalog_candidate']['partition_columns'] == ['trade_date']
    assert result.status == 'ready'
    assert result.coverage.row_count == 2
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == ['ts_code', 'trade_date', 'ret_1d', 'volatility_20d']


def test_daily_technical_state_partitioned_build_supports_resume_manifest(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    input_path = tmp_path / 'daily.parquet'
    output_root = tmp_path / 'daily_technical_state_v1'
    qa_path = tmp_path / 'daily_technical_state.qa.json'
    manifest_path = tmp_path / 'daily_technical_state.manifest.json'
    _daily_sample(days=25).to_parquet(input_path, index=False)

    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-root', str(output_root),
        '--partitioned',
        '--qa-output', str(qa_path),
        '--manifest-output', str(manifest_path),
        '--start', '20240109',
        '--end', '20240111',
        '--max-dates', '1',
    ]) == 0
    first_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    first_partition = output_root / 'trade_date=20240109' / 'part.parquet'
    first_mtime = first_partition.stat().st_mtime_ns
    assert first_manifest['processed_dates'] == ['20240109']
    assert first_manifest['remaining_dates'] == ['20240110', '20240111']

    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-root', str(output_root),
        '--partitioned',
        '--skip-existing',
        '--qa-output', str(qa_path),
        '--manifest-output', str(manifest_path),
        '--start', '20240109',
        '--end', '20240111',
    ]) == 0
    second_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert first_partition.stat().st_mtime_ns == first_mtime
    assert second_manifest['skipped_dates'] == ['20240109']
    assert second_manifest['processed_dates'] == ['20240110', '20240111']
    assert second_manifest['remaining_dates'] == []
    assert (output_root / 'trade_date=20240110' / 'part.parquet').exists()
    assert (output_root / 'trade_date=20240111' / 'part.parquet').exists()


def test_validate_daily_technical_state_blocks_missing_feature(tmp_path):
    pytest.importorskip('pyarrow')
    validator = _load_validator_module()
    feature_path = tmp_path / 'daily_technical_state.parquet'
    validation_path = tmp_path / 'daily_technical_state.validation.json'
    frame = build_daily_technical_state(_daily_sample(days=25)).drop(columns=['ret_20d'])
    frame.to_parquet(feature_path, index=False)

    exit_code = validator.main([
        '--feature-parquet', str(feature_path),
        '--output-path', str(validation_path),
    ])

    payload = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'missing_expected_columns' in payload['issues']
    assert 'ret_20d' in payload['missing_columns']


def test_validate_daily_technical_state_allows_partial_resume_qa_when_explicit(tmp_path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    validator = _load_validator_module()
    input_path = tmp_path / 'daily.parquet'
    output_root = tmp_path / 'daily_technical_state_v1'
    qa_path = tmp_path / 'daily_technical_state.qa.json'
    validation_path = tmp_path / 'daily_technical_state.validation.json'
    _daily_sample(days=25).to_parquet(input_path, index=False)
    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-root', str(output_root),
        '--partitioned',
        '--qa-output', str(qa_path),
        '--start', '20240109',
        '--end', '20240111',
        '--max-dates', '1',
    ]) == 0
    assert builder.main([
        '--input-parquet', str(input_path),
        '--output-root', str(output_root),
        '--partitioned',
        '--skip-existing',
        '--qa-output', str(qa_path),
        '--start', '20240109',
        '--end', '20240111',
    ]) == 0

    strict_exit = validator.main([
        '--feature-parquet', str(output_root),
        '--qa-path', str(qa_path),
        '--output-path', str(validation_path),
        '--min-row-count', '6',
    ])
    strict_payload = json.loads(validation_path.read_text(encoding='utf-8'))
    assert strict_exit == 1
    assert 'source_qa_mismatch:row_count' in strict_payload['issues']

    relaxed_exit = validator.main([
        '--feature-parquet', str(output_root),
        '--qa-path', str(qa_path),
        '--output-path', str(validation_path),
        '--min-row-count', '6',
        '--allow-partial-source-qa',
    ])
    relaxed_payload = json.loads(validation_path.read_text(encoding='utf-8'))
    assert relaxed_exit == 0
    assert relaxed_payload['verdict'] == 'ACCEPT'
    assert relaxed_payload['allow_partial_source_qa'] is True
