from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FEATURE_PRECOMPUTE_REGISTRY_SCHEMA_VERSION = 'feature_precompute_registry_v1'

ALLOWED_FREQUENCIES = {'daily', '1min', 'intraday_cutoff', 'event_bar'}
ALLOWED_PRIORITIES = {'P0', 'P1', 'P2', 'P3'}
ALLOWED_STATUSES = {
    'planned',
    'exploratory',
    'read_only_builder_available',
    'production_candidate',
    'production_ready',
    'blocked',
}
ALLOWED_PRODUCTION_READINESS = {
    'not_started',
    'bounded_proof_accept',
    'worker_plan_accept',
    'worker_full_window_required',
    'worker_full_window_accept',
    'production_ready',
    'blocked',
}


@dataclass(frozen=True)
class FeatureRegistryIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {'field': self.field, 'message': self.message}


def read_feature_registry(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'feature registry root must be an object: {source}')
    return payload


def _require_string(entry: dict[str, Any], field: str, issues: list[FeatureRegistryIssue], prefix: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        issues.append(FeatureRegistryIssue(f'{prefix}.{field}', 'must be a non-empty string'))
        return ''
    return value


def _require_bool(entry: dict[str, Any], field: str, issues: list[FeatureRegistryIssue], prefix: str) -> bool | None:
    value = entry.get(field)
    if not isinstance(value, bool):
        issues.append(FeatureRegistryIssue(f'{prefix}.{field}', 'must be a boolean'))
        return None
    return value


def _require_string_list(
    entry: dict[str, Any],
    field: str,
    issues: list[FeatureRegistryIssue],
    prefix: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    value = entry.get(field)
    if not isinstance(value, list):
        issues.append(FeatureRegistryIssue(f'{prefix}.{field}', 'must be a list'))
        return []
    if not allow_empty and not value:
        issues.append(FeatureRegistryIssue(f'{prefix}.{field}', 'must not be empty'))
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(FeatureRegistryIssue(f'{prefix}.{field}[{index}]', 'must be a non-empty string'))
        else:
            result.append(item)
    return result


def _path_exists(repo_root: Path, raw: str) -> bool:
    if not raw:
        return False
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.exists()


def _validate_entry(entry: Any, index: int, seen: set[str], repo_root: Path) -> list[FeatureRegistryIssue]:
    prefix = f'datasets[{index}]'
    issues: list[FeatureRegistryIssue] = []
    if not isinstance(entry, dict):
        return [FeatureRegistryIssue(prefix, 'must be an object')]

    dataset_id = _require_string(entry, 'dataset_id', issues, prefix)
    if dataset_id:
        if dataset_id in seen:
            issues.append(FeatureRegistryIssue(f'{prefix}.dataset_id', 'must be unique'))
        seen.add(dataset_id)

    frequency = _require_string(entry, 'frequency', issues, prefix)
    if frequency and frequency not in ALLOWED_FREQUENCIES:
        issues.append(FeatureRegistryIssue(f'{prefix}.frequency', f'must be one of {sorted(ALLOWED_FREQUENCIES)}'))

    priority = _require_string(entry, 'priority', issues, prefix)
    if priority and priority not in ALLOWED_PRIORITIES:
        issues.append(FeatureRegistryIssue(f'{prefix}.priority', f'must be one of {sorted(ALLOWED_PRIORITIES)}'))

    status = _require_string(entry, 'status', issues, prefix)
    if status and status not in ALLOWED_STATUSES:
        issues.append(FeatureRegistryIssue(f'{prefix}.status', f'must be one of {sorted(ALLOWED_STATUSES)}'))

    readiness = _require_string(entry, 'production_readiness', issues, prefix)
    if readiness and readiness not in ALLOWED_PRODUCTION_READINESS:
        issues.append(
            FeatureRegistryIssue(
                f'{prefix}.production_readiness',
                f'must be one of {sorted(ALLOWED_PRODUCTION_READINESS)}',
            )
        )

    _require_string(entry, 'feature_family', issues, prefix)
    _require_string(entry, 'full_window_strategy', issues, prefix)
    _require_string(entry, 'information_set_legality', issues, prefix)
    _require_string(entry, 'notes', issues, prefix)
    _require_bool(entry, 'recommended_first_production', issues, prefix)
    _require_bool(entry, 'projection_required', issues, prefix)

    _require_string_list(entry, 'source_datasets', issues, prefix)
    _require_string_list(entry, 'unique_key', issues, prefix)
    _require_string_list(entry, 'partition_columns', issues, prefix, allow_empty=True)
    blockers = _require_string_list(entry, 'registration_blockers', issues, prefix, allow_empty=True)

    builder_script = entry.get('builder_script', '')
    validator_script = entry.get('validator_script', '')
    proof_paths = entry.get('proof_paths', {})

    if not isinstance(builder_script, str):
        issues.append(FeatureRegistryIssue(f'{prefix}.builder_script', 'must be a string'))
        builder_script = ''
    if not isinstance(validator_script, str):
        issues.append(FeatureRegistryIssue(f'{prefix}.validator_script', 'must be a string'))
        validator_script = ''
    if not isinstance(proof_paths, dict):
        issues.append(FeatureRegistryIssue(f'{prefix}.proof_paths', 'must be an object'))
        proof_paths = {}
    elif any(not isinstance(key, str) or not isinstance(value, str) for key, value in proof_paths.items()):
        issues.append(FeatureRegistryIssue(f'{prefix}.proof_paths', 'keys and values must be strings'))

    if status in {'read_only_builder_available', 'production_candidate', 'production_ready'}:
        if not builder_script:
            issues.append(FeatureRegistryIssue(f'{prefix}.builder_script', 'required for builder-backed status'))
        elif not _path_exists(repo_root, builder_script):
            issues.append(FeatureRegistryIssue(f'{prefix}.builder_script', 'path does not exist'))
        if not validator_script:
            issues.append(FeatureRegistryIssue(f'{prefix}.validator_script', 'required for builder-backed status'))
        elif not _path_exists(repo_root, validator_script):
            issues.append(FeatureRegistryIssue(f'{prefix}.validator_script', 'path does not exist'))

    if readiness in {'bounded_proof_accept', 'worker_plan_accept', 'worker_full_window_accept', 'production_ready'}:
        if not proof_paths:
            issues.append(FeatureRegistryIssue(f'{prefix}.proof_paths', 'required once proof has been accepted'))

    if status == 'production_ready' or readiness == 'production_ready':
        if readiness != 'production_ready' or status != 'production_ready':
            issues.append(FeatureRegistryIssue(prefix, 'production_ready requires both status and production_readiness'))
        required = {'qa', 'catalog', 'worker_read_smoke'}
        missing = sorted(required.difference(proof_paths))
        if missing:
            issues.append(FeatureRegistryIssue(f'{prefix}.proof_paths', f'missing production proof keys: {missing}'))
        if blockers:
            issues.append(FeatureRegistryIssue(f'{prefix}.registration_blockers', 'must be empty for production_ready'))

    if readiness == 'production_ready' and 'worker_full_window' not in proof_paths:
        issues.append(
            FeatureRegistryIssue(
                f'{prefix}.proof_paths.worker_full_window',
                'production_ready requires worker full-window proof',
            )
        )

    if entry.get('recommended_first_production') is True and status not in {'production_candidate', 'production_ready'}:
        issues.append(
            FeatureRegistryIssue(
                f'{prefix}.recommended_first_production',
                'recommended first production must be a production candidate or production ready',
            )
        )

    return issues


def validate_feature_precompute_registry(
    payload: dict[str, Any],
    *,
    repo_root: str | Path | None = None,
) -> list[FeatureRegistryIssue]:
    issues: list[FeatureRegistryIssue] = []
    if payload.get('schema_version') != FEATURE_PRECOMPUTE_REGISTRY_SCHEMA_VERSION:
        issues.append(
            FeatureRegistryIssue(
                'schema_version',
                f'must equal {FEATURE_PRECOMPUTE_REGISTRY_SCHEMA_VERSION}',
            )
        )

    repo = Path(repo_root).expanduser() if repo_root is not None else Path.cwd()
    datasets = payload.get('datasets')
    if not isinstance(datasets, list) or not datasets:
        issues.append(FeatureRegistryIssue('datasets', 'must be a non-empty list'))
        return issues

    seen: set[str] = set()
    for index, entry in enumerate(datasets):
        issues.extend(_validate_entry(entry, index, seen, repo))
    return issues


def registry_summary(payload: dict[str, Any]) -> dict[str, Any]:
    datasets = payload.get('datasets') if isinstance(payload.get('datasets'), list) else []
    entries = [entry for entry in datasets if isinstance(entry, dict)]
    by_status: dict[str, int] = {}
    by_readiness: dict[str, int] = {}
    for entry in entries:
        status = str(entry.get('status') or '')
        readiness = str(entry.get('production_readiness') or '')
        by_status[status] = by_status.get(status, 0) + 1
        by_readiness[readiness] = by_readiness.get(readiness, 0) + 1
    return {
        'schema_version': payload.get('schema_version'),
        'dataset_count': len(entries),
        'recommended_first_production': [
            entry.get('dataset_id') for entry in entries if entry.get('recommended_first_production') is True
        ],
        'by_status': by_status,
        'by_production_readiness': by_readiness,
    }
