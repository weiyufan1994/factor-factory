from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = REPO_ROOT / 'scripts' / name
    spec = importlib.util.spec_from_file_location(name.removesuffix('.py'), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flow_distribution_worker_bundle_is_plan_only_and_full_is(tmp_path: Path):
    builder = _load_script('build_intraday_flow_distribution_worker_bundle.py')
    output_path = tmp_path / 'bundle.json'

    exit_code = builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--cache-root',
        '/home/ubuntu/factorforge_data_api_cache',
        '--prepared-minute-root',
        '/home/ubuntu/factorforge_data_api_cache/datamarts/prepared_minute_bar_v1',
        '--output-root',
        '/home/ubuntu/factorforge_data_api_cache/datamarts/intraday_flow_distribution_moments_v1_is',
        '--artifact-dir',
        '/home/ubuntu/factorforge_data_api_cache/proofs/intraday_flow_distribution_moments_v1',
        '--label',
        'full_is_flow_distribution',
        '--start',
        '20160104',
        '--end',
        '20250711',
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    local_command_text = '\n'.join(payload['local_readiness_commands'])
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['dataset_id'] == 'intraday_flow_distribution_moments_v1'
    assert payload['input_dataset'] == 'prepared_minute_bar_v1'
    assert payload['operator_backend'] == 'vectorized'
    assert payload['start'] == '20160104'
    assert payload['end'] == '20250711'
    assert payload['full_window_contract']['no_future_intraday_minutes'] is True
    assert payload['full_window_contract']['unique_key'] == ['ts_code', 'trade_date', 'cutoff_time']
    assert payload['resume_limitations']['resumable_shard_backfill_available'] is True
    assert 'scripts/build_intraday_flow_distribution_moments.py' in command_text
    assert '--prepared-minute-root /home/ubuntu/factorforge_data_api_cache/datamarts/prepared_minute_bar_v1' in command_text
    assert '--operator-backend vectorized' in command_text
    assert '--source-ready-only' in command_text
    assert '--skip-existing' in command_text
    assert '--max-dates' in command_text
    assert '--manifest-output' in command_text
    assert '--skip-upload' in command_text
    assert 'DataApiClient.from_catalog' in command_text
    assert 'scripts/closeout_intraday_flow_distribution_moments.py' in command_text
    assert 'aws ec2 describe-instance-status' in local_command_text
    assert 'aws ssm describe-instance-information' in local_command_text
    assert 'aws ec2 start-instances' not in command_text
    assert 'aws ssm send-command' not in command_text
    assert payload['safety']['starts_instance'] is False
    assert payload['safety']['sends_ssm_command'] is False
    assert payload['safety']['runs_worker_command'] is False


def test_flow_distribution_worker_bundle_validator_accepts_safe_bundle(tmp_path: Path):
    builder = _load_script('build_intraday_flow_distribution_worker_bundle.py')
    validator = _load_script('validate_intraday_flow_distribution_worker_bundle.py')
    bundle_path = tmp_path / 'bundle.json'
    validation_path = tmp_path / 'validation.json'
    assert builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--cache-root',
        '/home/ubuntu/factorforge_data_api_cache',
        '--prepared-minute-root',
        '/cache/prepared_minute_bar_v1',
        '--output-root',
        '/cache/intraday_flow_distribution_moments_v1_is',
        '--artifact-dir',
        '/cache/proofs',
        '--output-path',
        str(bundle_path),
    ]) == 0

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(validation_path),
    ])

    result = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert result['verdict'] == 'ACCEPT'
    assert result['issues'] == []
    assert result['resume_limitations']['resumable_shard_backfill_available'] is True


def test_flow_distribution_worker_bundle_validator_blocks_remote_dispatch(tmp_path: Path):
    builder = _load_script('build_intraday_flow_distribution_worker_bundle.py')
    validator = _load_script('validate_intraday_flow_distribution_worker_bundle.py')
    bundle_path = tmp_path / 'bundle.json'
    validation_path = tmp_path / 'validation.json'
    assert builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/repo',
        '--cache-root',
        '/cache',
        '--prepared-minute-root',
        '/cache/prepared',
        '--output-root',
        '/cache/out',
        '--artifact-dir',
        '/cache/proofs',
        '--output-path',
        str(bundle_path),
    ]) == 0
    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    payload['worker_commands'].append('aws ssm send-command --document-name AWS-RunShellScript')
    bundle_path.write_text(json.dumps(payload), encoding='utf-8')

    exit_code = validator.main([
        '--bundle-path',
        str(bundle_path),
        '--output-path',
        str(validation_path),
    ])

    result = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert result['verdict'] == 'BLOCK'
    assert any('aws ssm send-command' in issue for issue in result['issues'])
