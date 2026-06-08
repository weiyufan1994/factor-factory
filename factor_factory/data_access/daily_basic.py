from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .paths import LocalTusharePaths, inspect_trade_date_csv_root, resolve_local_tushare_paths

DAILY_BASIC_DATASET_ID = 'daily_basic'
DAILY_BASIC_PARQUET_SCHEMA_VERSION = 'daily_basic_parquet_v1'
DAILY_BASIC_PARQUET_PRODUCER_VERSION = 'factorforge_daily_basic_parquet_cache_v1'

DEFAULT_DAILY_BASIC_COLUMNS = [
    'ts_code',
    'trade_date',
    'turnover_rate',
    'turnover_rate_f',
    'volume_ratio',
    'pe',
    'pe_ttm',
    'pb',
    'ps',
    'ps_ttm',
    'dv_ratio',
    'dv_ttm',
    'total_share',
    'float_share',
    'free_share',
    'total_mv',
    'circ_mv',
]


def default_daily_basic_parquet_root() -> Path:
    explicit = os.getenv('FACTORFORGE_DAILY_BASIC_PARQUET_ROOT')
    if explicit:
        return Path(explicit).expanduser()
    cache_root = os.getenv('FACTORFORGE_DATA_CACHE')
    if cache_root:
        return Path(cache_root).expanduser() / 'daily_basic' / DAILY_BASIC_PARQUET_SCHEMA_VERSION
    worker_cache = Path('/home/ubuntu/factorforge_data_api_cache/daily_basic') / DAILY_BASIC_PARQUET_SCHEMA_VERSION
    if worker_cache.parent.exists():
        return worker_cache
    return Path.home() / '.cache' / 'factorforge_data_api' / 'daily_basic' / DAILY_BASIC_PARQUET_SCHEMA_VERSION


