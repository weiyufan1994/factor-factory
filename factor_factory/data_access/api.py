from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .catalog import DatasetEntry, default_catalog_path, list_dataset_summaries, load_catalog


DAILY_DATASET_ID = 'clean_daily_bar'
MINUTE_DATASET_ID = 'minute_bar'
DATASET_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    'instrument': ('ts_code', 'instrument'),
    'symbol': ('ts_code', 'instrument'),
    'date': ('trade_date', 'datetime'),
    'datetime': ('trade_date', 'datetime'),
    'open': ('open', '$open'),
    'high': ('high', '$high'),
    'low': ('low', '$low'),
    'close': ('close', '$close'),
    'volume': ('vol', 'volume', '$volume'),
    'vol': ('vol', 'volume', '$volume'),
    'amount': ('amount', '$amount'),
    'return': ('pct_chg', 'ret', 'return_daily', '$ret'),
    'return_daily': ('pct_chg', 'ret', 'return_daily', '$ret'),
    'pct_chg': ('pct_chg', 'ret', '$ret'),
    'turnover': ('turnover_rate', 'turnover_rate_f', 'turnover'),
    'turnover_rate': ('turnover_rate', 'turnover_rate_f'),
    'market_cap': ('total_mv', 'circ_mv', 'market_cap'),
    'total_mv': ('total_mv', 'market_cap'),
    'circ_mv': ('circ_mv',),
    'pe': ('pe', 'pe_ttm'),
    'pb': ('pb',),
    'ps': ('ps', 'ps_ttm'),
    'time': ('trade_time', 'datetime', 'time'),
    'trade_time': ('trade_time', 'datetime'),
    'bar_time': ('bar_time', 'time'),
    'minute_index': ('minute_index',),
}


@dataclass(frozen=True)
class DatasetRequest:
    dataset_id: str
    start: str | int | None = None
    end: str | int | None = None
    symbols: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        dataset_id: str,
        start: str | int | None = None,
        end: str | int | None = None,
        symbols: Iterable[str] | None = None,
        columns: Iterable[str] | None = None,
    ) -> 'DatasetRequest':
        return cls(
            dataset_id=dataset_id,
            start=start,
            end=end,
            symbols=tuple(str(symbol).strip() for symbol in symbols or () if str(symbol).strip()),
            columns=tuple(str(column).strip() for column in columns or () if str(column).strip()),
        )


def list_datasets(catalog_path: str | Path | None = None) -> list[dict[str, Any]]:
    return list_dataset_summaries(catalog_path)


def describe_dataset(dataset_id: str, catalog_path: str | Path | None = None) -> dict[str, Any]:
    entries = load_catalog(catalog_path)
    if dataset_id not in entries:
        resolved_path = Path(catalog_path).expanduser() if catalog_path else default_catalog_path()
        available = ', '.join(sorted(entries)) or '<empty catalog>'
        raise KeyError(f'unknown dataset_id={dataset_id}; catalog_path={resolved_path}; available={available}')
    return entries[dataset_id].to_dict()


def resolve_dataset_fields(entry: DatasetEntry, required_fields: Iterable[str]) -> dict[str, Any]:
    """Resolve logical fields against a catalog entry without guessing unknown columns."""
    available = set(entry.columns)
    qlib_map = dict(entry.qlib_field_map or {})
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for raw in required_fields:
        field = str(raw).strip()
        if not field:
            continue
        candidates = [field]
        candidates.extend(DATASET_FIELD_ALIASES.get(field.lower(), ()))
        qlib_key = f'${field.lower()}'
        if qlib_key in qlib_map:
            candidates.insert(0, qlib_map[qlib_key])
        match = next((candidate for candidate in candidates if candidate in available), None)
        if match:
            resolved[field] = match
        else:
            missing.append(field)
    return {
        'dataset_id': entry.dataset_id,
        'status': 'ready' if not missing else 'missing_fields',
        'resolved_fields': resolved,
        'missing_fields': missing,
        'available_columns': sorted(available),
    }


