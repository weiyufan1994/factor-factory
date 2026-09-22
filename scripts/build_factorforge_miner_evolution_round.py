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
from factor_factory.miner.evolution import build_evolution_round


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a verifier-bounded Factor Forge Miner evolution round."
    )
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--cheap-screen-summary", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--elite-limit", type=int, default=4)
    args = parser.parse_args()
    payload = build_evolution_round(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        candidate_manifest=read_json(Path(args.candidate_manifest)),
        cheap_screen_summary=read_json(Path(args.cheap_screen_summary)),
        generation=args.generation,
        elite_limit=args.elite_limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
