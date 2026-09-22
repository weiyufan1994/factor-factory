"""Bounded SQLite day lookups for the local PF/VV monthly caller.

The store is deliberately an adapter: it does not alter the execution engine
or invent price/constraint semantics.  Each Parquet source is scanned once in
64K batches, and each batch is passed through the supplied engine's real input
normalizer before it is persisted.
"""
from __future__ import annotations

from collections import OrderedDict
import importlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

import pandas as pd


BATCH_SIZE = 65_536
TABLES = ("daily", "execution", "constraints")


class DailyLookupStoreError(ValueError):
    pass


def _dates(values: Iterable[Any]) -> list[str]:
    series = pd.Series(list(values), dtype="string")
    text = series.str.strip()
    parsed = pd.to_datetime(text.where(~text.str.fullmatch(r"\d{8}")), errors="coerce")
    compact = text.str.fullmatch(r"\d{8}")
    parsed.loc[compact] = pd.to_datetime(text.loc[compact], format="%Y%m%d", errors="coerce")
    if parsed.isna().any():
        raise DailyLookupStoreError("invalid_calendar_date")
    return parsed.dt.strftime("%Y-%m-%d").tolist()


def _date_key(value: Any) -> str:
    """Use the engine's already-normalized ISO day without pandas work.

    The frozen engine calls ``row(code, trade_date)`` once per stock-day and
    supplies ``YYYY-MM-DD`` calendar values.  Parsing that value into a Series
    for every row would turn a bounded lookup into a per-security pandas hot
    path.  Noncanonical callers retain the original strict normalizer.
    """
    if (
        isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-"
        and value[:4].isdigit() and value[5:7].isdigit() and value[8:].isdigit()
    ):
        return value
    return _dates([value])[0]


def _path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise DailyLookupStoreError(f"{label}_must_be_existing_absolute_file")
    return path.resolve()


def _empty_like(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq
        return list(pq.ParquetFile(path).schema_arrow.names)
    except Exception as exc:
        raise DailyLookupStoreError(f"parquet_schema_unreadable:{path.name}") from exc


def _normalize_batch(engine: Any, factors: pd.DataFrame, domain: pd.DataFrame,
                     daily: pd.DataFrame, execution: pd.DataFrame,
                     constraints: pd.DataFrame, calendar: pd.DataFrame) -> tuple[pd.DataFrame, ...]:
    if not callable(getattr(engine, "_normalize_inputs", None)):
        raise DailyLookupStoreError("execution_engine_missing_normalize_inputs")
    try:
        result = engine._normalize_inputs(factors, domain, daily, execution, constraints, calendar)
    except Exception as exc:
        raise DailyLookupStoreError("engine_normalize_batch_failed") from exc
    if not isinstance(result, tuple) or len(result) != 6 or not all(isinstance(frame, pd.DataFrame) for frame in result[:5]):
        raise DailyLookupStoreError("engine_normalize_batch_shape_invalid")
    return result


def _execution_bridge(frame: pd.DataFrame) -> pd.DataFrame:
    try:
        backend = importlib.import_module("examples.mszq_intraday_momentum_pulse.pfvv_monthly_step4_backend_v1")
        legacy, _coverage = backend.bridge_execution_vwap(frame)
        return legacy
    except Exception as exc:
        raise DailyLookupStoreError("execution_bridge_failed") from exc


class SQLiteDayLookup:
    """Engine-compatible day partition object backed by an indexed SQLite table."""

    def __init__(self, sqlite_path: Path, table: str, *, cache_days: int = 4):
        self.sqlite_path, self.table, self.cache_days = sqlite_path, table, cache_days
        self._cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self.day_read_counts: dict[str, int] = {}

    def _date_frame(self, date: Any, *, copy: bool = True) -> pd.DataFrame:
        key = _date_key(date)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key].copy() if copy else self._cache[key]
        with sqlite3.connect(self.sqlite_path.as_uri() + '?mode=ro', uri=True) as connection:
            frame = pd.read_sql_query(
                f'SELECT * FROM "{self.table}" WHERE trade_date = ? ORDER BY ts_code', connection, params=[key],
            )
        self.day_read_counts[key] = self.day_read_counts.get(key, 0) + 1
        self._cache[key] = frame
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_days:
            self._cache.popitem(last=False)
        return frame.copy() if copy else frame

    def _date_partition(self, date: Any) -> pd.DataFrame:
        """DataFrame partition protocol for engines without a bounded-row type."""
        return self._date_frame(date)


