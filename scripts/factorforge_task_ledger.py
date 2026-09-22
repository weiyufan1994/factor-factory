#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
DEFAULT_RUNTIME_ROOT = LEGACY_WORKSPACE / 'factorforge'

VALID_STATUS = {
    'queued',
    'running',
    'blocked',
    'waiting_for_approval',
    'completed',
    'failed',
    'cancelled',
}
VALID_STEPS = {
    'intake',
    'Step1',
    'Step2',
    'Step3A',
    'Step3B',
    'Step4',
    'Step5',
    'Step6',
    'ProgramSearch',
    'SearchBranch',
    'KnowledgeSync',
    'DataReview',
    'ManualReview',
    'Done',
}
VALID_OWNERS = {'Bernard', 'Humphrey', 'Codex', 'EC2', 'human', 'unassigned'}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def resolve_runtime_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.getenv('FACTORFORGE_ROOT'):
        return Path(os.environ['FACTORFORGE_ROOT']).expanduser()
    if DEFAULT_RUNTIME_ROOT.exists():
        return DEFAULT_RUNTIME_ROOT
    return REPO_ROOT


def task_root(runtime_root: Path) -> Path:
    return runtime_root / 'objects' / 'task_ledger'


def task_path(runtime_root: Path, task_id: str) -> Path:
    return task_root(runtime_root) / f'task__{task_id}.json'


def slugify(value: str) -> str:
    value = re.sub(r'[^A-Za-z0-9_.-]+', '_', value.strip())
    value = value.strip('._-')
    return value[:72] or 'task'


def new_task_id(report_id: str | None, goal: str | None) -> str:
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = report_id or goal or 'manual'
    return f'TASK_{ts}_{slugify(base)}'


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {'1', 'true', 'yes', 'y'}:
        return True
    if lowered in {'0', 'false', 'no', 'n'}:
        return False
    raise SystemExit(f'invalid boolean: {value}')


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def make_event(kind: str, note: str | None = None, **kwargs: Any) -> dict[str, Any]:
    event = {
        'at_utc': utc_now(),
        'kind': kind,
    }
    if note:
        event['note'] = note
    event.update({k: v for k, v in kwargs.items() if v is not None})
    return event


def summary(task: dict[str, Any]) -> dict[str, Any]:
    return {
        'task_id': task.get('task_id'),
        'report_id': task.get('report_id'),
        'goal': task.get('goal'),
        'owner': task.get('owner'),
        'current_step': task.get('current_step'),
        'status': task.get('status'),
        'approval_required': task.get('approval_required'),
        'updated_at_utc': task.get('updated_at_utc'),
        'next_action': task.get('next_action'),
        'failure_signature': task.get('failure_signature'),
    }


def rebuild_index(runtime_root: Path) -> Path:
    root = task_root(runtime_root)
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(root.glob('task__*.json')):
        try:
            rows.append(summary(load_json(path)))
        except Exception as exc:  # keep index robust against partial files
            rows.append({'task_id': path.stem.removeprefix('task__'), 'status': 'index_error', 'error': str(exc)})
    index = {
        'updated_at_utc': utc_now(),
        'task_count': len(rows),
        'tasks': rows,
    }
    out = root / 'task_index.json'
    write_json(out, index)
    return out


def validate_task_payload(task: dict[str, Any]) -> list[str]:
    errors = []
    if not task.get('task_id'):
        errors.append('task_id missing')
    if task.get('status') not in VALID_STATUS:
        errors.append(f'invalid status: {task.get("status")}')
    if task.get('current_step') not in VALID_STEPS:
        errors.append(f'invalid current_step: {task.get("current_step")}')
    if task.get('owner') not in VALID_OWNERS:
        errors.append(f'invalid owner: {task.get("owner")}')
    if task.get('status') == 'waiting_for_approval' and not task.get('approval_required'):
        errors.append('waiting_for_approval requires approval_required=true')
    if task.get('status') == 'blocked' and not task.get('failure_signature'):
        errors.append('blocked status requires failure_signature')
    if task.get('status') in {'completed', 'failed', 'cancelled'} and not task.get('closed_at_utc'):
        errors.append(f'{task.get("status")} status requires closed_at_utc')
    if not isinstance(task.get('events'), list) or not task.get('events'):
        errors.append('events missing')
    return errors


