#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.flow_distribution_moments import (  # noqa: E402
    _build_threshold_frame,
    derive_intraday_flow_distribution_moments,
    derive_intraday_flow_distribution_moments_from_prepared,
    derive_intraday_flow_distribution_moments_numba_sorted_prepared,
    FlowDistributionParams,
    prepare_minute_frame,
)
from scripts.build_intraday_flow_distribution_moments import read_minute_root  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Compare vectorized and numba_sorted flow distribution moments.')
    parser.add_argument('--minute-root', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--cutoff-times', default='10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00')
    parser.add_argument('--threshold-lookback-days', default='20,60')
    parser.add_argument('--threshold-backend', default='pandas', choices=['pandas', 'polars'])
    parser.add_argument('--min-minutes', type=int, default=20)
    parser.add_argument('--tolerance', type=float, default=1e-9)
    parser.add_argument('--min-speedup-ratio', type=float, default=1.10)
    return parser.parse_args()


def split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(',') if item.strip())


def split_int_csv(raw: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in raw.split(',') if item.strip())


def _write_payload(output_path: str | Path, payload: dict[str, object]) -> None:
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _performance_promotion_summary(
    *,
    correctness_verdict: str,
    baseline_seconds: float,
    candidate_seconds: float,
    min_speedup_ratio: float,
) -> dict[str, object]:
    issues: list[str] = []
    baseline = float(baseline_seconds)
    candidate = float(candidate_seconds)
    speedup = baseline / candidate if baseline > 0.0 and candidate > 0.0 else 0.0
    if correctness_verdict != 'ACCEPT':
        issues.append('correctness_verdict_not_accept')
    if baseline <= 0.0 or candidate <= 0.0:
        issues.append('invalid_timing_seconds')
    elif speedup < float(min_speedup_ratio):
        issues.append('candidate_not_materially_faster')
    return {
        'performance_promotion_verdict': 'ACCEPT' if not issues else 'BLOCK',
        'performance_speedup_vs_vectorized': float(speedup),
        'performance_min_speedup_ratio': float(min_speedup_ratio),
        'performance_promotion_issues': issues,
    }


def _numba_block_payload(args: argparse.Namespace, issue: str, *, prepare_seconds: float, threshold_seconds: float, vectorized_seconds: float, vectorized_rows: int, missing_dates: list[str], source_profile_count: int) -> dict[str, object]:
    payload = {
        'verdict': 'BLOCK',
        'date': args.date,
        'row_count_vectorized': int(vectorized_rows),
        'row_count_numba_sorted': 0,
        'row_count_prepared_dispatcher': 0,
        'key_equal': False,
        'prepared_dispatcher_key_equal': False,
        'max_abs_diff': {},
        'tolerance': float(args.tolerance),
        'threshold_backend': args.threshold_backend,
        'prepare_seconds': float(prepare_seconds),
        'threshold_seconds': float(threshold_seconds),
        'vectorized_compute_seconds': float(vectorized_seconds),
        'numba_sorted_cold_compute_seconds': 0.0,
        'numba_sorted_warm_compute_seconds': 0.0,
        'numba_sorted_prepared_cold_seconds': 0.0,
        'numba_sorted_prepared_warm_seconds': 0.0,
        'prepared_dispatcher_backend': '',
        'prepared_dispatcher_cold_seconds': 0.0,
        'prepared_dispatcher_warm_seconds': 0.0,
        'missing_dates': missing_dates,
        'source_profile_count': int(source_profile_count),
        'issues': [issue],
    }
    payload.update(_performance_promotion_summary(
        correctness_verdict='BLOCK',
        baseline_seconds=vectorized_seconds,
        candidate_seconds=0.0,
        min_speedup_ratio=float(args.min_speedup_ratio),
    ))
    return payload


