#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
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
    OUTPUT_COLUMNS,
    PRODUCER_VERSION,
    SCHEMA_VERSION,
    SOURCE_DATASETS,
    UNIQUE_KEY,
    IntradayRetainedChipStateParams,
    build_intraday_retained_chip_state_qa,
    derive_intraday_retained_chip_state,
    normalize_trade_date,
    write_partitioned_datamart,
)


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build intraday_retained_chip_state_v1 from minute_bar and daily_basic/float-share sources.')
    minute = parser.add_mutually_exclusive_group(required=True)
    minute.add_argument('--minute-parquet')
    minute.add_argument('--minute-root')
    minute.add_argument('--minute-s3-root')
    daily = parser.add_mutually_exclusive_group(required=True)
    daily.add_argument('--daily-basic-parquet')
    daily.add_argument('--daily-basic-root')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--dates', default='')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--manifest-output', default='')
    parser.add_argument('--max-target-dates', type=int, default=5, help='Safety guard for partition-root runs; shard full-window backfills into small date batches.')
    parser.add_argument('--skip-existing', action='store_true', help='Skip target dates whose output partition already exists.')
    parser.add_argument('--allow-large-materialization', action='store_true', help='Override the partition-root max target-date guard. Use only for bounded controlled inputs.')
    parser.add_argument('--lookback-days', type=int, default=20)
    parser.add_argument('--interval-minutes', type=int, default=15)
    parser.add_argument('--cutoff-time', default='15:00:00')
    parser.add_argument('--turnover-denominator-col', default='float_share')
    parser.add_argument('--turnover-denominator-source', default='daily_basic.float_share')
    parser.add_argument('--float-share-unit', default='10k_shares')
    parser.add_argument('--minute-volume-unit', default='lot_100_shares')
    parser.add_argument('--amount-unit', default='minute_bar_amount_as_delivered')
    parser.add_argument('--volume-to-share-multiplier', type=float, default=100.0)
    parser.add_argument('--float-share-to-share-multiplier', type=float, default=10000.0)
    parser.add_argument('--is-end-date', default='20250711')
    parser.add_argument('--overwrite', action='store_true')
    return parser.parse_args(argv)


def discover_partition_dates(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir() and '=' in path.name
    })


def discover_s3_partition_dates(root: str) -> list[str]:
    import re
    import subprocess

    output = subprocess.check_output(['aws', 's3', 'ls', root.rstrip('/') + '/'], text=True)
    return sorted(set(re.findall(r'trade_date=(\d{8})/', output)))


def target_dates_from_args(args: argparse.Namespace, available_dates: list[str]) -> list[str]:
    if args.dates:
        return sorted({normalize_trade_date(item) for item in split_csv(args.dates)})
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    return [date for date in available_dates if start <= date <= end]


def filter_existing_targets(output_root: Path, target_dates: list[str], *, skip_existing: bool) -> tuple[list[str], list[str]]:
    if not skip_existing:
        return target_dates, []
    skipped = [
        date for date in target_dates
        if (output_root / f'trade_date={date}' / 'part.parquet').exists()
    ]
    remaining = [date for date in target_dates if date not in set(skipped)]
    return remaining, skipped


def source_dates_for_targets(available_dates: list[str], target_dates: list[str], lookback_days: int) -> list[str]:
    positions = {date: index for index, date in enumerate(available_dates)}
    needed: set[str] = set()
    for target in target_dates:
        if target not in positions:
            continue
        index = positions[target]
        needed.update(available_dates[max(0, index - int(lookback_days) + 1): index + 1])
    return sorted(needed)


def read_partition_root(root: Path, dates: list[str], *, dataset_name: str) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, Any]] = []
    missing: list[str] = []
    for trade_date in dates:
        part = root / f'trade_date={trade_date}'
        parquet_files = sorted(child for child in part.glob('*.parquet')) if part.exists() else []
        if not parquet_files:
            missing.append(trade_date)
            profile.append({'dataset': dataset_name, 'trade_date': trade_date, 'status': 'missing_partition_or_parquet', 'path': str(part)})
            continue
        frame = pd.concat([pd.read_parquet(file) for file in parquet_files], ignore_index=True)
        if 'trade_date' not in frame.columns:
            frame['trade_date'] = trade_date
        frames.append(frame)
        profile.append({'dataset': dataset_name, 'trade_date': trade_date, 'status': 'ready', 'path': str(part), 'file_count': len(parquet_files), 'row_count': int(len(frame))})
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), profile, missing


