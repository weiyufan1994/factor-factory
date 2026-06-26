#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.daily_basic import list_daily_basic_trade_dates  # noqa: E402
from factor_factory.data_access.paths import resolve_local_tushare_paths  # noqa: E402
from factor_factory.data_api.intraday_retained_chip_state import DATASET_ID, normalize_trade_date  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build source coverage proof for intraday_retained_chip_state_v1.')
    parser.add_argument('--minute-s3-root', default='s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/')
    parser.add_argument('--start', default='20160104')
    parser.add_argument('--is-end', default='20250711')
    parser.add_argument('--oos-start', default='20250714')
    parser.add_argument('--end', default='')
    parser.add_argument('--daily-basic-root', default='', help='Optional parquet warm-cache root partitioned by trade_date.')
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def list_minute_s3_dates(root: str) -> list[str]:
    output = subprocess.check_output(['aws', 's3', 'ls', root.rstrip('/') + '/'], text=True)
    return sorted(set(re.findall(r'trade_date=(\d{8})/', output)))


def list_trade_cal_dates(start: str, end: str) -> list[str]:
    paths = resolve_local_tushare_paths(require_daily_basic=True)
    frame = pd.read_csv(paths.trade_cal_csv, dtype={'cal_date': 'string', 'is_open': 'Int64'})
    dates = frame.loc[frame['is_open'].fillna(0).astype(int) == 1, 'cal_date'].map(normalize_trade_date)
    return sorted(date for date in dates.tolist() if start <= date <= end)


def list_local_partition_dates(root: str | Path) -> list[str]:
    path = Path(root).expanduser()
    if not path.exists():
        return []
    return sorted({
        normalize_trade_date(child.name.split('=', 1)[1])
        for child in path.glob('trade_date=*')
        if child.is_dir() and '=' in child.name
    })


def build_coverage(args: argparse.Namespace) -> dict[str, Any]:
    start = normalize_trade_date(args.start)
    minute_dates = list_minute_s3_dates(args.minute_s3_root)
    daily_basic_dates = list_local_partition_dates(args.daily_basic_root) if args.daily_basic_root else list_daily_basic_trade_dates()
    latest_intersection = min(max(minute_dates), max(daily_basic_dates)) if minute_dates and daily_basic_dates else ''
    end = normalize_trade_date(args.end) if args.end else latest_intersection
    if args.daily_basic_root:
        expected_dates = [date for date in daily_basic_dates if start <= date <= end]
        expected_source = 'daily_basic_parquet_partitions'
    else:
        expected_dates = list_trade_cal_dates(start, end) if end else []
        expected_source = 'trade_cal'
    minute_set = set(minute_dates)
    daily_set = set(daily_basic_dates)
    expected_set = set(expected_dates)
    intersection = sorted(expected_set & minute_set & daily_set)
    missing_minute = sorted(expected_set - minute_set)
    missing_daily = sorted(expected_set - daily_set)
    missing_intersection = sorted(expected_set - set(intersection))
    issues: list[str] = []
    if not expected_dates:
        issues.append('expected_dates_empty')
    if missing_intersection:
        issues.append('source_intersection_missing_dates')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'artifact_type': 'source_coverage_proof',
        'start': start,
        'end': end,
        'is_end': normalize_trade_date(args.is_end),
        'oos_start': normalize_trade_date(args.oos_start),
        'minute_s3_root': args.minute_s3_root,
        'minute_bar': {
            'date_count': len(minute_dates),
            'first': minute_dates[0] if minute_dates else None,
            'last': minute_dates[-1] if minute_dates else None,
            'missing_expected_dates': missing_minute,
        },
        'daily_basic_float_share': {
            'date_count': len(daily_basic_dates),
            'first': daily_basic_dates[0] if daily_basic_dates else None,
            'last': daily_basic_dates[-1] if daily_basic_dates else None,
            'required_field': 'float_share',
            'missing_expected_dates': missing_daily,
        },
        'expected_open_dates': {
            'date_count': len(expected_dates),
            'first': expected_dates[0] if expected_dates else None,
            'last': expected_dates[-1] if expected_dates else None,
            'source': expected_source,
        },
        'source_intersection': {
            'date_count': len(intersection),
            'first': intersection[0] if intersection else None,
            'last': intersection[-1] if intersection else None,
            'missing_expected_dates': missing_intersection,
        },
        'representative_smoke_dates': [
            date for date in ['20160104', '20250711', '20250714', latest_intersection] if date and date in set(intersection)
        ],
        'issues': issues,
        'information_set_legality': {
            'source_only': True,
            'no_future_data': True,
            'coverage_only_no_factor_backtest': True,
        },
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'runs_factor_loop': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_coverage(args)
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': payload['verdict'], 'output_path': str(output_path), 'end': payload['end']}, ensure_ascii=False))
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
