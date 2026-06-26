#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATASET_ID = 'intraday_pseudo_dollar_bar_v1'
SCHEMA_VERSION = 'pseudo_dollar_worker_bundle_v1'


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
    parser = argparse.ArgumentParser(description='Build a plan-only exploratory worker bundle for intraday_pseudo_dollar_bar_v1.')
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--cache-root', required=True)
    parser.add_argument('--s3-root', required=True)
    parser.add_argument('--local-input-dir', required=True)
    parser.add_argument('--artifact-dir', required=True)
    parser.add_argument('--clickhouse', default='/usr/bin/clickhouse')
    parser.add_argument('--label', default='intraday_pseudo_dollar_bar_v1_exploratory')
    parser.add_argument('--trade-date', default='20240110')
    parser.add_argument('--parquet-file-name', default='pseudo_dollar_bar__{trade_date}.parquet')
    parser.add_argument('--max-warm-read-seconds', type=float, default=10.0)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _paths(artifact_dir: Path, label: str, trade_date: str, parquet_file_name: str) -> dict[str, str]:
    local_parquet = artifact_dir / parquet_file_name.format(trade_date=trade_date)
    return {
        'ec2_status_path': str(artifact_dir / f'{label}.worker_ec2_status.json'),
        'ssm_status_path': str(artifact_dir / f'{label}.worker_ssm_status.json'),
        'worker_instance_readiness_path': str(artifact_dir / f'{label}.worker_instance_readiness.json'),
        'local_parquet_path': str(local_parquet),
        'probe_proof_path': str(artifact_dir / f'{label}.probe.json'),
        'readiness_summary_path': str(artifact_dir / f'{label}.readiness_summary.json'),
    }


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    issues: list[str] = []
    trade_date = str(args.trade_date).replace('-', '')
    if len(trade_date) != 8 or not trade_date.isdigit():
        issues.append('trade_date_must_be_yyyymmdd')
    artifact_dir = Path(args.artifact_dir)
    paths = _paths(artifact_dir, str(args.label), trade_date, str(args.parquet_file_name))
    s3_partition = f'{str(args.s3_root).rstrip("/")}/trade_date={trade_date}/'
    s3_source = f'{s3_partition}{Path(paths["local_parquet_path"]).name}'

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
        worker_commands = [
            f'mkdir -p {_quote(str(args.local_input_dir))} {_quote(str(args.artifact_dir))}',
            _shell_join(['aws', 's3', 'cp', s3_partition, str(args.local_input_dir), '--recursive', '--exclude', '*', '--include', '*.parquet']),
            (
                f'cd {_quote(str(args.repo))} && '
                + _shell_join([
                    'PYTHONPATH=.',
                    'python3',
                    'scripts/probe_clickhouse_intraday_pseudo_dollar_bar.py',
                    '--clickhouse',
                    str(args.clickhouse),
                    '--parquet',
                    paths['local_parquet_path'],
                    '--trade-date',
                    trade_date,
                    '--proof-output',
                    paths['probe_proof_path'],
                    '--host',
                    'factor-research-worker',
                    '--instance-id',
                    str(args.instance_id),
                    '--s3-source',
                    s3_source,
                ])
            ),
            (
                "python3 - <<'PY'\n"
                "import json\n"
                "from pathlib import Path\n"
                f"probe=Path({_quote(paths['probe_proof_path'])})\n"
                f"out=Path({_quote(paths['readiness_summary_path'])})\n"
                "payload=json.loads(probe.read_text())\n"
                "issues=[]\n"
                "if payload.get('verdict')!='ACCEPT': issues.append('probe_not_accept')\n"
                "if not payload.get('notes') or 'not true tick dollar bar' not in ' '.join(payload.get('notes')): issues.append('pseudo_label_missing')\n"
                "summary={'verdict':'ACCEPT' if not issues else 'BLOCK','issues':issues,'dataset_id':payload.get('dataset_id'),'trade_date':payload.get('trade_date'),'row_count':(payload.get('reference') or {}).get('row_count'),'duplicate_key_count':(payload.get('reference') or {}).get('duplicate_key_count'),'timings':payload.get('timings'),'source_is_pseudo_from_1m_bar':True,'production_readiness':'exploratory_worker_plan_only'}\n"
                "out.parent.mkdir(parents=True, exist_ok=True)\n"
                "out.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\\n')\n"
                "raise SystemExit(0 if summary['verdict']=='ACCEPT' else 2)\n"
                "PY"
            ),
        ]

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'schema_version': SCHEMA_VERSION,
        'dataset_id': DATASET_ID,
        'instance_id': str(args.instance_id),
        'repo': str(args.repo),
        'cache_root': str(args.cache_root),
        's3_root': str(args.s3_root),
        's3_partition': s3_partition,
        'local_input_dir': str(args.local_input_dir),
        'artifact_dir': str(args.artifact_dir),
        'label': str(args.label),
        'trade_date': trade_date,
        'input_dataset': 'minute_bar_derived_pseudo_dollar_bar',
        'scope': 'exploratory_single_partition_cost_and_readiness_probe',
        'not_full_window_production_plan': True,
        'true_tick_dollar_bar': False,
        'source_is_pseudo_from_1m_bar': True,
        'max_warm_read_seconds': float(args.max_warm_read_seconds),
        'full_window_contract': {
            'research_window': 'IS',
            'required_start': None,
            'required_end': None,
            'no_future_intraday_minutes': True,
            'cutoff_rule': 'only completed pseudo buckets before cutoff may be used by downstream signals',
            'unique_key': ['ts_code', 'trade_date', 'bucket_id'],
            'required_duplicate_key_count': 0,
        },
        'resume_limitations': {
            'resumable_shard_backfill_available': False,
            'current_builder_mode': 'exploratory_existing_partition_probe_only',
            'next_required_engineering_step': 'decide whether research demand justifies a real full-window builder before any production claim',
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
    print(json.dumps({'verdict': payload['verdict'], 'output_path': str(output_path), 'dataset_id': DATASET_ID}, ensure_ascii=False))
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
