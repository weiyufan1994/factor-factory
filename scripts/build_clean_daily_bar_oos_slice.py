#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from factor_factory.data_api import DataApiClient, DataQuery, validate_data_api_result  # noqa: E402
except ModuleNotFoundError:  # Worker-only fallback; QA still reads the produced parquet with pyarrow.
    DataApiClient = None  # type: ignore[assignment]
    DataQuery = None  # type: ignore[assignment]
    validate_data_api_result = None  # type: ignore[assignment]


DATASET_ID = 'clean_daily_bar_oos_slice'
SCHEMA_VERSION = 'clean_daily_bar_oos_slice_v1'
SOURCE_DATASET = 'clean_daily_bar/v1'
DEFAULT_SOURCE_S3 = 's3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet'
DEFAULT_OUTPUT_S3 = 's3://yufan-data-lake/factorforge/research_datamart/clean_daily_bar_oos_slice/v1'
DEFAULT_PROOF_S3 = 's3://yufan-data-lake/factorforge/proofs/clean_daily_bar_oos_slice/v1'
UNIQUE_KEY = ['trade_date', 'ts_code']
REQUIRED_COLUMNS = [
    'ts_code',
    'trade_date',
    'open',
    'high',
    'low',
    'close',
    'pre_close',
    'pct_chg',
    'amount',
    'vol',
    'turnover_rate',
    'turnover_rate_f',
    'volume_ratio',
    'total_mv',
    'circ_mv',
    'free_float_mcap',
    'ln_mcap_free',
    'ln_total_mv',
    'ln_circ_mv',
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build clean_daily_bar_oos_slice from latest clean_daily_bar parquet.')
    ap.add_argument('--source-parquet', required=True)
    ap.add_argument('--source-s3', default=DEFAULT_SOURCE_S3)
    ap.add_argument('--start', default='20250601')
    ap.add_argument('--end', default='20260612')
    ap.add_argument('--output-root', default='/tmp/clean_daily_bar_oos_slice_v1')
    ap.add_argument('--output-s3', default=DEFAULT_OUTPUT_S3)
    ap.add_argument('--proof-output', default='/tmp/clean_daily_bar_oos_slice_v1/proof.json')
    ap.add_argument('--catalog-output', default='/tmp/clean_daily_bar_oos_slice_v1/catalog.json')
    ap.add_argument('--proof-s3-prefix', default=DEFAULT_PROOF_S3)
    ap.add_argument('--skip-upload', action='store_true')
    return ap.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '').replace('.0', '')
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'invalid trade_date: {value!r}')
    return parsed.strftime('%Y%m%d')


def upload_tree(local_root: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'cp', str(local_root), s3_uri.rstrip('/'), '--recursive', '--only-show-errors'], check=True)


def upload_file(local_path: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'cp', str(local_path), s3_uri, '--only-show-errors'], check=True)


def read_slice(source_parquet: Path, start: str, end: str) -> pd.DataFrame:
    dataset = ds.dataset(str(source_parquet), format='parquet')
    schema_columns = set(dataset.schema.names)
    missing = sorted(set(REQUIRED_COLUMNS) - schema_columns)
    if missing:
        raise ValueError(f'source missing required columns: {missing}')
    table = dataset.to_table(
        columns=REQUIRED_COLUMNS,
        filter=(ds.field('trade_date') >= start) & (ds.field('trade_date') <= end),
    )
    frame = table.to_pandas()
    if frame.empty:
        return frame
    frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
    frame = frame[(frame['trade_date'] >= start) & (frame['trade_date'] <= end)]
    return frame.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)


def write_partitioned(frame: pd.DataFrame, output_root: Path) -> Path:
    if output_root.exists():
        for part in output_root.glob('trade_date=*/*.parquet'):
            part.unlink()
    output_root.mkdir(parents=True, exist_ok=True)
    for trade_date, group in frame.groupby('trade_date', sort=True, observed=True):
        part_dir = output_root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True, exist_ok=True)
        group.drop(columns=['trade_date']).to_parquet(part_dir / 'part-000.parquet', index=False)
    return output_root


def build_catalog(output_uri: str, proof_uri: str | Path, start: str, end: str) -> dict[str, Any]:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: {
                'uri': output_uri,
                'format': 'parquet',
                'version': 'v1',
                'storage': 's3' if output_uri.startswith('s3://') else 'local',
                'description': 'Fixed OOS daily clean bar slice for V18 incremental research.',
                'columns': REQUIRED_COLUMNS,
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'qlib_field_map': {
                    '$open': 'open',
                    '$high': 'high',
                    '$low': 'low',
                    '$close': 'close',
                    '$volume': 'vol',
                    '$amount': 'amount',
                    '$ret': 'pct_chg',
                    '$turnover': 'turnover_rate',
                    '$market_cap': 'total_mv',
                },
                'freshness': {
                    'trade_date_min': start,
                    'trade_date_max': end,
                },
                'metadata': {
                    'source_dataset': SOURCE_DATASET,
                    'source_s3': DEFAULT_SOURCE_S3,
                    'schema_version': SCHEMA_VERSION,
                    'unique_key': UNIQUE_KEY,
                    'sort_keys': UNIQUE_KEY,
                    'qa_summary_path': str(proof_uri),
                    'research_scope': 'fixed_oos_slice_for_v18_incremental_eval',
                },
            },
        },
    }


