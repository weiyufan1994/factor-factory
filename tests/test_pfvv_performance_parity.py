"""Same-input economics and bounded-state comparisons against frozen source bytes."""
import importlib.util
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pandas as pd
import pytest

from test_mszq_pfvv_monthly_evaluation_v1 import _frames
from test_mszq_pfvv_daily_lookup_store_v1 import _write_inputs, FakeEngine
from examples.mszq_intraday_momentum_pulse import pfvv_daily_lookup_store_v1 as store

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=ROOT/'examples/mszq_intraday_momentum_pulse'
REFERENCE=Path(__file__).parent/'reference/pfvv_frozen'


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


def engines():
    prior=list(sys.path)
    try:
        sys.path.insert(0,str(REFERENCE))
        reference=load_module('frozen_p4_engine',REFERENCE/'mszq_step4_portfolio_evaluator_candidate_v1.py')
        candidate=load_module('candidate_p4_engine',EXAMPLE/'local_is_execution_engine/mszq_step4_portfolio_evaluator_candidate_v1.py')
    finally:
        sys.path[:]=prior
    reference.__name__=candidate.__name__='same_frozen_economic_engine'
    return reference,candidate


def test_array_window_preserves_missing_days_new_tickers_and_exact_factors():
    old=load_module('frozen_p4_state',REFERENCE/'pfvv_source_baseline_partitioned_v1.py')
    new=load_module('candidate_p4_state',EXAMPLE/'pfvv_source_baseline_partitioned_v1.py')
    dates=pd.bdate_range('2016-01-04',periods=65)
    rng=np.random.default_rng(1985);frames={}
    for i,day in enumerate(dates):
        codes=[f'{x:06d}.SZ' for x in range(1,201 if i<17 else 205)]
        values=rng.normal(size=(len(codes),2));values[0,0]=np.nan if i==38 else values[0,0]
        frame=pd.DataFrame({'ts_code':codes,'trade_date':day.strftime('%Y%m%d'),'pf_daily':values[:,0],'vv_daily':values[:,1]})
        frames[day]=None if i==23 else frame.loc[~((frame.ts_code=='000002.SZ')&(i>30))]
    a=old.PFVVPartitionState(dates);b=new.PFVVPartitionState(dates)
    expected=pd.concat(old.stream_pfvv_prepared_daily_state(dates,frames.get,state=a),ignore_index=True)
    actual=pd.concat(new.stream_pfvv_prepared_daily_state(dates,frames.get,state=b),ignore_index=True)
    pd.testing.assert_frame_equal(expected,actual,check_exact=True)
    assert b.retained_daily_state_count()==a.retained_daily_state_count()<=2*20*204
    assert all(np.array_equal(list(a.pf_history[c]),list(b.pf_history[c]),equal_nan=True) for c in a.known_tickers)


@pytest.mark.parametrize('scenario',['ordinary','blocked_exit','delist_settlement','unvalued_delisting'])
def test_day_synchronized_accounts_keep_exact_independent_cash_and_trades(scenario):
    reference,candidate=engines()
    _,daily,execution,constraints,_,_=_frames()
    dates=pd.bdate_range('2016-01-05',periods=8).strftime('%Y-%m-%d').tolist();codes=['000001.SZ','000002.SZ']
    daily=daily.loc[daily.trade_date.isin(dates)&daily.ts_code.isin(codes)].copy()
    execution=execution.loc[execution.trade_date.isin(dates)&execution.ts_code.isin(codes)].copy()
    constraints=constraints.loc[constraints.trade_date.isin(dates)&constraints.ts_code.isin(codes)].copy()
    missing_day=dates[2] if scenario=='delist_settlement' else dates[3]
    daily.loc[(daily.trade_date==missing_day)&(daily.ts_code==codes[0]),'adj_factor']=np.nan
    if scenario=='blocked_exit':
        constraints.loc[(constraints.trade_date==dates[-2])&(constraints.ts_code==codes[0]),'pretrade_sell_blocked']=True
    if scenario.startswith('delist') or scenario=='unvalued_delisting':
        mask=(constraints.trade_date>=dates[3])&(constraints.ts_code==codes[0])
        constraints.loc[mask,'listing_status']='DELISTED'
        if scenario=='delist_settlement':constraints.loc[mask,'delist_cash_settlement_unadjusted']=7.
    exit_day=dates[-2] if scenario=='blocked_exit' else dates[-1]
    window=SimpleNamespace(status='MATURE',formation_date=pd.Timestamp('2016-01-04').date(),entry_date=pd.Timestamp(dates[0]).date(),exit_date=pd.Timestamp(exit_day).date())
    selection={'2016-01-04':pd.DataFrame({'ts_code':codes})}
    before=[reference._stock_day_lookup(x) for x in [daily,execution,constraints]]
    after=[candidate._stock_day_lookup(x) for x in [daily,execution,constraints]]
    expected=[reference._simulate([window],selection,*before,dates,cost_rate=cost) for cost in [.003,0.]]
    requests=[{'key':i,'selections':selection,'cost_rate':cost} for i,cost in enumerate([.003,0.])]
    actual=list(candidate._simulate_many([window],requests,*after,dates))
    for (_,nav,trades),(old_nav,old_trades) in zip(actual,expected):
        pd.testing.assert_frame_equal(nav,old_nav,check_exact=True)
        pd.testing.assert_frame_equal(trades,old_trades,check_exact=True)
    new_nav=candidate._attach_zero_cost_counterfactual(actual[0][1],actual[1][1])
    old_nav=reference._attach_zero_cost_counterfactual(expected[0][0],expected[1][0])
    assert json.dumps(candidate._nav_metrics(new_nav,actual[0][2]),sort_keys=True)==json.dumps(reference._nav_metrics(old_nav,expected[0][1]),sort_keys=True)
    assert set(after[1]._partition_build_counts).issubset({dates[0],dates[-2],dates[-1]})
    assert sum(after[0]._partition_build_counts.values())<=len(dates)
    if scenario=='ordinary':
        assert sum(before[1]._partition_build_counts.values())==16
        assert sum(after[1]._partition_build_counts.values())==2
    if scenario=='delist_settlement':
        assert actual[0][2].side.eq('DELIST_SETTLEMENT').any()
    if scenario=='unvalued_delisting':
        assert actual[0][1].nav.isna().any()


