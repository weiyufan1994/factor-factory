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
    step3_runner = load_module('skills/factor-forge-step3/scripts/run_step3.py', 'step3_runner_smoke')
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

    legacy_price_only_contract = {
        'version': 'factorforge_standard_formula_fields_contract_v1',
        'required_standard_formula_fields': [],
        'formula_text_standard_fields': [],
        'formula_text': 'rank(correlation(delay((open-close),1),close,200))+rank((open - close))',
        'required_fields': ['close', 'open'],
        'fields': {},
        'leakage_policy': 'no future rows; derived fields are computed per ts_code in trade_date order',
        'materialization_owner': 'Step3A_or_Step4_data_contract',
    }
    failures = validate_standard_formula_fields_contract(
        legacy_price_only_contract,
        formula_text=legacy_price_only_contract['formula_text'],
        required_fields=['close', 'open'],
        available_columns=['open', 'close'],
    )
    cases['legacy_price_only_empty_standard_contract_passes'] = {
        'ok': not failures,
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

    alpha019_like_formula_ir = {
        'parse_status': 'success',
        'root': {
            'type': 'operator',
            'operator': 'multiply',
            'args': [
                {'type': 'constant', 'value': -1},
                {
                    'type': 'operator',
                    'operator': 'sum',
                    'args': [
                        {'type': 'field', 'name': 'returns'},
                        {'type': 'constant', 'value': 250},
                    ],
                },
            ],
        },
    }
    alpha019_window = step3_runner.step3a_executability_window(
        {'start': '20160101', 'end': '20250711', 'calendar': 'A-share trading days'},
        formula_ir=alpha019_like_formula_ir,
    )
    cases['step3a_alpha019_250_lookback_window_expands'] = {
        'ok': alpha019_window.get('formula_max_lookback') == 250
        and int(alpha019_window.get('max_calendar_days') or 0) >= 480
        and str(alpha019_window.get('end') or '') >= '20170401',
        'window': alpha019_window,
    }

    step3b_runner = load_module('skills/factor-forge-step3/scripts/run_step3b.py', 'step3b_runner_smoke')
    old_rows = step3b_runner.STEP3B_SAMPLE_MAX_ROWS
    old_dates = step3b_runner.STEP3B_SAMPLE_MAX_DATES
    old_tickers = step3b_runner.STEP3B_SAMPLE_MAX_TICKERS
    try:
        step3b_runner.STEP3B_SAMPLE_MAX_ROWS = 1000
        step3b_runner.STEP3B_SAMPLE_MAX_DATES = 128
        step3b_runner.STEP3B_SAMPLE_MAX_TICKERS = 10
        rows = []
        for date in pd.bdate_range('2020-01-01', periods=300):
            trade_date = date.strftime('%Y%m%d')
            for ticker_i in range(10):
                rows.append({
                    'ts_code': f'{ticker_i:06d}.SZ',
                    'trade_date': trade_date,
                    'close': 10.0 + ticker_i,
                    'returns': 0.001 * ticker_i,
                })
        sampled, profile = step3b_runner.limit_step3b_sample_frame(
            pd.DataFrame(rows),
            label='clean_daily_bar',
            formula_ir=alpha019_like_formula_ir,
        )
    finally:
        step3b_runner.STEP3B_SAMPLE_MAX_ROWS = old_rows
        step3b_runner.STEP3B_SAMPLE_MAX_DATES = old_dates
        step3b_runner.STEP3B_SAMPLE_MAX_TICKERS = old_tickers
    cases['step3b_alpha019_250_lookback_sampling_preserves_history'] = {
        'ok': profile.get('sampling_strategy') == 'lookback_aware_date_ticker_cap'
        and int(profile.get('formula_max_lookback') or 0) == 250
        and int(sampled['trade_date'].nunique()) >= 250
        and len(sampled) <= 1000,
        'profile': profile,
        'sampled_date_count': int(sampled['trade_date'].nunique()),
        'sampled_rows': int(len(sampled)),
    }

    alpha015_like_prep = {
        'data_api_resolution': {
            'clean_daily_bar': {
                'resolved_fields': {
                    'amount': 'amount',
                    'high': 'high',
                    'vol': 'vol',
                },
                'request': {'fields': ['amount', 'high', 'vol']},
            },
            'daily_basic': {
                'resolved_fields': {
                    'ts_code': 'ts_code',
                    'trade_date': 'trade_date',
                    'turnover_rate': 'turnover_rate',
                },
                'request': {'fields': ['ts_code', 'trade_date', 'turnover_rate']},
            },
        },
        'local_input_paths': {
            'daily_io_contract': {
                'sort_contract': {
                    'schema': [
                        'ts_code',
                        'trade_date',
                        'high',
                        'vol',
                        'amount',
                        'turnover_rate',
                    ]
                }
            }
        },
    }
    schema = step3b_runner.infer_operator_schema(alpha015_like_prep)
    formula_text = '(((-1 * mean(rank(correlation(rank(high), rank(volume), 10)), 5)) * rank(amount)) * (0.50 + (0.50 * (1 - rank(turnover)))))'
    parsed = step3b_runner.parse_formula(formula_text)
    resolved = step3b_runner.resolve_formula_fields_for_schema(parsed, schema['columns'])
    cases['step3b_schema_infers_daily_basic_turnover_alias'] = {
        'ok': schema.get('source') == 'step3a_schema'
        and resolved.get('resolved_fields', {}).get('turnover') == 'turnover_rate'
        and resolved.get('resolved_fields', {}).get('volume') == 'vol',
        'schema': schema,
        'resolved_fields': resolved.get('resolved_fields'),
    }

    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td) / 'factor_workspace'
        target = workspace / 'runs' / 'RID' / 'step3a_local_inputs' / 'daily.parquet'
        target.parent.mkdir(parents=True)
        target.write_text('placeholder')
        stale = Path(td) / 'factor_research' / 'old_workspace' / 'runs' / 'RID' / 'step3a_local_inputs' / 'daily.parquet'
        original_ff = step3b_runner.FF
        try:
            step3b_runner.FF = workspace
            relocated = step3b_runner.resolve_local_input_path(str(stale))
        finally:
            step3b_runner.FF = original_ff
    cases['step3b_relocates_stale_workspace_local_input_path'] = {
        'ok': relocated == target,
        'relocated': str(relocated),
        'expected': str(target),
    }

    materializer = load_module('skills/factor-forge-step6/scripts/materialize_step6_child_revision.py', 'step6_materializer_smoke')
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td) / 'factor_workspace'
        target = workspace / 'runs' / 'PARENT' / 'step3a_local_inputs' / 'daily.parquet'
        target.parent.mkdir(parents=True)
        target.write_text('placeholder')
        stale = Path(td) / 'factor_research' / 'old_workspace' / 'runs' / 'PARENT' / 'step3a_local_inputs' / 'daily.parquet'
        relocated = materializer.resolved_path(workspace, str(stale))
    cases['materializer_relocates_stale_workspace_daily_snapshot_path'] = {
        'ok': relocated == target,
        'relocated': str(relocated),
        'expected': str(target),
    }

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
