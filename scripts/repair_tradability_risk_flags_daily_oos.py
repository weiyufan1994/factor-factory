#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.universe_builders import MIN_MARKET_CAP_WAN, build_tradability_risk_flags_daily  # noqa: E402


DATASET_ID = 'tradability_risk_flags_daily'
REQUIRED_COLUMNS = ['ts_code', 'trade_date', 'is_investable_core', 'is_investable_500m', 'market_cap']
OUTPUT_COLUMNS = [
    'trade_date',
    'ts_code',
    'market_cap',
    'market_cap_source',
    'excluded_small_cap',
    'excluded_st',
    'excluded_new_stock',
    'excluded_untradable',
    'excluded_major_risk',
    'is_investable_core',
    'is_investable_500m',
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Repair tradability_risk_flags_daily OOS coverage from S3 raw Tushare sources.')
    ap.add_argument('--start', default='20250714')
    ap.add_argument('--end', default='20260612')
    ap.add_argument('--run-root', default='/tmp/tradability_risk_flags_daily_oos_repair_20260616')
    ap.add_argument('--source-prefix', default='s3://yufan-data-lake/tushares')
    ap.add_argument('--output-s3', default='s3://yufan-data-lake/factorforge/datamart/tradability_risk_flags_daily/v1')
    ap.add_argument('--research-input-s3', default='s3://yufan-data-lake/factorforge/research_runs/dongwu_20241229_cpv_price_path_occupation_v3/research_20260616/_inputs/tradability_risk_flags_daily')
    ap.add_argument('--proof-s3', default='s3://yufan-data-lake/factorforge/proofs/tradability_risk_flags_daily/oos_coverage_repair_20260616/proof.json')
    ap.add_argument('--catalog-s3', default='s3://yufan-data-lake/factorforge/proofs/tradability_risk_flags_daily/oos_coverage_repair_20260616/catalog.json')
    ap.add_argument('--min-market-cap-wan', type=float, default=MIN_MARKET_CAP_WAN)
    ap.add_argument('--min-listing-days', type=int, default=60)
    ap.add_argument('--skip-upload', action='store_true')
    return ap.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def run_text(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '').replace('.0', '')
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'invalid trade_date: {value!r}')
    return parsed.strftime('%Y%m%d')


def download_sources(args: argparse.Namespace, raw_root: Path) -> dict[str, str]:
    raw_root.mkdir(parents=True, exist_ok=True)
    source = args.source_prefix.rstrip('/')
    paths = {
        'daily_csv': raw_root / 'daily.csv',
        'daily_basic_dir': raw_root / 'daily_basic_incremental',
        'stock_basic_csv': raw_root / 'stock_basic.csv',
        'stock_st_csv': raw_root / 'stock_st.csv',
        'trade_cal_csv': raw_root / 'trade_cal.csv',
    }
    run(['aws', 's3', 'cp', f'{source}/行情数据/daily.csv', str(paths['daily_csv']), '--only-show-errors'])
    run([
        'aws', 's3', 'sync',
        f'{source}/行情数据/daily_basic_incremental',
        str(paths['daily_basic_dir']),
        '--exclude', '*',
        '--include', 'trade_date=2025*/*',
        '--include', 'trade_date=2026*/*',
        '--only-show-errors',
    ])
    for name in ['stock_basic.csv', 'stock_st.csv', 'trade_cal.csv']:
        run(['aws', 's3', 'cp', f'{source}/基础数据/{name}', str(raw_root / name), '--only-show-errors'])
    return {key: str(value) for key, value in paths.items()}


def read_daily(path: Path, start: str, end: str) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        usecols=['ts_code', 'trade_date', 'vol', 'amount', 'close'],
        dtype={'ts_code': 'string', 'trade_date': 'string'},
    )
    frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
    frame = frame[(frame['trade_date'] >= start) & (frame['trade_date'] <= end)]
    return frame.reset_index(drop=True)


def read_daily_basic(root: Path, start: str, end: str) -> pd.DataFrame:
    paths = []
    for part in sorted(root.glob('trade_date=*')):
        if not part.is_dir():
            continue
        trade_date = normalize_trade_date(part.name.split('=', 1)[1])
        if start <= trade_date <= end:
            paths.extend(sorted(part.glob('*.csv')))
    frames = []
    for path in paths:
        frame = pd.read_csv(
            path,
            usecols=lambda column: column in {'ts_code', 'trade_date', 'circ_mv', 'total_mv'},
            dtype={'ts_code': 'string', 'trade_date': 'string'},
        )
        if 'trade_date' in frame:
            frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=['ts_code', 'trade_date', 'circ_mv', 'total_mv'])