def read_minute_s3_root(root: str, dates: list[str]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    if not dates:
        return pd.DataFrame(), [], []
    try:
        import pyarrow as pa
        import pyarrow.dataset as ds
        import pyarrow.fs as fs
    except ImportError as exc:
        raise SystemExit('pyarrow is required for --minute-s3-root') from exc
    stripped = root.removeprefix('s3://').rstrip('/')
    bucket, _, key = stripped.partition('/')
    if not bucket or not key:
        raise SystemExit(f'invalid s3 root: {root}')
    region = fs.resolve_s3_region(bucket)
    retry_strategy = fs.AwsStandardS3RetryStrategy(max_attempts=8)
    filesystem = fs.S3FileSystem(
        region=region,
        request_timeout=60.0,
        connect_timeout=10.0,
        retry_strategy=retry_strategy,
    ) if region else fs.S3FileSystem(
        request_timeout=60.0,
        connect_timeout=10.0,
        retry_strategy=retry_strategy,
    )
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    dataset = ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning)
    columns = ['ts_code', 'trade_date', 'trade_time', 'bar_time', 'vol', 'amount']
    available = [field.name for field in dataset.schema]
    projection = [column for column in columns if column in available]
    if 'trade_date' not in projection:
        projection.append('trade_date')
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, Any]] = []
    missing: list[str] = []
    for trade_date in dates:
        try:
            table = dataset.to_table(columns=projection, filter=ds.field('trade_date') == str(trade_date))
            frame = table.to_pandas()
        except Exception as exc:
            missing.append(trade_date)
            profile.append({'dataset': 'minute_bar', 'status': 's3_read_error', 'trade_date': trade_date, 'error': str(exc)})
            continue
        if frame.empty:
            missing.append(trade_date)
            profile.append({'dataset': 'minute_bar', 'status': 'empty_s3_partition', 'trade_date': trade_date})
            continue
        frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        frames.append(frame)
        profile.append({'dataset': 'minute_bar', 'status': 's3_partition_ready', 'trade_date': trade_date, 'row_count': int(len(frame))})
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    covered = sorted(combined['trade_date'].dropna().unique().tolist()) if not combined.empty and 'trade_date' in combined.columns else []
    profile.insert(0, {
        'dataset': 'minute_bar',
        'status': 's3_dataset_filtered_by_partition',
        'root': root,
        'requested_date_count': len(dates),
        'covered_date_count': len(covered),
        'row_count': int(len(combined)),
    })
    return combined, profile, missing


