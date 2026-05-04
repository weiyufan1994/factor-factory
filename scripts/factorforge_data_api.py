#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import load_clean_daily_layer, resolve_clean_daily_layer_paths  # noqa: E402
from factor_factory.data_access.api import (  # noqa: E402
    build_data_requirement,
    describe_dataset,
    list_datasets,
    load_dataset,
    write_data_requirement,
)
from factor_factory.data_access.catalog import DatasetEntry, default_catalog_path, load_catalog, upsert_dataset  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='FactorForge data catalog/API CLI.')
    ap.add_argument('--catalog', help='Catalog JSON path. Defaults to FACTORFORGE_DATA_CATALOG or factorforge/data/catalog/data_catalog.json.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('list')

    describe = sub.add_parser('describe')
    describe.add_argument('dataset_id')

    sample = sub.add_parser('sample')
    sample.add_argument('dataset_id')
    sample.add_argument('--start')
    sample.add_argument('--end')
    sample.add_argument('--symbols')
    sample.add_argument('--columns')
    sample.add_argument('--limit', type=int, default=20)

    request = sub.add_parser('request')
    request.add_argument('dataset_id')
    request.add_argument('--reason', required=True)
    request.add_argument('--frequency')
    request.add_argument('--start')
    request.add_argument('--end')
    request.add_argument('--symbols')
    request.add_argument('--columns')
    request.add_argument('--required-transform')
    request.add_argument('--output', required=True)

    publish = sub.add_parser('publish-clean-daily')
    publish.add_argument('--dataset-id', default='clean_daily_bar')
    publish.add_argument('--s3-uri', required=True, help='Destination URI, e.g. s3://bucket/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet')
    publish.add_argument('--description', default='FactorForge cleaned daily bar layer')

    return ap.parse_args()


def split_csv(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or '').split(',') if item.strip()]


def cmd_publish_clean_daily(args: argparse.Namespace) -> None:
    paths = resolve_clean_daily_layer_paths()
    if not paths.daily_parquet.exists():
        raise SystemExit(f'missing clean daily parquet: {paths.daily_parquet}')
    if not paths.metadata_json.exists():
        raise SystemExit(f'missing clean daily metadata: {paths.metadata_json}')

    subprocess.run(['aws', 's3', 'cp', str(paths.daily_parquet), args.s3_uri, '--only-show-errors'], check=True)
    meta_uri = args.s3_uri.rsplit('.', 1)[0] + '.meta.json'
    subprocess.run(['aws', 's3', 'cp', str(paths.metadata_json), meta_uri, '--only-show-errors'], check=True)

    frame, meta = load_clean_daily_layer(columns=['ts_code', 'trade_date'], return_metadata=True)
    full_meta = json.loads(paths.metadata_json.read_text(encoding='utf-8'))
    columns = list(
        full_meta.get('clean_meta', {}).get('columns')
        or full_meta.get('output_summary', {}).get('columns')
        or []
    )
    if not columns:
        try:
            import pyarrow.parquet as pq

            columns = list(pq.read_schema(paths.daily_parquet).names)
        except Exception:
            columns = list(load_clean_daily_layer(columns=['ts_code', 'trade_date']).head(0).columns)
    entry = DatasetEntry(
        dataset_id=args.dataset_id,
        uri=args.s3_uri,
        format='parquet',
        storage='s3',
        version='v1',
        description=args.description,
        columns=tuple(columns),
        partition_columns=(),
        date_column='trade_date',
        symbol_column='ts_code',
        qlib_field_map={
            '$open': 'open',
            '$high': 'high',
            '$low': 'low',
            '$close': 'close',
            '$volume': 'vol',
            '$amount': 'amount',
        },
        freshness={
            'trade_date_min': str(frame['trade_date'].min()) if not frame.empty else None,
            'trade_date_max': str(frame['trade_date'].max()) if not frame.empty else None,
            'rows': int(meta['slice_summary']['rows']),
            'tickers': int(meta['slice_summary']['tickers'] or 0),
        },
        metadata={
            'source': 'materialize_clean_daily_layer',
            'metadata_uri': meta_uri,
            'local_source_meta': str(paths.metadata_json),
        },
    )
    catalog_path = upsert_dataset(entry, args.catalog)
    print(json.dumps({'catalog': str(catalog_path), 'dataset': entry.to_dict()}, ensure_ascii=False, indent=2))


def manual_request_resolution(args: argparse.Namespace) -> dict:
    catalog_path = Path(args.catalog).expanduser() if args.catalog else default_catalog_path()
    entries = load_catalog(catalog_path)
    return {
        'status': 'manual_request',
        'catalog_path': str(catalog_path),
        'catalog_exists': catalog_path.exists(),
        'dataset_id': args.dataset_id,
        'missing_fields': split_csv(args.columns),
        'resolved_fields': {},
        'available_datasets': sorted(entries),
    }


def main() -> None:
    args = parse_args()
    if args.cmd == 'list':
        print(json.dumps(list_datasets(args.catalog), ensure_ascii=False, indent=2))
    elif args.cmd == 'describe':
        print(json.dumps(describe_dataset(args.dataset_id, args.catalog), ensure_ascii=False, indent=2))
    elif args.cmd == 'sample':
        frame = load_dataset(
            args.dataset_id,
            start=args.start,
            end=args.end,
            symbols=split_csv(args.symbols),
            columns=split_csv(args.columns),
            catalog_path=args.catalog,
        )
        print(frame.head(args.limit).to_json(orient='records', force_ascii=False, date_format='iso'))
    elif args.cmd == 'request':
        requirement = build_data_requirement(
            args.dataset_id,
            reason=args.reason,
            start=args.start,
            end=args.end,
            symbols=split_csv(args.symbols),
            columns=split_csv(args.columns),
            frequency=args.frequency,
            required_transform=args.required_transform,
        )
        requirement['resolution'] = manual_request_resolution(args)
        path = write_data_requirement(requirement, args.output)
        print(json.dumps({'wrote': str(path), 'requirement': requirement}, ensure_ascii=False, indent=2))
    elif args.cmd == 'publish-clean-daily':
        cmd_publish_clean_daily(args)


if __name__ == '__main__':
    main()
