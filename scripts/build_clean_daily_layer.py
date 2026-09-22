#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import (  # noqa: E402
    DailyFilterPolicy,
    default_clean_daily_layer_root,
    default_local_data_root,
    inspect_trade_date_csv_root,
    materialize_clean_daily_layer,
    resolve_local_tushare_paths,
)
from factor_factory.data_access.mutation_guard import require_data_mutation_authority  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build or refresh the shared cleaned daily layer used by Step3A and Step4.')
    ap.add_argument('--start')
    ap.add_argument('--end')
    ap.add_argument('--symbols', help='Comma-separated ts_code list.')
    ap.add_argument('--symbols-file', help='Text file with one ts_code per line.')
    ap.add_argument('--adjust-mode', choices=['forward', 'backward', 'none'], default='forward')
    ap.add_argument('--keep-bj', action='store_true')
    ap.add_argument('--keep-st', action='store_true')
    ap.add_argument('--min-listing-days', type=int, default=60)
    ap.add_argument('--keep-suspended', action='store_true')
    ap.add_argument('--keep-limit-events', action='store_true')
    ap.add_argument('--keep-abnormal-pct-move', action='store_true')
    ap.add_argument('--ensure-daily-basic', action='store_true', help='Require daily_basic cache to exist before building the clean layer.')
    ap.add_argument('--operator', default=None, help='Data mutation operator. Must be codex for shared clean-layer writes.')
    return ap.parse_args()


def parse_symbols(raw: str | None, symbols_file: str | None) -> list[str] | None:
    values: list[str] = []
    if raw:
        values.extend([item.strip() for item in raw.split(',') if item.strip()])
    if symbols_file:
        path = Path(symbols_file)
        if not path.exists():
            raise SystemExit(f'missing symbols file: {path}')
        values.extend([line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()])
    deduped = list(dict.fromkeys(values))
    return deduped or None


def build_policy(args: argparse.Namespace) -> DailyFilterPolicy:
    return replace(
        DailyFilterPolicy(),
        adjust_mode=args.adjust_mode,
        drop_bj=not args.keep_bj,
        drop_st=not args.keep_st,
        min_listing_days=args.min_listing_days,
        drop_suspended=not args.keep_suspended,
        drop_limit_events=not args.keep_limit_events,
        drop_abnormal_pct_move=not args.keep_abnormal_pct_move,
    )


def main() -> None:
    args = parse_args()
    require_data_mutation_authority(args.operator, operation='build_clean_daily_layer')
    symbols = parse_symbols(args.symbols, args.symbols_file)
    raw_paths = resolve_local_tushare_paths(require_daily_basic=args.ensure_daily_basic)
    if args.ensure_daily_basic and not inspect_trade_date_csv_root(raw_paths.daily_basic_dir):
        raise SystemExit(
            f'daily_basic cache not ready under {raw_paths.daily_basic_dir}; sync/update raw data first'
        )

    policy = build_policy(args)
    layer_paths, payload = materialize_clean_daily_layer(
        start=args.start,
        end=args.end,
        symbols=symbols,
        raw_paths=raw_paths,
        policy=policy,
    )
    print(f'[WRITE] {layer_paths.daily_parquet}')
    print(f'[WRITE] {layer_paths.metadata_json}')
    print(f'[ROOT] {layer_paths.root}')
    print(f'[RAW] {raw_paths.root}')
    print(f'[RAW_LABEL] {raw_paths.source_label}')
    print(f'[DEFAULT_RAW_ROOT] {default_local_data_root()}')
    print(f'[DEFAULT_CLEAN_ROOT] {default_clean_daily_layer_root()}')
    print(f'[ROWS] {payload["output_summary"]["rows"]}')
    print(f'[POLICY] {asdict(policy)}')


if __name__ == '__main__':
    main()
