from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from typing import Any

import numpy as np
import pandas as pd

from .operators import (
    cs_regression,
    cs_rank,
    cs_scale,
    rolling_corr,
    rolling_cov,
    signed_power,
    ts_argmax,
    ts_argmin,
    ts_delay,
    ts_delta,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_rank_reference,
    ts_std,
    ts_sum,
)
from .kernels import apply_kernel_operator, default_kernel_profile, resolve_formula_kernel_engine
from .profiling import OperatorProfiler


def _window(value) -> int:
    if isinstance(value, pd.Series):
        value = value.dropna().iloc[0]
    return int(value)


@contextmanager
def _null_phase():
    yield {}


def _validate_formula_ir_inputs(formula_ir: dict, frame: pd.DataFrame) -> None:
    if formula_ir.get('parse_status') != 'success':
        raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_SYNTAX: {formula_ir.get("parse_errors")}')
    required = {'ts_code', 'trade_date'}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f'BLOCK_MISSING_REFERENCE_KEYS: {sorted(missing)}')


def _adv_window(field: str) -> int | None:
    match = re.fullmatch(r'adv([1-9][0-9]*)', str(field or '').strip().lower())
    if not match:
        return None
    return int(match.group(1))


def _with_derived_formula_fields(formula_ir: dict, frame: pd.DataFrame) -> pd.DataFrame:
    required_fields = [str(field).strip().lower() for field in formula_ir.get('required_fields') or []]
    adv_fields = [(field, _adv_window(field)) for field in required_fields]
    adv_fields = [(field, window) for field, window in adv_fields if window is not None]
    needs_vwap = 'vwap' in required_fields and 'vwap' not in frame.columns
    if not adv_fields and not needs_vwap:
        return frame
    missing_adv = [field for field, _window_value in adv_fields if field not in frame.columns]
    if not missing_adv and not needs_vwap:
        return frame
    volume_col = 'volume' if 'volume' in frame.columns else 'vol' if 'vol' in frame.columns else None
    if missing_adv and volume_col is None:
        raise KeyError(f'BLOCK_MISSING_FIELD_ALIAS: adv derived fields require volume/vol source: {missing_adv}')
    working = frame.copy()
    volume = pd.to_numeric(working[volume_col], errors='coerce') if volume_col else None
    if needs_vwap:
        if volume_col is None or 'amount' not in working.columns:
            raise KeyError('BLOCK_MISSING_FIELD_ALIAS: vwap derived field requires amount and volume/vol source')
        amount = pd.to_numeric(working['amount'], errors='coerce')
        working['vwap'] = amount / volume.replace(0, np.nan)
    grouped_volume = volume.groupby(working['ts_code'], sort=False) if volume is not None else None
    for field, window in adv_fields:
        if field in working.columns:
            continue
        if grouped_volume is None:
            raise KeyError(f'BLOCK_MISSING_FIELD_ALIAS: adv derived fields require volume/vol source: {missing_adv}')
        working[field] = grouped_volume.transform(lambda s, window=window: s.rolling(window, min_periods=window).mean())
    return working


def _is_key_sorted(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return True
    keys = frame[['ts_code', 'trade_date']]
    sorted_keys = keys.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    return bool(keys.reset_index(drop=True).equals(sorted_keys))


def _prepare_reference_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True).copy()


def _prepare_optimized_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    input_presorted = _is_key_sorted(frame)
    if input_presorted:
        working = frame if isinstance(frame.index, pd.RangeIndex) and not frame.index.has_duplicates else frame.reset_index(drop=True)
    else:
        working = frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    return working, input_presorted


def _node_key(node: dict) -> str:
    blob = json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def _profile_operator_name(node: dict) -> str:
    typ = node.get('type')
    if typ == 'field':
        return 'column'
    if typ == 'constant':
        return 'literal'
    if typ != 'operator':
        return 'unknown'
    op = str(node.get('operator') or 'unknown')
    return {
        'multiply': 'mul',
        'divide': 'div',
        'negate': 'neg',
    }.get(op, op)


