#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATASET_ID = 'intraday_flow_distribution_moments_v1'
SCHEMA_VERSION = 'intraday_flow_distribution_worker_bundle_v1'


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
    parser = argparse.ArgumentParser(description='Build a plan-only worker bundle for intraday_flow_distribution_moments_v1 production proof.')
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--cache-root', required=True)
    parser.add_argument('--prepared-minute-root', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--artifact-dir', required=True)
    parser.add_argument('--label', default='intraday_flow_distribution_moments_v1_full_is')
    parser.add_argument('--start', default='20160104')
    parser.add_argument('--end', default='20250711')
    parser.add_argument('--cutoff-times', default='10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00')
    parser.add_argument('--threshold-lookback-days', default='20,60')
    parser.add_argument('--threshold-quantile', type=float, default=0.75)
    parser.add_argument('--threshold-backend', choices=['pandas', 'polars'], default='pandas')
    parser.add_argument('--operator-backend', default='vectorized')
    parser.add_argument('--min-minutes', type=int, default=20)
    parser.add_argument('--min-row-count', type=int, default=1000000)
    parser.add_argument('--min-date-count', type=int, default=2000)
    parser.add_argument('--max-dates', type=int, default=80)
    parser.add_argument('--max-warm-read-seconds', type=float, default=10.0)
    parser.add_argument('--smoke-date', default='20240110')
    parser.add_argument('--projection-fields', default='ret_skew,amount_hhi,signed_flow_hhi,large_proxy_amount,small_proxy_amount')
    parser.add_argument('--skip-upload', action='store_true', default=True)
    parser.add_argument('--parquet-s3-uri', default='s3://yufan-data-lake/factorforge/datamart/intraday_flow_distribution_moments_v1/is')
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _paths(artifact_dir: Path, label: str) -> dict[str, str]:
    return {
        'ec2_status_path': str(artifact_dir / f'{label}.worker_ec2_status.json'),
        'ssm_status_path': str(artifact_dir / f'{label}.worker_ssm_status.json'),
        'worker_instance_readiness_path': str(artifact_dir / f'{label}.worker_instance_readiness.json'),
        'qa_path': str(artifact_dir / f'{label}.qa.json'),
        'batch1_qa_path': str(artifact_dir / f'{label}.batch1.qa.json'),
        'batch1_manifest_path': str(artifact_dir / f'{label}.batch1.manifest.json'),
        'batch2_qa_path': str(artifact_dir / f'{label}.batch2.qa.json'),
        'batch2_manifest_path': str(artifact_dir / f'{label}.batch2.manifest.json'),
        'catalog_path': str(artifact_dir / f'{label}.catalog.json'),
        'read_smoke_path': str(artifact_dir / f'{label}.read_smoke.json'),
        'closeout_path': str(artifact_dir / f'{label}.closeout.json'),
    }


def _read_smoke_script(paths: dict[str, str], smoke_date: str, projection_fields: list[str], max_warm_read_seconds: float) -> str:
    return (
        "python3 - <<'PY'\n"
        "import json, time\n"
        "from pathlib import Path\n"
        "from factor_factory.data_api import DataApiClient, DataQuery\n"
        f"catalog_path=Path({_quote(paths['catalog_path'])})\n"
        f"out_path=Path({_quote(paths['read_smoke_path'])})\n"
        f"dataset_id={_quote(DATASET_ID)}\n"
        f"smoke_date={_quote(smoke_date)}\n"
        f"fields={projection_fields!r}\n"
        "started=time.perf_counter()\n"
        "result=DataApiClient.from_catalog(catalog_path).fetch(DataQuery(dataset_id,smoke_date,smoke_date,'a_share_all',fields))\n"
        "warm_read_seconds=time.perf_counter()-started\n"
        f"max_warm_read_seconds={float(max_warm_read_seconds)!r}\n"
        "payload={'verdict':'ACCEPT' if result.status=='ready' and result.coverage.row_count>0 and result.coverage.duplicate_key_count==0 and warm_read_seconds<=max_warm_read_seconds else 'BLOCK','status':result.status,'blocked_reason':result.blocked_reason,'warm_read_seconds':warm_read_seconds,'max_warm_read_seconds':max_warm_read_seconds,'row_count':result.coverage.row_count,'date_count':result.coverage.date_count,'ticker_count':result.coverage.ticker_count,'duplicate_key_count':result.coverage.duplicate_key_count,'columns':list(result.frame.columns),'catalog_path':str(catalog_path),'smoke_date':smoke_date,'projection_fields':fields}\n"
        "out_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\\n', encoding='utf-8')\n"
        "raise SystemExit(0 if payload['verdict']=='ACCEPT' else 2)\n"
        "PY"
    )


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    issues: list[str] = []
    if str(args.start) > str(args.end):
        issues.append('start_after_end')
    if int(args.min_minutes) <= 0:
        issues.append('min_minutes_must_be_positive')
    if int(args.min_row_count) <= 0:
        issues.append('min_row_count_must_be_positive')
    if int(args.min_date_count) <= 0:
        issues.append('min_date_count_must_be_positive')
    if int(args.max_dates) <= 0:
        issues.append('max_dates_must_be_positive')

    artifact_dir = Path(args.artifact_dir)
    paths = _paths(artifact_dir, str(args.label))
    projection_fields = [item.strip() for item in str(args.projection_fields).split(',') if item.strip()]

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

        common_build_parts = [
            'PYTHONPATH=.',
            'python3',
            'scripts/build_intraday_flow_distribution_moments.py',
            '--prepared-minute-root',
            str(args.prepared_minute_root),
            '--source-ready-only',
            '--start',
            str(args.start),
            '--end',
            str(args.end),
            '--output-root',
            str(args.output_root),
            '--catalog-output',
            paths['catalog_path'],
            '--cutoff-times',
            str(args.cutoff_times),
            '--threshold-lookback-days',
            str(args.threshold_lookback_days),
            '--threshold-quantile',
            str(float(args.threshold_quantile)),
            '--threshold-backend',
            str(args.threshold_backend),
            '--operator-backend',
            str(args.operator_backend),
            '--min-minutes',
            str(int(args.min_minutes)),
            '--research-window',
            'IS',
            '--skip-existing',
        ]
        if args.skip_upload:
            common_build_parts.append('--skip-upload')
        else:
            common_build_parts.extend(['--parquet-s3-uri', str(args.parquet_s3_uri)])
        batch1_parts = [
            *common_build_parts,
            '--qa-output',
            paths['batch1_qa_path'],
            '--manifest-output',
            paths['batch1_manifest_path'],
            '--max-dates',
            str(int(args.max_dates)),
        ]
        batch2_parts = [
            *common_build_parts,
            '--qa-output',
            paths['batch2_qa_path'],
            '--manifest-output',
            paths['batch2_manifest_path'],
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(batch1_parts)}')
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(batch2_parts)}')

        smoke_script = _read_smoke_script(paths, str(args.smoke_date), projection_fields, float(args.max_warm_read_seconds))
        worker_commands.append(f'cd {_quote(str(args.repo))} && PYTHONPATH=. {smoke_script}')

        closeout_parts = [
            'PYTHONPATH=.',
            'python3',
            'scripts/closeout_intraday_flow_distribution_moments.py',
            '--qa-path',
            paths['batch2_qa_path'],
            '--catalog-path',
            paths['catalog_path'],
            '--read-smoke-path',
            paths['read_smoke_path'],
            '--batch1-manifest-path',
            paths['batch1_manifest_path'],
            '--batch2-manifest-path',
            paths['batch2_manifest_path'],
            '--instance-id',
            str(args.instance_id),
            '--worker-command',
            'build_intraday_flow_distribution_moments.py resume batch1+batch2',
            '--required-start',
            str(args.start),
            '--required-end',
            str(args.end),
            '--min-row-count',
            str(int(args.min_row_count)),
            '--min-date-count',
            str(int(args.min_date_count)),
            '--output-path',
            paths['closeout_path'],
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(closeout_parts)}')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'schema_version': SCHEMA_VERSION,
        'dataset_id': DATASET_ID,
        'instance_id': str(args.instance_id),
        'repo': str(args.repo),
        'cache_root': str(args.cache_root),
        'prepared_minute_root': str(args.prepared_minute_root),
        'output_root': str(args.output_root),
        'artifact_dir': str(args.artifact_dir),
        'label': str(args.label),
        'start': str(args.start),
        'end': str(args.end),
        'cutoff_times': [item.strip() for item in str(args.cutoff_times).split(',') if item.strip()],
        'threshold_source': 'prior_dates',
        'threshold_lookback_days': [int(item.strip()) for item in str(args.threshold_lookback_days).split(',') if item.strip()],
        'threshold_quantile': float(args.threshold_quantile),
        'threshold_backend': str(args.threshold_backend),
        'operator_backend': str(args.operator_backend),
        'input_dataset': 'prepared_minute_bar_v1',
        'min_minutes': int(args.min_minutes),
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
            'unique_key': ['ts_code', 'trade_date', 'cutoff_time'],
            'required_duplicate_key_count': 0,
        },
        'resume_limitations': {
            'resumable_shard_backfill_available': True,
            'current_builder_mode': 'date_partition_skip_existing_with_max_dates',
            'next_required_engineering_step': 'run worker batch1 and resume batch2, then verify final QA/catalog/read smoke before active catalog registration',
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
    print(json.dumps({'verdict': payload['verdict'], 'output_path': str(output_path), 'dataset_id': DATASET_ID}, ensure_ascii=False, indent=2))
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