def cmd_create(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    task_id = args.task_id or new_task_id(args.report_id, args.goal)
    path = task_path(runtime_root, task_id)
    if path.exists() and not args.force:
        raise SystemExit(f'task already exists: {path}')
    status = args.status
    approval_required = parse_bool(args.approval_required, status == 'waiting_for_approval')
    now = utc_now()
    task = {
        'task_id': task_id,
        'goal': args.goal,
        'object': args.object,
        'report_id': args.report_id,
        'owner': args.owner,
        'current_step': args.current_step,
        'status': status,
        'boundary': args.boundary,
        'data_policy': args.data_policy,
        'expected_output': args.expected_output,
        'approval_required': approval_required,
        'approval_checkpoint': args.approval_checkpoint,
        'artifact_paths': list(args.artifact_path or []),
        'failure_signature': args.failure_signature,
        'last_evidence': args.last_evidence,
        'next_action': args.next_action,
        'created_at_utc': now,
        'updated_at_utc': now,
        'closed_at_utc': now if status in {'completed', 'failed', 'cancelled'} else None,
        'events': [make_event('created', args.event or 'task created', status=status, owner=args.owner, current_step=args.current_step)],
        'producer': 'factorforge_task_ledger_v1',
    }
    errors = validate_task_payload(task)
    if errors:
        raise SystemExit('TASK_LEDGER_INVALID: ' + '; '.join(errors))
    write_json(path, task)
    rebuild_index(runtime_root)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    path = task_path(runtime_root, args.task_id)
    if not path.exists():
        raise SystemExit(f'task not found: {path}')
    task = load_json(path)
    old = summary(task)
    for field in ['goal', 'object', 'report_id', 'owner', 'current_step', 'status', 'boundary', 'data_policy', 'expected_output', 'approval_checkpoint', 'failure_signature', 'last_evidence', 'next_action']:
        value = getattr(args, field, None)
        if value is not None:
            task[field] = value
    if args.approval_required is not None:
        task['approval_required'] = parse_bool(args.approval_required)
    if args.artifact_path:
        task.setdefault('artifact_paths', [])
        task['artifact_paths'].extend(args.artifact_path)
    if args.exit_code is not None:
        task['last_exit_code'] = args.exit_code
    task['updated_at_utc'] = utc_now()
    if task.get('status') in {'completed', 'failed', 'cancelled'} and not task.get('closed_at_utc'):
        task['closed_at_utc'] = task['updated_at_utc']
    if task.get('status') not in {'completed', 'failed', 'cancelled'}:
        task['closed_at_utc'] = None
    task.setdefault('events', []).append(make_event(
        args.event_kind or 'updated',
        args.event,
        before=old,
        after=summary(task),
        exit_code=args.exit_code,
    ))
    errors = validate_task_payload(task)
    if errors:
        raise SystemExit('TASK_LEDGER_INVALID: ' + '; '.join(errors))
    write_json(path, task)
    rebuild_index(runtime_root)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    path = task_path(runtime_root, args.task_id)
    if not path.exists():
        raise SystemExit(f'task not found: {path}')
    print(json.dumps(load_json(path), ensure_ascii=False, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    rebuild_index(runtime_root)
    index = load_json(task_root(runtime_root) / 'task_index.json')
    rows = []
    for row in index.get('tasks') or []:
        if args.status and row.get('status') != args.status:
            continue
        if args.owner and row.get('owner') != args.owner:
            continue
        if args.report_id and row.get('report_id') != args.report_id:
            continue
        rows.append(row)
    if args.json:
        print(json.dumps({'task_count': len(rows), 'tasks': rows}, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row.get('task_id')} | {row.get('status')} | {row.get('owner')} | {row.get('current_step')} | {row.get('report_id') or '-'} | {row.get('next_action') or '-'}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    paths = [task_path(runtime_root, args.task_id)] if args.task_id else sorted(task_root(runtime_root).glob('task__*.json'))
    checks = []
    for path in paths:
        if not path.exists():
            checks.append({'task_id': args.task_id, 'status': 'BLOCK', 'error': f'missing {path}'})
            continue
        task = load_json(path)
        errors = validate_task_payload(task)
        checks.append({
            'task_id': task.get('task_id'),
            'status': 'PASS' if not errors else 'BLOCK',
            'errors': errors,
        })
    result = 'BLOCK' if any(row['status'] == 'BLOCK' for row in checks) else 'PASS'
    report = {
        'result': result,
        'checked_at_utc': utc_now(),
        'checks': checks,
    }
    out = task_root(runtime_root) / 'task_validation.json'
    write_json(out, report)
    print(f'RESULT: {result}')
    if result == 'BLOCK':
        return 1
    return 0


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument('--runtime-root')


def add_task_fields(p: argparse.ArgumentParser, *, create: bool) -> None:
    p.add_argument('--goal', required=create)
    p.add_argument('--object')
    p.add_argument('--report-id')
    p.add_argument('--owner', choices=sorted(VALID_OWNERS), default='unassigned' if create else None)
    p.add_argument('--current-step', choices=sorted(VALID_STEPS), default='intake' if create else None)
    p.add_argument('--status', choices=sorted(VALID_STATUS), default='queued' if create else None)
    p.add_argument('--boundary')
    p.add_argument('--data-policy')
    p.add_argument('--expected-output')
    p.add_argument('--approval-required', choices=['true', 'false'])
    p.add_argument('--approval-checkpoint')
    p.add_argument('--artifact-path', action='append')
    p.add_argument('--failure-signature')
    p.add_argument('--last-evidence')
    p.add_argument('--next-action')


def main() -> int:
    parser = argparse.ArgumentParser(description='Factor Forge lightweight task ledger (Phase A agent orchestration).')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_create = sub.add_parser('create')
    add_common(p_create)
    p_create.add_argument('--task-id')
    p_create.add_argument('--force', action='store_true')
    p_create.add_argument('--event')
    add_task_fields(p_create, create=True)
    p_create.set_defaults(func=cmd_create)

    p_update = sub.add_parser('update')
    add_common(p_update)
    p_update.add_argument('--task-id', required=True)
    p_update.add_argument('--event')
    p_update.add_argument('--event-kind')
    p_update.add_argument('--exit-code', type=int)
    add_task_fields(p_update, create=False)
    p_update.set_defaults(func=cmd_update)

    p_show = sub.add_parser('show')
    add_common(p_show)
    p_show.add_argument('--task-id', required=True)
    p_show.set_defaults(func=cmd_show)

    p_list = sub.add_parser('list')
    add_common(p_list)
    p_list.add_argument('--status', choices=sorted(VALID_STATUS))
    p_list.add_argument('--owner', choices=sorted(VALID_OWNERS))
    p_list.add_argument('--report-id')
    p_list.add_argument('--json', action='store_true')
    p_list.set_defaults(func=cmd_list)

    p_validate = sub.add_parser('validate')
    add_common(p_validate)
    p_validate.add_argument('--task-id')
    p_validate.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
