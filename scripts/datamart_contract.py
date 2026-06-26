#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.catalog import DataCatalog, resolve_default_catalog_path  # noqa: E402
from factor_factory.data_api.datamart_contracts import (  # noqa: E402
    build_closeout_skeleton,
    build_datamart_inventory,
    build_shard_manifest_skeleton,
    read_json,
    validate_closeout,
    validate_shard_manifest,
    write_json,
)


def parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(',') if item.strip()]


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='FactorForge Data API datamart contract utilities.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    inventory = sub.add_parser('inventory')
    inventory.add_argument('--catalog', default='')
    inventory.add_argument('--output', default='')

    closeout = sub.add_parser('closeout-skeleton')
    closeout.add_argument('--dataset-id', required=True)
    closeout.add_argument('--source-datasets', default='')
    closeout.add_argument('--unique-key', default='')
    closeout.add_argument('--producer-version', default='')
    closeout.add_argument('--dataset-schema-version', default='')
    closeout.add_argument('--verdict', choices=['ACCEPT', 'BLOCK'], default='BLOCK')
    closeout.add_argument('--output', default='')

    validate_close = sub.add_parser('validate-closeout')
    validate_close.add_argument('path')

    shard = sub.add_parser('shard-manifest-skeleton')
    shard.add_argument('--dataset-id', required=True)
    shard.add_argument('--shard-id', default='')
    shard.add_argument('--output', default='')

    validate_shard = sub.add_parser('validate-shard-manifest')
    validate_shard.add_argument('path')

    return ap.parse_args()


def cmd_inventory(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog).expanduser() if args.catalog else resolve_default_catalog_path()
    inventory = build_datamart_inventory(DataCatalog.load(catalog_path))
    if args.output:
        target = write_json(args.output, inventory)
        print_json({'wrote': str(target), 'dataset_count': inventory['dataset_count']})
    else:
        print_json(inventory)
    return 0


def cmd_closeout_skeleton(args: argparse.Namespace) -> int:
    payload = build_closeout_skeleton(
        dataset_id=args.dataset_id,
        source_datasets=parse_csv(args.source_datasets),
        unique_key=parse_csv(args.unique_key),
        producer_version=args.producer_version,
        schema_version=args.dataset_schema_version,
        verdict=args.verdict,
    )
    if args.output:
        target = write_json(args.output, payload)
        print_json({'wrote': str(target), 'closeout': payload})
    else:
        print_json(payload)
    return 0


def cmd_validate_closeout(args: argparse.Namespace) -> int:
    payload = read_json(args.path)
    issues = validate_closeout(payload)
    print_json({'path': args.path, 'valid': not issues, 'issues': [issue.to_dict() for issue in issues]})
    return 0 if not issues else 2


def cmd_shard_manifest_skeleton(args: argparse.Namespace) -> int:
    payload = build_shard_manifest_skeleton(dataset_id=args.dataset_id, shard_id=args.shard_id)
    if args.output:
        target = write_json(args.output, payload)
        print_json({'wrote': str(target), 'shard_manifest': payload})
    else:
        print_json(payload)
    return 0


def cmd_validate_shard_manifest(args: argparse.Namespace) -> int:
    payload = read_json(args.path)
    issues = validate_shard_manifest(payload)
    print_json({'path': args.path, 'valid': not issues, 'issues': [issue.to_dict() for issue in issues]})
    return 0 if not issues else 2


def main() -> None:
    args = parse_args()
    if args.cmd == 'inventory':
        code = cmd_inventory(args)
    elif args.cmd == 'closeout-skeleton':
        code = cmd_closeout_skeleton(args)
    elif args.cmd == 'validate-closeout':
        code = cmd_validate_closeout(args)
    elif args.cmd == 'shard-manifest-skeleton':
        code = cmd_shard_manifest_skeleton(args)
    elif args.cmd == 'validate-shard-manifest':
        code = cmd_validate_shard_manifest(args)
    else:
        raise SystemExit(f'unknown command: {args.cmd}')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
