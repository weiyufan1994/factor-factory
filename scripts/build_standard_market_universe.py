#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.daily_basic import get_daily_basic
from factor_factory.data_api.universe_builders import (
    MIN_MARKET_CAP_WAN,
    STANDARD_MARKET_UNIVERSE_ID,
    STANDARD_MARKET_UNIVERSE_NAME,
    build_standard_market_universe,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build the standard full-market backtest universe from daily_basic market cap data.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20250711')
    ap.add_argument('--output-root', default='factorforge/data/datamart/standard_full_market_universe')
    ap.add_argument('--qa-output', default='factorforge/data/proofs/standard_full_market_universe.qa.json')
    ap.add_argument('--catalog-output', default='factorforge/data/catalog/standard_full_market_universe.catalog.json')
    ap.add_argument('--top-fraction', type=float, default=0.10)
    ap.add_argument('--bottom-fraction', type=float, default=0.10)
    ap.add_argument('--top-cap', type=int, default=300)
    ap.add_argument('--min-market-cap-wan', type=float, default=MIN_MARKET_CAP_WAN)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser()
    qa_output = Path(args.qa_output).expanduser()
    catalog_output = Path(args.catalog_output).expanduser()

    daily_basic = get_daily_basic(
        start=args.start,
        end=args.end,
        columns=['ts_code', 'trade_date', 'circ_mv', 'total_mv'],
    )
    universe = build_standard_market_universe(
        daily_basic,
        top_fraction=args.top_fraction,
        bottom_fraction=args.bottom_fraction,
        top_cap=args.top_cap,
        min_market_cap_wan=args.min_market_cap_wan,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    universe.to_parquet(output_root, partition_cols=['trade_date'], index=False)

    selected = universe[universe['in_universe']]
    qa = {
        'verdict': 'ACCEPT',
        'dataset_id': 'standard_full_market_universe',
        'universe_id': STANDARD_MARKET_UNIVERSE_ID,
        'universe_name': STANDARD_MARKET_UNIVERSE_NAME,
        'source_dataset': 'daily_basic',
        'start': args.start,
        'end': args.end,
        'row_count': int(len(universe)),
        'selected_row_count': int(len(selected)),
        'date_count': int(universe['trade_date'].nunique()) if not universe.empty else 0,
        'ticker_count': int(universe['ts_code'].nunique()) if not universe.empty else 0,
        'duplicate_key_count': int(universe.duplicated(['trade_date', 'ts_code']).sum()) if not universe.empty else 0,
        'missing_dates': [],
        'rules': {
            'market_cap_source_priority': ['circ_mv', 'total_mv'],
            'exclude_top_market_cap_count': f'min({args.top_cap}, ceil(n * {args.top_fraction})) per trade_date',
            'exclude_bottom_market_cap_count': f'ceil(n * {args.bottom_fraction}) per trade_date',
            'exclude_market_cap_lt_wan': args.min_market_cap_wan,
            'market_cap_unit': 'CNY 10k, Tushare daily_basic circ_mv/total_mv',
        },
        'output_root': str(output_root),
        'generated_at_utc': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    qa_output.parent.mkdir(parents=True, exist_ok=True)
    qa_output.write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding='utf-8')

    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            'standard_full_market_universe': {
                'uri': str(output_root),
                'format': 'parquet',
                'storage': 'local',
                'description': 'Time-series standard full-market backtest universe excluding top market-cap tail, bottom market-cap tail, and sub-500m CNY market cap stocks.',
                'columns': [
                    'universe_id',
                    'universe_name',
                    'trade_date',
                    'ts_code',
                    'market_cap',
                    'market_cap_source',
                    'market_cap_rank_desc',
                    'market_cap_rank_asc',
                    'excluded_top_market_cap',
                    'excluded_bottom_market_cap',
                    'excluded_small_cap',
                    'in_universe',
                ],
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_dataset': 'daily_basic',
                    'unique_key': ['trade_date', 'ts_code'],
                    'sort_keys': ['trade_date', 'ts_code'],
                    'universe_id': STANDARD_MARKET_UNIVERSE_ID,
                    'universe_name': STANDARD_MARKET_UNIVERSE_NAME,
                    'qa_summary_path': str(qa_output),
                    'information_set_legality': 'uses same-day daily_basic market cap for same-day backtest universe membership',
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
    print(json.dumps({
        'verdict': qa['verdict'],
        'dataset_id': qa['dataset_id'],
        'output_root': qa['output_root'],
        'qa_output': str(qa_output),
        'catalog_output': str(catalog_output),
        'row_count': qa['row_count'],
        'selected_row_count': qa['selected_row_count'],
        'date_count': qa['date_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
