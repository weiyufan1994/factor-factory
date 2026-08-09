#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.config import ConsoleConfig
from factor_factory.console.container_agent_adapter import (
    ContainerizedOpenClawResearchAgentAdapter,
)
from factor_factory.research_org import (
    ResearchOrganizationError,
    load_research_organization_plan,
    request_research_organization_cancel,
    run_research_organization_runtime,
    validate_research_organization_runtime,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run or validate workspace-local Factor Forge specialist Agent sessions."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--private-root")
    parser.add_argument("--worktree-root")
    parser.add_argument("--installation-id")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--require-formal", action="store_true")
    parser.add_argument("--cancel", action="store_true")
    parser.add_argument("--cancel-reason", default="operator requested cancellation")
    parser.add_argument("--requested-by", default="factorforge_operator")
    args = parser.parse_args()

    workspace = Path(args.workspace_root).expanduser().resolve(strict=False)
    worktree = Path(args.worktree).expanduser().resolve(strict=False)
    state_root = Path(args.state_root).expanduser().resolve(strict=False)
    try:
        plan = load_research_organization_plan(workspace)
        private_root = (
            Path(args.private_root).expanduser().resolve(strict=False)
            if args.private_root
            else state_root
            / "jobs"
            / str(plan["identity"]["job_id"])
            / "research_org_private"
        )
        installation_id = (
            args.installation_id
            or os.getenv("FACTORFORGE_CONSOLE_INSTALLATION_ID")
            or hashlib.sha256(
                f"{worktree.resolve(strict=False)}\0{state_root.resolve(strict=False)}".encode()
            ).hexdigest()[:16]
        )
        trust_root = state_root / "research-org-trust"
        if args.cancel:
            result = request_research_organization_cancel(
                workspace=workspace,
                requested_by=args.requested_by,
                reason=args.cancel_reason,
                private_root=private_root,
                trust_root=trust_root,
                installation_id=installation_id,
            )
        elif args.validate_only:
            result = validate_research_organization_runtime(
                workspace=workspace,
                require_complete=args.require_complete or args.require_formal,
                private_root=private_root,
                trust_root=trust_root,
                installation_id=installation_id,
                require_formal=args.require_formal,
            )
        else:
            config = ConsoleConfig.from_env(
                source_repo=worktree,
                state_root=state_root,
                worktree_root=(
                    Path(args.worktree_root).expanduser().resolve(strict=False)
                    if args.worktree_root
                    else worktree.parent
                ),
                data_catalogs=[],
                auth_disabled=False,
            )
            if args.installation_id:
                config = replace(config, installation_id=installation_id)
            runner = ContainerizedOpenClawResearchAgentAdapter(config)
            runner.validate_ready()
            result = run_research_organization_runtime(
                workspace=workspace,
                worktree=worktree,
                private_root=private_root,
                runner=runner,
                max_attempts=args.max_attempts,
                max_concurrency=args.max_concurrency,
                timeout_seconds=args.timeout_seconds,
                trust_root=trust_root,
                installation_id=config.installation_id,
            )
    except (
        OSError,
        RuntimeError,
        ValueError,
        ResearchOrganizationError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