def run_read_smoke(catalog_path: Path, output_root: Path, start: str, end: str) -> dict[str, Any]:
    sample_start = max(start, '20260610')
    sample_end = min(end, '20260612')
    fields = ['close', 'pre_close', 'pct_chg', 'amount', 'turnover_rate', 'total_mv', 'ln_total_mv']
    started = time.perf_counter()
    if DataApiClient is None:
        dataset = ds.dataset(str(output_root), format='parquet', partitioning='hive')
        partition_type = dataset.schema.field('trade_date').type if 'trade_date' in dataset.schema.names else None
        if partition_type is not None and str(partition_type).startswith('int'):
            lower: Any = int(sample_start)
            upper: Any = int(sample_end)
        else:
            lower = sample_start
            upper = sample_end
        table = dataset.to_table(
            columns=['ts_code', 'trade_date', *fields],
            filter=(ds.field('trade_date') >= lower) & (ds.field('trade_date') <= upper),
        )
        frame = table.to_pandas()
        if 'trade_date' in frame:
            frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        duplicate_key_count = int(frame.duplicated(['trade_date', 'ts_code']).sum()) if not frame.empty else 0
        return {
            'status': 'PASS' if not frame.empty and duplicate_key_count == 0 else 'FAIL',
            'data_api_status': 'pyarrow_worker_fallback',
            'validation_result': 'PASS' if not frame.empty and duplicate_key_count == 0 else 'FAIL',
            'sample_dates': [sample_start, sample_end],
            'row_count': int(len(frame)),
            'date_count': int(frame['trade_date'].nunique()) if 'trade_date' in frame else 0,
            'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame else 0,
            'duplicate_key_count': duplicate_key_count,
            'columns': frame.columns.tolist(),
            'elapsed_seconds': time.perf_counter() - started,
        }
    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(DATASET_ID, sample_start, sample_end, 'a_share_all', fields)
    )
    validation = validate_data_api_result(result)
    return {
        'status': 'PASS' if result.status == 'ready' and validation.result == 'PASS' and result.coverage.row_count > 0 else 'FAIL',
        'data_api_status': result.status,
        'validation_result': validation.result,
        'sample_dates': [sample_start, sample_end],
        'row_count': result.coverage.row_count,
        'date_count': result.coverage.date_count,
        'ticker_count': result.coverage.ticker_count,
        'duplicate_key_count': result.coverage.duplicate_key_count,
        'columns': result.frame.columns.tolist(),
        'elapsed_seconds': time.perf_counter() - started,
    }


def build_proof(
    frame: pd.DataFrame,
    *,
    args: argparse.Namespace,
    output_uri: str,
    read_smoke: dict[str, Any],
    runtime_seconds: float,
) -> dict[str, Any]:
    missing_required = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if not frame.empty else 0
    dates = sorted(frame['trade_date'].astype(str).unique().tolist()) if not frame.empty else []
    null_ratio = {col: float(frame[col].isna().mean()) for col in REQUIRED_COLUMNS if col in frame.columns}
    finite_ratio = {
        col: float(np.isfinite(pd.to_numeric(frame[col], errors='coerce')).mean())
        for col in REQUIRED_COLUMNS
        if col in frame.columns and col not in {'ts_code', 'trade_date'}
    }
    coverage_by_date = frame.groupby('trade_date')['ts_code'].nunique().astype(int).to_dict() if not frame.empty else {}
    hard_checks = {
        'row_count_positive': len(frame) > 0,
        'missing_required_columns_empty': not missing_required,
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'output_max_trade_date_gte_requested': bool(dates and max(dates) >= args.end),
        'read_smoke_pass': read_smoke.get('status') == 'PASS',
    }
    return {
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'source_dataset': SOURCE_DATASET,
        'source_s3': args.source_s3,
        'output_s3': output_uri,
        'requested_min_trade_date': args.start,
        'requested_max_trade_date': args.end,
        'output_min_trade_date': min(dates) if dates else None,
        'output_max_trade_date': max(dates) if dates else None,
        'date_count': len(dates),
        'row_count': int(len(frame)),
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame else 0,
        'duplicate_key_count': duplicate_key_count,
        'missing_required_columns': missing_required,
        'null_ratio_by_required_column': null_ratio,
        'finite_ratio_by_numeric_column': finite_ratio,
        'coverage_by_date_tail': {date: coverage_by_date[date] for date in dates[-5:]},
        'read_smoke': read_smoke,
        'hard_checks': hard_checks,
        'runtime_seconds': runtime_seconds,
        'generated_at_utc': utc_now(),
        'verdict': 'ACCEPT' if all(hard_checks.values()) else 'BLOCK',
    }


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    source_parquet = Path(args.source_parquet).expanduser()
    output_root = Path(args.output_root).expanduser()
    proof_output = Path(args.proof_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()

    frame = read_slice(source_parquet, args.start, args.end)
    write_partitioned(frame, output_root)
    output_uri = str(output_root) if args.skip_upload else args.output_s3.rstrip('/')
    proof_uri = str(proof_output) if args.skip_upload else f'{args.proof_s3_prefix.rstrip()}/proof.json'
    catalog_payload = build_catalog(output_uri, proof_uri, args.start, args.end)
    catalog_output.parent.mkdir(parents=True, exist_ok=True)
    catalog_output.write_text(json.dumps(catalog_payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    if not args.skip_upload:
        upload_tree(output_root, args.output_s3)
        upload_file(catalog_output, f'{args.proof_s3_prefix.rstrip()}/catalog.json')

    read_smoke = run_read_smoke(catalog_output, output_root, args.start, args.end)
    proof = build_proof(
        frame,
        args=args,
        output_uri=output_uri,
        read_smoke=read_smoke,
        runtime_seconds=time.perf_counter() - started,
    )
    proof_output.parent.mkdir(parents=True, exist_ok=True)
    proof_output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not args.skip_upload:
        upload_file(proof_output, proof_uri)
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
