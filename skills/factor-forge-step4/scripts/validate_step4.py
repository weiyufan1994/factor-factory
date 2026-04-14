#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

W = Path('/home/ubuntu/.openclaw/workspace')
OBJ = W / 'factorforge' / 'objects'
ALLOWED = {'success', 'partial', 'failed'}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    rid = args.report_id

    run_master_path = OBJ / 'factor_run_master' / f'factor_run_master__{rid}.json'
    diag_path = OBJ / 'validation' / f'factor_run_diagnostics__{rid}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step5__{rid}.json'
    revision_path = OBJ / 'validation' / f'factor_run_validation_revision__{rid}.json'

    assert run_master_path.exists(), f'missing run master: {run_master_path}'
    assert diag_path.exists(), f'missing diagnostics: {diag_path}'
    assert handoff_path.exists(), f'missing handoff: {handoff_path}'

    run_master = load_json(run_master_path)
    diagnostics = load_json(diag_path)
    handoff = load_json(handoff_path)

    issues: list[dict[str, Any]] = []
    proposed_status = run_master.get('run_status')

    if proposed_status not in ALLOWED:
        issues.append({'severity': 'error', 'code': 'INVALID_RUN_STATUS', 'message': f'invalid run_status={proposed_status}'})
        proposed_status = 'failed'

    output_paths = [Path(p) for p in run_master.get('output_paths', [])]
    output_exists = [p.exists() for p in output_paths]

    if run_master.get('run_status') in {'success', 'partial'}:
        if not output_paths:
            issues.append({'severity': 'error', 'code': 'MISSING_OUTPUT_PATHS', 'message': 'success/partial requires material output paths'})
            proposed_status = 'failed'
        elif not all(output_exists):
            issues.append({'severity': 'error', 'code': 'OUTPUT_PATH_NOT_FOUND', 'message': 'declared output path missing', 'evidence': {'paths': [str(p) for p in output_paths], 'exists': output_exists}})
            proposed_status = 'failed'
        elif diagnostics.get('output_validation', {}).get('row_count', 0) <= 0:
            issues.append({'severity': 'error', 'code': 'NONPOSITIVE_ROW_COUNT', 'message': 'success/partial requires positive row count'})
            proposed_status = 'failed'

    if run_master.get('run_status') == 'partial':
        scope = handoff.get('recommended_step5_scope')
        notes = ' '.join(handoff.get('notes_for_step5', []))
        if scope != 'partial_scope_only' and 'partial' not in notes.lower():
            issues.append({'severity': 'error', 'code': 'PARTIAL_SCOPE_UNDECLARED', 'message': 'partial result must declare evaluable scope in handoff'})
            proposed_status = 'failed'

    if run_master.get('run_status') == 'failed' and not run_master.get('failure_reason'):
        issues.append({'severity': 'error', 'code': 'FAILED_WITHOUT_REASON', 'message': 'failed run must declare failure_reason'})

    eval_plan = run_master.get('evaluation_plan')
    eval_results = run_master.get('evaluation_results', {})
    backend_runs = eval_results.get('backend_runs') if isinstance(eval_results, dict) else None
    if not isinstance(eval_plan, dict):
        issues.append({'severity': 'error', 'code': 'MISSING_EVALUATION_PLAN', 'message': 'factor_run_master must expose evaluation_plan'})
        proposed_status = 'failed'
    else:
        if not isinstance(eval_plan.get('backends'), list) or not eval_plan.get('backends'):
            issues.append({'severity': 'error', 'code': 'INVALID_EVALUATION_BACKENDS', 'message': 'evaluation_plan.backends must be a non-empty list'})
            proposed_status = 'failed'
        if eval_plan.get('metric_policy') in {None, ''}:
            issues.append({'severity': 'error', 'code': 'MISSING_METRIC_POLICY', 'message': 'evaluation_plan.metric_policy must be explicit'})
            proposed_status = 'failed'

    if not isinstance(backend_runs, list):
        issues.append({'severity': 'error', 'code': 'MISSING_BACKEND_RUNS', 'message': 'factor_run_master must expose evaluation_results.backend_runs'})
        proposed_status = 'failed'
    else:
        for item in backend_runs:
            if item.get('status') in {'success', 'partial'}:
                payload_path = item.get('payload_path')
                if not payload_path or not Path(payload_path).exists():
                    issues.append({'severity': 'error', 'code': 'BACKEND_PAYLOAD_MISSING', 'message': 'backend claims success/partial but payload_path is missing', 'evidence': item})
                    proposed_status = 'failed'
                else:
                    payload = load_json(Path(payload_path))
                    if item.get('backend') == 'qlib_backtest':
                        if payload.get('mode') not in {'sample_stub', 'native_minimal'}:
                            issues.append({'severity': 'error', 'code': 'QLIB_MODE_INVALID', 'message': 'qlib_backtest payload must declare supported mode', 'evidence': payload})
                            proposed_status = 'failed'
                        if payload.get('mode') == 'native_minimal':
                            metrics = payload.get('native_backtest_metrics') or {}
                            artifacts = payload.get('artifacts') or {}
                            if metrics.get('nonzero_value_rows') in {None, 0}:
                                issues.append({'severity': 'error', 'code': 'QLIB_NATIVE_EMPTY_PORTFOLIO', 'message': 'native qlib payload must show nonzero portfolio activity', 'evidence': metrics})
                                proposed_status = 'failed'
                            required_artifacts = ['portfolio_value_timeseries_png', 'benchmark_vs_strategy_png', 'turnover_timeseries_png']
                            for key in required_artifacts:
                                ap = artifacts.get(key)
                                if not ap or not Path(ap).exists():
                                    issues.append({'severity': 'error', 'code': 'QLIB_NATIVE_ARTIFACT_MISSING', 'message': f'missing qlib native artifact: {key}', 'evidence': artifacts})
                                    proposed_status = 'failed'

    if diagnostics.get('run_status') != run_master.get('run_status'):
        issues.append({'severity': 'warning', 'code': 'RUN_STATUS_MISMATCH', 'message': 'diagnostics run_status differs from run_master', 'evidence': {'run_master': run_master.get('run_status'), 'diagnostics': diagnostics.get('run_status')}})

    verdict = 'PASS' if not any(i['severity'] == 'error' for i in issues) else 'FAIL'
    revision = {
        'report_id': rid,
        'validator_generated_at_utc': utc_now(),
        'original_run_status': run_master.get('run_status'),
        'validated_run_status': proposed_status,
        'verdict': verdict,
        'issues': issues,
        'notes': [
            'Validator may output final acceptance conclusion.',
            'Validator does not silently rewrite original execution object.',
            'If statuses differ, this revision record is the explicit correction artifact.'
        ]
    }
    write_json(revision_path, revision)
    print(f'RESULT: {verdict}')
    print(f'VALIDATED_RUN_STATUS: {proposed_status}')


if __name__ == '__main__':
    main()
