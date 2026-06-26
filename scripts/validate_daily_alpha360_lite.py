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

from factor_factory.data_api.daily_alpha360_lite import (  # noqa: E402
    DailyAlpha360LiteParams,
    PRICE_FIELDS,
    VOLUME_FIELDS,
    build_daily_alpha360_lite_qa,
)


def _expected_columns(params: DailyAlpha360LiteParams) -> list[str]:
    columns = [params.symbol_col, params.date_col]
    for lag in range(params.lookback):
        columns.extend([f'{prefix}{lag}' for prefix in ['CLOSE', 'OPEN', 'HIGH', 'LOW', 'VWAP', 'VOLUME']])
    return columns


def _catalog_candidate(frame: pd.DataFrame, path: Path, qa_path: Path | None, params: DailyAlpha360LiteParams) -> dict[str, Any]:
    dates = frame[params.date_col].astype(str) if params.date_col in frame.columns and not frame.empty else pd.Series(dtype=str)
    partition_columns = [params.date_col] if path.is_dir() else []
    return {
        'dataset_id': 'daily_alpha360_lite_v1',
        'uri': str(path),
        'format': 'parquet',
        'version': 'v1',
        'storage': 'local',
        'description': 'Daily Qlib Alpha360-style normalized OHLCV/VWAP lag features.',
        'columns': list(frame.columns),
        'partition_columns': partition_columns,
        'date_column': params.date_col,
        'symbol_column': params.symbol_col,
        'metadata': {
            'source_dataset': 'clean_daily_bar',
            'schema_version': 'daily_alpha360_lite_v1',
            'producer_version': 'daily_alpha360_lite_builder_v1',
            'unique_key': [params.symbol_col, params.date_col],
            'sort_keys': [params.symbol_col, params.date_col],
            'partition_column': params.date_col if partition_columns else None,
            'lookback': int(params.lookback),
            'feature_family': 'alpha360_lite',
            'feature_count': int(params.lookback) * (len(PRICE_FIELDS) + len(VOLUME_FIELDS)),
            'information_set_legality': 'current and prior daily bars only; no future shifts',
            'qa_summary_path': str(qa_path) if qa_path else None,
        },
        'freshness': {
            'trade_date_min': str(dates.min()) if not dates.empty else None,
            'trade_date_max': str(dates.max()) if not dates.empty else None,
        },
    }


def validate_daily_alpha360_lite(
    *,
    feature_parquet: Path,
    qa_path: Path | None,
    params: DailyAlpha360LiteParams,
    min_row_count: int,
    max_warm_read_seconds: float | None,
    allow_partial_source_qa: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    frame = pd.read_parquet(feature_parquet)
    warm_read_seconds = float(time.perf_counter() - started)
    rebuilt_qa = build_daily_alpha360_lite_qa(frame, params=params)
    source_qa: dict[str, Any] = {}
    if qa_path is not None and qa_path.exists():
        source_qa = json.loads(qa_path.read_text(encoding='utf-8'))

    expected_columns = _expected_columns(params)
    actual_columns = list(frame.columns)
    missing_columns = [column for column in expected_columns if column not in frame.columns]
    unexpected_columns = [column for column in actual_columns if column not in expected_columns]
    issues: list[str] = []
    if rebuilt_qa.get('verdict') != 'ACCEPT':
        issues.append('rebuilt_qa_not_accept')
    if source_qa and source_qa.get('verdict') != 'ACCEPT':
        issues.append('source_qa_not_accept')
    if int(rebuilt_qa.get('row_count') or 0) < int(min_row_count):
        issues.append('row_count_below_minimum')
    if missing_columns:
        issues.append('missing_expected_columns')
    if unexpected_columns:
        issues.append('unexpected_columns')
    if max_warm_read_seconds is not None and warm_read_seconds > float(max_warm_read_seconds):
        issues.append('warm_read_seconds_above_maximum')
    if source_qa:
        for key in ['row_count', 'date_count', 'ticker_count', 'feature_count', 'duplicate_key_count']:
            if source_qa.get(key) != rebuilt_qa.get(key):
                if not allow_partial_source_qa:
                    issues.append(f'source_qa_mismatch:{key}')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': 'daily_alpha360_lite_v1',
        'schema_version': 'daily_alpha360_lite_v1',
        'feature_parquet': str(feature_parquet),
        'qa_path': str(qa_path) if qa_path else None,
        'warm_read_seconds': warm_read_seconds,
        'min_row_count': int(min_row_count),
        'max_warm_read_seconds': max_warm_read_seconds,
        'allow_partial_source_qa': bool(allow_partial_source_qa),
        'row_count': int(rebuilt_qa.get('row_count') or 0),
        'date_count': int(rebuilt_qa.get('date_count') or 0),
        'ticker_count': int(rebuilt_qa.get('ticker_count') or 0),
        'feature_count': int(rebuilt_qa.get('feature_count') or 0),
        'duplicate_key_count': int(rebuilt_qa.get('duplicate_key_count') or 0),
        'missing_columns': missing_columns,
        'unexpected_columns': unexpected_columns,
        'issues': issues,
        'rebuilt_qa': rebuilt_qa,
        'source_qa_summary': {
            key: source_qa.get(key)
            for key in ['verdict', 'row_count', 'date_count', 'ticker_count', 'feature_count', 'duplicate_key_count']
        } if source_qa else {},
        'catalog_candidate': _catalog_candidate(frame, feature_parquet, qa_path, params),
        'safety': {
            'starts_backfill': False,
            'writes_catalog': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a daily_alpha360_lite_v1 parquet and record warm-read proof.')
    parser.add_argument('--feature-parquet', required=True)
    parser.add_argument('--qa-path')
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--lookback', type=int, default=60)
    parser.add_argument('--min-row-count', type=int, default=1)
    parser.add_argument('--max-warm-read-seconds', type=float)
    parser.add_argument('--allow-partial-source-qa', action='store_true', help='Allow qa-path to describe only the latest resumable batch while validation rebuilds full output QA.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = validate_daily_alpha360_lite(
        feature_parquet=Path(args.feature_parquet).expanduser(),
        qa_path=Path(args.qa_path).expanduser() if args.qa_path else None,
        params=DailyAlpha360LiteParams(lookback=int(args.lookback)),
        min_row_count=int(args.min_row_count),
        max_warm_read_seconds=args.max_warm_read_seconds,
        allow_partial_source_qa=bool(args.allow_partial_source_qa),
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
