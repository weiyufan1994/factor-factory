#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_obligation_verifier import (
    component_verifier_identities,
    run_component_obligation_verifier,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute full-versus-ablated component evidence from a frozen "
            "cross-sectional panel."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument(
        "--identity-only",
        action="store_true",
        help=(
            "Diagnostic/smoke only: print panel identities without evaluating "
            "the component claim. Formal research must preregister through "
            "write_factorforge_evaluation_release_chain.py before OOS release."
        ),
    )
    args = parser.parse_args()
    root = Path(args.workspace_root)
    panel = Path(args.panel)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if args.identity_only:
        result = component_verifier_identities(
            workspace_root=root,
            panel_path=panel,
            spec=spec,
        )
    else:
        result = run_component_obligation_verifier(
            workspace_root=root,
            panel_path=panel,
            spec=spec,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.identity_only:
        return 0
    return 0 if result["verifier_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
