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
from factor_factory.data_api.feature_precompute_decision import (  # noqa: E402
    build_feature_precompute_decision_report,
)
from factor_factory.data_api.datamart_readiness import (  # noqa: E402
    build_datamart_readiness_report,
)
from factor_factory.data_api.registry_crosslinks import (  # noqa: E402
    registry_crosslink_summary,
    validate_registry_crosslinks,
)
from scripts.build_data_api_status_report import (  # noqa: E402
    DEFAULT_DATA_TEAM_OPS,
    DEFAULT_FEATURE_FAMILY,
    DEFAULT_FEATURE_PRECOMPUTE,
    build_status_report,
    render_markdown_report,
)
from scripts.build_datamart_readiness_report import render_markdown as render_readiness_markdown  # noqa: E402
from scripts.build_feature_precompute_decision_report import render_markdown as render_decision_markdown  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _issues_to_dict(issues: list[Any]) -> list[dict[str, str]]:
    return [issue.to_dict() for issue in issues]


def _registry_validation_reports(
    *,
    feature_precompute_path: Path,
    feature_family_path: Path,
    data_team_ops_path: Path,
    repo_root: Path,
) -> dict[str, dict[str, Any]]:
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
    return {
        'feature_precompute_registry.validation.json': {
            'path': str(feature_precompute_path),
            'valid': not precompute_issues,
            'verdict': 'ACCEPT' if not precompute_issues else 'BLOCK',
            'summary': registry_summary(feature_precompute),
            'issues': _issues_to_dict(precompute_issues),
        },
        'feature_family_registry.validation.json': {
            'path': str(feature_family_path),
            'valid': not family_issues,
            'verdict': 'ACCEPT' if not family_issues else 'BLOCK',
            'summary': feature_family_summary(feature_family),
            'issues': _issues_to_dict(family_issues),
        },
        'data_team_ops_registry.validation.json': {
            'path': str(data_team_ops_path),
            'valid': not ops_issues,
            'verdict': 'ACCEPT' if not ops_issues else 'BLOCK',
            'summary': data_team_ops_summary(data_team_ops),
            'issues': _issues_to_dict(ops_issues),
        },
        'registry_crosslinks.validation.json': {
            'valid': not crosslink_issues,
            'verdict': 'ACCEPT' if not crosslink_issues else 'BLOCK',
            'summary': registry_crosslink_summary(
                feature_precompute=feature_precompute,
                feature_family=feature_family,
                data_team_ops=data_team_ops,
            ),
            'issues': _issues_to_dict(crosslink_issues),
        },
    }


def _render_readme(summary: dict[str, Any], status_markdown_name: str) -> str:
    p0 = [
        item.get('dataset_id')
        for item in summary.get('recommended_p0_datasets') or []
        if item.get('dataset_id')
    ]
    p0_text = ', '.join(f'`{item}`' for item in p0) if p0 else '`none`'
    return '\n'.join([
        '# Data API Handoff Package',
        '',
        f"Generated: `{summary.get('generated_at_utc')}`",
        '',
        f"Verdict: `{summary.get('verdict')}`",
        '',
        'This package is a read-only handoff for Factor Forge architects and researchers.',
        'It summarizes Data API datamart readiness, registry health, recommended precompute work, and research-blocking data operations.',
        '',
        'It is not an active production catalog.',
        '',
        '## Files',
        '',
        f"- `{status_markdown_name}`: human-readable status report.",
        '- `data_api_status_report.json`: machine-readable consolidated status.',
        '- `feature_precompute_registry.validation.json`: precompute registry validation.',
        '- `feature_family_registry.validation.json`: feature-family registry validation.',
        '- `data_team_ops_registry.validation.json`: daily data-team ops validation.',
        '- `registry_crosslinks.validation.json`: cross-registry link validation.',
        '- `feature_precompute_decision_report.json`: precompute decision ranking and Alpha360/intraday position.',
        '- `feature_precompute_decision_report.md`: human-readable precompute decision report.',
        '- `datamart_readiness_report.json`: proof-path readiness and next-action matrix.',
        '- `datamart_readiness_report.md`: human-readable datamart readiness report.',
        '- `handoff_summary.json`: compact package index and safety flags.',
        '',
        '## Current P0 Data Work',
        '',
        f"- Recommended P0 datasets: {p0_text}",
        '',
        'Researchers should continue production proofs only after the required dataset closeout is `ACCEPT` and the runtime Data API catalog exposes the dataset they need.',
        '',
        '## Safety Boundary',
        '',
        '- Does not start workers.',
        '- Does not send SSM commands.',
        '- Does not write active catalog.',
        '- Does not write Factor Forge artifacts.',
        '- Does not start a Factor Forge production loop.',
        '',
    ])