def read_reference_csvs(raw_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stock_basic = pd.read_csv(
        raw_root / 'stock_basic.csv',
        usecols=lambda column: column in {'ts_code', 'name', 'list_status', 'list_date'},
        dtype={'ts_code': 'string', 'name': 'string', 'list_status': 'string', 'list_date': 'string'},
    )
    trade_calendar = pd.read_csv(
        raw_root / 'trade_cal.csv',
        usecols=lambda column: column in {'cal_date', 'is_open'},
        dtype={'cal_date': 'string'},
    )
    stock_st = pd.read_csv(
        raw_root / 'stock_st.csv',
        usecols=lambda column: column in {'ts_code', 'start_date', 'end_date', 'is_st'},
        dtype={'ts_code': 'string', 'start_date': 'string', 'end_date': 'string'},
    )
    return stock_basic, trade_calendar, stock_st


def expected_open_dates(trade_calendar: pd.DataFrame, start: str, end: str) -> list[str]:
    cal = trade_calendar.copy()
    cal['cal_date'] = cal['cal_date'].map(normalize_trade_date)
    return sorted(cal.loc[(cal['is_open'].astype(int) == 1) & (cal['cal_date'] >= start) & (cal['cal_date'] <= end), 'cal_date'].unique().tolist())


def write_partitioned(frame: pd.DataFrame, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for trade_date, group in frame.groupby('trade_date', sort=True, observed=True):
        part_dir = output_root / f'trade_date={trade_date}'
        if part_dir.exists():
            for old in part_dir.glob('*.parquet'):
                old.unlink()
        part_dir.mkdir(parents=True, exist_ok=True)
        group.drop(columns=['trade_date']).to_parquet(part_dir / 'part-000.parquet', index=False)


def build_catalog(output_s3: str, proof_s3: str, start: str, end: str) -> dict[str, Any]:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: {
                'uri': output_s3.rstrip('/'),
                'format': 'parquet',
                'version': 'v1',
                'storage': 's3',
                'description': 'Reusable daily investability flags for universe post-filtering without mutating raw universe membership.',
                'columns': OUTPUT_COLUMNS,
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'tushares daily + daily_basic + stock_basic + stock_st + trade_cal',
                    'unique_key': ['trade_date', 'ts_code'],
                    'sort_keys': ['trade_date', 'ts_code'],
                    'qa_summary_path': proof_s3,
                    'rules': {
                        'exclude_market_cap_lt_wan': 50000.0,
                        'exclude_new_stock_listing_days_lt': 60,
                        'is_investable_core': 'not excluded_st/new_stock/untradable/major_risk',
                        'is_investable_500m': 'is_investable_core and not excluded_small_cap',
                    },
                    'information_set_legality': 'uses same-day daily/daily_basic tradability and point-in-time listing/ST status available for same-day universe membership',
                },
                'freshness': {
                    'trade_date_min': '20160104',
                    'trade_date_max': end,
                },
            },
        },
    }


def read_smoke(output_root: Path, dates: list[str]) -> dict[str, Any]:
    dataset = ds.dataset(str(output_root), format='parquet', partitioning='hive')
    samples = []
    for date in dates:
        part_date: Any = int(date)
        started = time.perf_counter()
        table = dataset.to_table(
            columns=['trade_date', 'ts_code', 'is_investable_core', 'is_investable_500m', 'market_cap'],
            filter=ds.field('trade_date') == part_date,
        )
        frame = table.to_pandas()
        if 'trade_date' in frame:
            frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        samples.append({
            'trade_date': date,
            'status': 'PASS' if len(frame) > 0 and int(frame.duplicated(['trade_date', 'ts_code']).sum()) == 0 else 'FAIL',
            'row_count': int(len(frame)),
            'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame else 0,
            'duplicate_key_count': int(frame.duplicated(['trade_date', 'ts_code']).sum()) if not frame.empty else 0,
            'elapsed_seconds': time.perf_counter() - started,
        })
    return {
        'status': 'PASS' if all(item['status'] == 'PASS' for item in samples) else 'FAIL',
        'sample_dates': dates,
        'samples': samples,
    }


