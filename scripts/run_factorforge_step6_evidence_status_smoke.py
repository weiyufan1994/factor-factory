#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_validator():
    path = REPO_ROOT / 'skills/factor-forge-step6/scripts/validate_step6.py'
    scripts_dir = str(path.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location('step6_validator_evidence_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runner():
    path = REPO_ROOT / 'skills/factor-forge-step6/scripts/run_step6.py'
    spec = importlib.util.spec_from_file_location('step6_runner_evidence_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_status() -> dict:
    return {
        'version': 'factorforge_step6_evidence_status_v1',
        'wrapper_validation_status': 'PASS',
        'self_quant_evidence_status': 'complete',
        'qlib_native_status': 'partial_payload',
        'long_side_evidence_status': 'complete',
        'cost_model_status': 'complete',
        'drawdown_geometry_status': 'complete',
        'research_decision': 'iterate',
        'promotion_gate_status': 'not_applicable',
    }


def has(checks: list[dict], token: str) -> bool:
    return any(token in str(item.get('error')) or token in item.get('name', '') for item in checks)


def main() -> None:
    module = load_validator()
    runner = load_runner()
    cases: dict[str, dict] = {}

    status = valid_status()
    status['status'] = 'partial'
    checks = module.validate_evidence_status_contract(status)
    cases['generic_partial_status_blocks'] = {'ok': has(checks, 'BLOCK_STEP6_EVIDENCE_STATUS_GENERIC_PARTIAL'), 'checks': checks}

    for case_name, field, token in [
        ('missing_wrapper_status_blocks', 'wrapper_validation_status', 'BLOCK_STEP6_EVIDENCE_STATUS_WRAPPER_MISSING'),
        ('missing_self_quant_status_blocks', 'self_quant_evidence_status', 'BLOCK_STEP6_EVIDENCE_STATUS_SELF_QUANT_MISSING'),
        ('missing_qlib_status_blocks', 'qlib_native_status', 'BLOCK_STEP6_EVIDENCE_STATUS_QLIB_MISSING'),
        ('missing_research_decision_blocks', 'research_decision', 'BLOCK_STEP6_EVIDENCE_STATUS_RESEARCH_DECISION_MISSING'),
    ]:
        status = valid_status()
        status.pop(field)
        checks = module.validate_evidence_status_contract(status)
        cases[case_name] = {'ok': has(checks, token), 'checks': checks}

    checks = module.validate_evidence_status_contract(valid_status())
    failed_checks = [item for item in checks if item.get('status') == 'BLOCK']
    cases['valid_evidence_status_passes'] = {'ok': not failed_checks, 'checks': checks}

    status = valid_status()
    status['qlib_native_status'] = 'not_applicable'
    checks = module.validate_evidence_status_contract(status)
    failed_checks = [item for item in checks if item.get('status') == 'BLOCK']
    mapped = runner._qlib_native_status(
        {'qlib_backtest': {'status': 'skipped', 'qlib_native_status': 'not_applicable'}},
        {'qlib_backtest': 'skipped'},
    )
    cases['qlib_not_applicable_status_passes'] = {
        'ok': not failed_checks and mapped == 'not_applicable',
        'checks': checks,
        'mapped': mapped,
    }

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
