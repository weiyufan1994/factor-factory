#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_host_bootstrap import (
    EpistemicHostBootstrapError,
    build_b0_implementation_inventory,
    build_b0_validation_report,
    compile_b0_bootstrap_plan,
    compile_b0_obligation_skeleton,
    load_frozen_bootstrap_contracts,
    validate_b0_bootstrap_plan,
    validate_b0_obligation_skeleton,
    write_b0_candidate_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the synthetic-only, non-authorizing Factor Forge B0 Host "
            "bootstrap contract-compiler candidate."
        )
    )
    parser.add_argument("--stage1b-repo-root", default=str(REPO_ROOT))
    parser.add_argument("--r2-manifest", required=True)
    parser.add_argument("--o0-manifest", required=True)
    parser.add_argument("--o0-prime-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    try:
        contracts = load_frozen_bootstrap_contracts(
            stage1b_repo_root=Path(args.stage1b_repo_root),
            r2_manifest_path=Path(args.r2_manifest),
            o0_manifest_path=Path(args.o0_manifest),
            o0_prime_manifest_path=Path(args.o0_prime_manifest),
        )
        plan = compile_b0_bootstrap_plan(contracts)
        skeleton = compile_b0_obligation_skeleton(contracts)
        validate_b0_bootstrap_plan(plan, contracts=contracts)
        validate_b0_obligation_skeleton(skeleton, contracts=contracts)
        implementation_inventory = build_b0_implementation_inventory(
            Path(args.stage1b_repo_root)
        )
        report = build_b0_validation_report(
            contracts=contracts,
            plan=plan,
            skeleton=skeleton,
            implementation_inventory=implementation_inventory,
        )
        manifest = write_b0_candidate_bundle(
            Path(args.output_root),
            plan=plan,
            skeleton=skeleton,
            report=report,
            implementation_inventory=implementation_inventory,
        )
    except (OSError, ValueError, EpistemicHostBootstrapError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
