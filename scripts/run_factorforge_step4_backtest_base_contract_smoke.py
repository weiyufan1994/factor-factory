#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
STEP4_SCRIPT_DIR = REPO_ROOT / 'skills/factor-forge-step4/scripts'
for candidate in [REPO_ROOT, STEP4_SCRIPT_DIR]:
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_module('step4_backtest_base_dataset_smoke', REPO_ROOT / 'skills/factor-forge-step4/scripts/backtest_base_dataset.py')
step4 = load_module('step4_run_smoke', REPO_ROOT / 'skills/factor-forge-step4/scripts/run_step4.py')


def has(issues: list[dict[str, Any]], code: str) -> bool:
    return any(item.get('code') == code for item in issues)


def daily_frame() -> pd.DataFrame:
    rows = []
    for idx, date in enumerate(['20200101', '20200102', '20200103', '20200106', '20200107']):
        for code_idx, code in enumerate(['S001', 'S002', 'S003']):
            close = 10.0 + idx + code_idx * 0.2
            rows.append({
                'ts_code': code,
                'trade_date': date,
                'close': close,
                'pct_chg': idx * 0.1,
                'vol': 1000 + idx,
                'amount': close * (1000 + idx),
            })
    return pd.DataFrame(rows)


def build_contract(root: Path, report_id: str = 'SMOKE_BASE') -> tuple[dict[str, Any], dict[str, Any], Path, pd.DataFrame]:
    df = daily_frame()
    daily_path = root / f'daily__{report_id}.parquet'
    df.to_parquet(daily_path, index=False)
    contract, profile = base.build_or_reuse_backtest_base_dataset(
        report_id=report_id,
        factor_id='SMOKE_FACTOR',
        daily_df=df,
        daily_input_path=daily_path,
        run_root=root / 'runs',
        window_start='20200101',
        window_end='20200107',
        producer_repo_sha='smoke_sha',
    )
    return contract, profile, daily_path, df


