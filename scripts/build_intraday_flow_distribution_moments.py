#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.flow_distribution_moments import (  # noqa: E402
    DATASET_ID,
    FlowDistributionParams,
    PREPARED_MINUTE_COLUMNS,
    build_catalog_entry,
    build_qa_summary,
    derive_intraday_flow_distribution_moments,
    derive_intraday_flow_distribution_moments_from_prepared,
    normalize_trade_date,
    write_partitioned_datamart,
)


MINUTE_COLUMNS = list(dict.fromkeys(['ts_code', 'trade_date', 'trade_time', 'bar_time', 'open', 'close', 'high', 'low', 'vol', 'amount', *PREPARED_MINUTE_COLUMNS]))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build intraday_flow_distribution_moments_v1 from minute_bar-like parquet.')
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--minute-path', help='Single parquet file containing minute_bar-like rows.')
    source.add_argument('--minute-root', help='Hive partitioned minute root with trade_date=YYYYMMDD partitions.')
    source.add_argument('--prepared-minute-root', help='Hive partitioned prepared_minute_bar_v1 root with trade_date=YYYYMMDD partitions.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20250711')
    ap.add_argument('--dates', help='Comma-separated target trade dates. Overrides --start/--end selection.')
    ap.add_argument('--source-ready-only', action='store_true', help='Only use source partitions that contain parquet data files.')
    ap.add_argument('--output-root', default='factorforge/data/datamart/intraday_flow_distribution_moments_v1')
    ap.add_argument('--parquet-s3-uri', default='s3://yufan-data-lake/factorforge/datamart/intraday_flow_distribution_moments_v1/is')
    ap.add_argument('--qa-output', default='factorforge/data/proofs/intraday_flow_distribution_moments_v1.qa.json')
    ap.add_argument('--catalog-output', default='factorforge/data/catalog/intraday_flow_distribution_moments_v1.catalog.json')
    ap.add_argument('--skip-upload', action='store_true', help='Keep catalog pointed at local staging parquet.')
    ap.add_argument('--cutoff-times', default='10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00')
    ap.add_argument('--threshold-lookback-days', default='20,60')
    ap.add_argument('--threshold-quantile', type=float, default=0.75)
    ap.add_argument('--threshold-backend', default='pandas', choices=['pandas', 'polars'])
    ap.add_argument('--min-minutes', type=int, default=20)
    ap.add_argument('--research-window', default='IS', choices=['IS', 'OOS', 'SMOKE'])
    ap.add_argument('--skip-existing', action='store_true', help='Skip output trade_date partitions that already contain parquet files.')
    ap.add_argument('--max-dates', type=int, help='Process at most this many pending target trade dates.')
    ap.add_argument('--manifest-output', help='Optional resumable build manifest path.')
    ap.add_argument('--overwrite-date-partitions', action='store_true', help='Delete selected output trade_date partitions before writing them.')
    ap.add_argument(
        '--operator-backend',
        default='vectorized',
        choices=['vectorized', 'numba', 'numba_sorted', 'mapreduce', 'mapreduce_threaded', 'process_sharded_mapreduce', 'process_sharded_vectorized', 'polars', 'reference'],
    )
    return ap.parse_args(argv)


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(',') if item.strip()]


def split_int_csv(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(',') if item.strip()]


def parse_dates(raw: str | None, start: str, end: str, available: list[str]) -> list[str]:
    if raw:
        return sorted({normalize_trade_date(token) for token in raw.split(',') if token.strip()})
    start_date = normalize_trade_date(start)
    end_date = normalize_trade_date(end)
    return [date for date in available if start_date <= date <= end_date]


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
            statuses[normalize_trade_date(path.name.split('=', 1)[1])] = partition_has_parquet_data(path)
    return statuses


def filter_source_ready_dates(dates: list[str], statuses: dict[str, bool]) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    not_ready: list[str] = []
    for trade_date in dates:
        if trade_date in statuses and not statuses[trade_date]:
            not_ready.append(trade_date)
            continue
        ready.append(trade_date)
    return ready, not_ready


