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
from factor_factory.data_api.feature_precompute_registry import read_feature_registry  # noqa: E402
from factor_factory.data_api.registry_crosslinks import (  # noqa: E402
    registry_crosslink_summary,
    validate_registry_crosslinks,
)


DEFAULT_FEATURE_PRECOMPUTE = REPO_ROOT / 'docs' / 'operations' / 'feature-precompute-registry.v1.json'
DEFAULT_FEATURE_FAMILY = REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json'
DEFAULT_DATA_TEAM_OPS = REPO_ROOT / 'docs' / 'operations' / 'data-team-daily-ops-checklist.v1.json'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate crosslinks across Data API registry files.')
    parser.add_argument('--feature-precompute-registry', default=str(DEFAULT_FEATURE_PRECOMPUTE))
    parser.add_argument('--feature-family-registry', default=str(DEFAULT_FEATURE_FAMILY))
    parser.add_argument('--data-team-ops-registry', default=str(DEFAULT_DATA_TEAM_OPS))
    parser.add_argument('--output', default='')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feature_precompute = read_feature_registry(args.feature_precompute_registry)
    feature_family = read_feature_family_registry(args.feature_family_registry)
    data_team_ops = read_data_team_ops_registry(args.data_team_ops_registry)
    issues = validate_registry_crosslinks(
        feature_precompute=feature_precompute,
        feature_family=feature_family,
        data_team_ops=data_team_ops,
    )
    report = {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'valid': not issues,
        'paths': {
            'feature_precompute_registry': str(Path(args.feature_precompute_registry).expanduser()),
            'feature_family_registry': str(Path(args.feature_family_registry).expanduser()),
            'data_team_ops_registry': str(Path(args.data_team_ops_registry).expanduser()),
        },
        'summary': registry_crosslink_summary(
            feature_precompute=feature_precompute,
            feature_family=feature_family,
            data_team_ops=data_team_ops,
        ),
        'issues': [issue.to_dict() for issue in issues],
    }
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if not issues else 2)


if __name__ == '__main__':
    main()
