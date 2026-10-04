"""Small independent ledgers plus frozen pre-extraction account parity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from factor_factory.calendar_account import AccountBlocked, SUSPENSION_POLICY, simulate_account
from factor_factory.calendar_account_io import MonthlyMarket, WindowReader, digest
from factor_factory.calendar_month import (
    backtest_calendar_month, calendar_month_diagnostics, calendar_month_targets,
    calendar_month_windows, hac_mean, performance,
)
from factor_factory.primary_evaluator import validate_primary_evaluator_payload

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'tests/reference/calendar_account_v1'
ADAPTER = ROOT / 'skills/factor-forge-step4/scripts/calendar_month_adapter.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def market_rows(calendar, codes):
    return pd.DataFrame([{
        'trade_date': day, 'ts_code': code, 'price': 10., 'execution_close_raw': 10.,
        'execution_price_basis': 'unadjusted_close', 'price_basis_id': 'synthetic_fixed_snapshot',
        'constraint_complete': True, 'suspension_state': 'NOT_SUSPENDED', 'st_state': 'NOT_ST',
        'buy_allowed': True, 'sell_allowed': True, 'up_limit': 11., 'down_limit': 9.,
        'buy_execution_action': 'CHECK_UP_LIMIT_AT_EXECUTION__KEEP_CASH_ON_NO_FILL',
        'sell_execution_action': 'CHECK_DOWN_LIMIT_AT_EXECUTION__CARRY_ON_NO_FILL',
        'pretrade_buy_blocked': False, 'pretrade_sell_blocked': False,
    } for day in calendar for code in codes])


def kernel(cal, market, targets, fee=.003):
    return simulate_account(cal, market, targets, cost_rate=fee, valuation_policy=SUSPENSION_POLICY,
                            price_basis_id='synthetic_fixed_snapshot')


@pytest.mark.parametrize('fee', [.003, .006])
def test_hand_cash_fee_conservation_blocked_buy_never_reallocated_or_retried(fee):
    cal = pd.to_datetime(['2020-01-31', '2020-02-03', '2020-02-04', '2020-02-05'])
    market = market_rows(cal, ['A', 'B'])
    market.loc[market.trade_date.eq(cal[1]) & market.ts_code.eq('B'), 'execution_close_raw'] = 11.
    account = kernel(cal, market, {cal[1]: pd.Series({'A': .5, 'B': .5})}, fee)
    units = .5 / (1 + fee) / 10
    nav = account['daily_nav']
    assert nav.cash.iloc[1] == pytest.approx(.5)
    assert nav.holdings.iloc[1] == {'A': pytest.approx(units)}
    assert nav.nav.iloc[1] == pytest.approx(.5 + units * 10)
    assert nav.cash.iloc[-1] == pytest.approx(.5 + units * 10 * (1-fee))
    assert nav.cost.sum() == pytest.approx(2 * units * 10 * fee)
    assert nav.gross_shadow_nav.iloc[-1] == pytest.approx(.5 + units * 10 * (1+fee))
    assert account['trades'].side.tolist() == ['BUY', 'BUY', 'SELL']
    assert account['trades'].status.tolist() == ['FILLED', 'BLOCKED', 'FILLED']
    assert nav.cost.iloc[2] == 0
    assert account['terminal_state']['adjusted_price_units'] == {}
    assert np.allclose(nav.gross_shadow_nav - nav.nav, nav.cost.cumsum())


@pytest.mark.parametrize('event', ['suspension', 'down_limit', 'unknown', 'unpriced_buy'])
def test_old_kernel_exact_daily_holdings_cash_trades_fee_nav_parity(event):
    old = load(REF / 'account.py', 'frozen_account_' + event)
    cal = pd.to_datetime(['2020-01-31', '2020-02-03', '2020-02-04', '2020-02-05', '2020-02-06'])
    market = market_rows(cal, ['A', 'B'])
    mask = market.trade_date.eq(cal[2]) & market.ts_code.eq('A')
    if event == 'suspension':
        market.loc[mask, 'price'] = np.nan
        market.loc[mask, 'suspension_state'] = 'SUSPENSION_EVENT_PRESENT'
    elif event == 'down_limit':
        market.loc[mask, 'execution_close_raw'] = 9.
    elif event == 'unknown':
        market.loc[mask, 'constraint_complete'] = False
    else:
        market.loc[market.trade_date.eq(cal[1]) & market.ts_code.eq('B'), 'price'] = np.nan
    targets = {cal[1]: pd.Series({'A': .6, 'B': .4}), cal[2]: pd.Series(dtype=float)}
    for fee in (.003, .006):
        got = kernel(cal, market, targets, fee)
        expected = old.simulate_account(cal, market, targets, cost_rate=fee, valuation_policy=SUSPENSION_POLICY,
                                        price_basis_id='synthetic_fixed_snapshot')
        for key in ('daily_nav', 'trades', 'stale_marks'):
            assert_frame_equal(got[key], expected[key], check_exact=True)
        assert got['terminal_state'] == expected['terminal_state']
    trades = got['trades']
    if event != 'unpriced_buy':
        assert trades.loc[trades.trade_date.eq(cal[2]) & trades.ts_code.eq('A'), 'status'].item() == 'BLOCKED'
        assert trades.loc[trades.trade_date.eq(cal[3]) & trades.ts_code.eq('A'), 'status'].item() == 'FILLED'
    if event == 'suspension':
        assert got['daily_nav'].stale_position_count.iloc[2] == 1
        assert got['stale_marks'].iloc[0].status == 'CONFIRMED_SUSPENSION_CARRY_LAST_VALID'


@pytest.mark.parametrize('change', ['missing_mark', 'basis', 'corporate_action', 'delisted'])
def test_unresolved_held_valuation_blocks_instead_of_inventing_nav(change):
    cal = pd.bdate_range('2020-02-03', periods=3)
    market = market_rows(cal, ['A'])
    if change == 'missing_mark':
        market.loc[1, 'price'] = np.nan
    elif change == 'basis':
        market.loc[1, 'price_basis_id'] = 'other_snapshot'
    elif change == 'corporate_action':
        market['corporate_action_unresolved'] = False
        market.loc[1, 'corporate_action_unresolved'] = True
    else:
        market['listing_status'] = 'UNKNOWN'
        market.loc[1, 'listing_status'] = 'DELISTED'
    with pytest.raises(AccountBlocked):
        kernel(cal, market, {cal[0]: pd.Series({'A': 1.})})


def monthly_fixture():
    cal = pd.bdate_range('2020-01-27', '2020-04-06')
    windows = calendar_month_windows(cal)
    codes = [f'S{i:02}' for i in range(40)]
    members = pd.DataFrame([(t, c) for t in windows.signal_date for c in codes], columns=['trade_date', 'ts_code'])
    factor = pd.DataFrame([(e, c, float(i)) for e in windows.entry_date for i, c in enumerate(codes)],
                          columns=['trade_date', 'ts_code', 'factor_value'])
    market = market_rows(cal, codes)
    # Nonconstant prices and cross-sectional monthly returns make independent
    # monthly IC and daily account metrics estimable in the tiny fixture.
    offsets = market.trade_date.map({d: i for i, d in enumerate(cal)}).to_numpy()
    security = market.ts_code.str[1:].astype(int).to_numpy()
    market['price'] = 10. * (1 + (security % 9 - 4) * .0004 * offsets + .003 * np.sin(offsets))
    return cal, windows, members, factor, market


def test_calendar_targets_and_public_account_match_old_helpers_without_double_shift():
    cal, windows, members, factor, market = monthly_fixture()
    old = load(REF / 'calendar.py', 'frozen_month_helpers')
    old_account = load(REF / 'account.py', 'frozen_month_account')
    old_performance = load(REF / 'performance.py', 'frozen_performance')
    frozen_windows = old.calendar_windows(cal).drop(columns='proxy_end_date')
    assert_frame_equal(windows, frozen_windows)
    got = backtest_calendar_month(factor, calendar=cal, membership=members, market=market, price_basis_id='synthetic_fixed_snapshot')
    targets = {w.entry_date: old.upper_tail_targets(factor.loc[factor.trade_date.eq(w.entry_date)], 40)
               for w in windows.itertuples(index=False)}
    for name, fee in [('base30bp', .003), ('stress60bp', .006)]:
        expected = old_account.simulate_account(cal, market, targets, cost_rate=fee, valuation_policy=SUSPENSION_POLICY,
                                               price_basis_id='synthetic_fixed_snapshot')
        for key in ('daily_nav', 'trades', 'stale_marks'):
            assert_frame_equal(got['accounts'][name][key], expected[key], check_exact=True)
        assert got['accounts'][name]['performance'] == old_performance.performance(expected['daily_nav'])
    trades = got['accounts']['base30bp']['trades']
    assert trades.trade_date.iloc[0] == windows.entry_date.iloc[0] == pd.Timestamp('2020-02-03')
    base_units = got['accounts']['base30bp']['daily_nav'].loc[lambda x: x.trade_date.eq('2020-02-03'), 'holdings'].item()
    stress_units = got['accounts']['stress60bp']['daily_nav'].loc[lambda x: x.trade_date.eq('2020-02-03'), 'holdings'].item()
    assert all(stress_units[c] < base_units[c] for c in base_units)


def test_missing_signal_month_cash_does_not_compress_schedule_or_label_endpoint():
    cal, windows, members, factor, market = monthly_fixture()
    factor = factor.loc[~factor.trade_date.eq(windows.entry_date.iloc[1])]
    got = backtest_calendar_month(factor, calendar=cal, membership=members, market=market, price_basis_id='synthetic_fixed_snapshot')
    assert len(got['monthly_ic']) == 3
    assert got['monthly_ic'].n.tolist()[1:] == [0, 0]
    assert got['coverage'].scored.tolist() == [40, 0, 40]
    assert got['coverage'].reason.iloc[1] == 'insufficient_finite_scores'
    nav = got['accounts']['base30bp']['daily_nav'].set_index('trade_date')
    assert nav.loc['2020-03-02', 'holdings'] == {}
    row = got['monthly_labels'].loc[lambda x: x.ts_code.eq('S01')].iloc[0]
    px = market.loc[market.ts_code.eq('S01')].set_index('trade_date').price
    assert row.forward_return == pytest.approx(px.loc['2020-03-02']/px.loc['2020-02-03']-1)


def test_ties_missing_endpoint_and_immature_label_are_not_zero_filled():
    cal, windows, members, factor, market = monthly_fixture()
    factor['factor_value'] = 1.
    market.loc[market.trade_date.eq(windows.entry_date.iloc[1]) & market.ts_code.eq('S00'), 'price'] = np.nan
    _, values, targets, coverage = calendar_month_targets(factor, calendar=cal, membership=members)
    periods, labels = calendar_month_diagnostics(values, windows, market, price_basis_id='synthetic_fixed_snapshot')
    assert all(x.empty for x in targets.values())
    assert coverage.reason.tolist() == ['constant_signal'] * 3
    assert periods.group_3_selected_n.tolist() == [40] * 3
    assert periods.group_3_label_n.tolist() == [39, 39, 0]
    assert periods.group_1_return.isna().all() and periods.top_minus_bottom_label_spread.isna().all()
    assert labels.loc[labels.ts_code.eq('S00'), 'forward_return'].isna().all()
    assert periods.reason.iloc[-1] == 'immature_label'


def test_frozen_hac_slots_and_independent_missing_slot_sandwich():
    x = np.array([.1, np.nan, -.2, .4, np.nan, .3])
    old = load(REF / 'calendar.py', 'frozen_hac')
    got = hac_mean(x)
    assert got == old.hac_mean(x)
    ok = np.isfinite(x); mean = np.mean(x[ok]); residual = np.where(ok, x-mean, 0)
    weight = np.fromfunction(lambda i, j: np.maximum(1-np.abs(i-j)/4, 0), (6, 6))
    se = np.sqrt(residual @ weight @ residual) / 4
    assert got['se'] == pytest.approx(se)
    assert got['missing_slots'] == [1, 4]
    assert not np.isclose(got['se'], hac_mean(x[ok])['se'])


@pytest.mark.parametrize('kind', ['too_few', 'coverage', 'constant', 'tied_threshold'])
def test_full_pit_selection_gate_and_tie_inclusive_top_decile(kind):
    cal, windows, members, factor, _ = monthly_fixture()
    if kind == 'too_few':
        factor = factor.loc[factor.factor_value.lt(29)]
    elif kind == 'coverage':
        extra = members.copy(); extra.ts_code = 'X' + extra.ts_code
        members = pd.concat([members, extra, pd.DataFrame({'trade_date': windows.signal_date, 'ts_code': 'EXTRA'})])
    elif kind == 'constant':
        factor['factor_value'] = 3.
    else:
        factor.loc[factor.factor_value.ge(35), 'factor_value'] = 40.
    _, _, targets, cov = calendar_month_targets(factor, calendar=cal, membership=members)
    if kind == 'tied_threshold':
        assert cov.selected.tolist() == [5]*3
        assert all((w == .2).all() for w in targets.values())
    else:
        assert all(w.empty for w in targets.values())


@pytest.mark.parametrize('kind', ['missing_members', 'extra_symbol', 'signal_day', 'duplicate_factor', 'calendar_gap'])
def test_bad_keys_do_not_silently_change_monthly_account(kind):
    cal, windows, members, factor, _ = monthly_fixture()
    if kind == 'missing_members':
        members = members.loc[~members.trade_date.eq(windows.signal_date.iloc[1])]
    elif kind == 'extra_symbol':
        factor.loc[0, 'ts_code'] = 'NOT_MEMBER'
    elif kind == 'signal_day':
        factor.loc[0, 'trade_date'] = windows.signal_date.iloc[0]
    elif kind == 'duplicate_factor':
        factor = pd.concat([factor, factor.iloc[:1]])
    else:
        cal = cal[cal.month != 2]
    with pytest.raises(ValueError):
        calendar_month_targets(factor, calendar=cal, membership=members)


def prepared_fixture(tmp_path):
    cal, windows, members, factor, market = monthly_fixture()
    rid = 'IT_SYNTHETIC_MONTHLY'
    factor_path = tmp_path / 'runs' / rid / f'factor_values__{rid}.parquet'
    factor_path.parent.mkdir(parents=True)
    factor.to_parquet(factor_path, index=False)
    prepared = {'report_id': rid, 'scope': 'local_is_only', 'is_start': str(cal[0].date()),
                'is_end': str(cal[-1].date()), 'price_basis_id': 'synthetic_fixed_snapshot',
                'membership_semantics': 'explicit_pit_true_membership_flag', 'files': {}}
    frames = {'calendar': pd.DataFrame({'trade_date': cal}), 'membership': members.assign(is_member=True),
              'daily': market[['ts_code', 'trade_date', 'price']].rename(columns={'price': 'close_adj'}),
              'execution_prices': market[['ts_code', 'trade_date', 'execution_close_raw']],
              'constraints': market.drop(columns=['price', 'execution_close_raw', 'execution_price_basis'])}
    for role, frame in frames.items():
        path = tmp_path / (role + '.parquet')
        frame.to_parquet(path, index=False)
        prepared['files'][role] = {'path': str(path), 'sha256': digest(path), 'columns': {c: c for c in frame}}
    input_path = tmp_path / 'evaluation_inputs.json'
    input_path.write_text(json.dumps(prepared))
    manifest = tmp_path / 'runtime_manifest.json'
    manifest.write_text(json.dumps({'contract_version': 'factorforge_runtime_context_v2', 'report_id': rid,
                                   'factor_workspace': str(tmp_path), 'runs': {'factor_values_parquet': str(factor_path)}}))
    out = tmp_path / 'evaluations' / rid / 'calendar_month_account' / 'evaluation_payload.json'
    return SimpleNamespace(report_id=rid, factor_values=str(factor_path), output=str(out), manifest=str(manifest), prepared_inputs=str(input_path)), prepared


def test_step4_actual_subprocess_adapter_and_primary_result_contract(tmp_path, monkeypatch):
    args, prepared = prepared_fixture(tmp_path)
    step4 = load(ROOT / 'skills/factor-forge-step4/scripts/run_step4.py', 'monthly_step4_process')
    monkeypatch.setattr(step4, 'backend_runtime_python', lambda *a: sys.executable)
    cfg = step4.custom_backend_config_with_step4_factor_output(
        {'factor_values_source': 'step4_output', 'args': ['--prepared-inputs', args.prepared_inputs]},
        factor_parquet_path=Path(args.factor_values))
    rc, note = step4.run_backend_script(args.report_id, 'calendar_month_account', ADAPTER, Path(args.output), cfg,
                                       manifest_path_arg=Path(args.manifest))
    assert rc == 0, note
    payload = json.loads(Path(args.output).read_text())
    assert payload['status'] == 'success' and payload['accounts_completed'] == ['base30bp', 'stress60bp']
    plan = {'primary_backend': 'calendar_month_account', 'frequency': 'monthly', 'scope': 'local_is_only',
            'backends': [{'name': 'calendar_month_account', 'script_path': str(ADAPTER)}]}
    assert validate_primary_evaluator_payload(payload, plan) == []
    assert all(Path(p).is_file() for p in payload['artifacts'].values())
    assert payload['io_profile']['full_market_frame_loaded'] is False
    assert payload['bindings']['pin_changed_by_adapter'] is False
    assert 'gross_zero_cost_counterfactual_annual_return' not in payload['long_side_performance']
    assert payload['gross_shadow_performance']['return_basis'] == 'same_base30bp_units_fee_refund_idle_cash_shadow'
    assert Path(args.manifest).read_text() == json.dumps({'contract_version': 'factorforge_runtime_context_v2', 'report_id': args.report_id,
                                                       'factor_workspace': str(tmp_path), 'runs': {'factor_values_parquet': args.factor_values}})


@pytest.mark.parametrize('failure', ['hash', 'missing_membership', 'wrong_factor', 'existing_output'])
def test_adapter_preserves_failed_evidence_and_refuses_stale_input(tmp_path, failure):
    args, prepared = prepared_fixture(tmp_path)
    adapter = load(ADAPTER, 'monthly_adapter_failure_' + failure)
    if failure == 'hash':
        prepared['files']['daily']['sha256'] = '0'*64
    elif failure == 'missing_membership':
        prepared['membership_semantics'] = 'guessed'
    elif failure == 'wrong_factor':
        args.factor_values = str(tmp_path / 'another_study.parquet')
    else:
        Path(args.output).parent.mkdir(parents=True)
        Path(args.output).write_text('prior result')
    Path(args.prepared_inputs).write_text(json.dumps(prepared))
    with pytest.raises((ValueError, FileExistsError)):
        adapter.run(args)
    if failure in {'hash', 'missing_membership'}:
        payload = json.loads(Path(args.output).read_text())
        assert payload['status'] == 'failed' and payload['results_computed'] is False
        assert payload['accounts_completed'] == []
    elif failure == 'existing_output':
        assert Path(args.output).read_text() == 'prior result'


def test_reader_cache_preserves_suspension_only_row_and_input_date_encodings(tmp_path):
    args, prepared = prepared_fixture(tmp_path)
    daily = Path(prepared['files']['daily']['path'])
    frame = pd.read_parquet(daily)
    day = pd.Timestamp('2020-02-05')
    frame = frame.loc[~(frame.trade_date.eq(day) & frame.ts_code.eq('S39'))]
    frame.trade_date = frame.trade_date.dt.strftime('%Y%m%d').astype('int64')
    frame.to_parquet(daily, index=False)
    prepared['files']['daily']['sha256'] = digest(daily)
    reader = WindowReader(prepared['files'], start='2020-01-27', end='2020-04-06')
    market = MonthlyMarket(reader, symbols={'S39'})
    got = market.for_day(day, {'S39'})
    assert len(got) == 1 and pd.isna(got.price.iloc[0])
    assert got.constraint_complete.iloc[0]
    queries = reader.profile['queries']
    market.for_day(day + pd.Timedelta(days=1), {'S39'})
    assert reader.profile['queries'] == queries
    assert market.frame.trade_date.min().month == market.frame.trade_date.max().month == 2


def test_frozen_account_bytes_have_documented_origin():
    expected = 'b66ca8bbcc71835331daec6b7e834174408625cb406f17d619a1abe1865a7e0f'
    assert hashlib.sha256((REF / 'account.py').read_bytes()).hexdigest() == expected
    assert (ROOT / 'factor_factory/calendar_account.py').read_bytes() == (REF / 'account.py').read_bytes()


def test_terminal_blocked_sale_retains_position_and_does_not_invent_cash():
    cal = pd.bdate_range('2020-02-03', periods=3)
    market = market_rows(cal, ['A'])
    market.loc[2, 'execution_close_raw'] = 9.
    result = kernel(cal, market, {cal[0]: pd.Series({'A': 1.})})
    assert result['trades'].status.tolist() == ['FILLED', 'BLOCKED']
    assert result['terminal_state']['cash'] == pytest.approx(0.)
    assert result['daily_nav'].terminal_residual_weight.iloc[-1] == pytest.approx(1.)
    assert result['terminal_state']['adjusted_price_units']['A'] == pytest.approx(1/1.003/10)
    assert result['daily_nav'].cost.sum() == pytest.approx(.003/1.003)


def test_all_missing_signals_remain_cash_and_unknown_metrics(tmp_path):
    args, prepared = prepared_fixture(tmp_path)
    factor = pd.read_parquet(args.factor_values)
    factor['factor_value'] = np.nan
    factor.to_parquet(args.factor_values, index=False)
    adapter = load(ADAPTER, 'all_missing_adapter')
    assert adapter.run(args) == 0
    payload = json.loads(Path(args.output).read_text())
    assert payload['status'] == 'partial'
    assert payload['long_side_performance']['long_side_sharpe'] is None
    assert payload['ic_summary']['rank_ic_mean'] is None
    assert 'rank_ic_mean' in payload['missing_metrics']
    nav = pd.read_csv(payload['artifacts']['daily_nav'])
    assert (nav.nav == 1).all() and (nav.cash == 1).all()
    assert pd.read_csv(payload['artifacts']['trades']).empty


def test_mid_account_failure_preserves_partial_ledger_without_complete_nav(tmp_path):
    args, prepared = prepared_fixture(tmp_path)
    path = Path(prepared['files']['daily']['path'])
    frame = pd.read_parquet(path)
    frame.loc[frame.trade_date.eq('2020-02-04') & frame.ts_code.eq('S39'), 'close_adj'] = np.nan
    frame.to_parquet(path, index=False)
    prepared['files']['daily']['sha256'] = digest(path)
    Path(args.prepared_inputs).write_text(json.dumps(prepared))
    adapter = load(ADAPTER, 'partial_account_failure')
    with pytest.raises(AccountBlocked):
        adapter.run(args)
    payload = json.loads(Path(args.output).read_text())
    assert payload['status'] == 'failed' and payload['accounts_completed'] == []
    assert payload['results_computed'] is None
    assert payload['performance']['net_valuation_complete'] is False
    assert not pd.read_csv(payload['artifacts']['base30bp_trades']).empty
