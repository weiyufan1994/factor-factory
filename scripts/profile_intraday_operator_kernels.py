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
    cpv_price_volume_corr_state,
    grouped_ema_state_by_group,
    intraday_occupation_location_state,
    rolling_corr_by_group,
    terminal_ema_state_by_group,
    terminal_rolling_corr_by_group,
)


def _build_synthetic_minute_frame(*, groups: int, rows_per_group: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for group_idx in range(groups):
        ts_code = f'{group_idx + 1:06d}.SZ'
        base_price = 8.0 + float(group_idx % 17)
        price_steps = rng.normal(loc=0.0, scale=0.03, size=rows_per_group).cumsum()
        volume = rng.integers(100, 5000, size=rows_per_group).astype(float)
        for minute_idx in range(rows_per_group):
            price = base_price + float(price_steps[minute_idx])
            rows.append({
                'ts_code': ts_code,
                'trade_date': '20240104',
                'hhmmss': 93000 + minute_idx * 100,
                'price': price,
                'volume': float(volume[minute_idx]),
                'amount': price * float(volume[minute_idx]),
            })
    return pd.DataFrame(rows)


def _load_input_frame(
    *,
    input_parquet: str | None,
    row_limit: int | None,
    groups: int,
    rows_per_group: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any], str]:
    if input_parquet:
        path = Path(input_parquet)
        frame = pd.read_parquet(path)
        if row_limit is not None and row_limit > 0:
            frame = frame.head(int(row_limit)).copy()
        required = ['ts_code', 'trade_date', 'hhmmss', 'price', 'volume']
        missing = [col for col in required if col not in frame.columns]
        if missing:
            raise ValueError(f'input parquet missing required columns: {missing}')
        if 'amount' not in frame.columns:
            frame = frame.copy()
            frame['amount'] = pd.to_numeric(frame['price'], errors='coerce') * pd.to_numeric(frame['volume'], errors='coerce')
        return frame, {
            'synthetic': False,
            'source_format': 'parquet',
            'source_path': str(path),
            'row_limit': int(row_limit) if row_limit is not None and row_limit > 0 else None,
            'row_count': int(len(frame)),
        }, 'real_bounded_read_only'

    frame = _build_synthetic_minute_frame(groups=groups, rows_per_group=rows_per_group, seed=seed)
    return frame, {
        'synthetic': True,
        'groups': int(groups),
        'rows_per_group': int(rows_per_group),
        'row_count': int(len(frame)),
    }, 'synthetic_bounded'


