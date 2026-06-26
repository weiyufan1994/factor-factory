#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.daily import get_daily
from factor_factory.data_access.daily_basic import get_daily_basic
from factor_factory.data_access.paths import resolve_local_tushare_paths
from factor_factory.data_api.universe_builders import MIN_MARKET_CAP_WAN, build_tradability_risk_flags_daily


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build reusable daily tradability/risk flags for investable universe filters.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20250711')
    ap.add_argument('--output-root', default='factorforge/data/datamart/tradability_risk_flags_daily')
    ap.add_argument('--qa-output', default='factorforge/data/proofs/tradability_risk_flags_daily.qa.json')
    ap.add_argument('--catalog-output', default='factorforge/data/catalog/tradability_risk_flags_daily.catalog.json')
    ap.add_argument('--min-market-cap-wan', type=float, default=MIN_MARKET_CAP_WAN)
    ap.add_argument('--min-listing-days', type=int, default=60)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    paths = resolve_local_tushare_paths(require_daily_basic=True)
    output_root = Path(args.output_root).expanduser()
    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()

    daily = get_daily(
        start=args.start,
        end=args.end,
        columns=['ts_code', 'trade_date', 'vol', 'amount', 'close'],
        paths=paths,
    )
    daily_basic = get_daily_basic(
        start=args.start,
        end=args.end,
        columns=['ts_code', 'trade_date', 'circ_mv', 'total_mv'],
        paths=paths,
    )
    stock_basic = pd.read_csv(
        paths.stock_basic_csv,
        usecols=lambda column: column in {'ts_code', 'name', 'list_status', 'list_date'},
        dtype={'ts_code': 'string', 'name': 'string', 'list_status': 'string', 'list_date': 'string'},
    )
    trade_calendar = pd.read_csv(
        paths.trade_cal_csv,
        usecols=lambda column: column in {'cal_date', 'is_open'},
        dtype={'cal_date': 'string'},
    )
    stock_st = pd.read_csv(
        paths.stock_st_csv,
        usecols=lambda column: column in {'ts_code', 'start_date', 'end_date', 'is_st'},
        dtype={'ts_code': 'string', 'start_date': 'string', 'end_date': 'string'},
    ) if paths.stock_st_csv.exists() else pd.DataFrame()

    flags = build_tradability_risk_flags_daily(
        daily,
        daily_basic=daily_basic,
        stock_basic=stock_basic,
        trade_calendar=trade_calendar,
        stock_st=stock_st,
        min_market_cap_wan=args.min_market_cap_wan,
        min_listing_days=args.min_listing_days,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    flags.to_parquet(output_root, partition_cols=['trade_date'], index=False)

    duplicate_key_count = int(flags.duplicated(['trade_date', 'ts_code']).sum()) if not flags.empty else 0
    qa = {
        'verdict': 'ACCEPT' if duplicate_key_count == 0 and not flags.empty else 'BLOCK',
        'dataset_id': 'tradability_risk_flags_daily',
        'source_dataset': 'daily + daily_basic + stock_basic + stock_st + trade_cal',
        'start': args.start,
        'end': args.end,
        'row_count': int(len(flags)),
        'date_count': int(flags['trade_date'].nunique()) if not flags.empty else 0,
        'ticker_count': int(flags['ts_code'].nunique()) if not flags.empty else 0,
        'duplicate_key_count': duplicate_key_count,
        'investable_counts': {
            'is_investable_core': int(flags['is_investable_core'].sum()) if 'is_investable_core' in flags.columns else 0,
            'is_investable_500m': int(flags['is_investable_500m'].sum()) if 'is_investable_500m' in flags.columns else 0,
        },
        'daily_investable_counts': {
            'core_min': int(flags[flags['is_investable_core']].groupby('trade_date')['ts_code'].nunique().min()) if flags['is_investable_core'].any() else 0,
            'core_median': float(flags[flags['is_investable_core']].groupby('trade_date')['ts_code'].nunique().median()) if flags['is_investable_core'].any() else 0.0,
            'core_max': int(flags[flags['is_investable_core']].groupby('trade_date')['ts_code'].nunique().max()) if flags['is_investable_core'].any() else 0,
            'investable_500m_min': int(flags[flags['is_investable_500m']].groupby('trade_date')['ts_code'].nunique().min()) if flags['is_investable_500m'].any() else 0,
            'investable_500m_median': float(flags[flags['is_investable_500m']].groupby('trade_date')['ts_code'].nunique().median()) if flags['is_investable_500m'].any() else 0.0,
            'investable_500m_max': int(flags[flags['is_investable_500m']].groupby('trade_date')['ts_code'].nunique().max()) if flags['is_investable_500m'].any() else 0,
        },
        'exclusion_counts': {
            column: int(flags[column].fillna(False).sum())
            for column in [
                'excluded_small_cap',
                'excluded_st',
                'excluded_new_stock',
                'excluded_untradable',
                'excluded_major_risk',
            ]
            if column in flags.columns
        },
        'rules': {
            'market_cap_source_priority': ['circ_mv', 'total_mv'],
            'exclude_market_cap_lt_wan': args.min_market_cap_wan,
            'exclude_new_stock_listing_days_lt': args.min_listing_days,
            'exclude_untradable': 'same-day daily vol<=0 or amount<=0 or close is null',
            'exclude_st': 'stock_st interval or stock name contains ST',
            'exclude_major_risk': 'stock_basic.list_status != L or stock name contains 退',
            'is_investable_core': 'not excluded_st/new_stock/untradable/major_risk',
            'is_investable_500m': 'is_investable_core and not excluded_small_cap',
            'market_cap_unit': 'CNY 10k, Tushare daily_basic circ_mv/total_mv',
        },
        'paths': {
            'raw_root': str(paths.root),
            'daily_basic_dir': str(paths.daily_basic_dir),
            'daily_csv': str(paths.daily_csv),
            'stock_basic_csv': str(paths.stock_basic_csv),
            'stock_st_csv': str(paths.stock_st_csv),
            'trade_cal_csv': str(paths.trade_cal_csv),
            'output_root': str(output_root),
        },
        'generated_at_utc': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    qa_output.parent.mkdir(parents=True, exist_ok=True)
    qa_output.write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding='utf-8')
    write_catalog(catalog_output, output_root, qa_output, args)
    print(json.dumps({
        'verdict': qa['verdict'],
        'dataset_id': qa['dataset_id'],
        'output_root': qa['paths']['output_root'],
        'qa_output': str(qa_output),
        'catalog_output': str(catalog_output),
        'row_count': qa['row_count'],
        'date_count': qa['date_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'investable_counts': qa['investable_counts'],
        'daily_investable_counts': qa['daily_investable_counts'],
    }, indent=2, ensure_ascii=False))
    return 0 if qa['verdict'] == 'ACCEPT' else 1


def write_catalog(catalog_output: Path, output_root: Path, qa_output: Path, args: argparse.Namespace) -> None:
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            'tradability_risk_flags_daily': {
                'uri': str(output_root),
                'format': 'parquet',
                'storage': 'local',
                'description': 'Reusable daily investability flags for universe post-filtering without mutating raw universe membership.',
                'columns': [
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
                ],
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'daily + daily_basic + stock_basic + stock_st + trade_cal',
                    'unique_key': ['trade_date', 'ts_code'],
                    'sort_keys': ['trade_date', 'ts_code'],
                    'qa_summary_path': str(qa_output),
                    'rules': {
                        'exclude_market_cap_lt_wan': args.min_market_cap_wan,
                        'exclude_new_stock_listing_days_lt': args.min_listing_days,
                        'is_investable_core': 'not excluded_st/new_stock/untradable/major_risk',
                        'is_investable_500m': 'is_investable_core and not excluded_small_cap',
                    },
                    'information_set_legality': 'uses same-day daily/daily_basic tradability and point-in-time listing/ST status available for same-day universe membership',
                },
                'freshness': {
                    'trade_date_min': args.start,
                    'trade_date_max': args.end,
                },
            },
        },
    }
    catalog_output.parent.mkdir(parents=True, exist_ok=True)
    catalog_output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
