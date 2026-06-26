#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.flow_distribution_moments import PREPARED_MINUTE_COLUMNS, prepare_minute_frame  # noqa: E402
from scripts.build_intraday_flow_distribution_moments import discover_partition_dates  # noqa: E402
from scripts.build_prepared_minute_bar import RAW_COLUMNS, discover_source_ready_status, filter_source_ready_dates  # noqa: E402
from scripts.run_flow_distribution_moments_parity_smoke import main as parity_main  # noqa: E402


class SourceNotReadyError(RuntimeError):
    def __init__(self, payload: dict[str, object]):
        super().__init__('target date is not source-ready')
        self.payload = payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build prepared minute cache and run flow moments speed proof.')
    parser.add_argument('--raw-minute-root', required=True)
    parser.add_argument('--prepared-root', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--lookback-days', type=int, default=60)
    parser.add_argument('--cutoff-times', default='10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00')
    parser.add_argument('--threshold-lookback-days', default='20,60')
    parser.add_argument('--threshold-backend', default='pandas')
    parser.add_argument('--min-minutes', type=int, default=20)
    parser.add_argument('--tolerance', type=float, default=1e-6)
    parser.add_argument('--source-ready-only', action='store_true', help='Only build prepared cache from source partitions with parquet data files.')
    return parser.parse_args()


def build_prepared_cache(raw_root: Path, prepared_root: Path, target_date: str, lookback_days: int, *, source_ready_only: bool = False) -> dict[str, object]:
    available = discover_partition_dates(raw_root)
    source_not_ready_dates: list[str] = []
    if source_ready_only:
        available, source_not_ready_dates = filter_source_ready_dates(
            available,
            discover_source_ready_status(raw_root),
        )
    if target_date not in available:
        raise SourceNotReadyError({
            'verdict': 'BLOCK',
            'date': target_date,
            'issues': ['target_date_not_source_ready'] if source_ready_only else ['target_date_not_available'],
            'prepared_cache_build_seconds': 0.0,
            'prepared_cache_dates': [],
            'prepared_cache_source_not_ready_dates': source_not_ready_dates,
            'prepared_cache_source_ready_policy': {
                'enabled': bool(source_ready_only),
                'not_ready_dates': source_not_ready_dates,
            },
            'prepared_cache_date_count': 0,
            'prepared_cache_row_count': 0,
            'prepared_cache_partitions': [],
            'prepared_cache_skipped_partitions': [],
        })
    idx = available.index(target_date)
    dates = available[max(0, idx - lookback_days):idx + 1]
    started = time.perf_counter()
    rows = []
    skipped = []
    for trade_date in dates:
        source = raw_root / f'trade_date={trade_date}'
        target_dir = prepared_root / f'trade_date={trade_date}'
        try:
            frame = pd.read_parquet(source)
        except Exception as exc:  # noqa: BLE001
            skipped.append({'trade_date': trade_date, 'source_path': str(source), 'error': str(exc)})
            if trade_date == target_date:
                raise
            continue
        keep = [col for col in RAW_COLUMNS if col in frame.columns]
        prepared = prepare_minute_frame(frame[keep])
        target_dir.mkdir(parents=True, exist_ok=True)
        prepared[PREPARED_MINUTE_COLUMNS].to_parquet(target_dir / 'part.parquet', index=False)
        rows.append({
            'trade_date': trade_date,
            'row_count': int(len(prepared)),
            'ticker_count': int(prepared['ts_code'].nunique()) if not prepared.empty else 0,
        })
    return {
        'prepared_cache_build_seconds': float(time.perf_counter() - started),
        'prepared_cache_dates': dates,
        'prepared_cache_source_not_ready_dates': source_not_ready_dates,
        'prepared_cache_source_ready_policy': {
            'enabled': bool(source_ready_only),
            'not_ready_dates': source_not_ready_dates,
        },
        'prepared_cache_date_count': len(dates),
        'prepared_cache_row_count': int(sum(item['row_count'] for item in rows)),
        'prepared_cache_partitions': rows,
        'prepared_cache_skipped_partitions': skipped,
    }


def main() -> int:
    args = parse_args()
    raw_root = Path(args.raw_minute_root).expanduser()
    prepared_root = Path(args.prepared_root).expanduser()
    output_path = Path(args.output_path).expanduser()
    try:
        cache_summary = build_prepared_cache(raw_root, prepared_root, args.date, args.lookback_days, source_ready_only=bool(args.source_ready_only))
    except SourceNotReadyError as exc:
        payload = dict(exc.payload)
        payload['prepared_cache_root'] = str(prepared_root)
        payload['prepared_cache_size_bytes'] = int(sum(path.stat().st_size for path in prepared_root.rglob('*') if path.is_file())) if prepared_root.exists() else 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    old_argv = sys.argv[:]
    try:
        sys.argv = [
            'run_flow_distribution_moments_parity_smoke.py',
            '--minute-root', str(prepared_root),
            '--date', args.date,
            '--output-path', str(output_path),
            '--cutoff-times', args.cutoff_times,
            '--threshold-lookback-days', args.threshold_lookback_days,
            '--threshold-backend', args.threshold_backend,
            '--min-minutes', str(args.min_minutes),
            '--tolerance', str(args.tolerance),
        ]
        status = parity_main()
    finally:
        sys.argv = old_argv

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    payload.update(cache_summary)
    payload['prepared_cache_root'] = str(prepared_root)
    payload['prepared_cache_size_bytes'] = int(sum(path.stat().st_size for path in prepared_root.rglob('*') if path.is_file()))
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