def _bounded_lookup_class(engine: Any):
    base = getattr(engine, "_BoundedStockDayRows", object)
    if not isinstance(base, type):
        base = object
    if base is object:
        return SQLiteDayLookup
    class EngineBoundedSQLiteDayRows(base, SQLiteDayLookup):
        def _date_partition(self, date: Any):
            """Implement the frozen engine's bounded-row partition contract.

            ``base.row`` unpacks ``(positions, column_arrays, row_cache)``.
            Returning a DataFrame here looks superficially useful but breaks
            that contract and makes the real engine fail before simulation.
            """
            key = _date_key(date)
            partitions = getattr(self, "_sqlite_engine_partitions", None)
            if partitions is None:
                partitions = OrderedDict()
                self._sqlite_engine_partitions = partitions
            if key in partitions:
                partitions.move_to_end(key)
                return partitions[key]
            frame = SQLiteDayLookup._date_frame(self, key, copy=False)
            if frame.empty:
                partition = None
            else:
                positions = {str(code): ordinal for ordinal, code in enumerate(frame["ts_code"].tolist())}
                columns = {str(column): frame[column].to_numpy(copy=False) for column in frame.columns}
                for array in columns.values():
                    array.flags.writeable = False
                partition = positions, columns, {}
            partitions[key] = partition
            while len(partitions) > self.cache_days:
                partitions.popitem(last=False)
            return partition
    return EngineBoundedSQLiteDayRows


def _make_lookup(engine: Any, sqlite_path: Path, table: str) -> SQLiteDayLookup:
    cls = _bounded_lookup_class(engine)
    lookup = cls.__new__(cls)
    SQLiteDayLookup.__init__(lookup, sqlite_path, table, cache_days=4)
    return lookup


def _ensure_store_table(connection: sqlite3.Connection, table: str, frame: pd.DataFrame, initialized: set[str]) -> None:
    required = {"ts_code", "trade_date"}
    if not required.issubset(frame.columns):
        raise DailyLookupStoreError(f"{table}_normalized_missing_keys")
    if table not in initialized:
        frame.head(0).to_sql(table, connection, index=False)
        connection.execute(f'CREATE UNIQUE INDEX "{table}_key" ON "{table}" (trade_date, ts_code)')
        initialized.add(table)


def _store_frame(connection: sqlite3.Connection, table: str, frame: pd.DataFrame, initialized: set[str]) -> int:
    _ensure_store_table(connection, table, frame, initialized)
    if frame.empty:
        return 0
    frame = frame.copy()
    frame["ts_code"] = frame["ts_code"].astype("string").astype(str)
    frame["trade_date"] = _dates(frame["trade_date"])
    if frame.duplicated(["ts_code", "trade_date"]).any():
        raise DailyLookupStoreError(f"{table}_duplicate_key_within_batch")
    try:
        frame.to_sql(table, connection, index=False, if_exists="append")
    except sqlite3.IntegrityError as exc:
        raise DailyLookupStoreError(f"{table}_duplicate_key_across_batches") from exc
    return len(frame)


