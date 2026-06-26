from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_readiness_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_operator_backend_readiness.py'
    spec = importlib.util.spec_from_file_location('validate_operator_backend_readiness', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def _safe_validation(operator_replacement_verdict: str = 'PROMOTE', evidence_scope: str = 'production_scale') -> dict:
    return {
        'verdict': 'ACCEPT',
        'issues': [],
        'input_row_count': 250000,
        'date_count': 20,
        'evidence_scope': evidence_scope,
        'benchmark_scope': 'real_bounded_read_only',
        'production_default_allowed': False,
        'operator_replacement_verdict': operator_replacement_verdict,
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def _approval_validation(
    *,
    operator_id: str = 'cpv_price_volume_corr_state',
    default_backend: str = 'array_grouped',
    selected_backend: str = 'process_sharded_array_grouped',
    evidence_scope: str = 'production_scale',
) -> dict:
    return {
        'verdict': 'ACCEPT',
        'operator_id': operator_id,
        'default_backend': default_backend,
        'approved_backend': selected_backend,
        'approval_evidence_scope': evidence_scope,
        'safe_worker_validation_evidence_scope': evidence_scope,
        'issues': [],
        'decision': {
            'operator_id': operator_id,
            'default_backend': default_backend,
            'selected_backend': selected_backend,
            'candidate_backend': selected_backend,
            'replacement_allowed': True,
            'reason': 'approved_candidate_promoted_by_production_approval',
        },
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def _replacement_plan(
    *,
    operator_id: str = 'cpv_price_volume_corr_state',
    default_backend: str = 'array_grouped',
    selected_backend: str = 'process_sharded_array_grouped',
    evidence_scope: str = 'production_scale',
) -> dict:
    return {
        'verdict': 'ACCEPT',
        'operator_id': operator_id,
        'default_backend': default_backend,
        'selected_backend': selected_backend,
        'candidate_backend': selected_backend,
        'evidence_scope': evidence_scope,
        'replacement_action': 'plan_only',
        'issues': [],
        'required_next_step': 'manual_config_change_after_review',
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def test_operator_backend_readiness_accepts_cpv_complete_chain(tmp_path):
    validator = _load_readiness_module()
    safe_path = _write_json(tmp_path / 'safe.validation.json', _safe_validation())
    approval_path = _write_json(tmp_path / 'approval.validation.json', _approval_validation())
    plan_path = _write_json(tmp_path / 'replacement.plan.json', _replacement_plan())
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--operator-id',
        'cpv_price_volume_corr_state',
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
    assert payload['readiness'] == 'ready_for_manual_config_change_after_review'
    assert payload['operator_id'] == 'cpv_price_volume_corr_state'
    assert payload['default_backend'] == 'array_grouped'
    assert payload['selected_backend'] == 'process_sharded_array_grouped'


def test_operator_backend_readiness_blocks_bounded_evidence(tmp_path):
    validator = _load_readiness_module()
    safe_path = _write_json(tmp_path / 'safe.validation.json', _safe_validation(evidence_scope='bounded_worker'))
    approval_path = _write_json(
        tmp_path / 'approval.validation.json',
        _approval_validation(evidence_scope='bounded_worker'),
    )
    plan_path = _write_json(
        tmp_path / 'replacement.plan.json',
        _replacement_plan(evidence_scope='bounded_worker'),
    )
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--operator-id',
        'cpv_price_volume_corr_state',
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
    assert 'safe_validation_evidence_scope_not_production_scale_or_full_is' in payload['issues']


def test_operator_backend_readiness_blocks_replacement_plan_selected_backend_mismatch(tmp_path):
    validator = _load_readiness_module()
    safe_path = _write_json(tmp_path / 'safe.validation.json', _safe_validation())
    approval_path = _write_json(tmp_path / 'approval.validation.json', _approval_validation())
    plan_path = _write_json(
        tmp_path / 'replacement.plan.json',
        _replacement_plan(selected_backend='array_grouped'),
    )
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--operator-id',
        'cpv_price_volume_corr_state',
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
    assert 'replacement_plan_selected_backend_mismatch' in payload['issues']


def test_operator_backend_readiness_accepts_moneyflow_operator_chain(tmp_path):
    validator = _load_readiness_module()
    safe_path = _write_json(tmp_path / 'safe.validation.json', _safe_validation(evidence_scope='full_is'))
    approval_path = _write_json(
        tmp_path / 'approval.validation.json',
        _approval_validation(
            operator_id='moneyflow_slow_state_v1',
            default_backend='reference',
            selected_backend='array_grouped',
            evidence_scope='full_is',
        ),
    )
    plan_path = _write_json(
        tmp_path / 'replacement.plan.json',
        _replacement_plan(
            operator_id='moneyflow_slow_state_v1',
            default_backend='reference',
            selected_backend='array_grouped',
            evidence_scope='full_is',
        ),
    )
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--operator-id',
        'moneyflow_slow_state_v1',
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
    assert payload['evidence_scope'] == 'full_is'
    assert payload['selected_backend'] == 'array_grouped'