def build_proof(
    flags: pd.DataFrame,
    expected_dates: list[str],
    *,
    args: argparse.Namespace,
    raw_paths: dict[str, str],
    read_smoke_payload: dict[str, Any],
    runtime_seconds: float,
) -> dict[str, Any]:
    produced_dates = sorted(flags['trade_date'].astype(str).unique().tolist()) if not flags.empty else []
    missing_dates = sorted(set(expected_dates) - set(produced_dates))
    duplicate_key_count = int(flags.duplicated(['trade_date', 'ts_code']).sum()) if not flags.empty else 0
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(flags.columns))
    null_ratio = {col: float(flags[col].isna().mean()) for col in REQUIRED_COLUMNS if col in flags.columns}
    dtype_by_field = {col: str(flags[col].dtype) for col in REQUIRED_COLUMNS if col in flags.columns}
    coverage_by_date_tail = flags.groupby('trade_date')['ts_code'].nunique().astype(int).tail(5).to_dict() if not flags.empty else {}
    hard_checks = {
        'row_count_positive': len(flags) > 0,
        'required_columns_present': not missing_columns,
        'oos_missing_dates_empty': not missing_dates,
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'read_smoke_pass': read_smoke_payload['status'] == 'PASS',
        'output_max_trade_date_gte_requested': bool(produced_dates and max(produced_dates) >= args.end),
    }
    return {
        'status': 'ACCEPT' if all(hard_checks.values()) else 'BLOCK',
        'verdict': 'ACCEPT' if all(hard_checks.values()) else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': 'tradability_risk_flags_daily_v1_oos_coverage_repair_20260616',
        'source_dataset': 'tushares daily + daily_basic + stock_basic + stock_st + trade_cal',
        'source_s3_prefix': args.source_prefix.rstrip('/'),
        'raw_paths': raw_paths,
        'output_s3': args.output_s3.rstrip('/'),
        'research_input_s3': args.research_input_s3.rstrip('/'),
        'requested_min_trade_date': args.start,
        'requested_max_trade_date': args.end,
        'min_date': min(produced_dates) if produced_dates else None,
        'max_date': max(produced_dates) if produced_dates else None,
        'date_count': len(produced_dates),
        'expected_oos_date_count': len(expected_dates),
        'row_count': int(len(flags)),
        'ticker_count': int(flags['ts_code'].nunique()) if 'ts_code' in flags else 0,
        'duplicate_key_count': duplicate_key_count,
        'missing_dates': missing_dates,
        'missing_required_columns': missing_columns,
        'dtype_by_required_field': dtype_by_field,
        'null_ratio_by_required_column': null_ratio,
        'coverage_by_date_tail': coverage_by_date_tail,
        'read_smoke': read_smoke_payload,
        'hard_checks': hard_checks,
        'generated_at_utc': utc_now(),
        'runtime_seconds': runtime_seconds,
    }


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    run_root = Path(args.run_root).expanduser()
    raw_root = run_root / 'raw'
    output_root = run_root / 'datamart'
    proof_path = run_root / 'proof.json'
    catalog_path = run_root / 'catalog.json'

    raw_paths = download_sources(args, raw_root)
    daily = read_daily(Path(raw_paths['daily_csv']), args.start, args.end)
    daily_basic = read_daily_basic(Path(raw_paths['daily_basic_dir']), args.start, args.end)
    stock_basic, trade_calendar, stock_st = read_reference_csvs(raw_root)
    expected_dates = expected_open_dates(trade_calendar, args.start, args.end)
    flags = build_tradability_risk_flags_daily(
        daily,
        daily_basic=daily_basic,
        stock_basic=stock_basic,
        trade_calendar=trade_calendar,
        stock_st=stock_st,
        min_market_cap_wan=args.min_market_cap_wan,
        min_listing_days=args.min_listing_days,
    )
    write_partitioned(flags, output_root)
    smoke_dates = ['20250714', '20260612']
    if '20251231' in expected_dates:
        smoke_dates.insert(1, '20251231')
    read_smoke_payload = read_smoke(output_root, smoke_dates)
    proof = build_proof(
        flags,
        expected_dates,
        args=args,
        raw_paths=raw_paths,
        read_smoke_payload=read_smoke_payload,
        runtime_seconds=time.perf_counter() - started,
    )
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    catalog = build_catalog(args.output_s3, args.proof_s3, args.start, args.end)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not args.skip_upload:
        run(['aws', 's3', 'cp', str(output_root), args.output_s3.rstrip('/'), '--recursive', '--only-show-errors'])
        run(['aws', 's3', 'cp', str(output_root), args.research_input_s3.rstrip('/'), '--recursive', '--only-show-errors'])
        run(['aws', 's3', 'cp', str(proof_path), args.proof_s3, '--only-show-errors'])
        run(['aws', 's3', 'cp', str(catalog_path), args.catalog_s3, '--only-show-errors'])
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof['status'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