def _eval(node: dict, frame: pd.DataFrame):
    typ = node.get('type')
    if typ == 'field':
        return pd.to_numeric(frame[node['resolved_field']], errors='coerce')
    if typ == 'constant':
        return node['value']
    if typ != 'operator':
        raise ValueError(f'BLOCK_UNSUPPORTED_IR_NODE: {typ}')
    op = node['operator']
    args = [_eval(arg, frame) for arg in node.get('args') or []]
    if op == 'rank':
        return cs_rank(args[0], frame)
    if op == 'ts_rank':
        return ts_rank_reference(args[0], _window(args[1]), frame)
    if op in {'sum'}:
        return ts_sum(args[0], _window(args[1]), frame)
    if op == 'mean':
        return ts_mean(args[0], _window(args[1]), frame)
    if op in {'std', 'stddev'}:
        return ts_std(args[0], _window(args[1]), frame)
    if op == 'delta':
        return ts_delta(args[0], _window(args[1]), frame)
    if op == 'delay':
        return ts_delay(args[0], _window(args[1]), frame)
    if op in {'correlation', 'corr'}:
        return rolling_corr(args[0], args[1], _window(args[2]), frame)
    if op == 'covariance':
        return rolling_cov(args[0], args[1], _window(args[2]), frame)
    if op == 'min':
        return ts_min(args[0], _window(args[1]), frame)
    if op == 'max':
        return ts_max(args[0], _window(args[1]), frame)
    if op == 'argmin':
        return ts_argmin(args[0], _window(args[1]), frame)
    if op == 'argmax':
        return ts_argmax(args[0], _window(args[1]), frame)
    if op == 'scale':
        return cs_scale(args[0], frame)
    if op == 'cs_regression':
        return cs_regression(args[0], args[1], _window(args[2]), frame)
    if op == 'plus':
        return args[0] + args[1]
    if op == 'minus':
        return args[0] - args[1]
    if op == 'multiply':
        return args[0] * args[1]
    if op == 'divide':
        return args[0] / args[1]
    if op == 'negate':
        return -args[0]
    if op == 'abs':
        return args[0].abs()
    if op == 'log':
        return np.log(args[0])
    if op == 'sign':
        return np.sign(args[0])
    if op == 'signedpower':
        return signed_power(args[0], args[1])
    raise ValueError(f'BLOCK_UNSUPPORTED_OPERATOR_EVAL: {op}')


