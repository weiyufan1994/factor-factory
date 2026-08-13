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
    build_oos_exposure_provenance_addendum,
    write_oos_exposure_provenance_addendum_create_only,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record a create-only provenance correction when the original "
            "runner bytes for an OOS exposure incident are unavailable. This "
            "never restores formal-OOS authority."
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
        "--correction-at",
        required=True,
        help=(
            "Fixed UTC ISO-8601 timestamp ending in Z; reuse the same value "
            "for an exact idempotent replay."
        ),
    )
    args = parser.parse_args()
    payload = build_oos_exposure_provenance_addendum(
        workspace_root=args.workspace_root,
        report_id=args.report_id,
        correction_at=args.correction_at,
    )
    result = write_oos_exposure_provenance_addendum_create_only(
        workspace_root=args.workspace_root,
        payload=payload,
    )
    print(
        json.dumps(
            {**result, "path": str(result["path"])},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
