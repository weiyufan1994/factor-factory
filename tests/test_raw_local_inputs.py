"""Synthetic Parquet transport through real Step3A, Step3B and Step4 consumers."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from factor_factory.raw_local_inputs import digest, validate_raw_local_inputs

ROOT = Path(__file__).resolve().parents[1]


def load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    dates = ['20260105', '20260106', '20260107']
    symbols = ['000001.SZ', '000002.SZ']
    daily = pd.DataFrame([{'ts_code': symbol, 'trade_date': day, 'close': float(i + 10)}
                          for i, day in enumerate(dates) for symbol in symbols])
    minute = daily.assign(trade_time='15:00:00', vol=10.0)
    manifest = {'schema': 'factorforge_raw_local_snapshot_v1',
                'scope': 'bounded_local_is_engineering', 'symbols': symbols,
                'calendar_dates': dates, 'signal_timing': 'after_close_next_session',
                'source_identity': {'catalog_sha256': 'a' * 64, 'daily_dataset_version': 'synthetic_v1',
                                    'minute_dataset_version': 'synthetic_v1', 'daily_price_basis': 'synthetic'},
                'step3b_sample': {'symbols': symbols[:1], 'calendar_dates': dates[:1],
                                 'budget': {'max_symbols': 1, 'max_calendar_days': 1, 'max_minute_rows': 1}}}
    for role, frame in [('daily', daily), ('minute', minute)]:
        path = tmp_path / f'{role}.parquet'
        frame.to_parquet(path, index=False)
        manifest[role] = {'path': str(path), 'sha256': digest(path)}
        path = tmp_path / f'sample_{role}.parquet'
        frame.iloc[:1].to_parquet(path, index=False)
        manifest['step3b_sample'][role] = {'path': str(path), 'sha256': digest(path)}
    path = tmp_path / 'manifest.json'

    def bind():
        write(path, manifest)
        return {'input_mode': 'raw_local_snapshot', 'snapshot_manifest_path': str(path),
                'snapshot_manifest_sha256': digest(path)}
    return manifest, bind


def test_scope_hash_and_real_sample_is_separate(snapshot, monkeypatch):
    manifest, bind = snapshot
    declaration = validate_raw_local_inputs(bind())
    reads = []
    original = pd.read_parquet
    def track(path, *args, **kwargs):
        reads.append(str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(pd, 'read_parquet', track)
    sample = validate_raw_local_inputs(declaration, sample=True)
    assert reads == [manifest['step3b_sample'][r]['path'] for r in ('daily', 'minute')]
    assert sample['calendar_dates'] == ['20260105']
    assert sample['minute_df_parquet'] == manifest['step3b_sample']['minute']['path']


@pytest.mark.parametrize('mutation', ['hash', 'future', 'late', 'scope', 'budget', 'sample_values'])
def test_frozen_raw_rejects_invalid_data(snapshot, mutation):
    manifest, bind = snapshot
    if mutation == 'budget':
        manifest['step3b_sample']['budget']['max_minute_rows'] = 0
    else:
        role = manifest['step3b_sample']['minute'] if mutation == 'sample_values' else manifest['minute']
        path = Path(role['path'])
        frame = pd.read_parquet(path)
        if mutation == 'future':
            frame.loc[0, 'trade_time'] = '2026-01-06 15:00:00'
        elif mutation == 'late':
            frame.loc[0, 'trade_time'] = '15:01:00'
        elif mutation == 'scope':
            frame = frame.iloc[1:]
        else:
            frame.loc[0, 'close'] += 1
        frame.to_parquet(path, index=False)
        if mutation != 'hash':
            role['sha256'] = digest(path)
    with pytest.raises((ValueError, AssertionError)):
        validate_raw_local_inputs(bind())


def test_input_override_derived_and_hosted_are_rejected(snapshot, monkeypatch):
    _, bind = snapshot
    for extra in [{'minute_df_parquet': '/wrong.parquet'}, {'derived_state_root': '/states'},
                  {'step4_data_contract': {'full_queries': {'minute_bar': {}}}}]:
        with pytest.raises(ValueError):
            validate_raw_local_inputs({**bind(), **extra})
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    with pytest.raises(ValueError, match='local_is_only'):
        validate_raw_local_inputs(bind())


def test_actual_step3a_generation_and_readiness_without_api(snapshot, tmp_path, monkeypatch):
    _, bind = snapshot
    helper = load('tests/test_standard_formula_field_modes.py', 'raw_test_master_helper')
    master = helper.build_master.__wrapped__(monkeypatch)(fields=['minute_bar:close', 'minute_bar:vol'])
    master['sample_window'] = {'start': '20260105', 'end': '20260107'}
    step3 = load('skills/factor-forge-step3/scripts/run_step3.py', 'raw_test_step3')
    obj = tmp_path / 'study/objects'
    write(obj / f'factor_spec_master/factor_spec_master__{helper.RID}.json', master)
    write(obj / f'alpha_idea_master/alpha_idea_master__{helper.RID}.json', {})
    monkeypatch.setattr(step3, 'OBJ', obj)
    monkeypatch.setattr(step3, 'FF', obj.parent)
    monkeypatch.setattr(step3, 'WORKSPACE', tmp_path)
    # Review semantics are outside this input-transport regression; retain the
    # existing Stage2 fixture's declared route, without mocking data validation.
    monkeypatch.setattr(step3, 'validated_measurement_program_for_step3',
                        lambda *a, **k: {'implementation': {'route': 'direct_code'}})
    def no_api(*args, **kwargs):
        raise AssertionError('unexpected data API fallback')
    monkeypatch.setattr(step3, 'resolve_data_api_dataset', no_api)
    monkeypatch.setattr(step3, 'fetch_data_api_dataset', no_api)
    prep, qcfg, plan = step3.build_step3a(helper.RID, raw_local_inputs=bind())
    assert prep['feasibility'] == 'ready'
    assert prep['local_input_paths']['input_mode'] == 'raw_local_snapshot'
    validator = load('skills/factor-forge-step3/scripts/validate_step3.py', 'raw_test_validator')
    validator.validate_step3_readiness_contract(
        prep, qcfg, plan, {'step3a_ready': True, 'step3b_ready': False}, workspace=tmp_path)
    with pytest.raises(ValueError, match='mutually exclusive'):
        step3.build_step3a(helper.RID, prepared_local_inputs={}, raw_local_inputs=bind())


def test_step4_consumes_same_frozen_inputs_and_never_fetches(snapshot, tmp_path):
    manifest, bind = snapshot
    step4 = load('skills/factor-forge-step4/scripts/run_step4.py', 'raw_test_step4')
    local = validate_raw_local_inputs(bind())
    def no_api(*args, **kwargs):
        raise AssertionError('unexpected data API fallback')
    kwargs = dict(report_id='RAW_TEST', contract={}, run_dir=tmp_path, local_inputs=local,
                  force_contract_inputs=False, evo_pre_release=False, materializer=no_api)
    resolved, _ = step4.materialize_step4_contract_inputs_if_required(**kwargs)
    assert resolved['minute_df_parquet'] == manifest['minute']['path']
    assert len(pd.read_parquet(resolved['minute_df_parquet'])) == 6
    with pytest.raises(ValueError, match='API/EVO'):
        step4.materialize_step4_contract_inputs_if_required(**{**kwargs, 'force_contract_inputs': True})
    Path(manifest['minute']['path']).unlink()
    with pytest.raises(ValueError):
        step4.materialize_step4_contract_inputs_if_required(**kwargs)


def test_real_step3b_uses_sample_and_preserves_full_handoff(snapshot, tmp_path):
    manifest, bind = snapshot
    rid = 'RAW_SNAPSHOT_EXECUTION_TEST'
    study = tmp_path / 'study'
    code = study / 'generated_code' / rid
    impl = code / f'factor_impl__{rid}.py'
    source = '''from factor_factory.factors import PriceVolumeFactor
class Example(PriceVolumeFactor):
    name = "raw_snapshot_test"
    input_columns = {"daily_df": ("ts_code", "trade_date"), "minute_df": ("ts_code", "trade_date", "close")}
    def compute(self, inputs):
        assert len(inputs["daily_df"]) == len(inputs["minute_df"]) == 1
        return inputs["daily_df"][["ts_code", "trade_date"]].assign(factor_value=1.0)
FACTOR = Example()
'''
    code.mkdir(parents=True)
    impl.write_text(source)
    identity = {'report_id': rid, 'factor_id': rid, 'implementation_mode': 'direct_code',
                'branch_id': 'main', 'source_type': 'canonical_formula', 'spec_hash': 'synthetic',
                'code_contract_hash': 'synthetic_contract'}
    contract = {'source_code': source, 'code_contract_hash': 'synthetic_contract',
                'input_schema': {'daily_df': ['ts_code', 'trade_date'], 'minute_df': ['ts_code', 'trade_date', 'close']},
                'output_schema': {'index': ['datetime', 'instrument'], 'columns': ['factor_value']}}
    write(study / f'objects/factor_spec_master/factor_spec_master__{rid}.json',
          {'report_id': rid, 'factor_id': rid, 'implementation_mode': 'direct_code',
           'artifact_identity': identity, 'implementation_contract': {'code_contract': contract}})
    local = validate_raw_local_inputs(bind())
    write(study / f'objects/data_prep_master/data_prep_master__{rid}.json',
          {'report_id': rid, 'feasibility': 'ready', 'local_input_paths': local})
    env = {k: v for k, v in os.environ.items() if not k.startswith('FACTORFORGE_')}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', FACTORFORGE_REPO_ROOT=str(ROOT),
               FACTORFORGE_ROOT=str(tmp_path / 'canonical'), FACTORFORGE_DEBUG_ROOT=str(study),
               FACTORFORGE_ALLOW_DIRECT_STEP='1', FACTORFORGE_LOCAL_IS_ONLY='1')
    result = subprocess.run([sys.executable, str(ROOT / 'skills/factor-forge-step3/scripts/run_step3b.py'),
                             '--report-id', rid, '--csv-output-policy', 'no_csv'],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    handoff = json.loads((study / f'objects/handoff/handoff_to_step4__{rid}.json').read_text())
    assert handoff['local_input_paths'] == local
    assert handoff['first_run_outputs']['status'] == 'ready'
    assert handoff['local_input_paths']['minute_df_parquet'] == manifest['minute']['path']


def test_ultimate_cli_exposes_explicit_raw_route():
    from factor_factory.ultimate_loop.cli import build_parser
    args = build_parser().parse_args(['--report-id', 'SYNTHETIC', '--local-is-only', '--raw-local-inputs', 'raw.json'])
    assert args.raw_local_inputs == 'raw.json'
    with pytest.raises(SystemExit):
        build_parser().parse_args(['--report-id', 'SYNTHETIC', '--raw-local-inputs', 'raw.json',
                                   '--prepared-local-inputs', 'derived.json'])


def test_ultimate_dry_plan_forwards_raw_declaration(tmp_path):
    """Actual orchestration plan, no factor or market execution."""
    code = '''
import json
from pathlib import Path
from factor_factory.ultimate_loop.cli import parse_args
from factor_factory.ultimate_loop.runner import _run_formal_ultimate
from factor_factory.research_workspace import build_workspace_manifest, write_workspace_manifest, workspace_manifest_path
root = Path.cwd() / 'study'
manifest = build_workspace_manifest(repo_root=Path(__import__('factor_factory').__file__).parent.parent,
    factorforge_root=Path.cwd(), factor_id='raw_boundary', research_id='dry', root_report_id='RAW_BOUNDARY')
write_workspace_manifest(workspace_manifest_path(root), manifest)
args = parse_args(['--report-id', 'RAW_BOUNDARY', '--factor-workspace', str(root),
    '--local-is-only', '--dry-run', '--start-step', '3', '--end-step', '3',
    '--raw-local-inputs', '/synthetic/raw-declaration.json', '--council-mode', 'off'])
assert _run_formal_ultimate(args) == 0
proof = json.loads((root / 'objects/runtime_context/ultimate_run_report__RAW_BOUNDARY.json').read_text())
assert proof['status'] == 'DRY_RUN'
command = next(c['command'] for c in proof['commands'] if c['name'] == 'run_step3')
assert command[-2:] == ['--raw-local-inputs', '/synthetic/raw-declaration.json']
assert '--prepared-local-inputs' not in command
'''
    env = {k: v for k, v in os.environ.items() if not k.startswith('FACTORFORGE_')}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
