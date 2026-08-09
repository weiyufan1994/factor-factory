#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.miner.common import read_json
from factor_factory.miner.program_executor import execute_candidate_programs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute candidate-specific Factor Forge Miner programs."
    )
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--source-panel", required=True)
    parser.add_argument(
        "--data-split-manifest",
        required=True,
        help="Canonical pre-search IS/OOS split manifest.",
    )
    parser.add_argument("--artifact-tag", default="g00")
    args = parser.parse_args()
    report = execute_candidate_programs(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        candidate_manifest=read_json(Path(args.candidate_manifest)),
        source_panel_path=Path(args.source_panel),
        data_split_manifest_path=Path(args.data_split_manifest),
        artifact_tag=args.artifact_tag,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("executed_program_hashes") else 1


if __name__ == "__main__":
    raise SystemExit(main())
