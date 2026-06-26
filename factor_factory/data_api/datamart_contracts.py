from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import CatalogDataset, DataCatalog


INVENTORY_SCHEMA_VERSION = 'datamart_inventory_v1'
CLOSEOUT_SCHEMA_VERSION = 'datamart_closeout_v1'
SHARD_MANIFEST_SCHEMA_VERSION = 'datamart_shard_manifest_v1'

DATA_API_BLOCK_TOKENS = (
    'BLOCK_DATA_API_SOURCE_COVERAGE_INCOMPLETE',
    'BLOCK_DATA_API_DERIVED_DATAMART_QA_FAILED',
    'BLOCK_DATA_API_DERIVED_DATAMART_DUPLICATE_KEYS',
    'BLOCK_DATA_API_LOOKAHEAD_CONTRACT_MISSING',
    'BLOCK_DATA_API_WORKER_READ_SMOKE_MISSING',
    'BLOCK_DATA_API_BACKFILL_NOT_RESUMABLE',
    'BLOCK_DATA_API_PRODUCTION_CATALOG_NOT_PUBLISHED',
    'BLOCK_DATA_API_TRUE_DOLLAR_BAR_REQUIRES_TICK_DATA',
)


@dataclass(frozen=True)
class ContractIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {'field': self.field, 'message': self.message}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'json root must be object: {source}')
    return payload


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return target


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _source_datasets(entry: CatalogDataset) -> list[str]:
    metadata = entry.metadata or {}
    candidates = (
        metadata.get('source_datasets'),
        metadata.get('source_dataset'),
        metadata.get('source'),
    )
    for candidate in candidates:
        values = _as_list(candidate)
        if values:
            return values
    return []


def _deprecation_status(entry: CatalogDataset) -> str:
    metadata = entry.metadata or {}
    if metadata.get('tombstoned') is True:
        return 'tombstoned'
    if metadata.get('deprecated') is True:
        return 'deprecated'
    return str(metadata.get('deprecation_status') or 'active')


def inventory_entry(entry: CatalogDataset) -> dict[str, Any]:
    metadata = entry.metadata or {}
    freshness = dict(entry.freshness or {})
    return {
        'dataset_id': entry.dataset_id,
        'version': entry.version,
        'schema_version': str(metadata.get('schema_version') or entry.version),
        'producer_version': str(metadata.get('producer_version') or ''),
        'uri': entry.uri,
        'storage': entry.storage,
        'format': entry.format,
        'source_datasets': _source_datasets(entry),
        'partition_columns': list(entry.partition_columns),
        'unique_key': _as_list(metadata.get('unique_key') or metadata.get('key_columns')),
        'date_column': entry.date_column,
        'symbol_column': entry.symbol_column,
        'columns_count': len(entry.columns),
        'coverage': {
            'start_date': freshness.get('trade_date_min'),
            'end_date': freshness.get('trade_date_max') or freshness.get('latest_trade_date'),
            'rows': freshness.get('rows'),
            'dates': freshness.get('trade_dates') or freshness.get('date_count') or freshness.get('partitions'),
            'tickers': freshness.get('tickers'),
        },
        'qa_path': str(metadata.get('qa_summary_path') or metadata.get('qa_path') or ''),
        'catalog_path': str(metadata.get('catalog_path') or ''),
        'lookahead_policy': metadata.get('lookahead_policy') or metadata.get('information_set_legality') or '',
        'supported_cutoff_times': _as_list(metadata.get('supported_cutoff_times')),
        'latest_reviewer_verdict': str(metadata.get('latest_reviewer_verdict') or metadata.get('verdict') or ''),
        'deprecation_status': _deprecation_status(entry),
    }


def build_datamart_inventory(catalog: DataCatalog) -> dict[str, Any]:
    entries = [inventory_entry(entry) for entry in sorted(catalog.datasets.values(), key=lambda item: item.dataset_id)]
    return {
        'schema_version': INVENTORY_SCHEMA_VERSION,
        'generated_at_utc': utc_now_iso(),
        'catalog_path': str(catalog.path),
        'catalog_version': catalog.catalog_version,
        'dataset_count': len(entries),
        'datasets': entries,
    }


