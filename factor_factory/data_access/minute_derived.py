from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


MINUTE_DERIVED_FLOW_STATE_V1 = "minute_derived_flow_state_v1"
MINUTE_DERIVED_FLOW_SCHEMA_VERSION = "minute_derived_flow_state_v1"
MINUTE_DERIVED_FLOW_PRODUCER_VERSION = "factorforge_minute_derived_flow_state_v1"
DEFAULT_MINUTE_CUTOFF_TIME = "14:50:00"
DEFAULT_RESEARCH_IN_SAMPLE_END = "2025-07-11"
DEFAULT_RESEARCH_OOS_START = "2025-07-12"

FLOW_STATE_REQUIRED_COLUMNS = [
    "ts_code",
    "trade_date",
    "cutoff_time",
    "signed_pressure_sum",
    "gross_pressure_sum",
    "pressure_sq_sum",
    "participation_concentration",
    "minute_count",
    "absolute_move_sum",
    "intraday_ret_noise",
    "morning_signed_pressure",
    "afternoon_signed_pressure",
    "tail_signed_pressure",
    "tail_concentration",
    "amount_total",
    "signed_amt_sum",
    "gross_amt",
    "amt_sq_sum",
    "abs_ret_sum",
    "ret_std",
    "source_minute_dataset_id",
    "source_data_version",
    "schema_version",
    "producer_version",
    "artifact_hash",
]


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip()
    text = text.replace("-", "").replace("/", "")
    text = re.sub(r"\s+00:00:00$", "", text)
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid trade_date: {value!r}")
    return parsed.strftime("%Y%m%d")


def normalize_date_text(value: Any) -> str:
    return normalize_trade_date(value)


def iso_date(value: Any) -> str:
    date = normalize_trade_date(value)
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}"


def yyyymmdd_range(start: Any, end: Any) -> list[str]:
    start_dt = datetime.strptime(normalize_trade_date(start), "%Y%m%d")
    end_dt = datetime.strptime(normalize_trade_date(end), "%Y%m%d")
    out: list[str] = []
    cur = start_dt
    while cur <= end_dt:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def cutoff_to_hhmmss(cutoff_time: str | int | None = None) -> int:
    raw = str(cutoff_time or DEFAULT_MINUTE_CUTOFF_TIME).strip()
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) <= 4:
        return int(digits) * 100
    return int(digits[:6])


def normalize_cutoff_time(cutoff_time: str | int | None = None) -> str:
    hhmmss = f"{cutoff_to_hhmmss(cutoff_time):06d}"
    return f"{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}"


