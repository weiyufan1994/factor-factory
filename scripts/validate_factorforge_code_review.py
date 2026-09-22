#!/usr/bin/env python3
"""Read-only local-IS code-review checkpoint; never creates review evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Running this read-only command must not create import-cache artifacts.
sys.dont_write_bytecode = True
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.code_review_checkpoint import validate_code_review


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps({"status": "BLOCK", "reasons": [f"CLI_ARGUMENTS_INVALID:{message}"]}))
        raise SystemExit(1)


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--repo-root", help="Resolve only explicitly repo-based helper references.")
    args = parser.parse_args()
    result = validate_code_review(
        workspace_root=args.workspace_root,
        report_id=args.report_id,
        handoff=args.handoff,
        spec=args.spec,
        repo_root=args.repo_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
