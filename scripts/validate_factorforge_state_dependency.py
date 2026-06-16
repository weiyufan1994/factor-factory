#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.state_reuse import (
    BLOCK_STATE_DEPENDENCY_UNDECLARED,
    load_json,
    load_state_dependency_contract,
    resolve_state_dependencies,
    validate_state_dependency_contract,
    write_resolution_outputs,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Validate and resolve Factor Forge state dependency contracts.")
    ap.add_argument("--dependency-contract", required=True)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--factor-id", default=None)
    ap.add_argument("--research-id", default=None)
    ap.add_argument("--output-state-resolution", required=True)
    ap.add_argument("--output-data-request-dir", default=None)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = Path(args.dependency_contract).expanduser()
    catalog_path = Path(args.catalog).expanduser()
    resolution_path = Path(args.output_state_resolution).expanduser()
    request_dir = Path(args.output_data_request_dir).expanduser() if args.output_data_request_dir else None

    if not contract_path.exists():
        print(f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: missing {contract_path}", file=sys.stderr)
        return 1

    contract = load_state_dependency_contract(contract_path)
    failures = validate_state_dependency_contract(contract)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        resolution = {
            "contract_version": "factorforge_state_resolution_v1",
            "report_id": args.report_id,
            "factor_id": args.factor_id,
            "research_id": args.research_id,
            "dependency_contract_path": str(contract_path),
            "catalog_source": {"type": "local_json", "path_or_uri": str(catalog_path)},
            "reuse_hits": [],
            "missing_state_variables": [],
            "data_requests": [],
            "data_request_ids": [],
            "blocked": True,
            "blocker_token": failures[0].split(":", 1)[0],
            "failures": failures,
        }
        write_resolution_outputs(
            resolution=resolution,
            state_resolution_path=resolution_path,
            data_request_dir=request_dir,
        )
        return 1

    catalog = load_json(catalog_path)
    resolution = resolve_state_dependencies(
        contract=contract,
        catalog=catalog,
        report_id=args.report_id,
        factor_id=args.factor_id,
        research_id=args.research_id,
        dependency_contract_path=str(contract_path),
        catalog_source={"type": "local_json", "path_or_uri": str(catalog_path)},
    )
    write_resolution_outputs(
        resolution=resolution,
        state_resolution_path=resolution_path,
        data_request_dir=request_dir,
    )
    print(json.dumps(resolution, ensure_ascii=False, indent=2, sort_keys=True))
    if resolution.get("blocked") is True:
        print(resolution.get("blocker_token"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
