from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .data_requests import (
    DataRequestError,
    claim_request,
    find_request_status,
    read_json,
    validate_request,
)


def scan_request_inbox(
    inbox_dir: str | Path,
    claimed_dir: str | Path,
    resolved_dir: str | Path,
    *,
    claimed_by: str = 'data-api-scanner',
    note: str = 'Data API scanner claimed request for triage.',
    limit: int | None = None,
) -> dict[str, Any]:
    inbox_root = Path(inbox_dir).expanduser()
    claimed_root = Path(claimed_dir).expanduser()
    resolved_root = Path(resolved_dir).expanduser()
    summary: dict[str, Any] = {
        'inbox_dir': str(inbox_root),
        'claimed_dir': str(claimed_root),
        'resolved_dir': str(resolved_root),
        'claimed_by': claimed_by,
        'claimed': [],
        'skipped': [],
    }
    if not inbox_root.exists():
        summary['claimed_count'] = 0
        summary['skipped_count'] = 0
        summary['status'] = 'NO_INBOX'
        return summary

    for path in sorted(inbox_root.glob('*.json')):
        if limit is not None and len(summary['claimed']) >= limit:
            break
        try:
            payload = read_json(path)
        except DataRequestError as exc:
            summary['skipped'].append({'path': str(path), 'request_id': None, 'reason': 'invalid_json', 'detail': str(exc)})
            continue
        request_id = payload.get('request_id')
        issues = validate_request(payload)
        if issues:
            summary['skipped'].append({
                'path': str(path),
                'request_id': request_id,
                'reason': 'invalid_request',
                'issues': [issue.to_dict() for issue in issues],
            })
            continue

        status = find_request_status(request_id, inbox_root, resolved_root, claimed_root)
        if status['status'] in {'ACCEPT', 'BLOCK'}:
            summary['skipped'].append({'path': str(path), 'request_id': request_id, 'reason': 'already_resolved'})
            continue
        if status['status'] == 'IN_PROGRESS':
            summary['skipped'].append({'path': str(path), 'request_id': request_id, 'reason': 'already_in_progress'})
            continue
        if status['status'] != 'PENDING':
            summary['skipped'].append({'path': str(path), 'request_id': request_id, 'reason': status['status']})
            continue

        claim_path = claim_request(request_id, inbox_root, claimed_root, claimed_by=claimed_by, note=note)
        summary['claimed'].append({
            'path': str(path),
            'request_id': request_id,
            'dataset_id': payload.get('requested_dataset_id'),
            'priority': payload.get('priority'),
            'claim_path': str(claim_path),
        })

    summary['claimed_count'] = len(summary['claimed'])
    summary['skipped_count'] = len(summary['skipped'])
    summary['status'] = 'OK'
    return summary


def watch_request_inbox(
    inbox_dir: str | Path,
    claimed_dir: str | Path,
    resolved_dir: str | Path,
    *,
    claimed_by: str = 'data-api-scanner',
    note: str = 'Data API scanner claimed request for triage.',
    interval_seconds: float = 30.0,
    max_iterations: int | None = None,
    limit_per_scan: int | None = None,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        summaries.append(
            scan_request_inbox(
                inbox_dir,
                claimed_dir,
                resolved_dir,
                claimed_by=claimed_by,
                note=note,
                limit=limit_per_scan,
            )
        )
        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            break
        time.sleep(interval_seconds)
    return summaries