def build_handoff_package(
    *,
    output_dir: Path,
    feature_precompute_path: Path,
    feature_family_path: Path,
    data_team_ops_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    status_report = build_status_report(
        feature_precompute_path=feature_precompute_path,
        feature_family_path=feature_family_path,
        data_team_ops_path=data_team_ops_path,
        repo_root=repo_root,
    )
    status_json = output_dir / 'data_api_status_report.json'
    status_markdown = output_dir / 'data_api_status_report.md'
    _write_json(status_json, status_report)
    status_markdown.write_text(render_markdown_report(status_report), encoding='utf-8')

    validation_reports = _registry_validation_reports(
        feature_precompute_path=feature_precompute_path,
        feature_family_path=feature_family_path,
        data_team_ops_path=data_team_ops_path,
        repo_root=repo_root,
    )
    validation_paths: dict[str, str] = {}
    validation_verdicts: dict[str, str] = {}
    for filename, payload in validation_reports.items():
        target = output_dir / filename
        _write_json(target, payload)
        validation_paths[filename] = str(target)
        validation_verdicts[filename] = str(payload.get('verdict'))

    feature_family = read_feature_family_registry(feature_family_path)
    decision_report = build_feature_precompute_decision_report(feature_family)
    decision_report['verdict'] = 'ACCEPT' if not validate_feature_family_registry(feature_family) else 'BLOCK'
    decision_report['source_registry'] = str(feature_family_path)
    decision_json = output_dir / 'feature_precompute_decision_report.json'
    decision_markdown = output_dir / 'feature_precompute_decision_report.md'
    _write_json(decision_json, decision_report)
    decision_markdown.write_text(render_decision_markdown(decision_report), encoding='utf-8')

    feature_precompute = read_feature_registry(feature_precompute_path)
    readiness_report = build_datamart_readiness_report(feature_precompute, repo_root=repo_root)
    readiness_report['source_registry'] = str(feature_precompute_path)
    readiness_json = output_dir / 'datamart_readiness_report.json'
    readiness_markdown = output_dir / 'datamart_readiness_report.md'
    _write_json(readiness_json, readiness_report)
    readiness_markdown.write_text(render_readiness_markdown(readiness_report), encoding='utf-8')

    recommended_p0 = [
        item
        for item in status_report.get('recommended_dataset_actions') or []
        if item.get('priority') == 'P0'
    ]
    summary = {
        'schema_version': 'data_api_handoff_package_v1',
        'generated_at_utc': utc_now(),
        'verdict': status_report.get('verdict'),
        'output_dir': str(output_dir),
        'paths': {
            'readme': str(output_dir / 'README.md'),
            'status_json': str(status_json),
            'status_markdown': str(status_markdown),
            'feature_precompute_decision_json': str(decision_json),
            'feature_precompute_decision_markdown': str(decision_markdown),
            'datamart_readiness_json': str(readiness_json),
            'datamart_readiness_markdown': str(readiness_markdown),
            'validation_reports': validation_paths,
        },
        'validation_verdicts': validation_verdicts,
        'recommended_p0_datasets': recommended_p0,
        'research_blocking_ops': status_report.get('research_blocking_ops') or [],
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
        'notes': [
            'handoff package is read-only and not an active production catalog',
            'runtime reads must still use the active Data API catalog',
            'production factor loop must wait for dataset-specific ACCEPT closeout',
        ],
    }
    readme_path = output_dir / 'README.md'
    readme_path.write_text(_render_readme(summary, status_markdown.name), encoding='utf-8')
    _write_json(output_dir / 'handoff_summary.json', summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a read-only Data API researcher handoff package.')
    parser.add_argument('--feature-precompute-registry', default=str(DEFAULT_FEATURE_PRECOMPUTE))
    parser.add_argument('--feature-family-registry', default=str(DEFAULT_FEATURE_FAMILY))
    parser.add_argument('--data-team-ops-registry', default=str(DEFAULT_DATA_TEAM_OPS))
    parser.add_argument('--repo-root', default=str(REPO_ROOT))
    parser.add_argument('--output-dir', required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_handoff_package(
        output_dir=Path(args.output_dir).expanduser(),
        feature_precompute_path=Path(args.feature_precompute_registry).expanduser(),
        feature_family_path=Path(args.feature_family_registry).expanduser(),
        data_team_ops_path=Path(args.data_team_ops_registry).expanduser(),
        repo_root=Path(args.repo_root).expanduser(),
    )
    print(json.dumps({
        'verdict': summary['verdict'],
        'output_dir': summary['output_dir'],
        'summary': summary['paths']['readme'],
    }, ensure_ascii=False, indent=2))
    return 0 if summary['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
