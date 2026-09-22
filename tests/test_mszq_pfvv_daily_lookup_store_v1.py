"""Synthetic bounded SQLite lookup-store tests."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import time

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "examples/mszq_intraday_momentum_pulse/pfvv_daily_lookup_store_v1.py"
spec = importlib.util.spec_from_file_location("pfvv_daily_lookup_store_test", MODULE)
store = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(store)

from examples.mszq_intraday_momentum_pulse import pfvv_monthly_step4_backend_v1 as backend


ENGINE_DIR = ROOT / "examples" / "mszq_intraday_momentum_pulse" / "local_is_execution_engine"


class FakeEngine:
    def _normalize_inputs(self, factors, domain, daily, execution, constraints, calendar):
        return factors.copy(), domain.copy(), daily.copy(), execution.copy(), constraints.copy(), calendar.trade_date.tolist()


def _write_inputs(tmp_path: Path, *, duplicate=False):
    dates = ["20160104", "20160105", "20160106"]
    factors = pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"] * 3, "trade_date": sum(([day, day] for day in dates), []), "factor_value": [1., 2., 2., 1., 3., 4.]})
    domain = factors[["ts_code", "trade_date"]].copy()
    daily = pd.DataFrame({"ts_code": domain.ts_code, "trade_date": domain.trade_date, "close_unadjusted": [10., 11., 10.1, 11.1, 10.2, 11.2], "adj_factor": [1., 1., np.nan, 1., 1., 1.]})
    execution = pd.DataFrame({"ts_code": domain.ts_code, "trade_date": domain.trade_date, "vwap_0945_1000_unadjusted": [10., 11., 10.1, 11.1, 10.2, 11.2], "execution_bar_count": [16] * 6, "price_basis": ["UNADJUSTED_AMOUNT_OVER_VOL"] * 6, "execution_price_status": ["AVAILABLE"] * 6})
    constraints = pd.DataFrame({"ts_code": domain.ts_code, "trade_date": domain.trade_date, "st_new_buy_blocked": [False, True, False, False, False, False], "up_limit": [100.] * 6})
    if duplicate:
        daily = pd.concat([daily, daily.iloc[[0]]], ignore_index=True)
    paths = {}
    for name, frame in {"factor_values": factors, "measurement_domain": domain, "daily_prices": daily, "execution_vwap": execution, "normalized_constraints": constraints}.items():
        paths[f"{name}_path"] = tmp_path / f"{name}.parquet"
        frame.to_parquet(paths[f"{name}_path"], index=False, row_group_size=2)
    return dates, paths


def test_single_scan_store_matches_day_frames_and_nan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dates, paths = _write_inputs(tmp_path)
    result = store.build_pfvv_daily_lookup_store(**paths, calendar=pd.DataFrame({"trade_date": dates}), execution_engine=FakeEngine(), output_root=tmp_path / "store")
    assert result["month_end_dates"] == ["2016-01-06"]
    daily_frames = pd.concat([result["lookups"]["daily"]._date_partition(day) for day in dates], ignore_index=True)
    expected_daily = pd.read_parquet(paths["daily_prices_path"]).assign(trade_date=lambda frame: pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d"))
    pd.testing.assert_frame_equal(
        daily_frames.sort_values(["trade_date", "ts_code"]).reset_index(drop=True),
        expected_daily.sort_values(["trade_date", "ts_code"]).reset_index(drop=True),
        check_dtype=False,
    )
    assert result["lookups"]["daily"]._date_partition("20160105")["adj_factor"].isna().any()
    assert len(result["lookups"]["constraints"]._date_partition("20160104")) == 2
    assert result["qa"]["cache_days"] == 4
    # An already-normalized engine date must not invoke pandas parsing once per
    # security row.  This is a hot-cache probe, not a hardware benchmark.
    def parser_must_not_run(_values):
        raise AssertionError("hot ISO lookup invoked pandas date parser")
    monkeypatch.setattr(store, "_dates", parser_must_not_run)
    started = time.perf_counter()
    for _ in range(10_000):
        assert not result["lookups"]["daily"]._date_partition("2016-01-04").empty
    assert time.perf_counter() - started < 2.0


def test_duplicate_key_and_create_only_fail_closed(tmp_path: Path):
    dates, paths = _write_inputs(tmp_path, duplicate=True)
    with pytest.raises(store.DailyLookupStoreError, match="duplicate"):
        store.build_pfvv_daily_lookup_store(**paths, calendar=dates, execution_engine=FakeEngine(), output_root=tmp_path / "bad")
    dates, paths = _write_inputs(tmp_path / "ok") if (tmp_path / "ok").mkdir() is None else None
    target = tmp_path / "ok_store"
    store.build_pfvv_daily_lookup_store(**paths, calendar=dates, execution_engine=FakeEngine(), output_root=target)
    with pytest.raises(store.DailyLookupStoreError, match="output_root"):
        store.build_pfvv_daily_lookup_store(**paths, calendar=dates, execution_engine=FakeEngine(), output_root=target)


def test_opt_in_structural_nan_factor_tail_projects_only_measurement_domain(tmp_path: Path):
    dates, paths = _write_inputs(tmp_path)
    factors = pd.read_parquet(paths["factor_values_path"])
    factors["PF"] = np.arange(len(factors), dtype=float)
    factors["VV"] = np.arange(len(factors), dtype=float) + 10.0
    tail = pd.DataFrame({
        "ts_code": ["000099.SZ"], "trade_date": ["20160106"],
        "factor_value": [np.nan], "PF": [np.nan], "VV": [np.nan],
    })
    pd.concat([factors, tail], ignore_index=True).to_parquet(paths["factor_values_path"], index=False, row_group_size=2)
    with pytest.raises(store.DailyLookupStoreError, match="factor_domain_key_set_mismatch"):
        store.build_pfvv_daily_lookup_store(
            **paths, calendar=dates, execution_engine=FakeEngine(), output_root=tmp_path / "default",
            factor_value_columns=("factor_value", "PF", "VV"),
        )
    result = store.build_pfvv_daily_lookup_store(
        **paths, calendar=dates, execution_engine=FakeEngine(), output_root=tmp_path / "projected",
        factor_value_columns=("factor_value", "PF", "VV"),
        project_structural_nan_factor_tail=True,
    )
    projection = result["qa"]["factor_domain_projection"]
    assert projection == {
        "policy": "domain_subset_structural_nan_factor_tail_v1",
        "enabled": True,
        "signal_columns": ["factor_value", "PF", "VV"],
        "original_factor_rows": 7,
        "measurement_domain_rows": 6,
        "factor_only_rows": 1,
        "projected_factor_rows": 6,
        "projected_key_sets_equal": True,
        "projection_boundary": "bounded_batch_semi_join_to_measurement_domain",
    }
    assert result["month_end_factor_values"].ts_code.tolist() == ["000001.SZ", "000002.SZ"]
    assert result["month_end_measurement_domain"].ts_code.tolist() == ["000001.SZ", "000002.SZ"]


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("extra_finite", "factor_domain_extra_signal_not_nan"),
        ("domain_missing", "factor_domain_key_set_mismatch"),
        ("factor_duplicate", "factor_keys_duplicate_key"),
    ],
)
def test_opt_in_structural_nan_projection_remains_fail_closed(tmp_path: Path, mutation: str, error: str):
    dates, paths = _write_inputs(tmp_path)
    factors = pd.read_parquet(paths["factor_values_path"])
    factors["PF"] = np.arange(len(factors), dtype=float)
    factors["VV"] = np.arange(len(factors), dtype=float) + 10.0
    if mutation == "extra_finite":
        factors = pd.concat([factors, pd.DataFrame({
            "ts_code": ["000099.SZ"], "trade_date": ["20160106"],
            "factor_value": [np.nan], "PF": [1.0], "VV": [np.nan],
        })], ignore_index=True)
    elif mutation == "domain_missing":
        factors = factors.iloc[1:].reset_index(drop=True)
    else:
        factors = pd.concat([factors, factors.iloc[[0]]], ignore_index=True)
    factors.to_parquet(paths["factor_values_path"], index=False, row_group_size=2)
    with pytest.raises(store.DailyLookupStoreError, match=error):
        store.build_pfvv_daily_lookup_store(
            **paths, calendar=dates, execution_engine=FakeEngine(), output_root=tmp_path / f"fail_{mutation}",
            factor_value_columns=("factor_value", "PF", "VV"),
            project_structural_nan_factor_tail=True,
        )


def test_real_engine_sqlite_row_protocol_and_null_execution_key_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Exercise the frozen bounded-row protocol without market data or a skip."""

    assert ENGINE_DIR.is_dir()
    monkeypatch.setenv("PFVV_MONTHLY_EXECUTION_ENGINE_PATH", str(ENGINE_DIR))
    engine = backend.load_execution_engine(
        module_path=os.environ["PFVV_MONTHLY_EXECUTION_ENGINE_PATH"],
        module_name="mszq_step4_portfolio_evaluator_candidate_v1",
    )
    date, code = "20160104", "000001.SZ"
    root = tmp_path / "inputs"
    root.mkdir()
    frames = {
        "factor_values": pd.DataFrame({"ts_code": [code], "trade_date": [date], "factor_value": [1.0]}),
        "measurement_domain": pd.DataFrame({"ts_code": [code], "trade_date": [date]}),
        "daily_prices": pd.DataFrame({"ts_code": [code], "trade_date": [date], "close_unadjusted": [10.0], "adj_factor": [1.0]}),
        "execution_vwap": pd.DataFrame({
            "ts_code": [code], "trade_date": [date], "vwap_0945_1000_unadjusted": [np.nan],
            "execution_bar_count": [16], "price_basis": [backend.LEGACY_PRICE_BASIS], "execution_price_status": ["MISSING"],
        }),
        "normalized_constraints": pd.DataFrame({
            "ts_code": [code], "trade_date": [date], "constraint_complete": [True],
            "st_new_buy_blocked": [False], "pretrade_buy_blocked": [False], "pretrade_sell_blocked": [False],
            "is_st_asof_trade": [False], "up_limit": [20.0], "down_limit": [1.0],
            "historicalstatus_present": [False], "listing_status": ["UNKNOWN"],
        }),
    }
    paths = {}
    for name, frame in frames.items():
        path = root / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        paths[f"{name}_path"] = path
    result = store.build_pfvv_daily_lookup_store(
        **paths, calendar=pd.DataFrame({"trade_date": [date], "is_open": [True]}),
        execution_engine=engine, output_root=tmp_path / "store",
    )
    daily_lookup, execution_lookup = result["lookups"]["daily"], result["lookups"]["execution"]
    assert isinstance(daily_lookup, engine._BoundedStockDayRows)
    assert engine._row(daily_lookup, code, "2016-01-04")["close_unadjusted"] == 10.0
    assert engine._row(execution_lookup, code, "2016-01-04") is None
    with sqlite3.connect(result["sqlite_path"]) as connection:
        assert connection.execute("SELECT count(*) FROM execution").fetchone()[0] == 0

    # Null VWAP is intentionally removed by the old normalizer, but duplicate
    # raw source keys must still be rejected even when split one row per batch.
    duplicate = pd.concat([frames["execution_vwap"], frames["execution_vwap"]], ignore_index=True)
    duplicate.to_parquet(paths["execution_vwap_path"], index=False, row_group_size=1)
    monkeypatch.setattr(store, "BATCH_SIZE", 1)
    with pytest.raises(store.DailyLookupStoreError, match="execution_raw_duplicate_key_across_batches"):
        store.build_pfvv_daily_lookup_store(
            **paths, calendar=pd.DataFrame({"trade_date": [date], "is_open": [True]}),
            execution_engine=engine, output_root=tmp_path / "duplicate_store",
        )