def _eval_cached(
    node: dict,
    frame: pd.DataFrame,
    cache: dict[str, Any],
    stats: dict[str, Any],
    profiler: OperatorProfiler | None = None,
    ts_rank_engine_config: dict | None = None,
    formula_kernel_config: dict | None = None,
):
    typ = node.get('type')
    if typ == 'constant':
        key = _node_key(node)
        if key in cache:
            stats['cache_hits'] += 1
            result = cache[key]
            if profiler is not None:
                profiler.cache_hit(node_id=key[:16], operator='literal', value=result, input_rows=len(frame), detail={'node_type': typ})
            return result
        stats['cache_misses'] += 1
        with (profiler.phase(node_id=key[:16], operator='literal', input_rows=len(frame), detail={'node_type': typ}) if profiler is not None else _null_phase()) as event:
            result = node['value']
            if profiler is not None:
                profiler.set_output(event, result, output_name='literal')
        cache[key] = result
        return result
    if typ not in {'field', 'operator'}:
        raise ValueError(f'BLOCK_UNSUPPORTED_IR_NODE: {typ}')

    key = _node_key(node)
    if key in cache:
        stats['cache_hits'] += 1
        result = cache[key]
        if profiler is not None:
            profiler.cache_hit(
                node_id=key[:16],
                operator=_profile_operator_name(node),
                value=result,
                input_rows=len(frame),
                detail={'node_type': typ, 'operator': node.get('operator')},
            )
        return result
    stats['cache_misses'] += 1

    if typ == 'field':
        with (profiler.phase(
            node_id=key[:16],
            operator='column',
            input_rows=len(frame),
            detail={'node_type': typ, 'field': node.get('resolved_field')},
        ) if profiler is not None else _null_phase()) as event:
            result = pd.to_numeric(frame[node['resolved_field']], errors='coerce')
            if profiler is not None:
                profiler.set_output(event, result, output_name=str(node.get('resolved_field') or 'column'))
        cache[key] = result
        return result

    op = node['operator']
    args = [
        _eval_cached(
            arg,
            frame,
            cache,
            stats,
            profiler=profiler,
            ts_rank_engine_config=ts_rank_engine_config,
            formula_kernel_config=formula_kernel_config,
        )
        for arg in node.get('args') or []
    ]
    with (profiler.phase(
        node_id=key[:16],
        operator=_profile_operator_name(node),
        input_rows=len(frame),
        detail={'node_type': typ, 'operator': op},
    ) if profiler is not None else _null_phase()) as event:
        if op == 'rank':
            result = cs_rank(args[0], frame)
        elif op == 'ts_rank':
            if (ts_rank_engine_config or {}).get('experimental_enabled'):
                result = ts_rank(args[0], _window(args[1]), frame, stats=stats, engine_config=ts_rank_engine_config)
            elif formula_kernel_config:
                result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
            else:
                result = ts_rank(args[0], _window(args[1]), frame, stats=stats, engine_config=ts_rank_engine_config)
        elif op in {'sum'}:
            result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
        elif op == 'mean':
            result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
        elif op in {'std', 'stddev'}:
            result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
        elif op == 'delta':
            result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
        elif op == 'delay':
            result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
        elif op in {'correlation', 'corr'}:
            result = apply_kernel_operator(op, args, _window(args[2]), frame, stats=stats, config=formula_kernel_config)
        elif op == 'covariance':
            result = apply_kernel_operator(op, args, _window(args[2]), frame, stats=stats, config=formula_kernel_config)
        elif op == 'min':
            result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
        elif op == 'max':
            result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
        elif op == 'argmin':
            if formula_kernel_config:
                result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
            else:
                result = ts_argmin(args[0], _window(args[1]), frame)
        elif op == 'argmax':
            if formula_kernel_config:
                result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
            else:
                result = ts_argmax(args[0], _window(args[1]), frame)
        elif op == 'scale':
            result = cs_scale(args[0], frame)
        elif op == 'cs_regression':
            result = cs_regression(args[0], args[1], _window(args[2]), frame)
        elif op == 'plus':
            result = args[0] + args[1]
        elif op == 'minus':
            result = args[0] - args[1]
        elif op == 'multiply':
            result = args[0] * args[1]
        elif op == 'divide':
            result = args[0] / args[1]
        elif op == 'negate':
            result = -args[0]
        elif op == 'abs':
            result = args[0].abs()
        elif op == 'log':
            result = np.log(args[0])
        elif op == 'sign':
            result = np.sign(args[0])
        elif op == 'signedpower':
            result = signed_power(args[0], args[1])
        else:
            raise ValueError(f'BLOCK_UNSUPPORTED_OPERATOR_EVAL: {op}')
        if profiler is not None:
            profiler.set_output(event, result, output_name=_profile_operator_name(node))
    cache[key] = result
    return result


def evaluate_formula_ir_reference(formula_ir: dict, frame: pd.DataFrame) -> pd.Series:
    _validate_formula_ir_inputs(formula_ir, frame)
    working = _prepare_reference_frame(_with_derived_formula_fields(formula_ir, frame))
    return _eval(formula_ir['root'], working)


