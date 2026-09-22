"""Preparation correctness only: no real factor returns or OOS."""
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from test_mszq_pfvv_source_baseline_partitioned_v1 import load_module, minute_fixture

PATH = Path(__file__).resolve().parents[1] / "examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py"


@pytest.fixture
def producer():
    return load_module("test_pfvv_producer", PATH)


def source(days=1):
    frame, calendar = minute_fixture(days=days)
    frame["high"] = frame[["open", "close"]].max(axis=1)
    frame["low"] = frame[["open", "close"]].min(axis=1)
    frame["amount"] = frame.close * frame.vol
    return frame, calendar


def test_daily_delegates_frozen_kernel_and_counts_boundary_and_bj(producer):
    frame, _ = source()
    boundary = frame.groupby("ts_code").head(1).copy()
    boundary["trade_time"] = pd.Timestamp("2016-01-04 09:30")
    bj = frame.head(1).assign(ts_code="830001.BJ")
    output, facts = producer.compute_daily_measurements(pd.concat([frame, boundary, bj]), "20160104")
    clean, codes = producer._ADAPTER._validate_minute_rows(frame, pd.DatetimeIndex(["2016-01-04"]))
    close, opening, volume = producer._ADAPTER._one_day_panels(clean, pd.Timestamp("2016-01-04"), codes)
    returns = producer._KERNEL.minute_returns(close, opening)
    np.testing.assert_allclose(output.pf_daily, producer._KERNEL.pf_daily(returns)["daily"], equal_nan=True)
    np.testing.assert_allclose(output.vv_daily, producer._KERNEL.vv_daily(returns, volume)["daily"], equal_nan=True)
    assert facts["excluded_0930_boundary_rows"] == 4
    assert facts["excluded_non_sh_sz_a_rows"] == 1
    assert facts["missing_filled"] is False


def test_missing_bar_is_nan_not_zero(producer):
    frame, _ = source()
    frame = frame.drop(frame.index[100])
    output, _ = producer.compute_daily_measurements(frame, "20160104")
    assert output.set_index("ts_code").loc["000001.SZ", ["pf_daily", "vv_daily"]].isna().all()


def test_parquet_microseconds_and_compact_date_are_same_calendar_day(producer):
    frame, _ = source()
    frame["trade_time"] = frame.trade_time.astype("datetime64[us]")
    frame["trade_date"] = 20160104
    output, facts = producer.compute_daily_measurements(frame, "20160104")
    assert len(output) == 4
    assert facts["trade_date"] == "20160104"


@pytest.mark.parametrize("date", ["20160105", "20250714"])
def test_wrong_day_or_oos_rejected(producer, date):
    frame, _ = source()
    with pytest.raises(ValueError):
        producer.compute_daily_measurements(frame, date)


def test_execution_vwap_valid_missing_and_unit_mismatch(producer):
    frame, _ = source()
    actual = producer.execution_vwap(frame, "20160104").set_index("ts_code")
    assert actual.execution_bar_count.eq(16).all()
    assert actual.vwap_0945_1000_unadjusted.notna().all()
    missing = frame.loc[~((frame.ts_code == "000001.SZ") & (frame.trade_time.dt.strftime("%H:%M") == "09:50"))]
    result = producer.execution_vwap(missing, "20160104").set_index("ts_code")
    assert np.isnan(result.loc["000001.SZ", "vwap_0945_1000_unadjusted"])
    bad_units = producer.execution_vwap(frame.assign(amount=frame.amount * 100), "20160104")
    assert bad_units.vwap_0945_1000_unadjusted.isna().all()
    assert bad_units.execution_price_status.eq("AMOUNT_VOLUME_PRICE_RANGE_MISMATCH").all()
    unchanged, _ = producer.compute_daily_measurements(frame.assign(amount=frame.amount * 100), "20160104")
    baseline, _ = producer.compute_daily_measurements(frame, "20160104")
    pd.testing.assert_frame_equal(unchanged, baseline)


@pytest.mark.parametrize("mutation", ["date", "timezone", "off_minute"])
def test_execution_public_input_validation(producer, mutation):
    frame, _ = source()
    if mutation == "date":
        frame["trade_date"] = "20160105"
    elif mutation == "timezone":
        frame["trade_time"] = frame.trade_time.dt.tz_localize("Asia/Shanghai")
    else:
        frame["trade_time"] += pd.Timedelta(seconds=1)
    with pytest.raises(ValueError):
        producer.execution_vwap(frame, "20160104")


def plan(producer, calendar):
    return {"version": "pfvv_daily_source_plan_v1", "trading_calendar": calendar.trade_date.tolist(),
        "source_bucket": producer.SOURCE_BUCKET, "source_prefix": producer.SOURCE_PREFIX,
        "research_id": "synthetic_preparation"}


def test_create_only_materialization_one_read_per_day(producer, tmp_path):
    frame, calendar = source(2)
    calls = []
    def read(bucket, key, limit):
        day = key.split("trade_date=")[1].split("/")[0]
        calls.append(day)
        selected = frame.loc[frame.trade_time.dt.strftime("%Y%m%d").eq(day)]
        stream = io.BytesIO()
        selected.to_parquet(stream, index=False)
        return stream.getvalue(), {"etag": "synthetic"}
    root = tmp_path / "new"
    result = producer.materialize(plan(producer, calendar), root, read)
    assert calls == calendar.trade_date.tolist()
    assert result["pfvv_prepared_daily_state"]["day_paths"] == {d: f"daily_{d}.parquet" for d in calls}
    assert result["rolling_applied"] is False
    with pytest.raises(ValueError, match="new_absolute"):
        producer.materialize(plan(producer, calendar), root, read)
    assert len(calls) == 2


def test_failure_retains_partial_without_retry(producer, tmp_path):
    frame, calendar = source(2)
    calls = []
    def read(bucket, key, limit):
        calls.append(key)
        if len(calls) == 2:
            raise OSError("transport failure")
        stream = io.BytesIO()
        frame.loc[frame.trade_time.dt.normalize().eq(pd.Timestamp("2016-01-04"))].to_parquet(stream, index=False)
        return stream.getvalue(), {}
    root = tmp_path / "partial"
    with pytest.raises(OSError):
        producer.materialize(plan(producer, calendar), root, read)
    assert len(calls) == 2
    assert (root / "daily_20160104.parquet").is_file()
    assert not (root / "daily_measurements_manifest.json").exists()
    assert json.loads((root / "partial_failure.json").read_text())["auto_retry"] is False
