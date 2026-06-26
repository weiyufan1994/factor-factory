#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.daily_alpha360_lite import (  # noqa: E402
    DailyAlpha360LiteParams,
    build_daily_alpha360_lite,
    build_daily_alpha360_lite_qa,
)


def _normalize_date(value: str) -> str:
    return str(value).replace('-', '')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a read-only daily Alpha360-lite feature parquet and QA proof.')
    parser.add_argument('--input-parquet', required=True)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--output-parquet')
    output.add_argument('--output-root')
    parser.add_argument('--partitioned', action='store_true', help='Write hive-style trade_date partitions under --output-root.')
    parser.add_argument('--overwrite', action='store_true', help='Remove an existing --output-root before writing partitioned output.')
    parser.add_argument('--skip-existing', action='store_true', help='For partitioned output, skip trade_date partitions already present under --output-root.')
    parser.add_argument('--max-dates', type=int, help='For partitioned output, process at most this many pending output trade dates.')
    parser.add_argument('--manifest-output', help='Optional build manifest path for resumable partitioned runs.')
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--lookback', type=int, default=60)
    parser.add_argument('--start', help='Optional inclusive output start date; reads a lookback buffer before this date when possible.')
    parser.add_argument('--end', help='Optional inclusive output end date.')
    parser.add_argument('--volume-col', default='vol')
    parser.add_argument('--amount-col', default='amount')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    params = DailyAlpha360LiteParams(
        lookback=int(args.lookback),
        volume_col=str(args.volume_col),
        amount_col=str(args.amount_col),
    )
    source = pd.read_parquet(Path(args.input_parquet).expanduser())
    if 'trade_date' not in source.columns:
        raise SystemExit('daily Alpha360-lite build requires trade_date column')
    normalized_dates = source['trade_date'].map(lambda x: pd.to_datetime(str(x)).strftime('%Y%m%d') if '-' in str(x) else str(x).replace('.0', '').zfill(8))
    start = _normalize_date(args.start) if args.start else str(normalized_dates.min())
    end = _normalize_date(args.end) if args.end else str(normalized_dates.max())
    all_dates = sorted(normalized_dates.unique().tolist())
    available_dates = [date for date in all_dates if start <= date <= end]
    output_root = Path(args.output_root).expanduser() if args.output_root else None
    skipped_dates: list[str] = []
    pending_dates = list(available_dates)
    if output_root is not None and args.skip_existing:
        skipped_dates = [
            date for date in pending_dates
            if (output_root / f'trade_date={date}').exists()
        ]
        pending_dates = [date for date in pending_dates if date not in set(skipped_dates)]
    selected_dates = pending_dates[: int(args.max_dates)] if args.max_dates else pending_dates
    remaining_dates = pending_dates[len(selected_dates):]
    if not selected_dates:
        source = source.iloc[0:0].copy()
    else:
        first_idx = next((idx for idx, date in enumerate(all_dates) if date >= selected_dates[0]), 0)
        buffered_start = all_dates[max(0, first_idx - int(args.lookback) + 1)]
        source = source[(normalized_dates >= buffered_start) & (normalized_dates <= selected_dates[-1])].copy()
    features = build_daily_alpha360_lite(source, params=params)
    if selected_dates:
        dates = features['trade_date'].astype(str)
        features = features[dates.isin(set(selected_dates))].reset_index(drop=True)
    qa = build_daily_alpha360_lite_qa(features, params=params)
    qa['input_parquet'] = str(Path(args.input_parquet).expanduser())
    if args.output_root:
        qa['output_root'] = str(output_root)
        qa['partition_column'] = 'trade_date' if args.partitioned else None
    else:
        qa['output_parquet'] = str(Path(args.output_parquet).expanduser())
        qa['partition_column'] = None
    qa['requested_dates'] = available_dates
    qa['processed_dates'] = selected_dates
    qa['skipped_dates'] = skipped_dates
    qa['remaining_dates'] = remaining_dates
    qa['resume_policy'] = {
        'skip_existing': bool(args.skip_existing),
        'max_dates': int(args.max_dates) if args.max_dates else None,
    }
    qa['safety'] = {
        'starts_backfill': False,
        'writes_catalog': False,
        'writes_datamart': False,
        'production_loop_side_effect': False,
    }

    qa_path = Path(args.qa_output).expanduser()
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    if args.output_root:
        if not args.partitioned:
            raise SystemExit('--output-root requires --partitioned')
        if output_root.exists() and any(output_root.iterdir()):
            if args.overwrite and not args.skip_existing:
                shutil.rmtree(output_root)
            elif not args.skip_existing:
                raise SystemExit(f'output root already exists and is not empty: {output_root}; pass --overwrite or --skip-existing')
        output_root.mkdir(parents=True, exist_ok=True)
        partitions: list[dict[str, object]] = []
        for trade_date, part in features.groupby('trade_date', sort=True):
            part_dir = output_root / f'trade_date={trade_date}'
            part_dir.mkdir(parents=True, exist_ok=True)
            part_path = part_dir / 'part.parquet'
            part.drop(columns=['trade_date']).to_parquet(part_path, index=False)
            partitions.append({
                'trade_date': str(trade_date),
                'path': str(part_path),
                'row_count': int(len(part)),
                'ticker_count': int(part['ts_code'].nunique()) if 'ts_code' in part.columns else 0,
            })
        qa['partitions'] = partitions
        qa['partition_count'] = len(partitions)
    else:
        output_path = Path(args.output_parquet).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        features.to_parquet(output_path, index=False)
    if args.manifest_output:
        manifest_path = Path(args.manifest_output).expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            'verdict': qa['verdict'],
            'dataset_id': 'daily_alpha360_lite_v1',
            'output_root': str(output_root) if output_root is not None else None,
            'qa_output': str(qa_path),
            'requested_dates': available_dates,
            'processed_dates': selected_dates,
            'skipped_dates': skipped_dates,
            'remaining_dates': remaining_dates,
            'resume_policy': qa['resume_policy'],
            'safety': qa['safety'],
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if qa['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
