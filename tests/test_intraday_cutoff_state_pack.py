from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.intraday_cutoff_state_pack import (
    DATASET_ID,
    IntradayCutoffStateParams,
    build_qa_summary,
    derive_intraday_cutoff_state_pack,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_builder_module():
    path = REPO_ROOT / 'scripts' / 'build_intraday_cutoff_state_pack.py'
    spec = importlib.util.spec_from_file_location('build_intraday_cutoff_state_pack', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator_module():
    path = REPO_ROOT / 'scripts' / 'validate_intraday_cutoff_state_pack.py'
    spec = importlib.util.spec_from_file_location('validate_intraday_cutoff_state_pack', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_minute_frame() -> pd.DataFrame:
    rows = []
    for trade_date in ['20240102', '20240103']:
        for ts_code, base in [('000001.SZ', 10.0), ('000002.SZ', 20.0)]:
            for idx, minute in enumerate(['09:31:00', '09:32:00', '09:33:00', '09:34:00', '09:35:00', '14:56:00']):
                open_px = base + idx * 0.1
                close = open_px + (0.05 if idx % 2 == 0 else -0.03)
                high = max(open_px, close) + 0.02
                low = min(open_px, close) - 0.02
                vol = 1000.0 + idx * 100.0
                rows.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'trade_time': minute,
                    'open': open_px,
                    'high': high,
                    'low': low,
                    'close': close,
                    'vol': vol,
                    'amount': close * vol,
                })
    return pd.DataFrame(rows)


def test_intraday_cutoff_state_pack_uses_cutoff_minutes_only():
    params = IntradayCutoffStateParams(cutoff_times=('09:33:00', '09:35:00'), min_minutes=2, terminal_window_minutes=2, research_window='SMOKE')

    out = derive_intraday_cutoff_state_pack(sample_minute_frame(), params=params, target_dates=['20240103'])

    assert DATASET_ID == 'intraday_cutoff_state_pack_v1'
    assert set(out['cutoff_time']) == {'09:33:00', '09:35:00'}
    assert out.duplicated(['ts_code', 'trade_date', 'cutoff_time']).sum() == 0
    row_933 = out[(out['ts_code'] == '000001.SZ') & (out['cutoff_time'] == '09:33:00')].iloc[0]
    row_935 = out[(out['ts_code'] == '000001.SZ') & (out['cutoff_time'] == '09:35:00')].iloc[0]
    assert row_933['minute_count'] == 3
    assert row_935['minute_count'] == 5
    assert row_933['last_trade_time'] == '09:33:00'
    assert row_933['amount_sum'] < row_935['amount_sum']
    assert row_933['terminal_window_minutes'] == 2
    assert row_933['no_future_intraday_minutes'] is True
    assert row_933['research_window'] == 'SMOKE'


def test_intraday_cutoff_state_pack_future_mutation_does_not_change_prior_cutoff():
    params = IntradayCutoffStateParams(cutoff_times=('09:35:00',), min_minutes=2, terminal_window_minutes=2)
    source = sample_minute_frame()
    baseline = derive_intraday_cutoff_state_pack(source, params=params, target_dates=['20240103'])
    changed = source.copy()
    future_mask = changed['trade_time'].eq('14:56:00') & changed['ts_code'].eq('000001.SZ')
    changed.loc[future_mask, ['open', 'high', 'low', 'close', 'vol', 'amount']] = [99.0, 100.0, 98.0, 99.5, 999999.0, 99999999.0]
    mutated = derive_intraday_cutoff_state_pack(changed, params=params, target_dates=['20240103'])

    cols = [col for col in baseline.columns if col not in {'schema_version', 'producer_version'}]
    base_row = baseline[baseline['ts_code'].eq('000001.SZ')][cols].reset_index(drop=True)
    changed_row = mutated[mutated['ts_code'].eq('000001.SZ')][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(base_row, changed_row)


def test_intraday_cutoff_state_pack_qa_contract_accepts_nonempty_output():
    params = IntradayCutoffStateParams(cutoff_times=('09:35:00',), min_minutes=2)
    out = derive_intraday_cutoff_state_pack(sample_minute_frame(), params=params, target_dates=['20240103'])

    qa = build_qa_summary(out, params=params, missing_dates=[], input_minute_row_count=len(sample_minute_frame()))

    assert qa['verdict'] == 'ACCEPT'
    assert qa['dataset_id'] == 'intraday_cutoff_state_pack_v1'
    assert qa['duplicate_key_count'] == 0
    assert qa['information_set_legality']['no_future_intraday_minutes'] is True
    assert qa['information_set_legality']['uses_full_day_denominator'] is False


def test_intraday_cutoff_state_builder_validate_and_data_api_read_smoke(tmp_path: Path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    validator = _load_validator_module()
    minute_root = tmp_path / 'minute'
    output_root = tmp_path / 'cutoff_state'
    qa_path = tmp_path / 'cutoff.qa.json'
    catalog_path = tmp_path / 'cutoff.catalog.json'
    validation_path = tmp_path / 'cutoff.validation.json'
    manifest_path = tmp_path / 'cutoff.manifest.json'
    frame = sample_minute_frame()
    for trade_date, part in frame.groupby('trade_date'):
        part_dir = minute_root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True)
        part.to_parquet(part_dir / 'part.parquet', index=False)

    assert builder.main([
        '--minute-root', str(minute_root),
        '--start', '20240102',
        '--end', '20240103',
        '--output-root', str(output_root),
        '--qa-output', str(qa_path),
        '--catalog-output', str(catalog_path),
        '--cutoff-times', '09:35:00',
        '--min-minutes', '2',
        '--terminal-window-minutes', '2',
        '--research-window', 'SMOKE',
        '--max-dates', '1',
        '--manifest-output', str(manifest_path),
    ]) == 0
    first_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert first_manifest['processed_dates'] == ['20240102']
    assert first_manifest['remaining_dates'] == ['20240103']

    assert builder.main([
        '--minute-root', str(minute_root),
        '--start', '20240102',
        '--end', '20240103',
        '--output-root', str(output_root),
        '--qa-output', str(qa_path),
        '--catalog-output', str(catalog_path),
        '--cutoff-times', '09:35:00',
        '--min-minutes', '2',
        '--terminal-window-minutes', '2',
        '--research-window', 'SMOKE',
        '--skip-existing',
        '--manifest-output', str(manifest_path),
    ]) == 0
    assert validator.main([
        '--feature-parquet', str(output_root),
        '--qa-path', str(qa_path),
        '--output-path', str(validation_path),
        '--min-row-count', '4',
    ]) == 0

    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(
            'intraday_cutoff_state_pack_v1',
            '20240103',
            '20240103',
            'a_share_all',
            ['cutoff_ret', 'terminal_ret_20m', 'amount_sum'],
            frequency='intraday_cutoff',
        )
    )
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    assert validation['verdict'] == 'ACCEPT'
    assert catalog['datasets']['intraday_cutoff_state_pack_v1']['metadata']['supported_cutoff_times'] == ['09:35:00']
    assert catalog['datasets']['intraday_cutoff_state_pack_v1']['metadata']['research_window'] == 'SMOKE'
    assert result.status == 'ready'
    assert result.coverage.row_count == 2
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == ['ts_code', 'trade_date', 'cutoff_time', 'cutoff_ret', 'terminal_ret_20m', 'amount_sum']


def test_intraday_cutoff_state_builder_ignores_stale_partition_temp_files(tmp_path: Path):
    pytest.importorskip('pyarrow')
    builder = _load_builder_module()
    minute_root = tmp_path / 'minute'
    output_root = tmp_path / 'cutoff_state'
    qa_path = tmp_path / 'cutoff.qa.json'
    catalog_path = tmp_path / 'cutoff.catalog.json'
    part_dir = minute_root / 'trade_date=20240103'
    part_dir.mkdir(parents=True)
    sample_minute_frame().query("trade_date == '20240103'").to_parquet(part_dir / 'part-000.parquet', index=False)
    (part_dir / 'part-000.parquet.9AfeF8e6').write_text('stale partial file', encoding='utf-8')

    exit_code = builder.main([
        '--minute-root', str(minute_root),
        '--dates', '20240103',
        '--start', '20240103',
        '--end', '20240103',
        '--output-root', str(output_root),
        '--qa-output', str(qa_path),
        '--catalog-output', str(catalog_path),
        '--cutoff-times', '09:35:00',
        '--min-minutes', '2',
    ])

    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert qa['verdict'] == 'ACCEPT'
    assert qa['source_profile'][0]['files'] == [str(part_dir / 'part-000.parquet')]


def test_intraday_cutoff_state_validator_blocks_duplicate_keys(tmp_path: Path):
    pytest.importorskip('pyarrow')
    validator = _load_validator_module()
    output = tmp_path / 'cutoff_state.parquet'
    validation_path = tmp_path / 'validation.json'
    out = derive_intraday_cutoff_state_pack(
        sample_minute_frame(),
        params=IntradayCutoffStateParams(cutoff_times=('09:35:00',), min_minutes=2),
        target_dates=['20240103'],
    )
    duplicated = pd.concat([out, out.iloc[[0]]], ignore_index=True)
    duplicated.to_parquet(output, index=False)

    exit_code = validator.main([
        '--feature-parquet', str(output),
        '--output-path', str(validation_path),
    ])

    payload = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'duplicate_key_count_nonzero' in payload['issues']
