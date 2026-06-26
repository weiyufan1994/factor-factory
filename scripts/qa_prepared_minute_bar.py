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

from factor_factory.data_api import DataApiClient, DataQuery  # noqa: E402
from factor_factory.data_api.flow_distribution_moments import PREPARED_MINUTE_COLUMNS, normalize_trade_date, utc_now  # noqa: E402
from scripts.build_prepared_minute_bar import (  # noqa: E402
    DATASET_ID,
    SOURCE_DATASET,
    UNIQUE_KEY,
    discover_partition_dates,
    discover_source_ready_status,
    filter_source_ready_dates,
    write_catalog,
)


NUMERIC_COLUMNS = ['hhmmss', 'amount_abs', 'minute_ret', 'signed_amount', 'vol']


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='QA existing prepared_minute_bar_v1 partitions without building data.')
    parser.add_argument('--source-minute-root', required=True, help='Raw minute_bar root used only for expected date coverage.')
    parser.add_argument('--prepared-root', required=True, help='Prepared minute_bar root to validate.')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--read-smoke-output', help='Optional DataApiClient read-smoke json output path.')
    parser.add_argument('--source-ready-only', action='store_true', help='Only validate dates whose source partitions contain parquet data files.')
    return parser.parse_args()


def dates_in_range(root: Path, start: str, end: str, *, source_ready_only: bool) -> tuple[list[str], list[str]]:
    start_date = normalize_trade_date(start)
    end_date = normalize_trade_date(end)
    requested_dates = [date for date in discover_partition_dates(root) if start_date <= date <= end_date]
    if not source_ready_only:
        return requested_dates, []
    return filter_source_ready_dates(requested_dates, discover_source_ready_status(root))


def _empty_counts() -> dict[str, int]:
    return {column: 0 for column in PREPARED_MINUTE_COLUMNS}


def _empty_numeric_counts() -> dict[str, int]:
    return {column: 0 for column in NUMERIC_COLUMNS}


def scan_prepared_root(prepared_root: Path, expected_dates: list[str]) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], dict[str, int], dict[str, int], dict[str, int], int]:
    partitions: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    read_errors: list[dict[str, Any]] = []
    null_counts = _empty_counts()
    finite_counts = _empty_numeric_counts()
    numeric_counts = _empty_numeric_counts()
    duplicate_key_count = 0
    for trade_date in expected_dates:
        part_dir = prepared_root / f'trade_date={trade_date}'
        if not part_dir.exists():
            missing_dates.append(trade_date)
            read_errors.append({'trade_date': trade_date, 'status': 'missing_partition', 'path': str(part_dir)})
            continue
        try:
            frame = pd.read_parquet(part_dir)
        except Exception as exc:  # noqa: BLE001
            missing_dates.append(trade_date)
            read_errors.append({'trade_date': trade_date, 'status': 'read_error', 'path': str(part_dir), 'error': str(exc)})
            continue
        missing_columns = [column for column in PREPARED_MINUTE_COLUMNS if column not in frame.columns]
        if missing_columns:
            read_errors.append({'trade_date': trade_date, 'status': 'schema_error', 'path': str(part_dir), 'missing_columns': missing_columns})
        normalized = frame.copy()
        if 'trade_date' in normalized.columns:
            normalized['trade_date'] = normalized['trade_date'].map(normalize_trade_date)
        key_columns_present = all(column in normalized.columns for column in UNIQUE_KEY)
        duplicate_count = int(normalized.duplicated(UNIQUE_KEY).sum()) if key_columns_present else 0
        duplicate_key_count += duplicate_count
        for column in PREPARED_MINUTE_COLUMNS:
            if column in normalized.columns:
                null_counts[column] += int(normalized[column].isna().sum())
            else:
                null_counts[column] += int(len(normalized))
        for column in NUMERIC_COLUMNS:
            if column in normalized.columns:
                numeric = pd.to_numeric(normalized[column], errors='coerce')
                numeric_counts[column] += int(numeric.notna().sum())
                finite_counts[column] += int(np.isfinite(numeric).sum())
        partitions.append({
            'trade_date': trade_date,
            'path': str(part_dir),
            'row_count': int(len(normalized)),
            'ticker_count': int(normalized['ts_code'].nunique()) if 'ts_code' in normalized.columns and not normalized.empty else 0,
            'columns': [column for column in PREPARED_MINUTE_COLUMNS if column in normalized.columns],
            'missing_columns': missing_columns,
            'duplicate_key_count': duplicate_count,
        })
    return partitions, missing_dates, read_errors, null_counts, finite_counts, numeric_counts, duplicate_key_count


