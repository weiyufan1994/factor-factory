#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STEP4_VALIDATOR_PATH = ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / 'validate_step4.py'
spec = importlib.util.spec_from_file_location('factorforge_step4_validate_step4', STEP4_VALIDATOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f'failed to load Step4 validator from {STEP4_VALIDATOR_PATH}')
step4_validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(step4_validator)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def result(case: str, ok: bool, **extra: Any) -> dict[str, Any]:
    return {'case': case, 'ok': bool(ok), **extra}


def qlib_case(case: str, item: dict[str, Any], payload: dict[str, Any], *, expect_error: str | None = None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    step4_validator.validate_qlib_taxonomy(item, payload, issues)
    codes = [issue.get('code') for issue in issues]
    ok = (expect_error in codes) if expect_error else not codes
    return result(case, ok, issues=issues, codes=codes)


def qlib_not_attempted_optional_pass() -> dict[str, Any]:
    return qlib_case(
        'qlib_not_attempted_optional_pass',
        {'backend': 'qlib_backtest', 'status': 'skipped'},
        {
            'status': 'skipped',
            'mode': 'native',
            'qlib_native_status': 'not_attempted',
            'qlib_native_attempted': False,
            'qlib_preflight': {'provider_present': None, 'qlib_import_ok': None, 'qlib_python': sys.executable},
            'native_minimal_status': 'not_attempted',
            'native_backtest_status': 'not_attempted',
            'blocking_for_acceptance': False,
        },
    )


def qlib_preflight_blocked_optional_pass() -> dict[str, Any]:
    return qlib_case(
        'qlib_preflight_blocked_optional_pass',
        {'backend': 'qlib_backtest', 'status': 'skipped', 'qlib_native_status': 'preflight_blocked'},
        {
            'status': 'skipped',
            'mode': 'native',
            'qlib_native_status': 'preflight_blocked',
            'qlib_native_attempted': False,
            'qlib_preflight': {'provider_present': False, 'qlib_import_ok': True, 'qlib_python': sys.executable},
            'native_minimal_status': 'not_attempted',
            'native_backtest_status': 'not_attempted',
            'blocking_for_acceptance': False,
        },
    )


def qlib_partial_optional_pass() -> dict[str, Any]:
    return qlib_case(
        'qlib_partial_optional_pass',
        {'backend': 'qlib_backtest', 'status': 'partial', 'qlib_native_status': 'partial_payload'},
        {
            'status': 'partial',
            'mode': 'sample_stub',
            'qlib_native_status': 'partial_payload',
            'qlib_native_attempted': True,
            'qlib_preflight': {'provider_present': True, 'qlib_import_ok': False, 'qlib_python': sys.executable},
            'native_minimal_status': 'not_attempted',
            'native_backtest_status': 'not_attempted',
            'blocking_for_acceptance': False,
        },
    )


def qlib_partial_mandatory_blocks() -> dict[str, Any]:
    return qlib_case(
        'qlib_partial_mandatory_blocks',
        {'backend': 'qlib_backtest', 'status': 'partial', 'qlib_native_status': 'partial_payload', 'backend_config': {'qlib_full_success_mandatory': True}},
        {
            'status': 'partial',
            'mode': 'sample_stub',
            'qlib_native_status': 'partial_payload',
            'qlib_native_attempted': True,
            'qlib_preflight': {'provider_present': True, 'qlib_import_ok': False, 'qlib_python': sys.executable},
            'native_minimal_status': 'not_attempted',
            'native_backtest_status': 'not_attempted',
            'blocking_for_acceptance': True,
        },
        expect_error='BLOCK_QLIB_NATIVE_MANDATORY_NOT_SUCCESS',
    )


def qlib_native_success_pass() -> dict[str, Any]:
    return qlib_case(
        'qlib_native_success_pass',
        {'backend': 'qlib_backtest', 'status': 'success', 'qlib_native_status': 'native_minimal_success'},
        {
            'status': 'success',
            'mode': 'native_minimal',
            'qlib_native_status': 'native_minimal_success',
            'qlib_native_attempted': True,
            'qlib_preflight': {'provider_present': True, 'qlib_import_ok': True, 'qlib_python': sys.executable},
            'native_minimal_status': 'success',
            'native_backtest_status': 'not_attempted',
            'blocking_for_acceptance': False,
        },
    )


def acceptance_summary_payload() -> dict[str, Any]:
    return {
        'report_id': 'SMOKE',
        'run_id': 'SMOKE_RUN',
        'artifact_root': '/tmp/smoke',
        'repo_sha': 'deadbeef',
        'wrapper_validation_status': 'PASS',
        'step_status': {'step3': 'PASS', 'step3b': 'PASS', 'step4': 'PASS', 'step5': 'not_run', 'step6': 'not_run'},
        'step3b': {'backend': 'operator', 'input_format': 'parquet', 'sample_only': True, 'phase_seconds': {}, 'formula_engine_profile': {}, 'cache': {}},
        'step4': {'formal_factor_values_owner': 'Step4', 'formal_factor_values_path': '/tmp/smoke/factor.parquet', 'input_format': 'parquet', 'self_quant_status': 'success', 'qlib_native_status': 'partial_payload', 'phase_seconds': {}},
        'reuse': {'step3b_cache_reused_by_step4': False, 'reuse_gate_status': 'recomputed', 'reuse_reason': 'no_reusable_identity_matched'},
        'side_effects': {'generated_code_digest_changed': False, 'clean_data_digest_changed': False, 'official_record_written': False, 'search_worker_started': False},
        'financial_metrics': {'rank_ic_mean': None, 'long_side_annual_return': None, 'turnover_mean': None, 'cost_adjusted_annual_return': None, 'volatility_drag': None, 'max_drawdown': None, 'recovery_days': None, 'drawdown_recovery_area': None},
    }


def acceptance_summary_case(case: str, mutate: str | None = None, expect_error: str | None = None) -> dict[str, Any]:
    summary = acceptance_summary_payload()
    master = {'acceptance_summary': summary}
    if mutate == 'missing':
        master.pop('acceptance_summary')
    elif mutate == 'backend_split':
        summary['step4'].pop('qlib_native_status')
    elif mutate == 'reuse':
        summary['reuse'].pop('reuse_gate_status')
    issues: list[dict[str, Any]] = []
    step4_validator.validate_acceptance_summary(master, issues)
    codes = [issue.get('code') for issue in issues]
    ok = (expect_error in codes) if expect_error else not codes
    return result(case, ok, codes=codes, issues=issues)


def top_level_fields_case() -> dict[str, Any]:
    payload = {'report_id': 'SMOKE', 'run_id': 'RUN', 'artifact_root': '/tmp/smoke', 'producer': 'step4', 'status': 'success', 'verdict': 'PASS'}
    issues: list[dict[str, Any]] = []
    step4_validator.top_level_acceptance_fields('factor_run_master', payload, issues)
    return result('formal_artifact_top_level_acceptance_fields_pass', not issues, issues=issues)


def top_level_missing_blocks() -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    step4_validator.top_level_acceptance_fields('factor_run_master', {'report_id': 'SMOKE'}, issues)
    codes = [issue.get('code') for issue in issues]
    return result('formal_artifact_top_level_acceptance_fields_missing_blocks', 'FACTOR_RUN_MASTER_TOP_LEVEL_ACCEPTANCE_FIELD_MISSING' in codes, codes=codes)


def verdict_for(cases: list[dict[str, Any]]) -> str:
    return 'ACCEPT' if all(case.get('ok') for case in cases) else 'BLOCK'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--root', default='/tmp/factorforge_production_acceptance_contract_smoke')
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cases = [
        qlib_not_attempted_optional_pass(),
        qlib_preflight_blocked_optional_pass(),
        qlib_partial_optional_pass(),
        qlib_partial_mandatory_blocks(),
        qlib_native_success_pass(),
        acceptance_summary_case('acceptance_summary_missing_blocks', mutate='missing', expect_error='BLOCK_ACCEPTANCE_SUMMARY_MISSING'),
        acceptance_summary_case('acceptance_summary_missing_backend_split_blocks', mutate='backend_split', expect_error='BLOCK_ACCEPTANCE_SUMMARY_BACKEND_SPLIT_MISSING'),
        acceptance_summary_case('acceptance_summary_missing_reuse_status_blocks', mutate='reuse', expect_error='BLOCK_ACCEPTANCE_SUMMARY_REUSE_STATUS_MISSING'),
        acceptance_summary_case('valid_acceptance_summary_passes'),
        top_level_fields_case(),
        top_level_missing_blocks(),
    ]
    summary = {'verdict': verdict_for(cases), 'canonical_pollution': False, 'cases': cases}
    summary_path = root / 'objects' / 'validation' / 'production_acceptance_contract_smoke_summary.json'
    write_json(summary_path, summary)
    print(json.dumps({'summary_path': str(summary_path), 'verdict': summary['verdict']}, ensure_ascii=False))
    return 0 if summary['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
