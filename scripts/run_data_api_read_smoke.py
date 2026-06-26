#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api import DataApiClient, DataQuery, validate_data_api_result  # noqa: E402


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(',') if item.strip()]


def run_read_smoke(
    *,
    catalog_path: Path,
    dataset_id: str,
    start_date: str,
    end_date: str,
    fields: list[str],
    universe: str,
    frequency: str,
    max_warm_read_seconds: float | None,
    allow_duplicate_keys: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = DataApiClient.from_catalog(catalog_path).fetch(
        DataQuery(
            dataset=dataset_id,
            start_date=start_date,
            end_date=end_date,
            universe=universe,
            fields=fields,
            frequency=frequency,
            allow_duplicate_keys=allow_duplicate_keys,
        )
    )
    warm_read_seconds = float(time.perf_counter() - started)
    validation = validate_data_api_result(result)
    checks = [check.__dict__ for check in validation.checks]
    issues: list[str] = []
    if result.status not in {'ready', 'proxy_ready'}:
        issues.append('result_status_not_ready')
    if validation.result == 'BLOCK':
        issues.append('validation_result_block')
    if result.coverage.duplicate_key_count != 0 and not allow_duplicate_keys:
        issues.append('duplicate_key_count_nonzero')
    if max_warm_read_seconds is not None and warm_read_seconds > float(max_warm_read_seconds):
        issues.append('warm_read_seconds_above_maximum')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': dataset_id,
        'catalog_path': str(catalog_path),
        'status': result.status,
        'blocked_reason': result.blocked_reason,
        'validation_result': validation.result,
        'validation_checks': checks,
        'start_date': start_date,
        'end_date': end_date,
        'fields': fields,
        'universe': universe,
        'frequency': frequency,
        'allow_duplicate_keys': allow_duplicate_keys,
        'warm_read_seconds': warm_read_seconds,
        'max_warm_read_seconds': max_warm_read_seconds,
        'row_count': result.coverage.row_count,
        'date_count': result.coverage.date_count,
        'ticker_count': result.coverage.ticker_count,
        'duplicate_key_count': result.coverage.duplicate_key_count,
        'coverage': result.coverage.__dict__,
        'resolved_fields': result.resolved_fields,
        'source': result.source.__dict__,
        'freshness': result.freshness.__dict__,
        'returned_columns': list(result.frame.columns),
        'issues': issues,
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run a generic DataApiClient read-smoke against a catalog dataset.')
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--dataset-id', required=True)
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    parser.add_argument('--fields', required=True, help='Comma-separated requested fields.')
    parser.add_argument('--universe', default='a_share_all')
    parser.add_argument('--frequency', default='daily')
    parser.add_argument('--max-warm-read-seconds', type=float)
    parser.add_argument('--allow-duplicate-keys', action='store_true')
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_read_smoke(
        catalog_path=Path(args.catalog).expanduser(),
        dataset_id=str(args.dataset_id),
        start_date=str(args.start_date),
        end_date=str(args.end_date),
        fields=_split_csv(args.fields),
        universe=str(args.universe),
        frequency=str(args.frequency),
        max_warm_read_seconds=args.max_warm_read_seconds,
        allow_duplicate_keys=bool(args.allow_duplicate_keys),
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': payload['verdict'], 'output_path': str(output_path)}, ensure_ascii=False, indent=2))
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
