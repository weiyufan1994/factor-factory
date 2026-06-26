from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.intraday_ema_slow_state import (
    DATASET_ID,
    IntradayEmaSlowStateParams,
    build_intraday_ema_slow_state_qa,
    derive_intraday_ema_slow_state,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = REPO_ROOT / 'scripts' / name
    spec = importlib.util.spec_from_file_location(name.removesuffix('.py'), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_source_frame() -> pd.DataFrame:
    return pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ', '000001.SZ', '000001.SZ', '000001.SZ', '000002.SZ'],
        'trade_date': ['20241231', '20250102', '20250711', '20250714', '20250102', '20250102'],
        'cutoff_time': ['14:50:00', '14:50:00', '14:50:00', '14:50:00', '14:00:00', '14:50:00'],
        'v19d_score': [10.0, 30.0, 50.0, 70.0, 999.0, 100.0],
    })


def test_intraday_ema_slow_state_recurs_without_year_reset_and_labels_oos():
    params = IntradayEmaSlowStateParams(lambdas=(0.5,), cutoff_times=('14:50:00',), operator_backend='reference')

    out = derive_intraday_ema_slow_state(sample_source_frame(), params=params)

    assert DATASET_ID == 'intraday_ema_slow_state_v1'
    assert out.attrs['operator_backend'] == 'reference'
    assert out.duplicated(['ts_code', 'trade_date', 'cutoff_time', 'lambda']).sum() == 0
    stock = out[out['ts_code'] == '000001.SZ'].sort_values('trade_date').reset_index(drop=True)
    assert stock['trade_date'].tolist() == ['20241231', '20250102', '20250711', '20250714']
    np.testing.assert_allclose(stock['ema_state'].to_numpy(), np.array([10.0, 20.0, 35.0, 52.5]), rtol=1e-12, atol=1e-12)
    assert stock['research_window'].tolist() == ['IS', 'IS', 'IS', 'OOS']
    assert stock['state_source'].eq('prior_state_continuous').all()
    assert stock['source_signal_col'].eq('v19d_score').all()
    assert stock['no_future_data'].eq(True).all()


def test_intraday_ema_slow_state_multiple_lambda_paths_match_array_backend():
    params = {'lambdas': (0.5, 0.8), 'cutoff_times': ('14:50:00',)}

    reference = derive_intraday_ema_slow_state(sample_source_frame(), IntradayEmaSlowStateParams(**params, operator_backend='reference'))
    array = derive_intraday_ema_slow_state(sample_source_frame(), IntradayEmaSlowStateParams(**params, operator_backend='array_grouped'))

    assert sorted(reference['lambda'].unique().tolist()) == [0.5, 0.8]
    comparable = ['ts_code', 'trade_date', 'cutoff_time', 'lambda', 'signal_value', 'ema_state']
    pd.testing.assert_frame_equal(reference[comparable], array[comparable], check_dtype=False)


def test_intraday_ema_slow_state_qa_blocks_duplicate_keys():
    out = derive_intraday_ema_slow_state(sample_source_frame(), IntradayEmaSlowStateParams(lambdas=(0.5,), cutoff_times=('14:50:00',)))
    duplicated = pd.concat([out, out.head(1)], ignore_index=True)

    qa = build_intraday_ema_slow_state_qa(duplicated)

    assert qa['verdict'] == 'BLOCK'
    assert qa['duplicate_key_count'] == 1


def test_build_and_validate_intraday_ema_slow_state_partitioned_output(tmp_path: Path):
    pytest.importorskip('pyarrow')
    builder = _load_script('build_intraday_ema_slow_state.py')
    validator = _load_script('validate_intraday_ema_slow_state.py')
    input_path = tmp_path / 'source.parquet'
    output_root = tmp_path / 'intraday_ema_slow_state_v1'
    qa_path = tmp_path / 'ema.qa.json'
    catalog_path = tmp_path / 'ema.catalog.json'
    validation_path = tmp_path / 'ema.validation.json'
    manifest_path = tmp_path / 'ema.manifest.json'
    sample_source_frame().to_parquet(input_path, index=False)

    assert builder.main([
        '--input-parquet',
        str(input_path),
        '--start',
        '20241231',
        '--end',
        '20250714',
        '--output-root',
        str(output_root),
        '--qa-output',
        str(qa_path),
        '--catalog-output',
        str(catalog_path),
        '--manifest-output',
        str(manifest_path),
        '--cutoff-times',
        '14:50:00',
        '--lambdas',
        '0.5,0.8',
        '--operator-backend',
        'reference',
    ]) == 0
    assert validator.main([
        '--feature-parquet',
        str(output_root),
        '--qa-path',
        str(qa_path),
        '--output-path',
        str(validation_path),
        '--min-row-count',
        '10',
        '--max-warm-read-seconds',
        '10',
    ]) == 0

    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert qa['verdict'] == 'ACCEPT'
    assert qa['row_count'] == 10
    assert qa['research_windows'] == ['IS', 'OOS']
    assert validation['verdict'] == 'ACCEPT'
    assert manifest['verdict'] == 'ACCEPT'
    assert (output_root / 'trade_date=20250102' / 'part.parquet').exists()

    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(
            'intraday_ema_slow_state_v1',
            '20250102',
            '20250102',
            'a_share_all',
            ['cutoff_time', 'lambda', 'ema_state', 'source_signal_col'],
            frequency='intraday_cutoff',
        )
    )
    assert result.status == 'ready'
    assert result.coverage.row_count == 4
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == ['ts_code', 'trade_date', 'cutoff_time', 'lambda', 'ema_state', 'source_signal_col']
