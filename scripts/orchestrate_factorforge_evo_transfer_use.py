#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from factor_factory.evo_transfer_use_orchestrator import (
    TransferUseOrchestrationError,
    orchestrate_evo_v2_transfer_use,
    validate_evo_v2_transfer_use_orchestration,
)
from factor_factory.evo_v2 import EvoV2Error
from factor_factory.research_org.contracts import ResearchOrganizationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Host-only MINIMAL_MECHANISM_DELTA to transfer/cold lifecycle, "
            "staging, transfer-use preregistration, and private-admission "
            "orchestrator."
        )
    )
    parser.add_argument("command", choices=("run", "validate"))
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--expected-minimal-lifecycle-sha256", required=True)
    parser.add_argument("--expected-staging-content-sha256", required=True)
    parser.add_argument("--trust-root", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--admissions-root")
    parser.add_argument("--experience-transfer-bundle")
    parser.add_argument("--transfer-use-receipt")
    parser.add_argument("--review-decision-receipt")
    parser.add_argument("--transfer-use-change-receipt")
    parser.add_argument("--cold-start-search-receipt")
    parser.add_argument("--execution-tests")
    return parser


def main() -> int:
    args = _parser().parse_args()
    common = {
        "workspace_root": Path(args.workspace_root),
        "report_id": args.report_id,
        "expected_minimal_lifecycle_sha256": (args.expected_minimal_lifecycle_sha256),
        "expected_staging_content_sha256": (args.expected_staging_content_sha256),
        "trust_root": Path(args.trust_root),
        "installation_id": args.installation_id,
        "admissions_root": (
            Path(args.admissions_root) if args.admissions_root else None
        ),
    }
    try:
        if args.command == "validate":
            result = validate_evo_v2_transfer_use_orchestration(**common)
        else:
            if not args.experience_transfer_bundle or not args.transfer_use_receipt:
                raise TransferUseOrchestrationError(
                    [
                        (
                            "BLOCK_FACTORFORGE_EVO_V2_TRANSFER_USE_"
                            "ORCHESTRATION_INVALID:core_input_paths_required"
                        )
                    ]
                )
            result = orchestrate_evo_v2_transfer_use(
                **common,
                experience_transfer_bundle_path=(args.experience_transfer_bundle),
                transfer_use_receipt_path=args.transfer_use_receipt,
                review_decision_receipt_path=args.review_decision_receipt,
                transfer_use_change_receipt_path=(args.transfer_use_change_receipt),
                cold_start_search_receipt_path=(args.cold_start_search_receipt),
                execution_tests_path=args.execution_tests,
            )
    except (
        TransferUseOrchestrationError,
        EvoV2Error,
        ResearchOrganizationError,
        OSError,
        ValueError,
    ) as exc:
        reasons = getattr(exc, "reasons", None)
        print(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "reasons": list(reasons) if reasons else [str(exc)],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
