from __future__ import annotations

from pathlib import Path
from typing import Any

from .data_team_ops_registry import (
    data_team_ops_summary,
    validate_data_team_ops_registry,
)
from .datamart_readiness import build_datamart_readiness_report
from .feature_family_registry import (
    feature_family_summary,
    validate_feature_family_registry,
)
from .feature_precompute_decision import build_feature_precompute_decision_report
from .feature_precompute_registry import (
    registry_summary,
    validate_feature_precompute_registry,
)
from .registry_crosslinks import validate_registry_crosslinks


CLOSEOUT_SCHEMA_VERSION = 'feature_precompute_closeout_report_v1'


def _issues_to_dict(issues: list[Any]) -> list[dict[str, str]]:
    return [issue.to_dict() if hasattr(issue, 'to_dict') else {'field': '', 'message': str(issue)} for issue in issues]


def _stage_by_dataset(readiness: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get('dataset_id')): row
        for row in readiness.get('datasets') or []
        if isinstance(row, dict) and row.get('dataset_id')
    }


def _family_decisions(decision_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get('family_id')): row
        for row in decision_report.get('decisions') or []
        if isinstance(row, dict) and row.get('family_id')
    }


def build_feature_precompute_closeout_report(
    *,
    feature_precompute: dict[str, Any],
    feature_family: dict[str, Any],
    data_team_ops: dict[str, Any],
    repo_root: str | Path,
) -> dict[str, Any]:
    repo = Path(repo_root).expanduser()
    precompute_issues = validate_feature_precompute_registry(feature_precompute, repo_root=repo)
    family_issues = validate_feature_family_registry(feature_family)
    ops_issues = validate_data_team_ops_registry(data_team_ops, repo_root=repo)
    crosslink_issues = validate_registry_crosslinks(
        feature_family=feature_family,
        feature_precompute=feature_precompute,
        data_team_ops=data_team_ops,
    )
    decision_report = build_feature_precompute_decision_report(feature_family) if not family_issues else {
        'schema_version': 'feature_precompute_decision_report_v1',
        'decisions': [],
        'by_decision': {},
    }
    readiness = build_datamart_readiness_report(feature_precompute, repo_root=repo)
    stages = _stage_by_dataset(readiness)
    decisions = _family_decisions(decision_report)
    families = [row for row in feature_family.get('feature_families') or [] if isinstance(row, dict)]
    ops_tasks = [row for row in data_team_ops.get('tasks') or [] if isinstance(row, dict)]

    alpha360 = decisions.get('daily_alpha360_lag_tensor', {})
    production_sequence = [
        {
            'family_id': row.get('family_id'),
            'recommended_dataset': row.get('recommended_dataset'),
            'decision': decisions.get(str(row.get('family_id')), {}).get('decision'),
            'dataset_stage': stages.get(str(row.get('recommended_dataset')), {}).get('stage'),
            'production_readiness': stages.get(str(row.get('recommended_dataset')), {}).get('production_readiness'),
            'next_action': stages.get(str(row.get('recommended_dataset')), {}).get('next_action'),
        }
        for row in families
        if str(row.get('recommended_dataset') or '').endswith('_v1')
    ]
    daily_ops = [
        {
            'task_id': task.get('task_id'),
            'severity': task.get('severity'),
            'cadence': task.get('cadence'),
            'category': task.get('category'),
            'blocks_research_on_fail': task.get('blocks_research_on_fail') is True,
            'acceptance_rule': task.get('acceptance_rule'),
        }
        for task in ops_tasks
    ]
    issue_payload = {
        'feature_precompute': _issues_to_dict(precompute_issues),
        'feature_family': _issues_to_dict(family_issues),
        'data_team_ops': _issues_to_dict(ops_issues),
        'registry_crosslinks': _issues_to_dict(crosslink_issues),
    }
    all_issues = [item for values in issue_payload.values() for item in values]
    not_started = [row for row in readiness.get('datasets') or [] if row.get('stage') == 'not_started']
    return {
        'schema_version': CLOSEOUT_SCHEMA_VERSION,
        'verdict': 'ACCEPT' if not all_issues and not not_started else 'BLOCK',
        'issues': issue_payload,
        'repo_root': str(repo),
        'objective_coverage': {
            'time_series_precompute_menu': 'covered_by_feature_family_registry_and_feature_precompute_registry',
            'alpha360_position': 'daily_alpha360_lite_v1_is_model_specific_wide_tensor_projection_first',
            'private_fund_data_team_daily_work': 'covered_by_data_team_ops_registry_not_limited_to_cleaning',
        },
        'registry_summaries': {
            'feature_precompute': registry_summary(feature_precompute),
            'feature_family': feature_family_summary(feature_family),
            'data_team_ops': data_team_ops_summary(data_team_ops),
            'datamart_readiness_by_stage': readiness.get('by_stage') or {},
        },
        'alpha360_assessment': {
            'family_id': 'daily_alpha360_lag_tensor',
            'recommended_dataset': alpha360.get('recommended_dataset'),
            'decision': alpha360.get('decision'),
            'reason_tags': alpha360.get('reason_tags') or [],
            'position': 'worth_precomputing_for_model_pipelines_after_projection_and_worker_proof; not a universal replacement for compact daily technical state',
            'minute_policy': 'do_not_global_materialize_alpha360_style_minute_tensor_until fixed_model_pipeline_requires_it; prefer cutoff/distribution/terminal states first',
        },
        'production_sequence': production_sequence,
        'data_team_daily_work': {
            'not_just_cleaning': True,
            'task_count': len(daily_ops),
            'research_blocking_task_count': sum(1 for task in daily_ops if task['blocks_research_on_fail']),
            'categories': sorted({str(task.get('category')) for task in daily_ops}),
            'tasks': daily_ops,
        },
        'remaining_blockers': {
            'worker_plan_ready_requires_explicit_worker_run': [
                row.get('dataset_id')
                for row in readiness.get('datasets') or []
                if row.get('stage') == 'worker_plan_ready'
            ],
            'bounded_proof_ready_requires_worker_plan_or_full_window_decision': [
                row.get('dataset_id')
                for row in readiness.get('datasets') or []
                if row.get('stage') == 'bounded_proof_ready'
            ],
            'not_started': [row.get('dataset_id') for row in not_started],
        },
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    }
