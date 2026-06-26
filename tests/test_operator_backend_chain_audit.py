from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_audit_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_operator_backend_chain.py'
    spec = importlib.util.spec_from_file_location('audit_operator_backend_chain', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def _safe_validation(evidence_scope: str = 'production_scale') -> dict:
    return {
        'verdict': 'ACCEPT',
        'issues': [],
        'evidence_scope': evidence_scope,
        'input_row_count': 250000,
        'date_count': 20,
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


def _approval_validation(evidence_scope: str = 'production_scale') -> dict:
    return {
        'verdict': 'ACCEPT',
        'operator_id': 'cpv_price_volume_corr_state',
        'approval_evidence_scope': evidence_scope,
        'safe_worker_validation_evidence_scope': evidence_scope,
        'issues': [],
        'decision': {
            'operator_id': 'cpv_price_volume_corr_state',
            'default_backend': 'array_grouped',
            'selected_backend': 'process_sharded_array_grouped',
            'candidate_backend': 'process_sharded_array_grouped',
            'replacement_allowed': True,
            'reason': 'approved_candidate_promoted_by_production_approval',
        },
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def _replacement_plan(evidence_scope: str = 'production_scale') -> dict:
    return {
        'verdict': 'ACCEPT',
        'operator_id': 'cpv_price_volume_corr_state',
        'default_backend': 'array_grouped',
        'selected_backend': 'process_sharded_array_grouped',
        'candidate_backend': 'process_sharded_array_grouped',
        'evidence_scope': evidence_scope,
        'replacement_action': 'plan_only',
        'required_next_step': 'manual_config_change_after_review',
        'issues': [],
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def _write_chain(tmp_path: Path, *, evidence_scope: str = 'production_scale') -> tuple[Path, Path, Path]:
    safe_path = _write_json(tmp_path / 'safe.validation.json', _safe_validation(evidence_scope))
    approval_path = _write_json(tmp_path / 'approval.validation.json', _approval_validation(evidence_scope))
    plan_path = _write_json(tmp_path / 'replacement.plan.json', _replacement_plan(evidence_scope))
    return safe_path, approval_path, plan_path


def test_operator_backend_chain_audit_accepts_ready_runtime_chain(tmp_path):
    audit = _load_audit_module()
    safe_path, approval_path, plan_path = _write_chain(tmp_path)
    output_path = tmp_path / 'audit.json'

    exit_code = audit.main([
        '--operator-id',
        'cpv_price_volume_corr_state',
        '--default-backend',
        'array_grouped',
        '--configured-backend',
        'process_sharded_array_grouped',
        '--safe-validation-path',
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
    assert payload['readiness']['verdict'] == 'ACCEPT'
    assert payload['runtime_decision']['replacement_allowed'] is True
    assert payload['runtime_decision']['selected_backend'] == 'process_sharded_array_grouped'
    assert payload['safety']['writes_backend_config'] is False


def test_operator_backend_chain_audit_blocks_bounded_evidence_even_if_runtime_configured(tmp_path):
    audit = _load_audit_module()
    safe_path, approval_path, plan_path = _write_chain(tmp_path, evidence_scope='bounded_worker')
    output_path = tmp_path / 'audit.json'

    exit_code = audit.main([
        '--operator-id',
        'cpv_price_volume_corr_state',
        '--default-backend',
        'array_grouped',
        '--configured-backend',
        'process_sharded_array_grouped',
        '--safe-validation-path',
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
    assert 'readiness_not_accept' in payload['issues']
    assert 'runtime_registry_replacement_not_allowed' in payload['issues']
    assert payload['runtime_decision']['selected_backend'] == 'array_grouped'


def test_operator_backend_chain_audit_blocks_configured_backend_mismatch(tmp_path):
    audit = _load_audit_module()
    safe_path, approval_path, plan_path = _write_chain(tmp_path)
    output_path = tmp_path / 'audit.json'

    exit_code = audit.main([
        '--operator-id',
        'cpv_price_volume_corr_state',
        '--default-backend',
        'array_grouped',
        '--configured-backend',
        'threaded_grouped',
        '--safe-validation-path',
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
    assert payload['readiness']['verdict'] == 'ACCEPT'
    assert 'runtime_registry_replacement_not_allowed' in payload['issues']
    assert 'runtime_selected_backend_mismatch_readiness' in payload['issues']
    assert 'runtime_selected_backend_mismatch_configured_backend' in payload['issues']
