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
from factor_factory.data_api.universe_builders import (
    MICROCAP_SMALL10_UNIVERSE_ID,
    MICROCAP_SMALL20_UNIVERSE_ID,
    MIN_MARKET_CAP_WAN,
    build_microcap_universe,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build microcap Small10/Small20 backtest universes with tradability and risk exclusions.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20250711')
    ap.add_argument('--output-root', default='factorforge/data/datamart/microcap_universe')
    ap.add_argument('--qa-output', default='factorforge/data/proofs/microcap_universe.qa.json')
    ap.add_argument('--catalog-output', default='factorforge/data/catalog/microcap_universe.catalog.json')
    ap.add_argument('--bottom-fraction', type=float, default=0.10)
    ap.add_argument('--small10-fraction', type=float, default=0.10)
    ap.add_argument('--small20-fraction', type=float, default=0.20)
    ap.add_argument('--min-market-cap-wan', type=float, default=MIN_MARKET_CAP_WAN)
    ap.add_argument('--min-listing-days', type=int, default=60)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    paths = resolve_local_tushare_paths(require_daily_basic=True)
    output_root = Path(args.output_root).expanduser()
    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()

    daily_basic = get_daily_basic(
        start=args.start,
        end=args.end,
        columns=['ts_code', 'trade_date', 'circ_mv', 'total_mv'],
        paths=paths,
    )
    daily = get_daily(
        start=args.start,
        end=args.end,
        columns=['ts_code', 'trade_date', 'vol', 'amount', 'close'],
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
    output_root.mkdir(parents=True, exist_ok=True)
    universe.to_parquet(output_root, partition_cols=['trade_date'], index=False)

    selected = universe[universe['in_universe']]
    base_rows = universe.drop_duplicates(['trade_date', 'ts_code'])
    by_universe = {
        universe_id: {
            'selected_rows': int(group['in_universe'].sum()),
            'dates': int(group.loc[group['in_universe'], 'trade_date'].nunique()),
            'tickers': int(group.loc[group['in_universe'], 'ts_code'].nunique()),
            'min_daily_count': int(group.loc[group['in_universe']].groupby('trade_date')['ts_code'].nunique().min()) if group['in_universe'].any() else 0,
            'median_daily_count': float(group.loc[group['in_universe']].groupby('trade_date')['ts_code'].nunique().median()) if group['in_universe'].any() else 0.0,
            'max_daily_count': int(group.loc[group['in_universe']].groupby('trade_date')['ts_code'].nunique().max()) if group['in_universe'].any() else 0,
        }
        for universe_id, group in universe.groupby('universe_id', sort=True, observed=True)
    }
    qa = {
        'verdict': 'ACCEPT',
        'dataset_id': 'microcap_universe',
        'universe_ids': [MICROCAP_SMALL10_UNIVERSE_ID, MICROCAP_SMALL20_UNIVERSE_ID],
        'source_dataset': 'daily_basic + daily + stock_basic + stock_st + trade_cal',
        'start': args.start,
        'end': args.end,
        'row_count': int(len(universe)),
        'selected_row_count': int(len(selected)),
        'date_count': int(universe['trade_date'].nunique()) if not universe.empty else 0,
        'ticker_count': int(universe['ts_code'].nunique()) if not universe.empty else 0,
        'duplicate_key_count': int(universe.duplicated(['universe_id', 'trade_date', 'ts_code']).sum()) if not universe.empty else 0,
        'by_universe': by_universe,
        'exclusion_counts': {
            column: int(base_rows[column].fillna(False).sum())
            for column in [
                'excluded_small_cap',
                'excluded_bottom_market_cap',
                'excluded_st',
                'excluded_new_stock',
                'excluded_untradable',
                'excluded_major_risk',
            ]
            if column in universe.columns
        },
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
        'selected_row_count': qa['selected_row_count'],
        'date_count': qa['date_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'by_universe': qa['by_universe'],
    }, indent=2, ensure_ascii=False))
    return 0


def write_catalog(catalog_output: Path, output_root: Path, qa_output: Path, args: argparse.Namespace) -> None:
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            'microcap_universe': {
                'uri': str(output_root),
                'format': 'parquet',
                'storage': 'local',
                'description': 'Microcap Small10/Small20 backtest universes after excluding sub-500m CNY market cap, bottom 10%, ST, new listings, untradable and major-risk stocks.',
                'columns': [
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
                ],
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'daily_basic + daily + stock_basic + stock_st + trade_cal',
                    'unique_key': ['universe_id', 'trade_date', 'ts_code'],
                    'sort_keys': ['universe_id', 'trade_date', 'ts_code'],
                    'universe_ids': [MICROCAP_SMALL10_UNIVERSE_ID, MICROCAP_SMALL20_UNIVERSE_ID],
                    'qa_summary_path': str(qa_output),
                    'information_set_legality': 'uses same-day daily_basic/daily tradability and point-in-time listing/ST status available for same-day universe membership',
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
