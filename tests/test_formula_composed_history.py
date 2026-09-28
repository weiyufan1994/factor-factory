"""Arithmetic oracles for composed history, independent of the IR evaluator."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.pandas_codegen import generate_pandas_formula_code
from factor_factory.formula.parity import compare_outputs, make_operator_fixture, run_operator_parity
from factor_factory.formula.parser import parse_formula
from factor_factory.formula.semantics import max_formula_ir_lookback


@pytest.mark.parametrize(('formula', 'span'), [
    ('mean(delay(close,200),200)', 400),
    ('mean(mean(close,5),3)', 7),
    ('delay(mean(close,5),3)', 8),
    ('mean(delay(close,2)+mean(open,4),3)', 6),
    ('correlation(delay(close,4),mean(open,3),5)', 9),
    ('ts_ffill(delay(close,2),4)', 7),
    ('mean(adv20,5)', 24),
    ('rolling_max_inner_skew(delay(close,4),20,5)', 24),
    ('rolling_max_subwindow_sum(delay(close,4),20,5)', 24),
    ('rank(close)+open', 0),
    ('delay(close,1)', 2),
    ('ts_ffill(close,0)', 0),
])
def test_composed_input_span_includes_current_observation(formula, span):
    assert max_formula_ir_lookback(parse_formula(formula, raise_on_error=True)) == span


def _frame(size=420):
    values = np.arange(1., size + 1.)
    return pd.DataFrame({'ts_code': 'A', 'trade_date': pd.bdate_range('2020-01-01', periods=size).strftime('%Y%m%d'),
                         'close': values, 'open': 3 * values + 7, 'volume': values ** 2 + 1})


@pytest.mark.parametrize('engine', ['reference', 'optimized'])
@pytest.mark.parametrize(('formula', 'first', 'oracle'), [
    ('mean(delay(close,200),200)', 399, lambda i: i - 298.5),
    ('mean(mean(close,5),3)', 6, lambda i: i - 2.),
    ('mean(delay(close,2)+mean(open,4),3)', 5, lambda i: 4 * i + .5),
    ('mean(adv20,5)', 23, lambda i: sum(sum((k + 1) ** 2 + 1 for k in range(j-19, j+1))/20 for j in range(i-4, i+1))/5),
])
def test_first_valid_observation_and_values_have_independent_arithmetic_oracle(formula, first, oracle, engine):
    ir = parse_formula(formula, raise_on_error=True)
    frame = _frame()
    result = evaluate_formula_frame(ir, frame, engine=engine).factor_value.to_numpy()
    expected = np.array([np.nan if i < first else oracle(i) for i in range(len(frame))])
    np.testing.assert_allclose(result, expected, equal_nan=True)
    assert max_formula_ir_lookback(ir) == first + 1


def _step3b():
    path = Path(__file__).resolve().parents[1] / 'skills/factor-forge-step3/scripts/run_step3b.py'
    spec = importlib.util.spec_from_file_location('step3b_composed_history', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('formula', [
    'mean(delay(close,200),200)',
    'mean(delay(close,200),200)+mean(delay(open,180),150)',
])
def test_actual_step3b_row_cap_preserves_composed_history(formula):
    ir = parse_formula(formula, raise_on_error=True)
    full = pd.concat([_frame().assign(ts_code=f'S{i:04}') for i in range(600)], ignore_index=True)
    sample, profile = _step3b().limit_step3b_sample_frame(full, label='synthetic', formula_ir=ir)
    result = evaluate_formula_frame(ir, sample)
    assert profile['formula_max_lookback'] == 400
    assert profile['date_count'] == 420
    assert len(sample) <= 250000
    assert profile['ticker_count'] == 512
    expected = sample.sort_values(['ts_code', 'trade_date']).close.to_numpy() - 299.5
    if '+' in formula:
        # mean of open observations [t-329, t-180], open_j=3*(j+1)+7.
        expected += 3 * sample.sort_values(['ts_code', 'trade_date']).close.to_numpy() - 756.5
    valid = result.factor_value.notna().to_numpy()
    assert valid.sum() == 512 * 21
    np.testing.assert_allclose(result.factor_value[valid], expected[valid])


def test_step3b_fails_when_bounded_sample_cannot_contain_history(monkeypatch):
    module = _step3b()
    monkeypatch.setattr(module, 'STEP3B_SAMPLE_MAX_ROWS', 10)
    ir = parse_formula('mean(delay(close,20),20)', raise_on_error=True)
    with pytest.raises(ValueError, match='BLOCK_STEP3B_SAMPLE_HISTORY_INSUFFICIENT'):
        module.limit_step3b_sample_frame(_frame(50), label='synthetic', formula_ir=ir)


def test_nested_fixture_and_generated_parity_have_valid_values(tmp_path):
    ir = parse_formula('mean(delay(close,200),200)', raise_on_error=True)
    fixture = make_operator_fixture(ir)
    assert fixture.trade_date.nunique() >= 400
    path = tmp_path / 'generated.py'
    path.write_text(generate_pandas_formula_code(report_id='HISTORY_TEST', factor_id='HISTORY_TEST', formula_ir=ir))
    result = run_operator_parity(ir, path)
    assert result['status'] == 'PASS'
    assert result['non_null_count'] > 0


@pytest.mark.parametrize('values', [[], [np.nan, np.nan], [np.inf, np.inf], [0., np.inf]])
def test_parity_without_valid_finite_numeric_evidence_cannot_pass(values):
    frame = pd.DataFrame({'ts_code': ['A'] * len(values), 'trade_date': [str(i) for i in range(len(values))], 'factor_value': values})
    with pytest.raises(AssertionError, match='BLOCK_OPERATOR_PARITY_FAILED'):
        compare_outputs(frame, frame.copy())


def test_parity_with_warmup_nulls_and_zero_values_can_pass():
    frame = pd.DataFrame({'ts_code': ['A', 'A'], 'trade_date': ['1', '2'], 'factor_value': [np.nan, 0.]})
    assert compare_outputs(frame, frame.copy())['non_null_count'] == 1
