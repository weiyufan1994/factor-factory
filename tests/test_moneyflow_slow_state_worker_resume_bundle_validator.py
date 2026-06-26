from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_builder_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_moneyflow_slow_state_worker_resume_bundle.py'
    spec = importlib.util.spec_from_file_location('build_moneyflow_slow_state_worker_resume_bundle', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_moneyflow_slow_state_worker_resume_bundle.py'
    spec = importlib.util.spec_from_file_location('validate_moneyflow_slow_state_worker_resume_bundle', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_resume_bundle(tmp_path: Path, *, mutate: bool = False) -> Path:
    builder = _load_builder_module()
    bundle_path = tmp_path / 'resume.bundle.json'
    builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--cache-root',
        '/home/ubuntu/factorforge_data_api_cache',
        '--input-root',
        '/home/ubuntu/factorforge_data_api_cache/s3_parquet/intraday_flow_distribution_moments_v1',
        '--output-dir',
        '/tmp/moneyflow_slow_state_worker_benchmark',
        '--label',
        'real_bounded_slow_state',
        '--start',
        '20240110',
        '--end',
        '20240110',
        '--row-limit',
        '500000',
        '--min-row-count',
        '100000',
        '--max-workers',
        '8',
        '--output-path',
        str(bundle_path),
    ])
    if mutate:
        payload = json.loads(bundle_path.read_text(encoding='utf-8'))
        payload['worker_commands'].append('aws ec2 start-instances --instance-ids i-02cc0b6e93856fbb4')
        payload['safety']['starts_instance'] = True
        payload['execution_policy']['plan_only'] = False
        bundle_path.write_text(json.dumps(payload), encoding='utf-8')
    return bundle_path


def test_moneyflow_resume_bundle_validator_accepts_plan_only_bundle(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_resume_bundle(tmp_path)
    output_path = tmp_path / 'resume.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['command_count'] == 5
    assert payload['local_readiness_command_count'] == 3
    assert 'scripts/build_operator_backend_production_approval.py' in payload['required_command_fragments']
    assert payload['evidence_scope'] == 'bounded_worker'
    assert payload['default_backend'] == 'reference'
    assert payload['approved_backend'] == 'array_grouped'
    assert payload['safety']['starts_instance'] is False
    assert payload['safety']['runs_benchmark'] is False


def test_moneyflow_resume_bundle_validator_blocks_remote_execution_and_safety_drift(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_resume_bundle(tmp_path, mutate=True)
    output_path = tmp_path / 'resume.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'worker_command_contains_forbidden_remote_execution:aws ec2 start-instances' in payload['issues']
    assert 'execution_policy_plan_only_must_be_true' in payload['issues']
    assert 'safety_starts_instance_must_be_false' in payload['issues']


def test_moneyflow_resume_bundle_validator_blocks_forbidden_local_readiness_command(tmp_path):
    validator = _load_validator_module()
    bundle_path = _write_resume_bundle(tmp_path)
    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    payload['local_readiness_commands'].append('aws ssm send-command --instance-ids i-02cc0b6e93856fbb4')
    bundle_path.write_text(json.dumps(payload), encoding='utf-8')
    output_path = tmp_path / 'resume.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
    ])

    validation = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert validation['verdict'] == 'BLOCK'
    assert 'local_readiness_command_contains_forbidden_remote_execution:aws ssm send-command' in validation['issues']


def test_moneyflow_resume_bundle_validator_accepts_full_is_plan_only_bundle(tmp_path):
    validator = _load_validator_module()
    builder = _load_builder_module()
    bundle_path = tmp_path / 'full_is.resume.bundle.json'
    builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--cache-root',
        '/home/ubuntu/factorforge_data_api_cache',
        '--input-root',
        '/home/ubuntu/factorforge_data_api_cache/s3_parquet/intraday_flow_distribution_moments_v1',
        '--output-dir',
        '/tmp/moneyflow_slow_state_worker_benchmark',
        '--label',
        'full_is_slow_state',
        '--start',
        '20160104',
        '--end',
        '20250711',
        '--min-row-count',
        '1000000',
        '--min-date-count',
        '2000',
        '--required-start',
        '20160104',
        '--required-end',
        '20250711',
        '--evidence-scope',
        'full_is',
        '--approved-by',
        'reviewer-test',
        '--approval-reason',
        'full IS proof accepted',
        '--output-path',
        str(bundle_path),
    ])
    output_path = tmp_path / 'full_is.resume.validation.json'

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['evidence_scope'] == 'full_is'
    assert payload['command_count'] == 5
    assert payload['safety']['starts_instance'] is False
    assert payload['safety']['runs_benchmark'] is False
