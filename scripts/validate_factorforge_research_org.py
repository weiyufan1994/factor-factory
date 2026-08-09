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
    validate_research_organization_runtime,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a workspace-local Factor Forge research organization bundle."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--require-results", action="store_true")
    parser.add_argument("--require-runtime", action="store_true")
    parser.add_argument("--require-runtime-complete", action="store_true")
    parser.add_argument("--require-runtime-formal", action="store_true")
    parser.add_argument("--runtime-private-root")
    parser.add_argument("--runtime-trust-root")
    parser.add_argument("--runtime-installation-id")
    args = parser.parse_args()
    if args.require_runtime_formal and not (
        args.runtime_private_root
        and args.runtime_trust_root
        and args.runtime_installation_id
    ):
        parser.error(
            "--require-runtime-formal requires --runtime-private-root, "
            "--runtime-trust-root, and --runtime-installation-id"
        )
    try:
        result = validate_research_organization_bundle(
            workspace=Path(args.workspace_root).expanduser().resolve(strict=False),
            require_results=args.require_results,
        )
        if (
            args.require_runtime
            or args.require_runtime_complete
            or args.require_runtime_formal
        ):
            result["runtime"] = validate_research_organization_runtime(
                workspace=Path(args.workspace_root).expanduser().resolve(strict=False),
                require_complete=(
                    args.require_runtime_complete or args.require_runtime_formal
                ),
                private_root=(
                    Path(args.runtime_private_root).expanduser().resolve(strict=False)
                    if args.runtime_private_root
                    else None
                ),
                trust_root=(
                    Path(args.runtime_trust_root).expanduser().resolve(strict=False)
                    if args.runtime_trust_root
                    else None
                ),
                installation_id=args.runtime_installation_id,
                require_formal=args.require_runtime_formal,
            )
    except (OSError, ValueError, ResearchOrganizationError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
