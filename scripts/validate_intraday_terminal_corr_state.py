#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.intraday_terminal_corr_state import (  # noqa: E402
    DATASET_ID,
    OUTPUT_COLUMNS,
    SCHEMA_VERSION,
    UNIQUE_KEY,
    build_catalog_entry,
    build_intraday_terminal_corr_state_qa,
)


def validate_intraday_terminal_corr_state(
    *,
    feature_parquet: Path,
    qa_path: Path | None,
    min_row_count: int,
    max_warm_read_seconds: float | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    frame = pd.read_parquet(feature_parquet)
    warm_read_seconds = float(time.perf_counter() - started)
    rebuilt_qa = build_intraday_terminal_corr_state_qa(frame, output_path=feature_parquet)
    source_qa: dict[str, Any] = {}
    if qa_path is not None and qa_path.exists():
        source_qa = json.loads(qa_path.read_text(encoding='utf-8'))
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    unexpected_columns = [column for column in frame.columns if column not in OUTPUT_COLUMNS]
    issues: list[str] = []
    if rebuilt_qa['verdict'] != 'ACCEPT':
        issues.append('rebuilt_qa_not_accept')
    if int(rebuilt_qa.get('row_count') or 0) < int(min_row_count):
        issues.append('row_count_below_minimum')
    if missing_columns:
        issues.append('missing_expected_columns')
    if unexpected_columns:
        issues.append('unexpected_columns')
    if rebuilt_qa.get('duplicate_key_count') not in {0, 0.0}:
        issues.append('duplicate_key_count_nonzero')
    legality = rebuilt_qa.get('information_set_legality') or {}
    if legality.get('no_future_intraday_minutes') is not True:
        issues.append('no_future_intraday_minutes_missing')
    if legality.get('terminal_only') is not True:
        issues.append('terminal_only_missing')
    if max_warm_read_seconds is not None and warm_read_seconds > float(max_warm_read_seconds):
        issues.append('warm_read_seconds_above_maximum')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'feature_parquet': str(feature_parquet),
        'qa_path': str(qa_path) if qa_path else None,
        'warm_read_seconds': warm_read_seconds,
        'min_row_count': int(min_row_count),
        'max_warm_read_seconds': max_warm_read_seconds,
        'row_count': int(rebuilt_qa.get('row_count') or 0),
        'date_count': int(rebuilt_qa.get('date_count') or 0),
        'ticker_count': int(rebuilt_qa.get('ticker_count') or 0),
        'duplicate_key_count': int(rebuilt_qa.get('duplicate_key_count') or 0),
        'missing_columns': missing_columns,
        'unexpected_columns': unexpected_columns,
        'issues': issues,
        'rebuilt_qa': rebuilt_qa,
        'source_qa_summary': {
            key: source_qa.get(key)
            for key in ['verdict', 'row_count', 'date_count', 'ticker_count', 'duplicate_key_count']
        } if source_qa else {},
        'catalog_candidate': build_catalog_entry(
            feature_parquet,
            qa_path or '',
            str(rebuilt_qa.get('start_date') or ''),
            str(rebuilt_qa.get('end_date') or ''),
        ),
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate intraday_terminal_corr_state_v1 parquet and warm-read proof.')
    parser.add_argument('--feature-parquet', required=True)
    parser.add_argument('--qa-path', default='')
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--min-row-count', type=int, default=1)
    parser.add_argument('--max-warm-read-seconds', type=float)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = validate_intraday_terminal_corr_state(
        feature_parquet=Path(args.feature_parquet).expanduser(),
        qa_path=Path(args.qa_path).expanduser() if args.qa_path else None,
        min_row_count=int(args.min_row_count),
        max_warm_read_seconds=args.max_warm_read_seconds,
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': payload['verdict'], 'output_path': str(output_path)}, ensure_ascii=False))
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
