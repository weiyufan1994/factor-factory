"""Independent small-number checks, not a test of generated status wording."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_factory.factors import FormulaFactor, PriceVolumeFactor
from factor_factory.research_presentation import write_factor_review
from factor_factory.research_api import evaluate_factor, build_forward_returns
from examples.manual_interface_replay.factor_definitions import (
    HybridMeanIntradaySpread, MeanIntradaySpread, PointInTimeEarningsYield,
)

FIXTURE = Path(__file__).resolve().parents[1] / "examples/manual_interface_replay"


def inputs():
    return pd.read_csv(FIXTURE / "daily.csv", dtype={"ts_code": str, "trade_date": str})


@pytest.mark.parametrize("factor", [
    MeanIntradaySpread(2), HybridMeanIntradaySpread(2),
    FormulaFactor("mean(close - open, 2)"),
])
def test_three_routes_against_separately_written_oracle(factor):
    data = inputs()
    before = data.copy(deep=True)
    expected = pd.read_csv(FIXTURE / "expected_factor_values.csv", parse_dates=["datetime"])
    expected = expected.set_index(["datetime", "instrument"]).astype("float64")
    actual = factor({"daily_df": data})
    pd.testing.assert_frame_equal(actual, expected, check_exact=False, rtol=0, atol=1e-12)
    pd.testing.assert_frame_equal(data, before)
    assert actual.factor_value.isna().sum() == 3
    # A concrete independent arithmetic assertion: (1 + 3) / 2 = 2 CNY.
    assert actual.loc[(pd.Timestamp("2020-01-03"), "000001.SZ"), "factor_value"] == 2.0


def test_no_hidden_shared_state_between_instances():
    two = MeanIntradaySpread(2)
    three = MeanIntradaySpread(3)
    data = {"daily_df": inputs()}
    assert two(data).factor_value.isna().sum() == 3
    assert three(data).factor_value.isna().sum() == 6
    pd.testing.assert_frame_equal(two(data), two(data))


@pytest.mark.parametrize("factor", [MeanIntradaySpread(2), HybridMeanIntradaySpread(2)])
def test_known_estimator_prefix_and_future_perturbation_invariance(factor):
    data = inputs()
    cutoff = "20200106"
    baseline = factor({"daily_df": data})
    prefix = factor({"daily_df": data.loc[data.trade_date <= cutoff].copy()})
    pd.testing.assert_frame_equal(
        prefix, baseline.loc[baseline.index.get_level_values("datetime") <= pd.Timestamp(cutoff)],
    )
    future_changed = data.copy()
    future_changed.loc[future_changed.trade_date > cutoff, "close"] = 1_000_000.0
    revised = factor({"daily_df": future_changed})
    pd.testing.assert_frame_equal(
        prefix, revised.loc[revised.index.get_level_values("datetime") <= pd.Timestamp(cutoff)],
    )
    shuffled = factor({"daily_df": data.sample(frac=1, random_state=7)})
    pd.testing.assert_frame_equal(baseline, shuffled)


def test_input_roles_and_columns_are_checked():
    factor = MeanIntradaySpread()
    with pytest.raises(ValueError, match="missing factor input"):
        factor({})
    with pytest.raises(ValueError, match="missing columns"):
        factor({"daily_df": inputs().drop(columns="open")})
    with pytest.raises(TypeError):
        factor({"daily_df": [1, 2]})


def test_factor_body_is_not_retried_after_error():
    class FailingFactor(PriceVolumeFactor):
        name = "failing"
        calls = 0

        def compute(self, frames):
            self.calls += 1
            raise TypeError("body error, not signature mismatch")

    factor = FailingFactor()
    with pytest.raises(TypeError, match="body error"):
        factor({})
    assert factor.calls == 1


def test_fundamental_has_same_output_and_keeps_negative_earnings():
    data = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
        "trade_date": ["20200102"] * 3,
        "earnings_ttm_cny": [10.0, -10.0, 10.0],
        "market_cap_cny": [100.0, 100.0, 0.0],
    })
    result = PointInTimeEarningsYield()({"fundamentals": data})
    assert result.index.names == ["datetime", "instrument"]
    np.testing.assert_allclose(result.factor_value, [0.1, -0.1, np.nan], equal_nan=True)


def test_report_uses_values_and_escapes_source(tmp_path):
    frame = MeanIntradaySpread()({"daily_df": inputs()})
    path = write_factor_review(
        tmp_path / "report.html", factor_values=frame, source_code="# <script>alert(1)</script>",
        metrics={"analysis": "ic", "status": "not_run", "metrics": {}, "periods": [],
                 "api_version": "test_v1", "reason": "not_executed",
                 "warnings": ["timing_unknown"], "label_timing": {"source": "caller_supplied"},
                 "coverage": {"scope": "observed", "expected_rows": None}},
        command="python demo.py", selected_dates=["2020-01-03"],
    )
    html = path.read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "000001.SZ" in html
    assert "2020-01-03" in html
    assert "NaN" in html
    assert all(text in html for text in ["timing_unknown", "caller_supplied", "expected_rows", "not_executed", "test_v1"])


def test_metrics_against_hand_arithmetic_not_reference_implementation():
    values = MeanIntradaySpread()({"daily_df": inputs()})
    labels = pd.read_csv(FIXTURE / "forward_returns.csv", parse_dates=["datetime"])
    labels = labels.set_index(["datetime", "instrument"])
    values = values.loc[values.index.get_level_values("datetime") >= pd.Timestamp("2020-01-03")]
    ic = evaluate_factor(values, labels, analysis="ic")
    assert [row["rank_ic"] for row in ic["periods"]] == [1.0, -1.0, 1.0, 1.0]
    assert ic["metrics"]["rank_ic_mean"]["value"] == 0.5
    assert ic["metrics"]["rank_ic_std"]["value"] == 1.0  # ddof=1
    fmb = evaluate_factor(values, labels, analysis="fama_macbeth", newey_west_lags=0)
    # Slopes from two-point differences: .01/2, -.01/2, .01/2, .01/2.
    expected_slopes = [0.005, -0.005, 0.005, 0.005]
    np.testing.assert_allclose([row["lambda"] for row in fmb["periods"]], expected_slopes, atol=1e-14)
    # Bartlett L=0 uses denominator T=4: Var(mean)=sum(deviation^2)/16.
    mean = 0.0025
    se = (sum((x - mean)**2 for x in expected_slopes) / 16)**0.5
    assert fmb["metrics"]["lambda_mean"]["value"] == pytest.approx(mean)
    assert fmb["metrics"]["lambda_standard_error"]["value"] == pytest.approx(se)
    assert fmb["metrics"]["lambda_tstat"]["value"] == pytest.approx(mean / se)
    event = evaluate_factor(values, labels, analysis="event_study")
    assert event["metrics"]["event_return_mean"]["value"] == pytest.approx(0.02)
    assert event["metrics"]["event_return_mean"]["n"] == 12
    assert event["account_simulation"] is False


def test_missing_calendar_endpoint_does_not_hop_to_next_observed_price():
    prices = pd.DataFrame({
        "ts_code": ["000001.SZ"] * 3,
        "trade_date": ["20200102", "20200106", "20200107"],
        "close": [10.0, 12.0, 15.0],
    })
    labels = build_forward_returns(
        prices, calendar=["20200102", "20200103", "20200106", "20200107"],
        entry_offset=1, horizon=1,
    )
    # The entry on Jan 3 is missing. It must not become Jan 6 -> Jan 7 = 25%.
    assert np.isnan(labels.loc[(pd.Timestamp("2020-01-02"), "000001.SZ"), "forward_return"])