def _register_raw_execution_keys(connection: sqlite3.Connection, frame: pd.DataFrame) -> None:
    """Reject duplicate producer stock-days before null-VWAP filtering.

    The frozen normalizer deliberately removes unavailable VWAP rows.  Its
    post-normalization uniqueness check therefore cannot see duplicated null
    source rows split across batches; this separate create-only ledger can.
    """
    required = {"ts_code", "trade_date"}
    if not required.issubset(frame.columns):
        raise DailyLookupStoreError("execution_raw_missing_keys")
    keys = frame.loc[:, ["ts_code", "trade_date"]].copy()
    if keys["ts_code"].isna().any() or keys["ts_code"].astype("string").str.strip().eq("").any():
        raise DailyLookupStoreError("execution_raw_invalid_ts_code")
    keys["ts_code"] = keys["ts_code"].astype("string").astype(str)
    keys["trade_date"] = _dates(keys["trade_date"])
    if keys.duplicated().any():
        raise DailyLookupStoreError("execution_raw_duplicate_key_within_batch")
    try:
        keys.to_sql("execution_raw_keys", connection, index=False, if_exists="append")
    except sqlite3.IntegrityError as exc:
        raise DailyLookupStoreError("execution_raw_duplicate_key_across_batches") from exc


def _store_key_batch(connection: sqlite3.Connection, table: str, frame: pd.DataFrame) -> int:
    if not {"ts_code", "trade_date"}.issubset(frame.columns):
        raise DailyLookupStoreError(f"{table}_normalized_missing_keys")
    keys = frame.loc[:, ["ts_code", "trade_date"]].copy()
    keys["ts_code"] = keys["ts_code"].astype("string").astype(str)
    keys["trade_date"] = _dates(keys["trade_date"])
    if keys.duplicated().any():
        raise DailyLookupStoreError(f"{table}_duplicate_key_within_batch")
    try:
        keys.to_sql(table, connection, index=False, if_exists="append")
    except sqlite3.IntegrityError as exc:
        raise DailyLookupStoreError(f"{table}_duplicate_key_across_batches") from exc
    return len(keys)


def _project_structural_nan_factor_tail_batch(
    connection: sqlite3.Connection,
    frame: pd.DataFrame,
    *,
    signal_columns: tuple[str, ...],
) -> tuple[pd.DataFrame, int]:
    """Return only domain keys after rejecting an informative factor-only tail.

    ``domain_keys`` has already been made unique before this bounded batch is
    examined.  The temporary table is deliberately replaced for every batch:
    no full factor frame or auxiliary factor table is retained in SQLite.
    """
    frame.to_sql("_factor_batch", connection, index=False, if_exists="replace")
    selected = ", ".join(f'f."{column}"' for column in frame.columns)
    extra = pd.read_sql_query(
        "SELECT " + selected + " FROM _factor_batch f "
        "LEFT JOIN domain_keys d ON d.trade_date=f.trade_date AND d.ts_code=f.ts_code "
        "WHERE d.ts_code IS NULL",
        connection,
    )
    if not extra.empty and not extra.loc[:, list(signal_columns)].isna().all(axis=None):
        raise DailyLookupStoreError("factor_domain_extra_signal_not_nan")
    projected = pd.read_sql_query(
        "SELECT " + selected + " FROM _factor_batch f "
        "INNER JOIN domain_keys d ON d.trade_date=f.trade_date AND d.ts_code=f.ts_code",
        connection,
    )
    return projected, len(extra)


