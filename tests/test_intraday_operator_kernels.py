from __future__ import annotations

import numpy as np
import pandas as pd

import factor_factory.data_api.intraday_operator_kernels as kernels
from factor_factory.data_api.intraday_operator_kernels import (
    cpv_price_volume_corr_state,
    group_offsets_from_sorted_codes,
    group_offsets_from_sorted_frame,
    grouped_ema_state_arrays,
    grouped_ema_state_by_group,
    intraday_occupation_location_state,
    rolling_corr_1d,
    rolling_corr_by_group,
    terminal_ema_state_arrays,
    terminal_ema_state_by_group,
    terminal_rolling_corr_by_group,
)


def test_group_offsets_from_sorted_codes_handles_empty_and_contiguous_groups():
    empty = group_offsets_from_sorted_codes([])
    assert empty.starts.tolist() == []
    assert empty.ends.tolist() == []
    assert empty.sizes.tolist() == []

    offsets = group_offsets_from_sorted_codes(['a', 'a', 'b', 'b', 'b', 'c'])

    assert offsets.starts.tolist() == [0, 2, 5]
    assert offsets.ends.tolist() == [2, 5, 6]
    assert offsets.sizes.tolist() == [2, 3, 1]


def test_group_offsets_from_sorted_frame_supports_multi_key_groups():
    frame = pd.DataFrame({
        'trade_date': ['20240104', '20240104', '20240104', '20240105'],
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ', '000001.SZ'],
        'value': [1, 2, 3, 4],
    })

    offsets = group_offsets_from_sorted_frame(frame, ['trade_date', 'ts_code'])

    assert offsets.starts.tolist() == [0, 2, 3]
    assert offsets.ends.tolist() == [2, 3, 4]
    assert offsets.sizes.tolist() == [2, 1, 1]


def test_group_offsets_from_sorted_frame_avoids_multiindex_factorize(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104', '20240104', '20240105'],
        'ts_code': ['000001.SZ', '000002.SZ', '000001.SZ'],
    })

    def fail_from_frame(*args, **kwargs):
        raise AssertionError('sorted offset helper should compare adjacent columns directly')

    monkeypatch.setattr(pd.MultiIndex, 'from_frame', fail_from_frame)

    offsets = group_offsets_from_sorted_frame(frame, ['trade_date', 'ts_code'])

    assert offsets.starts.tolist() == [0, 1, 2]
    assert offsets.ends.tolist() == [1, 2, 3]


def test_rolling_corr_numpy_matches_pandas_rolling_corr():
    x = np.array([1.0, 2.0, 3.0, 5.0, 8.0, 13.0], dtype=float)
    y = np.array([2.0, 1.0, 4.0, 7.0, 11.0, 18.0], dtype=float)

    result = rolling_corr_1d(x, y, window=3, backend='numpy')
    expected = pd.Series(x).rolling(3).corr(pd.Series(y)).fillna(0.0).to_numpy()

    assert result.backend == 'numpy'
    np.testing.assert_allclose(result.values, expected, rtol=1e-12, atol=1e-12)


def test_rolling_corr_handles_constant_window_as_zero_not_nan():
    x = np.array([1.0, 1.0, 1.0, 2.0], dtype=float)
    y = np.array([2.0, 3.0, 4.0, 5.0], dtype=float)

    result = rolling_corr_1d(x, y, window=3, backend='numpy')

    assert np.isfinite(result.values).all()
    assert result.values[2] == 0.0


def test_rolling_corr_auto_reports_realized_backend():
    x = np.linspace(1.0, 20.0, 20)
    y = x[::-1].copy()

    result = rolling_corr_1d(x, y, window=5, backend='auto')

    assert result.backend in {'numpy', 'numba'}
    assert result.values.shape == x.shape


