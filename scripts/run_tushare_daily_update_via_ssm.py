#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.mutation_guard import require_data_mutation_authority


DEFAULT_INSTANCE_ID = 'i-01c0ceb9c04ae270e'
DEFAULT_REMOTE_ROOT = '/home/ubuntu/.openclaw/workspace/repos/quant_self/tushare数据获取'
DEFAULT_REMOTE_PYTHON = '/home/ubuntu/miniconda3/envs/rdagent/bin/python'
DEFAULT_BUCKET = 'yufan-data-lake'
DEFAULT_DAILY_KEY = 'tushares/行情数据/daily.csv'
DEFAULT_DAILY_INCREMENTAL_PREFIX = 'tushares/行情数据/daily_incremental'
DEFAULT_DAILY_BASIC_PREFIX = 'tushares/行情数据/daily_basic_incremental'
DEFAULT_TRADE_CAL_KEY = 'tushares/基础数据/trade_cal.csv'
DEFAULT_LOCAL_DAILY = str(Path.home() / '.qlib' / 'raw_tushare' / '行情数据' / 'daily.csv')


def run_local(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=capture)


def aws_text(args: list[str]) -> str:
    return run_local(['aws', *args]).stdout


def send_ssm(instance_id: str, comment: str, commands: list[str]) -> str:
    params = json.dumps({'commands': commands})
    return aws_text([
        'ssm', 'send-command',
        '--instance-ids', instance_id,
        '--document-name', 'AWS-RunShellScript',
        '--comment', comment,
        '--parameters', params,
        '--query', 'Command.CommandId',
        '--output', 'text',
    ]).strip()


def wait_ssm(instance_id: str, command_id: str, *, timeout_sec: int = 3600, poll_sec: int = 5) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        raw = aws_text([
            'ssm', 'get-command-invocation',
            '--command-id', command_id,
            '--instance-id', instance_id,
            '--output', 'json',
        ])
        payload = json.loads(raw)
        status = payload['Status']
        if status not in {'Pending', 'InProgress', 'Delayed'}:
            return payload
        time.sleep(poll_sec)
    raise TimeoutError(f'SSM command timed out: {command_id}')


def s3_list_partition_dates(bucket: str, prefix: str) -> set[str]:
    raw = aws_text(['s3', 'ls', f's3://{bucket}/{prefix}/', '--recursive'])
    out: set[str] = set()
    for line in raw.splitlines():
        if 'trade_date=' not in line:
            continue
        cols = line.split()
        if len(cols) < 4:
            continue
        key = cols[3]
        out.add(key.split('trade_date=')[1].split('/')[0])
    return out


