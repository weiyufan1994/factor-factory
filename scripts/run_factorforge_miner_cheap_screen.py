#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.miner.cheap_screen import run_cheap_screen


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Factor Forge Miner cheap screen.")
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--workspace-root", required=True)
    ap.add_argument("--candidate-manifest", required=True)
    ap.add_argument("--panel", required=True)
    ap.add_argument(
        "--program-execution-report",
        required=True,
        help="Executor report whose replayed output must match --panel.",
    )
    ap.add_argument("--screen-window", required=True)
    ap.add_argument("--universe", default="unknown")
    ap.add_argument(
        "--search-control",
        required=True,
        help="JSON file with sealed-OOS, trial-budget, multiplicity, cost, capacity, and regime controls.",
    )
    ap.add_argument(
        "--allow-fixture-shared-signal",
        action="store_true",
        help="Smoke-only compatibility mode; outputs are ineligible for the research queue.",
    )
    args = ap.parse_args()
    summary = run_cheap_screen(
        campaign_id=args.campaign_id,
        workspace_root=Path(args.workspace_root),
        candidate_manifest_path=Path(args.candidate_manifest),
        panel_path=Path(args.panel),
        program_execution_report_path=Path(
            args.program_execution_report
        ),
        screen_window=args.screen_window,
        universe=args.universe,
        search_control=json.loads(
            Path(args.search_control).expanduser().read_text(encoding="utf-8")
        ),
        allow_fixture_shared_signal=args.allow_fixture_shared_signal,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
