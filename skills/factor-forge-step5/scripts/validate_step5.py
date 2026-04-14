#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

W = Path('/home/ubuntu/.openclaw/workspace')
if str(W) not in sys.path:
    sys.path.insert(0, str(W))

from skills.factor_forge_step5.modules.io import load_json  # type: ignore
from skills.factor_forge_step5.modules.validator import (  # type: ignore
    check_archive_dir_nonempty,
    check_archive_paths_exist,
    check_file_exists,
    check_final_status_enum,
    check_no_placeholder_text,
)

OBJ = W / 'factorforge' / 'objects'
ARCH = W / 'factorforge' / 'archive'


def check(name: str, condition: bool, error: str | None = None):
    return {'name': name, 'ok': bool(condition), 'error': None if condition else error}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    a = ap.parse_args()
    rid = a.report_id

    case_path = OBJ / 'factor_case_master' / f'factor_case_master__{rid}.json'
    eval_path = OBJ / 'validation' / f'factor_evaluation__{rid}.json'
    arch_dir = ARCH / rid

    checks = []
    errors = []
    warnings = []

    case_exists = check_file_exists(case_path)
    eval_exists = check_file_exists(eval_path)
    archive_nonempty = check_archive_dir_nonempty(arch_dir)

    checks.append(check('factor_case_master_exists', case_exists['exists'], f'missing {case_path}'))
    checks.append(check('factor_evaluation_exists', eval_exists['exists'], f'missing {eval_path}'))
    checks.append(check('archive_dir_exists', arch_dir.exists(), f'missing {arch_dir}'))
    checks.append(check('archive_dir_nonempty', archive_nonempty['nonempty'], f'empty archive {arch_dir}'))

    if case_exists['exists'] and eval_exists['exists']:
        case = load_json(case_path)
        ev = load_json(eval_path)

        final_status = case.get('final_status')
        final_status_check = check_final_status_enum(final_status)
        checks.append(check('final_status_enum', final_status_check['valid'], final_status_check['reason']))
        checks.append(check('report_id_match', case.get('report_id') == ev.get('report_id') == rid, 'report_id mismatch'))
        checks.append(check('factor_id_match', case.get('factor_id') == ev.get('factor_id'), 'factor_id mismatch'))

        archive_paths = case.get('evidence', {}).get('archive_paths', [])
        checks.append(check('archive_paths_nonempty', bool(archive_paths), 'archive_paths empty'))
        archive_paths_check = check_archive_paths_exist(archive_paths)
        checks.append(check('archive_paths_exist', archive_paths_check['all_exist'], f"missing archive paths: {archive_paths_check['missing']}"))

        lessons = case.get('lessons') or []
        next_actions = case.get('next_actions') or []
        known_limits = case.get('known_limits') or []
        placeholder_check = check_no_placeholder_text([*lessons, *next_actions, *known_limits])
        checks.append(check('no_placeholder_text', placeholder_check['clean'], f"placeholder text detected: {placeholder_check['placeholders']}"))

        ev_summary = case.get('evaluation_summary') or {}
        cov = ev.get('coverage_summary') or {}
        checks.append(check('row_count_align', ev_summary.get('row_count') == cov.get('row_count'), 'row_count mismatch'))
        checks.append(check('date_count_align', ev_summary.get('date_count') == cov.get('date_count'), 'date_count mismatch'))
        checks.append(check('ticker_count_align', ev_summary.get('ticker_count') == cov.get('ticker_count'), 'ticker_count mismatch'))

        backend_summary = ev.get('backend_summary') or []
        successful_backend_count = sum(1 for item in backend_summary if item.get('status') == 'success')
        checks.append(check(
            'validated_requires_backend_success',
            final_status != 'validated' or successful_backend_count >= 1,
            'validated without successful backend'
        ))
        checks.append(check(
            'failed_cannot_claim_artifact_ready',
            final_status != 'failed' or not ev.get('artifact_ready'),
            'failed status cannot keep artifact_ready=true'
        ))
        checks.append(check(
            'failed_cannot_claim_successful_backend',
            final_status != 'failed' or successful_backend_count == 0,
            'failed status cannot keep successful backend'
        ))

        if final_status == 'validated' and ev.get('run_status') != 'success':
            warnings.append('validated case did not originate from run_status=success')

    for item in checks:
        if not item['ok']:
            errors.append(item['error'])

    result = 'PASS' if not errors else 'FAIL'
    payload = {
        'report_id': rid,
        'result': result,
        'checks': checks,
        'errors': errors,
        'warnings': warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result != 'PASS':
        raise SystemExit(1)
