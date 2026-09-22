#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import (
    clean_daily_layer_ready,
    load_clean_daily_layer,
    resolve_clean_daily_layer_paths,
)
from scripts.build_report_qlib_provider import build_source_snapshot, dump_provider


LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
OUTPUT_ROOT = Path(
    os.getenv('FACTORFORGE_ROOT')
    or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT)
).expanduser()
RUNS = OUTPUT_ROOT / 'runs'
# COMMENT_POLICY: preprocessing_entrypoint
# This script now slices a report-scoped daily snapshot from the shared clean
# daily layer. Cleaning itself lives in scripts/build_clean_daily_layer.py.


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Slice a report-scoped daily snapshot from the shared clean daily layer.')
    ap.add_argument('--report-id', help='Write outputs into runs/<report_id>/... using standard FactorFactory paths.')
    ap.add_argument('--output-csv', help='Explicit output CSV path for the cleaned daily snapshot.')
    ap.add_argument('--metadata-json', help='Explicit metadata JSON path.')
    ap.add_argument('--provider-dir', help='Explicit qlib provider output dir.')
    ap.add_argument('--start')
    ap.add_argument('--end')
    ap.add_argument('--symbols', help='Comma-separated ts_code list.')
    ap.add_argument('--symbols-file', help='Text file with one ts_code per line.')
    ap.add_argument('--build-provider', action='store_true', help='Also build a report-scoped qlib provider from the cleaned snapshot.')
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


def resolve_output_paths(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    if args.report_id:
        base = RUNS / args.report_id
        csv_path = Path(args.output_csv) if args.output_csv else base / 'step3a_local_inputs' / f'daily_input__{args.report_id}.csv'
        meta_path = Path(args.metadata_json) if args.metadata_json else base / 'step3a_local_inputs' / f'daily_input_meta__{args.report_id}.json'
        provider_dir = Path(args.provider_dir) if args.provider_dir else ((base / 'qlib_provider') if args.build_provider else None)
        return csv_path, meta_path, provider_dir

    if not args.output_csv:
        raise SystemExit('either --report-id or --output-csv is required')
    csv_path = Path(args.output_csv)
    meta_path = Path(args.metadata_json) if args.metadata_json else csv_path.with_suffix('.meta.json')
    provider_dir = Path(args.provider_dir) if args.provider_dir else ((csv_path.parent / 'qlib_provider') if args.build_provider else None)
    return csv_path, meta_path, provider_dir


def main() -> None:
    args = parse_args()
    csv_path, meta_path, provider_dir = resolve_output_paths(args)
    symbols = parse_symbols(args.symbols, args.symbols_file)
    layer_paths = resolve_clean_daily_layer_paths()
    if not clean_daily_layer_ready(layer_paths):
        raise SystemExit(
            f'shared clean daily layer missing under {layer_paths.root}; run scripts/build_clean_daily_layer.py first'
        )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    daily_df, clean_meta = load_clean_daily_layer(
        start=args.start,
        end=args.end,
        symbols=symbols,
        layer_paths=layer_paths,
        return_metadata=True,
    )
    daily_df.to_csv(csv_path, index=False)

    payload = {
        'mode': 'shared_daily_preprocess',
        'report_id': args.report_id,
        'output_csv': str(csv_path),
        'metadata_json': str(meta_path),
        'clean_layer_root': str(layer_paths.root),
        'clean_layer_daily_parquet': str(layer_paths.daily_parquet),
        'clean_layer_metadata_json': str(layer_paths.metadata_json),
        'resolved_source_label': clean_meta.get('source_label', layer_paths.source_label),
        'request': {
            'start': args.start,
            'end': args.end,
            'symbols': symbols,
        },
        'policy': clean_meta.get('policy'),
        'clean_meta': clean_meta,
        'output_summary': {
            'rows': int(len(daily_df)),
            'tickers': int(daily_df['ts_code'].nunique()) if 'ts_code' in daily_df.columns else None,
            'trade_dates': int(daily_df['trade_date'].nunique()) if 'trade_date' in daily_df.columns else None,
        },
    }

    if args.build_provider:
        if provider_dir is None:
            raise SystemExit('provider_dir resolution failed')
        build_dir = provider_dir.parent / 'qlib_build'
        source_dir, stats = build_source_snapshot(args.report_id or 'adhoc', csv_path, build_dir)
        dump_provider(source_dir, provider_dir)
        payload['provider'] = {
            'provider_dir': str(provider_dir),
            'build_dir': str(build_dir),
            'source_dir': str(source_dir),
            'stats': stats,
        }

    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {csv_path}')
    print(f'[WRITE] {meta_path}')
    if args.build_provider and provider_dir is not None:
        print(f'[PROVIDER] {provider_dir}')


if __name__ == '__main__':
    main()
