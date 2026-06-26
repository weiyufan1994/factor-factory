#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.flow_distribution_moments import (  # noqa: E402
    FlowDistributionParams,
    P0_COLUMNS,
    PREPARED_MINUTE_COLUMNS,
    _build_threshold_frame,
    _derive_vectorized_for_cutoff,
    _finalize_output,
    derive_intraday_flow_distribution_moments_numba_sorted_prepared,
    normalize_trade_date,
    prepare_minute_frame,
)
from scripts.build_intraday_flow_distribution_moments import (  # noqa: E402
    discover_partition_dates,
    discover_source_ready_status,
    filter_source_ready_dates,
    read_minute_root,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Profile stage timings for intraday_flow_distribution_moments_v1 operators.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--minute-root')
    source.add_argument('--prepared-minute-root')
    parser.add_argument('--date', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--cutoff-times', default='10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00')
    parser.add_argument('--threshold-lookback-days', default='20,60')
    parser.add_argument('--threshold-quantile', type=float, default=0.75)
    parser.add_argument('--threshold-backend', default='pandas', choices=['pandas', 'polars'])
    parser.add_argument('--min-minutes', type=int, default=20)
    parser.add_argument('--operator-backend', default='vectorized', choices=['vectorized', 'numba_sorted'])
    parser.add_argument('--source-ready-only', action='store_true')
    return parser.parse_args()


def split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(',') if item.strip())


def split_int_csv(raw: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in raw.split(',') if item.strip())


def _derive_profiled_operator(
    prepared_minute: pd.DataFrame,
    params: FlowDistributionParams,
    *,
    targets: set[str],
    thresholds: pd.DataFrame,
) -> pd.DataFrame:
    backend = str(params.operator_backend or 'vectorized').lower()
    if backend == 'vectorized':
        frames = [
            _derive_vectorized_for_cutoff(
                prepared_minute,
                targets=targets,
                cutoff_time=cutoff_time,
                params=params,
                thresholds=thresholds,
            )
            for cutoff_time in params.cutoff_times
        ]
        non_empty = [frame for frame in frames if not frame.empty]
        if not non_empty:
            return _finalize_output(pd.DataFrame(columns=P0_COLUMNS), 'vectorized_profiled')
        return _finalize_output(pd.concat(non_empty, ignore_index=True), 'vectorized_profiled')
    if backend == 'numba_sorted':
        out = derive_intraday_flow_distribution_moments_numba_sorted_prepared(
            prepared_minute,
            params,
            targets=targets,
            thresholds=thresholds,
        )
        out.attrs['operator_backend'] = 'numba_sorted_profiled'
        return out
    raise ValueError(f'unsupported operator_backend for profiler: {params.operator_backend}')


def _dominant_stage(stage_seconds: dict[str, float]) -> str:
    candidates = {
        'read': stage_seconds['read_seconds'],
        'prepare': stage_seconds['prepare_seconds'],
        'threshold': stage_seconds['threshold_seconds'],
        'operator': stage_seconds['operator_seconds'],
        'total_overhead': stage_seconds['total_overhead_seconds'],
    }
    return max(candidates.items(), key=lambda item: item[1])[0]


def _write_payload(output_path: Path, payload: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _output_key_hash(frame: pd.DataFrame) -> str:
    key = ['ts_code', 'trade_date', 'cutoff_time']
    if frame.empty or not set(key).issubset(frame.columns):
        return '0' * 64
    keys = frame[key].astype(str).sort_values(key).drop_duplicates()
    text = '\n'.join('|'.join(row) for row in keys.itertuples(index=False, name=None))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main() -> int:
    args = parse_args()
    target_date = normalize_trade_date(args.date)
    params = FlowDistributionParams(
        cutoff_times=split_csv(args.cutoff_times),
        threshold_lookback_days=split_int_csv(args.threshold_lookback_days),
        threshold_quantile=float(args.threshold_quantile),
        threshold_backend=args.threshold_backend,
        min_minutes=int(args.min_minutes),
        research_window='SMOKE',
        operator_backend=args.operator_backend,
    )
    root = Path(args.prepared_minute_root or args.minute_root).expanduser()
    input_dataset = 'prepared_minute_bar_v1' if args.prepared_minute_root else 'minute_bar'
    available_dates = discover_partition_dates(root)
    source_not_ready_dates: list[str] = []
    if args.source_ready_only:
        available_dates, source_not_ready_dates = filter_source_ready_dates(
            available_dates,
            discover_source_ready_status(root),
        )

    started = time.perf_counter()
    read_started = time.perf_counter()
    minute, source_profile, missing_dates = read_minute_root(
        root,
        [target_date],
        max(params.threshold_lookback_days),
        available_dates=available_dates,
    )
    read_seconds = time.perf_counter() - read_started

    prepare_started = time.perf_counter()
    if minute.empty:
        prepared_minute = pd.DataFrame(columns=PREPARED_MINUTE_COLUMNS)
    else:
        prepared_minute = prepare_minute_frame(minute) if args.minute_root else minute
    prepare_seconds = time.perf_counter() - prepare_started

    targets = {target_date}
    threshold_started = time.perf_counter()
    thresholds = _build_threshold_frame(
        prepared_minute,
        targets,
        int(params.threshold_lookback_days[0]),
        params.threshold_quantile,
        params.threshold_backend,
    )
    threshold_seconds = time.perf_counter() - threshold_started

    operator_started = time.perf_counter()
    error = ''
    try:
        state = _derive_profiled_operator(prepared_minute, params, targets=targets, thresholds=thresholds)
    except ImportError as exc:
        state = pd.DataFrame(columns=P0_COLUMNS)
        error = str(exc)
    operator_seconds = time.perf_counter() - operator_started
    total_seconds = time.perf_counter() - started
    stage_seconds = {
        'read_seconds': float(read_seconds),
        'prepare_seconds': float(prepare_seconds),
        'threshold_seconds': float(threshold_seconds),
        'operator_seconds': float(operator_seconds),
        'total_overhead_seconds': float(max(0.0, total_seconds - read_seconds - prepare_seconds - threshold_seconds - operator_seconds)),
        'total_seconds': float(total_seconds),
    }
    duplicate_key_count = int(state.duplicated(['ts_code', 'trade_date', 'cutoff_time']).sum()) if not state.empty else 0
    issues: list[str] = []
    if error:
        issues.append('operator_backend_unavailable')
    if missing_dates:
        issues.append('missing_target_dates')
    if duplicate_key_count != 0:
        issues.append('duplicate_keys')
    if state.empty:
        issues.append('empty_output')

    payload = {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'date': target_date,
        'input_dataset': input_dataset,
        'operator_backend': str(params.operator_backend),
        'realized_operator_backend': str(state.attrs.get('operator_backend') or ''),
        'row_count': int(len(state)),
        'ticker_count': int(state['ts_code'].nunique()) if not state.empty else 0,
        'duplicate_key_count': duplicate_key_count,
        'output_key_hash': _output_key_hash(state),
        'missing_dates': missing_dates,
        'source_not_ready_dates': source_not_ready_dates,
        'source_profile_count': int(len(source_profile)),
        'input_minute_row_count': int(len(minute)),
        'prepared_minute_row_count': int(len(prepared_minute)),
        'threshold_row_count': int(len(thresholds)),
        'stage_seconds': stage_seconds,
        'dominant_stage': _dominant_stage(stage_seconds),
        'issues': issues,
    }
    if error:
        payload['error'] = error
    output_path = Path(args.output_path).expanduser()
    _write_payload(output_path, payload)
    return 0 if payload['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
