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
from factor_factory.artifact_identity import assert_identity_matches_strict
from factor_factory.mechanism_math.validator import (
    validate_mechanism_math_contract,
    validate_mechanism_math_contract_v2,
)
from factor_factory.measurement_program import validate_measurement_program
from factor_factory.evo_child_execution import validate_evo_child_execution_gate

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


def artifact_identity_checks(left_label: str, left: dict, right_label: str, right: dict):
    checks = []
    left_identity = left.get('artifact_identity') or {}
    right_identity = right.get('artifact_identity') or {}
    required = ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'producer', 'spec_hash', 'branch_id', 'artifact_role']
    checks.append(check(f'{left_label}_artifact_identity_present', isinstance(left_identity, dict) and bool(left_identity), f'{left_label}.artifact_identity missing'))
    checks.append(check(f'{right_label}_artifact_identity_present', isinstance(right_identity, dict) and bool(right_identity), f'{right_label}.artifact_identity missing'))
    checks.append(check(f'{left_label}_artifact_identity_required', all(nonempty_str(left_identity.get(k)) for k in required), f'{left_label}.artifact_identity required fields missing: {left_identity}'))
    checks.append(check(f'{right_label}_artifact_identity_required', all(nonempty_str(right_identity.get(k)) for k in required), f'{right_label}.artifact_identity required fields missing: {right_identity}'))
    if left_identity and right_identity:
        try:
            assert_identity_matches_strict(
                left_identity,
                right_identity,
                expected_label=left_label,
                actual_label=right_label,
                allowed_role_transitions={(left_identity.get('artifact_role'), right_identity.get('artifact_role'))},
            )
            checks.append(check(f'{left_label}_{right_label}_identity_match', True))
        except AssertionError as exc:
            checks.append(check(f'{left_label}_{right_label}_identity_match', False, str(exc)))
    return checks


def check_identity_transition(expected_label: str, expected: dict, actual_label: str, actual: dict, actual_role: str):
    expected_identity = expected.get('artifact_identity') or {}
    actual_identity = actual.get('artifact_identity') or {}
    if not expected_identity or not actual_identity:
        return [check(f'{expected_label}_{actual_label}_strict_identity', False, f'{expected_label}/{actual_label} artifact_identity missing')]
    try:
        assert_identity_matches_strict(
            expected_identity,
            actual_identity,
            expected_label=expected_label,
            actual_label=actual_label,
            allowed_role_transitions={(expected_identity.get('artifact_role'), actual_role)},
        )
        return [check(f'{expected_label}_{actual_label}_strict_identity', True)]
    except AssertionError as exc:
        return [check(f'{expected_label}_{actual_label}_strict_identity', False, str(exc))]


