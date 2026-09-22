#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_ultimate_shadow import (  # noqa: E402
    HOOKS,
    run_ultimate_epistemic_shadow,
)
from factor_factory.research_org.contracts import strict_json_loads  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one candidate-only Factor Forge epistemic observation sidecar. "
            "This command cannot alter the formal Ultimate proof or verdict."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--hook", choices=sorted(HOOKS), required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--formal-proof", type=Path, default=None)
    parser.add_argument("--formal-proof-raw-sha256", default=None)
    parser.add_argument("--formal-artifact-snapshot-json", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        formal_artifact_snapshot = (
            strict_json_loads(
                args.formal_artifact_snapshot_json.encode("utf-8"),
                label="formal-artifact-snapshot-cli",
            )
            if args.formal_artifact_snapshot_json is not None
            else None
        )
        receipt = run_ultimate_epistemic_shadow(
            manifest_path=args.manifest.expanduser(),
            request_path=args.request.expanduser(),
            hook=args.hook,
            report_id=args.report_id,
            repo_root=REPO_ROOT,
            formal_proof_path=(
                args.formal_proof.expanduser() if args.formal_proof else None
            ),
            formal_proof_raw_sha256=args.formal_proof_raw_sha256,
            formal_artifact_snapshot=formal_artifact_snapshot,
        )
    except Exception as exc:
        print(f"BLOCK_FACTORFORGE_EPISTEMIC_SHADOW: {exc}", file=sys.stderr)
        return 2
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
