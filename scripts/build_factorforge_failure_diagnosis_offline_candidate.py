#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_failure_diagnosis_offline import (
    validate_failure_diagnosis_offline_candidate_packet,
    write_failure_diagnosis_offline_candidate_packet,
)
from factor_factory.epistemic_source_first_offline import read_stable_regular_bytes


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build and validate a standalone, offline failure-diagnosis "
            "planner candidate packet from an explicit fixture."
        )
    )
    parser.add_argument("--phase-safe-manifest", required=True)
    parser.add_argument("--diagnosis-fixture", required=True)
    parser.add_argument("--assertion-dependency-fixture", required=True)
    parser.add_argument("--revision-predecessor-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    phase_safe_manifest_path = Path(args.phase_safe_manifest)
    diagnosis_fixture_path = Path(args.diagnosis_fixture)
    assertion_dependency_fixture_path = Path(args.assertion_dependency_fixture)
    revision_predecessor_manifest_path = Path(args.revision_predecessor_manifest)
    output_root = Path(args.output_root)

    write_failure_diagnosis_offline_candidate_packet(
        output_root,
        phase_safe_manifest_path=phase_safe_manifest_path,
        diagnosis_fixture_path=diagnosis_fixture_path,
        assertion_dependency_fixture_path=assertion_dependency_fixture_path,
        revision_predecessor_manifest_path=revision_predecessor_manifest_path,
    )
    manifest_path = output_root / "packet_manifest.json"
    manifest = validate_failure_diagnosis_offline_candidate_packet(
        manifest_path,
        phase_safe_manifest_path=phase_safe_manifest_path,
        diagnosis_fixture_path=diagnosis_fixture_path,
        assertion_dependency_fixture_path=assertion_dependency_fixture_path,
        revision_predecessor_manifest_path=revision_predecessor_manifest_path,
    )
    manifest_raw = read_stable_regular_bytes(
        manifest_path,
        label="packet_manifest",
        max_bytes=4 * 1024 * 1024,
        require_private=True,
    )
    print(
        json.dumps(
            {
                "content_sha": manifest["content_sha256"],
                "manifest_path": str(manifest_path.resolve(strict=True)),
                "raw_sha": hashlib.sha256(manifest_raw).hexdigest(),
                "status": manifest["manifest_status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
