from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from .evaluator import _is_key_sorted, _prepare_optimized_frame, _validate_formula_ir_inputs, evaluate_formula_frame
POLARS_ENGINE = 'polars_experimental'
SUPPORTED_POLARS_OPERATORS = {'rank', 'delta', 'multiply', 'divide', 'plus', 'minus', 'negate'}


def polars_dependency_available() -> bool:
    try:
        import polars  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def _collect_operators(node: dict[str, Any], out: set[str]) -> None:
    if not isinstance(node, dict):
        return
    if node.get('type') == 'operator':
        out.add(str(node.get('operator')))
    for arg in node.get('args') or []:
        _collect_operators(arg, out)


def formula_operator_set(formula_ir: dict[str, Any]) -> set[str]:
    operators: set[str] = set()
    _collect_operators(formula_ir.get('root') or {}, operators)
    return operators


def first_unsupported_operator(formula_ir: dict[str, Any]) -> str | None:
    for op in sorted(formula_operator_set(formula_ir)):
        if op not in SUPPORTED_POLARS_OPERATORS:
            return op
    return None


def _constant_value(value: Any) -> float:
    if isinstance(value, pd.Series):
        value = value.dropna().iloc[0]
    return float(value)


def _nullify_nan(expr: Any) -> Any:
    return expr.fill_nan(None)


def _eval_expr(node: dict[str, Any], pl: Any):
    typ = node.get('type')
    if typ == 'field':
        return _nullify_nan(pl.col(node['resolved_field']).cast(pl.Float64, strict=False))
    if typ == 'constant':
        return _nullify_nan(pl.lit(_constant_value(node.get('value'))))
    if typ != 'operator':
        raise ValueError(f'BLOCK_POLARS_EXPERIMENTAL_UNSUPPORTED_NODE:{typ}')
    op = node.get('operator')
    args = [_eval_expr(arg, pl) for arg in node.get('args') or []]
    if op == 'rank':
        value = _nullify_nan(args[0])
        non_missing_count = value.is_not_null().sum().over('trade_date')
        ranked = value.rank(method='average').over('trade_date')
        return pl.when(value.is_null()).then(None).otherwise(ranked / non_missing_count)
    if op == 'delta':
        window = int(_constant_value(node.get('args', [None, {'value': 1}])[1].get('value')))
        value = _nullify_nan(args[0])
        return _nullify_nan(value - value.shift(window).over('ts_code'))
    if op == 'multiply':
        return _nullify_nan(args[0] * args[1])
    if op == 'divide':
        return _nullify_nan(args[0] / args[1])
    if op == 'plus':
        return _nullify_nan(args[0] + args[1])
    if op == 'minus':
        return _nullify_nan(args[0] - args[1])
    if op == 'negate':
        return _nullify_nan(-args[0])
    raise ValueError(f'BLOCK_POLARS_EXPERIMENTAL_UNSUPPORTED_OPERATOR:{op}')


def _node_key(node: dict[str, Any]) -> str:
    blob = json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


def _literal_column(value: Any, pl_frame: Any, pl: Any, name: str):
    return pl_frame.with_columns(_nullify_nan(pl.lit(_constant_value(value))).alias(name))


