#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_conjecture import (
    RESEARCH_PROTOCOL_SCOPE_HOSTED,
    RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
    validate_protocol_bundle,
    write_json,
)
from factor_factory.measurement_program import (
    INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING,
    research_compatibility_profile_from_spec,
)


INVALID_SPEC_PROFILE = "__invalid_report_bound_research_compatibility_profile__"


def report_bound_compatibility_profile(root: Path, report_id: str) -> str | None:
    """Read the current Step2 spec binding; never infer a profile from env/CLI."""
    path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        return INVALID_SPEC_PROFILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return INVALID_SPEC_PROFILE
    if not isinstance(payload, dict) or payload.get("report_id") not in {None, report_id}:
        return INVALID_SPEC_PROFILE
    profile = research_compatibility_profile_from_spec(payload)
    if profile == INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING:
        return INVALID_SPEC_PROFILE
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the Factor Forge Research Conjecture Protocol bundle."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument(
        "--stage",
        choices=["pre_council", "pre_revision", "pre_promotion", "final"],
        required=True,
    )
    parser.add_argument("--iteration-path")
    parser.add_argument(
        "--local-is-only",
        action="store_true",
        default=os.getenv("FACTORFORGE_LOCAL_IS_ONLY") == "1",
        help="Select the non-authoritative ordinary local-IS validation scope.",
    )
    args = parser.parse_args()

    root = Path(args.workspace_root).expanduser().resolve(strict=False)
    iteration_path = (
        Path(args.iteration_path).expanduser().resolve(strict=False)
        if args.iteration_path
        else None
    )
    report = validate_protocol_bundle(
        root=root,
        report_id=args.report_id,
        stage=args.stage,
        scope=(
            RESEARCH_PROTOCOL_SCOPE_LOCAL_IS
            if args.local_is_only
            else RESEARCH_PROTOCOL_SCOPE_HOSTED
        ),
        compatibility_profile=report_bound_compatibility_profile(root, args.report_id),
        iteration_path=iteration_path,
    )
    verifier_path = (
        root
        / "objects"
        / "research_protocol"
        / f"semantic_verifier_report__{args.report_id}.json"
    )
    write_json(verifier_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
