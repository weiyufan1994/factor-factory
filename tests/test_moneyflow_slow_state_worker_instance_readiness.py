from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_moneyflow_slow_state_worker_instance_readiness.py'
    spec = importlib.util.spec_from_file_location('validate_moneyflow_slow_state_worker_instance_readiness', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def test_worker_instance_readiness_accepts_running_and_ssm_online(tmp_path):
    validator = _load_validator_module()
    ec2_path = _write_json(tmp_path / 'ec2.json', {
        'InstanceId': 'i-02cc0b6e93856fbb4',
        'State': 'running',
        'SystemStatus': 'ok',
        'InstanceStatus': 'ok',
    })
    ssm_path = _write_json(tmp_path / 'ssm.json', {
        'InstanceId': 'i-02cc0b6e93856fbb4',
        'PingStatus': 'Online',
    })
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--ec2-status-path',
        str(ec2_path),
        '--ssm-status-path',
        str(ssm_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['instance_state'] == 'running'
    assert payload['ssm_ping_status'] == 'Online'
    assert payload['safety']['starts_instance'] is False
    assert payload['safety']['sends_ssm_command'] is False


def test_worker_instance_readiness_blocks_stopped_or_ssm_offline(tmp_path):
    validator = _load_validator_module()
    ec2_path = _write_json(tmp_path / 'ec2.json', {
        'InstanceId': 'i-02cc0b6e93856fbb4',
        'State': 'stopped',
        'SystemStatus': 'not-applicable',
        'InstanceStatus': 'not-applicable',
    })
    ssm_path = _write_json(tmp_path / 'ssm.json', None)
    output_path = tmp_path / 'readiness.json'

    exit_code = validator.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--ec2-status-path',
        str(ec2_path),
        '--ssm-status-path',
        str(ssm_path),
        '--output-path',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'instance_state_not_running:stopped' in payload['issues']
    assert 'ssm_ping_status_not_online:missing' in payload['issues']
    assert payload['ready_for_ssm_safe_benchmark'] is False
