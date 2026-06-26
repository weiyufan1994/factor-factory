#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DATASET_ID = 'intraday_flow_distribution_moments_v1'
SCHEMA_VERSION = 'intraday_flow_distribution_worker_bundle_v1'

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

REQUIRED_WORKER_FRAGMENTS = [
    'scripts/build_intraday_flow_distribution_moments.py',
    '--prepared-minute-root',
    '--source-ready-only',
    '--operator-backend vectorized',
    '--research-window IS',
    '--skip-upload',
    '--skip-existing',
    '--max-dates',
    '--manifest-output',
    'DataApiClient.from_catalog',
    'scripts/closeout_intraday_flow_distribution_moments.py',
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a plan-only intraday_flow_distribution_moments_v1 worker bundle.')
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
    if payload.get('schema_version') != SCHEMA_VERSION:
        issues.append('schema_version_invalid')
    if payload.get('dataset_id') != DATASET_ID:
        issues.append('dataset_id_invalid')
    if payload.get('input_dataset') != 'prepared_minute_bar_v1':
        issues.append('input_dataset_must_be_prepared_minute_bar_v1')
    if payload.get('threshold_source') != 'prior_dates':
        issues.append('threshold_source_must_be_prior_dates')
    if payload.get('operator_backend') != 'vectorized':
        issues.append('operator_backend_must_be_vectorized')
    if not payload.get('instance_id'):
        issues.append('instance_id_missing')
    if not payload.get('repo'):
        issues.append('repo_missing')
    if not payload.get('prepared_minute_root'):
        issues.append('prepared_minute_root_missing')
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
    if full_window.get('unique_key') != ['ts_code', 'trade_date', 'cutoff_time']:
        issues.append('full_window_contract_unique_key_invalid')

    resume = payload.get('resume_limitations') or {}
    if resume.get('resumable_shard_backfill_available') is not True:
        issues.append('resume_limitations_must_state_resumable_available')

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
    for fragment in REQUIRED_WORKER_FRAGMENTS:
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
        'qa_path',
        'batch1_qa_path',
        'batch1_manifest_path',
        'batch2_qa_path',
        'batch2_manifest_path',
        'catalog_path',
        'read_smoke_path',
        'closeout_path',
        'worker_instance_readiness_path',
    ]:
        if not payload.get(field):
            issues.append(f'{field}_missing')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'bundle_path': str(bundle_path),
        'dataset_id': payload.get('dataset_id'),
        'instance_id': payload.get('instance_id'),
        'start': payload.get('start'),
        'end': payload.get('end'),
        'operator_backend': payload.get('operator_backend'),
        'input_dataset': payload.get('input_dataset'),
        'min_row_count': payload.get('min_row_count'),
        'min_date_count': payload.get('min_date_count'),
        'max_dates': payload.get('max_dates'),
        'worker_command_count': len(worker_commands),
        'local_readiness_command_count': len(local_commands),
        'required_worker_fragments': REQUIRED_WORKER_FRAGMENTS,
        'required_local_readiness_fragments': REQUIRED_LOCAL_READINESS_FRAGMENTS,
        'forbidden_command_fragments': FORBIDDEN_COMMAND_FRAGMENTS,
        'resume_limitations': resume,
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
    print(json.dumps({'verdict': result['verdict'], 'issues': result['issues'], 'output_path': str(output_path)}, ensure_ascii=False, indent=2))
    return 0 if result['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
