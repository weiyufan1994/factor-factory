"""Explicit monthly signal diagnostics using the existing statistical kernels.

The C11 profile is opt-in, not a default control model. Inputs are supplied by
the caller; this module never constructs factors, labels, accounts or data.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from factor_factory.calendar_month import hac_mean
from factor_factory.research_api import _dates, _frame, _index, _numeric
from factor_factory.research_statistics import fama_macbeth_periods, partial_rank_ic_periods

RAW_CONTROL_NAMES = ('size_raw', 'value_raw', 'volatility_raw', 'activity_raw',
                     'low_price_raw', 'short_reversal_raw', 'momentum_raw')
C11_NAMES = ('size', 'size_square', 'value', 'volatility', 'short_reversal',
             'momentum', 'activity', 'low_price', 'activity_square',
             'volatility_square', 'activity_volatility_interaction')
C11_PROFILE = 'c11_rank_quantile_v1'


def _panel(inputs, *, expected_index, calendar_slots):
    slots = _dates(calendar_slots, name='monthly entry slots')
    if slots.empty or slots.has_duplicates or not slots.is_monotonic_increasing:
        raise ValueError('monthly slots must be nonempty, sorted and unique')
    if len(slots) > 1 and not (np.diff(slots.to_period('M').asi8) == 1).all():
        raise ValueError('monthly slots must retain every calendar month exactly once')
    expected = _index(expected_index).sort_values()
    if expected.empty or not expected.get_level_values('datetime').isin(slots).all():
        raise ValueError('expected membership keys must use declared monthly entry slots')
    panel = pd.DataFrame(index=expected)
    audit = pd.DataFrame(index=expected)
    for name, (frame, columns) in inputs.items():
        data = _frame(frame, list(columns), allow_empty=True)
        if len(data.index.difference(expected)):
            raise ValueError(name + ': keys outside expected membership')
        panel = panel.join(data, how='left', validate='one_to_one')
        audit[name + '_present'] = expected.isin(data.index)
        audit[name + '_complete'] = data.reindex(expected).notna().all(axis=1)
    if (panel.forward_return.dropna() < -1).any():
        raise ValueError('simple forward returns cannot be below -1')
    audit['complete_case'] = panel.notna().all(axis=1)
    return panel, audit, slots


def calendar_slot_hac3(values):
    """Existing missing-slot Bartlett HAC3 plus explicit normal intervals.

    The mean uses observed slots. Missing centered score contributions remain
    zero in their original slots; missing statistics are never zero observations.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or np.isinf(x).any():
        raise ValueError('HAC slots must be one dimensional and finite or missing')
    result = dict(hac_mean(x))
    result.update(slots=len(x), missing_slots=np.flatnonzero(~np.isfinite(x)).tolist(),
                  ci95_lower=None, ci95_upper=None, lower_995_one_sided=None,
                  tstat=None, reason=None)
    mean, se = result['mean'], result['se']
    if mean is None:
        result['reason'] = 'no_estimable_periods'
    elif not math.isfinite(mean) or (se is not None and not math.isfinite(se)):
        result.update(mean=mean if math.isfinite(mean) else None, se=None,
                      positive_p=None, negative_p=None, reason='numeric_overflow')
    elif se is None or se <= 0:
        result['reason'] = 'nonpositive_standard_error'
    elif not all(math.isfinite(v) for v in (mean, se, mean / se)):
        result.update(se=None, positive_p=None, negative_p=None, reason='numeric_overflow')
    else:
        z95, z995 = NormalDist().inv_cdf(.975), NormalDist().inv_cdf(.995)
        limits = (mean-z95*se, mean+z95*se, mean-z995*se)
        if not all(math.isfinite(v) for v in limits):
            result.update(se=None, positive_p=None, negative_p=None, reason='numeric_overflow')
        else:
            result.update(ci95_lower=limits[0], ci95_upper=limits[1],
                          lower_995_one_sided=limits[2], tstat=mean/se)
    return result


def c11_controls(complete_raw):
    """Transform finite raw7 on the FINAL complete-case cross section only.

    This pure transformation does not choose support. Its caller must intersect
    signal, label and all raw7 first. Average-tie quantile is (rank-.5)/N.
    """
    if set(complete_raw.columns) != set(RAW_CONTROL_NAMES) or complete_raw.columns.has_duplicates:
        raise ValueError('C11 requires exactly the seven explicitly named raw columns')
    numeric = pd.DataFrame({c: _numeric(complete_raw[c], c) for c in RAW_CONTROL_NAMES}, index=complete_raw.index)
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError('C11 transformation requires finite complete cases')
    u = (numeric.rank(method='average') - .5) / len(numeric)
    v = pd.DataFrame(index=complete_raw.index)
    v['size'], v['size_square'] = u.size_raw, (u.size_raw-.5)**2
    v['value'], v['volatility'] = -u.value_raw, u.volatility_raw
    v['short_reversal'], v['momentum'] = -u.short_reversal_raw, u.momentum_raw
    v['activity'], v['low_price'] = u.activity_raw, u.low_price_raw
    v['activity_square'] = (u.activity_raw-.5)**2
    v['volatility_square'] = (u.volatility_raw-.5)**2
    v['activity_volatility_interaction'] = (u.activity_raw-.5)*(u.volatility_raw-.5)
    return v.loc[:, list(C11_NAMES)]


