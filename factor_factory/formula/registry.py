from __future__ import annotations

import math


SUPPORTED_OPERATORS = {
    'rank': {'name': 'rank', 'aliases': ['rank'], 'arity': 1, 'category': 'cross_sectional', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Rank'},
    'ts_rank': {'name': 'ts_rank', 'aliases': ['ts_rank'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': False, 'qlib_name': None},
    'correlation': {'name': 'correlation', 'aliases': ['correlation', 'corr', 'rolling_corr'], 'arity': 3, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Corr'},
    'covariance': {'name': 'covariance', 'aliases': ['covariance', 'cov', 'rolling_cov'], 'arity': 3, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Cov'},
    'sum': {'name': 'sum', 'aliases': ['sum', 'ts_sum'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Sum'},
    'mean': {'name': 'mean', 'aliases': ['mean', 'ts_mean'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Mean'},
    'stddev': {'name': 'stddev', 'aliases': ['stddev', 'std', 'ts_std', 'ts_stddev'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Std'},
    'cs_regression': {'name': 'cs_regression', 'aliases': ['cs_regression', 'regression'], 'arity': 3, 'category': 'cross_sectional', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': False, 'qlib_name': None},
    'delta': {'name': 'delta', 'aliases': ['delta'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Delta'},
    'delay': {'name': 'delay', 'aliases': ['delay', 'lag', 'ref'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Ref'},
    'min': {'name': 'min', 'aliases': ['min'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Min'},
    'max': {'name': 'max', 'aliases': ['max'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Max'},
    'argmin': {'name': 'argmin', 'aliases': ['argmin'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': False, 'qlib_name': None},
    'argmax': {'name': 'argmax', 'aliases': ['argmax'], 'arity': 2, 'category': 'time_series', 'lookahead_safe': True, 'requires_window': True, 'supports_pandas': True, 'supports_qlib': False, 'qlib_name': None},
    'signedpower': {'name': 'signedpower', 'aliases': ['signedpower', 'signed_power'], 'arity': 2, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': False, 'qlib_name': None},
    'scale': {'name': 'scale', 'aliases': ['scale'], 'arity': 1, 'category': 'cross_sectional', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': False, 'qlib_name': None},
    'abs': {'name': 'abs', 'aliases': ['abs'], 'arity': 1, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Abs'},
    'log': {'name': 'log', 'aliases': ['log'], 'arity': 1, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Log'},
    'sign': {'name': 'sign', 'aliases': ['sign'], 'arity': 1, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': 'Sign'},
    'plus': {'name': 'plus', 'aliases': ['plus'], 'arity': 2, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': None},
    'minus': {'name': 'minus', 'aliases': ['minus'], 'arity': 2, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': None},
    'multiply': {'name': 'multiply', 'aliases': ['multiply'], 'arity': 2, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': None},
    'divide': {'name': 'divide', 'aliases': ['divide'], 'arity': 2, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': None},
    'negate': {'name': 'negate', 'aliases': ['negate'], 'arity': 1, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': True, 'supports_qlib': True, 'qlib_name': None},
    'where': {'name': 'where', 'aliases': ['where'], 'arity': 3, 'category': 'elementwise', 'lookahead_safe': True, 'requires_window': False, 'supports_pandas': False, 'supports_qlib': False, 'qlib_name': None},
}

ALIASES = {
    alias: name
    for name, meta in SUPPORTED_OPERATORS.items()
    for alias in meta['aliases']
}


def canonical_operator_name(name: str) -> str:
    key = str(name).strip().lower()
    if key not in ALIASES:
        raise KeyError(f'BLOCK_UNSUPPORTED_OPERATOR: {name}')
    return ALIASES[key]


def operator_meta(name: str) -> dict:
    return SUPPORTED_OPERATORS[canonical_operator_name(name)]


def validate_operator_call(name: str, args: list[dict]) -> None:
    meta = operator_meta(name)
    if len(args) != int(meta['arity']):
        raise ValueError(f'BLOCK_OPERATOR_ARITY_MISMATCH: {name} expected {meta["arity"]} args, got {len(args)}')
    if meta.get('requires_window'):
        window_node = args[-1]
        if window_node.get('type') != 'constant':
            raise ValueError(f'BLOCK_OPERATOR_WINDOW_NOT_LITERAL: {name}')
        value = window_node.get('value')
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) != int(value)
        ):
            raise ValueError(f'BLOCK_OPERATOR_WINDOW_NOT_INTEGER: {name}')
        try:
            window = int(value)
        except Exception as exc:
            raise ValueError(f'BLOCK_OPERATOR_WINDOW_INVALID: {name}') from exc
        if window <= 0:
            raise ValueError(f'BLOCK_OPERATOR_WINDOW_NONPOSITIVE: {name} window={window}')
