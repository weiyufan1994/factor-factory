"""Explicit, offline fractional-share long-only account replay.

Uses the same buy/sell cash transitions as the existing local-IS evaluator.
This is a bounded account model, not an exchange, capacity, or live-tradability
claim. No corporate actions, borrowing, lot rounding, slippage or price fetching.
"""
from __future__ import annotations

import json
from numbers import Integral

import numpy as np
import pandas as pd

from factor_factory.accounting import buy_fill, sell_fill
from factor_factory.research_api import _dates, _frame, _index, _metric, factor_coverage, normalize_factor_frame


def backtest(factor_values: pd.DataFrame, *, calendar, prices: pd.DataFrame,
             constraints: pd.DataFrame, formation_dates, holding_period: int = 1,
             entry_offset: int = 1, top_k: int = 1, initial_cash: float = 1_000_000.0,
             one_way_cost: float = 0.003, annualization: int = 252,
             backend: str = 'self_account', expected_index: pd.MultiIndex | None = None) -> dict:
    """Replay explicit signal cohorts through cash, holdings, fees and marks.

    Inputs use the standard datetime/instrument index or ts_code/trade_date.
    prices: execution_price and mark_price, positive or explicitly NaN, same
    currency/unit/basis. constraints: non-null bool can_buy/can_sell/is_suspended.
    formation_dates: explicit session schedule. At formation rank descending,
    include all names tied at kth value, ignore/report NaN signals. Enter after
    entry_offset>=1 sessions; exit holding_period>=1 sessions later. Selling
    comes before buying. A blocked sale retries each subsequent session; a
    blocked buy is canceled without redistributing its reserved budget. Each
    cohort splits currently available cash equally including the buy fee.
    Missing constraints block orders. Only a confirmed suspended held position
    may retain its last mark, with STALE_MARK disclosure. Other missing marks
    reject the replay instead of inventing a valuation.
    Metrics include every supplied calendar session, including cash-only days;
    annualization is the explicitly supplied sessions-per-year convention.
    """
    if backend not in {'self_account', 'qlib'}:
        raise ValueError('unknown portfolio backend')
    factor = normalize_factor_frame(factor_values)
    coverage = factor_coverage(factor, expected_index=expected_index)
    if coverage['unexpected_rows']:
        raise ValueError('factor keys lie outside expected_index')
    if backend == 'qlib':
        return {'api_version': 'factorforge_research_api_v1', 'analysis': 'portfolio', 'backend': 'qlib', 'status': 'unsupported',
                'reason': 'native_qlib_provider_and_account_adapter_not_bound',
                'account_simulation': False, 'coverage': coverage, 'metrics': {}, 'daily': [], 'trades': [], 'positions': []}
    for name, value in [('holding_period', holding_period), ('entry_offset', entry_offset), ('top_k', top_k), ('annualization', annualization)]:
        if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
            raise ValueError(f'{name} must be a positive integer')
    if not np.isfinite(initial_cash) or isinstance(initial_cash, bool) or initial_cash <= 0:
        raise ValueError('initial_cash must be finite and positive')
    if not np.isfinite(one_way_cost) or isinstance(one_way_cost, bool) or not 0 <= one_way_cost < 1:
        raise ValueError('one_way_cost must be a fraction in [0,1)')
    quotes = _frame(prices, ['execution_price', 'mark_price'])
    if (quotes.stack() <= 0).any():
        raise ValueError('observed prices must be positive')
    sessions = _dates(calendar, name='calendar')
    if sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError('calendar must be nonempty, sorted and unique')
    formations = _dates(formation_dates, name='formation_dates')
    if formations.empty or formations.has_duplicates or not formations.is_monotonic_increasing:
        raise ValueError('formation_dates must be explicit, sorted and unique')
    constraint_columns = ['can_buy', 'can_sell', 'is_suspended']
    if not isinstance(constraints, pd.DataFrame) or constraints.columns.has_duplicates:
        raise TypeError('constraints must be a DataFrame with unique column names')
    if not set(constraint_columns).issubset(constraints.columns):
        raise ValueError('constraints require can_buy/can_sell/is_suspended')
    if isinstance(constraints.index, pd.MultiIndex):
        idx = _index(constraints.index)
        required = set(constraint_columns)
    else:
        if not {'ts_code', 'trade_date'}.issubset(constraints):
            raise ValueError('constraints require explicit stock/session keys')
        idx = _index(pd.MultiIndex.from_arrays([_dates(constraints.trade_date, name='constraint date'), constraints.ts_code], names=['datetime', 'instrument']))
        required = set(constraint_columns) | {'ts_code', 'trade_date'}
    if set(constraints.columns) != required:
        raise ValueError('select only the three explicit constraint columns and keys')
    rules = pd.DataFrame(index=idx)
    for column in constraint_columns:
        values = constraints[column]
        if values.isna().any() or not values.map(lambda x: isinstance(x, (bool, np.bool_))).all():
            raise TypeError(f'{column} must contain explicit booleans, not strings/0/1/Unknown')
        rules[column] = values.to_numpy(dtype=bool)
    if (rules.is_suspended & (rules.can_buy | rules.can_sell)).any():
        raise ValueError('suspended rows cannot allow buying or selling')
    for name, index in [('factor', factor.index), ('prices', quotes.index), ('constraints', rules.index)]:
        if not index.get_level_values('datetime').isin(sessions).all():
            raise ValueError(f'{name} dates outside calendar')
    if not formations.isin(sessions).all():
        raise ValueError('formation dates outside calendar')
    scheduled = {}
    selections = []
    factor_dates = factor.index.get_level_values('datetime')
    for date in formations:
        position = sessions.get_loc(date)
        end = position + entry_offset + holding_period
        if end >= len(sessions):
            raise ValueError('calendar must include the scheduled exit for every formation')
        if date not in factor_dates:
            raise ValueError('formation date has no supplied factor rows; supply explicit NaNs if unavailable')
        day = factor.xs(date, level='datetime')['factor_value']
        valid = day.dropna()
        boundary = valid.nlargest(min(top_k, len(valid))).iloc[-1] if len(valid) else None
        selected = sorted(valid.index[valid >= boundary].tolist()) if boundary is not None else []
        entry, exit_date = sessions[position + entry_offset], sessions[end]
        event = {'formation': date, 'entry': entry, 'exit': exit_date, 'selected': selected}
        scheduled.setdefault(entry, []).append(event)
        selections.append({'formation_date': date.strftime('%Y-%m-%d'), 'observed_rows': len(day),
                           'valid_rows': len(valid), 'nan_rows': int(day.isna().sum()),
                           'selected': selected, 'entry_date': entry.strftime('%Y-%m-%d'),
                           'exit_date': exit_date.strftime('%Y-%m-%d')})
    # Index once, then constant-time key access inside the stateful account loop.
    quote_map = {key: tuple(row) for key, row in zip(quotes.index, quotes.to_numpy())}
    rule_map = {key: tuple(row) for key, row in zip(rules.index, rules.to_numpy())}
    cash, previous_nav = float(initial_cash), float(initial_cash)
    holdings, trades, daily, position_rows = [], [], [], []
    def order_reason(date, code, side):
        constraint = rule_map.get((date, code))
        quote = quote_map.get((date, code))
        if constraint is None:
            return 'CONSTRAINT_MISSING'
        if constraint[2]:
            return 'SUSPENDED'
        if not constraint[0 if side == 'BUY' else 1]:
            return side + '_NOT_ALLOWED'
        if quote is None or np.isnan(quote[0]):
            return 'EXECUTION_PRICE_MISSING'
        return None
    def record(date, position, side, reason, *, units=0., gross=0., fee=0., flow=0.):
        trades.append({'date': date.strftime('%Y-%m-%d'), 'formation_date': position['formation'].strftime('%Y-%m-%d'),
                       'instrument': position['code'], 'side': side, 'status': 'FILLED' if reason is None else 'BLOCKED',
                       'reason': reason, 'execution_price': float(quote_map[(date, position['code'])][0]) if reason is None else None,
                       'units': float(units), 'gross_amount': float(gross),
                       'fee': float(fee), 'cash_flow': float(flow), 'cash_after': float(cash)})
    for date in sessions:
        retained = []
        for position in holdings:
            if date < position['exit']:
                retained.append(position)
                continue
            code = position['code']
            reason = order_reason(date, code, 'SELL')
            if reason is not None:
                record(date, position, 'SELL', reason)
                retained.append(position)
                continue
            cash, gross, fee = sell_fill(cash, position['units'], quote_map[(date, code)][0], one_way_cost)
            record(date, position, 'SELL', None, units=position['units'], gross=gross, fee=fee, flow=gross-fee)
        holdings = retained
        for event in scheduled.get(date, []):
            codes = event['selected']
            budget = cash / (len(codes) * (1 + one_way_cost)) if codes else 0.
            for code in codes:
                position = {'code': code, 'formation': event['formation'], 'exit': event['exit']}
                reason = order_reason(date, code, 'BUY') or ('NO_CASH' if budget <= 0 else None)
                if reason is not None:
                    record(date, position, 'BUY', reason)
                    continue
                price = quote_map[(date, code)][0]
                cash, units, fee = buy_fill(cash, budget, price, one_way_cost)
                # Only absorb floating-point residue, never fund another order.
                if -1e-10 * max(1., initial_cash) < cash < 0:
                    cash = 0.
                position.update(units=units, last_mark=price)
                holdings.append(position)
                record(date, position, 'BUY', None, units=units, gross=budget, fee=fee, flow=-budget-fee)
        market_value, stale_count = 0., 0
        for position in holdings:
            quote = quote_map.get((date, position['code']))
            stale = quote is None or np.isnan(quote[1])
            if stale:
                rule = rule_map.get((date, position['code']))
                if rule is None or not rule[2]:
                    raise ValueError(f'missing mark without confirmed suspension: {date.date()} {position["code"]}')
            if not stale:
                position['last_mark'] = quote[1]
            stale_count += int(stale)
            value = position['units'] * position['last_mark']
            market_value += value
            position_rows.append({'date': date.strftime('%Y-%m-%d'), 'instrument': position['code'],
                                  'formation_date': position['formation'].strftime('%Y-%m-%d'),
                                  'units': float(position['units']), 'mark': float(position['last_mark']),
                                  'market_value': float(value), 'mark_status': 'STALE_MARK' if stale else 'OBSERVED'})
        nav = cash + market_value
        if not np.isfinite(nav) or nav <= 0:
            raise ValueError('account NAV is nonfinite or nonpositive')
        daily.append({'date': date.strftime('%Y-%m-%d'), 'cash': float(cash), 'market_value': float(market_value),
                      'equity': float(nav), 'nav': float(nav / initial_cash), 'daily_return': float(nav / previous_nav - 1),
                      'open_positions': len(holdings), 'stale_positions': stale_count,
                      'valuation_status': 'STALE_MARK' if stale_count else 'OBSERVED'})
        previous_nav = nav
    n = len(daily)
    returns = np.array([row['daily_return'] for row in daily])
    navs = np.array([initial_cash, *[row['equity'] for row in daily]])
    std = float(returns.std(ddof=1)) if n > 1 else None
    ratio = navs[-1] / initial_cash
    with np.errstate(over='ignore', invalid='ignore'):
        annual_return = float(np.power(ratio, annualization / n) - 1)
    drawdowns = navs / np.maximum.accumulate(navs) - 1
    filled = [row for row in trades if row['status'] == 'FILLED']
    fees = sum(row['fee'] for row in filled)
    result = {'api_version': 'factorforge_research_api_v1', 'analysis': 'portfolio', 'backend': 'self_account',
              'status': 'partial' if holdings else 'ok', 'coverage': coverage,
              'valuation': {'all_marks_observed': not any(row['stale_positions'] for row in daily),
                            'carried_mark_sessions': sum(bool(row['stale_positions']) for row in daily),
                            'carried_mark_position_sessions': sum(row['stale_positions'] for row in daily)},
              'evaluation_scope': 'offline_fractional_share_account', 'account_simulation': True,
              'tradable_net_alpha_evidence': False,
              'model': {'price_basis': 'caller_supplied_consistent_basis_no_corporate_actions',
                        'entry_offset_sessions': int(entry_offset), 'holding_period_sessions': int(holding_period),
                        'top_k_with_all_boundary_ties': int(top_k), 'annualization': int(annualization),
                        'one_way_cost': float(one_way_cost), 'initial_cash': float(initial_cash),
                        'sell_retry': 'every_session_after_scheduled_exit', 'buy_retry': 'none',
                        'mark_policy': 'last_mark_only_for_confirmed_suspension; other_missing_marks_raise'},
              'daily': daily, 'trades': trades, 'positions': position_rows, 'selections': selections,
              'metrics': {
                  'final_equity': _metric(navs[-1], 'currency', n),
                  'final_nav': _metric(ratio, 'initial_cash_multiple', n),
                  'final_cash': _metric(cash, 'currency', n),
                  'total_return': _metric(ratio-1, 'decimal_return_net_of_explicit_fees', n),
                  'annualized_return': _metric(annual_return, 'decimal_return_geometric_annualized', n),
                  'annualized_volatility': _metric(std * np.sqrt(annualization) if std is not None else None, 'decimal_return_annualized', n, 'insufficient_sessions'),
                  'sharpe': _metric(float(returns.mean()) / std * np.sqrt(annualization) if std is not None and std > 0 else None, 'ratio_annualized_zero_risk_free', n, 'zero_variance' if std == 0 else 'insufficient_sessions'),
                  'max_drawdown': _metric(float(drawdowns.min()), 'signed_nav_fraction_including_initial_cash', n),
                  'fees_paid': _metric(fees, 'currency', len(filled)),
                  'gross_traded_amount': _metric(sum(row['gross_amount'] for row in filled), 'currency_buys_plus_sells', len(filled)),
              },
              'warnings': ['Fractional-share account only; no lots, capacity, slippage, dividends, splits, delisting settlement or borrowing.']}
    if any(row['stale_positions'] for row in daily):
        result['warnings'].append('NAV uses last marks on disclosed sessions; this is not fully observed valuation.')
    if holdings:
        result['warnings'].append('Some scheduled exits remained blocked at the end; holdings remain in NAV.')
    json.dumps(result, allow_nan=False)
    return result
