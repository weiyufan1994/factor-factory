#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_org import (
    ResearchOrganizationError,
    validate_research_organization_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a workspace-local Factor Forge research organization bundle."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--require-results", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_research_organization_bundle(
            workspace=Path(args.workspace_root).expanduser().resolve(strict=False),
            require_results=args.require_results,
        )
    except ResearchOrganizationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
