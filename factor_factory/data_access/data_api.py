from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .clean_layer import CleanDailyLayerPaths, clean_daily_layer_ready, resolve_clean_daily_layer_paths


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq

        return list(pq.read_schema(path).names)
    except Exception:
        return list(pd.read_parquet(path).head(0).columns)


def _parquet_coverage(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    summary = metadata.get("output_summary") if isinstance(metadata.get("output_summary"), dict) else {}
    if summary:
        return {
            "rows": summary.get("rows"),
            "tickers": summary.get("tickers"),
            "trade_dates": summary.get("trade_dates"),
        }
    frame = pd.read_parquet(path, columns=["ts_code", "trade_date"])
    return {
        "rows": int(len(frame)),
        "tickers": int(frame["ts_code"].nunique()) if "ts_code" in frame.columns else None,
        "trade_dates": int(frame["trade_date"].nunique()) if "trade_date" in frame.columns else None,
    }


def _clean_daily_bar_resolution(
    *,
    start: str | int | None = None,
    end: str | int | None = None,
    layer_paths: CleanDailyLayerPaths | None = None,
) -> dict[str, Any]:
    resolved = layer_paths or resolve_clean_daily_layer_paths()
    if not clean_daily_layer_ready(resolved):
        return {
            "dataset_id": "clean_daily_bar",
            "status": "blocked",
            "block_code": "CLEAN_DAILY_BAR_MISSING",
            "access_mode": "local_clean_layer",
            "request": {"start": str(start) if start is not None else None, "end": str(end) if end is not None else None},
            "artifacts": {
                "root": str(resolved.root),
                "daily_parquet": str(resolved.daily_parquet),
                "metadata_json": str(resolved.metadata_json),
            },
            "message": "Clean daily layer is missing; build or sync it before executable Step3 readiness.",
        }

    metadata = _read_json(resolved.metadata_json)
    policy = metadata.get("policy") if isinstance(metadata.get("policy"), dict) else {}
    if policy.get("drop_suspended") is True and policy.get("drop_limit_events") is True:
        policy = {
            **policy,
            "invalid_days_do_not_enter_window": policy.get("invalid_days_do_not_enter_window", True),
        }
    return {
        "dataset_id": "clean_daily_bar",
        "status": "ready",
        "access_mode": "local_clean_layer",
        "request": {"start": str(start) if start is not None else None, "end": str(end) if end is not None else None},
        "artifacts": {
            "root": str(resolved.root),
            "daily_parquet": str(resolved.daily_parquet),
            "metadata_json": str(resolved.metadata_json),
        },
        "schema": {"columns": _parquet_columns(resolved.daily_parquet)},
        "daily_filter_policy": policy,
        "coverage": _parquet_coverage(resolved.daily_parquet, metadata),
        "metadata": {
            "source_label": metadata.get("source_label"),
            "mode": metadata.get("mode"),
        },
    }


def _catalog_dataset_resolution(dataset_id: str, catalog_path: Path | None) -> dict[str, Any] | None:
    if not catalog_path or not catalog_path.exists():
        return None
    catalog = _read_json(catalog_path)
    datasets = catalog.get("datasets") if isinstance(catalog.get("datasets"), dict) else catalog
    item = datasets.get(dataset_id) if isinstance(datasets, dict) else None
    if not isinstance(item, dict):
        return None
    local_path = Path(str(item.get("local_path") or item.get("path") or "")).expanduser()
    if not local_path.exists():
        return {
            "dataset_id": dataset_id,
            "status": "blocked",
            "block_code": f"{dataset_id.upper()}_LOCAL_PATH_MISSING",
            "access_mode": "catalog",
            "catalog_path": str(catalog_path),
            "artifacts": {"path": str(local_path)},
        }
    return {
        "dataset_id": dataset_id,
        "status": "ready",
        "access_mode": "catalog",
        "catalog_path": str(catalog_path),
        "artifacts": {"path": str(local_path)},
        "schema": {"columns": item.get("columns") or []},
        "coverage": item.get("coverage") or {},
        "daily_filter_policy": item.get("daily_filter_policy"),
    }


def resolve_data_api_dataset(
    dataset_id: str,
    *,
    start: str | int | None = None,
    end: str | int | None = None,
    layer_paths: CleanDailyLayerPaths | None = None,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve a Factor Forge dataset through the auditable local Data API boundary."""
    normalized = str(dataset_id)
    if normalized == "clean_daily_bar":
        return _clean_daily_bar_resolution(start=start, end=end, layer_paths=layer_paths)

    catalog = Path(catalog_path).expanduser() if catalog_path else None
    catalog_resolution = _catalog_dataset_resolution(normalized, catalog)
    if catalog_resolution:
        return catalog_resolution

    if normalized == "clean_minute_bar":
        return {
            "dataset_id": "clean_minute_bar",
            "status": "blocked",
            "block_code": "CLEAN_MINUTE_BAR_MISSING",
            "access_mode": "catalog",
            "catalog_path": str(catalog) if catalog else None,
            "message": "No clean minute-bar catalog entry or local clean minute dataset is available.",
        }

    return {
        "dataset_id": normalized,
        "status": "blocked",
        "block_code": "DATASET_NOT_REGISTERED",
        "access_mode": "catalog",
        "catalog_path": str(catalog) if catalog else None,
    }
