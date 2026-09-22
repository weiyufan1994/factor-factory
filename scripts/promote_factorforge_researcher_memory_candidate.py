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
from factor_factory.researcher_memory import promote_reviewed_candidate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote an independently reviewed researcher-memory candidate."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--review", required=True, help="Workspace-relative review path.")
    parser.add_argument("--memory-root", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--trust-root",
        help="Host-private research organization trust store. Defaults beside memory-root.",
    )
    args = parser.parse_args()
    try:
        result = promote_reviewed_candidate(
            workspace=Path(args.workspace_root).expanduser().resolve(strict=True),
            review_relative=args.review,
            root=Path(args.memory_root).expanduser(),
            installation_id=args.installation_id,
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
