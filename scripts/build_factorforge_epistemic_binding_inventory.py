#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).absolute().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_binding import (
    build_rejected_validation_receipt,
    write_stage1a_inventory_bundle,
)


class ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("ARGUMENT_PARSE_FAILED")


def main() -> int:
    parser = ClosedArgumentParser(
        description="Compile the frozen Stage1A-PREP inventory and blank readback template."
    )
    parser.add_argument("--p0-packet", required=True)
    parser.add_argument(
        "--output-root",
        required=True,
        help="Absolute path for a new atomically published bundle directory.",
    )
    try:
        args = parser.parse_args()
        result = write_stage1a_inventory_bundle(
            packet_root=Path(args.p0_packet),
            output_root=Path(args.output_root),
        )
    except Exception:  # Last-resort fail-closed CLI boundary.
        receipt = build_rejected_validation_receipt(boundary="BUILD_CLI")
        print(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
