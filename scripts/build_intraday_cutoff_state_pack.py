#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.intraday_cutoff_state_pack import (  # noqa: E402
    DATASET_ID,
    IntradayCutoffStateParams,
    build_catalog_entry,
    build_qa_summary,
    derive_intraday_cutoff_state_pack,
    normalize_trade_date,
    write_partitioned_datamart,
)


MINUTE_COLUMNS = ['ts_code', 'trade_date', 'trade_time', 'bar_time', 'open', 'high', 'low', 'close', 'vol', 'amount']


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(',') if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build intraday_cutoff_state_pack_v1 from minute_bar-like parquet.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--minute-path')
    source.add_argument('--minute-root')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--dates', default='')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--cutoff-times', default='10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00')
    parser.add_argument('--min-minutes', type=int, default=20)
    parser.add_argument('--terminal-window-minutes', type=int, default=20)
    parser.add_argument('--research-window', default='IS', choices=['IS', 'OOS', 'SMOKE'])
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--overwrite-date-partitions', action='store_true')
    parser.add_argument('--max-dates', type=int)
    parser.add_argument('--manifest-output', default='')
    return parser.parse_args(argv)


def discover_partition_dates(root: Path) -> list[str]:
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir()
    })


def partition_has_parquet(path: Path) -> bool:
    return any(child.is_file() and child.name.endswith('.parquet') for child in path.iterdir())


def discover_output_ready_dates(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir() and partition_has_parquet(path)
    })


def parse_target_dates(args: argparse.Namespace, available: list[str]) -> list[str]:
    if args.dates:
        return sorted({normalize_trade_date(item) for item in args.dates.split(',') if item.strip()})
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    return [date for date in available if start <= date <= end]


def select_resumable_dates(target_dates: list[str], output_root: Path, *, skip_existing: bool, max_dates: int | None) -> tuple[list[str], list[str], list[str], list[str]]:
    existing = discover_output_ready_dates(output_root)
    existing_set = set(existing)
    skipped = [date for date in target_dates if skip_existing and date in existing_set]
    pending = [date for date in target_dates if date not in set(skipped)]
    selected = pending[:max_dates] if max_dates is not None else pending
    remaining = pending[len(selected):]
    return selected, skipped, remaining, existing


def remove_selected_output_partitions(output_root: Path, dates: list[str]) -> list[str]:
    removed: list[str] = []
    for trade_date in dates:
        part = output_root / f'trade_date={trade_date}'
        if part.exists():
            shutil.rmtree(part)
            removed.append(trade_date)
    return removed


def read_minute_path(path: Path) -> tuple[pd.DataFrame, list[str], list[dict[str, object]]]:
    frame = pd.read_parquet(path)
    keep = [column for column in MINUTE_COLUMNS if column in frame.columns]
    frame = frame[keep]
    dates = sorted(frame['trade_date'].map(normalize_trade_date).unique().tolist()) if 'trade_date' in frame.columns else []
    return frame, dates, [{'status': 'single_file', 'path': str(path), 'minute_rows': int(len(frame))}]


