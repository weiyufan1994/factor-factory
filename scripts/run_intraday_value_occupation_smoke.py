#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api import DataApiClient, DataQuery, validate_data_api_result  # noqa: E402
from factor_factory.data_api.value_occupation import (  # noqa: E402
    DATASET_ID,
    ValueOccupationParams,
    build_catalog_entry,
    build_qa_summary,
    derive_intraday_value_occupation_state,
    normalize_trade_date,
    write_partitioned_datamart,
)
from scripts.build_intraday_value_occupation_state import (  # noqa: E402
    discover_partition_dates,
    read_minute_root,
    read_single_parquet,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Run a bounded intraday_value_occupation_state_v1 build + catalog read smoke.')
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--minute-path')
    source.add_argument('--minute-root')
    source.add_argument('--source-catalog', help='Catalog path used to fetch minute_bar through DataApiClient.')
    ap.add_argument('--minute-dataset', default='minute_bar')
    ap.add_argument('--source-start', help='Optional source fetch start date when lookback data before --start is staged.')
    ap.add_argument('--start', default='20240102')
    ap.add_argument('--end', default='20240110')
    ap.add_argument('--dates', help='Comma-separated target trade dates. Defaults to dates in --start/--end.')
    ap.add_argument('--output-root', default='/tmp/factorforge_intraday_value_occupation_state_v1_smoke/datamart')
    ap.add_argument('--parquet-s3-uri', default='s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1_smoke')
    ap.add_argument('--catalog-output', default='/tmp/factorforge_intraday_value_occupation_state_v1_smoke/catalog.json')
    ap.add_argument('--qa-output', default='/tmp/factorforge_intraday_value_occupation_state_v1_smoke/qa.json')
    ap.add_argument('--smoke-output', default='/tmp/factorforge_intraday_value_occupation_state_v1_smoke/read_smoke.json')
    ap.add_argument('--skip-upload', action='store_true')
    ap.add_argument('--cutoff-time', default='14:50:00')
    ap.add_argument('--lookback-days', type=int, default=20)
    ap.add_argument('--min-minutes', type=int, default=20)
    ap.add_argument('--fields', nargs='*', default=['lower_support_ratio', 'upper_overhang_ratio', 'below_cost_depth'])
    return ap.parse_args()


def parse_target_dates(raw: str | None, start: str, end: str, available: list[str]) -> list[str]:
    if raw:
        return sorted({normalize_trade_date(token) for token in raw.split(',') if token.strip()})
    start_date = normalize_trade_date(start)
    end_date = normalize_trade_date(end)
    return [date for date in available if start_date <= date <= end_date]


def upload_tree(local_root: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'sync', str(local_root), s3_uri.rstrip('/'), '--only-show-errors'], check=True)


def build_smoke_catalog(catalog_path: Path, datamart_uri: str | Path, qa_output: Path, start: str, end: str) -> None:
    payload = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: build_catalog_entry(datamart_uri, qa_output, start, end),
        },
    }
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_read_smoke(catalog_path: Path, start: str, end: str, fields: list[str]) -> dict[str, object]:
    started = time.perf_counter()
    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(DATASET_ID, start, end, 'a_share_all', fields)
    )
    validation = validate_data_api_result(result)
    elapsed = time.perf_counter() - started
    return {
        'status': result.status,
        'blocked_reason': result.blocked_reason,
        'validation_result': validation.result,
        'row_count': result.coverage.row_count,
        'date_count': result.coverage.date_count,
        'ticker_count': result.coverage.ticker_count,
        'duplicate_key_count': result.coverage.duplicate_key_count,
        'columns': result.frame.columns.tolist(),
        'source_backend': result.source.backend,
        'source_uri': result.source.uri,
        'elapsed_seconds': elapsed,
    }


