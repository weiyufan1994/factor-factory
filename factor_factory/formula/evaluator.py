from __future__ import annotations

import numpy as np
import pandas as pd

from .operators import (
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
    ts_std,
    ts_sum,
)


def _window(value) -> int:
    if isinstance(value, pd.Series):
        value = value.dropna().iloc[0]
    return int(value)


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
        return ts_rank(args[0], _window(args[1]), frame)
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


def evaluate_formula_ir(formula_ir: dict, frame: pd.DataFrame) -> pd.Series:
    if formula_ir.get('parse_status') != 'success':
        raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_SYNTAX: {formula_ir.get("parse_errors")}')
    required = {'ts_code', 'trade_date'}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f'BLOCK_MISSING_REFERENCE_KEYS: {sorted(missing)}')
    working = frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True).copy()
    return _eval(formula_ir['root'], working)


def evaluate_formula_frame(formula_ir: dict, frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True).copy()
    out = working[['ts_code', 'trade_date']].copy()
    out['factor_value'] = evaluate_formula_ir(formula_ir, working)
    return out
