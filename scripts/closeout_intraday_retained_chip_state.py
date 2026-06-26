#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
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
    normalize_trade_date,
)


REPRESENTATIVE_DATES = ('20160104', '20200102', '20250711')
FORBIDDEN_FIELD_TOKENS = (
    'ic',
    'rankic',
    'future_return',
    'next_return',
    'label',
    'target',
    'style_neutral',
    'composite_score',
)


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def discover_local_dates(root: Path) -> list[str]:
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir() and '=' in path.name
    })


def discover_s3_dates(root: str) -> list[str]:
    output = subprocess.check_output(['aws', 's3', 'ls', root.rstrip('/') + '/'], text=True)
    dates: list[str] = []
    for line in output.splitlines():
        token = line.rsplit(maxsplit=1)[-1].strip('/')
        if token.startswith('trade_date='):
            dates.append(normalize_trade_date(token.split('=', 1)[1]))
    return sorted(set(dates))


def expected_dates_from_daily_basic(root: Path, start: str, end: str) -> list[str]:
    return [date for date in discover_local_dates(root) if start <= date <= end]


def _s3_dataset(root: str):
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.fs as fs

    stripped = root.removeprefix('s3://').rstrip('/')
    bucket, _, key = stripped.partition('/')
    if not bucket or not key:
        raise ValueError(f'invalid s3 root: {root}')
    region = fs.resolve_s3_region(bucket)
    filesystem = fs.S3FileSystem(region=region) if region else fs.S3FileSystem()
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    return ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning), ds


def read_s3_date(root: str, trade_date: str, columns: list[str] | None = None) -> pd.DataFrame:
    dataset, ds = _s3_dataset(root)
    available = {field.name for field in dataset.schema}
    projection = [column for column in (columns or list(available)) if column in available]
    if 'trade_date' not in projection:
        projection.append('trade_date')
    table = dataset.to_table(columns=projection, filter=ds.field('trade_date') == str(trade_date))
    frame = table.to_pandas()
    if 'trade_date' in frame.columns:
        frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
    return frame


def build_catalog(
    root: str,
    qa_path: str,
    start: str,
    end: str,
    row_count: int,
    date_count: int,
    ticker_count: int,
    *,
    research_window: str = 'IS',
) -> dict[str, Any]:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: {
                'dataset_id': DATASET_ID,
                'uri': root.rstrip('/') + '/',
                'format': 'parquet',
                'version': 'v1',
                'storage': 's3' if root.startswith('s3://') else 'local',
                'description': 'LCR retained chip state from 20 trading days of 15-minute minute_bar intervals.',
                'columns': OUTPUT_COLUMNS,
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'freshness': {
                    'trade_date_min': start,
                    'trade_date_max': end,
                    'rows': int(row_count),
                    'tickers': int(ticker_count),
                    'trade_dates': int(date_count),
                },
                'metadata': {
                    'schema_version': SCHEMA_VERSION,
                    'producer_version': PRODUCER_VERSION,
                    'source_datasets': SOURCE_DATASETS,
                    'partition_column': 'trade_date',
                    'unique_key': UNIQUE_KEY,
                    'sort_keys': ['trade_date', 'ts_code'],
                    'lookback_days': 20,
                    'interval_minutes': 15,
                    'cutoff_time': '15:00:00',
                    'turnover_denominator_source': 'daily_basic.float_share',
                    'qa_summary_path': qa_path,
                    'information_set_legality': 'uses minute bars through target trade_date close only; no future returns or labels',
                    'no_future_data': True,
                    'no_future_intraday_minutes': True,
                    'research_window': research_window,
                },
            }
        },
    }


