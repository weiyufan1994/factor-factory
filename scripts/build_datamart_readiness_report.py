#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.datamart_readiness import build_datamart_readiness_report  # noqa: E402
from factor_factory.data_api.feature_precompute_registry import (  # noqa: E402
    read_feature_registry,
    validate_feature_precompute_registry,
)


DEFAULT_FEATURE_PRECOMPUTE = REPO_ROOT / 'docs' / 'operations' / 'feature-precompute-registry.v1.json'


def render_markdown(report: dict) -> str:
    lines = [
        '# Datamart Readiness Report',
        '',
        f"Verdict: `{report.get('verdict')}`",
        '',
        '## Stage Summary',
        '',
        '| Stage | Count |',
        '| --- | ---: |',
    ]
    for stage, count in sorted((report.get('by_stage') or {}).items()):
        lines.append(f'| `{stage}` | {count} |')
    lines.extend([
        '',
        '## Dataset Readiness',
        '',
        '| Dataset | Priority | Stage | Readiness | Missing Proofs | Non-ACCEPT Proofs | Next Action |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ])
    for item in report.get('datasets') or []:
        missing = ', '.join(item.get('missing_required_paths') or []) or 'none'
        bad = ', '.join(item.get('non_accept_proofs') or []) or 'none'
        lines.append(
            f"| `{item.get('dataset_id')}` | `{item.get('priority')}` | `{item.get('stage')}` | `{item.get('production_readiness')}` | {missing} | {bad} | {item.get('next_action')} |"
        )
    lines.extend([
        '',
        '## Safety',
        '',
        '- This report is read-only.',
        '- It does not start workers, send SSM commands, publish catalog entries, or write Factor Forge artifacts.',
        '',
    ])
    return '\n'.join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a read-only Data API datamart readiness report.')
    parser.add_argument('--feature-precompute-registry', default=str(DEFAULT_FEATURE_PRECOMPUTE))
    parser.add_argument('--repo-root', default=str(REPO_ROOT))
    parser.add_argument('--output', required=True)
    parser.add_argument('--markdown-output', default='')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry_path = Path(args.feature_precompute_registry).expanduser()
    repo_root = Path(args.repo_root).expanduser()
    payload = read_feature_registry(registry_path)
    issues = validate_feature_precompute_registry(payload, repo_root=repo_root)
    if issues:
        report = {
            'schema_version': 'datamart_readiness_report_v1',
            'verdict': 'BLOCK',
            'source_registry': str(registry_path),
            'issues': [issue.to_dict() for issue in issues],
            'safety': {
                'starts_worker': False,
                'sends_ssm_command': False,
                'writes_active_catalog': False,
                'writes_factorforge_artifacts': False,
                'production_loop_side_effect': False,
            },
        }
    else:
        report = build_datamart_readiness_report(payload, repo_root=repo_root)
        report['source_registry'] = str(registry_path)
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
