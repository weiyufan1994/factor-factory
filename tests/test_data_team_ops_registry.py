from __future__ import annotations

from pathlib import Path

from factor_factory.data_api.data_team_ops_registry import (
    data_team_ops_summary,
    read_data_team_ops_registry,
    validate_data_team_ops_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / 'docs' / 'operations' / 'data-team-daily-ops-checklist.v1.json'


def test_default_data_team_ops_registry_is_valid():
    payload = read_data_team_ops_registry(REGISTRY_PATH)

    issues = validate_data_team_ops_registry(payload, repo_root=REPO_ROOT)

    assert issues == []
    summary = data_team_ops_summary(payload)
    assert summary['task_count'] >= 8
    assert 'source_freshness_and_coverage' in summary['research_blocking_tasks']
    assert summary['active_catalog_tasks'] == ['active_catalog_publication_gate']


def test_ops_registry_rejects_duplicate_task_ids():
    payload = read_data_team_ops_registry(REGISTRY_PATH)
    payload['tasks'] = [payload['tasks'][0], dict(payload['tasks'][0])]

    fields = {issue.field for issue in validate_data_team_ops_registry(payload, repo_root=REPO_ROOT)}

    assert 'tasks[1].task_id' in fields


def test_ops_registry_rejects_p0_that_does_not_block_research():
    payload = read_data_team_ops_registry(REGISTRY_PATH)
    task = dict(payload['tasks'][0])
    task['blocks_research_on_fail'] = False
    payload['tasks'] = [task]

    fields = {issue.field for issue in validate_data_team_ops_registry(payload, repo_root=REPO_ROOT)}

    assert 'tasks[0].blocks_research_on_fail' in fields


def test_ops_registry_rejects_remote_dispatch_commands():
    payload = read_data_team_ops_registry(REGISTRY_PATH)
    task = dict(payload['tasks'][0])
    task['commands'] = ['aws ssm send-command --document-name AWS-RunShellScript']
    payload['tasks'] = [task]

    fields = {issue.field for issue in validate_data_team_ops_registry(payload, repo_root=REPO_ROOT)}

    assert 'tasks[0].commands[0]' in fields
