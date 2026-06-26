#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.flow_distribution_moments import normalize_cutoff_time, normalize_trade_date  # noqa: E402


OUTPUT_COLUMNS = ['ts_code', 'trade_date', 'cutoff_time', 'v18a_z', 'v18b_z', 'v19d_score']
UNIQUE_KEY = ['ts_code', 'trade_date', 'cutoff_time']


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a read-only bounded parquet sample for moneyflow_slow_state_v1 benchmark gates.')
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--output-parquet', required=True)
    parser.add_argument('--proof-output', required=True)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--dates', help='Comma-separated trade dates. Overrides --start/--end.')
    parser.add_argument('--row-limit', type=int, default=0)
    parser.add_argument('--ts-code-col', default='ts_code')
    parser.add_argument('--trade-date-col', default='trade_date')
    parser.add_argument('--cutoff-time-col', default='cutoff_time')
    parser.add_argument('--v18a-col', default='v18a_z')
    parser.add_argument('--v18b-col', default='v18b_z')
    parser.add_argument('--v19d-col', default='v19d_score')
    return parser.parse_args(argv)


def _is_s3_uri(value: str) -> bool:
    return value.startswith('s3://')


def normalize_input_root(value: str) -> str:
    return value.rstrip('/') if _is_s3_uri(value) else str(Path(value).expanduser())


def partition_path(root: str, trade_date: str) -> str:
    if _is_s3_uri(root):
        return f'{root.rstrip("/")}/trade_date={trade_date}'
    return str(Path(root) / f'trade_date={trade_date}')


def discover_partition_dates(root: str) -> list[str]:
    if _is_s3_uri(root):
        return []
    dates: list[str] = []
    for path in Path(root).glob('trade_date=*'):
        if path.is_dir():
            dates.append(normalize_trade_date(path.name.split('=', 1)[1]))
    return sorted(set(dates))


def select_dates(*, root: str, dates: str | None, start: str | None, end: str | None) -> list[str]:
    available = discover_partition_dates(root)
    if dates:
        return sorted({normalize_trade_date(item) for item in dates.split(',') if item.strip()})
    if not available:
        return []
    start_date = normalize_trade_date(start or available[0])
    end_date = normalize_trade_date(end or available[-1])
    return [trade_date for trade_date in available if start_date <= trade_date <= end_date]


def _read_partition(root: str, trade_date: str) -> pd.DataFrame:
    path = partition_path(root, trade_date)
    if not _is_s3_uri(path) and not Path(path).exists():
        raise FileNotFoundError(f'missing partition: {path}')
    return pd.read_parquet(path)


