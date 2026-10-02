"""Architect-owned regressions from the independent W04b review.

Synthetic action evidence only: these checks do not establish alpha quality,
causal identification, or a benefit from MCTS over the simple scheduler.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from factor_factory.hybrid_research.decision import Action, Context, Observation
from factor_factory.hybrid_research.mcts import (
    ActionResult,
    ResearchState,
    run_action_mcts,
    run_simple_scheduler,
)


CONTEXT = Context.from_mapping(
    stage="development",
    objective="independent bounded action review",
    conditions={"data": "synthetic", "scope": "engineering"},
    evaluation_protocol="independent-w04b-v1",
)
PLANNERS = (run_action_mcts, run_simple_scheduler)


def initial() -> ResearchState:
    return ResearchState(
        context=CONTEXT,
        hypothesis_ref="hypothesis:transient-response",
        prediction_refs=("prediction:response-decays",),
        competing_explanation_refs=("rival:permanent-response",),
    )


def action(name: str, cost: float = 1.0) -> Action:
    return Action(name, name, "exploit", cost, "predeclared synthetic action")


def observation(
    branch: ResearchState,
    selected: Action,
    run_id: str,
    *,
    value: float | None = 1.0,
    status: str = "completed",
    split: str = "development",
) -> ActionResult:
    return ActionResult(
        Observation(
            run_id=run_id,
            action_id=selected.action_id,
            context=branch.context,
            split=split,
            protocol_id=CONTEXT.evaluation_protocol,
            metric="distinguishing_gain",
            direction=1,
            baseline=0.0,
            result=value,
            scale=1.0,
            actual_cost=selected.estimated_cost,
            status=status,
            evidence_ref=f"synthetic:{run_id}",
        )
    )


def run(planner, evaluator, *, actions=None, start=None, **overrides):
    options = dict(
        enabled=True,
        initial_state=start or initial(),
        actions=actions or (action("work"),),
        evaluator=evaluator,
        metric="distinguishing_gain",
        direction=1,
        seed=1,
        total_budget=4.0,
        max_expansions=4,
        max_depth=2,
        explore_share=0.0,
    )
    options.update(overrides)
    return planner(**options)


@pytest.mark.parametrize("depth", (1, 3))
@pytest.mark.parametrize(
    ("value", "status"), ((-1.0, "completed"), (None, "failed"))
)
def test_stop_is_not_penalized_for_zero_cost_or_fewer_visits(value, status, depth):
    calls = []

    def evaluate(branch, selected, seed):
        assert selected.action_id != "stop"
        calls.append((selected.action_id, seed))
        return observation(branch, selected, f"fresh:{len(calls)}", value=value, status=status)

    result = run(
        run_action_mcts,
        evaluate,
        actions=(action("work"), action("stop", 0.0)),
        total_budget=1.0,
        max_expansions=8,
        max_depth=depth,
        stop_action_ids=("stop",),
    )

    assert {row.action_id for row in result.trace} == {"work", "stop"}
    assert result.selected_action_id is None
    assert result.spent_cost == 1.0
    assert len(calls) == 1


def test_known_stop_does_not_need_an_extra_expansion_to_beat_negative_work():
    def evaluate(branch, selected, seed):
        return observation(branch, selected, "negative-before-cap", value=-1.0)

    result = run(
        run_action_mcts,
        evaluate,
        actions=(action("work"), action("stop", 0.0)),
        seed=5,
        total_budget=1.0,
        max_expansions=1,
        max_depth=1,
        stop_action_ids=("stop",),
    )

    assert [row.action_id for row in result.trace] == ["work"]
    assert result.selected_action_id is None


@pytest.mark.parametrize("planner", PLANNERS)
@pytest.mark.parametrize("split", ("final", "confirmation"))
def test_held_out_result_cannot_become_a_recommendation(planner, split):
    def evaluate(branch, selected, seed):
        return observation(branch, selected, "held-out", split=split)

    result = run(planner, evaluate, total_budget=1.0, max_expansions=1)

    assert result.trace[0].status == "recorded_non_development_not_learned"
    assert result.trace[0].learning_increment is None
    assert result.selected_action_id is None
    assert result.spent_cost == 1.0


def test_cached_run_is_not_fresh_evidence_on_another_mcts_path():
    calls = []

    def evaluate(branch, selected, seed):
        calls.append((branch.completed_action_ids, selected.action_id))
        return observation(branch, selected, f"cached:{selected.action_id}")

    result = run(run_action_mcts, evaluate, actions=(action("a"), action("b")))

    assert len(calls) == 4
    assert sum(row.depth == 2 for row in result.trace) == 2
    assert result.nodes[0].visits == 2
    assert result.nodes[0].value_sum == 2.0
    assert result.nodes[0].cost_sum == 2.0
    assert result.spent_cost == 2.0
    duplicates = [row for row in result.trace if row.status == "duplicate_observation_not_relearned"]
    assert len(duplicates) == 2
    assert all(row.learning_increment is None for row in duplicates)


def test_conflicting_cached_run_is_rejected_instead_of_relearned():
    calls = {}

    def evaluate(branch, selected, seed):
        count = calls.get(selected.action_id, 0) + 1
        calls[selected.action_id] = count
        return observation(
            branch, selected, f"cached:{selected.action_id}", value=1.0 / count
        )

    with pytest.raises(ValueError, match="conflicting duplicate run_id"):
        run(run_action_mcts, evaluate, actions=(action("a"), action("b")))


@pytest.mark.parametrize("planner", PLANNERS)
def test_resume_trace_keeps_preexisting_action_prefix(planner):
    start = replace(initial(), completed_action_ids=("prior",), incurred_cost=9.0, depth=1)

    def evaluate(branch, selected, seed):
        assert branch.completed_action_ids == ("prior",)
        return observation(branch, selected, "continued")

    result = run(planner, evaluate, start=start, total_budget=1.0, max_expansions=1)

    assert result.trace[0].path_action_ids == ("prior", "work")
    assert result.trace[0].depth == 2
    if result.nodes:
        assert result.nodes[-1].completed_action_ids == result.trace[0].path_action_ids


@pytest.mark.parametrize("planner", PLANNERS)
def test_incremental_budget_is_separate_from_prior_and_cumulative_cost(planner):
    start = replace(initial(), completed_action_ids=("prior",), incurred_cost=9.0, depth=1)

    def evaluate(branch, selected, seed):
        return observation(branch, selected, "continued")

    result = run(planner, evaluate, start=start, total_budget=1.0, max_expansions=1)

    assert result.prior_incurred_cost == 9.0
    assert result.spent_cost == 1.0
    assert result.cumulative_known_cost == 10.0
    assert result.spent_cost <= result.total_budget


@pytest.mark.parametrize("planner", PLANNERS)
def test_no_budget_does_not_call_or_report_historical_cost_as_new(planner):
    def forbidden_evaluator(branch, selected, seed):
        pytest.fail("no additional budget was supplied")

    result = run(
        planner,
        forbidden_evaluator,
        start=replace(initial(), incurred_cost=9.0),
        total_budget=0.0,
    )

    assert result.expansion_count == 0
    assert result.spent_cost == 0.0
    assert result.prior_incurred_cost == result.cumulative_known_cost == 9.0


@pytest.mark.parametrize("planner", PLANNERS)
def test_callback_failure_keeps_partial_progress_and_unknown_cost(planner):
    calls = []

    def evaluate(branch, selected, seed):
        calls.append(selected.action_id)
        if len(calls) == 2:
            raise RuntimeError("synthetic interrupted action")
        return observation(branch, selected, "completed-before-interruption")

    result = run(
        planner,
        evaluate,
        actions=(action("a"), action("b"), action("c")),
        max_depth=3,
    )

    assert len(calls) == len(result.trace) == 2
    assert result.failure is not None
    assert result.failure.kind == "evaluator_exception"
    assert result.failure.known_actual_cost is None
    assert result.trace[-1].actual_cost is None
    assert result.trace[-1].learning_increment is None
    assert result.spent_cost == result.cumulative_known_cost == 1.0
    assert result.first_executed_action_id == calls[0]
    if result.nodes:
        assert result.nodes[0].visits == result.nodes[0].value_sum == 1


@pytest.mark.parametrize("planner", PLANNERS)
@pytest.mark.parametrize("bad_cost", (2.0, None))
def test_invalid_returned_cost_rejects_and_preserves_prior_progress(planner, bad_cost):
    calls = []

    def evaluate(branch, selected, seed):
        calls.append(selected.action_id)
        response = observation(branch, selected, f"cost-check:{len(calls)}")
        if len(calls) == 2:
            return replace(response, observation=replace(response.observation, actual_cost=bad_cost))
        return response

    with pytest.raises(ValueError) as rejected:
        run(
            planner,
            evaluate,
            actions=(action("a"), action("b"), action("c")),
            total_budget=2.0,
            max_depth=3,
        )

    partial = rejected.value.partial_result
    assert len(calls) == len(partial.trace) == 2
    assert partial.failure is not None
    assert partial.failure.kind == "evaluator_contract_violation"
    assert partial.failure.known_actual_cost == bad_cost
    assert partial.trace[-1].actual_cost == bad_cost
    assert partial.trace[-1].learning_increment is None
    assert partial.spent_cost == (3.0 if bad_cost is not None else 1.0)
    assert partial.first_executed_action_id == calls[0]
    if partial.nodes:
        assert partial.nodes[0].visits == partial.nodes[0].value_sum == 1


@pytest.mark.parametrize("planner", PLANNERS)
def test_first_invocation_is_recorded_even_when_it_fails(planner):
    calls = []

    def evaluate(branch, selected, seed):
        calls.append(selected.action_id)
        raise RuntimeError("synthetic failure before evidence returned")

    result = run(planner, evaluate)

    assert calls == ["work"]
    assert result.first_executed_action_id == "work"
    assert result.failure is not None
    assert result.failure.known_actual_cost is None
    assert result.trace[0].actual_cost is None
