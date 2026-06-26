#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.data_team_ops_registry import (  # noqa: E402
    data_team_ops_summary,
    read_data_team_ops_registry,
    validate_data_team_ops_registry,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate the Data API data-team daily ops registry.')
    parser.add_argument('path')
    parser.add_argument('--repo-root', default=str(REPO_ROOT))
    parser.add_argument('--output', default='')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = read_data_team_ops_registry(args.path)
    issues = validate_data_team_ops_registry(payload, repo_root=args.repo_root)
    report = {
        'path': args.path,
        'valid': not issues,
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'summary': data_team_ops_summary(payload),
        'issues': [issue.to_dict() for issue in issues],
    }
    if args.output:
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if not issues else 2)


if __name__ == '__main__':
    main()
