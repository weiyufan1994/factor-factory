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
    write_research_organization_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a governed Factor Forge research-organization plan and dispatch bundle."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument(
        "--request",
        help="Research request JSON. Defaults to identity/web_research_request.json.",
    )
    parser.add_argument("--preserve-existing", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace_root).expanduser().resolve(strict=False)
    request_path = (
        Path(args.request).expanduser().resolve(strict=False)
        if args.request
        else workspace / "identity" / "web_research_request.json"
    )
    if not request_path.is_file() or request_path.is_symlink():
        print(f"BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_MISSING: request={request_path}", file=sys.stderr)
        return 1
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise TypeError("request must be a JSON object")
        result = write_research_organization_bundle(
            workspace=workspace,
            request=request,
            preserve_existing=args.preserve_existing,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ResearchOrganizationError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
