#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.daily_technical_state import FEATURE_COLUMNS  # noqa: E402
from factor_factory.data_api.datamart_contracts import build_closeout_skeleton, validate_closeout  # noqa: E402


DATASET_ID = 'daily_technical_state_v1'
SCHEMA_VERSION = 'daily_technical_state_v1'
PRODUCER_VERSION = 'daily_technical_state_builder_v1'
UNIQUE_KEY = ['ts_code', 'trade_date']


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'json root must be object: {source}')
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a closeout proof for daily_technical_state_v1.')
    parser.add_argument('--validation-path', required=True)
    parser.add_argument('--catalog-path', required=True)
    parser.add_argument('--read-smoke-path', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--batch1-manifest-path', default='')
    parser.add_argument('--batch2-manifest-path', default='')
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--worker-command', required=True)
    parser.add_argument('--required-start', default='20160104')
    parser.add_argument('--required-end', default='20250711')
    parser.add_argument('--min-row-count', type=int, default=1000000)
    parser.add_argument('--min-date-count', type=int, default=2000)
    return parser.parse_args(argv)


def _dataset_entry(catalog: dict[str, Any]) -> dict[str, Any]:
    datasets = catalog.get('datasets')
    if isinstance(datasets, dict):
        entry = datasets.get(DATASET_ID)
        return entry if isinstance(entry, dict) else {}
    return {}


def _load_optional(path: str) -> dict[str, Any]:
    return read_json(path) if path else {}


def _parameter_hash(validation: dict[str, Any], catalog_entry: dict[str, Any]) -> str:
    payload = {
        'dataset_id': DATASET_ID,
        'schema_version': validation.get('schema_version'),
        'feature_count': validation.get('feature_count'),
        'metadata': catalog_entry.get('metadata') or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()[:16]


def _block_token_for_issues(issues: list[str]) -> str:
    if any('read_smoke' in issue for issue in issues):
        return 'BLOCK_DATA_API_WORKER_READ_SMOKE_MISSING'
    if any('duplicate' in issue for issue in issues):
        return 'BLOCK_DATA_API_DERIVED_DATAMART_DUPLICATE_KEYS'
    if any('future' in issue or 'lookahead' in issue for issue in issues):
        return 'BLOCK_DATA_API_LOOKAHEAD_CONTRACT_MISSING'
    if any('coverage' in issue or 'date' in issue or 'row_count' in issue for issue in issues):
        return 'BLOCK_DATA_API_SOURCE_COVERAGE_INCOMPLETE'
    return 'BLOCK_DATA_API_DERIVED_DATAMART_QA_FAILED'


def build_closeout(
    *,
    validation: dict[str, Any],
    catalog: dict[str, Any],
    read_smoke: dict[str, Any],
    batch1_manifest: dict[str, Any],
    batch2_manifest: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    catalog_entry = _dataset_entry(catalog)
    metadata = catalog_entry.get('metadata') if isinstance(catalog_entry.get('metadata'), dict) else {}
    rebuilt_qa = validation.get('rebuilt_qa') if isinstance(validation.get('rebuilt_qa'), dict) else {}
    issues: list[str] = []

    if validation.get('verdict') != 'ACCEPT':
        issues.append('validation_verdict_not_accept')
    if validation.get('dataset_id') != DATASET_ID:
        issues.append('validation_dataset_id_invalid')
    if rebuilt_qa.get('verdict') != 'ACCEPT':
        issues.append('rebuilt_qa_verdict_not_accept')
    if not catalog_entry:
        issues.append('catalog_dataset_entry_missing')
    if read_smoke.get('verdict') != 'ACCEPT':
        issues.append('read_smoke_not_accept')
    if read_smoke.get('duplicate_key_count') not in {0, 0.0}:
        issues.append('read_smoke_duplicate_key_count_nonzero')

    output_start = str(rebuilt_qa.get('start_date') or '')
    output_end = str(rebuilt_qa.get('end_date') or '')
    if output_start != str(args.required_start):
        issues.append('coverage_start_mismatch')
    if output_end != str(args.required_end):
        issues.append('coverage_end_mismatch')
    if int(validation.get('row_count') or 0) < int(args.min_row_count):
        issues.append('row_count_below_minimum')
    if int(validation.get('date_count') or 0) < int(args.min_date_count):
        issues.append('date_count_below_minimum')
    if validation.get('duplicate_key_count') not in {0, 0.0}:
        issues.append('validation_duplicate_key_count_nonzero')
    if validation.get('missing_columns'):
        issues.append('missing_columns_nonempty')
    if validation.get('unexpected_columns'):
        issues.append('unexpected_columns_nonempty')
    if int(validation.get('feature_count') or 0) != len(FEATURE_COLUMNS):
        issues.append('feature_count_invalid')
    if rebuilt_qa.get('information_set_legality', {}).get('uses_future_rows') is not False:
        issues.append('lookahead_contract_uses_future_rows')
    if metadata.get('unique_key') != UNIQUE_KEY:
        issues.append('catalog_unique_key_invalid')
    if metadata.get('source_dataset') != 'clean_daily_bar':
        issues.append('catalog_source_dataset_invalid')
    if batch2_manifest and batch2_manifest.get('remaining_dates'):
        issues.append('batch2_manifest_remaining_dates_nonempty')

    verdict = 'ACCEPT' if not issues else 'BLOCK'
    closeout = build_closeout_skeleton(
        dataset_id=DATASET_ID,
        source_datasets=['clean_daily_bar'],
        unique_key=UNIQUE_KEY,
        producer_version=str(metadata.get('producer_version') or PRODUCER_VERSION),
        schema_version=str(metadata.get('schema_version') or SCHEMA_VERSION),
        verdict=verdict,
    )
    closeout['output_identity']['parameter_hash'] = _parameter_hash(validation, catalog_entry)
    closeout['source_coverage'].update({
        'start': str(args.required_start),
        'end': str(args.required_end),
        'missing_dates': [],
    })
    closeout['output_coverage'].update({
        'date_count': int(validation.get('date_count') or 0),
        'row_count': int(validation.get('row_count') or 0),
        'ticker_count': int(validation.get('ticker_count') or 0),
        'duplicate_key_count': int(validation.get('duplicate_key_count') or 0),
        'missing_dates': [],
        'unique_key': UNIQUE_KEY,
        'start': output_start,
        'end': output_end,
        'feature_count': int(validation.get('feature_count') or 0),
    })
    closeout['lookahead_contract'].update({
        'no_future_intraday_minutes': True,
        'threshold_source': 'not_applicable_daily_bars',
        'notes': 'Daily technical state uses current and prior daily bars only; no future shifts or OOS fitting.',
    })
    closeout['performance_profile'].update({
        'read_seconds': float(validation.get('warm_read_seconds') or 0.0),
        'compute_seconds': 0.0,
        'write_seconds': 0.0,
        'qa_seconds': 0.0,
        'warm_read_seconds_representative': float(read_smoke.get('warm_read_seconds') or 0.0),
    })
    closeout['catalog_path'] = str(Path(args.catalog_path).expanduser())
    closeout['datamart_path'] = str(catalog_entry.get('uri') or validation.get('feature_parquet') or '')
    closeout['qa_path'] = str(Path(args.validation_path).expanduser())
    closeout['worker_smoke_path'] = str(Path(args.read_smoke_path).expanduser())
    closeout['worker_read_smoke'].update({
        'instance_id': str(args.instance_id),
        'command': str(args.worker_command),
        'warm_read_seconds': float(read_smoke.get('warm_read_seconds') or 0.0),
        'verdict': str(read_smoke.get('verdict') or 'BLOCK'),
    })
    closeout['shard_manifest_path'] = str(Path(args.batch2_manifest_path).expanduser()) if args.batch2_manifest_path else ''
    closeout['notes'] = [
        'daily_technical_state_v1 closeout generated from validation/catalog/read-smoke artifacts',
        'active catalog registration remains a separate explicit step',
    ]
    closeout['batch_manifests'] = {'batch1': batch1_manifest, 'batch2': batch2_manifest}
    closeout['validation_issues'] = issues
    if verdict == 'BLOCK':
        closeout['block_token'] = _block_token_for_issues(issues)
    contract_issues = validate_closeout(closeout)
    if contract_issues:
        closeout['verdict'] = 'BLOCK'
        closeout['block_token'] = closeout.get('block_token') or 'BLOCK_DATA_API_DERIVED_DATAMART_QA_FAILED'
        closeout['contract_issues'] = [issue.to_dict() for issue in contract_issues]
    else:
        closeout['contract_issues'] = []
    return closeout


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    closeout = build_closeout(
        validation=read_json(args.validation_path),
        catalog=read_json(args.catalog_path),
        read_smoke=read_json(args.read_smoke_path),
        batch1_manifest=_load_optional(args.batch1_manifest_path),
        batch2_manifest=_load_optional(args.batch2_manifest_path),
        args=args,
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(closeout, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': closeout['verdict'], 'block_token': closeout.get('block_token', ''), 'output_path': str(output_path)}, ensure_ascii=False, indent=2))
    return 0 if closeout['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
