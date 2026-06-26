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


def test_intraday_state_worker_bundle_accepts_ema_plan(tmp_path: Path):
    builder = _load_script('build_intraday_state_worker_bundle.py')
    validator = _load_script('validate_intraday_state_worker_bundle.py')
    bundle_path = tmp_path / 'ema.bundle.json'
    validation_path = tmp_path / 'ema.validation.json'

    assert builder.main([
        '--dataset-id', 'intraday_ema_slow_state_v1',
        '--instance-id', 'i-02cc0b6e93856fbb4',
        '--repo', '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--cache-root', '/home/ubuntu/factorforge_data_api_cache',
        '--input-root', '/home/ubuntu/factorforge_data_api_cache/datamarts/intraday_flow_distribution_moments_v1_is',
        '--output-root', '/home/ubuntu/factorforge_data_api_cache/datamarts/intraday_ema_slow_state_v1_is',
        '--artifact-dir', '/home/ubuntu/factorforge_data_api_cache/proofs/intraday_ema_slow_state_v1',
        '--label', 'intraday_ema_slow_state_v1_full_is',
        '--start', '20160104',
        '--end', '20250711',
        '--output-path', str(bundle_path),
    ]) == 0
    assert validator.main(['--bundle-path', str(bundle_path), '--output-path', str(validation_path)]) == 0

    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    assert validation['verdict'] == 'ACCEPT'
    assert payload['dataset_id'] == 'intraday_ema_slow_state_v1'
    assert payload['input_dataset'] == 'intraday_flow_distribution_moments_v1'
    assert payload['full_window_contract']['unique_key'] == ['ts_code', 'trade_date', 'cutoff_time', 'lambda']
    assert 'scripts/build_intraday_ema_slow_state.py' in command_text
    assert '--input-root /home/ubuntu/factorforge_data_api_cache/datamarts/intraday_flow_distribution_moments_v1_is' in command_text
    assert '--is-end-date 20250711' in command_text
    assert 'scripts/validate_intraday_ema_slow_state.py' in command_text
    assert 'scripts/run_data_api_read_smoke.py' in command_text
    assert 'aws ssm send-command' not in command_text
    assert payload['safety']['runs_worker_command'] is False


def test_intraday_state_worker_bundle_accepts_terminal_corr_plan(tmp_path: Path):
    builder = _load_script('build_intraday_state_worker_bundle.py')
    validator = _load_script('validate_intraday_state_worker_bundle.py')
    bundle_path = tmp_path / 'terminal.bundle.json'
    validation_path = tmp_path / 'terminal.validation.json'

    assert builder.main([
        '--dataset-id', 'intraday_terminal_corr_state_v1',
        '--instance-id', 'i-02cc0b6e93856fbb4',
        '--repo', '/repo',
        '--cache-root', '/cache',
        '--input-root', '/cache/minute_bar',
        '--output-root', '/cache/intraday_terminal_corr_state_v1_is',
        '--artifact-dir', '/cache/proofs',
        '--label', 'intraday_terminal_corr_state_v1_full_is',
        '--start', '20160104',
        '--end', '20250711',
        '--output-path', str(bundle_path),
    ]) == 0
    assert validator.main(['--bundle-path', str(bundle_path), '--output-path', str(validation_path)]) == 0

    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    assert validation['verdict'] == 'ACCEPT'
    assert payload['dataset_id'] == 'intraday_terminal_corr_state_v1'
    assert payload['input_dataset'] == 'minute_bar'
    assert payload['full_window_contract']['unique_key'] == ['ts_code', 'trade_date', 'cutoff_time', 'window_id']
    assert 'scripts/build_intraday_terminal_corr_state.py' in command_text
    assert '--minute-root /cache/minute_bar' in command_text
    assert '--skip-existing' in command_text
    assert '--max-dates' in command_text
    assert 'scripts/validate_intraday_terminal_corr_state.py' in command_text
    assert 'scripts/run_data_api_read_smoke.py' in command_text


def test_intraday_state_worker_bundle_validator_blocks_remote_dispatch(tmp_path: Path):
    builder = _load_script('build_intraday_state_worker_bundle.py')
    validator = _load_script('validate_intraday_state_worker_bundle.py')
    bundle_path = tmp_path / 'bundle.json'
    validation_path = tmp_path / 'validation.json'
    assert builder.main([
        '--dataset-id', 'intraday_terminal_corr_state_v1',
        '--instance-id', 'i-02cc0b6e93856fbb4',
        '--repo', '/repo',
        '--cache-root', '/cache',
        '--input-root', '/cache/minute',
        '--output-root', '/cache/out',
        '--artifact-dir', '/cache/proofs',
        '--label', 'terminal',
        '--output-path', str(bundle_path),
    ]) == 0
    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    payload['worker_commands'].append('aws ssm send-command --document-name AWS-RunShellScript')
    payload['safety']['runs_worker_command'] = True
    bundle_path.write_text(json.dumps(payload), encoding='utf-8')

    exit_code = validator.main(['--bundle-path', str(bundle_path), '--output-path', str(validation_path)])

    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert validation['verdict'] == 'BLOCK'
    assert any('aws ssm send-command' in issue for issue in validation['issues'])
