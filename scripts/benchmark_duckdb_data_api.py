#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api import DataApiClient, DataQuery, validate_data_api_result


DEFAULT_DATES = ['20160104', '20200102', '20210930', '20240110', '20250711']
DEFAULT_DATASETS = ['tradability_risk_flags_daily', 'microcap_universe', 'standard_full_market_universe']
DEFAULT_WINDOW_START = '20240102'
DEFAULT_WINDOW_END = '20240329'
DEFAULT_FIELDS = {
    'tradability_risk_flags_daily': ['is_investable_core', 'is_investable_500m'],
    'microcap_universe': ['universe_id', 'in_universe'],
    'standard_full_market_universe': ['in_universe', 'market_cap'],
}


def parse_args() -> argparse.Namespace:
    today = datetime.now().strftime('%Y%m%d')
    ap = argparse.ArgumentParser(description='Run isolated DuckDB Data API benchmark smoke without modifying canonical catalog/datamarts.')
    ap.add_argument('--catalog', default='factorforge/data/catalog/data_catalog.json')
    ap.add_argument('--dates', nargs='*', default=DEFAULT_DATES)
    ap.add_argument('--datasets', nargs='*', default=DEFAULT_DATASETS)
    ap.add_argument('--window-start', default=DEFAULT_WINDOW_START)
    ap.add_argument('--window-end', default=DEFAULT_WINDOW_END)
    ap.add_argument('--tmp-root', default='/tmp/factorforge-data-acceleration-duckdb')
    ap.add_argument('--proof-output', default=f'factorforge/data/proofs/data_acceleration/duckdb_backend_smoke__{today}.json')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    catalog_path = Path(args.catalog).expanduser()
    proof_output = Path(args.proof_output).expanduser()
    tmp_root = Path(args.tmp_root).expanduser()
    issues: list[str] = []

    try:
        import duckdb
        duckdb_version = getattr(duckdb, '__version__', 'unknown')
    except ImportError:
        duckdb_version = None
        issues.append('duckdb_import_failed')

    if not _is_allowed_output(proof_output):
        issues.append(f'proof_output_not_allowed: {proof_output}')

    tmp_root.mkdir(parents=True, exist_ok=True)
    duckdb_catalog = tmp_root / 'data_catalog.duckdb.json'
    if not issues:
        _write_duckdb_catalog(catalog_path, duckdb_catalog, args.datasets)

    read_results: list[dict[str, Any]] = []
    window_read_results: list[dict[str, Any]] = []
    join_results: list[dict[str, Any]] = []
    sql_join_results: list[dict[str, Any]] = []
    if not issues:
        reference_client = DataApiClient.from_catalog(catalog_path)
        duckdb_client = DataApiClient.from_catalog(duckdb_catalog)
        for dataset_id in args.datasets:
            if dataset_id not in reference_client.catalog.datasets:
                read_results.append({'dataset_id': dataset_id, 'status': 'skipped', 'reason': 'dataset_not_found'})
                continue
            fields = DEFAULT_FIELDS.get(dataset_id, [])
            for trade_date in args.dates:
                read_results.append(_run_read_pair(reference_client, duckdb_client, dataset_id, trade_date, trade_date, fields))
            window_read_results.append(_run_read_pair(reference_client, duckdb_client, dataset_id, args.window_start, args.window_end, fields))
        if {'microcap_universe', 'tradability_risk_flags_daily'}.issubset(reference_client.catalog.datasets):
            for trade_date in args.dates:
                join_results.append(_run_microcap_investability_join(reference_client, duckdb_client, trade_date))
            sql_join_results.append(_run_microcap_investability_join_sql(reference_client, duckdb_client, args.window_start, args.window_end))

    for item in [*read_results, *window_read_results]:
        if item.get('status') == 'skipped':
            continue
        if not item.get('matches_reference'):
            issues.append(f"read_mismatch:{item.get('dataset_id')}:{item.get('start_date')}:{item.get('end_date')}")
        if item.get('duckdb_status') not in {'ready', 'proxy_ready'}:
            issues.append(f"duckdb_read_not_ready:{item.get('dataset_id')}:{item.get('start_date')}:{item.get('end_date')}:{item.get('duckdb_status')}")
    for item in [*join_results, *sql_join_results]:
        if not item.get('matches_reference'):
            issues.append(f"join_mismatch:{item.get('start_date')}:{item.get('end_date')}:{item.get('query_name')}")

    proof = {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'benchmark_id': f'duckdb_backend_smoke_{datetime.now().strftime("%Y%m%d%H%M%S")}',
        'backend': 'duckdb',
        'duckdb_version': duckdb_version,
        'repo_sha': _repo_sha(),
        'catalog_path': str(catalog_path),
        'temporary_catalog_path': str(duckdb_catalog),
        'dates': list(args.dates),
        'window': {'start': args.window_start, 'end': args.window_end},
        'datasets': list(args.datasets),
        'isolation': {
            'writes_factorforge_objects': False,
            'writes_factorforge_runs': False,
            'writes_factorforge_evaluations': False,
            'modifies_canonical_datamart': False,
            'creates_aws_resources': False,
        },
        'read_results': read_results,
        'window_read_results': window_read_results,
        'join_results': join_results,
        'sql_join_results': sql_join_results,
        'issues': issues,
        'generated_at_utc': datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    proof_output.parent.mkdir(parents=True, exist_ok=True)
    proof_output.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({
        'verdict': proof['verdict'],
        'proof_output': str(proof_output),
        'read_count': len(read_results),
        'window_read_count': len(window_read_results),
        'join_count': len(join_results),
        'sql_join_count': len(sql_join_results),
        'issues': issues,
    }, indent=2, ensure_ascii=False))
    return 0 if proof['verdict'] == 'ACCEPT' else 1


