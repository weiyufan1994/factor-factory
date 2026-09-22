#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_org import ResearchOrganizationError
from factor_factory.researcher_memory import (
    ensure_researcher_memory_store,
    validate_researcher_memory_store,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize or validate the Host-private Factor Forge researcher-memory store."
    )
    parser.add_argument("--memory-root", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--workspace-root")
    args = parser.parse_args()

    root = Path(args.memory_root).expanduser()
    repo_root = Path(args.repo_root).expanduser().resolve(strict=False)
    workspace = (
        Path(args.workspace_root).expanduser().resolve(strict=False)
        if args.workspace_root
        else None
    )
    try:
        ensure_researcher_memory_store(
            root,
            installation_id=args.installation_id,
            repo_root=repo_root,
            workspace=workspace,
        )
        result = validate_researcher_memory_store(
            root,
            installation_id=args.installation_id,
            repo_root=repo_root,
            workspace=workspace,
        )
    except (OSError, ValueError, ResearchOrganizationError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