def test_rolling_corr_grouped_arrays_matches_dataframe_wrapper():
    starts = np.array([0, 4], dtype=np.int64)
    ends = np.array([4, 8], dtype=np.int64)
    price = np.array([1.0, 2.0, 3.0, 4.0, 4.0, 3.0, 2.0, 1.0], dtype=np.float64)
    volume = np.array([4.0, 3.0, 2.0, 1.0, 1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'] * 4,
        'hhmmss': [93100, 93200, 93300, 93400] * 2,
        'price': price,
        'volume': volume,
    })

    expected = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_corr',
        backend='array_grouped',
    )
    actual = kernels.rolling_corr_grouped_arrays(
        starts,
        ends,
        price,
        volume,
        window=3,
        backend='array_grouped',
    )

    assert actual.backend == 'array_grouped'
    np.testing.assert_allclose(actual.values, expected['cpv_corr'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_terminal_corr_grouped_arrays_matches_dataframe_wrapper():
    starts = np.array([0, 3], dtype=np.int64)
    ends = np.array([3, 6], dtype=np.int64)
    price = np.array([1.0, 2.0, 3.0, 5.0, 7.0, 11.0], dtype=np.float64)
    volume = np.array([3.0, 2.0, 1.0, 2.0, 4.0, 8.0], dtype=np.float64)
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': price,
        'volume': volume,
    })

    expected = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='array_grouped',
    )
    actual = kernels.terminal_corr_grouped_arrays(
        starts,
        ends,
        price,
        volume,
        window=3,
        backend='array_grouped',
    )

    assert actual.backend == 'array_grouped_terminal'
    np.testing.assert_allclose(actual.values, expected['terminal_corr'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_grouped_ema_state_arrays_computes_independent_group_recursion():
    starts = np.array([0, 3], dtype=np.int64)
    ends = np.array([3, 6], dtype=np.int64)
    signal = np.array([10.0, 20.0, 30.0, 100.0, 80.0, 60.0], dtype=np.float64)

    result = grouped_ema_state_arrays(starts, ends, signal, decay=0.5, backend='array_grouped')

    assert result.backend == 'array_grouped_ema_state'
    np.testing.assert_allclose(
        result.values,
        np.array([10.0, 15.0, 22.5, 100.0, 90.0, 75.0], dtype=np.float64),
        rtol=1e-12,
        atol=1e-12,
    )


def test_terminal_ema_state_arrays_matches_last_full_group_state():
    starts = np.array([0, 4], dtype=np.int64)
    ends = np.array([4, 8], dtype=np.int64)
    signal = np.array([10.0, 20.0, np.nan, 30.0, 100.0, np.nan, 80.0, 60.0], dtype=np.float64)

    full = grouped_ema_state_arrays(starts, ends, signal, decay=0.5, backend='array_grouped')
    terminal = terminal_ema_state_arrays(starts, ends, signal, decay=0.5, backend='array_grouped')

    assert terminal.backend == 'array_grouped_ema_terminal'
    np.testing.assert_allclose(terminal.values, full.values[ends - 1], rtol=1e-12, atol=1e-12)


def test_terminal_ema_state_by_group_uses_terminal_state_not_full_vector(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104', '20240104', '20240104', '20240104', '20240105', '20240105'],
        'ts_code': ['000002.SZ', '000001.SZ', '000002.SZ', '000001.SZ', '000001.SZ', '000001.SZ'],
        'hhmmss': [93100, 93100, 93200, 93200, 93100, 93200],
        'signal': [100.0, 10.0, 80.0, 20.0, 30.0, 50.0],
    })

    def fail_full_vector(*args, **kwargs):
        raise AssertionError('terminal EMA must not call full grouped_ema_state_arrays')

    monkeypatch.setattr(kernels, 'grouped_ema_state_arrays', fail_full_vector)

    out = terminal_ema_state_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        signal_col='signal',
        decay=0.5,
        output_col='terminal_h',
        backend='array_grouped',
    )

    assert out.attrs['operator_backend'] == 'array_grouped_ema_terminal'
    assert out[['trade_date', 'ts_code']].to_dict('records') == [
        {'trade_date': '20240104', 'ts_code': '000001.SZ'},
        {'trade_date': '20240104', 'ts_code': '000002.SZ'},
        {'trade_date': '20240105', 'ts_code': '000001.SZ'},
    ]
    assert out['terminal_order'].tolist() == [93200, 93200, 93200]
    assert out['bar_count'].tolist() == [2, 2, 2]
    np.testing.assert_allclose(out['terminal_h'].to_numpy(), np.array([15.0, 90.0, 40.0]), rtol=1e-12, atol=1e-12)


def test_grouped_ema_state_by_group_preserves_input_order_and_group_boundaries():
    frame = pd.DataFrame({
        'ts_code': ['000002.SZ', '000001.SZ', '000002.SZ', '000001.SZ', '000002.SZ', '000001.SZ'],
        'trade_date': ['20240105', '20240104', '20240104', '20240106', '20240106', '20240105'],
        'signal': [60.0, 10.0, 100.0, 30.0, 80.0, 20.0],
    })

    out = grouped_ema_state_by_group(
        frame,
        group_col='ts_code',
        order_col='trade_date',
        signal_col='signal',
        decay=0.5,
        output_col='h_state',
        backend='array_grouped',
    )

    assert out.attrs['operator_backend'] == 'array_grouped_ema_state'
    assert out['ts_code'].tolist() == frame['ts_code'].tolist()
    assert out['trade_date'].tolist() == frame['trade_date'].tolist()
    np.testing.assert_allclose(
        out['h_state'].to_numpy(),
        np.array([80.0, 10.0, 100.0, 22.5, 80.0, 15.0], dtype=np.float64),
        rtol=1e-12,
        atol=1e-12,
    )


