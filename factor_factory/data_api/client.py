from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
import json
import os

import pandas as pd


def _first_accessible_existing_path(candidates: list[str | Path | None]) -> Path | None:
    for raw_path in candidates:
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def _ensure_independent_data_api() -> None:
    try:
        import factorforge_data_api  # noqa: F401

        return
    except ModuleNotFoundError:
        here = Path(__file__).resolve()
        candidates = [
            here.parents[3] / "factorforge-data-api",
            here.parents[2] / "factorforge-data-api",
            Path("/home/ubuntu/.openclaw/workspace/factorforge-data-api"),
            Path("/Users/humphrey/projects/factorforge-data-api"),
        ]
        for sibling in candidates:
            if _first_accessible_existing_path([sibling]) and str(sibling) not in sys.path:
                sys.path.insert(0, str(sibling))
                break


_ensure_independent_data_api()

from factorforge_data_api import DataApiClient as IndependentDataApiClient  # noqa: E402
from factorforge_data_api import DataCatalogNotFound, DataQuery, DataQueryInvalid  # noqa: E402


DataApiClient = IndependentDataApiClient


class LocalDataApiResult:
    def __init__(
        self,
        dataset_id: str,
        frame: Any,
        query: dict[str, Any],
        metadata: dict[str, Any],
        *,
        status: str = "ready",
        blocked_reason: str | None = None,
    ) -> None:
        self.dataset_id = dataset_id
        self.frame = frame
        self.query = query
        self.metadata = metadata
        self.status = status
        self.blocked_reason = blocked_reason

    def to_metadata(self) -> dict[str, Any]:
        frame = self.frame
        raw_columns = getattr(frame, "columns", [])
        columns = list(raw_columns) if raw_columns is not None else []
        row_count = int(len(frame)) if hasattr(frame, "__len__") else 0
        date_count = int(frame["trade_date"].nunique()) if row_count and "trade_date" in columns else 0
        ticker_count = int(frame["ts_code"].nunique()) if row_count and "ts_code" in columns else 0
        return {
            "dataset_id": self.dataset_id,
            "status": self.status,
            "blocked_reason": self.blocked_reason,
            "query": self.query,
            "source": self.metadata.get("source") or {},
            "schema": {
                "columns": columns,
                "date_column": "trade_date" if "trade_date" in columns else None,
                "symbol_column": "ts_code" if "ts_code" in columns else None,
                "schema_hash": self.metadata.get("schema_hash"),
            },
            "coverage": {
                "row_count": row_count,
                "date_count": date_count,
                "ticker_count": ticker_count,
            },
            "freshness": self.metadata.get("freshness") or {},
            "resolved_fields": self.metadata.get("resolved_fields") or {},
            "proxy_rules": self.metadata.get("proxy_rules") or [],
            "performance_profile": self.metadata.get("performance_profile") or {},
            "metadata": self.metadata,
        }


