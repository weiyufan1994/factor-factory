#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.moneyflow_slow_state import (  # noqa: E402
    MoneyflowSlowStateParams,
    build_moneyflow_slow_state_qa,
    derive_moneyflow_slow_state_v1,
)


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(',') if item.strip())


def _split_float_csv(raw: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in raw.split(',') if item.strip())


def _build_synthetic_input(*, tickers: int, dates: int, cutoff_times: tuple[str, ...], seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = pd.Timestamp('2024-01-02')
    rows: list[dict[str, Any]] = []
    for ticker_idx in range(int(tickers)):
        ts_code = f'{ticker_idx + 1:06d}.SZ'
        level = 0.1 * (ticker_idx + 1)
        for date_idx in range(int(dates)):
            trade_date = (base + pd.Timedelta(days=date_idx)).strftime('%Y%m%d')
            signal_base = level + float(date_idx)
            for cutoff_time in cutoff_times:
                signed_flow = signal_base + float(rng.normal(0.0, 0.01))
                rows.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'cutoff_time': cutoff_time,
                    'v18a_z': signal_base / 10.0,
                    'v18b_z': 1.0 if (ticker_idx + date_idx) % 3 != 0 else -1.0,
                    'v19d_score': signed_flow,
                })
    return pd.DataFrame(rows)


