from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CATALOG_ENV = 'FACTORFORGE_DATA_CATALOG'
DEFAULT_CATALOG_RELATIVE_PATH = Path('data/catalog/data_catalog.json')
DEFAULT_REPO_CATALOG_PATH = Path('factorforge') / DEFAULT_CATALOG_RELATIVE_PATH

CATALOG_SCHEMA_FIELDS = (
    'dataset_id',
    'uri',
    'format',
    'storage',
    'columns',
    'date_column',
    'symbol_column',
    'qlib_field_map',
    'freshness',
    'metadata',
)


@dataclass(frozen=True)
class DatasetEntry:
    dataset_id: str
    uri: str
    format: str
    version: str = 'v1'
    storage: str = 'local'
    description: str = ''
    columns: tuple[str, ...] = ()
    partition_columns: tuple[str, ...] = ()
    date_column: str = 'trade_date'
    symbol_column: str = 'ts_code'
    qlib_field_map: dict[str, str] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'DatasetEntry':
        if not isinstance(payload, dict):
            raise ValueError(f'catalog dataset entry must be an object, got {type(payload).__name__}')
        _require_non_empty(payload, 'dataset_id')
        _require_non_empty(payload, 'uri')
        _require_non_empty(payload, 'format')
        columns = _string_tuple(payload.get('columns'), 'columns')
        date_column = str(payload.get('date_column') or '').strip()
        symbol_column = str(payload.get('symbol_column') or '').strip()
        if not date_column:
            raise ValueError(f'catalog dataset {payload["dataset_id"]} must declare date_column')
        if not symbol_column:
            raise ValueError(f'catalog dataset {payload["dataset_id"]} must declare symbol_column')
        qlib_field_map = _object(payload.get('qlib_field_map', {}), 'qlib_field_map')
        freshness = _object(payload.get('freshness', {}), 'freshness')
        metadata = _object(payload.get('metadata', {}), 'metadata')
        uri = str(payload['uri'])
        return cls(
            dataset_id=str(payload['dataset_id']),
            uri=uri,
            format=str(payload.get('format') or '').lower(),
            version=str(payload.get('version') or 'v1'),
            storage=str(payload.get('storage') or _infer_storage(uri)),
            description=str(payload.get('description') or ''),
            columns=columns,
            partition_columns=tuple(payload.get('partition_columns') or ()),
            date_column=date_column,
            symbol_column=symbol_column,
            qlib_field_map=qlib_field_map,
            freshness=freshness,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload['columns'] = list(self.columns)
        payload['partition_columns'] = list(self.partition_columns)
        return payload


def _infer_storage(uri: str) -> str:
    if uri.startswith('s3://'):
        return 's3'
    return 'local'


def _require_non_empty(payload: dict[str, Any], key: str) -> None:
    if not str(payload.get(key) or '').strip():
        raise ValueError(f'catalog dataset entry missing required non-empty field: {key}')


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f'catalog field {field_name} must be a list of strings')
    out = tuple(str(item).strip() for item in value if str(item).strip())
    if len(out) != len(value):
        raise ValueError(f'catalog field {field_name} contains empty column names')
    return out


def _object(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'catalog field {field_name} must be an object')
    return dict(value)


def default_catalog_path() -> Path:
    explicit = os.getenv(DEFAULT_CATALOG_ENV)
    if explicit:
        return Path(explicit).expanduser()
    factorforge_root = os.getenv('FACTORFORGE_ROOT')
    if factorforge_root:
        return Path(factorforge_root).expanduser() / DEFAULT_CATALOG_RELATIVE_PATH
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / DEFAULT_REPO_CATALOG_PATH


def load_catalog(path: str | Path | None = None) -> dict[str, DatasetEntry]:
    catalog_path = Path(path).expanduser() if path else default_catalog_path()
    if not catalog_path.exists():
        return {}
    try:
        payload = json.loads(catalog_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'invalid FactorForge data catalog JSON at {catalog_path}: {exc}') from exc
    if not isinstance(payload, dict):
        raise ValueError(f'FactorForge data catalog must be a JSON object: {catalog_path}')
    datasets = payload.get('datasets', payload)
    if isinstance(datasets, list):
        entries = [DatasetEntry.from_dict(item) for item in datasets]
    elif isinstance(datasets, dict):
        entries = [DatasetEntry.from_dict({'dataset_id': key, **value}) for key, value in datasets.items()]
    else:
        raise ValueError(f'FactorForge data catalog datasets must be a list or object: {catalog_path}')
    return {entry.dataset_id: entry for entry in entries}


def write_catalog(entries: dict[str, DatasetEntry], path: str | Path | None = None) -> Path:
    catalog_path = Path(path).expanduser() if path else default_catalog_path()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'schema_version': 1,
        'schema_fields': list(CATALOG_SCHEMA_FIELDS),
        'datasets': [entries[key].to_dict() for key in sorted(entries)],
    }
    catalog_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return catalog_path


def upsert_dataset(entry: DatasetEntry, path: str | Path | None = None) -> Path:
    entries = load_catalog(path)
    entries[entry.dataset_id] = entry
    return write_catalog(entries, path)


def list_dataset_summaries(path: str | Path | None = None) -> list[dict[str, Any]]:
    return [
        {
            'dataset_id': entry.dataset_id,
            'version': entry.version,
            'format': entry.format,
            'storage': entry.storage,
            'uri': entry.uri,
            'columns': list(entry.columns),
            'partition_columns': list(entry.partition_columns),
            'freshness': entry.freshness,
            'description': entry.description,
        }
        for entry in load_catalog(path).values()
    ]
