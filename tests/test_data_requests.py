from __future__ import annotations

import json
from pathlib import Path

from factor_factory.data_api.data_requests import (
    build_request_skeleton,
    build_resolution_skeleton,
    claim_request,
    find_request_status,
    list_requests,
    mirror_request,
    read_json,
    validate_request,
    validate_resolution,
)


def valid_request() -> dict:
    return {
        'schema_version': 'data_request_v1',
        'request_id': 'ORIG_REPORT__moneyflow_v20_slow_state_v1__20260615143000',
        'created_at_utc': '2026-06-15T06:30:00Z',
        'created_by': 'factorforge-researcher',
        'report_id': 'ORIG_REPORT',
        'priority': 'P0',
        'requested_dataset_id': 'moneyflow_v20_slow_state_v1',
        'request_type': 'new_datamart',
        'research_need': {
            'economic_purpose': 'slow moneyflow state',
            'formula_or_state': 'H_t = lambda H_{t-1} + (1-lambda) S_t',
            'upstream_datasets': ['intraday_flow_distribution_moments_v1', 'daily_basic_backtest_base'],
        },
        'window': {
            'is_start': '20160104',
            'is_end': '20250711',
            'oos_start': '20250714',
            'research_window_rule': 'OOS marked holdout',
        },
        'information_set': {
            'cutoff_times': ['14:50'],
            'no_future_data': True,
            'state_continuity_required': True,
        },
        'unique_key': ['ts_code', 'trade_date', 'cutoff_time', 'lambda'],
        'required_fields': ['ts_code', 'trade_date', 'cutoff_time', 'lambda', 'h_slow_state'],
        'qa_requirements': ['duplicate_key_count=0', 'missing_dates=[]', 'state_continuity_proof'],
        'execution_preference': {
            'preferred_executor': 'research_worker',
            'batch_spot_allowed': True,
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


def write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def test_valid_moneyflow_v20_request_has_no_issues():
    assert validate_request(valid_request()) == []


def test_build_request_skeleton_generates_valid_request():
    request = build_request_skeleton(
        report_id='ORIG_REPORT',
        dataset_id='moneyflow_v20_slow_state_v1',
        request_type='new_datamart',
        priority='P0',
        formula_or_state='H_t = lambda H_{t-1} + (1-lambda) S_t',
        upstream_datasets=['intraday_flow_distribution_moments_v1'],
        cutoff_times=['14:50'],
        unique_key=['ts_code', 'trade_date', 'cutoff_time', 'lambda'],
        required_fields=['ts_code', 'trade_date', 'h_slow_state'],
    )

    assert request['schema_version'] == 'data_request_v1'
    assert request['request_id'].startswith('ORIG_REPORT__moneyflow_v20_slow_state_v1__')
    assert validate_request(request) == []


def test_request_requires_no_future_and_boundaries():
    request = valid_request()
    request['information_set']['no_future_data'] = False
    request['boundaries']['do_not_start_factor_loop'] = False
    issues = validate_request(request)
    fields = {issue.field for issue in issues}
    assert 'information_set.no_future_data' in fields
    assert 'boundaries.do_not_start_factor_loop' in fields


def test_mirror_and_list_request(tmp_path):
    source = tmp_path / 'source' / 'request.json'
    inbox = tmp_path / 'inbox'
    write_payload(source, valid_request())

    target = mirror_request(source, inbox)

    assert target.exists()
    assert read_json(target)['request_id'] == valid_request()['request_id']
    listed = list_requests(inbox)
    assert len(listed) == 1
    assert listed[0]['valid'] is True
    assert listed[0]['dataset_id'] == 'moneyflow_v20_slow_state_v1'
    status = find_request_status(valid_request()['request_id'], inbox, tmp_path / 'resolved')
    assert status['status'] == 'PENDING'
    assert status['dataset_id'] == 'moneyflow_v20_slow_state_v1'


def test_claim_request_sets_in_progress_status(tmp_path):
    source = tmp_path / 'source' / 'request.json'
    inbox = tmp_path / 'inbox'
    claimed = tmp_path / 'claimed'
    write_payload(source, valid_request())
    mirror_request(source, inbox)

    claim_path = claim_request(valid_request()['request_id'], inbox, claimed, claimed_by='data-api', note='starting bounded proof')
    status = find_request_status(valid_request()['request_id'], inbox, tmp_path / 'resolved', claimed)

    assert claim_path.exists()
    assert status['status'] == 'IN_PROGRESS'
    assert status['claimed_by'] == 'data-api'
    assert status['note'] == 'starting bounded proof'


def test_resolution_skeleton_is_valid_block_resolution():
    resolution = build_resolution_skeleton(valid_request(), verdict='BLOCK')
    assert resolution['schema_version'] == 'data_request_resolution_v1'
    assert resolution['request_id'] == valid_request()['request_id']
    assert resolution['dataset_id'] == 'moneyflow_v20_slow_state_v1'
    assert resolution['coverage']['duplicate_key_count'] == 0
    assert validate_resolution(resolution) == []


def test_accept_resolution_requires_real_proofs():
    resolution = build_resolution_skeleton(valid_request(), verdict='ACCEPT')
    issues = validate_resolution(resolution)
    fields = {issue.field for issue in issues}
    assert 'catalog_path' in fields
    assert 'datamart_path' in fields
    assert 'qa_json_path' in fields
    assert 'worker_read_smoke.verdict' in fields
    assert 'coverage.rows' in fields


def test_status_prefers_resolution_over_pending_request(tmp_path):
    request = valid_request()
    inbox = tmp_path / 'inbox'
    claimed = tmp_path / 'claimed'
    resolved = tmp_path / 'resolved'
    write_payload(inbox / 'request.json', request)
    claim_request(request['request_id'], inbox, claimed)
    resolution = build_resolution_skeleton(request, verdict='BLOCK')
    write_payload(resolved / 'resolution.json', resolution)

    status = find_request_status(request['request_id'], inbox, resolved, claimed)

    assert status['status'] == 'BLOCK'
    assert status['dataset_id'] == 'moneyflow_v20_slow_state_v1'
    assert status['resolution_path'].endswith('resolution.json')


def test_status_not_found(tmp_path):
    status = find_request_status('missing', tmp_path / 'inbox', tmp_path / 'resolved')
    assert status['status'] == 'NOT_FOUND'