def _load_input(args: argparse.Namespace, cutoff_times: tuple[str, ...]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if args.input_parquet:
        path = Path(args.input_parquet).expanduser()
        frame = pd.read_parquet(path)
        if int(args.row_limit or 0) > 0:
            frame = frame.head(int(args.row_limit)).copy()
        return frame, {
            'synthetic': False,
            'benchmark_scope': 'real_bounded_read_only',
            'source_path': str(path),
            'row_limit': int(args.row_limit or 0) or None,
        }
    frame = _build_synthetic_input(
        tickers=int(args.tickers),
        dates=int(args.dates),
        cutoff_times=cutoff_times,
        seed=int(args.seed),
    )
    return frame, {
        'synthetic': True,
        'benchmark_scope': 'synthetic_bounded',
        'tickers': int(args.tickers),
        'dates': int(args.dates),
        'seed': int(args.seed),
    }


def _frame_hash(frame: pd.DataFrame) -> str:
    cols = ['ts_code', 'trade_date', 'cutoff_time', 'lambda', 'h_slow_state', 'v20a_score', 'v20b_score', 'research_window']
    if frame.empty or not set(cols).issubset(frame.columns):
        return '0' * 64
    work = frame[cols].copy().sort_values(['ts_code', 'cutoff_time', 'lambda', 'trade_date']).reset_index(drop=True)
    for col in ['lambda', 'h_slow_state', 'v20a_score', 'v20b_score']:
        work[col] = pd.to_numeric(work[col], errors='coerce').astype(float).round(10)
    return hashlib.sha256(work.to_csv(index=False).encode('utf-8')).hexdigest()


def _profile_backend(frame: pd.DataFrame, *, backend: str, lambdas: tuple[float, ...], cutoff_times: tuple[str, ...], max_workers: int | None) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        params = MoneyflowSlowStateParams(
            lambdas=lambdas,
            cutoff_times=cutoff_times,
            operator_backend=backend,
            max_workers=max_workers,
        )
        out = derive_moneyflow_slow_state_v1(frame, params)
        qa = build_moneyflow_slow_state_qa(out)
        issues = [] if qa['verdict'] == 'ACCEPT' else ['qa_not_accept']
        realized_backend = str(out.attrs.get('operator_backend') or backend)
    except Exception as exc:
        out = pd.DataFrame()
        qa = {'verdict': 'BLOCK', 'duplicate_key_count': 0}
        issues = ['operator_backend_unavailable']
        realized_backend = backend
        error = str(exc)
    else:
        error = ''
    elapsed = time.perf_counter() - started
    payload: dict[str, Any] = {
        'profile_id': backend,
        'requested_backend': backend,
        'operator_backend': realized_backend,
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'elapsed_seconds': round(float(elapsed), 6),
        'row_count': int(len(out)),
        'ticker_count': int(out['ts_code'].nunique()) if not out.empty and 'ts_code' in out.columns else 0,
        'duplicate_key_count': int(qa.get('duplicate_key_count') or 0),
        'result_hash': _frame_hash(out),
        'issues': issues,
    }
    if max_workers is not None:
        payload['max_workers'] = int(max_workers)
    if error:
        payload['error'] = error
    return payload


def _summarize(profiles: list[dict[str, Any]], *, min_speedup_ratio: float) -> dict[str, Any]:
    accepted = [item for item in profiles if item.get('verdict') == 'ACCEPT']
    baseline = next((item for item in profiles if item.get('profile_id') == 'reference'), {})
    baseline_seconds = float(baseline.get('elapsed_seconds') or 0.0)
    accepted_row_counts = {int(item.get('row_count', -1)) for item in accepted}
    accepted_hashes = {str(item.get('result_hash') or '') for item in accepted}
    row_count_equal = bool(accepted) and len(accepted_row_counts) == 1
    duplicate_zero = bool(accepted) and all(int(item.get('duplicate_key_count', -1)) == 0 for item in accepted)
    hash_equal = bool(accepted) and len(accepted_hashes) == 1 and '' not in accepted_hashes
    candidates = [item for item in accepted if item.get('profile_id') != 'reference']
    best = min(candidates, key=lambda item: float(item.get('elapsed_seconds') or float('inf'))) if candidates else {}
    best_seconds = float(best.get('elapsed_seconds') or 0.0)
    speedup = baseline_seconds / best_seconds if baseline_seconds > 0.0 and best_seconds > 0.0 else 0.0
    issues: list[str] = []
    if not baseline or baseline.get('verdict') != 'ACCEPT':
        issues.append('baseline_not_accept')
    if not row_count_equal:
        issues.append('accepted_profile_row_count_mismatch')
    if not duplicate_zero:
        issues.append('accepted_profile_duplicate_keys')
    if not hash_equal:
        issues.append('accepted_profile_hash_mismatch')
    if speedup < float(min_speedup_ratio):
        issues.append('best_profile_not_materially_faster_than_reference')
    contract_ok = bool(baseline) and baseline.get('verdict') == 'ACCEPT' and row_count_equal and duplicate_zero and hash_equal
    performance_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_seconds = float(candidate.get('elapsed_seconds') or 0.0)
        candidate_speedup = baseline_seconds / candidate_seconds if baseline_seconds > 0.0 and candidate_seconds > 0.0 else 0.0
        if not contract_ok:
            performance_verdict = 'BLOCK'
        elif candidate_speedup >= float(min_speedup_ratio):
            performance_verdict = 'PROMOTE'
        else:
            performance_verdict = 'HOLD'
        performance_candidates.append({
            'operator_id': 'moneyflow_slow_state_v1',
            'baseline_backend': 'reference',
            'candidate_backend': str(candidate.get('requested_backend') or candidate.get('profile_id') or ''),
            'realized_backend': str(candidate.get('operator_backend') or ''),
            'performance_verdict': performance_verdict,
            'speedup': round(float(candidate_speedup), 6),
            'elapsed_seconds': float(candidate_seconds),
            'row_count': int(candidate.get('row_count') or 0),
            'duplicate_key_count': int(candidate.get('duplicate_key_count') or 0),
        })
    default_replacement_verdict = (
        'PROMOTE'
        if any(item['performance_verdict'] == 'PROMOTE' for item in performance_candidates)
        else ('HOLD' if contract_ok and performance_candidates else 'BLOCK')
    )
    return {
        'baseline_profile_id': 'reference',
        'baseline_profile_accept': bool(baseline) and baseline.get('verdict') == 'ACCEPT',
        'best_profile_id': str(best.get('profile_id') or ''),
        'best_speedup_vs_reference': round(float(speedup), 6),
        'min_speedup_ratio': float(min_speedup_ratio),
        'accepted_profile_row_count_equal': row_count_equal,
        'accepted_profile_duplicate_key_count_zero': duplicate_zero,
        'accepted_profile_key_hash_equal': hash_equal,
        'operator_replacement_verdict': default_replacement_verdict,
        'operator_replacement_issues': issues,
        'performance_gate': {
            'operator_id': 'moneyflow_slow_state_v1',
            'production_default_allowed': False,
            'default_replacement_verdict': default_replacement_verdict,
            'min_speedup_ratio': float(min_speedup_ratio),
            'baseline_profile_id': 'reference',
            'best_profile_id': str(best.get('profile_id') or ''),
            'best_speedup_vs_reference': round(float(speedup), 6),
            'candidates': performance_candidates,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Profile bounded moneyflow_slow_state_v1 operator backends.')
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--input-parquet')
    parser.add_argument('--row-limit', type=int, default=0)
    parser.add_argument('--tickers', type=int, default=128)
    parser.add_argument('--dates', type=int, default=240)
    parser.add_argument('--cutoff-times', default='14:50:00')
    parser.add_argument('--lambdas', default='0.70,0.85,0.93')
    parser.add_argument('--operator-backends', default='reference,array_grouped,process_sharded_array_grouped')
    parser.add_argument('--min-speedup-ratio', type=float, default=1.10)
    parser.add_argument('--max-workers', type=int, default=1)
    parser.add_argument('--seed', type=int, default=20260617)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cutoff_times = _split_csv(args.cutoff_times)
    lambdas = _split_float_csv(args.lambdas)
    frame, input_meta = _load_input(args, cutoff_times)
    profiles = [
        _profile_backend(
            frame,
            backend=backend,
            lambdas=lambdas,
            cutoff_times=cutoff_times,
            max_workers=int(args.max_workers),
        )
        for backend in _split_csv(args.operator_backends)
    ]
    summary = _summarize(profiles, min_speedup_ratio=float(args.min_speedup_ratio))
    payload = {
        'verdict': 'ACCEPT' if profiles and not any(item.get('verdict') == 'BLOCK' for item in profiles) else 'BLOCK',
        'dataset_id': 'moneyflow_slow_state_v1',
        'source_dataset': 'intraday_flow_distribution_moments_v1',
        'benchmark_scope': str(input_meta.get('benchmark_scope')),
        'production_default_allowed': False,
        'input': {
            **input_meta,
            'row_count': int(len(frame)),
            'cutoff_times': list(cutoff_times),
            'lambdas': list(lambdas),
        },
        'profile_count': len(profiles),
        'profiles': profiles,
        'safety': {
            'uses_real_market_data': bool(not input_meta.get('synthetic')),
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
        **summary,
    }
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