def read_single(path: Path, start: str, end: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if 'trade_date' in frame.columns:
        dates = frame['trade_date'].map(normalize_trade_date)
        frame = frame[(dates >= start) & (dates <= end)].copy()
    return frame


def build_catalog(output_root: Path, qa_path: Path, start: str, end: str) -> dict[str, Any]:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: {
                'dataset_id': DATASET_ID,
                'uri': str(output_root),
                'format': 'parquet',
                'version': 'v1',
                'storage': 'local',
                'description': 'LCR retained chip state from 20 trading days of 15-minute minute_bar intervals.',
                'columns': OUTPUT_COLUMNS,
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'schema_version': SCHEMA_VERSION,
                    'producer_version': PRODUCER_VERSION,
                    'source_datasets': SOURCE_DATASETS,
                    'partition_column': 'trade_date',
                    'unique_key': UNIQUE_KEY,
                    'qa_summary_path': str(qa_path),
                    'information_set_legality': 'uses minute bars through target trade_date close only; no future returns or labels',
                    'no_future_data': True,
                    'no_future_intraday_minutes': True,
                },
                'freshness': {
                    'trade_date_min': start,
                    'trade_date_max': end,
                },
            }
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    output_root = Path(args.output_root).expanduser()
    if output_root.exists() and any(output_root.iterdir()) and not args.skip_existing:
        if not args.overwrite:
            raise SystemExit(f'output root already exists and is not empty: {output_root}; pass --overwrite')
        shutil.rmtree(output_root)

    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    target_dates: list[str]
    source_profile: list[dict[str, Any]] = []
    missing_source_dates: dict[str, list[str]] = {'minute_bar': [], 'daily_basic': []}
    skipped_existing_dates: list[str] = []
    if args.minute_parquet:
        minute = read_single(Path(args.minute_parquet).expanduser(), start, end)
        available_dates = sorted(minute['trade_date'].map(normalize_trade_date).unique().tolist()) if 'trade_date' in minute.columns else []
        target_dates = target_dates_from_args(args, available_dates)
        target_dates, skipped_existing_dates = filter_existing_targets(output_root, target_dates, skip_existing=bool(args.skip_existing))
        source_profile.append({'dataset': 'minute_bar', 'status': 'single_file', 'path': str(Path(args.minute_parquet).expanduser()), 'row_count': int(len(minute))})
    elif args.minute_root:
        minute_root = Path(args.minute_root).expanduser()
        available_dates = discover_partition_dates(minute_root)
        target_dates = target_dates_from_args(args, available_dates)
        target_dates, skipped_existing_dates = filter_existing_targets(output_root, target_dates, skip_existing=bool(args.skip_existing))
        if len(target_dates) > int(args.max_target_dates) and not args.allow_large_materialization:
            raise SystemExit(
                f'target date count {len(target_dates)} exceeds --max-target-dates={args.max_target_dates}; '
                'shard the worker run or pass --allow-large-materialization for a controlled bounded input'
            )
        source_dates = source_dates_for_targets(available_dates, target_dates, int(args.lookback_days))
        minute, profile, missing = read_partition_root(minute_root, source_dates, dataset_name='minute_bar')
        source_profile.extend(profile)
        missing_source_dates['minute_bar'] = missing
    else:
        available_dates = discover_s3_partition_dates(str(args.minute_s3_root))
        target_dates = target_dates_from_args(args, available_dates)
        target_dates, skipped_existing_dates = filter_existing_targets(output_root, target_dates, skip_existing=bool(args.skip_existing))
        if len(target_dates) > int(args.max_target_dates) and not args.allow_large_materialization:
            raise SystemExit(
                f'target date count {len(target_dates)} exceeds --max-target-dates={args.max_target_dates}; '
                'shard the worker run or pass --allow-large-materialization for a controlled bounded input'
            )
        source_dates = source_dates_for_targets(available_dates, target_dates, int(args.lookback_days))
        minute, profile, missing = read_minute_s3_root(str(args.minute_s3_root), source_dates)
        source_profile.extend(profile)
        missing_source_dates['minute_bar'] = missing

    if args.daily_basic_parquet:
        daily_basic = read_single(Path(args.daily_basic_parquet).expanduser(), start, end)
        source_profile.append({'dataset': 'daily_basic', 'status': 'single_file', 'path': str(Path(args.daily_basic_parquet).expanduser()), 'row_count': int(len(daily_basic))})
    else:
        daily_root = Path(args.daily_basic_root).expanduser()
        daily_dates = source_dates_for_targets(discover_partition_dates(daily_root), target_dates, int(args.lookback_days))
        daily_basic, profile, missing = read_partition_root(daily_root, daily_dates, dataset_name='daily_basic')
        source_profile.extend(profile)
        missing_source_dates['daily_basic'] = missing

    params = IntradayRetainedChipStateParams(
        lookback_days=int(args.lookback_days),
        interval_minutes=int(args.interval_minutes),
        cutoff_time=str(args.cutoff_time),
        turnover_denominator_col=str(args.turnover_denominator_col),
        turnover_denominator_source=str(args.turnover_denominator_source),
        float_share_unit=str(args.float_share_unit),
        minute_volume_unit=str(args.minute_volume_unit),
        amount_unit=str(args.amount_unit),
        volume_to_share_multiplier=float(args.volume_to_share_multiplier),
        float_share_to_share_multiplier=float(args.float_share_to_share_multiplier),
        is_end_date=str(args.is_end_date),
    )
    state = derive_intraday_retained_chip_state(minute, daily_basic, trade_dates=target_dates, params=params)
    write_partitioned_datamart(state, output_root)
    runtime_seconds = float(time.perf_counter() - started)
    qa = build_intraday_retained_chip_state_qa(state, expected_dates=target_dates, output_path=output_root, runtime_seconds=runtime_seconds)
    qa.update({
        'target_dates': target_dates,
        'skipped_existing_dates': skipped_existing_dates,
        'input_row_count': {'minute_bar': int(len(minute)), 'daily_basic': int(len(daily_basic))},
        'missing_source_dates': missing_source_dates,
        'source_profile': source_profile,
        'builder_parameters': vars(params),
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
            'requires_sharded_full_window_dispatch': True,
        },
    })
    if any(missing_source_dates.values()):
        qa['verdict'] = 'BLOCK'
        qa.setdefault('issues', []).append('missing_source_dates_nonempty')
    qa_path = Path(args.qa_output).expanduser()
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    catalog = build_catalog(output_root, qa_path, str(qa.get('start_date') or start), str(qa.get('end_date') or end))
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
            'processed_dates': qa['covered_dates'],
            'target_dates': target_dates,
            'missing_source_dates': missing_source_dates,
            'safety': qa['safety'],
        }
        manifest_path = Path(args.manifest_output).expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': qa['verdict'], 'dataset_id': DATASET_ID, 'row_count': qa['row_count'], 'output_root': str(output_root)}, ensure_ascii=False))
    return 0 if qa['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
