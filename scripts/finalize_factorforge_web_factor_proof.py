#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.web_factor_proof import finalize_web_factor_proof


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the web research OOS panel, replay formal metrics, and write "
            "a bound factor-proof certificate."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()

    workspace = Path(args.workspace_root).expanduser().resolve(strict=True)
    plan_path = workspace / "identity" / "web_research_plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise ValueError("web research plan must be a JSON object")
        if str((plan.get("identity") or {}).get("report_id") or "") != args.report_id:
            raise ValueError("BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_IDENTITY_MISMATCH")
        result = finalize_web_factor_proof(
            workspace_root=workspace,
            plan=plan,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "block_token": (
                        "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_FINALIZATION_FAILED"
                    ),
                    "block_reasons": [str(exc)],
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
