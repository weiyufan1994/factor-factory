from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_builder_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_operator_backend_production_approval.py'
    spec = importlib.util.spec_from_file_location('build_operator_backend_production_approval', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            'default_replacement_verdict': 'PROMOTE',
            'candidates': [
                {
                    'operator_id': 'moneyflow_slow_state_v1',
                    'baseline_backend': 'reference',
                    'candidate_backend': 'array_grouped',
                    'performance_verdict': 'PROMOTE',
                    'speedup': 4.5,
                },
            ],
        },
    }


def _validation() -> dict:
    return {
        'verdict': 'ACCEPT',
        'issue_count': 0,
        'issues': [],
    }


def _safe_worker_bundle() -> dict:
    return {
        'verdict': 'ACCEPT',
        'evidence_scope': 'production_scale',
        'preflight_summary': {'verdict': 'ACCEPT', 'issues': []},
        'worker_benchmark_summary': {
            'verdict': 'ACCEPT',
            'sample_row_count': 250000,
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


def _safe_worker_validation(row_count: int = 250000) -> dict:
    return {
        'verdict': 'ACCEPT',
        'issues': [],
        'input_row_count': row_count,
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


def _write_inputs(tmp_path: Path, *, row_count: int = 250000) -> dict[str, Path]:
    paths = {
        'profile_path': tmp_path / 'profile.json',
        'validation_path': tmp_path / 'validation.json',
        'safe_worker_bundle_path': tmp_path / 'safe_worker_bundle.json',
        'safe_worker_validation_path': tmp_path / 'safe_worker_validation.json',
    }
    paths['profile_path'].write_text(json.dumps(_profile()), encoding='utf-8')
    paths['validation_path'].write_text(json.dumps(_validation()), encoding='utf-8')
    paths['safe_worker_bundle_path'].write_text(json.dumps(_safe_worker_bundle()), encoding='utf-8')
    paths['safe_worker_validation_path'].write_text(json.dumps(_safe_worker_validation(row_count)), encoding='utf-8')
    return paths


def _base_args(paths: dict[str, Path], output_path: Path) -> list[str]:
    return [
        '--profile-path',
        str(paths['profile_path']),
        '--validation-path',
        str(paths['validation_path']),
        '--safe-worker-bundle-path',
        str(paths['safe_worker_bundle_path']),
        '--safe-worker-validation-path',
        str(paths['safe_worker_validation_path']),
        '--operator-id',
        'moneyflow_slow_state_v1',
        '--approved-backend',
        'array_grouped',
        '--approved-by',
        'reviewer-test',
        '--approval-reason',
        'production-scale safe worker proof accepted',
        '--output-path',
        str(output_path),
    ]


def test_approval_builder_blocks_bounded_worker_scope(tmp_path):
    builder = _load_builder_module()
    paths = _write_inputs(tmp_path)
    safe_validation = json.loads(paths['safe_worker_validation_path'].read_text())
    safe_validation['evidence_scope'] = 'bounded_worker'
    paths['safe_worker_validation_path'].write_text(json.dumps(safe_validation), encoding='utf-8')
    safe_bundle = json.loads(paths['safe_worker_bundle_path'].read_text())
    safe_bundle['evidence_scope'] = 'bounded_worker'
    paths['safe_worker_bundle_path'].write_text(json.dumps(safe_bundle), encoding='utf-8')
    output_path = tmp_path / 'approval.json'

    exit_code = builder.main([
        *_base_args(paths, output_path),
        '--evidence-scope',
        'bounded_worker',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['production_default_allowed'] is False
    assert 'evidence_scope_not_production_scale_or_full_is' in payload['issues']


def test_approval_builder_blocks_tiny_production_scale_proof(tmp_path):
    builder = _load_builder_module()
    paths = _write_inputs(tmp_path, row_count=9859)
    output_path = tmp_path / 'approval.json'

    exit_code = builder.main([
        *_base_args(paths, output_path),
        '--evidence-scope',
        'production_scale',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['production_default_allowed'] is False
    assert 'safe_worker_validation_input_row_count_below_minimum' in payload['issues']


def test_approval_builder_blocks_when_requested_scope_does_not_match_validation(tmp_path):
    builder = _load_builder_module()
    paths = _write_inputs(tmp_path, row_count=250000)
    safe_validation = json.loads(paths['safe_worker_validation_path'].read_text())
    safe_validation['evidence_scope'] = 'full_is'
    paths['safe_worker_validation_path'].write_text(json.dumps(safe_validation), encoding='utf-8')
    output_path = tmp_path / 'approval.json'

    exit_code = builder.main([
        *_base_args(paths, output_path),
        '--evidence-scope',
        'production_scale',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'safe_worker_validation_evidence_scope_mismatch' in payload['issues']


def test_approval_builder_output_is_accepted_by_production_validator(tmp_path):
    builder = _load_builder_module()
    validator = _load_validator_module()
    paths = _write_inputs(tmp_path, row_count=250000)
    approval_path = tmp_path / 'approval.json'
    validation_output = tmp_path / 'approval.validation.json'

    build_exit = builder.main([
        *_base_args(paths, approval_path),
        '--evidence-scope',
        'production_scale',
    ])
    validate_exit = validator.main([
        '--profile-path',
        str(paths['profile_path']),
        '--validation-path',
        str(paths['validation_path']),
        '--approval-path',
        str(approval_path),
        '--safe-worker-bundle-path',
        str(paths['safe_worker_bundle_path']),
        '--safe-worker-validation-path',
        str(paths['safe_worker_validation_path']),
        '--operator-id',
        'moneyflow_slow_state_v1',
        '--default-backend',
        'reference',
        '--output-path',
        str(validation_output),
    ])

    approval = json.loads(approval_path.read_text())
    validation = json.loads(validation_output.read_text())
    assert build_exit == 0
    assert validate_exit == 0
    assert approval['verdict'] == 'ACCEPT'
    assert approval['evidence_scope'] == 'production_scale'
    assert approval['evidence']['input_row_count'] == 250000
    assert approval['evidence']['evidence_scope'] == 'production_scale'
    assert approval['evidence']['date_count'] == 20
    assert set(approval['evidence']['sha256']) == {
        'profile_path',
        'validation_path',
        'safe_worker_bundle_path',
        'safe_worker_validation_path',
    }
    assert validation['verdict'] == 'ACCEPT'
    assert validation['approval_evidence_scope'] == 'production_scale'
    assert validation['safe_worker_validation_evidence_scope'] == 'production_scale'
    assert validation['decision']['selected_backend'] == 'array_grouped'
    assert validation['decision']['replacement_allowed'] is True
