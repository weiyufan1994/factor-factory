from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUEST_SCHEMA_VERSION = 'data_request_v1'
RESOLUTION_SCHEMA_VERSION = 'data_request_resolution_v1'
CLAIM_SCHEMA_VERSION = 'data_request_claim_v1'

REQUEST_REQUIRED_FIELDS = (
    'schema_version',
    'request_id',
    'created_at_utc',
    'created_by',
    'report_id',
    'priority',
    'requested_dataset_id',
    'request_type',
    'research_need',
    'window',
    'information_set',
    'unique_key',
    'required_fields',
    'qa_requirements',
    'execution_preference',
    'boundaries',
)

RESOLUTION_REQUIRED_FIELDS = (
    'schema_version',
    'request_id',
    'resolved_at_utc',
    'resolved_by',
    'verdict',
    'dataset_id',
    'catalog_path',
    'datamart_path',
    'qa_json_path',
    'worker_read_smoke',
    'coverage',
    'runtime',
)

VALID_PRIORITIES = {'P0', 'P1', 'P2'}
VALID_REQUEST_TYPES = {
    'new_datamart',
    'coverage_repair',
    'schema_addition',
    'performance_acceleration',
    'read_smoke',
}
VALID_VERDICTS = {'ACCEPT', 'BLOCK'}


class DataRequestError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {'field': self.field, 'message': self.message}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise DataRequestError(f'invalid json: {source}: {exc}') from exc
    if not isinstance(payload, dict):
        raise DataRequestError(f'json root must be object: {source}')
    return payload


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return target


