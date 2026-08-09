#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_org import ResearchOrganizationError
from factor_factory.researcher_memory import record_candidate_review


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Admit a pre-existing adapter-signed independent review of one "
            "workspace-local memory candidate. This command does not run a reviewer."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--candidate", required=True, help="Workspace-relative candidate path.")
    parser.add_argument("--memory-root", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--decision", required=True, choices=("APPROVE_CANONICAL", "REJECT"))
    parser.add_argument(
        "--reviewer-session-receipt",
        required=True,
        help=(
            "Host-private runtime-adapter receipt produced by an already completed "
            "independent reviewer session; operator-authored receipts are invalid."
        ),
    )
    parser.add_argument("--outcome-event-id", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--trust-root",
        help="Host-private research organization trust store. Defaults beside memory-root.",
    )
    args = parser.parse_args()
    try:
        memory_root = Path(args.memory_root).expanduser()
        state_root = memory_root.resolve(strict=False).parent
        receipt_path = Path(args.reviewer_session_receipt).expanduser()
        if receipt_path.is_symlink():
            raise ValueError("reviewer session receipt must not be a symlink")
        receipt_path = receipt_path.resolve(strict=True)
        receipt_relative = receipt_path.relative_to(state_root).as_posix()
        result = record_candidate_review(
            workspace=Path(args.workspace_root).expanduser().resolve(strict=True),
            candidate_relative=args.candidate,
            root=memory_root,
            installation_id=args.installation_id,
            decision=args.decision,
            reviewer_session_receipt_ref={
                "id": receipt_relative,
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            },
            outcome_event_id=args.outcome_event_id,
            rationale=args.rationale,
            repo_root=Path(args.repo_root).expanduser().resolve(strict=False),
            trust_root=(Path(args.trust_root).expanduser() if args.trust_root else None),
        )
    except (OSError, ValueError, ResearchOrganizationError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
