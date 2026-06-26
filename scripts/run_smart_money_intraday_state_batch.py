#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_smart_money_intraday_state import (  # noqa: E402
    discover_output_ready_dates,
    discover_s3_partition_dates,
    normalize_trade_date,
)


DATASET_ID = 'smart_money_intraday_state_v1'


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run resumable shard batches for smart_money_intraday_state_v1.')
    parser.add_argument('--minute-s3-root', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--work-root', required=True)
    parser.add_argument('--manifest-output', required=True)
    parser.add_argument('--shard-size', type=int, default=3)
    parser.add_argument('--max-shards', type=int)
    parser.add_argument('--lookback-trading-days', type=int, default=10)
    parser.add_argument('--cutoff-volume-share', type=float, default=0.20)
    parser.add_argument('--min-valid-minutes', type=int, default=5)
    parser.add_argument('--research-window', default='IS', choices=['IS', 'OOS', 'SMOKE'])
    parser.add_argument('--s3-local-cache', default='')
    parser.add_argument('--available-dates-file', default='', help='Optional cached source trade_date list; avoids top-level S3 listing for resumable production.')
    parser.add_argument('--write-available-dates-file', default='', help='Optional output path to persist the discovered source trade_date list.')
    parser.add_argument('--dry-run', action='store_true')
    return parser.parse_args(argv)


def select_dates(available: list[str], start: str, end: str) -> list[str]:
    start_norm = normalize_trade_date(start)
    end_norm = normalize_trade_date(end)
    return [date for date in available if start_norm <= date <= end_norm]


def chunk_dates(dates: list[str], shard_size: int) -> list[list[str]]:
    if shard_size <= 0:
        raise SystemExit('--shard-size must be positive')
    return [dates[pos:pos + shard_size] for pos in range(0, len(dates), shard_size)]


def write_json(path: str | Path, payload: dict[str, object]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def read_available_dates_file(path: str | Path) -> list[str]:
    raw = Path(path).expanduser().read_text(encoding='utf-8')
    return sorted({normalize_trade_date(line) for line in raw.splitlines() if line.strip() and not line.strip().startswith('#')})


def write_available_dates_file(path: str | Path, dates: list[str]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('\n'.join(dates) + '\n', encoding='utf-8')


def run_builder_for_shard(args: argparse.Namespace, shard_id: str, dates: list[str]) -> dict[str, object]:
    work_root = Path(args.work_root).expanduser()
    shard_root = work_root / 'shards' / shard_id
    shard_root.mkdir(parents=True, exist_ok=True)
    dates_text = shard_root / 'dates.txt'
    dates_text.write_text('\n'.join(dates) + '\n', encoding='utf-8')
    qa_path = shard_root / 'qa.json'
    catalog_path = shard_root / 'catalog.json'
    manifest_path = shard_root / 'manifest.json'
    batch_plan_path = shard_root / 'batch_plan.json'
    output_root = Path(args.output_root).expanduser()
    ready_dates = set(discover_output_ready_dates(output_root)) if output_root.exists() else set()
    skipped_existing_dates = [date for date in dates if date in ready_dates]
    pending_dates = [date for date in dates if date not in ready_dates]
    if not args.dry_run and not pending_dates:
        result = {
            'shard_id': shard_id,
            'dates': dates,
            'skipped_existing_dates': skipped_existing_dates,
            'pending_dates': pending_dates,
            'command': [],
            'returncode': 0,
            'stdout': '',
            'stderr': '',
            'runtime_seconds': 0.0,
            'qa_path': str(qa_path),
            'catalog_path': str(catalog_path),
            'manifest_path': str(manifest_path),
            'batch_plan_path': str(batch_plan_path),
            'status': 'SKIP_EXISTING',
            'dry_run': bool(args.dry_run),
        }
        write_json(manifest_path, result)
        return result
    command = [
        sys.executable,
        str(REPO_ROOT / 'scripts' / 'build_smart_money_intraday_state.py'),
        '--minute-s3-root',
        str(args.minute_s3_root),
        '--start',
        dates[0],
        '--end',
        dates[-1],
        '--dates-file',
        str(dates_text),
        '--output-root',
        str(Path(args.output_root).expanduser()),
        '--qa-output',
        str(qa_path),
        '--catalog-output',
        str(catalog_path),
        '--manifest-output',
        str(manifest_path),
        '--batch-plan-output',
        str(batch_plan_path),
        '--lookback-trading-days',
        str(int(args.lookback_trading_days)),
        '--cutoff-volume-share',
        str(float(args.cutoff_volume_share)),
        '--min-valid-minutes',
        str(int(args.min_valid_minutes)),
        '--research-window',
        str(args.research_window),
        '--skip-existing',
        '--max-target-dates-without-override',
        str(max(1, len(dates))),
    ]
    if args.available_dates_file:
        command.extend(['--available-dates-file', str(Path(args.available_dates_file).expanduser())])
    if args.s3_local_cache:
        command.extend(['--s3-local-cache', str(Path(args.s3_local_cache).expanduser())])
    if args.dry_run:
        command.append('--plan-only')
    started = time.perf_counter()
    proc = subprocess.run(command, text=True, capture_output=True)
    elapsed = float(time.perf_counter() - started)
    return {
        'shard_id': shard_id,
        'dates': dates,
        'skipped_existing_dates': skipped_existing_dates,
        'pending_dates': pending_dates,
        'command': command,
        'returncode': int(proc.returncode),
        'stdout': proc.stdout.strip(),
        'stderr': proc.stderr.strip(),
        'runtime_seconds': elapsed,
        'qa_path': str(qa_path),
        'catalog_path': str(catalog_path),
        'manifest_path': str(manifest_path),
        'batch_plan_path': str(batch_plan_path),
        'status': 'PASS' if proc.returncode == 0 else 'FAIL',
        'dry_run': bool(args.dry_run),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.available_dates_file:
        available = read_available_dates_file(args.available_dates_file)
    else:
        available = discover_s3_partition_dates(str(args.minute_s3_root))
    if args.write_available_dates_file:
        write_available_dates_file(args.write_available_dates_file, available)
    target_dates = select_dates(available, args.start, args.end)
    shards = chunk_dates(target_dates, int(args.shard_size))
    selected_shards = shards[:args.max_shards] if args.max_shards is not None else shards
    manifest: dict[str, object] = {
        'schema_version': 'smart_money_intraday_state_batch_run_v1',
        'dataset_id': DATASET_ID,
        'source_uri': str(args.minute_s3_root),
        'target_window': {
            'start': normalize_trade_date(args.start),
            'end': normalize_trade_date(args.end),
            'available_source_date_count': len(available),
            'target_date_count': len(target_dates),
            'shard_size': int(args.shard_size),
            'total_shard_count': len(shards),
            'selected_shard_count': len(selected_shards),
            'max_shards': args.max_shards,
        },
        'output_root': str(Path(args.output_root).expanduser()),
        'work_root': str(Path(args.work_root).expanduser()),
        'dry_run': bool(args.dry_run),
        'available_dates_source': str(Path(args.available_dates_file).expanduser()) if args.available_dates_file else str(args.minute_s3_root),
        'available_dates_file_written': str(Path(args.write_available_dates_file).expanduser()) if args.write_available_dates_file else '',
        'shards': [],
        'safety': {
            'writes_active_catalog': False,
            'starts_factorforge_loop': False,
            'starts_worker': False,
            'resume_with_skip_existing': True,
        },
    }
    failures = 0
    for index, dates in enumerate(selected_shards, start=1):
        shard_id = f'shard_{index:05d}_{dates[0]}_{dates[-1]}'
        result = run_builder_for_shard(args, shard_id, dates)
        manifest['shards'].append(result)  # type: ignore[index]
        write_json(args.manifest_output, manifest)
        if result['status'] not in {'PASS', 'SKIP_EXISTING'}:
            failures += 1
            break
    manifest['status'] = 'PASS' if failures == 0 else 'FAIL'
    manifest['completed_shard_count'] = len(manifest['shards'])  # type: ignore[arg-type]
    write_json(args.manifest_output, manifest)
    print(json.dumps({
        'status': manifest['status'],
        'dataset_id': DATASET_ID,
        'selected_shard_count': len(selected_shards),
        'completed_shard_count': manifest['completed_shard_count'],
        'manifest_output': str(Path(args.manifest_output).expanduser()),
    }, ensure_ascii=False))
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