def _eval_column(node: dict[str, Any], pl_frame: Any, pl: Any, cache: dict[str, str]) -> tuple[Any, str]:
    key = _node_key(node)
    if key in cache:
        return pl_frame, cache[key]
    name = f'__ff_polars_{len(cache)}_{key}'
    typ = node.get('type')
    if typ == 'field':
        pl_frame = pl_frame.with_columns(_nullify_nan(pl.col(node['resolved_field']).cast(pl.Float64, strict=False)).alias(name))
        cache[key] = name
        return pl_frame, name
    if typ == 'constant':
        pl_frame = _literal_column(node.get('value'), pl_frame, pl, name)
        cache[key] = name
        return pl_frame, name
    if typ != 'operator':
        raise ValueError(f'BLOCK_POLARS_EXPERIMENTAL_UNSUPPORTED_NODE:{typ}')

    op = node.get('operator')
    arg_cols: list[str] = []
    for arg in node.get('args') or []:
        pl_frame, arg_col = _eval_column(arg, pl_frame, pl, cache)
        arg_cols.append(arg_col)

    if op == 'rank':
        value = pl.col(arg_cols[0])
        non_missing_count = value.is_not_null().sum().over('trade_date')
        ranked = value.rank(method='average').over('trade_date')
        expr = pl.when(value.is_null()).then(None).otherwise(ranked / non_missing_count)
    elif op == 'delta':
        window = int(_constant_value(node.get('args', [None, {'value': 1}])[1].get('value')))
        value = pl.col(arg_cols[0])
        expr = _nullify_nan(value - value.shift(window).over('ts_code'))
    elif op == 'multiply':
        expr = _nullify_nan(pl.col(arg_cols[0]) * pl.col(arg_cols[1]))
    elif op == 'divide':
        expr = _nullify_nan(pl.col(arg_cols[0]) / pl.col(arg_cols[1]))
    elif op == 'plus':
        expr = _nullify_nan(pl.col(arg_cols[0]) + pl.col(arg_cols[1]))
    elif op == 'minus':
        expr = _nullify_nan(pl.col(arg_cols[0]) - pl.col(arg_cols[1]))
    elif op == 'negate':
        expr = _nullify_nan(-pl.col(arg_cols[0]))
    else:
        raise ValueError(f'BLOCK_POLARS_EXPERIMENTAL_UNSUPPORTED_OPERATOR:{op}')
    pl_frame = pl_frame.with_columns(expr.alias(name))
    cache[key] = name
    return pl_frame, name


def _rank_corr(reference: pd.DataFrame, optimized: pd.DataFrame) -> float | None:
    merged = reference[['ts_code', 'trade_date', 'factor_value']].merge(
        optimized[['ts_code', 'trade_date', 'factor_value']],
        on=['ts_code', 'trade_date'],
        how='inner',
        suffixes=('_reference', '_optimized'),
    )
    ref = pd.to_numeric(merged['factor_value_reference'], errors='coerce')
    opt = pd.to_numeric(merged['factor_value_optimized'], errors='coerce')
    valid = ref.notna() & opt.notna()
    if int(valid.sum()) < 2:
        return None
    corr = ref[valid].rank(method='average').corr(opt[valid].rank(method='average'), method='pearson')
    return float(corr) if pd.notna(corr) else None


def _json_safe_float(value: Any) -> float | None | str:
    if pd.isna(value):
        return None
    value = float(value)
    if np.isposinf(value):
        return 'inf'
    if np.isneginf(value):
        return '-inf'
    return value


def _parity_fields(reference: pd.DataFrame, candidate: pd.DataFrame, tolerance: float) -> dict[str, Any]:
    ref_sorted = reference.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    cand_sorted = candidate.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    ref_values = pd.to_numeric(ref_sorted['factor_value'], errors='coerce')
    cand_values = pd.to_numeric(cand_sorted['factor_value'], errors='coerce')
    ref_mask = ref_values.notna()
    cand_mask = cand_values.notna()
    ref_nan_mask = ref_values.isna().reset_index(drop=True)
    cand_nan_mask = cand_values.isna().reset_index(drop=True)
    nan_mask_mismatch = ref_nan_mask != cand_nan_mask
    if bool(ref_mask.equals(cand_mask)):
        diffs = (ref_values[ref_mask] - cand_values[cand_mask]).abs()
        max_abs_diff = float(diffs.max()) if len(diffs) else 0.0
    else:
        max_abs_diff = float('inf')
    mismatch_samples = []
    for idx in list(np.flatnonzero(nan_mask_mismatch.to_numpy()))[:5]:
        mismatch_samples.append({
            'ts_code': str(ref_sorted.loc[idx, 'ts_code']),
            'trade_date': str(ref_sorted.loc[idx, 'trade_date']),
            'reference_value': _json_safe_float(ref_values.iloc[idx]),
            'candidate_value': _json_safe_float(cand_values.iloc[idx]),
        })
    return {
        'parity_checked': True,
        'parity_sample_rows': int(len(reference)),
        'max_abs_diff': max_abs_diff,
        'rank_corr': _rank_corr(reference, candidate),
        'row_count_equal': int(len(reference)) == int(len(candidate)),
        'key_order_equal': bool(
            reference[['ts_code', 'trade_date']].reset_index(drop=True).equals(
                candidate[['ts_code', 'trade_date']].reset_index(drop=True)
            )
        ),
        'nan_mask_equal': bool(ref_nan_mask.equals(cand_nan_mask)),
        'nan_mask_mismatch_count': int(nan_mask_mismatch.sum()),
        'reference_nan_count': int(ref_nan_mask.sum()),
        'candidate_nan_count': int(cand_nan_mask.sum()),
        'mismatch_samples': mismatch_samples,
    }


