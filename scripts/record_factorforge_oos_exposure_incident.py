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
    build_oos_exposure_incident,
    record_oos_exposure_incident_durable,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record a create-only OOS exposure incident. This command emits "
            "negative evidence only and can never authorize formal OOS use."
        )
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--factor-id", required=True)
    parser.add_argument("--frozen-oos-start", required=True)
    parser.add_argument("--frozen-oos-end", required=True)
    parser.add_argument("--frozen-oos-release-token-sha256", required=True)
    parser.add_argument("--exposed-overlap-start", required=True)
    parser.add_argument("--exposed-overlap-end", required=True)
    parser.add_argument("--exposed-row-count", type=int, required=True)
    parser.add_argument("--exposed-period-count", type=int, required=True)
    parser.add_argument("--source-path", type=Path, required=True)
    parser.add_argument("--panel-path", type=Path, required=True)
    parser.add_argument("--metrics-path", type=Path, required=True)
    parser.add_argument("--runner-path", type=Path, required=True)
    parser.add_argument(
        "--host-trust-root",
        type=Path,
        required=True,
        help="Host-private trust root outside the factor workspace.",
    )
    parser.add_argument("--installation-id", required=True)
    parser.add_argument(
        "--incident-at",
        required=True,
        help="UTC ISO-8601 timestamp ending in Z; fixed input preserves exact idempotence.",
    )
    args = parser.parse_args()

    payload = build_oos_exposure_incident(
        workspace_root=args.workspace_root,
        report_id=args.report_id,
        factor_id=args.factor_id,
        frozen_oos_start=args.frozen_oos_start,
        frozen_oos_end=args.frozen_oos_end,
        frozen_oos_release_token_sha256=(
            args.frozen_oos_release_token_sha256
        ),
        exposed_overlap_start=args.exposed_overlap_start,
        exposed_overlap_end=args.exposed_overlap_end,
        exposed_row_count=args.exposed_row_count,
        exposed_period_count=args.exposed_period_count,
        source_path=args.source_path,
        panel_path=args.panel_path,
        metrics_path=args.metrics_path,
        runner_path=args.runner_path,
        incident_at=args.incident_at,
    )
    result = record_oos_exposure_incident_durable(
        workspace_root=args.workspace_root,
        payload=payload,
        trust_root=args.host_trust_root,
        installation_id=args.installation_id,
    )
    printable = {
        **result,
        "path": str(result["public"]["path"]),
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
