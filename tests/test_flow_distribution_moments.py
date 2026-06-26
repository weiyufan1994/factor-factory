from __future__ import annotations

import json

import pandas as pd
import pytest

import scripts.run_flow_distribution_moments_parity_smoke as parity_smoke
from scripts import compare_flow_distribution_operator_profiles
from scripts import profile_flow_distribution_moments_operator
from scripts import validate_flow_distribution_operator_comparison
from factor_factory.data_api.flow_distribution_moments import (
    DATASET_ID,
    FlowDistributionParams,
    _build_threshold_frame,
    build_catalog_entry,
    build_qa_summary,
    derive_intraday_flow_distribution_moments,
    derive_intraday_flow_distribution_moments_from_prepared,
    derive_intraday_flow_distribution_moments_numba_sorted_prepared,
    prepare_minute_frame,
)
from scripts.build_intraday_flow_distribution_moments import read_minute_root
from scripts.build_intraday_flow_distribution_moments import main as build_flow_distribution_main
from scripts.build_intraday_flow_distribution_moments import write_catalog
from scripts.run_flow_distribution_moments_parity_smoke import main as parity_smoke_main


def sample_minute_frame() -> pd.DataFrame:
    rows = []
    for trade_date, scale in [('20240102', 1.0), ('20240103', 1.2), ('20240104', 1.4)]:
        for ts_code in ['000001.SZ', '000002.SZ']:
            for minute, amount, direction in [
                ('09:31:00', 100.0 * scale, 1.0),
                ('10:00:00', 200.0 * scale, 0.0),
                ('10:31:00', 400.0 * scale, -1.0),
                ('14:50:00', 800.0 * scale, 1.0),
                ('14:56:00', 1600.0 * scale, -1.0),
            ]:
                open_px = 10.0
                close_px = open_px * (1.0 + (direction * amount / 100000.0))
                rows.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'trade_time': minute,
                    'open': open_px,
                    'close': close_px,
                    'high': max(open_px, close_px),
                    'low': min(open_px, close_px),
                    'vol': amount / 10.0,
                    'amount': amount,
                })
    return pd.DataFrame(rows)


def has_numba() -> bool:
    try:
        import numba  # noqa: F401
    except Exception:
        return False
    return True


def test_distribution_moments_use_cutoff_minutes_only_and_emit_unique_keys():
    params = FlowDistributionParams(cutoff_times=('10:30:00', '14:50:00'), min_minutes=2, threshold_lookback_days=(2,))

    out = derive_intraday_flow_distribution_moments(sample_minute_frame(), params, target_dates=['20240104'])

    assert DATASET_ID == 'intraday_flow_distribution_moments_v1'
    assert set(out['cutoff_time']) == {'10:30:00', '14:50:00'}
    assert out.duplicated(['ts_code', 'trade_date', 'cutoff_time']).sum() == 0
    row_1030 = out[(out['ts_code'] == '000001.SZ') & (out['cutoff_time'] == '10:30:00')].iloc[0]
    row_1450 = out[(out['ts_code'] == '000001.SZ') & (out['cutoff_time'] == '14:50:00')].iloc[0]
    assert row_1030['minute_count'] == 2
    assert row_1450['minute_count'] == 4
    assert row_1030['amount_sum'] < row_1450['amount_sum']
    assert row_1450['no_future_intraday_minutes'] is True


def test_large_small_proxy_uses_prior_date_threshold_not_current_full_day():
    params = FlowDistributionParams(cutoff_times=('14:50:00',), min_minutes=2, threshold_lookback_days=(2,), threshold_quantile=0.75)

    out = derive_intraday_flow_distribution_moments(sample_minute_frame(), params, target_dates=['20240104'])

    row = out[out['ts_code'] == '000001.SZ'].iloc[0]
    assert row['threshold_source'] == 'prior_dates'
    assert row['threshold_lookback_days'] == 2
    assert row['amount_threshold_stock_q75'] > 0
    assert row['large_proxy_amount'] > 0
    assert row['small_proxy_amount'] > 0
    assert row['large_proxy_amount'] + row['small_proxy_amount'] == row['amount_sum']


def test_qa_and_catalog_contract_are_accept_ready_for_non_empty_output(tmp_path):
    params = FlowDistributionParams(cutoff_times=('14:50:00',), min_minutes=2, threshold_lookback_days=(2,))
    out = derive_intraday_flow_distribution_moments(sample_minute_frame(), params, target_dates=['20240104'])

    qa = build_qa_summary(
        out,
        params=params,
        source_min_trade_date='20240102',
        source_max_trade_date='20240104',
        missing_dates=[],
        output_path=tmp_path / 'datamart',
        catalog_path=tmp_path / 'catalog.json',
        runtime_seconds=1.0,
        input_minute_row_count=len(sample_minute_frame()),
        performance_profile={'read_seconds': 0.1, 'compute_seconds': 0.8, 'write_seconds': 0.1},
    )
    catalog_entry = build_catalog_entry(tmp_path / 'datamart', tmp_path / 'qa.json', '20240104', '20240104')

    assert qa['verdict'] == 'ACCEPT'
    assert qa['duplicate_key_count'] == 0
    assert qa['operator_backend'] == 'vectorized'
    assert qa['hard_checks']['no_future_intraday_minutes_true'] is True
    assert catalog_entry['metadata']['source_dataset'] == 'minute_bar'
    assert catalog_entry['metadata']['threshold_source'] == 'prior_dates'
    assert catalog_entry['metadata']['operator_backend'] == 'vectorized'
    assert catalog_entry['metadata']['tail_asymmetry_method'] == 'exact_group_quantile_10_90_abs_mass'
    assert catalog_entry['metadata']['unique_key'] == ['ts_code', 'trade_date', 'cutoff_time']


