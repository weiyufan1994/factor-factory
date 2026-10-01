from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.prepared_daily_inputs import validate_prepared_daily, sample_inputs, validate_sample_frames, validate_paths, validate_full_scope

REPO = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name + '_daily_test', REPO / 'skills/factor-forge-step3/scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inputs():
    return dict(input_mode='daily_only', daily_df_parquet='full.parquet',
                exchange_calendar_parquet='full_calendar.parquet',
                step3b_daily_df_parquet='sample.parquet',
                step3b_exchange_calendar_parquet='calendar.parquet',
                sample_window_actual={'start': '20160104', 'end': '20250711'},
                step3b_sample_window={'start': '20160104', 'end': '20160106'})


@pytest.mark.parametrize('key', ['derived_state_root', 'step3b_derived_state_root', 'minute_df_parquet', 'minute_streaming_query'])
def test_daily_cannot_claim_minute_state(key):
    with pytest.raises(ValueError, match='forbid'):
        validate_prepared_daily({**inputs(), key: 'bad'})


def test_daily_requires_separate_sample_calendar_and_window():
    payload = inputs()
    payload.pop('step3b_exchange_calendar_parquet')
    with pytest.raises(ValueError, match='missing'):
        validate_prepared_daily(payload)
    payload = inputs()
    payload['step3b_sample_window']['end'] = '20260101'
    with pytest.raises(ValueError, match='outside'):
        validate_prepared_daily(payload)
    assert sample_inputs(inputs())['daily_df_parquet'] == 'sample.parquet'


def test_roles_override_incidental_minute_guard_but_preserve_minute_role():
    step3 = load('run_step3')
    contract = {'input_schema': {'daily_df': {}}, 'source_code': 'def compute_factor(daily_df, minute_df=None): pass'}
    fsm = {'implementation_contract': {'code_contract': contract}}
    assert step3.direct_code_requires_minute_inputs(fsm) is False
    contract['input_schema']['minute_df'] = {}
    assert step3.direct_code_requires_minute_inputs(fsm) is True
    contract.pop('input_schema')
    assert step3.direct_code_requires_minute_inputs(fsm) is True


def test_sample_calendar_is_independent_and_bounded():
    daily = pd.DataFrame({'ts_code': ['000001.SZ'], 'trade_date': ['20160104']})
    calendar = pd.DataFrame({'trade_date': ['20160104', '20160105', '20160106']})
    validate_sample_frames(daily, calendar, inputs()['step3b_sample_window'])
    with pytest.raises(ValueError, match='outside exchange calendar'):
        validate_sample_frames(daily, calendar.iloc[1:], inputs()['step3b_sample_window'])
    with pytest.raises(ValueError, match='exceeds'):
        validate_sample_frames(daily, pd.DataFrame({'trade_date': ['20200101']}), inputs()['step3b_sample_window'])


