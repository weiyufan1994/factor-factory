#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_dual_steward_review_handoff import (
    DualStewardReviewHandoffError,
    write_dual_steward_review_handoff_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare exact2 unsigned steward review requests and a read-only local "
            "Git landing readback. This command never submits, signs, or authorizes."
        )
    )
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--r14-manifest", required=True)
    parser.add_argument("--r14-review-manifest", required=True)
    parser.add_argument("--h1-manifest", required=True)
    parser.add_argument("--h1-review-manifest", required=True)
    parser.add_argument("--revision-predecessor-manifest", required=True)
    parser.add_argument("--ontology-repo", required=True)
    parser.add_argument("--reference-repo", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    try:
        manifest = write_dual_steward_review_handoff_packet(
            Path(args.output_root),
            candidate_manifest_path=Path(args.candidate_manifest),
            r14_manifest_path=Path(args.r14_manifest),
            r14_review_manifest_path=Path(args.r14_review_manifest),
            h1_manifest_path=Path(args.h1_manifest),
            h1_review_manifest_path=Path(args.h1_review_manifest),
            revision_predecessor_manifest_path=Path(args.revision_predecessor_manifest),
            ontology_repo=Path(args.ontology_repo),
            reference_repo=Path(args.reference_repo),
        )
    except (DualStewardReviewHandoffError, FileExistsError) as exc:
        reasons = getattr(exc, "reasons", [str(exc)])
        print(json.dumps({"status": "BLOCKED", "reasons": reasons}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": manifest["manifest_status"],
                "output_root": str(Path(args.output_root)),
                "packet_id": manifest["packet_id"],
                "request_count": manifest["request_count"],
                "local_repository_observation_count": manifest[
                    "local_repository_observation_count"
                ],
                "permissions_opened_count": manifest["permissions_opened_count"],
                "authority_effect": manifest["authority_effect"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
