from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_intraday_operator_worker_benchmark.py'
    spec = importlib.util.spec_from_file_location('validate_intraday_operator_worker_benchmark', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_worker_bundle(
    tmp_path: Path,
    *,
    safety_override: dict | None = None,
    include_evidence_scope: bool = True,
) -> Path:
    gate_validation_path = tmp_path / 'gate.validation.json'
    gate_validation_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'issues': [],
        'input_row_count': 120000,
        'min_row_count': 100000,
        'benchmark_scope': 'real_bounded_read_only',
        'production_default_allowed': False,
    }))
    gate_bundle_path = tmp_path / 'gate.bundle.json'
    gate_bundle_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'validation_path': str(gate_validation_path),
        'profile_summary': {
            'benchmark_scope': 'real_bounded_read_only',
            'production_default_allowed': False,
            'performance_candidates': [
                {
                    'operator_id': 'rolling_corr_by_group',
                    'candidate_backend': 'array_grouped',
                    'performance_verdict': 'PROMOTE',
                }
            ],
        },
        'validation_summary': {'verdict': 'ACCEPT', 'issues': []},
        'safety': {
            'uses_real_market_data': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }))
    sample_proof_path = tmp_path / 'sample.proof.json'
    sample_proof_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'row_count': 120000,
        'duplicate_key_count': 0,
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }))
    safety = {
        'read_only_input': True,
        'starts_backfill': False,
        'writes_datamart': False,
        'writes_catalog': False,
        'production_loop_side_effect': False,
    }
    if safety_override:
        safety.update(safety_override)
    bundle_path = tmp_path / 'worker.bundle.json'
    payload = {
        'verdict': 'ACCEPT',
        'evidence_scope': 'bounded_worker',
        'sample_proof_path': str(sample_proof_path),
        'gate_bundle_path': str(gate_bundle_path),
        'sample_summary': {'row_count': 120000, 'duplicate_key_count': 0},
        'gate_summary': {
            'verdict': 'ACCEPT',
            'validation_verdict': 'ACCEPT',
            'validation_issues': [],
            'benchmark_scope': 'real_bounded_read_only',
            'production_default_allowed': False,
            'performance_candidates': [
                {
                    'operator_id': 'rolling_corr_by_group',
                    'candidate_backend': 'array_grouped',
                    'performance_verdict': 'PROMOTE',
                }
            ],
        },
        'safety': safety,
    }
    if not include_evidence_scope:
        payload.pop('evidence_scope')
    bundle_path.write_text(json.dumps(payload))
    return bundle_path


def test_worker_benchmark_validator_accepts_complete_safe_bundle(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_worker_bundle(tmp_path)
    output_path = tmp_path / 'worker.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
        '--min-row-count',
        '100000',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['evidence_scope'] == 'bounded_worker'
    assert payload['promotion_candidate_count'] == 1
    assert payload['input_row_count'] == 120000


def test_worker_benchmark_validator_blocks_unsafe_bundle(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_worker_bundle(tmp_path, safety_override={'writes_datamart': True})
    output_path = tmp_path / 'worker.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
        '--min-row-count',
        '100000',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'safety_writes_datamart_must_be_false' in payload['issues']


def test_worker_benchmark_validator_blocks_missing_evidence_scope(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_worker_bundle(tmp_path, include_evidence_scope=False)
    output_path = tmp_path / 'worker.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
        '--min-row-count',
        '100000',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'evidence_scope_missing_or_invalid' in payload['issues']


def test_worker_benchmark_validator_allows_cli_evidence_scope_override(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_worker_bundle(tmp_path, include_evidence_scope=False)
    output_path = tmp_path / 'worker.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
        '--min-row-count',
        '100000',
        '--evidence-scope',
        'production_scale',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['evidence_scope'] == 'production_scale'


def test_worker_benchmark_validator_blocks_tiny_production_scope_threshold(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_worker_bundle(tmp_path)
    output_path = tmp_path / 'worker.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
        '--min-row-count',
        '8',
        '--evidence-scope',
        'production_scale',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'min_row_count_too_low_for_production_evidence' in payload['issues']