def evidence_identity_checks(case: dict, ev: dict, frm: dict):
    checks = []
    evidence_identity = case.get('evidence_identity') or {}
    evidence_quality = case.get('evidence_quality') or {}
    implementation_mode_decision = case.get('implementation_mode_decision') or {}
    source_refs = case.get('source_evidence_refs') or {}
    run_identity = frm.get('artifact_identity') or {}
    evidence_run_identity = evidence_identity.get('factor_run_master_identity') or {}

    checks.append(check('case_evidence_identity_present', isinstance(evidence_identity, dict) and bool(evidence_identity), 'factor_case_master.evidence_identity missing'))
    checks.append(check('case_implementation_mode_decision_present', isinstance(implementation_mode_decision, dict) and bool(implementation_mode_decision), 'factor_case_master.implementation_mode_decision missing'))
    checks.append(check('case_source_evidence_refs_present', isinstance(source_refs, dict) and bool(source_refs), 'factor_case_master.source_evidence_refs missing'))
    checks.append(check('case_evidence_quality_present', isinstance(evidence_quality, dict) and bool(evidence_quality), 'factor_case_master.evidence_quality missing'))
    checks.append(check('evidence_identity_factor_run_ref_present', nonempty_str(evidence_identity.get('factor_run_master_ref')), 'evidence_identity.factor_run_master_ref missing'))
    checks.append(check('evidence_identity_backend_refs_present', nonempty_list(evidence_identity.get('step4_backend_payload_refs')), 'evidence_identity.step4_backend_payload_refs missing'))
    checks.append(check('evidence_identity_mode_decision_present', isinstance(evidence_identity.get('implementation_mode_decision'), dict) and bool(evidence_identity.get('implementation_mode_decision')), 'evidence_identity.implementation_mode_decision missing'))

    if run_identity and evidence_run_identity:
        try:
            assert_identity_matches_strict(
                run_identity,
                evidence_run_identity,
                expected_label='factor_run_master',
                actual_label='evidence_identity.factor_run_master_identity',
                allowed_role_transitions={(run_identity.get('artifact_role'), evidence_run_identity.get('artifact_role'))},
            )
            checks.append(check('evidence_identity_factor_run_identity_match', True))
        except AssertionError as exc:
            checks.append(check('evidence_identity_factor_run_identity_match', False, str(exc)))
    else:
        checks.append(check('evidence_identity_factor_run_identity_match', False, 'factor_run_master identity missing from evidence_identity'))

    required_quality = [
        'step4_has_successful_backend',
        'self_quant_required_and_present',
        'long_side_metrics_present',
        'identity_chain_verified',
        'mode_decision_present',
    ]
    checks.append(check('evidence_quality_required_flags_present', all(key in evidence_quality for key in required_quality), f'evidence_quality missing required flags: {evidence_quality}'))
    if case.get('final_status') == 'validated':
        for key in required_quality:
            checks.append(check(f'validated_requires_{key}', evidence_quality.get(key) is True, f'validated Step5 requires evidence_quality.{key}=true'))
        checks.append(check('validated_evaluation_evidence_identity_present', isinstance(ev.get('evidence_identity'), dict) and bool(ev.get('evidence_identity')), 'validated factor_evaluation.evidence_identity missing'))
    return checks


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--expected-host-trust-manifest-sha256', default=None)
    a = ap.parse_args()
    rid = a.report_id

    case_path = OBJ / 'factor_case_master' / f'factor_case_master__{rid}.json'
    eval_path = OBJ / 'validation' / f'factor_evaluation__{rid}.json'
    frm_path = OBJ / 'factor_run_master' / f'factor_run_master__{rid}.json'
    fsm_path = OBJ / 'factor_spec_master' / f'factor_spec_master__{rid}.json'
    arch_dir = ARCH / rid

    checks = []
    errors = []
    warnings = []

    case_exists = check_file_exists(case_path)
    eval_exists = check_file_exists(eval_path)
    frm_exists = check_file_exists(frm_path)
    fsm_exists = check_file_exists(fsm_path)
    archive_nonempty = check_archive_dir_nonempty(arch_dir)

    checks.append(check('factor_case_master_exists', case_exists['exists'], f'missing {case_path}'))
    checks.append(check('factor_evaluation_exists', eval_exists['exists'], f'missing {eval_path}'))
    checks.append(check('factor_run_master_exists', frm_exists['exists'], f'missing {frm_path}'))
    checks.append(check('factor_spec_master_exists', fsm_exists['exists'], f'missing {fsm_path}'))
    checks.append(check('archive_dir_exists', arch_dir.exists(), f'missing {arch_dir}'))
    checks.append(check('archive_dir_nonempty', archive_nonempty['nonempty'], f'empty archive {arch_dir}'))

    if case_exists['exists'] and eval_exists['exists'] and frm_exists['exists'] and fsm_exists['exists']:
        case = load_json(case_path)
        ev = load_json(eval_path)
        frm = load_json(frm_path)
        fsm = load_json(fsm_path)
        evo_gate_reasons = validate_evo_child_execution_gate(
            workspace_root=FF,
            report_id=rid,
            factor_run_master=frm,
            expected_host_trust_manifest_sha256=(
                a.expected_host_trust_manifest_sha256
            ),
        )
        checks.append(check(
            'evo_child_execution_gate',
            not evo_gate_reasons,
            ';'.join(evo_gate_reasons) if evo_gate_reasons else None,
        ))
        checks.extend(artifact_identity_checks('factor_case_master', case, 'factor_evaluation', ev))
        checks.extend(check_identity_transition('factor_run_master', frm, 'factor_case_master', case, 'factor_case_master'))
        checks.extend(check_identity_transition('factor_run_master', frm, 'factor_evaluation', ev, 'factor_evaluation'))
        checks.extend(evidence_identity_checks(case, ev, frm))

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
        mechanism_math_contract = case.get('mechanism_math_contract') or math_review.get('mechanism_math_contract') or {}
        mechanism_math_contract_v2 = case.get('mechanism_math_contract_v2') or {}
        mechanism_math_failures = (
            validate_mechanism_math_contract(mechanism_math_contract)
            if isinstance(mechanism_math_contract, dict) and mechanism_math_contract
            else []
        )
        mechanism_math_v2_failures = (
            validate_mechanism_math_contract_v2(mechanism_math_contract_v2)
            if isinstance(mechanism_math_contract_v2, dict) and mechanism_math_contract_v2
            else []
        )
        measurement_program = case.get('mechanism_conditioned_measurement_program') or {}
        canonical = fsm.get('canonical_spec') or {}
        upstream_programs = [
            item for item in [
                fsm.get('mechanism_conditioned_measurement_program'),
                canonical.get('mechanism_conditioned_measurement_program'),
            ]
            if isinstance(item, dict) and item
        ]
        declared_node_ids = {
            str(node_id)
            for component in ((measurement_program.get('implementation') or {}).get('components') or [])
            if isinstance(component, dict)
            for node_id in (component.get('knowledge_node_ids') or [])
            if str(node_id).strip()
        } if isinstance(measurement_program, dict) else set()
        measurement_program_failures = (
            validate_measurement_program(
                measurement_program,
                available_knowledge_node_ids=declared_node_ids,
                require_web_executable=False,
            )
            if isinstance(measurement_program, dict) and measurement_program
            else []
        )
        adoption_constraints = case.get('adoption_constraints') or {}
        long_side_review = case.get('long_side_review') or math_review.get('long_side_objective') or {}
        information_set_legality = str(math_review.get('information_set_legality') or '').lower()
        overfit_risk = math_review.get('overfit_risk')

        checks.append(check('math_discipline_review_present', isinstance(math_review, dict) and bool(math_review), 'Step5 factor_case_master.math_discipline_review missing'))
        checks.append(check('mechanism_conditioned_measurement_program_present', isinstance(measurement_program, dict) and bool(measurement_program), 'Step5 factor_case_master.mechanism_conditioned_measurement_program missing'))
        checks.append(check('mechanism_conditioned_measurement_program_valid', not measurement_program_failures, f'Step5 measurement program invalid: {measurement_program_failures}'))
        checks.append(check('mechanism_conditioned_measurement_program_matches_step2', bool(upstream_programs) and all(item == measurement_program for item in upstream_programs), 'Step5 measurement program differs from factor_spec_master'))
        checks.append(check('mechanism_conditioned_measurement_program_ref_present', isinstance(math_review.get('mechanism_conditioned_measurement_program_ref'), dict) and bool(math_review.get('mechanism_conditioned_measurement_program_ref')), 'Step5 math_discipline_review.mechanism_conditioned_measurement_program_ref missing'))
        checks.append(check('legacy_mechanism_math_contract_valid_if_present', not mechanism_math_failures, f'Step5 legacy mechanism_math_contract invalid: {mechanism_math_failures}'))
        checks.append(check('legacy_mechanism_math_contract_v2_valid_if_present', not mechanism_math_v2_failures, f'Step5 legacy mechanism_math_contract_v2 invalid: {mechanism_math_v2_failures}'))
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
