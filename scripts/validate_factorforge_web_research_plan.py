#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:] = [item for item in sys.path if item != str(REPO_ROOT)]
sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.web_research_plan import (
    WebResearchPlanError,
    stable_json_hash,
    validate_plan,
)


def validate_authoring_plan(*, workspace: Path, plan_path: Path) -> dict[str, object]:
    workspace = workspace.expanduser().resolve(strict=True)
    plan_path = plan_path.expanduser().resolve(strict=True)
    plan_path.relative_to(workspace)
    if plan_path.is_symlink() or not plan_path.is_file():
        raise ValueError("plan path must be a regular file inside the workspace")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("web research plan must be a JSON object")
    _manifest, formula_ir = validate_plan(plan, workspace=workspace)
    return {
        "version": "factorforge_web_research_authoring_preflight_v1",
        "verdict": "PASS",
        "formal_research_started": False,
        "plan_semantic_sha256": stable_json_hash(plan),
        "formula_hash": str(formula_ir.get("formula_hash") or ""),
        "required_fields": formula_ir.get("required_fields") or [],
        "operator_set": formula_ir.get("operator_set") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an agent-authored web research plan without materializing "
            "artifacts or starting Factor Forge Ultimate."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    try:
        result = validate_authoring_plan(
            workspace=Path(args.workspace_root),
            plan_path=Path(args.plan),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, WebResearchPlanError) as exc:
        token = (
            exc.token
            if isinstance(exc, WebResearchPlanError)
            else "BLOCK_FACTORFORGE_WEB_RESEARCH_AUTHORING_PREFLIGHT_FAILED"
        )
        reasons = list(exc.reasons) if isinstance(exc, WebResearchPlanError) else [str(exc)]
        print(
            json.dumps(
                {
                    "version": "factorforge_web_research_authoring_preflight_v1",
                    "verdict": "BLOCK",
                    "formal_research_started": False,
                    "block_token": token,
                    "block_reasons": reasons,
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
