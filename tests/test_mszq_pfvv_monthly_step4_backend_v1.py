from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.mszq_intraday_momentum_pulse import pfvv_monthly_evaluation_v1 as monthly
from examples.mszq_intraday_momentum_pulse import pfvv_monthly_step4_backend_v1 as backend
from factor_factory.primary_evaluator import validate_primary_evaluator_payload


def _evaluation() -> dict[str, object]:
    windows = monthly.build_monthly_rebalance_windows(
        ["2016-01-04", "2016-01-29", "2016-02-01", "2016-02-29", "2016-03-01"],
        complete_months=["2016-01", "2016-02"],
    )
    groups = monthly.MonthlyTenGroups(
        members={},
        counts=pd.DataFrame([{"formation_date": "2016-01-29", **{f"G{number:02d}": 1 for number in range(1, 11)}, "ten_group_status": "EVALUABLE"}]),
        status_by_formation={"2016-01-29": "EVALUABLE"},
    )
    nav = pd.DataFrame({"trade_date": ["2016-02-01", "2016-03-01"], "nav": [0.997, 1.02], "daily_return": [0.0, 0.023], "gross_nav": [1.0, 1.03], "gross_daily_return": [0.0, 0.03], "cash": [0.0, 1.02]})
    trades = pd.DataFrame([
        {"trade_date": "2016-02-01", "formation_date": "2016-01-29", "ts_code": "000001.SZ", "portfolio_group": "G10", "side": "BUY", "status": "FILLED", "reason": "MONTH_END_G10", "gross_amount": 1.0, "cost": 0.003, "net_cash_flow": -1.003},
        {"trade_date": "2016-03-01", "formation_date": "2016-01-29", "ts_code": "000001.SZ", "portfolio_group": "G10", "side": "SELL", "status": "FILLED", "reason": "SCHEDULED_EXIT", "gross_amount": 1.023, "cost": 0.003069, "net_cash_flow": 1.019931},
        {"trade_date": "2016-03-01", "formation_date": "2016-02-29", "ts_code": "000002.SZ", "portfolio_group": "G10", "side": "BUY", "status": "BLOCKED", "reason": "BUY_BLOCKED_ST", "gross_amount": 0.0, "cost": 0.0, "net_cash_flow": 0.0},
    ])
    performance = {
        "net_valuation_complete": True, "gross_valuation_complete": True,
        "net_annualized_return": 0.12, "net_annualized_volatility": 0.2, "net_annualized_daily_sharpe": 0.6,
        "net_max_drawdown": -0.05, "net_recovery_days": 4, "net_recovery_status": "RECOVERED",
        "net_recovery_lower_bound_days": np.nan, "net_recovery_observation_end": "2016-03-01",
        "gross_annualized_return": 0.15, "gross_annualized_daily_sharpe": 0.8,
        "turnover_gross_amount": 2.023, "cost_sum": 0.006069,
    }
    account = {"daily_nav": nav, "trades": trades, "performance": performance}
    return {
        "status": "EVALUABLE", "engine_source": "explicit.test_engine", "portfolio_windows": windows,
        "label_windows": (), "groups": groups, "group_accounts": {"G10": account},
        "monthly_ic": pd.DataFrame({"pearson_ic": [0.1, 0.2], "rank_ic": [0.15, 0.25]}),
        "contracts": {"non_evaluable_mature_formations": []},
    }


def test_export_writes_step4_primary_artifacts_and_keeps_contracts_separate(tmp_path: Path) -> None:
    payload = backend.export_step4_payload(report_id="RID", output=tmp_path / "payload.json", evaluation=_evaluation())
    assert payload["backend"] == backend.BACKEND_ID and payload["status"] == "success"
    assert set(("daily_nav", "trades", "monthly_ic", "performance", "coverage")).issubset(payload["artifacts"])
    assert payload["portfolio_contract"]["exit"] == "NEXT_MONTH_REBALANCE_SAME_WINDOW"
    assert payload["ic_summary"]["label_contract"] == "INDEPENDENT_20_TRADING_DAYS__NOT_MONTHLY_PORTFOLIO_NAV"
    assert payload["portfolio_contract"]["final_immature_month_traded"] is False
    assert pd.read_csv(payload["artifacts"]["fees"])["cost"].sum() == pytest.approx(0.006069)
    constraint = pd.read_csv(payload["artifacts"]["trading_constraints"])
    assert constraint.loc[0, "reason"] == "BUY_BLOCKED_ST"
    holdings = pd.read_csv(payload["artifacts"]["holdings"])
    assert set(holdings["position_evidence_kind"]) == {"OPEN_ORDER_TRANSITION", "CLOSE_OR_SETTLEMENT_ORDER_TRANSITION"}
    with pytest.raises(backend.PfvvMonthlyBackendError, match="create_only_target_exists"):
        backend.export_step4_payload(report_id="RID", output=tmp_path / "payload.json", evaluation=_evaluation())


