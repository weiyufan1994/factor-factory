"""Local adapter tests; synthetic rows are not factor-efficacy evidence."""
from importlib.util import module_from_spec, spec_from_file_location
from inspect import signature
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


WORKSPACE = Path(__file__).resolve().parents[1]
ADAPTER_PATH = WORKSPACE / "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_dataframe_adapter_v1.py"
STEP4_PATH = WORKSPACE / "skills/factor-forge-step4/scripts/run_step4.py"


def load_module(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def adapter():
    return load_module("pfvv_dataframe_adapter_test", ADAPTER_PATH)


def minute_fixture(days: int = 22) -> tuple[pd.DataFrame, pd.DataFrame]:
    calendar = pd.bdate_range("2016-01-04", periods=days)
    codes = ["000001.SZ", "000002.SZ", "600000.SH", "600001.SH"]
    slots = np.r_[
        pd.date_range("2000-01-01 09:31", periods=120, freq="min").time,
        pd.date_range("2000-01-01 13:01", periods=120, freq="min").time,
    ]
    rows = []
    for day_number, day in enumerate(calendar):
        base = 0.0002 * (1.0 + day_number / 30.0)
        day_returns = np.array([base, base * 1.1, base * 4.0, -base * 0.7])
        for code_number, code in enumerate(codes):
            opening = 10.0 + code_number
            close = opening
            for slot_number, clock in enumerate(slots):
                minute_return = day_returns[code_number] * (1.0 + slot_number / 1000.0)
                close *= 1.0 + minute_return
                rows.append(
                    {
                        "ts_code": code,
                        "trade_time": pd.Timestamp.combine(day.date(), clock),
                        "open": opening if slot_number == 0 else close / (1.0 + minute_return),
                        "close": close,
                        "vol": 100.0 + code_number * 11.0 + (slot_number % 17) + day_number,
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame({"trade_date": calendar.strftime("%Y%m%d")})


def test_direct_code_shape_delegates_to_frozen_kernel_and_preserves_warmup(adapter, monkeypatch):
    minute, calendar = minute_fixture()
    seen = {}
    original = adapter._KERNEL.rolling_components

    def capture(pf, vv, dates, window):
        seen["pf"] = pf.copy()
        seen["vv"] = vv.copy()
        seen["dates"] = pd.DatetimeIndex(dates)
        seen["window"] = window
        return original(pf, vv, dates, window)

    monkeypatch.setattr(adapter._KERNEL, "rolling_components", capture)
    result = adapter.compute_factor(daily_df=calendar, minute_df=minute)
    expected = original(seen["pf"], seen["vv"], seen["dates"], seen["window"])

    assert list(signature(adapter.compute_factor).parameters)[:2] == ["daily_df", "minute_df"]
    assert seen["window"] == 20
    assert result.columns.tolist() == ["ts_code", "trade_date", "factor_value", "PF", "VV", "PF_z", "VV_z"]
    assert len(result) == len(calendar) * minute["ts_code"].nunique()
    assert result.loc[result["trade_date"].isin(calendar["trade_date"].iloc[:19]), "factor_value"].isna().all()

    expected_long = pd.concat(
        {"factor_value": expected["score"], "PF": expected["pf_raw"], "VV": expected["vv_raw"]}, axis=1
    ).stack(level=1, future_stack=True).reset_index()
    expected_long.columns = ["trade_date", "ts_code", "factor_value", "PF", "VV"]
    expected_long["trade_date"] = pd.to_datetime(expected_long["trade_date"]).dt.strftime("%Y%m%d")
    merged = result.merge(expected_long, on=["ts_code", "trade_date"], suffixes=("", "_frozen"), validate="one_to_one")
    for column in ["factor_value", "PF", "VV"]:
        np.testing.assert_allclose(merged[column], merged[f"{column}_frozen"], equal_nan=True)
    np.testing.assert_allclose(result["factor_value"], -(result["PF_z"] + result["VV_z"]) / 2.0, equal_nan=True)


@pytest.mark.skipif(not STEP4_PATH.is_file(), reason="Ultimate caller integration requires the existing Factor Forge checkout; standalone numerical package omits that runner")
def test_ultimate_direct_code_call_shape_is_a_real_callable(adapter):
    minute, calendar = minute_fixture()
    step4 = load_module("step4_compute_contract_test", STEP4_PATH)
    result = step4.compute_factor_with_contract(adapter, calendar, minute)
    assert isinstance(result, pd.DataFrame)
    assert {"ts_code", "trade_date", "factor_value", "PF", "VV"}.issubset(result.columns)
    assert result["trade_date"].min() == "20160104"


def test_unambiguous_existing_minute_aliases_normalize_without_changing_values(adapter):
    minute, calendar = minute_fixture()
    canonical = adapter.compute_factor(daily_df=calendar, minute_df=minute)
    aliased = adapter.compute_factor(
        daily_df=calendar,
        minute_df=minute.rename(columns={"trade_time": "datetime", "vol": "volume"}),
    )
    pd.testing.assert_frame_equal(canonical, aliased)


def test_requires_explicit_calendar_and_never_infers_one_from_an_ordinary_daily_panel(adapter):
    minute, _ = minute_fixture()
    with pytest.raises(ValueError, match="explicit trading calendar"):
        adapter.compute_factor(minute_df=minute)
    with pytest.raises(ValueError, match="ordinary daily panel"):
        adapter.compute_factor(daily_df=pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20160104"]}), minute_df=minute)


def test_frozen_is_start_is_20160104_not_20160101(adapter):
    minute, _ = minute_fixture()
    pre_is_calendar = pd.DataFrame({"trade_date": ["20160101"]})
    with pytest.raises(ValueError, match="2016-01-04 through 2025-07-11"):
        adapter.compute_factor(daily_df=pre_is_calendar, minute_df=minute)


def test_sparse_rows_cannot_trigger_a_large_calendar_x_slot_x_ticker_expansion(adapter):
    calendar = pd.DataFrame({"trade_date": pd.bdate_range("2016-01-04", periods=60).strftime("%Y%m%d")})
    codes = [f"{number:06d}.SZ" for number in range(10_000)]
    minute = pd.DataFrame(
        {
            "ts_code": codes,
            "trade_time": [pd.Timestamp("2016-01-04 09:31")] * len(codes),
            "open": [10.0] * len(codes),
            "close": [10.1] * len(codes),
            "vol": [100.0] * len(codes),
        }
    )
    with pytest.raises(ValueError, match="BLOCK_PFVV_LOCAL_SAMPLE_BUDGET") as excinfo:
        adapter.compute_factor(daily_df=calendar, minute_df=minute)
    assert "calendar_x_240_x_tickers=144000000" in str(excinfo.value)
    assert "full IS panel" in str(excinfo.value)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda minute: minute.assign(trade_time=minute["trade_time"].dt.normalize()), "midnight and 09:30"),
        (lambda minute: minute.assign(trade_time=minute["trade_time"].dt.normalize() + pd.Timedelta(hours=9, minutes=30)), "midnight and 09:30"),
        (lambda minute: minute.assign(ts_code="430001.BJ"), "BJ"),
        (lambda minute: minute.assign(trade_time=minute["trade_time"] + pd.Timedelta(days=3650)), "local IS"),
    ],
)
def test_rejects_placeholder_unsupported_market_and_oos_rows(adapter, mutate, message):
    minute, calendar = minute_fixture()
    with pytest.raises(ValueError, match=message):
        adapter.compute_factor(daily_df=calendar, minute_df=mutate(minute.copy()))


def test_missing_minute_is_not_filled_and_remains_unavailable(adapter):
    minute, calendar = minute_fixture()
    missing_code = "000001.SZ"
    missing_day = minute["trade_time"].dt.normalize().iloc[20 * 240 * 4]
    bad = minute.loc[
        ~(
            minute["ts_code"].eq(missing_code)
            & minute["trade_time"].eq(missing_day + pd.Timedelta(hours=10))
        )
    ].copy()
    result = adapter.compute_factor(daily_df=calendar, minute_df=bad)
    row = result.loc[
        result["ts_code"].eq(missing_code) & result["trade_date"].eq(missing_day.strftime("%Y%m%d"))
    ].iloc[0]
    assert pd.isna(row["PF"])
    assert pd.isna(row["factor_value"])
    assert len(result) == len(calendar) * minute["ts_code"].nunique()