def test_all_22_monthly_accounts_match_frozen_nav_trades_metrics_and_ic():
    reference,candidate=engines()
    old=load_module('frozen_p4_monthly',REFERENCE/'pfvv_monthly_evaluation_v1.py')
    new=load_module('candidate_p4_monthly',EXAMPLE/'pfvv_monthly_evaluation_v1.py')
    factor,daily,execution,constraints,calendar,months=_frames()
    daily['close_unadjusted']*=1+pd.factorize(daily.trade_date)[0]*.001
    execution['vwap_unadjusted']*=1+pd.factorize(execution.trade_date)[0]*.0008
    args=dict(factor_values=factor,measurement_domain=factor[['ts_code','trade_date']],daily_prices=daily,
        execution_vwap=execution,normalized_constraints=constraints,calendar=calendar,complete_months=months)
    expected=old.evaluate_monthly_groups(**args,execution_engine=reference)
    actual=new.evaluate_monthly_groups(**args,execution_engine=candidate)
    for name in ['monthly_ic','diagnostic_spread']:pd.testing.assert_frame_equal(actual[name],expected[name],check_exact=True)
    for key in ['G%02d'%i for i in range(1,11)]+['benchmark']:
        a=actual['benchmark'] if key=='benchmark' else actual['group_accounts'][key]
        b=expected['benchmark'] if key=='benchmark' else expected['group_accounts'][key]
        for name in ['daily_nav','trades','gross_trades']:pd.testing.assert_frame_equal(a[name],b[name],check_exact=True)
        assert json.dumps(a['performance'],sort_keys=True)==json.dumps(b['performance'],sort_keys=True)


def test_input_store_reuses_verified_bytes_and_rejects_artifact_corruption(tmp_path,monkeypatch):
    monkeypatch.delattr(hashlib,'file_digest',raising=False)
    dates,paths=_write_inputs(tmp_path);kwargs=dict(**paths,calendar=dates,execution_engine=FakeEngine(),cache_root=tmp_path/'cache')
    first=store.cached_pfvv_daily_lookup_store(**kwargs);assert first['reuse']['status']=='miss'
    original=store.build_pfvv_daily_lookup_store
    monkeypatch.setattr(store,'build_pfvv_daily_lookup_store',lambda **kw: pytest.fail('same-identity store rebuilt'))
    second=store.cached_pfvv_daily_lookup_store(**kwargs);assert second['reuse']['status']=='hit'
    pd.testing.assert_frame_equal(first['month_end_factor_values'],second['month_end_factor_values'])
    database=Path(second['sqlite_path']);database.chmod(0o644);database.write_bytes(database.read_bytes()+b'tampered')
    with pytest.raises(store.DailyLookupStoreError,match='artifact_hash_mismatch'):store.cached_pfvv_daily_lookup_store(**kwargs)


def test_input_store_snapshot_survives_source_a_b_a_and_changed_inputs_get_new_identity(tmp_path,monkeypatch):
    dates,paths=_write_inputs(tmp_path);source=paths['daily_prices_path'];a=source.read_bytes()
    changed=pd.read_parquet(source);changed['close_unadjusted']=999.;alternate=tmp_path/'b.parquet';changed.to_parquet(alternate,index=False);b=alternate.read_bytes()
    original=store.build_pfvv_daily_lookup_store
    def interleave(**kwargs):
        source.write_bytes(b)
        try:return original(**kwargs)
        finally:source.write_bytes(a)
    monkeypatch.setattr(store,'build_pfvv_daily_lookup_store',interleave)
    kwargs=dict(**paths,calendar=dates,execution_engine=FakeEngine(),cache_root=tmp_path/'cache')
    first=store.cached_pfvv_daily_lookup_store(**kwargs)
    assert first['lookups']['daily']._date_frame(dates[0]).close_unadjusted.tolist()==[10.,11.]
    source.write_bytes(b);monkeypatch.setattr(store,'build_pfvv_daily_lookup_store',original)
    second=store.cached_pfvv_daily_lookup_store(**kwargs)
    assert first['reuse']['identity_sha256']!=second['reuse']['identity_sha256']
    assert second['lookups']['daily']._date_frame(dates[0]).close_unadjusted.eq(999.).all()
