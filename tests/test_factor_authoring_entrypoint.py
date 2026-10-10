"""New-code generation uses FACTOR; old artifact reading stays in the runtime."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_factory.formula import parse_formula
from factor_factory.formula.pandas_codegen import generate_pandas_formula_code
from factor_factory.implementation_runtime import invoke_implementation, validate_factor_authoring
from factor_factory.research_api import normalize_factor_frame


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = {'index': ['datetime', 'instrument'], 'columns': ['factor_value']}
SOURCE = '''from factor_factory.factors import PriceVolumeFactor
class DifferenceFactor(PriceVolumeFactor):
    name = 'engineering_difference'
    input_columns = {'daily_df': ('ts_code', 'trade_date', 'open', 'close')}
    def compute(self, inputs):
        daily = inputs['daily_df']
        return daily[['ts_code', 'trade_date']].assign(factor_value=daily.close - daily.open)
FACTOR = DifferenceFactor()
'''


def load(relative):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location('authoring_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def contract():
    return {
        'source_code': SOURCE, 'entrypoint': 'FACTOR', 'function_name': 'FACTOR',
        'input_schema': {'daily_df': ['ts_code', 'trade_date', 'open', 'close']},
        'required_fields': ['open', 'close'], 'output_schema': deepcopy(OUTPUT),
        'source_derivation': {'not_fallback': True,
                              'derivation': 'source_code_preserved_from_formal_step2_raw_direct_code_contract'},
    }


@pytest.mark.parametrize('source,declared', [
    ('def compute_factor(daily_df):\n    return daily_df\n', {}),
    (SOURCE + '\ndef compute_factor(daily_df):\n    return FACTOR.run({"daily_df": daily_df})\n', {}),
    (SOURCE, {'entrypoint': 'compute_factor'}),
    (SOURCE, {'function_name': 'compute_factor', 'entrypoint': 'FACTOR'}),
    (SOURCE, {'output_schema': {'columns': ['ts_code', 'trade_date', 'factor_value']}}),
    ('# FACTOR = DifferenceFactor()\n', {}),
    ('def make():\n    FACTOR = object()\n', {}),
])
def test_new_authoring_rejects_old_or_conflicting_interface(source, declared):
    with pytest.raises(ValueError):
        validate_factor_authoring(source, declared)


def test_structure_does_not_execute_source_or_claim_runtime_type():
    source = 'FACTOR = object()\nraise RuntimeError("do not execute during structure check")\n'
    validate_factor_authoring(source)
    with pytest.raises(TypeError, match='BaseFactor'):
        invoke_implementation(SimpleNamespace(FACTOR=object()), None, None)


def test_step2_step3_preserve_class_source_without_wrapper():
    step2 = load('skills/factor-forge-step2/scripts/run_step2.py')
    step3a = load('skills/factor-forge-step3/scripts/run_step3.py')
    step3b = load('skills/factor-forge-step3/scripts/run_step3b.py')
    raw = contract()
    del raw['function_name']
    normalized = step2.explicit_direct_code_source_contract({}, {'code_contract': raw})
    assert normalized['entrypoint'] == normalized['function_name'] == 'FACTOR'
    assert normalized['source_code'] == SOURCE
    spec = {'factor_id': 'DIFFERENCE', 'implementation_contract': {'code_contract': normalized}}
    prepared = step3a.build_direct_code_contract_for_step3a(spec, {})
    assert prepared['status'] == 'ready'
    assert prepared['source_code'] == SOURCE
    assert prepared['code_contract']['output_schema'] == OUTPUT
    _plan, generated, _qlib, _hybrid = step3b.build_direct_code_artifacts('DIFFERENCE', {}, spec, {})
    assert generated == SOURCE
    assert not hasattr(step3b, 'ensure_direct_code_keyword_adapter')
    assert not hasattr(step3a, 'append_retained_chip_state_adapter')


@pytest.mark.parametrize('producer', ['bridge', 'provider'])
def test_provider_contract_does_not_reintroduce_legacy_entry_or_columns(producer):
    bridge = load('scripts/run_factorforge_step2_llm_bridge.py')
    payload = {'implementation_mode': 'direct_code', 'required_inputs': ['open', 'close'],
               'implementation_contract': {'code_contract': contract()}}
    if producer == 'bridge':
        normalized = bridge.normalize_command_raw(payload, role='primary', request={})
        failure = bridge.direct_code_source_contract_failure
    else:
        if not (ROOT / 'scripts/run_factorforge_humphrey_llm_provider.py').is_file():
            pytest.skip('optional hosted provider is only in the full-source distribution')
        provider = load('scripts/run_factorforge_humphrey_llm_provider.py')
        normalized = provider.normalize_step2_payload(payload, {'role': 'primary'})
        failure = provider._direct_code_source_contract_failure
    assert failure(normalized) is None
    code = normalized['implementation_contract']['code_contract']
    assert code['source_code'] == SOURCE
    assert code['output_schema'] == OUTPUT
    code['entrypoint'] = 'compute_factor'
    assert 'FACTOR' in failure(normalized)


@pytest.mark.parametrize('mode', ['operator', 'direct_code', 'hybrid'])
def test_generated_modules_have_one_class_entry_and_preserve_values(mode):
    daily = pd.DataFrame({'ts_code': ['000001.SZ'] * 4,
                          'trade_date': ['20240102', '20240103', '20240104', '20240105'],
                          'open': [1., 2., 3., 4.], 'close': [1., 3., np.nan, 2.]})
    ir = parse_formula('close-open', list(daily.columns), raise_on_error=True)
    if mode == 'operator':
        source = generate_pandas_formula_code(report_id='ARITHMETIC', factor_id='ARITHMETIC', formula_ir=ir)
    elif mode == 'direct_code':
        source = SOURCE
    else:
        step3 = load('skills/factor-forge-step3/scripts/run_step3b.py')
        source = step3.generate_hybrid_code(report_id='ARITHMETIC', factor_id='ARITHMETIC', formula_ir=ir,
            custom_block={'source_code': "def apply_custom_block(operator_df, daily_df):\n    return operator_df.rename(columns={'operator_value':'factor_value'})"},
            boundary={}, contract={})
    validate_factor_authoring(source)
    namespace = {}
    exec(source, namespace)
    assert 'compute_factor' not in namespace
    expected = normalize_factor_frame(daily[['ts_code', 'trade_date']].assign(factor_value=[0., 1., np.nan, -2.]))
    actual = invoke_implementation(SimpleNamespace(**namespace), daily, None)
    pd.testing.assert_frame_equal(actual, expected)
    assert np.isnan(actual.factor_value.iloc[2])
    assert actual.factor_value.iloc[0] == 0


@pytest.mark.parametrize('family', ['price_volume', 'shadow_candlestick'])
def test_explicit_family_templates_share_the_class_interface(family):
    plugin = importlib.import_module(f'factor_factory.factor_families.{family}')
    plan, source, *_ = plugin.PLUGIN.generate('SYNTHETIC_FAMILY', {}, {})
    validate_factor_authoring(source)
    assert plan['output_schema'] == OUTPUT
    namespace = {}
    exec(source, namespace)
    assert 'compute_factor' not in namespace
    daily = pd.DataFrame({'ts_code': ['000001.SZ', '000002.SZ'], 'trade_date': ['20240102'] * 2,
                          'open': [10., 20.], 'high': [12., 20.], 'low': [9., 20.],
                          'close': [11., 20.], 'vol': [100., 200.]})
    out = namespace['FACTOR'].run({'daily_df': daily})
    assert out.index.names == OUTPUT['index'] and list(out.columns) == OUTPUT['columns']
    expected = [1 / 15, 0.] if family == 'price_volume' else [0., np.nan]
    np.testing.assert_allclose(out.factor_value, expected, equal_nan=True)


def test_smoke_builder_is_explicitly_not_a_research_spec_builder():
    if not (ROOT / 'scripts/run_factorforge_acceptance_smoke.py').is_file():
        pytest.skip('historical smoke builder is only in the full-source distribution')
    smoke = load('scripts/run_factorforge_acceptance_smoke.py')
    assert not hasattr(smoke, 'build_direct_code_spec')
    spec = smoke.build_direct_code_smoke_spec('SMOKE', 'SMOKE', source_code=smoke.SAFE_DIRECT_CODE, run_id='SMOKE')
    code = spec['implementation_contract']['code_contract']
    assert code['entrypoint'] == 'FACTOR' and code['output_schema'] == OUTPUT


def test_step2_fixture_has_the_same_contract_as_the_provider_prompt():
    bridge = load('scripts/run_factorforge_step2_llm_bridge.py')
    fixture = bridge.fixture_primary('SYNTHETIC_BRIDGE', {})
    assert bridge.direct_code_source_contract_failure(fixture) is None
    for role in ['primary', 'challenger']:
        prompt = bridge.role_prompt(role)
        assert 'FACTOR' in prompt and 'compute_factor' not in prompt


def test_class_only_factor_never_enters_legacy_minute_fast_path():
    step4 = load('skills/factor-forge-step4/scripts/run_step4.py')
    namespace = {}
    exec(SOURCE, namespace)
    assert step4._supports_sp3_intraday_flow_fast_path(SimpleNamespace(**namespace)) is False
    assert step4._supports_sp3_intraday_flow_fast_path(namespace['FACTOR']) is False
    assert step4._supports_sp3_intraday_flow_fast_path(SimpleNamespace()) is False


def test_unconditional_step6_formula_wrapper_is_removed():
    from factor_factory.ultimate_loop.cli import build_parser
    for name in ['apply_step6_iteration.py', 'run_step6_autoloop.py']:
        assert not (ROOT / 'skills/factor-forge-step6/scripts' / name).exists()
    parser = build_parser()
    assert '--apply-approved-revision' not in parser._option_string_actions