def test_grouped_ema_state_by_group_numba_grouped_matches_array_when_available():
    try:
        import numba  # noqa: F401
    except Exception:
        return
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'] * 4,
        'trade_date': ['20240104', '20240105', '20240106', '20240107'] * 2,
        'signal': [10.0, 20.0, np.nan, 40.0, 100.0, 80.0, 60.0, 40.0],
    })

    expected = grouped_ema_state_by_group(
        frame,
        group_col='ts_code',
        order_col='trade_date',
        signal_col='signal',
        decay=0.7,
        output_col='h_state',
        backend='array_grouped',
    )
    actual = grouped_ema_state_by_group(
        frame,
        group_col='ts_code',
        order_col='trade_date',
        signal_col='signal',
        decay=0.7,
        output_col='h_state',
        backend='numba_grouped',
    )

    assert actual.attrs['operator_backend'] == 'numba_grouped_ema_state'
    np.testing.assert_allclose(actual['h_state'].to_numpy(), expected['h_state'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_grouped_ema_state_by_group_process_sharded_matches_array_grouped():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'] * 4 + ['000003.SZ'] * 4,
        'trade_date': ['20240104', '20240105', '20240106', '20240107'] * 3,
        'signal': [10.0, 20.0, np.nan, 40.0, 100.0, 80.0, 60.0, 40.0, 1.0, 2.0, 4.0, 8.0],
    })

    expected = grouped_ema_state_by_group(
        frame,
        group_col='ts_code',
        order_col='trade_date',
        signal_col='signal',
        decay=0.7,
        output_col='h_state',
        backend='array_grouped',
    )
    actual = grouped_ema_state_by_group(
        frame,
        group_col='ts_code',
        order_col='trade_date',
        signal_col='signal',
        decay=0.7,
        output_col='h_state',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert actual.attrs['operator_backend'] == 'process_sharded_array_grouped_ema_state'
    assert actual['ts_code'].tolist() == frame['ts_code'].tolist()
    np.testing.assert_allclose(actual['h_state'].to_numpy(), expected['h_state'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_grouped_ema_state_by_group_process_sharded_uses_coarse_shard_builder(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'trade_date': ['20240104', '20240105', '20240106'] * 2,
        'signal': [10.0, 20.0, 30.0, 100.0, 80.0, 60.0],
    })
    calls = {'builder': 0, 'shard': 0}

    def fake_builder(input_frame, group_cols, shard_count):
        calls['builder'] += 1
        assert group_cols == ['ts_code']
        assert shard_count == 1
        return [input_frame]

    def fake_shard(payload):
        calls['shard'] += 1
        shard = payload['frame']
        output_col = payload['output_col']
        out = shard.copy()
        out[output_col] = np.arange(len(shard), dtype=np.float64)
        return out.index, out[output_col].to_numpy(dtype=np.float64)

    monkeypatch.setattr(kernels, '_build_coarse_group_shards', fake_builder, raising=False)
    monkeypatch.setattr(kernels, '_ema_state_array_grouped_shard', fake_shard, raising=False)

    out = grouped_ema_state_by_group(
        frame,
        group_col='ts_code',
        order_col='trade_date',
        signal_col='signal',
        decay=0.5,
        output_col='h_state',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert calls == {'builder': 1, 'shard': 1}
    assert out.attrs['operator_backend'] == 'process_sharded_array_grouped_ema_state'
    np.testing.assert_array_equal(out['h_state'].to_numpy(), np.arange(6, dtype=np.float64))


def test_rolling_corr_by_group_preserves_rows_and_avoids_cross_stock_leakage():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'] * 4,
        'hhmmss': [93100, 93200, 93300, 93400] * 2,
        'price': [1.0, 2.0, 3.0, 4.0, 10.0, 10.0, 10.0, 10.0],
        'volume': [1.0, 2.0, 3.0, 4.0, 4.0, 3.0, 2.0, 1.0],
    })

    out = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_corr',
        backend='numpy',
    )

    assert len(out) == len(frame)
    assert out['ts_code'].tolist() == frame['ts_code'].tolist()
    assert out.loc[2, 'cpv_corr'] == 1.0
    assert out.loc[6, 'cpv_corr'] == 0.0
    assert out.attrs['operator_backend'] == 'numpy'


def test_rolling_corr_by_group_numba_grouped_matches_numpy_when_available():
    try:
        import numba  # noqa: F401
    except Exception:
        return
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 6 + ['000002.SZ'] * 6 + ['000003.SZ'] * 6,
        'hhmmss': [93100, 93200, 93300, 93400, 93500, 93600] * 3,
        'price': [1.0, 2.0, 4.0, 7.0, 11.0, 16.0, 3.0, 3.0, 3.0, 4.0, 5.0, 6.0, 10.0, 9.0, 7.0, 4.0, 2.0, 1.0],
        'volume': [1.0, 3.0, 2.0, 8.0, 13.0, 21.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
    })

    expected = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr',
        backend='numpy',
    )
    actual = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr',
        backend='numba_grouped',
    )

    assert actual.attrs['operator_backend'] == 'numba_grouped'
    np.testing.assert_allclose(actual['cpv_corr'].to_numpy(), expected['cpv_corr'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_rolling_corr_by_group_threaded_grouped_matches_numpy():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 6 + ['000002.SZ'] * 6 + ['000003.SZ'] * 6,
        'hhmmss': [93100, 93200, 93300, 93400, 93500, 93600] * 3,
        'price': [1.0, 2.0, 4.0, 7.0, 11.0, 16.0, 3.0, 3.0, 3.0, 4.0, 5.0, 6.0, 10.0, 9.0, 7.0, 4.0, 2.0, 1.0],
        'volume': [1.0, 3.0, 2.0, 8.0, 13.0, 21.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
    })

    expected = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr',
        backend='numpy',
    )
    actual = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr',
        backend='threaded_grouped',
        max_workers=2,
    )

    assert actual.attrs['operator_backend'] == 'threaded_grouped'
    np.testing.assert_allclose(actual['cpv_corr'].to_numpy(), expected['cpv_corr'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_rolling_corr_by_group_array_grouped_matches_numpy_and_preserves_input_order():
    frame = pd.DataFrame({
        'ts_code': ['000002.SZ', '000001.SZ', '000002.SZ', '000001.SZ', '000002.SZ', '000001.SZ'],
        'hhmmss': [93200, 93100, 93100, 93300, 93300, 93200],
        'price': [7.0, 1.0, 5.0, 3.0, 11.0, 2.0],
        'volume': [4.0, 3.0, 1.0, 1.0, 9.0, 2.0],
    })
    expected = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_corr',
        backend='numpy',
    )

    actual = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_corr',
        backend='array_grouped',
    )

    assert actual.attrs['operator_backend'] == 'array_grouped'
    assert actual['ts_code'].tolist() == frame['ts_code'].tolist()
    assert actual['hhmmss'].tolist() == frame['hhmmss'].tolist()
    np.testing.assert_allclose(actual['cpv_corr'].to_numpy(), expected['cpv_corr'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_rolling_corr_by_group_array_grouped_avoids_per_group_vector_kernel(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'] * 4,
        'hhmmss': [93100, 93200, 93300, 93400] * 2,
        'price': [1.0, 2.0, 3.0, 4.0, 4.0, 3.0, 2.0, 1.0],
        'volume': [4.0, 3.0, 2.0, 1.0, 1.0, 2.0, 3.0, 4.0],
    })

    def fail_per_group_vector_kernel(*_args, **_kwargs):
        raise AssertionError('array_grouped backend must not call rolling_corr_1d per group')

    monkeypatch.setattr(kernels, 'rolling_corr_1d', fail_per_group_vector_kernel)

    out = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_corr',
        backend='array_grouped',
    )

    assert out.attrs['operator_backend'] == 'array_grouped'
    assert np.isfinite(out['cpv_corr']).all()


