#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_ultimate_source_first_bridge import (  # noqa: E402
    run_and_validate_source_first_advisory,
    run_source_first_advisory_bridge,
)


from factor_factory.startup_experience import emit_startup_advisory, record_operational_failure


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the candidate-only Source-First advisory bridge. The research "
            "agent authors source semantics; RAG paths and session handles are "
            "managed internally and never supplied by the user."
        )
    )
    parser.add_argument("--factor-workspace", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--source-first-overlay", type=Path, required=True)
    parser.add_argument(
        "--emit-validated-advisory",
        action="store_true",
        help=(
            "Run the bridge and dedicated validator in one operation; emit only "
            "the validator's in-memory advisory JSON bytes instead of a receipt path."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runner = (
            run_and_validate_source_first_advisory
            if args.emit_validated_advisory
            else run_source_first_advisory_bridge
        )
        result = runner(
            workspace=args.factor_workspace.expanduser(),
            overlay_path=args.source_first_overlay.expanduser(),
            report_id=args.report_id,
        )
    except Exception as exc:
        if isinstance(exc, OSError):
            try:
                failure = record_operational_failure(args.factor_workspace, args.source_first_overlay,
                    args.report_id, exc, REPO_ROOT)
                import json
                print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
            except Exception:
                pass  # Original failure remains; invalid source never gains an outage receipt.
        print(
            f"BLOCK_FACTORFORGE_EPISTEMIC_SOURCE_FIRST_ADVISORY: {exc}",
            file=sys.stderr,
        )
        return 2
    if args.emit_validated_advisory:
        sys.stdout.buffer.write(emit_startup_advisory(result, REPO_ROOT))
        sys.stdout.buffer.flush()
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
