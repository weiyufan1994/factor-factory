#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 'intraday_state_worker_bundle_v1'

DATASET_CONFIGS = {
    'intraday_ema_slow_state_v1': {
        'build_script': 'scripts/build_intraday_ema_slow_state.py',
        'validate_script': 'scripts/validate_intraday_ema_slow_state.py',
        'input_arg': '--input-root',
        'input_dataset': 'intraday_flow_distribution_moments_v1',
        'default_projection_fields': 'cutoff_time,lambda,ema_state,source_signal_col',
        'default_cutoff_times': '14:50:00',
        'unique_key': ['ts_code', 'trade_date', 'cutoff_time', 'lambda'],
    },
    'intraday_terminal_corr_state_v1': {
        'build_script': 'scripts/build_intraday_terminal_corr_state.py',
        'validate_script': 'scripts/validate_intraday_terminal_corr_state.py',
        'input_arg': '--minute-root',
        'input_dataset': 'minute_bar',
        'default_projection_fields': 'cutoff_time,window_id,close_amount_corr,ret_amount_corr',
        'default_cutoff_times': '10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00',
        'unique_key': ['ts_code', 'trade_date', 'cutoff_time', 'window_id'],
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _quote(value: str | int | float) -> str:
    text = str(value)
    if not text:
        return "''"
    if all(ch.isalnum() or ch in '/._:=,-' for ch in text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


def _shell_join(parts: list[str]) -> str:
    return ' '.join(_quote(part) for part in parts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a plan-only worker bundle for intraday state datamart production proof.')
    parser.add_argument('--dataset-id', choices=sorted(DATASET_CONFIGS), required=True)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--cache-root', required=True)
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--artifact-dir', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--start', default='20160104')
    parser.add_argument('--end', default='20250711')
    parser.add_argument('--cutoff-times', default='')
    parser.add_argument('--lambdas', default='0.70,0.85,0.93')
    parser.add_argument('--signal-col', default='v19d_score')
    parser.add_argument('--windows', default='20,30,60')
    parser.add_argument('--min-minutes', type=int, default=20)
    parser.add_argument('--operator-backend', default='array_grouped')
    parser.add_argument('--max-workers', type=int)
    parser.add_argument('--min-row-count', type=int, default=1000000)
    parser.add_argument('--min-date-count', type=int, default=2000)
    parser.add_argument('--max-dates', type=int, default=80)
    parser.add_argument('--max-warm-read-seconds', type=float, default=10.0)
    parser.add_argument('--smoke-date', default='20240110')
    parser.add_argument('--projection-fields', default='')
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _paths(artifact_dir: Path, label: str) -> dict[str, str]:
    return {
        'ec2_status_path': str(artifact_dir / f'{label}.worker_ec2_status.json'),
        'ssm_status_path': str(artifact_dir / f'{label}.worker_ssm_status.json'),
        'worker_instance_readiness_path': str(artifact_dir / f'{label}.worker_instance_readiness.json'),
        'batch1_qa_path': str(artifact_dir / f'{label}.batch1.qa.json'),
        'batch1_manifest_path': str(artifact_dir / f'{label}.batch1.manifest.json'),
        'batch2_qa_path': str(artifact_dir / f'{label}.batch2.qa.json'),
        'batch2_manifest_path': str(artifact_dir / f'{label}.batch2.manifest.json'),
        'catalog_path': str(artifact_dir / f'{label}.catalog.json'),
        'validation_path': str(artifact_dir / f'{label}.validation.json'),
        'read_smoke_path': str(artifact_dir / f'{label}.read_smoke.json'),
    }


def _read_smoke_command(dataset_id: str, paths: dict[str, str], smoke_date: str, projection_fields: list[str], max_warm_read_seconds: float) -> list[str]:
    return [
        'PYTHONPATH=.',
        'python3',
        'scripts/run_data_api_read_smoke.py',
        '--catalog',
        paths['catalog_path'],
        '--dataset-id',
        dataset_id,
        '--start-date',
        smoke_date,
        '--end-date',
        smoke_date,
        '--fields',
        ','.join(projection_fields),
        '--frequency',
        'intraday_cutoff',
        '--max-warm-read-seconds',
        str(float(max_warm_read_seconds)),
        '--output-path',
        paths['read_smoke_path'],
    ]


def _common_build_parts(args: argparse.Namespace, cfg: dict[str, Any], paths: dict[str, str]) -> list[str]:
    parts = [
        'PYTHONPATH=.',
        'python3',
        str(cfg['build_script']),
        str(cfg['input_arg']),
        str(args.input_root),
        '--start',
        str(args.start),
        '--end',
        str(args.end),
        '--output-root',
        str(args.output_root),
        '--catalog-output',
        paths['catalog_path'],
        '--cutoff-times',
        str(args.cutoff_times or cfg['default_cutoff_times']),
        '--operator-backend',
        str(args.operator_backend),
    ]
    if args.dataset_id == 'intraday_ema_slow_state_v1':
        parts.extend([
            '--lambdas',
            str(args.lambdas),
            '--signal-col',
            str(args.signal_col),
            '--is-end-date',
            str(args.end),
        ])
    else:
        parts.extend([
            '--windows',
            str(args.windows),
            '--min-minutes',
            str(int(args.min_minutes)),
            '--research-window',
            'IS',
            '--skip-existing',
        ])
    if args.max_workers:
        parts.extend(['--max-workers', str(int(args.max_workers))])
    return parts


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    issues: list[str] = []
    if str(args.start) > str(args.end):
        issues.append('start_after_end')
    if int(args.min_row_count) <= 0:
        issues.append('min_row_count_must_be_positive')
    if int(args.min_date_count) <= 0:
        issues.append('min_date_count_must_be_positive')
    if int(args.max_dates) <= 0:
        issues.append('max_dates_must_be_positive')
    cfg = DATASET_CONFIGS[str(args.dataset_id)]
    artifact_dir = Path(args.artifact_dir)
    paths = _paths(artifact_dir, str(args.label))
    projection_fields = [
        item.strip()
        for item in str(args.projection_fields or cfg['default_projection_fields']).split(',')
        if item.strip()
    ]

    local_readiness_commands: list[str] = []
    worker_commands: list[str] = []
    if not issues:
        local_readiness_commands = [
            _shell_join([
                'aws',
                'ec2',
                'describe-instance-status',
                '--instance-ids',
                str(args.instance_id),
                '--include-all-instances',
                '--query',
                'InstanceStatuses[0].{InstanceId:InstanceId,State:InstanceState.Name,SystemStatus:SystemStatus.Status,InstanceStatus:InstanceStatus.Status}',
                '--output',
                'json',
            ]) + f' > {_quote(paths["ec2_status_path"])}',
            _shell_join([
                'aws',
                'ssm',
                'describe-instance-information',
                '--filters',
                f'Key=InstanceIds,Values={args.instance_id}',
                '--query',
                'InstanceInformationList[0].{InstanceId:InstanceId,PingStatus:PingStatus,PlatformName:PlatformName,AgentVersion:AgentVersion,LastPingDateTime:LastPingDateTime}',
                '--output',
                'json',
            ]) + f' > {_quote(paths["ssm_status_path"])}',
            _shell_join([
                'PYTHONPATH=.',
                'python3',
                'scripts/validate_moneyflow_slow_state_worker_instance_readiness.py',
                '--instance-id',
                str(args.instance_id),
                '--ec2-status-path',
                paths['ec2_status_path'],
                '--ssm-status-path',
                paths['ssm_status_path'],
                '--output-path',
                paths['worker_instance_readiness_path'],
            ]),
        ]
        common = _common_build_parts(args, cfg, paths)
        if args.dataset_id == 'intraday_ema_slow_state_v1':
            batch1 = [
                *common,
                '--qa-output',
                paths['batch1_qa_path'],
                '--manifest-output',
                paths['batch1_manifest_path'],
                '--overwrite',
            ]
            batch2 = [
                *common,
                '--qa-output',
                paths['batch2_qa_path'],
                '--manifest-output',
                paths['batch2_manifest_path'],
                '--overwrite',
            ]
        else:
            batch1 = [
                *common,
                '--qa-output',
                paths['batch1_qa_path'],
                '--manifest-output',
                paths['batch1_manifest_path'],
                '--max-dates',
                str(int(args.max_dates)),
            ]
            batch2 = [
                *common,
                '--qa-output',
                paths['batch2_qa_path'],
                '--manifest-output',
                paths['batch2_manifest_path'],
            ]
        validation = [
            'PYTHONPATH=.',
            'python3',
            str(cfg['validate_script']),
            '--feature-parquet',
            str(args.output_root),
            '--qa-path',
            paths['batch2_qa_path'],
            '--min-row-count',
            str(int(args.min_row_count)),
            '--max-warm-read-seconds',
            str(float(args.max_warm_read_seconds)),
            '--output-path',
            paths['validation_path'],
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(batch1)}')
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(batch2)}')
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(validation)}')
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(_read_smoke_command(str(args.dataset_id), paths, str(args.smoke_date), projection_fields, float(args.max_warm_read_seconds)))}')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'schema_version': SCHEMA_VERSION,
        'dataset_id': str(args.dataset_id),
        'instance_id': str(args.instance_id),
        'repo': str(args.repo),
        'cache_root': str(args.cache_root),
        'input_root': str(args.input_root),
        'input_dataset': str(cfg['input_dataset']),
        'output_root': str(args.output_root),
        'artifact_dir': str(args.artifact_dir),
        'label': str(args.label),
        'start': str(args.start),
        'end': str(args.end),
        'cutoff_times': [item.strip() for item in str(args.cutoff_times or cfg['default_cutoff_times']).split(',') if item.strip()],
        'operator_backend': str(args.operator_backend),
        'min_row_count': int(args.min_row_count),
        'min_date_count': int(args.min_date_count),
        'max_dates': int(args.max_dates),
        'smoke_date': str(args.smoke_date),
        'projection_fields': projection_fields,
        'max_warm_read_seconds': float(args.max_warm_read_seconds),
        'full_window_contract': {
            'research_window': 'IS',
            'required_start': str(args.start),
            'required_end': str(args.end),
            'no_future_intraday_minutes': True,
            'cutoff_rule': 'trade_time <= cutoff_time',
            'unique_key': list(cfg['unique_key']),
            'required_duplicate_key_count': 0,
        },
        'resume_limitations': {
            'resumable_shard_backfill_available': args.dataset_id != 'intraday_ema_slow_state_v1',
            'current_builder_mode': 'date_partition_skip_existing_with_max_dates' if args.dataset_id != 'intraday_ema_slow_state_v1' else 'stateful_full_window_rebuild_required_for_continuity',
            'next_required_engineering_step': 'run worker build/validate/read-smoke, then review final QA/catalog before active catalog registration',
        },
        **paths,
        'local_readiness_commands': local_readiness_commands,
        'worker_commands': worker_commands,
        'execution_policy': {
            'plan_only': True,
            'requires_explicit_worker_start': True,
            'requires_explicit_command_dispatch': True,
            'requires_reviewer_accept_before_catalog_registration': True,
            'requires_separate_active_catalog_registration': True,
        },
        'safety': {
            'starts_instance': False,
            'sends_ssm_command': False,
            'runs_worker_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
        'generated_at_utc': utc_now(),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_bundle(args)
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': payload['verdict'], 'output_path': str(output_path), 'dataset_id': payload['dataset_id']}, ensure_ascii=False))
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
