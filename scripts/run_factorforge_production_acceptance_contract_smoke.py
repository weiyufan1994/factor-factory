#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
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


def validate_formal_signal_coverage(module, run_master: dict, diagnostics: dict) -> list[dict]:
    issues: list[dict] = []
    module.validate_formal_signal_coverage(run_master=run_master, diagnostics=diagnostics, issues=issues)
    return issues


def has(issues: list[dict], code: str) -> bool:
    return any(item.get('code') == code for item in issues)


def run_performance_profile(root: Path, report_id: str) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / 'scripts/run_factorforge_performance_profile.py'),
            '--report-id',
            report_id,
            '--factorforge-root',
            str(root),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {'stdout': proc.stdout}
    return {'rc': proc.returncode, 'stdout': payload, 'stderr': proc.stderr}


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

    issues = validate_formal_signal_coverage(
        module,
        {'run_status': 'success', 'signal_column': 'factor_value'},
        {'quality_checks': {'null_ratio': {'factor_value': 0.9884}}},
    )
    cases['formal_signal_sparse_null_ratio_blocks'] = {
        'ok': has(issues, 'BLOCK_STEP4_FORMAL_SIGNAL_NON_NULL_COVERAGE_LOW'),
        'issues': issues,
    }

    issues = validate_formal_signal_coverage(
        module,
        {
            'run_status': 'success',
            'formal_signal_coverage': {
                'coverage_gate_verdict': 'PASS',
                'factor_value_non_null_coverage': 0.98,
                'nonnull_end': '20250711',
                'actual_window': {'end': '20250711'},
            },
        },
        {'quality_checks': {}},
    )
    cases['formal_signal_dense_coverage_passes'] = {'ok': not issues, 'issues': issues}

    with tempfile.TemporaryDirectory(prefix='factorforge_acceptance_summary_smoke_') as tmp:
        root = Path(tmp)
        report_id = 'SMOKE_ACCEPTANCE_PROFILE'
        factor_run_master_path = root / 'objects/factor_run_master' / f'factor_run_master__{report_id}.json'
        factor_run_master_path.parent.mkdir(parents=True, exist_ok=True)
        factor_run_master_path.write_text(
            json.dumps({'acceptance_summary': base_summary()}, ensure_ascii=False),
            encoding='utf-8',
        )
        result = run_performance_profile(root, report_id)
        profile = result.get('stdout') if isinstance(result.get('stdout'), dict) else {}
        acceptance = profile.get('acceptance_summary') if isinstance(profile.get('acceptance_summary'), dict) else {}
        cases['performance_profile_exposes_acceptance_summary'] = {
            'ok': result.get('rc') == 0 and acceptance.get('version') == 'factorforge_production_acceptance_summary_v1',
            'rc': result.get('rc'),
            'diagnostic_codes': profile.get('diagnostic_codes'),
            'acceptance_summary_version': acceptance.get('version'),
        }

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
