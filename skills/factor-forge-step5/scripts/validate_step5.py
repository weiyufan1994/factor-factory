#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
W = FF.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FF) not in sys.path:
    sys.path.append(str(FF))

from skills.factor_forge_step5.modules.io import load_json  # type: ignore
from skills.factor_forge_step5.modules.validator import (  # type: ignore
    check_archive_dir_nonempty,
    check_archive_paths_exist,
    check_file_exists,
    check_final_status_enum,
    check_no_placeholder_text,
)

OBJ = FF / 'objects'
ARCH = FF / 'archive'


def check(name: str, condition: bool, error: str | None = None, severity: str = 'BLOCK'):
    status = 'PASS' if condition else severity
    return {
        'name': name,
        'ok': bool(condition),
        'status': status,
        'severity': severity,
        'error': None if condition else error,
    }


def nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value) -> bool:
    return isinstance(value, list) and bool(value)


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
        quality_gate = ev.get('step4_quality_gate') or {}
        case_quality_gate = case.get('step4_quality_gate') or {}
        math_review = case.get('math_discipline_review') or {}
        adoption_constraints = case.get('adoption_constraints') or {}
        long_side_review = case.get('long_side_review') or math_review.get('long_side_objective') or {}
        information_set_legality = str(math_review.get('information_set_legality') or '').lower()
        overfit_risk = math_review.get('overfit_risk')

        checks.append(check('math_discipline_review_present', isinstance(math_review, dict) and bool(math_review), 'Step5 factor_case_master.math_discipline_review missing'))
        checks.append(check('information_set_legality_present', nonempty_str(math_review.get('information_set_legality')), 'information_set_legality missing'))
        checks.append(check('spec_stability_present', isinstance(math_review.get('spec_stability'), dict) and bool(math_review.get('spec_stability')), 'spec_stability missing'))
        checks.append(check('signal_vs_portfolio_gap_present', nonempty_str(math_review.get('signal_vs_portfolio_gap')), 'signal_vs_portfolio_gap missing'))
        checks.append(check('long_side_review_present', isinstance(long_side_review, dict) and bool(long_side_review), 'long_side_review missing'))
        checks.append(check('long_only_no_short_selling', adoption_constraints.get('no_short_selling') is True, 'Step5 must record no_short_selling=true'))
        checks.append(check('long_only_no_direct_decile_trading', adoption_constraints.get('no_direct_decile_trading') is True, 'Step5 must record no_direct_decile_trading=true'))
        checks.append(check('long_only_primary_objective', adoption_constraints.get('primary_objective') == 'long_side_risk_adjusted_alpha', 'Step5 primary objective must be long_side_risk_adjusted_alpha'))
        factor_business = long_side_review.get('factor_as_business_review') if isinstance(long_side_review, dict) else {}
        checks.append(check('long_side_risk_adjusted_review_present', isinstance(factor_business, dict) and bool(factor_business), 'Step5 long_side_review.factor_as_business_review missing'))
        thresholds = (factor_business or {}).get('thresholds') if isinstance(factor_business, dict) else {}
        checks.append(check('long_side_sharpe_thresholds_present', isinstance(thresholds, dict) and 'candidate_min_sharpe' in thresholds and 'official_min_sharpe' in thresholds, 'Step5 must record candidate/official long-side Sharpe thresholds'))
        checks.append(check('revision_scope_expression_only', adoption_constraints.get('revision_scope') == 'factor_expression_and_step3b_code_only', 'Step5 revision scope must be factor_expression_and_step3b_code_only'))
        checks.append(check(
            'validated_case_cannot_have_failed_long_side_review',
            final_status != 'validated' or long_side_review.get('status') != 'failed',
            'validated Step5 case cannot have failed long-side evidence under no-short mandate',
        ))
        checks.append(check(
            'validated_case_requires_supportive_long_side_review',
            final_status != 'validated' or long_side_review.get('status') in {'supportive', 'official_ready'},
            'validated Step5 case requires supportive or official_ready long-side risk-adjusted evidence',
        ))
        quality = (factor_business or {}).get('factor_business_quality') if isinstance(factor_business, dict) else {}
        required_business_fields = [
            'gross_revenue',
            'trading_cogs',
            'net_revenue_after_cogs',
            'volatility',
            'risk_capital_required',
            'capital_impairment',
            'economic_net_alpha',
        ]
        missing_business_fields = [
            key for key in required_business_fields
            if not isinstance(quality, dict) or quality.get(key) is None
        ]
        checks.append(check(
            'validated_case_requires_factor_business_quality',
            final_status != 'validated' or not missing_business_fields,
            f'validated Step5 case missing factor business quality fields: {missing_business_fields}',
        ))
        checks.append(check('overfit_risk_present', nonempty_list(overfit_risk), 'overfit_risk missing'))
        checks.append(check('step4_quality_gate_present', isinstance(quality_gate, dict) and bool(quality_gate), 'Step5 evaluation.step4_quality_gate missing'))
        checks.append(check('step4_quality_gate_copied_to_case', case_quality_gate.get('verdict') == quality_gate.get('verdict'), 'factor_case_master must copy step4_quality_gate verdict'))
        checks.append(check(
            'step4_quality_gate_not_blocking_for_nonfailed',
            final_status == 'failed' or quality_gate.get('verdict') != 'BLOCK',
            f'Step4 quality gate BLOCK must force final_status=failed: {quality_gate}',
        ))
        checks.append(check(
            'information_set_legality_not_illegal',
            'illegal' not in information_set_legality,
            f'information_set_legality is blocking: {math_review.get("information_set_legality")}',
        ))
        checks.append(check(
            'information_set_legality_confirmed_for_validated_case',
            final_status != 'validated' or 'requires_researcher_confirmation' not in information_set_legality,
            'validated case still requires researcher confirmation for information-set legality',
            severity='WARN',
        ))

        checks.append(check(
            'validated_requires_backend_success',
            final_status != 'validated' or successful_backend_count >= 1,
            'validated without successful backend'
        ))
        quality_gate_blocks = quality_gate.get('verdict') == 'BLOCK'
        checks.append(check(
            'failed_cannot_claim_artifact_ready_without_quality_gate_block',
            final_status != 'failed' or quality_gate_blocks or not ev.get('artifact_ready'),
            'failed status cannot keep artifact_ready=true unless Step4 quality gate deliberately blocked malformed evidence'
        ))
        checks.append(check(
            'failed_cannot_claim_successful_backend_without_quality_gate_block',
            final_status != 'failed' or quality_gate_blocks or successful_backend_count == 0,
            'failed status cannot keep successful backend unless Step4 quality gate deliberately blocked malformed evidence'
        ))

        if final_status == 'validated' and ev.get('run_status') != 'success':
            warnings.append('validated case did not originate from run_status=success')

    for item in checks:
        if item['status'] == 'BLOCK':
            errors.append(item['error'])
        elif item['status'] == 'WARN':
            warnings.append(item['error'])

    result = 'BLOCK' if errors else 'WARN' if warnings else 'PASS'
    payload = {
        'report_id': rid,
        'result': result,
        'checks': checks,
        'errors': errors,
        'warnings': warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result == 'BLOCK':
        raise SystemExit(1)
