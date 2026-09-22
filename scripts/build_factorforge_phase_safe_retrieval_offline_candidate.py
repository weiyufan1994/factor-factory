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

from factor_factory.epistemic_phase_safe_retrieval_offline import (
    validate_phase_safe_retrieval_offline_candidate_packet,
    write_phase_safe_retrieval_offline_candidate_packet,
)
from factor_factory.epistemic_source_first_offline import read_stable_regular_bytes
from factor_factory.research_org.contracts import strict_json_loads


FIXTURE_SCHEMA_ID = "factorforge_phase_safe_retrieval_fixture_input_v1"


def _load_corpus_fixture(path: Path) -> list[object]:
    raw = read_stable_regular_bytes(
        path,
        label="corpus_fixture",
        max_bytes=16 * 1024 * 1024,
    )
    payload = strict_json_loads(raw, label=str(path))
    if not isinstance(payload, dict):
        raise ValueError("corpus_fixture:object_required")
    expected_fields = {"schema_id", "objects"}
    if set(payload) != expected_fields:
        raise ValueError(
            "corpus_fixture:closed_fields:"
            f"expected={sorted(expected_fields)!r}:actual={sorted(payload)!r}"
        )
    if payload["schema_id"] != FIXTURE_SCHEMA_ID:
        raise ValueError("corpus_fixture:schema_id")
    objects = payload["objects"]
    if not isinstance(objects, list):
        raise ValueError("corpus_fixture:objects_array_required")
    return objects


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build and validate a standalone, offline phase-safe retrieval "
            "candidate packet from an explicit corpus fixture."
        )
    )
    parser.add_argument("--source-first-manifest", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--corpus-fixture", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    source_first_manifest_path = Path(args.source_first_manifest)
    source_path = Path(args.source_path)
    output_root = Path(args.output_root)
    corpus_objects = _load_corpus_fixture(Path(args.corpus_fixture))

    write_phase_safe_retrieval_offline_candidate_packet(
        output_root,
        source_first_manifest_path=source_first_manifest_path,
        source_path=source_path,
        corpus_objects=corpus_objects,
    )
    manifest_path = output_root / "packet_manifest.json"
    manifest = validate_phase_safe_retrieval_offline_candidate_packet(
        manifest_path,
        source_first_manifest_path=source_first_manifest_path,
        source_path=source_path,
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
                "manifest_path": str(manifest_path.resolve(strict=True)),
                "manifest_raw_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                "manifest_content_sha256": manifest["content_sha256"],
                "status": manifest["manifest_status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
