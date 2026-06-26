#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FORBIDDEN_COMMAND_FRAGMENTS = [
    'aws ec2 start-instances',
    'aws ssm send-command',
    'openclaw gateway start',
    'python -m pytest',
]

REQUIRED_COMMAND_FRAGMENTS = [
    'scripts/run_intraday_operator_safe_worker_benchmark.py',
    'scripts/validate_intraday_operator_worker_benchmark.py',
    'scripts/build_operator_backend_production_approval.py',
    'scripts/validate_operator_backend_production_approval.py',
    'scripts/plan_operator_backend_replacement.py',
]

REQUIRED_LOCAL_READINESS_FRAGMENTS = [
    'aws ec2 describe-instance-status',
    'aws ssm describe-instance-information',
    'scripts/validate_moneyflow_slow_state_worker_instance_readiness.py',
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a plan-only intraday operator worker resume bundle.')
    parser.add_argument('--bundle-path', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _flag_false(payload: dict[str, Any], field: str, issues: list[str], *, prefix: str) -> None:
    if payload.get(field) is not False:
        issues.append(f'{prefix}_{field}_must_be_false')


def validate_payload(payload: dict[str, Any], *, bundle_path: Path) -> dict[str, Any]:
    issues: list[str] = []
    if payload.get('verdict') != 'ACCEPT':
        issues.append('bundle_verdict_not_accept')
    if payload.get('operator_id') != 'cpv_price_volume_corr_state':
        issues.append('operator_id_not_cpv_price_volume_corr_state')
    if payload.get('evidence_scope') not in {'bounded_worker', 'production_scale', 'full_is'}:
        issues.append('evidence_scope_invalid')
    if not payload.get('default_backend'):
        issues.append('default_backend_missing')
    if not payload.get('approved_backend'):
        issues.append('approved_backend_missing')
    if not payload.get('instance_id'):
        issues.append('instance_id_missing')
    if not payload.get('repo'):
        issues.append('repo_missing')
    if not payload.get('input_root'):
        issues.append('input_root_missing')
    if payload.get('input_format') not in {'prepared_minute_bar_v1', 'raw_minute_bar'}:
        issues.append('input_format_invalid')

    commands = payload.get('worker_commands') or []
    if not isinstance(commands, list) or not commands:
        issues.append('worker_commands_missing')
        commands = []
    command_text = '\n'.join(str(item) for item in commands)
    local_commands = payload.get('local_readiness_commands') or []
    if not isinstance(local_commands, list) or not local_commands:
        issues.append('local_readiness_commands_missing')
        local_commands = []
    local_command_text = '\n'.join(str(item) for item in local_commands)

    for fragment in REQUIRED_COMMAND_FRAGMENTS:
        if fragment not in command_text:
            issues.append(f'worker_command_missing_required_fragment:{fragment}')
    for fragment in REQUIRED_LOCAL_READINESS_FRAGMENTS:
        if fragment not in local_command_text:
            issues.append(f'local_readiness_command_missing_required_fragment:{fragment}')
    for fragment in FORBIDDEN_COMMAND_FRAGMENTS:
        if fragment in command_text:
            issues.append(f'worker_command_contains_forbidden_remote_execution:{fragment}')
        if fragment in local_command_text:
            issues.append(f'local_readiness_command_contains_forbidden_remote_execution:{fragment}')

    policy = payload.get('execution_policy') or {}
    if policy.get('plan_only') is not True:
        issues.append('execution_policy_plan_only_must_be_true')
    if policy.get('requires_explicit_worker_start') is not True:
        issues.append('execution_policy_requires_explicit_worker_start_must_be_true')
    if policy.get('run_safe_worker_preflight_first') is not True:
        issues.append('execution_policy_run_safe_worker_preflight_first_must_be_true')
    if policy.get('requires_reviewer_approval_before_replacement') is not True:
        issues.append('execution_policy_requires_reviewer_approval_before_replacement_must_be_true')

    safety = payload.get('safety') or {}
    for field in [
        'starts_instance',
        'sends_ssm_command',
        'runs_benchmark',
        'writes_backend_config',
        'writes_datamart',
        'production_loop_side_effect',
    ]:
        _flag_false(safety, field, issues, prefix='safety')

    for field in [
        'profile_path',
        'validation_path',
        'bundle_path',
        'safe_worker_bundle_path',
        'safe_worker_validation_path',
        'approval_path',
        'approval_validation_path',
        'replacement_plan_path',
    ]:
        if not payload.get(field):
            issues.append(f'{field}_missing')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'bundle_path': str(bundle_path),
        'operator_id': payload.get('operator_id'),
        'instance_id': payload.get('instance_id'),
        'evidence_scope': payload.get('evidence_scope'),
        'default_backend': payload.get('default_backend'),
        'approved_backend': payload.get('approved_backend'),
        'command_count': len(commands),
        'local_readiness_command_count': len(local_commands),
        'required_command_fragments': REQUIRED_COMMAND_FRAGMENTS,
        'required_local_readiness_fragments': REQUIRED_LOCAL_READINESS_FRAGMENTS,
        'forbidden_command_fragments': FORBIDDEN_COMMAND_FRAGMENTS,
        'safety': {
            'starts_instance': safety.get('starts_instance'),
            'sends_ssm_command': safety.get('sends_ssm_command'),
            'runs_benchmark': safety.get('runs_benchmark'),
            'writes_backend_config': safety.get('writes_backend_config'),
            'writes_datamart': safety.get('writes_datamart'),
            'production_loop_side_effect': safety.get('production_loop_side_effect'),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_path = Path(args.bundle_path).expanduser()
    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    result = validate_payload(payload, bundle_path=bundle_path)
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if result['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