def resolve_dataset(
    dataset_id: str,
    required_fields: Iterable[str],
    *,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    catalog_file = Path(catalog_path).expanduser() if catalog_path else default_catalog_path()
    catalog_exists = catalog_file.exists()
    entries = load_catalog(catalog_file)
    required = list(dict.fromkeys(str(x).strip() for x in required_fields if str(x).strip()))
    if dataset_id not in entries:
        return {
            'dataset_id': dataset_id,
            'status': 'missing_dataset',
            'catalog_path': str(catalog_file),
            'catalog_exists': catalog_exists,
            'available_datasets': sorted(entries),
            'missing_fields': required,
            'resolved_fields': {},
            'error': (
                f'FactorForge Data API dataset {dataset_id} is not registered in catalog {catalog_file}. '
                'Step3A must write a data requirement instead of rebuilding clean data inside factor research.'
            ),
        }
    entry = entries[dataset_id]
    resolution = resolve_dataset_fields(entry, required)
    resolution.update({
        'catalog_path': str(catalog_file),
        'catalog_exists': catalog_exists,
        'dataset': entry.to_dict(),
    })
    if resolution.get('status') == 'missing_fields':
        resolution['error'] = (
            f'FactorForge Data API dataset {dataset_id} is missing required fields '
            f'{resolution.get("missing_fields")}; catalog_path={catalog_file}.'
        )
    return resolution


def resolve_daily_dataset(
    required_fields: Iterable[str],
    *,
    dataset_id: str = DAILY_DATASET_ID,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    return resolve_dataset(dataset_id, required_fields, catalog_path=catalog_path)


def build_data_requirement(
    dataset_id: str,
    reason: str,
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    frequency: str | None = None,
    required_transform: str | None = None,
) -> dict[str, Any]:
    request = DatasetRequest.build(dataset_id, start=start, end=end, symbols=symbols, columns=columns)
    return {
        'type': 'factorforge_data_requirement',
        'contract_version': 'factorforge_data_requirement_v1',
        'dataset_id': dataset_id,
        'frequency': frequency,
        'reason': reason,
        'request': asdict(request),
        'required_transform': required_transform,
        'producer_contract': {
            'publish_to_catalog': True,
            'preferred_storage': 's3',
            'preferred_format': 'parquet',
            'consumer': 'factor_forge_ultimate',
        },
    }


def write_data_requirement(requirement: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(requirement, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def load_dataset(
    dataset_id: str,
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    catalog_path: str | Path | None = None,
) -> pd.DataFrame:
    resolved_path = Path(catalog_path).expanduser() if catalog_path else default_catalog_path()
    entries = load_catalog(resolved_path)
    if dataset_id not in entries:
        available = ', '.join(sorted(entries)) or '<empty catalog>'
        raise KeyError(f'dataset unavailable: {dataset_id}; catalog_path={resolved_path}; available={available}')
    entry = entries[dataset_id]
    request = DatasetRequest.build(dataset_id, start=start, end=end, symbols=symbols, columns=columns)
    return _load_entry(entry, request)


def _load_entry(entry: DatasetEntry, request: DatasetRequest) -> pd.DataFrame:
    if entry.format == 'parquet':
        frame = _load_parquet(entry, request)
    elif entry.format == 'csv':
        frame = _load_csv(entry, request)
    else:
        raise ValueError(f'unsupported dataset format for {entry.dataset_id}: {entry.format}')
    return _filter_frame(frame, entry, request)


def _load_parquet(entry: DatasetEntry, request: DatasetRequest) -> pd.DataFrame:
    requested_columns = _projection_columns(entry, request)
    if entry.uri.startswith('s3://'):
        try:
            return _load_s3_parquet_with_pyarrow(entry, request, requested_columns)
        except ImportError:
            local_copy = _download_s3_object_to_temp(entry.uri)
            return pd.read_parquet(local_copy, columns=requested_columns or None)
    return pd.read_parquet(_local_path(entry.uri), columns=requested_columns or None)


def _load_csv(entry: DatasetEntry, request: DatasetRequest) -> pd.DataFrame:
    requested_columns = _projection_columns(entry, request)
    if entry.uri.startswith('s3://'):
        local_copy = _download_s3_object_to_temp(entry.uri)
        return pd.read_csv(local_copy, usecols=requested_columns or None)
    return pd.read_csv(_local_path(entry.uri), usecols=requested_columns or None)


def _load_s3_parquet_with_pyarrow(
    entry: DatasetEntry,
    request: DatasetRequest,
    columns: list[str],
) -> pd.DataFrame:
    import pyarrow.dataset as ds
    import pyarrow.fs as fs

    bucket, key = _split_s3_uri(entry.uri)
    region = os.getenv('FACTORFORGE_S3_REGION') or os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION')
    if not region:
        region = fs.resolve_s3_region(bucket)
    filesystem = fs.S3FileSystem(region=region) if region else fs.S3FileSystem()
    dataset = ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning='hive')
    filters = _pyarrow_filter(entry, request)
    table = dataset.to_table(columns=columns or None, filter=filters)
    return table.to_pandas()


def _pyarrow_filter(entry: DatasetEntry, request: DatasetRequest):
    import pyarrow.dataset as ds

    expr = None
    date_col = entry.date_column
    if request.start:
        expr = ds.field(date_col) >= _normalize_scalar(request.start)
    if request.end:
        next_expr = ds.field(date_col) <= _normalize_scalar(request.end)
        expr = next_expr if expr is None else expr & next_expr
    if request.symbols:
        next_expr = ds.field(entry.symbol_column).isin(list(request.symbols))
        expr = next_expr if expr is None else expr & next_expr
    return expr


def _filter_frame(frame: pd.DataFrame, entry: DatasetEntry, request: DatasetRequest) -> pd.DataFrame:
    out = frame.copy()
    if entry.date_column in out.columns:
        out[entry.date_column] = out[entry.date_column].astype(str).str.replace('.0', '', regex=False).str.zfill(8)
        if request.start:
            out = out[out[entry.date_column] >= _normalize_scalar(request.start)]
        if request.end:
            out = out[out[entry.date_column] <= _normalize_scalar(request.end)]
    if request.symbols and entry.symbol_column in out.columns:
        out = out[out[entry.symbol_column].astype(str).isin(request.symbols)]
    if request.columns:
        missing = [column for column in request.columns if column not in out.columns]
        if missing:
            raise KeyError(f'dataset {entry.dataset_id} missing requested columns: {missing}')
        out = out[list(request.columns)]
    return out.reset_index(drop=True)


def _projection_columns(entry: DatasetEntry, request: DatasetRequest) -> list[str]:
    if not request.columns:
        return []
    helper_columns = [entry.date_column, entry.symbol_column]
    return list(dict.fromkeys([*request.columns, *helper_columns]))


def _local_path(uri: str) -> Path:
    return Path(uri.removeprefix('file://')).expanduser()


def _normalize_scalar(value: str | int | None) -> str:
    return str(value).strip() if value is not None else ''


def _split_s3_uri(uri: str) -> tuple[str, str]:
    stripped = uri.removeprefix('s3://')
    bucket, _, key = stripped.partition('/')
    if not bucket or not key:
        raise ValueError(f'invalid s3 uri: {uri}')
    return bucket, key


def _download_s3_object_to_temp(uri: str) -> Path:
    _, key = _split_s3_uri(uri)
    suffix = Path(key).suffix
    handle = tempfile.NamedTemporaryFile(prefix='factorforge_s3_', suffix=suffix, delete=False)
    target = Path(handle.name)
    handle.close()
    subprocess.run(['aws', 's3', 'cp', uri, str(target), '--only-show-errors'], check=True)
    return target
