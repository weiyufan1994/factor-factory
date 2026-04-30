#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.mutation_guard import require_data_mutation_authority


DEFAULT_BUCKET = 'yufan-data-lake'
DEFAULT_DAILY_KEY = 'tushares/行情数据/daily.csv'
DEFAULT_ADJ_FACTOR_KEY = 'tushares/行情数据/adj_factor.csv'
DEFAULT_DAILY_BASIC_PREFIX = 'tushares/行情数据/daily_basic_incremental'
DEFAULT_MINUTE_PREFIX = 'tushares/分钟数据/raw/stk_mins_1min'
DEFAULT_TRADE_CAL_KEY = 'tushares/基础数据/trade_cal.csv'
DEFAULT_STOCK_BASIC_KEY = 'tushares/基础数据/stock_basic.csv'
DEFAULT_STOCK_ST_KEY = 'tushares/基础数据/stock_st.csv'
DEFAULT_STOCK_ST_DAILY_KEY = 'tushares/基础数据/stock_st_daily_20160101_current.csv'
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
DEFAULT_LOCAL_ROOT = Path.home() / '.qlib' / 'raw_tushare'
DEFAULT_EC2_PERSISTENT_ROOT = LEGACY_WORKSPACE / 'factorforge' / 'data' / 'raw_tushare'


def default_local_root() -> Path:
    explicit_root = os.getenv('FACTORFORGE_LOCAL_DATA_ROOT')
    if explicit_root:
        return Path(explicit_root).expanduser()
    if DEFAULT_EC2_PERSISTENT_ROOT.exists():
        return DEFAULT_EC2_PERSISTENT_ROOT.expanduser()
    if getattr(os, 'geteuid', lambda: -1)() == 0:
        raise RuntimeError(
            'FACTORFORGE_LOCAL_DATA_ROOT must be set when running as root; '
            'refusing to fall back to /root/.qlib/raw_tushare'
        )
    return DEFAULT_LOCAL_ROOT.expanduser()


@dataclass
class MinutePartition:
    trade_date: str
    size: int
    s3_uri: str


def run_aws(args: list[str]) -> str:
    cmd = ['aws', *args]
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def sync_s3_file(bucket: str, key: str, target: Path, optional: bool = False) -> bool:
    ensure_parent(target)
    try:
        subprocess.run(['aws', 's3', 'cp', f's3://{bucket}/{key}', str(target)], check=True)
        print(f'[synced] {target}')
        return True
    except subprocess.CalledProcessError:
        if optional:
            print(f'[skip-optional] s3://{bucket}/{key}')
            return False
        raise


def iter_dates(start: str, end: str) -> list[str]:
    current = datetime.strptime(start, '%Y%m%d')
    stop = datetime.strptime(end, '%Y%m%d')
    days: list[str] = []
    while current <= stop:
        days.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)
    return days


def inspect_daily(bucket: str, key: str) -> dict:
    raw = run_aws([
        's3api', 'head-object',
        '--bucket', bucket,
        '--key', key,
        '--query', '{Size:ContentLength,LastModified:LastModified}',
        '--output', 'json',
    ])
    meta = json.loads(raw)
    return {
        's3_uri': f's3://{bucket}/{key}',
        'size_bytes': int(meta['Size']),
        'last_modified': meta['LastModified'],
    }


def list_minute_partitions(bucket: str, prefix: str) -> list[MinutePartition]:
    raw = run_aws(['s3', 'ls', f's3://{bucket}/{prefix}/', '--recursive'])
    parts: list[MinutePartition] = []
    for line in raw.splitlines():
        if 'trade_date=' not in line or 'part-' not in line:
            continue
        cols = line.split()
        if len(cols) < 4:
            continue
        size = int(cols[2])
        key = cols[3]
        trade_date = key.split('trade_date=')[1].split('/')[0]
        parts.append(
            MinutePartition(
                trade_date=trade_date,
                size=size,
                s3_uri=f's3://{bucket}/{key}',
            )
        )
    return parts


