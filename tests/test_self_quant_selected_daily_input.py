"""Actual metric-consumer checks on synthetic data, with no market claim."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
RID = 'SELECTED_DAILY_ENGINEERING_FIXTURE'
PATH_ENV = 'FACTORFORGE_EVALUATION_DAILY_INPUT_PATH'
SHA_ENV = 'FACTORFORGE_EVALUATION_DAILY_INPUT_SHA256'


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        'selected_daily_' + name, ROOT / 'skills/factor-forge-step4/scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_ROOT', str(tmp_path))
    monkeypatch.setenv('FACTORFORGE_FACTOR_WORKSPACE', str(tmp_path))
    for key in (PATH_ENV, SHA_ENV, 'FACTORFORGE_SHARED_EVALUATION_CONTEXT_PATH',
                'FACTORFORGE_EXCHANGE_CALENDAR_PATH'):
        monkeypatch.delenv(key, raising=False)
    import factor_factory.data_access.step4 as data_access
    monkeypatch.setattr(data_access, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(data_access, 'OBJ', tmp_path / 'objects')
    rows = [{'trade_date': day.strftime('%Y%m%d'), 'ts_code': f'S{code:03d}',
             'close': 10. + code, 'pct_chg': code / 100.}
            for day in pd.bdate_range('2024-01-02', periods=5) for code in range(1, 21)]
    daily = pd.DataFrame(rows)
    run = tmp_path / 'runs' / RID
    legacy = run / 'step3a_local_inputs' / f'daily_input__{RID}.parquet'
    legacy.parent.mkdir(parents=True)
    # A valid but wrong legacy file would reverse the measured IC.
    daily.assign(pct_chg=-daily.pct_chg).to_parquet(legacy, index=False)
    daily[['trade_date', 'ts_code']].assign(factor_value=daily.close).to_parquet(
        run / f'factor_values__{RID}.parquet', index=False)
    return tmp_path, daily, load_script('self_quant_adapter')


def bind(monkeypatch, path):
    monkeypatch.setenv(PATH_ENV, str(path))
    monkeypatch.setenv(SHA_ENV, hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize('fmt', ['parquet', 'csv'])
def test_actual_metrics_use_selected_prices_over_opposite_legacy_snapshot(fixture, monkeypatch, fmt):
    root, daily, adapter = fixture
    selected = root / ('explicit-input.' + fmt)
    getattr(daily, 'to_' + fmt)(selected, index=False)
    bind(monkeypatch, selected)
    payload = adapter.run_self_quant_quick(RID)
    assert payload['ic_summary']['rank_ic_mean'] == pytest.approx(1.)
    # Preserve old standalone calls when no explicit input was provided.
    monkeypatch.delenv(PATH_ENV)
    monkeypatch.delenv(SHA_ENV)
    assert adapter.run_self_quant_quick(RID)['ic_summary']['rank_ic_mean'] == pytest.approx(-1.)


@pytest.mark.parametrize('failure', ['missing', 'changed', 'missing_hash'])
def test_explicit_binding_failure_never_uses_existing_legacy_snapshot(fixture, monkeypatch, failure):
    root, daily, adapter = fixture
    selected = root / 'explicit-input.csv'
    daily.to_csv(selected, index=False)
    bind(monkeypatch, selected)
    if failure == 'missing':
        selected.unlink()
    elif failure == 'changed':
        daily.assign(pct_chg=-daily.pct_chg).to_csv(selected, index=False)
    else:
        monkeypatch.delenv(SHA_ENV)
    with pytest.raises((ValueError, FileNotFoundError), match='explicit evaluation daily input'):
        adapter.run_self_quant_quick(RID)


def test_in_place_change_during_actual_read_is_rejected(fixture, monkeypatch):
    root, daily, adapter = fixture
    selected = root / 'explicit-input.csv'
    daily.to_csv(selected, index=False)
    bind(monkeypatch, selected)
    original_read = pd.read_csv

    def changing_read(stream, **kwargs):
        result = original_read(stream, **kwargs)
        with selected.open('ab') as out:
            out.write(b'\n')
        return result

    monkeypatch.setattr(pd, 'read_csv', changing_read)
    with pytest.raises(ValueError, match='changed during read'):
        adapter.run_self_quant_quick(RID)


def test_step4_passes_actual_evaluation_selection_and_overrides_backend_config(tmp_path, monkeypatch):
    step4 = load_script('run_step4')
    selected = tmp_path / 'actual-evaluation-input.csv'
    selected.write_text('ts_code,trade_date,close,pct_chg\nS001,20240102,10,0.1\n')
    observed = []

    def process(report_id, backend, script, payload_path, config, **kwargs):
        observed.append(config['env'])
        payload_path.write_text(json.dumps({'status': 'failed', 'summary': 'explicit unit-test process boundary'}))
        return 1, 'No backend process ran in this dispatch-only test.'

    monkeypatch.setattr(step4, 'run_backend_script', process)
    step4.write_backend_payloads(RID, [{
        'backend': 'self_quant_analyzer', 'payload_path': str(tmp_path / 'payload.json'),
        'backend_config': {'env': {PATH_ENV: '/wrong/snapshot.csv', SHA_ENV: '0' * 64}},
    }], evaluation_daily_path=selected)
    assert len(observed) == 1
    assert observed[0][PATH_ENV] == str(selected.resolve())
    assert observed[0][SHA_ENV] == hashlib.sha256(selected.read_bytes()).hexdigest()
