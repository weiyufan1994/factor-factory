#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.worker_execution import load_json, validate_worker_command_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a worker_command_report_v1 and distinguish transport success from business success.")
    parser.add_argument("report", help="Path to worker_command_report_v1 JSON.")
    parser.add_argument("--output", default=None, help="Optional output path for validation JSON.")
    args = parser.parse_args()
    report_path = Path(args.report).expanduser().resolve()
    validation = validate_worker_command_report(load_json(report_path))
    payload = json.dumps(validation, ensure_ascii=False, indent=2)
    if args.output:
        out = Path(args.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if validation.get("verdict") == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