def read_minute_root(root: Path, target_dates: list[str]) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, object]] = []
    missing: list[str] = []
    for trade_date in target_dates:
        part = root / f'trade_date={trade_date}'
        if not part.exists():
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 'missing_partition', 'path': str(part)})
            continue
        parquet_files = sorted(child for child in part.iterdir() if child.is_file() and child.name.endswith('.parquet'))
        if not parquet_files:
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 'missing_parquet_file', 'path': str(part)})
            continue
        try:
            frame = pd.concat([pd.read_parquet(file) for file in parquet_files], ignore_index=True)
        except Exception as exc:  # noqa: BLE001
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 'read_error', 'path': str(part), 'files': [str(file) for file in parquet_files], 'error': str(exc)})
            continue
        keep = [column for column in MINUTE_COLUMNS if column in frame.columns]
        frame = frame[keep]
        frames.append(frame)
        profile.append({'trade_date': trade_date, 'status': 'ready', 'path': str(part), 'files': [str(file) for file in parquet_files], 'minute_rows': int(len(frame))})
    if not frames:
        return pd.DataFrame(), profile, missing
    return pd.concat(frames, ignore_index=True), profile, sorted(set(missing))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    output_root = Path(args.output_root).expanduser()
    if args.max_dates is not None and int(args.max_dates) < 0:
        raise SystemExit('--max-dates must be non-negative')
    if args.minute_path:
        minute, available_dates, source_profile = read_minute_path(Path(args.minute_path).expanduser())
        target_dates = parse_target_dates(args, available_dates)
        missing_dates: list[str] = []
    else:
        minute_root = Path(args.minute_root).expanduser()
        available_dates = discover_partition_dates(minute_root)
        target_dates = parse_target_dates(args, available_dates)
        target_dates, skipped_dates, remaining_dates, existing_dates = select_resumable_dates(
            target_dates,
            output_root,
            skip_existing=bool(args.skip_existing),
            max_dates=args.max_dates,
        )
        if args.overwrite_date_partitions:
            removed_dates = remove_selected_output_partitions(output_root, target_dates)
        else:
            removed_dates = []
            if not args.skip_existing:
                conflicts = sorted(set(target_dates).intersection(existing_dates))
                if conflicts:
                    raise SystemExit(f'output partitions already exist; pass --skip-existing or --overwrite-date-partitions: {conflicts[:10]}')
        minute, source_profile, missing_dates = read_minute_root(minute_root, target_dates)
    if args.minute_path:
        target_dates, skipped_dates, remaining_dates, existing_dates = select_resumable_dates(
            target_dates,
            output_root,
            skip_existing=bool(args.skip_existing),
            max_dates=args.max_dates,
        )
        if args.overwrite_date_partitions:
            removed_dates = remove_selected_output_partitions(output_root, target_dates)
        else:
            removed_dates = []
            if not args.skip_existing:
                conflicts = sorted(set(target_dates).intersection(existing_dates))
                if conflicts:
                    raise SystemExit(f'output partitions already exist; pass --skip-existing or --overwrite-date-partitions: {conflicts[:10]}')
    params = IntradayCutoffStateParams(
        cutoff_times=tuple(split_csv(args.cutoff_times)),
        min_minutes=int(args.min_minutes),
        terminal_window_minutes=int(args.terminal_window_minutes),
        research_window=str(args.research_window),
    )
    output = derive_intraday_cutoff_state_pack(minute, params=params, target_dates=target_dates)
    write_partitioned_datamart(output, output_root)
    runtime_seconds = float(time.perf_counter() - started)
    qa = build_qa_summary(
        output,
        params=params,
        missing_dates=missing_dates,
        output_path=output_root,
        runtime_seconds=runtime_seconds,
        input_minute_row_count=int(len(minute)),
    )
    qa.update({
        'available_dates': available_dates,
        'target_dates': target_dates,
        'processed_dates': sorted(output['trade_date'].unique().tolist()) if not output.empty else [],
        'skipped_existing_dates': skipped_dates,
        'remaining_dates': remaining_dates,
        'existing_output_dates_before': existing_dates,
        'removed_output_partitions': removed_dates,
        'source_profile': source_profile,
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    })
    qa_path = Path(args.qa_output).expanduser()
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: build_catalog_entry(
                output_root,
                qa_path,
                str(qa.get('start_date') or args.start),
                str(qa.get('end_date') or args.end),
                cutoff_times=params.cutoff_times,
                research_window=params.research_window,
            )
        },
    }
    catalog_path = Path(args.catalog_output).expanduser()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    if args.manifest_output:
        manifest = {
            'verdict': qa['verdict'],
            'dataset_id': DATASET_ID,
            'output_root': str(output_root),
            'qa_output': str(qa_path),
            'catalog_output': str(catalog_path),
            'processed_dates': qa['processed_dates'],
            'skipped_existing_dates': skipped_dates,
            'remaining_dates': remaining_dates,
            'removed_output_partitions': removed_dates,
            'safety': qa['safety'],
        }
        manifest_path = Path(args.manifest_output).expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': qa['verdict'], 'dataset_id': DATASET_ID, 'row_count': qa['row_count'], 'output_root': str(output_root)}, ensure_ascii=False, indent=2))
    return 0 if qa['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
