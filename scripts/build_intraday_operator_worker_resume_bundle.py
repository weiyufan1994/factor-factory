#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a plan-only resume bundle for intraday operator worker proof commands.')
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--cache-root', required=True)
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--input-format', choices=['prepared_minute_bar_v1', 'raw_minute_bar'], required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='real_bounded_intraday_operator')
    parser.add_argument('--operator-id', default='cpv_price_volume_corr_state')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--dates')
    parser.add_argument('--row-limit', type=int, default=0)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--max-workers', type=int, default=8)
    parser.add_argument('--min-row-count', type=int, default=100000)
    parser.add_argument('--evidence-scope', choices=['bounded_worker', 'production_scale', 'full_is'], default='bounded_worker')
    parser.add_argument('--include-terminal-rolling-corr', action='store_true')
    parser.add_argument('--include-ema-state', action='store_true')
    parser.add_argument('--include-terminal-ema-state', action='store_true')
    parser.add_argument('--include-array-grouped', action='store_true')
    parser.add_argument('--include-process-sharded-array-grouped', action='store_true')
    parser.add_argument('--include-threaded-grouped', action='store_true')
    parser.add_argument('--include-numba-grouped', action='store_true')
    parser.add_argument('--cpv-backend', default='process_sharded_array_grouped')
    parser.add_argument('--cpv-terminal-only', action='store_true')
    parser.add_argument('--default-backend', default='')
    parser.add_argument('--approved-backend', default='')
    parser.add_argument('--approved-by', default='<reviewer-required>')
    parser.add_argument('--approval-reason', default='<approval-reason-required>')
    parser.add_argument('--approval-output', default='')
    parser.add_argument('--approval-validation-output', default='')
    parser.add_argument('--replacement-plan-output', default='')
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _append_optional(parts: list[str], flag: str, value: str | int | None) -> None:
    if value not in {None, '', 0}:
        parts.extend([flag, str(value)])


