from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_readiness_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_moneyflow_slow_state_backend_readiness.py'
    spec = importlib.util.spec_from_file_location('validate_moneyflow_slow_state_backend_readiness', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def _safe_worker_validation() -> dict:
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


def _approval_validation() -> dict:
    return {
        'verdict': 'ACCEPT',
        'operator_id': 'moneyflow_slow_state_v1',
        'default_backend': 'reference',
        'approved_backend': 'array_grouped',
        'approval_evidence_scope': 'production_scale',
        'safe_worker_validation_evidence_scope': 'production_scale',
        'issues': [],
        'decision': {
            'operator_id': 'moneyflow_slow_state_v1',
            'default_backend': 'reference',
            'selected_backend': 'array_grouped',
            'candidate_backend': 'array_grouped',
            'replacement_allowed': True,
            'reason': 'approved_candidate_promoted_by_production_approval',
        },
        'safe_worker_validation_path': '/tmp/safe.validation.json',
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def _replacement_plan() -> dict:
    return {
        'verdict': 'ACCEPT',
        'operator_id': 'moneyflow_slow_state_v1',
        'default_backend': 'reference',
        'selected_backend': 'array_grouped',
        'evidence_scope': 'production_scale',
        'replacement_action': 'plan_only',
        'issues': [],
        'required_next_step': 'manual_config_change_after_review',
        'proof_paths': {
            'safe_worker_validation_path': '/tmp/safe.validation.json',
        },
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def test_backend_readiness_accepts_complete_reviewed_chain(tmp_path):
    validator = _load_readiness_module()
    safe_path = _write_json(tmp_path / 'safe.validation.json', _safe_worker_validation())
    approval_path = _write_json(tmp_path / 'approval.validation.json', _approval_validation())
    plan_path = _write_json(tmp_path / 'replacement.plan.json', _replacement_plan())
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--safe-worker-validation-path',
        str(safe_path),
        '--approval-validation-path',
        str(approval_path),
        '--replacement-plan-path',
        str(plan_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['operator_id'] == 'moneyflow_slow_state_v1'
    assert payload['selected_backend'] == 'array_grouped'
    assert payload['evidence_scope'] == 'production_scale'
    assert payload['readiness'] == 'ready_for_manual_config_change_after_review'
    assert payload['safety']['writes_backend_config'] is False


def test_backend_readiness_blocks_when_true_worker_safe_validation_missing(tmp_path):
    validator = _load_readiness_module()
    approval_path = _write_json(tmp_path / 'approval.validation.json', _approval_validation())
    plan_path = _write_json(tmp_path / 'replacement.plan.json', _replacement_plan())
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--safe-worker-validation-path',
        str(tmp_path / 'missing.safe.validation.json'),
        '--approval-validation-path',
        str(approval_path),
        '--replacement-plan-path',
        str(plan_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'safe_worker_validation_missing_or_unreadable' in payload['issues']
    assert payload['readiness'] == 'not_ready'


def test_backend_readiness_blocks_bounded_worker_chain(tmp_path):
    validator = _load_readiness_module()
    safe_payload = _safe_worker_validation()
    safe_payload['evidence_scope'] = 'bounded_worker'
    approval_payload = _approval_validation()
    approval_payload['approval_evidence_scope'] = 'bounded_worker'
    approval_payload['safe_worker_validation_evidence_scope'] = 'bounded_worker'
    plan_payload = _replacement_plan()
    plan_payload['evidence_scope'] = 'bounded_worker'
    safe_path = _write_json(tmp_path / 'safe.validation.json', safe_payload)
    approval_path = _write_json(tmp_path / 'approval.validation.json', approval_payload)
    plan_path = _write_json(tmp_path / 'replacement.plan.json', plan_payload)
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--safe-worker-validation-path',
        str(safe_path),
        '--approval-validation-path',
        str(approval_path),
        '--replacement-plan-path',
        str(plan_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'safe_worker_validation_evidence_scope_not_production_scale_or_full_is' in payload['issues']
    assert payload['readiness'] == 'not_ready'


def test_backend_readiness_blocks_replacement_plan_evidence_scope_mismatch(tmp_path):
    validator = _load_readiness_module()
    safe_path = _write_json(tmp_path / 'safe.validation.json', _safe_worker_validation())
    approval_path = _write_json(tmp_path / 'approval.validation.json', _approval_validation())
    plan_payload = _replacement_plan()
    plan_payload['evidence_scope'] = 'bounded_worker'
    plan_path = _write_json(tmp_path / 'replacement.plan.json', plan_payload)
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--safe-worker-validation-path',
        str(safe_path),
        '--approval-validation-path',
        str(approval_path),
        '--replacement-plan-path',
        str(plan_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'replacement_plan_evidence_scope_mismatch' in payload['issues']
    assert payload['readiness'] == 'not_ready'