def test_all_nan_ic_is_partial_not_a_success_payload(tmp_path: Path) -> None:
    evaluation = _evaluation()
    evaluation["monthly_ic"] = pd.DataFrame({"pearson_ic": [np.nan], "rank_ic": [np.nan], "label_status": ["INSUFFICIENT_IC_NAMES"]})
    payload = backend.export_step4_payload(report_id="RID", output=tmp_path / "nan_ic.json", evaluation=evaluation)
    assert payload["status"] == "partial"
    assert payload["ic_summary"]["pearson_ic_mean"] is None
    assert payload["ic_summary"]["rank_ic_mean"] is None


def test_execution_bridge_exports_price_status_and_preserves_null_vwap_without_changing_eligibility(tmp_path: Path) -> None:
    raw = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"], "trade_date": ["20160129"] * 3,
        "vwap_0945_1000_unadjusted": [10.0, np.nan, 11.0], "execution_bar_count": [16, 16, 15],
        "price_basis": [backend.LEGACY_PRICE_BASIS] * 3,
        "execution_price_status": ["OK", "AMOUNT_VOLUME_PRICE_RANGE_MISMATCH", "OK"],
    })
    legacy, coverage = backend.bridge_execution_vwap(raw)
    assert legacy["bar_count"].tolist() == [16, 16]
    assert legacy["vwap_unadjusted"].isna().sum() == 1
    assert coverage.loc[coverage["ts_code"].eq("000002.SZ"), "execution_price_status"].eq("AMOUNT_VOLUME_PRICE_RANGE_MISMATCH").all()
    assert coverage.loc[coverage["execution_bar_count"].eq(15), "legacy_lookup_included"].eq(False).all()
    assert coverage.loc[coverage["execution_bar_count"].eq(15), "legacy_bridge_status"].eq("EXECUTION_UNAVAILABLE_NON16_BAR_WINDOW").all()
    payload = backend.export_step4_payload(
        report_id="RID", output=tmp_path / "price_status.json", evaluation=_evaluation(), execution_coverage=coverage,
    )
    exported = pd.read_csv(payload["artifacts"]["execution_coverage"])
    assert exported.loc[exported["ts_code"].eq("000002.SZ"), "execution_price_status"].eq("AMOUNT_VOLUME_PRICE_RANGE_MISMATCH").all()
    assert {item["execution_price_status"]: item["row_count"] for item in payload["summary"]["execution_price_status_counts"]} == {
        "OK": 2, "AMOUNT_VOLUME_PRICE_RANGE_MISMATCH": 1,
    }


