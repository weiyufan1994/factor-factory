#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.feature_family_registry import (  # noqa: E402
    read_feature_family_registry,
    validate_feature_family_registry,
)
from factor_factory.data_api.feature_precompute_decision import (  # noqa: E402
    build_feature_precompute_decision_report,
    recommended_precompute_sequence,
)


DEFAULT_FEATURE_FAMILY = REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json'


def render_markdown(report: dict) -> str:
    lines = [
        '# Feature Precompute Decision Report',
        '',
        f"Schema: `{report.get('schema_version')}`",
        '',
        '## Summary',
        '',
        '| Decision | Count |',
        '| --- | ---: |',
    ]
    for decision, count in sorted((report.get('by_decision') or {}).items()):
        lines.append(f'| `{decision}` | {count} |')
    lines.extend([
        '',
        '## Recommended Sequence',
        '',
        '| Family | Domain | Dataset | Decision | Reuse | Cost | Why |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ])
    for item in recommended_precompute_sequence(report):
        reasons = ', '.join(item.get('reason_tags') or [])
        lines.append(
            f"| `{item.get('family_id')}` | `{item.get('domain')}` | `{item.get('recommended_dataset')}` | `{item.get('decision')}` | `{item.get('reuse_tier')}` | `{item.get('cost_tier')}` | {reasons} |"
        )
    lines.extend([
        '',
        '## Alpha360 Position',
        '',
        'Alpha360-style daily lag tensors are useful as standardized temporal context for model pipelines, but they are wide and should be projected column-first. They are not the default replacement for compact daily technical states or formula-specific features.',
        '',
        '## Intraday Position',
        '',
        'For minute data, the first production targets should be reusable sufficient-statistics states and terminal/cutoff states. Raw-minute scans remain acceptable for bounded Step3 proofs, but full-window Step4 should prefer accepted datamarts or shared array kernels.',
        '',
    ])
    return '\n'.join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a Data API feature precompute decision report.')
    parser.add_argument('--feature-family-registry', default=str(DEFAULT_FEATURE_FAMILY))
    parser.add_argument('--output', required=True)
    parser.add_argument('--markdown-output', default='')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry_path = Path(args.feature_family_registry).expanduser()
    payload = read_feature_family_registry(registry_path)
    issues = validate_feature_family_registry(payload)
    if issues:
        report = {
            'schema_version': 'feature_precompute_decision_report_v1',
            'verdict': 'BLOCK',
            'source_registry': str(registry_path),
            'issues': [issue.to_dict() for issue in issues],
        }
    else:
        report = build_feature_precompute_decision_report(payload)
        report['verdict'] = 'ACCEPT'
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
