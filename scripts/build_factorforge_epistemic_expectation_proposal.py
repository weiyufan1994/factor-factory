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
from factor_factory.epistemic_host_bootstrap_expectation_proposal import (
    EpistemicExpectationProposalError,
    build_expectation_proposal_inventory,
    build_expectation_proposal_report,
    compile_candidate_definition_generation_target,
    compile_closed_steward_review_schema_bundle,
    compile_dual_git_review_handoff,
    compile_expectation_assignment_proposal,
    compile_expectation_semantic_derivation_registry,
    write_expectation_proposal_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the offline, nonauthorizing exact160 expectation-assignment "
            "proposal and dual-Git review handoff."
        )
    )
    parser.add_argument("--stage1b-repo-root", default=str(REPO_ROOT))
    parser.add_argument("--r2-manifest", required=True)
    parser.add_argument("--o0-manifest", required=True)
    parser.add_argument("--o0-prime-manifest", required=True)
    parser.add_argument("--b0b1-r2-manifest", required=True)
    parser.add_argument("--e1-r3-manifest", required=True)
    parser.add_argument("--e1-r4-manifest", required=True)
    parser.add_argument("--e1-r5-manifest", required=True)
    parser.add_argument("--e1-r6-manifest", required=True)
    parser.add_argument("--e1-r7-manifest", required=True)
    parser.add_argument("--e1-r8-manifest", required=True)
    parser.add_argument("--e1-r9-manifest", required=True)
    parser.add_argument("--e1-r9-review-manifest", required=True)
    parser.add_argument("--e1-r10-manifest", required=True)
    parser.add_argument("--e1-r10-review-manifest", required=True)
    parser.add_argument("--e1-r11-manifest", required=True)
    parser.add_argument("--e1-r11-review-manifest", required=True)
    parser.add_argument("--e1-r12-manifest", required=True)
    parser.add_argument("--e1-r12-review-manifest", required=True)
    parser.add_argument("--e1-r13-manifest", required=True)
    parser.add_argument("--e1-r13-review-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    try:
        repo_root = Path(args.stage1b_repo_root)
        b0b1_r2_manifest = Path(args.b0b1_r2_manifest)
        e1_r3_manifest = Path(args.e1_r3_manifest)
        e1_r4_manifest = Path(args.e1_r4_manifest)
        e1_r5_manifest = Path(args.e1_r5_manifest)
        e1_r6_manifest = Path(args.e1_r6_manifest)
        e1_r7_manifest = Path(args.e1_r7_manifest)
        e1_r8_manifest = Path(args.e1_r8_manifest)
        e1_r9_manifest = Path(args.e1_r9_manifest)
        e1_r9_review_manifest = Path(args.e1_r9_review_manifest)
        e1_r10_manifest = Path(args.e1_r10_manifest)
        e1_r10_review_manifest = Path(args.e1_r10_review_manifest)
        e1_r11_manifest = Path(args.e1_r11_manifest)
        e1_r11_review_manifest = Path(args.e1_r11_review_manifest)
        e1_r12_manifest = Path(args.e1_r12_manifest)
        e1_r12_review_manifest = Path(args.e1_r12_review_manifest)
        e1_r13_manifest = Path(args.e1_r13_manifest)
        e1_r13_review_manifest = Path(args.e1_r13_review_manifest)
        contracts = load_frozen_bootstrap_contracts(
            stage1b_repo_root=repo_root,
            r2_manifest_path=Path(args.r2_manifest),
            o0_manifest_path=Path(args.o0_manifest),
            o0_prime_manifest_path=Path(args.o0_prime_manifest),
        )
        semantic_registry = compile_expectation_semantic_derivation_registry(
            contracts,
            b0b1_r2_manifest_path=b0b1_r2_manifest,
            e1_r3_manifest_path=e1_r3_manifest,
            e1_r4_manifest_path=e1_r4_manifest,
            e1_r5_manifest_path=e1_r5_manifest,
            e1_r6_manifest_path=e1_r6_manifest,
            e1_r7_manifest_path=e1_r7_manifest,
            e1_r8_manifest_path=e1_r8_manifest,
            e1_r9_manifest_path=e1_r9_manifest,
            e1_r9_review_manifest_path=e1_r9_review_manifest,
            e1_r10_manifest_path=e1_r10_manifest,
            e1_r10_review_manifest_path=e1_r10_review_manifest,
            e1_r11_manifest_path=e1_r11_manifest,
            e1_r11_review_manifest_path=e1_r11_review_manifest,
            e1_r12_manifest_path=e1_r12_manifest,
            e1_r12_review_manifest_path=e1_r12_review_manifest,
            e1_r13_manifest_path=e1_r13_manifest,
            e1_r13_review_manifest_path=e1_r13_review_manifest,
        )
        proposal = compile_expectation_assignment_proposal(
            contracts,
            b0b1_r2_manifest_path=b0b1_r2_manifest,
            e1_r3_manifest_path=e1_r3_manifest,
            e1_r4_manifest_path=e1_r4_manifest,
            e1_r5_manifest_path=e1_r5_manifest,
            e1_r6_manifest_path=e1_r6_manifest,
            e1_r7_manifest_path=e1_r7_manifest,
            e1_r8_manifest_path=e1_r8_manifest,
            e1_r9_manifest_path=e1_r9_manifest,
            e1_r9_review_manifest_path=e1_r9_review_manifest,
            e1_r10_manifest_path=e1_r10_manifest,
            e1_r10_review_manifest_path=e1_r10_review_manifest,
            e1_r11_manifest_path=e1_r11_manifest,
            e1_r11_review_manifest_path=e1_r11_review_manifest,
            e1_r12_manifest_path=e1_r12_manifest,
            e1_r12_review_manifest_path=e1_r12_review_manifest,
            e1_r13_manifest_path=e1_r13_manifest,
            e1_r13_review_manifest_path=e1_r13_review_manifest,
            semantic_registry=semantic_registry,
        )
        definition_target = compile_candidate_definition_generation_target(
            semantic_registry=semantic_registry,
            proposal=proposal,
        )
        schema_bundle = compile_closed_steward_review_schema_bundle(
            semantic_registry=semantic_registry,
            proposal=proposal,
            definition_target=definition_target,
        )
        handoff = compile_dual_git_review_handoff(
            proposal,
            semantic_registry=semantic_registry,
            definition_target=definition_target,
            schema_bundle=schema_bundle,
        )
        inventory = build_expectation_proposal_inventory(repo_root)
        report = build_expectation_proposal_report(
            contracts=contracts,
            b0b1_r2_manifest_path=b0b1_r2_manifest,
            e1_r3_manifest_path=e1_r3_manifest,
            e1_r4_manifest_path=e1_r4_manifest,
            e1_r5_manifest_path=e1_r5_manifest,
            e1_r6_manifest_path=e1_r6_manifest,
            e1_r7_manifest_path=e1_r7_manifest,
            e1_r8_manifest_path=e1_r8_manifest,
            e1_r9_manifest_path=e1_r9_manifest,
            e1_r9_review_manifest_path=e1_r9_review_manifest,
            e1_r10_manifest_path=e1_r10_manifest,
            e1_r10_review_manifest_path=e1_r10_review_manifest,
            e1_r11_manifest_path=e1_r11_manifest,
            e1_r11_review_manifest_path=e1_r11_review_manifest,
            e1_r12_manifest_path=e1_r12_manifest,
            e1_r12_review_manifest_path=e1_r12_review_manifest,
            e1_r13_manifest_path=e1_r13_manifest,
            e1_r13_review_manifest_path=e1_r13_review_manifest,
            semantic_registry=semantic_registry,
            proposal=proposal,
            definition_target=definition_target,
            schema_bundle=schema_bundle,
            handoff=handoff,
            inventory=inventory,
        )
        manifest = write_expectation_proposal_packet(
            Path(args.output_root),
            semantic_registry=semantic_registry,
            proposal=proposal,
            definition_target=definition_target,
            schema_bundle=schema_bundle,
            handoff=handoff,
            report=report,
            inventory=inventory,
        )
    except (
        OSError,
        ValueError,
        EpistemicHostBootstrapError,
        EpistemicExpectationProposalError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