def _quote(value: str | int | float) -> str:
    text = str(value)
    if not text:
        return "''"
    if all(ch.isalnum() or ch in '/._:=,-' for ch in text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


def _shell_join(parts: list[str]) -> str:
    return ' '.join(_quote(part) for part in parts)


def _paths(output_dir: Path, label: str, approval_output: str, approval_validation_output: str, replacement_plan_output: str) -> dict[str, str]:
    gate_dir = output_dir / f'{label}.gate'
    return {
        'ec2_status_path': str(output_dir / f'{label}.worker_ec2_status.json'),
        'ssm_status_path': str(output_dir / f'{label}.worker_ssm_status.json'),
        'worker_instance_readiness_path': str(output_dir / f'{label}.worker_instance_readiness.json'),
        'profile_path': str(gate_dir / f'{label}.profile.json'),
        'validation_path': str(gate_dir / f'{label}.validation.json'),
        'bundle_path': str(output_dir / f'{label}.worker_benchmark.bundle.json'),
        'safe_worker_bundle_path': str(output_dir / f'{label}.safe_worker_benchmark.bundle.json'),
        'safe_worker_validation_path': str(output_dir / f'{label}.safe_worker_benchmark.validation.json'),
        'approval_path': str(Path(approval_output) if approval_output else output_dir / f'{label}.production_approval.json'),
        'approval_validation_path': str(
            Path(approval_validation_output) if approval_validation_output else output_dir / f'{label}.production_approval.validation.json'
        ),
        'replacement_plan_path': str(
            Path(replacement_plan_output) if replacement_plan_output else output_dir / f'{label}.backend_replacement.plan.json'
        ),
    }


def _default_backend(args: argparse.Namespace) -> str:
    if args.default_backend:
        return str(args.default_backend)
    if str(args.operator_id) == 'cpv_price_volume_corr_state' and bool(args.cpv_terminal_only):
        return 'array_grouped_terminal'
    if str(args.operator_id) == 'cpv_price_volume_corr_state':
        return 'array_grouped'
    return 'reference'


def _approved_backend(args: argparse.Namespace) -> str:
    if args.approved_backend:
        return str(args.approved_backend)
    if str(args.operator_id) == 'cpv_price_volume_corr_state' and bool(args.cpv_terminal_only):
        return f'{args.cpv_backend}_terminal'
    if str(args.operator_id) == 'cpv_price_volume_corr_state':
        return str(args.cpv_backend)
    return 'array_grouped'


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    issues: list[str] = []
    if int(args.min_row_count) <= 0:
        issues.append('min_row_count_must_be_positive')
    if int(args.max_workers) <= 0:
        issues.append('max_workers_must_be_positive')
    if not (args.dates or args.start or args.end):
        issues.append('date_selection_required')
    if str(args.operator_id) != 'cpv_price_volume_corr_state':
        issues.append('unsupported_operator_id')

    output_dir = Path(args.output_dir)
    label = str(args.label)
    proof_paths = _paths(
        output_dir,
        label,
        approval_output=str(args.approval_output or ''),
        approval_validation_output=str(args.approval_validation_output or ''),
        replacement_plan_output=str(args.replacement_plan_output or ''),
    )
    default_backend = _default_backend(args)
    approved_backend = _approved_backend(args)
    local_readiness_commands: list[str] = []
    worker_commands: list[str] = []

    if not issues:
        local_readiness_commands.append(
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
            ]) + f' > {_quote(proof_paths["ec2_status_path"])}'
        )
        local_readiness_commands.append(
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
            ]) + f' > {_quote(proof_paths["ssm_status_path"])}'
        )
        local_readiness_commands.append(
            _shell_join([
                'PYTHONPATH=.',
                'python3',
                'scripts/validate_moneyflow_slow_state_worker_instance_readiness.py',
                '--instance-id',
                str(args.instance_id),
                '--ec2-status-path',
                proof_paths['ec2_status_path'],
                '--ssm-status-path',
                proof_paths['ssm_status_path'],
                '--output-path',
                proof_paths['worker_instance_readiness_path'],
            ])
        )

        safe_parts = [
            'PYTHONPATH=.',
            'python3',
            'scripts/run_intraday_operator_safe_worker_benchmark.py',
            '--input-root',
            str(args.input_root),
            '--input-format',
            str(args.input_format),
            '--output-dir',
            str(output_dir),
            '--label',
            label,
            '--evidence-scope',
            str(args.evidence_scope),
            '--window',
            str(int(args.window)),
            '--max-workers',
            str(int(args.max_workers)),
            '--min-row-count',
            str(int(args.min_row_count)),
            '--include-cpv-operator',
            '--cpv-backend',
            str(args.cpv_backend),
        ]
        _append_optional(safe_parts, '--start', args.start)
        _append_optional(safe_parts, '--end', args.end)
        _append_optional(safe_parts, '--dates', args.dates)
        _append_optional(safe_parts, '--row-limit', int(args.row_limit or 0))
        for enabled, flag in [
            (args.cpv_terminal_only, '--cpv-terminal-only'),
            (args.include_array_grouped, '--include-array-grouped'),
            (args.include_process_sharded_array_grouped, '--include-process-sharded-array-grouped'),
            (args.include_threaded_grouped, '--include-threaded-grouped'),
            (args.include_numba_grouped, '--include-numba-grouped'),
            (args.include_terminal_rolling_corr, '--include-terminal-rolling-corr'),
            (args.include_ema_state, '--include-ema-state'),
            (args.include_terminal_ema_state, '--include-terminal-ema-state'),
        ]:
            if enabled:
                safe_parts.append(flag)
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(safe_parts)}')

        validate_parts = [
            'PYTHONPATH=.',
            'python3',
            'scripts/validate_intraday_operator_worker_benchmark.py',
            '--bundle-path',
            proof_paths['safe_worker_bundle_path'].replace('.safe_worker_benchmark.bundle.json', '.worker_benchmark.bundle.json'),
            '--output-path',
            proof_paths['safe_worker_validation_path'],
            '--min-row-count',
            str(int(args.min_row_count)),
            '--evidence-scope',
            str(args.evidence_scope),
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(validate_parts)}')

        approval_build_parts = [
            'PYTHONPATH=.',
            'python3',
            'scripts/build_operator_backend_production_approval.py',
            '--profile-path',
            proof_paths['profile_path'],
            '--validation-path',
            proof_paths['validation_path'],
            '--safe-worker-bundle-path',
            proof_paths['safe_worker_bundle_path'],
            '--safe-worker-validation-path',
            proof_paths['safe_worker_validation_path'],
            '--operator-id',
            str(args.operator_id),
            '--approved-backend',
            approved_backend,
            '--evidence-scope',
            str(args.evidence_scope),
            '--approved-by',
            str(args.approved_by),
            '--approval-reason',
            str(args.approval_reason),
            '--min-input-row-count',
            str(int(args.min_row_count)),
            '--output-path',
            proof_paths['approval_path'],
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(approval_build_parts)}')

        approval_validate_parts = [
            'PYTHONPATH=.',
            'python3',
            'scripts/validate_operator_backend_production_approval.py',
            '--profile-path',
            proof_paths['profile_path'],
            '--validation-path',
            proof_paths['validation_path'],
            '--approval-path',
            proof_paths['approval_path'],
            '--safe-worker-bundle-path',
            proof_paths['safe_worker_bundle_path'],
            '--safe-worker-validation-path',
            proof_paths['safe_worker_validation_path'],
            '--operator-id',
            str(args.operator_id),
            '--default-backend',
            default_backend,
            '--output-path',
            proof_paths['approval_validation_path'],
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(approval_validate_parts)}')

        plan_parts = [
            'PYTHONPATH=.',
            'python3',
            'scripts/plan_operator_backend_replacement.py',
            '--approval-validation-path',
            proof_paths['approval_validation_path'],
            '--target-scope',
            'data_api_operator_backend_registry',
            '--output-path',
            proof_paths['replacement_plan_path'],
        ]
        worker_commands.append(f'cd {_quote(str(args.repo))} && {_shell_join(plan_parts)}')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'operator_id': str(args.operator_id),
        'evidence_scope': str(args.evidence_scope),
        'default_backend': default_backend,
        'approved_backend': approved_backend,
        'instance_id': str(args.instance_id),
        'repo': str(args.repo),
        'cache_root': str(args.cache_root),
        'input_root': str(args.input_root),
        'input_format': str(args.input_format),
        'output_dir': str(output_dir),
        'label': label,
        **proof_paths,
        'local_readiness_commands': local_readiness_commands,
        'worker_commands': worker_commands,
        'execution_policy': {
            'plan_only': True,
            'requires_explicit_worker_start': True,
            'run_safe_worker_preflight_first': True,
            'requires_reviewer_approval_before_replacement': True,
            'approval_builder_uses_placeholder_until_reviewer_fills_fields': str(args.approved_by).startswith('<') or str(args.approval_reason).startswith('<'),
        },
        'safety': {
            'starts_instance': False,
            'sends_ssm_command': False,
            'runs_benchmark': False,
            'writes_backend_config': False,
            'writes_datamart': False,
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
