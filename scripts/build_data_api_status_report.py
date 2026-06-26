#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.data_team_ops_registry import (  # noqa: E402
    data_team_ops_summary,
    read_data_team_ops_registry,
    validate_data_team_ops_registry,
)
from factor_factory.data_api.feature_family_registry import (  # noqa: E402
    feature_family_summary,
    read_feature_family_registry,
    validate_feature_family_registry,
)
from factor_factory.data_api.feature_precompute_registry import (  # noqa: E402
    read_feature_registry,
    registry_summary,
    validate_feature_precompute_registry,
)
from factor_factory.data_api.registry_crosslinks import (  # noqa: E402
    registry_crosslink_summary,
    validate_registry_crosslinks,
)


DEFAULT_FEATURE_PRECOMPUTE = REPO_ROOT / 'docs' / 'operations' / 'feature-precompute-registry.v1.json'
DEFAULT_FEATURE_FAMILY = REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json'
DEFAULT_DATA_TEAM_OPS = REPO_ROOT / 'docs' / 'operations' / 'data-team-daily-ops-checklist.v1.json'


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _issues_to_dict(issues: list[Any]) -> list[dict[str, str]]:
    return [issue.to_dict() for issue in issues]


def _top_dataset_actions(feature_precompute: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for entry in feature_precompute.get('datasets') or []:
        if not isinstance(entry, dict):
            continue
        status = entry.get('status')
        readiness = entry.get('production_readiness')
        priority = entry.get('priority')
        if priority in {'P0', 'P1'} and status in {'production_candidate', 'read_only_builder_available', 'planned'}:
            actions.append({
                'dataset_id': entry.get('dataset_id'),
                'priority': priority,
                'status': status,
                'production_readiness': readiness,
                'recommended_first_production': entry.get('recommended_first_production') is True,
                'registration_blockers': entry.get('registration_blockers') or [],
                'next_action': _dataset_next_action(entry),
            })
    return sorted(actions, key=lambda item: (item['priority'], not item['recommended_first_production'], str(item['dataset_id'])))


def _dataset_next_action(entry: dict[str, Any]) -> str:
    dataset_id = str(entry.get('dataset_id') or '')
    readiness = str(entry.get('production_readiness') or '')
    status = str(entry.get('status') or '')
    if readiness == 'worker_plan_accept':
        return 'run true-worker full-window proof and review closeout before catalog registration'
    if readiness == 'bounded_proof_accept':
        return 'decide full-window cost and true-worker proof requirement before production use'
    if status == 'planned':
        return 'implement builder/validator only if feature-family reuse justifies production'
    if dataset_id:
        return 'review dataset-specific registration blockers'
    return 'review registry entry'


def _top_family_actions(feature_family: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for entry in feature_family.get('feature_families') or []:
        if not isinstance(entry, dict):
            continue
        policy = entry.get('precompute_policy')
        if policy in {'precompute_now', 'precompute_after_source_ready'}:
            actions.append({
                'family_id': entry.get('family_id'),
                'domain': entry.get('domain'),
                'precompute_policy': policy,
                'reuse_tier': entry.get('reuse_tier'),
                'cost_tier': entry.get('cost_tier'),
                'recommended_dataset': entry.get('recommended_dataset'),
                'reasoning': entry.get('reasoning'),
            })
    return actions


def _blocking_ops(data_team_ops: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for entry in data_team_ops.get('tasks') or []:
        if isinstance(entry, dict) and entry.get('blocks_research_on_fail') is True:
            blockers.append({
                'task_id': entry.get('task_id'),
                'severity': entry.get('severity'),
                'cadence': entry.get('cadence'),
                'category': entry.get('category'),
                'acceptance_rule': entry.get('acceptance_rule'),
                'failure_tokens': entry.get('failure_tokens') or [],
            })
    return blockers


def build_status_report(
    *,
    feature_precompute_path: Path,
    feature_family_path: Path,
    data_team_ops_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    feature_precompute = read_feature_registry(feature_precompute_path)
    feature_family = read_feature_family_registry(feature_family_path)
    data_team_ops = read_data_team_ops_registry(data_team_ops_path)

    precompute_issues = validate_feature_precompute_registry(feature_precompute, repo_root=repo_root)
    family_issues = validate_feature_family_registry(feature_family)
    ops_issues = validate_data_team_ops_registry(data_team_ops, repo_root=repo_root)
    crosslink_issues = validate_registry_crosslinks(
        feature_precompute=feature_precompute,
        feature_family=feature_family,
        data_team_ops=data_team_ops,
    )
    all_valid = not precompute_issues and not family_issues and not ops_issues and not crosslink_issues
    return {
        'schema_version': 'data_api_status_report_v1',
        'generated_at_utc': utc_now(),
        'verdict': 'ACCEPT' if all_valid else 'BLOCK',
        'paths': {
            'feature_precompute_registry': str(feature_precompute_path),
            'feature_family_registry': str(feature_family_path),
            'data_team_ops_registry': str(data_team_ops_path),
        },
        'registries': {
            'feature_precompute': {
                'verdict': 'ACCEPT' if not precompute_issues else 'BLOCK',
                'summary': registry_summary(feature_precompute),
                'issues': _issues_to_dict(precompute_issues),
            },
            'feature_family': {
                'verdict': 'ACCEPT' if not family_issues else 'BLOCK',
                'summary': feature_family_summary(feature_family),
                'issues': _issues_to_dict(family_issues),
            },
            'data_team_ops': {
                'verdict': 'ACCEPT' if not ops_issues else 'BLOCK',
                'summary': data_team_ops_summary(data_team_ops),
                'issues': _issues_to_dict(ops_issues),
            },
            'crosslinks': {
                'verdict': 'ACCEPT' if not crosslink_issues else 'BLOCK',
                'summary': registry_crosslink_summary(
                    feature_precompute=feature_precompute,
                    feature_family=feature_family,
                    data_team_ops=data_team_ops,
                ),
                'issues': _issues_to_dict(crosslink_issues),
            },
        },
        'recommended_dataset_actions': _top_dataset_actions(feature_precompute),
        'recommended_feature_family_actions': _top_family_actions(feature_family),
        'research_blocking_ops': _blocking_ops(data_team_ops),
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    }


def _fmt_list(items: list[Any], *, empty: str = 'none') -> str:
    values = [str(item) for item in items if str(item)]
    return ', '.join(values) if values else empty


def render_markdown_report(report: dict[str, Any]) -> str:
    registries = report.get('registries') or {}
    precompute = (registries.get('feature_precompute') or {}).get('summary') or {}
    family = (registries.get('feature_family') or {}).get('summary') or {}
    ops = (registries.get('data_team_ops') or {}).get('summary') or {}
    crosslinks = (registries.get('crosslinks') or {}).get('summary') or {}
    lines: list[str] = [
        '# Data API Status Report',
        '',
        f"Generated: `{report.get('generated_at_utc')}`",
        '',
        f"Verdict: `{report.get('verdict')}`",
        '',
        '## Registry Health',
        '',
        '| Registry | Verdict | Summary |',
        '| --- | --- | --- |',
        f"| feature_precompute | `{(registries.get('feature_precompute') or {}).get('verdict')}` | datasets={precompute.get('dataset_count')}; recommended={_fmt_list(precompute.get('recommended_first_production') or [])} |",
        f"| feature_family | `{(registries.get('feature_family') or {}).get('verdict')}` | families={family.get('family_count')}; precompute_now={_fmt_list(family.get('precompute_now') or [])}; alpha360={_fmt_list(family.get('alpha360_related') or [])} |",
        f"| data_team_ops | `{(registries.get('data_team_ops') or {}).get('verdict')}` | tasks={ops.get('task_count')}; blocking={len(ops.get('research_blocking_tasks') or [])}; active_catalog_tasks={_fmt_list(ops.get('active_catalog_tasks') or [])} |",
        f"| crosslinks | `{(registries.get('crosslinks') or {}).get('verdict')}` | family_links={crosslinks.get('family_link_count')}; ops_dataset_refs={crosslinks.get('ops_dataset_ref_count')} |",
        '',
        '## Recommended Dataset Actions',
        '',
        '| Dataset | Priority | Status | Readiness | Next Action |',
        '| --- | --- | --- | --- | --- |',
    ]
    for item in report.get('recommended_dataset_actions') or []:
        lines.append(
            f"| `{item.get('dataset_id')}` | `{item.get('priority')}` | `{item.get('status')}` | `{item.get('production_readiness')}` | {item.get('next_action')} |"
        )
    lines.extend([
        '',
        '## Feature Families To Precompute',
        '',
        '| Family | Domain | Policy | Reuse | Cost | Dataset |',
        '| --- | --- | --- | --- | --- | --- |',
    ])
    for item in report.get('recommended_feature_family_actions') or []:
        lines.append(
            f"| `{item.get('family_id')}` | `{item.get('domain')}` | `{item.get('precompute_policy')}` | `{item.get('reuse_tier')}` | `{item.get('cost_tier')}` | `{item.get('recommended_dataset')}` |"
        )
    lines.extend([
        '',
        '## Research-Blocking Data Ops',
        '',
        '| Task | Severity | Cadence | Category | Acceptance Rule |',
        '| --- | --- | --- | --- | --- |',
    ])
    for item in report.get('research_blocking_ops') or []:
        lines.append(
            f"| `{item.get('task_id')}` | `{item.get('severity')}` | `{item.get('cadence')}` | `{item.get('category')}` | {item.get('acceptance_rule')} |"
        )
    safety = report.get('safety') or {}
    lines.extend([
        '',
        '## Safety',
        '',
        f"- starts_worker: `{safety.get('starts_worker')}`",
        f"- sends_ssm_command: `{safety.get('sends_ssm_command')}`",
        f"- writes_active_catalog: `{safety.get('writes_active_catalog')}`",
        f"- writes_factorforge_artifacts: `{safety.get('writes_factorforge_artifacts')}`",
        f"- production_loop_side_effect: `{safety.get('production_loop_side_effect')}`",
        '',
    ])
    return '\n'.join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a consolidated Data API registry status report.')
    parser.add_argument('--feature-precompute-registry', default=str(DEFAULT_FEATURE_PRECOMPUTE))
    parser.add_argument('--feature-family-registry', default=str(DEFAULT_FEATURE_FAMILY))
    parser.add_argument('--data-team-ops-registry', default=str(DEFAULT_DATA_TEAM_OPS))
    parser.add_argument('--repo-root', default=str(REPO_ROOT))
    parser.add_argument('--output', required=True)
    parser.add_argument('--markdown-output', default='')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_status_report(
        feature_precompute_path=Path(args.feature_precompute_registry).expanduser(),
        feature_family_path=Path(args.feature_family_registry).expanduser(),
        data_team_ops_path=Path(args.data_team_ops_registry).expanduser(),
        repo_root=Path(args.repo_root).expanduser(),
    )
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    markdown_output = ''
    if args.markdown_output:
        markdown_path = Path(args.markdown_output).expanduser()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown_report(report), encoding='utf-8')
        markdown_output = str(markdown_path)
    print(json.dumps({'verdict': report['verdict'], 'output': str(output_path), 'markdown_output': markdown_output}, ensure_ascii=False, indent=2))
    return 0 if report['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
