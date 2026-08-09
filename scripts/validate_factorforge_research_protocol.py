#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_conjecture import validate_protocol_bundle, write_json


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
