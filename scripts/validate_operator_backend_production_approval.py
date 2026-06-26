#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.operator_backend_policy import decide_operator_backend  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a production approval artifact before allowing a non-default operator backend.')
    parser.add_argument('--profile-path', required=True)
    parser.add_argument('--validation-path', required=True)
    parser.add_argument('--approval-path', required=True)
    parser.add_argument('--safe-worker-bundle-path')
    parser.add_argument('--safe-worker-validation-path')
    parser.add_argument('--operator-id', required=True)
    parser.add_argument('--default-backend', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _validate_approval_fields(approval: dict[str, Any], *, operator_id: str) -> list[str]:
    issues: list[str] = []
    if approval.get('verdict') != 'ACCEPT':
        issues.append('approval_verdict_not_accept')
    if approval.get('approval_scope') != 'production_default_backend':
        issues.append('approval_scope_not_production_default_backend')
    if approval.get('operator_id') != operator_id:
        issues.append('approval_operator_id_mismatch')
    if not approval.get('approved_backend'):
        issues.append('approved_backend_missing')
    if approval.get('production_default_allowed') is not True:
        issues.append('approval_production_default_allowed_not_true')
    if not approval.get('approved_by'):
        issues.append('approved_by_missing')
    if not approval.get('approval_reason'):
        issues.append('approval_reason_missing')
    if approval.get('evidence_scope') not in {'production_scale', 'full_is'}:
        issues.append('approval_evidence_scope_not_production_scale_or_full_is')
    return issues


def _validate_safe_worker_validation(
    safe_worker_validation: dict[str, Any] | None,
    *,
    approval_evidence_scope: str | None = None,
) -> list[str]:
    issues: list[str] = []
    if not safe_worker_validation:
        return ['safe_worker_validation_missing']
    if safe_worker_validation.get('verdict') != 'ACCEPT':
        issues.append('safe_worker_validation_not_accept')
    if int(safe_worker_validation.get('input_row_count') or 0) <= 0:
        issues.append('safe_worker_validation_input_row_count_missing')
    if safe_worker_validation.get('benchmark_scope') not in {None, 'real_bounded_read_only'}:
        issues.append('safe_worker_validation_benchmark_scope_not_real_bounded_read_only')
    if safe_worker_validation.get('production_default_allowed') not in {None, False}:
        issues.append('safe_worker_validation_production_default_allowed_must_be_false')
    if safe_worker_validation.get('operator_replacement_verdict') != 'PROMOTE':
        issues.append('safe_worker_validation_operator_replacement_not_promote')
    if approval_evidence_scope and safe_worker_validation.get('evidence_scope') != approval_evidence_scope:
        issues.append('safe_worker_validation_evidence_scope_mismatch')
    safety = safe_worker_validation.get('safety') or {}
    if safety and safety.get('read_only_input') is not True:
        issues.append('safe_worker_validation_read_only_input_must_be_true')
    for key in ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if safety and safety.get(key) is not False:
            issues.append(f'safe_worker_validation_safety_{key}_must_be_false')
    return issues


def _validate_safe_worker_bundle(
    safe_worker_bundle: dict[str, Any] | None,
    safe_worker_validation: dict[str, Any] | None = None,
    approval_evidence_scope: str | None = None,
) -> list[str]:
    issues: list[str] = []
    if not safe_worker_bundle:
        return ['safe_worker_bundle_missing']
    if safe_worker_bundle.get('verdict') != 'ACCEPT':
        issues.append('safe_worker_bundle_verdict_not_accept')
    preflight = safe_worker_bundle.get('preflight_summary') or {}
    worker_benchmark = safe_worker_bundle.get('worker_benchmark_summary') or {}
    worker_validation = safe_worker_bundle.get('worker_validation_summary') or {}
    safety = safe_worker_bundle.get('safety') or {}
    if preflight.get('verdict') != 'ACCEPT':
        issues.append('safe_worker_preflight_not_accept')
    if worker_benchmark.get('verdict') != 'ACCEPT':
        issues.append('safe_worker_benchmark_not_accept')
    if safe_worker_validation is not None:
        issues.extend(
            _validate_safe_worker_validation(
                safe_worker_validation,
                approval_evidence_scope=approval_evidence_scope,
            )
        )
    elif not worker_validation:
        issues.append('safe_worker_validation_missing')
    else:
        if worker_validation.get('verdict') != 'ACCEPT':
            issues.append('safe_worker_validation_not_accept')
        if int(worker_validation.get('input_row_count') or 0) <= 0:
            issues.append('safe_worker_validation_input_row_count_missing')
        if int(worker_validation.get('promotion_candidate_count') or 0) <= 0:
            issues.append('safe_worker_validation_promotion_candidate_missing')
    for key in ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if safety.get(key) is not False:
            issues.append(f'safe_worker_safety_{key}_must_be_false')
    return issues


def validate_payload(
    *,
    profile: dict[str, Any],
    validation: dict[str, Any],
    approval: dict[str, Any],
    safe_worker_bundle: dict[str, Any] | None,
    safe_worker_validation: dict[str, Any] | None,
    operator_id: str,
    default_backend: str,
) -> dict[str, Any]:
    field_issues = _validate_approval_fields(approval, operator_id=operator_id)
    safe_worker_issues = _validate_safe_worker_bundle(
        safe_worker_bundle,
        safe_worker_validation=safe_worker_validation,
        approval_evidence_scope=approval.get('evidence_scope'),
    )
    decision = decide_operator_backend(
        profile=profile,
        validation=validation,
        production_approval=approval if not field_issues and not safe_worker_issues else None,
        operator_id=operator_id,
        default_backend=default_backend,
    )
    issues = list(field_issues)
    issues.extend(safe_worker_issues)
    if not decision.get('replacement_allowed'):
        issues.append(str(decision.get('reason') or 'replacement_not_allowed'))
    return {
        'verdict': 'ACCEPT' if not issues and decision.get('replacement_allowed') is True else 'BLOCK',
        'operator_id': operator_id,
        'default_backend': default_backend,
        'approved_backend': approval.get('approved_backend'),
        'issues': issues,
        'decision': decision,
        'profile_verdict': profile.get('verdict'),
        'validation_verdict': validation.get('verdict'),
        'approval_verdict': approval.get('verdict'),
        'approval_evidence_scope': approval.get('evidence_scope'),
        'safe_worker_bundle_verdict': safe_worker_bundle.get('verdict') if safe_worker_bundle else None,
        'safe_worker_validation_verdict': safe_worker_validation.get('verdict') if safe_worker_validation else None,
        'safe_worker_validation_evidence_scope': safe_worker_validation.get('evidence_scope') if safe_worker_validation else None,
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile_path = Path(args.profile_path)
    validation_path = Path(args.validation_path)
    approval_path = Path(args.approval_path)
    safe_worker_bundle_path = Path(args.safe_worker_bundle_path) if args.safe_worker_bundle_path else None
    safe_worker_bundle = _load_json(safe_worker_bundle_path) if safe_worker_bundle_path and safe_worker_bundle_path.exists() else None
    safe_worker_validation_path = Path(args.safe_worker_validation_path) if args.safe_worker_validation_path else None
    safe_worker_validation = (
        _load_json(safe_worker_validation_path)
        if safe_worker_validation_path and safe_worker_validation_path.exists()
        else None
    )
    payload = validate_payload(
        profile=_load_json(profile_path),
        validation=_load_json(validation_path),
        approval=_load_json(approval_path),
        safe_worker_bundle=safe_worker_bundle,
        safe_worker_validation=safe_worker_validation,
        operator_id=str(args.operator_id),
        default_backend=str(args.default_backend),
    )
    payload['profile_path'] = str(profile_path)
    payload['validation_path'] = str(validation_path)
    payload['approval_path'] = str(approval_path)
    payload['safe_worker_bundle_path'] = str(safe_worker_bundle_path) if safe_worker_bundle_path else None
    payload['safe_worker_validation_path'] = str(safe_worker_validation_path) if safe_worker_validation_path else None
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
