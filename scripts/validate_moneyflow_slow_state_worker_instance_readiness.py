#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Validate whether the true worker instance is ready for read-only safe benchmark dispatch.'
    )
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--ec2-status-path')
    parser.add_argument('--ssm-status-path')
    parser.add_argument('--instance-state')
    parser.add_argument('--system-status')
    parser.add_argument('--instance-status')
    parser.add_argument('--ssm-ping-status')
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return None
    payload = json.loads(candidate.read_text(encoding='utf-8'))
    return payload if isinstance(payload, dict) else None


def _pick(*values: Any, default: str = '') -> str:
    for value in values:
        if value not in {None, ''}:
            return str(value)
    return default


def validate_payload(
    *,
    instance_id: str,
    ec2_status: dict[str, Any] | None,
    ssm_status: dict[str, Any] | None,
    instance_state: str | None,
    system_status: str | None,
    instance_status: str | None,
    ssm_ping_status: str | None,
) -> dict[str, Any]:
    ec2_status = ec2_status or {}
    ssm_status = ssm_status or {}
    observed_instance_id = _pick(ec2_status.get('InstanceId'), ssm_status.get('InstanceId'), instance_id)
    state = _pick(instance_state, ec2_status.get('State'), default='missing')
    system = _pick(system_status, ec2_status.get('SystemStatus'), default='missing')
    inst_status = _pick(instance_status, ec2_status.get('InstanceStatus'), default='missing')
    ping = _pick(ssm_ping_status, ssm_status.get('PingStatus'), default='missing')

    issues: list[str] = []
    if observed_instance_id != instance_id:
        issues.append(f'instance_id_mismatch:{observed_instance_id}')
    if state != 'running':
        issues.append(f'instance_state_not_running:{state}')
    if system not in {'ok', 'initializing'}:
        issues.append(f'system_status_not_ok_or_initializing:{system}')
    if inst_status not in {'ok', 'initializing'}:
        issues.append(f'instance_status_not_ok_or_initializing:{inst_status}')
    if ping != 'Online':
        issues.append(f'ssm_ping_status_not_online:{ping}')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'instance_id': instance_id,
        'observed_instance_id': observed_instance_id,
        'instance_state': state,
        'system_status': system,
        'instance_status': inst_status,
        'ssm_ping_status': ping,
        'ready_for_ssm_safe_benchmark': not issues,
        'safety': {
            'starts_instance': False,
            'sends_ssm_command': False,
            'runs_benchmark': False,
            'writes_datamart': False,
            'writes_backend_config': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = validate_payload(
        instance_id=str(args.instance_id),
        ec2_status=_load_json(args.ec2_status_path),
        ssm_status=_load_json(args.ssm_status_path),
        instance_state=args.instance_state,
        system_status=args.system_status,
        instance_status=args.instance_status,
        ssm_ping_status=args.ssm_ping_status,
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
