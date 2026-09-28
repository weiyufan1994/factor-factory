from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.parser import parse_formula


@pytest.mark.parametrize('keyword', [
    'with_one_col=False', 'fill_predict=True', 'dummies=open',
    'with_one_col=1', 'fill_predict=0', 'dummies=False',
    'with_one_col=close', 'fill_predict=unknown', 'dummies=[]',
    'with_one_col=True,with_one_col=False', 'out_type=0,out_type=1',
])
def test_unsupported_regression_keywords_fail_explicitly(keyword):
    formula = f'cs_regression(close,open,{keyword})'
    result = parse_formula(formula)
    assert result['parse_status'] == 'failed'
    with pytest.raises(ValueError, match='BLOCK_'):
        parse_formula(formula, raise_on_error=True)


@pytest.mark.parametrize('suffix', ['', ',with_one_col=True', ',fill_predict=False', ',dummies=None',
                                    ',with_one_col=True,fill_predict=False,dummies=None'])
@pytest.mark.parametrize(('mode', 'expected'), [(0, [1/3, -2/3, 1/3]), (1, [2/3, 8/3, 14/3]), (2, [2., 2., 2.])])
def test_defaults_keep_ols_semantics_with_independent_oracle(suffix, mode, expected):
    frame = pd.DataFrame({'ts_code': ['A', 'B', 'C'], 'trade_date': '20240102', 'open': [1., 2., 3.], 'close': [1., 2., 5.]})
    ir = parse_formula(f'cs_regression(close,open,out_type={mode}{suffix})', raise_on_error=True)
    result = evaluate_formula_frame(ir, frame)
    np.testing.assert_allclose(result.factor_value, expected, atol=1e-14)
    default = parse_formula(f'cs_regression(close,open,{mode})', raise_on_error=True)
    assert ir['root'] == default['root']