def evaluate_formula_ir_optimized(
    formula_ir: dict,
    frame: pd.DataFrame,
    return_profile: bool = False,
    operator_profile_enabled: bool = False,
    ts_rank_engine_config: dict | None = None,
    formula_kernel_config: dict | None = None,
):
    _validate_formula_ir_inputs(formula_ir, frame)
    working, input_presorted = _prepare_optimized_frame(_with_derived_formula_fields(formula_ir, frame))
    resolved_formula_kernel_config = formula_kernel_config or resolve_formula_kernel_engine()
    cache: dict[str, Any] = {}
    stats: dict[str, Any] = {
        'engine': 'pandas_formula_ir_optimized',
        'reference_engine': 'pandas_formula_ir_reference',
        'memoization_enabled': True,
        'cache_hits': 0,
        'cache_misses': 0,
        'input_presorted': bool(input_presorted),
        'output_presorted': True,
        'ts_rank_engine': None,
        'ts_rank_fast_path_enabled': False,
        'ts_rank_fast_path_count': 0,
        'ts_rank_fallback_count': 0,
        'ts_rank_fallback_reasons': [],
        'kernel_profile': default_kernel_profile(resolved_formula_kernel_config),
    }
    profiler = OperatorProfiler(enabled=operator_profile_enabled, engine='pandas_formula_ir_optimized')
    result = _eval_cached(
        formula_ir['root'],
        working,
        cache,
        stats,
        profiler=profiler,
        ts_rank_engine_config=ts_rank_engine_config,
        formula_kernel_config=resolved_formula_kernel_config,
    )
    stats['operator_profile'] = profiler.summary()
    if return_profile:
        return result, stats
    return result


def evaluate_formula_ir(formula_ir: dict, frame: pd.DataFrame, engine: str = 'optimized'):
    if engine == 'reference':
        return evaluate_formula_ir_reference(formula_ir, frame)
    if engine == 'optimized':
        return evaluate_formula_ir_optimized(formula_ir, frame)
    raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_ENGINE: {engine}')


def evaluate_formula_frame(
    formula_ir: dict,
    frame: pd.DataFrame,
    engine: str = 'optimized',
    return_profile: bool = False,
    operator_profile_enabled: bool = False,
    ts_rank_engine_config: dict | None = None,
    formula_kernel_config: dict | None = None,
):
    if engine == 'reference':
        _validate_formula_ir_inputs(formula_ir, frame)
        working = _prepare_reference_frame(_with_derived_formula_fields(formula_ir, frame))
        values = _eval(formula_ir['root'], working)
        profile: dict[str, Any] = {
            'engine': 'pandas_formula_ir_reference',
            'reference_engine': 'pandas_formula_ir_reference',
            'memoization_enabled': False,
            'cache_hits': None,
            'cache_misses': None,
            'input_presorted': _is_key_sorted(frame),
            'output_presorted': True,
            'operator_profile': OperatorProfiler(enabled=False, engine='pandas_formula_ir_reference').summary(),
            'kernel_profile': default_kernel_profile({'selected_engine': 'pandas_reference', 'experimental_enabled': False, 'selection_source': 'reference'}),
        }
    elif engine == 'optimized':
        _validate_formula_ir_inputs(formula_ir, frame)
        working, input_presorted = _prepare_optimized_frame(_with_derived_formula_fields(formula_ir, frame))
        values, profile = evaluate_formula_ir_optimized(
            formula_ir,
            working,
            return_profile=True,
            operator_profile_enabled=operator_profile_enabled,
            ts_rank_engine_config=ts_rank_engine_config,
            formula_kernel_config=formula_kernel_config,
        )
        profile['input_presorted'] = bool(input_presorted)
        profile['output_presorted'] = True
    elif engine == 'polars_experimental':
        from .polars_evaluator import evaluate_formula_frame_polars_experimental

        return evaluate_formula_frame_polars_experimental(formula_ir, frame, return_profile=return_profile)
    else:
        raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_ENGINE: {engine}')
    out = working[['ts_code', 'trade_date']].copy()
    out['factor_value'] = values
    if return_profile:
        return out, profile
    return out