def test_explicit_file_engine_load_does_not_reuse_same_named_module(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir(); second.mkdir()
    (first / "engine.py").write_text("MARKER = 'first'\n", encoding="utf-8")
    (second / "engine.py").write_text("MARKER = 'second'\n", encoding="utf-8")
    loaded_first = backend.load_execution_engine(module_path=str(first), module_name="engine")
    loaded_second = backend.load_execution_engine(module_path=str(second), module_name="engine")
    assert loaded_first.MARKER == "first" and loaded_second.MARKER == "second"
    assert Path(loaded_second.__file__).resolve() == (second / "engine.py").resolve()


def test_event_u_is_rejected_before_prepared_input_read(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps({"schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "event_u_state_path": "forbidden"}), encoding="utf-8")
    with pytest.raises(backend.PfvvMonthlyBackendError, match="EVENT_U_FORBIDDEN"):
        backend.load_prepared_inputs(prepared, report_id="RID")


def test_optional_total_row_count_does_not_confuse_bounded_metadata_with_invalid_count() -> None:
    manifest = {"input_metadata": {"factor_values": {"month_end_row_count": 100}}}
    assert backend._declared_row_count(manifest, "factor_values") is None
    for invalid in (None, True, -1, "not-a-count"):
        manifest["input_metadata"]["factor_values"]["row_count"] = invalid
        with pytest.raises(backend.PfvvMonthlyBackendError, match="row_count_invalid:factor_values"):
            backend._declared_row_count(manifest, "factor_values")


def test_bounded_work_root_retains_failure_state_and_cleans_success(tmp_path: Path) -> None:
    retained = None
    with pytest.raises(RuntimeError) as exc:
        with backend._RetainedBoundedWorkRoot(prefix=".pfvv_test_", parent=tmp_path) as work:
            retained = work
            raise RuntimeError("synthetic_failure")
    assert retained is not None and retained.is_dir()
    assert any(str(retained) in note for note in exc.value.__notes__)
    assert str(retained) in str(exc.value)
    shutil.rmtree(retained)
    with backend._RetainedBoundedWorkRoot(prefix=".pfvv_test_", parent=tmp_path) as successful:
        assert successful.is_dir()
    assert not successful.exists()


def test_factor_frame_with_event_u_column_is_rejected(tmp_path: Path) -> None:
    paths = {}
    for key, frame in {
        "factor_values": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"], "factor_value": [1.0], "event_u": [0.1]}),
        "measurement_domain": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"]}),
        "daily_prices": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"], "close_unadjusted": [1.0], "adj_factor": [1.0]}),
        "execution_vwap": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"], "vwap_unadjusted": [1.0]}),
        "normalized_constraints": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"]}),
        "calendar": pd.DataFrame({"trade_date": ["20160129"], "is_open": [True]}),
    }.items():
        path = tmp_path / f"{key}.csv"
        frame.to_csv(path, index=False)
        paths[f"{key}_path"] = str(path)
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps({"schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01"], **paths}), encoding="utf-8")
    with pytest.raises(backend.PfvvMonthlyBackendError, match="EVENT_U_FORBIDDEN"):
        backend.load_prepared_inputs(prepared, report_id="RID")


def test_step4_factor_values_override_must_match_manifest_and_projects_only_selection_columns(tmp_path: Path) -> None:
    paths = {}
    frames = {
        "factor_values": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"], "factor_value": [1.0]}),
        "measurement_domain": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"]}),
        "daily_prices": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"], "close_unadjusted": [1.0], "adj_factor": [1.0]}),
        "execution_vwap": pd.DataFrame({
            "ts_code": ["000001.SZ"], "trade_date": ["20160129"],
            "vwap_0945_1000_unadjusted": [1.0], "execution_bar_count": [16],
            "price_basis": [backend.LEGACY_PRICE_BASIS], "execution_price_status": ["OK"],
        }),
        "normalized_constraints": pd.DataFrame({
            "ts_code": ["000001.SZ"], "trade_date": ["20160129"],
            "constraint_complete": [True], "st_new_buy_blocked": [False],
            "pretrade_buy_blocked": [False], "pretrade_sell_blocked": [False],
            "is_st_asof_trade": [False], "up_limit": [2.0], "down_limit": [0.5],
            "historicalstatus_present": [False], "listing_status": ["UNKNOWN"],
        }),
        "calendar": pd.DataFrame({"trade_date": ["20160129"], "is_open": [True]}),
    }
    for key, frame in frames.items():
        value = tmp_path / f"{key}.csv"
        frame.to_csv(value, index=False)
        paths[f"{key}_path"] = str(value)
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps({
        "schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01"], **paths,
    }), encoding="utf-8")
    override = tmp_path / "step4_factor.parquet"
    pd.DataFrame({
        "ts_code": ["000001.SZ"], "trade_date": ["20160129"], "PF": [0.1],
        "factor_value": [1.0], "warmup": [False],
    }).to_parquet(override, index=False)
    with pytest.raises(backend.PfvvMonthlyBackendError, match="factor_values_override_manifest_mismatch"):
        backend.load_prepared_inputs(prepared, report_id="RID", factor_values_override=override)
    paths["factor_values_path"] = str(override)
    prepared.write_text(json.dumps({
        "schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01"], **paths,
    }), encoding="utf-8")
    loaded = backend.load_prepared_inputs(prepared, report_id="RID", factor_values_override=override)
    assert list(loaded["factor_values"].columns) == ["ts_code", "trade_date", "factor_value"]


