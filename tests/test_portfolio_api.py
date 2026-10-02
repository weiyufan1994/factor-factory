"""Cash/positions oracle written independently of the replay implementation."""
import json

import numpy as np
import pandas as pd
import pytest

from factor_factory.portfolio_api import backtest


def inputs():
    dates = ['20200102','20200103','20200106','20200107']
    factor = pd.DataFrame({'ts_code':['A'],'trade_date':[dates[0]],'factor_value':[1.]})
    prices = pd.DataFrame({'ts_code':['A']*4,'trade_date':dates,
                           'execution_price':[10.,10.,np.nan,12.], 'mark_price':[10.,10.,np.nan,12.]})
    rules = prices[['ts_code','trade_date']].assign(can_buy=[True,True,False,True],can_sell=[True,True,False,True],is_suspended=[False,False,True,False])
    return factor, dict(calendar=dates, prices=prices, constraints=rules,
                        formation_dates=[dates[0]], initial_cash=1010., one_way_cost=.01)


def test_two_fees_cash_units_nav_and_blocked_sell_then_retry():
    factor, kwargs = inputs()
    result = backtest(factor, **kwargs)
    # Jan3 spend1000+fee10 =>100 shares, cash0; Jan6 suspended lastmark10;
    # Jan7 sell100*12=1200-fee12 =>1188 cash, fees22.
    assert [r['cash'] for r in result['daily']] == pytest.approx([1010.,0.,0.,1188.])
    assert [r['equity'] for r in result['daily']] == pytest.approx([1010.,1000.,1000.,1188.])
    assert [r['nav'] for r in result['daily']] == pytest.approx([1.,1000/1010,1000/1010,1188/1010])
    assert [r['status'] for r in result['trades']] == ['FILLED','BLOCKED','FILLED']
    assert result['trades'][1]['reason'] == 'SUSPENDED'
    assert result['positions'][0]['units'] == pytest.approx(100.)
    assert result['positions'][1]['mark_status'] == 'STALE_MARK'
    assert result['metrics']['fees_paid']['value'] == pytest.approx(22.)
    assert result['metrics']['total_return']['value'] == pytest.approx(1188/1010-1)
    assert result['metrics']['max_drawdown']['value'] == pytest.approx(1000/1010-1)
    assert result['account_simulation'] is True and result['tradable_net_alpha_evidence'] is False
    json.dumps(result, allow_nan=False)


def test_blocked_buy_retains_cash_and_does_not_retry():
    factor, kwargs = inputs()
    kwargs['constraints'].loc[1,'can_buy'] = False
    result = backtest(factor, **kwargs)
    assert [r['cash'] for r in result['daily']] == [1010.]*4
    assert [r['nav'] for r in result['daily']] == [1.]*4
    assert len(result['trades']) == 1 and result['trades'][0]['status'] == 'BLOCKED'
    assert result['positions'] == [] and result['metrics']['fees_paid']['value'] == 0.
    assert result['metrics']['sharpe']['value'] is None
    assert result['metrics']['sharpe']['reason'] == 'zero_variance'


def test_ordinary_missing_mark_or_unknown_suspension_is_not_forward_filled():
    factor, kwargs = inputs()
    kwargs['constraints'].loc[2,'is_suspended'] = False
    with pytest.raises(ValueError, match='missing mark without confirmed suspension'):
        backtest(factor, **kwargs)
    factor, kwargs = inputs()
    kwargs['constraints'] = kwargs['constraints'].drop(index=2)
    with pytest.raises(ValueError, match='missing mark without confirmed suspension'):
        backtest(factor, **kwargs)


def test_tied_selection_includes_all_and_blocked_budget_stays_cash():
    factor, kwargs = inputs()
    factor = pd.concat([factor, factor.assign(ts_code='B')],ignore_index=True)
    kwargs['prices'] = pd.concat([kwargs['prices'],kwargs['prices'].assign(ts_code='B')],ignore_index=True)
    kwargs['constraints'] = pd.concat([kwargs['constraints'],kwargs['constraints'].assign(ts_code='B',can_buy=False)],ignore_index=True)
    result = backtest(factor, **kwargs)
    assert result['selections'][0]['selected'] == ['A','B']
    assert result['daily'][1]['cash'] == pytest.approx(505.)
    assert result['positions'][0]['units'] == pytest.approx(50.)


def test_explicit_schedule_and_strict_constraints():
    factor, kwargs = inputs()
    with pytest.raises(ValueError, match='scheduled exit'):
        backtest(factor, **{**kwargs,'holding_period':10})
    kwargs['constraints']['can_buy'] = 'False'
    with pytest.raises(TypeError, match='explicit booleans'):
        backtest(factor, **kwargs)


def test_q_lib_is_explicitly_unsupported_not_group_mean_fallback():
    factor, kwargs = inputs()
    result = backtest(factor, **kwargs, backend='qlib')
    assert result['status'] == 'unsupported' and not result['account_simulation']
    assert result['daily'] == [] and result['metrics'] == {}
