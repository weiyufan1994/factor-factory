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
    INCOMPLETE_VERDICT,
    build_rejected_validation_receipt,
    validate_stage1a_files,
)


class ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("ARGUMENT_PARSE_FAILED")


def main() -> int:
    parser = ClosedArgumentParser(
        description="Offline-validate a frozen Stage1A-PREP inventory and blank template."
    )
    parser.add_argument("--p0-packet", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--template", required=True)
    try:
        args = parser.parse_args()
        receipt = validate_stage1a_files(
            packet_root=Path(args.p0_packet),
            inventory_path=Path(args.inventory),
            template_path=Path(args.template),
        )
    except Exception:  # Last-resort fail-closed CLI boundary.
        receipt = build_rejected_validation_receipt(boundary="VALIDATE_CLI")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt.get("validation_status") == INCOMPLETE_VERDICT else 1


if __name__ == "__main__":
    raise SystemExit(main())
