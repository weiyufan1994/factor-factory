from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.smart_money_intraday_state import (
    DATASET_ID,
    SmartMoneyIntradayStateParams,
    build_smart_money_intraday_state_qa,
    derive_smart_money_intraday_state,
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


def sample_minute_frame() -> pd.DataFrame:
    rows = []
    for trade_date, offset in [('20240102', 0.0), ('20240103', 0.4), ('20240104', 99.0)]:
        for ts_code, base in [('000001.SZ', 10.0 + offset), ('000002.SZ', 20.0 + offset)]:
            for idx in range(1, 7):
                open_px = base + idx * 0.02
                direction = 1 if ts_code == '000001.SZ' else -1
                close = open_px * (1.0 + direction * 0.001 * idx)
                vol = 1000.0 + idx * 100.0
                rows.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'trade_time': f'09:3{idx}:00',
                    'open': open_px,
                    'close': close,
                    'vol': vol,
                    'amount': vol * close,
                })
    return pd.DataFrame(rows)


def test_smart_money_state_uses_only_dates_through_target():
    params = SmartMoneyIntradayStateParams(lookback_trading_days=2, min_valid_minutes=3)
    baseline = derive_smart_money_intraday_state(sample_minute_frame(), target_dates=['20240103'], params=params)
    changed_future = sample_minute_frame()
    changed_future.loc[changed_future['trade_date'] == '20240104', ['open', 'close', 'vol', 'amount']] = [1.0, 1000.0, 999999.0, 999999000.0]
    changed = derive_smart_money_intraday_state(changed_future, target_dates=['20240103'], params=params)

    assert DATASET_ID == 'smart_money_intraday_state_v1'
    comparable = [
        'ts_code',
        'trade_date',
        'q_log_volume',
        'q_beta_0p1',
        'q_beta_0p25',
        'q_original_beta_0p5',
        'q_volume_only',
        'q_rank_absret_plus_rankvol',
        'selected_volume_share',
        'selected_minute_count',
    ]
    pd.testing.assert_frame_equal(baseline[comparable], changed[comparable])
    assert baseline['source_max_date'].eq('20240103').all()
    assert baseline['no_future_data'].eq(True).all()
    assert baseline['no_future_intraday_minutes'].eq(True).all()


def test_smart_money_state_qa_blocks_duplicate_keys():
    state = derive_smart_money_intraday_state(
        sample_minute_frame(),
        target_dates=['20240103'],
        params=SmartMoneyIntradayStateParams(lookback_trading_days=2, min_valid_minutes=3),
    )
    duplicated = pd.concat([state, state.head(1)], ignore_index=True)

    qa = build_smart_money_intraday_state_qa(duplicated)

    assert qa['verdict'] == 'BLOCK'
    assert qa['duplicate_key_count'] == 1


def test_build_smart_money_state_partitioned_output(tmp_path: Path):
    pytest.importorskip('pyarrow')
    builder = _load_script('build_smart_money_intraday_state.py')
    input_path = tmp_path / 'minute.parquet'
    output_root = tmp_path / 'smart_money_intraday_state_v1'
    qa_path = tmp_path / 'smart_money.qa.json'
    catalog_path = tmp_path / 'smart_money.catalog.json'
    manifest_path = tmp_path / 'smart_money.manifest.json'
    sample_minute_frame().to_parquet(input_path, index=False)

    assert builder.main([
        '--minute-path',
        str(input_path),
        '--start',
        '20240102',
        '--end',
        '20240103',
        '--output-root',
        str(output_root),
        '--qa-output',
        str(qa_path),
        '--catalog-output',
        str(catalog_path),
        '--manifest-output',
        str(manifest_path),
        '--lookback-trading-days',
        '2',
        '--min-valid-minutes',
        '3',
        '--research-window',
        'SMOKE',
    ]) == 0

    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert qa['verdict'] == 'ACCEPT'
    assert qa['row_count'] == 4
    assert qa['duplicate_key_count'] == 0
    assert manifest['verdict'] == 'ACCEPT'

    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(
            'smart_money_intraday_state_v1',
            '20240102',
            '20240103',
            'a_share_all',
            ['q_log_volume', 'q_beta_0p1', 'vwap_smart_log_volume', 'vwap_all'],
            frequency='day',
        )
    )
    assert result.status == 'ready'
    assert result.coverage.row_count == 4
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == ['ts_code', 'trade_date', 'q_log_volume', 'q_beta_0p1', 'vwap_smart_log_volume', 'vwap_all']