def _validate_required(payload: dict[str, Any], required: tuple[str, ...]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field in required:
        if field not in payload:
            issues.append(ValidationIssue(field, 'missing required field'))
    return issues


def _validate_string_list(payload: dict[str, Any], field: str, *, allow_empty: bool = False) -> list[ValidationIssue]:
    value = payload.get(field)
    if not isinstance(value, list):
        return [ValidationIssue(field, 'must be a list')]
    if not allow_empty and not value:
        return [ValidationIssue(field, 'must not be empty')]
    bad = [item for item in value if not isinstance(item, str) or not item]
    if bad:
        return [ValidationIssue(field, 'all items must be non-empty strings')]
    return []


def validate_request(payload: dict[str, Any]) -> list[ValidationIssue]:
    issues = _validate_required(payload, REQUEST_REQUIRED_FIELDS)
    if payload.get('schema_version') != REQUEST_SCHEMA_VERSION:
        issues.append(ValidationIssue('schema_version', f'must equal {REQUEST_SCHEMA_VERSION}'))
    if payload.get('priority') not in VALID_PRIORITIES:
        issues.append(ValidationIssue('priority', f'must be one of {sorted(VALID_PRIORITIES)}'))
    if payload.get('request_type') not in VALID_REQUEST_TYPES:
        issues.append(ValidationIssue('request_type', f'must be one of {sorted(VALID_REQUEST_TYPES)}'))
    for field in ('request_id', 'created_by', 'report_id', 'requested_dataset_id'):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            issues.append(ValidationIssue(field, 'must be a non-empty string'))
    for field in ('research_need', 'window', 'information_set', 'execution_preference', 'boundaries'):
        if not isinstance(payload.get(field), dict):
            issues.append(ValidationIssue(field, 'must be an object'))
    issues.extend(_validate_string_list(payload, 'unique_key'))
    issues.extend(_validate_string_list(payload, 'required_fields'))
    issues.extend(_validate_string_list(payload, 'qa_requirements'))

    info = payload.get('information_set')
    if isinstance(info, dict):
        if info.get('no_future_data') is not True:
            issues.append(ValidationIssue('information_set.no_future_data', 'must be true'))
        cutoff_times = info.get('cutoff_times')
        if cutoff_times is not None:
            if not isinstance(cutoff_times, list) or not all(isinstance(item, str) and item for item in cutoff_times):
                issues.append(ValidationIssue('information_set.cutoff_times', 'must be a list of strings'))

    boundaries = payload.get('boundaries')
    if isinstance(boundaries, dict):
        for field in (
            'do_not_start_clean_data',
            'do_not_start_search_worker',
            'do_not_start_official_promotion',
            'do_not_write_factor_forge_research_artifacts',
            'do_not_start_factor_loop',
        ):
            if boundaries.get(field) is not True:
                issues.append(ValidationIssue(f'boundaries.{field}', 'must be true'))
    return issues


def validate_resolution(payload: dict[str, Any]) -> list[ValidationIssue]:
    issues = _validate_required(payload, RESOLUTION_REQUIRED_FIELDS)
    verdict = payload.get('verdict')
    if payload.get('schema_version') != RESOLUTION_SCHEMA_VERSION:
        issues.append(ValidationIssue('schema_version', f'must equal {RESOLUTION_SCHEMA_VERSION}'))
    if verdict not in VALID_VERDICTS:
        issues.append(ValidationIssue('verdict', f'must be one of {sorted(VALID_VERDICTS)}'))
    for field in ('request_id', 'resolved_by', 'dataset_id'):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            issues.append(ValidationIssue(field, 'must be a non-empty string'))
    for field in ('worker_read_smoke', 'coverage', 'runtime'):
        if not isinstance(payload.get(field), dict):
            issues.append(ValidationIssue(field, 'must be an object'))

    coverage = payload.get('coverage')
    if isinstance(coverage, dict):
        if coverage.get('duplicate_key_count') not in (0, '0'):
            issues.append(ValidationIssue('coverage.duplicate_key_count', 'must be 0 for ACCEPT-ready data'))
        missing_dates = coverage.get('missing_dates')
        if missing_dates is not None and not isinstance(missing_dates, list):
            issues.append(ValidationIssue('coverage.missing_dates', 'must be a list'))

    runtime = payload.get('runtime')
    if isinstance(runtime, dict) and 'estimated_total_cost_usd' not in runtime:
        issues.append(ValidationIssue('runtime.estimated_total_cost_usd', 'must be present'))
    if verdict == 'ACCEPT':
        for field in ('catalog_path', 'datamart_path', 'qa_json_path'):
            if not isinstance(payload.get(field), str) or not payload.get(field):
                issues.append(ValidationIssue(field, 'must be non-empty for ACCEPT'))
        smoke = payload.get('worker_read_smoke')
        if isinstance(smoke, dict) and smoke.get('verdict') != 'ACCEPT':
            issues.append(ValidationIssue('worker_read_smoke.verdict', 'must be ACCEPT for ACCEPT resolution'))
        if isinstance(coverage, dict):
            for field in ('rows', 'dates'):
                try:
                    if int(coverage.get(field, 0)) <= 0:
                        issues.append(ValidationIssue(f'coverage.{field}', 'must be positive for ACCEPT'))
                except (TypeError, ValueError):
                    issues.append(ValidationIssue(f'coverage.{field}', 'must be numeric for ACCEPT'))
    return issues


def assert_valid_request(payload: dict[str, Any]) -> None:
    issues = validate_request(payload)
    if issues:
        detail = '; '.join(f'{issue.field}: {issue.message}' for issue in issues)
        raise DataRequestError(detail)


def assert_valid_resolution(payload: dict[str, Any]) -> None:
    issues = validate_resolution(payload)
    if issues:
        detail = '; '.join(f'{issue.field}: {issue.message}' for issue in issues)
        raise DataRequestError(detail)


def request_filename(payload: dict[str, Any]) -> str:
    request_id = str(payload.get('request_id') or '').strip()
    if not request_id:
        raise DataRequestError('request_id is required for filename')
    safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in request_id)
    return f'data_request__{safe}.json'


def resolution_filename(payload: dict[str, Any]) -> str:
    request_id = str(payload.get('request_id') or '').strip()
    if not request_id:
        raise DataRequestError('request_id is required for filename')
    safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in request_id)
    return f'data_request_resolution__{safe}.json'


def claim_filename(payload: dict[str, Any]) -> str:
    request_id = str(payload.get('request_id') or '').strip()
    if not request_id:
        raise DataRequestError('request_id is required for filename')
    safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in request_id)
    return f'data_request_claim__{safe}.json'


