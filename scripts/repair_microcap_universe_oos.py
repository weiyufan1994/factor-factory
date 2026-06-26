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

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.universe_builders import (  # noqa: E402
    MICROCAP_SMALL10_UNIVERSE_ID,
    MICROCAP_SMALL10_UNIVERSE_NAME,
    MICROCAP_SMALL20_UNIVERSE_ID,
    MICROCAP_SMALL20_UNIVERSE_NAME,
    MIN_MARKET_CAP_WAN,
    build_microcap_universe,
)


DATASET_ID = 'microcap_universe'
REQUIRED_UNIVERSE_IDS = [MICROCAP_SMALL10_UNIVERSE_ID, MICROCAP_SMALL20_UNIVERSE_ID]
REQUIRED_COLUMNS = [
    'universe_id',
    'universe_name',
    'trade_date',
    'ts_code',
    'market_cap',
    'market_cap_source',
    'base_market_cap_rank_asc',
    'microcap_rank_asc_after_exclusion',
    'microcap_rank_pct_after_exclusion',
    'microcap_fraction',
    'excluded_small_cap',
    'excluded_bottom_market_cap',
    'excluded_st',
    'excluded_new_stock',
    'excluded_untradable',
    'excluded_major_risk',
    'is_eligible_after_exclusion',
    'in_universe',
]
EXCLUSION_COLUMNS = [
    'excluded_small_cap',
    'excluded_bottom_market_cap',
    'excluded_st',
    'excluded_new_stock',
    'excluded_untradable',
    'excluded_major_risk',
]
ALPHA_FORBIDDEN_COLUMNS = [
    'factor_value',
    'alpha',
    'ic',
    'rank_ic',
    'residual_ic',
    'support_minus_overhang',
    'below_cost_guarded_support',
    'vp_below_cost_repair_v1',
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Refresh microcap_universe coverage from S3 raw Tushare sources.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20260612')
    ap.add_argument('--oos-start', default='20250714')
    ap.add_argument('--oos-end', default='20260612')
    ap.add_argument('--run-root', default='/tmp/microcap_universe_oos_repair_20260617')
    ap.add_argument('--source-prefix', default='s3://yufan-data-lake/tushares')
    ap.add_argument('--output-s3', default='s3://yufan-data-lake/factorforge/datamart/microcap_universe/v1')
    ap.add_argument('--research-input-s3', default='s3://yufan-data-lake/factorforge/research_runs/dongwu_20241229_cpv_price_path_occupation_v3/research_20260616/_inputs/microcap_universe')
    ap.add_argument('--proof-s3', default='s3://yufan-data-lake/factorforge/proofs/microcap_universe/oos_coverage_repair_20260617/proof.json')
    ap.add_argument('--catalog-s3', default='s3://yufan-data-lake/factorforge/proofs/microcap_universe/oos_coverage_repair_20260617/catalog.json')
    ap.add_argument('--bottom-fraction', type=float, default=0.10)
    ap.add_argument('--small10-fraction', type=float, default=0.10)
    ap.add_argument('--small20-fraction', type=float, default=0.20)
    ap.add_argument('--min-market-cap-wan', type=float, default=MIN_MARKET_CAP_WAN)
    ap.add_argument('--min-listing-days', type=int, default=60)
    ap.add_argument('--skip-upload', action='store_true')
    return ap.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


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
        '--only-show-errors',
    ])
    for name in ['stock_basic.csv', 'stock_st.csv', 'trade_cal.csv']:
        run(['aws', 's3', 'cp', f'{source}/基础数据/{name}', str(raw_root / name), '--only-show-errors'])
    return {key: str(value) for key, value in paths.items()}


def read_daily(path: Path, start: str, end: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path,
        usecols=['ts_code', 'trade_date', 'vol', 'amount', 'close'],
        dtype={'ts_code': 'string', 'trade_date': 'string'},
        chunksize=1_000_000,
    ):
        chunk['trade_date'] = chunk['trade_date'].map(normalize_trade_date)
        chunk = chunk[(chunk['trade_date'] >= start) & (chunk['trade_date'] <= end)]
        if not chunk.empty:
            frames.append(chunk)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=['ts_code', 'trade_date', 'vol', 'amount', 'close'])


def read_daily_basic(root: Path, start: str, end: str) -> pd.DataFrame:
    paths = []
    for part in sorted(root.glob('trade_date=*')):
        if not part.is_dir():
            continue
        trade_date = normalize_trade_date(part.name.split('=', 1)[1])
        if start <= trade_date <= end:
            paths.extend(sorted(part.glob('*.csv')))
            paths.extend(sorted(part.glob('*.parquet')))
    frames: list[pd.DataFrame] = []
    for path in paths:
        columns = ['ts_code', 'trade_date', 'circ_mv', 'total_mv']
        if path.suffix == '.parquet':
            frame = pd.read_parquet(path, columns=columns)
        else:
            frame = pd.read_csv(
                path,
                usecols=lambda column: column in set(columns),
                dtype={'ts_code': 'string', 'trade_date': 'string'},
            )
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