def build_pfvv_daily_lookup_store(*, factor_values_path: str | Path, measurement_domain_path: str | Path,
                                  daily_prices_path: str | Path, execution_vwap_path: str | Path,
                                  normalized_constraints_path: str | Path, calendar: pd.DataFrame | Iterable[Any],
                                  execution_engine: Any, output_root: str | Path,
                                  factor_value_columns: Iterable[str] = ("factor_value",),
                                  project_structural_nan_factor_tail: bool = False) -> dict[str, Any]:
    """Build one create-only SQLite store and return bounded engine lookups.

    The optional projection is intentionally off by default.  When explicitly
    enabled, it permits only factor-only rows whose *declared* signal columns
    are all missing, then sends the measurement-domain key projection to the
    monthly evaluator.  It never edits the upstream factor artifact.
    """
    if not isinstance(project_structural_nan_factor_tail, bool):
        raise DailyLookupStoreError("project_structural_nan_factor_tail_must_be_bool")
    paths = {name: _path(value, name) for name, value in {
        "factor_values": factor_values_path, "measurement_domain": measurement_domain_path,
        "daily_prices": daily_prices_path, "execution_vwap": execution_vwap_path,
        "normalized_constraints": normalized_constraints_path,
    }.items()}
    factor_available_columns = _parquet_columns(paths["factor_values"])
    requested_factor_values = tuple(str(column) for column in factor_value_columns)
    if not requested_factor_values or len(set(requested_factor_values)) != len(requested_factor_values):
        raise DailyLookupStoreError("factor_value_columns_invalid")
    factor_columns = ["ts_code", "trade_date", *requested_factor_values]
    if not set(factor_columns).issubset(factor_available_columns):
        raise DailyLookupStoreError("factor_value_columns_missing")
    domain_columns = _parquet_columns(paths["measurement_domain"])
    daily_columns = _parquet_columns(paths["daily_prices"])
    execution_columns = ["ts_code", "trade_date", "vwap_unadjusted", "bar_count", "price_basis"]
    constraints_columns = _parquet_columns(paths["normalized_constraints"])
    if not {"ts_code", "trade_date"}.issubset(factor_available_columns) or not {"ts_code", "trade_date"}.issubset(domain_columns):
        raise DailyLookupStoreError("factor_or_domain_missing_keys")
    calendar_frame = calendar.copy() if isinstance(calendar, pd.DataFrame) else pd.DataFrame({"trade_date": list(calendar)})
    if "trade_date" not in calendar_frame:
        raise DailyLookupStoreError("calendar_missing_trade_date")
    calendar_dates = _dates(calendar_frame["trade_date"])
    if len(calendar_dates) != len(set(calendar_dates)) or calendar_dates != sorted(calendar_dates):
        raise DailyLookupStoreError("calendar_must_be_sorted_unique")
    calendar_norm = calendar_frame.copy()
    calendar_norm["trade_date"] = calendar_dates
    month_end = sorted({max(day for day in calendar_dates if day[:7] == month) for month in {day[:7] for day in calendar_dates}})
    output = Path(output_root).expanduser()
    if not output.is_absolute() or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise DailyLookupStoreError("output_root_must_be_new_absolute_directory")
    output.mkdir()
    sqlite_path = output / "_join.sqlite.partial"
    final_sqlite = output / "_join.sqlite"
    initialized: set[str] = set()
    counts = {table: 0 for table in TABLES}
    factor_month_parts: list[pd.DataFrame] = []
    domain_month_parts: list[pd.DataFrame] = []
    factor_input_rows = 0
    domain_input_rows = 0
    factor_only_rows = 0
    try:
        with sqlite3.connect(sqlite_path) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute('CREATE TABLE factor_keys (trade_date TEXT NOT NULL, ts_code TEXT NOT NULL)')
            connection.execute('CREATE UNIQUE INDEX factor_keys_key ON factor_keys (trade_date, ts_code)')
            connection.execute('CREATE TABLE domain_keys (trade_date TEXT NOT NULL, ts_code TEXT NOT NULL)')
            connection.execute('CREATE UNIQUE INDEX domain_keys_key ON domain_keys (trade_date, ts_code)')
            connection.execute('CREATE TABLE execution_raw_keys (trade_date TEXT NOT NULL, ts_code TEXT NOT NULL)')
            connection.execute('CREATE UNIQUE INDEX execution_raw_keys_key ON execution_raw_keys (trade_date, ts_code)')
            parquet_loader = __import__("pyarrow.parquet", fromlist=["ParquetFile"])

            # The structural-NaN policy needs the complete unique domain key
            # ledger before it streams factor batches.  The legacy exact-set
            # route preserves its original scan order and semantics.
            key_scan_order = (
                (("measurement_domain", "domain_keys", domain_month_parts, False),
                 ("factor_values", "factor_keys", factor_month_parts, True))
                if project_structural_nan_factor_tail
                else (("factor_values", "factor_keys", factor_month_parts, True),
                      ("measurement_domain", "domain_keys", domain_month_parts, False))
            )
            for source_name, key_table, month_parts, is_factor in key_scan_order:
                parquet = parquet_loader.ParquetFile(paths[source_name])
                selected_columns = factor_columns if is_factor else None
                for batch in parquet.iter_batches(batch_size=BATCH_SIZE, columns=selected_columns):
                    frame = batch.to_pandas()
                    if is_factor:
                        factor_input_rows += len(frame)
                    else:
                        domain_input_rows += len(frame)
                    normalized = _normalize_batch(
                        execution_engine,
                        frame if is_factor else _empty_like(factor_columns),
                        _empty_like(domain_columns) if is_factor else frame,
                        _empty_like(daily_columns), _empty_like(execution_columns),
                        _empty_like(constraints_columns), calendar_norm,
                    )
                    selected = normalized[0 if is_factor else 1].copy()
                    selected["trade_date"] = _dates(selected["trade_date"])
                    _store_key_batch(connection, key_table, selected)
                    if is_factor and project_structural_nan_factor_tail:
                        selected, extra_count = _project_structural_nan_factor_tail_batch(
                            connection, selected, signal_columns=requested_factor_values,
                        )
                        factor_only_rows += extra_count
                    month_parts.append(selected.loc[selected["trade_date"].isin(month_end)].copy())

            domain_missing_factor = connection.execute(
                "SELECT 1 FROM domain_keys d WHERE NOT EXISTS "
                "(SELECT 1 FROM factor_keys f WHERE f.trade_date=d.trade_date AND f.ts_code=d.ts_code) LIMIT 1"
            ).fetchone()
            if domain_missing_factor:
                raise DailyLookupStoreError("factor_domain_key_set_mismatch")
            if not project_structural_nan_factor_tail:
                factor_only = connection.execute(
                    "SELECT 1 FROM factor_keys f WHERE NOT EXISTS "
                    "(SELECT 1 FROM domain_keys d WHERE d.trade_date=f.trade_date AND d.ts_code=f.ts_code) LIMIT 1"
                ).fetchone()
                if factor_only:
                    raise DailyLookupStoreError("factor_domain_key_set_mismatch")
            if project_structural_nan_factor_tail:
                # The batch table is working state only; successful lookup
                # stores retain no duplicate factor-frame payload.
                connection.execute("DROP TABLE IF EXISTS _factor_batch")
            for source_name, table in (("daily_prices", "daily"), ("execution_vwap", "execution"), ("normalized_constraints", "constraints")):
                parquet = parquet_loader.ParquetFile(paths[source_name])
                for batch in parquet.iter_batches(batch_size=BATCH_SIZE):
                    frame = batch.to_pandas()
                    if table == "execution":
                        _register_raw_execution_keys(connection, frame)
                        frame = _execution_bridge(frame)
                    empty_daily = _empty_like(daily_columns)
                    empty_execution = _empty_like(execution_columns)
                    empty_constraints = _empty_like(constraints_columns)
                    normalized = _normalize_batch(
                        execution_engine, _empty_like(factor_columns), _empty_like(domain_columns),
                        frame if table == "daily" else empty_daily,
                        frame if table == "execution" else empty_execution,
                        frame if table == "constraints" else empty_constraints,
                        calendar_norm,
                    )
                    selected = normalized[{"daily": 2, "execution": 3, "constraints": 4}[table]]
                    counts[table] += _store_frame(connection, table, selected, initialized)
            connection.commit()
        os.link(sqlite_path, final_sqlite)
        sqlite_path.unlink()
    except Exception:
        raise
    month_end_factor = pd.concat(factor_month_parts, ignore_index=True) if factor_month_parts else pd.DataFrame(columns=factor_columns)
    month_end_domain = pd.concat(domain_month_parts, ignore_index=True) if domain_month_parts else pd.DataFrame(columns=domain_columns)
    lookups = {table: _make_lookup(execution_engine, final_sqlite, table) for table in TABLES}
    return {"store_root": os.fspath(output), "sqlite_path": os.fspath(final_sqlite),
            "calendar_dates": calendar_dates, "month_end_dates": month_end,
            "factor_values": month_end_factor, "measurement_domain": month_end_domain,
            "month_end_factor_values": month_end_factor, "month_end_measurement_domain": month_end_domain,
            "lookups": lookups,
            "qa": {
                "rows": counts,
                "batch_size": BATCH_SIZE,
                "cache_days": 4,
                "factor_domain_projection": {
                    "policy": (
                        "domain_subset_structural_nan_factor_tail_v1"
                        if project_structural_nan_factor_tail else "exact_key_set_v1"
                    ),
                    "enabled": project_structural_nan_factor_tail,
                    "signal_columns": list(requested_factor_values),
                    "original_factor_rows": factor_input_rows,
                    "measurement_domain_rows": domain_input_rows,
                    "factor_only_rows": factor_only_rows,
                    "projected_factor_rows": factor_input_rows - factor_only_rows,
                    "projected_key_sets_equal": True,
                    "projection_boundary": (
                        "bounded_batch_semi_join_to_measurement_domain"
                        if project_structural_nan_factor_tail else "none"
                    ),
                },
            }}