def test_read_minute_root_marks_read_error_target_as_missing(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    bad_part = tmp_path / 'trade_date=20240103'
    bad_part.mkdir()
    (bad_part / 'broken.parquet').write_text('not parquet', encoding='utf-8')

    good_part = tmp_path / 'trade_date=20240104'
    good_part.mkdir()
    sample_minute_frame().query("trade_date == '20240104'").to_parquet(good_part / 'part.parquet', index=False)

    frame, source_profile, missing_dates = read_minute_root(
        tmp_path,
        target_dates=['20240103', '20240104'],
        lookback_days=0,
    )

    assert not frame.empty
    assert '20240103' in missing_dates
    assert any(item['trade_date'] == '20240103' and item['status'] == 'read_error' for item in source_profile)


def test_write_catalog_uses_runtime_threshold_and_window_params(tmp_path):
    params = FlowDistributionParams(
        threshold_lookback_days=(5, 10),
        threshold_quantile=0.6,
        threshold_backend='polars',
        research_window='SMOKE',
        operator_backend='numba_sorted',
    )
    catalog_path = tmp_path / 'catalog.json'

    write_catalog(
        catalog_path,
        tmp_path / 'datamart',
        tmp_path / 'qa.json',
        '20240104',
        '20240104',
        operator_backend=params.operator_backend,
        params=params,
    )

    payload = json.loads(catalog_path.read_text(encoding='utf-8'))
    metadata = payload['datasets']['intraday_flow_distribution_moments_v1']['metadata']
    assert metadata['threshold_lookback_days'] == [5, 10]
    assert metadata['threshold_quantile'] == 0.6
    assert metadata['threshold_backend'] == 'polars'
    assert metadata['research_window'] == 'SMOKE'
    assert metadata['operator_backend'] == 'numba_sorted'


def test_flow_distribution_builder_supports_skip_existing_resume_manifest(tmp_path):
    pytest.importorskip('pyarrow')
    minute_root = tmp_path / 'minute'
    output_root = tmp_path / 'flow_state'
    qa_path = tmp_path / 'flow.qa.json'
    catalog_path = tmp_path / 'flow.catalog.json'
    manifest_path = tmp_path / 'flow.manifest.json'
    frame = sample_minute_frame()
    for trade_date, part in frame.groupby('trade_date'):
        part_dir = minute_root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True)
        part.to_parquet(part_dir / 'part.parquet', index=False)

    assert build_flow_distribution_main([
        '--minute-root', str(minute_root),
        '--start', '20240103',
        '--end', '20240104',
        '--output-root', str(output_root),
        '--qa-output', str(qa_path),
        '--catalog-output', str(catalog_path),
        '--skip-upload',
        '--cutoff-times', '14:50:00',
        '--threshold-lookback-days', '2',
        '--min-minutes', '2',
        '--max-dates', '1',
        '--manifest-output', str(manifest_path),
    ]) == 0
    first_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    first_partition = output_root / 'trade_date=20240103'
    first_files = sorted(first_partition.glob('*.parquet'))
    assert first_manifest['processed_dates'] == ['20240103']
    assert first_manifest['remaining_dates'] == ['20240104']
    assert first_files

    assert build_flow_distribution_main([
        '--minute-root', str(minute_root),
        '--start', '20240103',
        '--end', '20240104',
        '--output-root', str(output_root),
        '--qa-output', str(qa_path),
        '--catalog-output', str(catalog_path),
        '--skip-upload',
        '--cutoff-times', '14:50:00',
        '--threshold-lookback-days', '2',
        '--min-minutes', '2',
        '--skip-existing',
        '--manifest-output', str(manifest_path),
    ]) == 0
    second_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert second_manifest['skipped_existing_dates'] == ['20240103']
    assert second_manifest['processed_dates'] == ['20240104']
    assert second_manifest['remaining_dates'] == []
    assert (output_root / 'trade_date=20240104').exists()
    assert sorted(first_partition.glob('*.parquet')) == first_files


def test_flow_distribution_builder_blocks_duplicate_partition_rewrite_without_policy(tmp_path):
    pytest.importorskip('pyarrow')
    minute_root = tmp_path / 'minute'
    output_root = tmp_path / 'flow_state'
    frame = sample_minute_frame()
    for trade_date, part in frame.groupby('trade_date'):
        part_dir = minute_root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True)
        part.to_parquet(part_dir / 'part.parquet', index=False)

    common = [
        '--minute-root', str(minute_root),
        '--dates', '20240104',
        '--output-root', str(output_root),
        '--qa-output', str(tmp_path / 'flow.qa.json'),
        '--catalog-output', str(tmp_path / 'flow.catalog.json'),
        '--skip-upload',
        '--cutoff-times', '14:50:00',
        '--threshold-lookback-days', '2',
        '--min-minutes', '2',
    ]
    assert build_flow_distribution_main(common) == 0

    with pytest.raises(SystemExit) as exc_info:
        build_flow_distribution_main(common)
    assert exc_info.value.code != 0


