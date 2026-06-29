#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.static_app import serve_console  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the read-only Factor Forge Console.")
    parser.add_argument("--root", action="append", required=True, help="Repo or worktree root to scan.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    print(f"Factor Forge Console running at http://{args.host}:{args.port}", flush=True)
    serve_console([Path(root) for root in args.root], args.host, args.port)


if __name__ == "__main__":
    main()
