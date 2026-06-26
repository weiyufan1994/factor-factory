#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.smart_money_intraday_state import (  # noqa: E402
    DATASET_ID,
    OUTPUT_COLUMNS,
    PRODUCER_VERSION,
    SCHEMA_VERSION,
    SOURCE_DATASET,
    UNIQUE_KEY,
    normalize_trade_date,
)


FORBIDDEN_FIELD_EXACT = {
    'ic',
    'rankic',
    'future_return',
    'next_return',
    'label',
    'target',
    'style_neutral',
    'composite_score',
}
FORBIDDEN_FIELD_PREFIXES = (
    'ic_',
    'rankic_',
    'future_return_',
    'next_return_',
    'label_',
    'target_',
    'style_neutral_',
    'composite_score_',
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


def expected_dates_from_file(path: str | Path, start: str, end: str) -> list[str]:
    raw = Path(path).expanduser().read_text(encoding='utf-8')
    dates = sorted({normalize_trade_date(line) for line in raw.splitlines() if line.strip() and not line.strip().startswith('#')})
    return [date for date in dates if start <= date <= end]


def read_local_date(root: Path, trade_date: str, columns: list[str] | None = None) -> pd.DataFrame:
    part = root / f'trade_date={trade_date}'
    files = sorted(path for path in part.glob('*.parquet') if path.is_file())
    if not files:
        return pd.DataFrame(columns=columns or OUTPUT_COLUMNS)
    read_columns = [column for column in columns if column != 'trade_date'] if columns else None
    frames = [pd.read_parquet(path, columns=read_columns) if read_columns else pd.read_parquet(path) for path in files]
    frame = pd.concat(frames, ignore_index=True)
    if 'trade_date' not in frame.columns:
        frame['trade_date'] = trade_date
    if columns:
        frame = frame[[column for column in columns if column in frame.columns]]
    return frame


def read_s3_date(root: str, trade_date: str, columns: list[str] | None = None) -> pd.DataFrame:
    partition_uri = f"{root.rstrip('/')}/trade_date={trade_date}/"
    listing = subprocess.check_output(['aws', 's3', 'ls', partition_uri], text=True)
    uris = [partition_uri + line.strip().split()[-1] for line in listing.splitlines() if line.strip().endswith('.parquet')]
    if not uris:
        return pd.DataFrame(columns=columns or OUTPUT_COLUMNS)
    with tempfile.TemporaryDirectory(prefix='smart_money_closeout_') as tmp:
        local_files: list[Path] = []
        for index, uri in enumerate(uris):
            target = Path(tmp) / f'part-{index:03d}.parquet'
            subprocess.run(['aws', 's3', 'cp', uri, str(target), '--only-show-errors'], check=True)
            local_files.append(target)
        read_columns = [column for column in columns if column != 'trade_date'] if columns else None
        frames = [pd.read_parquet(path, columns=read_columns) if read_columns else pd.read_parquet(path) for path in local_files]
        frame = pd.concat(frames, ignore_index=True)
    if 'trade_date' not in frame.columns:
        frame['trade_date'] = trade_date
    if columns:
        frame = frame[[column for column in columns if column in frame.columns]]
    return frame


def read_date(root: str, trade_date: str, columns: list[str] | None = None) -> pd.DataFrame:
    if root.startswith('s3://'):
        return read_s3_date(root, trade_date, columns=columns)
    return read_local_date(Path(root).expanduser(), trade_date, columns=columns)


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
                'uri': root.rstrip('/') + ('/' if root.startswith('s3://') else ''),
                'format': 'parquet',
                'version': 'v1',
                'storage': 's3' if root.startswith('s3://') else 'local',
                'description': 'Smart-money intraday state Q variants from 10 trading days of minute_bar selected by S-score cumulative volume.',
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
                    'source_datasets': [SOURCE_DATASET],
                    'partition_column': 'trade_date',
                    'unique_key': UNIQUE_KEY,
                    'sort_keys': ['trade_date', 'ts_code'],
                    'variants': [
                        'q_log_volume',
                        'q_beta_0p1',
                        'q_beta_0p25',
                        'q_original_beta_0p5',
                        'q_volume_only',
                        'q_rank_absret_plus_rankvol',
                    ],
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
        if column.lower() in FORBIDDEN_FIELD_EXACT or column.lower().startswith(FORBIDDEN_FIELD_PREFIXES)
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
    for flag in ['no_future_data', 'no_future_intraday_minutes']:
        if flag in frame.columns and not frame.empty and not bool(frame[flag].all()):
            issues.append(f'{flag}_not_true')
    qa_status_counts = (
        {str(key): int(value) for key, value in frame['qa_status'].value_counts(dropna=False).items()}
        if 'qa_status' in frame.columns and not frame.empty else {}
    )
    if frame.empty or qa_status_counts.get('pass', 0) <= 0:
        issues.append('qa_status_pass_row_count_zero')
    return {
        'trade_date': trade_date,
        'row_count': int(len(frame)),
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'duplicate_key_count': duplicate_key_count,
        'qa_status_counts': qa_status_counts,
        'research_windows': sorted(frame['research_window'].dropna().astype(str).unique().tolist()) if 'research_window' in frame.columns and not frame.empty else [],
        'missing_columns': missing_columns,
        'forbidden_columns': forbidden_columns,
        'issues': issues,
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Close out smart_money_intraday_state_v1 datamart.')
    parser.add_argument('--datamart-root', required=True)
    parser.add_argument('--expected-dates-file', required=True)
    parser.add_argument('--start', default='20160104')
    parser.add_argument('--end', default='20250711')
    parser.add_argument('--representative-dates', default='20160104,20200102,20250711')
    parser.add_argument('--scan-mode', choices=['representative', 'full'], default='representative')
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--read-smoke-output', required=True)
    parser.add_argument('--closeout-output', required=True)
    parser.add_argument('--qa-uri', default='')
    parser.add_argument('--research-window', default='IS')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    root = str(args.datamart_root).rstrip('/')
    expected_dates = expected_dates_from_file(args.expected_dates_file, start, end)
    observed_dates = discover_s3_dates(root) if root.startswith('s3://') else discover_local_dates(Path(root).expanduser())
    in_window_observed = [date for date in observed_dates if start <= date <= end]
    missing_dates = [date for date in expected_dates if date not in set(observed_dates)]
    extra_dates = [date for date in observed_dates if date < start or date > end]
    representative_dates = [normalize_trade_date(date) for date in split_csv(args.representative_dates)]
    sample_dates = sorted(set([date for date in representative_dates if date in observed_dates]))
    if not sample_dates and in_window_observed:
        sample_dates = [in_window_observed[0], in_window_observed[-1]]

    read_smokes: list[dict[str, Any]] = []
    sample_issues: list[str] = []
    for trade_date in sample_dates:
        read_started = time.perf_counter()
        frame = read_date(root, trade_date, columns=OUTPUT_COLUMNS)
        summary = validate_frame(frame, trade_date)
        summary['warm_read_seconds'] = float(time.perf_counter() - read_started)
        read_smokes.append(summary)
        sample_issues.extend([f'{trade_date}:{issue}' for issue in summary['issues']])

    scan_dates = in_window_observed if args.scan_mode == 'full' else sample_dates
    row_count = 0
    ticker_set: set[str] = set()
    duplicate_key_count = 0
    qa_status_counts: dict[str, int] = {}
    full_started = time.perf_counter()
    for trade_date in scan_dates:
        frame = read_date(root, trade_date, columns=['ts_code', 'trade_date', 'qa_status', 'no_future_data', 'no_future_intraday_minutes'])
        row_count += int(len(frame))
        if 'ts_code' in frame.columns and not frame.empty:
            ticker_set.update(frame['ts_code'].dropna().astype(str).unique().tolist())
        if all(column in frame.columns for column in UNIQUE_KEY):
            duplicate_key_count += int(frame.duplicated(UNIQUE_KEY).sum())
        if 'qa_status' in frame.columns and not frame.empty:
            for key, value in frame['qa_status'].value_counts(dropna=False).items():
                qa_status_counts[str(key)] = qa_status_counts.get(str(key), 0) + int(value)
    scan_seconds = float(time.perf_counter() - full_started)

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
    if args.scan_mode == 'full' and len(in_window_observed) < len(expected_dates):
        issues.append('observed_date_count_below_expected')
    if args.scan_mode != 'full':
        issues.append('representative_scan_only_not_production_accept')
    verdict = 'ACCEPT' if not issues else 'BLOCK'

    qa = {
        'verdict': verdict,
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'datamart_root': root,
        'scan_mode': str(args.scan_mode),
        'start_date': start,
        'end_date': end,
        'expected_date_count': len(expected_dates),
        'observed_date_count': len(in_window_observed),
        'scanned_date_count': len(scan_dates),
        'row_count': int(row_count),
        'ticker_count': int(len(ticker_set)),
        'duplicate_key_count': int(duplicate_key_count),
        'qa_status_counts': qa_status_counts,
        'missing_dates': missing_dates,
        'extra_dates': extra_dates,
        'scan_seconds': scan_seconds,
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
        qa_path=str(args.qa_uri or Path(args.qa_output).expanduser()),
        start=start,
        end=end,
        row_count=row_count,
        date_count=len(in_window_observed),
        ticker_count=len(ticker_set),
        research_window=str(args.research_window),
    )
    closeout = {
        'verdict': verdict,
        'dataset_id': DATASET_ID,
        'catalog_path': str(Path(args.catalog_output).expanduser()),
        'qa_path': str(Path(args.qa_output).expanduser()),
        'read_smoke_path': str(Path(args.read_smoke_output).expanduser()),
        'datamart_path': root,
        'worker_read_smoke': {
            'verdict': read_smoke['verdict'],
            'representative_dates': representative_dates,
            'warm_read_seconds_max': max((float(item.get('warm_read_seconds') or 0.0) for item in read_smokes), default=None),
        },
        'coverage': {
            'expected_date_count': qa['expected_date_count'],
            'observed_date_count': qa['observed_date_count'],
            'scanned_date_count': qa['scanned_date_count'],
            'missing_dates': missing_dates,
            'duplicate_key_count': duplicate_key_count,
            'row_count': row_count,
            'ticker_count': len(ticker_set),
        },
        'safety': qa['safety'],
    }
    for path, payload in [
        (args.qa_output, qa),
        (args.catalog_output, catalog),
        (args.read_smoke_output, read_smoke),
        (args.closeout_output, closeout),
    ]:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': verdict, 'qa_output': str(Path(args.qa_output).expanduser()), 'catalog_output': str(Path(args.catalog_output).expanduser())}, ensure_ascii=False))
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
