#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.miner.data_split import write_data_split_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the canonical IS/OOS split for a Miner campaign."
    )
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--is-panel", required=True)
    parser.add_argument("--is-window-id", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--oos-panel", action="append", required=True)
    parser.add_argument("--oos-window-id", action="append", required=True)
    parser.add_argument(
        "--oos-release-state",
        action="append",
        choices=["SEALED_UNRELEASED"],
    )
    args = parser.parse_args()
    if len(args.oos_panel) != len(args.oos_window_id):
        raise SystemExit("--oos-panel and --oos-window-id counts must match")
    states = args.oos_release_state or ["SEALED_UNRELEASED"] * len(
        args.oos_panel
    )
    if len(states) != len(args.oos_panel):
        raise SystemExit("--oos-release-state count must match --oos-panel")
    path, payload = write_data_split_manifest(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        is_panel_path=Path(args.is_panel),
        is_window_id=args.is_window_id,
        universe_id=args.universe,
        oos_windows=[
            {
                "panel_path": Path(panel),
                "window_id": window_id,
                "release_state": release_state,
            }
            for panel, window_id, release_state in zip(
                args.oos_panel,
                args.oos_window_id,
                states,
            )
        ],
    )
    print(
        json.dumps(
            {"manifest_path": str(path), "manifest": payload},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
