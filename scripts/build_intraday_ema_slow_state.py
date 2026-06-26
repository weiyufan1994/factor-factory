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

from factor_factory.data_api.intraday_ema_slow_state import (  # noqa: E402
    DATASET_ID,
    IntradayEmaSlowStateParams,
    build_catalog_entry,
    build_intraday_ema_slow_state_qa,
    derive_intraday_ema_slow_state,
    normalize_trade_date,
    write_partitioned_datamart,
)


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build intraday_ema_slow_state_v1 from an accepted intraday cutoff source datamart.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input-parquet')
    source.add_argument('--input-root')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--dates', default='')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--cutoff-times', default='14:50:00')
    parser.add_argument('--lambdas', default='0.70,0.85,0.93')
    parser.add_argument('--signal-col', default='v19d_score')
    parser.add_argument('--is-end-date', default='20250711')
    parser.add_argument('--operator-backend', default='array_grouped')
    parser.add_argument('--max-workers', type=int)
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--manifest-output', default='')
    return parser.parse_args(argv)


def discover_partition_dates(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir()
    })


def parse_target_dates(args: argparse.Namespace, available_dates: list[str]) -> list[str]:
    if args.dates:
        return sorted({normalize_trade_date(item) for item in split_csv(args.dates)})
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    return [date for date in available_dates if start <= date <= end]


def read_input_root(root: Path, dates: list[str]) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, object]] = []
    missing: list[str] = []
    for trade_date in dates:
        part = root / f'trade_date={trade_date}'
        parquet_files = sorted(child for child in part.iterdir() if child.is_file() and child.name.endswith('.parquet')) if part.exists() else []
        if not parquet_files:
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 'missing_partition_or_parquet', 'path': str(part)})
            continue
        frame = pd.concat([pd.read_parquet(file) for file in parquet_files], ignore_index=True)
        if 'trade_date' not in frame.columns:
            frame['trade_date'] = trade_date
        frames.append(frame)
        profile.append({'trade_date': trade_date, 'status': 'ready', 'path': str(part), 'files': [str(file) for file in parquet_files], 'row_count': int(len(frame))})
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), profile, missing


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    output_root = Path(args.output_root).expanduser()
    if output_root.exists() and any(output_root.iterdir()):
        if not args.overwrite:
            raise SystemExit(f'output root already exists and is not empty: {output_root}; pass --overwrite')
        shutil.rmtree(output_root)

    if args.input_parquet:
        source = pd.read_parquet(Path(args.input_parquet).expanduser())
        if 'trade_date' not in source.columns:
            raise SystemExit('input parquet requires trade_date column')
        available_dates = sorted(source['trade_date'].map(normalize_trade_date).unique().tolist())
        target_dates = parse_target_dates(args, available_dates)
        source = source[source['trade_date'].map(normalize_trade_date).isin(set(target_dates))].copy()
        source_profile = [{'status': 'single_file', 'path': str(Path(args.input_parquet).expanduser()), 'row_count': int(len(source))}]
        missing_dates: list[str] = []
    else:
        input_root = Path(args.input_root).expanduser()
        available_dates = discover_partition_dates(input_root)
        target_dates = parse_target_dates(args, available_dates)
        source, source_profile, missing_dates = read_input_root(input_root, target_dates)

    params = IntradayEmaSlowStateParams(
        lambdas=tuple(float(item) for item in split_csv(args.lambdas)),
        cutoff_times=tuple(split_csv(args.cutoff_times)),
        signal_col=str(args.signal_col),
        is_end_date=str(args.is_end_date),
        operator_backend=str(args.operator_backend),
        max_workers=args.max_workers,
    )
    state = derive_intraday_ema_slow_state(source, params=params)
    write_partitioned_datamart(state, output_root)
    runtime_seconds = float(time.perf_counter() - started)
    qa = build_intraday_ema_slow_state_qa(state, params=params, output_path=output_root, runtime_seconds=runtime_seconds)
    qa.update({
        'available_dates': available_dates,
        'target_dates': target_dates,
        'processed_dates': sorted(state['trade_date'].unique().tolist()) if not state.empty else [],
        'missing_dates': missing_dates,
        'source_profile': source_profile,
        'input_row_count': int(len(source)),
        'operator_backend': str(state.attrs.get('operator_backend') or args.operator_backend),
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    })
    if missing_dates:
        qa['verdict'] = 'BLOCK'
        qa.setdefault('issues', []).append('missing_dates_nonempty')
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
                params=params,
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
            'missing_dates': missing_dates,
            'safety': qa['safety'],
        }
        manifest_path = Path(args.manifest_output).expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': qa['verdict'], 'dataset_id': DATASET_ID, 'row_count': qa['row_count'], 'output_root': str(output_root)}, ensure_ascii=False))
    return 0 if qa['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
