"""Classify candidate changes against the active mathematical derivation.

Classification is deliberately conservative: this module routes a proposal; it
does not decide that its economics are true or that a new structure is admissible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VariationKind = Literal[
    "implementation_equivalent",
    "measurement_estimation_variant",
    "new_response_structure",
]


@dataclass(frozen=True)
class DerivationScope:
    derivation_ref: str
    mathematical_object: str
    domain: str
    initial_state: str
    clock: str
    missing_value_policy: str
    observation_map: str
    allowed_transformations: tuple[str, ...]
    distinguishing_predictions: tuple[str, ...]
    current_gap: str
    allowed_response_families: tuple[str, ...] = ()
    allowed_research_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.derivation_ref,
            self.mathematical_object,
            self.domain,
            self.initial_state,
            self.clock,
            self.missing_value_policy,
            self.observation_map,
            self.current_gap,
        )
        if not all(part.strip() for part in required):
            raise ValueError("derivation scope requires a complete public reference and semantics")


@dataclass(frozen=True)
class VariationProposal:
    candidate_id: str
    parent_id: str
    changed_aspects: tuple[str, ...]
    rationale: str
    derivation_ref: str

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.parent_id or not self.rationale or not self.derivation_ref:
            raise ValueError("proposal identity, rationale, and derivation reference are required")
        if not self.changed_aspects:
            raise ValueError("proposal must declare changed aspects")


@dataclass(frozen=True)
class VariationDecision:
    kind: VariationKind
    requires_step2_reformalization: bool
    reason: str
    derivation_ref: str


_IMPLEMENTATION_ASPECTS = frozenset({"implementation", "backend", "optimization", "refactor"})
_MEASUREMENT_ASPECTS = frozenset({
    "estimator", "memory_length", "phase", "sign", "target", "observation_map",
    "proxy", "normalization", "sampling", "missing_value_policy",
})
_STRUCTURE_ASPECTS = frozenset({
    "economic_assumption", "mathematical_object", "response_structure", "state_equation",
    "observation_equation", "domain", "initial_state", "clock",
})


def classify_variation(scope: DerivationScope, proposal: VariationProposal) -> VariationDecision:
    """Route a declared change without accepting its claimed semantic class."""
    if proposal.derivation_ref != scope.derivation_ref:
        raise ValueError("proposal must bind to the active derivation reference")
    changed = frozenset(proposal.changed_aspects)
    unknown = changed - _IMPLEMENTATION_ASPECTS - _MEASUREMENT_ASPECTS - _STRUCTURE_ASPECTS
    if unknown or changed & _STRUCTURE_ASPECTS:
        return VariationDecision(
            "new_response_structure", True,
            "new or undeclared structural semantics require a fresh forward induction",
            scope.derivation_ref,
        )
    if changed & _MEASUREMENT_ASPECTS:
        return VariationDecision(
            "measurement_estimation_variant", True,
            "measurement or estimation changes require Step2 review of the observation bridge",
            scope.derivation_ref,
        )
    return VariationDecision(
        "implementation_equivalent", False,
        "no Step2 re-formalization; any Step3 behavior change still needs independent Step2 code review and parity",
        scope.derivation_ref,
    )
