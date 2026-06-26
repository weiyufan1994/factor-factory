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

from factor_factory.data_api.intraday_retained_chip_state import (  # noqa: E402
    DATASET_ID,
    IntradayRetainedChipStateParams,
    build_intraday_retained_chip_state_qa,
    derive_intraday_retained_chip_state_from_intervals,
    normalize_trade_date,
    write_partitioned_datamart,
)


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build LCR retained chip state from precomputed interval base.')
    parser.add_argument('--interval-root', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--dates', default='')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--manifest-output', default='')
    parser.add_argument('--lookback-days', type=int, default=20)
    parser.add_argument('--max-target-dates', type=int, default=20)
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    return parser.parse_args(argv)


def discover_dates(root: Path) -> list[str]:
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir() and '=' in path.name
    })


def target_dates(args: argparse.Namespace, available: list[str]) -> list[str]:
    if args.dates:
        return sorted({normalize_trade_date(item) for item in split_csv(args.dates)})
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    return [date for date in available if start <= date <= end]


def source_dates_for_targets(available: list[str], targets: list[str], lookback: int) -> list[str]:
    positions = {date: index for index, date in enumerate(available)}
    needed: set[str] = set()
    for target in targets:
        if target not in positions:
            continue
        idx = positions[target]
        needed.update(available[max(0, idx - int(lookback) + 1): idx + 1])
    return sorted(needed)


def read_interval_root(root: Path, dates: list[str]) -> pd.DataFrame:
    frames = []
    for date in dates:
        part = root / f'trade_date={date}'
        files = sorted(part.glob('*.parquet')) if part.exists() else []
        if not files:
            continue
        frame = pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)
        if 'trade_date' not in frame.columns:
            frame['trade_date'] = date
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    interval_root = Path(args.interval_root).expanduser()
    output_root = Path(args.output_root).expanduser()
    if output_root.exists() and any(output_root.iterdir()) and not args.skip_existing:
        if not args.overwrite:
            raise SystemExit(f'output root already exists and is not empty: {output_root}; pass --overwrite')
        shutil.rmtree(output_root)
    available = discover_dates(interval_root)
    targets = target_dates(args, available)
    if args.skip_existing:
        targets = [date for date in targets if not (output_root / f'trade_date={date}' / 'part.parquet').exists()]
    if len(targets) > int(args.max_target_dates):
        raise SystemExit(f'target dates {len(targets)} exceeds --max-target-dates={args.max_target_dates}')
    source_dates = source_dates_for_targets(available, targets, int(args.lookback_days))
    intervals = read_interval_root(interval_root, source_dates)
    params = IntradayRetainedChipStateParams(lookback_days=int(args.lookback_days))
    state = derive_intraday_retained_chip_state_from_intervals(intervals, trade_dates=targets, params=params)
    if not state.empty:
        write_partitioned_datamart(state, output_root)
    qa = build_intraday_retained_chip_state_qa(state, expected_dates=targets, output_path=output_root, runtime_seconds=float(time.perf_counter() - started))
    qa.update({
        'input_interval_rows': int(len(intervals)),
        'source_dates': source_dates,
        'target_dates': targets,
        'skipped_existing': args.skip_existing,
        'safety': {'starts_worker': False, 'writes_active_catalog': False, 'writes_factorforge_artifacts': False},
    })
    qa_path = Path(args.qa_output).expanduser()
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {DATASET_ID: {'dataset_id': DATASET_ID, 'uri': str(output_root), 'format': 'parquet', 'storage': 'local', 'partition_columns': ['trade_date']}},
    }
    catalog_path = Path(args.catalog_output).expanduser()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    if args.manifest_output:
        manifest_path = Path(args.manifest_output).expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({'verdict': qa['verdict'], 'dataset_id': DATASET_ID, 'output_root': str(output_root), 'qa_output': str(qa_path)}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': qa['verdict'], 'row_count': qa['row_count'], 'date_count': qa['date_count']}, ensure_ascii=False))
    return 0 if qa['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