def list_csv_partitions(bucket: str, prefix: str) -> list[MinutePartition]:
    raw = run_aws(['s3', 'ls', f's3://{bucket}/{prefix}/', '--recursive'])
    parts: list[MinutePartition] = []
    for line in raw.splitlines():
        if 'trade_date=' not in line or not line.endswith('.csv'):
            continue
        cols = line.split()
        if len(cols) < 4:
            continue
        size = int(cols[2])
        key = cols[3]
        trade_date = key.split('trade_date=')[1].split('/')[0]
        parts.append(
            MinutePartition(
                trade_date=trade_date,
                size=size,
                s3_uri=f's3://{bucket}/{key}',
            )
        )
    return parts


def command_inspect(args: argparse.Namespace) -> int:
    daily = inspect_daily(args.bucket, args.daily_key)
    daily_basic_parts = list_csv_partitions(args.bucket, args.daily_basic_prefix)
    parts = list_minute_partitions(args.bucket, args.minute_prefix)
    suspicious = [p for p in parts if p.size < args.suspicious_size]

    print('[daily]')
    print(json.dumps(daily, ensure_ascii=False, indent=2))
    print()
    print('[daily_basic]')
    if not daily_basic_parts:
        print('no daily_basic partitions found')
    else:
        print(json.dumps({
            'count': len(daily_basic_parts),
            'first_trade_date': daily_basic_parts[0].trade_date,
            'last_trade_date': daily_basic_parts[-1].trade_date,
        }, ensure_ascii=False, indent=2))
    print()
    print('[minute]')
    if not parts:
        print('no partitions found')
        return 0

    print(json.dumps({
        'count': len(parts),
        'first_trade_date': parts[0].trade_date,
        'last_trade_date': parts[-1].trade_date,
        'suspicious_small_partitions': [
            {'trade_date': p.trade_date, 'size_bytes': p.size, 's3_uri': p.s3_uri}
            for p in suspicious[:50]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


def command_sync_daily(args: argparse.Namespace) -> int:
    target = Path(args.local_root) / '行情数据' / 'daily.csv'
    sync_s3_file(args.bucket, args.daily_key, target)
    return 0


def command_sync_core(args: argparse.Namespace) -> int:
    local_root = Path(args.local_root)
    synced = {
        'daily_csv': sync_s3_file(args.bucket, args.daily_key, local_root / '行情数据' / 'daily.csv'),
        'adj_factor_csv': sync_s3_file(args.bucket, args.adj_factor_key, local_root / '行情数据' / 'adj_factor.csv'),
        'trade_cal_csv': sync_s3_file(args.bucket, args.trade_cal_key, local_root / '基础数据' / 'trade_cal.csv'),
        'stock_basic_csv': sync_s3_file(args.bucket, args.stock_basic_key, local_root / '基础数据' / 'stock_basic.csv'),
        'stock_st_csv': sync_s3_file(args.bucket, args.stock_st_key, local_root / '基础数据' / 'stock_st.csv'),
        'stock_st_daily_csv': sync_s3_file(
            args.bucket,
            args.stock_st_daily_key,
            local_root / '基础数据' / 'stock_st_daily_20160101_current.csv',
            optional=True,
        ),
    }
    print()
    print(json.dumps({'local_root': str(local_root), 'synced': synced}, ensure_ascii=False, indent=2))
    return 0


def command_sync_daily_basic_range(args: argparse.Namespace) -> int:
    all_parts = {p.trade_date: p for p in list_csv_partitions(args.bucket, args.daily_basic_prefix)}
    local_base = Path(args.local_root) / '行情数据' / 'daily_basic_incremental'
    local_base.mkdir(parents=True, exist_ok=True)

    wanted = iter_dates(args.start, args.end)
    copied = 0
    missing: list[str] = []
    for trade_date in wanted:
        part = all_parts.get(trade_date)
        if not part:
            missing.append(trade_date)
            continue
        target = local_base / f'trade_date={trade_date}' / f'daily_basic_{trade_date}.csv'
        ensure_parent(target)
        subprocess.run(['aws', 's3', 'cp', part.s3_uri, str(target)], check=True)
        copied += 1
        print(f'[synced] {trade_date} -> {target}')

    print()
    print(json.dumps({
        'copied_partitions': copied,
        'missing_trade_dates': missing,
        'local_root': str(local_base),
    }, ensure_ascii=False, indent=2))
    return 0


def command_sync_daily_basic_all(args: argparse.Namespace) -> int:
    local_base = Path(args.local_root) / '行情数据' / 'daily_basic_incremental'
    local_base.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            'aws',
            's3',
            'sync',
            f's3://{args.bucket}/{args.daily_basic_prefix}/',
            str(local_base),
            '--exclude',
            '*',
            '--include',
            'trade_date=*/*.csv',
        ],
        check=True,
    )
    print(f'[synced-all] {local_base}')
    return 0


def command_sync_minute_range(args: argparse.Namespace) -> int:
    all_parts = {p.trade_date: p for p in list_minute_partitions(args.bucket, args.minute_prefix)}
    local_base = Path(args.local_root) / '分钟数据' / 'raw' / 'stk_mins_1min'
    local_base.mkdir(parents=True, exist_ok=True)

    wanted = iter_dates(args.start, args.end)
    copied = 0
    missing: list[str] = []
    for trade_date in wanted:
        part = all_parts.get(trade_date)
        if not part:
            missing.append(trade_date)
            continue
        target = local_base / f'trade_date={trade_date}' / 'part-000.parquet'
        ensure_parent(target)
        subprocess.run(['aws', 's3', 'cp', part.s3_uri, str(target)], check=True)
        copied += 1
        print(f'[synced] {trade_date} -> {target}')

    print()
    print(json.dumps({
        'copied_partitions': copied,
        'missing_trade_dates': missing,
        'local_root': str(local_base),
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Inspect and sync raw Tushare daily/minute data from S3 into a local qlib-friendly cache.'
    )
    parser.add_argument('--bucket', default=DEFAULT_BUCKET)
    parser.add_argument('--daily-key', default=DEFAULT_DAILY_KEY)
    parser.add_argument('--adj-factor-key', default=DEFAULT_ADJ_FACTOR_KEY)
    parser.add_argument('--daily-basic-prefix', default=DEFAULT_DAILY_BASIC_PREFIX)
    parser.add_argument('--minute-prefix', default=DEFAULT_MINUTE_PREFIX)
    parser.add_argument('--trade-cal-key', default=DEFAULT_TRADE_CAL_KEY)
    parser.add_argument('--stock-basic-key', default=DEFAULT_STOCK_BASIC_KEY)
    parser.add_argument('--stock-st-key', default=DEFAULT_STOCK_ST_KEY)
    parser.add_argument('--stock-st-daily-key', default=DEFAULT_STOCK_ST_DAILY_KEY)
    parser.add_argument('--local-root', default=None)
    parser.add_argument('--operator', default=None, help='Data mutation operator. Required for sync-* commands.')

    sub = parser.add_subparsers(dest='command', required=True)

    inspect_parser = sub.add_parser('inspect')
    inspect_parser.add_argument('--suspicious-size', type=int, default=1_000_000)
    inspect_parser.set_defaults(func=command_inspect)

    daily_parser = sub.add_parser('sync-daily')
    daily_parser.set_defaults(func=command_sync_daily)

    core_parser = sub.add_parser('sync-core')
    core_parser.set_defaults(func=command_sync_core)

    daily_basic_parser = sub.add_parser('sync-daily-basic-range')
    daily_basic_parser.add_argument('--start', required=True, help='Inclusive YYYYMMDD start date.')
    daily_basic_parser.add_argument('--end', required=True, help='Inclusive YYYYMMDD end date.')
    daily_basic_parser.set_defaults(func=command_sync_daily_basic_range)

    daily_basic_all_parser = sub.add_parser('sync-daily-basic-all')
    daily_basic_all_parser.set_defaults(func=command_sync_daily_basic_all)

    minute_parser = sub.add_parser('sync-minute-range')
    minute_parser.add_argument('--start', required=True, help='Inclusive YYYYMMDD start date.')
    minute_parser.add_argument('--end', required=True, help='Inclusive YYYYMMDD end date.')
    minute_parser.set_defaults(func=command_sync_minute_range)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.local_root is None and args.command != 'inspect':
        args.local_root = str(default_local_root())
    if args.command != 'inspect':
        require_data_mutation_authority(args.operator, operation=f'sync_tushare_raw_from_s3:{args.command}')
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
