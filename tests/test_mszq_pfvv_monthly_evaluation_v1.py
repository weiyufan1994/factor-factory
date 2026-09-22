from __future__ import annotations

from datetime import date
import importlib
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.mszq_intraday_momentum_pulse import pfvv_monthly_evaluation_v1 as monthly


def _real_engine_or_skip():
    engine_path = os.environ.get("PFVV_MONTHLY_EXECUTION_ENGINE_PATH")
    module_name = os.environ.get("PFVV_MONTHLY_EXECUTION_ENGINE_MODULE", "mszq_step4_portfolio_evaluator_candidate_v1")
    if not engine_path:
        pytest.skip("real execution engine path is intentionally explicit: set PFVV_MONTHLY_EXECUTION_ENGINE_PATH")
    path = Path(engine_path)
    if not path.is_dir():
        pytest.skip("explicit real execution engine path is absent")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return importlib.import_module(module_name)


def _calendar() -> tuple[list[str], list[str]]:
    dates = pd.bdate_range("2016-01-04", "2016-03-31").strftime("%Y-%m-%d").tolist()
    # These are explicit exchange holidays in this small fixture.  Their removal
    # makes the monthly rebalance exit differ from the separate 20-session IC.
    dates = [value for value in dates if value not in {"2016-02-10", "2016-02-11"}]
    return dates, ["2016-01", "2016-02"]


