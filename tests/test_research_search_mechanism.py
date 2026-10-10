import pytest
from dataclasses import replace

from factor_factory.research_search.mechanism import (
    ExperimentEvidence, MechanismEvaluation, MechanismState, Prediction,
    ResearchAction, apply_research_action, run_mechanism_mcts,
)
from tests.research_search_d05_helpers import approved_scope


def _state():
    return MechanismState(
        state_id="root", mechanism="observed x drives a finite causal response",
        response_family="causal_affine_response_estimator",
        response_structure="affine distributed lag", induction_record_hash="synthetic-induction-hash",
        assumptions=("x is observed by t",),
        predictions=(Prediction("p-sign", "an x shock has the declared signed response",
                                ("common-cause-only",)),),
        competing_mechanisms=("common-cause-only",), unknowns=("response sign",),
    )


def _conditional_actions():
    return (
        ResearchAction("test-sign", "check_observation", "explore", 1.0,
                       "run the predeclared sign discrimination", resolve_unknowns=("response sign",)),
        ResearchAction("deepen-supported", "deepen", "exploit", 1.0,
                       "derive the supported branch", add_assumptions=("sign survived the test",),
                       requires_assessment=("supported",)),
        ResearchAction("revise-refuted", "deepen", "explore", 1.0,
                       "revise the refuted mechanism", mechanism="common cause drives both x and response",
                       requires_assessment=("refuted",)),
    )


def _evaluation(action, outcome="supports", *, protocol="disc-v1", comparable=True,
                discriminating=True, utility=0.8, score=-99.0):
    return MechanismEvaluation(
        ExperimentEvidence(f"synthetic://{action.action_id}", "p-sign", protocol, outcome,
                           comparable, discriminating, utility),
        actual_cost=1.0, implementation_score=score)


def test_action_creates_substantive_successor_and_prediction_id_is_immutable():
    root = _state()
    child = apply_research_action(root, _conditional_actions()[0])
    assert child.unknowns == ()
    assert child.depth == 1
    overwrite = ResearchAction(
        "overwrite", "deepen", "explore", 1.0, "change a prediction after seeing evidence",
        add_predictions=(Prediction("p-sign", "different statement", ("another",)),))
    with pytest.raises(ValueError, match="cannot be overwritten"):
        apply_research_action(root, overwrite)


def test_support_and_refutation_both_reward_discriminating_test_utility():
    for outcome in ("supports", "refutes"):
        result = run_mechanism_mcts(
            initial_state=_state(), actions=_conditional_actions(),
            evaluator=lambda state, action, seed, outcome=outcome: _evaluation(action, outcome),
            protocol_id="disc-v1", seed=4, total_budget=2.0, max_expansions=2, max_depth=2)
        first = result.expansions[0]
        assert first.research_reward == 0.8
        assert first.successor.mechanism_assessment == ("supported" if outcome == "supports" else "refuted")
        assert first.implementation_score == -99.0
        assert result.planning.trace[1].action_id == (
            "deepen-supported" if outcome == "supports" else "revise-refuted")


def test_new_response_without_induction_stops_before_effect_evaluator():
    action = ResearchAction("new-kernel", "derive_new_structure", "explore", 1.0,
                            "propose nonlinear response", response_family="nonlinear-response",
                            response_structure="quadratic kernel")
    calls = []
    result = run_mechanism_mcts(
        initial_state=_state(), actions=(action,),
        evaluator=lambda *args: calls.append(args), protocol_id="disc-v1", seed=1,
        total_budget=1.0, max_expansions=1)
    assert calls == []
    assert result.expansions[0].successor.status == "needs_induction"
    assert result.expansions[0].evidence is None
    assert result.decision == "needs_induction"


def test_new_response_with_matching_induction_delta_can_reach_evaluator():
    record = replace(
        approved_scope().induction_record,
        record_id="synthetic-three-lag-v1", response_family="causal-affine-three-lag",
        parent_delta=("extend the finite causal kernel from two lags to three",),
    )
    action = ResearchAction(
        "three-lag", "derive_new_structure", "explore", 1.0, "derive a reviewed three-lag response",
        response_family="causal-affine-three-lag", response_structure="affine three-lag kernel",
        induction_record=record)
    calls = []

    def evaluator(state, action, seed):
        calls.append((state.state_id, action.action_id, seed))
        return _evaluation(action)

    result = run_mechanism_mcts(
        initial_state=_state(), actions=(action,), evaluator=evaluator,
        protocol_id="disc-v1", seed=1, total_budget=1.0, max_expansions=1)
    assert len(calls) == 1
    assert result.expansions[0].successor.induction_record_hash == record.record_hash
    assert result.expansions[0].successor.response_structure == "affine three-lag kernel"


def test_mismatched_equivalence_and_expression_score_cannot_change_mechanism():
    action = _conditional_actions()[0]
    result = run_mechanism_mcts(
        initial_state=_state(), actions=(action,),
        evaluator=lambda state, action, seed: _evaluation(
            action, "observationally_equivalent", protocol="wrong-protocol",
            discriminating=False, utility=None, score=1000.0),
        protocol_id="disc-v1", seed=2, total_budget=1.0, max_expansions=1)
    expansion = result.expansions[0]
    assert expansion.research_reward is None
    assert expansion.successor.mechanism_assessment == "unknown"
    assert expansion.successor.status == "active"
    assert result.planning.trace[0].learning_increment is None
    assert result.decision == "needs_discriminating_evidence"


def test_stop_action_needs_no_evidence_or_evaluator_and_empty_unknowns_are_valid():
    state = _state()
    state = MechanismState(**{**state.__dict__, "unknowns": ()})
    stop = ResearchAction("stop", "stop", "exploit", 0.0, "stop this bounded branch")
    calls = []
    result = run_mechanism_mcts(
        initial_state=state, actions=(stop,), evaluator=lambda *args: calls.append(args),
        protocol_id="disc-v1", seed=3, total_budget=1.0, max_expansions=1)
    assert calls == []
    assert result.expansions == ()
    assert result.planning.trace[0].status == "stopped"
