#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.evo_oos import build_and_allocate_fresh_child_oos


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Host-only sealed-carrier build, signed append and CAS allocator "
            "for a child-specific fresh EVO V2 OOS window. Raw, derived and "
            "release-token hashes are computed internally."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--allocation-id", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--parent-report-id", required=True)
    parser.add_argument("--oos-start", required=True)
    parser.add_argument("--oos-end", required=True)
    parser.add_argument("--sealed-oos-carrier", required=True)
    parser.add_argument("--sealed-oos-private-root", required=True)
    parser.add_argument(
        "--sealed-oos-agent-visible-root", action="append", default=[]
    )
    parser.add_argument(
        "--expected-registry-sha256",
        required=True,
        help="Current registry file SHA-256, or ABSENT for the first append.",
    )
    parser.add_argument("--trust-root", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--admissions-root")
    args = parser.parse_args()
    expected = (
        None
        if args.expected_registry_sha256 == "ABSENT"
        else args.expected_registry_sha256
    )
    try:
        result = build_and_allocate_fresh_child_oos(
            workspace_root=Path(args.workspace_root),
            allocation_id=args.allocation_id,
            report_id=args.report_id,
            parent_report_id=args.parent_report_id,
            oos_start=args.oos_start,
            oos_end=args.oos_end,
            sealed_oos_carrier_path=Path(args.sealed_oos_carrier),
            sealed_oos_private_root=Path(args.sealed_oos_private_root),
            agent_visible_roots=[
                Path(item) for item in args.sealed_oos_agent_visible_root
            ],
            expected_registry_sha256=expected,
            trust_root=Path(args.trust_root),
            installation_id=args.installation_id,
            admissions_root=(
                Path(args.admissions_root) if args.admissions_root else None
            ),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
