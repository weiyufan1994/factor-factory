#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.field_aliases import (
    build_standard_formula_fields_contract,
    standard_formula_fields_from_text,
    validate_standard_formula_fields_contract,
)

def load_module(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {rel}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_token(failures: list[dict], token: str) -> bool:
    return any(item.get('code') == token or token in str(item) for item in failures)


def main() -> None:
    step3_validator = load_module('skills/factor-forge-step3/scripts/validate_step3.py', 'step3_validator_smoke')
    step4_runner = load_module('skills/factor-forge-step4/scripts/run_step4.py', 'step4_runner_smoke')
    cases: dict[str, dict] = {}

    implied = standard_formula_fields_from_text('rank(vwap)+rank(adv20)+returns+volume')
    cases['formula_text_extracts_standard_fields'] = {
        'ok': implied == ['vwap', 'adv20', 'returns', 'volume'],
        'fields': implied,
    }

    failures = validate_standard_formula_fields_contract({}, formula_text='rank(vwap)+rank(adv20)+returns+volume')
    cases['missing_standard_formula_fields_contract_blocks'] = {
        'ok': has_token(failures, 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING'),
        'failures': failures,
    }

    contract = build_standard_formula_fields_contract(formula_text='rank(adv20)', available_source_fields=['close'])
    failures = validate_standard_formula_fields_contract(contract, formula_text='rank(adv20)', available_columns=['close'])
    cases['adv20_without_volume_source_blocks'] = {
        'ok': has_token(failures, 'BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING'),
        'failures': failures,
    }

    contract = build_standard_formula_fields_contract(formula_text='rank(vwap)', available_source_fields=['close', 'vol'])
    failures = validate_standard_formula_fields_contract(contract, formula_text='rank(vwap)', available_columns=['close', 'vol'])
    cases['vwap_without_amount_or_volume_source_blocks'] = {
        'ok': has_token(failures, 'BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING'),
        'failures': failures,
    }

    contract = build_standard_formula_fields_contract(formula_text='returns', available_source_fields=['pct_chg'])
    contract['derivation_rules']['returns'].pop('output_unit', None)
    failures = validate_standard_formula_fields_contract(contract, formula_text='returns', available_columns=['pct_chg'])
    cases['returns_without_unit_policy_blocks'] = {
        'ok': has_token(failures, 'BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS'),
        'failures': failures,
    }

    contract = build_standard_formula_fields_contract(formula_text='vwap', available_source_fields=['amount', 'vol'])
    contract['derivation_rules']['vwap'].pop('source_unit', None)
    failures = validate_standard_formula_fields_contract(contract, formula_text='vwap', available_columns=['amount', 'vol'])
    cases['vwap_without_unit_policy_blocks'] = {
        'ok': has_token(failures, 'BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS'),
        'failures': failures,
    }

    contract = build_standard_formula_fields_contract(formula_text='adv20', available_source_fields=['volume'])
    contract['derivation_rules']['adv20'].pop('lookback_window', None)
    contract['derivation_rules']['adv20'].pop('lookback', None)
    failures = validate_standard_formula_fields_contract(contract, formula_text='adv20', available_columns=['volume'])
    cases['adv20_without_lookback_policy_blocks'] = {
        'ok': has_token(failures, 'BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING'),
        'failures': failures,
    }

    try:
        step3_validator.validate_derived_field_contract(
            {'derived_field_contract': {'version': 'factorforge_derived_field_contract_v1', 'report_local_only': True, 'clean_data_mutation': False, 'validation_result': 'PASS', 'derived_fields': {}}},
            ['vwap'],
        )
        step3_blocked = False
    except AssertionError as exc:
        step3_blocked = 'BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT' in str(exc)
    cases['step3a_snapshot_missing_required_field_blocks'] = {'ok': step3_blocked}

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        daily_path = root / 'daily.csv'
        pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20200102', 'close': 10.0}]).to_csv(daily_path, index=False)
        fsm = {
            'report_id': 'SMOKE',
            'factor_id': 'SMOKE',
            'canonical_spec': {'formula_text': 'rank(vwap)', 'required_fields': ['vwap']},
            'standard_formula_fields_contract': build_standard_formula_fields_contract(formula_text='rank(vwap)', available_source_fields=['amount', 'vol']),
        }
        dpm = {'report_id': 'SMOKE', 'factor_id': 'SMOKE', 'sample_window': {'start': '20200101', 'end': '20200103'}, 'field_mapping': {}, 'data_sources': ['clean_daily_bar']}
        issues, _warnings = step4_runner.validate_inputs('SMOKE', fsm, dpm, {'report_id': 'SMOKE'}, {'daily': daily_path})
    cases['step4_input_missing_required_field_blocks'] = {
        'ok': any(item.get('code') == 'BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT' for item in issues),
        'issues': issues,
    }

    valid = build_standard_formula_fields_contract(
        formula_text='rank(vwap)+rank(adv20)+returns+volume',
        required_fields=[],
        available_source_fields=['amount', 'vol', 'pct_chg'],
    )
    failures = validate_standard_formula_fields_contract(
        valid,
        formula_text='rank(vwap)+rank(adv20)+returns+volume',
        available_columns=['amount', 'vol', 'pct_chg'],
    )
    cases['valid_alpha101_standard_field_contract_passes'] = {'ok': not failures, 'contract': valid, 'failures': failures}

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
