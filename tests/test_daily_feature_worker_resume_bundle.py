from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_builder_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'build_daily_feature_worker_resume_bundle.py'
    spec = importlib.util.spec_from_file_location('build_daily_feature_worker_resume_bundle', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_daily_feature_worker_resume_bundle.py'
    spec = importlib.util.spec_from_file_location('validate_daily_feature_worker_resume_bundle', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_feature_worker_resume_bundle_accepts_daily_technical_plan(tmp_path):
    builder = _load_builder_module()
    validator = _load_validator_module()
    bundle_path = tmp_path / 'daily_technical.resume_bundle.json'
    validation_path = tmp_path / 'daily_technical.resume_bundle.validation.json'

    exit_code = builder.main([
        '--dataset-id', 'daily_technical_state_v1',
        '--instance-id', 'i-02cc0b6e93856fbb4',
        '--repo', '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--input-parquet', '/home/ubuntu/factorforge_data_api_cache/data/clean/daily_clean.parquet',
        '--output-root', '/home/ubuntu/factorforge_data_api_cache/datamarts/daily_technical_state_v1',
        '--artifact-dir', '/tmp/daily_feature_worker',
        '--label', 'daily_technical_state_full_is',
        '--start', '20160104',
        '--end', '20250711',
        '--max-dates', '80',
        '--min-row-count', '1000000',
        '--smoke-date', '20240110',
        '--output-path', str(bundle_path),
    ])
    validate_exit = validator.main([
        '--bundle-path', str(bundle_path),
        '--output-path', str(validation_path),
    ])

    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    assert exit_code == 0
    assert validate_exit == 0
    assert validation['verdict'] == 'ACCEPT'
    assert payload['dataset_id'] == 'daily_technical_state_v1'
    assert 'scripts/build_daily_technical_state.py' in command_text
    assert 'scripts/validate_daily_technical_state.py' in command_text
    assert '--skip-existing' in command_text
    assert '--allow-partial-source-qa' in command_text
    assert 'scripts/run_data_api_read_smoke.py' in command_text
    assert 'open("/tmp/daily_feature_worker/daily_technical_state_full_is.validation.json")' in command_text
    assert 'Path("/tmp/daily_feature_worker/daily_technical_state_full_is.catalog.json")' in command_text
    assert 'dataset_id="daily_technical_state_v1"' in command_text
    assert 'scripts/closeout_daily_technical_state.py' in command_text
    assert 'aws ssm send-command' not in command_text
    assert payload['safety']['starts_instance'] is False
    assert payload['safety']['writes_active_catalog'] is False


def test_daily_feature_worker_resume_bundle_accepts_alpha360_plan(tmp_path):
    builder = _load_builder_module()
    validator = _load_validator_module()
    bundle_path = tmp_path / 'alpha360.resume_bundle.json'
    validation_path = tmp_path / 'alpha360.resume_bundle.validation.json'

    assert builder.main([
        '--dataset-id', 'daily_alpha360_lite_v1',
        '--instance-id', 'i-02cc0b6e93856fbb4',
        '--repo', '/repo',
        '--input-parquet', '/data/daily_clean.parquet',
        '--output-root', '/data/daily_alpha360_lite_v1',
        '--artifact-dir', '/tmp/daily_feature_worker',
        '--label', 'daily_alpha360_lite_full_is',
        '--start', '20160104',
        '--end', '20250711',
        '--max-dates', '20',
        '--min-row-count', '1000000',
        '--lookback', '60',
        '--output-path', str(bundle_path),
    ]) == 0
    assert validator.main([
        '--bundle-path', str(bundle_path),
        '--output-path', str(validation_path),
    ]) == 0

    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    assert validation['verdict'] == 'ACCEPT'
    assert payload['projection_fields'] == ['CLOSE0', 'CLOSE59', 'VOLUME1']
    assert 'scripts/build_daily_alpha360_lite.py' in command_text
    assert 'scripts/validate_daily_alpha360_lite.py' in command_text
    assert 'scripts/run_data_api_read_smoke.py' in command_text
    assert '--lookback 60' in command_text


def test_daily_feature_worker_resume_bundle_validator_blocks_remote_execution(tmp_path):
    builder = _load_builder_module()
    validator = _load_validator_module()
    bundle_path = tmp_path / 'daily_technical.resume_bundle.json'
    validation_path = tmp_path / 'daily_technical.resume_bundle.validation.json'

    builder.main([
        '--dataset-id', 'daily_technical_state_v1',
        '--instance-id', 'i-02cc0b6e93856fbb4',
        '--repo', '/repo',
        '--input-parquet', '/data/daily_clean.parquet',
        '--output-root', '/data/daily_technical_state_v1',
        '--artifact-dir', '/tmp/daily_feature_worker',
        '--label', 'daily_technical_state_full_is',
        '--start', '20160104',
        '--end', '20250711',
        '--output-path', str(bundle_path),
    ])
    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    payload['worker_commands'].append('aws ssm send-command --document-name AWS-RunShellScript')
    payload['safety']['runs_worker_command'] = True
    bundle_path.write_text(json.dumps(payload), encoding='utf-8')

    exit_code = validator.main([
        '--bundle-path', str(bundle_path),
        '--output-path', str(validation_path),
    ])

    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert validation['verdict'] == 'BLOCK'
    assert 'worker_command_contains_forbidden_remote_execution:aws ssm send-command' in validation['issues']
    assert 'safety_runs_worker_command_must_be_false' in validation['issues']
