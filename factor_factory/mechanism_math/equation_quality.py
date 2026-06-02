from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_EVIDENCE_TIERS = {
    "logical_identity",
    "institutional_rule",
    "documented_microstructure_law",
    "cross_asset_empirical_invariance",
    "single_market_empirical_regular",
    "report_specific_hypothesis",
}

VALID_DEMOTION_TRIGGERS = {
    "identity_violation",
    "rule_change",
    "participant_structure_change",
    "liquidity_regime_change",
    "cost_or_capacity_break",
    "cross_sample_failure",
    "metric_signature_mismatch",
}


@dataclass(frozen=True)
class EquationQualityResult:
    ok: bool
    block_codes: tuple[str, ...]
    quality_score: int
    evidence_tier: str


def score_research_equation(equation: dict[str, Any]) -> EquationQualityResult:
    status = str(equation.get("equation_status") or "")
    evidence_tier = str(equation.get("evidence_tier") or "")
    assumptions = equation.get("assumptions") or []
    validity_scope = equation.get("validity_scope") or {}
    participant_loop = equation.get("participant_constraint_loop") or {}
    demotion_triggers = equation.get("demotion_triggers") or []
    audit_basis = equation.get("audit_basis") or []
    block_codes: list[str] = []
    score = 0

    if evidence_tier not in VALID_EVIDENCE_TIERS:
        block_codes.append("BLOCK_DIRAC_EQUATION_EVIDENCE_TIER_INVALID")
    else:
        score += {
            "logical_identity": 30,
            "institutional_rule": 24,
            "documented_microstructure_law": 20,
            "cross_asset_empirical_invariance": 18,
            "single_market_empirical_regular": 12,
            "report_specific_hypothesis": 8,
        }[evidence_tier]

    if status == "strict_identity" and not audit_basis:
        block_codes.append("BLOCK_DIRAC_EQUATION_AUDIT_BASIS_MISSING")
    if status == "behavioral_feedback" and not participant_loop:
        block_codes.append("BLOCK_DIRAC_EQUATION_PARTICIPANT_LOOP_MISSING")
    if status in {"empirical_invariance", "research_conjecture"} and not validity_scope:
        block_codes.append("BLOCK_DIRAC_EQUATION_SCOPE_MISSING")
    if status == "research_conjecture" and equation.get("promotion_allowed") is True:
        block_codes.append("BLOCK_DIRAC_EQUATION_CONJECTURE_PROMOTION_FORBIDDEN")
    if not assumptions:
        block_codes.append("BLOCK_DIRAC_EQUATION_ASSUMPTIONS_MISSING")
    if not demotion_triggers:
        block_codes.append("BLOCK_DIRAC_EQUATION_DEMOTION_TRIGGERS_MISSING")
    if any(str(item) not in VALID_DEMOTION_TRIGGERS for item in demotion_triggers):
        block_codes.append("BLOCK_DIRAC_EQUATION_DEMOTION_TRIGGER_INVALID")

    repeat_mechanism = participant_loop.get("repeat_mechanism") if isinstance(participant_loop, dict) else None
    if status == "behavioral_feedback" and not repeat_mechanism:
        block_codes.append("BLOCK_DIRAC_EQUATION_PARTICIPANT_REPEAT_MISSING")

    score += min(len(assumptions), 4) * 4
    score += min(len(demotion_triggers), 4) * 3
    score += 8 if validity_scope else 0
    score += 8 if participant_loop else 0
    score += 8 if audit_basis else 0
    return EquationQualityResult(
        ok=not block_codes,
        block_codes=tuple(block_codes),
        quality_score=min(score, 100),
        evidence_tier=evidence_tier,
    )
