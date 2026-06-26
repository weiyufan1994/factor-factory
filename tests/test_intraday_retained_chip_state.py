from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_factory.data_api.intraday_retained_chip_state import (
    DATASET_ID,
    IntradayRetainedChipStateParams,
    build_intraday_retained_chip_state_qa,
    derive_intraday_retained_chip_state,
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


def sample_minute() -> pd.DataFrame:
    rows = []
    for trade_date, amounts in [
        ('20250102', [100.0, 300.0]),
        ('20250103', [500.0, 700.0]),
    ]:
        for trade_time, amount in zip(['09:45:00', '10:00:00'], amounts, strict=True):
            rows.append({
                'ts_code': '000001.SZ',
                'trade_date': trade_date,
                'trade_time': trade_time,
                'vol': 10.0,
                'amount': amount,
            })
    rows.append({
        'ts_code': '000002.SZ',
        'trade_date': '20250103',
        'trade_time': '09:45:00',
        'vol': 100000.0,
        'amount': 1000.0,
    })
    return pd.DataFrame(rows)


def sample_daily_basic() -> pd.DataFrame:
    return pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ'],
        'trade_date': ['20250102', '20250103', '20250103'],
        'float_share': [1.0, 1.0, 1.0],
    })


def params() -> IntradayRetainedChipStateParams:
    return IntradayRetainedChipStateParams(
        lookback_days=2,
        interval_minutes=15,
        interval_endpoints=('09:45:00', '10:00:00'),
        volume_to_share_multiplier=1.0,
        float_share_to_share_multiplier=100.0,
        is_end_date='20250102',
    )


def test_retained_chip_state_matches_survival_product_math():
    out = derive_intraday_retained_chip_state(
        sample_minute(),
        sample_daily_basic(),
        trade_dates=['20250102', '20250103'],
        params=params(),
    )

    assert DATASET_ID == 'intraday_retained_chip_state_v1'
    assert out.duplicated(['ts_code', 'trade_date']).sum() == 0
    row = out[(out['ts_code'] == '000001.SZ') & (out['trade_date'] == '20250103')].iloc[0]
    turnovers = np.array([0.1, 0.1, 0.1, 0.1])
    amounts = np.array([100.0, 300.0, 500.0, 700.0])
    expected_survival = np.array([
        (1 - turnovers[1]) * (1 - turnovers[2]) * (1 - turnovers[3]),
        (1 - turnovers[2]) * (1 - turnovers[3]),
        (1 - turnovers[3]),
        1.0,
    ])
    expected_retained = float((amounts * expected_survival).sum())
    expected_amount = float(amounts.sum())

    assert math.isclose(row['retained_amount_sum'], expected_retained, rel_tol=1e-12)
    assert math.isclose(row['amount_sum_20d'], expected_amount, rel_tol=1e-12)
    assert math.isclose(row['lcr_raw'], expected_retained / expected_amount, rel_tol=1e-12)
    assert row['interval_count'] == 4
    assert row['valid_interval_count'] == 4
    assert row['missing_interval_count'] == 0
    assert row['qa_status'] == 'OK'
    assert row['research_window'] == 'OOS'
    assert bool(row['no_future_data']) is True
    assert bool(row['no_future_intraday_minutes']) is True


def test_retained_chip_state_reports_missing_intervals_and_clipping():
    out = derive_intraday_retained_chip_state(
        sample_minute(),
        sample_daily_basic(),
        trade_dates=['20250102', '20250103'],
        params=params(),
    )
    row = out[(out['ts_code'] == '000002.SZ') & (out['trade_date'] == '20250103')].iloc[0]

    assert row['turnover_clipped_count'] == 1
    assert row['missing_interval_count'] == 3
    assert 'turnover_clipped' in row['qa_status']
    assert 'missing_intervals' in row['qa_status']


def test_retained_chip_state_qa_accepts_unique_complete_sample_and_blocks_duplicate():
    out = derive_intraday_retained_chip_state(
        sample_minute(),
        sample_daily_basic(),
        trade_dates=['20250102', '20250103'],
        params=params(),
    )

    qa = build_intraday_retained_chip_state_qa(out, expected_dates=['20250102', '20250103'])
    assert qa['verdict'] == 'ACCEPT'
    assert qa['duplicate_key_count'] == 0
    assert qa['missing_dates'] == []
    assert qa['turnover_clipped_count_sum'] == 1

    duplicated = pd.concat([out, out.head(1)], ignore_index=True)
    blocked = build_intraday_retained_chip_state_qa(duplicated, expected_dates=['20250102', '20250103'])
    assert blocked['verdict'] == 'BLOCK'
    assert blocked['duplicate_key_count'] == 1


def test_build_and_validate_retained_chip_state_partitioned_output(tmp_path: Path):
    pytest.importorskip('pyarrow')
    builder = _load_script('build_intraday_retained_chip_state.py')
    validator = _load_script('validate_intraday_retained_chip_state.py')
    minute_path = tmp_path / 'minute.parquet'
    daily_path = tmp_path / 'daily_basic.parquet'
    output_root = tmp_path / 'intraday_retained_chip_state_v1'
    qa_path = tmp_path / 'lcr.qa.json'
    catalog_path = tmp_path / 'lcr.catalog.json'
    manifest_path = tmp_path / 'lcr.manifest.json'
    validation_path = tmp_path / 'lcr.validation.json'
    sample_minute().to_parquet(minute_path, index=False)
    sample_daily_basic().to_parquet(daily_path, index=False)

    assert builder.main([
        '--minute-parquet',
        str(minute_path),
        '--daily-basic-parquet',
        str(daily_path),
        '--start',
        '20250102',
        '--end',
        '20250103',
        '--output-root',
        str(output_root),
        '--qa-output',
        str(qa_path),
        '--catalog-output',
        str(catalog_path),
        '--manifest-output',
        str(manifest_path),
        '--lookback-days',
        '2',
        '--volume-to-share-multiplier',
        '1',
        '--float-share-to-share-multiplier',
        '100',
    ]) == 0
    assert validator.main([
        '--feature-parquet',
        str(output_root),
        '--qa-path',
        str(qa_path),
        '--output-path',
        str(validation_path),
        '--expected-dates',
        '20250102,20250103',
        '--expected-lookback-days',
        '2',
        '--min-row-count',
        '3',
        '--max-warm-read-seconds',
        '10',
    ]) == 0

    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    assert qa['verdict'] == 'ACCEPT'
    assert qa['row_count'] == 3
    assert qa['duplicate_key_count'] == 0
    assert qa['missing_dates'] == []
    assert validation['verdict'] == 'ACCEPT'
    assert validation['forbidden_columns'] == []
    assert manifest['verdict'] == 'ACCEPT'
    assert catalog['datasets']['intraday_retained_chip_state_v1']['metadata']['schema_version'] == 'intraday_retained_chip_state_v1_p0'
    assert (output_root / 'trade_date=20250103' / 'part.parquet').exists()
