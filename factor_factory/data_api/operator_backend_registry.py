from __future__ import annotations

from typing import Any


PRODUCTION_EVIDENCE_SCOPES = {'production_scale', 'full_is'}


def _decision(
    *,
    operator_id: str,
    default_backend: str,
    configured_backend: str | None,
    selected_backend: str,
    replacement_allowed: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        'operator_id': operator_id,
        'default_backend': default_backend,
        'configured_backend': configured_backend,
        'selected_backend': selected_backend,
        'replacement_allowed': bool(replacement_allowed),
        'reason': reason,
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def _approval_evidence_scope_valid(approval_validation: dict[str, Any]) -> bool:
    approval_scope = str(approval_validation.get('approval_evidence_scope') or '')
    safe_scope = str(approval_validation.get('safe_worker_validation_evidence_scope') or '')
    return approval_scope in PRODUCTION_EVIDENCE_SCOPES and approval_scope == safe_scope


def resolve_operator_backend(
    *,
    operator_id: str,
    default_backend: str,
    configured_backend: str | None,
    approval_validation: dict[str, Any] | None,
) -> dict[str, Any]:
    if not configured_backend or configured_backend == default_backend:
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            configured_backend=configured_backend,
            selected_backend=default_backend,
            replacement_allowed=False,
            reason='default_backend_selected',
        )
    if not approval_validation:
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            configured_backend=configured_backend,
            selected_backend=default_backend,
            replacement_allowed=False,
            reason='approval_validation_required',
        )
    decision = approval_validation.get('decision') or {}
    if approval_validation.get('verdict') != 'ACCEPT':
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            configured_backend=configured_backend,
            selected_backend=default_backend,
            replacement_allowed=False,
            reason='approval_validation_not_accept',
        )
    if not _approval_evidence_scope_valid(approval_validation):
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            configured_backend=configured_backend,
            selected_backend=default_backend,
            replacement_allowed=False,
            reason='approval_validation_evidence_scope_invalid',
        )
    if decision.get('operator_id') != operator_id and approval_validation.get('operator_id') != operator_id:
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            configured_backend=configured_backend,
            selected_backend=default_backend,
            replacement_allowed=False,
            reason='approval_validation_operator_mismatch',
        )
    selected_backend = str(decision.get('selected_backend') or '')
    if decision.get('replacement_allowed') is not True or selected_backend != configured_backend:
        return _decision(
            operator_id=operator_id,
            default_backend=default_backend,
            configured_backend=configured_backend,
            selected_backend=default_backend,
            replacement_allowed=False,
            reason='approval_validation_backend_mismatch',
        )
    return _decision(
        operator_id=operator_id,
        default_backend=default_backend,
        configured_backend=configured_backend,
        selected_backend=configured_backend,
        replacement_allowed=True,
        reason='approval_validation_accept',
    )
