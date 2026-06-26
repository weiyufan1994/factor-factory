from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..catalog import CatalogDataset
from ..errors import DataBackendUnavailable
from ..query import DataQuery


def load_duckdb_file(entry: CatalogDataset, query: DataQuery, columns: list[str]) -> pd.DataFrame:
    if entry.format != 'parquet':
        raise DataBackendUnavailable(f'unsupported DuckDB format for {entry.dataset_id}: {entry.format}')
    try:
        import duckdb
    except ImportError as exc:
        raise DataBackendUnavailable('duckdb is required for DuckDB acceleration backend') from exc

    path = Path(entry.uri.removeprefix('file://')).expanduser()
    parquet_path = _parquet_path(path)
    projection = ', '.join(_quote_identifier(column) for column in columns) if columns else '*'
    filters = [
        f'CAST({_quote_identifier(entry.date_column)} AS VARCHAR) >= ?',
        f'CAST({_quote_identifier(entry.date_column)} AS VARCHAR) <= ?',
    ]
    params: list[object] = [query.start_date, query.end_date]
    if query.symbols:
        placeholders = ', '.join('?' for _ in query.symbols)
        filters.append(f'CAST({_quote_identifier(entry.symbol_column)} AS VARCHAR) IN ({placeholders})')
        params.extend(query.symbols)

    sql = (
        f'SELECT {projection} '
        f'FROM read_parquet(?, hive_partitioning = true) '
        f'WHERE {" AND ".join(filters)}'
    )
    with duckdb.connect(database=':memory:') as con:
        return con.execute(sql, [parquet_path, *params]).fetchdf()


def _parquet_path(path: Path) -> str:
    if path.is_dir():
        return str(path / '**' / '*.parquet')
    return str(path)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
