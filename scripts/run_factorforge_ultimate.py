#!/usr/bin/env python3
"""Compatibility CLI for the installed Ultimate research runner."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.ultimate_loop.cli import parse_args


def _run_formal_ultimate(args):
    from factor_factory.ultimate_loop.runner import _run_formal_ultimate as run
    return run(args)


def __getattr__(name):
    # Preserve historical imports; the CLI itself only loads the chosen mode.
    from factor_factory.ultimate_loop import runner
    return getattr(runner, name)


def main() -> int:
    return _run_formal_ultimate(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
