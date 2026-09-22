from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest


ROOT = Path(__file__).parents[1]
PATH = ROOT / "examples/mszq_intraday_momentum_pulse/candidate_v2.py"
SPEC = importlib.util.spec_from_file_location("mszq_candidate_v2", PATH)
assert SPEC and SPEC.loader
v2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v2)


def _canonical(dates: list[str], volumes: list[float], bars: int = 240) -> pd.DataFrame:
    rows = []
    for date, volume in zip(dates, volumes):
        for ordinal in range(bars):
            rows.append({"ts_code": "000001.SZ", "trade_date": date, "bar_time": v2.CANONICAL_TIMES[ordinal], "session_ordinal": ordinal, "vol": volume, "log_return": 0.001})
    return pd.DataFrame(rows)


def test_robust_z_preserves_nonconstant_mad_zero_order_and_nan() -> None:
    result = v2._robust_z(pd.Series([0.0, 0.0, 0.0, 1.0, 2.0, np.nan]))
    assert result.iloc[:5].notna().all() and result.iloc[5] != result.iloc[5]
    assert result.iloc[0] == result.iloc[1] == result.iloc[2]
    assert result.iloc[0] < result.iloc[3] < result.iloc[4]


def test_robust_z_keeps_true_constant_zero() -> None:
    result = v2._robust_z(pd.Series([4.0, 4.0, np.nan, 4.0]))
    assert result.iloc[[0, 1, 3]].eq(0.0).all()
    assert np.isnan(result.iloc[2])


def test_robust_z_treats_infinite_values_as_missing() -> None:
    result = v2._robust_z(pd.Series([0.0, 0.0, 1.0, 2.0, np.inf, -np.inf]))
    assert np.isnan(result.iloc[4]) and np.isnan(result.iloc[5])
    assert result.iloc[0] < result.iloc[2] < result.iloc[3]


def test_event_cold_start_is_missing_not_zero_and_future_does_not_leak() -> None:
    dates = [f"201601{day:02d}" for day in range(1, 17)]
    frame = _canonical(dates, [10.0] * 15 + [1_000_000.0])
    output = v2._event_outputs(frame)
    assert output.iloc[0]["event_coverage_state"] == "INSUFFICIENT_HISTORY"
    assert output.iloc[0]["event_u"] != output.iloc[0]["event_u"]
    assert pd.isna(output.iloc[0]["event_count"])
    # Day 15 has exactly 14 prior observations; the huge day-16 volume cannot
    # make it mature, proving the baseline uses only strictly prior history.
    assert output.iloc[14]["event_coverage_state"] == "INSUFFICIENT_HISTORY"


def test_event_valid_no_event_is_zero_only_with_complete_search_baselines() -> None:
    dates = [f"201602{day:02d}" for day in range(1, 17)]
    volumes = [10.0 + day for day in range(16)]
    output = v2._event_outputs(_canonical(dates, volumes))
    row = output.iloc[-1]
    assert row["event_coverage_state"] == "VALID_NO_EVENT"
    assert row["event_u"] == 0.0
    assert row["event_valid_baseline_count"] == row["event_search_slot_count"]


def test_event_invalid_or_partial_baselines_are_diagnostic_missing() -> None:
    dates = [f"201603{day:02d}" for day in range(1, 17)]
    invalid = v2._event_outputs(_canonical(dates, [10.0] * 16)).iloc[-1]
    assert invalid["event_coverage_state"] == "INVALID_BASELINE"
    assert np.isnan(invalid["event_u"])
    partial_frame = _canonical(dates, [10.0 + day for day in range(16)])
    # A mature search-slot with constant historical volume makes its baseline
    # invalid while other slots remain valid.
    partial_frame.loc[partial_frame["session_ordinal"] == 4, "vol"] = 10.0
    partial = v2._event_outputs(partial_frame).iloc[-1]
    assert partial["event_coverage_state"] == "PARTIAL_COVERAGE"
    assert np.isnan(partial["event_u"])