def _normalize_frame(frame: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    source_cols = {
        'ts_code': args.ts_code_col,
        'trade_date': args.trade_date_col,
        'cutoff_time': args.cutoff_time_col,
        'v18a_z': args.v18a_col,
        'v18b_z': args.v18b_col,
        'v19d_score': args.v19d_col,
    }
    missing = [source for source in source_cols.values() if source not in frame.columns]
    if missing:
        raise ValueError(f'missing required columns: {missing}')
    out = pd.DataFrame({
        'ts_code': frame[source_cols['ts_code']].astype(str),
        'trade_date': frame[source_cols['trade_date']].map(normalize_trade_date),
        'cutoff_time': frame[source_cols['cutoff_time']].map(normalize_cutoff_time),
        'v18a_z': pd.to_numeric(frame[source_cols['v18a_z']], errors='coerce'),
        'v18b_z': pd.to_numeric(frame[source_cols['v18b_z']], errors='coerce'),
        'v19d_score': pd.to_numeric(frame[source_cols['v19d_score']], errors='coerce'),
    })
    out = out.dropna(subset=OUTPUT_COLUMNS).copy()
    return out[OUTPUT_COLUMNS]


def build_sample(*, input_root: str, selected_dates: list[str], row_limit: int, args: argparse.Namespace) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[pd.DataFrame] = []
    partitions: list[dict[str, Any]] = []
    read_errors: list[dict[str, Any]] = []
    for trade_date in selected_dates:
        try:
            raw = _read_partition(input_root, trade_date)
            if args.trade_date_col not in raw.columns:
                raw[args.trade_date_col] = trade_date
            normalized = _normalize_frame(raw, args)
        except Exception as exc:
            read_errors.append({'trade_date': trade_date, 'status': 'read_or_normalize_error', 'error': str(exc)})
            continue
        rows.append(normalized)
        partitions.append({
            'trade_date': trade_date,
            'row_count': int(len(normalized)),
            'ticker_count': int(normalized['ts_code'].nunique()) if not normalized.empty else 0,
            'source_path': partition_path(input_root, trade_date),
        })
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = out.sort_values(UNIQUE_KEY).reset_index(drop=True)
    if row_limit and row_limit > 0:
        out = out.head(int(row_limit)).copy()
    return out[OUTPUT_COLUMNS], partitions, read_errors


def build_proof(
    *,
    input_root: str,
    output_parquet: Path,
    selected_dates: list[str],
    frame: pd.DataFrame,
    partitions: list[dict[str, Any]],
    read_errors: list[dict[str, Any]],
    runtime_seconds: float,
    row_limit: int,
) -> dict[str, Any]:
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if not frame.empty else 0
    hard_checks = {
        'row_count_nonzero': len(frame) > 0,
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'read_errors_empty': not read_errors,
        'schema_columns_match': list(frame.columns) == OUTPUT_COLUMNS,
    }
    return {
        'verdict': 'ACCEPT' if all(hard_checks.values()) else 'BLOCK',
        'dataset_id': 'moneyflow_slow_state_benchmark_sample',
        'source_dataset': 'intraday_flow_distribution_moments_v1_or_derived_input',
        'input_root': str(input_root),
        'output_parquet': str(output_parquet),
        'selected_dates': selected_dates,
        'row_limit': int(row_limit),
        'row_count': int(len(frame)),
        'date_count': int(frame['trade_date'].nunique()) if not frame.empty else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if not frame.empty else 0,
        'duplicate_key_count': duplicate_key_count,
        'columns': OUTPUT_COLUMNS,
        'unique_key': UNIQUE_KEY,
        'semantic_scope': 'moneyflow_slow_state_operator_speed_benchmark_not_alpha_input',
        'hard_checks': hard_checks,
        'partitions': partitions,
        'read_errors': read_errors,
        'runtime_seconds': float(runtime_seconds),
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
        'generated_at_utc': utc_now(),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_root = normalize_input_root(str(args.input_root))
    output_parquet = Path(args.output_parquet).expanduser()
    proof_output = Path(args.proof_output).expanduser()
    selected_dates = select_dates(root=input_root, dates=args.dates, start=args.start, end=args.end)
    started = time.perf_counter()
    frame, partitions, read_errors = build_sample(
        input_root=input_root,
        selected_dates=selected_dates,
        row_limit=int(args.row_limit or 0),
        args=args,
    )
    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_parquet, index=False)
    proof = build_proof(
        input_root=input_root,
        output_parquet=output_parquet,
        selected_dates=selected_dates,
        frame=frame,
        partitions=partitions,
        read_errors=read_errors,
        runtime_seconds=time.perf_counter() - started,
        row_limit=int(args.row_limit or 0),
    )
    proof_output.parent.mkdir(parents=True, exist_ok=True)
    proof_output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'verdict': proof['verdict'],
        'output_parquet': str(output_parquet),
        'proof_output': str(proof_output),
        'row_count': proof['row_count'],
        'date_count': proof['date_count'],
        'duplicate_key_count': proof['duplicate_key_count'],
        'semantic_scope': proof['semantic_scope'],
    }, ensure_ascii=False, indent=2))
    return 0 if proof['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
