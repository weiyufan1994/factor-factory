#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.pre_oos_human_bridge import (
    PreOosHumanBridgeError,
    materialize_pre_oos_human_bridge,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an external-human EVO V2 pre-OOS approval and materialize "
            "only its closed child handoff/intent records. This command never "
            "starts or releases the child."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--human-approval-receipt", required=True)
    parser.add_argument("--human-trust-manifest-sha256", required=True)
    parser.add_argument("--host-trust-root", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--incident-trust-root", required=True)
    parser.add_argument("--incident-installation-id", required=True)
    parser.add_argument("--admissions-root")
    args = parser.parse_args()
    try:
        result = materialize_pre_oos_human_bridge(
            workspace_root=args.workspace_root,
            report_id=args.report_id,
            human_approval_receipt=args.human_approval_receipt,
            human_trust_manifest_sha256=args.human_trust_manifest_sha256,
            host_trust_root=args.host_trust_root,
            installation_id=args.installation_id,
            incident_trust_root=args.incident_trust_root,
            incident_installation_id=args.incident_installation_id,
            admissions_root=args.admissions_root,
        )
    except (PreOosHumanBridgeError, OSError, ValueError) as exc:
        reasons = (
            exc.reasons
            if isinstance(exc, PreOosHumanBridgeError)
            else [
                f"BLOCK_FACTORFORGE_PRE_OOS_HUMAN_BRIDGE_INVALID:{type(exc).__name__}"
            ]
        )
        print(
            json.dumps(
                {"verdict": "BLOCK", "report_id": args.report_id, "reasons": reasons},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
