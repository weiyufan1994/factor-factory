from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


def default_catalog_path() -> Path | None:
    explicit = os.getenv("FACTORFORGE_DATA_CATALOG")
    if explicit:
        return Path(explicit).expanduser()

    root = os.getenv("FACTORFORGE_ROOT")
    if root:
        return Path(root).expanduser() / "data" / "catalog" / "data_catalog.json"

    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _as_local_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()


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


def _catalog_datasets(catalog: dict[str, Any]) -> dict[str, Any]:
    datasets = catalog.get("datasets")
    if isinstance(datasets, dict):
        return datasets
    return catalog if isinstance(catalog, dict) else {}


class DataApiClient:
    """Resolve published data products from a catalog.

    This client intentionally does not build, clean, or discover local raw data.
    Producers publish clean datasets and catalog metadata; Factor Forge consumes
    the published contract.
    """

    def __init__(self, catalog_path: str | Path | None = None):
        self.catalog_path = Path(catalog_path).expanduser() if catalog_path else default_catalog_path()

    def resolve_dataset(
        self,
        dataset_id: str,
        *,
        start: str | int | None = None,
        end: str | int | None = None,
    ) -> dict[str, Any]:
        normalized = str(dataset_id)
        request = {
            "start": str(start) if start is not None else None,
            "end": str(end) if end is not None else None,
        }

        if self.catalog_path is None:
            return {
                "dataset_id": normalized,
                "status": "catalog_missing",
                "block_code": "DATA_API_CATALOG_NOT_CONFIGURED",
                "access_mode": "catalog",
                "catalog_path": None,
                "request": request,
            }
        if not self.catalog_path.exists():
            return {
                "dataset_id": normalized,
                "status": "catalog_missing",
                "block_code": "DATA_API_CATALOG_MISSING",
                "access_mode": "catalog",
                "catalog_path": str(self.catalog_path),
                "request": request,
            }

        catalog = _read_json(self.catalog_path)
        item = _catalog_datasets(catalog).get(normalized)
        if not isinstance(item, dict):
            return {
                "dataset_id": normalized,
                "status": "catalog_missing",
                "block_code": "DATASET_NOT_REGISTERED",
                "access_mode": "catalog",
                "catalog_path": str(self.catalog_path),
                "request": request,
            }

        artifacts = item.get("artifacts") if isinstance(item.get("artifacts"), dict) else {}
        local_data = _as_local_path(
            artifacts.get("daily_parquet")
            or artifacts.get("parquet")
            or artifacts.get("path")
            or item.get("daily_parquet")
            or item.get("local_path")
            or item.get("path")
        )
        metadata_path = _as_local_path(
            artifacts.get("metadata_json")
            or artifacts.get("metadata")
            or item.get("metadata_json")
            or item.get("metadata_path")
        )

        if local_data is None or not local_data.exists():
            return {
                "dataset_id": normalized,
                "status": "blocked",
                "block_code": f"{normalized.upper()}_LOCAL_ARTIFACT_MISSING",
                "access_mode": "catalog",
                "catalog_path": str(self.catalog_path),
                "request": request,
                "source_uri": item.get("source_uri") or item.get("s3_uri"),
                "artifacts": {
                    "path": str(local_data) if local_data else None,
                    "metadata_json": str(metadata_path) if metadata_path else None,
                },
            }

        metadata = _read_json(metadata_path) if metadata_path else {}
        policy = (
            item.get("daily_filter_policy")
            or item.get("policy")
            or metadata.get("policy")
            or {}
        )
        schema_columns = item.get("schema")
        if isinstance(schema_columns, dict):
            schema_columns = schema_columns.get("columns")
        if not schema_columns:
            schema_columns = _parquet_columns(local_data)

        return {
            "dataset_id": normalized,
            "status": "ready",
            "access_mode": "catalog",
            "catalog_path": str(self.catalog_path),
            "request": request,
            "source_uri": item.get("source_uri") or item.get("s3_uri"),
            "artifacts": {
                "path": str(local_data),
                "daily_parquet": str(local_data),
                "metadata_json": str(metadata_path) if metadata_path else None,
            },
            "schema": {"columns": list(schema_columns)},
            "daily_filter_policy": policy,
            "coverage": item.get("coverage") or _parquet_coverage(local_data, metadata),
            "metadata": {
                "dataset_version": item.get("dataset_version") or item.get("version"),
                "content_hash": item.get("content_hash"),
                "catalog_hash": item.get("catalog_hash"),
                "producer": item.get("producer"),
            },
        }


def resolve_data_api_dataset(
    dataset_id: str,
    *,
    start: str | int | None = None,
    end: str | int | None = None,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    return DataApiClient(catalog_path=catalog_path).resolve_dataset(dataset_id, start=start, end=end)