def test_default_operator_is_vectorized_and_matches_reference():
    params = FlowDistributionParams(cutoff_times=('10:30:00', '14:50:00'), min_minutes=2, threshold_lookback_days=(2,))

    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), params, target_dates=['20240104'])
    reference = derive_intraday_flow_distribution_moments(
        sample_minute_frame(),
        FlowDistributionParams(
            cutoff_times=('10:30:00', '14:50:00'),
            min_minutes=2,
            threshold_lookback_days=(2,),
            operator_backend='reference',
        ),
        target_dates=['20240104'],
    )

    assert params.operator_backend == 'vectorized'
    assert optimized.attrs['operator_backend'] == 'vectorized'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_vectorized_uses_market_threshold_fallback_for_target_only_ticker():
    frame = sample_minute_frame()
    extra = []
    for minute, amount in [
        ('09:31:00', 150.0),
        ('10:00:00', 250.0),
        ('10:31:00', 450.0),
        ('14:50:00', 850.0),
    ]:
        extra.append({
            'ts_code': '000003.SZ',
            'trade_date': '20240104',
            'trade_time': minute,
            'open': 10.0,
            'close': 10.0 * (1.0 + amount / 100000.0),
            'high': 10.0 * (1.0 + amount / 100000.0),
            'low': 10.0,
            'vol': amount / 10.0,
            'amount': amount,
        })
    frame = pd.concat([frame, pd.DataFrame(extra)], ignore_index=True)
    params = FlowDistributionParams(cutoff_times=('14:50:00',), min_minutes=2, threshold_lookback_days=(2,))

    optimized = derive_intraday_flow_distribution_moments(frame, params, target_dates=['20240104'])
    reference = derive_intraday_flow_distribution_moments(
        frame,
        FlowDistributionParams(cutoff_times=('14:50:00',), min_minutes=2, threshold_lookback_days=(2,), operator_backend='reference'),
        target_dates=['20240104'],
    )

    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'large_proxy_amount',
        'small_proxy_amount',
        'amount_threshold_stock_q75',
        'amount_threshold_market_q75',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_polars_threshold_backend_matches_pandas_threshold_backend_when_available():
    try:
        import polars  # noqa: F401
    except Exception:
        return
    pandas_params = FlowDistributionParams(
        cutoff_times=('14:50:00',),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='vectorized',
        threshold_backend='pandas',
    )
    polars_params = FlowDistributionParams(
        cutoff_times=('14:50:00',),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='vectorized',
        threshold_backend='polars',
    )

    pandas_out = derive_intraday_flow_distribution_moments(sample_minute_frame(), pandas_params, target_dates=['20240104'])
    polars_out = derive_intraday_flow_distribution_moments(sample_minute_frame(), polars_params, target_dates=['20240104'])

    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'large_proxy_amount',
        'small_proxy_amount',
        'amount_threshold_stock_q75',
        'amount_threshold_market_q75',
    ]
    pd.testing.assert_frame_equal(
        polars_out[comparable_columns].reset_index(drop=True),
        pandas_out[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_prepared_minute_frame_without_open_close_matches_raw_input():
    params = FlowDistributionParams(cutoff_times=('14:50:00',), min_minutes=2, threshold_lookback_days=(2,))
    raw = sample_minute_frame()
    prepared = prepare_minute_frame(raw)

    raw_out = derive_intraday_flow_distribution_moments(raw, params, target_dates=['20240104'])
    prepared_out = derive_intraday_flow_distribution_moments(prepared, params, target_dates=['20240104'])

    pd.testing.assert_frame_equal(
        prepared_out.reset_index(drop=True),
        raw_out.reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_prepared_operator_entry_does_not_reprepare_minute_frame(monkeypatch):
    params = FlowDistributionParams(cutoff_times=('14:50:00',), min_minutes=2, threshold_lookback_days=(2,), operator_backend='vectorized')
    raw = sample_minute_frame()
    prepared = prepare_minute_frame(raw)
    expected = derive_intraday_flow_distribution_moments(raw, params, target_dates=['20240104'])

    def fail_prepare(_frame):
        raise AssertionError('prepared fast path should not call prepare_minute_frame')

    monkeypatch.setattr('factor_factory.data_api.flow_distribution_moments.prepare_minute_frame', fail_prepare)
    actual = derive_intraday_flow_distribution_moments_from_prepared(prepared, params, target_dates=['20240104'])

    assert actual.attrs['operator_backend'] == 'vectorized_prepared'
    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_build_script_marks_explicit_prepared_minute_input(tmp_path, monkeypatch, capsys):
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    prepared = prepare_minute_frame(sample_minute_frame())
    for trade_date, group in prepared.groupby('trade_date'):
        partition = prepared_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    output_root = tmp_path / 'moments'
    qa_output = tmp_path / 'moments.qa.json'
    catalog_output = tmp_path / 'moments.catalog.json'

    monkeypatch.setattr(
        'sys.argv',
        [
            'build_intraday_flow_distribution_moments.py',
            '--prepared-minute-root',
            str(prepared_root),
            '--dates',
            '20240104',
            '--output-root',
            str(output_root),
            '--qa-output',
            str(qa_output),
            '--catalog-output',
            str(catalog_output),
            '--skip-upload',
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
        ],
    )

    assert build_flow_distribution_main() == 0

    printed = json.loads(capsys.readouterr().out)
    qa = json.loads(qa_output.read_text(encoding='utf-8'))
    assert printed['verdict'] == 'ACCEPT'
    assert printed['input_dataset'] == 'prepared_minute_bar_v1'
    assert qa['verdict'] == 'ACCEPT'
    assert qa['input_dataset'] == 'prepared_minute_bar_v1'
    assert qa['input_minute_format'] == 'prepared'
    assert qa['input_prepared_minute_columns'] == [
        'ts_code',
        'trade_date',
        'hhmmss',
        'amount_abs',
        'minute_ret',
        'signed_amount',
        'vol',
    ]
    assert qa['performance_profile']['input_dataset'] == 'prepared_minute_bar_v1'
    assert qa['realized_operator_backend'] == 'vectorized_prepared'
    assert qa['duplicate_key_count'] == 0


def test_build_script_can_skip_source_not_ready_prepared_partitions(tmp_path, monkeypatch, capsys):
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    prepared = prepare_minute_frame(sample_minute_frame())
    for trade_date in ['20240104', '20240106']:
        partition = prepared_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        prepared.assign(trade_date=trade_date).to_parquet(partition / 'part.parquet', index=False)
    marker_partition = prepared_root / 'trade_date=20240105'
    marker_partition.mkdir(parents=True)
    (marker_partition / 'part-000.parquet.missing').write_text('source unavailable', encoding='utf-8')
    output_root = tmp_path / 'moments'
    qa_output = tmp_path / 'moments.qa.json'
    catalog_output = tmp_path / 'moments.catalog.json'

    monkeypatch.setattr(
        'sys.argv',
        [
            'build_intraday_flow_distribution_moments.py',
            '--prepared-minute-root',
            str(prepared_root),
            '--start',
            '20240104',
            '--end',
            '20240106',
            '--source-ready-only',
            '--output-root',
            str(output_root),
            '--qa-output',
            str(qa_output),
            '--catalog-output',
            str(catalog_output),
            '--skip-upload',
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
        ],
    )

    assert build_flow_distribution_main() == 0

    printed = json.loads(capsys.readouterr().out)
    qa = json.loads(qa_output.read_text(encoding='utf-8'))
    assert printed['verdict'] == 'ACCEPT'
    assert printed['source_not_ready_dates'] == ['20240105']
    assert qa['missing_dates'] == []
    assert qa['source_not_ready_dates'] == ['20240105']
    assert qa['output_min_trade_date'] == '20240104'
    assert qa['output_max_trade_date'] == '20240106'
    assert {item['trade_date'] for item in qa['source_profile']} == {'20240104', '20240106'}


def test_parity_smoke_is_wired_to_prepared_dispatcher():
    assert parity_smoke.derive_intraday_flow_distribution_moments_from_prepared is not None


def test_parity_smoke_records_prepared_dispatcher_backend_when_numba_available(tmp_path, monkeypatch, capsys):
    if not has_numba():
        return
    minute_root = tmp_path / 'minute_bar'
    for trade_date, group in sample_minute_frame().groupby('trade_date'):
        partition = minute_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    proof_output = tmp_path / 'parity.json'

    monkeypatch.setattr(
        'sys.argv',
        [
            'run_flow_distribution_moments_parity_smoke.py',
            '--minute-root',
            str(minute_root),
            '--date',
            '20240104',
            '--output-path',
            str(proof_output),
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
        ],
    )

    assert parity_smoke_main() == 0

    payload = json.loads(proof_output.read_text(encoding='utf-8'))
    assert json.loads(capsys.readouterr().out)['verdict'] == 'ACCEPT'
    assert payload['prepared_dispatcher_backend'] == 'numba_sorted_prepared'
    assert payload['prepared_dispatcher_warm_seconds'] >= 0.0
    assert payload['performance_promotion_verdict'] in {'ACCEPT', 'BLOCK'}
    assert payload['performance_min_speedup_ratio'] == 1.10
    assert 'performance_speedup_vs_vectorized' in payload


def test_parity_smoke_blocks_with_proof_when_numba_backend_unavailable(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    for trade_date, group in sample_minute_frame().groupby('trade_date'):
        partition = minute_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    proof_output = tmp_path / 'parity.numba_unavailable.json'
    real_derive = parity_smoke.derive_intraday_flow_distribution_moments

    def derive_or_fail(minute_df, params, *, target_dates=None):
        if params.operator_backend == 'numba_sorted':
            raise ImportError('No module named numba')
        return real_derive(minute_df, params, target_dates=target_dates)

    monkeypatch.setattr(parity_smoke, 'derive_intraday_flow_distribution_moments', derive_or_fail)
    monkeypatch.setattr(
        'sys.argv',
        [
            'run_flow_distribution_moments_parity_smoke.py',
            '--minute-root',
            str(minute_root),
            '--date',
            '20240104',
            '--output-path',
            str(proof_output),
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
        ],
    )

    assert parity_smoke_main() == 2

    payload = json.loads(proof_output.read_text(encoding='utf-8'))
    assert json.loads(capsys.readouterr().out)['verdict'] == 'BLOCK'
    assert payload['verdict'] == 'BLOCK'
    assert 'numba_unavailable' in payload['issues']
    assert payload['prepared_dispatcher_backend'] == ''


def test_parity_smoke_performance_promotion_blocks_correct_but_slow_backend():
    summary = parity_smoke._performance_promotion_summary(
        correctness_verdict='ACCEPT',
        baseline_seconds=10.0,
        candidate_seconds=12.5,
        min_speedup_ratio=1.10,
    )

    assert summary['performance_promotion_verdict'] == 'BLOCK'
    assert summary['performance_speedup_vs_vectorized'] == 0.8
    assert summary['performance_min_speedup_ratio'] == 1.10
    assert summary['performance_promotion_issues'] == ['candidate_not_materially_faster']


def test_operator_profiler_writes_stage_timing_proof_for_raw_minute_root(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    for trade_date, group in sample_minute_frame().groupby('trade_date'):
        partition = minute_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    output_path = tmp_path / 'operator_profile.json'

    monkeypatch.setattr(
        'sys.argv',
        [
            'profile_flow_distribution_moments_operator.py',
            '--minute-root',
            str(minute_root),
            '--date',
            '20240104',
            '--output-path',
            str(output_path),
            '--cutoff-times',
            '10:30:00,14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
            '--operator-backend',
            'vectorized',
        ],
    )

    assert profile_flow_distribution_moments_operator.main() == 0

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    printed = json.loads(capsys.readouterr().out)
    assert printed == payload
    assert payload['verdict'] == 'ACCEPT'
    assert payload['date'] == '20240104'
    assert payload['input_dataset'] == 'minute_bar'
    assert payload['operator_backend'] == 'vectorized'
    assert payload['realized_operator_backend'] == 'vectorized_profiled'
    assert payload['row_count'] == 4
    assert payload['duplicate_key_count'] == 0
    assert isinstance(payload['output_key_hash'], str)
    assert len(payload['output_key_hash']) == 64
    assert payload['dominant_stage'] in {'read', 'prepare', 'threshold', 'operator', 'total_overhead'}
    for field in ['read_seconds', 'prepare_seconds', 'threshold_seconds', 'operator_seconds', 'total_seconds']:
        assert field in payload['stage_seconds']
        assert payload['stage_seconds'][field] >= 0.0


def test_operator_profiler_marks_prepared_minute_input_without_raw_prepare(tmp_path, monkeypatch):
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    prepared = prepare_minute_frame(sample_minute_frame())
    for trade_date, group in prepared.groupby('trade_date'):
        partition = prepared_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    output_path = tmp_path / 'operator_profile_prepared.json'

    monkeypatch.setattr(
        'sys.argv',
        [
            'profile_flow_distribution_moments_operator.py',
            '--prepared-minute-root',
            str(prepared_root),
            '--date',
            '20240104',
            '--output-path',
            str(output_path),
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
            '--operator-backend',
            'vectorized',
        ],
    )

    assert profile_flow_distribution_moments_operator.main() == 0

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert payload['verdict'] == 'ACCEPT'
    assert payload['input_dataset'] == 'prepared_minute_bar_v1'
    assert payload['realized_operator_backend'] == 'vectorized_profiled'
    assert payload['stage_seconds']['prepare_seconds'] >= 0.0
    assert payload['prepared_minute_row_count'] == payload['input_minute_row_count']


def test_operator_profiler_blocks_with_proof_when_backend_unavailable(tmp_path, monkeypatch, capsys):
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    prepared = prepare_minute_frame(sample_minute_frame())
    for trade_date, group in prepared.groupby('trade_date'):
        partition = prepared_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    output_path = tmp_path / 'operator_profile_numba_unavailable.json'

    def unavailable_backend(*_args, **_kwargs):
        raise ImportError('No module named numba')

    monkeypatch.setattr(
        profile_flow_distribution_moments_operator,
        'derive_intraday_flow_distribution_moments_numba_sorted_prepared',
        unavailable_backend,
    )
    monkeypatch.setattr(
        'sys.argv',
        [
            'profile_flow_distribution_moments_operator.py',
            '--prepared-minute-root',
            str(prepared_root),
            '--date',
            '20240104',
            '--output-path',
            str(output_path),
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
            '--operator-backend',
            'numba_sorted',
        ],
    )

    assert profile_flow_distribution_moments_operator.main() == 2

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert json.loads(capsys.readouterr().out)['verdict'] == 'BLOCK'
    assert payload['verdict'] == 'BLOCK'
    assert payload['operator_backend'] == 'numba_sorted'
    assert payload['realized_operator_backend'] == ''
    assert payload['row_count'] == 0
    assert 'operator_backend_unavailable' in payload['issues']
    assert 'No module named numba' in payload['error']
    assert payload['stage_seconds']['operator_seconds'] >= 0.0


def test_operator_profiler_blocks_with_proof_when_target_date_is_not_source_ready(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    raw_partition = minute_root / 'trade_date=20240104'
    raw_partition.mkdir(parents=True)
    sample_minute_frame().query("trade_date == '20240104'").to_parquet(raw_partition / 'part.parquet', index=False)
    marker_partition = minute_root / 'trade_date=20240105'
    marker_partition.mkdir(parents=True)
    (marker_partition / 'part-000.parquet.missing').write_text('source unavailable', encoding='utf-8')
    output_path = tmp_path / 'operator_profile_source_not_ready.json'

    monkeypatch.setattr(
        'sys.argv',
        [
            'profile_flow_distribution_moments_operator.py',
            '--minute-root',
            str(minute_root),
            '--date',
            '20240105',
            '--output-path',
            str(output_path),
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
            '--operator-backend',
            'vectorized',
            '--source-ready-only',
        ],
    )

    assert profile_flow_distribution_moments_operator.main() == 2

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert json.loads(capsys.readouterr().out)['verdict'] == 'BLOCK'
    assert payload['verdict'] == 'BLOCK'
    assert payload['date'] == '20240105'
    assert payload['row_count'] == 0
    assert payload['missing_dates'] == ['20240105']
    assert payload['source_not_ready_dates'] == ['20240105']
    assert payload['source_profile_count'] == 0
    assert 'missing_target_dates' in payload['issues']
    assert payload['stage_seconds']['prepare_seconds'] >= 0.0


def test_operator_profile_comparison_writes_raw_vs_prepared_matrix(tmp_path, monkeypatch, capsys):
    minute_root = tmp_path / 'minute_bar'
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    prepared = prepare_minute_frame(sample_minute_frame())
    for trade_date, group in sample_minute_frame().groupby('trade_date'):
        partition = minute_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    for trade_date, group in prepared.groupby('trade_date'):
        partition = prepared_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    output_path = tmp_path / 'operator_profile_comparison.json'

    monkeypatch.setattr(
        'sys.argv',
        [
            'compare_flow_distribution_operator_profiles.py',
            '--minute-root',
            str(minute_root),
            '--prepared-minute-root',
            str(prepared_root),
            '--date',
            '20240104',
            '--output-path',
            str(output_path),
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
            '--operator-backends',
            'vectorized',
        ],
    )

    assert compare_flow_distribution_operator_profiles.main() == 0

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert json.loads(capsys.readouterr().out)['verdict'] == 'ACCEPT'
    assert payload['verdict'] == 'ACCEPT'
    assert payload['profile_count'] == 2
    assert {item['profile_id'] for item in payload['profiles']} == {'raw:vectorized', 'prepared:vectorized'}
    assert payload['best_profile_id'] in {'raw:vectorized', 'prepared:vectorized'}
    assert payload['prepared_vs_raw_total_speedup'] > 0.0
    assert payload['accepted_profile_key_hash_equal'] is True
    assert payload['operator_replacement_verdict'] in {'ACCEPT', 'BLOCK'}
    for profile in payload['profiles']:
        assert profile['verdict'] == 'ACCEPT'
        assert profile['duplicate_key_count'] == 0
        assert isinstance(profile['output_key_hash'], str)
        assert len(profile['output_key_hash']) == 64
        assert profile['stage_seconds']['total_seconds'] >= 0.0


def test_operator_profile_comparison_keeps_blocked_backend_proofs(tmp_path, monkeypatch):
    minute_root = tmp_path / 'minute_bar'
    prepared_root = tmp_path / 'prepared_minute_bar_v1'
    prepared = prepare_minute_frame(sample_minute_frame())
    for trade_date, group in sample_minute_frame().groupby('trade_date'):
        partition = minute_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    for trade_date, group in prepared.groupby('trade_date'):
        partition = prepared_root / f'trade_date={trade_date}'
        partition.mkdir(parents=True)
        group.to_parquet(partition / 'part.parquet', index=False)
    output_path = tmp_path / 'operator_profile_comparison_block.json'

    def unavailable_backend(*_args, **_kwargs):
        raise ImportError('No module named numba')

    monkeypatch.setattr(
        profile_flow_distribution_moments_operator,
        'derive_intraday_flow_distribution_moments_numba_sorted_prepared',
        unavailable_backend,
    )
    monkeypatch.setattr(
        'sys.argv',
        [
            'compare_flow_distribution_operator_profiles.py',
            '--minute-root',
            str(minute_root),
            '--prepared-minute-root',
            str(prepared_root),
            '--date',
            '20240104',
            '--output-path',
            str(output_path),
            '--cutoff-times',
            '14:50:00',
            '--threshold-lookback-days',
            '2',
            '--min-minutes',
            '2',
            '--operator-backends',
            'vectorized,numba_sorted',
        ],
    )

    assert compare_flow_distribution_operator_profiles.main() == 2

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert payload['verdict'] == 'BLOCK'
    assert payload['profile_count'] == 4
    blocked = [item for item in payload['profiles'] if item['verdict'] == 'BLOCK']
    assert {item['profile_id'] for item in blocked} == {'raw:numba_sorted', 'prepared:numba_sorted'}
    assert all('operator_backend_unavailable' in item['issues'] for item in blocked)
    assert payload['best_profile_id'] in {'raw:vectorized', 'prepared:vectorized'}
    assert payload['operator_replacement_verdict'] in {'ACCEPT', 'BLOCK'}


def test_operator_profile_comparison_blocks_replacement_when_accepted_row_counts_differ():
    profiles = [
        {
            'profile_id': 'raw:vectorized',
            'verdict': 'ACCEPT',
            'row_count': 4,
            'duplicate_key_count': 0,
            'stage_seconds': {'total_seconds': 10.0},
        },
        {
            'profile_id': 'prepared:numba_sorted',
            'verdict': 'ACCEPT',
            'row_count': 3,
            'duplicate_key_count': 0,
            'stage_seconds': {'total_seconds': 1.0},
        },
    ]

    summary = compare_flow_distribution_operator_profiles._summarize_profiles(
        profiles,
        min_speedup_ratio=1.10,
    )

    assert summary['accepted_profile_row_count_equal'] is False
    assert summary['accepted_profile_duplicate_key_count_zero'] is True
    assert summary['operator_replacement_verdict'] == 'BLOCK'
    assert 'accepted_profile_row_count_mismatch' in summary['operator_replacement_issues']


def test_operator_profile_comparison_blocks_replacement_when_accepted_key_hashes_differ():
    profiles = [
        {
            'profile_id': 'raw:vectorized',
            'verdict': 'ACCEPT',
            'row_count': 4,
            'duplicate_key_count': 0,
            'output_key_hash': 'a' * 64,
            'stage_seconds': {'total_seconds': 10.0},
        },
        {
            'profile_id': 'prepared:numba_sorted',
            'verdict': 'ACCEPT',
            'row_count': 4,
            'duplicate_key_count': 0,
            'output_key_hash': 'b' * 64,
            'stage_seconds': {'total_seconds': 1.0},
        },
    ]

    summary = compare_flow_distribution_operator_profiles._summarize_profiles(
        profiles,
        min_speedup_ratio=1.10,
    )

    assert summary['accepted_profile_key_hash_equal'] is False
    assert summary['operator_replacement_verdict'] == 'BLOCK'
    assert 'accepted_profile_key_hash_mismatch' in summary['operator_replacement_issues']


def test_operator_profile_comparison_blocks_replacement_when_baseline_profile_not_accept():
    profiles = [
        {
            'profile_id': 'raw:vectorized',
            'verdict': 'BLOCK',
            'row_count': 0,
            'duplicate_key_count': 0,
            'output_key_hash': '0' * 64,
            'stage_seconds': {'total_seconds': 10.0},
            'issues': ['missing_target_dates'],
        },
        {
            'profile_id': 'prepared:vectorized',
            'verdict': 'ACCEPT',
            'row_count': 4,
            'duplicate_key_count': 0,
            'output_key_hash': 'a' * 64,
            'stage_seconds': {'total_seconds': 1.0},
        },
    ]

    summary = compare_flow_distribution_operator_profiles._summarize_profiles(
        profiles,
        min_speedup_ratio=1.10,
    )

    assert summary['baseline_profile_id'] == 'raw:vectorized'
    assert summary['baseline_profile_accept'] is False
    assert summary['operator_replacement_verdict'] == 'BLOCK'
    assert 'baseline_profile_not_accept' in summary['operator_replacement_issues']


def valid_operator_comparison_payload() -> dict:
    return {
        'verdict': 'ACCEPT',
        'date': '20240104',
        'profile_count': 2,
        'profiles': [
            {
                'profile_id': 'raw:vectorized',
                'verdict': 'ACCEPT',
                'row_count': 4,
                'duplicate_key_count': 0,
                'output_key_hash': 'a' * 64,
                'stage_seconds': {'total_seconds': 10.0},
            },
            {
                'profile_id': 'prepared:vectorized',
                'verdict': 'ACCEPT',
                'row_count': 4,
                'duplicate_key_count': 0,
                'output_key_hash': 'a' * 64,
                'stage_seconds': {'total_seconds': 8.0},
            },
        ],
        'best_profile_id': 'prepared:vectorized',
        'prepared_vs_raw_total_speedup': 1.25,
        'best_speedup_vs_raw_vectorized': 1.25,
        'min_speedup_ratio': 1.10,
        'baseline_profile_id': 'raw:vectorized',
        'baseline_profile_accept': True,
        'accepted_profile_row_count_equal': True,
        'accepted_profile_duplicate_key_count_zero': True,
        'accepted_profile_key_hash_equal': True,
        'operator_replacement_verdict': 'ACCEPT',
        'operator_replacement_issues': [],
    }


def test_operator_comparison_validator_accepts_complete_accept_proof(tmp_path, monkeypatch, capsys):
    proof_path = tmp_path / 'comparison.json'
    output_path = tmp_path / 'comparison.validation.json'
    proof_path.write_text(json.dumps(valid_operator_comparison_payload()), encoding='utf-8')

    monkeypatch.setattr(
        'sys.argv',
        [
            'validate_flow_distribution_operator_comparison.py',
            '--proof-path',
            str(proof_path),
            '--output-path',
            str(output_path),
        ],
    )

    assert validate_flow_distribution_operator_comparison.main() == 0

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert json.loads(capsys.readouterr().out)['verdict'] == 'ACCEPT'
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['proof_path'] == str(proof_path)


def test_operator_comparison_validator_blocks_missing_required_field(tmp_path):
    proof = valid_operator_comparison_payload()
    proof.pop('accepted_profile_key_hash_equal')
    proof_path = tmp_path / 'comparison.missing.json'
    output_path = tmp_path / 'comparison.missing.validation.json'
    proof_path.write_text(json.dumps(proof), encoding='utf-8')

    assert validate_flow_distribution_operator_comparison.validate_proof_path(proof_path, output_path) == 2

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert payload['verdict'] == 'BLOCK'
    assert 'missing_required_field:accepted_profile_key_hash_equal' in payload['issues']


def test_operator_comparison_validator_blocks_replacement_gate_block(tmp_path):
    proof = valid_operator_comparison_payload()
    proof['operator_replacement_verdict'] = 'BLOCK'
    proof['operator_replacement_issues'] = ['best_profile_not_materially_faster_than_raw_vectorized']
    proof_path = tmp_path / 'comparison.block.json'
    output_path = tmp_path / 'comparison.block.validation.json'
    proof_path.write_text(json.dumps(proof), encoding='utf-8')

    assert validate_flow_distribution_operator_comparison.validate_proof_path(proof_path, output_path) == 2

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert payload['verdict'] == 'BLOCK'
    assert 'operator_replacement_verdict_not_accept' in payload['issues']


def test_polars_operator_matches_reference_core_contract():
    reference_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='reference',
    )
    polars_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='polars',
    )

    reference = derive_intraday_flow_distribution_moments(sample_minute_frame(), reference_params, target_dates=['20240104'])
    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), polars_params, target_dates=['20240104'])

    assert optimized.attrs['operator_backend'] == 'polars'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_mapreduce_operator_matches_reference_core_contract():
    reference_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='reference',
    )
    mapreduce_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='mapreduce',
    )

    reference = derive_intraday_flow_distribution_moments(sample_minute_frame(), reference_params, target_dates=['20240104'])
    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), mapreduce_params, target_dates=['20240104'])

    assert optimized.attrs['operator_backend'] == 'mapreduce'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_mean',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_amount_mean',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_mapreduce_threaded_operator_matches_reference_core_contract():
    reference_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='reference',
    )
    threaded_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='mapreduce_threaded',
    )

    reference = derive_intraday_flow_distribution_moments(sample_minute_frame(), reference_params, target_dates=['20240104'])
    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), threaded_params, target_dates=['20240104'])

    assert optimized.attrs['operator_backend'] == 'mapreduce_threaded'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_process_sharded_mapreduce_operator_matches_reference_core_contract():
    reference_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='reference',
    )
    sharded_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='process_sharded_mapreduce',
    )

    reference = derive_intraday_flow_distribution_moments(sample_minute_frame(), reference_params, target_dates=['20240104'])
    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), sharded_params, target_dates=['20240104'])

    assert optimized.attrs['operator_backend'] == 'process_sharded_mapreduce'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_process_sharded_vectorized_operator_matches_reference_core_contract():
    reference_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='reference',
    )
    sharded_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='process_sharded_vectorized',
    )

    reference = derive_intraday_flow_distribution_moments(sample_minute_frame(), reference_params, target_dates=['20240104'])
    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), sharded_params, target_dates=['20240104'])

    assert optimized.attrs['operator_backend'] == 'process_sharded_vectorized'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_numba_operator_matches_reference_core_contract_when_available():
    if not has_numba():
        return
    reference_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='reference',
    )
    numba_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='numba',
    )

    reference = derive_intraday_flow_distribution_moments(sample_minute_frame(), reference_params, target_dates=['20240104'])
    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), numba_params, target_dates=['20240104'])

    assert optimized.attrs['operator_backend'] == 'numba'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_mean',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_amount_mean',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_numba_sorted_operator_matches_reference_core_contract_when_available():
    if not has_numba():
        return
    reference_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='reference',
    )
    numba_params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='numba_sorted',
    )

    reference = derive_intraday_flow_distribution_moments(sample_minute_frame(), reference_params, target_dates=['20240104'])
    optimized = derive_intraday_flow_distribution_moments(sample_minute_frame(), numba_params, target_dates=['20240104'])

    assert optimized.attrs['operator_backend'] == 'numba_sorted'
    comparable_columns = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'minute_count',
        'amount_sum',
        'ret_mean',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_amount_mean',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
    ]
    pd.testing.assert_frame_equal(
        optimized[comparable_columns].reset_index(drop=True),
        reference[comparable_columns].reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_numba_sorted_prepared_matches_numba_sorted_when_available():
    if not has_numba():
        return
    params = FlowDistributionParams(
        cutoff_times=('10:30:00', '14:50:00'),
        min_minutes=2,
        threshold_lookback_days=(2,),
        operator_backend='numba_sorted',
    )
    minute = prepare_minute_frame(sample_minute_frame())
    targets = {'20240104'}
    thresholds = _build_threshold_frame(minute, targets, 2, params.threshold_quantile, params.threshold_backend)

    normal = derive_intraday_flow_distribution_moments(sample_minute_frame(), params, target_dates=['20240104'])
    prepared = derive_intraday_flow_distribution_moments_numba_sorted_prepared(
        minute,
        params,
        targets=targets,
        thresholds=thresholds,
    )

    pd.testing.assert_frame_equal(
        prepared.reset_index(drop=True),
        normal.reset_index(drop=True),
        check_exact=False,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )
