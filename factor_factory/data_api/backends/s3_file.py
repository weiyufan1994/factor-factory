from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

from ..catalog import CatalogDataset
from ..errors import DataBackendUnavailable
from ..query import DataQuery


def load_s3_file(entry: CatalogDataset, query: DataQuery, columns: list[str]) -> pd.DataFrame:
    if entry.format == 'csv':
        local_copy = _download_s3_object_to_temp(entry.uri)
        return pd.read_csv(local_copy, usecols=columns or None)
    if entry.format != 'parquet':
        raise DataBackendUnavailable(f'unsupported s3 format for {entry.dataset_id}: {entry.format}')
    try:
        import pyarrow as pa
        import pyarrow.dataset as ds
        import pyarrow.fs as fs
    except ImportError as exc:
        raise DataBackendUnavailable('pyarrow is required for S3 parquet') from exc
    bucket, key = _split_s3_uri(entry.uri)
    region = os.getenv('FACTORFORGE_S3_REGION') or os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION')
    if not region:
        region = fs.resolve_s3_region(bucket)
    filesystem = fs.S3FileSystem(region=region) if region else fs.S3FileSystem()
    partitioning = 'hive'
    if entry.partition_columns:
        partition_schema = pa.schema([(column, pa.large_string()) for column in entry.partition_columns])
        partitioning = ds.partitioning(partition_schema, flavor='hive')
    try:
        dataset = ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning)
    except Exception:
        if not entry.partition_columns:
            raise
        partition_schema = pa.schema([(column, pa.string()) for column in entry.partition_columns])
        partitioning = ds.partitioning(partition_schema, flavor='hive')
        dataset = ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning)
    filters = _pyarrow_filter(entry, query)
    return dataset.to_table(columns=columns or None, filter=filters).to_pandas()


def _pyarrow_filter(entry: CatalogDataset, query: DataQuery):
    import pyarrow.dataset as ds

    expr = ds.field(entry.date_column) >= str(query.start_date)
    expr = expr & (ds.field(entry.date_column) <= str(query.end_date))
    if query.symbols:
        expr = expr & ds.field(entry.symbol_column).isin(list(query.symbols))
    return expr


def _split_s3_uri(uri: str) -> tuple[str, str]:
    stripped = uri.removeprefix('s3://')
    bucket, _, key = stripped.partition('/')
    if not bucket or not key:
        raise DataBackendUnavailable(f'invalid s3 uri: {uri}')
    return bucket, key


def _download_s3_object_to_temp(uri: str) -> Path:
    _, key = _split_s3_uri(uri)
    handle = tempfile.NamedTemporaryFile(prefix='factor_data_api_s3_', suffix=Path(key).suffix, delete=False)
    target = Path(handle.name)
    handle.close()
    subprocess.run(['aws', 's3', 'cp', uri, str(target), '--only-show-errors'], check=True)
    return target