def candidate_daily_basic_parquet_roots(explicit_root: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_root:
        candidates.append(Path(explicit_root).expanduser())
    candidates.append(default_daily_basic_parquet_root())
    if os.getenv('FACTORFORGE_DATA_CACHE'):
        candidates.append(Path(os.environ['FACTORFORGE_DATA_CACHE']).expanduser() / 'daily_basic' / DAILY_BASIC_PARQUET_SCHEMA_VERSION)
    candidates.append(Path('/home/ubuntu/factorforge_data_api_cache/daily_basic') / DAILY_BASIC_PARQUET_SCHEMA_VERSION)
    candidates.append(Path.home() / '.cache' / 'factorforge_data_api' / 'daily_basic' / DAILY_BASIC_PARQUET_SCHEMA_VERSION)
    out: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            out.append(candidate)
            seen.add(key)
    return out


def daily_basic_partition_dir(root: str | Path, trade_date: str | int) -> Path:
    return Path(root).expanduser() / f'trade_date={_normalize_date(trade_date)}'


def daily_basic_partition_path(root: str | Path, trade_date: str | int) -> Path:
    date = _normalize_date(trade_date)
    return daily_basic_partition_dir(root, date) / f'{DAILY_BASIC_DATASET_ID}__{date}.parquet'


def daily_basic_partition_metadata_path(root: str | Path, trade_date: str | int) -> Path:
    date = _normalize_date(trade_date)
    return daily_basic_partition_dir(root, date) / f'{DAILY_BASIC_DATASET_ID}__{date}.metadata.json'


def _normalize_date(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    text = text.replace('-', '').replace('/', '').replace('.0', '')
    return text[:8] if text else None


def _normalize_symbols(symbols: Iterable[str] | None) -> set[str] | None:
    if symbols is None:
        return None
    return {str(symbol).strip() for symbol in symbols if str(symbol).strip()}


def _stable_frame_hash(frame: pd.DataFrame, metadata: dict[str, Any] | None = None) -> str:
    data = frame.drop(columns=['artifact_hash'], errors='ignore').copy()
    sort_cols = [col for col in ['trade_date', 'ts_code'] if col in data.columns]
    if sort_cols:
        data = data.sort_values(sort_cols).reset_index(drop=True)
    payload = {
        'columns': [str(col) for col in data.columns],
        'rows_sha256': hashlib.sha256(data.to_csv(index=False).encode('utf-8')).hexdigest(),
        'metadata': metadata or {},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def list_daily_basic_trade_dates(paths: LocalTusharePaths | None = None) -> list[str]:
    resolved_paths = paths or resolve_local_tushare_paths()
    meta = inspect_trade_date_csv_root(Path(resolved_paths.daily_basic_dir))
    return list(meta['trade_dates']) if meta else []


def _iter_daily_basic_csvs(root: Path, start: str | None, end: str | None) -> list[Path]:
    csv_paths: list[Path] = []
    for part_dir in sorted(root.glob('trade_date=*')):
        if not part_dir.is_dir():
            continue
        trade_date = part_dir.name.replace('trade_date=', '')
        if start and trade_date < start:
            continue
        if end and trade_date > end:
            continue
        csv_paths.extend(sorted(part_dir.glob('*.csv')))
    return csv_paths


def _read_daily_basic_from_csv(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    resolved_paths = paths or resolve_local_tushare_paths()
    root = Path(resolved_paths.daily_basic_dir)
    if not root.exists():
        raise FileNotFoundError(f'daily_basic_incremental not found: {root}')

    requested_columns = list(columns) if columns else list(DEFAULT_DAILY_BASIC_COLUMNS)
    required_columns = ['ts_code', 'trade_date']
    usecols = list(dict.fromkeys(required_columns + requested_columns))

    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    csv_paths = _iter_daily_basic_csvs(root, start_date, end_date)
    if not csv_paths:
        return pd.DataFrame(columns=requested_columns)

    frames: list[pd.DataFrame] = []
    symbol_set = _normalize_symbols(symbols)
    for csv_path in csv_paths:
        frame = pd.read_csv(
            csv_path,
            usecols=lambda column: column in usecols,
            dtype={'ts_code': 'string', 'trade_date': 'string'},
        )
        if 'trade_date' in frame.columns:
            frame['trade_date'] = frame['trade_date'].str.replace('.0', '', regex=False).str.zfill(8)
        if symbol_set:
            frame = frame[frame['ts_code'].isin(symbol_set)]
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=requested_columns)
    merged = pd.concat(frames, ignore_index=True)
    return merged[requested_columns].reset_index(drop=True)


def write_daily_basic_parquet_partitions(
    frame: pd.DataFrame,
    *,
    root: str | Path | None = None,
    source_data_version: str = 'daily_basic_incremental_csv',
) -> dict[str, Any]:
    started = time.perf_counter()
    cache_root = Path(root).expanduser() if root else default_daily_basic_parquet_root()
    payload = frame.copy()
    if payload.empty:
        return {
            'version': 'factorforge_daily_basic_parquet_write_profile_v1',
            'dataset_id': DAILY_BASIC_DATASET_ID,
            'root': str(cache_root),
            'written_partitions': [],
            'row_count': 0,
            'write_seconds': time.perf_counter() - started,
        }
    if 'trade_date' not in payload.columns:
        raise ValueError('daily_basic parquet cache requires trade_date')
    payload['trade_date'] = payload['trade_date'].map(_normalize_date)
    if 'ts_code' in payload.columns:
        payload['ts_code'] = payload['ts_code'].astype('string')

    written: list[dict[str, Any]] = []
    for trade_date, part in payload.groupby('trade_date', sort=True):
        date = _normalize_date(trade_date)
        if not date:
            continue
        metadata = {
            'dataset_id': DAILY_BASIC_DATASET_ID,
            'schema_version': DAILY_BASIC_PARQUET_SCHEMA_VERSION,
            'producer_version': DAILY_BASIC_PARQUET_PRODUCER_VERSION,
            'source_data_version': source_data_version,
            'trade_date': date,
            'columns': [str(col) for col in part.columns],
        }
        artifact_hash = _stable_frame_hash(part, metadata)
        enriched = part.copy()
        enriched['source_data_version'] = source_data_version
        enriched['schema_version'] = DAILY_BASIC_PARQUET_SCHEMA_VERSION
        enriched['producer_version'] = DAILY_BASIC_PARQUET_PRODUCER_VERSION
        enriched['artifact_hash'] = artifact_hash
        path = daily_basic_partition_path(cache_root, date)
        meta_path = daily_basic_partition_metadata_path(cache_root, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        enriched.to_parquet(path, index=False)
        meta_payload = {
            **metadata,
            'artifact_hash': artifact_hash,
            'path': str(path),
            'row_count': int(len(enriched)),
            'written_at_utc': pd.Timestamp.utcnow().isoformat(),
        }
        meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        written.append(meta_payload)
    return {
        'version': 'factorforge_daily_basic_parquet_write_profile_v1',
        'dataset_id': DAILY_BASIC_DATASET_ID,
        'root': str(cache_root),
        'written_partitions': written,
        'row_count': int(len(payload)),
        'date_count': len(written),
        'write_seconds': time.perf_counter() - started,
    }


def load_daily_basic_parquet_partitions(
    *,
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    root: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    started = time.perf_counter()
    cache_roots = candidate_daily_basic_parquet_roots(root)
    requested_columns = list(columns) if columns else list(DEFAULT_DAILY_BASIC_COLUMNS)
    required_columns = ['ts_code', 'trade_date']
    parquet_columns = list(dict.fromkeys(required_columns + requested_columns))
    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    symbol_set = _normalize_symbols(symbols)
    frames: list[pd.DataFrame] = []
    scanned_partitions = 0
    selected_paths: list[str] = []
    cache_root_used: str | None = None
    for candidate_root in cache_roots:
        if not candidate_root.exists():
            continue
        part_paths: list[Path] = []
        for path in sorted(candidate_root.glob('trade_date=*/*.parquet')):
            date = path.parent.name.replace('trade_date=', '')
            if start_date and date < start_date:
                continue
            if end_date and date > end_date:
                continue
            part_paths.append(path)
        if not part_paths:
            continue
        cache_root_used = str(candidate_root)
        for path in part_paths:
            scanned_partitions += 1
            available_columns = pd.read_parquet(path).head(0).columns
            use_columns = [col for col in parquet_columns if col in available_columns]
            frame = pd.read_parquet(path, columns=use_columns)
            if symbol_set and 'ts_code' in frame.columns:
                frame = frame[frame['ts_code'].astype('string').isin(symbol_set)]
            for column in requested_columns:
                if column not in frame.columns:
                    frame[column] = pd.NA
            frames.append(frame[requested_columns])
            selected_paths.append(str(path))
        break
    if not frames:
        return pd.DataFrame(columns=requested_columns), {
            'version': 'factorforge_daily_basic_cache_profile_v1',
            'dataset_id': DAILY_BASIC_DATASET_ID,
            'selected_format': 'none',
            'cache_hit': False,
            'cache_status': 'miss',
            'cache_root': cache_root_used,
            'candidate_roots': [str(path) for path in cache_roots],
            'row_count': 0,
            'date_count': 0,
            'ticker_count': 0,
            'load_seconds': time.perf_counter() - started,
        }
    merged = pd.concat(frames, ignore_index=True)
    profile = {
        'version': 'factorforge_daily_basic_cache_profile_v1',
        'dataset_id': DAILY_BASIC_DATASET_ID,
        'selected_format': 'parquet',
        'cache_hit': True,
        'cache_status': 'warm_hit',
        'cache_root': cache_root_used,
        'candidate_roots': [str(path) for path in cache_roots],
        'selected_paths': selected_paths,
        'partition_count': scanned_partitions,
        'row_count': int(len(merged)),
        'date_count': int(merged['trade_date'].nunique()) if 'trade_date' in merged.columns else 0,
        'ticker_count': int(merged['ts_code'].nunique()) if 'ts_code' in merged.columns else 0,
        'load_seconds': time.perf_counter() - started,
    }
    return merged.reset_index(drop=True), profile


def get_daily_basic_with_profile(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
    *,
    parquet_root: str | Path | None = None,
    source_data_version: str = 'daily_basic_incremental_csv',
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if os.getenv('FACTORFORGE_DISABLE_DAILY_BASIC_PARQUET_CACHE', '').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        cached, cache_profile = load_daily_basic_parquet_partitions(
            start=start,
            end=end,
            symbols=symbols,
            columns=columns,
            root=parquet_root,
        )
        if not cached.empty:
            return cached, cache_profile

    csv_started = time.perf_counter()
    frame = _read_daily_basic_from_csv(start=start, end=end, symbols=symbols, columns=columns, paths=paths)
    csv_seconds = time.perf_counter() - csv_started
    write_profile = write_daily_basic_parquet_partitions(
        frame,
        root=parquet_root,
        source_data_version=source_data_version,
    ) if not frame.empty else {}
    profile = {
        'version': 'factorforge_daily_basic_cache_profile_v1',
        'dataset_id': DAILY_BASIC_DATASET_ID,
        'selected_format': 'parquet' if write_profile else 'csv_empty',
        'cache_hit': False,
        'cache_status': 'backfilled_from_csv' if write_profile else 'empty_source',
        'cache_root': write_profile.get('root') if isinstance(write_profile, dict) else str(parquet_root or default_daily_basic_parquet_root()),
        'csv_load_seconds': csv_seconds,
        'write_profile': write_profile,
        'row_count': int(len(frame)),
        'date_count': int(frame['trade_date'].nunique()) if 'trade_date' in frame.columns and len(frame) else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and len(frame) else 0,
    }
    return frame.reset_index(drop=True), profile


def get_daily_basic(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    frame, _ = get_daily_basic_with_profile(
        start=start,
        end=end,
        symbols=symbols,
        columns=columns,
        paths=paths,
    )
    return frame
