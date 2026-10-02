#!/usr/bin/env python3
"""Validate or explicitly execute frozen W11 development comparison packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.hybrid_research.proposal_comparison import (
    comparison_as_dict,
    load_development_package,
    run_development_comparison,
)
from factor_factory.runtime_context import write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages", nargs="+", type=Path)
    parser.add_argument("--execute-development", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= len(args.packages) <= 3:
        raise SystemExit("one to three frozen task packages are required")
    packages = [load_development_package(path) for path in args.packages]
    if len({package.task_id for package in packages}) != len(packages):
        raise SystemExit("task_id values must be unique")
    if not args.execute_development:
        payload = {
            "status": "validated_not_executed",
            "task_count": len(packages),
            "tasks": [
                {
                    "task_id": package.task_id,
                    "package_hash": package.package_hash,
                    "proposer_seeds": package.proposer_seeds,
                    "proposers": ["simple_seeded_nonadaptive", "response_gp"],
                    "confirmation_status": "not_loaded_not_scored",
                }
                for package in packages
            ],
        }
    else:
        payload = {
            "status": "development_executed_confirmation_not_loaded",
            "results": [
                comparison_as_dict(run_development_comparison(package, enabled=True))
                for package in packages
            ],
        }
    if args.output is not None:
        write_json_atomic(args.output.expanduser().resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
