"""Real prepared-input -> generated class -> Step3B/Step4 loading boundaries.

Prices, membership and expectations are tiny synthetic arithmetic fixtures.
No market reads, wrapper injection or mocked factor loading/argument binding.
"""
from __future__ import annotations

import importlib.util
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_stage(stage, script):
    path = ROOT / 'skills' / f'factor-forge-step{stage}' / 'scripts' / script
    spec = importlib.util.spec_from_file_location(f'named_inputs_{script[:-3]}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepared_fixture(tmp_path, monkeypatch, *, use_helper=True, layout='legacy'):
    # The real debug entry owns only this synthetic workspace.
    for key in list(__import__('os').environ):
        if key.startswith('FACTORFORGE_'):
            monkeypatch.delenv(key)
    ff = tmp_path / 'factorforge'
    ff.mkdir()
    files = tmp_path if layout == 'legacy' else ff
    monkeypatch.setenv('FACTORFORGE_ROOT', str(ff))
    monkeypatch.setenv('FACTORFORGE_DEBUG_ROOT', str(ff))
    monkeypatch.setenv('FACTORFORGE_ALLOW_DIRECT_STEP', '1')
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    monkeypatch.setenv('MPLCONFIGDIR', str(tmp_path / 'matplotlib'))
    if layout == 'environment':
        monkeypatch.setenv('FACTORFORGE_FACTOR_WORKSPACE', str(ff))
    elif layout == 'manifest':
        from factor_factory.runtime_context import FactorForgeContext
        manifest = FactorForgeContext(repo_root=ROOT, workspace_root=tmp_path,
            factorforge_root=tmp_path / 'shared', factor_workspace=ff).build_manifest('NAMED_ROLES')
        (ff / 'runtime_manifest.json').write_text(json.dumps(manifest))
    days = ['20200102', '20200103', '20200106', '20200107']
    daily = pd.DataFrame({'trade_date': days, 'ts_code': ['000001.SZ'] * 4,
                          'close': [1., np.nan, 3., 4.], 'pct_chg': [1., 1., 1., 1.]})
    members = pd.DataFrame({'trade_date': [*days, days[0]],
                            'ts_code': ['000001.SZ'] * 4 + ['000002.SZ'],
                            'eligible': [True] * 5})
    for name, frame in [('full', daily), ('sample', daily.iloc[:2]),
                        ('calendar', pd.DataFrame({'trade_date': days})),
                        ('sample_calendar', pd.DataFrame({'trade_date': days[:2]})),
                        ('members', members), ('sample_members', members.loc[members.trade_date <= days[1]])]:
        frame.to_parquet(files / (name + '.parquet'), index=False)
    payload = dict(input_mode='daily_only', prepared_input_kind='prepared_daily_v1',
                   daily_df_parquet='full.parquet', step3b_daily_df_parquet='sample.parquet',
                   exchange_calendar_parquet='calendar.parquet',
                   step3b_exchange_calendar_parquet='sample_calendar.parquet',
                   sample_window_actual={'start': days[0], 'end': days[-1]},
                   step3b_sample_window={'start': days[0], 'end': days[1]},
                   additional_input_paths={'formation_membership': 'members.parquet'},
                   step3b_additional_input_paths={'formation_membership': 'sample_members.parquet'})
    if layout != 'legacy':
        # Modern manifests resolve primary selectors before dispatch. The new
        # auxiliary selectors and ordinary helpers live in the factor workspace.
        for key in ('daily_df_parquet', 'step3b_daily_df_parquet',
                    'exchange_calendar_parquet', 'step3b_exchange_calendar_parquet'):
            payload[key] = str(files / payload[key])
    stage3a = load_stage(3, 'run_step3.py')
    payload = stage3a.validate_prepared_local_inputs(payload)
    helper = '''def measure(inputs):
    from implementation.constants import SCALE
    daily = inputs['daily_df']
    calendar = inputs['exchange_calendar']
    members = inputs['formation_membership']
    values = members.merge(daily, on=['ts_code', 'trade_date'], how='left', validate='one_to_one')
    values['factor_value'] = (values.close * SCALE + len(calendar)).where(values.eligible).astype('float64')
    values['datetime'] = pd.to_datetime(values.trade_date, format='%Y%m%d')
    return values.rename(columns={'ts_code': 'instrument'}).set_index(['datetime', 'instrument'])[['factor_value']].sort_index()
'''
    package = files / 'implementation'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'constants.py').write_text('SCALE = 2.\n')
    (package / 'local_math.py').write_text('import pandas as pd\n' + helper)
    body = ('from implementation.local_math import measure\n' if use_helper else
            helper.replace('    from implementation.constants import SCALE', '    SCALE = 2.'))
    source = 'import pandas as pd\nfrom factor_factory.factors import PriceVolumeFactor\n' + body + '''
class ArithmeticFactor(PriceVolumeFactor):
    name = 'SYNTHETIC_NAMED_ROLES'
    input_columns = {'daily_df': ('ts_code', 'trade_date', 'close'),
                     'exchange_calendar': ('trade_date',),
                     'formation_membership': ('ts_code', 'trade_date', 'eligible')}
    def compute(self, inputs):
        return measure(inputs)
FACTOR = ArithmeticFactor()
'''
    contract = {'source_code': source, 'entrypoint': 'FACTOR',
        'output_schema': {'index': ['datetime', 'instrument'], 'columns': ['factor_value']},
        'input_schema': {
        'daily_df': ['ts_code', 'trade_date', 'close'],
        'exchange_calendar': ['trade_date'],
        'formation_membership': ['ts_code', 'trade_date', 'eligible']},
        'performance_scope': {'formal_step4_full_window_execution_allowed': True}}
    fsm = {'report_id': 'NAMED_ROLES', 'factor_id': 'SYNTHETIC_NAMED_ROLES',
           'implementation_mode': 'direct_code',
           'artifact_identity': {'implementation_mode': 'direct_code', 'spec_hash': 'synthetic_named_roles_spec'},
           'implementation_contract': {'mode': 'direct_code', 'code_contract': contract}}
    stage3 = load_stage(3, 'run_step3b.py')
    _plan, generated, _qlib, _hybrid = stage3.build_direct_code_artifacts('NAMED_ROLES', {}, fsm, {})
    path = ff / 'generated_code' / 'factor.py'
    path.parent.mkdir()
    path.write_text(generated)
    return ff, payload, contract, fsm, path