def test_normal_mad_input_preserves_prior_median_mad_and_event_u_formula() -> None:
    values = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0, 7.0, 6.0, 9.0, 8.0, 11.0, 10.0, 13.0, 12.0, 15.0, 14.0, 100.0])
    median, mad, count = v2._prior_median_mad(values, 20, 15)
    expected_median = values.shift(1).rolling(20, min_periods=15).median()
    def old_mad(window: np.ndarray) -> float:
        finite = window[np.isfinite(window)]
        return np.nan if finite.size < 15 else float(np.median(np.abs(finite - np.median(finite))))

    expected_mad = values.shift(1).rolling(20, min_periods=15).apply(old_mad, raw=True)
    pdt.assert_series_equal(median, expected_median)
    pdt.assert_series_equal(mad, expected_mad)
    assert count.iloc[-1] == 15


def test_normal_mature_event_matches_small_math_oracle() -> None:
    """Usable-event raw-U math is fixed without relying on a local old file."""
    dates = [f"201604{day:02d}" for day in range(1, 17)]
    frame = _canonical(dates, [10.0 + day for day in range(15)] + [1000.0])
    new_row = v2._event_outputs(frame).iloc[-1]
    assert new_row["event_coverage_state"] == "VALID_WITH_EVENT"
    # With 240 identical positive returns, retained candidates are 0,31,...,186
    # (seven events); immediate=.001, post=30*.001, residual=.031, U=31.
    assert new_row["event_count"] == 7
    assert new_row["event_k0_identity_abs_mean"] == pytest.approx(0.001)
    assert new_row["event_h1_h_signed_response_mean"] == pytest.approx(0.03)
    assert new_row["event_residual_pressure_sum"] == pytest.approx(7 * 0.031)
    assert new_row["event_immediate_abs_sum"] == pytest.approx(7 * 0.001)
    assert new_row["event_u"] == pytest.approx(31.0)


def test_index_permutation_duplicate_missing_and_nonfinite_inputs_are_explicit() -> None:
    dates = [f"201605{day:02d}" for day in range(1, 17)]
    frame = _canonical(dates, [10.0 + day for day in range(16)]).sample(frac=1.0, random_state=7)
    ordered = v2._event_outputs(frame.sort_index()).sort_values("trade_date").reset_index(drop=True)
    shuffled = v2._event_outputs(frame).sort_values("trade_date").reset_index(drop=True)
    pdt.assert_frame_equal(ordered, shuffled)
    with np.testing.assert_raises_regex(ValueError, "duplicate"):
        v2._event_outputs(pd.concat([frame, frame.iloc[[0]]], ignore_index=True))
    with np.testing.assert_raises_regex(ValueError, "incomplete canonical"):
        v2._event_outputs(frame.iloc[1:])
    broken_return = frame.copy()
    broken_return.iloc[0, broken_return.columns.get_loc("log_return")] = np.inf
    with np.testing.assert_raises_regex(ValueError, "log_return"):
        v2._event_outputs(broken_return)
    broken_volume = frame.copy()
    broken_volume.iloc[0, broken_volume.columns.get_loc("vol")] = -1.0
    with np.testing.assert_raises_regex(ValueError, "vol"):
        v2._event_outputs(broken_volume)


def test_invalid_last_horizon_baselines_do_not_downgrade_valid_search_slots() -> None:
    dates = [f"201606{day:02d}" for day in range(1, 17)]
    frame = _canonical(dates, [10.0 + day for day in range(16)])
    # Last 30 bars cannot launch H30 events.  Their final-day constant/zero
    # volume is diagnostic outside the eligible event-search slots.
    frame.loc[(frame["trade_date"] == dates[-1]) & (frame["session_ordinal"] >= 210), "vol"] = 0.0
    row = v2._event_outputs(frame).iloc[-1]
    assert row["event_search_slot_count"] == 210
    assert row["event_coverage_state"] == "VALID_NO_EVENT"