def discover_output_ready_dates(root: Path) -> list[str]:
    if not root.exists():
        return []
    ready: list[str] = []
    for path in root.glob('trade_date=*'):
        if path.is_dir() and partition_has_parquet_data(path):
            ready.append(normalize_trade_date(path.name.split('=', 1)[1]))
    return sorted(set(ready))


def select_resumable_dates(
    target_dates: list[str],
    *,
    output_root: Path,
    skip_existing: bool,
    max_dates: int | None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    existing = discover_output_ready_dates(output_root)
    existing_set = set(existing)
    skipped = [date for date in target_dates if skip_existing and date in existing_set]
    pending = [date for date in target_dates if date not in set(skipped)]
    if max_dates is not None and max_dates < 0:
        raise ValueError('--max-dates must be non-negative')
    selected = pending[:max_dates] if max_dates is not None else pending
    remaining = pending[len(selected):]
    return selected, skipped, remaining, existing


def remove_selected_output_partitions(output_root: Path, selected_dates: list[str]) -> list[str]:
    removed: list[str] = []
    for trade_date in selected_dates:
        partition = output_root / f'trade_date={trade_date}'
        if partition.exists():
            shutil.rmtree(partition)
            removed.append(trade_date)
    return removed


def read_single_parquet(path: Path) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    frame = pd.read_parquet(path)
    keep = [col for col in MINUTE_COLUMNS if col in frame.columns]
    frame = frame[keep]
    return frame, [{'status': 'single_file', 'path': str(path), 'minute_rows': int(len(frame))}]


def read_minute_root(
    root: Path,
    target_dates: list[str],
    lookback_days: int,
    *,
    available_dates: list[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
    available = sorted(set(available_dates or discover_partition_dates(root)))
    needed: set[str] = set()
    targets = set(target_dates)
    missing_targets = [date for date in target_dates if date not in available]
    failed_targets: list[str] = []
    loaded_targets: set[str] = set()
    for target in target_dates:
        if target not in available:
            continue
        idx = available.index(target)
        needed.update(available[max(0, idx - lookback_days):idx + 1])
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, object]] = []
    for trade_date in sorted(needed):
        part_dir = root / f'trade_date={trade_date}'
        try:
            frame = pd.read_parquet(part_dir)
        except Exception as exc:  # noqa: BLE001
            profile.append({'trade_date': trade_date, 'status': 'read_error', 'path': str(part_dir), 'error': str(exc)})
            if trade_date in targets:
                failed_targets.append(trade_date)
            continue
        keep = [col for col in MINUTE_COLUMNS if col in frame.columns]
        frame = frame[keep]
        if trade_date in targets and not frame.empty:
            loaded_targets.add(trade_date)
        frames.append(frame)
        profile.append({'trade_date': trade_date, 'status': 'ready', 'path': str(part_dir), 'minute_rows': int(len(frame))})
    missing_targets.extend(sorted(targets - loaded_targets - set(missing_targets) - set(failed_targets)))
    missing_targets.extend(date for date in failed_targets if date not in missing_targets)
    if not frames:
        return pd.DataFrame(), profile, missing_targets
    return pd.concat(frames, ignore_index=True), profile, sorted(set(missing_targets))


def upload_tree(local_root: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'sync', str(local_root), s3_uri.rstrip('/'), '--only-show-errors'], check=True)


