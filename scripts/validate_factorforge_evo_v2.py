#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.evo_v2 import (
    BLOCK_EVO_V2_INVALID,
    artifact_sha256,
    validate_materialized_evo_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the five canonical Factor Forge EVO V2 semantic artifacts, "
            "including canonical paths, hashes, authority, state, lower-layer "
            "clearance, Dirac minimality, experience transfer, and OOS non-use "
            "guards. This command does not validate child allocation, container "
            "execution, termination receipts, or the terminal checkpoint."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()

    try:
        root = Path(args.workspace_root).expanduser().resolve(strict=True)
        artifacts, reasons = validate_materialized_evo_v2(root, args.report_id)
    except OSError as exc:
        artifacts = {}
        reasons = [f"filesystem_error:{type(exc).__name__}:{exc}"]
    if reasons:
        print(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "block_token": BLOCK_EVO_V2_INVALID,
                    "report_id": args.report_id,
                    "block_reasons": reasons,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "verdict": "PASS",
                "report_id": args.report_id,
                "current_state": artifacts["feedback_ledger"]["current_state"],
                "mechanism_status": artifacts["mechanism_delta"]["status"],
                "transfer_status": artifacts["experience_transfer_bundle"]["status"],
                "receipt_status": artifacts["transfer_use_receipt"]["status"],
                "artifact_sha256": {
                    name: artifact_sha256(payload)
                    for name, payload in artifacts.items()
                },
                "formal_factor_verdict": "NOT_ISSUED",
                "canonical_write_allowed": False,
                "child_execution_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
