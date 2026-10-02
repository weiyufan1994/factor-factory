"""Independent tiny oracles for the shared public boundary and statistics."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_factory.research_api import (
    build_forward_returns, evaluate_factor, factor_coverage, normalize_factor_frame,
)
from factor_factory.research_statistics import newey_west_mean


def frame(values, dates=None, codes=None, name='factor_value'):
    return pd.DataFrame({'ts_code': codes or list('ABCD')[:len(values)],
                         'trade_date': dates or ['20200102'] * len(values), name: values})


def test_normalize_retains_nan_zero_and_rejects_ambiguity_without_mutating():
    source = frame([np.nan, 0., 2.])
    original = source.copy(deep=True)
    out = normalize_factor_frame(source)
    assert out.index.names == ['datetime', 'instrument']
    assert out.factor_value.dtype == np.dtype('float64')
    assert np.isnan(out.factor_value.iloc[0]) and out.factor_value.iloc[1] == 0.
    pd.testing.assert_frame_equal(source, original)
    pd.testing.assert_frame_equal(out, normalize_factor_frame(out))
    with pytest.raises(ValueError, match='unexpected columns'):
        normalize_factor_frame(source.assign(audit=[1., 2., 3.]))


@pytest.mark.parametrize('edit,error', [
    (lambda f: f.assign(factor_value=['1','2','3']), TypeError),
    (lambda f: f.assign(factor_value=[True,False,True]), TypeError),
    (lambda f: f.assign(factor_value=[1.,np.inf,3.]), ValueError),
    (lambda f: f.assign(factor_value=[1+2j,2j,3j]), TypeError),
    (lambda f: f.assign(trade_date=['20200230']*3), ValueError),
    (lambda f: f.assign(trade_date=['01/02/2020']*3), ValueError),
    (lambda f: f.assign(trade_date=[20200102.0]*3), ValueError),
    (lambda f: f.assign(trade_date=pd.to_datetime(['2020-01-02 12:00']*3)), ValueError),
    (lambda f: f.assign(ts_code=['A',None,'C']), ValueError),
    (lambda f: f.assign(ts_code=['A',' A','C']), ValueError),
    (lambda f: pd.concat([f,f.iloc[:1]]), ValueError),
    (lambda f: f.rename(columns={'factor_value':'signal'}), ValueError),
])
def test_bad_factor_inputs_raise_at_public_boundary(edit, error):
    with pytest.raises(error):
        normalize_factor_frame(edit(frame([1.,2.,3.])))


def test_coverage_uses_external_keys_and_keeps_missing_rows_separate():
    source = frame([0., np.nan], codes=['A','B'])
    expected = pd.MultiIndex.from_product([pd.to_datetime(['2020-01-02']), ['A','B','C','D']], names=['datetime','instrument'])
    observed = factor_coverage(source)
    assert observed['scope'] == 'observed' and observed['expected_valid_ratio'] is None
    assert observed['completeness_verified'] is False
    audited = factor_coverage(source, expected_index=expected)
    assert audited['valid_rows'] == 1 and audited['nan_rows'] == 1
    assert audited['missing_rows'] == 2 and audited['expected_valid_ratio'] == .25
    assert audited['observed_valid_ratio'] == .5


def test_returns_use_exact_calendar_endpoints_never_next_observed_quote():
    prices = frame([10.,12.,15.], ['20200102','20200106','20200107'], ['A']*3, name='close')
    cal = ['20200102','20200103','20200106','20200107']
    labels = build_forward_returns(prices, calendar=cal, entry_offset=0)
    assert np.isnan(labels.forward_return.iloc[0])  # Jan3 is missing, Jan6 is not t+1.
    assert labels.forward_return.iloc[1] == pytest.approx(.25)
    delayed = build_forward_returns(prices, calendar=cal)
    assert np.isnan(delayed.forward_return.iloc[0])
    with pytest.raises(ValueError, match='sorted and unique'):
        build_forward_returns(prices, calendar=list(reversed(cal)))


def test_ic_positive_negative_constant_and_independent_spearman_ties():
    values = frame([1.,2.,3.,4.])
    labels = frame([.01,.02,.03,.04], name='forward_return')
    positive = evaluate_factor(values, labels)
    negative = evaluate_factor(values.assign(factor_value=[-1.,-2.,-3.,-4.]), labels)
    constant = evaluate_factor(values.assign(factor_value=0.), labels)
    assert positive['metrics']['rank_ic_mean']['value'] == pytest.approx(1.)
    assert negative['metrics']['rank_ic_mean']['value'] == pytest.approx(-1.)
    assert constant['periods'][0]['rank_ic'] is None
    assert constant['periods'][0]['reason'] == 'constant_signal'
    assert positive['metrics']['rank_ic_ir']['value'] is None
    assert positive['metrics']['rank_ic_ir']['reason'] == 'insufficient_observations'
    tied = evaluate_factor(values.assign(factor_value=[1.,1.,2.,2.]), labels)
    assert tied['periods'][0]['rank_ic'] == pytest.approx(2/np.sqrt(5))
    json.dumps(constant, allow_nan=False)


def test_fmb_known_coefficients_hac_and_rank_deficient_control():
    rows = []
    for date, slope in [('20200102',.01),('20200103',.02),('20200106',.03)]:
        for code, x, z in [('A',-1.,1.),('B',0.,0.),('C',1.,0.),('D',2.,1.)]:
            rows.append((date,code,x,.05 + slope*x + .04*z,z))
    data = pd.DataFrame(rows, columns=['trade_date','ts_code','factor_value','forward_return','control'])
    factor = data[['ts_code','trade_date','factor_value']]
    labels = data[['ts_code','trade_date','forward_return']]
    controls = data[['ts_code','trade_date','control']]
    result = evaluate_factor(factor, labels, analysis='fama_macbeth', controls=controls)
    assert [p['lambda'] for p in result['periods']] == pytest.approx([.01,.02,.03])
    metrics = result['metrics']
    assert metrics['lambda_mean']['value'] == pytest.approx(.02)
    assert metrics['lambda_standard_error']['value'] == pytest.approx(np.sqrt(2)*.01/3)
    assert metrics['lambda_tstat']['value'] == pytest.approx(3*np.sqrt(2))
    assert metrics['lambda_pvalue_normal']['value'] == pytest.approx(0.0000220904969986)
    broken = evaluate_factor(factor, labels, analysis='fama_macbeth', controls=controls.assign(control=data.factor_value))
    assert broken['metrics']['lambda_tstat']['value'] is None
    assert all(p['reason'] == 'rank_deficient' for p in broken['periods'])


def test_hac_oracle_with_nonzero_lag_covariance():
    # Slopes 1,2,3,4: gamma0=1.25; gamma1=.3125. Bartlett weight=.5;
    # Var(mean)=(1.25+.3125)/4=.390625, SE=.625, t=4.
    result = newey_west_mean([1.,2.,3.,4.], 1)
    assert result['standard_error'] == pytest.approx(.625)
    assert result['tstat'] == pytest.approx(4.)


def test_event_mean_does_not_treat_signal_as_weight_or_annualize():
    values = frame([0.,20.,-5.], dates=['20200102','20200102','20200203'])
    labels = frame([.1,.3,-.1], dates=['20200102','20200102','20200203'], name='forward_return')
    result = evaluate_factor(values, labels, analysis='event_study')
    assert result['metrics']['event_return_mean']['value'] == pytest.approx(.1)
    assert result['metrics']['date_mean_return_mean']['value'] == pytest.approx(.05)
    assert result['account_simulation'] is False
    assert all('annual' not in name for name in result['metrics'])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('stage', ['step3','step4'])
def test_stage_entry_rejects_duplicate_and_infinite_factor_values(stage):
    root = Path(__file__).resolve().parents[1]
    name = 'run_step3b.py' if stage == 'step3' else 'run_step4.py'
    spec = importlib.util.spec_from_file_location('strict_' + stage, root/'skills'/('factor-forge-'+stage)/'scripts'/name)
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    source = frame([1.,2.])
    for bad in [pd.concat([source, source.iloc[:1]]), source.assign(factor_value=np.inf)]:
        module = SimpleNamespace(compute_factor=lambda daily_df, minute_df=None: bad)
        with pytest.raises(ValueError):
            runner.compute_factor_with_contract(module, source, None)


def test_signal_column_never_uses_trailing_audit_column():
    from factor_factory.data_access.step4 import infer_signal_column
    assert infer_signal_column(frame([1.,2.]).assign(warmup=False)) == 'factor_value'
    with pytest.raises(KeyError):
        infer_signal_column(frame([1.,2.]).rename(columns={'factor_value':'audit'}))


def test_class_only_source_works_through_actual_codegen_sample_and_fixture(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('FACTORFORGE_ROOT', str(tmp_path/'workspace'))
    def load(name):
        spec = importlib.util.spec_from_file_location(name + '_class_generator', root/'skills/factor-forge-step3/scripts'/f'{name}.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module
    runner, validator = load('run_step3b'), load('validate_step3b')
    source = '''from factor_factory.factors import PriceVolumeFactor
class Spread(PriceVolumeFactor):
    name = 'spread'
    input_columns = {'daily_df': ('ts_code','trade_date','open','close')}
    def compute(self, inputs):
        daily = inputs['daily_df']
        return daily[['ts_code','trade_date']].assign(factor_value=daily.close-daily.open)
FACTOR = Spread()
'''
    _plan, generated, _, _ = runner.build_direct_code_artifacts('CLASS_ONLY', {}, {
        'factor_id':'spread', 'implementation_contract': {'source_code':source}}, {})
    assert generated == source and '_factorforge_user_compute_factor' not in generated
    path = tmp_path/'factor.py'; path.write_text(generated)
    daily = frame([1.,2.]).drop(columns='factor_value').assign(open=[1.,2.],close=[3.,5.])
    input_path = tmp_path/'daily.parquet'; daily.to_parquet(input_path, index=False)
    result = runner.generate_first_run_factor_values('CLASS_ONLY','spread',path,
        {'input_mode':'daily_only','daily_df_parquet':str(input_path)}, {},csv_output_policy='no_csv')
    produced = tmp_path/'workspace/runs/CLASS_ONLY/step3b_sample_factor_values__CLASS_ONLY.parquet'
    assert pd.read_parquet(produced).factor_value.tolist() == [2.,3.]
    validator.run_direct_code_fixture_smoke(path, {'columns':['ts_code','trade_date','factor_value']})
    for fake in ["# FACTOR = Fake()\ntext = 'def compute_factor()'", "def make():\n    FACTOR = object()"]:
        with pytest.raises(SystemExit, match='module-level FACTOR'):
            runner.build_direct_code_artifacts('BAD', {}, {'implementation_contract':{'source_code':fake}}, {})


def test_stage_price_label_exact_endpoints_and_pct_chg_calendar_gap():
    from factor_factory.data_access.step4 import build_forward_return_frame
    prices = frame([10.,12.,15.], ['20200102','20200106','20200107'], ['A']*3, name='close')
    prices['pct_chg'] = [1.,20.,25.]
    calendar = ['20200102','20200103','20200106','20200107']
    labels = build_forward_return_frame(prices, return_col=None, entry_offset=2, exit_offset=3,
                                        calendar_dates=calendar, include_label_path=True)
    row = labels.iloc[0]
    assert row.future_return_1d == pytest.approx(.25)
    assert row.label_start_price == 12. and row.label_end_price == 15.
    exact_pct = build_forward_return_frame(prices, calendar_dates=calendar)
    assert np.isnan(exact_pct.future_return_1d.iloc[0])
    assert exact_pct.future_return_1d.iloc[1] == pytest.approx(.25)
    assert exact_pct.attrs['label_timing']['calendar_alignment'] == 'independent_calendar'


def test_verifier_uses_same_statistics_but_keeps_formal_rejection():
    from factor_factory.metric_verifier import _fama_macbeth, _newey_west_tstat
    data = pd.DataFrame([(d, x, .2+x*b) for d,b in [('a',1.),('b',2.),('c',3.),('d',4.)]
                         for x in [-1.,0.,1.,2.]], columns=['date','signal','return'])
    mean, statistic, n = _fama_macbeth(data,date_col='date',signal_col='signal',return_col='return',controls=[],lags=1)
    assert (mean,statistic,n) == pytest.approx((2.5,4.,4))
    assert _newey_west_tstat(np.array([1.,2.,3.,4.]),1) == pytest.approx(4.)
    with pytest.raises(ValueError, match='RANK_DEFICIENT'):
        _fama_macbeth(data.assign(z=data.signal),date_col='date',signal_col='signal',return_col='return',controls=['z'],lags=0)


def test_step5_retains_units_n_and_reason_and_rejects_nonfinite_metrics():
    from skills.factor_forge_step5.modules.evaluator import _extract_key_metrics, _payload_shape_errors
    public = evaluate_factor(frame([1.,1.,1.]),frame([.1,.2,.3],name='forward_return'))
    assert _extract_key_metrics({'research_metrics':public},{})['research_metrics'] == public
    assert not _payload_shape_errors({'research_metrics':public})
    public['metrics']['rank_ic_mean']['value'] = float('inf')
    assert _payload_shape_errors({'research_metrics':public})


def test_constant_ols_slopes_do_not_become_roundoff_significance():
    rows = [(day, str(x), float(x), intercept + .01*x)
            for day, intercept in zip(['20200102','20200103','20200106','20200107'],[0.,.05,.1,.2])
            for x in [1,2,3,4]]
    data = pd.DataFrame(rows, columns=['trade_date','ts_code','factor_value','forward_return'])
    result = evaluate_factor(data[['ts_code','trade_date','factor_value']],
                             data[['ts_code','trade_date','forward_return']],analysis='fama_macbeth')
    assert result['metrics']['lambda_mean']['value'] == pytest.approx(.01)
    assert result['metrics']['lambda_tstat']['value'] is None
    assert result['metrics']['lambda_tstat']['reason'] == 'zero_variation_at_float_precision'
    for scale in [1., 1e-20, 1e-200, 1e200]:
        # Same nonzero variation and t statistic in any valid unit scale.
        stats = newey_west_mean(np.array([1.,2.,3.,4.])*scale, 1)
        assert stats['tstat'] == pytest.approx(4.)
        assert stats['standard_error']/scale == pytest.approx(.625)


@pytest.mark.parametrize('stage', ['step3','step4'])
def test_class_auxiliary_role_reaches_shared_stage_execution(stage):
    from examples.manual_interface_replay.factor_definitions import PointInTimeEarningsYield
    root = Path(__file__).resolve().parents[1]
    name = 'run_step3b.py' if stage == 'step3' else 'run_step4.py'
    spec = importlib.util.spec_from_file_location('aux_' + stage, root/'skills'/('factor-forge-'+stage)/'scripts'/name)
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    fundamentals = frame([1.,2.]).drop(columns='factor_value').assign(earnings_ttm_cny=[10.,-10.],market_cap_cny=[100.,100.])
    result = runner.compute_factor_with_contract(PointInTimeEarningsYield(), pd.DataFrame(), None,
        additional_inputs={'fundamentals':fundamentals})
    assert result.factor_value.tolist() == [.1,-.1]
