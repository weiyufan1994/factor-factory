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

from factor_factory.data_api.value_occupation import (  # noqa: E402
    DATASET_ID,
    ValueOccupationParams,
    build_catalog_entry,
    build_qa_summary,
    derive_intraday_value_occupation_state,
    normalize_trade_date,
    write_partitioned_datamart,
)


MINUTE_COLUMNS = ['ts_code', 'trade_date', 'trade_time', 'bar_time', 'open', 'close', 'high', 'low', 'vol', 'amount']


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build intraday_value_occupation_state_v1 from minute_bar-like parquet.')
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--minute-path', help='Single parquet file containing minute_bar-like rows.')
    source.add_argument('--minute-root', help='Hive partitioned minute root with trade_date=YYYYMMDD partitions.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20250711')
    ap.add_argument('--dates', help='Comma-separated target trade dates. Overrides --start/--end target selection.')
    ap.add_argument('--output-root', default='factorforge/data/datamart/intraday_value_occupation_state_v1')
    ap.add_argument('--parquet-s3-uri', default='s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1')
    ap.add_argument('--qa-output', default='factorforge/data/proofs/intraday_value_occupation_state_v1.qa.json')
    ap.add_argument('--catalog-output', default='factorforge/data/catalog/intraday_value_occupation_state_v1.catalog.json')
    ap.add_argument('--skip-upload', action='store_true', help='Keep catalog pointed at local staging parquet instead of uploading/registering S3.')
    ap.add_argument('--cutoff-time', default='14:50:00')
    ap.add_argument('--lookback-days', type=int, default=20)
    ap.add_argument('--bin-width-bps', type=float, default=20.0)
    ap.add_argument('--value-area-mass', type=float, default=0.70)
    ap.add_argument('--near-band-bps', type=float, default=300.0)
    ap.add_argument('--min-minutes', type=int, default=20)
    return ap.parse_args()


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


def read_single_parquet(path: Path) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    frame = pd.read_parquet(path)
    keep = [col for col in MINUTE_COLUMNS if col in frame.columns]
    frame = frame[keep]
    profile = [{'status': 'single_file', 'path': str(path), 'minute_rows': int(len(frame))}]
    return frame, profile


def read_minute_root(root: Path, target_dates: list[str], lookback_days: int) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
    available = discover_partition_dates(root)
    needed: set[str] = set()
    for target in target_dates:
        if target not in available:
            continue
        idx = available.index(target)
        needed.update(available[max(0, idx - lookback_days + 1): idx + 1])
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, object]] = []
    missing_targets = [date for date in target_dates if date not in available]
    for trade_date in sorted(needed):
        part_dir = root / f'trade_date={trade_date}'
        try:
            frame = pd.read_parquet(part_dir)
        except Exception as exc:  # noqa: BLE001
            profile.append({'trade_date': trade_date, 'status': 'read_error', 'path': str(part_dir), 'error': str(exc)})
            continue
        frames.append(frame)
        profile.append({'trade_date': trade_date, 'status': 'ready', 'path': str(part_dir), 'minute_rows': int(len(frame))})
    if not frames:
        return pd.DataFrame(), profile, missing_targets
    return pd.concat(frames, ignore_index=True), profile, missing_targets


def upload_tree(local_root: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'sync', str(local_root), s3_uri.rstrip('/'), '--only-show-errors'], check=True)


def write_catalog(path: Path, uri: str | Path, qa_output: Path, start: str, end: str) -> None:
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: build_catalog_entry(uri, qa_output, start, end),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    params = ValueOccupationParams(
        lookback_days=args.lookback_days,
        cutoff_time=args.cutoff_time,
        bin_width_bps=args.bin_width_bps,
        value_area_mass=args.value_area_mass,
        near_band_bps=args.near_band_bps,
        min_minutes=args.min_minutes,
    )

    if args.minute_path:
        minute, source_profile = read_single_parquet(Path(args.minute_path).expanduser())
        available_dates = sorted(minute['trade_date'].astype(str).map(normalize_trade_date).unique().tolist())
        target_dates = parse_dates(args.dates, args.start, args.end, available_dates)
        missing_dates: list[str] = []
    else:
        minute_root = Path(args.minute_root).expanduser()
        available_dates = discover_partition_dates(minute_root)
        target_dates = parse_dates(args.dates, args.start, args.end, available_dates)
        minute, source_profile, missing_dates = read_minute_root(minute_root, target_dates, args.lookback_days)

    state = derive_intraday_value_occupation_state(minute, params, target_dates=target_dates)
    output_root = write_partitioned_datamart(state, args.output_root)
    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()
    catalog_uri: str | Path = output_root
    if not args.skip_upload:
        upload_tree(output_root, args.parquet_s3_uri)
        catalog_uri = args.parquet_s3_uri
    write_catalog(catalog_output, catalog_uri, qa_output, args.start, args.end)

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
        source_profile=source_profile,
    )
    qa_output.parent.mkdir(parents=True, exist_ok=True)
    qa['local_output_path'] = str(output_root)
    qa['parquet_s3_uri'] = None if args.skip_upload else args.parquet_s3_uri
    qa['catalog_uri'] = str(catalog_uri)
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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
    }, ensure_ascii=False, indent=2))
    return 0 if qa['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
