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
    spec = importlib.util.spec_from_file_location('step4_validator_acceptance_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_summary() -> dict:
    return {
        'version': 'factorforge_production_acceptance_summary_v1',
        'report_id': 'SMOKE',
        'factor_id': 'SMOKE_FACTOR',
        'run_id': 'RUN_SMOKE',
        'artifact_root': '/tmp/factorforge-smoke',
        'repo_sha': 'abc123',
        'wrapper_status': 'PASS',
        'validator_verdicts': {'step4': 'PASS'},
        'step3b': {
            'backend': 'step3b_sample_proof',
            'input_format': 'parquet',
            'sample_only': True,
            'is_formal_factor_values': False,
            'phase_seconds': {},
            'formula_engine_profile': {},
            'parity_checked': True,
        },
        'step4': {
            'formal_factor_values_owner': 'Step4',
            'formal_factor_values_path': '/tmp/factor.parquet',
            'self_quant_status': 'success',
            'qlib_native_status': 'partial_payload',
            'phase_seconds': {},
        },
        'reuse': {
            'step3b_cache_reused_by_step4': False,
            'reuse_gate_status': 'recomputed',
            'reuse_reason': 'smoke',
        },
        'side_effects': {
            'clean_data_mutated': False,
            'generated_code_digest_changed': False,
            'official_record_written': False,
            'search_worker_started': False,
        },
        'metrics': {},
    }


def validate(module, summary: dict | None) -> list[dict]:
    issues: list[dict] = []
    module.validate_acceptance_summary(summary, issues)
    return issues


def has(issues: list[dict], code: str) -> bool:
    return any(item.get('code') == code for item in issues)


def main() -> None:
    module = load_validator()
    cases: dict[str, dict] = {}

    issues = validate(module, None)
    cases['missing_acceptance_summary_blocks'] = {'ok': has(issues, 'BLOCK_ACCEPTANCE_SUMMARY_MISSING'), 'issues': issues}

    summary = base_summary()
    summary.pop('run_id')
    issues = validate(module, summary)
    cases['acceptance_summary_missing_run_identity_blocks'] = {'ok': has(issues, 'BLOCK_ACCEPTANCE_SUMMARY_RUN_IDENTITY_MISSING'), 'issues': issues}

    summary = base_summary()
    summary['step4'].pop('qlib_native_status')
    issues = validate(module, summary)
    cases['acceptance_summary_missing_backend_split_blocks'] = {'ok': has(issues, 'BLOCK_ACCEPTANCE_SUMMARY_BACKEND_SPLIT_MISSING'), 'issues': issues}

    summary = base_summary()
    summary['reuse'].pop('reuse_gate_status')
    issues = validate(module, summary)
    cases['acceptance_summary_missing_reuse_status_blocks'] = {'ok': has(issues, 'BLOCK_ACCEPTANCE_SUMMARY_REUSE_STATUS_MISSING'), 'issues': issues}

    summary = base_summary()
    summary['side_effects'].pop('official_record_written')
    issues = validate(module, summary)
    cases['acceptance_summary_missing_side_effects_blocks'] = {'ok': has(issues, 'BLOCK_ACCEPTANCE_SUMMARY_SIDE_EFFECTS_MISSING'), 'issues': issues}

    issues = validate(module, base_summary())
    cases['valid_acceptance_summary_passes'] = {'ok': not issues, 'issues': issues}

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
