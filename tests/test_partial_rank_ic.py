"""Offline mathematical oracles for the public two-sided partial Rank IC."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from factor_factory.research_api import evaluate_factor


def frames(a, y, controls, date='2020-01-31'):
    index = pd.MultiIndex.from_product([[pd.Timestamp(date)], [f'S{i:04}' for i in range(len(a))]],
                                      names=['datetime', 'instrument'])
    return (pd.DataFrame({'factor_value': a}, index=index),
            pd.DataFrame({'forward_return': y}, index=index),
            pd.DataFrame(controls, index=index))


def evaluate(f, y, c, **kwargs):
    return evaluate_factor(f, y, controls=c, analysis='partial_rank_ic', **kwargs)


def test_hand_computed_two_group_projection_is_two_sided_without_reranking():
    f, y, c = frames([1., 2., 3., 4., 5., 6.], np.array([1., 3., 2., 5., 4., 6.]) / 10,
                     {'group': [0, 1, 0, 1, 0, 1]})
    saved = [x.copy(deep=True) for x in (f, y, c)]
    result = evaluate(f, y, c, min_observations=6)
    row = result['periods'][0]
    # Group demeaning gives U=(-2,-2,0,0,2,2),
    # V=(-4,-5,-1,1,5,4)/3. Their correlation is sqrt(27/28).
    assert row['partial_rank_ic'] == pytest.approx(math.sqrt(27 / 28), abs=1e-14)
    assert row['design_rank'] == 2 and row['reason'] is None
    u = np.array([-2., -2., 0., 0., 2., 2.])
    v = np.array([-4., -5., -1., 1., 5., 4.]) / 3
    assert abs(row['partial_rank_ic'] - pd.Series(u).corr(pd.Series(v), method='spearman')) > .01
    assert abs(row['partial_rank_ic'] - np.corrcoef(u, y.forward_return.rank())[0, 1]) > .01
    for old, new in zip(saved, (f, y, c)):
        pd.testing.assert_frame_equal(old, new)
    json.dumps(result, allow_nan=False)


def test_complete_cases_are_selected_before_midranking_and_raw_ic_shares_support():
    f, y, c = frames([1., 2., 3., 3.5, 4., 5., 6.],
                     np.array([1., 3., 2., 999., 5., 4., 6.]) / 1000,
                     {'group': [0., 1., 0., np.nan, 1., 0., 1.]})
    row = evaluate(f, y, c, min_observations=6)['periods'][0]
    assert row['input_n'] == 7 and row['n'] == 6 and row['excluded_n'] == 1
    assert row['partial_rank_ic'] == pytest.approx(math.sqrt(27 / 28), abs=1e-14)
    assert row['same_support_rank_ic'] == pytest.approx(31 / 35)


def test_average_ties_and_both_ranks_match_independent_group_means_oracle():
    a, b = np.array([1., 1., 2., 3., 3., 4.]), np.array([6., 2., 2., 1., 5., 6.])
    f, y, c = frames(a, b / 10, {'group': [0, 1, 0, 1, 0, 1]})
    u, v = pd.Series(a).rank(method='average'), pd.Series(b).rank(method='average')
    group = pd.Series([0, 1, 0, 1, 0, 1])
    u = u - u.groupby(group).transform('mean')
    v = v - v.groupby(group).transform('mean')
    assert evaluate(f, y, c, min_observations=6)['periods'][0]['partial_rank_ic'] == pytest.approx(u.corr(v), abs=1e-14)


def panel(n=120):
    rng = np.random.default_rng(637)
    return frames(rng.normal(size=n), rng.normal(scale=.03, size=n),
                  {f'C{k}': rng.normal(size=n) for k in range(11)})


def test_eleven_controls_project_both_ranked_variables_and_preserve_units():
    f, y, c = panel()
    result = evaluate(f, y, c)
    z = np.column_stack([np.ones(len(c)), c.to_numpy()])
    ranks = np.column_stack([f.factor_value.rank(), y.forward_return.rank()])
    # Independent direct full-rank normal-equation oracle on a well-conditioned fixture.
    residuals = ranks - z @ np.linalg.solve(z.T @ z, z.T @ ranks)
    expected = np.corrcoef(residuals.T)[0, 1]
    assert result['periods'][0]['partial_rank_ic'] == pytest.approx(expected, abs=1e-13)
    assert result['periods'][0]['design_rank'] == 12
    scaled = c * np.logspace(-120, 120, 11)
    assert evaluate(f, y, scaled)['periods'][0]['partial_rank_ic'] == pytest.approx(expected, abs=1e-13)
    assert result['method']['controls'] == list(c.columns)
    assert result['method']['inference'] == 'not_computed'
    assert result['account_simulation'] is False
    assert result['tradable_net_alpha_evidence'] is False


@pytest.mark.parametrize('n,reason', [(99, 'cross_section_insufficient'), (100, None)])
def test_default_minimum_is_one_hundred_complete_observations(n, reason):
    row = evaluate(*panel(n))['periods'][0]
    assert row['reason'] == reason
    assert (row['partial_rank_ic'] is None) == (reason is not None)


@pytest.mark.parametrize('mutation', ['collinear', 'constant_control', 'signal_in_span', 'return_in_span', 'constant_signal', 'constant_return'])
def test_undefined_projection_stays_unknown_without_removing_controls(mutation):
    f, y, c = panel()
    reason = 'zero_residual_variance'
    if mutation == 'collinear':
        c['C10'] = 2 * c['C0']; reason = 'rank_deficient'
    elif mutation == 'constant_control':
        c['C10'] = 1.; reason = 'rank_deficient'
    elif mutation == 'signal_in_span': c['C0'] = f.factor_value.rank()
    elif mutation == 'return_in_span': c['C0'] = y.forward_return.rank()
    elif mutation == 'constant_signal': f['factor_value'] = 1.
    elif mutation == 'constant_return': y['forward_return'] = .01
    result = evaluate(f, y, c)
    assert result['periods'][0]['reason'] == reason
    assert result['periods'][0]['partial_rank_ic'] is None
    assert result['metrics']['partial_rank_ic_mean']['value'] is None
    assert result['method']['controls'] == list(c.columns)
    json.dumps(result, allow_nan=False)


def test_missing_control_rows_and_missing_scheduled_month_are_retained():
    f, y, c = panel(120)
    c.iloc[:21, 0] = np.nan
    later = pd.MultiIndex.from_product([[pd.Timestamp('2020-02-28')], f.index.get_level_values('instrument')],
                                       names=f.index.names)
    result = evaluate(f, y, c, expected_index=f.index.append(later))
    assert [r['n'] for r in result['periods']] == [99, 0]
    assert all(r['reason'] == 'cross_section_insufficient' for r in result['periods'])
    assert result['alignment']['complete_case_rows'] == 99
    assert result['coverage']['missing_rows'] == 120


@pytest.mark.parametrize('minimum', [True, 2, 3.5, None])
def test_invalid_minimum_rejected(minimum):
    with pytest.raises(ValueError, match='min_observations'):
        evaluate(*panel(), min_observations=minimum)


def test_missing_controls_and_infinite_values_remain_contract_errors():
    f, y, c = panel()
    with pytest.raises(ValueError, match='requires explicitly supplied controls'):
        evaluate_factor(f, y, analysis='partial_rank_ic')
    c.iloc[0, 0] = np.inf
    with pytest.raises(ValueError, match='Infinity'):
        evaluate(f, y, c)
