"""Synthetic local-input assembler tests; no network, returns, or OOS."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples/mszq_intraday_momentum_pulse/pfvv_prepared_inputs_v1.py"
spec = importlib.util.spec_from_file_location("pfvv_prepared_inputs_test", MODULE_PATH)
assembler = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(assembler)


def _manifest(tmp_path: Path, count: int = 45) -> Path:
    days, entries = [], []
    for index in range(count):
        day = f"2016{index + 1:04d}"  # synthetic explicit labels only
        daily = tmp_path / f"daily_{day}.parquet"
        execution = tmp_path / f"execution_{day}.parquet"
        pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": [day], "pf_daily": [index + 0.1], "vv_daily": [index + 0.2]}).to_parquet(daily, index=False)
        pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": [day], "vwap_0945_1000_unadjusted": [None], "execution_bar_count": [15], "price_basis": ["UNADJUSTED_AMOUNT_OVER_VOL"], "execution_price_status": ["MISSING_OR_INVALID_16_BAR_WINDOW"], "extra": [index]}).to_parquet(execution, index=False)
        days.append(day)
        entries.append({"trade_date": day, "path": daily.name, "execution_path": execution.name,
                        "output_sha256": hashlib.sha256(daily.read_bytes()).hexdigest(), "execution_sha256": hashlib.sha256(execution.read_bytes()).hexdigest()})
    data = {"version": "pfvv_daily_measurements_manifest_v1", "status": "COMPLETE", "trading_calendar": days, "days": entries,
            "pfvv_prepared_daily_state": {"contract_version": "pfvv_prepared_daily_state_v1", "measurement_authority": "pfvv_source_baseline_v1",
                                           "calendar_dates": days, "day_paths": {row["trade_date"]: row["path"] for row in entries}}}
    path = tmp_path / "daily_measurements_manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_streams_full_and_sample_without_transmitting_full_paths(tmp_path: Path):
    manifest = _manifest(tmp_path)
    result = assembler.assemble_pfvv_prepared_inputs(manifest, tmp_path / "prepared")
    assert len(pd.read_parquet(result["measurement_domain_path"])) == 45
    assert len(pd.read_parquet(result["execution_vwap_path"])) == 45
    assert len(pd.read_parquet(result["sample_measurement_domain_path"])) == 40
    assert len(pd.read_parquet(result["sample_execution_vwap_path"])) == 40
    full = result["controllers"]["full"]["local_inputs"]["pfvv_prepared_daily_state"]
    sample = result["controllers"]["sample"]["local_inputs"]["pfvv_prepared_daily_state"]
    assert len(full["day_paths"]) == 45
    assert list(sample["day_paths"]) == [f"2016{index + 1:04d}" for index in range(40)]
    assert sample["calendar_dates"] == list(sample["day_paths"])
    assert set(sample["day_paths"]) != set(full["day_paths"])
    assert result["controllers"]["sample"]["local_inputs"]["daily_df_parquet"] == result["sample_measurement_domain_path"]
    assert result["controllers"]["sample"]["sample_budget"] == {"max_calendar_days": 40}
    assert result["controllers"]["sample"]["sample_calendar_dates"] == sample["calendar_dates"]
    assert result["controllers"]["sample"]["local_inputs"]["step3b_prepared_controller_config"].endswith("controller_sample.json")
    assert "execution_price_status" in pd.read_parquet(result["execution_vwap_path"]).columns


def test_sample_local_inputs_match_actual_step3_prepared_validator(tmp_path: Path):
    manifest = _manifest(tmp_path, 45)
    result = assembler.assemble_pfvv_prepared_inputs(manifest, tmp_path / "prepared")
    run_step3_path = ROOT / "skills/factor-forge-step3/scripts/run_step3.py"
    validator_spec = importlib.util.spec_from_file_location("run_step3_actual_validator", run_step3_path)
    run_step3 = importlib.util.module_from_spec(validator_spec)
    assert validator_spec and validator_spec.loader
    validator_spec.loader.exec_module(run_step3)
    sample = result["controllers"]["sample"]["local_inputs"]
    assert run_step3.validate_prepared_local_inputs(sample) == sample


def test_assembler_to_step3b_to_frozen_controller_is_sample_only(tmp_path: Path):
    # Use 40 valid synthetic business dates so the frozen calendar adapter can
    # exercise its 20-observation warm-up without touching real data.
    days = pd.bdate_range("2016-01-04", periods=40).strftime("%Y%m%d").tolist()
    entries = []
    for index, day in enumerate(days):
        daily = tmp_path / f"daily_{day}.parquet"
        execution = tmp_path / f"execution_{day}.parquet"
        pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "trade_date": [day, day],
                      "pf_daily": [float(index + 1), float(index + 2)], "vv_daily": [float(index + 2), float(index + 1)]}).to_parquet(daily, index=False)
        pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "trade_date": [day, day],
                      "vwap_0945_1000_unadjusted": [10.0, 11.0], "execution_bar_count": [16, 16],
                      "price_basis": ["UNADJUSTED_AMOUNT_OVER_VOL"] * 2,
                      "execution_price_status": ["AVAILABLE"] * 2}).to_parquet(execution, index=False)
        entries.append({"trade_date": day, "path": daily.name, "execution_path": execution.name,
                        "output_sha256": __import__("hashlib").sha256(daily.read_bytes()).hexdigest(),
                        "execution_sha256": __import__("hashlib").sha256(execution.read_bytes()).hexdigest()})
    manifest = tmp_path / "daily_measurements_manifest.json"
    manifest.write_text(json.dumps({"version": "pfvv_daily_measurements_manifest_v1", "status": "COMPLETE",
        "trading_calendar": days, "days": entries, "pfvv_prepared_daily_state": {
            "contract_version": "pfvv_prepared_daily_state_v1", "measurement_authority": "pfvv_source_baseline_v1",
            "calendar_dates": days, "day_paths": {item["trade_date"]: item["path"] for item in entries}}}), encoding="utf-8")
    result = assembler.assemble_pfvv_prepared_inputs(manifest, tmp_path / "prepared")
    sample_local = result["controllers"]["sample"]["local_inputs"]
    run_step3_spec = importlib.util.spec_from_file_location("run_step3_end_to_end_test", ROOT / "skills/factor-forge-step3/scripts/run_step3.py")
    run_step3 = importlib.util.module_from_spec(run_step3_spec)
    assert run_step3_spec and run_step3_spec.loader
    run_step3_spec.loader.exec_module(run_step3)
    assert run_step3.validate_prepared_local_inputs(sample_local) == sample_local
    run_step3b_spec = importlib.util.spec_from_file_location("run_step3b_end_to_end_test", ROOT / "skills/factor-forge-step3/scripts/run_step3b.py")
    run_step3b = importlib.util.module_from_spec(run_step3b_spec)
    assert run_step3b_spec and run_step3b_spec.loader
    run_step3b_spec.loader.exec_module(run_step3b)
    run_step3b.FF = tmp_path.parent / (tmp_path.name + "_factorforge")
    run_step3b.RUNS = run_step3b.FF / "runs"
    # The frozen study controller predates the generic high-speed policy's
    # metadata field; this test is about the real dispatch and output route.
    run_step3b.assert_high_speed_code_policy = lambda text, contract=None: {"synthetic_test": True}
    output = run_step3b.generate_first_run_factor_values(
        "synthetic_pfvv", "pfvv", ROOT / "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_partitioned_v1.py",
        sample_local, {}, trust_step3a_sort_contract=False,
    )
    values = pd.read_parquet(run_step3b.FF / output["output_paths"][0])
    assert set(values["trade_date"]) <= set(days[:40])
    assert values["factor_value"].notna().any()
    assert values.loc[values["trade_date"].isin(days[20:]), "factor_value"].notna().any()


@pytest.mark.parametrize("mutation", ["daily_hash", "execution_hash", "missing_day"])
def test_explicit_hash_and_day_fail_closed(tmp_path: Path, mutation: str):
    manifest = _manifest(tmp_path, 2)
    data = json.loads(manifest.read_text())
    if mutation == "daily_hash":
        data["days"][0]["output_sha256"] = "0" * 64
    elif mutation == "execution_hash":
        data["days"][0]["execution_sha256"] = "0" * 64
    else:
        data["days"].pop()
    manifest.write_text(json.dumps(data))
    with pytest.raises(assembler.PreparedInputsError):
        assembler.assemble_pfvv_prepared_inputs(manifest, tmp_path / "prepared")


def test_create_only_root_and_no_path_guessing(tmp_path: Path):
    manifest = _manifest(tmp_path, 1)
    target = tmp_path / "prepared"
    assembler.assemble_pfvv_prepared_inputs(manifest, target)
    with pytest.raises(assembler.PreparedInputsError, match="output_root"):
        assembler.assemble_pfvv_prepared_inputs(manifest, target)
    target.joinpath("daily_20160001.parquet").unlink(missing_ok=True)
    assert not target.joinpath("daily_20160001.parquet").exists()
