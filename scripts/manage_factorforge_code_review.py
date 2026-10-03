#!/usr/bin/env python3
"""Prepare/check a local journal handoff; actual sends and tests use agent tools."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from factor_factory.code_review_handoff import CodeReviewHandoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "delivery", "receive", "tests", "command-result", "recover-artifacts", "status"))
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--request-file", help="Author's preparation input; never executable commands")
    parser.add_argument("--request-id")
    parser.add_argument("--record", help="Actual reviewer result or actual post-review test record")
    parser.add_argument("--outcome", choices=("begin", "sent", "failed", "unknown"))
    parser.add_argument("--reference", help="Actual tool call/result locator, or a concrete failure reason")
    parser.add_argument("--retry-reason", default="")
    parser.add_argument("--step", choices=("4", "5"), help="Blocked writer stage for recover-artifacts")
    parser.add_argument("--proof", help="Original failed Ultimate wrapper report; never a newly invented receipt")
    parser.add_argument("--artifact-repair", help="Explicit file/directory reference correction JSON; no metrics or code changes")
    args = parser.parse_args()
    try:
        flow = CodeReviewHandoff(args.workspace_root, args.report_id, args.repo_root)
        if args.action == "prepare":
            if not args.request_file:
                raise ValueError("prepare needs --request-file")
            result = flow.prepare(json.loads(Path(args.request_file).read_text(encoding="utf-8")))
        elif args.action == "status":
            result = flow.status()
        else:
            if not args.request_id:
                raise ValueError("--request-id is required; stale handoffs cannot change current work")
            if args.action == "delivery":
                result = flow.delivery(args.request_id, args.outcome, args.reference, retry_reason=args.retry_reason)
            elif args.action == "recover-artifacts":
                if not args.step or not args.proof or not args.reference:
                    raise ValueError("recover-artifacts needs --step, --proof and actual tool/result --reference")
                result = flow.recover_artifacts(args.request_id, args.step,
                                                proof_path=args.proof, reference=args.reference, repair_path=args.artifact_repair)
            else:
                if not args.record:
                    raise ValueError("--record is required")
                if args.action == "command-result":
                    flow._active(args.request_id)
                    if not args.reference:
                        raise ValueError("Reconciling an interrupted command needs the actual tool/result --reference")
                    record_path = Path(args.record)
                    if not record_path.is_absolute():
                        record_path = flow.workspace / record_path
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    record["outcome_reference"] = args.reference
                    flow.record_command(record)
                    result = flow.status()
                else:
                    result = (flow.receive_review if args.action == "receive" else flow.record_tests)(args.request_id, args.record)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # A recorded pending/failed handoff is not a failed journal write or a PASS.
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "BLOCK", "reason": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
