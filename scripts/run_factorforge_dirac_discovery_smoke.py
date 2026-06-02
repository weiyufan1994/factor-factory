#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.mechanism_math.factor_discovery_queue import (
    DiscoveryCandidate,
    build_default_discovery_queue,
    disposition_feedback_candidates,
    square_root_impact_candidates,
    validate_discovery_candidate,
)
from factor_factory.mechanism_math.equation_quality import score_research_equation


def valid_behavioral_feedback_equation() -> dict[str, object]:
    return {
        "equation_status": "behavioral_feedback",
        "evidence_tier": "report_specific_hypothesis",
        "assumptions": ["anchored holders repeatedly respond to cost-basis reference points"],
        "validity_scope": {
            "market": "A-share equities",
            "frequency": "daily",
            "regime": "normal liquidity",
            "participant_structure": "retail-heavy flow with anchored holders",
        },
        "participant_constraint_loop": {
            "payer": "anchored holders",
            "constraint": "cannot immediately abandon cost-basis anchored behavior",
            "repeat_mechanism": "new trapped positions are created by prior trading waves",
            "failure_condition": "participant mix changes or cost-basis density no longer maps to selling pressure",
        },
        "audit_basis": ["Report text and behavioral evidence support the cost-basis pressure claim."],
        "demotion_triggers": [
            "participant_structure_change",
            "metric_signature_mismatch",
            "cross_sample_failure",
        ],
    }


def main() -> None:
    queue = build_default_discovery_queue()
    square_root = square_root_impact_candidates()[0]
    disposition = disposition_feedback_candidates()[0]
    quality_equation = valid_behavioral_feedback_equation()
    cases = {
        "strict_identity_without_audit_basis_blocks": "BLOCK_DIRAC_EQUATION_AUDIT_BASIS_MISSING"
        in score_research_equation({**quality_equation, "equation_status": "strict_identity", "evidence_tier": "logical_identity", "audit_basis": []}).block_codes,
        "behavioral_feedback_without_participant_loop_blocks": "BLOCK_DIRAC_EQUATION_PARTICIPANT_LOOP_MISSING"
        in score_research_equation({**quality_equation, "participant_constraint_loop": {}}).block_codes,
        "empirical_invariance_without_scope_blocks": "BLOCK_DIRAC_EQUATION_SCOPE_MISSING"
        in score_research_equation({**quality_equation, "equation_status": "empirical_invariance", "evidence_tier": "cross_asset_empirical_invariance", "validity_scope": {}}).block_codes,
        "research_conjecture_auto_promotion_blocks": "BLOCK_DIRAC_EQUATION_CONJECTURE_PROMOTION_FORBIDDEN"
        in score_research_equation({**quality_equation, "equation_status": "research_conjecture", "promotion_allowed": True}).block_codes,
        "valid_behavioral_feedback_quality_passes": score_research_equation(quality_equation).ok,
        "equation_to_detector_queue_contains_no_auto_run": queue.get("auto_run_allowed") is False
        and all(candidate.get("auto_run_allowed") is False for candidate in queue.get("candidates", [])),
        "queue_candidate_missing_observables_blocks": "BLOCK_DIRAC_DISCOVERY_OBSERVABLES_MISSING"
        in validate_discovery_candidate(replace(square_root, observable_inputs=())),
        "queue_candidate_missing_expected_signature_blocks": "BLOCK_DIRAC_DISCOVERY_METRIC_SIGNATURE_MISSING"
        in validate_discovery_candidate(replace(square_root, expected_metric_signature=())),
        "queue_candidate_missing_cost_risk_hypothesis_blocks": "BLOCK_DIRAC_DISCOVERY_COST_RISK_MISSING"
        in validate_discovery_candidate(replace(square_root, expected_cost_risk_profile=())),
        "queue_candidate_autorun_blocks": "BLOCK_DIRAC_DISCOVERY_AUTORUN_FORBIDDEN"
        in validate_discovery_candidate(replace(square_root, auto_run_allowed=True)),
        "queue_candidate_unknown_source_blocks": "BLOCK_DIRAC_DISCOVERY_SOURCE_EQUATION_UNKNOWN"
        in validate_discovery_candidate(
            DiscoveryCandidate(
                candidate_id="unknown_source",
                source_equation_id="missing_equation",
                detector_hypothesis="unknown",
                observable_inputs=("close",),
                measurement_equation="x=close",
                expected_metric_signature=("rank_ic nonzero",),
                expected_cost_risk_profile=("turnover cost is COGS",),
                stochastic_benchmark_terms=("drift",),
                falsification_tests=("no return signature",),
                branch_action="review_only",
            )
        ),
        "valid_square_root_impact_candidate_passes": validate_discovery_candidate(square_root) == (),
        "valid_disposition_feedback_candidate_passes": validate_discovery_candidate(disposition) == (),
    }
    failed = [name for name, ok in cases.items() if not ok]
    print(json.dumps({"verdict": "ACCEPT" if not failed else "BLOCK", "failed": failed, **cases}, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
