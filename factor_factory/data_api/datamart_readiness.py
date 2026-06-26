from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATAMART_READINESS_SCHEMA_VERSION = 'datamart_readiness_report_v1'


def _resolve_path(raw: str, repo_root: Path) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path


def _read_verdict(path: Path) -> str | None:
    if not path.exists() or path.is_dir() or path.suffix.lower() != '.json':
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return 'UNREADABLE'
    if isinstance(payload, dict):
        verdict = payload.get('verdict') or payload.get('status') or payload.get('valid')
        if isinstance(verdict, bool):
            return 'ACCEPT' if verdict else 'BLOCK'
        if verdict is not None:
            return str(verdict)
    return None


def _path_status(raw: str, repo_root: Path) -> dict[str, Any]:
    path = _resolve_path(raw, repo_root)
    return {
        'path': str(path),
        'exists': path.exists(),
        'is_file': path.is_file(),
        'is_dir': path.is_dir(),
        'verdict': _read_verdict(path),
    }


def _next_action(entry: dict[str, Any], missing_required_paths: list[str], non_accept_proofs: list[str]) -> str:
    readiness = str(entry.get('production_readiness') or '')
    status = str(entry.get('status') or '')
    blockers = entry.get('registration_blockers') or []
    if status == 'planned' or readiness == 'not_started':
        if status == 'read_only_builder_available':
            return 'run bounded real-data proof before worker planning'
        return 'implement builder and bounded proof before worker planning'
    if missing_required_paths:
        return 'generate or restore missing proof artifacts'
    if non_accept_proofs:
        return 'repair proof artifacts that are not ACCEPT'
    if readiness == 'bounded_proof_accept':
        return 'decide whether full-window worker proof is justified'
    if readiness == 'worker_plan_accept':
        if status == 'exploratory':
            return 'run exploratory true-worker partition probe and cost decision before any full-window production plan'
        return 'run true-worker full-window build/read-smoke/closeout after explicit approval'
    if blockers:
        return 'close remaining registration blockers before active catalog'
    if readiness == 'production_ready':
        return 'eligible for active catalog review'
    return 'review registry status and dataset-specific blockers'


def build_datamart_readiness_report(
    feature_precompute: dict[str, Any],
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    repo = Path(repo_root).expanduser()
    datasets = [entry for entry in (feature_precompute.get('datasets') or []) if isinstance(entry, dict)]
    entries: list[dict[str, Any]] = []
    by_stage: dict[str, int] = {}
    for entry in datasets:
        proof_paths = entry.get('proof_paths') if isinstance(entry.get('proof_paths'), dict) else {}
        path_statuses = {str(key): _path_status(str(value), repo) for key, value in proof_paths.items()}
        builder = str(entry.get('builder_script') or '')
        validator = str(entry.get('validator_script') or '')
        required_path_statuses: dict[str, dict[str, Any]] = {}
        if builder:
            required_path_statuses['builder_script'] = _path_status(builder, repo)
        if validator:
            required_path_statuses['validator_script'] = _path_status(validator, repo)
        for key, status_payload in path_statuses.items():
            required_path_statuses[f'proof_paths.{key}'] = status_payload

        missing_required_paths = [
            key for key, status_payload in required_path_statuses.items() if status_payload.get('exists') is not True
        ]
        non_accept_proofs = [
            key
            for key, status_payload in path_statuses.items()
            if status_payload.get('verdict') not in {None, 'ACCEPT'}
        ]
        blockers = [str(item) for item in (entry.get('registration_blockers') or [])]
        readiness = str(entry.get('production_readiness') or '')
        status = str(entry.get('status') or '')
        if status == 'production_ready' and readiness == 'production_ready' and not blockers and not missing_required_paths and not non_accept_proofs:
            stage = 'production_ready_review'
        elif readiness == 'worker_plan_accept' and not missing_required_paths and not non_accept_proofs:
            stage = 'worker_plan_ready'
        elif readiness == 'bounded_proof_accept' and not missing_required_paths and not non_accept_proofs:
            stage = 'bounded_proof_ready'
        elif status == 'read_only_builder_available' and not missing_required_paths and not non_accept_proofs:
            stage = 'builder_available'
        elif status == 'planned' or readiness == 'not_started':
            stage = 'not_started'
        else:
            stage = 'blocked_or_incomplete'
        by_stage[stage] = by_stage.get(stage, 0) + 1
        entries.append({
            'dataset_id': entry.get('dataset_id'),
            'priority': entry.get('priority'),
            'status': status,
            'production_readiness': readiness,
            'feature_family': entry.get('feature_family'),
            'stage': stage,
            'recommended_first_production': entry.get('recommended_first_production') is True,
            'missing_required_paths': missing_required_paths,
            'non_accept_proofs': non_accept_proofs,
            'registration_blockers': blockers,
            'next_action': _next_action(entry, missing_required_paths, non_accept_proofs),
            'path_statuses': required_path_statuses,
        })
    return {
        'schema_version': DATAMART_READINESS_SCHEMA_VERSION,
        'verdict': 'ACCEPT',
        'dataset_count': len(entries),
        'by_stage': by_stage,
        'datasets': sorted(entries, key=lambda item: (str(item.get('priority')), str(item.get('dataset_id')))),
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    }
