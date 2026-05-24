#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.kernels import (
    DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS,
    DEFAULT_NUMPY_TS_OPERATORS,
    resolve_formula_kernel_engine,
)
from factor_factory.formula.parser import parse_formula
from factor_factory.formula.polars_evaluator import assert_polars_result_parity

VERSION = 'factorforge_formula_kernel_benchmark_v1'
CANONICAL_DIRS = ['objects', 'runs', 'evaluations', 'generated_code', 'archive', 'factorforge', 'data/clean']
ROLLBACK_ENV = 'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL'


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


@contextmanager
def temporary_envs(values: dict[str, str | None]):
    old_values = {name: os.environ.get(name) for name in values}
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    try:
        yield
    finally:
        for name, old in old_values.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def synthetic_panel(*, ticker_count: int, days: int, seed: int, unsorted: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ticker_count = max(int(ticker_count), 4)
    days = max(int(days), 30)
    dates = pd.bdate_range('2020-01-02', periods=days)
    rows: list[dict[str, Any]] = []
    for ticker_idx in range(ticker_count):
        code = f'S{ticker_idx:05d}'
        trend = rng.normal(loc=0.0, scale=1.0, size=days).cumsum()
        close = 20.0 + trend + rng.normal(scale=0.05, size=days)
        high = close + np.abs(rng.normal(scale=0.4, size=days))
        low = close - np.abs(rng.normal(scale=0.4, size=days))
        volume = 1_000_000.0 + 1_000.0 * trend + rng.normal(scale=5_000.0, size=days)
        if ticker_idx % 17 == 0:
            close[7] = np.nan
            volume[11] = np.nan
        if ticker_idx % 23 == 0:
            close[13:17] = close[13]
        for day_idx, dt in enumerate(dates):
            rows.append({
                'ts_code': code,
                'trade_date': dt.strftime('%Y%m%d'),
                'close': float(close[day_idx]) if not np.isnan(close[day_idx]) else np.nan,
                'high': float(high[day_idx]) if not np.isnan(high[day_idx]) else np.nan,
                'low': float(low[day_idx]) if not np.isnan(low[day_idx]) else np.nan,
                'volume': float(volume[day_idx]) if not np.isnan(volume[day_idx]) else np.nan,
            })
    frame = pd.DataFrame(rows)
    if unsorted:
        order = np.arange(len(frame))
        rng.shuffle(order)
        frame = frame.iloc[order].reset_index(drop=True)
    return frame


def measure_formula(formula: str, frame: pd.DataFrame, *, rollback: bool, repeats: int) -> tuple[pd.DataFrame, dict[str, Any], float]:
    formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
    elapsed: list[float] = []
    result: pd.DataFrame | None = None
    profile: dict[str, Any] = {}
    env = {
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_TS_RANK_ENGINE': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
        'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
        ROLLBACK_ENV: '1' if rollback else None,
    }
    for _ in range(max(int(repeats), 1)):
        with temporary_envs(env):
            started = time.perf_counter()
            result, profile = evaluate_formula_frame(
                formula_ir,
                frame,
                engine='optimized',
                return_profile=True,
                formula_kernel_config=resolve_formula_kernel_engine(),
            )
            elapsed.append(time.perf_counter() - started)
    if result is None:
        raise RuntimeError('formula benchmark produced no result')
    return result, profile, float(median(elapsed))


def compare_default_to_rollback(rollback_result: pd.DataFrame, default_result: pd.DataFrame, *, tolerance: float) -> dict[str, Any]:
    try:
        parity = assert_polars_result_parity(rollback_result, default_result, tolerance=tolerance)
        return {**parity, 'parity_pass': True, 'parity_error': None, 'parity_tolerance': float(tolerance)}
    except AssertionError as exc:
        try:
            parity = assert_polars_result_parity(rollback_result, default_result, tolerance=float('inf'))
        except AssertionError:
            parity = {
                'parity_checked': True,
                'parity_sample_rows': int(len(rollback_result)),
                'max_abs_diff': None,
                'rank_corr': None,
                'row_count_equal': int(len(rollback_result)) == int(len(default_result)),
                'key_order_equal': False,
                'nan_mask_equal': False,
                'nan_mask_mismatch_count': None,
                'reference_nan_count': None,
                'candidate_nan_count': None,
                'mismatch_samples': [],
            }
        return {**parity, 'parity_pass': False, 'parity_error': str(exc), 'parity_tolerance': float(tolerance)}


def run_case(case: str, formula: str, frame: pd.DataFrame, *, repeats: int, tolerance: float) -> dict[str, Any]:
    default_result, default_profile, default_seconds = measure_formula(formula, frame, rollback=False, repeats=repeats)
    rollback_result, rollback_profile, rollback_seconds = measure_formula(formula, frame, rollback=True, repeats=repeats)
    parity = compare_default_to_rollback(rollback_result, default_result, tolerance=tolerance)
    speedup = float(rollback_seconds / default_seconds) if default_seconds > 0 else None
    return {
        'case': case,
        'formula': formula,
        'rows': int(len(frame)),
        'tickers': int(frame['ts_code'].nunique()),
        'days': int(frame['trade_date'].nunique()),
        'default_seconds': default_seconds,
        'rollback_seconds': rollback_seconds,
        'speedup_default_vs_rollback': speedup,
        'default_kernel_profile': default_profile.get('kernel_profile') or {},
        'rollback_kernel_profile': rollback_profile.get('kernel_profile') or {},
        **parity,
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    before = snapshot_canonical_files(REPO_ROOT)
    frame = synthetic_panel(
        ticker_count=args.ticker_count,
        days=args.days,
        seed=args.seed,
        unsorted=bool(args.unsorted),
    )
    cases = [
        run_case(
            'promoted_ts_mix',
            'mean(close, 20) + sum(volume, 20) + min(low, 10) + max(high, 10) + delta(close, 1) + delay(volume, 1) + argmin(close, 20) + argmax(volume, 20) + ts_rank(close, 20)',
            frame,
            repeats=args.repeats,
            tolerance=1e-7,
        ),
        run_case(
            'corr_cov_mix',
            'correlation(close, volume, 20) + covariance(close, volume, 20)',
            frame,
            repeats=args.repeats,
            tolerance=1e-7,
        ),
        run_case(
            'std_excluded_control',
            'std(close, 20) + mean(close, 20)',
            frame,
            repeats=args.repeats,
            tolerance=1e-9,
        ),
    ]
    after = snapshot_canonical_files(REPO_ROOT)
    canonical_pollution = bool(after - before)
    diagnostics = [
        {
            'code': 'FORMULA_KERNEL_BENCHMARK_READ_ONLY',
            'severity': 'info',
            'message': 'Benchmark uses synthetic panel only and does not write canonical Factor Forge artifacts.',
        },
        {
            'code': 'DEFAULT_NUMPY_TS_ROLLBACK_COMPARED',
            'severity': 'info',
            'message': f'Default Formula-IR kernel path was compared with {ROLLBACK_ENV}=1 rollback path.',
        },
    ]
    if any(case.get('parity_pass') is not True for case in cases):
        diagnostics.append({
            'code': 'FORMULA_KERNEL_BENCHMARK_PARITY_FAILED',
            'severity': 'block',
            'message': 'At least one benchmark case failed default-vs-rollback parity.',
        })
    if canonical_pollution:
        diagnostics.append({
            'code': 'FORMULA_KERNEL_BENCHMARK_CANONICAL_POLLUTION',
            'severity': 'block',
            'message': 'Benchmark created files in canonical Factor Forge artifact directories.',
        })
    verdict = 'ACCEPT' if all(case.get('parity_pass') is True for case in cases) and not canonical_pollution else 'BLOCK'
    return {
        'version': VERSION,
        'created_at_utc': utc_now(),
        'repo_root': str(REPO_ROOT),
        'read_only': True,
        'production_semantics_changed': False,
        'canonical_pollution': canonical_pollution,
        'canonical_pollution_new_files': sorted(after - before),
        'input_policy': 'synthetic_only_no_clean_data',
        'frame': {
            'rows': int(len(frame)),
            'ticker_count': int(frame['ts_code'].nunique()),
            'days': int(frame['trade_date'].nunique()),
            'unsorted_input': bool(args.unsorted),
            'seed': int(args.seed),
        },
        'default_numpy_ts_operators': sorted(DEFAULT_NUMPY_TS_OPERATORS),
        'default_numpy_ts_excluded_operators': sorted(DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS),
        'rollback_env': ROLLBACK_ENV,
        'repeats': int(args.repeats),
        'formula_cases': cases,
        'diagnostics': diagnostics,
        'verdict': verdict,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Benchmark default Formula-IR NumPy kernels against rollback pandas path.')
    parser.add_argument('--output', required=True, help='Output JSON path. Defaults to /tmp-only unless --allow-non-tmp-output is set.')
    parser.add_argument('--ticker-count', type=int, default=160)
    parser.add_argument('--days', type=int, default=520)
    parser.add_argument('--seed', type=int, default=1010)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--unsorted', action='store_true', help='Shuffle synthetic input before evaluation.')
    parser.add_argument('--allow-non-tmp-output', action='store_true')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser()
    if not args.allow_non_tmp_output and not is_tmp_path(output):
        print(f'BLOCK_FORMULA_KERNEL_BENCHMARK_NON_TMP_OUTPUT: {output}', file=sys.stderr)
        return 1
    payload = build_payload(args)
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get('verdict') == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
