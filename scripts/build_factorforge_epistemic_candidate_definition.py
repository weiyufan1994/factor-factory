#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_candidate_definition_generation import (
    CandidateDefinitionGenerationError,
    write_candidate_definition_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the offline, R14-bound exact160 candidate definition. "
            "The output is unsigned, inactive, and nonauthorizing."
        )
    )
    parser.add_argument("--r14-manifest", required=True)
    parser.add_argument("--r14-review-manifest", required=True)
    parser.add_argument("--h1-manifest", required=True)
    parser.add_argument("--h1-review-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    try:
        manifest = write_candidate_definition_packet(
            Path(args.output_root),
            r14_manifest_path=Path(args.r14_manifest),
            r14_review_manifest_path=Path(args.r14_review_manifest),
            h1_manifest_path=Path(args.h1_manifest),
            h1_review_manifest_path=Path(args.h1_review_manifest),
        )
    except (CandidateDefinitionGenerationError, FileExistsError) as exc:
        reasons = getattr(exc, "reasons", [str(exc)])
        print(json.dumps({"status": "BLOCKED", "reasons": reasons}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "CANDIDATE_GENERATED__NO_AUTHORITY_EFFECT",
                "output_root": str(Path(args.output_root)),
                "packet_id": manifest["packet_id"],
                "candidate_definition_generation_id": manifest[
                    "candidate_definition_generation_id"
                ],
                "candidate_definition_generation_content_sha256": manifest[
                    "candidate_definition_generation_content_sha256"
                ],
                "definition_content_sha256": manifest["definition_content_sha256"],
                "definition_bytes_manifest_sha256": manifest[
                    "definition_bytes_manifest_sha256"
                ],
                "authority_effect": manifest["authority_effect"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
