#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.revision_council.pre_oos_outcome import (
    PreOosCouncilOutcomeError,
    materialize_pre_oos_council_outcome,
    pre_oos_outcome_evidence_reference,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an agent-authored pre-OOS Council root selection and "
            "materialize a Host-verifiable review-only evidence report."
        )
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--synthesis", type=Path, default=None)
    parser.add_argument(
        "--validate-existing",
        action="store_true",
        help="Replay an already materialized report instead of writing it.",
    )
    parser.add_argument(
        "--expected-transition-state",
        choices=("MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"),
        default=None,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.validate_existing:
            reference, reasons = pre_oos_outcome_evidence_reference(
                workspace_root=args.workspace_root,
                report_id=args.report_id,
                expected_transition_state=args.expected_transition_state,
            )
            if reasons or reference is None:
                raise PreOosCouncilOutcomeError(reasons)
            result = {
                "result": "PASS",
                "mode": "validated_existing",
                "evidence_ref": reference,
                "host_transition_performed": False,
                "human_approval_granted": False,
            }
        else:
            if args.synthesis is None:
                raise PreOosCouncilOutcomeError(
                    [
                        "BLOCK_FACTORFORGE_PRE_OOS_COUNCIL_OUTCOME_INVALID:"
                        "synthesis_path_required"
                    ]
                )
            result = materialize_pre_oos_council_outcome(
                workspace_root=args.workspace_root,
                report_id=args.report_id,
                synthesis_path=args.synthesis,
            )
            if (
                args.expected_transition_state is not None
                and result.get("authorized_host_transition_state")
                != args.expected_transition_state
            ):
                raise PreOosCouncilOutcomeError(
                    [
                        "BLOCK_FACTORFORGE_PRE_OOS_COUNCIL_OUTCOME_INVALID:"
                        "expected_transition_state_mismatch"
                    ]
                )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (PreOosCouncilOutcomeError, OSError, RuntimeError, ValueError) as exc:
        reasons = getattr(exc, "reasons", [f"{type(exc).__name__}:{exc}"])
        print(
            json.dumps(
                {
                    "result": "BLOCK",
                    "report_id": args.report_id,
                    "block_reasons": reasons,
                    "host_transition_performed": False,
                    "human_approval_granted": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
