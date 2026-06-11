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
    path = REPO_ROOT / 'skills/factor-forge-step4/scripts/validate_step4.py'
    spec = importlib.util.spec_from_file_location('step4_validator_qlib_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(module, payload: dict, mandatory: bool = False) -> list[dict]:
    issues: list[dict] = []
    module.validate_qlib_taxonomy(payload, mandatory=mandatory, issues=issues)
    return issues


def has(issues: list[dict], code: str) -> bool:
    return any(item.get('code') == code for item in issues)


def main() -> None:
    module = load_validator()
    cases: dict[str, dict] = {}

    issues = validate(module, {'status': 'success', 'mode': 'sample_stub', 'qlib_native_status': 'partial_payload'})
    cases['qlib_partial_labeled_success_blocks'] = {
        'ok': has(issues, 'BLOCK_QLIB_PARTIAL_LABELED_SUCCESS'),
        'issues': issues,
    }

    issues = validate(module, {'status': 'success', 'mode': 'sample_stub', 'qlib_native_status': 'native_minimal_success'})
    cases['qlib_sample_stub_labeled_native_success_blocks'] = {
        'ok': has(issues, 'BLOCK_QLIB_SAMPLE_STUB_NATIVE_SUCCESS'),
        'issues': issues,
    }

    issues = validate(module, {'status': 'partial', 'mode': 'sample_stub', 'qlib_native_status': 'partial_payload'}, mandatory=False)
    cases['qlib_partial_optional_passes_with_explicit_status'] = {'ok': not issues, 'issues': issues}

    issues = validate(module, {'status': 'partial', 'mode': 'sample_stub', 'qlib_native_status': 'partial_payload'}, mandatory=True)
    cases['qlib_partial_mandatory_blocks'] = {'ok': has(issues, 'BLOCK_QLIB_PARTIAL_MANDATORY'), 'issues': issues}

    issues = validate(module, {'status': 'skipped', 'mode': 'native', 'qlib_native_status': 'preflight_ready'}, mandatory=False)
    cases['qlib_preflight_ready_passes_as_preflight_only'] = {'ok': not issues, 'issues': issues}

    issues = validate(module, {'status': 'skipped', 'mode': 'sample_stub', 'qlib_native_status': 'not_applicable'}, mandatory=False)
    cases['qlib_not_applicable_passes_as_explicit_skip'] = {'ok': not issues, 'issues': issues}

    issues = validate(module, {'status': 'success', 'mode': 'native_minimal', 'qlib_native_status': 'native_backtest_success'}, mandatory=True)
    cases['qlib_native_backtest_success_passes'] = {'ok': not issues, 'issues': issues}

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
