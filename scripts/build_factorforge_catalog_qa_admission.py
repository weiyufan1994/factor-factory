#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.fs as fs
import pyarrow.parquet as pq


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _s3_client(region: str) -> Any:
    """Load the optional AWS client only when catalog QA actually runs."""

    try:
        boto3 = importlib.import_module("boto3")
    except ImportError as exc:
        raise SystemExit(
            "boto3 is required for catalog QA; install factor-factory with "
            "the step4 extra: python3 -m pip install -e '.[step4]'"
        ) from exc
    return boto3.client("s3", region_name=region)


def _object_identity(head: dict[str, Any]) -> dict[str, Any]:
    etag = str(head.get("ETag") or "").strip('"')
    content_length = head.get("ContentLength")
    last_modified = head.get("LastModified")
    if (
        not etag
        or type(content_length) is not int
        or content_length < 0
        or not isinstance(last_modified, datetime)
        or last_modified.tzinfo is None
    ):
        raise SystemExit("S3 object identity is incomplete")
    identity: dict[str, Any] = {
        "etag": etag,
        "content_length": content_length,
        "last_modified_utc": last_modified.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    version_id = head.get("VersionId")
    if version_id is not None:
        if not isinstance(version_id, str) or not version_id:
            raise SystemExit("S3 object version identity is invalid")
        identity["version_id"] = version_id
    return identity


def _canonical_arrow_schema_sha256(schema: pa.Schema) -> str:
    return hashlib.sha256(schema.serialize().to_pybytes()).hexdigest()


def _normalize_date(value: object, *, label: str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise SystemExit(f"{label} is not an ASCII date") from exc
    if isinstance(value, bool):
        raise SystemExit(f"{label} is not a valid date")
    text = str(value).strip()
    compact = (
        text.replace("-", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)
        else text
    )
    if re.fullmatch(r"\d{8}", compact) is None:
        raise SystemExit(f"{label} must be YYYYMMDD or YYYY-MM-DD")
    try:
        datetime.strptime(compact, "%Y%m%d")
    except ValueError as exc:
        raise SystemExit(f"{label} is not a valid calendar date") from exc
    return compact


def _iso_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _validate_schema(schema: pa.Schema, required: list[str]) -> None:
    names = schema.names
    required_columns = ["trade_date", *required]
    missing = sorted({name for name in required_columns if name not in names})
    if missing:
        raise SystemExit("missing required fields: " + ",".join(missing))
    duplicates = sorted({name for name in required_columns if names.count(name) != 1})
    if duplicates:
        raise SystemExit("required fields must be unique: " + ",".join(duplicates))

    trade_date_type = schema.field("trade_date").type
    if not (
        pa.types.is_string(trade_date_type)
        or pa.types.is_large_string(trade_date_type)
        or pa.types.is_integer(trade_date_type)
        or pa.types.is_date(trade_date_type)
        or pa.types.is_timestamp(trade_date_type)
    ):
        raise SystemExit(f"unsupported trade_date type: {trade_date_type}")
    invalid_factor_types = [
        f"{name}:{schema.field(name).type}"
        for name in required
        if not (
            pa.types.is_integer(schema.field(name).type)
            or pa.types.is_floating(schema.field(name).type)
            or pa.types.is_decimal(schema.field(name).type)
        )
    ]
    if invalid_factor_types:
        raise SystemExit(
            "required factor fields must be numeric: "
            + ",".join(invalid_factor_types)
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a hash-bound read-only catalog QA admission."
    )
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output-catalog", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--required-field", action="append", default=[])
    parser.add_argument("--required-start", required=True)
    parser.add_argument("--required-end", required=True)
    parser.add_argument("--region", default="ap-southeast-1")
    args = parser.parse_args()

    required_start = _normalize_date(args.required_start, label="required start")
    required_end = _normalize_date(args.required_end, label="required end")
    if required_start > required_end:
        raise SystemExit("required start must not be after required end")

    source = Path(args.catalog).resolve(strict=True)
    output = Path(args.output_catalog).resolve(strict=False)
    receipt_path = Path(args.receipt).resolve(strict=False)
    payload = json.loads(source.read_text(encoding="utf-8"))
    entries = payload.get("datasets")
    if not isinstance(entries, list):
        raise SystemExit("catalog datasets must be a list")
    matching_entries = [
        item
        for item in entries
        if isinstance(item, dict) and item.get("dataset_id") == args.dataset_id
    ]
    if not matching_entries:
        raise SystemExit("dataset not found")
    if len(matching_entries) != 1:
        raise SystemExit("dataset_id must identify exactly one catalog entry")
    entry = matching_entries[0]
    uri = str(entry.get("uri") or "")
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise SystemExit("dataset URI must be a single S3 parquet object")
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    client = _s3_client(args.region)
    object_identity = _object_identity(
        client.head_object(Bucket=bucket, Key=key)
    )
    filesystem = fs.S3FileSystem(
        region=args.region,
        connect_timeout=10,
        request_timeout=60,
    )
    parquet = pq.ParquetFile(f"{bucket}/{key}", filesystem=filesystem)
    required = list(dict.fromkeys(args.required_field))
    if not required:
        raise SystemExit("at least one --required-field is required")
    if "trade_date" in required:
        raise SystemExit("trade_date is not a factor field")
    schema = parquet.schema_arrow
    _validate_schema(schema, required)
    names = schema.names
    indexes = {name: names.index(name) for name in ["trade_date", *required]}
    date_min: str | None = None
    date_max: str | None = None
    trade_date_null_count = 0
    null_counts = {name: 0 for name in required}
    for row_group in range(parquet.metadata.num_row_groups):
        metadata = parquet.metadata.row_group(row_group)
        date_stats = metadata.column(indexes["trade_date"]).statistics
        if (
            date_stats is None
            or not date_stats.has_min_max
            or not date_stats.has_null_count
        ):
            raise SystemExit("trade_date statistics missing")
        row_date_min = _normalize_date(date_stats.min, label="trade_date minimum")
        row_date_max = _normalize_date(date_stats.max, label="trade_date maximum")
        if row_date_min > row_date_max:
            raise SystemExit("trade_date statistics are invalid")
        date_min = min(date_min, row_date_min) if date_min is not None else row_date_min
        date_max = max(date_max, row_date_max) if date_max is not None else row_date_max
        trade_date_null_count += int(date_stats.null_count)
        for name in required:
            stats = metadata.column(indexes[name]).statistics
            if stats is None or not stats.has_null_count:
                raise SystemExit(f"statistics missing: {name}")
            null_counts[name] += int(stats.null_count)
    if (
        date_min is None
        or date_max is None
        or date_min > required_start
        or date_max < required_end
    ):
        raise SystemExit("required date coverage is not satisfied")
    if trade_date_null_count:
        raise SystemExit("trade_date contains nulls")
    if any(null_counts.values()):
        raise SystemExit("required factor fields contain nulls")
    if (
        _object_identity(client.head_object(Bucket=bucket, Key=key))
        != object_identity
    ):
        raise SystemExit("S3 object identity changed during catalog QA")

    unsigned = {
        "contract_version": "factorforge_host_catalog_qa_attestation_v1",
        "verdict": "ACCEPT",
        "scope": "schema_date_coverage_and_required_factor_field_completeness",
        "dataset_id": args.dataset_id,
        "uri": uri,
        "object_identity": object_identity,
        "parquet_identity": {
            "row_count": parquet.metadata.num_rows,
            "row_group_count": parquet.metadata.num_row_groups,
            "schema_encoding": "arrow_ipc_schema_v1",
            "schema_sha256": _canonical_arrow_schema_sha256(schema),
            "trade_date_null_count": trade_date_null_count,
        },
        "required_window": {
            "start": _iso_date(required_start),
            "end": _iso_date(required_end),
        },
        "observed_window": {
            "start": _iso_date(date_min),
            "end": _iso_date(date_max),
        },
        "required_fields": required,
        "required_field_null_counts": null_counts,
        "executed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_catalog_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    attestation = {**unsigned, "attestation_sha256": stable_hash(unsigned)}
    updated = deepcopy(payload)
    target = next(
        item
        for item in updated["datasets"]
        if item.get("dataset_id") == args.dataset_id
    )
    metadata = target.setdefault("metadata", {})
    metadata["qa_verdict"] = "ACCEPT"
    metadata["host_qa_attestation"] = attestation
    target["freshness"] = {
        **dict(target.get("freshness") or {}),
        "rows": parquet.metadata.num_rows,
        "trade_date_min": _iso_date(date_min),
        "trade_date_max": _iso_date(date_max),
        "s3_etag": attestation["object_identity"]["etag"],
        "s3_last_modified_utc": attestation["object_identity"]["last_modified_utc"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    receipt_path.write_text(
        json.dumps(attestation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(attestation, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