def _write_duckdb_catalog(source: Path, target: Path, dataset_ids: list[str]) -> None:
    payload = json.loads(source.read_text(encoding='utf-8'))
    work = deepcopy(payload)
    raw = work.get('datasets', work)
    if isinstance(raw, list):
        for entry in raw:
            if entry.get('dataset_id') in dataset_ids:
                _enable_duckdb(entry)
    elif isinstance(raw, dict):
        for dataset_id in dataset_ids:
            if dataset_id in raw:
                _enable_duckdb(raw[dataset_id])
    else:
        raise ValueError(f'catalog datasets must be list or object: {source}')
    target.write_text(json.dumps(work, indent=2, ensure_ascii=False), encoding='utf-8')


def _enable_duckdb(entry: dict[str, Any]) -> None:
    metadata = entry.setdefault('metadata', {})
    acceleration = metadata.setdefault('acceleration', {})
    acceleration['default_backend'] = 'duckdb'
    supported = list(dict.fromkeys([*acceleration.get('supported_backends', []), 'local_file', 'duckdb']))
    acceleration['supported_backends'] = supported


def _run_read_pair(
    reference_client: DataApiClient,
    duckdb_client: DataApiClient,
    dataset_id: str,
    start_date: str,
    end_date: str,
    fields: list[str],
) -> dict[str, Any]:
    query = DataQuery(dataset_id, start_date, end_date, 'a_share_all', fields)
    start = time.perf_counter()
    reference = reference_client.fetch(query)
    reference_seconds = time.perf_counter() - start
    start = time.perf_counter()
    accelerated = duckdb_client.fetch(query)
    duckdb_seconds = time.perf_counter() - start
    reference_validation = validate_data_api_result(reference).result
    duckdb_validation = validate_data_api_result(accelerated).result
    matches = (
        reference.status == accelerated.status
        and reference.coverage.row_count == accelerated.coverage.row_count
        and reference.coverage.date_count == accelerated.coverage.date_count
        and reference.coverage.ticker_count == accelerated.coverage.ticker_count
        and reference.coverage.duplicate_key_count == accelerated.coverage.duplicate_key_count
    )
    return {
        'dataset_id': dataset_id,
        'start_date': start_date,
        'end_date': end_date,
        'fields': list(fields),
        'reference_status': reference.status,
        'duckdb_status': accelerated.status,
        'reference_validation': reference_validation,
        'duckdb_validation': duckdb_validation,
        'reference_backend': reference.source.backend,
        'duckdb_backend': accelerated.source.backend,
        'reference_seconds': reference_seconds,
        'duckdb_seconds': duckdb_seconds,
        'row_count': accelerated.coverage.row_count,
        'date_count': accelerated.coverage.date_count,
        'ticker_count': accelerated.coverage.ticker_count,
        'duplicate_key_count': accelerated.coverage.duplicate_key_count,
        'matches_reference': matches,
    }


def _run_microcap_investability_join(reference_client: DataApiClient, duckdb_client: DataApiClient, trade_date: str) -> dict[str, Any]:
    micro_query = DataQuery('microcap_universe', trade_date, trade_date, 'a_share_all', ['universe_id', 'in_universe'])
    flags_query = DataQuery('tradability_risk_flags_daily', trade_date, trade_date, 'a_share_all', ['is_investable_core', 'is_investable_500m'])
    start = time.perf_counter()
    reference_join = _join_microcap_flags(reference_client.fetch(micro_query).frame, reference_client.fetch(flags_query).frame)
    reference_seconds = time.perf_counter() - start
    start = time.perf_counter()
    duckdb_join = _join_microcap_flags(duckdb_client.fetch(micro_query).frame, duckdb_client.fetch(flags_query).frame)
    duckdb_seconds = time.perf_counter() - start
    return {
        'query_name': 'microcap_universe_join_tradability_risk_flags_daily',
        'start_date': trade_date,
        'end_date': trade_date,
        'execution_mode': 'data_api_fetch_then_pandas_join',
        'reference_seconds': reference_seconds,
        'duckdb_seconds': duckdb_seconds,
        'reference_row_count': int(len(reference_join)),
        'duckdb_row_count': int(len(duckdb_join)),
        'reference_investable_core_rows': _true_count(reference_join, 'is_investable_core'),
        'duckdb_investable_core_rows': _true_count(duckdb_join, 'is_investable_core'),
        'matches_reference': len(reference_join) == len(duckdb_join),
    }