def test_projected_parquet_inputs_and_preflight_are_bounded_and_deployment_configurable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthetic closed manifest proves projection/preflight without market data."""

    frames = {
        "factor_values": pd.DataFrame({
            "ts_code": ["000001.SZ"], "trade_date": ["20160129"], "factor_value": [1.0],
            "PF": [0.2], "VV": [0.3], "warmup": [False],
        }),
        "measurement_domain": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160129"], "ignored": [1]}),
        "daily_prices": pd.DataFrame({
            "ts_code": ["000001.SZ"], "trade_date": ["20160129"], "close_unadjusted": [1.0],
            "adj_factor": [1.0], "ignored": [1],
        }),
        "execution_vwap": pd.DataFrame({
            "ts_code": ["000001.SZ"], "trade_date": ["20160129"],
            "vwap_0945_1000_unadjusted": [1.0], "execution_bar_count": [16],
            "price_basis": [backend.LEGACY_PRICE_BASIS], "execution_price_status": ["OK"], "ignored": [1],
        }),
        "normalized_constraints": pd.DataFrame({
            "ts_code": ["000001.SZ"], "trade_date": ["20160129"],
            "constraint_complete": [True], "st_new_buy_blocked": [False],
            "pretrade_buy_blocked": [False], "pretrade_sell_blocked": [False],
            "is_st_asof_trade": [False], "up_limit": [2.0], "down_limit": [0.5],
            "historicalstatus_present": [False], "listing_status": ["UNKNOWN"],
            "delist_cash_settlement_unadjusted": [np.nan], "ignored": [1],
        }),
        "calendar": pd.DataFrame({"trade_date": ["20160129"], "is_open": [True], "ignored": [1]}),
    }
    paths: dict[str, str] = {}
    for key, frame in frames.items():
        value = tmp_path / f"{key}.parquet"
        frame.to_parquet(value, index=False)
        paths[f"{key}_path"] = str(value)
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps({
        "schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01"],
        # Deliberately conservative declared counts exercise metadata use without
        # opening a real full-IS table in this test.
        "input_metadata": {key: {"row_count": 1_000_000} for key in frames}, **paths,
    }), encoding="utf-8")
    factor_path = Path(paths["factor_values_path"])
    monkeypatch.setattr(backend, "_available_memory_bytes", lambda: 8 * 1024 * 1024 * 1024)
    monkeypatch.setattr(backend, "_parent_rss_bytes", lambda: 128 * 1024 * 1024)

    loaded = backend.load_prepared_inputs(prepared, report_id="RID", factor_values_override=factor_path)
    assert list(loaded["factor_values"].columns) == ["ts_code", "trade_date", "factor_value"]
    assert "ignored" not in loaded["daily_prices"].columns
    assert "delist_cash_settlement_unadjusted" in loaded["normalized_constraints"].columns
    assert "execution_price_status" in loaded["execution_vwap"].columns

    passing = backend.preflight_prepared_inputs(
        prepared, report_id="RID", factor_values_override=factor_path, memory_budget_mb=4096,
    )
    assert passing["passes"] is True
    assert passing["memory_budget_source"] == "min_explicit_memory_budget_mb_and_available_memory_60_percent"
    assert passing["parent_rss_bytes"] == 128 * 1024 * 1024
    assert passing["inputs"]["factor_values"]["selected_columns"] == list(backend.SELECTION_COLUMNS)
    assert passing["inputs"]["execution_vwap"]["sample_rows"] <= backend.MEMORY_SAMPLE_ROWS
    assert passing["inputs"]["daily_prices"]["row_count"] == 1_000_000

    blocked = backend.preflight_prepared_inputs(
        prepared, report_id="RID", factor_values_override=factor_path, memory_budget_mb=1,
    )
    assert blocked["passes"] is False
    assert blocked["blocking_reason"] == "BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED"
    with pytest.raises(backend.PfvvMemoryBudgetError) as exc:
        backend.run_backend(
            report_id="RID", output=tmp_path / "must_not_exist.json", prepared_inputs=prepared,
            execution_engine_path=str(tmp_path / "no_engine"), execution_engine_module="engine",
            factor_values_override=factor_path, memory_budget_mb=1,
        )
    assert exc.value.report["passes"] is False
    assert not (tmp_path / "must_not_exist.json").exists()

    default_budget = backend.preflight_prepared_inputs(
        prepared, report_id="RID", factor_values_override=factor_path,
    )
    assert default_budget["configured_memory_budget_bytes"] == int(8 * 1024 * 1024 * 1024 * 0.60)
    capped_explicit = backend.preflight_prepared_inputs(
        prepared, report_id="RID", factor_values_override=factor_path, memory_budget_mb=16 * 1024,
    )
    assert capped_explicit["requested_memory_budget_bytes"] == 16 * 1024 * 1024 * 1024
    assert capped_explicit["effective_memory_budget_bytes"] == int(8 * 1024 * 1024 * 1024 * 0.60)
    assert "conservative_co_resident_addition" in capped_explicit["parent_overlap_note"]

    bounded_metadata = {
        key: {
            "row_count": 1_000_000,
            **({"month_end_row_count": 2_000} if key in {"factor_values", "measurement_domain"} else {}),
            **({"max_rows_per_trade_date": 100} if key in {"daily_prices", "execution_vwap", "normalized_constraints"} else {}),
        }
        for key in frames
    }
    # This matches a pre-compute manifest: month-end bound is known but total
    # factor rows are read from the Step4-owned parquet when it exists.
    bounded_metadata["factor_values"].pop("row_count")
    prepared.write_text(json.dumps({
        "schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01"],
        "input_metadata": bounded_metadata, **paths,
    }), encoding="utf-8")
    bounded = backend.preflight_prepared_inputs(
        prepared, report_id="RID", factor_values_override=factor_path,
        evaluation_mode="bounded_lookup_store",
    )
    assert bounded["passes"] is True
    assert bounded["evaluation_mode"] == "bounded_lookup_store"
    assert bounded["bounded_lookup_store"]["lookup_cache_days"] == 4
    assert bounded["bounded_lookup_store"]["estimated_retained_trade_rows_upper"] > 0
    assert bounded["inputs"]["factor_values"]["bounded_active_rows"] == 2_000
    assert bounded["inputs"]["factor_values"]["row_count"] == len(frames["factor_values"])
    assert bounded["inputs"]["factor_values"]["row_count_source"] == "file_metadata"
    assert bounded["inputs"]["daily_prices"]["bounded_active_rows"] == 400


def test_bounded_lookup_backend_matches_full_frame_with_the_same_explicit_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parity checks the shared kernel, rather than introducing a second simulator."""

    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "engine.py").write_text(
        '''import pandas as pd
ONE_WAY_COST = 0.003
def _iso(series):
    return pd.to_datetime(series.astype(str), format="mixed").dt.strftime("%Y-%m-%d")
def _normalize_inputs(factors, domain, daily, execution, constraints, calendar):
    pieces = [frame.copy() for frame in (factors, domain, daily, execution, constraints)]
    for frame in pieces:
        if "trade_date" in frame:
            frame["trade_date"] = _iso(frame["trade_date"])
    cal = calendar.copy(); cal["trade_date"] = _iso(cal["trade_date"])
    return (*pieces, cal.loc[cal["is_open"], "trade_date"].tolist())
def _date_lookup(frame): return frame
def _validate_factor_domain(factor_by_date, measurement_by_date): return None
def _stock_day_lookup(frame): return frame
def _day(lookup, day):
    if hasattr(lookup, "_date_partition"): return lookup._date_partition(day)
    return lookup.loc[lookup["trade_date"].eq(day)]
def _simulate(windows, selections, daily_lookup, execution_lookup, constraint_lookup, calendar_dates, *, cost_rate):
    for day in calendar_dates:
        _day(daily_lookup, day); _day(execution_lookup, day); _day(constraint_lookup, day)
    nav = pd.DataFrame({"trade_date": calendar_dates, "nav": 1.0, "daily_return": 0.0, "gross_nav": 1.0, "gross_daily_return": 0.0, "cash": 1.0})
    trades = pd.DataFrame(columns=["side", "reason", "status", "trade_date", "formation_date", "ts_code", "gross_amount", "cost", "net_cash_flow"])
    return nav, trades
def _attach_zero_cost_counterfactual(net, gross): return net.copy()
def _nav_metrics(nav, trades):
    return {"net_valuation_complete": True, "gross_valuation_complete": True, "net_annualized_return": 0.0, "net_annualized_volatility": 0.0, "net_annualized_daily_sharpe": 0.0, "net_max_drawdown": 0.0, "net_recovery_days": 0, "net_recovery_status": "RECOVERED", "net_recovery_lower_bound_days": 0, "net_recovery_observation_end": nav.iloc[-1]["trade_date"], "gross_annualized_return": 0.0, "gross_annualized_daily_sharpe": 0.0, "turnover_gross_amount": 0.0, "cost_sum": 0.0}
def _monthly_ic(factor_by_date, daily_lookup, execution_lookup, windows):
    return pd.DataFrame({"formation_date": [window.formation_date.isoformat() for window in windows], "pearson_ic": 0.0, "rank_ic": 0.0})
''', encoding="utf-8")
    calendar_dates = pd.bdate_range("2016-01-04", "2016-03-01").strftime("%Y-%m-%d").tolist()
    formations = ["2016-01-29", "2016-02-29"]
    codes = [f"{number:06d}.SZ" for number in range(1, 11)]
    domain = pd.DataFrame([{"ts_code": code, "trade_date": formation} for formation in formations for code in codes])
    frames = {
        "factor_values": domain.assign(factor_value=list(range(1, 11)) * len(formations)),
        "measurement_domain": domain,
        "daily_prices": pd.DataFrame([{"ts_code": code, "trade_date": day, "close_unadjusted": 10.0, "adj_factor": 1.0} for day in calendar_dates for code in codes]),
        "execution_vwap": pd.DataFrame([{"ts_code": code, "trade_date": day, "vwap_0945_1000_unadjusted": 10.0, "execution_bar_count": 16, "price_basis": backend.LEGACY_PRICE_BASIS, "execution_price_status": "OK"} for day in calendar_dates for code in codes]),
        "normalized_constraints": pd.DataFrame([{"ts_code": code, "trade_date": day, "constraint_complete": True, "st_new_buy_blocked": False, "pretrade_buy_blocked": False, "pretrade_sell_blocked": False, "is_st_asof_trade": False, "up_limit": 100.0, "down_limit": 0.01, "historicalstatus_present": False, "listing_status": "UNKNOWN"} for day in calendar_dates for code in codes]),
        "calendar": pd.DataFrame({"trade_date": calendar_dates, "is_open": True}),
    }
    paths: dict[str, str] = {}
    for key, frame in frames.items():
        path = tmp_path / f"{key}.parquet"
        frame.to_parquet(path, index=False, row_group_size=8)
        paths[f"{key}_path"] = str(path)
    metadata = {
        key: {
            "row_count": len(frame),
            **({"month_end_row_count": len(domain)} if key in {"factor_values", "measurement_domain"} else {}),
            **({"max_rows_per_trade_date": len(codes)} if key in {"daily_prices", "execution_vwap", "normalized_constraints"} else {}),
        }
        for key, frame in frames.items()
    }
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps({
        "schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01", "2016-02"],
        "input_metadata": metadata, **paths,
    }), encoding="utf-8")
    full = backend.run_backend(
        report_id="RID", output=tmp_path / "full.json", prepared_inputs=prepared,
        execution_engine_path=str(engine_dir), execution_engine_module="engine",
    )
    bounded_output = tmp_path / "bounded.json"
    completed = subprocess.run([
        sys.executable, str(Path(backend.__file__)), "--report-id", "RID", "--output", str(bounded_output),
        "--prepared-inputs", str(prepared), "--execution-engine-path", str(engine_dir),
        "--execution-engine-module", "engine", "--evaluation-mode", "bounded_lookup_store",
    ], capture_output=True, text=True, check=False, cwd=ROOT)
    assert completed.returncode == 0, completed.stderr
    bounded = json.loads(bounded_output.read_text(encoding="utf-8"))
    assert bounded["resource_budget"]["evaluation_mode"] == "bounded_lookup_store"
    assert bounded["resource_budget"]["bounded_lookup_store"]["account_spool_required"] is True
    assert pd.read_csv(full["artifacts"]["daily_nav"]).equals(pd.read_csv(bounded["artifacts"]["daily_nav"]))
    assert pd.read_csv(full["artifacts"]["monthly_ic"]).equals(pd.read_csv(bounded["artifacts"]["monthly_ic"]))
    assert pd.read_csv(full["artifacts"]["diagnostic_spread"]).equals(pd.read_csv(bounded["artifacts"]["diagnostic_spread"]))
    assert not pd.read_csv(bounded["artifacts"]["diagnostic_spread"]).empty
    coverage = pd.read_parquet(bounded["artifacts"]["execution_coverage"])
    assert len(coverage) == len(frames["execution_vwap"])
    assert coverage["legacy_lookup_included"].all()
    assert len(pd.read_csv(bounded["artifacts"]["account_summaries"])) == 11
    spool = json.loads(Path(bounded["artifacts"]["all_accounts_manifest"]).read_text(encoding="utf-8"))
    assert set(spool) == {*(f"G{number:02d}" for number in range(1, 11)), "BENCHMARK_ALL_TEN_GROUPS"}
    for account in spool.values():
        assert set(account) == {"daily_nav", "trades", "gross_trades", "performance"}
        assert all(Path(path).is_file() for path in account.values())

    # The preregistered standalone diagnostics reuse the same bounded store;
    # their input columns and negative orientation are fixed before any result.
    component_factors = frames["factor_values"].copy()
    component_factors["PF"] = np.arange(1, len(component_factors) + 1, dtype=float)
    component_factors["VV"] = np.arange(len(component_factors), 0, -1, dtype=float)
    component_factors.to_parquet(paths["factor_values_path"], index=False, row_group_size=8)
    _, pf_support = backend._component_factor_values(component_factors, "PF")
    pf_values, _ = backend._component_factor_values(component_factors, "PF")
    assert pf_values["factor_value"].tolist()[:3] == [-1.0, -2.0, -3.0]
    assert pf_support["factor_value_expression"] == "-(PF)"
    component_metadata = json.loads(json.dumps(metadata))
    component_metadata["factor_values"]["month_end_row_count"] = 1_000_000
    component_metadata["measurement_domain"]["month_end_row_count"] = 1_000_000
    prepared.write_text(json.dumps({
        "schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01", "2016-02"],
        "standalone_components": ["PF", "VV"], "input_metadata": component_metadata, **paths,
    }), encoding="utf-8")
    monkeypatch.setattr(backend, "_available_memory_bytes", lambda: 16 * 1024 * 1024 * 1024)
    monkeypatch.setattr(backend, "_parent_rss_bytes", lambda: 0)
    component_preflight = backend.preflight_prepared_inputs(
        prepared, report_id="RID", evaluation_mode="bounded_lookup_store",
    )
    details = component_preflight["bounded_lookup_store"]
    assert component_preflight["inputs"]["factor_values"]["selected_columns"] == ["ts_code", "trade_date", "factor_value", "PF", "VV"]
    assert details["estimated_sequential_component_month_end_peak_bytes"] > 2 * 1024 * 1024
    assert component_preflight["estimated_backend_peak_bytes"] >= (
        details["estimated_month_end_input_peak_bytes"]
        + details["estimated_source_batch_peak_bytes"]
        + details["estimated_retained_trade_peak_bytes"]
        + details["estimated_sequential_component_month_end_peak_bytes"]
    )
    near_cap_mb = int(math.ceil((
        component_preflight["estimated_backend_peak_bytes"]
        - details["estimated_sequential_component_month_end_peak_bytes"] / 2
    ) / (1024 * 1024)))
    assert not backend.preflight_prepared_inputs(
        prepared, report_id="RID", evaluation_mode="bounded_lookup_store", memory_budget_mb=near_cap_mb,
    )["passes"]
    prepared.write_text(json.dumps({
        "schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": ["2016-01", "2016-02"],
        "standalone_components": ["PF", "VV"], "input_metadata": metadata, **paths,
    }), encoding="utf-8")
    component_output = tmp_path / "bounded_components.json"
    completed = subprocess.run([
        sys.executable, str(Path(backend.__file__)), "--report-id", "RID", "--output", str(component_output),
        "--prepared-inputs", str(prepared), "--execution-engine-path", str(engine_dir),
        "--execution-engine-module", "engine", "--evaluation-mode", "bounded_lookup_store",
    ], capture_output=True, text=True, check=False, cwd=ROOT)
    assert completed.returncode == 0, completed.stderr
    component_payload = json.loads(component_output.read_text(encoding="utf-8"))
    assert pd.read_csv(component_payload["artifacts"]["daily_nav"]).equals(pd.read_csv(bounded["artifacts"]["daily_nav"]))
    diagnostics = component_payload["component_diagnostics"]
    assert diagnostics["comparison_contract"] == "COMPONENTS_USE_OWN_FINITE_SUPPORT__NO_COMMON_MASK_PORTFOLIO_RERUN"
    assert set(diagnostics["components"]) == {"PF", "VV"}
    for component, record in diagnostics["components"].items():
        assert record["support"]["factor_value_expression"] == f"-({component})"
        artifact_payload = json.loads(Path(record["payload_path"]).read_text(encoding="utf-8"))
        assert artifact_payload["diagnostic_signal"]["component"] == component
        assert Path(artifact_payload["artifacts"]["all_accounts_manifest"]).is_file()


