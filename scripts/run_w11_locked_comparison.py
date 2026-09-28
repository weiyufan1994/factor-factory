#!/usr/bin/env python3
"""Inspect or explicitly execute the frozen one-shot W11 comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.hybrid_research.w11_locked_driver import (
    _plan_identity,
    _public_plan_projection,
    execute_plan_once,
    locked_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--execute-once", action="store_true")
    args = parser.parse_args()
    plan = locked_plan()
    if args.execute_once:
        payload = execute_plan_once(plan, args.output_root)
    else:
        payload = {
            "status": "validated_plan_not_generated_not_executed",
            "output_root": str(args.output_root.expanduser().resolve()),
            "plan_identity": _plan_identity(plan),
            "plan": _public_plan_projection(plan),
            "next": "independent review is required before --execute-once",
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
