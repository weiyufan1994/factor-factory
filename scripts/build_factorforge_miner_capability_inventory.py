#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.miner.capability_inventory import build_capability_inventory


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Factor Forge Miner capability inventory.")
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--workspace-root", required=True)
    ap.add_argument("--catalog", action="append", default=[])
    args = ap.parse_args()
    payload = build_capability_inventory(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        catalog_paths=[Path(value) for value in args.catalog],
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