def build_closeout_skeleton(
    *,
    dataset_id: str,
    source_datasets: list[str] | None = None,
    unique_key: list[str] | None = None,
    producer_version: str = '',
    schema_version: str = '',
    verdict: str = 'BLOCK',
) -> dict[str, Any]:
    return {
        'schema_version': CLOSEOUT_SCHEMA_VERSION,
        'dataset_id': dataset_id,
        'producer_version': producer_version,
        'dataset_schema_version': schema_version,
        'source_datasets': list(source_datasets or []),
        'output_identity': {
            'dataset_id': dataset_id,
            'schema_version': schema_version,
            'producer_version': producer_version,
            'parameter_hash': '',
            'immutable': True,
            'tombstone_not_delete': True,
        },
        'source_coverage': {
            'start': '',
            'end': '',
            'missing_dates': [],
        },
        'output_coverage': {
            'date_count': 0,
            'row_count': 0,
            'ticker_count': 0,
            'duplicate_key_count': 0,
            'missing_dates': [],
            'unique_key': list(unique_key or []),
        },
        'lookahead_contract': {
            'no_future_intraday_minutes': True,
            'threshold_source': '',
            'notes': '',
        },
        'performance_profile': {
            'read_seconds': 0.0,
            'compute_seconds': 0.0,
            'write_seconds': 0.0,
            'qa_seconds': 0.0,
            'warm_read_seconds_representative': 0.0,
        },
        'catalog_path': '',
        'datamart_path': '',
        'qa_path': '',
        'worker_smoke_path': '',
        'worker_read_smoke': {
            'instance_id': '',
            'command': '',
            'warm_read_seconds': 0.0,
            'verdict': 'BLOCK',
        },
        'shard_manifest_path': '',
        'verdict': verdict,
        'block_token': '',
        'notes': [],
    }


def _require_object(payload: dict[str, Any], field: str, issues: list[ContractIssue]) -> dict[str, Any] | None:
    value = payload.get(field)
    if not isinstance(value, dict):
        issues.append(ContractIssue(field, 'must be an object'))
        return None
    return value


def _require_string(payload: dict[str, Any], field: str, issues: list[ContractIssue], *, allow_empty: bool = False) -> None:
    value = payload.get(field)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        issues.append(ContractIssue(field, 'must be a non-empty string' if not allow_empty else 'must be a string'))


def _require_string_list(payload: dict[str, Any], field: str, issues: list[ContractIssue], *, allow_empty: bool = False) -> None:
    value = payload.get(field)
    if not isinstance(value, list):
        issues.append(ContractIssue(field, 'must be a list'))
        return
    if not allow_empty and not value:
        issues.append(ContractIssue(field, 'must not be empty'))
    if any(not isinstance(item, str) or not item for item in value):
        issues.append(ContractIssue(field, 'all items must be non-empty strings'))


