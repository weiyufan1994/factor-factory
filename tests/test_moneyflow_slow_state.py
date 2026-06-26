from __future__ import annotations

import numpy as np
import pandas as pd

import factor_factory.data_api as data_api
import factor_factory.data_api.moneyflow_slow_state as slow_state
from factor_factory.data_api.moneyflow_slow_state import (
    MoneyflowSlowStateParams,
    build_moneyflow_slow_state_qa,
    derive_moneyflow_slow_state_v1,
)


def test_moneyflow_slow_state_is_exported_from_data_api_package():
    assert data_api.MoneyflowSlowStateParams is MoneyflowSlowStateParams
    assert data_api.derive_moneyflow_slow_state_v1 is derive_moneyflow_slow_state_v1
    assert data_api.build_moneyflow_slow_state_qa is build_moneyflow_slow_state_qa


def test_moneyflow_slow_state_recurs_by_stock_cutoff_and_lambda_without_year_reset():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ', '000001.SZ', '000001.SZ', '000001.SZ', '000002.SZ'],
        'trade_date': ['20241231', '20250102', '20250711', '20250714', '20250102', '20250102'],
        'cutoff_time': ['14:50:00', '14:50:00', '14:50:00', '14:50:00', '14:00:00', '14:50:00'],
        'v18a_z': [1.0, 2.0, 3.0, 4.0, 99.0, 5.0],
        'v18b_z': [1.0, -1.0, 0.5, 2.0, 99.0, -0.5],
        'v19d_score': [10.0, 30.0, 50.0, 70.0, 999.0, 100.0],
    })
    params = MoneyflowSlowStateParams(lambdas=(0.5,), cutoff_times=('14:50:00',), is_end_date='20250711')

    out = derive_moneyflow_slow_state_v1(frame, params)

    assert out.attrs['dataset_id'] == 'moneyflow_slow_state_v1'
    assert out.attrs['operator_backend'] == 'reference'
    assert out.duplicated(['ts_code', 'trade_date', 'cutoff_time', 'lambda']).sum() == 0
    stock = out[out['ts_code'] == '000001.SZ'].sort_values('trade_date').reset_index(drop=True)
    assert stock['trade_date'].tolist() == ['20241231', '20250102', '20250711', '20250714']
    np.testing.assert_allclose(stock['h_slow_state'].to_numpy(), np.array([10.0, 20.0, 35.0, 52.5]), rtol=1e-12, atol=1e-12)
    assert stock['research_window'].tolist() == ['IS', 'IS', 'IS', 'OOS']
    assert stock['v20a_score'].tolist() == stock['h_slow_state'].tolist()
    assert pd.isna(stock.loc[1, 'v20b_score'])
    assert stock.loc[2, 'v20b_score'] == stock.loc[2, 'h_slow_state']
    assert stock['state_source'].eq('prior_state_continuous').all()
    assert stock['no_future_data'].eq(True).all()
    assert stock['state_init_policy'].eq('first_finite_signal').all()


def test_moneyflow_slow_state_emits_multiple_lambda_paths_with_independent_keys():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ'],
        'trade_date': ['20240102', '20240103'],
        'cutoff_time': ['14:50:00', '14:50:00'],
        'v18a_z': [0.1, 0.2],
        'v18b_z': [1.0, 1.0],
        'v19d_score': [10.0, 30.0],
    })
    params = MoneyflowSlowStateParams(lambdas=(0.5, 0.8), cutoff_times=('14:50:00',))

    out = derive_moneyflow_slow_state_v1(frame, params)

    assert sorted(out['lambda'].unique().tolist()) == [0.5, 0.8]
    slow_05 = out[out['lambda'] == 0.5].sort_values('trade_date')
    slow_08 = out[out['lambda'] == 0.8].sort_values('trade_date')
    np.testing.assert_allclose(slow_05['h_slow_state'].to_numpy(), np.array([10.0, 20.0]), rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(slow_08['h_slow_state'].to_numpy(), np.array([10.0, 14.0]), rtol=1e-12, atol=1e-12)


def test_moneyflow_slow_state_reference_and_process_sharded_match_array_backend():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'] * 4,
        'trade_date': ['20240102', '20240103', '20240104', '20240105'] * 2,
        'cutoff_time': ['14:50:00'] * 8,
        'v18a_z': [0.1, 0.2, 0.3, 0.4, 1.1, 1.2, 1.3, 1.4],
        'v18b_z': [1.0, -1.0, 1.0, 1.0, -1.0, 1.0, 1.0, -1.0],
        'v19d_score': [10.0, 30.0, 50.0, 70.0, 100.0, 80.0, 60.0, 40.0],
    })
    base_params = {'lambdas': (0.5, 0.8), 'cutoff_times': ('14:50:00',)}

    reference = derive_moneyflow_slow_state_v1(frame, MoneyflowSlowStateParams(**base_params, operator_backend='reference'))
    array_grouped = derive_moneyflow_slow_state_v1(frame, MoneyflowSlowStateParams(**base_params, operator_backend='array_grouped'))
    process = derive_moneyflow_slow_state_v1(frame, MoneyflowSlowStateParams(**base_params, operator_backend='process_sharded_array_grouped'))

    assert reference.attrs['operator_backend'] == 'reference'
    assert process.attrs['operator_backend'] == 'process_sharded_array_grouped_ema_state'
    comparable = ['ts_code', 'trade_date', 'cutoff_time', 'lambda', 'h_slow_state', 'v20a_score', 'v20b_score']
    pd.testing.assert_frame_equal(reference[comparable], array_grouped[comparable], check_dtype=False)
    pd.testing.assert_frame_equal(process[comparable], array_grouped[comparable], check_dtype=False)


def test_moneyflow_slow_state_passes_max_workers_to_process_backend(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ'],
        'trade_date': ['20240102', '20240103'],
        'cutoff_time': ['14:50:00', '14:50:00'],
        'v18a_z': [0.1, 0.2],
        'v18b_z': [1.0, 1.0],
        'v19d_score': [10.0, 30.0],
    })
    calls = []

    def fake_grouped_ema(input_frame, **kwargs):
        calls.append(kwargs)
        out = input_frame.copy()
        out[kwargs['output_col']] = [10.0, 20.0]
        out.attrs['operator_backend'] = 'process_sharded_array_grouped_ema_state'
        return out

    monkeypatch.setattr(slow_state, 'grouped_ema_state_by_group', fake_grouped_ema)

    out = derive_moneyflow_slow_state_v1(
        frame,
        MoneyflowSlowStateParams(
            lambdas=(0.5,),
            cutoff_times=('14:50:00',),
            operator_backend='process_sharded_array_grouped',
            max_workers=3,
        ),
    )

    assert calls[0]['max_workers'] == 3
    assert out.attrs['operator_backend'] == 'process_sharded_array_grouped_ema_state'


def test_moneyflow_slow_state_qa_blocks_duplicate_unique_keys():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ', '000001.SZ'],
        'trade_date': ['20240102', '20240102'],
        'cutoff_time': ['14:50:00', '14:50:00'],
        'v18a_z': [0.1, 0.1],
        'v18b_z': [1.0, 1.0],
        'v19d_score': [10.0, 10.0],
    })
    state = derive_moneyflow_slow_state_v1(frame, MoneyflowSlowStateParams(lambdas=(0.5,), cutoff_times=('14:50:00',)))

    qa = build_moneyflow_slow_state_qa(state)

    assert qa['verdict'] == 'BLOCK'
    assert qa['duplicate_key_count'] == 1
    assert qa['source_dataset'] == 'intraday_flow_distribution_moments_v1'
