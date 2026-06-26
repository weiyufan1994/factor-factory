#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.flow_distribution_moments import PREPARED_MINUTE_COLUMNS, normalize_trade_date, prepare_minute_frame, utc_now  # noqa: E402


RAW_COLUMNS = ['ts_code', 'trade_date', 'trade_time', 'bar_time', 'open', 'close', 'vol', 'amount']
DATASET_ID = 'prepared_minute_bar_v1'
SOURCE_DATASET = 'minute_bar'
SCHEMA_VERSION = 'prepared_minute_bar_v1_p0'
PRODUCER_VERSION = 'factorforge_data_api_prepared_minute_bar_20260616'
UNIQUE_KEY = ['ts_code', 'trade_date', 'hhmmss']
SORT_KEYS = ['trade_date', 'ts_code', 'hhmmss']


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build prepared minute_bar partitions for fast intraday state kernels.')
    parser.add_argument('--minute-root', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--dates', help='Comma-separated target dates. Overrides --start/--end.')
    parser.add_argument('--qa-output', help='Optional QA json output path.')
    parser.add_argument('--catalog-output', help='Optional standalone Data API catalog json output path.')
    parser.add_argument('--manifest-output', help='Optional resumable backfill manifest json output path.')
    parser.add_argument('--max-dates', type=int, help='Process at most this many non-skipped dates in this run.')
    parser.add_argument('--skip-existing', action='store_true', help='Skip target partitions that already contain part.parquet.')
    parser.add_argument('--source-ready-only', action='store_true', help='Only process source partitions that contain parquet data files.')
    return parser.parse_args()


def discover_partition_dates(root: Path) -> list[str]:
    dates: list[str] = []
    for path in root.glob('trade_date=*'):
        if path.is_dir():
            dates.append(normalize_trade_date(path.name.split('=', 1)[1]))
    return sorted(set(dates))


def partition_has_parquet_data(path: Path) -> bool:
    return any(child.is_file() and child.suffix == '.parquet' for child in path.iterdir())


def discover_source_ready_status(root: Path) -> dict[str, bool]:
    statuses: dict[str, bool] = {}
    for path in root.glob('trade_date=*'):
        if path.is_dir():
            trade_date = normalize_trade_date(path.name.split('=', 1)[1])
            statuses[trade_date] = partition_has_parquet_data(path)
    return statuses


def select_dates(args: argparse.Namespace, available: list[str]) -> list[str]:
    if args.dates:
        return sorted({normalize_trade_date(item) for item in args.dates.split(',') if item.strip()})
    if not available:
        return []
    start = normalize_trade_date(args.start or available[0])
    end = normalize_trade_date(args.end or available[-1])
    return [date for date in available if start <= date <= end]


def filter_source_ready_dates(requested_dates: list[str], statuses: dict[str, bool]) -> tuple[list[str], list[str]]:
    ready_dates: list[str] = []
    not_ready_dates: list[str] = []
    for trade_date in requested_dates:
        if trade_date in statuses and not statuses[trade_date]:
            not_ready_dates.append(trade_date)
            continue
        ready_dates.append(trade_date)
    return ready_dates, not_ready_dates


def _empty_null_counts() -> dict[str, int]:
    return {col: 0 for col in PREPARED_MINUTE_COLUMNS}


def _empty_finite_counts() -> dict[str, int]:
    return {col: 0 for col in ['hhmmss', 'amount_abs', 'minute_ret', 'signed_amount', 'vol']}


def build_catalog_entry(output_root: str | Path, qa_output: str | Path | None, start_date: str | None, end_date: str | None) -> dict[str, Any]:
    uri = str(output_root) if str(output_root).startswith('s3://') else str(Path(output_root).expanduser())
    return {
        'uri': uri,
        'format': 'parquet',
        'storage': 's3' if uri.startswith('s3://') else 'local',
        'description': 'Prepared minute_bar cache with normalized time key, absolute amount, minute return, and signed amount for fast intraday state kernels.',
        'columns': PREPARED_MINUTE_COLUMNS,
        'partition_columns': ['trade_date'],
        'date_column': 'trade_date',
        'symbol_column': 'ts_code',
        'metadata': {
            'source_dataset': SOURCE_DATASET,
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'unique_key': UNIQUE_KEY,
            'sort_keys': SORT_KEYS,
            'partition_column': 'trade_date',
            'field_boundary': 'prepared_raw_state_only_no_alpha_scores',
            'derived_columns': {
                'hhmmss': 'normalized integer minute timestamp from trade_time/bar_time',
                'amount_abs': 'abs(amount)',
                'minute_ret': 'close/open - 1',
                'signed_amount': 'sign(close-open)*abs(amount)',
            },
            'information_set_legality': 'per-minute transformation only; no cross-date fitting or future minutes are introduced',
            'no_future_intraday_minutes': True,
            'replacement_policy': 'opt_in_until_full_worker_qa_and_research_parity_accept',
            'qa_summary_path': str(Path(qa_output).expanduser()) if qa_output else '',
        },
        'freshness': {
            'trade_date_min': normalize_trade_date(start_date) if start_date else None,
            'trade_date_max': normalize_trade_date(end_date) if end_date else None,
        },
    }


def write_catalog(path: Path, output_root: Path, qa_output: Path | None, start_date: str | None, end_date: str | None) -> None:
    payload = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: build_catalog_entry(output_root, qa_output, start_date, end_date),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build_qa_summary(
    *,
    output_root: Path,
    catalog_output: Path | None,
    target_dates: list[str],
    partitions: list[dict[str, Any]],
    missing_dates: list[str],
    read_errors: list[dict[str, Any]],
    source_not_ready_dates: list[str],
    runtime_seconds: float,
    null_counts: dict[str, int],
    finite_counts: dict[str, int],
    numeric_counts: dict[str, int],
    duplicate_key_count: int,
) -> dict[str, Any]:
    row_count = int(sum(item['row_count'] for item in partitions))
    date_count = len(partitions)
    ticker_count = int(len({ticker for item in partitions for ticker in item.get('tickers', [])}))
    null_ratio = {col: (float(count) / row_count if row_count else 0.0) for col, count in null_counts.items()}
    finite_ratio = {
        col: (float(finite_counts.get(col, 0)) / numeric_counts[col] if numeric_counts.get(col, 0) else 0.0)
        for col in numeric_counts
    }
    output_dates = [item['trade_date'] for item in partitions]
    hard_checks = {
        'row_count_nonzero': row_count > 0,
        'date_count_matches_requested_minus_missing': date_count == max(len(target_dates) - len(set(missing_dates)), 0),
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'schema_columns_match': all(item.get('columns') == PREPARED_MINUTE_COLUMNS for item in partitions) if partitions else False,
        'missing_dates_empty': not missing_dates,
        'read_errors_empty': not read_errors,
    }
    verdict = 'ACCEPT' if all(hard_checks.values()) else 'BLOCK'
    return {
        'verdict': verdict,
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'output_root': str(output_root),
        'catalog_path': str(catalog_output) if catalog_output else '',
        'requested_dates': target_dates,
        'missing_dates': sorted(set(missing_dates)),
        'source_not_ready_dates': sorted(set(source_not_ready_dates)),
        'output_min_trade_date': min(output_dates) if output_dates else None,
        'output_max_trade_date': max(output_dates) if output_dates else None,
        'date_count': date_count,
        'requested_date_count': len(target_dates),
        'row_count': row_count,
        'ticker_count': ticker_count,
        'duplicate_key_count': int(duplicate_key_count),
        'unique_key': UNIQUE_KEY,
        'columns': PREPARED_MINUTE_COLUMNS,
        'partition_column': 'trade_date',
        'null_ratio_by_field': null_ratio,
        'finite_ratio_by_numeric_field': finite_ratio,
        'hard_checks': hard_checks,
        'coverage_by_date': {item['trade_date']: int(item['ticker_count']) for item in partitions},
        'partitions': [
            {key: value for key, value in item.items() if key != 'tickers'}
            for item in partitions
        ],
        'read_errors': read_errors,
        'runtime_seconds': float(runtime_seconds),
        'no_future_intraday_minutes': True,
        'information_set_legality': 'per-minute transformation only; no full-day threshold, cross-date fitting, or alpha label is computed',
        'generated_at_utc': utc_now(),
    }


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    args = parse_args()
    raw_root = Path(args.minute_root).expanduser()
    output_root = Path(args.output_root).expanduser()
    available = discover_partition_dates(raw_root)
    requested_dates = select_dates(args, available)
    source_not_ready_dates: list[str] = []
    if args.source_ready_only:
        requested_dates, source_not_ready_dates = filter_source_ready_dates(
            requested_dates,
            discover_source_ready_status(raw_root),
        )
    skipped_existing: list[dict[str, Any]] = []
    candidate_dates: list[str] = []
    for trade_date in requested_dates:
        part_file = output_root / f'trade_date={trade_date}' / 'part.parquet'
        if args.skip_existing and part_file.exists():
            skipped_existing.append({
                'trade_date': trade_date,
                'output_path': str(part_file),
                'status': 'skipped_existing',
            })
        else:
            candidate_dates.append(trade_date)
    if args.max_dates is not None and args.max_dates < 0:
        raise ValueError('--max-dates must be non-negative')
    target_dates = candidate_dates[:args.max_dates] if args.max_dates is not None else candidate_dates
    remaining_dates = candidate_dates[len(target_dates):]
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    read_errors: list[dict[str, Any]] = []
    null_counts = _empty_null_counts()
    finite_counts = _empty_finite_counts()
    numeric_counts = _empty_finite_counts()
    duplicate_key_count = 0
    for trade_date in target_dates:
        source = raw_root / f'trade_date={trade_date}'
        target_dir = output_root / f'trade_date={trade_date}'
        if not source.exists():
            missing_dates.append(trade_date)
            read_errors.append({'trade_date': trade_date, 'source_path': str(source), 'status': 'missing_source_partition'})
            continue
        try:
            frame = pd.read_parquet(source)
        except Exception as exc:
            missing_dates.append(trade_date)
            read_errors.append({'trade_date': trade_date, 'source_path': str(source), 'status': 'read_error', 'error': str(exc)})
            continue
        keep = [col for col in RAW_COLUMNS if col in frame.columns]
        try:
            prepared = prepare_minute_frame(frame[keep])
        except Exception as exc:
            missing_dates.append(trade_date)
            read_errors.append({'trade_date': trade_date, 'source_path': str(source), 'status': 'prepare_error', 'error': str(exc)})
            continue
        prepared = prepared[PREPARED_MINUTE_COLUMNS].sort_values(SORT_KEYS).reset_index(drop=True)
        duplicate_key_count += int(prepared.duplicated(UNIQUE_KEY).sum())
        for col in PREPARED_MINUTE_COLUMNS:
            null_counts[col] += int(prepared[col].isna().sum())
        for col in finite_counts:
            numeric = pd.to_numeric(prepared[col], errors='coerce')
            numeric_counts[col] += int(numeric.notna().sum())
            finite_counts[col] += int(np.isfinite(numeric).sum())
        target_dir.mkdir(parents=True, exist_ok=True)
        prepared.to_parquet(target_dir / 'part.parquet', index=False)
        rows.append({
            'trade_date': trade_date,
            'source_path': str(source),
            'output_path': str(target_dir / 'part.parquet'),
            'row_count': int(len(prepared)),
            'ticker_count': int(prepared['ts_code'].nunique()) if not prepared.empty else 0,
            'columns': PREPARED_MINUTE_COLUMNS,
            'tickers': sorted(prepared['ts_code'].dropna().astype(str).unique().tolist()),
        })
    runtime_seconds = float(time.perf_counter() - started)
    qa_output = Path(args.qa_output).expanduser() if args.qa_output else None
    catalog_output = Path(args.catalog_output).expanduser() if args.catalog_output else None
    manifest_output = Path(args.manifest_output).expanduser() if args.manifest_output else None
    qa = build_qa_summary(
        output_root=output_root,
        catalog_output=catalog_output,
        target_dates=target_dates,
        partitions=rows,
        missing_dates=missing_dates,
        read_errors=read_errors,
        source_not_ready_dates=source_not_ready_dates,
        runtime_seconds=runtime_seconds,
        null_counts=null_counts,
        finite_counts=finite_counts,
        numeric_counts=numeric_counts,
        duplicate_key_count=duplicate_key_count,
    )
    if qa_output:
        qa_output.parent.mkdir(parents=True, exist_ok=True)
        qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if catalog_output:
        start_date = qa['output_min_trade_date'] or (target_dates[0] if target_dates else None)
        end_date = qa['output_max_trade_date'] or (target_dates[-1] if target_dates else None)
        write_catalog(catalog_output, output_root, qa_output, start_date, end_date)
    manifest = {
        'verdict': qa['verdict'],
        'dataset_id': DATASET_ID,
        'source_dataset': SOURCE_DATASET,
        'output_root': str(output_root),
        'qa_output': str(qa_output) if qa_output else '',
        'catalog_output': str(catalog_output) if catalog_output else '',
        'manifest_output': str(manifest_output) if manifest_output else '',
        'requested_dates': requested_dates,
        'target_dates': target_dates,
        'processed_dates': [item['trade_date'] for item in rows],
        'skipped_dates': [item['trade_date'] for item in skipped_existing],
        'remaining_dates': remaining_dates,
        'missing_dates': qa['missing_dates'],
        'source_ready_policy': {
            'enabled': bool(args.source_ready_only),
            'not_ready_dates': source_not_ready_dates,
        },
        'read_errors': read_errors,
        'resume_policy': {
            'skip_existing': bool(args.skip_existing),
            'max_dates': args.max_dates,
            'partition_success_marker': 'part.parquet',
        },
        'row_count': qa['row_count'],
        'date_count': qa['date_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'runtime_seconds': runtime_seconds,
        'generated_at_utc': utc_now(),
    }
    if manifest_output:
        write_manifest(manifest_output, manifest)
    summary = {
        'verdict': qa['verdict'],
        'dataset_id': DATASET_ID,
        'source_dataset': SOURCE_DATASET,
        'output_root': str(output_root),
        'qa_output': str(qa_output) if qa_output else '',
        'catalog_output': str(catalog_output) if catalog_output else '',
        'manifest_output': str(manifest_output) if manifest_output else '',
        'date_count': len(rows),
        'requested_date_count': len(target_dates),
        'row_count': qa['row_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'missing_dates': qa['missing_dates'],
        'source_not_ready_dates': source_not_ready_dates,
        'processed_dates': manifest['processed_dates'],
        'skipped_dates': manifest['skipped_dates'],
        'remaining_dates': remaining_dates,
        'skipped_date_count': len(skipped_existing),
        'runtime_seconds': runtime_seconds,
        'dates': target_dates,
        'partitions': qa['partitions'],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
