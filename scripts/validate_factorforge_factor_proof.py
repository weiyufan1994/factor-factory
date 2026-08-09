#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_proof import (
    CERTIFICATE_VERSION,
    factor_proof_certificate_path,
    load_json,
    validate_factor_proof_certificate,
    write_json,
)
from factor_factory.research_workspace import load_workspace_manifest


BOUND_VERIFIER_VERSION = "factorforge_console_bound_factor_proof_verifier_v1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Factor Forge factor proof certificate."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--certificate")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve(strict=False)
    certificate_path = (
        Path(args.certificate).expanduser().resolve(strict=False)
        if args.certificate
        else factor_proof_certificate_path(workspace_root, args.report_id)
    )
    if not certificate_path.is_file():
        report = {
            "certificate_version": CERTIFICATE_VERSION,
            "report_id": args.report_id,
            "verdict": "BLOCK",
            "block_reasons": [
                "BLOCK_FACTORFORGE_FACTOR_PROOF_CERTIFICATE_MISSING"
            ],
            "certificate_path": str(certificate_path),
        }
    else:
        payload = load_json(certificate_path)
        report = validate_factor_proof_certificate(
            payload,
            workspace_root=workspace_root,
            expected_report_id=args.report_id,
        )
        report["certificate_path"] = str(certificate_path)
    try:
        workspace_manifest = load_workspace_manifest(workspace_root / "manifest.json")
    except (OSError, ValueError):
        workspace_manifest = {}
    report["verifier_contract_version"] = BOUND_VERIFIER_VERSION
    report["research_id"] = workspace_manifest.get("research_id")
    report["formal_proof_eligible"] = report.get("verdict") in {
        "ACCEPT",
        "REJECT",
        "ITERATE",
    } and not report.get("block_reasons")
    verifier_path = (
        workspace_root
        / "objects"
        / "research_protocol"
        / f"factor_proof_verifier_report__{args.report_id}.json"
    )
    write_json(verifier_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("verdict") != "BLOCK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