def run_read_smoke(
    catalog_output: Path,
    start: str,
    end: str,
    output_path: Path,
    *,
    expected_dates: list[str],
    source_not_ready_dates: list[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    result = DataApiClient.from_catalog(catalog_output).fetch(
        DataQuery(
            DATASET_ID,
            normalize_trade_date(start),
            normalize_trade_date(end),
            'a_share_all',
            ['ts_code', 'trade_date', 'hhmmss', 'amount_abs'],
        )
    )
    elapsed = time.perf_counter() - started
    frame = result.frame
    manual_duplicate = int(frame.duplicated(UNIQUE_KEY).sum()) if not frame.empty and all(column in frame.columns for column in UNIQUE_KEY) else 0
    observed_dates = sorted(frame['trade_date'].astype(str).unique().tolist()) if 'trade_date' in frame.columns and not frame.empty else []
    missing_ready_dates = sorted(set(expected_dates) - set(observed_dates))
    unexpected_dates = sorted(set(observed_dates) - set(expected_dates))
    payload = {
        'verdict': 'ACCEPT'
        if (
            result.status == 'ready'
            and len(frame) > 0
            and result.coverage.duplicate_key_count == 0
            and manual_duplicate == 0
            and not missing_ready_dates
            and not unexpected_dates
        )
        else 'BLOCK',
        'dataset_id': DATASET_ID,
        'status': result.status,
        'blocked_reason': result.blocked_reason,
        'row_count': int(len(frame)),
        'date_count': int(result.coverage.date_count),
        'expected_dates': expected_dates,
        'observed_dates': observed_dates,
        'source_not_ready_dates': source_not_ready_dates,
        'missing_ready_dates': missing_ready_dates,
        'unexpected_dates': unexpected_dates,
        'ticker_count': int(result.coverage.ticker_count),
        'coverage_duplicate_key_count': int(result.coverage.duplicate_key_count),
        'manual_duplicate_key_count': manual_duplicate,
        'elapsed_seconds': float(elapsed),
        'catalog_path': str(catalog_output),
        'columns': list(frame.columns),
        'generated_at_utc': utc_now(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return payload


def build_qa(
    *,
    prepared_root: Path,
    source_root: Path,
    catalog_output: Path,
    expected_dates: list[str],
    source_not_ready_dates: list[str],
    partitions: list[dict[str, Any]],
    missing_dates: list[str],
    read_errors: list[dict[str, Any]],
    null_counts: dict[str, int],
    finite_counts: dict[str, int],
    numeric_counts: dict[str, int],
    duplicate_key_count: int,
    runtime_seconds: float,
    read_smoke: dict[str, Any] | None,
) -> dict[str, Any]:
    row_count = int(sum(item['row_count'] for item in partitions))
    prepared_dates = [item['trade_date'] for item in partitions]
    schema_ok = bool(partitions) and all(item['columns'] == PREPARED_MINUTE_COLUMNS and not item['missing_columns'] for item in partitions)
    hard_checks = {
        'row_count_nonzero': row_count > 0,
        'date_coverage_complete': expected_dates == prepared_dates and not missing_dates,
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'schema_columns_match': schema_ok,
        'read_errors_empty': not read_errors,
        'read_smoke_accept': read_smoke is None or read_smoke.get('verdict') == 'ACCEPT',
    }
    null_ratio = {column: (float(count) / row_count if row_count else 0.0) for column, count in null_counts.items()}
    finite_ratio = {
        column: (float(finite_counts[column]) / numeric_counts[column] if numeric_counts[column] else 0.0)
        for column in numeric_counts
    }
    return {
        'verdict': 'ACCEPT' if all(hard_checks.values()) else 'BLOCK',
        'dataset_id': DATASET_ID,
        'source_dataset': SOURCE_DATASET,
        'prepared_root': str(prepared_root),
        'source_minute_root': str(source_root),
        'catalog_path': str(catalog_output),
        'expected_dates': expected_dates,
        'source_not_ready_dates': source_not_ready_dates,
        'prepared_dates': prepared_dates,
        'missing_dates': sorted(set(missing_dates)),
        'output_min_trade_date': min(prepared_dates) if prepared_dates else None,
        'output_max_trade_date': max(prepared_dates) if prepared_dates else None,
        'date_count': len(prepared_dates),
        'expected_date_count': len(expected_dates),
        'row_count': row_count,
        'ticker_count': int(max((item['ticker_count'] for item in partitions), default=0)),
        'duplicate_key_count': int(duplicate_key_count),
        'unique_key': UNIQUE_KEY,
        'columns': PREPARED_MINUTE_COLUMNS,
        'hard_checks': hard_checks,
        'null_ratio_by_field': null_ratio,
        'finite_ratio_by_numeric_field': finite_ratio,
        'coverage_by_date': {item['trade_date']: int(item['row_count']) for item in partitions},
        'partitions': partitions,
        'read_errors': read_errors,
        'read_smoke': read_smoke or {},
        'runtime_seconds': float(runtime_seconds),
        'generated_at_utc': utc_now(),
    }


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    source_root = Path(args.source_minute_root).expanduser()
    prepared_root = Path(args.prepared_root).expanduser()
    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()
    expected_dates, source_not_ready_dates = dates_in_range(
        source_root,
        args.start,
        args.end,
        source_ready_only=bool(args.source_ready_only),
    )
    partitions, missing_dates, read_errors, null_counts, finite_counts, numeric_counts, duplicate_key_count = scan_prepared_root(prepared_root, expected_dates)
    start_date = min(expected_dates) if expected_dates else normalize_trade_date(args.start)
    end_date = max(expected_dates) if expected_dates else normalize_trade_date(args.end)
    write_catalog(catalog_output, prepared_root, qa_output, start_date, end_date)
    read_smoke = None
    if args.read_smoke_output:
        read_smoke = run_read_smoke(
            catalog_output,
            args.start,
            args.end,
            Path(args.read_smoke_output).expanduser(),
            expected_dates=expected_dates,
            source_not_ready_dates=source_not_ready_dates,
        )
    qa = build_qa(
        prepared_root=prepared_root,
        source_root=source_root,
        catalog_output=catalog_output,
        expected_dates=expected_dates,
        source_not_ready_dates=source_not_ready_dates,
        partitions=partitions,
        missing_dates=missing_dates,
        read_errors=read_errors,
        null_counts=null_counts,
        finite_counts=finite_counts,
        numeric_counts=numeric_counts,
        duplicate_key_count=duplicate_key_count,
        runtime_seconds=time.perf_counter() - started,
        read_smoke=read_smoke,
    )
    qa_output.parent.mkdir(parents=True, exist_ok=True)
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'verdict': qa['verdict'],
        'dataset_id': DATASET_ID,
        'row_count': qa['row_count'],
        'date_count': qa['date_count'],
        'expected_date_count': qa['expected_date_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'missing_dates': qa['missing_dates'],
        'qa_output': str(qa_output),
        'catalog_output': str(catalog_output),
        'read_smoke_output': str(Path(args.read_smoke_output).expanduser()) if args.read_smoke_output else '',
        'read_smoke_verdict': (read_smoke or {}).get('verdict'),
    }, ensure_ascii=False, indent=2))
    return 0 if qa['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