def bind_manifest(stage, ff):
    path = ff / 'runtime_manifest.json'
    if path.is_file():
        stage.apply_runtime_manifest(str(path))


def assert_oracle(frame, *, sample):
    frame = frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    keys = [('000001.SZ', '20200102'), ('000001.SZ', '20200103')]
    expected = [4., np.nan] if sample else [6., np.nan, 10., 12.]
    if not sample:
        keys += [('000001.SZ', '20200106'), ('000001.SZ', '20200107')]
    keys += [('000002.SZ', '20200102')]
    expected += [np.nan]
    assert list(zip(frame.ts_code, frame.trade_date)) == keys
    assert frame.factor_value.dtype == np.dtype('float64')
    np.testing.assert_allclose(frame.factor_value, expected, rtol=0, atol=0, equal_nan=True)


@pytest.mark.parametrize('layout', ['legacy', 'environment', 'manifest'])
@pytest.mark.parametrize('use_helper', [False, True])
def test_real_step3b_prepared_roles_and_workspace_import(tmp_path, monkeypatch, use_helper, layout):
    ff, payload, contract, _fsm, path = prepared_fixture(tmp_path, monkeypatch, use_helper=use_helper, layout=layout)
    stage3 = load_stage(3, 'run_step3b.py')
    bind_manifest(stage3, ff)
    (ff / 'runs/NAMED_ROLES').mkdir(parents=True)
    before = list(sys.path)
    result = stage3.generate_first_run_factor_values('NAMED_ROLES', 'SYNTHETIC_NAMED_ROLES',
        path, payload, {}, csv_output_policy='no_csv', code_contract=contract)
    assert result['status'] == 'ready'
    assert_oracle(pd.read_parquet(ff / 'runs/NAMED_ROLES/step3b_sample_factor_values__NAMED_ROLES.parquet'), sample=True)
    assert sys.path == before
    assert not any(name == 'implementation' or name.startswith('implementation.') for name in sys.modules)
    validator = load_stage(3, 'validate_step3b.py')
    bind_manifest(validator, ff)
    validator.run_direct_code_fixture_smoke(path, {}, contract, prepared_daily_inputs=payload)
    assert sys.path == before
    assert not any(name == 'implementation' or name.startswith('implementation.') for name in sys.modules)


