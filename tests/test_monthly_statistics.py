"""Offline support, statistical-oracle and real consumer-entry checks."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from factor_factory.calendar_account_io import digest
from factor_factory.calendar_month import calendar_month_windows, hac_mean
from factor_factory.monthly_statistics import (
    C11_NAMES, C11_PROFILE, RAW_CONTROL_NAMES, c11_controls,
    calendar_slot_hac3, evaluate_c11_monthly, paired_monthly_rank_ic,
)
from factor_factory.research_statistics import fama_macbeth_periods, newey_west_mean

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'scripts/evaluate_monthly_diagnostics.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def panel(n=120, months=5):
    rng = np.random.default_rng(853)
    slots = pd.date_range('2020-02-01', periods=months, freq='MS')
    index = pd.MultiIndex.from_product([slots, [f'S{i:04}' for i in range(n)]], names=['datetime', 'instrument'])
    factor = pd.DataFrame({'factor_value': rng.integers(0, 90, len(index)).astype(float)}, index=index)
    labels = pd.DataFrame({'forward_return': rng.normal(0, .03, len(index))}, index=index)
    raw = pd.DataFrame({k: rng.integers(0, 100, len(index)).astype(float) for k in RAW_CONTROL_NAMES}, index=index)
    return factor, labels, raw, index, slots


def evaluate(f, y, c, index, slots):
    return evaluate_c11_monthly(f, y, c, expected_index=index, calendar_slots=slots)


def test_c11_transform_hand_ties_signs_squares_and_interaction():
    raw = pd.DataFrame({k: [1., 1., 3., 4.] for k in RAW_CONTROL_NAMES})
    got = c11_controls(raw)
    u = np.array([.25, .25, .625, .875])
    assert list(got) == list(C11_NAMES)
    for col in ('size', 'volatility', 'momentum', 'activity', 'low_price'):
        np.testing.assert_array_equal(got[col], u)
    for col in ('value', 'short_reversal'):
        np.testing.assert_array_equal(got[col], -u)
    for col in ('size_square', 'activity_square', 'volatility_square', 'activity_volatility_interaction'):
        np.testing.assert_array_equal(got[col], (u-.5)**2)


def test_final_support_before_ranking_frozen_design_and_independent_projection():
    f, y, raw, idx, slots = panel(months=1)
    # Opposite extremes outside H would change ranks if ranked before joining.
    f.iloc[0] = np.nan
    y.iloc[1] = np.nan
    raw.iloc[2, 0] = np.nan
    raw.iloc[0, 1] = -9999.
    f.iloc[2] = 1e9
    old = load(ROOT/'tests/reference/calendar_account_v1/conditional.py', 'frozen_conditional')
    before = [x.copy(deep=True) for x in (f, y, raw)]
    result = evaluate(f, y, raw, idx, slots)
    row = result['periods'][0]
    assert row['input_n'] == 120 and row['n'] == 117 and row['excluded_n'] == 3
    clean = f.join(y).join(raw).dropna()
    reference = clean.rename(columns={'forward_return': 'y'}).reset_index().rename(columns={'instrument': 'ts_code'})
    reference['score_gate'] = reference['varying_signal'] = True
    x = old.design_matrix(reference)
    controls = c11_controls(clean.loc[:, list(RAW_CONTROL_NAMES)])
    np.testing.assert_array_equal(controls.to_numpy(), x[:, 2:])
    np.testing.assert_array_equal((clean.factor_value.rank().to_numpy()-.5)/len(clean), x[:, 1])
    assert row['lambda'] == pytest.approx(old.monthly_regression(reference)['beta'], abs=1e-14)
    # Independent normal equations on a well-conditioned finite fixture.
    z = np.column_stack([np.ones(len(clean)), controls])
    ranks = clean[['factor_value', 'forward_return']].rank().to_numpy()
    residual = ranks-z@np.linalg.solve(z.T@z, z.T@ranks)
    assert row['partial_rank_ic'] == pytest.approx(np.corrcoef(residual.T)[0, 1], abs=2e-13)
    assert abs(row['partial_rank_ic']-pd.DataFrame(residual).corr(method='spearman').iloc[0, 1]) > .0001
    assert row['same_support_rank_ic'] == pytest.approx(clean.factor_value.corr(clean.forward_return, method='spearman'))
    assert result['support'].complete_case.sum() == 117
    for old_frame, current in zip(before, (f, y, raw)):
        assert_frame_equal(old_frame, current)
    json.dumps({k: v for k, v in result.items() if k != 'support'}, allow_nan=False)


@pytest.mark.parametrize('n', [99, 100])
def test_minimum_sample_boundary(n):
    result = evaluate(*panel(n=n, months=1))
    row = result['periods'][0]
    assert (row['partial_rank_ic'] is None) == (n < 100)
    assert (row['lambda'] is None) == (n < 100)
    assert row['partial_reason'] == ('cross_section_insufficient' if n < 100 else None)
    assert row['fmb_reason'] == ('cross_section_insufficient' if n < 100 else None)


@pytest.mark.parametrize('kind', ['constant_control', 'duplicate_control', 'factor_in_controls'])
def test_singular_or_zero_residual_models_stay_unknown(kind):
    f, y, raw, idx, slots = panel(months=1)
    if kind == 'constant_control':
        raw['size_raw'] = 1.
    elif kind == 'duplicate_control':
        raw['size_raw'] = raw['momentum_raw']
    else:
        f.factor_value = raw.size_raw
    row = evaluate(f, y, raw, idx, slots)['periods'][0]
    assert row['lambda'] is None and row['fmb_reason'] == 'rank_deficient'
    assert row['partial_rank_ic'] is None
    assert row['partial_reason'] == ('zero_residual_variance' if kind == 'factor_in_controls' else 'rank_deficient')


def test_missing_months_remain_calendar_slots_and_support_counts_missing_rows():
    f, y, raw, idx, slots = panel()
    absent = f.index.get_level_values('datetime') == slots[1]
    f = f.loc[~absent]
    raw.loc[slots[3], :] = np.nan
    result = evaluate(f, y, raw, idx, slots)
    assert len(result['periods']) == 5
    assert result['summary']['lambda']['missing_slots'] == [1, 3]
    got = result['summary']['lambda']
    original_slots = [r['lambda'] for r in result['periods']]
    expected = hac_mean(original_slots)
    assert got['se'] == expected['se']
    assert got['se'] != pytest.approx(hac_mean([v for v in original_slots if v is not None])['se'])
    support = result['support']
    missing = support.datetime.eq(slots[1])
    assert not support.loc[missing, 'factor_present'].any()
    assert support.loc[missing, 'label_present'].all()


def test_hac_hand_sandwich_intervals_and_no_zero_filling():
    values = [1., None, 2., 4., None, 3.]
    z = np.array([-1.5, 0., -.5, 1.5, 0., .5])
    variance = (z@z+2*sum((1-k/4)*(z[k:]@z[:-k]) for k in range(1, 4)))/16
    got = calendar_slot_hac3(values)
    assert got['mean'] == 2.5 and got['n'] == 4 and got['missing_slots'] == [1, 4]
    assert got['se'] == pytest.approx(np.sqrt(variance))
    assert got['ci95_lower'] == pytest.approx(2.5-1.959963984540054*got['se'])
    assert got['lower_995_one_sided'] == pytest.approx(2.5-2.5758293035489*got['se'])
    assert calendar_slot_hac3([None, None])['reason'] == 'no_estimable_periods'
    assert calendar_slot_hac3([2., None, 2.])['positive_p'] is None
    assert calendar_slot_hac3([2., None, 2.])['ci95_lower'] is None
    with np.errstate(over='ignore', invalid='ignore'):
        overflow = calendar_slot_hac3([1e308, 1e308])
    assert overflow['mean'] is None and overflow['reason'] == 'numeric_overflow'
    json.dumps(overflow, allow_nan=False)


def test_paired_ic_uses_same_h_and_hac_of_difference():
    f, y, raw, idx, slots = panel(n=40)
    alternative = raw[['momentum_raw']].rename(columns={'momentum_raw': 'factor_value'})
    y.iloc[4] = np.nan
    alternative.iloc[5] = np.nan
    result = paired_monthly_rank_ic(f, alternative, y, expected_index=idx, calendar_slots=slots)
    a = f.xs(slots[0]).factor_value
    b = alternative.xs(slots[0]).factor_value
    yy = y.xs(slots[0]).forward_return
    h = pd.concat([a.rename('a'), b.rename('b'), yy], axis=1).dropna().rank()
    first = result['periods'][0]
    assert first['n'] == 38
    assert first['delta'] == pytest.approx(h.a.corr(h.forward_return)-h.b.corr(h.forward_return))
    expected = hac_mean([r['delta'] for r in result['periods']])
    assert result['delta_hac3']['se'] == expected['se']
    # Joint inference differs from adding marginal standard errors in quadrature.
    independent = np.hypot(hac_mean([r['reference_rank_ic'] for r in result['periods']])['se'],
                           hac_mean([r['alternative_rank_ic'] for r in result['periods']])['se'])
    assert result['delta_hac3']['se'] != pytest.approx(independent)
    same = paired_monthly_rank_ic(f, f, y, expected_index=idx, calendar_slots=slots)
    assert same['delta_hac3']['mean'] == 0 and same['delta_hac3']['positive_p'] is None


@pytest.mark.parametrize('scale', [1., 1e-24, 1e-120])
def test_constant_exact_ols_coefficients_with_gaps_do_not_imply_significance(scale):
    f, y, raw, idx, slots = panel(n=137, months=6)
    for day in slots:
        quantile = (f.xs(day).factor_value.rank()-.5)/137
        y.loc[day, 'forward_return'] = .02*scale*quantile.to_numpy()
    y.loc[slots[2], :] = np.nan
    result = evaluate(f, y, raw, idx, slots)
    coefficients = [r['lambda'] for r in result['periods'] if r['lambda'] is not None]
    np.testing.assert_allclose(np.asarray(coefficients)/scale, .02, atol=1e-15, rtol=0.)
    inference = result['summary']['lambda']
    assert inference['missing_slots'] == [2] and inference['n'] == 5
    assert inference['reason'] == 'zero_variation_at_float_precision'
    for key in ['se', 'positive_p', 'negative_p', 'tstat', 'ci95_lower', 'ci95_upper', 'lower_995_one_sided']:
        assert inference[key] is None
    assert newey_west_mean(coefficients, 3)['reason'] == inference['reason']


@pytest.mark.parametrize('scale', [1e-24, 1e-120])
def test_tiny_units_preserve_real_ols_variation_and_calendar_hac(scale):
    f, y, raw, idx, slots = panel(n=137, months=6)
    slopes = [.02, .05, np.nan, .03, .07, .01]
    for day, slope in zip(slots, slopes):
        quantile = (f.xs(day).factor_value.rank()-.5)/137
        y.loc[day, 'forward_return'] = slope*scale*quantile.to_numpy()
    inference = evaluate(f, y, raw, idx, slots)['summary']['lambda']
    expected = hac_mean(slopes)
    assert inference['reason'] is None and inference['missing_slots'] == [2]
    assert inference['mean']/scale == pytest.approx(expected['mean'], abs=1e-15)
    assert inference['se']/scale == pytest.approx(expected['se'], abs=1e-15)
    assert inference['positive_p'] == pytest.approx(expected['positive_p'], abs=1e-14)


@pytest.mark.parametrize('n', [29, 30])
def test_paired_minimum(n):
    f, y, raw, idx, slots = panel(n=n, months=1)
    row = paired_monthly_rank_ic(f, raw[['size_raw']].rename(columns={'size_raw': 'factor_value'}), y,
                                expected_index=idx, calendar_slots=slots)['periods'][0]
    assert (row['delta'] is None) == (n < 30)


@pytest.mark.parametrize('problem', ['missing_slot', 'duplicate', 'outside', 'infinity', 'text', 'return_below_minus1'])
def test_invalid_inputs_reject(problem):
    f, y, raw, idx, slots = panel()
    if problem == 'missing_slot':
        slots = slots.delete(2)
    elif problem == 'duplicate':
        f = pd.concat([f, f.iloc[:1]])
    elif problem == 'outside':
        idx = idx[1:]
    elif problem == 'infinity':
        raw.iloc[0, 0] = np.inf
    elif problem == 'text':
        raw['size_raw'] = raw.size_raw.astype(str)
    else:
        y.iloc[0] = -1.01
    with pytest.raises((TypeError, ValueError)):
        evaluate(f, y, raw, idx, slots)


def test_fmb_optional_arguments_preserve_legacy_default_and_explicit_rank_threshold():
    x = np.arange(20.)
    frame = pd.DataFrame({'date': '2020-01-01', 'signal': x, 'y': .02*x})
    args = dict(date_col='date', signal_col='signal', return_col='y', controls=[])
    assert fama_macbeth_periods(frame, **args)[0]['lambda'] == pytest.approx(.02)
    assert fama_macbeth_periods(frame, **args, min_observations=100)[0]['reason'] == 'cross_section_insufficient'
    frame['tiny'] = 1e-11*np.random.default_rng(1).normal(size=len(x))
    assert fama_macbeth_periods(frame, **{**args, 'controls': ['tiny']}, rcond=1e-10)[0]['reason'] == 'rank_deficient'


def consumer_fixture(tmp_path):
    rid = 'IT_SYNTHETIC_CONDITIONAL'
    calendar = pd.bdate_range('2020-01-01', '2020-06-05')
    windows = calendar_month_windows(calendar)
    f, y, raw, idx, old_slots = panel(months=len(windows))
    dates = idx.get_level_values('datetime').map(dict(zip(old_slots, windows.entry_date)))
    expected = pd.MultiIndex.from_arrays([dates, idx.get_level_values('instrument')], names=idx.names)
    for frame in (f, y, raw):
        frame.index = expected
    y.loc[windows.entry_date.iloc[-1], :] = np.nan
    factor_path = tmp_path/'runs'/rid/'factor.parquet'
    factor_path.parent.mkdir(parents=True)
    f.to_parquet(factor_path)
    eval_dir = tmp_path/'evaluations'/rid
    eval_dir.mkdir(parents=True)
    labels_path = eval_dir/'monthly_labels.csv'
    y.reset_index().rename(columns={'datetime': 'trade_date', 'instrument': 'ts_code'}).to_csv(labels_path, index=False)
    prepared = {'report_id': rid, 'scope': 'local_is_only', 'is_start': str(calendar[0].date()),
                'is_end': str(calendar[-1].date()), 'price_basis_id': 'fixed-synthetic',
                'membership_semantics': 'explicit_pit_true_rows', 'files': {}}
    formation = pd.DataFrame([(w.signal_date, code) for w in windows.itertuples(index=False)
                             for code in idx.get_level_values('instrument').unique()], columns=['trade_date', 'ts_code'])
    for role, frame in [('calendar', pd.DataFrame({'trade_date': calendar})), ('membership', formation)]:
        path = tmp_path/(role+'.parquet')
        frame.to_parquet(path, index=False)
        prepared['files'][role] = {'path': str(path), 'sha256': digest(path), 'columns': {c: c for c in frame}}
    # No daily prices exist: the diagnostic cannot accidentally replay accounts.
    prepared['files']['daily'] = {'path': str(tmp_path/'DOES_NOT_EXIST_daily.parquet'), 'sha256': '0'*64}
    prepared_path = tmp_path/'evaluation_inputs.json'
    prepared_path.write_text(json.dumps(prepared))
    primary_path = eval_dir/'primary.json'
    primary_path.write_text(json.dumps({'report_id': rid, 'scope': 'local_is_only', 'status': 'success',
        'bindings': {'factor_values_path': str(factor_path), 'factor_values_sha256': digest(factor_path),
                     'prepared_inputs': str(prepared_path), 'prepared_inputs_sha256': digest(prepared_path),
                     **{k: prepared[k] for k in ['price_basis_id', 'is_start', 'is_end']}},
        'diagnostics': {'label': 'observed_adjusted_close_next_monthly_entry_over_entry_minus_one'},
        'artifacts': {'monthly_labels': str(labels_path)}}))
    binding = {'report_id': 'OLD_ID_IS_PROVENANCE_ONLY', 'monthly_controls': {}}
    for w in windows.itertuples(index=False):
        key = w.signal_date.strftime('%Y%m%d')
        path = tmp_path/(key+'_raw.parquet')
        frame = raw.xs(w.entry_date).reset_index().rename(columns={'instrument': 'ts_code'})
        frame['signal_date'], frame['entry_date'] = key, w.entry_date.strftime('%Y%m%d')
        # Deliberately unusable old study columns must never enter the consumer.
        frame['factor_value'], frame['y'], frame['score_gate'] = 'irrelevant', 'old label', False
        frame.to_parquet(path, index=False)
        binding['monthly_controls'][key] = {'path': str(path), 'sha256': digest(path),
            'signal_date': key, 'entry_date': w.entry_date.strftime('%Y%m%d'),
            'label_end_date': None if pd.isna(w.label_end_date) else w.label_end_date.strftime('%Y%m%d'),
            'source_kind': 'full_member_attrition', 'source_report_id': 'OLD_ID_IS_PROVENANCE_ONLY',
            'source_contract_sha256': '1'*64}
    binding_path = tmp_path/'raw_binding.json'
    binding_path.write_text(json.dumps(binding))
    manifest_path = tmp_path/'runtime_manifest.json'
    manifest_path.write_text(json.dumps({'contract_version': 'factorforge_runtime_context_v2',
        'report_id': rid, 'factor_workspace': str(tmp_path), 'runs': {'factor_values_parquet': str(factor_path)}}))
    args = SimpleNamespace(report_id=rid, factor_values=str(factor_path), primary_payload=str(primary_path),
        controls_binding=str(binding_path), control_profile=C11_PROFILE, output=str(eval_dir/'conditional.json'), manifest=str(manifest_path))
    return args, (f, y, raw, expected, pd.DatetimeIndex(windows.entry_date))


def test_actual_cli_uses_current_labels_raw7_only_and_preserves_primary(tmp_path):
    args, inputs = consumer_fixture(tmp_path)
    protected = {p: digest(p) for p in [args.factor_values, args.primary_payload, args.manifest, args.controls_binding]}
    argv = [sys.executable, str(SCRIPT)]
    for key, value in vars(args).items():
        argv.extend(['--'+key.replace('_', '-'), value])
    completed = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    assert completed.returncode == 0, completed.stdout+completed.stderr
    result = json.loads(Path(args.output).read_text())
    oracle = evaluate(*inputs)
    assert result['periods'] == oracle['periods']
    assert result['summary'] == oracle['summary']
    assert result['account_simulation'] is False and result['results_computed'] is True
    assert result['summary']['lambda']['missing_slots'] == [4]
    assert result['status'] == 'partial'
    assert result['raw_control_inputs'][0]['source_report_id'] == 'OLD_ID_IS_PROVENANCE_ONLY'
    assert len(pd.read_parquet(result['artifacts']['support'])) == 600
    assert all(digest(p) == value for p, value in protected.items())
    second = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    assert second.returncode != 0 and 'existing_diagnostic_preserved' in second.stderr


@pytest.mark.parametrize('problem', ['hash', 'window', 'label_end', 'source_kind', 'missing_column', 'duplicate', 'row_date'])
def test_consumer_rejects_bad_control_bindings_without_old_fallback(tmp_path, problem):
    args, _ = consumer_fixture(tmp_path)
    binding_path = Path(args.controls_binding)
    binding = json.loads(binding_path.read_text())
    first = next(iter(binding['monthly_controls'].values()))
    if problem == 'hash':
        first['sha256'] = '0'*64
    elif problem == 'window':
        first['entry_date'] = '20200204'
    elif problem == 'label_end':
        first['label_end_date'] = '20200303'
    elif problem == 'source_kind':
        first['source_kind'] = 'old_complete_case_only'
    else:
        path = Path(first['path'])
        frame = pd.read_parquet(path)
        if problem == 'missing_column':
            frame = frame.drop(columns=['size_raw'])
        elif problem == 'duplicate':
            frame = pd.concat([frame, frame.iloc[:1]])
        else:
            frame.loc[0, 'signal_date'] = '20200130'
        frame.to_parquet(path, index=False)
        first['sha256'] = digest(path)
    binding_path.write_text(json.dumps(binding))
    primary_hash = digest(args.primary_payload)
    consumer = load(SCRIPT, 'consumer_bad_'+problem)
    with pytest.raises(Exception):
        consumer.run(args)
    assert digest(args.primary_payload) == primary_hash
    result = json.loads(Path(args.output).read_text())
    assert result['status'] == 'failed' and result['results_computed'] is False


def test_missing_control_reference_keeps_month_and_unknown_statistics(tmp_path):
    args, _ = consumer_fixture(tmp_path)
    path = Path(args.controls_binding)
    binding = json.loads(path.read_text())
    del binding['monthly_controls'][list(binding['monthly_controls'])[1]]
    path.write_text(json.dumps(binding))
    consumer = load(SCRIPT, 'consumer_missing')
    assert consumer.run(args) == 0
    result = json.loads(Path(args.output).read_text())
    assert len(result['periods']) == 5
    assert result['periods'][1]['n'] == 0 and result['periods'][1]['lambda'] is None
    assert result['summary']['lambda']['missing_slots'] == [1, 4]


def test_old_source_extra_member_does_not_change_current_membership_ranks(tmp_path):
    args, inputs = consumer_fixture(tmp_path)
    path = Path(args.controls_binding)
    binding = json.loads(path.read_text())
    first = next(iter(binding['monthly_controls'].values()))
    raw_path = Path(first['path'])
    raw = pd.read_parquet(raw_path)
    extra = raw.iloc[:1].copy()
    extra['ts_code'] = 'NOT_CURRENT_MEMBER'
    extra.loc[:, list(RAW_CONTROL_NAMES)] = 1e20
    pd.concat([raw, extra]).to_parquet(raw_path, index=False)
    first['sha256'] = digest(raw_path)
    path.write_text(json.dumps(binding))
    assert load(SCRIPT, 'consumer_extra_member').run(args) == 0
    result = json.loads(Path(args.output).read_text())
    assert result['periods'] == evaluate(*inputs)['periods']
    assert result['raw_control_inputs'][0]['outside_current_membership_rows'] == 1


@pytest.mark.parametrize('problem', ['report', 'factor_hash', 'profile', 'primary_identity', 'prepared_hash'])
def test_consumer_identity_and_snapshot_guard(tmp_path, problem):
    args, _ = consumer_fixture(tmp_path)
    primary = json.loads(Path(args.primary_payload).read_text())
    if problem == 'report':
        args.report_id = 'WRONG'
    elif problem == 'profile':
        args.control_profile = 'guess_controls'
    elif problem == 'primary_identity':
        primary['report_id'] = 'OLD'
    elif problem == 'factor_hash':
        primary['bindings']['factor_values_sha256'] = '0'*64
    else:
        primary['bindings']['prepared_inputs_sha256'] = '0'*64
    Path(args.primary_payload).write_text(json.dumps(primary))
    consumer = load(SCRIPT, 'consumer_identity_'+problem)
    with pytest.raises(ValueError):
        consumer.run(args)
    assert not Path(args.output).exists()
