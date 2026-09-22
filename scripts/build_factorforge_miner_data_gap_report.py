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
from factor_factory.miner.data_gap import build_data_gap_report


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Factor Forge Miner data gap report.")
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--workspace-root", required=True)
    ap.add_argument("--candidate-manifest", required=True)
    ap.add_argument("--inventory", required=True)
    args = ap.parse_args()
    manifest = read_json(Path(args.candidate_manifest))
    report = build_data_gap_report(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        candidates=list(manifest.get("candidates", [])),
        inventory=read_json(Path(args.inventory)),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
