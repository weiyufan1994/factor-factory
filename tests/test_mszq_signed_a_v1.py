
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from examples.mszq_signed_a_response.signed_a_v1 import compute_factor, compute_signed_a_scores


def _frame(values, *, dates=None, eligible=None, codes=None):
    values = list(values)
    dates = dates or ["20250102"] * len(values)
    eligible = [True] * len(values) if eligible is None else list(eligible)
    codes = codes or [f"{i:06d}.SZ" for i in range(len(values))]
    return pd.DataFrame({"ts_code": codes, "trade_date": dates,
                         "pf_daily": values, "baseline_eligible": eligible})


def _by_key(result):
    return result.scores.set_index(["trade_date", "ts_code"])["score"].sort_index()


def test_manual_signed_z_score_and_status():
    result = compute_signed_a_scores(_frame([-1.0, 0.0, 1.0]))
    assert result.scores["score"].tolist() == pytest.approx([1.0, 0.0, -1.0])
    assert result.date_status.loc[0, "status"] == "OK"
    assert result.date_status.loc[0, "n_finite_eligible"] == 3


def test_translation_and_positive_scaling_are_invariant():
    base = compute_signed_a_scores(_frame([-2.0, 1.0, 4.0]))
    shifted_scaled = compute_signed_a_scores(_frame([10.0, 19.0, 28.0]))
    assert _by_key(base).equals(_by_key(shifted_scaled))


def test_computed_score_sign_reverses_when_computed_a_is_negated():
    frame = _frame([2.0, 4.0, 8.0])
    negated = frame.assign(pf_daily=-frame["pf_daily"])
    original_scores = _by_key(compute_signed_a_scores(frame))
    negated_scores = _by_key(compute_signed_a_scores(negated))
    assert negated_scores.equals(-original_scores)


def test_future_date_cannot_change_past_scores_and_row_order_is_irrelevant():
    original = _frame([-1.0, 2.0, 5.0], codes=["A", "B", "C"])
    extended = pd.concat([original, _frame([100.0, 200.0], dates=["20250103"] * 2,
                                           codes=["D", "E"])], ignore_index=True)
    reordered = original.iloc[[2, 0, 1]].reset_index(drop=True)
    assert _by_key(compute_signed_a_scores(original)).equals(
        _by_key(compute_signed_a_scores(extended)).loc[_by_key(compute_signed_a_scores(original)).index]
    )
    assert _by_key(compute_signed_a_scores(original)).equals(_by_key(compute_signed_a_scores(reordered)))


def test_constant_zero_is_not_missing_and_is_non_discriminating():
    constant = compute_signed_a_scores(_frame([0.0, 0.0]))
    missing = compute_signed_a_scores(_frame([np.nan, np.nan]))
    assert constant.scores["score"].tolist() == [0.0, 0.0]
    assert constant.date_status.loc[0, "status"] == "NONDISCRIMINATING"
    assert missing.scores["score"].isna().all()
    assert missing.date_status.loc[0, "status"] == "MISSING"


def test_singleton_is_missing():
    result = compute_signed_a_scores(_frame([3.0]))
    assert np.isnan(result.scores.loc[0, "score"])
    assert result.date_status.loc[0, "status"] == "MISSING"


def test_excluded_rows_do_not_enter_cross_section():
    result = compute_signed_a_scores(_frame([-1.0, 1.0, 100.0], eligible=[True, True, False]))
    assert result.scores["score"].iloc[:2].tolist() == pytest.approx([1 / np.sqrt(2), -1 / np.sqrt(2)])
    assert np.isnan(result.scores["score"].iloc[2])
    assert result.date_status.loc[0, "n_eligible"] == 2


@pytest.mark.parametrize("mutator", [
    lambda f: f.assign(trade_date=["20250102", "not-a-date", "20250102"]),
    lambda f: f.assign(trade_date=[20250102, "20250102", "20250102"]),
    lambda f: f.assign(trade_date=["20250230", "20250230", "20250230"]),
    lambda f: f.assign(trade_date=["2025-01-02", "20250102", "20250102"]),
    lambda f: f.assign(ts_code=["A", "A", "C"]),
    lambda f: f.assign(pf_daily=[-1.0, np.inf, 1.0]),
    lambda f: f.assign(baseline_eligible=[True, None, True]),
    lambda f: f.assign(baseline_eligible=[True, 1, True]),
])
def test_invalid_inputs_fail_closed(mutator):
    with pytest.raises((TypeError, ValueError)):
        compute_signed_a_scores(mutator(_frame([-1.0, 0.0, 1.0])))


def test_mean20_delta_b_is_not_b():
    b = np.arange(21, dtype=float) ** 2
    delta_b = b[20] - b[19]
    mean20_delta = np.mean(np.diff(b))
    assert mean20_delta != pytest.approx(b[20])
    assert mean20_delta == pytest.approx((b[20] - b[0]) / 20.0)
    assert delta_b != pytest.approx(b[20])


def test_cumulative_reversal_grows_while_marginal_decays_and_kappa_zero_is_void():
    theta, kappa, rho, a = 2.0, 0.5, 0.8, 3.0
    cumulative = np.array([theta * kappa * (1 - rho**h) * a for h in range(1, 6)])
    marginal = np.diff(np.r_[0.0, cumulative])
    assert np.all(np.diff(cumulative) > 0)
    assert np.all(np.diff(marginal) < 0)
    assert np.allclose([theta * 0.0 * (1 - rho**h) * a for h in range(1, 6)], 0.0)


def test_non_range_index_is_preserved_and_input_is_not_modified():
    frame = _frame([-1.0, 0.0, 1.0]).set_axis([10, 20, 30])
    before = frame.copy(deep=True)
    result = compute_signed_a_scores(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert result.scores.index.equals(pd.RangeIndex(3))


def test_finite_extreme_values_that_overflow_sample_sd_fail_closed():
    with pytest.raises(ValueError, match="non-finite|overflow"):
        compute_signed_a_scores(_frame([1e308, -1e308]))


def test_compute_factor_adapter_has_expected_columns_and_status():
    frame = _frame([-1.0, 0.0, 1.0])
    output = compute_factor(frame)
    assert list(output.columns) == ["ts_code", "trade_date", "factor_value"]
    assert output["factor_value"].tolist() == pytest.approx([1.0, 0.0, -1.0])
    assert output.attrs["date_status"].loc[0, "status"] == "OK"


def test_compute_factor_adapter_keeps_future_rows_isolated():
    base = _frame([-1.0, 0.0, 1.0], codes=["A", "B", "C"])
    future = _frame([100.0, 200.0], dates=["20250103"] * 2, codes=["D", "E"])
    first = compute_factor(base).set_index("ts_code")["factor_value"]
    extended = compute_factor(pd.concat([base, future], ignore_index=True))
    later = extended[extended["trade_date"] == "20250102"].set_index("ts_code")["factor_value"]
    assert later.equals(first)