@pytest.mark.parametrize('layout', ['legacy', 'environment', 'manifest'])
@pytest.mark.parametrize('route', ['class', 'function'])
def test_real_step3a_prepared_bindings_and_readiness(tmp_path, monkeypatch, layout, route):
    ff, payload, _contract, fsm, _path = prepared_fixture(tmp_path, monkeypatch, layout=layout)
    if route == 'function':
        _contract['entrypoint'] = 'compute_factor'
        _contract['output_schema'] = {'columns': ['ts_code', 'trade_date', 'factor_value']}
        _contract['source_code'] = _contract['source_code'].split('class ArithmeticFactor')[0] + '''
def compute_factor(daily_df, minute_df=None, *, exchange_calendar, formation_membership):
    return measure(dict(daily_df=daily_df, exchange_calendar=exchange_calendar,
                        formation_membership=formation_membership))
'''
    # Supply the unrelated structural Step2 requirement, explicitly as a
    # synthetic fixture; do not mock the Step3A builder or input validation.
    from factor_factory.measurement_program import measurement_program_template
    program = measurement_program_template(
        placeholder='synthetic arithmetic integration fixture', implementation_route='direct_code')
    for index, candidate in enumerate(program['model_selection']['candidate_models']):
        candidate.update(model_family=f'synthetic fixture model {index}',
            mechanism_equation_or_functional=f'synthetic_object_{index} = arithmetic_{index}(inputs)',
            target_functional=program['observation_and_estimation']['estimand'] if index == 0 else f'synthetic estimand {index}',
            market_outcome_projection=program['market_outcome_projection']['projection_equation_or_map'] if index == 0 else f'synthetic projection {index}',
            observation_mapping=program['observation_and_estimation']['observation_map'] if index == 0 else f'synthetic observation {index}')
    fsm['mechanism_conditioned_measurement_program'] = program
    fsm['canonical_spec'] = {'mechanism_conditioned_measurement_program': program}
    for kind, value in [('factor_spec_master', fsm), ('alpha_idea_master', {})]:
        output = ff / 'objects' / kind / f'{kind}__NAMED_ROLES.json'
        output.parent.mkdir(parents=True)
        output.write_text(json.dumps(value))
    handoff = ff / 'objects/handoff/handoff_to_step3__NAMED_ROLES.json'
    handoff.parent.mkdir(parents=True)
    handoff.write_text(json.dumps({'mechanism_conditioned_measurement_program': program}))
    stage3a = load_stage(3, 'run_step3.py')
    bind_manifest(stage3a, ff)
    prep, qcfg, impl = stage3a.build_step3a('NAMED_ROLES', csv_output_policy='no_csv', prepared_local_inputs=payload)
    assert prep['local_input_paths'] == payload
    validator = load_stage(3, 'validate_step3.py')
    bind_manifest(validator, ff)
    validator.validate_step3_readiness_contract(prep, qcfg, impl, {})
    # Exercise the real gate that Ultimate calls, not just its readiness helper.
    # Only entrypoint was supplied above: Step3A must mirror its function_name.
    assert impl['code_contract']['function_name'] == _contract['entrypoint']
    validator.validate_direct_code_source_contract(impl)
    for kind, name, value in [
        ('data_prep_master', 'data_prep_master', prep),
        ('data_prep_master', 'qlib_adapter_config', qcfg),
        ('implementation_plan_master', 'implementation_plan_master', impl),
        ('handoff', 'handoff_to_step4', {'report_id': 'NAMED_ROLES', 'step3a_ready': True, 'step3b_ready': False}),
        ('validation', 'data_feasibility_report', {'report_id': 'NAMED_ROLES', 'final_result': prep['feasibility']}),
    ]:
        target = ff / 'objects' / kind / f'{name}__NAMED_ROLES.json'
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_text(json.dumps(value))
    command = [sys.executable, str(ROOT / 'skills/factor-forge-step3/scripts/validate_step3.py'),
               '--report-id', 'NAMED_ROLES', '--require-ready']
    if layout == 'manifest':
        command.extend(['--manifest', str(ff / 'runtime_manifest.json')])
    result = subprocess.run(command, env=os.environ.copy(), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'RESULT: PASS' in result.stdout


def source_plan(source='FACTOR = object()\n', entrypoint='FACTOR'):
    return {'code_contract': {
        'code_contract_version': 'factorforge_direct_code_contract_v1',
        'entrypoint': entrypoint, 'function_name': entrypoint,
        'source_code': source, 'code_hash': hashlib.sha256(source.encode()).hexdigest(),
        'source_derivation': {'not_fallback': True, 'derivation': 'source_code_preserved_from_step2_direct_code_contract'},
        'imports': ['pandas'], 'input_schema': {'daily_df': ['ts_code', 'trade_date', 'close']},
        'output_schema': {'index': ['datetime', 'instrument'], 'columns': ['factor_value']},
    }}


@pytest.mark.parametrize('source,entrypoint', [
    ('# FACTOR = Fake()\n', 'FACTOR'),
    ('message = "FACTOR = Fake()"\n', 'FACTOR'),
    ('def nested():\n    FACTOR = object()\n', 'FACTOR'),
    ('def compute_factor(daily_df):\n    return daily_df\n', 'FACTOR'),
    ('FACTOR = object()\n', 'compute_factor'),
    ('# def compute_factor(daily_df):\npass\n', 'compute_factor'),
    ('def nested():\n    def compute_factor(daily_df):\n        return daily_df\n', 'compute_factor'),
    ('async def compute_factor(daily_df):\n    return daily_df\n', 'compute_factor'),
    ('FACTOR = object()\ndef compute_factor(daily_df):\n    return daily_df\n', 'compute_factor'),
    ('FACTOR = (\n', 'FACTOR'),
    ('FACTOR = object()\nreturn 1\n', 'FACTOR'),
    ('FACTOR = object()\n', 'arbitrary_name'),
])
def test_step3_contract_rejects_forged_or_mismatched_source_entry(source, entrypoint):
    validator = load_stage(3, 'validate_step3.py')
    with pytest.raises(AssertionError, match='BLOCK_DIRECT_CODE_SOURCE_CONTRACT'):
        validator.validate_direct_code_source_contract(source_plan(source, entrypoint))


@pytest.mark.parametrize('change', [
    {'function_name': 'compute_factor'}, {'code_hash': '0' * 64},
    {'source_derivation': {'not_fallback': False}},
    {'output_schema': {'index': ['instrument', 'datetime'], 'columns': ['factor_value']}},
    {'output_schema': {'index': ['datetime', 'instrument'], 'columns': ['factor_value', 'extra']}},
    {'output_schema': {'columns': ['factor_value']}},
    {'output_schema': {'columns': ['ts_code', 'trade_date', 'close']}},
])
def test_step3_contract_retains_hash_provenance_and_output_gates(change):
    plan = source_plan()
    plan['code_contract'].update(copy.deepcopy(change))
    with pytest.raises(AssertionError, match='BLOCK_DIRECT_CODE_SOURCE_CONTRACT'):
        load_stage(3, 'validate_step3.py').validate_direct_code_source_contract(plan)


def test_step3_structure_never_executes_source_and_runtime_still_rejects_fake_class(tmp_path):
    validator = load_stage(3, 'validate_step3.py')
    validator.validate_direct_code_source_contract(source_plan('FACTOR = object()\nraise RuntimeError("must not execute")\n'))
    # A source declaration is not a runtime type certificate. The same gate
    # shared by Step3B/4 must reject it before attempting any factor calculation.
    from factor_factory.implementation_runtime import implementation_callable, load_implementation
    path = tmp_path / 'fake.py';path.write_text('FACTOR = object()\n')
    with pytest.raises(TypeError, match='BaseFactor instance'):
        implementation_callable(load_implementation(path))


@pytest.mark.parametrize('body', [
    "return f[['ts_code', 'trade_date', 'close']]",
    "return f[['ts_code', 'trade_date']].assign(factor_value='wrong dtype')",
])
def test_class_with_wrong_actual_output_fails_real_step3b_gate(tmp_path, body):
    source = '''from factor_factory.factors import PriceVolumeFactor
class Bad(PriceVolumeFactor):
    name = 'SYNTHETIC_BAD_OUTPUT'
    def compute(self, inputs):
        f = inputs['daily_df']
        BODY
FACTOR = Bad()
'''.replace('BODY', body)
    plan = source_plan(source)
    load_stage(3, 'validate_step3.py').validate_direct_code_source_contract(plan)
    path = tmp_path / 'bad.py';path.write_text(source)
    with pytest.raises((AssertionError, ValueError), match='factor_value|numeric real dtype'):
        load_stage(3, 'validate_step3b.py').run_direct_code_fixture_smoke(
            path, plan['code_contract']['output_schema'], plan['code_contract'])


def dispatch_step4(tmp_path, monkeypatch, fixture):
    ff, payload, _contract, fsm, path = fixture
    dpm = {'report_id': 'NAMED_ROLES', 'factor_id': 'SYNTHETIC_NAMED_ROLES',
           'sample_window': payload['sample_window_actual'], 'field_mapping': {'close': 'close'},
           'data_sources': ['synthetic_local_frames'], 'sparse_signal_allowed': True,
           'local_input_paths': payload}
    handoff = {'report_id': 'NAMED_ROLES', 'implementation_path': str(path),
               'local_input_paths': payload, 'evaluation_plan': {'backends': []}}
    for kind, value in [('factor_spec_master', fsm), ('data_prep_master', dpm), ('handoff', handoff)]:
        name = 'handoff_to_step4' if kind == 'handoff' else kind
        output = ff / 'objects' / kind / f'{name}__NAMED_ROLES.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value))
    canonical = tmp_path / 'canonical'
    canonical.mkdir(exist_ok=True)
    monkeypatch.setenv('FACTORFORGE_ROOT', str(canonical))
    stage4 = load_stage(4, 'run_step4.py')
    manifest_args = ['--manifest', str(ff / 'runtime_manifest.json')] if (ff / 'runtime_manifest.json').is_file() else []
    monkeypatch.setattr(sys, 'argv', ['run_step4.py', '--report-id', 'NAMED_ROLES', *manifest_args])
    before = list(sys.path)
    stage4.main()
    assert sys.path == before
    assert not any(name == 'implementation' or name.startswith('implementation.') for name in sys.modules)
    return ff / 'runs/NAMED_ROLES'


@pytest.mark.parametrize('layout', ['legacy', 'environment', 'manifest'])
@pytest.mark.parametrize('use_helper', [False, True])
def test_real_step4_main_loads_full_named_roles(tmp_path, monkeypatch, use_helper, layout):
    fixture = prepared_fixture(tmp_path, monkeypatch, use_helper=use_helper, layout=layout)
    run = dispatch_step4(tmp_path, monkeypatch, fixture)
    assert_oracle(pd.read_parquet(run / 'factor_values__NAMED_ROLES.parquet'), sample=False)


@pytest.mark.parametrize('mutation,reason', [
    ('missing_role', 'missing factor input: formation_membership'),
    ('missing_file', 'INPUT_ROLE_MISSING'),
    ('primary_conflict', 'INPUT_ROLE_DUPLICATE'),
    ('outside_window', 'INPUT_ROLE_WINDOW'),
])
def test_real_step4_errors_do_not_execute_with_inferred_roles(tmp_path, monkeypatch, mutation, reason):
    fixture = prepared_fixture(tmp_path, monkeypatch)
    ff, payload, _contract, _fsm, _path = fixture
    if mutation == 'missing_role':
        payload['additional_input_paths'] = {}
        payload['step3b_additional_input_paths'] = {}
    elif mutation == 'missing_file':
        payload['additional_input_paths']['formation_membership'] = 'absent.parquet'
    elif mutation == 'outside_window':
        frame = pd.read_parquet(tmp_path / 'members.parquet')
        frame.loc[0, 'trade_date'] = '20200108'
        frame.to_parquet(tmp_path / 'members.parquet', index=False)
    else:
        payload['additional_input_paths']['daily_df'] = 'members.parquet'
        payload['step3b_additional_input_paths']['daily_df'] = 'sample_members.parquet'
    before = list(sys.path)
    try:
        dispatch_step4(tmp_path, monkeypatch, fixture)
    except (ValueError, SystemExit) as exc:
        assert reason in str(exc)
    diagnostics = ff / 'objects/validation/factor_run_diagnostics__NAMED_ROLES.json'
    assert reason in diagnostics.read_text()
    assert not (ff / 'runs/NAMED_ROLES/factor_values__NAMED_ROLES.parquet').exists()
    assert sys.path == before
    assert not any(name == 'implementation' or name.startswith('implementation.') for name in sys.modules)


@pytest.mark.parametrize('layout', ['legacy', 'environment', 'manifest'])
@pytest.mark.parametrize('changed', ['frame', 'helper'])
def test_step4_cache_binds_auxiliary_data_and_helper_source(tmp_path, monkeypatch, changed, layout):
    fixture = prepared_fixture(tmp_path, monkeypatch, layout=layout)
    files = tmp_path if layout == 'legacy' else fixture[0]
    run = dispatch_step4(tmp_path, monkeypatch, fixture)
    assert_oracle(pd.read_parquet(run / 'factor_values__NAMED_ROLES.parquet'), sample=False)
    dispatch_step4(tmp_path, monkeypatch, fixture)
    meta_path = run / 'run_metadata__NAMED_ROLES.json'
    assert json.loads(meta_path.read_text())['step4_factor_io_profile']['recomputed_factor'] is False
    if changed == 'frame':
        frame = pd.read_parquet(files / 'members.parquet')
        frame.loc[frame.trade_date == '20200106', 'eligible'] = False
        frame.to_parquet(files / 'members.parquet', index=False)
    else:
        (files / 'implementation/constants.py').write_text('SCALE = 3.\n')
    dispatch_step4(tmp_path, monkeypatch, fixture)
    assert json.loads(meta_path.read_text())['step4_factor_io_profile']['recomputed_factor'] is True
    actual = pd.read_parquet(run / 'factor_values__NAMED_ROLES.parquet')
    value = actual.loc[(actual.ts_code == '000001.SZ') & (actual.trade_date == '20200106'), 'factor_value'].iloc[0]
    assert np.isnan(value) if changed == 'frame' else value == 13.


@pytest.mark.parametrize('mutation,reason', [
    ('missing_role', 'missing factor input: formation_membership'),
    ('missing_sample', 'INPUT_ROLE_MISSING'),
    ('missing_file', 'INPUT_ROLE_MISSING'),
    ('primary_conflict', 'INPUT_ROLE_DUPLICATE'),
])
def test_step3b_role_errors_do_not_infer_membership(tmp_path, monkeypatch, mutation, reason):
    ff, payload, contract, _fsm, path = prepared_fixture(tmp_path, monkeypatch)
    if mutation == 'missing_role':
        payload['additional_input_paths'] = {}
        payload['step3b_additional_input_paths'] = {}
    elif mutation == 'missing_sample':
        payload['step3b_additional_input_paths'] = {}
    elif mutation == 'missing_file':
        payload['step3b_additional_input_paths']['formation_membership'] = 'absent.parquet'
    else:
        payload['additional_input_paths']['exchange_calendar'] = 'calendar.parquet'
        payload['step3b_additional_input_paths']['exchange_calendar'] = 'sample_calendar.parquet'
    stage3 = load_stage(3, 'run_step3b.py')
    (ff / 'runs/NAMED_ROLES').mkdir(parents=True)
    before = list(sys.path)
    with pytest.raises(ValueError, match=reason):
        stage3.generate_first_run_factor_values('NAMED_ROLES', 'SYNTHETIC_NAMED_ROLES',
            path, payload, {}, csv_output_policy='no_csv', code_contract=contract)
    assert sys.path == before
    assert not any(name == 'implementation' or name.startswith('implementation.') for name in sys.modules)


@pytest.mark.parametrize('failure', ['module_import', 'lazy_import'])
def test_failed_import_restores_foreign_modules_and_path(tmp_path, monkeypatch, failure):
    ff, payload, contract, _fsm, path = prepared_fixture(tmp_path, monkeypatch)
    foreign = ModuleType('implementation')
    foreign.__path__ = ['/a/different/study/implementation']
    foreign_math = ModuleType('implementation.local_math')
    monkeypatch.setitem(sys.modules, 'implementation', foreign)
    monkeypatch.setitem(sys.modules, 'implementation.local_math', foreign_math)
    if failure == 'module_import':
        (tmp_path / 'implementation/local_math.py').write_text('import factorforge_missing_helper_xyz\n')
    else:
        (tmp_path / 'implementation/constants.py').unlink()
    stage3 = load_stage(3, 'run_step3b.py')
    (ff / 'runs/NAMED_ROLES').mkdir(parents=True)
    before = list(sys.path)
    with pytest.raises(ModuleNotFoundError):
        stage3.generate_first_run_factor_values('NAMED_ROLES', 'SYNTHETIC_NAMED_ROLES',
            path, payload, {}, csv_output_policy='no_csv', code_contract=contract)
    assert sys.path == before
    assert sys.modules['implementation'] is foreign
    assert sys.modules['implementation.local_math'] is foreign_math
    assert 'implementation.constants' not in sys.modules


def test_two_studies_do_not_share_helper_modules(tmp_path, monkeypatch):
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.mkdir(); second.mkdir()
    one = prepared_fixture(first, monkeypatch)
    stage_one = load_stage(3, 'run_step3b.py')
    two = prepared_fixture(second, monkeypatch)
    stage_two = load_stage(3, 'run_step3b.py')
    (second / 'implementation/constants.py').write_text('SCALE = 7.\n')
    modules = [stage_one.import_module_from_path(one[-1]), stage_two.import_module_from_path(two[-1])]
    frames = []
    for workspace in [first, second]:
        frames.append([pd.read_parquet(workspace / name) for name in
                       ['sample.parquet', 'sample_calendar.parquet', 'sample_members.parquet']])
    # Revisit the first module after the second to exercise cached eager and
    # lazy imports, not just a fresh one-shot process per study.
    for index, expected in [(0, 4.), (1, 9.), (0, 4.)]:
        stage = [stage_one, stage_two][index]
        daily, calendar, members = frames[index]
        before = list(sys.path)
        result = stage.compute_factor_with_contract(modules[index], daily, None,
            exchange_calendar=calendar, additional_inputs={'formation_membership': members})
        assert result.loc[(result.ts_code == '000001.SZ') & (result.trade_date == '20200102'), 'factor_value'].iloc[0] == expected
        assert sys.path == before
        assert not any(name == 'implementation' or name.startswith('implementation.') for name in sys.modules)


def test_generated_legacy_adapter_accepts_generic_named_role(tmp_path, monkeypatch):
    _ff, _payload, _contract, _fsm, _path = prepared_fixture(tmp_path, monkeypatch)
    stage = load_stage(3, 'run_step3b.py')
    source = 'def compute_factor(daily_df, *, risk_exposure):\n    return daily_df.close + risk_exposure.beta\n'
    namespace = {}
    exec(stage.ensure_direct_code_keyword_adapter(source,
         {'daily_df': ['close'], 'risk_exposure': ['beta']}), namespace)
    daily, risk = pd.DataFrame({'close': [2.]}), pd.DataFrame({'beta': [.5]})
    assert namespace['compute_factor'](daily_df=daily, risk_exposure=risk).tolist() == [2.5]
    with pytest.raises(TypeError, match='INPUT_ROLE_MISSING: risk_exposure'):
        namespace['compute_factor'](daily_df=daily)


@pytest.mark.parametrize('conflict', ['active_root', 'environment'])
def test_explicit_workspace_conflict_does_not_fall_back(tmp_path, monkeypatch, conflict):
    ff, payload, contract, _fsm, path = prepared_fixture(tmp_path, monkeypatch, layout='manifest')
    stage = load_stage(3, 'run_step3b.py')
    bind_manifest(stage, ff)
    other = tmp_path / 'different_study'
    other.mkdir()
    if conflict == 'active_root':
        monkeypatch.setattr(stage, 'FF', other)
    else:
        monkeypatch.setenv('FACTORFORGE_FACTOR_WORKSPACE', str(other))
    before = list(sys.path)
    with pytest.raises(ValueError, match='WORKSPACE_CONFLICT'):
        stage.generate_first_run_factor_values('NAMED_ROLES', 'SYNTHETIC_NAMED_ROLES',
            path, payload, {}, csv_output_policy='no_csv', code_contract=contract)
    assert sys.path == before
    assert not (ff / 'runs/NAMED_ROLES/step3b_sample_factor_values__NAMED_ROLES.parquet').exists()