def default_catalog_path() -> Path | None:
    try:
        from factorforge_data_api.catalog import resolve_default_catalog_path

        return resolve_default_catalog_path()
    except DataCatalogNotFound:
        return None


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or _first_accessible_existing_path([path]) is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog_item(catalog_path: Path | None, dataset_id: str) -> dict[str, Any]:
    catalog = _read_json(catalog_path)
    raw = catalog.get("datasets", catalog)
    if isinstance(raw, dict):
        item = raw.get(dataset_id)
        return item if isinstance(item, dict) else {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("dataset_id") == dataset_id:
                return item
    return {}


def _default_fields(dataset_id: str) -> list[str]:
    if dataset_id == "clean_daily_bar":
        return ["open", "high", "low", "close", "vol", "amount", "pct_chg"]
    if dataset_id == "daily_basic":
        return ["turnover_rate", "pe", "pb", "total_mv", "circ_mv"]
    if dataset_id == "minute_bar":
        return ["open", "high", "low", "close", "vol", "amount"]
    if dataset_id == "moneyflow":
        return [
            "buy_sm_amount",
            "sell_sm_amount",
            "buy_md_amount",
            "sell_md_amount",
            "buy_lg_amount",
            "sell_lg_amount",
            "buy_elg_amount",
            "sell_elg_amount",
            "net_mf_amount",
        ]
    return ["close"]


def _default_frequency(dataset_id: str) -> str:
    return "1min" if dataset_id == "minute_bar" else "daily"


def _normalize_result_metadata(result: Any, catalog_path: Path | None, dataset_id: str) -> dict[str, Any]:
    payload = result.to_metadata()
    catalog_item = _catalog_item(catalog_path, dataset_id)
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    schema = payload.get("schema") if isinstance(payload.get("schema"), dict) else {}
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    freshness = payload.get("freshness") if isinstance(payload.get("freshness"), dict) else {}
    policy = (
        catalog_item.get("daily_filter_policy")
        or catalog_item.get("policy")
        or (catalog_item.get("metadata") or {}).get("daily_filter_policy")
        or (catalog_item.get("metadata") or {}).get("policy")
        or {}
    )
    return {
        "dataset_id": dataset_id,
        "status": payload.get("status"),
        "blocked_reason": payload.get("blocked_reason"),
        "access_mode": "catalog",
        "catalog_path": str(catalog_path) if catalog_path else source.get("catalog_path"),
        "request": payload.get("query"),
        "source_uri": source.get("uri"),
        "source": source,
        "freshness": freshness,
        "schema": {
            "columns": schema.get("columns") or [],
            "date_column": schema.get("date_column"),
            "symbol_column": schema.get("symbol_column"),
            "qlib_field_map": schema.get("qlib_field_map") or {},
            "logical_fields": schema.get("logical_fields") or {},
            "schema_hash": schema.get("schema_hash"),
        },
        "coverage": coverage,
        "daily_filter_policy": policy,
        "resolved_fields": payload.get("resolved_fields") or {},
        "proxy_rules": payload.get("proxy_rules") or [],
        "metadata": {
            "dataset_version": catalog_item.get("version") or catalog_item.get("dataset_version"),
            "producer": catalog_item.get("producer") or (catalog_item.get("metadata") or {}).get("producer"),
            "independent_package": "factorforge_data_api",
        },
    }


def _blocked_metadata(
    dataset_id: str,
    *,
    status: str,
    block_code: str,
    reason: str,
    catalog_path: Path | None,
    start: str | int | None,
    end: str | int | None,
    fields: list[str],
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "status": status,
        "block_code": block_code,
        "blocked_reason": reason,
        "access_mode": "catalog",
        "catalog_path": str(catalog_path) if catalog_path else None,
        "request": {
            "dataset": dataset_id,
            "start_date": str(start) if start is not None else None,
            "end_date": str(end) if end is not None else None,
            "universe": "a_share_all",
            "fields": list(fields),
        },
        "schema": {"columns": []},
        "coverage": {"row_count": 0, "date_count": 0, "ticker_count": 0, "missing_fields": list(fields)},
        "daily_filter_policy": {},
        "resolved_fields": {},
        "proxy_rules": [],
        "metadata": {"independent_package": "factorforge_data_api"},
    }


def fetch_data_api_dataset(
    dataset_id: str,
    *,
    start: str | int,
    end: str | int,
    fields: list[str] | None = None,
    universe: str | list[str] = "a_share_all",
    frequency: str | None = None,
    catalog_path: str | Path | None = None,
):
    if (
        dataset_id == "daily_basic"
        and os.getenv("FACTORFORGE_DISABLE_CLEAN_DAILY_LOCAL_PARQUET", "").strip().lower()
        not in {"1", "true", "yes", "on"}
    ):
        requested_fields = fields or _default_fields(dataset_id)
        candidates = [
            os.getenv("FACTORFORGE_CLEAN_DAILY_PARQUET"),
            "/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet",
            "/Users/humphrey/projects/factor-factory/data/clean/daily_clean.parquet",
            "/home/ubuntu/projects/factor-factory-data-api/data/clean/daily_clean.parquet",
        ]
        local_path = _first_accessible_existing_path(candidates)
        if local_path is not None:
            read_columns = list(dict.fromkeys(["ts_code", "trade_date", *requested_fields]))
            try:
                frame = pd.read_parquet(local_path, columns=read_columns)
            except Exception:
                frame = None
            if frame is not None:
                start_s = str(start).replace("-", "")
                end_s = str(end).replace("-", "")
                frame = frame[
                    (frame["trade_date"].astype(str) >= start_s)
                    & (frame["trade_date"].astype(str) <= end_s)
                ]
                if isinstance(universe, list):
                    symbols = {str(symbol).strip() for symbol in universe if str(symbol).strip()}
                    frame = frame[frame["ts_code"].astype(str).isin(symbols)]
                frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
                query = {
                    "dataset": dataset_id,
                    "start_date": start_s,
                    "end_date": end_s,
                    "universe": universe,
                    "fields": list(requested_fields),
                    "frequency": frequency or _default_frequency(dataset_id),
                }
                meta_path = local_path.with_suffix(".meta.json")
                local_meta = _read_json(meta_path)
                return LocalDataApiResult(
                    dataset_id,
                    frame,
                    query,
                    {
                        "source": {
                            "access_mode": "local_clean_daily_parquet_warm_cache",
                            "uri": str(local_path),
                            "meta_uri": (
                                str(meta_path)
                                if _first_accessible_existing_path([meta_path]) is not None
                                else None
                            ),
                        },
                        "freshness": local_meta.get("freshness") or {
                            "latest_trade_date": str(frame["trade_date"].max()) if not frame.empty else None,
                            "trade_date_min": str(frame["trade_date"].min()) if not frame.empty else None,
                            "trade_date_max": str(frame["trade_date"].max()) if not frame.empty else None,
                        },
                        "performance_profile": {
                            "version": "factorforge_daily_basic_from_clean_daily_local_parquet_profile_v1",
                            "clean_daily_selected_format": "parquet",
                            "clean_daily_cache_path": str(local_path),
                            "daily_basic_rows": int(len(frame)),
                            "daily_basic_dates": int(frame["trade_date"].nunique()) if not frame.empty else 0,
                            "daily_basic_tickers": int(frame["ts_code"].nunique()) if not frame.empty else 0,
                        },
                        "resolved_fields": {field: field for field in requested_fields},
                        "independent_package": "factorforge_data_api",
                        "local_proxy": "factor_factory.data_api.clean_daily_local_parquet.daily_basic_fields",
                    },
                )

    if (
        dataset_id == "clean_daily_bar"
        and os.getenv("FACTORFORGE_DISABLE_CLEAN_DAILY_LOCAL_PARQUET", "").strip().lower()
        not in {"1", "true", "yes", "on"}
    ):
        candidates = [
            os.getenv("FACTORFORGE_CLEAN_DAILY_PARQUET"),
            "/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet",
            "/home/ubuntu/projects/factor-factory-data-api/data/clean/daily_clean.parquet",
        ]
        local_path = _first_accessible_existing_path(candidates)
        if local_path is not None:
            requested_fields = fields or _default_fields(dataset_id)
            read_columns = list(dict.fromkeys(["ts_code", "trade_date", *requested_fields]))
            frame = pd.read_parquet(local_path, columns=read_columns)
            start_s = str(start).replace("-", "")
            end_s = str(end).replace("-", "")
            frame = frame[
                (frame["trade_date"].astype(str) >= start_s)
                & (frame["trade_date"].astype(str) <= end_s)
            ]
            if isinstance(universe, list):
                symbols = {str(symbol).strip() for symbol in universe if str(symbol).strip()}
                frame = frame[frame["ts_code"].astype(str).isin(symbols)]
            frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
            query = {
                "dataset": dataset_id,
                "start_date": start_s,
                "end_date": end_s,
                "universe": universe,
                "fields": list(requested_fields),
                "frequency": frequency or _default_frequency(dataset_id),
            }
            meta_path = local_path.with_suffix(".meta.json")
            local_meta = _read_json(meta_path)
            return LocalDataApiResult(
                dataset_id,
                frame,
                query,
                {
                    "source": {
                        "access_mode": "local_parquet_warm_cache",
                        "uri": str(local_path),
                        "meta_uri": (
                            str(meta_path)
                            if _first_accessible_existing_path([meta_path]) is not None
                            else None
                        ),
                    },
                    "freshness": local_meta.get("freshness") or {
                        "latest_trade_date": str(frame["trade_date"].max()) if not frame.empty else None,
                        "trade_date_min": str(frame["trade_date"].min()) if not frame.empty else None,
                        "trade_date_max": str(frame["trade_date"].max()) if not frame.empty else None,
                    },
                    "performance_profile": {
                        "version": "factorforge_clean_daily_local_parquet_profile_v1",
                        "clean_daily_selected_format": "parquet",
                        "clean_daily_cache_path": str(local_path),
                        "clean_daily_rows": int(len(frame)),
                        "clean_daily_dates": int(frame["trade_date"].nunique()) if not frame.empty else 0,
                        "clean_daily_tickers": int(frame["ts_code"].nunique()) if not frame.empty else 0,
                    },
                    "resolved_fields": {field: field for field in requested_fields},
                    "independent_package": "factorforge_data_api",
                    "local_proxy": "factor_factory.data_api.clean_daily_local_parquet",
                },
            )

    if (
        dataset_id == "daily_basic"
        and os.getenv("FACTORFORGE_DISABLE_DAILY_BASIC_PARQUET_CACHE", "").strip().lower()
        not in {"1", "true", "yes", "on"}
    ):
        try:
            from factor_factory.data_access.daily_basic import get_daily_basic_with_profile

            requested_fields = fields or _default_fields(dataset_id)
            frame, profile = get_daily_basic_with_profile(
                start=start,
                end=end,
                symbols=universe if isinstance(universe, list) else None,
                columns=list(dict.fromkeys(["ts_code", "trade_date", *requested_fields])),
                source_data_version="daily_basic_incremental_csv",
            )
            if not frame.empty:
                query = {
                    "dataset": dataset_id,
                    "start_date": str(start) if start is not None else None,
                    "end_date": str(end) if end is not None else None,
                    "universe": universe,
                    "fields": list(requested_fields),
                    "frequency": frequency or _default_frequency(dataset_id),
                }
                return LocalDataApiResult(
                    dataset_id,
                    frame,
                    query,
                    {
                        "source": {
                            "access_mode": "local_parquet_warm_cache",
                            "uri": profile.get("cache_root"),
                        },
                        "performance_profile": {
                            "version": "factorforge_daily_basic_data_api_profile_v1",
                            "daily_basic_selected_format": profile.get("selected_format"),
                            "daily_basic_cache_hit": bool(profile.get("cache_hit")),
                            "daily_basic_cache_status": profile.get("cache_status"),
                            "daily_basic_cache_path": profile.get("cache_root"),
                            "daily_basic_rows": profile.get("row_count"),
                            "daily_basic_dates": profile.get("date_count"),
                            "daily_basic_tickers": profile.get("ticker_count"),
                            "daily_basic_load_seconds": profile.get("load_seconds") or profile.get("csv_load_seconds"),
                            "raw_cache_profile": profile,
                        },
                        "resolved_fields": {field: field for field in requested_fields},
                        "independent_package": "factorforge_data_api",
                        "local_proxy": "factor_factory.data_access.daily_basic",
                    },
                )
        except Exception:
            # Fall through to the independent catalog path. The caller will still
            # receive the catalog error if neither path can serve the data.
            pass

    catalog = Path(catalog_path).expanduser() if catalog_path else default_catalog_path()
    if catalog is None:
        raise DataCatalogNotFound("no Data API catalog configured")
    query = DataQuery(
        dataset_id,
        start,
        end,
        universe,
        fields or _default_fields(dataset_id),
        frequency or _default_frequency(dataset_id),
    )
    return IndependentDataApiClient.from_catalog(catalog).fetch(query)


def resolve_data_api_dataset(
    dataset_id: str,
    *,
    start: str | int | None = None,
    end: str | int | None = None,
    fields: list[str] | None = None,
    universe: str | list[str] = "a_share_all",
    frequency: str | None = None,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    requested_fields = fields or _default_fields(dataset_id)
    catalog = Path(catalog_path).expanduser() if catalog_path else default_catalog_path()
    if catalog is None:
        return _blocked_metadata(
            dataset_id,
            status="catalog_missing",
            block_code="DATA_API_CATALOG_NOT_CONFIGURED",
            reason="no Data API catalog configured",
            catalog_path=None,
            start=start,
            end=end,
            fields=requested_fields,
        )
    if not catalog.exists():
        return _blocked_metadata(
            dataset_id,
            status="catalog_missing",
            block_code="DATA_API_CATALOG_MISSING",
            reason=f"data catalog not found: {catalog}",
            catalog_path=catalog,
            start=start,
            end=end,
            fields=requested_fields,
        )
    catalog_item = _catalog_item(catalog, dataset_id)
    if not catalog_item:
        return _blocked_metadata(
            dataset_id,
            status="dataset_missing",
            block_code="DATA_API_DATASET_MISSING",
            reason=f"dataset not registered in catalog: {dataset_id}",
            catalog_path=catalog,
            start=start,
            end=end,
            fields=requested_fields,
        )
    source = catalog_item.get("source") if isinstance(catalog_item.get("source"), dict) else {}
    metadata = catalog_item.get("metadata") if isinstance(catalog_item.get("metadata"), dict) else {}
    schema = catalog_item.get("schema") if isinstance(catalog_item.get("schema"), dict) else {}
    freshness = catalog_item.get("freshness") if isinstance(catalog_item.get("freshness"), dict) else {}
    policy = (
        catalog_item.get("daily_filter_policy")
        or catalog_item.get("policy")
        or metadata.get("daily_filter_policy")
        or metadata.get("policy")
        or {}
    )
    uri = (
        catalog_item.get("uri")
        or catalog_item.get("path")
        or source.get("uri")
        or source.get("path")
    )
    return {
        "dataset_id": dataset_id,
        "status": catalog_item.get("status") or "ready",
        "blocked_reason": catalog_item.get("blocked_reason"),
        "access_mode": "catalog",
        "catalog_path": str(catalog),
        "request": {
            "dataset": dataset_id,
            "start_date": str(start) if start is not None else None,
            "end_date": str(end) if end is not None else None,
            "universe": universe,
            "fields": list(requested_fields),
            "frequency": frequency or _default_frequency(dataset_id),
        },
        "source_uri": uri,
        "source": {"uri": uri, **source} if uri else source,
        "freshness": freshness,
        "schema": {
            "columns": schema.get("columns") or [],
            "date_column": schema.get("date_column"),
            "symbol_column": schema.get("symbol_column"),
            "qlib_field_map": schema.get("qlib_field_map") or {},
            "logical_fields": schema.get("logical_fields") or {},
            "schema_hash": schema.get("schema_hash"),
        },
        "coverage": catalog_item.get("coverage") or {},
        "daily_filter_policy": policy,
        "resolved_fields": {field: field for field in requested_fields},
        "proxy_rules": catalog_item.get("proxy_rules") or [],
        "metadata": {
            "dataset_version": catalog_item.get("version") or catalog_item.get("dataset_version"),
            "producer": catalog_item.get("producer") or metadata.get("producer"),
            "independent_package": "factorforge_data_api",
            "resolve_mode": "catalog_only",
        },
    }