def test_rolling_corr_by_group_array_grouped_uses_whole_array_grouped_kernel(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'] * 4,
        'hhmmss': [93100, 93200, 93300, 93400] * 2,
        'price': [1.0, 2.0, 3.0, 4.0, 4.0, 3.0, 2.0, 1.0],
        'volume': [4.0, 3.0, 2.0, 1.0, 1.0, 2.0, 3.0, 4.0],
    })
    calls = {'count': 0}

    def fail_per_group_helper(*_args, **_kwargs):
        raise AssertionError('array_grouped backend must not call per-group vectorized helper')

    def fake_whole_array_helper(starts, ends, x, y, window):
        calls['count'] += 1
        assert int(window) == 3
        np.testing.assert_array_equal(starts, np.array([0, 4], dtype=np.int64))
        np.testing.assert_array_equal(ends, np.array([4, 8], dtype=np.int64))
        assert len(x) == 8
        assert len(y) == 8
        return np.arange(8, dtype=np.float64)

    monkeypatch.setattr(kernels, '_rolling_corr_group_vectorized_numpy', fail_per_group_helper)
    monkeypatch.setattr(kernels, '_rolling_corr_grouped_vectorized_numpy', fake_whole_array_helper, raising=False)

    out = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_corr',
        backend='array_grouped',
    )

    assert calls['count'] == 1
    assert out.attrs['operator_backend'] == 'array_grouped'
    assert out['cpv_corr'].tolist() == list(np.arange(8, dtype=np.float64))