def read_source_catalog(catalog_path: str | Path, dataset_id: str, source_start: str, end: str) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    fields = ['trade_time', 'open', 'high', 'low', 'close', 'vol', 'amount']
    started = time.perf_counter()
    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(dataset_id, source_start, end, 'a_share_all', fields, frequency='1min')
    )
    if result.status == 'blocked':
        raise RuntimeError(f'source catalog minute read blocked: {result.blocked_reason}')
    profile = [{
        'status': result.status,
        'path': result.source.uri,
        'backend': result.source.backend,
        'minute_rows': int(len(result.frame)),
        'date_count': int(result.coverage.date_count),
        'ticker_count': int(result.coverage.ticker_count),
        'elapsed_seconds': time.perf_counter() - started,
    }]
    return result.frame, profile


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    params = ValueOccupationParams(
        lookback_days=args.lookback_days,
        cutoff_time=args.cutoff_time,
        min_minutes=args.min_minutes,
    )
    if args.source_catalog:
        source_start = normalize_trade_date(args.source_start or args.start)
        minute, source_profile = read_source_catalog(args.source_catalog, args.minute_dataset, source_start, args.end)
        available_dates = sorted(minute['trade_date'].astype(str).map(normalize_trade_date).unique().tolist())
        target_dates = parse_target_dates(args.dates, args.start, args.end, available_dates)
        missing_dates = []
    elif args.minute_path:
        minute, source_profile = read_single_parquet(Path(args.minute_path).expanduser())
        available_dates = sorted(minute['trade_date'].astype(str).map(normalize_trade_date).unique().tolist())
        target_dates = parse_target_dates(args.dates, args.start, args.end, available_dates)
        missing_dates: list[str] = []
    else:
        root = Path(args.minute_root).expanduser()
        available_dates = discover_partition_dates(root)
        target_dates = parse_target_dates(args.dates, args.start, args.end, available_dates)
        minute, source_profile, missing_dates = read_minute_root(root, target_dates, args.lookback_days)

    state = derive_intraday_value_occupation_state(minute, params, target_dates=target_dates)
    output_root = write_partitioned_datamart(state, args.output_root)
    catalog_uri: str | Path = output_root
    if not args.skip_upload:
        upload_tree(output_root, args.parquet_s3_uri)
        catalog_uri = args.parquet_s3_uri

    catalog_output = Path(args.catalog_output).expanduser()
    qa_output = Path(args.qa_output).expanduser()
    smoke_output = Path(args.smoke_output).expanduser()
    build_smoke_catalog(catalog_output, catalog_uri, qa_output, args.start, args.end)
    qa = build_qa_summary(
        state,
        params=params,
        source_min_trade_date=min(available_dates) if available_dates else None,
        source_max_trade_date=max(available_dates) if available_dates else None,
        missing_dates=missing_dates,
        output_path=output_root,
        catalog_path=catalog_output,
        runtime_seconds=time.perf_counter() - started,
        input_minute_row_count=int(len(minute)),
        source_profile=source_profile,
    )
    qa['local_output_path'] = str(output_root)
    qa['catalog_uri'] = str(catalog_uri)
    qa['parquet_s3_uri'] = None if args.skip_upload else args.parquet_s3_uri
    qa_output.parent.mkdir(parents=True, exist_ok=True)
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    read_smoke = run_read_smoke(catalog_output, args.start, args.end, args.fields)
    summary = {
        'verdict': 'ACCEPT' if qa['verdict'] == 'ACCEPT' and read_smoke['status'] == 'ready' and read_smoke['validation_result'] == 'PASS' else 'BLOCK',
        'dataset_id': DATASET_ID,
        'qa_output': str(qa_output),
        'catalog_output': str(catalog_output),
        'smoke_output': str(smoke_output),
        'catalog_uri': str(catalog_uri),
        'parquet_s3_uri': None if args.skip_upload else args.parquet_s3_uri,
        'read_smoke': read_smoke,
    }
    smoke_output.parent.mkdir(parents=True, exist_ok=True)
    smoke_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