def build_catalog(args: argparse.Namespace) -> dict[str, Any]:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: {
                'uri': args.output_s3.rstrip('/'),
                'format': 'parquet',
                'version': 'v1',
                'storage': 's3',
                'description': 'Microcap Small10/Small20 backtest universes after excluding sub-500m CNY market cap, full-market bottom 10%, ST, new listings, untradable and major-risk stocks.',
                'columns': REQUIRED_COLUMNS,
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'tushares daily_basic + daily + stock_basic + stock_st + trade_cal',
                    'unique_key': ['universe_id', 'trade_date', 'ts_code'],
                    'sort_keys': ['universe_id', 'trade_date', 'ts_code'],
                    'universe_ids': REQUIRED_UNIVERSE_IDS,
                    'universe_names': {
                        MICROCAP_SMALL10_UNIVERSE_ID: MICROCAP_SMALL10_UNIVERSE_NAME,
                        MICROCAP_SMALL20_UNIVERSE_ID: MICROCAP_SMALL20_UNIVERSE_NAME,
                    },
                    'rules': {
                        'market_cap_source_priority': ['circ_mv', 'total_mv'],
                        'exclude_market_cap_lt_wan': args.min_market_cap_wan,
                        'exclude_bottom_market_cap_fraction': args.bottom_fraction,
                        'small10_fraction': args.small10_fraction,
                        'small20_fraction': args.small20_fraction,
                        'exclude_new_stock_listing_days_lt': args.min_listing_days,
                        'exclude_untradable': 'same-day daily vol<=0 or amount<=0 or close is null',
                        'exclude_st': 'stock_st interval or stock name contains ST',
                        'exclude_major_risk': 'stock_basic.list_status != L or stock name contains 退',
                    },
                    'qa_summary_path': args.proof_s3,
                    'research_input_copy': args.research_input_s3.rstrip('/'),
                    'information_set_legality': 'uses same-day daily_basic/daily tradability and point-in-time listing/ST status available for same-day universe membership',
                    'alpha_conclusion_owner': 'research_group',
                },
                'freshness': {
                    'trade_date_min': args.start,
                    'trade_date_max': args.end,
                },
            },
        },
    }


def dataset_for_path(path: str | Path):
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    return ds.dataset(str(path), format='parquet', partitioning=partitioning)


def dataset_for_s3(uri: str):
    import os
    import pyarrow.fs as fs

    stripped = uri.removeprefix('s3://').rstrip('/')
    bucket, _, key = stripped.partition('/')
    region = os.getenv('FACTORFORGE_S3_REGION') or os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or 'ap-southeast-1'
    filesystem = fs.S3FileSystem(region=region)
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    return ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning)


def read_smoke_from_dataset(dataset, dates: list[str]) -> dict[str, Any]:
    samples = []
    columns = ['universe_id', 'trade_date', 'ts_code', 'market_cap', 'in_universe']
    for date in dates:
        started = time.perf_counter()
        table = dataset.to_table(columns=columns, filter=ds.field('trade_date') == str(date))
        frame = table.to_pandas()
        if 'trade_date' in frame:
            frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        duplicate_key_count = int(frame.duplicated(['universe_id', 'trade_date', 'ts_code']).sum()) if not frame.empty else 0
        by_universe = {}
        for universe_id, group in frame.groupby('universe_id', sort=True, observed=True):
            by_universe[str(universe_id)] = {
                'row_count': int(len(group)),
                'selected_row_count': int(group['in_universe'].fillna(False).sum()),
                'ticker_count': int(group['ts_code'].nunique()),
            }
        universe_ids = sorted(by_universe)
        samples.append({
            'trade_date': date,
            'status': 'PASS' if len(frame) > 0 and duplicate_key_count == 0 and universe_ids == REQUIRED_UNIVERSE_IDS else 'FAIL',
            'row_count': int(len(frame)),
            'selected_row_count': int(frame['in_universe'].fillna(False).sum()) if 'in_universe' in frame else 0,
            'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame else 0,
            'universe_ids': universe_ids,
            'by_universe': by_universe,
            'duplicate_key_count': duplicate_key_count,
            'elapsed_seconds': time.perf_counter() - started,
        })
    return {
        'status': 'PASS' if all(item['status'] == 'PASS' for item in samples) else 'FAIL',
        'sample_dates': dates,
        'samples': samples,
    }