def _number_ok(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_closeout(payload: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if payload.get('schema_version') != CLOSEOUT_SCHEMA_VERSION:
        issues.append(ContractIssue('schema_version', f'must equal {CLOSEOUT_SCHEMA_VERSION}'))
    if payload.get('verdict') not in {'ACCEPT', 'BLOCK'}:
        issues.append(ContractIssue('verdict', 'must be ACCEPT or BLOCK'))
    _require_string(payload, 'dataset_id', issues)
    _require_string(payload, 'producer_version', issues, allow_empty=payload.get('verdict') != 'ACCEPT')
    _require_string(payload, 'dataset_schema_version', issues, allow_empty=payload.get('verdict') != 'ACCEPT')
    _require_string_list(payload, 'source_datasets', issues)

    output_identity = _require_object(payload, 'output_identity', issues)
    source_coverage = _require_object(payload, 'source_coverage', issues)
    output_coverage = _require_object(payload, 'output_coverage', issues)
    lookahead = _require_object(payload, 'lookahead_contract', issues)
    performance = _require_object(payload, 'performance_profile', issues)
    worker_smoke = _require_object(payload, 'worker_read_smoke', issues)

    verdict = payload.get('verdict')
    if verdict == 'ACCEPT':
        for field in ('catalog_path', 'datamart_path', 'qa_path', 'worker_smoke_path'):
            _require_string(payload, field, issues)
        if payload.get('block_token'):
            issues.append(ContractIssue('block_token', 'must be empty for ACCEPT'))
    elif verdict == 'BLOCK':
        token = payload.get('block_token')
        if token not in DATA_API_BLOCK_TOKENS:
            issues.append(ContractIssue('block_token', f'must be one of {list(DATA_API_BLOCK_TOKENS)} for BLOCK'))

    if output_identity is not None:
        if output_identity.get('dataset_id') != payload.get('dataset_id'):
            issues.append(ContractIssue('output_identity.dataset_id', 'must match dataset_id'))
        if output_identity.get('immutable') is not True:
            issues.append(ContractIssue('output_identity.immutable', 'must be true'))
        if output_identity.get('tombstone_not_delete') is not True:
            issues.append(ContractIssue('output_identity.tombstone_not_delete', 'must be true'))
        if verdict == 'ACCEPT':
            for field in ('schema_version', 'producer_version', 'parameter_hash'):
                if not isinstance(output_identity.get(field), str) or not output_identity.get(field):
                    issues.append(ContractIssue(f'output_identity.{field}', 'must be non-empty for ACCEPT'))

    if source_coverage is not None:
        for field in ('start', 'end'):
            if verdict == 'ACCEPT' and not source_coverage.get(field):
                issues.append(ContractIssue(f'source_coverage.{field}', 'must be non-empty for ACCEPT'))
        if not isinstance(source_coverage.get('missing_dates', []), list):
            issues.append(ContractIssue('source_coverage.missing_dates', 'must be a list'))
        if verdict == 'ACCEPT' and source_coverage.get('missing_dates'):
            issues.append(ContractIssue('source_coverage.missing_dates', 'must be empty for ACCEPT'))

    if output_coverage is not None:
        if output_coverage.get('duplicate_key_count') != 0:
            issues.append(ContractIssue('output_coverage.duplicate_key_count', 'must be 0'))
        if not isinstance(output_coverage.get('missing_dates', []), list):
            issues.append(ContractIssue('output_coverage.missing_dates', 'must be a list'))
        if verdict == 'ACCEPT':
            for field in ('date_count', 'row_count'):
                if not _number_ok(output_coverage.get(field)) or output_coverage.get(field) <= 0:
                    issues.append(ContractIssue(f'output_coverage.{field}', 'must be positive for ACCEPT'))
            if output_coverage.get('missing_dates'):
                issues.append(ContractIssue('output_coverage.missing_dates', 'must be empty for ACCEPT'))
            if not output_coverage.get('unique_key'):
                issues.append(ContractIssue('output_coverage.unique_key', 'must be non-empty for ACCEPT'))

    if lookahead is not None:
        if lookahead.get('no_future_intraday_minutes') is not True:
            issues.append(ContractIssue('lookahead_contract.no_future_intraday_minutes', 'must be true'))
        if verdict == 'ACCEPT' and 'minute_bar' in set(_as_list(payload.get('source_datasets'))) and not lookahead.get('notes'):
            issues.append(ContractIssue('lookahead_contract.notes', 'must describe intraday information-set legality'))

    if performance is not None:
        for field in ('read_seconds', 'compute_seconds', 'write_seconds', 'qa_seconds', 'warm_read_seconds_representative'):
            if not _number_ok(performance.get(field)) or performance.get(field) < 0:
                issues.append(ContractIssue(f'performance_profile.{field}', 'must be non-negative number'))
        if verdict == 'ACCEPT' and performance.get('warm_read_seconds_representative', 0) <= 0:
            issues.append(ContractIssue('performance_profile.warm_read_seconds_representative', 'must be positive for ACCEPT'))

    if worker_smoke is not None:
        if verdict == 'ACCEPT' and worker_smoke.get('verdict') != 'ACCEPT':
            issues.append(ContractIssue('worker_read_smoke.verdict', 'must be ACCEPT for ACCEPT'))
        if verdict == 'ACCEPT':
            for field in ('instance_id', 'command'):
                if not isinstance(worker_smoke.get(field), str) or not worker_smoke.get(field):
                    issues.append(ContractIssue(f'worker_read_smoke.{field}', 'must be non-empty for ACCEPT'))

    return issues


def build_shard_manifest_skeleton(*, dataset_id: str, shard_id: str = '') -> dict[str, Any]:
    return {
        'schema_version': SHARD_MANIFEST_SCHEMA_VERSION,
        'dataset_id': dataset_id,
        'generated_at_utc': utc_now_iso(),
        'resumable': True,
        'shards': [
            {
                'shard_id': shard_id,
                'source_partitions': [],
                'input_row_count': 0,
                'output_row_count': 0,
                'duplicate_key_count': 0,
                'read_seconds': 0.0,
                'compute_seconds': 0.0,
                'write_seconds': 0.0,
                'status': 'PENDING',
                'retry_count': 0,
                'error_message': '',
            }
        ],
    }


def validate_shard_manifest(payload: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if payload.get('schema_version') != SHARD_MANIFEST_SCHEMA_VERSION:
        issues.append(ContractIssue('schema_version', f'must equal {SHARD_MANIFEST_SCHEMA_VERSION}'))
    _require_string(payload, 'dataset_id', issues)
    if payload.get('resumable') is not True:
        issues.append(ContractIssue('resumable', 'must be true'))
    shards = payload.get('shards')
    if not isinstance(shards, list) or not shards:
        issues.append(ContractIssue('shards', 'must be a non-empty list'))
        return issues
    for idx, shard in enumerate(shards):
        prefix = f'shards[{idx}]'
        if not isinstance(shard, dict):
            issues.append(ContractIssue(prefix, 'must be an object'))
            continue
        for field in ('shard_id', 'status'):
            if not isinstance(shard.get(field), str) or not shard.get(field):
                issues.append(ContractIssue(f'{prefix}.{field}', 'must be non-empty string'))
        if not isinstance(shard.get('source_partitions'), list):
            issues.append(ContractIssue(f'{prefix}.source_partitions', 'must be a list'))
        for field in ('input_row_count', 'output_row_count', 'duplicate_key_count', 'read_seconds', 'compute_seconds', 'write_seconds', 'retry_count'):
            if not _number_ok(shard.get(field)) or shard.get(field) < 0:
                issues.append(ContractIssue(f'{prefix}.{field}', 'must be non-negative number'))
    return issues