def test_rolling_corr_by_group_process_sharded_array_grouped_matches_numpy():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 6 + ['000002.SZ'] * 6 + ['000003.SZ'] * 6 + ['000004.SZ'] * 6,
        'hhmmss': [93100, 93200, 93300, 93400, 93500, 93600] * 4,
        'price': [
            1.0, 2.0, 4.0, 7.0, 11.0, 16.0,
            3.0, 3.0, 3.0, 4.0, 5.0, 6.0,
            10.0, 9.0, 7.0, 4.0, 2.0, 1.0,
            6.0, 8.0, 9.0, 13.0, 12.0, 15.0,
        ],
        'volume': [
            1.0, 3.0, 2.0, 8.0, 13.0, 21.0,
            9.0, 8.0, 7.0, 6.0, 5.0, 4.0,
            1.0, 2.0, 4.0, 8.0, 16.0, 32.0,
            11.0, 7.0, 10.0, 5.0, 6.0, 12.0,
        ],
    })
    expected = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr',
        backend='numpy',
    )

    actual = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert actual.attrs['operator_backend'] == 'process_sharded_array_grouped'
    assert actual['ts_code'].tolist() == frame['ts_code'].tolist()
    np.testing.assert_allclose(actual['cpv_corr'].to_numpy(), expected['cpv_corr'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_rolling_corr_by_group_process_sharded_array_grouped_uses_shard_helper(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
        'volume': [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
    })
    calls = {'count': 0}

    def fake_shard(payload):
        calls['count'] += 1
        shard = payload['frame']
        return shard.index, np.arange(len(shard), dtype=np.float64)

    monkeypatch.setattr(kernels, '_rolling_corr_array_grouped_shard', fake_shard, raising=False)

    out = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=2,
        output_col='cpv_corr',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert calls['count'] == 1
    assert out.attrs['operator_backend'] == 'process_sharded_array_grouped'
    np.testing.assert_array_equal(out['cpv_corr'].to_numpy(), np.arange(6, dtype=np.float64))


def test_rolling_corr_by_group_process_sharded_array_grouped_uses_coarse_shard_builder(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
        'volume': [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
    })
    calls = {'builder': 0, 'shard': 0}

    def fake_builder(input_frame, group_cols, shard_count):
        calls['builder'] += 1
        assert group_cols == ['ts_code']
        assert shard_count == 1
        return [input_frame]

    def fake_shard(payload):
        calls['shard'] += 1
        shard = payload['frame']
        return shard.index, np.arange(len(shard), dtype=np.float64)

    monkeypatch.setattr(kernels, '_build_coarse_group_shards', fake_builder, raising=False)
    monkeypatch.setattr(kernels, '_rolling_corr_array_grouped_shard', fake_shard, raising=False)

    out = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=2,
        output_col='cpv_corr',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert calls == {'builder': 1, 'shard': 1}
    assert out.attrs['operator_backend'] == 'process_sharded_array_grouped'
    np.testing.assert_array_equal(out['cpv_corr'].to_numpy(), np.arange(6, dtype=np.float64))


def test_cpv_price_volume_corr_state_full_reuses_grouped_rolling_backend():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0],
        'volume': [3.0, 2.0, 1.0, 2.0, 4.0, 8.0],
    })
    expected = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_corr',
        backend='array_grouped',
    )

    actual = cpv_price_volume_corr_state(
        frame,
        window=3,
        backend='array_grouped',
        output_col='cpv_corr',
    )

    assert actual.attrs['operator_id'] == 'cpv_price_volume_corr_state'
    assert actual.attrs['operator_backend'] == 'array_grouped'
    assert actual.attrs['source_operator'] == 'rolling_corr_by_group'
    assert actual.attrs['terminal_only'] is False
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_cpv_price_volume_corr_state_terminal_reuses_terminal_backend():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6 + ['20240105'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3 + ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 4,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0, 2.0, 4.0, 8.0, 3.0, 6.0, 12.0],
        'volume': [3.0, 2.0, 1.0, 1.0, 4.0, 9.0, 8.0, 4.0, 2.0, 2.0, 5.0, 10.0],
    })
    expected = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='cpv_terminal_corr',
        backend='array_grouped',
    )

    actual = cpv_price_volume_corr_state(
        frame,
        window=3,
        backend='array_grouped',
        output_col='cpv_terminal_corr',
        terminal_only=True,
    )

    assert actual.attrs['operator_id'] == 'cpv_price_volume_corr_state'
    assert actual.attrs['operator_backend'] == 'array_grouped_terminal'
    assert actual.attrs['source_operator'] == 'terminal_rolling_corr_by_group'
    assert actual.attrs['terminal_only'] is True
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_rolling_corr_by_group_numba_grouped_uses_grouped_kernel(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
        'volume': [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
    })
    calls = {'count': 0}

    def fake_kernel():
        calls['count'] += 1

        def run(_starts, _ends, _x, _y, _window):
            return np.arange(6, dtype=np.float64)

        return run

    monkeypatch.setattr(kernels, '_numba_grouped_rolling_corr_kernel', fake_kernel, raising=False)

    out = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=2,
        output_col='cpv_corr',
        backend='numba_grouped',
    )

    assert calls['count'] == 1
    assert out.attrs['operator_backend'] == 'numba_grouped'
    np.testing.assert_array_equal(out['cpv_corr'].to_numpy(), np.arange(6, dtype=np.float64))


def test_terminal_rolling_corr_by_group_matches_last_full_rolling_value():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 12,
        'ts_code': ['000001.SZ'] * 6 + ['000002.SZ'] * 6,
        'hhmmss': [93100, 93200, 93300, 93400, 93500, 93600] * 2,
        'price': [1.0, 2.0, 4.0, 7.0, 11.0, 16.0, 3.0, 3.0, 3.0, 4.0, 5.0, 6.0],
        'volume': [1.0, 3.0, 2.0, 8.0, 13.0, 21.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0],
    })
    full = rolling_corr_by_group(
        frame,
        group_col='ts_code',
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr',
        backend='numpy',
    ).sort_values(['ts_code', 'hhmmss'])
    expected = full.groupby('ts_code', sort=True).tail(1)[['ts_code', 'cpv_corr']].reset_index(drop=True)

    actual = terminal_rolling_corr_by_group(
        frame,
        group_cols=['ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=4,
        output_col='cpv_corr_terminal',
        backend='numpy',
    )

    assert actual.attrs['operator_backend'] == 'numpy_terminal'
    assert len(actual) == 2
    assert actual['ts_code'].tolist() == expected['ts_code'].tolist()
    np.testing.assert_allclose(actual['cpv_corr_terminal'].to_numpy(), expected['cpv_corr'].to_numpy(), rtol=1e-12, atol=1e-12)


def test_terminal_rolling_corr_by_group_supports_multi_key_threaded_backend():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6 + ['20240105'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3 + ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 4,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0, 2.0, 4.0, 8.0, 3.0, 6.0, 12.0],
        'volume': [3.0, 2.0, 1.0, 1.0, 4.0, 9.0, 8.0, 4.0, 2.0, 2.0, 5.0, 10.0],
    })
    expected = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='numpy',
    )

    actual = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='threaded_grouped',
        max_workers=2,
    )

    assert actual.attrs['operator_backend'] == 'threaded_grouped_terminal'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_terminal_rolling_corr_by_group_array_grouped_matches_numpy():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6 + ['20240105'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3 + ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 4,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0, 2.0, 4.0, 8.0, 3.0, 6.0, 12.0],
        'volume': [3.0, 2.0, 1.0, 1.0, 4.0, 9.0, 8.0, 4.0, 2.0, 2.0, 5.0, 10.0],
    })
    expected = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='numpy',
    )

    actual = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='array_grouped',
    )

    assert actual.attrs['operator_backend'] == 'array_grouped_terminal'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_terminal_rolling_corr_by_group_array_grouped_avoids_dataframe_group_kernel(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 5,
        'ts_code': ['000001.SZ'] * 5,
        'hhmmss': [93100, 93200, 93300, 93400, 93500],
        'price': [1.0, 2.0, 3.0, 4.0, 5.0],
        'volume': [7.0, 6.0, 5.0, 4.0, 3.0],
    })

    def fail_dataframe_group_kernel(*_args, **_kwargs):
        raise AssertionError('array_grouped terminal backend must not use per-group DataFrame kernel')

    monkeypatch.setattr(kernels, '_terminal_corr_for_group', fail_dataframe_group_kernel)

    out = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='array_grouped',
    )

    assert out.attrs['operator_backend'] == 'array_grouped_terminal'
    assert out.loc[0, 'terminal_corr'] == -1.0


