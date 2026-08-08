from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from factor_factory.console.config import ConsoleConfig


CATALOG_BUCKET = "yufan-data-lake"
CATALOG_KEY = "factorforge/data/catalog/data_catalog.json"
CATALOG_RECEIPT_VERSION = "factorforge_console_active_catalog_receipt_v1"
CATALOG_MAX_AGE = timedelta(hours=24)
CATALOG_MAX_BYTES = 32 * 1024 * 1024
CACHE_TTL_SECONDS = 30.0
CACHE_MAX_ENTRIES = 16
_S3_ETAG = re.compile(r"[0-9a-fA-F]{32}(?:-[1-9][0-9]*)?")
_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple[object, ...], tuple[tuple[object, ...], bool, float]] = OrderedDict()


def catalogs_healthy(config: ConsoleConfig, *, now: datetime | None = None) -> bool:
    if now is not None:
        return _evaluate_catalogs(config, now=now)
    key = (
        tuple(str(path) for path in config.data_catalogs),
        str(config.catalog_receipt or ""),
        config.aws_readonly_role_name,
        config.auth_disabled,
    )
    fingerprint = _catalog_fingerprint(config)
    checked_at = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if (
            cached is not None
            and cached[0] == fingerprint
            and checked_at - cached[2] <= CACHE_TTL_SECONDS
        ):
            _CACHE.move_to_end(key)
            return cached[1]
        result = _evaluate_catalogs(config, now=datetime.now(timezone.utc))
        _CACHE[key] = (fingerprint, result, time.monotonic())
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
        return result


def _evaluate_catalogs(config: ConsoleConfig, *, now: datetime) -> bool:
    if not config.data_catalogs:
        return config.auth_disabled
    try:
        bounded_catalogs = all(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size <= CATALOG_MAX_BYTES
            for path in config.data_catalogs
        )
    except OSError:
        return False
    if not bounded_catalogs:
        return False
    if config.auth_disabled and config.catalog_receipt is None:
        return True
    receipt_path = config.catalog_receipt
    if receipt_path is None:
        return False
    try:
        invalid_receipt = (
            receipt_path.is_symlink()
            or not receipt_path.is_file()
            or receipt_path.stat().st_size > 1024 * 1024
        )
    except OSError:
        return False
    if invalid_receipt:
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        catalog_data = config.data_catalogs[0].read_bytes()
        catalog = json.loads(catalog_data)
        fetched_at = _timestamp(receipt.get("fetched_at_utc"))
        source_modified = _timestamp(receipt.get("source_last_modified_utc"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return False
    if not isinstance(receipt, dict) or not isinstance(catalog, dict):
        return False
    datasets = catalog.get("datasets")
    current = now
    etag = str(receipt.get("etag") or "")
    version_id = receipt.get("version_id")
    return bool(
        receipt.get("version") == CATALOG_RECEIPT_VERSION
        and receipt.get("bucket") == CATALOG_BUCKET
        and receipt.get("key") == CATALOG_KEY
        and receipt.get("role_name") == config.aws_readonly_role_name
        and receipt.get("catalog_sha256") == hashlib.sha256(catalog_data).hexdigest()
        and receipt.get("catalog_bytes") == len(catalog_data)
        and receipt.get("schema_version") == catalog.get("schema_version")
        and isinstance(datasets, list)
        and bool(datasets)
        and len(datasets) == receipt.get("dataset_count")
        and all(isinstance(item, dict) and item.get("dataset_id") for item in datasets)
        and _S3_ETAG.fullmatch(etag) is not None
        and isinstance(version_id, str)
        and fetched_at.tzinfo is not None
        and source_modified.tzinfo is not None
        and current - CATALOG_MAX_AGE <= fetched_at <= current + timedelta(minutes=5)
        and source_modified <= fetched_at + timedelta(minutes=5)
    )


def _catalog_fingerprint(config: ConsoleConfig) -> tuple[object, ...]:
    paths = (*config.data_catalogs, *((config.catalog_receipt,) if config.catalog_receipt else ()))
    values: list[object] = []
    for path in paths:
        try:
            metadata = path.lstat()
            values.append(
                (
                    str(path),
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                )
            )
        except OSError:
            values.append((str(path), "missing"))
    return tuple(values)


def require_catalogs_healthy(config: ConsoleConfig) -> None:
    if not catalogs_healthy(config):
        raise RuntimeError("BLOCK_FACTORFORGE_CONSOLE_DATA_CATALOG_UNAVAILABLE")


def catalog_admission_projection(
    config: ConsoleConfig,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a public, hash-bound statement about the active catalog transport.

    This projection deliberately does not promote catalog transport health into a
    dataset-level QA verdict. Formal dataset acceptance remains owned by Step3.
    """

    if not config.data_catalogs:
        return {
            "version": "factorforge_console_catalog_admission_v1",
            "verdict": "NOT_APPLICABLE",
            "admission_scope": "no_catalog_configured",
            "formal_dataset_qa_implied": False,
        }
    if config.catalog_receipt is None:
        require_catalogs_healthy(config)
        return {
            "version": "factorforge_console_catalog_admission_v1",
            "verdict": "NOT_APPLICABLE",
            "admission_scope": "local_or_test_catalog_snapshot",
            "formal_dataset_qa_implied": False,
        }
    if not _evaluate_catalogs(
        config,
        now=now or datetime.now(timezone.utc),
    ):
        raise RuntimeError("BLOCK_FACTORFORGE_CONSOLE_DATA_CATALOG_UNAVAILABLE")
    receipt_path = config.catalog_receipt
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    catalog_path = config.data_catalogs[0]
    return {
        "version": "factorforge_console_catalog_admission_v1",
        "verdict": "PASS",
        "admission_scope": "active_catalog_identity_freshness_and_transport",
        "formal_dataset_qa_implied": False,
        "catalog_sha256": str(receipt["catalog_sha256"]),
        "catalog_bytes": int(receipt["catalog_bytes"]),
        "catalog_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "dataset_count": int(receipt["dataset_count"]),
        "schema_version": receipt["schema_version"],
        "catalog_source": {
            "bucket": str(receipt["bucket"]),
            "key": str(receipt["key"]),
            "etag": str(receipt["etag"]),
            "version_id": str(receipt["version_id"]),
            "source_last_modified_utc": str(receipt["source_last_modified_utc"]),
            "fetched_at_utc": str(receipt["fetched_at_utc"]),
        },
        "host_catalog_filename": catalog_path.name,
    }


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("catalog receipt timestamp must include timezone")
    return parsed.astimezone(timezone.utc)
