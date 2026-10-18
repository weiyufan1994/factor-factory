"""Offline contract tests; blocked data fixtures are not research readiness."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
RID = 'STANDARD_FIELD_MODE_TEST'
PROSE = 'Classify one-minute returns by volume state and aggregate the state contributions.'
SOURCE = '''from factor_factory.factors import PriceVolumeFactor

class ContractExample(PriceVolumeFactor):
    factor_id = "STANDARD_FIELD_MODE_TEST"
    required_inputs = {"daily": ["ts_code", "trade_date", "close"]}

    def compute(self, inputs):
        frame = inputs["daily"][["ts_code", "trade_date"]].copy()
        frame["factor_value"] = inputs["daily"]["close"]
        return frame

FACTOR = ContractExample()
'''


def load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def build_master(monkeypatch):
    step2 = load('skills/factor-forge-step2/scripts/run_step2.py', 'field_mode_step2')
    # These checks concern dependency transport, not research judgment or retrieval.
    monkeypatch.setattr(step2, 'validated_step1_measurement_program',
                        lambda **kw: {'implementation': {'route': kw['implementation_mode']}})
    monkeypatch.setattr(step2, 'build_step2_research_contract', lambda *args: {
        'target_statistic': 'synthetic test', 'economic_mechanism': 'synthetic test',
        'expected_failure_modes': [], 'similar_case_lessons_imported': [],
        'innovative_idea_seeds': [], 'reuse_instruction_for_future_agents': [],
    })

    def build(mode='direct_code', text=PROSE, fields=(), code_fields=(), ir_fields=None):
        aim = {'report_id': RID, 'source_type': 'pdf_report', 'implementation_mode': mode}
        primary = {
            'factor_id': RID, 'construction_id': RID, 'raw_formula_text': text,
            'required_inputs': list(fields),
            'code_contract': {
                'source_code': SOURCE, 'required_fields': list(code_fields),
                'input_schema': {'daily': ['ts_code', 'trade_date', 'close']},
            },
        }
        if ir_fields is not None:
            primary['formula_ir'] = {'required_fields': list(ir_fields)}
        return step2.build_factor_spec_master(RID, aim, primary, {}, {})

    return build


def run_step3_validator(tmp_path, master, *, mutate_plan_mode=None):
    """Use the actual CLI; data stays explicitly blocked throughout the test."""
    root = tmp_path / 'factorforge'
    implementation = deepcopy(master['implementation_contract'])
    implementation['report_id'] = RID
    if mutate_plan_mode is not None:
        implementation['implementation_mode'] = mutate_plan_mode
    objects = {
        ('factor_spec_master', 'factor_spec_master'): master,
        ('data_prep_master', 'data_prep_master'): {
            'report_id': RID, 'feasibility': 'blocked',
            'blocked_items': [{'code': 'SYNTHETIC_DATA_UNAVAILABLE'}],
            'data_sources': ['synthetic'], 'local_input_paths': {},
            'sample_window': {'start': '20260105', 'end': '20260106'},
        },
        ('data_prep_master', 'qlib_adapter_config'): {
            'report_id': RID, 'logical_fields': {'close': 'close'},
            'qlib_field_map': {'$close': 'close'},
            'instrument_field': 'ts_code', 'date_field': 'trade_date',
        },
        ('implementation_plan_master', 'implementation_plan_master'): implementation,
        ('handoff', 'handoff_to_step4'): {
            'report_id': RID, 'step3a_ready': False, 'step3b_ready': False,
        },
    }
    for (directory, stem), value in objects.items():
        path = root / 'objects' / directory / f'{stem}__{RID}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    env = dict(os.environ, FACTORFORGE_ROOT=str(root), PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run(
        [sys.executable, str(ROOT / 'skills/factor-forge-step3/scripts/validate_step3.py'),
         '--report-id', RID], cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )


def erase_standard_dependencies(master):
    # Keep both contract copies consistent so the test reaches dependency checks.
    for contract in [master['standard_formula_fields_contract'],
                     master['canonical_spec']['standard_formula_fields_contract']]:
        contract['required_standard_formula_fields'] = []


def test_direct_prose_survives_step2_and_real_step3_without_daily_dependencies(build_master, tmp_path):
    master = build_master(fields=['minute_bar:close', 'minute_bar:vol'])
    assert master['canonical_spec']['formula_text'] == PROSE
    assert master['standard_formula_fields_contract']['required_standard_formula_fields'] == []
    result = run_step3_validator(tmp_path, master)
    assert result.returncode == 0, result.stderr
    assert 'NATIVE_STEP3A_FEASIBILITY: blocked' in result.stdout


@pytest.mark.parametrize('mode', ['operator', 'hybrid'])
def test_real_operator_expression_still_generates_and_requires_fields(build_master, tmp_path, mode):
    master = build_master(mode, 'rank(volume) + returns + vwap + adv20')
    expected = {'volume', 'returns', 'vwap', 'adv20'}
    assert set(master['standard_formula_fields_contract']['required_standard_formula_fields']) == expected
    positive = run_step3_validator(tmp_path / 'positive', master)
    assert positive.returncode == 0, positive.stderr
    erase_standard_dependencies(master)
    negative = run_step3_validator(tmp_path / 'negative', master)
    assert negative.returncode != 0
    assert 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING' in negative.stderr


@pytest.mark.parametrize('mode', ['direct_code', 'operator', 'hybrid'])
def test_explicit_required_fields_remain_required_without_prose_tokens(build_master, tmp_path, mode):
    master = build_master(mode, 'rank(close)', fields=['returns'])
    assert master['standard_formula_fields_contract']['required_standard_formula_fields'] == ['returns']
    positive = run_step3_validator(tmp_path / 'positive', master)
    assert positive.returncode == 0, positive.stderr
    erase_standard_dependencies(master)
    negative = run_step3_validator(tmp_path / 'negative', master)
    assert negative.returncode != 0
    assert 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING' in negative.stderr


def test_direct_code_contract_dependencies_are_not_lost(build_master, tmp_path):
    master = build_master(text='Use the declared observations.', fields=['close'], code_fields=['volume'])
    assert master['standard_formula_fields_contract']['required_standard_formula_fields'] == ['volume']
    positive = run_step3_validator(tmp_path / 'positive', master)
    assert positive.returncode == 0, positive.stderr
    erase_standard_dependencies(master)
    negative = run_step3_validator(tmp_path / 'negative', master)
    assert negative.returncode != 0
    assert 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING' in negative.stderr


def test_ir_fields_do_not_hide_explicit_input_dependencies(build_master, tmp_path):
    master = build_master(text='Use declared observations.', fields=['volume'], ir_fields=['close'])
    assert master['standard_formula_fields_contract']['required_standard_formula_fields'] == ['volume']
    erase_standard_dependencies(master)
    result = run_step3_validator(tmp_path, master)
    assert result.returncode != 0
    assert 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING' in result.stderr


def test_plan_only_direct_code_mode_does_not_exempt_operator_spec(build_master, tmp_path):
    master = build_master()
    master['implementation_mode'] = 'operator'
    result = run_step3_validator(tmp_path, master)
    assert result.returncode != 0
    assert 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING' in result.stderr


def test_explicit_dependency_still_requires_no_future_policy(build_master, tmp_path):
    master = build_master(fields=['returns'])
    master['standard_formula_fields_contract']['leakage_policy'] = 'unchecked'
    result = run_step3_validator(tmp_path, master)
    assert result.returncode != 0
    assert 'BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING' in result.stderr


def test_step4_prepared_route_does_not_bypass_real_declared_fields(build_master, tmp_path):
    step4 = load('skills/factor-forge-step4/scripts/run_step4.py', 'field_mode_step4')
    daily = tmp_path / 'calendar.parquet'
    pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20260105'}]).to_parquet(daily)
    prep = {
        'report_id': RID, 'factor_id': RID,
        'sample_window': {'start': '20260105', 'end': '20260105'},
        'field_mapping': {'ts_code': 'ts_code'}, 'data_sources': ['synthetic'],
    }
    handoff = {
        'report_id': RID,
        'local_input_paths': {'input_mode': 'derived_state_with_daily', 'daily_df_parquet': str(daily)},
        'formal_route_binding': {'route': 'explicit_prepared_partitioned_controller'},
    }
    master = build_master()
    issues, _ = step4.validate_inputs(RID, master, prep, handoff, {'daily': daily})
    assert issues == []
    master = build_master(fields=['returns'])
    issues, _ = step4.validate_inputs(RID, master, prep, handoff, {'daily': daily})
    assert any(item['code'] == 'BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT' for item in issues)
