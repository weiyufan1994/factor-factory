#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api import DataApiClient, DataQuery  # noqa: E402
from factor_factory.data_api.value_occupation import (  # noqa: E402
    DATASET_ID,
    ValueOccupationParams,
    build_catalog_entry,
    build_qa_summary,
    derive_intraday_value_occupation_state,
    normalize_trade_date,
)


SOURCE_FIELDS = ['trade_time', 'open', 'high', 'low', 'close', 'vol', 'amount']


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Shard backfill intraday_value_occupation_state_v1 to S3.')
    ap.add_argument('--source-catalog', required=True)
    ap.add_argument('--minute-dataset', default='minute_bar')
    ap.add_argument('--expected-dates-file', required=True)
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20250711')
    ap.add_argument('--target-dates', help='Comma-separated target dates. Overrides index range.')
    ap.add_argument('--start-index', type=int, default=0, help='0-based index into filtered expected dates.')
    ap.add_argument('--end-index', type=int, help='Exclusive index into filtered expected dates.')
    ap.add_argument('--batch-size', type=int, default=5)
    ap.add_argument('--output-root', default='/tmp/factorforge_intraday_value_occupation_state_v1_backfill')
    ap.add_argument('--parquet-s3-uri', default='s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1')
    ap.add_argument('--qa-output', default='/tmp/factorforge_intraday_value_occupation_state_v1_backfill/backfill_summary.json')
    ap.add_argument('--catalog-output', default='/tmp/factorforge_intraday_value_occupation_state_v1_backfill/catalog.json')
    ap.add_argument('--proof-s3-prefix', default='s3://yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1')
    ap.add_argument('--skip-upload', action='store_true')
    ap.add_argument('--cutoff-time', default='14:50:00')
    ap.add_argument('--lookback-days', type=int, default=20)
    ap.add_argument('--bin-width-bps', type=float, default=20.0)
    ap.add_argument('--value-area-mass', type=float, default=0.70)
    ap.add_argument('--near-band-bps', type=float, default=300.0)
    ap.add_argument('--min-minutes', type=int, default=20)
    return ap.parse_args()


def read_expected_dates(path: str | Path, start: str, end: str) -> list[str]:
    raw = Path(path).expanduser().read_text(encoding='utf-8').splitlines()
    start_date = normalize_trade_date(start)
    end_date = normalize_trade_date(end)
    return sorted({date for date in (normalize_trade_date(item) for item in raw if item.strip()) if start_date <= date <= end_date})


def select_target_dates(args: argparse.Namespace, expected_dates: list[str]) -> list[str]:
    if args.target_dates:
        allowed = set(expected_dates)
        return [date for date in (normalize_trade_date(item) for item in args.target_dates.split(',') if item.strip()) if date in allowed]
    end_index = args.end_index if args.end_index is not None else len(expected_dates)
    return expected_dates[args.start_index:end_index]


def batches(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        raise ValueError('--batch-size must be positive')
    return [items[idx: idx + size] for idx in range(0, len(items), size)]


def upload_tree(local_root: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'sync', str(local_root), s3_uri.rstrip('/'), '--only-show-errors'], check=True)


def upload_file(local_path: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'cp', str(local_path), s3_uri, '--only-show-errors'], check=True)


def write_trade_date_partitions(frame: pd.DataFrame, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        return
    for trade_date, group in frame.groupby('trade_date', sort=True, observed=True):
        part_dir = output_root / f'trade_date={trade_date}'
        if part_dir.exists():
            for old in part_dir.glob('*.parquet'):
                old.unlink()
        part_dir.mkdir(parents=True, exist_ok=True)
        group.drop(columns=['trade_date']).to_parquet(part_dir / 'part-000.parquet', index=False)


def source_start_for_batch(batch: list[str], expected_dates: list[str], lookback_days: int) -> str:
    first = batch[0]
    idx = expected_dates.index(first)
    return expected_dates[max(0, idx - lookback_days + 1)]


def fetch_source_minutes(catalog_path: str | Path, dataset_id: str, start: str, end: str) -> tuple[pd.DataFrame, dict[str, object]]:
    started = time.perf_counter()
    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(dataset_id, start, end, 'a_share_all', SOURCE_FIELDS, frequency='1min')
    )
    elapsed = time.perf_counter() - started
    if result.status == 'blocked':
        raise RuntimeError(f'source minute read blocked: {result.blocked_reason}')
    return result.frame, {
        'status': result.status,
        'source_uri': result.source.uri,
        'source_backend': result.source.backend,
        'start': start,
        'end': end,
        'row_count': int(result.coverage.row_count),
        'date_count': int(result.coverage.date_count),
        'ticker_count': int(result.coverage.ticker_count),
        'elapsed_seconds': elapsed,
    }


