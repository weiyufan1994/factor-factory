#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.ts_rank_candidates import (  # noqa: E402
    available_candidates,
    compare_candidate_to_reference,
    prepare_ts_rank_frame,
)

VERSION = 'factorforge_ts_rank_candidate_benchmark_v1'
ALPHA017_DAILY_PARQUET = (
    REPO_ROOT
    / 'runs'
    / 'ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP'
    / 'step3a_local_inputs'
    / 'daily_input__ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP.parquet'
)
CANONICAL_DIRS = ['objects', 'runs', 'evaluations', 'generated_code', 'archive', 'factorforge', 'data/clean']


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def parse_windows(raw: str) -> list[int]:
    windows = []
    for chunk in str(raw or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        value = int(chunk)
        if value <= 0:
            raise SystemExit(f'BLOCK_TS_RANK_BENCHMARK_INVALID_WINDOW:{value}')
        windows.append(value)
    return windows or [5, 10, 20]


def is_tmp_root(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    text = str(resolved)
    return text.startswith('/tmp/') or text.startswith('/private/tmp/')


def snapshot_repo_files() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_DIRS:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        if root.is_file():
            files.add(str(root.relative_to(REPO_ROOT)))
            continue
        for path in root.rglob('*'):
            if path.is_file():
                files.add(str(path.relative_to(REPO_ROOT)))
    return files


def small_fixture() -> pd.DataFrame:
    rows = []
    for code in ['A', 'B', 'C']:
        for idx, dt in enumerate(pd.bdate_range('2020-01-01', periods=24)):
            value = float((idx * 5) % 9)
            if code == 'B' and idx in {7, 8, 9}:
                value = 4.0
            if code == 'C' and idx == 11:
                value = np.nan
            rows.append({'ts_code': code, 'trade_date': dt.strftime('%Y%m%d'), 'value': value})
    frame = pd.DataFrame(rows)
    return frame.iloc[[*range(2, len(frame), 3), *range(0, len(frame), 3), *range(1, len(frame), 3)]].reset_index(drop=True)


def panel_fixture(*, ticker_count: int, days: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range('2020-01-01', periods=days)
    rows = []
    for code_idx in range(ticker_count):
        code = f'S{code_idx:05d}'
        base = rng.normal(loc=0.0, scale=1.0, size=days).cumsum()
        values = base + (np.arange(days) % 17) * 0.01
        if code_idx % 19 == 0 and days > 40:
            values[20:23] = np.nan
        if code_idx % 23 == 0 and days > 70:
            values[50:54] = 3.0
        for day_idx, dt in enumerate(dates):
            rows.append({'ts_code': code, 'trade_date': dt.strftime('%Y%m%d'), 'value': float(values[day_idx])})
    return pd.DataFrame(rows)


def alpha017_sample(max_tickers: int) -> tuple[pd.DataFrame | None, str | None]:
    if not ALPHA017_DAILY_PARQUET.exists():
        return None, f'missing_alpha017_daily_parquet:{ALPHA017_DAILY_PARQUET}'
    frame = pd.read_parquet(ALPHA017_DAILY_PARQUET)
    if 'ts_code' not in frame.columns or 'trade_date' not in frame.columns:
        return None, 'alpha017_daily_missing_keys'
    value_col = 'close' if 'close' in frame.columns else None
    if not value_col:
        numeric_cols = [col for col in frame.columns if col not in {'ts_code', 'trade_date'} and pd.api.types.is_numeric_dtype(frame[col])]
        if not numeric_cols:
            return None, 'alpha017_daily_missing_numeric_value_column'
        value_col = numeric_cols[0]
    codes = sorted(pd.unique(frame['ts_code']))[:max_tickers]
    sample = frame[frame['ts_code'].isin(codes)][['ts_code', 'trade_date', value_col]].rename(columns={value_col: 'value'})
    return sample.reset_index(drop=True), None


def run_candidate(candidate_name: str, func, frame: pd.DataFrame, window: int, reference_values: pd.Series | None) -> dict[str, Any]:
    tracemalloc.start()
    start = time.perf_counter()
    try:
        candidate = func(frame, 'value', window)
        seconds = time.perf_counter() - start
        _current, peak = tracemalloc.get_traced_memory()
        if candidate.status == 'SKIP':
            return {
                'candidate': candidate_name,
                'status': 'SKIP',
                'seconds': seconds,
                'rows_per_second': None,
                'peak_memory_mb': peak / 1024 / 1024,
                'parity_pass': False,
                'max_abs_diff': None,
                'rank_corr': None,
                'nan_mask_equal': None,
                'key_order_equal': None,
                'speedup_vs_reference': None,
                'skip_reason': candidate.skip_reason,
                'failure_reason': None,
            }
        if candidate.values is None:
            raise RuntimeError('candidate returned no values')
        parity = {
            'parity_pass': True,
            'max_abs_diff': 0.0,
            'rank_corr': 1.0,
            'nan_mask_equal': True,
            'key_order_equal': True,
        }
        if reference_values is not None and candidate_name != 'pandas_reference':
            parity = compare_candidate_to_reference(frame, reference_values, candidate.values)
        return {
            'candidate': candidate_name,
            'status': 'PASS' if parity.get('parity_pass') else 'FAIL',
            'seconds': seconds,
            'rows_per_second': float(len(frame) / seconds) if seconds > 0 else None,
            'peak_memory_mb': peak / 1024 / 1024,
            'parity_pass': bool(parity.get('parity_pass')),
            'max_abs_diff': parity.get('max_abs_diff'),
            'rank_corr': parity.get('rank_corr'),
            'nan_mask_equal': parity.get('nan_mask_equal'),
            'key_order_equal': parity.get('key_order_equal'),
            'speedup_vs_reference': None,
            'skip_reason': None,
            'failure_reason': None if parity.get('parity_pass') else 'parity_failed',
        }
    except Exception as exc:
        seconds = time.perf_counter() - start
        _current, peak = tracemalloc.get_traced_memory()
        return {
            'candidate': candidate_name,
            'status': 'FAIL',
            'seconds': seconds,
            'rows_per_second': float(len(frame) / seconds) if seconds > 0 else None,
            'peak_memory_mb': peak / 1024 / 1024,
            'parity_pass': False,
            'max_abs_diff': None,
            'rank_corr': None,
            'nan_mask_equal': None,
            'key_order_equal': None,
            'speedup_vs_reference': None,
            'skip_reason': None,
            'failure_reason': f'{type(exc).__name__}:{exc}',
        }
    finally:
        tracemalloc.stop()


def run_case(case_name: str, raw_frame: pd.DataFrame, window: int) -> dict[str, Any]:
    frame = prepare_ts_rank_frame(raw_frame[['ts_code', 'trade_date', 'value']].copy())
    candidates = available_candidates()
    reference_result = run_candidate('pandas_reference', candidates['pandas_reference'], frame, window, None)
    reference_values = candidates['pandas_reference'](frame, 'value', window).values
    results = [reference_result]
    ref_seconds = float(reference_result.get('seconds') or 0.0)
    for name, func in candidates.items():
        if name == 'pandas_reference':
            continue
        result = run_candidate(name, func, frame, window, reference_values)
        if ref_seconds > 0 and result.get('seconds'):
            result['speedup_vs_reference'] = float(ref_seconds / float(result['seconds']))
        results.append(result)
    passing = [
        item for item in results
        if item['candidate'] != 'pandas_reference'
        and item.get('status') == 'PASS'
        and item.get('parity_pass') is True
        and item.get('speedup_vs_reference') is not None
    ]
    passing.sort(key=lambda item: float(item.get('speedup_vs_reference') or 0.0), reverse=True)
    recommended = passing[0]['candidate'] if passing and float(passing[0].get('speedup_vs_reference') or 0.0) > 1.0 else None
    return {
        'case': case_name,
        'rows': int(len(frame)),
        'tickers': int(frame['ts_code'].nunique()),
        'dates': int(frame['trade_date'].nunique()),
        'window': int(window),
        'results': results,
        'recommended_candidate': recommended,
        'recommendation_reason': (
            f'best parity-passing speedup {passing[0]["speedup_vs_reference"]:.3f}x'
            if recommended else 'no parity-passing candidate exceeded reference speed'
        ),
    }


def build_cases(*, windows: list[int], include_alpha017_sample: bool, include_full_alpha017: bool, max_tickers: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    small = small_fixture()
    medium = panel_fixture(ticker_count=80, days=160, seed=17)
    large = panel_fixture(ticker_count=300, days=250, seed=29)
    for window in windows:
        cases.append(run_case(f'small_ties_nan_window_{window}', small, window))
        cases.append(run_case(f'medium_panel_window_{window}', medium, window))
        cases.append(run_case(f'large_synthetic_panel_window_{window}', large, window))
    if include_alpha017_sample or include_full_alpha017:
        alpha_frame, skip_reason = alpha017_sample(max_tickers if not include_full_alpha017 else 10_000_000)
        if alpha_frame is None:
            for window in windows:
                cases.append({
                    'case': f'alpha017_sample_window_{window}',
                    'rows': 0,
                    'tickers': 0,
                    'dates': 0,
                    'window': int(window),
                    'results': [],
                    'recommended_candidate': None,
                    'recommendation_reason': skip_reason,
                    'skip_reason': skip_reason,
                    'ok': True,
                })
        else:
            label = 'alpha017_full' if include_full_alpha017 else 'alpha017_sample'
            for window in windows:
                cases.append(run_case(f'{label}_window_{window}', alpha_frame, window))
    return cases


def global_recommendation(cases: list[dict[str, Any]]) -> dict[str, Any]:
    alpha_cases = [case for case in cases if str(case.get('case', '')).startswith('alpha017_sample')]
    all_result_rows = [result for case in cases for result in case.get('results', [])]
    failed = [result for result in all_result_rows if result.get('status') == 'FAIL' and result.get('candidate') != 'pandas_reference']
    candidate_counts: dict[str, list[float]] = {}
    for case in alpha_cases:
        for result in case.get('results', []):
            if (
                result.get('candidate') != 'pandas_reference'
                and result.get('status') == 'PASS'
                and result.get('parity_pass') is True
                and result.get('speedup_vs_reference') is not None
            ):
                candidate_counts.setdefault(str(result['candidate']), []).append(float(result['speedup_vs_reference']))
    best_candidate = None
    best_speed = 0.0
    for candidate, speeds in candidate_counts.items():
        if speeds and min(speeds) > best_speed:
            best_candidate = candidate
            best_speed = min(speeds)
    safe_experimental = bool(best_candidate and best_speed >= 1.5 and not failed)
    return {
        'candidate': best_candidate if safe_experimental else None,
        'safe_to_promote_to_step3b_experimental': safe_experimental,
        'safe_to_make_default': False,
        'reason': (
            f'{best_candidate} passed alpha017 sample parity with minimum speedup {best_speed:.3f}x'
            if safe_experimental
            else 'N.3G does not promote a default; candidate requires parity and >=1.5x alpha017 sample speedup without pathologies'
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='/tmp/factorforge_ts_rank_candidate_benchmark_n3g')
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--include-alpha017-sample', action='store_true')
    ap.add_argument('--include-full-alpha017', action='store_true')
    ap.add_argument('--max-tickers', type=int, default=500)
    ap.add_argument('--windows', default='5,10,20')
    ap.add_argument('--write-report', action='store_true')
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not is_tmp_root(root):
        print(f'BLOCK_NON_TMP_FACTORFORGE_ROOT: {root}')
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = snapshot_repo_files()

    windows = parse_windows(args.windows)
    cases = build_cases(
        windows=windows,
        include_alpha017_sample=args.include_alpha017_sample,
        include_full_alpha017=args.include_full_alpha017,
        max_tickers=max(1, int(args.max_tickers)),
    )
    after = snapshot_repo_files()
    canonical_pollution = {'polluted': bool(after - before), 'new_files': sorted(after - before)}
    summary = {
        'version': VERSION,
        'created_at_utc': utc_now(),
        'verdict': 'ACCEPT',
        'candidates': list(available_candidates()),
        'cases': cases,
        'global_recommendation': global_recommendation(cases),
        'canonical_pollution': canonical_pollution,
        'notes': [
            'Benchmark-only harness. Does not change Step3B default path.',
            'pandas_reference remains correctness oracle.',
            'No full Step3B/Step4 wrapper was run.',
        ],
    }
    if canonical_pollution['polluted']:
        summary['verdict'] = 'BLOCK'
    out = root / 'ts_rank_candidate_benchmark_summary.json'
    write_json(out, summary)
    if args.write_report:
        report_path = REPO_ROOT / 'objects' / 'validation' / f'ts_rank_candidate_benchmark__{int(time.time())}.json'
        write_json(report_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f'[SUMMARY] {out}')
    return 0 if summary['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
