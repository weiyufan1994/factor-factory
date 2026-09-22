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
    load_frozen_bootstrap_contracts,
)
from factor_factory.epistemic_host_bootstrap_b0b import (
    EpistemicHostBootstrapB0BError,
    build_b0b_implementation_inventory,
    build_b0b_validation_report,
    compile_b0b_exact261_layout_scaffold,
    compile_b0b_expectation_gap_ledger,
    compile_b0b_plan,
    write_b0b_candidate_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the offline, non-authorizing Factor Forge B0-B1 expectation "
            "gap and exact261 layout scaffold."
        )
    )
    parser.add_argument("--stage1b-repo-root", default=str(REPO_ROOT))
    parser.add_argument("--r2-manifest", required=True)
    parser.add_argument("--o0-manifest", required=True)
    parser.add_argument("--o0-prime-manifest", required=True)
    parser.add_argument("--b0a-r2-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    try:
        contracts = load_frozen_bootstrap_contracts(
            stage1b_repo_root=Path(args.stage1b_repo_root),
            r2_manifest_path=Path(args.r2_manifest),
            o0_manifest_path=Path(args.o0_manifest),
            o0_prime_manifest_path=Path(args.o0_prime_manifest),
        )
        b0a_manifest_path = Path(args.b0a_r2_manifest)
        plan = compile_b0b_plan(
            contracts,
            b0a_r2_manifest_path=b0a_manifest_path,
        )
        gap_ledger = compile_b0b_expectation_gap_ledger(contracts)
        layout = compile_b0b_exact261_layout_scaffold(
            contracts,
            gap_ledger=gap_ledger,
        )
        implementation_inventory = build_b0b_implementation_inventory(
            Path(args.stage1b_repo_root)
        )
        report = build_b0b_validation_report(
            contracts=contracts,
            b0a_r2_manifest_path=b0a_manifest_path,
            plan=plan,
            gap_ledger=gap_ledger,
            layout=layout,
            implementation_inventory=implementation_inventory,
        )
        manifest = write_b0b_candidate_bundle(
            Path(args.output_root),
            plan=plan,
            gap_ledger=gap_ledger,
            layout=layout,
            report=report,
            implementation_inventory=implementation_inventory,
        )
    except (
        OSError,
        ValueError,
        EpistemicHostBootstrapError,
        EpistemicHostBootstrapB0BError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
