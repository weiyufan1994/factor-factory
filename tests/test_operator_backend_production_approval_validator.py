from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_operator_backend_production_approval.py'
    spec = importlib.util.spec_from_file_location('validate_operator_backend_production_approval', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile() -> dict:
    return {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': False,
            'candidates': [
                {
                    'operator_id': 'cpv_price_volume_corr_state',
                    'baseline_backend': 'array_grouped',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 2.1,
                }
            ],
        },
    }


def _validation() -> dict:
    return {
        'verdict': 'ACCEPT',
        'issue_count': 0,
        'issues': [],
    }


def _approval(backend: str = 'process_sharded_array_grouped') -> dict:
    return {
        'verdict': 'ACCEPT',
        'approval_scope': 'production_default_backend',
        'operator_id': 'cpv_price_volume_corr_state',
        'approved_backend': backend,
        'production_default_allowed': True,
        'approved_by': 'reviewer-test',
        'approval_reason': 'real worker bounded proof accepted',
        'evidence_scope': 'production_scale',
    }


def _safe_worker_bundle() -> dict:
    return {
        'verdict': 'ACCEPT',
        'preflight_summary': {'verdict': 'ACCEPT', 'issues': []},
        'worker_benchmark_summary': {'verdict': 'ACCEPT'},
        'worker_validation_summary': {
            'verdict': 'ACCEPT',
            'issues': [],
            'input_row_count': 120000,
            'promotion_candidate_count': 1,
        },
        'safety': {
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def _moneyflow_profile() -> dict:
    return {
        'verdict': 'ACCEPT',
        'performance_gate': {
            'production_default_allowed': False,
            'default_replacement_verdict': 'PROMOTE',
            'candidates': [
                {
                    'operator_id': 'moneyflow_slow_state_v1',
                    'baseline_backend': 'reference',
                    'candidate_backend': 'process_sharded_array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 1.35,
                }
            ],
        },
    }


def _moneyflow_approval() -> dict:
    return {
        'verdict': 'ACCEPT',
        'approval_scope': 'production_default_backend',
        'operator_id': 'moneyflow_slow_state_v1',
        'approved_backend': 'process_sharded_array_grouped',
        'production_default_allowed': True,
        'approved_by': 'reviewer-test',
        'approval_reason': 'moneyflow slow-state safe worker proof accepted',
        'evidence_scope': 'production_scale',
    }


def _moneyflow_safe_worker_bundle() -> dict:
    return {
        'verdict': 'ACCEPT',
        'preflight_summary': {'verdict': 'ACCEPT', 'issues': []},
        'worker_benchmark_summary': {
            'verdict': 'ACCEPT',
            'sample_row_count': 120000,
            'benchmark_scope': 'real_bounded_read_only',
            'operator_replacement_verdict': 'PROMOTE',
        },
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def _moneyflow_safe_worker_validation() -> dict:
    return {
        'verdict': 'ACCEPT',
        'issues': [],
        'input_row_count': 120000,
        'date_count': 20,
        'min_trade_date': '20240102',
        'max_trade_date': '20240131',
        'evidence_scope': 'production_scale',
        'benchmark_scope': 'real_bounded_read_only',
        'production_default_allowed': False,
        'operator_replacement_verdict': 'PROMOTE',
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def test_production_approval_validator_requires_safe_worker_bundle(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    validation_path = tmp_path / 'validation.json'
    approval_path = tmp_path / 'approval.json'
    output_path = tmp_path / 'approval.validation.json'
    profile_path.write_text(json.dumps(_profile()))
    validation_path.write_text(json.dumps(_validation()))
    approval_path.write_text(json.dumps(_approval()))

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--validation-path',
        str(validation_path),
        '--approval-path',
        str(approval_path),
        '--operator-id',
        'cpv_price_volume_corr_state',
        '--default-backend',
        'array_grouped',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'safe_worker_bundle_missing' in payload['issues']
    assert payload['decision']['replacement_allowed'] is False


def test_production_approval_validator_accepts_matching_promoted_candidate_with_safe_worker_bundle(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    validation_path = tmp_path / 'validation.json'
    approval_path = tmp_path / 'approval.json'
    safe_worker_bundle_path = tmp_path / 'safe_worker_bundle.json'
    output_path = tmp_path / 'approval.validation.json'
    profile_path.write_text(json.dumps(_profile()))
    validation_path.write_text(json.dumps(_validation()))
    approval_path.write_text(json.dumps(_approval()))
    safe_worker_bundle_path.write_text(json.dumps(_safe_worker_bundle()))

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--validation-path',
        str(validation_path),
        '--approval-path',
        str(approval_path),
        '--safe-worker-bundle-path',
        str(safe_worker_bundle_path),
        '--operator-id',
        'cpv_price_volume_corr_state',
        '--default-backend',
        'array_grouped',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['decision']['selected_backend'] == 'process_sharded_array_grouped'
    assert payload['decision']['replacement_allowed'] is True
    assert payload['issues'] == []


def test_production_approval_validator_blocks_mismatched_backend(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    validation_path = tmp_path / 'validation.json'
    approval_path = tmp_path / 'approval.json'
    safe_worker_bundle_path = tmp_path / 'safe_worker_bundle.json'
    output_path = tmp_path / 'approval.validation.json'
    profile_path.write_text(json.dumps(_profile()))
    validation_path.write_text(json.dumps(_validation()))
    approval_path.write_text(json.dumps(_approval(backend='array_grouped')))
    safe_worker_bundle_path.write_text(json.dumps(_safe_worker_bundle()))

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--validation-path',
        str(validation_path),
        '--approval-path',
        str(approval_path),
        '--safe-worker-bundle-path',
        str(safe_worker_bundle_path),
        '--operator-id',
        'cpv_price_volume_corr_state',
        '--default-backend',
        'array_grouped',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'production_approval_not_valid_for_candidate' in payload['issues']
    assert payload['decision']['selected_backend'] == 'array_grouped'


def test_production_approval_validator_blocks_bounded_only_approval_scope(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    validation_path = tmp_path / 'validation.json'
    approval_path = tmp_path / 'approval.json'
    safe_worker_bundle_path = tmp_path / 'safe_worker_bundle.json'
    output_path = tmp_path / 'approval.validation.json'
    approval = _approval()
    approval['evidence_scope'] = 'bounded_worker'
    profile_path.write_text(json.dumps(_profile()))
    validation_path.write_text(json.dumps(_validation()))
    approval_path.write_text(json.dumps(approval))
    safe_worker_bundle_path.write_text(json.dumps(_safe_worker_bundle()))

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--validation-path',
        str(validation_path),
        '--approval-path',
        str(approval_path),
        '--safe-worker-bundle-path',
        str(safe_worker_bundle_path),
        '--operator-id',
        'cpv_price_volume_corr_state',
        '--default-backend',
        'array_grouped',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'approval_evidence_scope_not_production_scale_or_full_is' in payload['issues']
    assert payload['decision']['replacement_allowed'] is False


def test_production_approval_validator_accepts_moneyflow_safe_worker_validation(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    validation_path = tmp_path / 'validation.json'
    approval_path = tmp_path / 'approval.json'
    safe_worker_bundle_path = tmp_path / 'safe_worker_bundle.json'
    safe_worker_validation_path = tmp_path / 'safe_worker.validation.json'
    output_path = tmp_path / 'approval.validation.json'
    profile_path.write_text(json.dumps(_moneyflow_profile()))
    validation_path.write_text(json.dumps(_validation()))
    approval_path.write_text(json.dumps(_moneyflow_approval()))
    safe_worker_bundle_path.write_text(json.dumps(_moneyflow_safe_worker_bundle()))
    safe_worker_validation_path.write_text(json.dumps(_moneyflow_safe_worker_validation()))

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--validation-path',
        str(validation_path),
        '--approval-path',
        str(approval_path),
        '--safe-worker-bundle-path',
        str(safe_worker_bundle_path),
        '--safe-worker-validation-path',
        str(safe_worker_validation_path),
        '--operator-id',
        'moneyflow_slow_state_v1',
        '--default-backend',
        'array_grouped',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['decision']['selected_backend'] == 'process_sharded_array_grouped'
    assert payload['decision']['replacement_allowed'] is True
    assert payload['safe_worker_validation_verdict'] == 'ACCEPT'


def test_production_approval_validator_blocks_moneyflow_without_safe_validation(tmp_path):
    validator = _load_validator_module()
    profile_path = tmp_path / 'profile.json'
    validation_path = tmp_path / 'validation.json'
    approval_path = tmp_path / 'approval.json'
    safe_worker_bundle_path = tmp_path / 'safe_worker_bundle.json'
    output_path = tmp_path / 'approval.validation.json'
    profile_path.write_text(json.dumps(_moneyflow_profile()))
    validation_path.write_text(json.dumps(_validation()))
    approval_path.write_text(json.dumps(_moneyflow_approval()))
    safe_worker_bundle_path.write_text(json.dumps(_moneyflow_safe_worker_bundle()))

    exit_code = validator.main([
        '--profile-path',
        str(profile_path),
        '--validation-path',
        str(validation_path),
        '--approval-path',
        str(approval_path),
        '--safe-worker-bundle-path',
        str(safe_worker_bundle_path),
        '--operator-id',
        'moneyflow_slow_state_v1',
        '--default-backend',
        'array_grouped',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'safe_worker_validation_missing' in payload['issues']
