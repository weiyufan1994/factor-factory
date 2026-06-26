#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.miner.candidates import build_candidate_packets
from factor_factory.miner.common import read_json


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Factor Forge Miner candidate packets.")
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--workspace-root", required=True)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--template-id", action="append", default=[])
    args = ap.parse_args()
    inventory = read_json(Path(args.inventory))
    packets = build_candidate_packets(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        template_ids=list(args.template_id),
        inventory=inventory,
    )
    print(json.dumps({"candidate_count": len(packets), "candidates": packets}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