def write_catalog(
    path: Path,
    uri: str | Path,
    qa_output: Path,
    start: str,
    end: str,
    *,
    storage: str | None = None,
    operator_backend: str = 'vectorized',
    params: FlowDistributionParams | None = None,
) -> None:
    flow_params = params or FlowDistributionParams(operator_backend=operator_backend)
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: build_catalog_entry(
                uri,
                qa_output,
                start,
                end,
                storage=storage,
                operator_backend=operator_backend,
                threshold_lookback_days=flow_params.threshold_lookback_days,
                threshold_quantile=flow_params.threshold_quantile,
                threshold_backend=flow_params.threshold_backend,
                research_window=flow_params.research_window,
            ),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    output_root_arg = Path(args.output_root).expanduser()
    params = FlowDistributionParams(
        cutoff_times=tuple(split_csv(args.cutoff_times)),
        threshold_lookback_days=tuple(split_int_csv(args.threshold_lookback_days)),
        threshold_quantile=args.threshold_quantile,
        threshold_backend=args.threshold_backend,
        min_minutes=args.min_minutes,
        research_window=args.research_window,
        operator_backend=args.operator_backend,
    )

    read_start = time.perf_counter()
    input_dataset = 'minute_bar'
    input_minute_format = 'raw'
    input_prepared_minute_columns: list[str] = []
    source_not_ready_dates: list[str] = []
    skipped_existing_dates: list[str] = []
    remaining_dates: list[str] = []
    existing_output_dates_before: list[str] = []
    removed_output_partitions: list[str] = []
    if args.minute_path:
        minute, source_profile = read_single_parquet(Path(args.minute_path).expanduser())
        available_dates = sorted(minute['trade_date'].astype(str).map(normalize_trade_date).unique().tolist()) if 'trade_date' in minute.columns else []
        target_dates = parse_dates(args.dates, args.start, args.end, available_dates)
        missing_dates: list[str] = []
    else:
        if args.prepared_minute_root:
            input_dataset = 'prepared_minute_bar_v1'
            input_minute_format = 'prepared'
            input_prepared_minute_columns = list(PREPARED_MINUTE_COLUMNS)
            minute_root = Path(args.prepared_minute_root).expanduser()
        else:
            minute_root = Path(args.minute_root).expanduser()
        available_dates = discover_partition_dates(minute_root)
        source_not_ready_dates: list[str] = []
        if args.source_ready_only:
            available_dates, source_not_ready_dates = filter_source_ready_dates(
                available_dates,
                discover_source_ready_status(minute_root),
            )
        target_dates = parse_dates(args.dates, args.start, args.end, available_dates)
        target_dates, skipped_existing_dates, remaining_dates, existing_output_dates_before = select_resumable_dates(
            target_dates,
            output_root=output_root_arg,
            skip_existing=bool(args.skip_existing),
            max_dates=args.max_dates,
        )
        if args.overwrite_date_partitions:
            removed_output_partitions = remove_selected_output_partitions(output_root_arg, target_dates)
        elif not args.skip_existing:
            conflicting_dates = sorted(set(target_dates).intersection(existing_output_dates_before))
            if conflicting_dates:
                raise SystemExit(
                    'output partitions already exist for selected dates; pass --skip-existing or '
                    f'--overwrite-date-partitions: {conflicting_dates[:10]}'
                )
        minute, source_profile, missing_dates = read_minute_root(
            minute_root,
            target_dates,
            max(params.threshold_lookback_days),
            available_dates=available_dates,
        )
    if args.minute_path:
        target_dates, skipped_existing_dates, remaining_dates, existing_output_dates_before = select_resumable_dates(
            target_dates,
            output_root=output_root_arg,
            skip_existing=bool(args.skip_existing),
            max_dates=args.max_dates,
        )
        if args.overwrite_date_partitions:
            removed_output_partitions = remove_selected_output_partitions(output_root_arg, target_dates)
        elif not args.skip_existing:
            conflicting_dates = sorted(set(target_dates).intersection(existing_output_dates_before))
            if conflicting_dates:
                raise SystemExit(
                    'output partitions already exist for selected dates; pass --skip-existing or '
                    f'--overwrite-date-partitions: {conflicting_dates[:10]}'
                )
    read_seconds = time.perf_counter() - read_start

    compute_start = time.perf_counter()
    if input_minute_format == 'prepared':
        state = derive_intraday_flow_distribution_moments_from_prepared(minute, params, target_dates=target_dates)
    else:
        state = derive_intraday_flow_distribution_moments(minute, params, target_dates=target_dates)
    compute_seconds = time.perf_counter() - compute_start

    write_start = time.perf_counter()
    output_root = write_partitioned_datamart(state, output_root_arg)
    write_seconds = time.perf_counter() - write_start

    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()
    catalog_uri: str | Path = output_root
    catalog_storage = 'local'
    if not args.skip_upload:
        upload_tree(output_root, args.parquet_s3_uri)
        catalog_uri = args.parquet_s3_uri
        catalog_storage = 's3'
    write_catalog(catalog_output, catalog_uri, qa_output, args.start, args.end, storage=catalog_storage, operator_backend=params.operator_backend, params=params)

    qa = build_qa_summary(
        state,
        params=params,
        source_min_trade_date=min(available_dates) if available_dates else None,
        source_max_trade_date=max(available_dates) if available_dates else None,
        missing_dates=missing_dates,
        output_path=output_root,
        catalog_path=catalog_output,
        runtime_seconds=time.perf_counter() - started,
        input_minute_row_count=int(len(minute)),
        performance_profile={
            'read_seconds': read_seconds,
            'compute_seconds': compute_seconds,
            'write_seconds': write_seconds,
            'input_dataset': input_dataset,
            'input_minute_format': input_minute_format,
        },
        source_profile=source_profile,
    )
    qa['input_dataset'] = input_dataset
    qa['input_minute_format'] = input_minute_format
    qa['input_prepared_minute_columns'] = input_prepared_minute_columns
    qa['source_ready_policy'] = {
        'enabled': bool(args.source_ready_only),
        'not_ready_dates': source_not_ready_dates,
    }
    qa['source_not_ready_dates'] = source_not_ready_dates
    qa['resume_policy'] = {
        'skip_existing': bool(args.skip_existing),
        'max_dates': int(args.max_dates) if args.max_dates is not None else None,
        'overwrite_date_partitions': bool(args.overwrite_date_partitions),
    }
    qa['target_dates_selected'] = target_dates
    qa['skipped_existing_dates'] = skipped_existing_dates
    qa['remaining_dates'] = remaining_dates
    qa['existing_output_dates_before'] = existing_output_dates_before
    qa['removed_output_partitions'] = removed_output_partitions
    qa['local_output_path'] = str(output_root)
    qa['parquet_s3_uri'] = None if args.skip_upload else args.parquet_s3_uri
    qa['catalog_uri'] = str(catalog_uri)
    qa_output.parent.mkdir(parents=True, exist_ok=True)
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.manifest_output:
        manifest_path = Path(args.manifest_output).expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            'verdict': qa['verdict'],
            'dataset_id': DATASET_ID,
            'output_root': str(output_root),
            'qa_output': str(qa_output),
            'catalog_output': str(catalog_output),
            'requested_start': args.start,
            'requested_end': args.end,
            'processed_dates': target_dates,
            'skipped_existing_dates': skipped_existing_dates,
            'remaining_dates': remaining_dates,
            'missing_dates': missing_dates,
            'source_not_ready_dates': source_not_ready_dates,
            'resume_policy': qa['resume_policy'],
            'source_ready_policy': qa['source_ready_policy'],
            'removed_output_partitions': removed_output_partitions,
            'safety': {
                'starts_worker': False,
                'sends_ssm_command': False,
                'writes_active_catalog': False,
                'writes_factorforge_artifacts': False,
                'production_loop_side_effect': False,
            },
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'verdict': qa['verdict'],
        'dataset_id': qa['dataset_id'],
        'output_path': qa['output_path'],
        'qa_output': str(qa_output),
        'catalog_output': str(catalog_output),
        'catalog_uri': qa['catalog_uri'],
        'parquet_s3_uri': qa['parquet_s3_uri'],
        'row_count': qa['row_count'],
        'date_count': qa['date_count'],
        'ticker_count': qa['ticker_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'missing_dates': qa['missing_dates'],
        'source_not_ready_dates': qa['source_not_ready_dates'],
        'skipped_existing_dates': qa['skipped_existing_dates'],
        'remaining_dates': qa['remaining_dates'],
        'performance_profile': qa['performance_profile'],
        'operator_backend': qa['operator_backend'],
        'realized_operator_backend': qa['realized_operator_backend'],
        'input_dataset': qa['input_dataset'],
        'input_minute_format': qa['input_minute_format'],
    }, ensure_ascii=False, indent=2))
    return 0 if qa['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
