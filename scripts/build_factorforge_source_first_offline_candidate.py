#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_source_first_offline import (
    SourceFirstOfflineError,
    read_stable_regular_bytes,
    write_source_first_offline_candidate_packet,
)
from factor_factory.research_org.contracts import strict_json_loads


def _load_config(path: Path) -> dict:
    raw = read_stable_regular_bytes(
        path,
        label="config",
        max_bytes=4 * 1024 * 1024,
    )
    payload = strict_json_loads(raw, label=str(path))
    if not isinstance(payload, dict):
        raise SourceFirstOfflineError(["config:object_required"])
    expected = {
        "source_lineage",
        "author_claims",
        "analyst_notes",
        "selected_semantic_body",
        "pre_a0_predictions",
        "phase_policy_candidate",
    }
    if set(payload) != expected:
        raise SourceFirstOfflineError(
            [f"config:closed_fields:expected={sorted(expected)!r}:actual={sorted(payload)!r}"]
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local, offline Source-First blind-handoff candidate packet. "
            "This command does not execute retrieval or access Host, memory, OOS, "
            "Skill runtime, or deployment systems."
        )
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    try:
        config = _load_config(Path(args.config))
        manifest = write_source_first_offline_candidate_packet(
            Path(args.output_root),
            source_path=Path(args.source),
            **config,
        )
    except (SourceFirstOfflineError, FileExistsError, OSError) as exc:
        reasons = getattr(exc, "reasons", [str(exc)])
        print(
            json.dumps(
                {"status": "BLOCKED", "reasons": list(reasons)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": manifest["manifest_status"],
                "packet_id": manifest["packet_id"],
                "artifact_count": manifest["artifact_count"],
                "permissions_opened_count": manifest["permissions_opened_count"],
                "authority_effect": manifest["authority_effect"],
                "output_root": str(Path(args.output_root)),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
