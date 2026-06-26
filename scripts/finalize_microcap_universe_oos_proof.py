#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.fs as fs

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.repair_microcap_universe_oos as repair  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Finalize microcap_universe proof from an existing worker build.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20260612')
    ap.add_argument('--oos-start', default='20250714')
    ap.add_argument('--oos-end', default='20260612')
    ap.add_argument('--run-root', default='/tmp/microcap_oos_repair_20260617/work')
    ap.add_argument('--source-prefix', default='s3://yufan-data-lake/tushares')
    ap.add_argument('--output-s3', default='s3://yufan-data-lake/factorforge/datamart/microcap_universe/v1')
    ap.add_argument('--research-input-s3', default='s3://yufan-data-lake/factorforge/research_runs/dongwu_20241229_cpv_price_path_occupation_v3/research_20260616/_inputs/microcap_universe')
    ap.add_argument('--proof-s3', default='s3://yufan-data-lake/factorforge/proofs/microcap_universe/oos_coverage_repair_20260617/proof.json')
    ap.add_argument('--catalog-s3', default='s3://yufan-data-lake/factorforge/proofs/microcap_universe/oos_coverage_repair_20260617/catalog.json')
    ap.add_argument('--bottom-fraction', type=float, default=0.10)
    ap.add_argument('--small10-fraction', type=float, default=0.10)
    ap.add_argument('--small20-fraction', type=float, default=0.20)
    ap.add_argument('--min-market-cap-wan', type=float, default=repair.MIN_MARKET_CAP_WAN)
    ap.add_argument('--min-listing-days', type=int, default=60)
    ap.add_argument('--s3-region', default='ap-southeast-1')
    return ap.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def dataset_for_s3(uri: str, region: str):
    stripped = uri.removeprefix('s3://').rstrip('/')
    bucket, _, key = stripped.partition('/')
    filesystem = fs.S3FileSystem(region=region)
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    return ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning)


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    run_root = Path(args.run_root).expanduser()
    raw_root = run_root / 'raw'
    output_root = run_root / 'datamart'
    proof_path = run_root / 'proof.json'
    catalog_path = run_root / 'catalog.json'

    if not output_root.exists():
        raise FileNotFoundError(f'missing built datamart: {output_root}')
    _, trade_calendar, _ = repair.read_reference_csvs(raw_root)
    expected_full_dates = repair.expected_open_dates(trade_calendar, args.start, args.end)
    expected_oos_dates = repair.expected_open_dates(trade_calendar, args.oos_start, args.oos_end)
    smoke_dates = ['20250714', '20260612']
    if '20251231' in expected_oos_dates:
        smoke_dates.insert(1, '20251231')

    local_dataset = repair.dataset_for_path(output_root)
    local_read_smoke = repair.read_smoke_from_dataset(local_dataset, smoke_dates)
    s3_read_smoke = repair.read_smoke_from_dataset(dataset_for_s3(args.output_s3, args.s3_region), smoke_dates)
    universe = local_dataset.to_table(columns=repair.REQUIRED_COLUMNS).to_pandas()
    if 'trade_date' in universe:
        universe['trade_date'] = universe['trade_date'].map(repair.normalize_trade_date)

    raw_paths = {
        'daily_csv': str(raw_root / 'daily.csv'),
        'daily_basic_dir': str(raw_root / 'daily_basic_incremental'),
        'stock_basic_csv': str(raw_root / 'stock_basic.csv'),
        'stock_st_csv': str(raw_root / 'stock_st.csv'),
        'trade_cal_csv': str(raw_root / 'trade_cal.csv'),
    }
    proof = repair.build_proof(
        universe,
        expected_full_dates,
        expected_oos_dates,
        args=args,
        raw_paths=raw_paths,
        local_read_smoke=local_read_smoke,
        s3_read_smoke=s3_read_smoke,
        runtime_seconds=time.perf_counter() - started,
    )
    catalog = repair.build_catalog(args)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    run(['aws', 's3', 'cp', str(proof_path), args.proof_s3, '--only-show-errors'])
    run(['aws', 's3', 'cp', str(catalog_path), args.catalog_s3, '--only-show-errors'])
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof['status'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