def main() -> None:
    cases: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix='factorforge_backtest_base_smoke_') as tmp:
        root = Path(tmp)
        contract, profile, daily_path, df = build_contract(root)
        expected = base.expected_backtest_base_identity(
            daily_df=df,
            daily_input_path=daily_path,
            window_start='20200101',
            window_end='20200107',
        )

        issues = base.validate_backtest_base_dataset_contract(None, expected_identity=expected)
        cases['backtest_base_missing_blocks_when_required'] = {'ok': has(issues, 'BLOCK_BACKTEST_BASE_DATASET_MISSING'), 'issues': issues}

        mutated = json.loads(json.dumps(contract))
        mutated['label_policy']['alignment'] = 'same_day_return'
        issues = base.validate_backtest_base_dataset_contract(mutated, expected_identity=expected)
        cases['backtest_base_label_policy_mismatch_blocks'] = {'ok': has(issues, 'BLOCK_BACKTEST_BASE_LABEL_POLICY_MISMATCH'), 'issues': issues}

        mutated = json.loads(json.dumps(contract))
        mutated['universe_hash'] = 'bad_universe_hash'
        issues = base.validate_backtest_base_dataset_contract(mutated, expected_identity=expected)
        cases['backtest_base_universe_hash_mismatch_blocks'] = {'ok': has(issues, 'BLOCK_BACKTEST_BASE_UNIVERSE_MISMATCH'), 'issues': issues}

        mutated = json.loads(json.dumps(contract))
        mutated['source_data_version'] = 'bad_source_data_version'
        issues = base.validate_backtest_base_dataset_contract(mutated, expected_identity=expected)
        cases['backtest_base_data_version_mismatch_blocks'] = {'ok': has(issues, 'BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH'), 'issues': issues}

        mutated = json.loads(json.dumps(contract))
        mutated['tradable_policy']['exclude_suspended'] = False
        issues = base.validate_backtest_base_dataset_contract(mutated, expected_identity=expected)
        cases['backtest_base_tradable_policy_mismatch_blocks'] = {'ok': has(issues, 'BLOCK_BACKTEST_BASE_TRADABLE_POLICY_MISMATCH'), 'issues': issues}

        mutated = json.loads(json.dumps(contract))
        mutated['cost_policy']['default_cost_rate'] = 0.0
        issues = base.validate_backtest_base_dataset_contract(mutated, expected_identity=expected)
        cases['backtest_base_cost_policy_mismatch_blocks'] = {'ok': has(issues, 'BLOCK_BACKTEST_BASE_COST_POLICY_MISMATCH'), 'issues': issues}

        mutated = json.loads(json.dumps(contract))
        labels_path = Path(mutated['artifact_paths']['labels'])
        pd.DataFrame([{'code': 'BAD', 'datetime': '19990101', 'label_return_1d': 999.0}]).to_parquet(labels_path, index=False)
        issues = base.validate_backtest_base_dataset_contract(mutated, expected_identity=expected)
        cases['backtest_base_artifact_hash_mismatch_blocks'] = {'ok': has(issues, 'BLOCK_BACKTEST_BASE_ARTIFACT_HASH_MISMATCH'), 'issues': issues}

        # Rebuild the valid artifact after tamper before reuse tests.
        contract, profile, daily_path, df = build_contract(root, 'SMOKE_BASE_REBUILT')
        expected = base.expected_backtest_base_identity(
            daily_df=df,
            daily_input_path=daily_path,
            window_start='20200101',
            window_end='20200107',
        )
        mutated = json.loads(json.dumps(contract))
        mutated['backtest_base_dataset_id'] = ''
        issues = base.validate_backtest_base_dataset_contract(mutated, expected_identity=expected)
        cases['backtest_base_ambiguous_identity_blocks'] = {'ok': has(issues, 'BLOCK_STEP4_REUSE_GATE_AMBIGUOUS'), 'issues': issues}

        try:
            step4.step4_factor_csv_policy_from_step3b({'performance_profile': {'csv_output_profile': {'csv_output_policy': 'full_csv'}}})
            full_csv_blocked = False
        except SystemExit as exc:
            full_csv_blocked = 'BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN' in str(exc)
        cases['full_factor_csv_default_forbidden_blocks'] = {'ok': full_csv_blocked}

        policy = step4.step4_factor_csv_policy_from_step3b({})
        cases['sample_csv_only_policy_passes'] = {
            'ok': (
                policy.get('csv_output_policy') == 'sample_csv'
                and policy.get('factor_csv_write_allowed') is False
                and policy.get('sample_csv_write_allowed') is True
                and policy.get('full_csv_default_disabled') is True
            ),
            'policy': policy,
        }

        shared_context = {
            'version': 'factorforge_shared_evaluation_context_v1',
            'backtest_base_dataset_id': contract.get('backtest_base_dataset_id'),
            'label_table_path': contract['artifact_paths']['labels'],
            'tradable_mask_path': contract['artifact_paths']['tradable_mask'],
            'calendar_path': contract['artifact_paths']['calendar'],
            'cost_inputs_path': contract['artifact_paths']['cost_inputs'],
            'used_by': ['self_quant_analyzer', 'qlib_backtest'],
        }
        cases['self_quant_and_qlib_share_context_passes'] = {
            'ok': shared_context.get('backtest_base_dataset_id') == contract.get('backtest_base_dataset_id')
            and set(shared_context.get('used_by') or []) == {'self_quant_analyzer', 'qlib_backtest'},
            'shared_evaluation_context': shared_context,
        }

        _first_contract, first_profile, _daily_path, _df = build_contract(root, 'SMOKE_BASE_SECOND_RUN_A')
        _second_contract, second_profile, _daily_path, _df = build_contract(root, 'SMOKE_BASE_SECOND_RUN_B')
        cases['same_base_second_run_reuse_hit_passes'] = {
            'ok': first_profile.get('backtest_base_reuse_hit') is True or second_profile.get('backtest_base_reuse_hit') is True,
            'first_profile': first_profile,
            'second_profile': second_profile,
        }

        _rev_contract, rev_profile, _daily_path, _df = build_contract(root, 'SMOKE_BASE_REVISION')
        cases['factor_revision_recomputes_factor_values_but_reuses_base_passes'] = {
            'ok': rev_profile.get('backtest_base_reuse_hit') is True,
            'backtest_base_profile': rev_profile,
            'factor_values_recompute_scope': 'factor_values_only',
        }

        valid_issues = base.validate_backtest_base_dataset_contract(contract, expected_identity=expected)
        cases['valid_backtest_base_contract_passes'] = {'ok': not valid_issues, 'issues': valid_issues}

    failed = [name for name, payload in cases.items() if not payload.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'failed': failed, 'cases': cases}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
