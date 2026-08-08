#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_org import ResearchOrganizationError, admit_agent_result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and admit one private Factor Forge Agent result."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--result", required=True, help="Private candidate result JSON.")
    parser.add_argument("--role-id")
    args = parser.parse_args()

    candidate_path = Path(args.result).expanduser().resolve(strict=False)
    if (
        not candidate_path.is_file()
        or candidate_path.is_symlink()
        or candidate_path.stat().st_size > 2 * 1024 * 1024
    ):
        print(
            f"BLOCK_FACTORFORGE_RESEARCH_ORG_RESULT_INVALID: unsafe result={candidate_path}",
            file=sys.stderr,
        )
        return 1
    try:
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        if not isinstance(candidate, dict):
            raise TypeError("result must be a JSON object")
        summary = admit_agent_result(
            workspace=Path(args.workspace_root).expanduser().resolve(strict=False),
            result=candidate,
            role_id=args.role_id,
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
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
