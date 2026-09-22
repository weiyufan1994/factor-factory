"""Prepared input adapter for Signed-A partitioned factor computation."""
from __future__ import annotations

import hashlib
import json
import re
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from examples.mszq_signed_a_response.signed_a_v1 import compute_signed_a_scores


_DATE_RE = re.compile(r"^\d{8}$")
_MIN_DATE = "20160104"
_MAX_DATE = "20250711"

_REQUIRED_STATE_KEYS = {
    "manifest_path",
    "manifest_sha256",
    "calendar_dates",
    "day_paths",
    "day_sha256",
    "parent_daily_paths",
    "parent_daily_sha256",
}

_REQUIRED_DAY_COLUMNS = ("ts_code", "trade_date", "pf_daily")
_REQUIRED_PARENT_COLUMNS = ("ts_code", "trade_date", "PF", "VV", "factor_value")


def _sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_date(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an 8-digit YYYYMMDD string")
    text = value
    if not _DATE_RE.fullmatch(text):
        raise ValueError(f"{label} must be an 8-digit YYYYMMDD string: {value!r}")
    try:
        parsed = datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{label} contains invalid YYYYMMDD date: {value!r}") from exc
    if parsed.strftime("%Y%m%d") != text:
        raise ValueError(f"{label} must be canonical YYYYMMDD: {value!r}")
    return text


def _validate_calendar_dates(calendar_dates: Any) -> list[str]:
    if not isinstance(calendar_dates, Iterable) or isinstance(calendar_dates, (str, bytes, bytearray)):
        raise TypeError("calendar_dates must be a sequence of YYYYMMDD strings")
    dates = [_validate_date(value, label=f"calendar_dates[{idx}]") for idx, value in enumerate(calendar_dates)]
    if len(dates) == 0:
        raise ValueError("calendar_dates must be non-empty")
    if len(dates) != len(set(dates)):
        raise ValueError("calendar_dates contains duplicates")
    if any(d < _MIN_DATE or d > _MAX_DATE for d in dates):
        raise ValueError(f"calendar_dates outside allowed range [{_MIN_DATE}, {_MAX_DATE}]")
    if dates != sorted(dates):
        raise ValueError("calendar_dates must be strictly increasing")
    return dates


def _require_file(path_value: Any, *, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {path}")
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path


def _validate_required_columns(frame: pd.DataFrame, required: tuple[str, ...], *, label: str) -> None:
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}")


def _normalize_trade_dates(frame: pd.DataFrame, *, label: str) -> pd.Series:
    return pd.Series([_validate_date(v, label=f"{label} trade_date") for v in frame["trade_date"]], index=frame.index)


def _validate_numeric_column(values: pd.Series, *, label: str) -> pd.Series:
    return pd.to_numeric(values, errors="raise")


def _validate_partition_keys(frame: pd.DataFrame, *, label: str) -> None:
    if frame["ts_code"].isna().any():
        raise ValueError(f"{label} has missing ts_code")
    if (frame["ts_code"].astype(str).str.len() == 0).any():
        raise ValueError(f"{label} has empty ts_code")
    if frame.duplicated(subset=["ts_code", "trade_date"]).any():
        raise ValueError(f"{label} has duplicate (ts_code, trade_date)")


def _require_nonexistent_path(path_value: Path, *, label: str) -> None:
    if path_value.is_symlink():
        raise FileExistsError(f"{label} is a symlink: {path_value}")
    if path_value.exists():
        raise FileExistsError(f"refusing overwrite for existing path: {path_value}")


def _require_output_path(path_value: Any) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"output_path must be an absolute path: {path}")
    if path.is_symlink():
        raise ValueError(f"output_path must not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"refusing overwrite for existing path: {path}")
    return path


def _prepare_inputs(local_inputs: Mapping[str, Any]) -> tuple[dict[str, Any], list[str], dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    if "signed_a_prepared_state" not in local_inputs:
        raise ValueError("local_inputs must contain signed_a_prepared_state")
    state = local_inputs["signed_a_prepared_state"]
    if not isinstance(state, Mapping):
        raise TypeError("signed_a_prepared_state must be a mapping")

    missing_state = [key for key in _REQUIRED_STATE_KEYS if key not in state]
    if missing_state:
        raise ValueError(f"missing signed_a_prepared_state keys: {missing_state}")

    manifest_path = _require_file(state["manifest_path"], label="manifest_path")
    manifest_sha256 = str(state["manifest_sha256"])
    if _sha256_hex(manifest_path) != manifest_sha256:
        raise ValueError("manifest_path hash mismatch")

    calendar_dates = _validate_calendar_dates(state["calendar_dates"])

    day_paths = state["day_paths"]
    day_sha256 = state["day_sha256"]
    parent_daily_paths = state["parent_daily_paths"]
    parent_daily_sha256 = state["parent_daily_sha256"]
    if not isinstance(day_paths, Mapping) or not isinstance(day_sha256, Mapping):
        raise TypeError("day_paths and day_sha256 must be mappings keyed by trade_date")
    if not isinstance(parent_daily_paths, Mapping) or not isinstance(parent_daily_sha256, Mapping):
        raise TypeError("parent_daily_paths and parent_daily_sha256 must be mappings keyed by trade_date")

    if set(day_paths.keys()) != set(calendar_dates):
        raise ValueError("day_paths keys must equal calendar_dates")
    if set(parent_daily_paths.keys()) != set(calendar_dates):
        raise ValueError("parent_daily_paths keys must equal calendar_dates")
    if set(day_sha256.keys()) != set(calendar_dates):
        raise ValueError("day_sha256 keys must equal calendar_dates")
    if set(parent_daily_sha256.keys()) != set(calendar_dates):
        raise ValueError("parent_daily_sha256 keys must equal calendar_dates")

    verified_day_hashes: dict[str, str] = {}
    verified_parent_hashes: dict[str, str] = {}
    for trade_date in calendar_dates:
        day_path = _require_file(day_paths[trade_date], label=f"day_paths[{trade_date}]")
        expected_day_hash = str(day_sha256[trade_date])
        observed_day_hash = _sha256_hex(day_path)
        if expected_day_hash != observed_day_hash:
            raise ValueError(f"day_paths[{trade_date}] hash mismatch")
        verified_day_hashes[trade_date] = observed_day_hash

        parent_path = _require_file(parent_daily_paths[trade_date], label=f"parent_daily_paths[{trade_date}]")
        expected_parent_hash = str(parent_daily_sha256[trade_date])
        observed_parent_hash = _sha256_hex(parent_path)
        if expected_parent_hash != observed_parent_hash:
            raise ValueError(f"parent_daily_paths[{trade_date}] hash mismatch")
        verified_parent_hashes[trade_date] = observed_parent_hash

    return (
        {
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha256,
        },
        calendar_dates,
        {trade_date: str(day_paths[trade_date]) for trade_date in calendar_dates},
        verified_day_hashes,
        {trade_date: str(parent_daily_paths[trade_date]) for trade_date in calendar_dates},
        verified_parent_hashes,
    )


def compute_factor_partitioned(
    *,
    local_inputs: Mapping[str, Any],
    derived_state_root: Any,
    daily_input_path: Any,
    output_path: str | Path,
) -> str:
    """Compute prepared signed-A factor output from explicit partition files."""
    del derived_state_root
    del daily_input_path

    source_hashes, calendar_dates, day_paths, day_hashes, parent_daily_paths, parent_hashes = _prepare_inputs(local_inputs)
    output_path = _require_output_path(output_path)
    partial_path = output_path.with_name(output_path.name + ".partial")
    status_path = Path(f"{output_path}.date_status.json")
    sidecar_path = Path(f"{output_path}.sidecar.json")

    for path in (output_path, partial_path, status_path, sidecar_path):
        _require_nonexistent_path(path, label=f"{path}")

    date_status_rows: list[dict[str, Any]] = []
    writer: pq.ParquetWriter | None = None

    try:
        for trade_date in calendar_dates:
            day_df = pd.read_parquet(day_paths[trade_date])
            parent_df = pd.read_parquet(parent_daily_paths[trade_date])

            _validate_required_columns(day_df, _REQUIRED_DAY_COLUMNS, label=f"day_df[{trade_date}]")
            _validate_required_columns(parent_df, _REQUIRED_PARENT_COLUMNS, label=f"parent_df[{trade_date}]")

            if day_df.empty:
                raise ValueError(f"empty day partition: {trade_date}")
            day_df = day_df.copy(deep=True)
            parent_df = parent_df.copy(deep=True)

            day_df["trade_date"] = _normalize_trade_dates(day_df, label=f"day_df[{trade_date}]")
            parent_df["trade_date"] = _normalize_trade_dates(parent_df, label=f"parent_df[{trade_date}]")

            if (day_df["trade_date"] != trade_date).any():
                raise ValueError(f"day_df[{trade_date}] contains rows outside trade_date {trade_date}")

            if (parent_df["trade_date"] != trade_date).any():
                raise ValueError(f"parent_df[{trade_date}] contains rows outside trade_date {trade_date}")

            if (day_df["ts_code"].isna().any() or parent_df["ts_code"].isna().any()):
                raise ValueError(f"day_df[{trade_date}] or parent_df[{trade_date}] has missing ts_code")

            _validate_partition_keys(day_df, label=f"day_df[{trade_date}]")
            _validate_partition_keys(parent_df, label=f"parent_df[{trade_date}]")

            parent_df["PF"] = _validate_numeric_column(parent_df["PF"], label=f"parent_df[{trade_date}].PF")
            parent_df["VV"] = _validate_numeric_column(parent_df["VV"], label=f"parent_df[{trade_date}].VV")
            parent_df["factor_value"] = _validate_numeric_column(
                parent_df["factor_value"],
                label=f"parent_df[{trade_date}].factor_value",
            )

            merged = day_df.merge(
                parent_df[["ts_code", "trade_date", "PF", "VV", "factor_value"]],
                on=["ts_code", "trade_date"],
                how="left",
                validate="many_to_one",
            )
            eligibility = np.isfinite(merged["PF"].to_numpy()) & np.isfinite(merged["VV"].to_numpy()) & np.isfinite(
                merged["factor_value"].to_numpy()
            )
            merged["baseline_eligible"] = eligibility

            scores = compute_signed_a_scores(
                merged[["ts_code", "trade_date", "pf_daily", "baseline_eligible"]]
            )
            factor_df = scores.scores.rename(columns={"score": "factor_value"})[
                ["ts_code", "trade_date", "factor_value"]
            ]
            status_rows = scores.date_status.to_dict(orient="records")
            if len(status_rows) != 1:
                raise ValueError(f"missing or multiple date statuses: {trade_date}")
            date_status_rows.extend(status_rows)

            table = pa.Table.from_pandas(factor_df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(partial_path, table.schema)
            writer.write_table(table)

        if writer is None:
            raise ValueError("no data written")
        writer.close()
        os.link(partial_path, output_path)
        partial_path.unlink()
    except Exception:
        if writer is not None:
            writer.close()
        raise

    status_path.write_text(json.dumps(date_status_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    sidecar = {
        "source_hashes": {
            "manifest": source_hashes,
            "day_paths": day_paths,
            "day_sha256": day_hashes,
            "parent_daily_paths": parent_daily_paths,
            "parent_daily_sha256": parent_hashes,
        },
        "date_status_path": str(status_path),
    }
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(output_path)
