"""Prepared-state Step3B sample dispatch regression coverage only."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest


REPO = Path(__file__).resolve().parents[1]


def _load_step3b():
    path = REPO / "skills/factor-forge-step3/scripts/run_step3b.py"
    spec = importlib.util.spec_from_file_location("step3b_prepared_sample_dispatch_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_pfvv_assembler():
    path = REPO / "examples/mszq_intraday_momentum_pulse/pfvv_prepared_inputs_v1.py"
    spec = importlib.util.spec_from_file_location("pfvv_prepared_inputs_step3b_integration_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _implementation(path: Path) -> None:
    path.write_text(
        "from examples.mszq_intraday_momentum_pulse import pfvv_source_baseline_partitioned_v1 as _pfvv\n"
        "METADATA = _pfvv.METADATA\n"
        "def compute_factor_partitioned(*, local_inputs, derived_state_root, daily_input_path, output_path):\n"
        "    return _pfvv.compute_factor_partitioned(local_inputs=local_inputs, derived_state_root=derived_state_root, daily_input_path=daily_input_path, output_path=output_path)\n",
        encoding="utf-8",
    )


def _sample_config(tmp_path: Path, days: int = 40) -> tuple[dict, list[str], Path]:
    calendar = pd.bdate_range("2016-01-04", periods=days).strftime("%Y%m%d").tolist()
    sample = tmp_path / "sample"
    state_root = sample / "states"
    state_root.mkdir(parents=True)
    codes = ["000001.SZ", "000002.SZ", "600000.SH", "600001.SH"]
    control_rows = []
    day_paths = {}
    for day_index, day in enumerate(calendar):
        rows = []
        for code_index, code in enumerate(codes):
            # Deliberately varying cross-sections make the post-warmup output
            # non-null, while remaining wholly synthetic measurement state.
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": day,
                    "pf_daily": (code_index + 1) * ((day_index % 7) + 1) + day_index / 10,
                    "vv_daily": ((code_index + 1) * (day_index % 5)) + ((code_index + day_index) % 3),
                }
            )
        frame = pd.DataFrame(rows)
        path = state_root / f"daily_{day}.parquet"
        frame.to_parquet(path, index=False)
        control_rows.extend(frame[["ts_code", "trade_date"]].to_dict("records"))
        day_paths[day] = path.name
    control = sample / "measurement_domain.parquet"
    pd.DataFrame(control_rows).to_parquet(control, index=False)
    sample_inputs = {
        "input_mode": "derived_state_with_daily",
        "daily_df_parquet": "sample/measurement_domain.parquet",
        "derived_state_root": "sample/states",
        "calendar_dates": calendar,
        "pfvv_prepared_daily_state": {
            "contract_version": "pfvv_prepared_daily_state_v1",
            "measurement_authority": "pfvv_source_baseline_v1",
            "calendar_dates": calendar,
            "day_paths": day_paths,
            "required_columns": ["ts_code", "trade_date", "pf_daily", "vv_daily"],
        },
    }
    config = sample / "controller_sample.json"
    config.write_text(
        json.dumps(
            {
                "controller": "sample",
                "sample_budget": {"max_calendar_days": 40},
                "sample_calendar_dates": calendar,
                "local_inputs": sample_inputs,
            }
        ),
        encoding="utf-8",
    )
    # Primary/full declarations deliberately cannot be read as a dataframe;
    # success proves generate_first_run selected the isolated sample config.
    full = tmp_path / "full"
    full.mkdir()
    (full / "not_a_dataframe.parquet").write_bytes(b"full state must not be consumed by Step3B")
    top = {
        "input_mode": "derived_state_with_daily",
        "daily_df_parquet": "full/not_a_dataframe.parquet",
        "derived_state_root": "full",
        "calendar_dates": [*calendar, "20160301"],
        "pfvv_prepared_daily_state": {"calendar_dates": [*calendar, "20160301"], "day_paths": {}},
        "step3b_daily_df_parquet": "sample/measurement_domain.parquet",
        "step3b_derived_state_root": "sample/states",
        "step3b_calendar_dates": calendar,
        "step3b_prepared_controller_config": "sample/controller_sample.json",
    }
    return top, calendar, config


def test_generate_first_run_uses_only_explicit_40_day_sample_controller(tmp_path: Path):
    step3b = _load_step3b()
    assert step3b.step3b_first_run_dispatch_enabled("derived_state_with_daily", None, None) is True
    assert step3b.step3b_first_run_dispatch_enabled("daily_only", None, None) is False
    step3b.WORKSPACE = tmp_path
    step3b.FF = tmp_path / "factorforge"
    step3b.RUNS = step3b.FF / "runs"
    implementation = tmp_path / "prepared_impl.py"
    _implementation(implementation)
    top_inputs, calendar, config = _sample_config(tmp_path)

    result = step3b.generate_first_run_factor_values(
        report_id="SYNTHETIC_PFVV",
        factor_id="PFVV_COMPOSITE",
        implementation_path=implementation,
        local_inputs=top_inputs,
        step2_research_context={},
        csv_output_policy="no_csv",
    )

    assert result["status"] == "ready"
    assert result["signal_column"] == "factor_value"
    output = step3b.FF / result["output_paths"][0]
    actual = pd.read_parquet(output)
    assert set(actual["trade_date"]) == set(calendar)
    assert actual["trade_date"].max() == calendar[-1]
    assert actual["factor_value"].notna().any()
    metadata = json.loads((step3b.FF / result["run_metadata_path"]).read_text())
    assert metadata["sample_only"] is True
    assert metadata["prepared_sample_calendar_dates"] == calendar
    assert metadata["input_paths"]["prepared_sample_controller_config"] == str(config.resolve())
    assert metadata["input_paths"]["daily"].endswith("sample/measurement_domain.parquet")


def test_prepared_route_without_explicit_sample_controller_fails_closed(tmp_path: Path):
    step3b = _load_step3b()
    step3b.WORKSPACE = tmp_path
    implementation = tmp_path / "prepared_impl.py"
    _implementation(implementation)
    top_inputs, _, _ = _sample_config(tmp_path)
    top_inputs.pop("step3b_prepared_controller_config")

    with pytest.raises(SystemExit, match="PREPARED_SAMPLE_CONFIG_MISSING"):
        step3b.generate_first_run_factor_values(
            report_id="SYNTHETIC_PFVV",
            factor_id="PFVV_COMPOSITE",
            implementation_path=implementation,
            local_inputs=top_inputs,
            step2_research_context={},
            csv_output_policy="no_csv",
        )


def test_prepared_sample_controller_refuses_more_than_40_days(tmp_path: Path):
    step3b = _load_step3b()
    step3b.WORKSPACE = tmp_path
    top_inputs, _, config = _sample_config(tmp_path, days=41)
    with pytest.raises(SystemExit, match="PREPARED_SAMPLE_CONFIG_INVALID"):
        step3b.load_prepared_step3b_sample_inputs(top_inputs)
    assert config.exists()


def test_generic_prepared_controller_uses_its_own_sample_budget_not_pfvv_keys(tmp_path: Path):
    step3b = _load_step3b()
    step3b.WORKSPACE = tmp_path
    step3b.FF = tmp_path.parent / (tmp_path.name + "_factorforge")
    step3b.RUNS = step3b.FF / "runs"
    calendar = ["20200102", "20200103"]
    sample = tmp_path / "generic_sample"
    sample.mkdir()
    daily = sample / "daily.parquet"
    pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "trade_date": [calendar[0], calendar[0], calendar[1], calendar[1]],
        }
    ).to_parquet(daily, index=False)
    state_root = sample / "state"
    state_root.mkdir()
    sample_inputs = {
        "input_mode": "derived_state_with_daily",
        "daily_df_parquet": "generic_sample/daily.parquet",
        "derived_state_root": "generic_sample/state",
        "calendar_dates": calendar,
        "another_factor_prepared_state": {"opaque_controller_owned": True},
    }
    config = sample / "controller_sample.json"
    config.write_text(
        json.dumps(
            {
                "controller": "sample",
                "sample_budget": {"max_calendar_days": 2},
                "sample_calendar_dates": calendar,
                "local_inputs": sample_inputs,
            }
        ),
        encoding="utf-8",
    )
    implementation = tmp_path / "generic_prepared_impl.py"
    implementation.write_text(
        "import pandas as pd\n"
        "METADATA = {'prepared_state_projection': True, 'raw_minute_access': False}\n"
        "def compute_factor_partitioned(*, daily_input_path, output_path, **kwargs):\n"
        "    frame = pd.read_parquet(daily_input_path)\n"
        "    frame['factor_value'] = 1.0\n"
        "    frame.to_parquet(output_path, index=False)\n"
        "    return output_path\n",
        encoding="utf-8",
    )
    full = tmp_path / "generic_full"
    full.mkdir()
    (full / "unreadable.parquet").write_bytes(b"not a dataframe")
    top = {
        "input_mode": "derived_state_with_daily",
        "daily_df_parquet": "generic_full/unreadable.parquet",
        "derived_state_root": "generic_full",
        "step3b_daily_df_parquet": "generic_sample/daily.parquet",
        "step3b_derived_state_root": "generic_sample/state",
        "step3b_prepared_controller_config": "generic_sample/controller_sample.json",
    }
    result = step3b.generate_first_run_factor_values(
        report_id="GENERIC_PREPARED",
        factor_id="GENERIC_FACTOR",
        implementation_path=implementation,
        local_inputs=top,
        step2_research_context={},
        csv_output_policy="no_csv",
    )
    assert result["status"] == "ready"
    assert result["date_count"] == 2
    assert result["signal_column"] == "factor_value"


def test_actual_pfvv_assembler_sample_config_drives_generate_chain(tmp_path: Path):
    """Exercise the assembler-produced controller_sample.json, not a hand mock."""
    assembler = _load_pfvv_assembler()
    day = "20160104"
    daily = tmp_path / f"daily_{day}.parquet"
    execution = tmp_path / f"execution_{day}.parquet"
    codes = ["000001.SZ", "000002.SZ", "600000.SH", "600001.SH"]
    pd.DataFrame(
        {
            "ts_code": codes,
            "trade_date": [day] * len(codes),
            "pf_daily": [0.1, 0.2, 0.3, 0.4],
            "vv_daily": [0.4, 0.3, 0.2, 0.1],
        }
    ).to_parquet(daily, index=False)
    pd.DataFrame(
        {
            "ts_code": codes,
            "trade_date": [day] * len(codes),
            "vwap_0945_1000_unadjusted": [None] * len(codes),
            "execution_bar_count": [0] * len(codes),
            "price_basis": ["UNADJUSTED_AMOUNT_OVER_VOL"] * len(codes),
            "execution_price_status": ["MISSING_OR_INVALID_16_BAR_WINDOW"] * len(codes),
        }
    ).to_parquet(execution, index=False)
    manifest = tmp_path / "daily_measurements_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "pfvv_daily_measurements_manifest_v1",
                "status": "COMPLETE",
                "trading_calendar": [day],
                "days": [
                    {
                        "trade_date": day,
                        "path": daily.name,
                        "execution_path": execution.name,
                        "output_sha256": hashlib.sha256(daily.read_bytes()).hexdigest(),
                        "execution_sha256": hashlib.sha256(execution.read_bytes()).hexdigest(),
                    }
                ],
                "pfvv_prepared_daily_state": {
                    "contract_version": "pfvv_prepared_daily_state_v1",
                    "measurement_authority": "pfvv_source_baseline_v1",
                    "calendar_dates": [day],
                    "day_paths": {day: daily.name},
                },
            }
        ),
        encoding="utf-8",
    )
    prepared = assembler.assemble_pfvv_prepared_inputs(manifest, tmp_path / "prepared", sample_days=1)
    top_inputs = prepared["controllers"]["sample"]["local_inputs"]
    step3b = _load_step3b()
    step3b.WORKSPACE = tmp_path
    step3b.FF = tmp_path.parent / (tmp_path.name + "_assembler_factorforge")
    step3b.RUNS = step3b.FF / "runs"
    implementation = tmp_path / "prepared_impl.py"
    _implementation(implementation)
    result = step3b.generate_first_run_factor_values(
        report_id="ASSEMBLER_PFVV",
        factor_id="PFVV_COMPOSITE",
        implementation_path=implementation,
        local_inputs=top_inputs,
        step2_research_context={},
        csv_output_policy="no_csv",
    )
    assert result["status"] == "ready"
    assert result["date_count"] == 1
    metadata = json.loads((step3b.FF / result["run_metadata_path"]).read_text())
    assert metadata["prepared_sample_calendar_dates"] == [day]
    assert metadata["input_paths"]["prepared_sample_controller_config"].endswith("controller_sample.json")
