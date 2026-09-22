#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.worker_execution import run_task_spec


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a versioned worker task spec and write worker_command_report_v1.")
    parser.add_argument("task_spec", help="Path to worker_task_spec_v1 JSON.")
    parser.add_argument("--report-path", default=None, help="Optional output path for worker_command_report_v1 JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Validate/preflight and render command without executing the runner.")
    parser.add_argument("--preflight-only", action="store_true", help="Run preflight checks only.")
    args = parser.parse_args()
    rc, report = run_task_spec(args.task_spec, report_path=args.report_path, dry_run=args.dry_run, preflight_only=args.preflight_only)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

