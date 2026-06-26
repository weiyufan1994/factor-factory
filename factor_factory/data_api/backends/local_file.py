from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..catalog import CatalogDataset
from ..errors import DataBackendUnavailable
from ..query import DataQuery


def load_local_file(entry: CatalogDataset, query: DataQuery, columns: list[str]) -> pd.DataFrame:
    path = Path(entry.uri.removeprefix('file://')).expanduser()
    if entry.format == 'csv':
        return pd.read_csv(path, usecols=columns or None)
    if entry.format != 'parquet':
        raise DataBackendUnavailable(f'unsupported local format for {entry.dataset_id}: {entry.format}')
    if entry.partition_columns or path.is_dir():
        try:
            import pyarrow as pa
            import pyarrow.dataset as ds
        except ImportError as exc:
            raise DataBackendUnavailable('pyarrow is required for partitioned local parquet') from exc
        partitioning = 'hive'
        if entry.partition_columns:
            partitioning = ds.partitioning(pa.schema([(column, pa.large_string()) for column in entry.partition_columns]), flavor='hive')
        try:
            dataset = ds.dataset(str(path), format='parquet', partitioning=partitioning)
        except Exception:
            if not entry.partition_columns:
                raise
            partitioning = ds.partitioning(pa.schema([(column, pa.string()) for column in entry.partition_columns]), flavor='hive')
            dataset = ds.dataset(str(path), format='parquet', partitioning=partitioning)
        return dataset.to_table(columns=columns or None, filter=_pyarrow_filter(entry, query)).to_pandas()
    return pd.read_parquet(path, columns=columns or None)


def _pyarrow_filter(entry: CatalogDataset, query: DataQuery):
    import pyarrow.dataset as ds

    expr = ds.field(entry.date_column) >= str(query.start_date)
    expr = expr & (ds.field(entry.date_column) <= str(query.end_date))
    if query.symbols:
        expr = expr & ds.field(entry.symbol_column).isin(list(query.symbols))
    return expr
