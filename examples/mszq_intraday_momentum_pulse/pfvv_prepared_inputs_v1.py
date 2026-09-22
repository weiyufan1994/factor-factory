"""Assemble closed, producer-owned PF/VV daily inputs for local callers.

This module is intentionally an input assembler, not a data producer.  It
consumes only the completed ``pfvv_daily_measurements_manifest_v1`` and the
explicit files named by that manifest.  No network, raw minute input, return,
OOS, or directory discovery is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


SCHEMA_VERSION = "pfvv_prepared_inputs_v1"
DAILY_COLUMNS = ["ts_code", "trade_date", "pf_daily", "vv_daily"]
EXECUTION_REQUIRED = {
    "ts_code", "trade_date", "vwap_0945_1000_unadjusted", "execution_bar_count",
    "price_basis", "execution_price_status",
}
REFERENCE_PATH_FIELDS = (
    "daily_prices_path", "adj_factor_path", "normalized_constraints_path", "constraints_path",
)


class PreparedInputsError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _explicit_file(value: Any, *, base: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PreparedInputsError(f"{field}_must_be_explicit_path")
    candidate = Path(value).expanduser()
    path = candidate if candidate.is_absolute() else base / candidate
    if path.is_symlink() or not path.is_file():
        raise PreparedInputsError(f"{field}_missing_or_symlink:{path}")
    return path.resolve()


def _validate_manifest(manifest: dict[str, Any], manifest_path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    if manifest.get("version") != "pfvv_daily_measurements_manifest_v1":
        raise PreparedInputsError("producer_manifest_version_mismatch")
    if manifest.get("status") != "COMPLETE":
        raise PreparedInputsError("producer_manifest_not_complete")
    calendar = manifest.get("trading_calendar")
    days = manifest.get("days")
    if not isinstance(calendar, list) or not calendar or any(not isinstance(day, str) for day in calendar):
        raise PreparedInputsError("trading_calendar_must_be_explicit_nonempty_list")
    if len(calendar) != len(set(calendar)) or any(len(day) != 8 or not day.isdigit() for day in calendar):
        raise PreparedInputsError("trading_calendar_invalid_or_duplicate")
    if not isinstance(days, list) or len(days) != len(calendar):
        raise PreparedInputsError("days_must_cover_exact_calendar")
    by_date = {row.get("trade_date"): row for row in days if isinstance(row, dict)}
    if set(by_date) != set(calendar):
        raise PreparedInputsError("days_trade_dates_do_not_match_calendar")
    ordered = []
    base = manifest_path.parent
    state = manifest.get("pfvv_prepared_daily_state")
    if not isinstance(state, dict) or state.get("contract_version") != "pfvv_prepared_daily_state_v1":
        raise PreparedInputsError("prepared_daily_state_contract_missing")
    if state.get("measurement_authority") != "pfvv_source_baseline_v1":
        raise PreparedInputsError("prepared_daily_state_authority_mismatch")
    if state.get("calendar_dates") != calendar:
        raise PreparedInputsError("prepared_daily_state_calendar_mismatch")
    state_paths = state.get("day_paths")
    if not isinstance(state_paths, dict) or set(state_paths) != set(calendar):
        raise PreparedInputsError("prepared_daily_state_day_paths_mismatch")
    for day in calendar:
        row = by_date[day]
        for field in ("path", "execution_path", "output_sha256", "execution_sha256"):
            if field not in row:
                raise PreparedInputsError(f"day_{field}_missing:{day}")
        if row["path"] != state_paths[day]:
            raise PreparedInputsError(f"day_path_state_mismatch:{day}")
        path = _explicit_file(row["path"], base=base, field=f"day_path:{day}")
        execution = _explicit_file(row["execution_path"], base=base, field=f"execution_path:{day}")
        if _sha256(path) != row["output_sha256"]:
            raise PreparedInputsError(f"day_output_hash_mismatch:{day}")
        if _sha256(execution) != row["execution_sha256"]:
            raise PreparedInputsError(f"day_execution_hash_mismatch:{day}")
        ordered.append({"trade_date": day, "path": path, "execution_path": execution})
    return calendar, ordered


def _path_reference(manifest: dict[str, Any], key: str, base: Path) -> str | None:
    if key not in manifest:
        return None
    return str(_explicit_file(manifest[key], base=base, field=key))


def _write_controller(path: Path, config: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(config, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def assemble_pfvv_prepared_inputs(manifest_path: str | Path, output_root: str | Path, *, sample_days: int = 40) -> dict[str, Any]:
    """Materialize measurement/execution domains and return full/sample callers."""
    source_manifest = Path(manifest_path).expanduser().resolve()
    try:
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparedInputsError("producer_manifest_unreadable") from exc
    if not isinstance(manifest, dict):
        raise PreparedInputsError("producer_manifest_must_be_object")
    if isinstance(sample_days, bool) or not isinstance(sample_days, int) or not 0 < sample_days <= 40:
        raise PreparedInputsError("sample_days_must_be_between_1_and_40")
    calendar, rows = _validate_manifest(manifest, source_manifest)
    root = Path(output_root).expanduser()
    if not root.is_absolute() or root.exists() or not root.parent.is_dir() or root.is_symlink():
        raise PreparedInputsError("output_root_must_be_new_absolute_directory")
    root.mkdir()
    base = source_manifest.parent
    selected = rows[:sample_days]
    measurement_path = root / "measurement_domain.parquet"
    execution_path = root / "execution_vwap.parquet"
    sample_measurement_path = root / "measurement_domain_sample.parquet"
    sample_execution_path = root / "execution_vwap_sample.parquet"
    calendar_path = root / "trading_calendar.json"
    sample_calendar_path = root / "trading_calendar_sample.json"
    writers: dict[str, Any] = {}
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        for row in rows:
            daily = pd.read_parquet(row["path"], columns=DAILY_COLUMNS)
            if list(daily.columns) != DAILY_COLUMNS or daily.empty:
                raise PreparedInputsError(f"daily_measurement_schema_invalid:{row['trade_date']}")
            if daily["trade_date"].astype(str).ne(row["trade_date"]).any() or daily[["ts_code", "trade_date"]].duplicated().any():
                raise PreparedInputsError(f"daily_measurement_date_or_key_invalid:{row['trade_date']}")
            execution = pd.read_parquet(row["execution_path"])
            if not EXECUTION_REQUIRED.issubset(execution.columns):
                raise PreparedInputsError(f"execution_schema_invalid:{row['trade_date']}")
            if execution["trade_date"].astype(str).ne(row["trade_date"]).any():
                raise PreparedInputsError(f"execution_date_invalid:{row['trade_date']}")
            domains = pa.Table.from_pandas(daily.loc[:, ["ts_code", "trade_date"]], preserve_index=False)
            executions = pa.Table.from_pandas(execution, preserve_index=False)
            tables = [("measurement", domains, measurement_path), ("execution", executions, execution_path)]
            if row in selected:
                tables.extend((("sample_measurement", domains, sample_measurement_path),
                               ("sample_execution", executions, sample_execution_path)))
            for name, table, target in tables:
                if name not in writers:
                    writers[name] = pq.ParquetWriter(target, table.schema)
                writers[name].write_table(table)
    finally:
        for writer in writers.values():
            writer.close()
    with calendar_path.open("x", encoding="utf-8") as stream:
        json.dump(calendar, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    with sample_calendar_path.open("x", encoding="utf-8") as stream:
        json.dump(calendar[:sample_days], stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    refs = {key: _path_reference(manifest, key, base) for key in REFERENCE_PATH_FIELDS}
    refs = {key: value for key, value in refs.items() if value is not None}
    def controller(name: str, chosen: list[dict[str, Any]]) -> dict[str, Any]:
        dates = [item["trade_date"] for item in chosen]
        day_paths = {item["trade_date"]: os.fspath(item["path"]) for item in chosen}
        contract = {"contract_version": "pfvv_prepared_daily_state_v1", "measurement_authority": "pfvv_source_baseline_v1",
                    "calendar_dates": dates, "day_paths": day_paths, "required_columns": DAILY_COLUMNS}
        is_sample = name == "sample"
        selected_measurement_path = sample_measurement_path if is_sample else measurement_path
        selected_execution_path = sample_execution_path if is_sample else execution_path
        selected_calendar_path = sample_calendar_path if is_sample else calendar_path
        actual_window = {"start": dates[0], "end": dates[-1]}
        sample_window = {"start": selected[0]["trade_date"], "end": selected[-1]["trade_date"]}
        local = {"input_mode": "derived_state_with_daily", "daily_df_parquet": os.fspath(selected_measurement_path),
                 "derived_state_root": os.fspath(source_manifest.parent), "calendar_dates": dates,
                 "step3b_daily_df_parquet": os.fspath(sample_measurement_path),
                 "step3b_derived_state_root": os.fspath(source_manifest.parent),
                 "step3b_calendar_dates": [item["trade_date"] for item in selected],
                 "sample_window_actual": actual_window, "step3b_sample_window": sample_window,
                 "pfvv_prepared_daily_state": contract, "measurement_domain_path": os.fspath(selected_measurement_path),
                 "execution_vwap_path": os.fspath(selected_execution_path), "calendar_path": os.fspath(selected_calendar_path), **refs}
        return {"controller": name, "local_inputs": local, "daily_input_path": os.fspath(selected_measurement_path),
                "derived_state_root": os.fspath(source_manifest.parent), "measurement_domain_path": os.fspath(selected_measurement_path),
                "execution_vwap_path": os.fspath(selected_execution_path), "calendar_path": os.fspath(selected_calendar_path), **refs}
    sample_config_path = root / "controller_sample.json"
    configs = {"full": controller("full", rows), "sample": controller("sample", selected)}
    for config in configs.values():
        config["local_inputs"]["step3b_prepared_controller_config"] = os.fspath(sample_config_path)
    configs["sample"]["sample_budget"] = {"max_calendar_days": 40}
    configs["sample"]["sample_calendar_dates"] = [item["trade_date"] for item in selected]
    for name, config in configs.items():
        _write_controller(root / f"controller_{name}.json", config)
    result = {"schema_id": SCHEMA_VERSION, "prepared_path": os.fspath(root),
              "measurement_domain_path": os.fspath(measurement_path), "execution_vwap_path": os.fspath(execution_path),
              "sample_measurement_domain_path": os.fspath(sample_measurement_path), "sample_execution_vwap_path": os.fspath(sample_execution_path),
              "controllers": configs}
    _write_controller(root / "prepared_inputs_manifest.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--sample-days", type=int, default=40)
    args = parser.parse_args()
    print(json.dumps(assemble_pfvv_prepared_inputs(args.manifest, args.output_root, sample_days=args.sample_days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