def read_s3_csv_rows(bucket: str, key: str) -> list[dict[str, str]]:
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        run_local(['aws', 's3', 'cp', f's3://{bucket}/{key}', str(tmp_path)], capture=False)
        with tmp_path.open('r', encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    finally:
        tmp_path.unlink(missing_ok=True)


def read_local_last_trade_date(path: str) -> str:
    csv_path = Path(path).expanduser().resolve()
    last = ''
    with csv_path.open('r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            last = row['trade_date']
    if not last:
        raise RuntimeError(f'local daily.csv has no rows: {csv_path}')
    return last


def compute_missing_daily_trade_dates(bucket: str, trade_cal_key: str, daily_incremental_prefix: str, start_after: str, end_date: str) -> list[str]:
    trade_cal = read_s3_csv_rows(bucket, trade_cal_key)
    existing = s3_list_partition_dates(bucket, daily_incremental_prefix)
    wanted: list[str] = []
    for row in trade_cal:
        cal_date = row['cal_date']
        if row['is_open'] != '1':
            continue
        if not (start_after < cal_date <= end_date):
            continue
        if cal_date in existing:
            continue
        wanted.append(cal_date)
    return wanted


def build_remote_daily_basic_refresh_command(python_bin: str) -> str:
    return f"""{python_bin} - <<'PY'
from subprocess import run
import sys
cmd = ['{python_bin}', '15_daily_basic_incremental_to_s3.py']
proc = run(cmd, text=True, capture_output=True)
if proc.stdout:
    print(proc.stdout, end='')
if proc.returncode != 0:
    if '返回空结果' in (proc.stderr or ''):
        print('[WARN] daily_basic empty result; skip and retry next run')
    else:
        if proc.stderr:
            print(proc.stderr, end='', file=sys.stderr)
        raise SystemExit(proc.returncode)
PY"""


def build_remote_daily_refresh_commands(remote_root: str, python_bin: str, missing_dates: list[str], daily_basic_command: str | None) -> list[str]:
    commands = [
        'set -e',
        f'cd {remote_root}',
        f'{python_bin} 11_stock_basic_to_s3.py',
        f'{python_bin} 12_trade_cal_to_s3.py',
        f'{python_bin} 13_stock_st_to_s3.py',
        f'{python_bin} 14_stock_st_daily_fallback_to_s3.py',
    ]

    for trade_date in missing_dates:
        commands.append(
            f"""{python_bin} - <<'PY'
from subprocess import run
import sys
trade_date = '{trade_date}'
cmd = ['{python_bin}', '16_daily_incremental_to_s3.py', '--trade-date', trade_date]
proc = run(cmd, text=True, capture_output=True)
if proc.stdout:
    print(proc.stdout, end='')
if proc.returncode != 0:
    if '返回空结果' in (proc.stderr or ''):
        print(f'[WARN] daily_incremental empty result for {{trade_date}}; skip and retry next run')
    else:
        if proc.stderr:
            print(proc.stderr, end='', file=sys.stderr)
        raise SystemExit(proc.returncode)
PY"""
        )

    commands.append(daily_basic_command or build_remote_daily_basic_refresh_command(python_bin))

    return commands


def run_remote_refresh(args: argparse.Namespace) -> dict:
    start_after = args.start_after or read_local_last_trade_date(args.local_daily_csv)
    missing_dates = compute_missing_daily_trade_dates(
        bucket=args.bucket,
        trade_cal_key=args.trade_cal_key,
        daily_incremental_prefix=args.daily_incremental_prefix,
        start_after=start_after,
        end_date=args.end_date,
    )
    command_id = send_ssm(
        args.instance_id,
        'tushare daily refresh via factorforge',
        build_remote_daily_refresh_commands(
            remote_root=args.remote_root,
            python_bin=args.remote_python,
            missing_dates=missing_dates,
            daily_basic_command=args.daily_basic_command,
        ),
    )
    payload = wait_ssm(args.instance_id, command_id, timeout_sec=args.timeout_sec)
    return {
        'command_id': command_id,
        'status': payload['Status'],
        'missing_trade_dates': missing_dates,
        'stdout': payload.get('StandardOutputContent', ''),
        'stderr': payload.get('StandardErrorContent', ''),
        'start_after': start_after,
        'end_date': args.end_date,
    }


def run_local_merge(args: argparse.Namespace) -> dict:
    cmd = [
        'python3',
        'scripts/merge_daily_incremental_into_daily.py',
        '--base-csv', args.local_daily_csv,
        '--end-date', args.end_date,
        '--replace-base',
        '--operator',
        args.operator,
    ]
    if args.merge_upload:
        cmd.append('--upload')
    result = run_local(cmd)
    return json.loads(result.stdout)


def run_local_clean_refresh(args: argparse.Namespace) -> dict:
    cmd = [
        'python3',
        'scripts/refresh_clean_daily_after_tushare_update.py',
        '--end-date',
        args.end_date,
        '--clean-start',
        args.clean_start,
        '--clean-end',
        args.clean_end,
    ]
    if args.force_clean_refresh:
        cmd.append('--force')
    if args.clean_backup:
        cmd.append('--backup')
    if args.skip_clean_daily_basic_sync:
        cmd.append('--skip-sync-daily-basic')
    if args.sync_all_daily_basic_if_missing:
        cmd.append('--sync-all-daily-basic-if-missing')
    cmd.extend(['--operator', args.operator])

    result = run_local(cmd)
    return json.loads(result.stdout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Run the fixed Tushare daily update SOP: basics refresh, daily_incremental fill, and optional canonical daily.csv merge.'
    )
    parser.add_argument('--instance-id', default=DEFAULT_INSTANCE_ID)
    parser.add_argument('--remote-root', default=DEFAULT_REMOTE_ROOT)
    parser.add_argument('--remote-python', default=DEFAULT_REMOTE_PYTHON)
    parser.add_argument('--bucket', default=DEFAULT_BUCKET)
    parser.add_argument('--trade-cal-key', default=DEFAULT_TRADE_CAL_KEY)
    parser.add_argument('--daily-incremental-prefix', default=DEFAULT_DAILY_INCREMENTAL_PREFIX)
    parser.add_argument('--local-daily-csv', default=DEFAULT_LOCAL_DAILY)
    parser.add_argument('--start-after', default=None, help='Exclusive YYYYMMDD lower bound. Defaults to local daily.csv max trade_date.')
    parser.add_argument('--end-date', default=datetime.now().strftime('%Y%m%d'))
    parser.add_argument('--timeout-sec', type=int, default=3600)
    parser.add_argument('--daily-basic-command', default=None, help='Optional remote shell command for the daily_basic daily trigger after the backfill finishes. Defaults to 15_daily_basic_incremental_to_s3.py on the remote host.')
    parser.add_argument('--skip-merge', action='store_true')
    parser.add_argument('--merge-upload', action='store_true', help='Upload merged canonical daily.csv back to S3 after local merge.')
    parser.add_argument('--refresh-clean-layer', action='store_true', help='After raw update/merge, sync daily_basic locally if needed, rebuild daily_clean if stale, and merge daily_basic enhancement columns.')
    parser.add_argument('--clean-start', default='20100104', help='Start date used when rebuilding the shared clean daily layer.')
    parser.add_argument('--clean-end', default='current', help='End date used when rebuilding the shared clean daily layer.')
    parser.add_argument('--force-clean-refresh', action='store_true', help='Force clean layer rebuild and daily_basic enhancement merge even if the layer appears current.')
    parser.add_argument('--clean-backup', action='store_true', help='Keep large parquet backups when daily_basic enhancement replaces daily_clean.')
    parser.add_argument('--skip-clean-daily-basic-sync', action='store_true', help='Do not sync local daily_basic from S3 before refreshing clean layer.')
    parser.add_argument('--sync-all-daily-basic-if-missing', action='store_true', help='If no local daily_basic cache exists, sync all daily_basic partitions from S3 before refreshing clean layer.')
    parser.add_argument('--operator', default=None, help='Data mutation operator. Must be codex for raw/clean data mutation workflows.')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    require_data_mutation_authority(args.operator, operation='run_tushare_daily_update_via_ssm')

    remote = run_remote_refresh(args)
    summary: dict[str, object] = {'remote_refresh': remote}

    if remote['status'] != 'Success':
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    if not args.skip_merge:
        summary['local_merge'] = run_local_merge(args)

    if args.refresh_clean_layer:
        summary['local_clean_refresh'] = run_local_clean_refresh(args)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
