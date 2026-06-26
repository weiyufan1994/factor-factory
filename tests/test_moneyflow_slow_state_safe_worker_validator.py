from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_moneyflow_slow_state_safe_worker_benchmark.py'
    spec = importlib.util.spec_from_file_location('validate_moneyflow_slow_state_safe_worker_benchmark', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_safe_bundle(tmp_path: Path, *, overrides: dict | None = None) -> Path:
    profile_path = tmp_path / 'gate.profile.json'
    profile_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'dataset_id': 'moneyflow_slow_state_v1',
        'source_dataset': 'intraday_flow_distribution_moments_v1',
        'benchmark_scope': 'real_bounded_read_only',
        'production_default_allowed': False,
        'operator_replacement_verdict': 'HOLD',
        'input': {'row_count': 120000, 'dates': ['20240102', '20240103']},
        'safety': {
            'uses_real_market_data': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }))
    validation_path = tmp_path / 'gate.validation.json'
    validation_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'issue_count': 0,
        'issues': [],
        'benchmark_scope': 'real_bounded_read_only',
        'production_default_allowed': False,
        'operator_replacement_verdict': 'HOLD',
        'input_row_count': 120000,
        'min_row_count': 100000,
        'date_count': 2,
        'min_trade_date': '20240102',
        'max_trade_date': '20240103',
    }))
    gate_bundle_path = tmp_path / 'gate.bundle.json'
    gate_bundle_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'profile_path': str(profile_path),
        'validation_path': str(validation_path),
        'profile_summary': {
            'verdict': 'ACCEPT',
            'benchmark_scope': 'real_bounded_read_only',
            'production_default_allowed': False,
            'operator_replacement_verdict': 'HOLD',
        },
        'validation_summary': {
            'verdict': 'ACCEPT',
            'issue_count': 0,
            'issues': [],
            'operator_replacement_verdict': 'HOLD',
        },
        'safety': {
            'uses_real_market_data': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }))
    sample_proof_path = tmp_path / 'sample.proof.json'
    sample_proof_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'row_count': 120000,
        'date_count': 2,
        'min_trade_date': '20240102',
        'max_trade_date': '20240103',
        'duplicate_key_count': 0,
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }))
    worker_bundle_path = tmp_path / 'worker.bundle.json'
    worker_bundle_path.write_text(json.dumps({
        'verdict': 'ACCEPT',
        'sample_proof_path': str(sample_proof_path),
        'gate_bundle_path': str(gate_bundle_path),
        'sample_summary': {
            'verdict': 'ACCEPT',
            'row_count': 120000,
            'duplicate_key_count': 0,
        },
        'gate_summary': {
            'verdict': 'ACCEPT',
            'validation_verdict': 'ACCEPT',
            'benchmark_scope': 'real_bounded_read_only',
            'operator_replacement_verdict': 'HOLD',
            'production_default_allowed': False,
        },
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }))
    preflight_path = tmp_path / 'preflight.json'
    preflight_path.write_text(json.dumps({'verdict': 'ACCEPT', 'issues': []}))
    safe_bundle = {
        'verdict': 'ACCEPT',
        'preflight_path': str(preflight_path),
        'preflight_summary': {'verdict': 'ACCEPT', 'issues': []},
        'worker_benchmark_bundle_path': str(worker_bundle_path),
        'worker_benchmark_summary': {
            'verdict': 'ACCEPT',
            'sample_row_count': 120000,
            'benchmark_scope': 'real_bounded_read_only',
            'operator_replacement_verdict': 'HOLD',
        },
        'safety': {
            'read_only_input': True,
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(safe_bundle.get(key), dict):
                safe_bundle[key].update(value)
            else:
                safe_bundle[key] = value
    safe_bundle_path = tmp_path / 'safe.bundle.json'
    safe_bundle_path.write_text(json.dumps(safe_bundle))
    return safe_bundle_path


def test_moneyflow_safe_worker_validator_accepts_complete_safe_bundle(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_safe_bundle(tmp_path)
    output_path = tmp_path / 'safe.validation.json'

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
    assert payload['input_row_count'] == 120000
    assert payload['date_count'] == 2
    assert payload['evidence_scope'] == 'bounded_worker'
    assert payload['operator_replacement_verdict'] == 'HOLD'


def test_moneyflow_safe_worker_validator_blocks_unsafe_or_tiny_bundle(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_safe_bundle(
        tmp_path,
        overrides={
            'safety': {'writes_datamart': True},
            'worker_benchmark_summary': {'sample_row_count': 10},
        },
    )
    output_path = tmp_path / 'safe.validation.json'

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
    assert 'safe_safety_writes_datamart_must_be_false' in payload['issues']
    assert 'safe_summary_sample_row_count_below_minimum' in payload['issues']


def test_moneyflow_safe_worker_validator_blocks_full_is_without_required_coverage(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_safe_bundle(tmp_path)
    output_path = tmp_path / 'safe.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
        '--min-row-count',
        '100000',
        '--evidence-scope',
        'full_is',
        '--min-date-count',
        '10',
        '--required-start',
        '20160104',
        '--required-end',
        '20250711',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['evidence_scope'] == 'full_is'
    assert 'date_count_below_minimum' in payload['issues']
    assert 'required_start_not_covered' in payload['issues']
    assert 'required_end_not_covered' in payload['issues']
