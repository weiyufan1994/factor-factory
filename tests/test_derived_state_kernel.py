"""Refactoring evidence, not evidence that the historical factors have alpha.

The oracle is the byte-identical generator at 24be21fe. It stays under test
fixtures, never in the runtime package. Hand calculations separately exercise
cross-sectional scaling, cutoff selection, lagging and input ownership.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from factor_factory.factor_laws.moneyflow.derived_state import (
    SUPPORTED_MILLER_DERIVED_STATE_LAWS,
    _minute_derived_flow_state_adapter,
    minute_derived_flow_state_law_source,
)
from factor_factory.factor_laws.moneyflow.derived_state_common import _factorforge_z_by_day
from factor_factory.factor_laws.moneyflow.derived_state_moments import _select_absorption_cutoffs
from factor_factory.factor_laws.moneyflow.derived_state_runtime import compute_derived_state


REFERENCE = Path(__file__).parent / 'fixtures/derived_state_before_cleanup.py'
REFERENCE_SHA = '2076aff7a8cb4f9f256289a1e1677e2061ab5606e4fd1ad5b87a00168f20d9f0'
legacy = {}
exec(compile(REFERENCE.read_text(), str(REFERENCE), 'exec'), legacy)
LEGACY_TEMPLATE = legacy['_minute_derived_flow_state_adapter']()
HISTORICAL_LAWS = sorted({node.value for node in ast.walk(ast.parse(LEGACY_TEMPLATE))
                          if isinstance(node, ast.Constant) and isinstance(node.value, str)
                          and node.value.startswith('miller_flow_')}) + ['']
REGISTERED_LAWS = sorted(SUPPORTED_MILLER_DERIVED_STATE_LAWS)
MOMENTS = (
    'signed_flow_imbalance signed_amount_skew signed_amount_excess_kurtosis '
    'signed_flow_tail_asymmetry large_small_signed_spread amount_hhi '
    'amount_top5_share amount_entropy ret_skew ret_excess_kurtosis '
    'ret_tail_asymmetry realized_vol realized_vol_of_vol '
    'positive_signed_amount_share negative_signed_amount_share'
).split()


def _execute_source(source, daily, state):
    namespace = {}
    exec(compile(source, '<derived-state-factor>', 'exec'), namespace)
    return namespace['compute_factor_from_derived_state'](daily, state)


def _frames(mode='pressure'):
    rng = np.random.default_rng(1027)
    daily = pd.MultiIndex.from_product(
        [pd.bdate_range('2024-01-02', periods=28).strftime('%Y-%m-%d'),
         [f'{number:06}.SZ' for number in range(1, 7)]],
        names=['trade_date', 'ts_code'],
    ).to_frame(index=False)
    for column in ['turnover_rate', 'turnover_rate_f', 'volume_ratio', 'pct_chg']:
        daily[column] = rng.normal(1, 2, len(daily))
    daily['total_mv'] = rng.uniform(40000, 900000, len(daily))
    daily['circ_mv'] = daily.total_mv * .75
    daily['fixed_small_universe_flag'] = np.tile([0, 0, 0, 1, 1, 1], 28)
    daily['fixed_small_rank_pct'] = np.tile(np.arange(1, 7) / 6, 28)
    state = daily[['ts_code', 'trade_date']].copy()
    if mode in {'moments', 'partial_moments'}:
        state = state.loc[state.index.repeat(3)].reset_index(drop=True)
        state['cutoff_time'] = np.tile(['14:00:00', '14:50:00', '15:00:00'], len(daily))
    for column in ['signed_pressure_sum', 'gross_pressure_sum', 'pressure_sq_sum',
                   'absolute_move_sum', 'intraday_ret_noise']:
        state[column] = rng.uniform(.1, 20, len(state))
    state['signed_pressure_sum'] -= 10
    state['minute_count'] = 200
    if mode != 'pressure' and mode != 'aliases':
        for column in MOMENTS:
            state[column] = rng.normal(0, 2, len(state))
    if mode == 'partial_moments':
        state = state.drop(columns=[name for name in MOMENTS
                                    if name not in {'signed_flow_imbalance', 'ret_excess_kurtosis'}])
        state.loc[state.index[::17], 'signed_flow_imbalance'] = np.nan
    if mode == 'aliases':
        state = state.rename(columns={
            'signed_pressure_sum': 'signed_amt_sum', 'gross_pressure_sum': 'gross_amt',
            'pressure_sq_sum': 'amt_sq_sum', 'absolute_move_sum': 'abs_ret_sum',
            'intraday_ret_noise': 'ret_std',
        })
        state.loc[0, 'gross_amt'] = 0
        state.loc[1, 'gross_amt'] = -1
        state.loc[2, 'signed_amt_sum'] = np.nan
    if mode == 'singleton':
        daily, state = daily[daily.ts_code == '000001.SZ'], state[state.ts_code == '000001.SZ']
    # The old implementation's sorting and grouping, not caller row order, decides the output.
    return daily.sample(frac=1, random_state=7), state.sample(frac=1, random_state=11)


def test_reference_is_frozen_original_bytes():
    assert hashlib.sha256(REFERENCE.read_bytes()).hexdigest() == REFERENCE_SHA


@pytest.mark.parametrize('law_id', HISTORICAL_LAWS)
@pytest.mark.parametrize('mode', ['pressure', 'moments'])
def test_every_historical_law_preserves_exact_outputs(law_id, mode):
    daily, state = _frames(mode)
    before_daily, before_state = daily.copy(deep=True), state.copy(deep=True)
    expected = _execute_source(legacy['_minute_derived_flow_state_adapter'](law_id), daily, state)
    direct = compute_derived_state(daily, state, law_id)
    generated = _execute_source(_minute_derived_flow_state_adapter(law_id), daily, state)
    assert_frame_equal(direct, expected, check_exact=True)
    assert_frame_equal(generated, expected, check_exact=True)
    assert_frame_equal(daily, before_daily, check_exact=True)
    assert_frame_equal(state, before_state, check_exact=True)
    assert len(expected) > 0
    assert expected.factor_value.notna().any()
    assert expected.factor_value.dropna().abs().sum() > 0


@pytest.mark.parametrize('law_id', REGISTERED_LAWS)
@pytest.mark.parametrize('mode', ['partial_moments', 'no_cutoff', 'aliases', 'singleton'])
def test_registered_laws_preserve_missing_optional_and_legacy_inputs(law_id, mode):
    daily, state = _frames(mode)
    expected = _execute_source(legacy['_minute_derived_flow_state_adapter'](law_id), daily, state)
    actual = _execute_source(minute_derived_flow_state_law_source(law_id), daily, state)
    assert_frame_equal(actual, expected, check_exact=True)


@pytest.mark.parametrize('law_id', REGISTERED_LAWS)
@pytest.mark.parametrize('mode', ['pressure', 'moments'])
def test_empty_inputs_keep_the_original_shape(law_id, mode):
    daily, state = _frames(mode)
    daily, state = daily.iloc[:0], state.iloc[:0]
    expected = _execute_source(legacy['_minute_derived_flow_state_adapter'](law_id), daily, state)
    assert_frame_equal(compute_derived_state(daily, state, law_id), expected, check_exact=True)


@pytest.mark.parametrize('missing', ['daily', 'state', 'gross_pressure_sum'])
def test_invalid_inputs_preserve_the_error(missing):
    daily, state = _frames()
    if missing == 'daily':
        daily = None
    elif missing == 'state':
        state = None
    else:
        state = state.drop(columns=[missing])
    with pytest.raises(ValueError) as previous:
        _execute_source(legacy['_minute_derived_flow_state_adapter'](), daily, state)
    with pytest.raises(type(previous.value)) as current:
        compute_derived_state(daily, state)
    assert str(current.value) == str(previous.value)


def test_day_scaling_has_a_hand_calculated_oracle():
    frame = pd.DataFrame({'trade_date': ['a', 'a', 'a', 'b'], 'x': [1., 2., 3., 50.]})
    actual = _factorforge_z_by_day(frame, 'x')
    np.testing.assert_array_equal(actual.iloc[:3], [-1., 0., 1.])
    assert np.isnan(actual.iloc[3])


def test_cutoff_comparison_uses_1400_and_1450_not_the_later_row():
    frame = pd.DataFrame({
        'ts_code': ['A'] * 4 + ['B'] * 4,
        'trade_date': ['20240102'] * 8,
        'cutoff_time': ['13:30:00', '14:00:00', '14:50:00', '15:00:00'] * 2,
        'absorption_state': [1., 2., 4., 999., 1., 3., 7., 999.],
    })
    for col in ['seller_pressure_state', 'discount_repair_state', 'bad_selling_noise_state',
                'crowded_chasing_state', 'ret_tail_asymmetry_z', 'ret_excess_kurtosis_z',
                'signed_flow_imbalance_z', 'signed_flow_tail_asymmetry_z']:
        frame[col] = 0.
    actual = _select_absorption_cutoffs(frame)
    assert list(actual.cutoff_time) == ['14:50:00', '14:50:00']
    np.testing.assert_allclose(actual.v14_prior_absorption_state, [.44 * 2, .44 * 3], rtol=0, atol=1e-15)
    np.testing.assert_allclose(actual.v14_absorption_momentum_raw, [.88, 1.76], rtol=0, atol=1e-15)


@pytest.mark.parametrize('law_id', REGISTERED_LAWS)
def test_same_day_daily_controls_cannot_change_same_day_factor(law_id):
    daily, state = _frames('moments')
    before = compute_derived_state(daily, state, law_id)
    last_day = daily.trade_date.max()
    for col in ['total_mv', 'circ_mv', 'turnover_rate', 'turnover_rate_f', 'volume_ratio', 'pct_chg']:
        daily.loc[daily.trade_date == last_day, col] *= 100
    after = compute_derived_state(daily, state, law_id)
    assert_frame_equal(after, before, check_exact=True)


def test_generated_source_is_standalone_and_has_no_giant_function(monkeypatch):
    law_id = REGISTERED_LAWS[0]
    daily, state = _frames('moments')
    expected = compute_derived_state(daily, state, law_id)
    source = minute_derived_flow_state_law_source(law_id)
    tree = ast.parse(source)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert max(node.end_lineno - node.lineno + 1 for node in functions) < 200
    assert all(not isinstance(node, ast.ImportFrom) for node in ast.walk(tree))
    original_import = builtins.__import__

    def no_framework_import(name, *args, **kwargs):
        if name == 'factor_factory' or name.startswith('factor_factory.'):
            raise AssertionError('generated factor depended on the SDK implementation')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', no_framework_import)
    assert_frame_equal(_execute_source(source, daily, state), expected, check_exact=True)


def test_public_registry_still_rejects_an_unsupported_law():
    with pytest.raises(ValueError, match='unsupported moneyflow derived-state law'):
        minute_derived_flow_state_law_source('not-a-law')
