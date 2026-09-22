#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_ultimate_source_first_bridge import (  # noqa: E402
    validate_source_first_advisory_package,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a Source-First advisory exact3 package. The chief advisory "
            "path is emitted only after every live binding and rebuilt byte passes."
        )
    )
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validated = validate_source_first_advisory_package(
            receipt_path=args.receipt.expanduser(),
        )
    except Exception as exc:
        print(
            f"BLOCK_FACTORFORGE_EPISTEMIC_SOURCE_FIRST_ADVISORY_CONSUMPTION: {exc}",
            file=sys.stderr,
        )
        return 2
    sys.stdout.buffer.write(validated.chief_advisory_raw)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
