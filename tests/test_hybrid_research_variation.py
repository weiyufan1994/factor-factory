from __future__ import annotations

import pytest

from factor_factory.hybrid_research.variation import DerivationScope, VariationProposal, classify_variation


SCOPE = DerivationScope(
    derivation_ref="step2:response-v1", mathematical_object="causal response kernel",
    domain="finite signed impulses", initial_state="zero", clock="event time",
    missing_value_policy="missing is not zero", observation_map="signed J to y",
    allowed_transformations=("causal convolution",),
    distinguishing_predictions=("temporary response decays",), current_gap="permanent component unidentified",
)


def proposal(*aspects: str, derivation_ref: str = "step2:response-v1") -> VariationProposal:
    return VariationProposal("child", "parent", aspects, "bounded candidate change", derivation_ref)


def test_implementation_only_change_requires_parity_but_not_step2_reformalization() -> None:
    decision = classify_variation(SCOPE, proposal("implementation", "refactor"))
    assert decision.kind == "implementation_equivalent"
    assert decision.requires_step2_reformalization is False
    assert "code review" in decision.reason


@pytest.mark.parametrize("aspect", ("memory_length", "phase", "sign", "target", "observation_map"))
def test_measurement_changes_return_to_step2(aspect: str) -> None:
    decision = classify_variation(SCOPE, proposal(aspect))
    assert decision.kind == "measurement_estimation_variant"
    assert decision.requires_step2_reformalization is True


@pytest.mark.parametrize("aspect", ("economic_assumption", "response_structure", "state_equation", "unknown_feature"))
def test_new_or_unknown_semantics_require_fresh_induction(aspect: str) -> None:
    decision = classify_variation(SCOPE, proposal(aspect))
    assert decision.kind == "new_response_structure"
    assert decision.requires_step2_reformalization is True


def test_proposal_cannot_silently_switch_derivation() -> None:
    with pytest.raises(ValueError, match="active derivation"):
        classify_variation(SCOPE, proposal("implementation", derivation_ref="step2:other"))
