#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from factor_factory.data_api.intraday_operator_kernels import (
    group_offsets_from_sorted_frame,
    occupation_location_grouped_arrays,
    rolling_corr_1d,
    rolling_corr_grouped_arrays,
    terminal_corr_grouped_arrays,
)


def _build_synthetic_arrays(*, groups: int, rows_per_group: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    starts = np.arange(groups, dtype=np.int64) * int(rows_per_group)
    ends = starts + int(rows_per_group)
    total_rows = int(groups) * int(rows_per_group)
    group_base = np.repeat(8.0 + (np.arange(groups, dtype=np.float64) % 17.0), rows_per_group)
    price_steps = rng.normal(loc=0.0, scale=0.03, size=total_rows)
    price = group_base + np.concatenate([
        np.cumsum(price_steps[start:end])
        for start, end in zip(starts, ends, strict=True)
    ])
    volume = rng.integers(100, 5000, size=total_rows).astype(np.float64)
    amount = price * volume
    return {
        'starts': starts,
        'ends': ends,
        'price': price.astype(np.float64),
        'volume': volume,
        'amount': amount.astype(np.float64),
        'input_meta': {
            'synthetic': True,
            'groups': int(groups),
            'rows_per_group': int(rows_per_group),
            'row_count': int(total_rows),
            'seed': int(seed),
            'direct_array_inputs': True,
        },
        'benchmark_scope': 'synthetic_bounded_direct_array',
    }


def _load_parquet_arrays(
    *,
    input_parquet: str,
    row_limit: int | None,
    group_cols: list[str],
    order_col: str,
    price_col: str,
    volume_col: str,
    amount_col: str,
) -> dict[str, Any]:
    path = Path(input_parquet).expanduser()
    frame = pd.read_parquet(path)
    if row_limit is not None and row_limit > 0:
        frame = frame.head(int(row_limit)).copy()
    required = [*group_cols, order_col, price_col, volume_col]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f'input parquet missing required columns: {missing}')
    ordered = frame.sort_values([*group_cols, order_col]).reset_index(drop=True)
    offsets = group_offsets_from_sorted_frame(ordered, group_cols)
    price = pd.to_numeric(ordered[price_col], errors='coerce').to_numpy(dtype=np.float64)
    volume = pd.to_numeric(ordered[volume_col], errors='coerce').to_numpy(dtype=np.float64)
    if amount_col in ordered.columns:
        amount = pd.to_numeric(ordered[amount_col], errors='coerce').to_numpy(dtype=np.float64)
    else:
        amount = price * volume
    return {
        'starts': offsets.starts,
        'ends': offsets.ends,
        'price': price,
        'volume': volume,
        'amount': amount,
        'input_meta': {
            'synthetic': False,
            'source_format': 'parquet',
            'source_path': str(path),
            'row_limit': int(row_limit) if row_limit is not None and row_limit > 0 else None,
            'row_count': int(len(ordered)),
            'group_count': int(len(offsets.starts)),
            'group_cols': group_cols,
            'order_col': order_col,
            'price_col': price_col,
            'volume_col': volume_col,
            'amount_col': amount_col if amount_col in ordered.columns else None,
            'direct_array_inputs': True,
        },
        'benchmark_scope': 'real_bounded_direct_array',
    }


def _hash_array(values: np.ndarray) -> str:
    rounded = np.asarray(values, dtype=np.float64).round(8)
    return hashlib.sha256(rounded.tobytes()).hexdigest()


def _accepted_profile(
    *,
    operator_id: str,
    backend: str,
    elapsed_seconds: float,
    row_count: int,
    result_hash: str,
) -> dict[str, Any]:
    return {
        'operator_id': operator_id,
        'backend': backend,
        'verdict': 'ACCEPT',
        'elapsed_seconds': round(float(elapsed_seconds), 6),
        'row_count': int(row_count),
        'result_hash': result_hash,
        'issues': [],
    }


def _blocked_profile(*, operator_id: str, backend: str, elapsed_seconds: float, exc: Exception) -> dict[str, Any]:
    return {
        'operator_id': operator_id,
        'backend': backend,
        'verdict': 'BLOCK',
        'elapsed_seconds': round(float(elapsed_seconds), 6),
        'row_count': 0,
        'result_hash': None,
        'issues': [{'code': 'array_kernel_backend_unavailable', 'message': str(exc)}],
    }