def _frames_for(dates: list[str], complete: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    codes = [f"{value:06d}.SZ" for value in range(1, 101)]
    month_end = {month: max(value for value in dates if value.startswith(month)) for month in complete}
    factors = pd.DataFrame([
        {"ts_code": code, "trade_date": formation, "factor_value": float(number)}
        for formation in month_end.values() for number, code in enumerate(codes, start=1)
    ])
    daily = pd.DataFrame([
        {"ts_code": code, "trade_date": trade_date, "close_unadjusted": 10.0 + number / 100.0, "adj_factor": 1.0}
        for trade_date in dates for number, code in enumerate(codes, start=1)
    ])
    execution = pd.DataFrame([
        {"ts_code": code, "trade_date": trade_date, "vwap_unadjusted": 10.0 + number / 100.0, "bar_count": 16, "price_basis": "UNADJUSTED_AMOUNT_OVER_VOL"}
        for trade_date in dates for number, code in enumerate(codes, start=1)
    ])
    constraints = pd.DataFrame([
        {"ts_code": code, "trade_date": trade_date, "constraint_complete": True,
         "st_new_buy_blocked": False, "pretrade_buy_blocked": False, "pretrade_sell_blocked": False,
         "is_st_asof_trade": False, "up_limit": 100.0, "down_limit": 0.01, "unknown_reason": "",
         "delisting_execution_policy": "NO_STATUS_EVIDENCE", "historicalstatus_present": False,
         "listing_status": "UNKNOWN", "delist_cash_settlement_unadjusted": np.nan}
        for trade_date in dates for code in codes
    ])
    return factors, daily, execution, constraints, pd.DataFrame({"trade_date": dates, "is_open": True}), complete


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    return _frames_for(*_calendar())


class _SyntheticFrozenEngine:
    """Small explicit engine surface for full-route/bounded-kernel parity."""

    ONE_WAY_COST = monthly.ONE_WAY_COST
    __name__ = "synthetic_frozen_engine"

    def _normalize_inputs(self, factors, measurement, daily, execution, constraints, calendar):
        return (
            factors.copy(), measurement.copy(), daily.copy(), execution.copy(),
            constraints.copy(), calendar.loc[calendar["is_open"], "trade_date"].tolist(),
        )

    def _date_lookup(self, frame):
        return frame

    def _validate_factor_domain(self, factor_by_date, measurement_by_date):
        del factor_by_date, measurement_by_date

    def _stock_day_lookup(self, frame):
        return frame.copy()

    def _simulate(self, windows, selections, daily_lookup, execution_lookup, constraint_lookup, calendar_dates, *, cost_rate):
        del windows, selections, daily_lookup, execution_lookup, constraint_lookup, cost_rate
        nav = pd.DataFrame({
            "trade_date": list(calendar_dates), "nav": 1.0,
            "daily_return": 0.0, "gross_nav": 1.0,
            "gross_daily_return": 0.0, "cash": 1.0,
        })
        trades = pd.DataFrame(columns=["side", "reason", "status", "trade_date", "formation_date", "ts_code", "gross_amount", "cost", "net_cash_flow"])
        return nav, trades

    def _attach_zero_cost_counterfactual(self, net_nav, gross_nav):
        result = net_nav.copy()
        result["gross_nav"] = gross_nav["gross_nav"].to_numpy()
        result["gross_daily_return"] = gross_nav["gross_daily_return"].to_numpy()
        return result

    def _nav_metrics(self, nav, trades):
        del nav, trades
        return {"net_valuation_complete": True, "gross_valuation_complete": True}

    def _monthly_ic(self, factor_by_date, daily_lookup, execution_lookup, windows):
        del factor_by_date, daily_lookup, execution_lookup
        return pd.DataFrame({
            "formation_date": [window.formation_date.isoformat() for window in windows],
            "pearson_ic": 0.0, "rank_ic": 0.0,
        })


def test_normalized_lookup_kernel_matches_full_frame_route_without_a_second_simulator() -> None:
    factors, daily, execution, constraints, calendar, complete = _frames()
    engine = _SyntheticFrozenEngine()
    full = monthly.evaluate_monthly_groups(
        factor_values=factors, measurement_domain=factors[["ts_code", "trade_date"]],
        daily_prices=daily, execution_vwap=execution, normalized_constraints=constraints,
        calendar=calendar, complete_months=complete, execution_engine=engine,
    )
    normalized = engine._normalize_inputs(
        factors, factors[["ts_code", "trade_date"]], daily, execution, constraints, calendar,
    )
    bounded = monthly.evaluate_monthly_groups_from_normalized(
        factor_values=normalized[0], measurement_domain=normalized[1],
        calendar_dates=normalized[5], daily_lookup=engine._stock_day_lookup(normalized[2]),
        execution_lookup=engine._stock_day_lookup(normalized[3]),
        constraint_lookup=engine._stock_day_lookup(normalized[4]),
        complete_months=complete, execution_engine=engine,
    )
    assert full["portfolio_windows"] == bounded["portfolio_windows"]
    assert full["label_windows"] == bounded["label_windows"]
    assert full["contracts"] == bounded["contracts"]
    pd.testing.assert_frame_equal(full["groups"].counts, bounded["groups"].counts)
    pd.testing.assert_frame_equal(full["monthly_ic"], bounded["monthly_ic"])
    for group in [f"G{number:02d}" for number in range(1, 11)]:
        pd.testing.assert_frame_equal(full["group_accounts"][group]["daily_nav"], bounded["group_accounts"][group]["daily_nav"])

    emitted: list[str] = []
    compact = monthly.evaluate_monthly_groups_from_normalized(
        factor_values=normalized[0], measurement_domain=normalized[1],
        calendar_dates=normalized[5], daily_lookup=engine._stock_day_lookup(normalized[2]),
        execution_lookup=engine._stock_day_lookup(normalized[3]),
        constraint_lookup=engine._stock_day_lookup(normalized[4]),
        complete_months=complete, execution_engine=engine,
        retain_account_ids={"G01", "G10"}, account_sink=lambda account_id, account: emitted.append(account_id),
    )
    assert set(compact["group_accounts"]) == {"G01", "G10"}
    assert compact["benchmark"] is None
    assert emitted == [*(f"G{number:02d}" for number in range(1, 11)), "BENCHMARK_ALL_TEN_GROUPS"]
    assert set(compact["account_summaries"]) == set(emitted)
    pd.testing.assert_frame_equal(compact["diagnostic_spread"], full["diagnostic_spread"])


def test_monthly_windows_exit_at_next_rebalance_not_fixed_twenty_days() -> None:
    calendar, complete = _calendar()
    portfolio = monthly.build_monthly_rebalance_windows(calendar, complete_months=complete)
    labels = monthly.build_twenty_trading_day_label_windows(calendar, complete_months=complete)
    assert portfolio[0].formation_date == date(2016, 1, 29)
    assert portfolio[0].entry_date == date(2016, 2, 1)
    assert portfolio[0].exit_date == date(2016, 3, 1)
    assert portfolio[0].exit_date != labels[0].exit_date
    assert portfolio[0].holding_trading_days is None
    assert labels[0].holding_trading_days == 20
    assert portfolio[-1].status == "IMMATURE" and portfolio[-1].exit_date is None


def test_nonconsecutive_complete_months_fail_closed() -> None:
    calendar, _ = _calendar()
    with pytest.raises(monthly.MonthlyEvaluationError, match="complete_months_not_consecutive"):
        monthly.build_monthly_rebalance_windows(calendar, complete_months=["2016-01", "2016-03"])


def test_ten_groups_are_pre_return_complete_and_have_fixed_tie_rule() -> None:
    factors, _, _, _, _, complete = _frames()
    calendar, _ = _calendar()
    windows = monthly.build_monthly_rebalance_windows(calendar, complete_months=complete)
    groups = monthly.build_monthly_ten_groups(factors, factors[["ts_code", "trade_date"]], windows)
    first = windows[0].formation_date.isoformat()
    assert groups.tie_rule == monthly.TIE_RULE
    assert set(groups.members[first]) == {f"G{number:02d}" for number in range(1, 11)}
    assert groups.counts.loc[0, [f"G{number:02d}" for number in range(1, 11)]].tolist() == [10] * 10
    assert groups.members[first]["G01"]["ts_code"].tolist() == [f"{number:06d}.SZ" for number in range(1, 11)]
    assert groups.members[first]["G10"]["ts_code"].tolist() == [f"{number:06d}.SZ" for number in range(91, 101)]
    # All ties remain together: this is not manufactured into ten nonempty
    # groups by a ticker sort or any future-return/execution field.
    tied = factors.copy()
    tied.loc[tied["trade_date"].eq(first), "factor_value"] = 1.0
    tied_groups = monthly.build_monthly_ten_groups(tied, tied[["ts_code", "trade_date"]], windows)
    tied_counts = tied_groups.counts.loc[0, [f"G{number:02d}" for number in range(1, 11)]].tolist()
    assert tied_counts == [0, 0, 0, 0, 0, 100, 0, 0, 0, 0]
    assert tied_groups.status_by_formation[first] == "NOT_EVALUABLE_EMPTY_GROUPS"


def test_compact_dates_and_small_cross_section_are_preserved_as_not_evaluable() -> None:
    factors, _, _, _, _, complete = _frames()
    calendar, _ = _calendar()
    windows = monthly.build_monthly_rebalance_windows(calendar, complete_months=complete)
    compact = factors.copy()
    compact["trade_date"] = compact["trade_date"].str.replace("-", "", regex=False).astype(int)
    small = compact.loc[compact["ts_code"].isin([f"{number:06d}.SZ" for number in range(1, 8)])]
    groups = monthly.build_monthly_ten_groups(small, small[["ts_code", "trade_date"]], windows)
    first = windows[0].formation_date.isoformat()
    assert groups.counts.loc[0, [f"G{number:02d}" for number in range(1, 11)]].sum() == 7
    assert groups.status_by_formation[first] == "NOT_EVALUABLE_EMPTY_GROUPS"


def test_incomplete_frozen_cutoff_month_cannot_be_declared_complete() -> None:
    calendar = pd.bdate_range("2025-07-01", "2025-07-11").strftime("%Y-%m-%d").tolist()
    with pytest.raises(monthly.MonthlyEvaluationError, match="cutoff_month_not_complete"):
        monthly.build_monthly_rebalance_windows(calendar, complete_months=["2025-07"])
    calendar_to_midmonth = pd.bdate_range("2016-01-04", "2016-03-15").strftime("%Y-%m-%d").tolist()
    with pytest.raises(monthly.MonthlyEvaluationError, match="cutoff_month_not_complete"):
        monthly.build_monthly_rebalance_windows(calendar_to_midmonth, complete_months=["2016-01", "2016-02", "2016-03"], cutoff=20160331)
    with pytest.raises(monthly.MonthlyEvaluationError, match="calendar_terminal_month_not_proven_complete"):
        monthly.build_monthly_rebalance_windows(calendar_to_midmonth, complete_months=["2016-01", "2016-02", "2016-03"])


def test_explicit_real_engine_keeps_cash_cost_blocked_sell_and_independent_ic() -> None:
    legacy_engine = _real_engine_or_skip()
    factors, daily, execution, constraints, calendar, complete = _frames()
    windows = monthly.build_monthly_rebalance_windows(calendar["trade_date"].tolist(), complete_months=complete)
    exit_date = windows[0].exit_date.isoformat()
    # G10 is codes 91..100 under the fixed pre-return grouping.  The monthly
    # rebalance sell is blocked at the scheduled window, then fills next day.
    constraints.loc[
        constraints["trade_date"].eq(exit_date) & constraints["ts_code"].isin([f"{number:06d}.SZ" for number in range(91, 101)]),
        "pretrade_sell_blocked",
    ] = True
    result = monthly.evaluate_monthly_groups(
        factor_values=factors, measurement_domain=factors[["ts_code", "trade_date"]], daily_prices=daily,
        execution_vwap=execution, normalized_constraints=constraints, calendar=calendar,
        complete_months=complete, execution_engine=legacy_engine,
    )
    assert result["status"] == "EVALUABLE"
    assert result["engine_source"] == legacy_engine.__name__
    assert result["portfolio_windows"][0].exit_date != result["label_windows"][0].exit_date
    assert set(result["group_accounts"]) == {f"G{number:02d}" for number in range(1, 11)}
    g10 = result["group_accounts"]["G10"]
    trades = g10["trades"]
    blocked = trades.loc[(trades["side"] == "SELL") & (trades["status"] == "BLOCKED")]
    filled_sells = trades.loc[(trades["side"] == "SELL") & (trades["status"] == "FILLED")]
    assert blocked["trade_date"].eq(exit_date).all()
    assert (filled_sells["trade_date"] > exit_date).all()
    filled = trades.loc[trades["status"].eq("FILLED")]
    assert filled["cost"].sum() == pytest.approx(filled["gross_amount"].sum() * monthly.ONE_WAY_COST)
    gross_filled = g10["gross_trades"].loc[g10["gross_trades"]["status"].eq("FILLED")]
    assert gross_filled["cost"].sum() == 0.0
    assert g10["daily_nav"]["cash"].ge(-1e-12).all()  # independent cash-only, no short financing
    buy = trades.loc[(trades["side"] == "BUY") & (trades["status"] == "FILLED")].iloc[0]
    assert buy["reason"] == "MONTH_END_G10"
    assert buy["engine_trade_reason"] == "MONTH_END_TOP_QUINTILE"
    assert buy["adapter_trade_reason"] == "MONTH_END_G10"
    assert buy["engine_source"] == legacy_engine.__name__
    benchmark = result["benchmark"]
    assert benchmark["trades"]["portfolio_group"].eq("BENCHMARK_ALL_TEN_GROUPS").all()
    assert benchmark["daily_nav"]["cash"].ge(-1e-12).all()
    assert result["contracts"]["preferred_long_group"] == "G10"
    assert result["contracts"]["g10_minus_g01"] == "DIAGNOSTIC_ONLY__NOT_A_SHORT_ACCOUNT"
    assert result["diagnostic_spread"]["diagnostic_only"].all()
    assert result["monthly_ic"].iloc[0]["exit_date"] == result["label_windows"][0].exit_date.isoformat()


def test_partial_unevaluable_month_has_no_new_buys_with_real_engine() -> None:
    legacy_engine = _real_engine_or_skip()
    dates = pd.bdate_range("2016-01-04", "2016-04-29").strftime("%Y-%m-%d").tolist()
    dates = [value for value in dates if value not in {"2016-02-10", "2016-02-11"}]
    complete = ["2016-01", "2016-02", "2016-03"]
    factors, daily, execution, constraints, calendar, _ = _frames_for(dates, complete)
    february_end = max(value for value in dates if value.startswith("2016-02"))
    factors.loc[factors["trade_date"].eq(february_end), "factor_value"] = 1.0
    result = monthly.evaluate_monthly_groups(
        factor_values=factors, measurement_domain=factors[["ts_code", "trade_date"]], daily_prices=daily,
        execution_vwap=execution, normalized_constraints=constraints, calendar=calendar,
        complete_months=complete, execution_engine=legacy_engine,
    )
    assert result["status"] == "PARTIAL_EVALUABLE"
    assert february_end in result["contracts"]["non_evaluable_mature_formations"]
    for account in [*result["group_accounts"].values(), result["benchmark"]]:
        buys = account["trades"].loc[(account["trades"]["side"] == "BUY") & account["trades"]["formation_date"].eq(february_end)]
        assert buys.empty
