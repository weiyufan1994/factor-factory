#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.data_team_ops_registry import read_data_team_ops_registry  # noqa: E402
from factor_factory.data_api.feature_family_registry import read_feature_family_registry  # noqa: E402
from factor_factory.data_api.feature_precompute_closeout import build_feature_precompute_closeout_report  # noqa: E402
from factor_factory.data_api.feature_precompute_registry import read_feature_registry  # noqa: E402


DEFAULT_FEATURE_PRECOMPUTE = REPO_ROOT / 'docs' / 'operations' / 'feature-precompute-registry.v1.json'
DEFAULT_FEATURE_FAMILY = REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json'
DEFAULT_DATA_TEAM_OPS = REPO_ROOT / 'docs' / 'operations' / 'data-team-daily-ops-checklist.v1.json'


def render_markdown(report: dict) -> str:
    alpha = report.get('alpha360_assessment') or {}
    blockers = report.get('remaining_blockers') or {}
    lines = [
        '# Feature Precompute Closeout Report',
        '',
        f"Verdict: `{report.get('verdict')}`",
        '',
        '## What Is Covered',
        '',
        '- Time-series feature precompute menu: covered by feature family and concrete dataset registries.',
        '- Alpha360: useful as daily model-specific temporal context, projection-first; not a universal replacement for compact daily states.',
        '- Data-team work: source freshness, universe/investability, feature datamarts, performance, catalog governance, handoff, and cost guardrails, not only cleaning.',
        '',
        '## Readiness',
        '',
        '| Stage | Count |',
        '| --- | ---: |',
    ]
    for stage, count in sorted(((report.get('registry_summaries') or {}).get('datamart_readiness_by_stage') or {}).items()):
        lines.append(f'| `{stage}` | {count} |')
    lines.extend([
        '',
        '## Alpha360 Position',
        '',
        f"- Dataset: `{alpha.get('recommended_dataset')}`",
        f"- Decision: `{alpha.get('decision')}`",
        f"- Position: {alpha.get('position')}",
        f"- Minute policy: {alpha.get('minute_policy')}",
        '',
        '## Production Sequence',
        '',
        '| Family | Dataset | Decision | Stage | Readiness | Next Action |',
        '| --- | --- | --- | --- | --- | --- |',
    ])
    for item in report.get('production_sequence') or []:
        lines.append(
            f"| `{item.get('family_id')}` | `{item.get('recommended_dataset')}` | `{item.get('decision')}` | `{item.get('dataset_stage')}` | `{item.get('production_readiness')}` | {item.get('next_action')} |"
        )
    lines.extend([
        '',
        '## Data Team Daily Work',
        '',
        '| Task | Severity | Cadence | Category | Blocks Research |',
        '| --- | --- | --- | --- | --- |',
    ])
    for task in (report.get('data_team_daily_work') or {}).get('tasks') or []:
        lines.append(
            f"| `{task.get('task_id')}` | `{task.get('severity')}` | `{task.get('cadence')}` | `{task.get('category')}` | `{task.get('blocks_research_on_fail')}` |"
        )
    lines.extend([
        '',
        '## Remaining Blockers',
        '',
        f"- Worker-plan ready, still needs explicit worker run: `{', '.join(blockers.get('worker_plan_ready_requires_explicit_worker_run') or [])}`",
        f"- Bounded-proof ready, still needs worker plan/full-window decision: `{', '.join(blockers.get('bounded_proof_ready_requires_worker_plan_or_full_window_decision') or [])}`",
        f"- Not started: `{', '.join(blockers.get('not_started') or [])}`",
        '',
        '## Safety',
        '',
        '- This report is read-only.',
        '- It does not start workers, send SSM commands, publish active catalog entries, or write Factor Forge artifacts.',
        '',
    ])
    return '\n'.join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a closeout report for Data API feature precompute planning.')
    parser.add_argument('--feature-precompute-registry', default=str(DEFAULT_FEATURE_PRECOMPUTE))
    parser.add_argument('--feature-family-registry', default=str(DEFAULT_FEATURE_FAMILY))
    parser.add_argument('--data-team-ops-registry', default=str(DEFAULT_DATA_TEAM_OPS))
    parser.add_argument('--repo-root', default=str(REPO_ROOT))
    parser.add_argument('--output', required=True)
    parser.add_argument('--markdown-output', default='')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_feature_precompute_closeout_report(
        feature_precompute=read_feature_registry(Path(args.feature_precompute_registry).expanduser()),
        feature_family=read_feature_family_registry(Path(args.feature_family_registry).expanduser()),
        data_team_ops=read_data_team_ops_registry(Path(args.data_team_ops_registry).expanduser()),
        repo_root=Path(args.repo_root).expanduser(),
    )
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    markdown_output = ''
    if args.markdown_output:
        markdown_path = Path(args.markdown_output).expanduser()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding='utf-8')
        markdown_output = str(markdown_path)
    print(json.dumps({'verdict': report['verdict'], 'output': str(output_path), 'markdown_output': markdown_output}, ensure_ascii=False, indent=2))
    return 0 if report['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
