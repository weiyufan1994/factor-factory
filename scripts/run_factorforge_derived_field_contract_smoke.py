#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_step3_validator():
    path = REPO_ROOT / 'skills/factor-forge-step3/scripts/validate_step3.py'
    spec = importlib.util.spec_from_file_location('step3_validator_derived_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_step3_runner():
    path = REPO_ROOT / 'skills/factor-forge-step3/scripts/run_step3.py'
    spec = importlib.util.spec_from_file_location('step3_runner_derived_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_blocks(module, contract: dict, required: list[str], token: str, expected_operators: list[dict] | None = None) -> dict:
    try:
        module.validate_derived_field_contract({'derived_field_contract': contract}, required, expected_operators)
    except AssertionError as exc:
        return {'ok': token in str(exc), 'error': str(exc)}
    return {'ok': False, 'error': None}


def base_contract() -> dict:
    return {
        'version': 'factorforge_derived_field_contract_v1',
        'report_local_only': True,
        'clean_data_mutation': False,
        'required_fields': [],
        'source_fields': [],
        'derived_fields': {},
        'validation_result': 'PASS',
        'blocked_items': [],
    }


def vwap_adv_contract() -> dict:
    contract = base_contract()
    contract['required_fields'] = ['vwap', 'adv20']
    contract['source_fields'] = ['amount', 'vol']
    contract['derived_fields'] = {
        'vwap': {
            'sources': ['amount', 'vol'],
            'rule': 'amount / normalized_volume',
            'source_units': {'amount': 'amount_unit_from_catalog', 'vol': 'shares_or_lots_from_catalog'},
            'output_unit': 'price',
            'lookback_window': None,
            'include_current_day': True,
            'leakage_policy': 'no future data',
            'null_policy': 'null when source is null',
        },
        'adv20': {
            'sources': ['vol'],
            'rule': 'rolling_mean(vol, 20)',
            'source_units': {'vol': 'shares_or_lots_from_catalog'},
            'output_unit': 'documented_volume_unit',
            'lookback_window': 20,
            'include_current_day': True,
            'leakage_policy': 'no future data',
            'null_policy': 'null until lookback_window observations are available',
        },
    }
    return contract


def operator_contract() -> dict:
    contract = base_contract()
    contract['required_fields'] = ['open', 'close']
    contract['source_fields'] = ['open', 'close']
    contract['materialization_status'] = 'planned_by_formula_contract'
    contract['derived_fields'] = {
        'formula_op_1_minus': {
            'operator': 'minus',
            'sources': ['open', 'close'],
            'rule': 'minus(open, close)',
            'source_units': {'open': 'price', 'close': 'price'},
            'output_unit': 'price',
            'lookback_window': None,
            'include_current_day': True,
            'leakage_policy': 'no future data',
            'null_policy': 'preserve operator nulls according to lookback/window availability',
        },
        'formula_op_2_delay': {
            'operator': 'delay',
            'sources': ['open', 'close'],
            'rule': 'delay(open, close)',
            'source_units': {'open': 'price', 'close': 'price'},
            'output_unit': 'price',
            'lookback_window': 1,
            'include_current_day': False,
            'leakage_policy': 'no future data',
            'null_policy': 'preserve operator nulls according to lookback/window availability',
        },
        'formula_op_3_correlation': {
            'operator': 'correlation',
            'sources': ['open', 'close'],
            'rule': 'correlation(open, close)',
            'source_units': {'open': 'price', 'close': 'price'},
            'output_unit': 'dimensionless_correlation',
            'lookback_window': 200,
            'include_current_day': True,
            'leakage_policy': 'no future data',
            'null_policy': 'preserve operator nulls according to lookback/window availability',
            'window_policy': 'rolling per ts_code in trade_date order',
        },
        'formula_op_4_rank': {
            'operator': 'rank',
            'sources': ['open', 'close'],
            'rule': 'rank(open, close)',
            'source_units': {'open': 'price', 'close': 'price'},
            'output_unit': 'rank_score',
            'lookback_window': None,
            'include_current_day': True,
            'leakage_policy': 'no future data',
            'null_policy': 'preserve operator nulls according to lookback/window availability',
            'rank_scope': 'cross_sectional_per_trade_date',
        },
    }
    return contract


def alpha037_expected_operators() -> list[dict]:
    return [
        {'operator': 'minus', 'sources': ['open', 'close'], 'output_unit': 'price'},
        {'operator': 'delay', 'sources': ['open', 'close'], 'output_unit': 'price', 'lookback_window': 1},
        {
            'operator': 'correlation',
            'sources': ['open', 'close'],
            'output_unit': 'dimensionless_correlation',
            'lookback_window': 200,
        },
        {'operator': 'rank', 'sources': ['open', 'close'], 'output_unit': 'rank_score', 'rank_scope_required': True},
    ]


def main() -> None:
    module = load_step3_validator()
    runner = load_step3_runner()
    cases: dict[str, dict] = {}
    cases['derived_field_contract_missing_blocks'] = assert_blocks(
        module,
        {},
        ['vwap'],
        'BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT',
    )

    contract = vwap_adv_contract()
    contract['derived_fields']['vwap'].pop('output_unit', None)
    cases['derived_field_unit_missing_blocks'] = assert_blocks(
        module,
        contract,
        ['vwap', 'adv20'],
        'BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS',
    )

    contract = vwap_adv_contract()
    contract['derived_fields']['vwap'].pop('leakage_policy', None)
    cases['derived_field_leakage_policy_missing_blocks'] = assert_blocks(
        module,
        contract,
        ['vwap', 'adv20'],
        'BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING',
    )

    contract = vwap_adv_contract()
    contract['clean_data_mutation'] = True
    cases['derived_field_claims_clean_data_mutation_blocks'] = assert_blocks(
        module,
        contract,
        ['vwap'],
        'BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT',
    )

    contract = operator_contract()
    contract['derived_fields']['formula_op_3_correlation'].pop('lookback_window', None)
    cases['operator_derived_field_lookback_missing_blocks'] = assert_blocks(
        module,
        contract,
        [],
        'BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING',
    )

    contract = operator_contract()
    contract['derived_fields']['formula_op_4_rank'].pop('rank_scope', None)
    cases['operator_rank_scope_missing_blocks'] = assert_blocks(
        module,
        contract,
        [],
        'BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING',
    )

    cases['alpha037_expected_operator_contract_missing_blocks'] = assert_blocks(
        module,
        base_contract(),
        [],
        'BLOCK_STANDARD_FORMULA_OPERATOR_CONTRACT_MISSING',
        alpha037_expected_operators(),
    )

    contract = operator_contract()
    contract['derived_fields']['formula_op_3_correlation']['sources'] = ['volume']
    cases['alpha037_operator_wrong_sources_block'] = assert_blocks(
        module,
        contract,
        [],
        'BLOCK_STANDARD_FORMULA_OPERATOR_CONTRACT_MISMATCH',
        alpha037_expected_operators(),
    )

    contract = operator_contract()
    contract['derived_fields']['formula_op_4_rank']['output_unit'] = 'price'
    cases['alpha037_operator_wrong_output_unit_block'] = assert_blocks(
        module,
        contract,
        [],
        'BLOCK_STANDARD_FORMULA_OPERATOR_CONTRACT_MISMATCH',
        alpha037_expected_operators(),
    )

    contract = base_contract()
    contract['required_fields'] = ['returns']
    contract['source_fields'] = ['pct_chg']
    contract['derived_fields'] = {
        'returns': {
            'sources': ['pct_chg'],
            'rule': 'pct_chg / 100 if pct_chg is percent',
            'source_units': {'pct_chg': 'percent_or_decimal_from_catalog'},
            'output_unit': 'decimal_return',
            'lookback_window': None,
            'include_current_day': True,
            'leakage_policy': 'no future data',
            'null_policy': 'preserve source nulls',
        }
    }
    cases['returns_ambiguous_unit_blocks'] = assert_blocks(
        module,
        contract,
        ['returns'],
        'BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS',
    )

    try:
        module.validate_derived_field_contract({'derived_field_contract': base_contract()}, [])
        no_derived_ok = True
    except AssertionError as exc:
        no_derived_ok = False
        cases['valid_no_derived_fields_contract_passes_error'] = {'error': str(exc)}
    cases['valid_no_derived_fields_contract_passes'] = {'ok': no_derived_ok}

    try:
        module.validate_derived_field_contract({'derived_field_contract': vwap_adv_contract()}, ['vwap', 'adv20'])
        derived_ok = True
    except AssertionError as exc:
        derived_ok = False
        cases['valid_vwap_adv20_derived_fields_contract_passes_error'] = {'error': str(exc)}
    cases['valid_vwap_adv20_derived_fields_contract_passes'] = {'ok': derived_ok}

    try:
        module.validate_derived_field_contract({'derived_field_contract': operator_contract()}, [])
        operator_ok = True
    except AssertionError as exc:
        operator_ok = False
        cases['valid_operator_derived_fields_contract_passes_error'] = {'error': str(exc)}
    cases['valid_operator_derived_fields_contract_passes'] = {'ok': operator_ok}

    try:
        frame = pd.DataFrame({
            'ts_code': ['000001.SZ', '000001.SZ'],
            'trade_date': ['20200101', '20200102'],
            'pct_chg': [12.5, -3.0],
        })
        enriched, contract = runner.enrich_report_local_daily_fields(frame, ['returns'])
        returns_ok = list(enriched['returns'].round(6)) == [0.125, -0.03]
        unit_ok = (
            contract['derived_fields']['returns']['source_units'].get('pct_chg') == 'percent'
            and contract['derived_fields']['returns']['output_unit'] == 'decimal_return'
        )
        cases['returns_pct_chg_normalized_to_decimal'] = {'ok': returns_ok and unit_ok, 'values': list(enriched['returns']), 'contract': contract['derived_fields']['returns']}
    except Exception as exc:
        cases['returns_pct_chg_normalized_to_decimal'] = {'ok': False, 'error': str(exc)}

    failed = [name for name, item in cases.items() if not item.get('ok', True)]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
