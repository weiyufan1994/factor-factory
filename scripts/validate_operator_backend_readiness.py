#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PRODUCTION_EVIDENCE_SCOPES = {'production_scale', 'full_is'}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Validate a complete reviewed chain before manually changing an operator backend.'
    )
    parser.add_argument('--operator-id', required=True)
    parser.add_argument('--safe-validation-path', required=True)
    parser.add_argument('--approval-validation-path', required=True)
    parser.add_argument('--replacement-plan-path', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _load_json(path: str | Path) -> dict[str, Any] | None:
    candidate = Path(path)
    if not candidate.exists():
        return None
    return json.loads(candidate.read_text(encoding='utf-8'))


def _check_safety(prefix: str, safety: dict[str, Any], issues: list[str], *, read_only_required: bool = False) -> None:
    if read_only_required and safety.get('read_only_input') is not True:
        issues.append(f'{prefix}_read_only_input_must_be_true')
    for key in ['starts_backfill', 'writes_backend_config', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if key in safety and safety.get(key) is not False:
            issues.append(f'{prefix}_{key}_must_be_false')


def validate_payload(
    *,
    operator_id: str,
    safe_validation: dict[str, Any] | None,
    approval_validation: dict[str, Any] | None,
    replacement_plan: dict[str, Any] | None,
    safe_validation_path: Path,
    approval_validation_path: Path,
    replacement_plan_path: Path,
) -> dict[str, Any]:
    issues: list[str] = []
    if safe_validation is None:
        issues.append('safe_validation_missing_or_unreadable')
        safe_validation = {}
    if approval_validation is None:
        issues.append('approval_validation_missing_or_unreadable')
        approval_validation = {}
    if replacement_plan is None:
        issues.append('replacement_plan_missing_or_unreadable')
        replacement_plan = {}

    if safe_validation.get('verdict') != 'ACCEPT':
        issues.append('safe_validation_not_accept')
    if approval_validation.get('verdict') != 'ACCEPT':
        issues.append('approval_validation_not_accept')
    if replacement_plan.get('verdict') != 'ACCEPT':
        issues.append('replacement_plan_not_accept')

    evidence_scope = str(safe_validation.get('evidence_scope') or '')
    if evidence_scope not in PRODUCTION_EVIDENCE_SCOPES:
        issues.append('safe_validation_evidence_scope_not_production_scale_or_full_is')
    if approval_validation.get('approval_evidence_scope') != evidence_scope:
        issues.append('approval_validation_evidence_scope_mismatch')
    if approval_validation.get('safe_worker_validation_evidence_scope') != evidence_scope:
        issues.append('approval_safe_validation_evidence_scope_mismatch')
    if replacement_plan.get('evidence_scope') != evidence_scope:
        issues.append('replacement_plan_evidence_scope_mismatch')

    if approval_validation.get('operator_id') != operator_id:
        issues.append('approval_validation_operator_id_mismatch')
    if replacement_plan.get('operator_id') != operator_id:
        issues.append('replacement_plan_operator_id_mismatch')
    decision = approval_validation.get('decision') or {}
    if decision.get('operator_id') not in {None, operator_id}:
        issues.append('approval_decision_operator_id_mismatch')
    if decision.get('replacement_allowed') is not True:
        issues.append('approval_validation_replacement_not_allowed')

    default_backend = str(decision.get('default_backend') or replacement_plan.get('default_backend') or '')
    selected_backend = str(decision.get('selected_backend') or replacement_plan.get('selected_backend') or '')
    if not selected_backend:
        issues.append('selected_backend_missing')
    if selected_backend and default_backend and selected_backend == default_backend:
        issues.append('selected_backend_equals_default_backend')
    if replacement_plan.get('selected_backend') and selected_backend and replacement_plan.get('selected_backend') != selected_backend:
        issues.append('replacement_plan_selected_backend_mismatch')

    if replacement_plan.get('replacement_action') != 'plan_only':
        issues.append('replacement_plan_action_not_plan_only')
    if replacement_plan.get('required_next_step') != 'manual_config_change_after_review':
        issues.append('replacement_plan_next_step_not_manual_review')

    if safe_validation.get('operator_replacement_verdict') not in {None, 'PROMOTE'}:
        issues.append('safe_validation_operator_replacement_not_promote')
    if safe_validation.get('production_default_allowed') not in {None, False}:
        issues.append('safe_validation_production_default_allowed_must_be_false')

    _check_safety('safe_validation_safety', safe_validation.get('safety') or {}, issues, read_only_required=True)
    _check_safety('approval_validation_safety', approval_validation.get('safety') or {}, issues)
    _check_safety('replacement_plan_safety', replacement_plan.get('safety') or {}, issues)

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'readiness': 'ready_for_manual_config_change_after_review' if not issues else 'not_ready',
        'operator_id': operator_id,
        'default_backend': default_backend,
        'selected_backend': selected_backend,
        'evidence_scope': evidence_scope,
        'proof_paths': {
            'safe_validation_path': str(safe_validation_path),
            'approval_validation_path': str(approval_validation_path),
            'replacement_plan_path': str(replacement_plan_path),
        },
        'safe_validation_verdict': safe_validation.get('verdict'),
        'approval_validation_verdict': approval_validation.get('verdict'),
        'replacement_plan_verdict': replacement_plan.get('verdict'),
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    safe_validation_path = Path(args.safe_validation_path).expanduser()
    approval_validation_path = Path(args.approval_validation_path).expanduser()
    replacement_plan_path = Path(args.replacement_plan_path).expanduser()
    payload = validate_payload(
        operator_id=str(args.operator_id),
        safe_validation=_load_json(safe_validation_path),
        approval_validation=_load_json(approval_validation_path),
        replacement_plan=_load_json(replacement_plan_path),
        safe_validation_path=safe_validation_path,
        approval_validation_path=approval_validation_path,
        replacement_plan_path=replacement_plan_path,
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