def _reference_rolling_corr(starts: np.ndarray, ends: np.ndarray, x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros(len(x), dtype=np.float64)
    for start, end in zip(starts, ends, strict=True):
        result = rolling_corr_1d(x[start:end], y[start:end], window=window, backend='numpy')
        out[start:end] = result.values
    return out


def _reference_terminal_corr(starts: np.ndarray, ends: np.ndarray, x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros(len(starts), dtype=np.float64)
    for group_idx, (start, end) in enumerate(zip(starts, ends, strict=True)):
        if end - start < window:
            continue
        result = rolling_corr_1d(x[start:end], y[start:end], window=window, backend='numpy')
        out[group_idx] = result.values[-1] if len(result.values) else 0.0
    return out


def _reference_occupation(starts: np.ndarray, ends: np.ndarray, price: np.ndarray, volume: np.ndarray, amount: np.ndarray) -> np.ndarray:
    out = np.zeros((len(starts), 6), dtype=np.float64)
    for group_idx, (start, end) in enumerate(zip(starts, ends, strict=True)):
        group_price = price[start:end]
        group_volume = volume[start:end]
        group_amount = amount[start:end]
        valid_price = np.isfinite(group_price)
        count = float(valid_price.sum())
        if count > 0.0:
            price_sum = float(group_price[valid_price].sum())
            amount_sum = float(np.where(np.isfinite(group_amount[valid_price]), group_amount[valid_price], 0.0).sum())
            volume_sum = float(np.where(np.isfinite(group_volume[valid_price]), group_volume[valid_price], 0.0).sum())
            twap = price_sum / count
            vwap = amount_sum / volume_sum if volume_sum > 0.0 else 0.0
        else:
            amount_sum = 0.0
            volume_sum = 0.0
            twap = 0.0
            vwap = 0.0
        out[group_idx] = [count, amount_sum, volume_sum, twap, vwap, vwap - twap]
    return out


def _time_call(fn: Any) -> tuple[float, np.ndarray]:
    started = time.perf_counter()
    values = fn()
    return time.perf_counter() - started, np.asarray(values)


def _profile_reference_and_candidate(
    *,
    operator_id: str,
    reference_backend: str,
    candidate_backend: str,
    reference_fn: Any,
    candidate_fn: Any,
    tolerance: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    ref_seconds, ref_values = _time_call(reference_fn)
    profiles = [
        _accepted_profile(
            operator_id=operator_id,
            backend=reference_backend,
            elapsed_seconds=ref_seconds,
            row_count=int(ref_values.shape[0]),
            result_hash=_hash_array(ref_values),
        )
    ]
    try:
        candidate_seconds, candidate_values = _time_call(candidate_fn)
    except Exception as exc:
        profiles.append(_blocked_profile(operator_id=operator_id, backend=candidate_backend, elapsed_seconds=0.0, exc=exc))
        return profiles, issues
    profiles.append(
        _accepted_profile(
            operator_id=operator_id,
            backend=candidate_backend,
            elapsed_seconds=candidate_seconds,
            row_count=int(candidate_values.shape[0]),
            result_hash=_hash_array(candidate_values),
        )
    )
    if ref_values.shape != candidate_values.shape:
        issues.append({'code': 'array_kernel_shape_mismatch', 'operator_id': operator_id, 'backend': candidate_backend})
    elif not np.allclose(ref_values, candidate_values, rtol=tolerance, atol=tolerance):
        max_abs = float(np.nanmax(np.abs(ref_values - candidate_values))) if ref_values.size else 0.0
        issues.append({
            'code': 'array_kernel_value_mismatch',
            'operator_id': operator_id,
            'backend': candidate_backend,
            'max_abs_diff': max_abs,
            'tolerance': float(tolerance),
        })
    return profiles, issues


def _performance_gate(profiles: list[dict[str, Any]], *, min_speedup_for_default: float, benchmark_scope: str) -> dict[str, Any]:
    baseline_by_operator = {
        profile['operator_id']: profile
        for profile in profiles
        if profile['backend'] == 'reference_loop'
    }
    candidates: list[dict[str, Any]] = []
    for profile in profiles:
        if profile['backend'] == 'reference_loop':
            continue
        baseline = baseline_by_operator.get(profile['operator_id'])
        if baseline is None or profile.get('verdict') != 'ACCEPT':
            candidates.append({
                'operator_id': profile.get('operator_id'),
                'baseline_backend': 'reference_loop',
                'candidate_backend': profile.get('backend'),
                'speedup': None,
                'performance_verdict': 'BLOCK',
                'reason': 'baseline_missing_or_candidate_blocked',
            })
            continue
        baseline_seconds = float(baseline.get('elapsed_seconds') or 0.0)
        candidate_seconds = float(profile.get('elapsed_seconds') or 0.0)
        speedup = baseline_seconds / candidate_seconds if candidate_seconds > 0.0 else None
        verdict = 'PROMOTE' if speedup is not None and speedup >= float(min_speedup_for_default) else 'HOLD'
        candidates.append({
            'operator_id': profile.get('operator_id'),
            'baseline_backend': 'reference_loop',
            'candidate_backend': profile.get('backend'),
            'baseline_seconds': round(baseline_seconds, 6),
            'candidate_seconds': round(candidate_seconds, 6),
            'speedup': round(float(speedup), 6) if speedup is not None else None,
            'performance_verdict': verdict,
            'reason': 'speedup_gate_met' if verdict == 'PROMOTE' else 'speedup_gate_not_met',
        })
    return {
        'benchmark_scope': benchmark_scope,
        'production_default_allowed': False,
        'min_speedup_for_default': float(min_speedup_for_default),
        'candidates': candidates,
    }


def run_profile(
    *,
    groups: int,
    rows_per_group: int,
    window: int,
    seed: int,
    include_numba_grouped: bool,
    input_parquet: str | None = None,
    row_limit: int | None = None,
    group_cols: list[str] | None = None,
    order_col: str = 'hhmmss',
    price_col: str = 'price',
    volume_col: str = 'volume',
    amount_col: str = 'amount',
) -> dict[str, Any]:
    if input_parquet:
        arrays = _load_parquet_arrays(
            input_parquet=input_parquet,
            row_limit=row_limit,
            group_cols=group_cols or ['trade_date', 'ts_code'],
            order_col=order_col,
            price_col=price_col,
            volume_col=volume_col,
            amount_col=amount_col,
        )
    else:
        arrays = _build_synthetic_arrays(groups=groups, rows_per_group=rows_per_group, seed=seed)
    starts = arrays['starts']
    ends = arrays['ends']
    price = arrays['price']
    volume = arrays['volume']
    amount = arrays['amount']
    profiles: list[dict[str, Any]] = []
    comparison_issues: list[dict[str, Any]] = []

    specs = [
        (
            'rolling_corr_grouped_arrays',
            lambda: _reference_rolling_corr(starts, ends, price, volume, window),
            lambda backend='array_grouped': rolling_corr_grouped_arrays(starts, ends, price, volume, window=window, backend=backend).values,
            2e-5,
        ),
        (
            'terminal_corr_grouped_arrays',
            lambda: _reference_terminal_corr(starts, ends, price, volume, window),
            lambda backend='array_grouped': terminal_corr_grouped_arrays(starts, ends, price, volume, window=window, backend=backend).values,
            2e-5,
        ),
        (
            'occupation_location_grouped_arrays',
            lambda: _reference_occupation(starts, ends, price, volume, amount),
            lambda backend='array_grouped': occupation_location_grouped_arrays(starts, ends, price, volume, amount=amount, backend=backend).values,
            1e-8,
        ),
    ]
    for operator_id, reference_fn, candidate_builder, tolerance in specs:
        current_profiles, current_issues = _profile_reference_and_candidate(
            operator_id=operator_id,
            reference_backend='reference_loop',
            candidate_backend='array_grouped',
            reference_fn=reference_fn,
            candidate_fn=lambda builder=candidate_builder: builder('array_grouped'),
            tolerance=tolerance,
        )
        profiles.extend(current_profiles)
        comparison_issues.extend(current_issues)
        if include_numba_grouped:
            numba_profiles, numba_issues = _profile_reference_and_candidate(
                operator_id=operator_id,
                reference_backend='reference_loop',
                candidate_backend='numba_grouped',
                reference_fn=reference_fn,
                candidate_fn=lambda builder=candidate_builder: builder('numba_grouped'),
                tolerance=tolerance,
            )
            profiles.extend([profile for profile in numba_profiles if profile['backend'] != 'reference_loop'])
            comparison_issues.extend(numba_issues)

    verdict = 'ACCEPT'
    if comparison_issues or any(profile['verdict'] != 'ACCEPT' for profile in profiles):
        verdict = 'BLOCK'
    return {
        'verdict': verdict,
        'profile_count': len(profiles),
        'input': {
            **arrays['input_meta'],
            'window': int(window),
        },
        'profiles': profiles,
        'comparison_issues': comparison_issues,
        'performance_gate': _performance_gate(profiles, min_speedup_for_default=1.2, benchmark_scope=str(arrays['benchmark_scope'])),
        'safety': {
            'uses_real_market_data': bool(input_parquet),
            'starts_backfill': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Profile bounded direct-array intraday kernels on synthetic sorted arrays.')
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--groups', type=int, default=1024)
    parser.add_argument('--rows-per-group', type=int, default=240)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--seed', type=int, default=20260617)
    parser.add_argument('--input-parquet')
    parser.add_argument('--row-limit', type=int)
    parser.add_argument('--group-cols', default='trade_date,ts_code')
    parser.add_argument('--order-col', default='hhmmss')
    parser.add_argument('--price-col', default='price')
    parser.add_argument('--volume-col', default='volume')
    parser.add_argument('--amount-col', default='amount')
    parser.add_argument('--include-numba-grouped', action='store_true')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_profile(
        groups=int(args.groups),
        rows_per_group=int(args.rows_per_group),
        window=int(args.window),
        seed=int(args.seed),
        include_numba_grouped=bool(args.include_numba_grouped),
        input_parquet=args.input_parquet,
        row_limit=args.row_limit,
        group_cols=[col.strip() for col in str(args.group_cols).split(',') if col.strip()],
        order_col=str(args.order_col),
        price_col=str(args.price_col),
        volume_col=str(args.volume_col),
        amount_col=str(args.amount_col),
    )
    path = Path(args.output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
