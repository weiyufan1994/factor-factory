from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_resume_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_moneyflow_slow_state_worker_resume_bundle.py'
    spec = importlib.util.spec_from_file_location('build_moneyflow_slow_state_worker_resume_bundle', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_moneyflow_worker_resume_bundle_is_plan_only_and_contains_safe_commands(tmp_path):
    resume = _load_resume_module()
    output_path = tmp_path / 'resume.bundle.json'

    exit_code = resume.main([
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
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    local_command_text = '\n'.join(payload['local_readiness_commands'])
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['instance_id'] == 'i-02cc0b6e93856fbb4'
    assert payload['repo'] == '/home/ubuntu/.openclaw/workspace/factorforge-data-api'
    assert payload['safe_worker_bundle_path'].endswith('real_bounded_slow_state.safe_worker_benchmark.bundle.json')
    assert payload['safe_worker_validation_path'].endswith('real_bounded_slow_state.safe_worker_benchmark.validation.json')
    assert payload['approval_path'].endswith('real_bounded_slow_state.production_approval.json')
    assert payload['evidence_scope'] == 'bounded_worker'
    assert payload['default_backend'] == 'reference'
    assert payload['approved_backend'] == 'array_grouped'
    assert 'scripts/run_moneyflow_slow_state_safe_worker_benchmark.py' in command_text
    assert 'scripts/validate_moneyflow_slow_state_safe_worker_benchmark.py' in command_text
    assert 'scripts/build_operator_backend_production_approval.py' in command_text
    assert 'scripts/validate_operator_backend_production_approval.py' in command_text
    assert 'scripts/plan_operator_backend_replacement.py' in command_text
    assert '--evidence-scope bounded_worker' in command_text
    assert '--default-backend reference' in command_text
    assert '--approved-backend array_grouped' in command_text
    assert 'aws ec2 describe-instance-status' in local_command_text
    assert 'aws ssm describe-instance-information' in local_command_text
    assert 'scripts/validate_moneyflow_slow_state_worker_instance_readiness.py' in local_command_text
    assert 'aws ec2 start-instances' not in command_text
    assert 'aws ssm send-command' not in command_text
    assert 'aws ec2 start-instances' not in local_command_text
    assert 'aws ssm send-command' not in local_command_text
    assert payload['worker_instance_readiness_path'].endswith('real_bounded_slow_state.worker_instance_readiness.json')
    assert payload['safety']['starts_instance'] is False
    assert payload['safety']['sends_ssm_command'] is False
    assert payload['safety']['runs_benchmark'] is False
    assert payload['safety']['writes_backend_config'] is False


def test_moneyflow_worker_resume_bundle_full_is_commands_carry_required_coverage(tmp_path):
    resume = _load_resume_module()
    output_path = tmp_path / 'resume.bundle.json'

    exit_code = resume.main([
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
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['evidence_scope'] == 'full_is'
    assert '--evidence-scope full_is' in command_text
    assert '--min-date-count 2000' in command_text
    assert '--required-start 20160104' in command_text
    assert '--required-end 20250711' in command_text
    assert '--min-input-row-count 1000000' in command_text
    assert '--approved-by reviewer-test' in command_text
    assert '--approval-reason ' in command_text


def test_moneyflow_worker_resume_bundle_blocks_invalid_row_threshold(tmp_path):
    resume = _load_resume_module()
    output_path = tmp_path / 'resume.bundle.json'

    exit_code = resume.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/repo',
        '--cache-root',
        '/cache',
        '--input-root',
        '/input',
        '--output-dir',
        '/tmp/out',
        '--label',
        'real_bounded_slow_state',
        '--min-row-count',
        '0',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'min_row_count_must_be_positive' in payload['issues']
    assert payload['worker_commands'] == []
    assert payload['local_readiness_commands'] == []
