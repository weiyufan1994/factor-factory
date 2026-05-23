#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.operator_candidate_benchmarks import (
    OperatorCandidateResult,
    available_operator_candidates,
    available_ts_rank_candidates,
    compare_candidate_to_reference,
    compare_series_to_reference,
    prepare_ts_rank_frame,
)

VERSION = 'factorforge_operator_candidate_benchmark_v1'
CANONICAL_DIRS = ['objects', 'runs', 'evaluations', 'generated_code', 'archive', 'factorforge', 'data/clean']


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def is_tmp_path(path: Path) -> bool:
    text = str(path.expanduser().resolve())
    return text.startswith('/tmp/') or text.startswith('/private/tmp/')


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def snapshot_canonical_files(repo_root: Path) -> set[str]:
    out: set[str] = set()
    for raw_dir in CANONICAL_DIRS:
        root = repo_root / raw_dir
        if not root.exists():
            continue
        for item in root.rglob('*'):
            if item.is_file():
                out.add(str(item.relative_to(repo_root)))
    return out


def panel_fixture(*, ticker_count: int, days: int, seed: int, unsorted: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    ticker_count = max(int(ticker_count), 4)
    days = max(int(days), 12)
    for ticker_idx in range(ticker_count):
        code = f'S{ticker_idx:04d}'
        base = rng.normal(loc=0.0, scale=1.0, size=days).cumsum()
        left = base + rng.normal(scale=0.05, size=days)
        right = base * 0.4 + rng.normal(scale=0.08, size=days)
        value = base.copy()
        if ticker_idx < 3:
            value[2:4] = np.nan
            left[5] = np.nan
            right[6] = np.nan
        if ticker_idx in {3, 4}:
            value[5:10] = 7.0
        if ticker_idx == 1:
            left[0:10] = 1.0
        for day in range(days):
            rows.append({
                'ts_code': code,
                'trade_date': f'2020{(day // 28) + 1:02d}{(day % 28) + 1:02d}',
                'value': float(value[day]) if not np.isnan(value[day]) else np.nan,
                'left': float(left[day]) if not np.isnan(left[day]) else np.nan,
                'right': float(right[day]) if not np.isnan(right[day]) else np.nan,
            })
    frame = pd.DataFrame(rows)
    if unsorted:
        order = np.arange(len(frame))
        rng.shuffle(order)
        frame = frame.iloc[order].reset_index(drop=True)
    return frame


def measure_result(func: Callable[[], Any]) -> tuple[Any, float, float | None]:
    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = func()
    finally:
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    seconds = time.perf_counter() - started
    return result, seconds, float(peak / (1024 * 1024))


def _empty_parity() -> dict[str, Any]:
    return {
        'row_count_equal': None,
        'key_order_equal': None,
        'nan_mask_equal': None,
        'max_abs_diff': None,
        'rank_corr': None,
        'parity_pass': None,
    }


def run_candidate(
    operator: str,
    candidate_name: str,
    func: Callable,
    frame: pd.DataFrame,
    window: int,
    reference_values: pd.Series | None,
) -> dict[str, Any]:
    value_col = 'value'
    left_col = 'left'
    right_col = 'right'
    try:
        if operator in {'ts_argmin', 'ts_argmax'}:
            result, seconds, peak_mb = measure_result(lambda: func(frame, value_col, window))
        elif operator in {'rolling_corr', 'rolling_cov'}:
            result, seconds, peak_mb = measure_result(lambda: func(frame, left_col, right_col, window))
        elif operator == 'ts_rank':
            result, seconds, peak_mb = measure_result(lambda: func(frame, value_col, window))
        else:
            raise ValueError(f'unsupported operator: {operator}')
    except Exception as exc:
        return {
            'operator': operator,
            'candidate': candidate_name,
            'status': 'FAIL',
            'seconds': None,
            'rows_per_second': None,
            'peak_memory_mb': None,
            **_empty_parity(),
            'speedup_vs_reference': None,
            'safe_to_wire_into_step3b': False,
            'skip_reason': None,
            'failure_reason': f'{type(exc).__name__}: {exc}',
        }

    if getattr(result, 'status', None) == 'SKIP':
        return {
            'operator': operator,
            'candidate': candidate_name,
            'status': 'SKIP',
            'seconds': seconds,
            'rows_per_second': None,
            'peak_memory_mb': peak_mb,
            **_empty_parity(),
            'speedup_vs_reference': None,
            'safe_to_wire_into_step3b': False,
            'skip_reason': getattr(result, 'skip_reason', None),
            'failure_reason': getattr(result, 'failure_reason', None),
        }
    values = result.values
    status = getattr(result, 'status', 'PASS')
    parity = {
        'row_count_equal': True,
        'key_order_equal': True,
        'nan_mask_equal': True,
        'max_abs_diff': 0.0,
        'rank_corr': 1.0,
        'parity_pass': True,
    } if reference_values is None and candidate_name == 'pandas_reference' else _empty_parity()
    if reference_values is not None and values is not None:
        tolerance = 1e-10 if operator in {'rolling_corr', 'rolling_cov'} else 1e-12
        if operator == 'ts_rank':
            parity = compare_candidate_to_reference(frame, reference_values, values, tolerance=tolerance)
        else:
            parity = compare_series_to_reference(frame, reference_values, values, tolerance=tolerance)
    return {
        'operator': operator,
        'candidate': candidate_name,
        'status': status,
        'seconds': seconds,
        'rows_per_second': float(len(frame) / seconds) if seconds else None,
        'peak_memory_mb': peak_mb,
        **parity,
        'speedup_vs_reference': None,
        'safe_to_wire_into_step3b': False,
        'skip_reason': getattr(result, 'skip_reason', None),
        'failure_reason': getattr(result, 'failure_reason', None),
    }


def run_operator_case(case_name: str, frame: pd.DataFrame, window: int, include_ts_rank: bool) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    operators = available_operator_candidates()
    for operator, candidates in operators.items():
        reference = run_candidate(operator, 'pandas_reference', candidates['pandas_reference'], frame, window, None)
        reference_values = candidates['pandas_reference'](frame, 'value' if operator.startswith('ts_') else 'left', window).values if operator in {'ts_argmin', 'ts_argmax'} else candidates['pandas_reference'](frame, 'left', 'right', window).values
        reference_seconds = reference.get('seconds')
        results.append(reference)
        for candidate_name, func in candidates.items():
            if candidate_name == 'pandas_reference':
                continue
            item = run_candidate(operator, candidate_name, func, frame, window, reference_values)
            if item.get('seconds') is not None and reference_seconds:
                item['speedup_vs_reference'] = float(reference_seconds / item['seconds'])
            results.append(item)
    if include_ts_rank:
        ts_frame = prepare_ts_rank_frame(frame)
        ts_candidates = available_ts_rank_candidates()
        reference = run_candidate('ts_rank', 'pandas_reference', ts_candidates['pandas_reference'], ts_frame, window, None)
        reference_values = ts_candidates['pandas_reference'](ts_frame, 'value', window).values
        reference_seconds = reference.get('seconds')
        results.append(reference)
        for candidate_name, func in ts_candidates.items():
            if candidate_name == 'pandas_reference':
                continue
            item = run_candidate('ts_rank', candidate_name, func, ts_frame, window, reference_values)
            if item.get('seconds') is not None and reference_seconds:
                item['speedup_vs_reference'] = float(reference_seconds / item['seconds'])
            results.append(item)
    return {
        'case': case_name,
        'rows': int(len(frame)),
        'tickers': int(frame['ts_code'].nunique()),
        'dates': int(frame['trade_date'].nunique()),
        'window': int(window),
        'ts_rank_fixture_sorted_by_benchmark': bool(include_ts_rank),
        'results': results,
    }


def build_recommendations(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operators = ['ts_argmin', 'ts_argmax', 'rolling_corr', 'rolling_cov', 'ts_rank']
    recommendations: list[dict[str, Any]] = []
    for operator in operators:
        by_candidate: dict[str, list[dict[str, Any]]] = {}
        for case in cases:
            for result in case.get('results', []):
                if result.get('operator') == operator and result.get('candidate') != 'pandas_reference':
                    by_candidate.setdefault(str(result.get('candidate')), []).append(result)
        best_name = None
        best_speedup = None
        for name, items in by_candidate.items():
            if not items:
                continue
            if not all(item.get('status') == 'PASS' and item.get('parity_pass') is True for item in items):
                continue
            speedups = [float(item.get('speedup_vs_reference') or 0.0) for item in items]
            mean_speedup = float(sum(speedups) / len(speedups)) if speedups else 0.0
            if mean_speedup > 1.0 and (best_speedup is None or mean_speedup > best_speedup):
                best_name = name
                best_speedup = mean_speedup
        if best_name:
            recommendations.append({
                'operator': operator,
                'recommended_candidate': best_name,
                'speedup_vs_reference': best_speedup,
                'reason': 'fastest parity-passing candidate in benchmark fixtures',
                'safe_to_wire_into_step3b': False,
                'next_phase_required': 'RTA-07C opt-in experimental kernel implementation with smoke and reviewer approval',
            })
        else:
            recommendations.append({
                'operator': operator,
                'recommended_candidate': None,
                'speedup_vs_reference': None,
                'reason': 'no parity-passing candidate exceeded pandas reference speed',
                'safe_to_wire_into_step3b': False,
                'next_phase_required': 'keep pandas reference until better candidate exists',
            })
    return recommendations


def diagnostics() -> list[dict[str, str]]:
    return [
        {'severity': 'info', 'code': 'OPERATOR_CANDIDATE_BENCHMARK_READ_ONLY', 'message': 'Benchmark only writes the explicit output JSON.'},
        {'severity': 'info', 'code': 'PRODUCTION_OPERATOR_PATH_UNCHANGED', 'message': 'operators.py, kernels.py, Step3B, and Step4 are not modified or invoked by this benchmark.'},
        {'severity': 'info', 'code': 'ARGMIN_ARGMAX_CANDIDATES_BENCHMARKED', 'message': 'ts_argmin and ts_argmax numpy candidates were benchmarked against pandas reference.'},
        {'severity': 'info', 'code': 'CORR_COV_CANDIDATES_BENCHMARKED', 'message': 'rolling_corr and rolling_cov numpy formula candidates were benchmarked against pandas reference.'},
        {'severity': 'info', 'code': 'TS_RANK_EXISTING_CANDIDATES_INCLUDED', 'message': 'Existing ts_rank candidates are included only when --include-ts-rank is set.'},
    ]


def parse_windows(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(',') if item.strip()]


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    before = snapshot_canonical_files(REPO_ROOT)
    cases: list[dict[str, Any]] = []
    fixtures = [
        ('small_ties_nan_unsorted', panel_fixture(ticker_count=8, days=35, seed=args.seed, unsorted=True)),
        ('medium_panel_sorted', panel_fixture(ticker_count=args.ticker_count, days=args.days, seed=args.seed + 1, unsorted=False)),
        ('medium_panel_unsorted', panel_fixture(ticker_count=args.ticker_count, days=args.days, seed=args.seed + 2, unsorted=True)),
    ]
    for case_name, frame in fixtures:
        for window in parse_windows(args.windows):
            cases.append(run_operator_case(case_name, frame, window, args.include_ts_rank))
    operators = ['ts_argmin', 'ts_argmax', 'rolling_corr', 'rolling_cov'] + (['ts_rank'] if args.include_ts_rank else [])
    after = snapshot_canonical_files(REPO_ROOT)
    return {
        'version': VERSION,
        'generated_at': utc_now(),
        'repo_root': str(REPO_ROOT),
        'read_only': True,
        'production_semantics_changed': False,
        'operators': operators,
        'cases': cases,
        'recommendations': build_recommendations(cases),
        'diagnostics': diagnostics(),
        'canonical_pollution': bool(after - before),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    ap.add_argument('--allow-non-tmp-output', action='store_true')
    ap.add_argument('--windows', default='5,10,20')
    ap.add_argument('--ticker-count', type=int, default=120)
    ap.add_argument('--days', type=int, default=180)
    ap.add_argument('--seed', type=int, default=707)
    ap.add_argument('--include-ts-rank', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser()
    if not is_tmp_path(output) and not args.allow_non_tmp_output:
        print(f'BLOCK_OPERATOR_CANDIDATE_BENCHMARK_NON_TMP_OUTPUT: {output}', file=sys.stderr)
        return 1
    payload = build_payload(args)
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print(f'[WRITE] {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
