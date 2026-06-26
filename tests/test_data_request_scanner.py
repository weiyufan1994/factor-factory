from __future__ import annotations

import json
from pathlib import Path

from factor_factory.data_api.data_requests import build_resolution_skeleton
from factor_factory.data_api.request_scanner import scan_request_inbox
from tests.test_data_requests import valid_request


def write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def test_scanner_claims_valid_pending_request(tmp_path):
    inbox = tmp_path / 'inbox'
    claimed = tmp_path / 'claimed'
    resolved = tmp_path / 'resolved'
    request = valid_request()
    write_payload(inbox / 'request.json', request)

    summary = scan_request_inbox(inbox, claimed, resolved, claimed_by='scanner-test')

    assert summary['claimed_count'] == 1
    assert summary['skipped_count'] == 0
    assert summary['claimed'][0]['request_id'] == request['request_id']
    claim_files = list(claimed.glob('*.json'))
    assert len(claim_files) == 1
    claim = json.loads(claim_files[0].read_text(encoding='utf-8'))
    assert claim['status'] == 'IN_PROGRESS'
    assert claim['claimed_by'] == 'scanner-test'


def test_scanner_skips_claimed_resolved_and_invalid_requests(tmp_path):
    inbox = tmp_path / 'inbox'
    claimed = tmp_path / 'claimed'
    resolved = tmp_path / 'resolved'
    pending = valid_request()
    already_claimed = {**valid_request(), 'request_id': 'already_claimed'}
    already_resolved = {**valid_request(), 'request_id': 'already_resolved'}
    invalid = {**valid_request(), 'request_id': 'invalid'}
    invalid['information_set']['no_future_data'] = False
    write_payload(inbox / 'pending.json', pending)
    write_payload(inbox / 'already_claimed.json', already_claimed)
    write_payload(inbox / 'already_resolved.json', already_resolved)
    write_payload(inbox / 'invalid.json', invalid)
    write_payload(claimed / 'claim.json', {
        'schema_version': 'data_request_claim_v1',
        'request_id': 'already_claimed',
        'claimed_at_utc': '2026-06-15T00:00:00Z',
        'claimed_by': 'data-api',
        'status': 'IN_PROGRESS',
        'dataset_id': 'x',
        'report_id': 'x',
        'priority': 'P0',
        'request_type': 'new_datamart',
        'note': '',
    })
    write_payload(resolved / 'resolution.json', build_resolution_skeleton(already_resolved, verdict='BLOCK'))

    summary = scan_request_inbox(inbox, claimed, resolved, claimed_by='scanner-test')

    assert summary['claimed_count'] == 1
    assert summary['claimed'][0]['request_id'] == pending['request_id']
    skipped = {item['request_id']: item['reason'] for item in summary['skipped']}
    assert skipped['already_claimed'] == 'already_in_progress'
    assert skipped['already_resolved'] == 'already_resolved'
    assert skipped['invalid'] == 'invalid_request'