def test_real_dispatch_reads_only_sample_and_passes_none(tmp_path, monkeypatch):
    step3b = load('run_step3b')
    monkeypatch.setattr(step3b, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(step3b, 'FF', tmp_path)
    monkeypatch.setattr(step3b, 'RUNS', tmp_path / 'runs')
    (tmp_path / 'runs' / 'DAILY').mkdir(parents=True)
    # Unreadable full files prove no fallback to Step4 inputs occurs.
    (tmp_path / 'full.parquet').write_bytes(b'never read full')
    (tmp_path / 'full_calendar.parquet').write_bytes(b'never read full calendar')
    pd.DataFrame({'ts_code': ['000001.SZ'], 'trade_date': ['20160104'], 'member': [True]}).to_parquet(tmp_path / 'sample.parquet')
    pd.DataFrame({'trade_date': ['20160104', '20160105', '20160106']}).to_parquet(tmp_path / 'calendar.parquet')
    implementation = tmp_path / 'implementation.py'
    implementation.write_text("METADATA = {}\ndef compute_factor(daily_df, exchange_calendar, minute_df=None):\n    assert minute_df is None\n    assert len(exchange_calendar) == 3\n    assert daily_df['member'].all()\n    return daily_df.assign(factor_value=1.0)[['ts_code','trade_date','factor_value']]\n")
    payload = validate_prepared_daily(inputs())
    result = step3b.generate_first_run_factor_values('DAILY', 'TEST', implementation, payload, {}, csv_output_policy='no_csv')
    assert result['status'] == 'ready'
    assert result['date_count'] == 1
    validator = load('validate_step3b')
    monkeypatch.setattr(validator, 'FF', tmp_path / 'factorforge')
    validator.run_direct_code_fixture_smoke(implementation, {'columns': ['ts_code', 'trade_date', 'factor_value']},
        {'input_schema': {'daily_df': {}, 'exchange_calendar': {}}}, prepared_daily_inputs=payload)


def test_readiness_prepared_route_remains_local_only(tmp_path, monkeypatch):
    validator = load('validate_step3')
    payload = validate_prepared_daily(inputs())
    prep = {'feasibility': 'ready', 'local_input_paths': payload}
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY', raising=False)
    with pytest.raises(AssertionError, match='LOCAL_IS_ONLY'):
        validator.validate_step3_readiness_contract(prep, {}, {}, {}, workspace=tmp_path)


def scope_fixture(tmp_path):
    payload = inputs()
    payload['sample_window_actual'] = {'start': '20160104', 'end': '20160107'}
    dates = ['20160104', '20160105', '20160106', '20160107']
    pd.DataFrame({'trade_date': dates}).to_parquet(tmp_path / 'full_calendar.parquet')
    pd.DataFrame({'trade_date': dates, 'ts_code': ['000001.SZ'] * 4}).to_parquet(tmp_path / 'full.parquet')
    pd.DataFrame({'trade_date': dates[:3]}).to_parquet(tmp_path / 'calendar.parquet')
    pd.DataFrame({'trade_date': dates[:3], 'ts_code': ['000001.SZ'] * 3}).to_parquet(tmp_path / 'sample.parquet')
    return payload


def test_full_scope_checks_real_dates_not_declarations(tmp_path):
    payload = scope_fixture(tmp_path)
    assert validate_full_scope(payload, tmp_path)['session_count'] == 4
    pd.DataFrame({'trade_date': ['20160104', '20160106']}).to_parquet(tmp_path / 'full.parquet')
    with pytest.raises(ValueError, match='coverage differs'):
        validate_full_scope(payload, tmp_path)
    pd.DataFrame({'trade_date': ['20160104', '20200101']}).to_parquet(tmp_path / 'full.parquet')
    with pytest.raises(ValueError, match='exceeds'):
        validate_full_scope(payload, tmp_path)


@pytest.mark.parametrize('key', ['evaluation_daily_df_parquet', 'signal_daily_df_parquet'])
def test_full_scope_rejects_unchecked_consumption_override(tmp_path, key):
    payload = scope_fixture(tmp_path)
    pd.DataFrame({'trade_date': ['20260101']}).to_parquet(tmp_path / 'override.parquet')
    payload[key] = 'override.parquet'
    with pytest.raises(ValueError, match=f'forbid {key}'):
        validate_prepared_daily(payload)
    # Step4 invokes this check even if the declaration bypassed Step3.
    with pytest.raises(ValueError, match=f'forbid {key}'):
        validate_full_scope(payload, tmp_path)


def test_short_calendar_cannot_claim_long_window(tmp_path):
    payload = scope_fixture(tmp_path)
    payload['exchange_calendar_parquet'] = 'calendar.parquet'
    # Separate files still cannot hide the short actual calendar.
    payload['step3b_exchange_calendar_parquet'] = 'full_calendar.parquet'
    with pytest.raises(ValueError, match='does not span'):
        validate_full_scope(payload, tmp_path)


def test_aliases_rejected_except_same_scope(tmp_path):
    payload = scope_fixture(tmp_path)
    (tmp_path / 'alias.parquet').symlink_to(tmp_path / 'sample.parquet')
    payload['daily_df_parquet'] = 'alias.parquet'
    with pytest.raises(ValueError, match='alias'):
        validate_paths(payload, tmp_path)
    payload['sample_window_actual'] = dict(payload['step3b_sample_window'])
    payload['exchange_calendar_parquet'] = payload['step3b_exchange_calendar_parquet']
    assert validate_full_scope(payload, tmp_path)['session_count'] == 3
