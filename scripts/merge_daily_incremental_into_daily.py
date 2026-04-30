#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.mutation_guard import require_data_mutation_authority


DEFAULT_BUCKET = 'yufan-data-lake'
DEFAULT_DAILY_KEY = 'tushares/行情数据/daily.csv'
DEFAULT_INCREMENTAL_PREFIX = 'tushares/行情数据/daily_incremental'
DEFAULT_LOCAL_DAILY = Path.home() / '.qlib' / 'raw_tushare' / '行情数据' / 'daily.csv'


def run_aws(args: list[str]) -> str:
    cmd = ['aws', *args]
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout


def list_incremental_partitions(bucket: str, prefix: str) -> list[dict[str, str | int]]:
    raw = run_aws(['s3', 'ls', f's3://{bucket}/{prefix}/', '--recursive'])
    parts: list[dict[str, str | int]] = []
    for line in raw.splitlines():
        if 'trade_date=' not in line or not line.endswith('.csv'):
            continue
        cols = line.split()
        if len(cols) < 4:
            continue
        key = cols[3]
        parts.append({
            'trade_date': key.split('trade_date=')[1].split('/')[0],
            'size_bytes': int(cols[2]),
            's3_uri': f's3://{bucket}/{key}',
        })
    return parts


def read_local_last_trade_date(path: Path) -> str:
    last_trade_date = ''
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            last_trade_date = row['trade_date']
    if not last_trade_date:
        raise RuntimeError(f'base daily.csv is empty: {path}')
    return last_trade_date


def select_trade_dates(parts: list[dict[str, str | int]], start: str | None, end: str | None, base_max_date: str) -> list[str]:
    dates = sorted(str(p['trade_date']) for p in parts)
    if start is None:
        start = str(int(base_max_date) + 1)
    selected = [d for d in dates if start <= d and (end is None or d <= end)]
    return selected


def download_incremental_rows(bucket: str, prefix: str, trade_dates: list[str]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix='daily_incremental_merge_') as tmp_dir:
        tmp_root = Path(tmp_dir)
        for trade_date in trade_dates:
            remote = f's3://{bucket}/{prefix}/trade_date={trade_date}/daily_{trade_date}.csv'
            local = tmp_root / f'daily_{trade_date}.csv'
            subprocess.run(['aws', 's3', 'cp', remote, str(local)], check=True, stdout=subprocess.DEVNULL)
            with local.open('r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    grouped[row['ts_code']].append(row)

    for rows in grouped.values():
        rows.sort(key=lambda row: row['trade_date'])
    return grouped


def merge_tail_range(base_csv: Path, output_csv: Path, update_dates: list[str], incremental_rows: dict[str, list[dict[str, str]]]) -> dict[str, int | str]:
    update_dates_set = set(update_dates)
    pending_codes = set(incremental_rows)
    replaced_rows = 0
    written_rows = 0

    output_csv.parent.mkdir(parents=True, exist_ok=True)

    with base_csv.open('r', encoding='utf-8-sig', newline='') as src, output_csv.open('w', encoding='utf-8-sig', newline='') as dst:
        reader = csv.DictReader(src)
        if reader.fieldnames is None:
            raise RuntimeError(f'base daily.csv has no header: {base_csv}')
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()

        current_code = None
        for row in reader:
            code = row['ts_code']
            if current_code is None:
                current_code = code
            elif code != current_code:
                for inc_row in incremental_rows.get(current_code, []):
                    writer.writerow(inc_row)
                    written_rows += 1
                pending_codes.discard(current_code)
                current_code = code

            if row['trade_date'] in update_dates_set:
                replaced_rows += 1
                continue

            writer.writerow(row)
            written_rows += 1

        if current_code is not None:
            for inc_row in incremental_rows.get(current_code, []):
                writer.writerow(inc_row)
                written_rows += 1
            pending_codes.discard(current_code)

        for code in sorted(pending_codes):
            for inc_row in incremental_rows[code]:
                writer.writerow(inc_row)
                written_rows += 1

    return {
        'output_csv': str(output_csv),
        'written_rows': written_rows,
        'replaced_rows': replaced_rows,
        'incremental_trade_dates': len(update_dates),
        'incremental_codes': len(incremental_rows),
    }


def upload_file(local_path: Path, bucket: str, key: str) -> None:
    subprocess.run(['aws', 's3', 'cp', str(local_path), f's3://{bucket}/{key}'], check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Merge tail daily_incremental partitions into the canonical daily.csv without re-running a full history rebuild.'
    )
    parser.add_argument('--bucket', default=DEFAULT_BUCKET)
    parser.add_argument('--daily-key', default=DEFAULT_DAILY_KEY)
    parser.add_argument('--incremental-prefix', default=DEFAULT_INCREMENTAL_PREFIX)
    parser.add_argument('--base-csv', default=str(DEFAULT_LOCAL_DAILY))
    parser.add_argument('--output-csv', default=None, help='Defaults to <base>.merged when omitted.')
    parser.add_argument('--start-date', default=None, help='Inclusive YYYYMMDD start date. Defaults to base max date + 1.')
    parser.add_argument('--end-date', default=None, help='Inclusive YYYYMMDD end date.')
    parser.add_argument('--replace-base', action='store_true', help='Move merged output over the base CSV after success.')
    parser.add_argument('--upload', action='store_true', help='Upload merged output back to the canonical daily.csv S3 key.')
    parser.add_argument('--operator', default=None, help='Data mutation operator. Must be codex when replacing/uploading canonical daily data.')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.replace_base or args.upload:
        require_data_mutation_authority(args.operator, operation='merge_daily_incremental_into_daily')
    base_csv = Path(args.base_csv).expanduser().resolve()
    if not base_csv.exists():
        raise FileNotFoundError(f'base daily.csv does not exist: {base_csv}')

    output_csv = Path(args.output_csv).expanduser().resolve() if args.output_csv else base_csv.with_suffix('.merged.csv')
    base_max_date = read_local_last_trade_date(base_csv)
    parts = list_incremental_partitions(args.bucket, args.incremental_prefix)
    update_dates = select_trade_dates(parts, args.start_date, args.end_date, base_max_date)
    if not update_dates:
        print(json.dumps({
            'status': 'noop',
            'reason': 'no incremental partitions selected',
            'base_max_trade_date': base_max_date,
        }, ensure_ascii=False, indent=2))
        return 0

    incremental_rows = download_incremental_rows(args.bucket, args.incremental_prefix, update_dates)
    summary = merge_tail_range(base_csv, output_csv, update_dates, incremental_rows)
    summary.update({
        'status': 'merged',
        'base_csv': str(base_csv),
        'base_max_trade_date': base_max_date,
        'first_update_trade_date': update_dates[0],
        'last_update_trade_date': update_dates[-1],
    })

    if args.replace_base:
        backup_path = base_csv.with_suffix('.pre_merge.bak')
        if backup_path.exists():
            backup_path.unlink()
        shutil.copy2(base_csv, backup_path)
        os.replace(output_csv, base_csv)
        summary['backup_csv'] = str(backup_path)
        summary['active_csv'] = str(base_csv)
        output_for_upload = base_csv
    else:
        output_for_upload = output_csv

    if args.upload:
        upload_file(output_for_upload, args.bucket, args.daily_key)
        summary['uploaded_s3_uri'] = f's3://{args.bucket}/{args.daily_key}'

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
