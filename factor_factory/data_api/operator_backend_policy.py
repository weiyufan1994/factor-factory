from __future__ import annotations

from typing import Any


PRODUCTION_EVIDENCE_SCOPES = {'production_scale', 'full_is'}


def _find_candidate(profile: dict[str, Any], operator_id: str) -> dict[str, Any] | None:
    gate = profile.get('performance_gate') or {}
    first_match: dict[str, Any] | None = None
    for candidate in gate.get('candidates') or []:
        if candidate.get('operator_id') == operator_id:
            if first_match is None:
                first_match = candidate
            if candidate.get('performance_verdict') == 'PROMOTE':
                return candidate
    return first_match


def _decision(
    *,
    operator_id: str,
    default_backend: str,
    selected_backend: str,
    candidate_backend: str | None,
    replacement_allowed: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        'operator_id': operator_id,
        'default_backend': default_backend,
        'selected_backend': selected_backend,
        'candidate_backend': candidate_backend,
        'replacement_allowed': bool(replacement_allowed),
        'reason': reason,
    }


def _production_approval_matches(
    *,
    production_approval: dict[str, Any] | None,
    operator_id: str,
    candidate_backend: str | None,
) -> bool:
    if not production_approval or not candidate_backend:
        return False
    if production_approval.get('verdict') != 'ACCEPT':
        return False
    if production_approval.get('production_default_allowed') is not True:
        return False
    if production_approval.get('approval_scope') != 'production_default_backend':
        return False
    if production_approval.get('operator_id') != operator_id:
        return False
    if production_approval.get('evidence_scope') not in PRODUCTION_EVIDENCE_SCOPES:
        return False
    return production_approval.get('approved_backend') == candidate_backend


def decide_operator_backend(
    *,
    profile: dict[str, Any],
    validation: dict[str, Any],
    operator_id: str,
    default_backend: str,
    production_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = _find_candidate(profile, operator_id)
    candidate_backend = candidate.get('candidate_backend') if candidate else None
    if validation.get('verdict') != 'ACCEPT':
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            selected_backend=default_backend,
            candidate_backend=candidate_backend,
            replacement_allowed=False,
            reason='validation_not_accept',
        )
    if profile.get('verdict') != 'ACCEPT':
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            selected_backend=default_backend,
            candidate_backend=candidate_backend,
            replacement_allowed=False,
            reason='profile_not_accept',
        )
    if not candidate or candidate.get('performance_verdict') != 'PROMOTE' or not candidate_backend:
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            selected_backend=default_backend,
            candidate_backend=candidate_backend,
            replacement_allowed=False,
            reason='no_promoted_candidate_for_operator',
        )
    if _production_approval_matches(
        production_approval=production_approval,
        operator_id=operator_id,
        candidate_backend=str(candidate_backend),
    ):
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            selected_backend=str(candidate_backend),
            candidate_backend=str(candidate_backend),
            replacement_allowed=True,
            reason='approved_candidate_promoted_by_production_approval',
        )
    if production_approval:
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            selected_backend=default_backend,
            candidate_backend=candidate_backend,
            replacement_allowed=False,
            reason='production_approval_not_valid_for_candidate',
        )
    return _decision(
        operator_id=operator_id,
        default_backend=default_backend,
        selected_backend=default_backend,
        candidate_backend=candidate_backend,
        replacement_allowed=False,
        reason='production_approval_required',
    )
