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
from factor_factory.miner.research_queue import build_research_queue


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Factor Forge Miner research queue.")
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--workspace-root", required=True)
    ap.add_argument("--cheap-screen-summary", required=True)
    args = ap.parse_args()
    queue = build_research_queue(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        cheap_screen_summary=read_json(Path(args.cheap_screen_summary)),
    )
    print(json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
