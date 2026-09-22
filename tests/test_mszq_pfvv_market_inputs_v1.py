"""Synthetic bounded market-input join tests only."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "examples/mszq_intraday_momentum_pulse/pfvv_market_inputs_v1.py"
spec = importlib.util.spec_from_file_location("pfvv_market_inputs_test", MODULE)
market = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(market)


def _inputs(tmp_path: Path, *, duplicate=False, out_of_range=False):
    dates = ["20160104", "20160105", "20160106"]
    daily = pd.DataFrame({"ts_code": ["000001.SZ", "600000.SH", "830001.BJ", "000001.SZ"], "trade_date": [dates[0], dates[0], dates[0], dates[1]], "close": [10.0, 20.0, 30.0, 11.0]})
    adj = pd.DataFrame({"ts_code": ["000001.SZ", "600000.SH"], "trade_date": [dates[0], dates[0]], "adj_factor": [1.0, 2.0]})
    if duplicate:
        adj = pd.concat([adj, adj.iloc[[0]]], ignore_index=True)
    if out_of_range:
        daily.loc[0, "trade_date"] = "20151231"
    daily_path, adj_path, calendar_path = tmp_path / "daily.parquet", tmp_path / "adj.parquet", tmp_path / "calendar.parquet"
    daily.to_parquet(daily_path, index=False, row_group_size=1)
    adj.to_parquet(adj_path, index=False, row_group_size=1)
    pd.DataFrame({"trade_date": dates}).to_parquet(calendar_path, index=False)
    return daily_path, adj_path, calendar_path


def test_explicit_join_preserves_nan_and_reports_bj_and_missing_adj(tmp_path: Path):
    paths = _inputs(tmp_path)
    result = market.assemble_market_inputs(daily_path=paths[0], adj_factor_path=paths[1], calendar_path=paths[2], output_root=tmp_path / "out")
    frame = pd.read_parquet(result["daily_prices_path"])
    assert frame.columns.tolist() == market.OUTPUT_COLUMNS
    assert set(frame.ts_code) == {"000001.SZ", "600000.SH"}
    assert frame.loc[frame.trade_date.eq("20160105"), "adj_factor"].isna().all()
    assert result["qa"]["daily_bj_rows"] == 1
    assert result["qa"]["missing_adj_factor_rows"] == 1
    assert result["qa"]["forward_fill"] is False and result["qa"]["backfill"] is False


def test_duplicate_and_out_of_range_fail_closed(tmp_path: Path):
    for kwargs, message in [({"duplicate": True}, "adj_factor_duplicate"), ({"out_of_range": True}, "outside_supported")]:
        case = tmp_path / message
        case.mkdir()
        paths = _inputs(case, **kwargs)
        with pytest.raises(market.MarketInputsError, match=message):
            market.assemble_market_inputs(daily_path=paths[0], adj_factor_path=paths[1], calendar_path=paths[2], output_root=(tmp_path / message / "out"))


def test_explicit_off_calendar_adjustment_exclusion_does_not_change_price_domain(tmp_path: Path):
    paths = _inputs(tmp_path)
    adj = pd.read_parquet(paths[1])
    adj = pd.concat([adj, pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20160109", "adj_factor": 9.0}])], ignore_index=True)
    adj.to_parquet(paths[1], index=False)
    with pytest.raises(market.MarketInputsError, match="adj_factor_date_outside_explicit_calendar"):
        market.assemble_market_inputs(daily_path=paths[0], adj_factor_path=paths[1], calendar_path=paths[2], output_root=tmp_path / "strict")
    result = market.assemble_market_inputs(daily_path=paths[0], adj_factor_path=paths[1], calendar_path=paths[2], output_root=tmp_path / "explicit", ignore_off_calendar_adj=True)
    frame = pd.read_parquet(result["daily_prices_path"])
    assert len(frame) == 3
    assert "20160109" not in set(frame.trade_date)
    assert result["qa"]["off_calendar_adj_excluded_dates"] == {"20160109": 1}
    assert result["qa"]["missing_adj_factor_rows"] == 1
    assert (tmp_path / "strict/_join.sqlite").exists()


def test_output_root_is_create_only(tmp_path: Path):
    paths = _inputs(tmp_path)
    target = tmp_path / "out"
    market.assemble_market_inputs(daily_path=paths[0], adj_factor_path=paths[1], calendar_path=paths[2], output_root=target)
    with pytest.raises(market.MarketInputsError, match="output_root"):
        market.assemble_market_inputs(daily_path=paths[0], adj_factor_path=paths[1], calendar_path=paths[2], output_root=target)


def test_security_clustered_sources_are_consumed_once_and_exactly_joined(tmp_path: Path, monkeypatch):
    """Rows grouped by security still require one sequential source pass each."""
    dates = ["20160104", "20160105", "20160106"]
    daily = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 3 + ["600000.SH"] * 3,
            "trade_date": dates * 2,
            "close": [10.0, 11.0, 12.0, 20.0, 21.0, 22.0],
        }
    )
    adj = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 3 + ["600000.SH"] * 2,
            "trade_date": dates + dates[:2],
            "adj_factor": [1.0, 1.1, 1.2, 2.0, 2.1],
        }
    )
    daily_path, adj_path, calendar_path = tmp_path / "daily.parquet", tmp_path / "adj.parquet", tmp_path / "calendar.parquet"
    daily.to_parquet(daily_path, index=False, row_group_size=2)
    adj.to_parquet(adj_path, index=False, row_group_size=2)
    pd.DataFrame({"trade_date": dates}).to_parquet(calendar_path, index=False)

    original_iter_batches = pq.ParquetFile.iter_batches
    iter_calls, consumed_rows = {}, {}

    def tracked_iter_batches(parquet_file, *args, **kwargs):
        # The two synthetic source files deliberately have different row counts.
        source_rows = parquet_file.metadata.num_rows
        iter_calls[source_rows] = iter_calls.get(source_rows, 0) + 1
        for batch in original_iter_batches(parquet_file, *args, **kwargs):
            consumed_rows[source_rows] = consumed_rows.get(source_rows, 0) + batch.num_rows
            yield batch

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", tracked_iter_batches)
    result = market.assemble_market_inputs(
        daily_path=daily_path,
        adj_factor_path=adj_path,
        calendar_path=calendar_path,
        output_root=tmp_path / "out",
    )

    assert iter_calls == {6: 1, 5: 1}
    assert consumed_rows == {6: 6, 5: 5}
    joined = pd.read_parquet(result["daily_prices_path"]).set_index(["ts_code", "trade_date"])
    assert joined.loc[("000001.SZ", "20160106"), "adj_factor"] == pytest.approx(1.2)
    assert joined.loc[("600000.SH", "20160106"), "adj_factor"] != joined.loc[("600000.SH", "20160106"), "adj_factor"]
    assert result["qa"]["daily_source_rows_scanned"] == 6
    assert result["qa"]["adj_source_rows_scanned"] == 5


def test_duplicate_across_stream_batch_fails_and_preserves_failed_root(tmp_path: Path):
    """A repeated exact key after the 64k input batch boundary still fails closed."""
    codes = [f"{index:06d}.SZ" for index in range(65_536)]
    daily = pd.DataFrame(
        {
            "ts_code": codes + [codes[0]],
            "trade_date": ["20160104"] * 65_537,
            "close": np.arange(65_537, dtype=float),
        }
    )
    adj = pd.DataFrame(
        {
            "ts_code": pd.Series(dtype="str"),
            "trade_date": pd.Series(dtype="str"),
            "adj_factor": pd.Series(dtype="float64"),
        }
    )
    daily_path, adj_path, calendar_path = tmp_path / "daily.parquet", tmp_path / "adj.parquet", tmp_path / "calendar.parquet"
    daily.to_parquet(daily_path, index=False, row_group_size=32_768)
    adj.to_parquet(adj_path, index=False)
    pd.DataFrame({"trade_date": ["20160104"]}).to_parquet(calendar_path, index=False)
    source_before = daily_path.read_bytes()
    failed_root = tmp_path / "failed_output"

    with pytest.raises(market.MarketInputsError, match="daily_duplicate"):
        market.assemble_market_inputs(
            daily_path=daily_path,
            adj_factor_path=adj_path,
            calendar_path=calendar_path,
            output_root=failed_root,
        )

    assert failed_root.is_dir()
    assert (failed_root / "_join.sqlite").exists()
    assert daily_path.read_bytes() == source_before


def test_is_date_outside_explicit_calendar_fails_closed(tmp_path: Path):
    paths = _inputs(tmp_path)
    # 2016-01-05 is inside the frozen IS range, but not in this supplied calendar.
    pd.DataFrame({"trade_date": ["20160104"]}).to_parquet(paths[2], index=False)
    with pytest.raises(market.MarketInputsError, match="daily_date_outside_explicit_calendar"):
        market.assemble_market_inputs(
            daily_path=paths[0],
            adj_factor_path=paths[1],
            calendar_path=paths[2],
            output_root=tmp_path / "out",
        )
