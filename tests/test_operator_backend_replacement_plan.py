from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_plan_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'plan_operator_backend_replacement.py'
    spec = importlib.util.spec_from_file_location('plan_operator_backend_replacement', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _approval_validation(verdict: str = 'ACCEPT') -> dict:
    decision = {
        'operator_id': 'cpv_price_volume_corr_state',
        'default_backend': 'array_grouped',
        'selected_backend': 'process_sharded_array_grouped',
        'candidate_backend': 'process_sharded_array_grouped',
        'replacement_allowed': verdict == 'ACCEPT',
        'reason': 'approved_candidate_promoted_by_production_approval' if verdict == 'ACCEPT' else 'production_approval_not_valid_for_candidate',
    }
    return {
        'verdict': verdict,
        'operator_id': 'cpv_price_volume_corr_state',
        'default_backend': 'array_grouped',
        'approved_backend': 'process_sharded_array_grouped',
        'issues': [] if verdict == 'ACCEPT' else ['production_approval_not_valid_for_candidate'],
        'decision': decision,
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def _moneyflow_approval_validation() -> dict:
    return {
        'verdict': 'ACCEPT',
        'operator_id': 'moneyflow_slow_state_v1',
        'default_backend': 'reference',
        'approved_backend': 'array_grouped',
        'approval_evidence_scope': 'production_scale',
        'safe_worker_validation_evidence_scope': 'production_scale',
        'safe_worker_bundle_path': '/tmp/moneyflow/real_bounded.safe_worker_benchmark.bundle.json',
        'safe_worker_validation_path': '/tmp/moneyflow/real_bounded.safe_worker_benchmark.validation.json',
        'profile_path': '/tmp/moneyflow/real_bounded.profile.json',
        'validation_path': '/tmp/moneyflow/real_bounded.validation.json',
        'issues': [],
        'decision': {
            'operator_id': 'moneyflow_slow_state_v1',
            'default_backend': 'reference',
            'selected_backend': 'array_grouped',
            'candidate_backend': 'array_grouped',
            'replacement_allowed': True,
            'reason': 'approved_candidate_promoted_by_production_approval',
        },
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def test_backend_replacement_plan_accepts_valid_approval_validation(tmp_path):
    planner = _load_plan_module()
    approval_validation_path = tmp_path / 'approval.validation.json'
    output_path = tmp_path / 'backend_replacement.plan.json'
    approval_validation_path.write_text(json.dumps(_approval_validation('ACCEPT')))

    exit_code = planner.main([
        '--approval-validation-path',
        str(approval_validation_path),
        '--target-scope',
        'data_api_operator_backend_registry',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['operator_id'] == 'cpv_price_volume_corr_state'
    assert payload['default_backend'] == 'array_grouped'
    assert payload['selected_backend'] == 'process_sharded_array_grouped'
    assert payload['replacement_action'] == 'plan_only'
    assert payload['safety']['writes_backend_config'] is False
    assert payload['safety']['production_loop_side_effect'] is False


def test_backend_replacement_plan_blocks_when_approval_validation_blocks(tmp_path):
    planner = _load_plan_module()
    approval_validation_path = tmp_path / 'approval.validation.json'
    output_path = tmp_path / 'backend_replacement.plan.json'
    approval_validation_path.write_text(json.dumps(_approval_validation('BLOCK')))

    exit_code = planner.main([
        '--approval-validation-path',
        str(approval_validation_path),
        '--target-scope',
        'data_api_operator_backend_registry',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'approval_validation_not_accept' in payload['issues']
    assert payload['selected_backend'] == 'array_grouped'
    assert payload['safety']['writes_backend_config'] is False


def test_backend_replacement_plan_carries_moneyflow_safe_worker_provenance(tmp_path):
    planner = _load_plan_module()
    approval_validation_path = tmp_path / 'moneyflow.approval.validation.json'
    output_path = tmp_path / 'moneyflow.backend_replacement.plan.json'
    approval_validation_path.write_text(json.dumps(_moneyflow_approval_validation()))

    exit_code = planner.main([
        '--approval-validation-path',
        str(approval_validation_path),
        '--target-scope',
        'data_api_operator_backend_registry',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['operator_id'] == 'moneyflow_slow_state_v1'
    assert payload['default_backend'] == 'reference'
    assert payload['selected_backend'] == 'array_grouped'
    assert payload['evidence_scope'] == 'production_scale'
    assert payload['proof_paths']['safe_worker_bundle_path'].endswith('safe_worker_benchmark.bundle.json')
    assert payload['proof_paths']['safe_worker_validation_path'].endswith('safe_worker_benchmark.validation.json')
    assert payload['proof_paths']['profile_path'].endswith('real_bounded.profile.json')
    assert payload['proof_paths']['validation_path'].endswith('real_bounded.validation.json')
    assert payload['replacement_action'] == 'plan_only'