def default_minute_derived_root() -> Path:
    explicit = os.getenv("FACTORFORGE_MINUTE_DERIVED_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    cache_root = os.getenv("FACTORFORGE_DATA_CACHE")
    if cache_root:
        return Path(cache_root).expanduser() / "minute_derived" / MINUTE_DERIVED_FLOW_STATE_V1
    worker_cache = Path("/home/ubuntu/factorforge_data_api_cache/minute_derived") / MINUTE_DERIVED_FLOW_STATE_V1
    if worker_cache.parent.exists():
        return worker_cache
    return Path.home() / ".cache" / "factorforge_data_api" / "minute_derived" / MINUTE_DERIVED_FLOW_STATE_V1


def candidate_minute_derived_roots(explicit_root: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_root:
        candidates.append(Path(explicit_root).expanduser())
    candidates.append(default_minute_derived_root())
    if os.getenv("FACTORFORGE_DATA_CACHE"):
        candidates.append(Path(os.environ["FACTORFORGE_DATA_CACHE"]).expanduser() / "minute_derived" / MINUTE_DERIVED_FLOW_STATE_V1)
    candidates.append(Path("/home/ubuntu/factorforge_data_api_cache/minute_derived") / MINUTE_DERIVED_FLOW_STATE_V1)
    candidates.append(Path.home() / ".cache" / "factorforge_data_api" / "minute_derived" / MINUTE_DERIVED_FLOW_STATE_V1)
    out: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            out.append(candidate)
            seen.add(key)
    return out


def minute_derived_partition_dir(root: str | Path, trade_date: Any) -> Path:
    return Path(root).expanduser() / f"trade_date={normalize_trade_date(trade_date)}"


def minute_derived_partition_path(root: str | Path, trade_date: Any) -> Path:
    date = normalize_trade_date(trade_date)
    return minute_derived_partition_dir(root, date) / f"{MINUTE_DERIVED_FLOW_STATE_V1}__{date}.parquet"


def minute_derived_partition_metadata_path(root: str | Path, trade_date: Any) -> Path:
    date = normalize_trade_date(trade_date)
    return minute_derived_partition_dir(root, date) / f"{MINUTE_DERIVED_FLOW_STATE_V1}__{date}.metadata.json"


def stable_frame_hash(frame: pd.DataFrame, metadata: dict[str, Any] | None = None) -> str:
    data = frame.drop(columns=["artifact_hash"], errors="ignore").sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    payload = {
        "columns": list(data.columns),
        "rows_sha256": hashlib.sha256(data.to_csv(index=False).encode("utf-8")).hexdigest(),
        "metadata": metadata or {},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _time_key(series: pd.Series) -> pd.Series:
    token = series.astype(str).str.strip().str.split().str[-1].str.replace(":", "", regex=False)
    digits = token.str.extract(r"(\d{3,6})$", expand=False).fillna("145000")
    numeric = pd.to_numeric(digits, errors="coerce")
    short = numeric.where(digits.str.len() > 4, numeric * 100)
    return short.fillna(145000).astype(int)


def derive_flow_state_for_day(
    minute_df: pd.DataFrame,
    *,
    cutoff_time: str | int | None = DEFAULT_MINUTE_CUTOFF_TIME,
    source_minute_dataset_id: str = "minute_bar",
    source_data_version: str = "unknown",
) -> pd.DataFrame:
    cutoff = cutoff_to_hhmmss(cutoff_time)
    cutoff_text = normalize_cutoff_time(cutoff_time)
    minute = minute_df.copy()
    if "trade_date" in minute.columns:
        minute["trade_date"] = minute["trade_date"].map(normalize_trade_date)
    if "trade_time" not in minute.columns and "datetime" in minute.columns:
        minute["trade_time"] = minute["datetime"]
    if "trade_time" not in minute.columns:
        minute["trade_time"] = f"{cutoff_text}"
    if "open" not in minute.columns and "close" in minute.columns:
        minute["open"] = minute["close"]
    if "amount" not in minute.columns and "vol" in minute.columns:
        minute["amount"] = minute["vol"]
    minute["hhmmss"] = _time_key(minute["trade_time"])
    minute = minute[minute["hhmmss"] <= cutoff].copy()
    for col in ["open", "close", "amount", "vol"]:
        if col in minute.columns:
            minute[col] = pd.to_numeric(minute[col], errors="coerce")
    minute = minute.dropna(subset=["ts_code", "trade_date", "open", "close", "amount"])
    minute = minute[(minute["open"] > 0) & (minute["amount"].abs() > 0)]
    if minute.empty:
        return pd.DataFrame(columns=FLOW_STATE_REQUIRED_COLUMNS)

    minute["bar_ret"] = minute["close"] / minute["open"] - 1.0
    minute["amt_abs"] = minute["amount"].abs()
    minute["signed_amt"] = np.sign(minute["bar_ret"].fillna(0.0)) * minute["amt_abs"]
    minute["amt_sq"] = minute["amt_abs"] * minute["amt_abs"]
    minute["abs_bar_ret"] = minute["bar_ret"].abs()
    minute["morning_signed"] = np.where(minute["hhmmss"] <= 113000, minute["signed_amt"], 0.0)
    minute["afternoon_signed"] = np.where(minute["hhmmss"] > 113000, minute["signed_amt"], 0.0)
    minute["tail_signed"] = np.where(minute["hhmmss"] >= 143000, minute["signed_amt"], 0.0)
    minute["tail_amt"] = np.where(minute["hhmmss"] >= 143000, minute["amt_abs"], 0.0)
    minute["tail_amt_sq"] = np.where(minute["hhmmss"] >= 143000, minute["amt_sq"], 0.0)

    grouped = minute.groupby(["ts_code", "trade_date"], sort=False).agg(
        signed_pressure_sum=("signed_amt", "sum"),
        gross_pressure_sum=("amt_abs", "sum"),
        pressure_sq_sum=("amt_sq", "sum"),
        minute_count=("bar_ret", "count"),
        absolute_move_sum=("abs_bar_ret", "sum"),
        intraday_ret_noise=("bar_ret", "std"),
        morning_signed_pressure=("morning_signed", "sum"),
        afternoon_signed_pressure=("afternoon_signed", "sum"),
        tail_signed_pressure=("tail_signed", "sum"),
        tail_gross_pressure=("tail_amt", "sum"),
        tail_pressure_sq_sum=("tail_amt_sq", "sum"),
        amount_total=("amount", "sum"),
    ).reset_index()

    gross_sq = grouped["gross_pressure_sum"] * grouped["gross_pressure_sum"]
    tail_gross_sq = grouped["tail_gross_pressure"] * grouped["tail_gross_pressure"]
    grouped["participation_concentration"] = grouped["pressure_sq_sum"] / gross_sq.replace(0, np.nan)
    grouped["tail_concentration"] = grouped["tail_pressure_sq_sum"] / tail_gross_sq.replace(0, np.nan)
    grouped["signed_amt_sum"] = grouped["signed_pressure_sum"]
    grouped["gross_amt"] = grouped["gross_pressure_sum"]
    grouped["amt_sq_sum"] = grouped["pressure_sq_sum"]
    grouped["abs_ret_sum"] = grouped["absolute_move_sum"]
    grouped["ret_std"] = grouped["intraday_ret_noise"]
    grouped["cutoff_time"] = cutoff_text
    grouped["source_minute_dataset_id"] = source_minute_dataset_id
    grouped["source_data_version"] = source_data_version
    grouped["schema_version"] = MINUTE_DERIVED_FLOW_SCHEMA_VERSION
    grouped["producer_version"] = MINUTE_DERIVED_FLOW_PRODUCER_VERSION
    grouped = grouped.drop(columns=["tail_gross_pressure", "tail_pressure_sq_sum"], errors="ignore")
    for col in FLOW_STATE_REQUIRED_COLUMNS:
        if col not in grouped.columns and col != "artifact_hash":
            grouped[col] = np.nan
    metadata = {
        "schema_version": MINUTE_DERIVED_FLOW_SCHEMA_VERSION,
        "producer_version": MINUTE_DERIVED_FLOW_PRODUCER_VERSION,
        "cutoff_time": cutoff_text,
        "source_minute_dataset_id": source_minute_dataset_id,
        "source_data_version": source_data_version,
    }
    grouped["artifact_hash"] = stable_frame_hash(grouped, metadata)
    return grouped[FLOW_STATE_REQUIRED_COLUMNS].sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def write_flow_state_partition(
    frame: pd.DataFrame,
    *,
    root: str | Path,
    trade_date: Any,
    cutoff_time: str | int | None = DEFAULT_MINUTE_CUTOFF_TIME,
    source_data_version: str = "unknown",
) -> dict[str, Any]:
    date = normalize_trade_date(trade_date)
    path = minute_derived_partition_path(root, date)
    metadata_path = minute_derived_partition_metadata_path(root, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = frame.copy()
    if "artifact_hash" not in payload.columns:
        payload["artifact_hash"] = stable_frame_hash(payload)
    payload.to_parquet(path, index=False)
    artifact_hash = stable_frame_hash(payload, {
        "schema_version": MINUTE_DERIVED_FLOW_SCHEMA_VERSION,
        "cutoff_time": normalize_cutoff_time(cutoff_time),
        "source_data_version": source_data_version,
    })
    payload["artifact_hash"] = artifact_hash
    payload.to_parquet(path, index=False)
    metadata = {
        "dataset_id": MINUTE_DERIVED_FLOW_STATE_V1,
        "trade_date": date,
        "partition_path": str(path),
        "schema_version": MINUTE_DERIVED_FLOW_SCHEMA_VERSION,
        "producer_version": MINUTE_DERIVED_FLOW_PRODUCER_VERSION,
        "cutoff_time": normalize_cutoff_time(cutoff_time),
        "source_data_version": source_data_version,
        "source_minute_dataset_id": str(payload["source_minute_dataset_id"].iloc[0]) if len(payload) and "source_minute_dataset_id" in payload.columns else "minute_bar",
        "artifact_hash": artifact_hash,
        "row_count": int(len(payload)),
        "columns": list(payload.columns),
        "written_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


@dataclass
class MinuteDerivedLoadResult:
    status: str
    frame: pd.DataFrame
    profile: dict[str, Any]


def load_flow_state_partitions(
    *,
    start_date: Any,
    end_date: Any,
    required_dates: list[str] | None = None,
    root: str | Path | None = None,
    cutoff_time: str | int | None = DEFAULT_MINUTE_CUTOFF_TIME,
    source_data_version: str | None = None,
    required_fields: list[str] | None = None,
) -> MinuteDerivedLoadResult:
    started = time.perf_counter()
    roots = candidate_minute_derived_roots(root)
    dates = [normalize_trade_date(date) for date in (required_dates or yyyymmdd_range(start_date, end_date))]
    fields = list(dict.fromkeys(required_fields or FLOW_STATE_REQUIRED_COLUMNS))
    expected_cutoff = normalize_cutoff_time(cutoff_time)
    probes: list[dict[str, Any]] = []
    for candidate_root in roots:
        missing_dates: list[str] = []
        identity_mismatches: list[dict[str, Any]] = []
        frames: list[pd.DataFrame] = []
        partition_metadata: list[dict[str, Any]] = []
        for date in dates:
            path = minute_derived_partition_path(candidate_root, date)
            meta_path = minute_derived_partition_metadata_path(candidate_root, date)
            if not path.exists() or not meta_path.exists():
                missing_dates.append(date)
                continue
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if metadata.get("schema_version") != MINUTE_DERIVED_FLOW_SCHEMA_VERSION:
                identity_mismatches.append({"trade_date": date, "field": "schema_version", "actual": metadata.get("schema_version")})
                continue
            if normalize_cutoff_time(metadata.get("cutoff_time")) != expected_cutoff:
                identity_mismatches.append({"trade_date": date, "field": "cutoff_time", "actual": metadata.get("cutoff_time"), "expected": expected_cutoff})
                continue
            if source_data_version and str(metadata.get("source_data_version")) != str(source_data_version):
                identity_mismatches.append({"trade_date": date, "field": "source_data_version", "actual": metadata.get("source_data_version"), "expected": source_data_version})
                continue
            frame = pd.read_parquet(path)
            missing_cols = sorted(set(fields) - set(frame.columns))
            if missing_cols:
                identity_mismatches.append({"trade_date": date, "field": "columns", "missing": missing_cols})
                continue
            if "artifact_hash" in frame.columns and metadata.get("artifact_hash"):
                observed_hashes = set(str(value) for value in frame["artifact_hash"].dropna().unique())
                if observed_hashes and observed_hashes != {str(metadata["artifact_hash"])}:
                    identity_mismatches.append({"trade_date": date, "field": "artifact_hash", "actual": sorted(observed_hashes)[:3], "expected": metadata.get("artifact_hash")})
                    continue
            frames.append(frame[fields])
            partition_metadata.append(metadata)
        probe = {
            "root": str(candidate_root),
            "requested_date_count": len(dates),
            "missing_date_count": len(missing_dates),
            "missing_dates_head": missing_dates[:10],
            "identity_mismatch_count": len(identity_mismatches),
            "identity_mismatches_head": identity_mismatches[:10],
            "partition_count": len(partition_metadata),
        }
        probes.append(probe)
        if missing_dates:
            continue
        if identity_mismatches:
            return MinuteDerivedLoadResult(
                status="identity_mismatch",
                frame=pd.DataFrame(columns=fields),
                profile={
                    "dataset_id": MINUTE_DERIVED_FLOW_STATE_V1,
                    "status": "identity_mismatch",
                    "blocker": "BLOCK_MINUTE_DERIVED_STATE_IDENTITY_MISMATCH",
                    "root": str(candidate_root),
                    "date_start": dates[0] if dates else None,
                    "date_end": dates[-1] if dates else None,
                    "identity_mismatches": identity_mismatches,
                    "probes": probes,
                    "load_seconds": time.perf_counter() - started,
                },
            )
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=fields)
        return MinuteDerivedLoadResult(
            status="ready",
            frame=frame,
            profile={
                "dataset_id": MINUTE_DERIVED_FLOW_STATE_V1,
                "status": "ready",
                "root": str(candidate_root),
                "date_start": dates[0] if dates else None,
                "date_end": dates[-1] if dates else None,
                "date_count": len(dates),
                "row_count": int(len(frame)),
                "partition_count": len(partition_metadata),
                "cutoff_time": expected_cutoff,
                "source_data_version": source_data_version,
                "schema_version": MINUTE_DERIVED_FLOW_SCHEMA_VERSION,
                "artifact_hashes_head": [item.get("artifact_hash") for item in partition_metadata[:5]],
                "probes": probes,
                "load_seconds": time.perf_counter() - started,
            },
        )
    return MinuteDerivedLoadResult(
        status="coverage_incomplete",
        frame=pd.DataFrame(columns=fields),
        profile={
            "dataset_id": MINUTE_DERIVED_FLOW_STATE_V1,
            "status": "coverage_incomplete",
            "blocker": "BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE",
            "date_start": dates[0] if dates else None,
            "date_end": dates[-1] if dates else None,
            "date_count": len(dates),
            "roots": [str(root) for root in roots],
            "probes": probes,
            "load_seconds": time.perf_counter() - started,
        },
    )


def minute_derived_flow_state_requirement(
    *,
    start_date: Any,
    end_date: Any,
    cutoff_time: str | int | None = DEFAULT_MINUTE_CUTOFF_TIME,
    source_data_version: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": MINUTE_DERIVED_FLOW_STATE_V1,
        "schema_version": MINUTE_DERIVED_FLOW_SCHEMA_VERSION,
        "partition_key": "trade_date",
        "partition_format": "parquet",
        "start_date": iso_date(start_date),
        "end_date": iso_date(end_date),
        "cutoff_time": normalize_cutoff_time(cutoff_time),
        "source_minute_dataset_id": "minute_bar",
        "source_data_version": source_data_version,
        "required_fields": FLOW_STATE_REQUIRED_COLUMNS,
        "required_for_full_window": True,
        "fallback_policy": "block_or_explicit_backfill",
        "local_warm_cache_root": str(Path(root).expanduser()) if root else str(default_minute_derived_root()),
        "s3_warm_cache_uri": os.getenv("FACTORFORGE_MINUTE_DERIVED_S3_URI"),
        "identity_fields": ["source_data_version", "cutoff_time", "schema_version", "artifact_hash"],
    }


def research_window_contract(sample_window: dict[str, Any] | None = None) -> dict[str, Any]:
    sample_window = sample_window or {}
    raw_start = sample_window.get("start") or "2016-01-01"
    raw_end = sample_window.get("end") or DEFAULT_RESEARCH_IN_SAMPLE_END
    start = iso_date(raw_start)
    end = iso_date(DEFAULT_RESEARCH_IN_SAMPLE_END if str(raw_end).lower() == "current" else raw_end)
    in_sample_end = min(end, DEFAULT_RESEARCH_IN_SAMPLE_END)
    return {
        "version": "factorforge_research_window_contract_v1",
        "default_in_sample_end": DEFAULT_RESEARCH_IN_SAMPLE_END,
        "in_sample": {"start": start, "end": in_sample_end},
        "oos": {
            "start": DEFAULT_RESEARCH_OOS_START,
            "policy": "holdout_only_no_revision_fitting",
        },
        "revision_fitting_policy": "Step5/Step6 may diagnose OOS but must not repeatedly fit revisions on OOS evidence.",
    }
