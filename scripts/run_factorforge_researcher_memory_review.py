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
from factor_factory.research_org import ResearchOrganizationError
from factor_factory.researcher_memory_review import (
    run_and_record_independent_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a disposable independent reviewer Agent and admit its signed "
            "researcher-memory decision."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--outcome-event-id", required=True)
    parser.add_argument("--installation-id")
    parser.add_argument("--worktree-root")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    workspace = Path(args.workspace_root).expanduser().resolve(strict=False)
    worktree = Path(args.worktree).expanduser().resolve(strict=False)
    state_root = Path(args.state_root).expanduser().resolve(strict=False)
    installation_id = (
        args.installation_id
        or os.getenv("FACTORFORGE_CONSOLE_INSTALLATION_ID")
        or hashlib.sha256(
            f"{worktree}\0{state_root}".encode("utf-8")
        ).hexdigest()[:16]
    )
    try:
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
        config = replace(config, installation_id=installation_id)
        runner = ContainerizedOpenClawResearchAgentAdapter(config)
        runner.validate_ready()
        result = run_and_record_independent_review(
            workspace=workspace,
            worktree=worktree,
            memory_root=state_root / "researcher-memory",
            installation_id=installation_id,
            candidate_relative=args.candidate,
            outcome_event_id=args.outcome_event_id,
            runner=runner,
            timeout_seconds=args.timeout_seconds,
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