def assert_polars_result_parity(reference: pd.DataFrame, candidate: pd.DataFrame, tolerance: float = 1e-12) -> dict[str, Any]:
    parity_fields = _parity_fields(reference, candidate, tolerance)
    rank_corr = parity_fields.get('rank_corr')
    max_abs_diff = parity_fields.get('max_abs_diff')
    max_abs_diff_value = float(max_abs_diff) if max_abs_diff is not None else float('inf')
    if (
        not parity_fields.get('row_count_equal')
        or not parity_fields.get('key_order_equal')
        or not parity_fields.get('nan_mask_equal')
        or max_abs_diff_value > tolerance
        or (rank_corr is not None and float(rank_corr) < 0.999999)
    ):
        raise AssertionError(
            'BLOCK_POLARS_EXPERIMENTAL_PARITY_FAILED: '
            f"max_abs_diff={parity_fields.get('max_abs_diff')} "
            f"rank_corr={rank_corr} "
            f"row_count_equal={parity_fields.get('row_count_equal')} "
            f"key_order_equal={parity_fields.get('key_order_equal')} "
            f"nan_mask_equal={parity_fields.get('nan_mask_equal')} "
            f"nan_mask_mismatch_count={parity_fields.get('nan_mask_mismatch_count')} "
            f"reference_nan_count={parity_fields.get('reference_nan_count')} "
            f"candidate_nan_count={parity_fields.get('candidate_nan_count')} "
            f"mismatch_samples={parity_fields.get('mismatch_samples')}"
        )
    return parity_fields


def _fallback_profile(reason: str, frame: pd.DataFrame, fallback_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        **fallback_profile,
        'polars_enabled': True,
        'polars_used': False,
        'polars_fallback_used': True,
        'polars_fallback_reason': reason,
        'row_count_equal': None,
        'key_order_equal': None,
        'nan_mask_equal': None,
    }


def evaluate_formula_frame_polars_experimental(
    formula_ir: dict[str, Any],
    frame: pd.DataFrame,
    *,
    return_profile: bool = False,
    tolerance: float = 1e-12,
):
    _validate_formula_ir_inputs(formula_ir, frame)
    if not polars_dependency_available():
        raise ModuleNotFoundError('BLOCK_POLARS_EXPERIMENTAL_DEPENDENCY_MISSING')

    unsupported = first_unsupported_operator(formula_ir)
    if unsupported is not None:
        fallback_frame, fallback_profile = evaluate_formula_frame(formula_ir, frame, engine='optimized', return_profile=True)
        reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
        parity_fields = assert_polars_result_parity(reference, fallback_frame, tolerance)
        profile = _fallback_profile(f'unsupported_operator:{unsupported}', frame, fallback_profile)
        profile.update(parity_fields)
        if return_profile:
            return fallback_frame, profile
        return fallback_frame

    import polars as pl

    working, input_presorted = _prepare_optimized_frame(frame)
    pl_frame = pl.from_pandas(working)
    pl_frame, factor_col = _eval_column(formula_ir['root'], pl_frame, pl, {})
    result = (
        pl_frame
        .select([
            pl.col('ts_code'),
            pl.col('trade_date'),
            pl.col(factor_col).alias('factor_value'),
        ])
        .with_columns(pl.col('factor_value').fill_nan(None))
        .sort(['ts_code', 'trade_date'])
        .to_pandas()
    )
    result['factor_value'] = pd.to_numeric(result['factor_value'], errors='coerce')
    reference = evaluate_formula_frame(formula_ir, working, engine='reference')
    parity_fields = assert_polars_result_parity(reference, result, tolerance)
    profile = {
        'engine': POLARS_ENGINE,
        'reference_engine': 'pandas_formula_ir_reference',
        'memoization_enabled': False,
        'cache_hits': None,
        'cache_misses': None,
        'input_presorted': bool(input_presorted),
        'output_presorted': True,
        'ts_rank_engine': None,
        'ts_rank_fast_path_enabled': False,
        'ts_rank_fast_path_count': 0,
        'ts_rank_fallback_count': 0,
        'ts_rank_fallback_reasons': [],
        'polars_enabled': True,
        'polars_used': True,
        'polars_fallback_used': False,
        'polars_fallback_reason': None,
        **parity_fields,
    }
    if return_profile:
        return result, profile
    return result
