from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_builder_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_intraday_operator_worker_resume_bundle.py'
    spec = importlib.util.spec_from_file_location('build_intraday_operator_worker_resume_bundle', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_intraday_operator_worker_resume_bundle.py'
    spec = importlib.util.spec_from_file_location('validate_intraday_operator_worker_resume_bundle', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_intraday_operator_worker_resume_bundle_accepts_cpv_terminal_plan(tmp_path):
    builder = _load_builder_module()
    validator = _load_validator_module()
    bundle_path = tmp_path / 'cpv.resume_bundle.json'
    validation_path = tmp_path / 'cpv.resume_bundle.validation.json'

    exit_code = builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--cache-root',
        '/home/ubuntu/factorforge_data_api_cache',
        '--input-root',
        '/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar',
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        '/tmp/intraday_operator_worker_benchmark',
        '--label',
        'real_bounded_cpv_terminal',
        '--start',
        '20240110',
        '--end',
        '20240110',
        '--row-limit',
        '500000',
        '--window',
        '20',
        '--min-row-count',
        '100000',
        '--max-workers',
        '8',
        '--evidence-scope',
        'bounded_worker',
        '--cpv-terminal-only',
        '--include-terminal-rolling-corr',
        '--include-process-sharded-array-grouped',
        '--output-path',
        str(bundle_path),
    ])
    validate_exit = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(validation_path),
    ])

    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    assert exit_code == 0
    assert validate_exit == 0
    assert validation['verdict'] == 'ACCEPT'
    assert payload['operator_id'] == 'cpv_price_volume_corr_state'
    assert payload['default_backend'] == 'array_grouped_terminal'
    assert payload['approved_backend'] == 'process_sharded_array_grouped_terminal'
    assert '--evidence-scope bounded_worker' in command_text
    assert '--cpv-terminal-only' in command_text
    assert 'scripts/run_intraday_operator_safe_worker_benchmark.py' in command_text
    assert 'scripts/validate_intraday_operator_worker_benchmark.py' in command_text
    assert 'scripts/build_operator_backend_production_approval.py' in command_text
    assert 'aws ec2 start-instances' not in command_text
    assert 'aws ssm send-command' not in command_text
    assert payload['safety']['starts_instance'] is False
    assert payload['safety']['runs_benchmark'] is False


def test_intraday_operator_worker_resume_bundle_validator_blocks_remote_execution(tmp_path):
    builder = _load_builder_module()
    validator = _load_validator_module()
    bundle_path = tmp_path / 'cpv.resume_bundle.json'
    validation_path = tmp_path / 'cpv.resume_bundle.validation.json'

    builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/repo',
        '--cache-root',
        '/cache',
        '--input-root',
        '/input',
        '--input-format',
        'raw_minute_bar',
        '--output-dir',
        '/tmp/out',
        '--label',
        'real_bounded_cpv_terminal',
        '--dates',
        '20240110',
        '--output-path',
        str(bundle_path),
    ])
    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    payload['worker_commands'].append('aws ssm send-command --document-name AWS-RunShellScript')
    payload['safety']['runs_benchmark'] = True
    bundle_path.write_text(json.dumps(payload), encoding='utf-8')

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(validation_path),
    ])

    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert validation['verdict'] == 'BLOCK'
    assert 'worker_command_contains_forbidden_remote_execution:aws ssm send-command' in validation['issues']
    assert 'safety_runs_benchmark_must_be_false' in validation['issues']
