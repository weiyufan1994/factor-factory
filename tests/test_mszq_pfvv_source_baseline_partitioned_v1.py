"""Synthetic local-controller tests; they are not research or efficacy evidence."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_factory.partitioned_direct_code import run_partitioned_controller


WORKSPACE = Path(__file__).resolve().parents[1]
ADAPTER_PATH = WORKSPACE / "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_dataframe_adapter_v1.py"
PARTITIONED_PATH = WORKSPACE / "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_partitioned_v1.py"
PRODUCER_PATH = WORKSPACE / "examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py"


def load_module(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def modules():
    return (
        load_module("pfvv_adapter_partitioned_test", ADAPTER_PATH),
        load_module("pfvv_partitioned_test", PARTITIONED_PATH),
    )


def minute_fixture(days: int = 22, future_ticker: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    calendar = pd.bdate_range("2016-01-04", periods=days)
    base_codes = ["000001.SZ", "000002.SZ", "600000.SH", "600001.SH"]
    slots = np.r_[
        pd.date_range("2000-01-01 09:31", periods=120, freq="min").time,
        pd.date_range("2000-01-01 13:01", periods=120, freq="min").time,
    ]
    rows = []
    for day_number, day in enumerate(calendar):
        codes = [*base_codes, *( ["600002.SH"] if future_ticker and day_number >= 21 else [])]
        for code_number, code in enumerate(codes):
            opening = 10.0 + code_number
            close = opening
            scale = 0.0002 * (1.0 + day_number / 30.0)
            minute_return = [scale, scale * 1.1, scale * 4.0, -scale * 0.7, scale * 2.2][code_number]
            for slot_number, clock in enumerate(slots):
                current_return = minute_return * (1.0 + slot_number / 1000.0)
                close *= 1.0 + current_return
                rows.append(
                    {
                        "ts_code": code,
                        "trade_time": pd.Timestamp.combine(day.date(), clock),
                        "open": opening if slot_number == 0 else close / (1.0 + current_return),
                        "close": close,
                        "vol": 100.0 + code_number * 11.0 + (slot_number % 17) + day_number,
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame({"trade_date": calendar.strftime("%Y%m%d")})


def day_loader(frame: pd.DataFrame, calls: dict[pd.Timestamp, int] | None = None):
    by_day = {day: rows.copy() for day, rows in frame.groupby(frame["trade_time"].dt.normalize(), sort=False)}

    def load(day: pd.Timestamp):
        if calls is not None:
            calls[day] = calls.get(day, 0) + 1
        return by_day.get(day)

    return load


def stream_all(partitioned, calendar, loader, **kwargs) -> pd.DataFrame:
    outputs = list(partitioned.stream_pfvv_source_baseline(calendar, loader, **kwargs))
    return pd.concat(outputs, ignore_index=True) if outputs else partitioned._empty_output()


def frozen_full_panel_reference(adapter, minute: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    dates = adapter._resolve_calendar(None, calendar)
    frame, codes = adapter._validate_minute_rows(minute, dates)
    pf_rows = {}
    vv_rows = {}
    for day in dates:
        close, opening, volume = adapter._one_day_panels(frame, day, codes)
        returns = adapter._KERNEL.minute_returns(close, opening)
        pf_rows[day] = adapter._KERNEL.pf_daily(returns, expected_slots=adapter.EXPECTED_SLOTS)["daily"]
        vv_rows[day] = adapter._KERNEL.vv_daily(returns, volume, expected_slots=adapter.EXPECTED_SLOTS)["daily"]
    components = adapter._KERNEL.rolling_components(
        pd.DataFrame.from_dict(pf_rows, orient="index").reindex(index=dates, columns=codes),
        pd.DataFrame.from_dict(vv_rows, orient="index").reindex(index=dates, columns=codes),
        dates,
        window=20,
    )
    values = pd.concat(
        {
            "factor_value": components["score"],
            "PF": components["pf_raw"],
            "VV": components["vv_raw"],
            "PF_z": components["pf_z"],
            "VV_z": components["vv_z"],
        },
        axis=1,
    )
    values.index.name = "trade_date"
    values.columns.names = [None, "ts_code"]
    out = values.stack(level="ts_code", future_stack=True).reset_index()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y%m%d")
    return out


def test_streaming_matches_full_panel_frozen_rolling_components_and_crosses_chunks(modules):
    adapter, partitioned = modules
    minute, calendar = minute_fixture()
    reference = frozen_full_panel_reference(adapter, minute, calendar)
    calls = {}
    state = partitioned.PFVVPartitionState(calendar)
    first = list(partitioned.stream_pfvv_source_baseline(calendar, day_loader(minute, calls), state=state, stop_index=15))
    second = list(partitioned.stream_pfvv_source_baseline(calendar, day_loader(minute, calls), state=state, stop_index=len(calendar)))
    streamed = pd.concat([*first, *second], ignore_index=True)

    assert state.next_index == len(calendar)
    assert all(count == 1 for count in calls.values())
    assert state.retained_daily_state_count() <= 2 * 20 * minute["ts_code"].nunique()
    merged = streamed.merge(reference, on=["ts_code", "trade_date"], suffixes=("_stream", "_full"), validate="one_to_one")
    for column in ["PF", "VV", "PF_z", "VV_z", "factor_value"]:
        np.testing.assert_allclose(merged[f"{column}_stream"], merged[f"{column}_full"], equal_nan=True)
    np.testing.assert_allclose(merged["composite"], merged["factor_value_stream"], equal_nan=True)
    assert streamed.loc[streamed["trade_date"].isin(calendar["trade_date"].iloc[:19]), "warmup"].all()
    assert streamed.loc[streamed["trade_date"].eq(calendar["trade_date"].iloc[19]), "warmup"].eq(False).all()


def test_missing_whole_day_and_missing_minute_remain_nan_without_calendar_compression(modules):
    _, partitioned = modules
    minute, calendar = minute_fixture()
    day20 = pd.Timestamp(calendar["trade_date"].iloc[20])
    day21 = pd.Timestamp(calendar["trade_date"].iloc[21])
    bad_minute = minute.loc[
        ~(
            minute["ts_code"].eq("000001.SZ")
            & minute["trade_time"].eq(day21 + pd.Timedelta(hours=10))
        )
    ].copy()
    loader = day_loader(bad_minute)
    original = loader

    def missing_day_loader(day):
        return None if day == day20 else original(day)

    streamed = stream_all(partitioned, calendar, missing_day_loader)
    assert streamed["trade_date"].nunique() == len(calendar)
    missing_day_rows = streamed.loc[streamed["trade_date"].eq(day20.strftime("%Y%m%d"))]
    assert len(missing_day_rows) == 4
    assert missing_day_rows[["PF", "VV", "factor_value"]].isna().all().all()
    partial_row = streamed.loc[
        streamed["trade_date"].eq(day21.strftime("%Y%m%d")) & streamed["ts_code"].eq("000001.SZ")
    ].iloc[0]
    assert pd.isna(partial_row["PF"])
    assert pd.isna(partial_row["factor_value"])


def test_future_ticker_does_not_revise_history_and_is_its_own_warmup(modules):
    _, partitioned = modules
    base, calendar = minute_fixture()
    future, _ = minute_fixture(future_ticker=True)
    base_out = stream_all(partitioned, calendar, day_loader(base))
    future_out = stream_all(partitioned, calendar, day_loader(future))
    before_arrival = calendar["trade_date"].iloc[:21]
    compare_base = base_out.loc[base_out["trade_date"].isin(before_arrival)].sort_values(["trade_date", "ts_code"])
    compare_future = future_out.loc[future_out["trade_date"].isin(before_arrival)].sort_values(["trade_date", "ts_code"])
    pd.testing.assert_frame_equal(compare_base.reset_index(drop=True), compare_future.reset_index(drop=True))
    new_row = future_out.loc[
        future_out["trade_date"].eq(calendar["trade_date"].iloc[21]) & future_out["ts_code"].eq("600002.SH")
    ].iloc[0]
    assert new_row["warmup"]
    assert pd.isna(new_row["factor_value"])


def test_rejects_0930_and_daily_budget_before_pivot(modules):
    _, partitioned = modules
    minute, calendar = minute_fixture()
    bad_clock = minute.copy()
    bad_clock.loc[bad_clock.index[0], "trade_time"] = pd.Timestamp("2016-01-04 09:30")
    with pytest.raises(ValueError, match="midnight and 09:30"):
        list(partitioned.stream_pfvv_source_baseline(calendar, day_loader(bad_clock)))
    with pytest.raises(ValueError, match="BLOCK_PFVV_PARTITIONED_DAY_BUDGET"):
        list(partitioned.stream_pfvv_source_baseline(calendar, day_loader(minute), max_raw_rows_per_day=1))


def test_full_is_sized_calendar_can_start_with_an_empty_local_stream(modules):
    _, partitioned = modules
    # This is only a calendar/streaming control test: it supplies no minute
    # observations and is not a synthetic factor result or full-IS claim.
    calendar = pd.DataFrame({"trade_date": pd.bdate_range("2016-01-04", periods=2313).strftime("%Y%m%d")})
    calls = []

    def empty_loader(day):
        calls.append(day)
        return None

    state = partitioned.PFVVPartitionState(calendar)
    outputs = list(partitioned.stream_pfvv_source_baseline(calendar, empty_loader, state=state, stop_index=1))
    assert len(outputs) == 1
    assert outputs[0].empty
    assert state.next_index == 1
    assert calls == [pd.Timestamp("2016-01-04")]


def test_failed_kernel_call_marks_state_nonreusable_and_never_reloads_that_day(modules, monkeypatch):
    _, partitioned = modules
    minute, calendar = minute_fixture()
    calls = {}
    state = partitioned.PFVVPartitionState(calendar)

    def fail_kernel(*args, **kwargs):
        raise RuntimeError("synthetic kernel failure")

    monkeypatch.setattr(partitioned._KERNEL, "pf_daily", fail_kernel)
    loader = day_loader(minute, calls)
    with pytest.raises(RuntimeError, match="synthetic kernel failure"):
        list(partitioned.stream_pfvv_source_baseline(calendar, loader, state=state, stop_index=1))
    assert state.failed
    assert state.outputs_reusable is False
    assert state.next_index == 0
    assert state.known_tickers == []
    assert state.pf_history == {}
    assert state.vv_z_history == {}
    assert calls == {pd.Timestamp("2016-01-04"): 1}
    with pytest.raises(RuntimeError, match="cannot resume after a failed day"):
        list(partitioned.stream_pfvv_source_baseline(calendar, loader, state=state, stop_index=1))
    assert calls == {pd.Timestamp("2016-01-04"): 1}


def test_invalid_state_index_blocks_before_loader_call(modules):
    _, partitioned = modules
    _, calendar = minute_fixture()
    state = partitioned.PFVVPartitionState(calendar)
    state.next_index = "bad"
    calls = []
    with pytest.raises(ValueError, match="state.next_index"):
        list(partitioned.stream_pfvv_source_baseline(calendar, lambda day: calls.append(day), state=state, stop_index=1))
    assert calls == []


def prepared_daily_partitions(tmp_path: Path, adapter, minute: pd.DataFrame, calendar: pd.DataFrame) -> tuple[Path, dict]:
    root = tmp_path / "prepared_state"
    root.mkdir()
    dates = adapter._resolve_calendar(None, calendar)
    frame, codes = adapter._validate_minute_rows(minute, dates)
    day_paths = {}
    for day in dates:
        close, opening, volume = adapter._one_day_panels(frame, day, codes)
        returns = adapter._KERNEL.minute_returns(close, opening)
        pf_daily = adapter._KERNEL.pf_daily(returns, expected_slots=adapter.EXPECTED_SLOTS)["daily"]
        vv_daily = adapter._KERNEL.vv_daily(returns, volume, expected_slots=adapter.EXPECTED_SLOTS)["daily"]
        path = root / f"{day:%Y%m%d}.parquet"
        pd.DataFrame(
            {
                "ts_code": codes,
                "trade_date": day.strftime("%Y%m%d"),
                "pf_daily": pf_daily.reindex(codes).to_numpy(),
                "vv_daily": vv_daily.reindex(codes).to_numpy(),
            }
        ).to_parquet(path, index=False)
        day_paths[day.strftime("%Y%m%d")] = path.name
    contract = {
        "contract_version": "pfvv_prepared_daily_state_v1",
        "measurement_authority": "pfvv_source_baseline_v1",
        "calendar_dates": calendar["trade_date"].tolist(),
        "day_paths": day_paths,
        "required_columns": ["ts_code", "trade_date", "pf_daily", "vv_daily"],
    }
    return root, contract


def test_prepared_daily_state_controller_uses_explicit_partitions_and_step_owned_output(modules, tmp_path):
    adapter, partitioned = modules
    minute, calendar = minute_fixture()
    root, contract = prepared_daily_partitions(tmp_path, adapter, minute, calendar)
    output = tmp_path / "step_owned" / "factor_values.parquet"
    unreadable_daily_input = tmp_path / "daily.parquet"
    unreadable_daily_input.write_bytes(b"must not be read")
    local_inputs = {
        "input_mode": "derived_state_with_daily",
        "pfvv_prepared_daily_state": contract,
    }
    result = run_partitioned_controller(
        SimpleNamespace(compute_factor_partitioned=partitioned.compute_factor_partitioned),
        local_inputs=local_inputs,
        derived_state_root=root,
        daily_input_path=unreadable_daily_input,
        output_path=output,
        run_dir=tmp_path,
        report_id="PFVV_TEST",
        factor_id="PFVV",
        factorforge_root=tmp_path,
        workspace_root=tmp_path,
    )
    assert result == output.resolve()
    actual = pd.read_parquet(result)
    reference = frozen_full_panel_reference(adapter, minute, calendar)
    merged = actual.merge(reference, on=["ts_code", "trade_date"], suffixes=("_prepared", "_full"), validate="one_to_one")
    for column in ["PF", "VV", "PF_z", "VV_z", "factor_value"]:
        np.testing.assert_allclose(merged[f"{column}_prepared"], merged[f"{column}_full"], equal_nan=True)
    assert not (root in output.resolve().parents)


def test_prepared_daily_state_null_day_preserves_calendar_and_manifest_escape_blocks(modules, tmp_path):
    adapter, partitioned = modules
    minute, calendar = minute_fixture()
    root, contract = prepared_daily_partitions(tmp_path, adapter, minute, calendar)
    missing_day = calendar["trade_date"].iloc[20]
    contract["day_paths"][missing_day] = None
    output = tmp_path / "result.parquet"
    partitioned.compute_factor_partitioned(
        local_inputs={"input_mode": "derived_state_with_daily", "pfvv_prepared_daily_state": contract},
        derived_state_root=root,
        daily_input_path=tmp_path / "unused.parquet",
        output_path=output,
    )
    result = pd.read_parquet(output)
    missing_rows = result.loc[result["trade_date"].eq(missing_day)]
    assert len(missing_rows) == 4
    assert missing_rows[["PF", "VV", "factor_value"]].isna().all().all()

    bad = {**contract, "day_paths": dict(contract["day_paths"])}
    bad["day_paths"][calendar["trade_date"].iloc[0]] = "../outside.parquet"
    with pytest.raises(ValueError, match="escapes derived_state_root"):
        partitioned.compute_factor_partitioned(
            local_inputs={"input_mode": "derived_state_with_daily", "pfvv_prepared_daily_state": bad},
            derived_state_root=root,
            daily_input_path=tmp_path / "unused.parquet",
            output_path=tmp_path / "blocked.parquet",
        )


@pytest.mark.parametrize("column, invalid", [("pf_daily", np.inf), ("pf_daily", -np.inf), ("vv_daily", np.inf), ("vv_daily", -np.inf)])
def test_prepared_daily_state_allows_missing_but_rejects_infinite_measurements(modules, column, invalid):
    _, partitioned = modules
    day = pd.Timestamp("2016-01-04")
    allowed = pd.DataFrame(
        {"ts_code": ["000001.SZ"], "trade_date": ["20160104"], "pf_daily": [np.nan], "vv_daily": [np.nan]}
    )
    pf_daily, vv_daily, _ = partitioned._validate_prepared_daily_frame(allowed, day)
    assert np.isnan(pf_daily.iloc[0])
    assert np.isnan(vv_daily.iloc[0])
    rejected = allowed.copy()
    rejected.loc[0, column] = invalid
    with pytest.raises(ValueError, match=r"must not contain \+/-inf"):
        partitioned._validate_prepared_daily_frame(rejected, day)


def test_prepared_state_root_symlink_and_concurrent_publication_are_rejected(modules, tmp_path, monkeypatch):
    adapter, partitioned = modules
    minute, calendar = minute_fixture()
    root, contract = prepared_daily_partitions(tmp_path, adapter, minute, calendar)
    alias = tmp_path / "prepared_state_alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - platform configuration
        pytest.skip(f"symlink unavailable: {exc}")
    kwargs = {
        "local_inputs": {"input_mode": "derived_state_with_daily", "pfvv_prepared_daily_state": contract},
        "daily_input_path": tmp_path / "unused.parquet",
    }
    with pytest.raises(ValueError, match="must not use a symlink alias"):
        partitioned.compute_factor_partitioned(
            **kwargs, derived_state_root=alias, output_path=tmp_path / "alias_blocked.parquet"
        )

    output = tmp_path / "published.parquet"
    def lose_publication_race(source, target):
        raise FileExistsError("synthetic competing publisher")

    monkeypatch.setattr(partitioned.os, "link", lose_publication_race)
    with pytest.raises(ValueError, match="created concurrently; partial retained"):
        partitioned.compute_factor_partitioned(**kwargs, derived_state_root=root, output_path=output)
    assert not output.exists()
    assert output.with_name(output.name + ".partial").is_file()


def test_synthetic_producer_to_prepared_controller_parity_and_first_finite_day(modules, tmp_path):
    """Pure synthetic daily preparation integration; it does not evaluate returns."""
    adapter, partitioned = modules
    producer = load_module("pfvv_producer_to_controller_integration_test", PRODUCER_PATH)
    minute, calendar = minute_fixture()
    root = tmp_path / "producer_daily_states"
    root.mkdir()
    day_paths = {}
    for declared_day in calendar["trade_date"]:
        raw_day = minute.loc[minute["trade_time"].dt.strftime("%Y%m%d").eq(declared_day)].copy()
        prepared, _ = producer.compute_daily_measurements(raw_day, declared_day)
        path = root / f"daily_{declared_day}.parquet"
        prepared.to_parquet(path, index=False)
        day_paths[declared_day] = path.name
    contract = {
        "contract_version": "pfvv_prepared_daily_state_v1",
        "measurement_authority": "pfvv_source_baseline_v1",
        "calendar_dates": calendar["trade_date"].tolist(),
        "day_paths": day_paths,
        "required_columns": ["ts_code", "trade_date", "pf_daily", "vv_daily"],
    }
    output = tmp_path / "synthetic_prepared_factor.parquet"
    partitioned.compute_factor_partitioned(
        local_inputs={"input_mode": "derived_state_with_daily", "pfvv_prepared_daily_state": contract},
        derived_state_root=root,
        daily_input_path=tmp_path / "not_read.parquet",
        output_path=output,
    )
    actual = pd.read_parquet(output)
    reference = frozen_full_panel_reference(adapter, minute, calendar)
    merged = actual.merge(reference, on=["ts_code", "trade_date"], suffixes=("_actual", "_reference"), validate="one_to_one")
    for column in ["PF", "VV", "PF_z", "VV_z", "factor_value"]:
        np.testing.assert_allclose(merged[f"{column}_actual"], merged[f"{column}_reference"], equal_nan=True)
    first_finite = actual.loc[actual["factor_value"].notna(), "trade_date"].min()
    assert first_finite == calendar["trade_date"].iloc[19]


def test_partitioned_entry_advertises_prepared_state_without_raw_minute_access(modules):
    _, partitioned = modules
    assert partitioned.METADATA["prepared_state_projection"] is True
    assert partitioned.METADATA["raw_minute_access"] is False
    assert callable(partitioned.compute_factor_partitioned)


def test_step3b_prepared_controller_validator_accepts_the_real_entry():
    validator = load_module(
        "validate_step3b_pfvv_partitioned_test",
        WORKSPACE / "skills/factor-forge-step3/scripts/validate_step3b.py",
    )
    validator.validate_prepared_partitioned_controller(PARTITIONED_PATH)