def evaluate_c11_monthly(factor_values, forward_returns, raw_controls, *,
                         expected_index, calendar_slots):
    """Opt-in frozen C11 profile; partial Rank IC and rank-quantile FMB.

    Reuses partial_rank_ic_periods and fama_macbeth_periods, with N >= 100.
    FMB uses raw simple returns, an intercept and rcond=1e-10. Partial IC uses
    the shared scaled-SVD projection and never re-ranks its residuals.
    """
    panel, support, slots = _panel({
        'factor': (factor_values, ['factor_value']),
        'label': (forward_returns, ['forward_return']),
        'controls': (raw_controls, RAW_CONTROL_NAMES),
    }, expected_index=expected_index, calendar_slots=calendar_slots)
    periods = []
    dates = panel.index.get_level_values('datetime')
    for day in slots:
        group = panel.loc[dates == day]
        clean = group.dropna()
        n = len(clean)
        row = {'date': day.strftime('%Y-%m-%d'), 'input_n': len(group), 'n': n,
               'excluded_n': len(group)-n, 'partial_rank_ic': None,
               'same_support_rank_ic': None, 'same_support_pearson_ic': None,
               'lambda': None, 'partial_reason': 'cross_section_insufficient',
               'fmb_reason': 'cross_section_insufficient', 'control_design_rank': None}
        if n:
            control = c11_controls(clean.loc[:, list(RAW_CONTROL_NAMES)])
            work = clean[['factor_value', 'forward_return']].join(control).reset_index(drop=True)
            work['date'] = row['date']
            partial = partial_rank_ic_periods(work, date_col='date', signal_col='factor_value',
                return_col='forward_return', controls=list(C11_NAMES), min_observations=100)[0]
            work['signal_quantile'] = (work.factor_value.rank(method='average')-.5)/n
            fmb = fama_macbeth_periods(work, date_col='date', signal_col='signal_quantile',
                return_col='forward_return', controls=list(C11_NAMES), min_observations=100, rcond=1e-10)[0]
            row.update({k: partial[k] for k in ('partial_rank_ic', 'same_support_rank_ic', 'same_support_pearson_ic')})
            row.update(partial_reason=partial['reason'], control_design_rank=partial['design_rank'],
                       fmb_reason=fmb['reason'], **{'lambda': fmb['lambda']})
        periods.append(row)
    return {
        'control_profile': C11_PROFILE, 'account_simulation': False,
        'tradable_net_alpha_evidence': False, 'periods': periods,
        'support': support.reset_index(),
        'summary': {key: calendar_slot_hac3([r[key] for r in periods])
                    for key in ('partial_rank_ic', 'same_support_rank_ic', 'lambda')},
        'method': {'raw_controls': list(RAW_CONTROL_NAMES), 'controls': list(C11_NAMES),
                   'support': 'H=complete(signal,raw_simple_return,raw7); rank only inside H',
                   'rank_quantile': '(average_rank-.5)/N', 'min_observations': 100,
                   'partial': 'Corr(M_Z rank(signal),M_Z rank(return)); Z=[1,C11]; no residual rerank',
                   'partial_tolerance': 'shared scaled-SVD: eps*max(N,12)',
                   'fmb': 'raw_simple_return ~ 1 + rank_quantile(signal) + C11',
                   'fmb_rcond': 1e-10,
                   'hac': 'existing Bartlett lag3 observed-score sandwich; original calendar slots'},
    }


def paired_monthly_rank_ic(reference, alternative, forward_returns, *, expected_index, calendar_slots):
    """IC(reference)-IC(alternative), ranked on their COMMON finite H with y.

    N >= 30, average ties; HAC3 is applied directly to the paired difference.
    This is a signal diagnostic, not an equivalence test or portfolio claim.
    """
    other = _frame(alternative, ['factor_value'], allow_empty=True).rename(columns={'factor_value': 'alternative'})
    panel, support, slots = _panel({
        'reference': (reference, ['factor_value']), 'alternative': (other, ['alternative']),
        'label': (forward_returns, ['forward_return']),
    }, expected_index=expected_index, calendar_slots=calendar_slots)
    periods = []
    dates = panel.index.get_level_values('datetime')
    for day in slots:
        group = panel.loc[dates == day]
        clean = group.dropna()
        row = {'date': day.strftime('%Y-%m-%d'), 'input_n': len(group), 'n': len(clean),
               'reference_rank_ic': None, 'alternative_rank_ic': None, 'delta': None, 'reason': None}
        if len(clean) < 30:
            row['reason'] = 'cross_section_insufficient'
        elif any(clean[c].nunique() < 2 for c in clean):
            row['reason'] = 'constant_signal_or_return'
        else:
            ranks = clean.rank(method='average')
            a = float(ranks.factor_value.corr(ranks.forward_return))
            b = float(ranks.alternative.corr(ranks.forward_return))
            row.update(reference_rank_ic=a, alternative_rank_ic=b, delta=a-b)
        periods.append(row)
    return {'analysis': 'paired_common_support_rank_ic', 'account_simulation': False,
            'tradable_net_alpha_evidence': False, 'periods': periods, 'support': support.reset_index(),
            'delta_hac3': calendar_slot_hac3([r['delta'] for r in periods]),
            'method': 'H=finite(reference,alternative,y); N>=30; average ranks in H; Delta=IC(reference)-IC(alternative); HAC3 on Delta slots; no equivalence conclusion'}
