from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd

from .query import DataQuery

DataStatus = Literal['ready', 'proxy_ready', 'blocked']
FreshnessStatus = Literal['fresh', 'stale', 'unknown']
StorageType = Literal['local', 's3']
DataFormat = Literal['csv', 'parquet']
ValidationResult = Literal['PASS', 'WARN', 'BLOCK']


@dataclass(frozen=True)
class DataSchema:
    dataset: str
    columns: list[str]
    date_column: str
    symbol_column: str
    qlib_field_map: dict[str, str]
    logical_fields: dict[str, str]
    field_aliases: dict[str, list[str]]
    schema_hash: str

    @classmethod
    def build(
        cls,
        *,
        dataset: str,
        columns: list[str],
        date_column: str,
        symbol_column: str,
        qlib_field_map: dict[str, str],
        logical_fields: dict[str, str],
        field_aliases: dict[str, list[str]],
    ) -> 'DataSchema':
        payload = {
            'dataset': dataset,
            'columns': list(columns),
            'date_column': date_column,
            'symbol_column': symbol_column,
            'qlib_field_map': dict(sorted(qlib_field_map.items())),
            'logical_fields': dict(sorted(logical_fields.items())),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
        return cls(
            dataset=dataset,
            columns=list(columns),
            date_column=date_column,
            symbol_column=symbol_column,
            qlib_field_map=dict(qlib_field_map),
            logical_fields=dict(logical_fields),
            field_aliases={key: list(value) for key, value in field_aliases.items()},
            schema_hash=digest,
        )


@dataclass(frozen=True)
class DataCoverage:
    row_count: int
    date_count: int
    ticker_count: int
    start_date_requested: str
    end_date_requested: str
    start_date_actual: str | None
    end_date_actual: str | None
    missing_fields: list[str]
    missing_dates: list[str]
    universe_requested: str | list[str]
    universe_matched_count: int | None
    duplicate_key_count: int


@dataclass(frozen=True)
class DataSourceRef:
    dataset_id: str
    uri: str
    storage: StorageType
    format: DataFormat
    backend: str
    catalog_path: str | None


@dataclass(frozen=True)
class DataFreshness:
    latest_trade_date: str | None
    source_updated_at: str | None
    freshness_status: FreshnessStatus


@dataclass(frozen=True)
class ProxyRule:
    requested: str
    resolved: str
    rationale: str = 'catalog_configured_proxy'


@dataclass
class DataApiResult:
    frame: pd.DataFrame
    query: DataQuery
    schema: DataSchema
    coverage: DataCoverage
    source: DataSourceRef
    freshness: DataFreshness
    warnings: list[str]
    status: DataStatus
    blocked_reason: str | None = None
    resolved_fields: dict[str, str] = field(default_factory=dict)
    proxy_rules: list[ProxyRule] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop('frame', None)
        return payload


@dataclass(frozen=True)
class DataValidationCheck:
    name: str
    result: ValidationResult
    message: str = ''


@dataclass(frozen=True)
class DataValidationReport:
    result: ValidationResult
    checks: list[DataValidationCheck]
