from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATA_TEAM_OPS_REGISTRY_SCHEMA_VERSION = 'data_team_ops_registry_v1'

ALLOWED_CADENCE = {'daily', 'intraday', 'weekly', 'on_demand'}
ALLOWED_SEVERITY = {'P0', 'P1', 'P2'}
ALLOWED_AUTOMATION = {'manual', 'scripted', 'scheduled', 'monitored'}


@dataclass(frozen=True)
class DataTeamOpsIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {'field': self.field, 'message': self.message}


def read_data_team_ops_registry(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'data team ops registry root must be an object: {source}')
    return payload


def _require_string(entry: dict[str, Any], field: str, issues: list[DataTeamOpsIssue], prefix: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        issues.append(DataTeamOpsIssue(f'{prefix}.{field}', 'must be a non-empty string'))
        return ''
    return value


def _require_bool(entry: dict[str, Any], field: str, issues: list[DataTeamOpsIssue], prefix: str) -> bool | None:
    value = entry.get(field)
    if not isinstance(value, bool):
        issues.append(DataTeamOpsIssue(f'{prefix}.{field}', 'must be a boolean'))
        return None
    return value


def _require_string_list(
    entry: dict[str, Any],
    field: str,
    issues: list[DataTeamOpsIssue],
    prefix: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    value = entry.get(field)
    if not isinstance(value, list):
        issues.append(DataTeamOpsIssue(f'{prefix}.{field}', 'must be a list'))
        return []
    if not allow_empty and not value:
        issues.append(DataTeamOpsIssue(f'{prefix}.{field}', 'must not be empty'))
    result: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(DataTeamOpsIssue(f'{prefix}.{field}[{idx}]', 'must be a non-empty string'))
        else:
            result.append(item)
    return result


def _path_exists(repo_root: Path, raw: str) -> bool:
    if not raw:
        return False
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.exists()


def _validate_task(entry: Any, index: int, seen: set[str], repo_root: Path) -> list[DataTeamOpsIssue]:
    prefix = f'tasks[{index}]'
    issues: list[DataTeamOpsIssue] = []
    if not isinstance(entry, dict):
        return [DataTeamOpsIssue(prefix, 'must be an object')]

    task_id = _require_string(entry, 'task_id', issues, prefix)
    if task_id:
        if task_id in seen:
            issues.append(DataTeamOpsIssue(f'{prefix}.task_id', 'must be unique'))
        seen.add(task_id)

    cadence = _require_string(entry, 'cadence', issues, prefix)
    if cadence and cadence not in ALLOWED_CADENCE:
        issues.append(DataTeamOpsIssue(f'{prefix}.cadence', f'must be one of {sorted(ALLOWED_CADENCE)}'))

    severity = _require_string(entry, 'severity', issues, prefix)
    if severity and severity not in ALLOWED_SEVERITY:
        issues.append(DataTeamOpsIssue(f'{prefix}.severity', f'must be one of {sorted(ALLOWED_SEVERITY)}'))

    automation = _require_string(entry, 'automation', issues, prefix)
    if automation and automation not in ALLOWED_AUTOMATION:
        issues.append(DataTeamOpsIssue(f'{prefix}.automation', f'must be one of {sorted(ALLOWED_AUTOMATION)}'))

    _require_string(entry, 'category', issues, prefix)
    _require_string(entry, 'owner_role', issues, prefix)
    _require_string(entry, 'description', issues, prefix)
    _require_string(entry, 'acceptance_rule', issues, prefix)
    _require_bool(entry, 'blocks_research_on_fail', issues, prefix)
    _require_bool(entry, 'writes_active_catalog', issues, prefix)
    _require_string_list(entry, 'required_proofs', issues, prefix)
    _require_string_list(entry, 'datasets', issues, prefix, allow_empty=True)
    _require_string_list(entry, 'failure_tokens', issues, prefix)
    commands = _require_string_list(entry, 'commands', issues, prefix, allow_empty=True)
    for idx, command in enumerate(commands):
        if command.startswith('aws ssm send-command') or 'aws ec2 start-instances' in command:
            issues.append(DataTeamOpsIssue(f'{prefix}.commands[{idx}]', 'must not directly start instances or dispatch SSM'))
    for idx, proof in enumerate(entry.get('required_proofs') or []):
        if isinstance(proof, str) and proof.endswith('.py') and not _path_exists(repo_root, proof):
            issues.append(DataTeamOpsIssue(f'{prefix}.required_proofs[{idx}]', 'script proof path does not exist'))

    if entry.get('writes_active_catalog') is True and severity != 'P0':
        issues.append(DataTeamOpsIssue(f'{prefix}.writes_active_catalog', 'active catalog writes must be P0 controlled tasks'))
    if severity == 'P0' and entry.get('blocks_research_on_fail') is not True:
        issues.append(DataTeamOpsIssue(f'{prefix}.blocks_research_on_fail', 'P0 tasks must block research on failure'))
    return issues


def validate_data_team_ops_registry(
    payload: dict[str, Any],
    *,
    repo_root: str | Path | None = None,
) -> list[DataTeamOpsIssue]:
    issues: list[DataTeamOpsIssue] = []
    if payload.get('schema_version') != DATA_TEAM_OPS_REGISTRY_SCHEMA_VERSION:
        issues.append(DataTeamOpsIssue('schema_version', f'must equal {DATA_TEAM_OPS_REGISTRY_SCHEMA_VERSION}'))
    tasks = payload.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        issues.append(DataTeamOpsIssue('tasks', 'must be a non-empty list'))
        return issues
    repo = Path(repo_root).expanduser() if repo_root is not None else Path.cwd()
    seen: set[str] = set()
    for idx, task in enumerate(tasks):
        issues.extend(_validate_task(task, idx, seen, repo))
    return issues


def data_team_ops_summary(payload: dict[str, Any]) -> dict[str, Any]:
    tasks = payload.get('tasks') if isinstance(payload.get('tasks'), list) else []
    entries = [entry for entry in tasks if isinstance(entry, dict)]
    by_category: dict[str, int] = {}
    by_cadence: dict[str, int] = {}
    blockers: list[str] = []
    active_catalog_tasks: list[str] = []
    for entry in entries:
        category = str(entry.get('category') or '')
        cadence = str(entry.get('cadence') or '')
        by_category[category] = by_category.get(category, 0) + 1
        by_cadence[cadence] = by_cadence.get(cadence, 0) + 1
        if entry.get('blocks_research_on_fail') is True:
            blockers.append(str(entry.get('task_id')))
        if entry.get('writes_active_catalog') is True:
            active_catalog_tasks.append(str(entry.get('task_id')))
    return {
        'schema_version': payload.get('schema_version'),
        'task_count': len(entries),
        'by_category': by_category,
        'by_cadence': by_cadence,
        'research_blocking_tasks': blockers,
        'active_catalog_tasks': active_catalog_tasks,
    }
