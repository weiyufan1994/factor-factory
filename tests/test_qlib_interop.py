"""Hand-calculated offline interchange oracles; no Qlib or market execution."""
from __future__ import annotations

import importlib.abc
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from factor_factory.data_access.qlib import (
    daily_to_qlib_features, normalize_qlib_instrument, to_qlib_frame, to_qlib_signal_frame,
)
from factor_factory.research_api import normalize_factor_frame

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    class DenyQlib(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'qlib' or fullname.startswith('qlib.'):
                raise AssertionError('native Qlib import forbidden in offline interchange tests')
    guard = DenyQlib()
    sys.meta_path.insert(0, guard)
    def deny_network(*args, **kwargs):
        raise AssertionError('network forbidden in offline interchange tests')
    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    monkeypatch.setattr(socket, 'create_connection', deny_network)
    try:
        yield
    finally:
        sys.meta_path.remove(guard)


def module(name):
    spec = importlib.util.spec_from_file_location('interop_' + name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def signals():
    return pd.DataFrame({'ts_code': ['000001.SZ', '600000.SH', '920599.BJ'],
                         'trade_date': ['20260202'] * 3,
                         'factor_value': [0., .05, np.nan]})


def bars():
    # Observed adjusted price 7.5 = raw price 15 * 0.5.
    # 2 lots = 200 physical shares = 400 adjusted-price units; 3 kCNY = 3000 CNY.
    return pd.DataFrame({'ts_code': ['000001.SZ'] * 2,
                         'trade_date': ['20260129', '20260202'],
                         **{k: [7.5, 9.] for k in ['open', 'high', 'low', 'close', 'pre_close']},
                         'vol': [2., 0.], 'amount': [3., 0.], 'pct_chg': [5., 0.],
                         'price_scale': [.5, .5]})


OPTIONS = dict(volume_unit='lot100', amount_unit='cny_thousand', return_unit='percent',
               price_basis='adjusted', adjustment_factor_col='price_scale')
CALENDAR = ['20260129', '20260130', '20260202', '20260203']


def intervals():
    return pd.DataFrame({'instrument': ['000001.SZ', '920599.BJ'],
                         'start_time': ['20260129', '20260202'],
                         'end_time': ['20260203', '20260203']})


def test_standard_signal_round_trip_retains_zero_nan_entry_date_and_original():
    original = normalize_factor_frame(signals())
    saved = original.copy(deep=True)
    out = to_qlib_signal_frame(original, dropna_value_columns=False)
    assert out.index.names == ['datetime', 'instrument']
    assert list(out.index.get_level_values('instrument')) == ['BJ920599', 'SH600000', 'SZ000001']
    assert out.loc[(pd.Timestamp('2026-02-02'), 'SH600000'), 'factor_value'] == .05
    assert out.loc[(pd.Timestamp('2026-02-02'), 'SZ000001'), 'factor_value'] == 0.
    assert np.isnan(out.loc[(pd.Timestamp('2026-02-02'), 'BJ920599'), 'factor_value'])
    # Entry is already Feb 2; conversion must not shift back to formation Jan30
    # or forward to Feb3, and must not derive a calendar from sparse signals.
    assert out.index.get_level_values('datetime').unique().tolist() == [pd.Timestamp('2026-02-02')]
    pd.testing.assert_frame_equal(original, to_qlib_signal_frame(
        out, instrument_style='ts_code', dropna_value_columns=False))
    pd.testing.assert_frame_equal(original, saved)
    assert len(to_qlib_signal_frame(original)) == 2  # explicit documented legacy NaN default


@pytest.mark.parametrize('dates', [
    ['20260202'] * 3, [20260202] * 3, ['2026-02-02'] * 3,
    pd.to_datetime(['2026-02-02'] * 3),
])
def test_supported_dates_never_silently_disappear(dates):
    out = to_qlib_signal_frame(signals().assign(trade_date=dates), dropna_value_columns=False)
    assert len(out) == 3


@pytest.mark.parametrize('bad', [None, '20260230', '02/03/2026', 20260202.0,
                                  pd.Timestamp('2026-02-02 12:00'),
                                  pd.Timestamp('2026-02-02', tz='UTC')])
def test_bad_keys_fail_even_on_a_nan_signal(bad):
    frame = signals().astype({'trade_date': object})
    frame.loc[2, 'trade_date'] = bad
    with pytest.raises((ValueError, TypeError)):
        to_qlib_signal_frame(frame)


def test_duplicate_normalized_keys_and_rename_collision_fail():
    frame = signals().iloc[:2].assign(ts_code=['000001.SZ', 'SZ000001'])
    with pytest.raises(ValueError, match='duplicate'):
        to_qlib_signal_frame(frame)
    with pytest.raises(ValueError, match='unique'):
        to_qlib_frame(bars(), ['vol', 'amount'], rename_fields={'vol': 'x', 'amount': 'x'})
    out = to_qlib_frame(bars(), (x for x in ['vol', 'amount']))
    assert list(out) == ['vol', 'amount']
    with pytest.raises(ValueError, match='key columns'):
        to_qlib_signal_frame(normalize_factor_frame(signals()).assign(ts_code='000001.SZ'))


@pytest.mark.parametrize('value', [np.inf, True, '0.05'])
def test_signal_values_are_real_numeric_or_nan(value):
    with pytest.raises((TypeError, ValueError)):
        to_qlib_signal_frame(signals().assign(factor_value=value))


def test_security_spelling_is_reversible_and_explicit():
    for code in ['600000.SH', '000001.SZ', '920599.BJ']:
        assert normalize_qlib_instrument(normalize_qlib_instrument(code), 'ts_code') == code
    assert normalize_qlib_instrument('sh600000') == 'SH600000'
    assert normalize_qlib_instrument('SPY', 'raw') == 'SPY'
    for value in ['600000', '600000.XX', '', ' 000001.SZ', None]:
        with pytest.raises(ValueError):
            normalize_qlib_instrument(value)
    with pytest.raises(ValueError, match='unsupported'):
        normalize_qlib_instrument('SPY', 'unknown_style')


def test_explicit_units_and_price_scale_hand_oracle():
    source = bars()
    before = source.copy(deep=True)
    out = daily_to_qlib_features(source, **OPTIONS)
    row = out.iloc[0]
    assert row['$close'] == 7.5 and row['$factor'] == .5
    assert row['$volume'] == 400. and row['$amount'] == 3000.
    assert row['$ret'] == .05
    assert row['$volume'] * row['$factor'] == 200.  # physical shares
    assert row['$close'] / row['$factor'] == 15.  # raw price, not another adjustment
    assert row['$close'] * row['$volume'] == row['$amount']
    assert out.iloc[1]['$volume'] == 0. and out.iloc[1]['$ret'] == 0.
    assert out.attrs['qlib_semantics']['native_execution_equivalence'] == 'not_verified'
    pd.testing.assert_frame_equal(source, before)
    raw = daily_to_qlib_features(source.drop(columns='price_scale'), price_basis='raw',
                                volume_unit='share', amount_unit='cny', return_unit='decimal')
    assert raw.iloc[0]['$factor'] == 1. and raw.iloc[0]['$volume'] == 2.
    assert raw.iloc[0]['$amount'] == 3. and raw.iloc[0]['$ret'] == 5.


@pytest.mark.parametrize('edit', [
    lambda x: x.drop(columns='price_scale'), lambda x: x.assign(price_scale=0.),
    lambda x: x.assign(price_scale=np.nan), lambda x: x.assign(vol=-1.),
])
def test_invalid_declared_price_units_fail(edit):
    with pytest.raises((ValueError, KeyError)):
        daily_to_qlib_features(edit(bars()), **OPTIONS)


def test_unspecified_basis_does_not_manufacture_factor_or_decimal_units():
    source = bars()
    out = daily_to_qlib_features(source)
    assert '$factor' not in out and out.iloc[0]['$ret'] == 5.
    assert out.attrs['qlib_semantics']['price_basis'] == 'unspecified'
    builder = module('build_report_qlib_provider')
    legacy = builder.normalize_source(source.drop(columns='pct_chg').assign(change=123.))
    assert legacy.factor.isna().all() and legacy.change.isna().all()


def read_feature(root, code, field):
    return np.fromfile(root / 'features' / code.lower() / (field + '.day.bin'), dtype='<f4')


def test_explicit_provider_round_trip_keeps_calendar_gaps_and_unobserved_instrument(tmp_path):
    builder = module('build_report_qlib_provider')
    source = builder.normalize_source(bars(), instrument_style='legacy_qlib', **OPTIONS)
    stats = builder.build_provider(source, tmp_path / 'provider', instrument_style='legacy_qlib',
                                   calendar=CALENDAR, instruments=intervals())
    p = tmp_path / 'provider'
    assert (p / 'calendars/day.txt').read_text().splitlines() == [
        '2026-01-29', '2026-01-30', '2026-02-02', '2026-02-03']
    assert (p / 'instruments/all.txt').read_text().splitlines() == [
        'BJ920599\t2026-02-02\t2026-02-03', 'SZ000001\t2026-01-29\t2026-02-03']
    np.testing.assert_equal(read_feature(p, 'SZ000001', 'close'), [0., 7.5, np.nan, 9., np.nan])
    np.testing.assert_equal(read_feature(p, 'SZ000001', 'volume'), [0., 400., np.nan, 0., np.nan])
    np.testing.assert_equal(read_feature(p, 'SZ000001', 'amount'), [0., 3000., np.nan, 0., np.nan])
    np.testing.assert_equal(read_feature(p, 'BJ920599', 'close'), [2., np.nan, np.nan])
    assert stats['native_data_contract_declared'] is True
    assert stats['native_execution_equivalence'] == 'not_verified'
    assert stats['symbols'] == 2 and stats['dates'] == 4
    assert builder.raw_format_smoke(p)['status'] == 'PASS'


def test_binary_rounding_is_measured_not_called_engine_equivalence(tmp_path):
    builder = module('build_report_qlib_provider')
    x = pd.Series([7.123456789, np.nan, 0.])
    builder.write_feature_bin(tmp_path / 'close.day.bin', 2, x)
    raw = np.fromfile(tmp_path / 'close.day.bin', dtype='<f4')
    assert raw[0] == 2. and np.isnan(raw[2]) and raw[3] == 0.
    assert float(raw[1]) != x.iloc[0]
    assert abs(float(raw[1]) - x.iloc[0]) <= abs(x.iloc[0]) * np.finfo(np.float32).eps


@pytest.mark.parametrize('kind', ['duplicate', 'calendar_gap', 'calendar_order', 'span_overlap',
                                   'span_excludes_bar', 'missing_instrument', 'overflow'])
def test_bad_provider_inputs_fail_before_replacing_store(tmp_path, kind):
    builder = module('build_report_qlib_provider')
    source = builder.normalize_source(bars(), **OPTIONS)
    calendar, spans = CALENDAR, intervals()
    if kind == 'duplicate': source = pd.concat([source, source.iloc[:1]])
    if kind == 'calendar_gap': calendar = CALENDAR[:2]
    if kind == 'calendar_order': calendar = list(reversed(CALENDAR))
    if kind == 'span_overlap': spans = pd.concat([spans, spans.iloc[:1]])
    if kind == 'span_excludes_bar': spans.loc[0, 'end_time'] = '20260130'
    if kind == 'missing_instrument': spans = spans.iloc[1:]
    if kind == 'overflow': source.loc[0, 'amount'] = 1e300
    p = tmp_path / 'existing';p.mkdir();sentinel = p / 'keep.txt';sentinel.write_text('old')
    with pytest.raises(ValueError):
        builder.build_provider(source, p, calendar=calendar, instruments=spans)
    assert sentinel.read_text() == 'old'


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink'])
def test_valid_provider_build_never_replaces_existing_output(tmp_path, kind):
    builder = module('build_report_qlib_provider')
    source = builder.normalize_source(bars(), **OPTIONS)
    p = tmp_path / 'existing'
    if kind == 'file':
        p.write_text('old')
        sentinel = p
    else:
        target = tmp_path / 'original' if kind == 'symlink' else p
        target.mkdir()
        sentinel = target / 'keep.txt'
        sentinel.write_text('old')
        if kind == 'symlink':
            p.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        builder.build_provider(source, p, calendar=CALENDAR, instruments=intervals())
    assert sentinel.read_text() == 'old'
    assert not (p / 'calendars').exists()


def test_multiple_explicit_intervals_are_not_merged_into_continuous_membership(tmp_path):
    builder = module('build_report_qlib_provider')
    source = builder.normalize_source(bars(), **OPTIONS)
    spans = pd.DataFrame({'instrument': ['000001.SZ'] * 2,
                         'start_time': ['20260129', '20260202'],
                         'end_time': ['20260129', '20260203']})
    builder.build_provider(source, tmp_path / 'p', calendar=CALENDAR, instruments=spans)
    assert len((tmp_path / 'p/instruments/all.txt').read_text().splitlines()) == 2
    assert np.isnan(read_feature(tmp_path / 'p', '000001.SZ', 'close')[2])


def test_legacy_observation_spans_are_labeled_without_listing_claim(tmp_path):
    builder = module('build_report_qlib_provider')
    stats = builder.build_provider(builder.normalize_source(bars()), tmp_path / 'p')
    assert stats['native_data_contract_declared'] is False
    assert stats['calendar_source'] == 'observed_bar_union_not_exchange_calendar'
    assert stats['instrument_intervals_source'] == 'observed_bar_extent_not_listing_or_membership'
    assert np.isnan(read_feature(tmp_path / 'p', '000001.SZ', 'factor')[1:]).all()


def test_existing_publisher_cli_accepts_explicit_metadata_without_qlib(tmp_path, monkeypatch):
    publisher = module('publish_qlib_daily_provider')
    bars().to_parquet(tmp_path / 'bars.parquet', index=False)
    pd.DataFrame({'trade_date': CALENDAR}).to_csv(tmp_path / 'calendar.csv', index=False)
    intervals().to_csv(tmp_path / 'instruments.csv', index=False)
    monkeypatch.setattr(sys, 'argv', ['publish', '--input', str(tmp_path / 'bars.parquet'),
        '--provider-dir', str(tmp_path / 'p'), '--calendar-file', str(tmp_path / 'calendar.csv'),
        '--instrument-intervals-file', str(tmp_path / 'instruments.csv'),
        '--volume-unit', 'lot100', '--amount-unit', 'cny_thousand', '--return-unit', 'percent',
        '--price-basis', 'adjusted', '--adjustment-factor-column', 'price_scale'])
    publisher.main()
    report = json.loads((tmp_path / 'p/publish_report.json').read_text())
    assert report['provider_stats']['native_data_contract_declared'] is True
    assert 'microsoft_qlib_smoke' not in report


def test_native_smoke_requires_declared_contract_before_output_or_engine(tmp_path, monkeypatch):
    publisher = module('publish_qlib_daily_provider')
    bars().to_parquet(tmp_path / 'bars.parquet', index=False)
    monkeypatch.setattr(sys, 'argv', ['publish', '--input', str(tmp_path / 'bars.parquet'),
        '--provider-dir', str(tmp_path / 'p'), '--qlib-smoke'])
    def forbidden(*args, **kwargs):
        pytest.fail('native smoke must not be entered without the declared contract')
    monkeypatch.setattr(publisher, 'run_microsoft_qlib_smoke', forbidden)
    with pytest.raises(SystemExit, match='explicit calendar'):
        publisher.main()
    assert not (tmp_path / 'p').exists()


@pytest.mark.parametrize('script', ['publish_qlib_daily_provider', 'build_report_qlib_provider'])
def test_real_cli_rejects_dangling_output_symlink_without_creating_target(tmp_path, script):
    source = tmp_path / 'bars.parquet'
    bars().to_parquet(source, index=False)
    target, output = tmp_path / 'absent-target', tmp_path / 'provider-link'
    output.symlink_to(target, target_is_directory=True)
    args = (['--input', str(source)] if script == 'publish_qlib_daily_provider'
            else ['--report-id', 'OFFLINE_HAND_ORACLE', '--source', str(source)])
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / (script + '.py')),
                             *args, '--provider-dir', str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'FileExistsError' in result.stderr
    assert output.is_symlink() and output.readlink() == target
    assert not target.exists()