__all__ = ["BATCH_SIZE", "DailyLookupStoreError", "SQLiteDayLookup", "build_pfvv_daily_lookup_store"]


def cached_pfvv_daily_lookup_store(*, cache_root, **kwargs):
    """Reuse exact, validated input bytes and their normalized read-only store.

    No row-count or latest-day shortcut proves reuse: every input and cached
    artifact is content hashed. New identities build in a separate directory;
    a corrupt existing identity fails rather than silently replacing evidence.
    """
    import fcntl
    import hashlib
    import inspect
    import marshal
    import uuid
    import platform
    import shutil
    import pyarrow
    import numpy

    def digest(path):
        with Path(path).open('rb') as handle:
            value = hashlib.sha256()
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                value.update(block)
            return value.hexdigest()

    paths = {name: _path(kwargs[name], name) for name in (
        'factor_values_path', 'measurement_domain_path', 'daily_prices_path',
        'execution_vwap_path', 'normalized_constraints_path')}
    engine = kwargs['execution_engine']
    engine_path = getattr(engine, '__file__', None) or inspect.getsourcefile(type(engine))
    if not engine_path:
        raise DailyLookupStoreError('reusable_store_requires_identified_execution_engine')
    normalizer = getattr(engine._normalize_inputs, '__func__', engine._normalize_inputs)
    calendar = kwargs['calendar']
    calendar_frame = calendar.copy() if isinstance(calendar, pd.DataFrame) else pd.DataFrame({'trade_date': list(calendar)})
    kwargs = {**kwargs, 'calendar': calendar_frame, 'factor_value_columns': tuple(kwargs.get('factor_value_columns', ('factor_value',)))}
    identity = {
        'version': 'pfvv_lookup_cache_v1',
        'inputs': {name: {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size} for name, path in paths.items()},
        'calendar_json': calendar_frame.to_json(orient='split', date_format='iso'),
        'factor_value_columns': list(kwargs.get('factor_value_columns', ('factor_value',))),
        'project_structural_nan_factor_tail': kwargs.get('project_structural_nan_factor_tail', False),
        'code': {'store': digest(__file__), 'bridge': digest(Path(__file__).with_name('pfvv_monthly_step4_backend_v1.py')),
            'engine': digest(engine_path), 'normalizer': hashlib.sha256(marshal.dumps(normalizer.__code__)).hexdigest()},
        'runtime': {'python': platform.python_version(), 'pandas': pd.__version__,
            'pyarrow': pyarrow.__version__, 'numpy': numpy.__version__, 'sqlite': sqlite3.sqlite_version},
    }
    if getattr(engine, '__file__', None):
        identity['code']['engine_dependencies'] = {p.name: digest(p) for p in Path(engine_path).parent.glob('*.py')}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    root = Path(cache_root).resolve();root.mkdir(parents=True, exist_ok=True)
    target = root/key
    with (root/(key+'.lock')).open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            receipt = json.loads((target/'receipt.json').read_text())
            if receipt['identity'] != identity:
                raise DailyLookupStoreError('cached_store_identity_mismatch')
            for name in ['_join.sqlite', 'month_end_factor.parquet', 'month_end_domain.parquet', 'metadata.json']:
                if digest(target/name) != receipt['artifacts'][name]:
                    raise DailyLookupStoreError('cached_store_artifact_hash_mismatch')
            status = 'hit'
        else:
            temporary = root/('.building-'+key+'-'+uuid.uuid4().hex)
            inputs = root/('.inputs-'+key+'-'+uuid.uuid4().hex)
            inputs.mkdir()
            frozen_kwargs = dict(kwargs)
            for name, source in paths.items():
                target_input = inputs/(name+source.suffix)
                shutil.copyfile(source, target_input)
                if digest(target_input) != identity['inputs'][name]['sha256']:
                    raise DailyLookupStoreError('input_bytes_changed_during_store_snapshot')
                target_input.chmod(0o444)
                frozen_kwargs[name] = target_input
            result = build_pfvv_daily_lookup_store(**frozen_kwargs, output_root=temporary)
            result['month_end_factor_values'].to_parquet(temporary/'month_end_factor.parquet', index=False)
            result['month_end_measurement_domain'].to_parquet(temporary/'month_end_domain.parquet', index=False)
            metadata = {name: result[name] for name in ['calendar_dates', 'month_end_dates', 'qa']}
            with (temporary/'metadata.json').open('x') as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
            if any(digest(frozen_kwargs[name]) != identity['inputs'][name]['sha256'] for name in paths):
                raise DailyLookupStoreError('immutable_input_bytes_changed_during_store_build')
            receipt = {'identity': identity, 'artifacts': {name: digest(temporary/name)
                for name in ['_join.sqlite', 'month_end_factor.parquet', 'month_end_domain.parquet', 'metadata.json']}}
            with (temporary/'receipt.json').open('x') as handle:
                json.dump(receipt, handle, ensure_ascii=False, indent=2)
            for name in receipt['artifacts']:
                (temporary/name).chmod(0o444)
            temporary.rename(target)
            shutil.rmtree(inputs)
            status = 'miss'
        metadata = json.loads((target/'metadata.json').read_text())
        factors, domain = pd.read_parquet(target/'month_end_factor.parquet'), pd.read_parquet(target/'month_end_domain.parquet')
        return {**metadata, 'store_root': str(target), 'sqlite_path': str(target/'_join.sqlite'),
            'factor_values': factors, 'measurement_domain': domain, 'month_end_factor_values': factors,
            'month_end_measurement_domain': domain, 'lookups': {table: _make_lookup(engine, target/'_join.sqlite', table) for table in TABLES},
            'reuse': {'status': status, 'identity_sha256': key, 'artifact_sha256': receipt['artifacts'],
                'input_snapshot_copied_bytes': sum(v['bytes'] for v in identity['inputs'].values()) if status == 'miss' else 0,
                'input_identity': identity}}