def summarize_by_universe(frame: pd.DataFrame) -> dict[str, Any]:
    out = {}
    for universe_id, group in frame.groupby('universe_id', sort=True, observed=True):
        selected = group[group['in_universe'].fillna(False)]
        daily = selected.groupby('trade_date')['ts_code'].nunique().astype(int)
        out[str(universe_id)] = {
            'selected_rows': int(len(selected)),
            'date_count': int(selected['trade_date'].nunique()),
            'ticker_count': int(selected['ts_code'].nunique()),
            'min_daily_selected_count': int(daily.min()) if not daily.empty else 0,
            'median_daily_selected_count': float(daily.median()) if not daily.empty else 0.0,
            'max_daily_selected_count': int(daily.max()) if not daily.empty else 0,
        }
    return out


def build_proof(
    universe: pd.DataFrame,
    expected_full_dates: list[str],
    expected_oos_dates: list[str],
    *,
    args: argparse.Namespace,
    raw_paths: dict[str, str],
    local_read_smoke: dict[str, Any],
    s3_read_smoke: dict[str, Any] | None,
    runtime_seconds: float,
) -> dict[str, Any]:
    produced_dates = sorted(universe['trade_date'].astype(str).unique().tolist()) if not universe.empty else []
    produced_oos_dates = [date for date in produced_dates if args.oos_start <= date <= args.oos_end]
    full_missing_dates = sorted(set(expected_full_dates) - set(produced_dates))
    oos_missing_dates = sorted(set(expected_oos_dates) - set(produced_oos_dates))
    duplicate_key_count = int(universe.duplicated(['universe_id', 'trade_date', 'ts_code']).sum()) if not universe.empty else 0
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(universe.columns))
    forbidden_columns_present = sorted(set(ALPHA_FORBIDDEN_COLUMNS) & set(universe.columns))
    dtype_by_field = {col: str(universe[col].dtype) for col in REQUIRED_COLUMNS if col in universe.columns}
    null_ratio = {col: float(universe[col].isna().mean()) for col in REQUIRED_COLUMNS if col in universe.columns}
    universe_date = universe.groupby(['trade_date', 'universe_id'], observed=True).size().reset_index(name='rows') if not universe.empty else pd.DataFrame(columns=['trade_date', 'universe_id', 'rows'])
    present_by_date = universe_date.groupby('trade_date')['universe_id'].apply(lambda s: sorted(set(s.astype(str)))).to_dict() if not universe_date.empty else {}
    missing_universe_dates = {
        date: sorted(set(REQUIRED_UNIVERSE_IDS) - set(present_by_date.get(date, [])))
        for date in expected_oos_dates
        if set(present_by_date.get(date, [])) != set(REQUIRED_UNIVERSE_IDS)
    }
    selected_oos = universe[(universe['trade_date'] >= args.oos_start) & (universe['trade_date'] <= args.oos_end) & universe['in_universe'].fillna(False)] if not universe.empty else universe
    selected_by_date_universe = selected_oos.groupby(['trade_date', 'universe_id'], observed=True)['ts_code'].nunique() if not selected_oos.empty else pd.Series(dtype='int64')
    zero_selected_universe_dates = [
        {'trade_date': date, 'universe_id': universe_id}
        for date in expected_oos_dates
        for universe_id in REQUIRED_UNIVERSE_IDS
        if int(selected_by_date_universe.get((date, universe_id), 0)) <= 0
    ]
    base_rows = universe[universe['universe_id'] == MICROCAP_SMALL10_UNIVERSE_ID].copy() if not universe.empty else universe
    exclusion_counts = {
        column: int(base_rows[column].fillna(False).sum())
        for column in EXCLUSION_COLUMNS
        if column in base_rows.columns
    }
    hard_checks = {
        'row_count_positive': len(universe) > 0,
        'selected_row_count_positive': int(universe['in_universe'].fillna(False).sum()) > 0 if 'in_universe' in universe else False,
        'required_columns_present': not missing_columns,
        'forbidden_alpha_columns_absent': not forbidden_columns_present,
        'full_missing_dates_empty': not full_missing_dates,
        'oos_missing_dates_empty': not oos_missing_dates,
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'required_universe_ids_present_every_oos_date': not missing_universe_dates,
        'required_universe_ids_have_selected_rows_every_oos_date': not zero_selected_universe_dates,
        'local_worker_read_smoke_pass': local_read_smoke['status'] == 'PASS',
        's3_worker_read_smoke_pass': (s3_read_smoke or {}).get('status') == 'PASS',
    }
    return {
        'status': 'ACCEPT' if all(hard_checks.values()) else 'BLOCK',
        'verdict': 'ACCEPT' if all(hard_checks.values()) else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': 'microcap_universe_v1_oos_coverage_repair_20260617',
        'repair_mode': 'full_refresh',
        'source_dataset': 'tushares daily_basic + daily + stock_basic + stock_st + trade_cal',
        'source_s3_prefix': args.source_prefix.rstrip('/'),
        'raw_paths': raw_paths,
        'output_s3': args.output_s3.rstrip('/'),
        'research_input_s3': args.research_input_s3.rstrip('/'),
        'requested_min_trade_date': args.start,
        'requested_max_trade_date': args.end,
        'oos_start': args.oos_start,
        'oos_end': args.oos_end,
        'min_date': min(produced_dates) if produced_dates else None,
        'max_date': max(produced_dates) if produced_dates else None,
        'date_count': len(produced_dates),
        'expected_full_date_count': len(expected_full_dates),
        'expected_oos_date_count': len(expected_oos_dates),
        'row_count': int(len(universe)),
        'selected_row_count': int(universe['in_universe'].fillna(False).sum()) if 'in_universe' in universe else 0,
        'ticker_count': int(universe['ts_code'].nunique()) if 'ts_code' in universe else 0,
        'universe_ids': sorted(universe['universe_id'].astype(str).unique().tolist()) if 'universe_id' in universe else [],
        'duplicate_key_count': duplicate_key_count,
        'missing_dates': oos_missing_dates,
        'full_missing_dates': full_missing_dates,
        'missing_required_columns': missing_columns,
        'forbidden_alpha_columns_present': forbidden_columns_present,
        'required_universe_ids': REQUIRED_UNIVERSE_IDS,
        'missing_universe_dates': missing_universe_dates,
        'zero_selected_universe_dates': zero_selected_universe_dates[:20],
        'zero_selected_universe_date_count': len(zero_selected_universe_dates),
        'by_universe': summarize_by_universe(universe),
        'exclusion_counts': exclusion_counts,
        'dtype_by_required_field': dtype_by_field,
        'null_ratio_by_required_column': null_ratio,
        'local_worker_read_smoke': local_read_smoke,
        's3_worker_read_smoke': s3_read_smoke,
        'rules': {
            'market_cap_source_priority': ['circ_mv', 'total_mv'],
            'exclude_market_cap_lt_wan': args.min_market_cap_wan,
            'exclude_bottom_market_cap_count': f'ceil(n * {args.bottom_fraction}) per trade_date before microcap ranking',
            'small10': f'ceil(eligible_n * {args.small10_fraction}) smallest market-cap stocks after exclusions',
            'small20': f'ceil(eligible_n * {args.small20_fraction}) smallest market-cap stocks after exclusions',
            'exclude_new_stock_listing_days_lt': args.min_listing_days,
            'exclude_untradable': 'same-day daily vol<=0 or amount<=0 or close is null',
            'exclude_st': 'stock_st interval or stock name contains ST',
            'exclude_major_risk': 'stock_basic.list_status != L or stock name contains 退',
            'market_cap_unit': 'CNY 10k, Tushare daily_basic circ_mv/total_mv',
        },
        'hard_checks': hard_checks,
        'alpha_conclusion': 'not_evaluated_by_data_group',
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
    expected_full_dates = expected_open_dates(trade_calendar, args.start, args.end)
    expected_oos_dates = expected_open_dates(trade_calendar, args.oos_start, args.oos_end)
    universe = build_microcap_universe(
        daily_basic,
        stock_basic=stock_basic,
        trade_calendar=trade_calendar,
        stock_st=stock_st,
        daily_tradability=daily,
        bottom_fraction=args.bottom_fraction,
        microcap_fractions=(args.small10_fraction, args.small20_fraction),
        min_market_cap_wan=args.min_market_cap_wan,
        min_listing_days=args.min_listing_days,
    )
    write_partitioned(universe, output_root)
    smoke_dates = ['20250714', '20260612']
    if '20251231' in expected_oos_dates:
        smoke_dates.insert(1, '20251231')
    local_read_smoke = read_smoke_from_dataset(dataset_for_path(output_root), smoke_dates)
    catalog = build_catalog(args)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    s3_read_smoke = None
    if not args.skip_upload:
        run(['aws', 's3', 'cp', str(output_root), args.output_s3.rstrip('/'), '--recursive', '--only-show-errors'])
        run(['aws', 's3', 'cp', str(output_root), args.research_input_s3.rstrip('/'), '--recursive', '--only-show-errors'])
        s3_read_smoke = read_smoke_from_dataset(dataset_for_s3(args.output_s3), smoke_dates)

    proof = build_proof(
        universe,
        expected_full_dates,
        expected_oos_dates,
        args=args,
        raw_paths=raw_paths,
        local_read_smoke=local_read_smoke,
        s3_read_smoke=s3_read_smoke,
        runtime_seconds=time.perf_counter() - started,
    )
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not args.skip_upload:
        run(['aws', 's3', 'cp', str(proof_path), args.proof_s3, '--only-show-errors'])
        run(['aws', 's3', 'cp', str(catalog_path), args.catalog_s3, '--only-show-errors'])
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof['status'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