def _run_microcap_investability_join_sql(reference_client: DataApiClient, duckdb_client: DataApiClient, start_date: str, end_date: str) -> dict[str, Any]:
    micro_query = DataQuery('microcap_universe', start_date, end_date, 'a_share_all', ['universe_id', 'in_universe'])
    flags_query = DataQuery('tradability_risk_flags_daily', start_date, end_date, 'a_share_all', ['is_investable_core', 'is_investable_500m'])
    start = time.perf_counter()
    reference_join = _join_microcap_flags(reference_client.fetch(micro_query).frame, reference_client.fetch(flags_query).frame)
    reference_seconds = time.perf_counter() - start

    micro_entry = duckdb_client.catalog.datasets['microcap_universe']
    flags_entry = duckdb_client.catalog.datasets['tradability_risk_flags_daily']
    start = time.perf_counter()
    duckdb_summary = _duckdb_microcap_flags_join_summary(micro_entry, flags_entry, start_date, end_date)
    duckdb_seconds = time.perf_counter() - start
    reference_core = _true_count(reference_join, 'is_investable_core')
    return {
        'query_name': 'microcap_universe_join_tradability_risk_flags_daily',
        'start_date': start_date,
        'end_date': end_date,
        'execution_mode': 'single_duckdb_sql_join',
        'reference_seconds': reference_seconds,
        'duckdb_seconds': duckdb_seconds,
        'reference_row_count': int(len(reference_join)),
        'duckdb_row_count': int(duckdb_summary['row_count']),
        'reference_investable_core_rows': reference_core,
        'duckdb_investable_core_rows': int(duckdb_summary['investable_core_rows']),
        'matches_reference': len(reference_join) == int(duckdb_summary['row_count']) and reference_core == int(duckdb_summary['investable_core_rows']),
    }


def _join_microcap_flags(microcap, flags):
    return microcap.merge(flags, on=['trade_date', 'ts_code'], how='left', validate='many_to_one')


def _duckdb_microcap_flags_join_summary(micro_entry, flags_entry, start_date: str, end_date: str) -> dict[str, int]:
    import duckdb

    micro_path = _duckdb_parquet_path(micro_entry.uri)
    flags_path = _duckdb_parquet_path(flags_entry.uri)
    sql = """
        WITH micro AS (
            SELECT trade_date, ts_code, universe_id, in_universe
            FROM read_parquet(?, hive_partitioning = true)
            WHERE CAST(trade_date AS VARCHAR) >= ? AND CAST(trade_date AS VARCHAR) <= ?
        ),
        flags AS (
            SELECT trade_date, ts_code, is_investable_core, is_investable_500m
            FROM read_parquet(?, hive_partitioning = true)
            WHERE CAST(trade_date AS VARCHAR) >= ? AND CAST(trade_date AS VARCHAR) <= ?
        )
        SELECT
            count(*) AS row_count,
            sum(CASE WHEN coalesce(CAST(flags.is_investable_core AS BOOLEAN), false) THEN 1 ELSE 0 END) AS investable_core_rows
        FROM micro
        LEFT JOIN flags
        USING (trade_date, ts_code)
    """
    with duckdb.connect(database=':memory:') as con:
        row = con.execute(sql, [micro_path, start_date, end_date, flags_path, start_date, end_date]).fetchone()
    return {'row_count': int(row[0] or 0), 'investable_core_rows': int(row[1] or 0)}


def _duckdb_parquet_path(uri: str) -> str:
    path = Path(uri.removeprefix('file://')).expanduser()
    if path.is_dir():
        return str(path / '**' / '*.parquet')
    return str(path)


def _true_count(frame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    values = frame[column].map(_as_bool)
    return int(values.sum())


def _as_bool(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {'1', 'true', 't', 'yes', 'y'}


def _repo_sha() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return 'unknown'


def _is_allowed_output(path: Path) -> bool:
    resolved = path.resolve()
    allowed = [
        Path('/tmp').resolve(),
        (REPO_ROOT / 'factorforge' / 'data' / 'proofs' / 'data_acceleration').resolve(),
        (REPO_ROOT / 'factorforge' / 'data' / 'benchmarks' / 'data_acceleration').resolve(),
    ]
    return any(resolved == root or root in resolved.parents for root in allowed)


if __name__ == '__main__':
    raise SystemExit(main())