def validate_frame(frame: pd.DataFrame, trade_date: str) -> dict[str, Any]:
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    forbidden_columns = [
        column for column in frame.columns
        if any(token in column.lower() for token in FORBIDDEN_FIELD_TOKENS)
    ]
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if all(column in frame.columns for column in UNIQUE_KEY) else 0
    issues: list[str] = []
    if frame.empty:
        issues.append('empty_partition')
    if missing_columns:
        issues.append('missing_expected_columns')
    if forbidden_columns:
        issues.append('forbidden_alpha_or_label_columns')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if 'lcr_raw' in frame.columns and not frame.empty:
        valid_lcr = pd.to_numeric(frame['lcr_raw'], errors='coerce').dropna()
        if not valid_lcr.between(0.0, 1.0).all():
            issues.append('lcr_raw_outside_0_1')
    for flag in ['no_future_data', 'no_future_intraday_minutes']:
        if flag in frame.columns and not frame.empty and not bool(frame[flag].all()):
            issues.append(f'{flag}_not_true')
    return {
        'trade_date': trade_date,
        'row_count': int(len(frame)),
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'duplicate_key_count': duplicate_key_count,
        'research_windows': sorted(frame['research_window'].dropna().astype(str).unique().tolist()) if 'research_window' in frame.columns and not frame.empty else [],
        'missing_columns': missing_columns,
        'forbidden_columns': forbidden_columns,
        'issues': issues,
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Close out intraday_retained_chip_state_v1 S3 production datamart.')
    parser.add_argument('--datamart-root', required=True)
    parser.add_argument('--daily-basic-root', required=True, help='Local worker daily_basic parquet root used as IS trading-date calendar.')
    parser.add_argument('--start', default='20160104')
    parser.add_argument('--end', default='20250711')
    parser.add_argument('--representative-dates', default=','.join(REPRESENTATIVE_DATES))
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--read-smoke-output', required=True)
    parser.add_argument('--closeout-output', required=True)
    parser.add_argument('--qa-uri', default='', help='Published QA URI to embed in the catalog. Defaults to --qa-output.')
    parser.add_argument('--research-window', default='IS', help='Catalog-level research window label, e.g. IS, OOS, or IS+OOS.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    root = str(args.datamart_root).rstrip('/') + '/'
    expected_dates = expected_dates_from_daily_basic(Path(args.daily_basic_root).expanduser(), start, end)
    observed_dates = discover_s3_dates(root)
    missing_dates = [date for date in expected_dates if date not in set(observed_dates)]
    extra_dates = [date for date in observed_dates if date < start or date > end]
    representative_dates = [normalize_trade_date(date) for date in split_csv(args.representative_dates)]
    sample_dates = sorted(set([date for date in representative_dates if date in observed_dates]))
    if not sample_dates and observed_dates:
        sample_dates = [observed_dates[0], observed_dates[-1]]

    read_smokes: list[dict[str, Any]] = []
    row_count = 0
    ticker_set: set[str] = set()
    duplicate_key_count = 0
    sample_issues: list[str] = []
    for trade_date in sample_dates:
        read_started = time.perf_counter()
        frame = read_s3_date(root, trade_date, columns=OUTPUT_COLUMNS)
        warm_read_seconds = float(time.perf_counter() - read_started)
        summary = validate_frame(frame, trade_date)
        summary['warm_read_seconds'] = warm_read_seconds
        read_smokes.append(summary)
        sample_issues.extend([f'{trade_date}:{issue}' for issue in summary['issues']])

    # Full row/duplicate counts are computed partition-by-partition to avoid a
    # single large materialization while still proving the production contract.
    full_started = time.perf_counter()
    for trade_date in observed_dates:
        if trade_date < start or trade_date > end:
            continue
        frame = read_s3_date(
            root,
            trade_date,
            columns=[
                'ts_code',
                'trade_date',
                'lcr_raw',
                'no_future_data',
                'no_future_intraday_minutes',
            ],
        )
        row_count += int(len(frame))
        if 'ts_code' in frame.columns and not frame.empty:
            ticker_set.update(frame['ts_code'].dropna().astype(str).unique().tolist())
        if all(column in frame.columns for column in UNIQUE_KEY):
            duplicate_key_count += int(frame.duplicated(UNIQUE_KEY).sum())
    full_scan_seconds = float(time.perf_counter() - full_started)

    issues: list[str] = []
    if missing_dates:
        issues.append('missing_dates_nonempty')
    if extra_dates:
        issues.append('extra_dates_outside_window')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if sample_issues:
        issues.append('representative_read_smoke_issues')
    if not expected_dates:
        issues.append('expected_dates_empty')
    if len(observed_dates) < len(expected_dates):
        issues.append('observed_date_count_below_expected')
    verdict = 'ACCEPT' if not issues else 'BLOCK'

    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()
    read_smoke_output = Path(args.read_smoke_output).expanduser()
    closeout_output = Path(args.closeout_output).expanduser()
    for path in [qa_output, catalog_output, read_smoke_output, closeout_output]:
        path.parent.mkdir(parents=True, exist_ok=True)

    qa = {
        'verdict': verdict,
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'datamart_root': root,
        'start_date': start,
        'end_date': end,
        'expected_date_count': len(expected_dates),
        'observed_date_count': len([date for date in observed_dates if start <= date <= end]),
        'row_count': int(row_count),
        'ticker_count': int(len(ticker_set)),
        'duplicate_key_count': int(duplicate_key_count),
        'missing_dates': missing_dates,
        'extra_dates': extra_dates,
        'full_scan_seconds': full_scan_seconds,
        'runtime_seconds': float(time.perf_counter() - started),
        'issues': issues,
        'information_set_legality': {
            'no_future_data': True,
            'no_future_intraday_minutes': True,
            'state_asof': 'selection trade_date close',
        },
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    }
    read_smoke = {
        'verdict': 'ACCEPT' if not sample_issues and read_smokes else 'BLOCK',
        'dataset_id': DATASET_ID,
        'datamart_root': root,
        'representative_dates': representative_dates,
        'read_smokes': read_smokes,
        'issues': sample_issues,
    }
    catalog = build_catalog(
        root=root,
        qa_path=str(args.qa_uri or qa_output),
        start=start,
        end=end,
        row_count=row_count,
        date_count=len([date for date in observed_dates if start <= date <= end]),
        ticker_count=len(ticker_set),
        research_window=str(args.research_window),
    )
    closeout = {
        'verdict': verdict,
        'dataset_id': DATASET_ID,
        'catalog_path': str(catalog_output),
        'qa_path': str(qa_output),
        'read_smoke_path': str(read_smoke_output),
        'datamart_path': root,
        'worker_read_smoke': {
            'verdict': read_smoke['verdict'],
            'representative_dates': representative_dates,
            'warm_read_seconds_max': max((float(item.get('warm_read_seconds') or 0.0) for item in read_smokes), default=None),
        },
        'coverage': {
            'expected_date_count': qa['expected_date_count'],
            'observed_date_count': qa['observed_date_count'],
            'missing_dates': missing_dates,
            'duplicate_key_count': duplicate_key_count,
            'row_count': row_count,
            'ticker_count': len(ticker_set),
        },
        'safety': qa['safety'],
    }

    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    catalog_output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    read_smoke_output.write_text(json.dumps(read_smoke, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    closeout_output.write_text(json.dumps(closeout, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': verdict, 'qa_output': str(qa_output), 'catalog_output': str(catalog_output)}, ensure_ascii=False))
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
