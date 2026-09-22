#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.oos_exposure_incident import (
    register_oos_exposure_incident_host_private,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Host-register an existing public OOS exposure incident in signed "
            "private append-only negative state. This recovery command never "
            "restores formal-OOS authority."
        )
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        required=True,
        help="Factor workspace that already contains the public incident marker.",
    )
    parser.add_argument(
        "--report-id",
        required=True,
        help="Report identity bound by the existing incident marker.",
    )
    parser.add_argument(
        "--trust-root",
        type=Path,
        required=True,
        help="Host-private trust root outside the factor workspace.",
    )
    parser.add_argument(
        "--installation-id",
        required=True,
        help="Host installation identity bound to the signed private registry.",
    )
    args = parser.parse_args()
    result = register_oos_exposure_incident_host_private(
        workspace_root=args.workspace_root,
        report_id=args.report_id,
        trust_root=args.trust_root,
        installation_id=args.installation_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
