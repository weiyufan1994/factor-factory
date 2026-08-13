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
    'cs_regression': {
        'name': 'cs_regression',
        'aliases': ['cs_regression', 'regression'],
        'arity': 3,
        'category': 'cross_sectional',
        'lookahead_safe': True,
        'requires_window': False,
        'literal_integer_args': [2],
        'minimum_integer_values': {2: 0},
        'allowed_integer_values': {2: [0, 1, 2]},
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
    },
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
    'cs_zscore': {
        'name': 'cs_zscore',
        'aliases': ['cs_zscore'],
        'arity': 2,
        'category': 'cross_sectional',
        'lookahead_safe': True,
        'requires_window': False,
        'literal_integer_args': [1],
        'minimum_integer_values': {1: 0},
        'allowed_integer_values': {1: [0, 1]},
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_cs_zscore_v1',
        'semantic_definition': 'Per-trade-date z-score over finite observations; zero variance returns NaN.',
    },
    'signed_log1p': {
        'name': 'signed_log1p',
        'aliases': ['signed_log1p'],
        'arity': 1,
        'category': 'elementwise',
        'lookahead_safe': True,
        'requires_window': False,
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_signed_log1p_v1',
        'semantic_definition': 'sign(x) * log(1 + abs(x)).',
    },
    'rolling_excess_kurtosis': {
        'name': 'rolling_excess_kurtosis',
        'aliases': ['rolling_excess_kurtosis'],
        'arity': 2,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1],
        'minimum_integer_values': {1: 4},
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_excess_kurtosis_unbiased_v1',
        'semantic_definition': 'Bias-corrected Fisher excess kurtosis over the trailing window including t.',
    },
    'rolling_pearson_kurtosis': {
        'name': 'rolling_pearson_kurtosis',
        'aliases': ['rolling_pearson_kurtosis'],
        'arity': 2,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1],
        'minimum_integer_values': {1: 4},
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_pearson_kurtosis_unbiased_v1',
        'semantic_definition': 'Bias-corrected Pearson kurtosis over the trailing window including t.',
    },
    'rolling_topk_skew': {
        'name': 'rolling_topk_skew',
        'aliases': ['rolling_topk_skew'],
        'arity': 3,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1, 2],
        'minimum_integer_values': {1: 3, 2: 3},
        'ordered_integer_args': [[2, 1]],
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_topk_skew_unbiased_v1',
        'semantic_definition': 'Bias-corrected sample skewness of the k largest finite values in the trailing n observations.',
    },
    'rolling_bottomk_skew': {
        'name': 'rolling_bottomk_skew',
        'aliases': ['rolling_bottomk_skew'],
        'arity': 3,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1, 2],
        'minimum_integer_values': {1: 3, 2: 3},
        'ordered_integer_args': [[2, 1]],
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_bottomk_skew_unbiased_v1',
        'semantic_definition': 'Bias-corrected sample skewness of the k smallest finite values in the trailing n observations.',
    },
    'rolling_max_inner_skew': {
        'name': 'rolling_max_inner_skew',
        'aliases': ['rolling_max_inner_skew'],
        'arity': 3,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1, 2],
        'minimum_integer_values': {1: 3, 2: 3},
        'ordered_integer_args': [[2, 1]],
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_max_inner_skew_unbiased_v1',
        'semantic_definition': 'Maximum bias-corrected k-observation rolling skewness within the trailing n observations.',
    },
    'rolling_min_inner_skew': {
        'name': 'rolling_min_inner_skew',
        'aliases': ['rolling_min_inner_skew'],
        'arity': 3,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1, 2],
        'minimum_integer_values': {1: 3, 2: 3},
        'ordered_integer_args': [[2, 1]],
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_min_inner_skew_unbiased_v1',
        'semantic_definition': 'Minimum bias-corrected k-observation rolling skewness within the trailing n observations.',
    },
    'rolling_max_subwindow_sum': {
        'name': 'rolling_max_subwindow_sum',
        'aliases': ['rolling_max_subwindow_sum'],
        'arity': 3,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1, 2],
        'minimum_integer_values': {1: 1, 2: 1},
        'ordered_integer_args': [[2, 1]],
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_max_subwindow_sum_v1',
        'semantic_definition': 'Maximum sum among contiguous k-observation subwindows contained in the trailing n observations.',
    },
    'rolling_topk_sum': {
        'name': 'rolling_topk_sum',
        'aliases': ['rolling_topk_sum'],
        'arity': 3,
        'category': 'time_series',
        'lookahead_safe': True,
        'requires_window': True,
        'lookback_arg_positions': [1],
        'literal_integer_args': [1, 2],
        'minimum_integer_values': {1: 1, 2: 1},
        'ordered_integer_args': [[2, 1]],
        'supports_pandas': True,
        'supports_qlib': False,
        'qlib_name': None,
        'web_safe': True,
        'semantic_contract_version': 'factorforge_rolling_topk_sum_v1',
        'semantic_definition': 'Sum of the k largest finite values in the trailing n observations.',
    },
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
    literal_integer_args = list(meta.get('literal_integer_args') or [])
    legacy_window_validation = bool(meta.get('requires_window') and not literal_integer_args)
    if legacy_window_validation:
        literal_integer_args = [len(args) - 1]
    parsed_integers: dict[int, int] = {}
    for position in literal_integer_args:
        value_node = args[position]
        if value_node.get('type') != 'constant':
            if legacy_window_validation:
                raise ValueError(f'BLOCK_OPERATOR_WINDOW_NOT_LITERAL: {name}')
            raise ValueError(f'BLOCK_OPERATOR_PARAMETER_NOT_LITERAL: {name} arg={position + 1}')
        value = value_node.get('value')
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) != int(value)
        ):
            if legacy_window_validation:
                raise ValueError(f'BLOCK_OPERATOR_WINDOW_NOT_INTEGER: {name}')
            raise ValueError(f'BLOCK_OPERATOR_PARAMETER_NOT_INTEGER: {name} arg={position + 1}')
        try:
            parsed = int(value)
        except Exception as exc:
            if legacy_window_validation:
                raise ValueError(f'BLOCK_OPERATOR_WINDOW_INVALID: {name}') from exc
            raise ValueError(f'BLOCK_OPERATOR_PARAMETER_INVALID: {name} arg={position + 1}') from exc
        minimum = int((meta.get('minimum_integer_values') or {}).get(position, 1))
        if parsed < minimum:
            if legacy_window_validation:
                raise ValueError(f'BLOCK_OPERATOR_WINDOW_NONPOSITIVE: {name} window={parsed}')
            raise ValueError(
                f'BLOCK_OPERATOR_PARAMETER_BELOW_MINIMUM: {name} arg={position + 1} value={parsed} minimum={minimum}'
            )
        allowed = (meta.get('allowed_integer_values') or {}).get(position)
        if allowed is not None and parsed not in {int(item) for item in allowed}:
            raise ValueError(
                f'BLOCK_OPERATOR_PARAMETER_UNSUPPORTED: {name} arg={position + 1} value={parsed}'
            )
        parsed_integers[position] = parsed
    for lesser_position, greater_position in meta.get('ordered_integer_args') or []:
        if parsed_integers[lesser_position] > parsed_integers[greater_position]:
            raise ValueError(
                f'BLOCK_OPERATOR_PARAMETER_ORDER_INVALID: {name} '
                f'arg{lesser_position + 1}>{greater_position + 1}'
            )