def test_terminal_rolling_corr_by_group_array_grouped_uses_grouped_terminal_kernel(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0],
        'volume': [3.0, 2.0, 1.0, 2.0, 4.0, 8.0],
    })

    def fail_per_group_array_kernel(*_args, **_kwargs):
        raise AssertionError('array_grouped terminal backend must not call per-group array kernel')

    monkeypatch.setattr(kernels, '_terminal_corr_from_arrays', fail_per_group_array_kernel)

    out = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='array_grouped',
    )

    assert out.attrs['operator_backend'] == 'array_grouped_terminal'
    np.testing.assert_allclose(out['terminal_corr'].to_numpy(), np.array([-1.0, 1.0]), rtol=1e-12, atol=1e-12)


def test_terminal_rolling_corr_by_group_process_sharded_array_grouped_matches_numpy():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6 + ['20240105'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3 + ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 4,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0, 2.0, 4.0, 8.0, 3.0, 6.0, 12.0],
        'volume': [3.0, 2.0, 1.0, 1.0, 4.0, 9.0, 8.0, 4.0, 2.0, 2.0, 5.0, 10.0],
    })
    expected = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='numpy',
    )

    actual = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert actual.attrs['operator_backend'] == 'process_sharded_array_grouped_terminal'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_terminal_rolling_corr_by_group_process_sharded_array_grouped_uses_shard_helper(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 3 + ['20240105'] * 3,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
        'volume': [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
    })
    calls = {'count': 0}

    def fake_shard(payload):
        calls['count'] += 1
        shard = payload['frame']
        keys = shard[['trade_date', 'ts_code']].drop_duplicates().sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
        keys['terminal_order'] = 93300
        keys['bar_count'] = 3
        keys['terminal_corr'] = np.arange(len(keys), dtype=np.float64)
        return keys

    monkeypatch.setattr(kernels, '_terminal_corr_array_grouped_shard', fake_shard, raising=False)

    out = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=2,
        output_col='terminal_corr',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert calls['count'] == 1
    assert out.attrs['operator_backend'] == 'process_sharded_array_grouped_terminal'
    assert out['terminal_corr'].tolist() == [0.0, 1.0]


def test_terminal_rolling_corr_by_group_process_sharded_array_grouped_uses_coarse_shard_builder(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 3 + ['20240105'] * 3,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
        'volume': [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
    })
    calls = {'builder': 0, 'shard': 0}

    def fake_builder(input_frame, group_cols, shard_count):
        calls['builder'] += 1
        assert group_cols == ['trade_date', 'ts_code']
        assert shard_count == 1
        return [input_frame]

    def fake_shard(payload):
        calls['shard'] += 1
        shard = payload['frame']
        keys = shard[['trade_date', 'ts_code']].drop_duplicates().sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
        keys['terminal_order'] = 93300
        keys['bar_count'] = 3
        keys['terminal_corr'] = np.arange(len(keys), dtype=np.float64)
        return keys

    monkeypatch.setattr(kernels, '_build_coarse_group_shards', fake_builder, raising=False)
    monkeypatch.setattr(kernels, '_terminal_corr_array_grouped_shard', fake_shard, raising=False)

    out = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=2,
        output_col='terminal_corr',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert calls == {'builder': 1, 'shard': 1}
    assert out.attrs['operator_backend'] == 'process_sharded_array_grouped_terminal'
    assert out['terminal_corr'].tolist() == [0.0, 1.0]


def test_terminal_rolling_corr_by_group_numba_grouped_uses_grouped_terminal_kernel(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 2,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0],
        'volume': [3.0, 2.0, 1.0, 1.0, 4.0, 9.0],
    })
    calls = {'count': 0}

    def fake_kernel():
        calls['count'] += 1

        def run(_starts, _ends, _x, _y, _window):
            return np.array([0.25, -0.5], dtype=np.float64)

        return run

    monkeypatch.setattr(kernels, '_numba_grouped_terminal_corr_kernel', fake_kernel, raising=False)

    out = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='numba_grouped',
    )

    assert calls['count'] == 1
    assert out.attrs['operator_backend'] == 'numba_grouped_terminal'
    np.testing.assert_array_equal(out['terminal_corr'].to_numpy(), np.array([0.25, -0.5], dtype=np.float64))