def _frame_hash(frame: pd.DataFrame, columns: list[str], sort_columns: list[str]) -> str:
    work = frame[columns].copy()
    work = work.sort_values(sort_columns).reset_index(drop=True)
    for col in work.select_dtypes(include=[np.number]).columns:
        work[col] = work[col].astype(float).round(8)
    payload = work.to_csv(index=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _accepted_profile(
    *,
    operator_id: str,
    backend: str,
    elapsed_seconds: float,
    row_count: int,
    result_hash: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        'operator_id': operator_id,
        'backend': backend,
        'verdict': 'ACCEPT',
        'elapsed_seconds': round(float(elapsed_seconds), 6),
        'row_count': int(row_count),
        'result_hash': result_hash,
        'issues': [],
    }
    if extra:
        payload.update(extra)
    return payload


def _blocked_profile(*, operator_id: str, backend: str, elapsed_seconds: float, exc: Exception) -> dict[str, Any]:
    return {
        'operator_id': operator_id,
        'backend': backend,
        'verdict': 'BLOCK',
        'elapsed_seconds': round(float(elapsed_seconds), 6),
        'row_count': 0,
        'result_hash': None,
        'issues': [{
            'code': 'operator_backend_unavailable',
            'message': str(exc),
        }],
    }


def _profile_rolling_corr(frame: pd.DataFrame, *, backend: str, window: int, max_workers: int | None = None) -> tuple[dict[str, Any], pd.DataFrame | None]:
    started = time.perf_counter()
    try:
        out = rolling_corr_by_group(
            frame,
            group_col='ts_code',
            order_col='hhmmss',
            x_col='price',
            y_col='volume',
            window=window,
            output_col='cpv_corr',
            backend=backend,
            max_workers=max_workers,
        )
    except Exception as exc:
        return _blocked_profile(
            operator_id='rolling_corr_by_group',
            backend=backend,
            elapsed_seconds=time.perf_counter() - started,
            exc=exc,
        ), None
    result_hash = _frame_hash(out, ['ts_code', 'trade_date', 'hhmmss', 'cpv_corr'], ['ts_code', 'trade_date', 'hhmmss'])
    return _accepted_profile(
        operator_id='rolling_corr_by_group',
        backend=backend,
        elapsed_seconds=time.perf_counter() - started,
        row_count=len(out),
        result_hash=result_hash,
    ), out


def _profile_occupation(frame: pd.DataFrame, *, backend: str, max_workers: int | None = None) -> tuple[dict[str, Any], pd.DataFrame | None]:
    started = time.perf_counter()
    try:
        out = intraday_occupation_location_state(
            frame,
            group_cols=['trade_date', 'ts_code'],
            price_col='price',
            volume_col='volume',
            amount_col='amount',
            backend=backend,
            max_workers=max_workers,
        )
    except Exception as exc:
        return _blocked_profile(
            operator_id='intraday_occupation_location_state',
            backend=backend,
            elapsed_seconds=time.perf_counter() - started,
            exc=exc,
        ), None
    result_hash = _frame_hash(
        out,
        ['trade_date', 'ts_code', 'bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap'],
        ['trade_date', 'ts_code'],
    )
    return _accepted_profile(
        operator_id='intraday_occupation_location_state',
        backend=backend if backend == 'pandas' else str(out.attrs.get('operator_backend') or backend),
        elapsed_seconds=time.perf_counter() - started,
        row_count=len(out),
        result_hash=result_hash,
    ), out


def _profile_ema_state(frame: pd.DataFrame, *, backend: str, max_workers: int | None = None) -> tuple[dict[str, Any], pd.DataFrame | None]:
    started = time.perf_counter()
    try:
        work = frame.copy()
        work['_ema_signal'] = pd.to_numeric(work['amount'], errors='coerce')
        out = grouped_ema_state_by_group(
            work,
            group_col='ts_code',
            order_col='hhmmss',
            signal_col='_ema_signal',
            decay=0.85,
            output_col='ema_state',
            backend=backend,
            max_workers=max_workers,
        )
    except Exception as exc:
        return _blocked_profile(
            operator_id='grouped_ema_state_by_group',
            backend=f'{backend}_ema_state' if backend in {'array_grouped', 'numba_grouped'} else backend,
            elapsed_seconds=time.perf_counter() - started,
            exc=exc,
        ), None
    result_hash = _frame_hash(out, ['ts_code', 'trade_date', 'hhmmss', 'ema_state'], ['ts_code', 'trade_date', 'hhmmss'])
    return _accepted_profile(
        operator_id='grouped_ema_state_by_group',
        backend=str(out.attrs.get('operator_backend') or f'{backend}_ema_state'),
        elapsed_seconds=time.perf_counter() - started,
        row_count=len(out),
        result_hash=result_hash,
        extra={'decay': 0.85},
    ), out


def _terminal_reference_from_full(full: pd.DataFrame, *, output_col: str) -> pd.DataFrame:
    return (
        full.sort_values(['trade_date', 'ts_code', 'hhmmss'])
        .groupby(['trade_date', 'ts_code'], sort=True)
        .tail(1)[['trade_date', 'ts_code', 'hhmmss', output_col]]
        .rename(columns={'hhmmss': 'terminal_order', output_col: 'terminal_corr'})
        .reset_index(drop=True)
    )


def _terminal_ema_reference_from_full(full: pd.DataFrame, *, output_col: str) -> pd.DataFrame:
    return (
        full.sort_values(['trade_date', 'ts_code', 'hhmmss'])
        .groupby(['trade_date', 'ts_code'], sort=True)
        .tail(1)[['trade_date', 'ts_code', 'hhmmss', output_col]]
        .rename(columns={'hhmmss': 'terminal_order', output_col: 'terminal_ema_state'})
        .reset_index(drop=True)
    )


def _profile_terminal_rolling_corr(
    frame: pd.DataFrame,
    *,
    backend: str,
    window: int,
    full_row_count: int,
    max_workers: int | None = None,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    started = time.perf_counter()
    try:
        out = terminal_rolling_corr_by_group(
            frame,
            group_cols=['trade_date', 'ts_code'],
            order_col='hhmmss',
            x_col='price',
            y_col='volume',
            window=window,
            output_col='terminal_corr',
            backend=backend,
            max_workers=max_workers,
        )
    except Exception as exc:
        return _blocked_profile(
            operator_id='terminal_rolling_corr_by_group',
            backend=f'{backend}_terminal' if backend in {'numpy', 'threaded_grouped', 'array_grouped', 'numba_grouped'} else backend,
            elapsed_seconds=time.perf_counter() - started,
            exc=exc,
        ), None
    result_hash = _frame_hash(
        out,
        ['trade_date', 'ts_code', 'terminal_order', 'bar_count', 'terminal_corr'],
        ['trade_date', 'ts_code'],
    )
    row_reduction_ratio = (float(len(out)) / float(full_row_count)) if full_row_count else 0.0
    return _accepted_profile(
        operator_id='terminal_rolling_corr_by_group',
        backend=str(out.attrs.get('operator_backend') or f'{backend}_terminal'),
        elapsed_seconds=time.perf_counter() - started,
        row_count=len(out),
        result_hash=result_hash,
        extra={
            'comparison_row_count': int(full_row_count),
            'row_reduction_ratio': round(row_reduction_ratio, 6),
        },
    ), out


def _profile_terminal_ema_state(
    frame: pd.DataFrame,
    *,
    backend: str,
    full_row_count: int,
    max_workers: int | None = None,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    started = time.perf_counter()
    try:
        work = frame.copy()
        work['_ema_signal'] = pd.to_numeric(work['amount'], errors='coerce')
        out = terminal_ema_state_by_group(
            work,
            group_cols=['trade_date', 'ts_code'],
            order_col='hhmmss',
            signal_col='_ema_signal',
            decay=0.85,
            output_col='terminal_ema_state',
            backend=backend,
            max_workers=max_workers,
        )
    except Exception as exc:
        return _blocked_profile(
            operator_id='terminal_ema_state_by_group',
            backend=f'{backend}_ema_terminal' if backend in {'array_grouped', 'numba_grouped'} else backend,
            elapsed_seconds=time.perf_counter() - started,
            exc=exc,
        ), None
    result_hash = _frame_hash(
        out,
        ['trade_date', 'ts_code', 'terminal_order', 'bar_count', 'terminal_ema_state'],
        ['trade_date', 'ts_code'],
    )
    row_reduction_ratio = (float(len(out)) / float(full_row_count)) if full_row_count else 0.0
    return _accepted_profile(
        operator_id='terminal_ema_state_by_group',
        backend=str(out.attrs.get('operator_backend') or f'{backend}_ema_terminal'),
        elapsed_seconds=time.perf_counter() - started,
        row_count=len(out),
        result_hash=result_hash,
        extra={
            'comparison_row_count': int(full_row_count),
            'row_reduction_ratio': round(row_reduction_ratio, 6),
            'decay': 0.85,
        },
    ), out


def _profile_cpv_operator(
    frame: pd.DataFrame,
    *,
    backend: str,
    window: int,
    terminal_only: bool,
    max_workers: int | None = None,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    output_col = 'cpv_terminal_corr' if terminal_only else 'cpv_corr'
    started = time.perf_counter()
    try:
        out = cpv_price_volume_corr_state(
            frame,
            window=window,
            backend=backend,
            max_workers=max_workers,
            output_col=output_col,
            terminal_only=terminal_only,
        )
    except Exception as exc:
        return _blocked_profile(
            operator_id='cpv_price_volume_corr_state',
            backend=f'{backend}_terminal' if terminal_only else backend,
            elapsed_seconds=time.perf_counter() - started,
            exc=exc,
        ), None
    if terminal_only:
        result_hash = _frame_hash(
            out,
            ['trade_date', 'ts_code', 'terminal_order', 'bar_count', output_col],
            ['trade_date', 'ts_code'],
        )
        row_reduction_ratio = (float(len(out)) / float(len(frame))) if len(frame) else 0.0
        return _accepted_profile(
            operator_id='cpv_price_volume_corr_state',
            backend=str(out.attrs.get('operator_backend') or f'{backend}_terminal'),
            elapsed_seconds=time.perf_counter() - started,
            row_count=len(out),
            result_hash=result_hash,
            extra={
                'terminal_only': True,
                'comparison_row_count': int(len(frame)),
                'row_reduction_ratio': round(row_reduction_ratio, 6),
            },
        ), out
    result_hash = _frame_hash(out, ['ts_code', 'trade_date', 'hhmmss', output_col], ['ts_code', 'trade_date', 'hhmmss'])
    return _accepted_profile(
        operator_id='cpv_price_volume_corr_state',
        backend=str(out.attrs.get('operator_backend') or backend),
        elapsed_seconds=time.perf_counter() - started,
        row_count=len(out),
        result_hash=result_hash,
        extra={'terminal_only': False},
    ), out


def _compare_rolling_corr(baseline: pd.DataFrame | None, candidate: pd.DataFrame | None, *, backend: str) -> list[dict[str, str]]:
    if baseline is None or candidate is None:
        return []
    if len(baseline) != len(candidate):
        return [{'code': 'rolling_corr_row_count_mismatch', 'backend': backend}]
    if not np.allclose(baseline['cpv_corr'].to_numpy(), candidate['cpv_corr'].to_numpy(), rtol=2e-5, atol=2e-5):
        return [{'code': 'rolling_corr_value_mismatch', 'backend': backend}]
    return []


def _compare_occupation(baseline: pd.DataFrame | None, candidate: pd.DataFrame | None, *, backend: str) -> list[dict[str, str]]:
    if baseline is None or candidate is None:
        return []
    merged = baseline.merge(candidate, on=['trade_date', 'ts_code'], suffixes=('_baseline', '_candidate'), how='outer', indicator=True)
    if not (merged['_merge'] == 'both').all():
        return [{'code': 'occupation_key_mismatch', 'backend': backend}]
    value_cols = ['bar_count', 'amount_sum', 'volume_sum', 'twap', 'vwap', 'vwap_minus_twap']
    for col in value_cols:
        if not np.allclose(merged[f'{col}_baseline'].to_numpy(), merged[f'{col}_candidate'].to_numpy(), rtol=1e-8, atol=1e-8):
            return [{'code': 'occupation_value_mismatch', 'backend': backend, 'column': col}]
    return []


def _compare_ema_state(baseline: pd.DataFrame | None, candidate: pd.DataFrame | None, *, backend: str) -> list[dict[str, str]]:
    if baseline is None or candidate is None:
        return []
    if len(baseline) != len(candidate):
        return [{'code': 'ema_state_row_count_mismatch', 'backend': backend}]
    if not np.allclose(baseline['ema_state'].to_numpy(), candidate['ema_state'].to_numpy(), rtol=1e-10, atol=1e-10):
        return [{'code': 'ema_state_value_mismatch', 'backend': backend}]
    return []


def _compare_terminal_corr(reference: pd.DataFrame | None, candidate: pd.DataFrame | None, *, backend: str) -> list[dict[str, str]]:
    if reference is None or candidate is None:
        return []
    merged = reference.merge(
        candidate,
        on=['trade_date', 'ts_code', 'terminal_order'],
        how='outer',
        suffixes=('_reference', '_candidate'),
        indicator=True,
    )
    if not (merged['_merge'] == 'both').all():
        return [{'code': 'terminal_corr_key_mismatch', 'backend': backend}]
    if not np.allclose(merged['terminal_corr_reference'].to_numpy(), merged['terminal_corr_candidate'].to_numpy(), rtol=1e-6, atol=1e-6):
        return [{'code': 'terminal_corr_value_mismatch', 'backend': backend}]
    return []


def _compare_terminal_ema_state(reference: pd.DataFrame | None, candidate: pd.DataFrame | None, *, backend: str) -> list[dict[str, str]]:
    if reference is None or candidate is None:
        return []
    merged = reference.merge(
        candidate,
        on=['trade_date', 'ts_code', 'terminal_order'],
        how='outer',
        suffixes=('_reference', '_candidate'),
        indicator=True,
    )
    if not (merged['_merge'] == 'both').all():
        return [{'code': 'terminal_ema_state_key_mismatch', 'backend': backend}]
    if not np.allclose(
        merged['terminal_ema_state_reference'].to_numpy(),
        merged['terminal_ema_state_candidate'].to_numpy(),
        rtol=1e-10,
        atol=1e-10,
    ):
        return [{'code': 'terminal_ema_state_value_mismatch', 'backend': backend}]
    return []


def _compare_cpv_terminal(reference: pd.DataFrame | None, candidate: pd.DataFrame | None, *, backend: str) -> list[dict[str, str]]:
    if reference is None or candidate is None:
        return []
    merged = reference.merge(
        candidate,
        on=['trade_date', 'ts_code', 'terminal_order'],
        how='outer',
        suffixes=('_reference', '_candidate'),
        indicator=True,
    )
    if not (merged['_merge'] == 'both').all():
        return [{'code': 'cpv_terminal_key_mismatch', 'backend': backend}]
    if not np.allclose(merged['cpv_terminal_corr_reference'].to_numpy(), merged['cpv_terminal_corr_candidate'].to_numpy(), rtol=1e-6, atol=1e-6):
        return [{'code': 'cpv_terminal_value_mismatch', 'backend': backend}]
    return []


def _terminal_summary(profiles: list[dict[str, Any]]) -> dict[str, Any] | None:
    terminal_profiles = [
        profile for profile in profiles
        if profile.get('operator_id') == 'terminal_rolling_corr_by_group' and profile.get('verdict') == 'ACCEPT'
    ]
    if not terminal_profiles:
        return None
    baseline = next((profile for profile in terminal_profiles if profile.get('backend') == 'numpy_terminal'), terminal_profiles[0])
    return {
        'full_row_count': int(baseline.get('comparison_row_count') or 0),
        'terminal_row_count': int(baseline.get('row_count') or 0),
        'row_reduction_ratio': float(baseline.get('row_reduction_ratio') or 0.0),
        'profile_count': len(terminal_profiles),
    }


def _baseline_backend_for_profile(profile: dict[str, Any]) -> str:
    operator_id = str(profile.get('operator_id'))
    if operator_id == 'cpv_price_volume_corr_state':
        return 'array_grouped_terminal' if profile.get('terminal_only') is True else 'array_grouped'
    if operator_id == 'rolling_corr_by_group':
        return 'numpy'
    if operator_id == 'intraday_occupation_location_state':
        return 'pandas'
    if operator_id == 'grouped_ema_state_by_group':
        return 'array_grouped_ema_state'
    if operator_id == 'terminal_rolling_corr_by_group':
        return 'numpy_terminal'
    if operator_id == 'terminal_ema_state_by_group':
        return 'array_grouped_ema_terminal'
    raise ValueError(f'unsupported operator id for performance gate: {operator_id}')


def _performance_key(profile: dict[str, Any]) -> tuple[str, bool | None]:
    operator_id = str(profile.get('operator_id'))
    if operator_id == 'cpv_price_volume_corr_state':
        return operator_id, bool(profile.get('terminal_only'))
    return operator_id, None


def _build_performance_gate(
    profiles: list[dict[str, Any]],
    *,
    min_speedup_for_default: float,
    benchmark_scope: str = 'synthetic_bounded',
) -> dict[str, Any]:
    baseline_by_key = {
        _performance_key(profile): profile
        for profile in profiles
        if profile['backend'] == _baseline_backend_for_profile(profile)
    }
    candidates: list[dict[str, Any]] = []
    for profile in profiles:
        operator_id = profile['operator_id']
        baseline_backend = _baseline_backend_for_profile(profile)
        if profile['backend'] == baseline_backend:
            continue
        baseline = baseline_by_key.get(_performance_key(profile))
        if baseline is None:
            candidates.append({
                'operator_id': operator_id,
                'baseline_backend': baseline_backend,
                'candidate_backend': profile['backend'],
                'baseline_seconds': None,
                'candidate_seconds': profile.get('elapsed_seconds'),
                'speedup': None,
                'performance_verdict': 'BLOCK',
                'reason': 'baseline_profile_missing',
            })
            continue
        if profile['verdict'] != 'ACCEPT':
            candidates.append({
                'operator_id': operator_id,
                'baseline_backend': baseline_backend,
                'candidate_backend': profile['backend'],
                'baseline_seconds': baseline.get('elapsed_seconds'),
                'candidate_seconds': profile.get('elapsed_seconds'),
                'speedup': None,
                'performance_verdict': 'BLOCK',
                'reason': 'candidate_profile_not_accepted',
            })
            continue
        baseline_seconds = float(baseline.get('elapsed_seconds') or 0.0)
        candidate_seconds = float(profile.get('elapsed_seconds') or 0.0)
        speedup = baseline_seconds / candidate_seconds if candidate_seconds > 0.0 else None
        performance_verdict = 'PROMOTE' if speedup is not None and speedup >= float(min_speedup_for_default) else 'HOLD'
        candidates.append({
            'operator_id': operator_id,
            'baseline_backend': baseline_backend,
            'candidate_backend': profile['backend'],
            'baseline_seconds': round(baseline_seconds, 6),
            'candidate_seconds': round(candidate_seconds, 6),
            'speedup': round(float(speedup), 6) if speedup is not None else None,
            'performance_verdict': performance_verdict,
            'reason': 'speedup_gate_met' if performance_verdict == 'PROMOTE' else 'speedup_gate_not_met',
        })

    if not candidates:
        default_verdict = 'NO_CANDIDATE'
    elif all(candidate['performance_verdict'] == 'BLOCK' for candidate in candidates):
        default_verdict = 'BLOCK'
    elif all(candidate['performance_verdict'] == 'PROMOTE' for candidate in candidates):
        default_verdict = 'PROMOTE'
    else:
        default_verdict = 'HOLD'
    return {
        'benchmark_scope': benchmark_scope,
        'production_default_allowed': False,
        'min_speedup_for_default': float(min_speedup_for_default),
        'default_replacement_verdict': default_verdict,
        'candidates': candidates,
    }


def run_profile(
    *,
    groups: int,
    rows_per_group: int,
    window: int,
    include_array_grouped: bool = False,
    include_process_sharded_array_grouped: bool = False,
    include_cpv_operator: bool = False,
    cpv_backend: str = 'array_grouped',
    cpv_terminal_only: bool = False,
    include_numba_grouped: bool,
    include_threaded_grouped: bool,
    include_terminal_rolling_corr: bool = False,
    include_ema_state: bool = False,
    include_terminal_ema_state: bool = False,
    max_workers: int | None,
    seed: int,
    input_parquet: str | None = None,
    row_limit: int | None = None,
) -> dict[str, Any]:
    frame, input_meta, benchmark_scope = _load_input_frame(
        input_parquet=input_parquet,
        row_limit=row_limit,
        groups=groups,
        rows_per_group=rows_per_group,
        seed=seed,
    )
    profiles: list[dict[str, Any]] = []
    comparison_issues: list[dict[str, str]] = []

    if include_cpv_operator:
        cpv_baseline_backend = 'array_grouped'
        cpv_baseline_profile: dict[str, Any] | None = None
        cpv_baseline: pd.DataFrame | None = None
        requested_backend = str(cpv_backend)
        if requested_backend != cpv_baseline_backend:
            cpv_baseline_profile, cpv_baseline = _profile_cpv_operator(
                frame,
                backend=cpv_baseline_backend,
                window=window,
                terminal_only=cpv_terminal_only,
                max_workers=max_workers,
            )
            profiles.append(cpv_baseline_profile)
        cpv_profile, cpv_candidate = _profile_cpv_operator(
            frame,
            backend=requested_backend,
            window=window,
            terminal_only=cpv_terminal_only,
            max_workers=max_workers,
        )
        profiles.append(cpv_profile)
        if cpv_terminal_only and cpv_baseline is not None:
            comparison_issues.extend(_compare_cpv_terminal(cpv_baseline, cpv_candidate, backend=str(cpv_profile.get('backend'))))

    rolling_baseline_profile, rolling_baseline = _profile_rolling_corr(frame, backend='numpy', window=window)
    occupation_baseline_profile, occupation_baseline = _profile_occupation(frame, backend='pandas')
    profiles.extend([rolling_baseline_profile, occupation_baseline_profile])

    ema_baseline: pd.DataFrame | None = None
    if include_ema_state or include_terminal_ema_state:
        ema_baseline_profile, ema_baseline = _profile_ema_state(frame, backend='array_grouped')
        if include_ema_state:
            profiles.append(ema_baseline_profile)

    if include_array_grouped:
        rolling_array_profile, rolling_array = _profile_rolling_corr(frame, backend='array_grouped', window=window)
        occupation_array_profile, occupation_array = _profile_occupation(frame, backend='array_grouped')
        profiles.append(rolling_array_profile)
        profiles.append(occupation_array_profile)
        comparison_issues.extend(_compare_rolling_corr(rolling_baseline, rolling_array, backend='array_grouped'))
        comparison_issues.extend(_compare_occupation(occupation_baseline, occupation_array, backend='array_grouped_occupation'))

    if include_process_sharded_array_grouped:
        rolling_process_profile, rolling_process = _profile_rolling_corr(
            frame,
            backend='process_sharded_array_grouped',
            window=window,
            max_workers=max_workers,
        )
        occupation_process_profile, occupation_process = _profile_occupation(
            frame,
            backend='process_sharded_array_grouped',
            max_workers=max_workers,
        )
        profiles.append(rolling_process_profile)
        profiles.append(occupation_process_profile)
        comparison_issues.extend(_compare_rolling_corr(rolling_baseline, rolling_process, backend='process_sharded_array_grouped'))
        comparison_issues.extend(_compare_occupation(occupation_baseline, occupation_process, backend='process_sharded_array_grouped_occupation'))
        if include_ema_state:
            ema_process_profile, ema_process = _profile_ema_state(
                frame,
                backend='process_sharded_array_grouped',
                max_workers=max_workers,
            )
            profiles.append(ema_process_profile)
            comparison_issues.extend(_compare_ema_state(ema_baseline, ema_process, backend='process_sharded_array_grouped_ema_state'))

    if include_terminal_rolling_corr:
        terminal_reference = _terminal_reference_from_full(rolling_baseline, output_col='cpv_corr') if rolling_baseline is not None else None
        terminal_baseline_profile, terminal_baseline = _profile_terminal_rolling_corr(
            frame,
            backend='numpy',
            window=window,
            full_row_count=len(rolling_baseline) if rolling_baseline is not None else 0,
        )
        profiles.append(terminal_baseline_profile)
        comparison_issues.extend(_compare_terminal_corr(terminal_reference, terminal_baseline, backend='numpy_terminal'))
        terminal_array_profile, terminal_array = _profile_terminal_rolling_corr(
            frame,
            backend='array_grouped',
            window=window,
            full_row_count=len(rolling_baseline) if rolling_baseline is not None else 0,
        )
        profiles.append(terminal_array_profile)
        comparison_issues.extend(_compare_terminal_corr(terminal_reference, terminal_array, backend='array_grouped_terminal'))
        if include_process_sharded_array_grouped:
            terminal_process_profile, terminal_process = _profile_terminal_rolling_corr(
                frame,
                backend='process_sharded_array_grouped',
                window=window,
                full_row_count=len(rolling_baseline) if rolling_baseline is not None else 0,
                max_workers=max_workers,
            )
            profiles.append(terminal_process_profile)
            comparison_issues.extend(_compare_terminal_corr(terminal_reference, terminal_process, backend='process_sharded_array_grouped_terminal'))
        if include_threaded_grouped:
            terminal_threaded_profile, terminal_threaded = _profile_terminal_rolling_corr(
                frame,
                backend='threaded_grouped',
                window=window,
                full_row_count=len(rolling_baseline) if rolling_baseline is not None else 0,
                max_workers=max_workers,
            )
            profiles.append(terminal_threaded_profile)
            comparison_issues.extend(_compare_terminal_corr(terminal_reference, terminal_threaded, backend='threaded_grouped_terminal'))
        if include_numba_grouped:
            terminal_numba_profile, terminal_numba = _profile_terminal_rolling_corr(
                frame,
                backend='numba_grouped',
                window=window,
                full_row_count=len(rolling_baseline) if rolling_baseline is not None else 0,
            )
            profiles.append(terminal_numba_profile)
            comparison_issues.extend(_compare_terminal_corr(terminal_reference, terminal_numba, backend='numba_grouped_terminal'))

    if include_terminal_ema_state:
        terminal_ema_reference = _terminal_ema_reference_from_full(ema_baseline, output_col='ema_state') if ema_baseline is not None else None
        terminal_ema_array_profile, terminal_ema_array = _profile_terminal_ema_state(
            frame,
            backend='array_grouped',
            full_row_count=len(ema_baseline) if ema_baseline is not None else 0,
        )
        profiles.append(terminal_ema_array_profile)
        comparison_issues.extend(_compare_terminal_ema_state(terminal_ema_reference, terminal_ema_array, backend='array_grouped_ema_terminal'))
        if include_process_sharded_array_grouped:
            terminal_ema_process_profile, terminal_ema_process = _profile_terminal_ema_state(
                frame,
                backend='process_sharded_array_grouped',
                full_row_count=len(ema_baseline) if ema_baseline is not None else 0,
                max_workers=max_workers,
            )
            profiles.append(terminal_ema_process_profile)
            comparison_issues.extend(_compare_terminal_ema_state(terminal_ema_reference, terminal_ema_process, backend='process_sharded_array_grouped_ema_terminal'))
        if include_numba_grouped:
            terminal_ema_numba_profile, terminal_ema_numba = _profile_terminal_ema_state(
                frame,
                backend='numba_grouped',
                full_row_count=len(ema_baseline) if ema_baseline is not None else 0,
            )
            profiles.append(terminal_ema_numba_profile)
            comparison_issues.extend(_compare_terminal_ema_state(terminal_ema_reference, terminal_ema_numba, backend='numba_grouped_ema_terminal'))

    if include_threaded_grouped:
        rolling_threaded_profile, rolling_threaded = _profile_rolling_corr(
            frame,
            backend='threaded_grouped',
            window=window,
            max_workers=max_workers,
        )
        occupation_threaded_profile, occupation_threaded = _profile_occupation(
            frame,
            backend='threaded_grouped',
            max_workers=max_workers,
        )
        profiles.extend([rolling_threaded_profile, occupation_threaded_profile])
        comparison_issues.extend(_compare_rolling_corr(rolling_baseline, rolling_threaded, backend='threaded_grouped'))
        comparison_issues.extend(_compare_occupation(occupation_baseline, occupation_threaded, backend='threaded_grouped'))

    if include_numba_grouped:
        rolling_candidate_profile, rolling_candidate = _profile_rolling_corr(frame, backend='numba_grouped', window=window)
        occupation_candidate_profile, occupation_candidate = _profile_occupation(frame, backend='numba_grouped')
        profiles.extend([rolling_candidate_profile, occupation_candidate_profile])
        comparison_issues.extend(_compare_rolling_corr(rolling_baseline, rolling_candidate, backend='numba_grouped'))
        comparison_issues.extend(_compare_occupation(occupation_baseline, occupation_candidate, backend='numba_grouped'))
        if include_ema_state:
            ema_candidate_profile, ema_candidate = _profile_ema_state(frame, backend='numba_grouped')
            profiles.append(ema_candidate_profile)
            comparison_issues.extend(_compare_ema_state(ema_baseline, ema_candidate, backend='numba_grouped_ema_state'))

    verdict = 'ACCEPT'
    if any(profile['verdict'] != 'ACCEPT' for profile in profiles) or comparison_issues:
        verdict = 'BLOCK'
    performance_gate = _build_performance_gate(profiles, min_speedup_for_default=1.2, benchmark_scope=benchmark_scope)
    input_payload = {
        **input_meta,
        'window': int(window),
        'seed': int(seed),
        'max_workers': int(max_workers or 1),
    }
    return {
        'verdict': verdict,
        'profile_count': len(profiles),
        'input': input_payload,
        'profiles': profiles,
        'comparison_issues': comparison_issues,
        'performance_gate': performance_gate,
        'terminal_rolling_corr_summary': _terminal_summary(profiles),
        'safety': {
            'uses_real_market_data': bool(input_parquet),
            'starts_backfill': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Profile bounded generic intraday operator kernels on synthetic data.')
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--groups', type=int, default=64)
    parser.add_argument('--rows-per-group', type=int, default=240)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--seed', type=int, default=20260616)
    parser.add_argument('--input-parquet')
    parser.add_argument('--row-limit', type=int)
    parser.add_argument('--include-array-grouped', action='store_true')
    parser.add_argument('--include-process-sharded-array-grouped', action='store_true')
    parser.add_argument('--include-numba-grouped', action='store_true')
    parser.add_argument('--include-threaded-grouped', action='store_true')
    parser.add_argument('--include-terminal-rolling-corr', action='store_true')
    parser.add_argument('--include-ema-state', action='store_true')
    parser.add_argument('--include-terminal-ema-state', action='store_true')
    parser.add_argument('--include-cpv-operator', action='store_true')
    parser.add_argument('--cpv-backend', default='array_grouped')
    parser.add_argument('--cpv-terminal-only', action='store_true')
    parser.add_argument('--max-workers', type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    proof = run_profile(
        groups=args.groups,
        rows_per_group=args.rows_per_group,
        window=args.window,
        include_array_grouped=bool(args.include_array_grouped),
        include_process_sharded_array_grouped=bool(args.include_process_sharded_array_grouped),
        include_cpv_operator=bool(args.include_cpv_operator),
        cpv_backend=str(args.cpv_backend),
        cpv_terminal_only=bool(args.cpv_terminal_only),
        include_numba_grouped=bool(args.include_numba_grouped),
        include_threaded_grouped=bool(args.include_threaded_grouped),
        include_terminal_rolling_corr=bool(args.include_terminal_rolling_corr),
        include_ema_state=bool(args.include_ema_state),
        include_terminal_ema_state=bool(args.include_terminal_ema_state),
        max_workers=args.max_workers,
        seed=args.seed,
        input_parquet=args.input_parquet,
        row_limit=args.row_limit,
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    return 0 if proof['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
