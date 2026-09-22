#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.evo_pre_oos_orchestrator import (
    ALLOWED_OUTCOMES,
    BLOCK_PRE_OOS_ORCHESTRATION,
    PreOosOutcomeOrchestrationError,
    orchestrate_pre_oos_council_outcome,
)
from factor_factory.evo_v2 import EvoV2Error


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Host-only orchestration of one canonical pre-OOS Council outcome "
            "through signed lifecycle CAS and staged EVO V2 materialization."
        )
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument(
        "--expected-transition-state",
        choices=sorted(ALLOWED_OUTCOMES),
        required=True,
    )
    parser.add_argument("--expected-qualified-lifecycle-sha256", required=True)
    parser.add_argument("--trust-root", type=Path, required=True)
    parser.add_argument("--installation-id", required=True)
    args = parser.parse_args()
    try:
        result = orchestrate_pre_oos_council_outcome(
            workspace_root=args.workspace_root,
            report_id=args.report_id,
            expected_transition_state=args.expected_transition_state,
            expected_qualified_lifecycle_sha256=(
                args.expected_qualified_lifecycle_sha256
            ),
            trust_root=args.trust_root,
            installation_id=args.installation_id,
        )
    except (
        EvoV2Error,
        PreOosOutcomeOrchestrationError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        reasons = getattr(exc, "reasons", None)
        if not isinstance(reasons, list) or not reasons:
            reasons = [f"{BLOCK_PRE_OOS_ORCHESTRATION}:{type(exc).__name__}"]
        print(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "report_id": args.report_id,
                    "block_reasons": reasons,
                    "host_transition_performed": False,
                    "human_approval_granted": False,
                    "child_execution_allowed": False,
                    "oos_accessed": False,
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
