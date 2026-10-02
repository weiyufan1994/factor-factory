#!/usr/bin/env python3
"""Inspect or run the locked W08 hybrid-research comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.hybrid_research.evaluation_v2 import (
    protocol_manifest,
    report_as_dict,
    run_locked_evaluation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--run-development",
        action="store_true",
        help="run planning with development evidence but do not read held-out scores",
    )
    mode.add_argument(
        "--run-final",
        action="store_true",
        help="run the frozen held-out comparison after protocol review",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.run_development or args.run_final:
        payload = report_as_dict(run_locked_evaluation(include_final=args.run_final))
    else:
        payload = {
            "mode": "protocol_only",
            "final_results_read": False,
            "protocol": protocol_manifest(),
        }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
