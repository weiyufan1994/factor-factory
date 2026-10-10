import pytest

from factor_factory.research_search.generator import ExpressionCandidate, evaluate_candidate
from factor_factory.research_search.induction import ForwardInductionRecord, InductionScopeError
from factor_factory.research_search.typed_ast import ASTNode
from tests.research_search_d05_helpers import approved_scope


def candidate(scope, **changes):
    values = dict(candidate_id="c1", root=ASTNode.field("x"),
                  response_family=scope.response_family, induction_scope_hash=scope.scope_hash,
                  generation=0, parents=(), operation="seed", changed_aspects=("parameter",))
    values.update(changes)
    return ExpressionCandidate(**values)


@pytest.mark.parametrize("candidate_change,error", [
    ({"induction_scope_hash": "stale"}, "stale_or_different"),
    ({"response_family": "same_unit_but_different_response"}, "response_family_requires"),
])
def test_effect_evaluator_is_never_called_before_induction_gate(candidate_change, error):
    scope = approved_scope()
    calls = []
    with pytest.raises(InductionScopeError, match=error):
        evaluate_candidate(candidate(scope, **candidate_change), scope, lambda row: calls.append(row))
    assert calls == []


def test_induction_needs_substantive_public_content_and_step2_adapter():
    with pytest.raises(ValueError, match="substantive public derivation"):
        ForwardInductionRecord(
            record_id="bad", origin="synthetic_fixture", source_ref="synthetic://bad",
            assumptions=(), key_derivation_steps=(), parent_delta=(), observation_map="map",
            response_family="family", response_constraint="causal_affine",
            grammar_productions=("field",), conclusions=(), falsifiers=(),
            review_decision="proceed", data_exposure="synthetic_only")
    with pytest.raises(ValueError, match="synthetic fixtures only"):
        ForwardInductionRecord(
            record_id="not-reviewed", origin="step2_review", source_ref="file-ref",
            assumptions=("a",), key_derivation_steps=("d",), parent_delta=(), observation_map="map",
            response_family="family", response_constraint="causal_affine",
            grammar_productions=("field", "constant"), conclusions=("c",), falsifiers=("f",),
            review_decision="proceed", data_exposure="development_only")


def test_domain_parameter_reuse_is_allowed_inside_reviewed_family():
    scope = approved_scope()
    row = candidate(scope, changed_aspects=("parameter",))
    assert evaluate_candidate(row, scope, lambda value: value.candidate_id) == "c1"


def test_structural_change_needs_new_induction_even_if_units_match():
    scope = approved_scope(change_class="in_family_parameter")
    row = candidate(scope, changed_aspects=("response_structure",))
    with pytest.raises(InductionScopeError, match="structural_change_not_bound"):
        evaluate_candidate(row, scope, lambda _: 1.0)


def test_same_unit_nonlinear_tree_cannot_enter_linear_response_family():
    scope = approved_scope()
    row = candidate(scope, root=ASTNode.operator("multiply", ASTNode.field("x"), ASTNode.field("y")))
    calls = []
    with pytest.raises(ValueError, match="field-by-field product"):
        evaluate_candidate(row, scope, lambda value: calls.append(value))
    assert calls == []
