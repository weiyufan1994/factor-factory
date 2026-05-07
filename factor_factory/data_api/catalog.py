from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import DataCatalogNotFound

CATALOG_ENV = 'FACTORFORGE_DATA_CATALOG'
CATALOG_RELATIVE_PATH = Path('data/catalog/data_catalog.json')
REPO_LOCAL_CATALOG = Path('factorforge') / CATALOG_RELATIVE_PATH


@dataclass(frozen=True)
class CatalogDataset:
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
    logical_fields: dict[str, str] = field(default_factory=dict)
    proxy_fields: dict[str, dict[str, str]] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'CatalogDataset':
        if not isinstance(payload, dict):
            raise ValueError(f'catalog dataset must be object, got {type(payload).__name__}')
        dataset_id = str(payload.get('dataset_id') or '').strip()
        uri = str(payload.get('uri') or '').strip()
        fmt = str(payload.get('format') or '').strip().lower()
        if not dataset_id or not uri or not fmt:
            raise ValueError('catalog dataset requires dataset_id, uri, and format')
        storage = str(payload.get('storage') or ('s3' if uri.startswith('s3://') else 'local'))
        metadata = dict(payload.get('metadata') or {})
        proxy_fields = dict(payload.get('proxy_fields') or metadata.get('proxy_fields') or {})
        return cls(
            dataset_id=dataset_id,
            uri=uri,
            format=fmt,
            version=str(payload.get('version') or 'v1'),
            storage=storage,
            description=str(payload.get('description') or ''),
            columns=tuple(str(x).strip() for x in payload.get('columns') or () if str(x).strip()),
            partition_columns=tuple(str(x).strip() for x in payload.get('partition_columns') or () if str(x).strip()),
            date_column=str(payload.get('date_column') or 'trade_date'),
            symbol_column=str(payload.get('symbol_column') or 'ts_code'),
            qlib_field_map=dict(payload.get('qlib_field_map') or {}),
            logical_fields=dict(payload.get('logical_fields') or metadata.get('logical_fields') or {}),
            proxy_fields=proxy_fields,
            freshness=dict(payload.get('freshness') or {}),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload['columns'] = list(self.columns)
        payload['partition_columns'] = list(self.partition_columns)
        return payload


@dataclass(frozen=True)
class DataCatalog:
    path: Path
    datasets: dict[str, CatalogDataset]
    catalog_version: str = 'factorforge_data_catalog_v1'

    @classmethod
    def load(cls, path: str | Path) -> 'DataCatalog':
        catalog_path = Path(path).expanduser()
        if not catalog_path.exists():
            raise DataCatalogNotFound(f'data catalog not found: {catalog_path}')
        payload = json.loads(catalog_path.read_text(encoding='utf-8'))
        version = str(payload.get('catalog_version') or payload.get('schema_version') or 'factorforge_data_catalog_v1')
        raw = payload.get('datasets', payload)
        if isinstance(raw, list):
            entries = [CatalogDataset.from_dict(item) for item in raw]
        elif isinstance(raw, dict):
            entries = [CatalogDataset.from_dict({'dataset_id': key, **value}) for key, value in raw.items()]
        else:
            raise ValueError(f'catalog datasets must be list or object: {catalog_path}')
        return cls(path=catalog_path, datasets={entry.dataset_id: entry for entry in entries}, catalog_version=version)


def resolve_default_catalog_path() -> Path:
    explicit = os.getenv(CATALOG_ENV)
    if explicit:
        return Path(explicit).expanduser()
    factorforge_root = os.getenv('FACTORFORGE_ROOT')
    if factorforge_root:
        return Path(factorforge_root).expanduser() / CATALOG_RELATIVE_PATH
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / REPO_LOCAL_CATALOG
    if candidate.exists():
        return candidate
    raise DataCatalogNotFound(
        f'no data catalog configured; set {CATALOG_ENV} or FACTORFORGE_ROOT, '
        f'or create repo-local {REPO_LOCAL_CATALOG}'
    )
