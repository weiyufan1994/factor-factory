#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.intraday_retained_chip_state import (  # noqa: E402
    DATASET_ID,
    IntradayRetainedChipStateParams,
    build_interval_turnover_frame,
    normalize_trade_date,
    write_partitioned_datamart,
)


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build LCR 15-minute interval turnover base from minute_bar and daily_basic.')
    parser.add_argument('--minute-s3-root', required=True)
    parser.add_argument('--daily-basic-root', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--dates', default='')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--max-dates', type=int, default=20)
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    return parser.parse_args(argv)


def discover_s3_partition_dates(root: str) -> list[str]:
    output = subprocess.check_output(['aws', 's3', 'ls', root.rstrip('/') + '/'], text=True)
    return sorted(set(re.findall(r'trade_date=(\d{8})/', output)))


def discover_local_partition_dates(root: Path) -> list[str]:
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir() and '=' in path.name
    })


def target_dates(args: argparse.Namespace, available: list[str]) -> list[str]:
    if args.dates:
        return sorted({normalize_trade_date(item) for item in split_csv(args.dates)})
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    return [date for date in available if start <= date <= end]


def read_minute_s3_day(root: str, trade_date: str) -> pd.DataFrame:
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.fs as fs

    stripped = root.removeprefix('s3://').rstrip('/')
    bucket, _, key = stripped.partition('/')
    region = fs.resolve_s3_region(bucket)
    filesystem = fs.S3FileSystem(
        region=region,
        request_timeout=60.0,
        connect_timeout=10.0,
        retry_strategy=fs.AwsStandardS3RetryStrategy(max_attempts=8),
    )
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    dataset = ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning)
    wanted = ['ts_code', 'trade_date', 'trade_time', 'bar_time', 'hhmmss', 'vol', 'amount', 'amount_abs']
    columns = [column for column in wanted if column in dataset.schema.names]
    table = dataset.to_table(columns=columns, filter=ds.field('trade_date') == str(trade_date))
    frame = table.to_pandas()
    if 'trade_date' not in frame.columns:
        frame['trade_date'] = trade_date
    return frame


def read_daily_basic_day(root: Path, trade_date: str) -> pd.DataFrame:
    part = root / f'trade_date={trade_date}'
    files = sorted(part.glob('*.parquet')) if part.exists() else []
    if not files:
        return pd.DataFrame()
    frame = pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)
    if 'trade_date' not in frame.columns:
        frame['trade_date'] = trade_date
    return frame


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    output_root = Path(args.output_root).expanduser()
    if output_root.exists() and any(output_root.iterdir()) and not args.skip_existing:
        if not args.overwrite:
            raise SystemExit(f'output root already exists and is not empty: {output_root}; pass --overwrite')
        shutil.rmtree(output_root)
    minute_dates = discover_s3_partition_dates(args.minute_s3_root)
    daily_root = Path(args.daily_basic_root).expanduser()
    daily_dates = discover_local_partition_dates(daily_root)
    available = sorted(set(minute_dates) & set(daily_dates))
    dates = target_dates(args, available)
    if len(dates) > int(args.max_dates):
        raise SystemExit(f'target dates {len(dates)} exceeds --max-dates={args.max_dates}')
    if args.skip_existing:
        dates = [date for date in dates if not (output_root / f'trade_date={date}' / 'part.parquet').exists()]

    rows: list[pd.DataFrame] = []
    profile: list[dict[str, Any]] = []
    params = IntradayRetainedChipStateParams()
    for trade_date in dates:
        minute = read_minute_s3_day(args.minute_s3_root, trade_date)
        daily = read_daily_basic_day(daily_root, trade_date)
        if minute.empty or daily.empty:
            profile.append({'trade_date': trade_date, 'status': 'missing_source', 'minute_rows': int(len(minute)), 'daily_rows': int(len(daily))})
            continue
        interval = build_interval_turnover_frame(minute, daily, params)
        rows.append(interval)
        profile.append({'trade_date': trade_date, 'status': 'ready', 'minute_rows': int(len(minute)), 'daily_rows': int(len(daily)), 'interval_rows': int(len(interval))})
    frame = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not frame.empty:
        write_partitioned_datamart(frame, output_root)
    covered = sorted(frame['trade_date'].astype(str).unique().tolist()) if 'trade_date' in frame.columns and not frame.empty else []
    missing = sorted(set(dates).difference(covered))
    issues: list[str] = []
    if not dates:
        issues.append('target_dates_empty')
    if missing:
        issues.append('missing_output_dates')
    qa = {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'artifact_type': 'intraday_retained_chip_interval_base_qa',
        'row_count': int(len(frame)),
        'date_count': len(covered),
        'covered_dates': covered,
        'missing_dates': missing,
        'target_dates': dates,
        'profile': profile,
        'runtime_seconds': float(time.perf_counter() - started),
        'issues': issues,
        'output_root': str(output_root),
        'safety': {'starts_worker': False, 'writes_active_catalog': False, 'writes_factorforge_artifacts': False},
    }
    qa_path = Path(args.qa_output).expanduser()
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': qa['verdict'], 'row_count': qa['row_count'], 'date_count': qa['date_count']}, ensure_ascii=False))
    return 0 if qa['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