def test_terminal_rolling_corr_by_group_numba_grouped_matches_numpy_when_available():
    try:
        import numba  # noqa: F401
    except Exception:
        return
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6 + ['20240105'] * 6,
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 3 + ['000001.SZ'] * 3 + ['000002.SZ'] * 3,
        'hhmmss': [93100, 93200, 93300] * 4,
        'price': [1.0, 2.0, 3.0, 5.0, 7.0, 11.0, 2.0, 4.0, 8.0, 3.0, 6.0, 12.0],
        'volume': [3.0, 2.0, 1.0, 1.0, 4.0, 9.0, 8.0, 4.0, 2.0, 2.0, 5.0, 10.0],
    })
    expected = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='numpy',
    )

    actual = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='numba_grouped',
    )

    assert actual.attrs['operator_backend'] == 'numba_grouped_terminal'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_terminal_rolling_corr_by_group_uses_terminal_window_not_full_vector(monkeypatch):
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 5,
        'ts_code': ['000001.SZ'] * 5,
        'hhmmss': [93100, 93200, 93300, 93400, 93500],
        'price': [1.0, 2.0, 3.0, 4.0, 5.0],
        'volume': [7.0, 6.0, 5.0, 4.0, 3.0],
    })

    def fail_full_vector(*_args, **_kwargs):
        raise AssertionError('terminal operator must not materialize full rolling vector')

    monkeypatch.setattr(kernels, 'rolling_corr_1d', fail_full_vector)

    out = terminal_rolling_corr_by_group(
        frame,
        group_cols=['trade_date', 'ts_code'],
        order_col='hhmmss',
        x_col='price',
        y_col='volume',
        window=3,
        output_col='terminal_corr',
        backend='numpy',
    )

    assert out.loc[0, 'terminal_corr'] == -1.0
    assert out.loc[0, 'terminal_order'] == 93500


def test_intraday_occupation_location_state_computes_vwap_minus_twap_by_group():
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 2,
        'price': [10.0, 12.0, 14.0, 20.0, 30.0],
        'volume': [1.0, 2.0, 3.0, 0.0, 2.0],
        'amount': [10.0, 24.0, 42.0, 0.0, 60.0],
    })

    out = intraday_occupation_location_state(
        frame,
        group_cols=['ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
    )

    row1 = out[out['ts_code'] == '000001.SZ'].iloc[0]
    assert row1['bar_count'] == 3
    assert row1['amount_sum'] == 76.0
    assert row1['volume_sum'] == 6.0
    assert row1['twap'] == 12.0
    assert row1['vwap'] == 76.0 / 6.0
    assert row1['vwap_minus_twap'] == (76.0 / 6.0) - 12.0

    row2 = out[out['ts_code'] == '000002.SZ'].iloc[0]
    assert row2['twap'] == 25.0
    assert row2['vwap'] == 30.0
    assert row2['vwap_minus_twap'] == 5.0
    assert out.attrs['operator_backend'] == 'pandas_grouped'


def test_occupation_location_grouped_arrays_matches_dataframe_wrapper():
    starts = np.array([0, 3], dtype=np.int64)
    ends = np.array([3, 5], dtype=np.int64)
    price = np.array([10.0, 12.0, 14.0, 20.0, 30.0], dtype=np.float64)
    volume = np.array([1.0, 2.0, 3.0, 0.0, 2.0], dtype=np.float64)
    amount = np.array([10.0, 24.0, 42.0, 0.0, 60.0], dtype=np.float64)
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 3 + ['000002.SZ'] * 2,
        'price': price,
        'volume': volume,
        'amount': amount,
    })

    expected = intraday_occupation_location_state(
        frame,
        group_cols=['ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='pandas',
    )
    actual = kernels.occupation_location_grouped_arrays(
        starts,
        ends,
        price,
        volume,
        amount=amount,
        backend='array_grouped',
    )

    assert actual.backend == 'array_grouped_occupation'
    np.testing.assert_allclose(
        actual.values,
        expected[['bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap']].to_numpy(dtype=np.float64),
        rtol=1e-12,
        atol=1e-12,
    )


def test_occupation_location_grouped_arrays_vectorized_masks_invalid_price_rows():
    starts = np.array([0, 4, 6], dtype=np.int64)
    ends = np.array([4, 6, 6], dtype=np.int64)
    price = np.array([10.0, np.nan, 14.0, 16.0, np.nan, np.nan], dtype=np.float64)
    volume = np.array([1.0, 1000.0, np.nan, 4.0, 7.0, np.nan], dtype=np.float64)
    amount = np.array([10.0, 9999.0, 42.0, np.nan, 100.0, np.nan], dtype=np.float64)

    actual = kernels.occupation_location_grouped_arrays(
        starts,
        ends,
        price,
        volume,
        amount=amount,
        backend='array_grouped',
    )

    assert actual.backend == 'array_grouped_occupation'
    np.testing.assert_allclose(
        actual.values,
        np.array([
            [3.0, 52.0, 5.0, 40.0 / 3.0, 52.0 / 5.0, (52.0 / 5.0) - (40.0 / 3.0)],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ], dtype=np.float64),
        rtol=1e-12,
        atol=1e-12,
    )


def test_intraday_occupation_location_state_supports_multiple_group_columns():
    frame = pd.DataFrame({
        'trade_date': ['20240104', '20240104', '20240105'],
        'ts_code': ['000001.SZ', '000001.SZ', '000001.SZ'],
        'price': [10.0, 20.0, 30.0],
        'volume': [1.0, 3.0, 2.0],
    })

    out = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
    )

    assert out[['trade_date', 'ts_code']].values.tolist() == [
        ['20240104', '000001.SZ'],
        ['20240105', '000001.SZ'],
    ]
    assert out.loc[0, 'vwap'] == 17.5
    assert out.loc[0, 'twap'] == 15.0