def main() -> int:
    args = parse_args()
    minute, source_profile, missing_dates = read_minute_root(
        Path(args.minute_root).expanduser(),
        [args.date],
        max(split_int_csv(args.threshold_lookback_days)),
    )
    common = {
        'cutoff_times': split_csv(args.cutoff_times),
        'threshold_lookback_days': split_int_csv(args.threshold_lookback_days),
        'threshold_backend': args.threshold_backend,
        'min_minutes': args.min_minutes,
        'research_window': 'SMOKE',
    }
    vectorized_params = FlowDistributionParams(**common, operator_backend='vectorized')
    numba_params = FlowDistributionParams(**common, operator_backend='numba_sorted')

    started = time.perf_counter()
    prepared_minute = prepare_minute_frame(minute)
    prepare_seconds = time.perf_counter() - started
    targets = {args.date}
    started = time.perf_counter()
    thresholds = _build_threshold_frame(
        prepared_minute,
        targets,
        int(numba_params.threshold_lookback_days[0]),
        numba_params.threshold_quantile,
        numba_params.threshold_backend,
    )
    threshold_seconds = time.perf_counter() - started

    started = time.perf_counter()
    vectorized = derive_intraday_flow_distribution_moments(minute, vectorized_params, target_dates=[args.date])
    vectorized_seconds = time.perf_counter() - started
    try:
        started = time.perf_counter()
        numba_sorted = derive_intraday_flow_distribution_moments(minute, numba_params, target_dates=[args.date])
        numba_cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        numba_sorted_warm = derive_intraday_flow_distribution_moments(minute, numba_params, target_dates=[args.date])
        numba_warm_seconds = time.perf_counter() - started
        started = time.perf_counter()
        numba_sorted_prepared = derive_intraday_flow_distribution_moments_numba_sorted_prepared(
            prepared_minute,
            numba_params,
            targets=targets,
            thresholds=thresholds,
        )
        numba_prepared_cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        numba_sorted_prepared_warm = derive_intraday_flow_distribution_moments_numba_sorted_prepared(
            prepared_minute,
            numba_params,
            targets=targets,
            thresholds=thresholds,
        )
        numba_prepared_warm_seconds = time.perf_counter() - started
        started = time.perf_counter()
        prepared_dispatcher = derive_intraday_flow_distribution_moments_from_prepared(prepared_minute, numba_params, target_dates=[args.date])
        prepared_dispatcher_cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        prepared_dispatcher_warm = derive_intraday_flow_distribution_moments_from_prepared(prepared_minute, numba_params, target_dates=[args.date])
        prepared_dispatcher_warm_seconds = time.perf_counter() - started
    except ImportError as exc:
        payload = _numba_block_payload(
            args,
            'numba_unavailable',
            prepare_seconds=prepare_seconds,
            threshold_seconds=threshold_seconds,
            vectorized_seconds=vectorized_seconds,
            vectorized_rows=len(vectorized),
            missing_dates=missing_dates,
            source_profile_count=len(source_profile),
        )
        payload['error'] = str(exc)
        _write_payload(args.output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    key = ['ts_code', 'trade_date', 'cutoff_time']
    columns = key + [
        'minute_count',
        'amount_sum',
        'ret_skew',
        'ret_tail_asymmetry',
        'amount_hhi',
        'amount_entropy',
        'signed_flow_hhi',
        'signed_flow_tail_asymmetry',
        'large_proxy_amount',
        'small_proxy_amount',
    ]
    left = vectorized[columns].sort_values(key).reset_index(drop=True)
    right = numba_sorted_prepared_warm[columns].sort_values(key).reset_index(drop=True)
    dispatcher_right = prepared_dispatcher_warm[columns].sort_values(key).reset_index(drop=True)
    max_abs_diff: dict[str, float] = {}
    for column in columns:
        if column in key:
            continue
        max_abs_diff[column] = float(
            (
                pd.to_numeric(left[column], errors='coerce')
                - pd.to_numeric(right[column], errors='coerce')
            ).abs().max()
        )

    max_diff = max(max_abs_diff.values()) if max_abs_diff else 0.0
    correctness_verdict = (
        'ACCEPT'
        if (
            left[key].equals(right[key])
            and right[key].equals(dispatcher_right[key])
            and len(left) == len(right) == len(dispatcher_right)
            and max_diff <= args.tolerance
        )
        else 'BLOCK'
    )
    payload = {
        'verdict': correctness_verdict,
        'date': args.date,
        'row_count_vectorized': int(len(vectorized)),
        'row_count_numba_sorted': int(len(numba_sorted_warm)),
        'row_count_prepared_dispatcher': int(len(prepared_dispatcher_warm)),
        'key_equal': bool(left[key].equals(right[key])),
        'prepared_dispatcher_key_equal': bool(right[key].equals(dispatcher_right[key])),
        'max_abs_diff': max_abs_diff,
        'tolerance': float(args.tolerance),
        'threshold_backend': args.threshold_backend,
        'prepare_seconds': float(prepare_seconds),
        'threshold_seconds': float(threshold_seconds),
        'vectorized_compute_seconds': float(vectorized_seconds),
        'numba_sorted_cold_compute_seconds': float(numba_cold_seconds),
        'numba_sorted_warm_compute_seconds': float(numba_warm_seconds),
        'numba_sorted_prepared_cold_seconds': float(numba_prepared_cold_seconds),
        'numba_sorted_prepared_warm_seconds': float(numba_prepared_warm_seconds),
        'prepared_dispatcher_backend': str(prepared_dispatcher_warm.attrs.get('operator_backend') or ''),
        'prepared_dispatcher_cold_seconds': float(prepared_dispatcher_cold_seconds),
        'prepared_dispatcher_warm_seconds': float(prepared_dispatcher_warm_seconds),
        'missing_dates': missing_dates,
        'source_profile_count': len(source_profile),
    }
    payload.update(_performance_promotion_summary(
        correctness_verdict=correctness_verdict,
        baseline_seconds=vectorized_seconds,
        candidate_seconds=prepared_dispatcher_warm_seconds,
        min_speedup_ratio=float(args.min_speedup_ratio),
    ))
    _write_payload(args.output_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