def _real_engine_path_or_skip() -> str:
    value = os.environ.get("PFVV_MONTHLY_EXECUTION_ENGINE_PATH")
    if not value or not Path(value).is_dir():
        pytest.skip("set PFVV_MONTHLY_EXECUTION_ENGINE_PATH to run the explicit execution-engine integration")
    return value


def test_run_backend_uses_only_explicit_synthetic_inputs_and_engine(tmp_path: Path) -> None:
    engine_path = _real_engine_path_or_skip()
    dates = pd.bdate_range("2016-01-04", "2016-03-31").strftime("%Y-%m-%d").tolist()
    dates = [value for value in dates if value not in {"2016-02-10", "2016-02-11"}]
    complete = ["2016-01", "2016-02"]
    codes = [f"{number:06d}.SZ" for number in range(1, 101)]
    formations = [max(value for value in dates if value.startswith(month)) for month in complete]
    frames = {
        "factor_values": pd.DataFrame([{"ts_code": code, "trade_date": formation, "factor_value": float(number)} for formation in formations for number, code in enumerate(codes, start=1)]),
        "measurement_domain": pd.DataFrame([{"ts_code": code, "trade_date": formation} for formation in formations for code in codes]),
        "daily_prices": pd.DataFrame([{"ts_code": code, "trade_date": day, "close_unadjusted": 10.0 + number / 100.0, "adj_factor": 1.0} for day in dates for number, code in enumerate(codes, start=1)]),
        "execution_vwap": pd.DataFrame([{"ts_code": code, "trade_date": day, "vwap_0945_1000_unadjusted": 10.0 + number / 100.0, "execution_bar_count": 16, "price_basis": "UNADJUSTED_AMOUNT_OVER_VOL", "execution_price_status": "OK"} for day in dates for number, code in enumerate(codes, start=1)]),
        "normalized_constraints": pd.DataFrame([{"ts_code": code, "trade_date": day, "constraint_complete": True, "st_new_buy_blocked": False, "pretrade_buy_blocked": False, "pretrade_sell_blocked": False, "is_st_asof_trade": False, "up_limit": 100.0, "down_limit": 0.01, "unknown_reason": "", "delisting_execution_policy": "NO_STATUS_EVIDENCE", "historicalstatus_present": False, "listing_status": "UNKNOWN", "delist_cash_settlement_unadjusted": np.nan} for day in dates for code in codes]),
        "calendar": pd.DataFrame({"trade_date": dates, "is_open": True}),
    }
    manifest = {"schema_id": backend.PREPARED_SCHEMA_ID, "report_id": "RID", "complete_months": complete}
    for key, frame in frames.items():
        path = tmp_path / f"{key}.csv"
        frame.to_csv(path, index=False)
        manifest[f"{key}_path"] = str(path)
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "payload.json"
    command = [
        sys.executable, str(Path(backend.__file__)), "--report-id", "RID", "--output", str(output),
        "--prepared-inputs", str(prepared), "--execution-engine-path", engine_path,
        "--execution-engine-module", "mszq_step4_portfolio_evaluator_candidate_v1",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, cwd=ROOT)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "partial"  # constant synthetic labels are not fake success evidence
    assert payload["artifacts"]["daily_nav"] and Path(payload["artifacts"]["daily_nav"]).is_file()
    assert payload["summary"]["event_u_inputs_rejected"] is True
    coverage = pd.read_csv(payload["artifacts"]["execution_coverage"])
    assert coverage["legacy_lookup_included"].all()
    plan = {"primary_backend": backend.BACKEND_ID, "frequency": "monthly", "scope": "local_is_only", "backends": [{"name": backend.BACKEND_ID, "script_path": str(Path(backend.__file__))}]}
    codes = {item["code"] for item in validate_primary_evaluator_payload(payload, plan)}
    assert "PRIMARY_EVALUATOR_ARTIFACTS_MISSING" not in codes
