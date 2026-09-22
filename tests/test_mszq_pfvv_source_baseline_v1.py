"""Independent source-equation oracles, not parity with the old candidate.

Synthetic inputs here cannot establish factor efficacy or formal Step4 completion.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

WORKSPACE = Path(__file__).resolve().parents[1]
spec = spec_from_file_location("pfvv_source_baseline", WORKSPACE / "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_v1.py")
kernel = module_from_spec(spec)
spec.loader.exec_module(kernel)


def pulse_returns():
    # Same-sign mean +0.02/-0.01; deviations [-.01,-.01,.02,0,0,0].
    row = np.array([.01, .01, .04, -.01, -.01, 0.])
    return pd.DataFrame([row, -row], columns=list("ABCDEF"))


def test_pf_hand_oracle_same_sign_means_skew_gate_and_sum():
    result = kernel.pf_daily(pulse_returns(), expected_slots=2)
    expected_delta = np.array([-.01, -.01, .02, 0., 0., 0.])
    np.testing.assert_allclose(result["deviations"].iloc[0], expected_delta, atol=1e-15)
    np.testing.assert_allclose(result["skewness"], [1., -1.], atol=1e-13)
    assert result["selected_minutes"].tolist() == [True, False]
    np.testing.assert_allclose(result["daily"], np.log1p(expected_delta), atol=1e-15)


def test_pf_log_sensitivity_is_explicit_and_not_identical():
    first = kernel.pf_daily(pulse_returns(), expected_slots=2)["daily"]
    alt = kernel.pf_daily(pulse_returns(), expected_slots=2, log_mode="log_return_difference")["daily"]
    r = pulse_returns().iloc[0].to_numpy()
    means = np.array([.02, .02, .02, -.01, -.01, 0.])
    np.testing.assert_allclose(alt, np.log1p(r) - np.log1p(means), atol=1e-15)
    assert np.max(np.abs(first - alt)) > 1e-5


def test_valid_no_event_zero_is_distinct_from_missing():
    flat = pd.DataFrame(0., index=range(2), columns=list("ABCD"))
    valid = kernel.pf_daily(flat, expected_slots=2)
    assert (valid["daily"] == 0.).all()
    flat.loc[1, "A"] = np.nan
    missing = kernel.pf_daily(flat, expected_slots=2)
    assert np.isnan(missing["daily"]["A"])
    assert (missing["daily"].drop("A") == 0.).all()


def test_unknown_cross_section_gate_is_not_no_event_zero():
    x = pd.DataFrame(0., index=range(2), columns=list("ABC"))
    x.loc[1, "A"] = np.nan
    result = kernel.pf_daily(x, expected_slots=2)
    assert result["daily"].isna().all()


def test_pf_stock_permutation_equivariance():
    x = pulse_returns()
    a = kernel.pf_daily(x, expected_slots=2)["daily"]
    b = kernel.pf_daily(x[x.columns[::-1]], expected_slots=2)["daily"]
    np.testing.assert_allclose(a, b.reindex(a.index), atol=1e-15)


def test_pf_tiny_nonzero_dispersion_must_not_be_collapsed_by_absolute_epsilon():
    x = pulse_returns() * 1e-10
    result = kernel.pf_daily(x, expected_slots=2)
    assert result["selected_minutes"].tolist() == [True, False]
    assert result["daily"].abs().max() > 0.


def test_minute_returns_first_open_and_no_overnight():
    closes = pd.DataFrame({"A": [11., 12.1, 10.89], "B": [22., 22., 24.2]})
    result = kernel.minute_returns(closes, pd.Series({"A": 10., "B": 20.}))
    np.testing.assert_allclose(result["A"], [.1, .1, -.1], atol=1e-14)
    np.testing.assert_allclose(result["B"], [.1, 0., .1], atol=1e-14)
    np.testing.assert_allclose(kernel.minute_returns(closes * 7, pd.Series({"A": 70., "B": 140.})), result)


def test_minute_missing_price_does_not_forward_fill():
    closes = pd.DataFrame({"A": [10., np.nan, 12.]})
    result = kernel.minute_returns(closes, pd.Series({"A": 10.}))
    assert result["A"].iloc[1:].isna().all()


def test_vv_partition_internal_peak_left_and_synchronous_rounds():
    v = np.array([100., 7., 9., 1., 8., 100.])
    assert kernel.vv_segments(v, rounds=1, skip_open=0) == [(0, 3), (3, 6)]
    assert kernel.vv_segments(v, rounds=2, skip_open=0) == [(0, 2), (2, 3), (3, 5), (5, 6)]
    assert kernel.vv_segments(v, rounds=3, skip_open=0) == [(i, i + 1) for i in range(6)]


def test_vv_equal_internal_peaks_choose_first():
    assert kernel.vv_segments(np.array([99., 7., 7., 7., 99.]), rounds=1, skip_open=0) == [(0, 2), (2, 5)]


def test_vv_skip_open_removes_ten_slots_and_partition_is_exact_cover():
    rng = np.random.default_rng(8841)
    v = rng.integers(0, 100, 240).astype(float)
    parts = kernel.vv_segments(v)
    assert 1 <= len(parts) <= 64
    assert [j for a, b in parts for j in range(a, b)] == list(range(10, 240))
    changed = v.copy()
    changed[:10] = 1e9
    assert kernel.vv_segments(changed) == parts


def test_vv_hand_oracle_segment_returns_include_first_bar_and_singleton():
    r = pd.DataFrame({"A": [.1, .2, -.1, .3]})
    v = pd.DataFrame({"A": [100., 9., 1., 100.]})
    result = kernel.vv_daily(r, v, rounds=1, skip_open=0, expected_slots=4)
    # [0,2) returns 1.1*1.2-1=.32; [2,4) returns .9*1.3-1=.17.
    expected = abs(.32 - .17) / np.sqrt(2.)
    np.testing.assert_allclose(result["daily"]["A"], expected, atol=1e-14)
    all_singletons = kernel.vv_daily(r, v, rounds=2, skip_open=0, expected_slots=4)
    np.testing.assert_allclose(all_singletons["daily"]["A"], np.std([.1, .2, -.1, .3], ddof=1), atol=1e-14)
    assert all_singletons["segment_counts"]["A"] == 4


def test_vv_missing_or_negative_volume_is_not_a_valid_zero():
    r = pd.DataFrame(0., index=range(4), columns=["A", "B"])
    v = pd.DataFrame(1., index=range(4), columns=["A", "B"])
    v.loc[1, "A"] = np.nan
    v.loc[1, "B"] = -1.
    result = kernel.vv_daily(r, v, rounds=2, skip_open=0, expected_slots=4)
    assert result["daily"].isna().all()


def test_vv_missing_return_invalidates_stock_day():
    r = pd.DataFrame({"A": [.01, np.nan, 0., .03]})
    v = pd.DataFrame({"A": [1., 2., 3., 4.]})
    assert kernel.vv_daily(r, v, rounds=2, skip_open=0, expected_slots=4)["daily"].isna().all()


def daily_panels(n=24):
    dates = pd.bdate_range("2016-01-04", periods=n)
    x = np.arange(n, dtype=float)
    pf = pd.DataFrame({"A": x, "B": x * 2, "C": x ** 2}, index=dates)
    vv = pd.DataFrame({"A": x + 1, "B": (x + 2) ** 2, "C": 10 + np.sin(x)}, index=dates)
    return dates, pf, vv


def test_pf_sum_then_std_cannot_be_replaced_by_two_direction_stds():
    dates, pf, vv = daily_panels()
    up = pd.Series([1., -1.] * 12, index=dates)
    down = -up
    pf["A"] = up + down
    result = kernel.rolling_components(pf, vv, dates)
    assert result["pf_raw"]["A"].iloc[19] == 0.
    assert up.iloc[:20].std() + down.iloc[:20].std() > 2.


def test_vv_cross_section_standardizes_before_twenty_day_std():
    dates = pd.bdate_range("2016-01-04", periods=21)
    x = np.arange(1., 22.)
    pf = pd.DataFrame({"A": x, "B": 2 * x}, index=dates)
    vv = pd.DataFrame({"A": x, "B": 2 * x}, index=dates)
    result = kernel.rolling_components(pf, vv, dates)
    np.testing.assert_allclose(result["vv_raw"].iloc[19:], 0., atol=1e-14)
    assert vv["A"].iloc[:20].std() > 5.


def test_twenty_calendar_day_window_does_not_compress_missing_day():
    dates, pf, vv = daily_panels()
    dropped = pf.drop(dates[10])
    result = kernel.rolling_components(dropped, vv, dates)
    assert result["pf_raw"].index.equals(dates)
    assert result["pf_raw"].iloc[:24].isna().all().all()


def test_future_mutation_does_not_change_earlier_rolling_outputs():
    dates, pf, vv = daily_panels(30)
    before = kernel.rolling_components(pf, vv, dates)
    pf.iloc[25:] *= 100
    vv.iloc[25:] += 42
    after = kernel.rolling_components(pf, vv, dates)
    for name in ("pf_raw", "vv_raw", "pf_z", "vv_z", "composite"):
        pd.testing.assert_frame_equal(before[name].iloc[:25], after[name].iloc[:25])


def test_composite_has_fixed_equal_weights_and_no_partial_components():
    dates, pf, vv = daily_panels()
    vv["C"] = np.nan
    result = kernel.rolling_components(pf, vv, dates)
    assert result["composite"]["C"].isna().all()
    assert result["pf_z"]["C"].isna().all()
    pd.testing.assert_frame_equal(result["composite"], -(result["pf_z"] + result["vv_z"]) / 2.)
    pd.testing.assert_frame_equal(result["score"], result["composite"])


@pytest.mark.parametrize("kind", ["duplicate_slot", "unsorted_slot", "duplicate_ticker"])
def test_rejects_ambiguous_matrix_identity(kind):
    x = pulse_returns()
    if kind == "duplicate_slot":
        x.index = [0, 0]
    elif kind == "unsorted_slot":
        x.index = [1, 0]
    else:
        x.columns = ["A"] * 6
    with pytest.raises(ValueError):
        kernel.pf_daily(x, expected_slots=2)


def test_rejects_misaligned_volume_matrix():
    r = pd.DataFrame(0., index=range(4), columns=["A", "B"])
    v = pd.DataFrame(1., index=range(4), columns=["B", "A"])
    with pytest.raises(ValueError):
        kernel.vv_daily(r, v, rounds=2, skip_open=0, expected_slots=4)


def test_zero_cross_section_and_insufficient_cross_section_differ():
    x = pd.DataFrame([[4., 4., np.nan], [4., np.nan, np.nan]], columns=list("ABC"))
    result = kernel.daily_cross_section_zscore(x)
    np.testing.assert_allclose(result.iloc[0, :2], [0., 0.])
    assert result.iloc[1].isna().all()


def test_vv_discarded_open_slots_do_not_validate_the_retained_path():
    returns = pd.DataFrame({"A": np.zeros(12)})
    volume = pd.DataFrame({"A": np.ones(12)})
    returns.iloc[0, 0] = np.nan
    returns.iloc[1, 0] = -99.0
    volume.iloc[0, 0] = np.nan
    volume.iloc[1, 0] = -1.0
    result = kernel.vv_daily(returns, volume, rounds=1, skip_open=10, expected_slots=12)
    assert result["daily"]["A"] == 0.0
    assert result["segment_counts"]["A"] == 2


def test_retained_return_and_illegal_pf_return_are_unavailable_not_zero():
    returns = pd.DataFrame({"A": np.zeros(12)})
    volume = pd.DataFrame({"A": np.ones(12)})
    returns.iloc[10, 0] = np.nan
    assert kernel.vv_daily(returns, volume, rounds=1, skip_open=10, expected_slots=12)["daily"].isna().all()

    pf_returns = pd.DataFrame([[0.01, 0.02, -2.0], [0.0, 0.0, 0.0]], columns=list("ABC"))
    pf_result = kernel.pf_daily(pf_returns, expected_slots=2)
    assert pf_result["daily"].isna().all()
    assert not pf_result["diagnostics"]["cross_section_gate_available"]