def build_request_skeleton(
    *,
    report_id: str,
    dataset_id: str,
    request_type: str,
    priority: str = 'P1',
    created_by: str = 'factorforge-researcher',
    economic_purpose: str = '',
    formula_or_state: str = '',
    upstream_datasets: list[str] | None = None,
    is_start: str = '20160104',
    is_end: str = '20250711',
    oos_start: str = '20250714',
    cutoff_times: list[str] | None = None,
    unique_key: list[str] | None = None,
    required_fields: list[str] | None = None,
    qa_requirements: list[str] | None = None,
    preferred_executor: str = 'research_worker',
    batch_spot_allowed: bool = True,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    request = {
        'schema_version': REQUEST_SCHEMA_VERSION,
        'request_id': f'{report_id}__{dataset_id}__{timestamp}',
        'created_at_utc': utc_now_iso(),
        'created_by': created_by,
        'report_id': report_id,
        'priority': priority,
        'requested_dataset_id': dataset_id,
        'request_type': request_type,
        'research_need': {
            'economic_purpose': economic_purpose,
            'formula_or_state': formula_or_state,
            'upstream_datasets': upstream_datasets or [],
        },
        'window': {
            'is_start': is_start,
            'is_end': is_end,
            'oos_start': oos_start,
            'research_window_rule': 'OOS marked holdout; do not fit parameters on OOS',
        },
        'information_set': {
            'cutoff_times': cutoff_times or [],
            'no_future_data': True,
            'state_continuity_required': True,
        },
        'unique_key': unique_key or ['ts_code', 'trade_date'],
        'required_fields': required_fields or ['ts_code', 'trade_date'],
        'qa_requirements': qa_requirements or [
            'duplicate_key_count=0',
            'missing_dates=[]',
            'coverage_summary',
            'representative_read_smoke',
        ],
        'execution_preference': {
            'preferred_executor': preferred_executor,
            'batch_spot_allowed': bool(batch_spot_allowed),
            'requires_cost_estimate_before_full_run': True,
        },
        'boundaries': {
            'do_not_start_clean_data': True,
            'do_not_start_search_worker': True,
            'do_not_start_official_promotion': True,
            'do_not_write_factor_forge_research_artifacts': True,
            'do_not_start_factor_loop': True,
        },
    }
    assert_valid_request(request)
    return request


def mirror_request(source: str | Path, inbox_dir: str | Path) -> Path:
    payload = read_json(source)
    assert_valid_request(payload)
    target = Path(inbox_dir).expanduser() / request_filename(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(source).expanduser(), target)
    return target


def list_requests(inbox_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(inbox_dir).expanduser()
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob('*.json')):
        try:
            payload = read_json(path)
            issues = validate_request(payload)
            items.append({
                'path': str(path),
                'request_id': payload.get('request_id'),
                'report_id': payload.get('report_id'),
                'dataset_id': payload.get('requested_dataset_id'),
                'priority': payload.get('priority'),
                'request_type': payload.get('request_type'),
                'valid': not issues,
                'issues': [issue.to_dict() for issue in issues],
            })
        except DataRequestError as exc:
            items.append({'path': str(path), 'valid': False, 'issues': [{'field': 'json', 'message': str(exc)}]})
    return items


def build_claim(request: dict[str, Any], *, claimed_by: str = 'data-api', note: str = '') -> dict[str, Any]:
    assert_valid_request(request)
    return {
        'schema_version': CLAIM_SCHEMA_VERSION,
        'request_id': request['request_id'],
        'claimed_at_utc': utc_now_iso(),
        'claimed_by': claimed_by,
        'status': 'IN_PROGRESS',
        'dataset_id': request['requested_dataset_id'],
        'report_id': request['report_id'],
        'priority': request['priority'],
        'request_type': request['request_type'],
        'note': note,
    }


def claim_request(
    request_id: str,
    inbox_dir: str | Path,
    claimed_dir: str | Path,
    *,
    claimed_by: str = 'data-api',
    note: str = '',
) -> Path:
    inbox_root = Path(inbox_dir).expanduser()
    if not inbox_root.exists():
        raise DataRequestError(f'inbox does not exist: {inbox_root}')
    for path in sorted(inbox_root.glob('*.json'), reverse=True):
        payload = read_json(path)
        if payload.get('request_id') != request_id:
            continue
        claim = build_claim(payload, claimed_by=claimed_by, note=note)
        target = Path(claimed_dir).expanduser() / claim_filename(claim)
        write_json(target, claim)
        return target
    raise DataRequestError(f'request not found in inbox: {request_id}')


def find_request_status(
    request_id: str,
    inbox_dir: str | Path,
    resolved_dir: str | Path,
    claimed_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not request_id:
        raise DataRequestError('request_id is required')

    resolved_root = Path(resolved_dir).expanduser()
    if resolved_root.exists():
        for path in sorted(resolved_root.glob('*.json'), reverse=True):
            try:
                payload = read_json(path)
            except DataRequestError as exc:
                return {
                    'request_id': request_id,
                    'status': 'INVALID',
                    'resolution_path': str(path),
                    'issues': [{'field': 'json', 'message': str(exc)}],
                }
            if payload.get('request_id') != request_id:
                continue
            issues = validate_resolution(payload)
            if issues:
                return {
                    'request_id': request_id,
                    'status': 'INVALID',
                    'resolution_path': str(path),
                    'verdict': payload.get('verdict'),
                    'issues': [issue.to_dict() for issue in issues],
                }
            return {
                'request_id': request_id,
                'status': payload['verdict'],
                'resolution_path': str(path),
                'dataset_id': payload.get('dataset_id'),
                'catalog_path': payload.get('catalog_path'),
                'datamart_path': payload.get('datamart_path'),
                'qa_json_path': payload.get('qa_json_path'),
                'worker_read_smoke': payload.get('worker_read_smoke'),
                'coverage': payload.get('coverage'),
                'runtime': payload.get('runtime'),
            }

    claimed_root = Path(claimed_dir).expanduser() if claimed_dir is not None else Path(inbox_dir).expanduser().parent / 'claimed'
    if claimed_root.exists():
        for path in sorted(claimed_root.glob('*.json'), reverse=True):
            try:
                payload = read_json(path)
            except DataRequestError as exc:
                return {
                    'request_id': request_id,
                    'status': 'INVALID',
                    'claim_path': str(path),
                    'issues': [{'field': 'json', 'message': str(exc)}],
                }
            if payload.get('request_id') != request_id:
                continue
            if payload.get('schema_version') != CLAIM_SCHEMA_VERSION:
                return {
                    'request_id': request_id,
                    'status': 'INVALID',
                    'claim_path': str(path),
                    'issues': [{'field': 'schema_version', 'message': f'must equal {CLAIM_SCHEMA_VERSION}'}],
                }
            return {
                'request_id': request_id,
                'status': 'IN_PROGRESS',
                'claim_path': str(path),
                'claimed_at_utc': payload.get('claimed_at_utc'),
                'claimed_by': payload.get('claimed_by'),
                'dataset_id': payload.get('dataset_id'),
                'report_id': payload.get('report_id'),
                'priority': payload.get('priority'),
                'request_type': payload.get('request_type'),
                'note': payload.get('note'),
            }

    inbox_root = Path(inbox_dir).expanduser()
    if inbox_root.exists():
        for path in sorted(inbox_root.glob('*.json'), reverse=True):
            try:
                payload = read_json(path)
            except DataRequestError:
                continue
            if payload.get('request_id') != request_id:
                continue
            issues = validate_request(payload)
            return {
                'request_id': request_id,
                'status': 'PENDING' if not issues else 'INVALID',
                'request_path': str(path),
                'report_id': payload.get('report_id'),
                'dataset_id': payload.get('requested_dataset_id'),
                'priority': payload.get('priority'),
                'request_type': payload.get('request_type'),
                'issues': [issue.to_dict() for issue in issues],
            }

    return {
        'request_id': request_id,
        'status': 'NOT_FOUND',
        'inbox_dir': str(Path(inbox_dir).expanduser()),
        'resolved_dir': str(Path(resolved_dir).expanduser()),
    }


def build_resolution_skeleton(request: dict[str, Any], *, verdict: str = 'BLOCK') -> dict[str, Any]:
    if verdict not in VALID_VERDICTS:
        raise DataRequestError(f'invalid verdict: {verdict}')
    assert_valid_request(request)
    return {
        'schema_version': RESOLUTION_SCHEMA_VERSION,
        'request_id': request['request_id'],
        'resolved_at_utc': utc_now_iso(),
        'resolved_by': 'data-api',
        'verdict': verdict,
        'dataset_id': request['requested_dataset_id'],
        'catalog_path': '',
        'datamart_path': '',
        'qa_json_path': '',
        'worker_read_smoke': {
            'instance_id': '',
            'command': '',
            'warm_read_seconds': 0.0,
            'verdict': 'BLOCK',
        },
        'coverage': {
            'start_date': request.get('window', {}).get('is_start', ''),
            'end_date': request.get('window', {}).get('is_end', ''),
            'rows': 0,
            'dates': 0,
            'tickers': 0,
            'missing_dates': [],
            'duplicate_key_count': 0,
        },
        'runtime': {
            'executor': request.get('execution_preference', {}).get('preferred_executor', ''),
            'read_seconds': 0.0,
            'compute_seconds': 0.0,
            'write_seconds': 0.0,
            'qa_seconds': 0.0,
            'total_seconds': 0.0,
            'estimated_total_cost_usd': 0.0,
        },
        'notes': [],
    }
