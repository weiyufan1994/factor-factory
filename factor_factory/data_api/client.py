from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .backends import load_local_file, load_s3_file
from .catalog import CatalogDataset, DataCatalog, resolve_default_catalog_path
from .contracts import DataApiResult, DataCoverage, DataFreshness, DataSourceRef, ProxyRule
from .datasets import CLEAN_DAILY_BAR, DAILY_BASIC, HELPER_FIELDS, MINUTE_BAR, SORT_KEYS, FIELD_ALIASES
from .errors import DataFieldUnavailable, DataSetNotFound
from .query import DataQuery
from .schemas import build_schema
from .validation import validate_data_api_result


class DataApiClient:
    def __init__(self, catalog: DataCatalog):
        self.catalog = catalog

    @classmethod
    def from_default_catalog(cls) -> 'DataApiClient':
        return cls.from_catalog(resolve_default_catalog_path())

    @classmethod
    def from_catalog(cls, path: str | Path) -> 'DataApiClient':
        return cls(DataCatalog.load(path))

    @classmethod
    def from_env(cls) -> 'DataApiClient':
        return cls.from_default_catalog()

    def list_datasets(self) -> list[str]:
        return sorted(self.catalog.datasets)

    def fetch(self, query: DataQuery) -> DataApiResult:
        if query.dataset not in self.catalog.datasets:
            return self._blocked_result(query, f'dataset_not_found: {query.dataset}', missing_fields=list(query.fields))
        entry = self.catalog.datasets[query.dataset]
        resolved_fields, missing_fields, proxy_rules = self._resolve_fields(entry, query.fields)
        if missing_fields:
            return self._blocked_result(query, f'missing_fields: {missing_fields}', entry=entry, missing_fields=missing_fields, resolved_fields=resolved_fields)
        projection = self._projection_columns(entry, query, resolved_fields)
        frame = self._load(entry, query, projection)
        frame = self._normalize_filter_sort(entry, query, frame, resolved_fields)
        coverage = self._coverage(entry, query, frame, missing_fields=[])
        status = 'proxy_ready' if proxy_rules else 'ready'
        result = DataApiResult(
            frame=frame,
            query=query,
            schema=build_schema(
                dataset=entry.dataset_id,
                columns=list(entry.columns),
                date_column=entry.date_column,
                symbol_column=entry.symbol_column,
                qlib_field_map=entry.qlib_field_map,
                resolved_fields=resolved_fields,
            ),
            coverage=coverage,
            source=self._source(entry),
            freshness=self._freshness(entry),
            warnings=[],
            status=status,
            resolved_fields=resolved_fields,
            proxy_rules=proxy_rules,
        )
        report = validate_data_api_result(result)
        block_checks = [check for check in report.checks if check.result == 'BLOCK']
        ignorable_duplicate_blocks = {
            'duplicate_key_count_zero',
            'duplicate_key_count_zero_or_allowed',
        }
        non_ignorable_blocks = [
            check for check in block_checks
            if not (query.allow_duplicate_keys and check.name in ignorable_duplicate_blocks)
        ]
        if non_ignorable_blocks:
            result.status = 'blocked'
            result.blocked_reason = '; '.join(check.name for check in non_ignorable_blocks)
        return result

    def get_daily_bars(self, start_date, end_date, universe='a_share_all', fields: Iterable[str] | None = None) -> DataApiResult:
        return self.fetch(DataQuery(CLEAN_DAILY_BAR, start_date, end_date, universe, list(fields or ['open', 'high', 'low', 'close', 'vol', 'amount']), 'daily'))

    def get_daily_basic(self, start_date, end_date, universe='a_share_all', fields: Iterable[str] | None = None) -> DataApiResult:
        return self.fetch(DataQuery(DAILY_BASIC, start_date, end_date, universe, list(fields or ['turnover_rate', 'pe', 'pb', 'total_mv', 'circ_mv']), 'daily'))

    def get_minute_bars(self, start_date, end_date, universe='a_share_all', fields: Iterable[str] | None = None) -> DataApiResult:
        return self.fetch(DataQuery(MINUTE_BAR, start_date, end_date, universe, list(fields or ['open', 'high', 'low', 'close', 'vol', 'amount']), '1min'))

    def _resolve_fields(self, entry: CatalogDataset, fields: list[str]) -> tuple[dict[str, str], list[str], list[ProxyRule]]:
        available = set(entry.columns)
        resolved: dict[str, str] = {}
        missing: list[str] = []
        proxy_rules: list[ProxyRule] = []
        for field in fields:
            proxy = entry.proxy_fields.get(field)
            if proxy:
                target = str(proxy.get('field') or proxy.get('resolved') or '').strip()
                if target in available:
                    resolved[field] = target
                    proxy_rules.append(ProxyRule(requested=field, resolved=target, rationale=str(proxy.get('rationale') or 'catalog_configured_proxy')))
                    continue
            candidates = [field]
            if field in entry.logical_fields:
                candidates.insert(0, entry.logical_fields[field])
            qlib_key = f'${field.lower()}'
            if qlib_key in entry.qlib_field_map:
                candidates.insert(0, entry.qlib_field_map[qlib_key])
            candidates.extend(FIELD_ALIASES.get(field.lower(), ()))
            match = next((candidate for candidate in candidates if candidate in available), None)
            if match and field == 'market_cap' and match in {'total_mv', 'circ_mv'} and not proxy:
                missing.append(field)
            elif match:
                resolved[field] = match
            else:
                missing.append(field)
        return resolved, missing, proxy_rules

    def _projection_columns(self, entry: CatalogDataset, query: DataQuery, resolved_fields: dict[str, str]) -> list[str]:
        helpers = [entry.symbol_column, entry.date_column]
        if query.dataset == MINUTE_BAR and 'trade_time' in entry.columns:
            helpers.append('trade_time')
        return list(dict.fromkeys([*helpers, *resolved_fields.values()]))

    def _load(self, entry: CatalogDataset, query: DataQuery, columns: list[str]) -> pd.DataFrame:
        if entry.storage == 's3' or entry.uri.startswith('s3://'):
            return load_s3_file(entry, query, columns)
        return load_local_file(entry, query, columns)

    def _normalize_filter_sort(self, entry: CatalogDataset, query: DataQuery, frame: pd.DataFrame, resolved_fields: dict[str, str]) -> pd.DataFrame:
        out = frame.copy()
        if entry.date_column in out.columns:
            out[entry.date_column] = out[entry.date_column].map(lambda x: pd.to_datetime(str(x)).strftime('%Y%m%d') if '-' in str(x) else str(x).replace('.0', '').zfill(8))
            out = out[(out[entry.date_column] >= query.start_date) & (out[entry.date_column] <= query.end_date)]
        if query.symbols and entry.symbol_column in out.columns:
            out = out[out[entry.symbol_column].astype(str).isin(query.symbols)]
        wanted = self._projection_columns(entry, query, resolved_fields)
        existing = [column for column in wanted if column in out.columns]
        out = out[existing]
        sort_keys = [key for key in SORT_KEYS.get(query.dataset, (entry.symbol_column, entry.date_column)) if key in out.columns]
        if sort_keys:
            out = out.sort_values(sort_keys)
        return out.reset_index(drop=True)

    def _coverage(self, entry: CatalogDataset, query: DataQuery, frame: pd.DataFrame, missing_fields: list[str]) -> DataCoverage:
        dates = frame[entry.date_column].astype(str) if entry.date_column in frame.columns and not frame.empty else pd.Series(dtype=str)
        tickers = frame[entry.symbol_column].astype(str) if entry.symbol_column in frame.columns and not frame.empty else pd.Series(dtype=str)
        key_cols = [entry.symbol_column, entry.date_column]
        if query.dataset == MINUTE_BAR and 'trade_time' in frame.columns:
            key_cols.append('trade_time')
        duplicate_count = int(frame.duplicated(key_cols).sum()) if all(column in frame.columns for column in key_cols) else 0
        return DataCoverage(
            row_count=int(len(frame)),
            date_count=int(dates.nunique()) if not dates.empty else 0,
            ticker_count=int(tickers.nunique()) if not tickers.empty else 0,
            start_date_requested=query.start_date,
            end_date_requested=query.end_date,
            start_date_actual=str(dates.min()) if not dates.empty else None,
            end_date_actual=str(dates.max()) if not dates.empty else None,
            missing_fields=list(missing_fields),
            missing_dates=[],
            universe_requested='a_share_all' if query.universe == 'a_share_all' else list(query.symbols),
            universe_matched_count=None if query.universe == 'a_share_all' else int(tickers.nunique()),
            duplicate_key_count=duplicate_count,
        )

    def _source(self, entry: CatalogDataset) -> DataSourceRef:
        backend = 's3_file' if entry.storage == 's3' or entry.uri.startswith('s3://') else 'local_file'
        return DataSourceRef(entry.dataset_id, entry.uri, 's3' if backend == 's3_file' else 'local', entry.format, backend, str(self.catalog.path))

    def _freshness(self, entry: CatalogDataset) -> DataFreshness:
        latest = entry.freshness.get('latest_trade_date') or entry.freshness.get('trade_date_max')
        updated = entry.freshness.get('source_updated_at') or entry.metadata.get('source_updated_at')
        status = 'unknown'
        if latest:
            status = 'fresh'
        return DataFreshness(latest_trade_date=str(latest) if latest else None, source_updated_at=str(updated) if updated else None, freshness_status=status)

    def _blocked_result(
        self,
        query: DataQuery,
        reason: str,
        *,
        entry: CatalogDataset | None = None,
        missing_fields: list[str] | None = None,
        resolved_fields: dict[str, str] | None = None,
    ) -> DataApiResult:
        resolved = resolved_fields or {}
        columns = list(entry.columns) if entry else []
        date_column = entry.date_column if entry else 'trade_date'
        symbol_column = entry.symbol_column if entry else 'ts_code'
        schema = build_schema(
            dataset=entry.dataset_id if entry else query.dataset,
            columns=columns or [symbol_column, date_column],
            date_column=date_column,
            symbol_column=symbol_column,
            qlib_field_map=entry.qlib_field_map if entry else {},
            resolved_fields=resolved,
        )
        coverage = DataCoverage(
            row_count=0,
            date_count=0,
            ticker_count=0,
            start_date_requested=query.start_date,
            end_date_requested=query.end_date,
            start_date_actual=None,
            end_date_actual=None,
            missing_fields=list(missing_fields or query.fields),
            missing_dates=[],
            universe_requested='a_share_all' if query.universe == 'a_share_all' else list(query.symbols),
            universe_matched_count=0 if query.universe != 'a_share_all' else None,
            duplicate_key_count=0,
        )
        source = self._source(entry) if entry else DataSourceRef(query.dataset, '', 'local', 'parquet', 'none', str(self.catalog.path))
        return DataApiResult(
            frame=pd.DataFrame(),
            query=query,
            schema=schema,
            coverage=coverage,
            source=source,
            freshness=self._freshness(entry) if entry else DataFreshness(None, None, 'unknown'),
            warnings=[],
            status='blocked',
            blocked_reason=reason,
            resolved_fields=resolved,
            proxy_rules=[],
        )
