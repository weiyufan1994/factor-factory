"""Calendar-month targets, label diagnostics and the shared accepted account.

Factor keys are already scheduled entry dates. They are never shifted again.
Account selection uses formation membership/scores, never future labels.
See docs/calendar-month-account.md for source provenance and model boundaries.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from factor_factory.calendar_account import SUSPENSION_POLICY, simulate_account
from factor_factory.research_api import _dates, _frame, _index


def calendar_month_windows(calendar):
    """Certified month-end t, next supplied exchange session e, next month's e.

    The caller supplies the complete independent exchange calendar, already
    clipped to the research window. The last month needs an observed next-month
    session to certify its formation; the last certified label may be immature.
    """
    c = _dates(calendar, name='calendar')
    if c.empty or c.has_duplicates or not c.is_monotonic_increasing:
        raise ValueError('calendar must be nonempty, sorted and unique')
    months = c.to_period('M').asi8
    if (np.diff(months) > 1).any():
        raise ValueError('calendar has a missing whole month')
    f = np.flatnonzero(months[:-1] != months[1:])
    entries = c[f + 1]
    return pd.DataFrame({'signal_date': c[f], 'entry_date': entries,
                         'label_end_date': [*entries[1:], pd.NaT] if len(entries) else []})


def _members(membership):
    """Rows assert true PIT membership; never infer members from factor output."""
    if not isinstance(membership, pd.DataFrame) or set(membership.columns) != {'ts_code', 'trade_date'}:
        raise ValueError('membership requires exactly ts_code/trade_date true PIT member rows')
    result = membership.copy()
    result['trade_date'] = _dates(result.trade_date, name='membership formation date')
    _index(pd.MultiIndex.from_arrays([result.trade_date, result.ts_code], names=['datetime', 'instrument']))
    return result


def calendar_month_targets(factor_values, *, calendar, membership):
    """Frozen upper-decile rule, with missing signal months explicitly in cash.

    >=30 finite scores, >=50% of full PIT members, nonconstant signal; otherwise
    empty target. Type-7 90th percentile, inclusive ties, equal selected weights.
    No labels/controls participate. Extra symbols or non-entry keys are errors.
    """
    windows = calendar_month_windows(calendar)
    if windows.empty:
        raise ValueError('calendar contains no certified month-end formation')
    values = _frame(factor_values, ['factor_value'], allow_empty=True).reset_index().rename(
        columns={'datetime': 'trade_date', 'instrument': 'ts_code'})
    members = _members(membership)
    if not values.trade_date.isin(windows.entry_date).all():
        raise ValueError('factor keys must be scheduled monthly entry dates; no second shift')
    targets, coverage = {}, []
    for w in windows.itertuples(index=False):
        names = set(members.loc[members.trade_date.eq(w.signal_date), 'ts_code'])
        if not names:
            raise ValueError(f'missing_PIT_denominator:{w.signal_date.date()}')
        day = values.loc[values.trade_date.eq(w.entry_date)]
        if not set(day.ts_code).issubset(names):
            raise ValueError(f'factor_outside_formation_membership:{w.signal_date.date()}')
        valid = day.loc[day.factor_value.notna()]
        reason = ('insufficient_finite_scores' if len(valid) < 30 else
                  'insufficient_member_coverage' if len(valid) / len(names) < .5 else
                  'constant_signal' if valid.factor_value.nunique() < 2 else None)
        threshold = np.quantile(valid.factor_value, .9, method='linear') if reason is None else None
        selected = valid.loc[valid.factor_value.ge(threshold), 'ts_code'] if threshold is not None else pd.Series(dtype=str)
        targets[w.entry_date] = pd.Series(1 / len(selected), index=selected, name='target_weight') if len(selected) else pd.Series(dtype=float, name='target_weight')
        coverage.append({'signal_date': w.signal_date, 'entry_date': w.entry_date,
                         'PIT_members': len(names), 'returned_rows': len(day), 'scored': len(valid),
                         'missing_rows': len(names) - len(day), 'nan_rows': int(day.factor_value.isna().sum()),
                         'coverage': len(valid) / len(names), 'score_gate': reason is None,
                         'threshold': threshold, 'selected': len(selected), 'reason': reason})
    return windows, values, targets, pd.DataFrame(coverage)


def _market_day(market, day, symbols):
    if hasattr(market, 'for_day'):
        frame = market.for_day(day, symbols)
    else:
        frame = market.loc[market.trade_date.eq(day) & market.ts_code.isin(symbols)].copy()
    if frame.duplicated(['trade_date', 'ts_code']).any() or not frame.trade_date.eq(day).all():
        raise ValueError('invalid label endpoint keys')
    return frame


def calendar_month_diagnostics(values, windows, market, *, price_basis_id, group_boundary='lower'):
    """Observed adjusted close(e_next)/close(e)-1, never stale/next-valid quotes.

    Five groups are formed on all finite formation signals before reading labels;
    means disclose the available label counts. They are not accounts or shorts.
    """
    if group_boundary not in {'lower', 'upper'}:
        raise ValueError('group_boundary must be lower or upper')
    periods, labels = [], []
    for w in windows.itertuples(index=False):
        day = values.loc[values.trade_date.eq(w.entry_date), ['ts_code', 'factor_value']].copy()
        day['forward_return'] = np.nan
        if pd.notna(w.label_end_date) and not day.empty:
            endpoints = []
            for date in (w.entry_date, w.label_end_date):
                frame = _market_day(market, date, set(day.ts_code))
                if 'price_basis_id' in frame and not frame.price_basis_id.eq(price_basis_id).all():
                    raise ValueError('label price basis mismatch')
                price = pd.to_numeric(frame.set_index('ts_code')['price'], errors='raise').reindex(day.ts_code)
                price = price.where(np.isfinite(price) & price.gt(0))
                endpoints.append(price.to_numpy())
            with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
                day['forward_return'] = endpoints[1] / endpoints[0] - 1
            if np.isinf(day.forward_return).any():
                raise ValueError('monthly label overflow')
        paired = day.dropna(subset=['factor_value', 'forward_return'])
        reason = ('immature_label' if pd.isna(w.label_end_date) else
                  'cross_section_insufficient' if len(paired) < 2 else
                  'constant_signal' if paired.factor_value.nunique() < 2 else
                  'constant_return' if paired.forward_return.nunique() < 2 else None)
        row = {'signal_date': w.signal_date, 'entry_date': w.entry_date, 'label_end_date': w.label_end_date,
               'input_n': len(day), 'n': len(paired), 'reason': reason}
        for method, key in [('pearson', 'pearson_ic'), ('spearman', 'rank_ic')]:
            row[key] = paired.factor_value.corr(paired.forward_return, method=method) if reason is None else np.nan
        finite = day.loc[day.factor_value.notna()].copy()
        percentile = (finite.factor_value.rank(method='average') - .5) / len(finite) if len(finite) else pd.Series(dtype=float)
        finite['group'] = np.searchsorted([.2, .4, .6, .8], percentile,
                                          side='left' if group_boundary == 'lower' else 'right') + 1
        for group in range(1, 6):
            selected = finite.loc[finite.group.eq(group), 'forward_return']
            row[f'group_{group}_selected_n'] = len(selected)
            row[f'group_{group}_label_n'] = int(selected.notna().sum())
            row[f'group_{group}_return'] = selected.mean()
        row['top_minus_bottom_label_spread'] = row['group_5_return'] - row['group_1_return']
        periods.append(row)
        day['trade_date'] = w.entry_date
        labels.append(day[['ts_code', 'trade_date', 'forward_return']])
    return pd.DataFrame(periods), pd.concat(labels, ignore_index=True)


def backtest_calendar_month(factor_values, *, calendar, membership, market, price_basis_id,
                            group_boundary='lower', retain_holdings=True, sinks=None, on_complete=None):
    """Public calendar-month account; same accepted kernel, two independent fees.

    market is keyed trade_date/ts_code with price (adjusted mark), raw execution
    close/limits and explicit V17 states, or the shared bounded market reader.
    initial_cash=1, terminal liquidation attempt, 30bp/60bp one-way costs are
    frozen here. Streaming sinks are keyed by account then trades/stale_marks.
    """
    if not isinstance(price_basis_id, str) or not price_basis_id.strip():
        raise ValueError('explicit fixed price_basis_id required')
    if group_boundary not in {'lower', 'upper'}:
        raise ValueError('group_boundary must be lower or upper')
    calendar = _dates(calendar, name='calendar')
    windows, values, targets, coverage = calendar_month_targets(factor_values, calendar=calendar, membership=membership)
    if isinstance(market, pd.DataFrame):
        market = market.copy()
        market['trade_date'] = _dates(market.trade_date, name='market date')
        _index(pd.MultiIndex.from_arrays([market.trade_date, market.ts_code], names=['datetime', 'instrument']))
    accounts = {}
    for name, fee in [('base30bp', .003), ('stress60bp', .006)]:
        sink = (sinks or {}).get(name, {})
        account = simulate_account(calendar, market, targets, initial_cash=1., terminal=True, cost_rate=fee,
                                   retain_holdings=retain_holdings, ledger_sink=sink.get('trades'),
                                   mark_sink=sink.get('stale_marks'), valuation_policy=SUSPENSION_POLICY,
                                   price_basis_id=price_basis_id)
        account['performance'] = performance(account['daily_nav'])
        accounts[name] = account
        if on_complete is not None:
            on_complete(name, account)
    periods, labels = calendar_month_diagnostics(values, windows, market, price_basis_id=price_basis_id,
                                                group_boundary=group_boundary)
    summary = {}
    for key in ('pearson_ic', 'rank_ic'):
        available = periods[key].dropna()
        summary[key + '_mean'] = available.mean()
        sd = available.std(ddof=1)
        summary[key + '_ir'] = available.mean() / sd if sd > 0 else np.nan
        # Exact calendar slots are retained, including a fully missing signal
        # month. Terminal immature labels have no observation, never zero IC.
        summary[key + '_hac3'] = hac_mean(periods[key].to_numpy(float))
    return {'accounts': accounts, 'windows': windows, 'coverage': coverage,
            'monthly_ic': periods, 'monthly_labels': labels, 'ic_summary': summary,
            'price_basis_id': price_basis_id, 'group_boundary': group_boundary, 'account_simulation': True,
            'stress_comparison': 'same_signal_rules_dates_constraints_independent_fee_aware_quantities_not_same_unit_path',
            'tradable_net_alpha_evidence': False}


def performance(nav):
    """252 exchange sessions/year; sample SD; recovery from worst DD trough.

    Initial cash NAV=1 is included in high-water mark so entry cost is not lost.
    Recovery is sessions after worst trough until prior high is regained; when
    not regained report observed lower bound/right censor rather than252.
    """
    x, ret = nav.nav.to_numpy(float), nav.daily_return.to_numpy(float)
    if not len(x) or not np.isfinite(x).all() or not np.isfinite(ret).all() or (x <= 0).any():
        raise ValueError("incomplete_account_valuation")
    peak = np.maximum.accumulate(np.r_[1., x])[1:]
    dd = x/peak-1
    trough = int(np.argmin(dd))
    recover = np.flatnonzero(x[trough+1:] >= peak[trough])
    recovered = dd[trough] >= 0 or len(recover) > 0
    recovery = 0 if dd[trough] >= 0 else int(recover[0]+1) if len(recover) else None
    sd = np.std(ret, ddof=1) if len(ret) > 1 else np.nan
    sharpe = np.sqrt(252)*ret.mean()/sd if sd > 0 else np.nan
    return {"long_side_annual_return": float(np.prod(1+ret)**(252/len(ret))-1),
            "long_side_annual_volatility": float(sd*np.sqrt(252)),
            "long_side_sharpe": sharpe, "cost_adjusted_long_side_sharpe": sharpe,
            "long_side_max_drawdown": float(dd.min()), "long_side_recovery_days": recovery,
            "long_side_recovery_status": "RECOVERED" if recovered else "NOT_RECOVERED_BY_WINDOW_END",
            "long_side_recovery_lower_bound_days": None if recovered else len(x)-1-trough,
            "long_side_recovery_observation_end": str(nav.trade_date.iloc[-1].date()),
            "long_side_turnover_mean_daily": float(nav.half_L1_turnover.mean()),
            "trading_cogs_daily": float(nav.cost_weight.mean()),
            "drawdown_area_sessions": float(-dd.sum()),
            "metric_period": "daily", "annualization_factor": 252,
            "return_basis": "net_after_explicit_trading_costs"}



def hac_mean(slots):
    """Bartlett lag3, calendar slots kept; pair sums / n_observed**2.

    Equivalent sandwich intercept-only mean variance with missing scores zero
    in calendar slots, NOT compressing gaps or imputing missing observations.
    No finite-sample multiplier. Degenerate SE is unavailable inference.
    """
    x = np.asarray(slots, dtype=float)
    mask = np.isfinite(x)
    n = int(mask.sum())
    if not n:
        return {"n": 0, "mean": None, "se": None, "positive_p": None, "negative_p": None}
    mean = float(x[mask].mean())
    z = np.where(mask, x-mean, 0.)
    meat = float(z@z)
    for lag in range(1, 4):
        meat += 2*(1-lag/4)*float(z[lag:]@z[:-lag])
    se = math.sqrt(max(0., meat))/n
    return {"n": n, "mean": mean, "se": se if se > 0 else None,
            "positive_p": .5*math.erfc(mean/se/math.sqrt(2)) if se > 0 else None,
            "negative_p": .5*math.erfc(-mean/se/math.sqrt(2)) if se > 0 else None,
            "missing_slots": np.flatnonzero(~mask).tolist()}