def write_catalog(catalog_output: Path, catalog_uri: str | Path, qa_output: Path, start: str, end: str) -> None:
    payload = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: build_catalog_entry(catalog_uri, qa_output, start, end),
        },
    }
    catalog_output.parent.mkdir(parents=True, exist_ok=True)
    catalog_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    args = parse_args()
    run_started = time.perf_counter()
    expected_dates = read_expected_dates(args.expected_dates_file, args.start, args.end)
    target_dates = select_target_dates(args, expected_dates)
    params = ValueOccupationParams(
        lookback_days=args.lookback_days,
        cutoff_time=args.cutoff_time,
        bin_width_bps=args.bin_width_bps,
        value_area_mass=args.value_area_mass,
        near_band_bps=args.near_band_bps,
        min_minutes=args.min_minutes,
    )
    output_root = Path(args.output_root).expanduser()
    shard_root = output_root / f'shard_{target_dates[0]}_{target_dates[-1]}' if target_dates else output_root / 'empty_shard'
    shard_root.mkdir(parents=True, exist_ok=True)
    batch_summaries: list[dict[str, object]] = []
    all_frames: list[pd.DataFrame] = []
    source_profiles: list[dict[str, object]] = []
    missing_output_dates: list[str] = []

    for idx, batch in enumerate(batches(target_dates, args.batch_size), start=1):
        batch_started = time.perf_counter()
        source_start = source_start_for_batch(batch, expected_dates, args.lookback_days)
        source_end = batch[-1]
        minute, source_profile = fetch_source_minutes(args.source_catalog, args.minute_dataset, source_start, source_end)
        source_profiles.append(source_profile)
        state = derive_intraday_value_occupation_state(
            minute,
            params,
            target_dates=batch,
            calendar_dates=expected_dates,
        )
        produced_dates = set(state['trade_date'].astype(str).unique()) if not state.empty else set()
        missing = [date for date in batch if date not in produced_dates]
        missing_output_dates.extend(missing)
        write_trade_date_partitions(state, shard_root)
        if not args.skip_upload and not state.empty:
            upload_tree(shard_root, args.parquet_s3_uri)
        all_frames.append(state)
        batch_summaries.append({
            'batch_index': idx,
            'target_dates': batch,
            'source_start': source_start,
            'source_end': source_end,
            'input_minute_row_count': int(len(minute)),
            'output_row_count': int(len(state)),
            'output_date_count': int(state['trade_date'].nunique()) if not state.empty else 0,
            'output_ticker_count': int(state['ts_code'].nunique()) if not state.empty else 0,
            'missing_output_dates': missing,
            'runtime_seconds': time.perf_counter() - batch_started,
        })

    full = pd.concat(all_frames, ignore_index=True, sort=False) if all_frames else pd.DataFrame()
    catalog_uri: str | Path = shard_root if args.skip_upload else args.parquet_s3_uri
    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()
    write_catalog(catalog_output, catalog_uri, qa_output, args.start, args.end)
    qa = build_qa_summary(
        full,
        params=params,
        source_min_trade_date=source_profiles[0]['start'] if source_profiles else None,
        source_max_trade_date=source_profiles[-1]['end'] if source_profiles else None,
        missing_dates=sorted(set(missing_output_dates)),
        output_path=shard_root,
        catalog_path=catalog_output,
        runtime_seconds=time.perf_counter() - run_started,
        input_minute_row_count=sum(int(item['row_count']) for item in source_profiles),
        source_profile=source_profiles,
    )
    qa['expected_date_count'] = len(expected_dates)
    qa['target_date_count'] = len(target_dates)
    qa['target_dates_start'] = target_dates[0] if target_dates else None
    qa['target_dates_end'] = target_dates[-1] if target_dates else None
    qa['batch_size'] = args.batch_size
    qa['batch_summaries'] = batch_summaries
    qa['catalog_uri'] = str(catalog_uri)
    qa['parquet_s3_uri'] = None if args.skip_upload else args.parquet_s3_uri
    qa['proof_s3_prefix'] = None if args.skip_upload else args.proof_s3_prefix
    qa_output.parent.mkdir(parents=True, exist_ok=True)
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not args.skip_upload:
        prefix = args.proof_s3_prefix.rstrip('/')
        upload_file(qa_output, f'{prefix}/shards/{target_dates[0]}_{target_dates[-1]}.qa.json')
        upload_file(catalog_output, f'{prefix}/catalog.json')
    print(json.dumps({
        'verdict': qa['verdict'],
        'dataset_id': DATASET_ID,
        'target_date_count': qa['target_date_count'],
        'target_dates_start': qa['target_dates_start'],
        'target_dates_end': qa['target_dates_end'],
        'row_count': qa['row_count'],
        'date_count': qa['date_count'],
        'ticker_count': qa['ticker_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'missing_dates': qa['missing_dates'],
        'qa_output': str(qa_output),
        'catalog_output': str(catalog_output),
        'catalog_uri': qa['catalog_uri'],
    }, ensure_ascii=False, indent=2))
    return 0 if qa['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
