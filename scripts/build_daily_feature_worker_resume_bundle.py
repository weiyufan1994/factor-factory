#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _py_literal(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a plan-only worker resume bundle for daily feature datamart production.')
    parser.add_argument('--dataset-id', choices=['daily_technical_state_v1', 'daily_alpha360_lite_v1'], required=True)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--input-parquet', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--artifact-dir', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--max-dates', type=int, default=80)
    parser.add_argument('--min-row-count', type=int, default=1000000)
    parser.add_argument('--max-warm-read-seconds', type=float, default=10.0)
    parser.add_argument('--lookback', type=int, default=60, help='Only used for daily_alpha360_lite_v1.')
    parser.add_argument('--projection-fields', default='')
    parser.add_argument('--smoke-date', default='')
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
        'validation_path': str(artifact_dir / f'{label}.validation.json'),
        'catalog_candidate_path': str(artifact_dir / f'{label}.catalog.json'),
        'read_smoke_path': str(artifact_dir / f'{label}.read_smoke.json'),
        'closeout_path': str(artifact_dir / f'{label}.closeout.json'),
    }


def _dataset_scripts(dataset_id: str) -> dict[str, str]:
    if dataset_id == 'daily_technical_state_v1':
        return {
            'build': 'scripts/build_daily_technical_state.py',
            'validate': 'scripts/validate_daily_technical_state.py',
            'default_projection_fields': 'ret_1d,volatility_20d,amihud_20d',
        }
    return {
        'build': 'scripts/build_daily_alpha360_lite.py',
        'validate': 'scripts/validate_daily_alpha360_lite.py',
        'default_projection_fields': 'CLOSE0,CLOSE59,VOLUME1',
    }


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    issues: list[str] = []
    if int(args.max_dates) <= 0:
        issues.append('max_dates_must_be_positive')
    if int(args.min_row_count) <= 0:
        issues.append('min_row_count_must_be_positive')
    if str(args.start) > str(args.end):
        issues.append('start_after_end')
    artifact_dir = Path(args.artifact_dir)
    paths = _paths(artifact_dir, str(args.label))
    scripts = _dataset_scripts(str(args.dataset_id))
    projection_fields = str(args.projection_fields or scripts['default_projection_fields'])
    smoke_date = str(args.smoke_date or args.start)

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

    common_build = [
        'PYTHONPATH=.',
        'python3',
        scripts['build'],
        '--input-parquet',
        str(args.input_parquet),
        '--output-root',
        str(args.output_root),
        '--partitioned',
        '--start',
        str(args.start),
        '--end',
        str(args.end),
    ]
    if args.dataset_id == 'daily_alpha360_lite_v1':
        common_build.extend(['--lookback', str(int(args.lookback))])

    batch1 = [
        *common_build,
        '--overwrite',
        '--max-dates',
        str(int(args.max_dates)),
        '--qa-output',
        paths['batch1_qa_path'],
        '--manifest-output',
        paths['batch1_manifest_path'],
    ]
    batch2 = [
        *common_build,
        '--skip-existing',
        '--qa-output',
        paths['batch2_qa_path'],
        '--manifest-output',
        paths['batch2_manifest_path'],
    ]
    validate = [
        'PYTHONPATH=.',
        'python3',
        scripts['validate'],
        '--feature-parquet',
        str(args.output_root),
        '--qa-path',
        paths['batch2_qa_path'],
        '--output-path',
        paths['validation_path'],
        '--min-row-count',
        str(int(args.min_row_count)),
        '--max-warm-read-seconds',
        str(float(args.max_warm_read_seconds)),
        '--allow-partial-source-qa',
    ]
    if args.dataset_id == 'daily_alpha360_lite_v1':
        validate.extend(['--lookback', str(int(args.lookback))])

    catalog_script = (
        "python3 - <<'PY'\n"
        "import json\n"
        "from pathlib import Path\n"
        f"validation=json.load(open({_py_literal(paths['validation_path'])}))\n"
        f"catalog_path=Path({_py_literal(paths['catalog_candidate_path'])})\n"
        f"dataset_id={_py_literal(str(args.dataset_id))}\n"
        "catalog_path.write_text(json.dumps({'catalog_version':'factorforge_data_catalog_v1','datasets':{dataset_id:validation['catalog_candidate']}}, ensure_ascii=False, indent=2))\n"
        "PY"
    )
    read_smoke = [
        'PYTHONPATH=.',
        'python3',
        'scripts/run_data_api_read_smoke.py',
        '--catalog',
        paths['catalog_candidate_path'],
        '--dataset-id',
        str(args.dataset_id),
        '--start-date',
        smoke_date,
        '--end-date',
        smoke_date,
        '--fields',
        projection_fields,
        '--frequency',
        'daily',
        '--max-warm-read-seconds',
        str(float(args.max_warm_read_seconds)),
        '--output-path',
        paths['read_smoke_path'],
    ]

    worker_commands = [
        f'cd {_quote(str(args.repo))} && {_shell_join(batch1)}',
        f'cd {_quote(str(args.repo))} && {_shell_join(batch2)}',
        f'cd {_quote(str(args.repo))} && {_shell_join(validate)}',
        f'cd {_quote(str(args.repo))} && PYTHONPATH=. {catalog_script} && {_shell_join(read_smoke)}',
    ]
    if args.dataset_id == 'daily_technical_state_v1':
        closeout = [
            'PYTHONPATH=.',
            'python3',
            'scripts/closeout_daily_technical_state.py',
            '--validation-path',
            paths['validation_path'],
            '--catalog-path',
            paths['catalog_candidate_path'],
            '--read-smoke-path',
            paths['read_smoke_path'],
            '--batch1-manifest-path',
            paths['batch1_manifest_path'],
            '--batch2-manifest-path',
            paths['batch2_manifest_path'],
            '--instance-id',
            str(args.instance_id),
            '--worker-command',
            'build_daily_technical_state.py resume batch1+batch2',
            '--required-start',
            str(args.start),
            '--required-end',
            str(args.end),
            '--min-row-count',
            str(int(args.min_row_count)),
            '--min-date-count',
            '2000',
            '--output-path',
            paths['closeout_path'],
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(closeout)}')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'schema_version': 'daily_feature_worker_resume_bundle_v1',
        'dataset_id': str(args.dataset_id),
        'instance_id': str(args.instance_id),
        'repo': str(args.repo),
        'input_parquet': str(args.input_parquet),
        'output_root': str(args.output_root),
        'artifact_dir': str(args.artifact_dir),
        'label': str(args.label),
        'start': str(args.start),
        'end': str(args.end),
        'max_dates': int(args.max_dates),
        'min_row_count': int(args.min_row_count),
        'projection_fields': [item.strip() for item in projection_fields.split(',') if item.strip()],
        'smoke_date': smoke_date,
        **paths,
        'local_readiness_commands': local_readiness_commands,
        'worker_commands': worker_commands,
        'execution_policy': {
            'plan_only': True,
            'requires_explicit_worker_start': True,
            'requires_explicit_command_dispatch': True,
            'requires_reviewer_accept_before_catalog_registration': True,
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
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