def test_intraday_occupation_location_state_threaded_grouped_matches_pandas():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 4 + ['20240105'] * 4,
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ', '000002.SZ'] * 2,
        'price': [10.0, 20.0, 30.0, 40.0, 11.0, 19.0, 29.0, 41.0],
        'volume': [1.0, 3.0, 2.0, 2.0, 2.0, 2.0, 1.0, 3.0],
        'amount': [10.0, 60.0, 60.0, 80.0, 22.0, 38.0, 29.0, 123.0],
    })

    expected = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='pandas',
    )
    actual = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='threaded_grouped',
        max_workers=2,
    )

    assert actual.attrs['operator_backend'] == 'threaded_grouped'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_intraday_occupation_location_state_array_grouped_matches_pandas():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 4 + ['20240105'] * 4,
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ', '000002.SZ'] * 2,
        'price': [10.0, 20.0, 30.0, 40.0, 11.0, 19.0, 29.0, 41.0],
        'volume': [1.0, 3.0, 2.0, 2.0, 2.0, 2.0, 1.0, 3.0],
        'amount': [10.0, 60.0, 60.0, 80.0, 22.0, 38.0, 29.0, 123.0],
    })

    expected = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='pandas',
    )
    actual = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='array_grouped',
    )

    assert actual.attrs['operator_backend'] == 'array_grouped_occupation'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_intraday_occupation_location_state_process_sharded_array_grouped_matches_pandas():
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 6 + ['20240105'] * 6,
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ', '000002.SZ', '000003.SZ', '000003.SZ'] * 2,
        'price': [10.0, 20.0, 30.0, 40.0, 15.0, 16.0, 11.0, 19.0, 29.0, 41.0, 14.0, 18.0],
        'volume': [1.0, 3.0, 2.0, 2.0, 5.0, 1.0, 2.0, 2.0, 1.0, 3.0, 4.0, 2.0],
        'amount': [10.0, 60.0, 60.0, 80.0, 75.0, 16.0, 22.0, 38.0, 29.0, 123.0, 56.0, 36.0],
    })

    expected = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='pandas',
    )
    actual = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='process_sharded_array_grouped',
        max_workers=1,
    )

    assert actual.attrs['operator_backend'] == 'process_sharded_array_grouped_occupation'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)


def test_intraday_occupation_location_state_numba_grouped_uses_grouped_kernel(monkeypatch):
    frame = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 2 + ['000002.SZ'] * 2,
        'price': [10.0, 20.0, 30.0, 40.0],
        'volume': [1.0, 3.0, 2.0, 2.0],
        'amount': [10.0, 60.0, 60.0, 80.0],
    })
    calls = {'count': 0}

    def fake_kernel():
        calls['count'] += 1

        def run(_starts, _ends, _price, _volume, _amount):
            return np.array([
                [2.0, 70.0, 4.0, 15.0, 17.5, 2.5],
                [2.0, 140.0, 4.0, 35.0, 35.0, 0.0],
            ], dtype=np.float64)

        return run

    monkeypatch.setattr(kernels, '_numba_grouped_occupation_location_kernel', fake_kernel, raising=False)

    out = intraday_occupation_location_state(
        frame,
        group_cols=['ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='numba_grouped',
    )

    assert calls['count'] == 1
    assert out.attrs['operator_backend'] == 'numba_grouped'
    assert out['vwap_minus_twap'].tolist() == [2.5, 0.0]


def test_intraday_occupation_location_state_numba_grouped_matches_pandas_when_available():
    try:
        import numba  # noqa: F401
    except Exception:
        return
    frame = pd.DataFrame({
        'trade_date': ['20240104'] * 4 + ['20240105'] * 4,
        'ts_code': ['000001.SZ', '000001.SZ', '000002.SZ', '000002.SZ'] * 2,
        'price': [10.0, 20.0, 30.0, 40.0, 11.0, 19.0, 29.0, 41.0],
        'volume': [1.0, 3.0, 2.0, 2.0, 2.0, 2.0, 1.0, 3.0],
        'amount': [10.0, 60.0, 60.0, 80.0, 22.0, 38.0, 29.0, 123.0],
    })

    expected = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='pandas',
    )
    actual = intraday_occupation_location_state(
        frame,
        group_cols=['trade_date', 'ts_code'],
        price_col='price',
        volume_col='volume',
        amount_col='amount',
        backend='numba_grouped',
    )

    assert actual.attrs['operator_backend'] == 'numba_grouped'
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)
