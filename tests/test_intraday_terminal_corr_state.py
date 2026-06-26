from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.intraday_terminal_corr_state import (
    DATASET_ID,
    IntradayTerminalCorrStateParams,
    build_intraday_terminal_corr_state_qa,
    derive_intraday_terminal_corr_state,
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
    for ts_code, base in [('000001.SZ', 10.0), ('000002.SZ', 20.0)]:
        for idx in range(1, 7):
            close = base + idx * (1 if ts_code == '000001.SZ' else -0.5)
            rows.append({
                'ts_code': ts_code,
                'trade_date': '20240103',
                'trade_time': f'09:3{idx}:00',
                'open': close - 0.1,
                'close': close,
                'vol': 1000.0 + idx * 10.0,
                'amount': (1000.0 + idx * 10.0) * close,
            })
        rows.append({
            'ts_code': ts_code,
            'trade_date': '20240103',
            'trade_time': '14:56:00',
            'open': 999.0,
            'close': 1000.0,
            'vol': 9999.0,
            'amount': 9999000.0,
        })
    return pd.DataFrame(rows)


def test_terminal_corr_state_uses_cutoff_minutes_only():
    params = IntradayTerminalCorrStateParams(cutoff_times=('09:36:00',), windows=(3,), min_minutes=3, operator_backend='numpy')
    baseline = derive_intraday_terminal_corr_state(sample_minute_frame(), params=params)
    changed_future = sample_minute_frame()
    changed_future.loc[changed_future['trade_time'] == '14:56:00', ['open', 'close', 'vol', 'amount']] = [1.0, 2.0, 3.0, 4.0]
    changed = derive_intraday_terminal_corr_state(changed_future, params=params)

    assert DATASET_ID == 'intraday_terminal_corr_state_v1'
    pd.testing.assert_frame_equal(
        baseline[['ts_code', 'trade_date', 'cutoff_time', 'window_id', 'close_amount_corr', 'ret_amount_corr']],
        changed[['ts_code', 'trade_date', 'cutoff_time', 'window_id', 'close_amount_corr', 'ret_amount_corr']],
    )
    assert baseline['no_future_intraday_minutes'].eq(True).all()
    assert baseline['window_id'].unique().tolist() == ['3m']


def test_terminal_corr_state_array_grouped_matches_numpy_backend():
    params = {'cutoff_times': ('09:36:00',), 'windows': (3, 5), 'min_minutes': 3}
    numpy_out = derive_intraday_terminal_corr_state(sample_minute_frame(), params=IntradayTerminalCorrStateParams(**params, operator_backend='numpy'))
    array_out = derive_intraday_terminal_corr_state(sample_minute_frame(), params=IntradayTerminalCorrStateParams(**params, operator_backend='array_grouped'))

    comparable = ['ts_code', 'trade_date', 'cutoff_time', 'window_id', 'bar_count', 'close_amount_corr', 'ret_amount_corr']
    pd.testing.assert_frame_equal(numpy_out[comparable], array_out[comparable], check_dtype=False)
    assert array_out['operator_backend'].eq('array_grouped_terminal').all()


def test_terminal_corr_state_qa_blocks_duplicate_keys():
    state = derive_intraday_terminal_corr_state(
        sample_minute_frame(),
        params=IntradayTerminalCorrStateParams(cutoff_times=('09:36:00',), windows=(3,), min_minutes=3),
    )
    duplicated = pd.concat([state, state.head(1)], ignore_index=True)

    qa = build_intraday_terminal_corr_state_qa(duplicated)

    assert qa['verdict'] == 'BLOCK'
    assert qa['duplicate_key_count'] == 1


def test_build_and_validate_terminal_corr_state_partitioned_output(tmp_path: Path):
    pytest.importorskip('pyarrow')
    builder = _load_script('build_intraday_terminal_corr_state.py')
    validator = _load_script('validate_intraday_terminal_corr_state.py')
    input_path = tmp_path / 'minute.parquet'
    output_root = tmp_path / 'intraday_terminal_corr_state_v1'
    qa_path = tmp_path / 'terminal.qa.json'
    catalog_path = tmp_path / 'terminal.catalog.json'
    validation_path = tmp_path / 'terminal.validation.json'
    manifest_path = tmp_path / 'terminal.manifest.json'
    sample_minute_frame().to_parquet(input_path, index=False)

    assert builder.main([
        '--minute-path',
        str(input_path),
        '--start',
        '20240103',
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
        '--cutoff-times',
        '09:36:00',
        '--windows',
        '3,5',
        '--min-minutes',
        '3',
        '--operator-backend',
        'array_grouped',
    ]) == 0
    assert validator.main([
        '--feature-parquet',
        str(output_root),
        '--qa-path',
        str(qa_path),
        '--output-path',
        str(validation_path),
        '--min-row-count',
        '4',
        '--max-warm-read-seconds',
        '10',
    ]) == 0

    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert qa['verdict'] == 'ACCEPT'
    assert qa['row_count'] == 4
    assert qa['operator_backend'] == 'array_grouped_terminal'
    assert validation['verdict'] == 'ACCEPT'
    assert manifest['verdict'] == 'ACCEPT'

    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(
            'intraday_terminal_corr_state_v1',
            '20240103',
            '20240103',
            'a_share_all',
            ['cutoff_time', 'window_id', 'close_amount_corr', 'ret_amount_corr'],
            frequency='intraday_cutoff',
        )
    )
    assert result.status == 'ready'
    assert result.coverage.row_count == 4
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == ['ts_code', 'trade_date', 'cutoff_time', 'window_id', 'close_amount_corr', 'ret_amount_corr']
