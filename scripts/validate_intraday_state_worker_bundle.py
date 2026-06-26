#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 'intraday_state_worker_bundle_v1'

FORBIDDEN_COMMAND_FRAGMENTS = [
    'aws ec2 start-instances',
    'aws ssm send-command',
    'openclaw gateway start',
    'python -m pytest',
]

REQUIRED_LOCAL_READINESS_FRAGMENTS = [
    'aws ec2 describe-instance-status',
    'aws ssm describe-instance-information',
    'scripts/validate_moneyflow_slow_state_worker_instance_readiness.py',
]

REQUIRED_BY_DATASET = {
    'intraday_ema_slow_state_v1': [
        'scripts/build_intraday_ema_slow_state.py',
        '--input-root',
        '--is-end-date',
        'scripts/validate_intraday_ema_slow_state.py',
        'scripts/run_data_api_read_smoke.py',
        '--frequency intraday_cutoff',
    ],
    'intraday_terminal_corr_state_v1': [
        'scripts/build_intraday_terminal_corr_state.py',
        '--minute-root',
        '--research-window IS',
        '--skip-existing',
        '--max-dates',
        '--manifest-output',
        'scripts/validate_intraday_terminal_corr_state.py',
        'scripts/run_data_api_read_smoke.py',
        '--frequency intraday_cutoff',
    ],
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a plan-only intraday state worker bundle.')
    parser.add_argument('--bundle-path', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _flag_false(payload: dict[str, Any], field: str, issues: list[str], *, prefix: str) -> None:
    if payload.get(field) is not False:
        issues.append(f'{prefix}_{field}_must_be_false')


def validate_payload(payload: dict[str, Any], *, bundle_path: Path) -> dict[str, Any]:
    issues: list[str] = []
    dataset_id = str(payload.get('dataset_id') or '')
    if payload.get('verdict') != 'ACCEPT':
        issues.append('bundle_verdict_not_accept')
    if payload.get('schema_version') != SCHEMA_VERSION:
        issues.append('schema_version_invalid')
    if dataset_id not in REQUIRED_BY_DATASET:
        issues.append('dataset_id_invalid')
    if not payload.get('instance_id'):
        issues.append('instance_id_missing')
    if not payload.get('repo'):
        issues.append('repo_missing')
    if not payload.get('input_root'):
        issues.append('input_root_missing')
    if not payload.get('output_root'):
        issues.append('output_root_missing')
    if not payload.get('start') or not payload.get('end'):
        issues.append('date_window_missing')
    if int(payload.get('min_row_count') or 0) <= 0:
        issues.append('min_row_count_must_be_positive')
    if int(payload.get('min_date_count') or 0) <= 0:
        issues.append('min_date_count_must_be_positive')
    if int(payload.get('max_dates') or 0) <= 0:
        issues.append('max_dates_must_be_positive')

    full_window = payload.get('full_window_contract') or {}
    if full_window.get('research_window') != 'IS':
        issues.append('full_window_contract_research_window_must_be_is')
    if full_window.get('no_future_intraday_minutes') is not True:
        issues.append('full_window_contract_no_future_intraday_minutes_must_be_true')
    if full_window.get('cutoff_rule') != 'trade_time <= cutoff_time':
        issues.append('full_window_contract_cutoff_rule_invalid')
    if not full_window.get('unique_key'):
        issues.append('full_window_contract_unique_key_missing')

    local_commands = payload.get('local_readiness_commands') or []
    worker_commands = payload.get('worker_commands') or []
    if not isinstance(local_commands, list) or not local_commands:
        issues.append('local_readiness_commands_missing')
        local_commands = []
    if not isinstance(worker_commands, list) or not worker_commands:
        issues.append('worker_commands_missing')
        worker_commands = []
    local_text = '\n'.join(str(item) for item in local_commands)
    worker_text = '\n'.join(str(item) for item in worker_commands)
    for fragment in REQUIRED_LOCAL_READINESS_FRAGMENTS:
        if fragment not in local_text:
            issues.append(f'local_readiness_command_missing_required_fragment:{fragment}')
    for fragment in REQUIRED_BY_DATASET.get(dataset_id, []):
        if fragment not in worker_text:
            issues.append(f'worker_command_missing_required_fragment:{fragment}')
    for fragment in FORBIDDEN_COMMAND_FRAGMENTS:
        if fragment in local_text:
            issues.append(f'local_readiness_command_contains_forbidden_remote_execution:{fragment}')
        if fragment in worker_text:
            issues.append(f'worker_command_contains_forbidden_remote_execution:{fragment}')

    policy = payload.get('execution_policy') or {}
    for field in [
        'plan_only',
        'requires_explicit_worker_start',
        'requires_explicit_command_dispatch',
        'requires_reviewer_accept_before_catalog_registration',
        'requires_separate_active_catalog_registration',
    ]:
        if policy.get(field) is not True:
            issues.append(f'execution_policy_{field}_must_be_true')

    safety = payload.get('safety') or {}
    for field in [
        'starts_instance',
        'sends_ssm_command',
        'runs_worker_command',
        'writes_active_catalog',
        'writes_factorforge_artifacts',
        'production_loop_side_effect',
    ]:
        _flag_false(safety, field, issues, prefix='safety')

    for field in [
        'batch1_qa_path',
        'batch1_manifest_path',
        'batch2_qa_path',
        'batch2_manifest_path',
        'catalog_path',
        'validation_path',
        'read_smoke_path',
        'worker_instance_readiness_path',
    ]:
        if not payload.get(field):
            issues.append(f'{field}_missing')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'bundle_path': str(bundle_path),
        'dataset_id': dataset_id,
        'instance_id': payload.get('instance_id'),
        'start': payload.get('start'),
        'end': payload.get('end'),
        'input_dataset': payload.get('input_dataset'),
        'min_row_count': payload.get('min_row_count'),
        'min_date_count': payload.get('min_date_count'),
        'max_dates': payload.get('max_dates'),
        'worker_command_count': len(worker_commands),
        'local_readiness_command_count': len(local_commands),
        'required_worker_fragments': REQUIRED_BY_DATASET.get(dataset_id, []),
        'required_local_readiness_fragments': REQUIRED_LOCAL_READINESS_FRAGMENTS,
        'forbidden_command_fragments': FORBIDDEN_COMMAND_FRAGMENTS,
        'resume_limitations': payload.get('resume_limitations') or {},
        'safety': {
            'starts_instance': safety.get('starts_instance'),
            'sends_ssm_command': safety.get('sends_ssm_command'),
            'runs_worker_command': safety.get('runs_worker_command'),
            'writes_active_catalog': safety.get('writes_active_catalog'),
            'writes_factorforge_artifacts': safety.get('writes_factorforge_artifacts'),
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
    print(json.dumps({'verdict': result['verdict'], 'issues': result['issues'], 'output_path': str(output_path)}, ensure_ascii=False))
    return 0 if result['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
