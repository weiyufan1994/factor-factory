from __future__ import annotations

import pytest

from factor_factory.hybrid_research.decision import Action, Context, Observation
from factor_factory.hybrid_research.mcts import (
    ActionResult,
    PlannerContractError,
    ResearchState,
    run_action_mcts,
    run_simple_scheduler,
)


CONTEXT = Context.from_mapping(
    stage="development",
    objective="distinguish bounded response structures",
    conditions={"clock": "event", "input": "signed impulses"},
    evaluation_protocol="mcts-development-v1",
)


def action(
    action_id: str,
    *,
    mode: str = "exploit",
    cost: float = 1.0,
    family: str | None = None,
) -> Action:
    return Action(
        action_id=action_id,
        family=family or action_id,
        mode=mode,  # type: ignore[arg-type]
        estimated_cost=cost,
        rationale="registered bounded research action",
    )


def state() -> ResearchState:
    return ResearchState(
        context=CONTEXT,
        hypothesis_ref="hypothesis:conditional-transient-response",
        prediction_refs=("prediction:decay",),
        competing_explanation_refs=("alternative:permanent-component",),
    )


def evaluator_for(
    results: dict[str, float | None],
    *,
    costs: dict[str, float] | None = None,
    splits: dict[str, str] | None = None,
    statuses: dict[str, str] | None = None,
):
    calls: list[tuple[ResearchState, Action, int]] = []

    def evaluate(branch: ResearchState, selected: Action, seed: int) -> ActionResult:
        calls.append((branch, selected, seed))
        result = results[selected.action_id]
        status = (statuses or {}).get(selected.action_id, "completed")
        observation = Observation(
            run_id=f"run:{len(calls)}:{selected.action_id}",
            action_id=selected.action_id,
            context=branch.context,
            split=(splits or {}).get(selected.action_id, "development"),
            protocol_id=branch.context.evaluation_protocol,
            metric="recovery_error",
            direction=-1,
            baseline=1.0,
            result=result,
            scale=1.0,
            actual_cost=(costs or {}).get(selected.action_id, selected.estimated_cost),
            status=status,
            evidence_ref=f"evidence:{selected.action_id}:{len(calls)}",
        )
        return ActionResult(
            observation=observation,
            added_prediction_refs=(f"prediction:{selected.action_id}",),
            experiment_ref=observation.evidence_ref,
        )

    return evaluate, calls


def test_mcts_is_disabled_by_default_and_does_not_call_evaluator() -> None:
    evaluate, calls = evaluator_for({"a": 0.0})

    result = run_action_mcts(
        initial_state=state(),
        actions=(action("a"),),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=7,
        total_budget=1.0,
        max_expansions=1,
    )

    assert result.enabled is False
    assert result.expansion_count == 0
    assert result.stop_reason == "disabled: explicit opt-in required"
    assert calls == []


def test_planner_rejects_non_development_context_even_when_disabled() -> None:
    final_context = Context.from_mapping(
        stage="final",
        objective="forbidden",
        conditions={},
        evaluation_protocol="final-v1",
    )
    final_state = ResearchState(
        context=final_context,
        hypothesis_ref="hypothesis:final",
        prediction_refs=("prediction:final",),
        competing_explanation_refs=("alternative:final",),
    )

    with pytest.raises(ValueError, match="development context only"):
        run_action_mcts(
            initial_state=final_state,
            actions=(action("a"),),
            metric="recovery_error",
            direction=-1,
            seed=1,
            total_budget=1.0,
            max_expansions=1,
        )


def test_mcts_performs_selection_expansion_and_mean_backpropagation() -> None:
    actions = (
        action("deepen", cost=1.0),
        action("compete", mode="explore", cost=1.0),
        action("diagnose", mode="explore", cost=1.0),
    )
    evaluate, _ = evaluator_for({"deepen": 0.5, "compete": 0.2, "diagnose": 0.8})

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=actions,
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=11,
        total_budget=7.0,
        max_expansions=7,
        max_depth=3,
        exploration_weight=0.7,
        explore_share=0.5,
    )

    assert result.expansion_count == 7
    assert result.virtual_rollout_count == 0
    assert any(row.depth >= 2 for row in result.trace)
    root = result.nodes[0]
    assert root.visits == 7
    assert root.cost_sum == 7.0
    assert any(node.parent_node_id != "n000" and node.visits >= 1 for node in result.nodes)
    assert result.selected_action_id in {item.action_id for item in actions}


def test_mcts_replay_is_deterministic_for_same_seed_and_inputs() -> None:
    actions = (action("a"), action("b", mode="explore"), action("c", mode="explore"))

    def run():
        evaluate, _ = evaluator_for({"a": 0.5, "b": 0.25, "c": 0.75})
        return run_action_mcts(
            enabled=True,
            initial_state=state(),
            actions=actions,
            evaluator=evaluate,
            metric="recovery_error",
            direction=-1,
            seed=41,
            total_budget=6.0,
            max_expansions=6,
            max_depth=3,
            explore_share=0.5,
        )

    assert run() == run()


def test_mcts_does_not_relearn_or_recharge_identical_cached_runs_across_branches() -> None:
    actions = (action("a"), action("b"))

    def cached(branch: ResearchState, selected: Action, seed: int) -> ActionResult:
        del seed
        return ActionResult(Observation(
            run_id=f"cached:{selected.action_id}",
            action_id=selected.action_id,
            context=branch.context,
            split="development",
            protocol_id=branch.context.evaluation_protocol,
            metric="recovery_error",
            direction=-1,
            baseline=1.0,
            result=0.5,
            scale=1.0,
            actual_cost=1.0,
            status="completed",
            evidence_ref=f"evidence:cached:{selected.action_id}",
        ))

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=actions,
        evaluator=cached,
        metric="recovery_error",
        direction=-1,
        seed=17,
        total_budget=4.0,
        max_expansions=4,
        max_depth=2,
        explore_share=0.0,
    )

    assert result.expansion_count == 4
    assert result.spent_cost == 2.0
    assert result.nodes[0].visits == 2
    assert result.nodes[0].value_sum == 1.0
    duplicates = [row for row in result.trace if row.status == "duplicate_observation_not_relearned"]
    assert len(duplicates) == 2
    assert all(row.actual_cost == 0.0 and row.learning_increment is None for row in duplicates)


def test_mcts_rejects_conflicting_reuse_of_run_id() -> None:
    actions = (action("a"), action("b"))
    calls: dict[str, int] = {"a": 0, "b": 0}

    def conflict(branch: ResearchState, selected: Action, seed: int) -> ActionResult:
        del seed
        calls[selected.action_id] += 1
        return ActionResult(Observation(
            run_id=f"cached:{selected.action_id}",
            action_id=selected.action_id,
            context=branch.context,
            split="development",
            protocol_id=branch.context.evaluation_protocol,
            metric="recovery_error",
            direction=-1,
            baseline=1.0,
            result=0.5 + 0.1 * calls[selected.action_id],
            scale=1.0,
            actual_cost=1.0,
            status="completed",
            evidence_ref=f"evidence:cached:{selected.action_id}",
        ))

    with pytest.raises(ValueError, match="conflicting duplicate run_id"):
        run_action_mcts(
            enabled=True,
            initial_state=state(),
            actions=actions,
            evaluator=conflict,
            metric="recovery_error",
            direction=-1,
            seed=17,
            total_budget=4.0,
            max_expansions=4,
            max_depth=2,
            explore_share=0.0,
        )


def test_explore_share_controls_real_expansion_opportunities() -> None:
    actions = (action("exploit"), action("explore", mode="explore"))
    evaluate, _ = evaluator_for({"exploit": 0.5, "explore": 0.5})

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=actions,
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=3,
        total_budget=2.0,
        max_expansions=2,
        explore_share=0.5,
    )

    assert [row.action_mode for row in result.trace] == ["exploit", "explore"]


@pytest.mark.parametrize("planner", [run_action_mcts, run_simple_scheduler])
def test_matching_development_prior_changes_first_action_without_disabling_online_adaptation(
    planner,
) -> None:
    actions = (action("a", family="a"), action("b", family="b"))
    priors = (
        Observation(
            "prior:a", "a", CONTEXT, "development", CONTEXT.evaluation_protocol,
            "recovery_error", -1, 1.0, 0.9, 1.0, 1.0, "completed", "evidence:prior:a",
        ),
        Observation(
            "prior:b", "b", CONTEXT, "development", CONTEXT.evaluation_protocol,
            "recovery_error", -1, 1.0, 0.1, 1.0, 1.0, "completed", "evidence:prior:b",
        ),
    )
    evaluate, _ = evaluator_for({"a": 0.2, "b": 0.2})

    result = planner(
        enabled=True,
        initial_state=state(),
        actions=actions,
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=19,
        total_budget=2.0,
        max_expansions=2,
        max_depth=2,
        explore_share=0.0,
        prior_observations=priors,
    )

    assert result.trace[0].action_id == "b"
    assert result.expansion_count == 2


@pytest.mark.parametrize("planner", [run_action_mcts, run_simple_scheduler])
def test_prior_observations_must_be_development_only(planner) -> None:
    held_out = Observation(
        "prior:final", "a", CONTEXT, "final", CONTEXT.evaluation_protocol,
        "recovery_error", -1, 1.0, 0.0, 1.0, 1.0, "completed", "evidence:final",
    )

    with pytest.raises(ValueError, match="development-only"):
        planner(
            initial_state=state(),
            actions=(action("a"),),
            metric="recovery_error",
            direction=-1,
            seed=1,
            total_budget=1.0,
            max_expansions=1,
            prior_observations=(held_out,),
        )


def test_hard_budget_reserves_cost_before_evaluator_call() -> None:
    evaluate, calls = evaluator_for({"expensive": 0.0})

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=(action("expensive", cost=2.0),),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=1,
        total_budget=1.0,
        max_expansions=2,
    )

    assert calls == []
    assert result.spent_cost == 0.0
    assert result.stop_reason == "no_expandable_branch_within_budget"


def test_actual_cost_cannot_exceed_reserved_or_remaining_budget() -> None:
    evaluate, _ = evaluator_for({"a": 0.0}, costs={"a": 1.5})

    with pytest.raises(PlannerContractError, match="reservation cap") as caught:
        run_action_mcts(
            enabled=True,
            initial_state=state(),
            actions=(action("a", cost=1.0),),
            evaluator=evaluate,
            metric="recovery_error",
            direction=-1,
            seed=1,
            total_budget=2.0,
            max_expansions=1,
        )

    partial = caught.value.partial_result
    assert partial.failure is not None
    assert partial.failure.kind == "evaluator_contract_violation"
    assert partial.failure.known_actual_cost == 1.5
    assert partial.spent_cost == 1.5
    assert partial.trace[-1].status == "evaluator_contract_violation"


@pytest.mark.parametrize("planner", [run_action_mcts, run_simple_scheduler])
def test_evaluator_exception_stops_without_inventing_cost_or_retry(planner) -> None:
    calls = 0

    def broken(branch: ResearchState, selected: Action, seed: int) -> ActionResult:
        nonlocal calls
        calls += 1
        raise RuntimeError("unknown completion")

    result = planner(
        enabled=True,
        initial_state=state(),
        actions=(action("a"),),
        evaluator=broken,
        metric="recovery_error",
        direction=-1,
        seed=1,
        total_budget=1.0,
        max_expansions=3,
    )

    assert calls == 1
    assert result.stop_reason == "evaluator_exception_unknown_cost"
    assert result.failure is not None
    assert result.failure.known_actual_cost is None
    assert result.spent_cost == 0.0
    assert result.trace[-1].actual_cost is None


def test_failed_attempt_counts_cost_without_becoming_reward() -> None:
    evaluate, _ = evaluator_for(
        {"fail": None},
        statuses={"fail": "failed"},
    )

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=(action("fail"),),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=1,
        total_budget=1.0,
        max_expansions=1,
    )

    assert result.spent_cost == 1.0
    assert result.trace[0].learning_increment is None
    assert result.nodes[0].value_sum == 0.0
    assert result.nodes[0].cost_sum == 1.0


@pytest.mark.parametrize("split", ["final", "confirmation"])
def test_final_and_confirmation_are_recorded_but_never_learned(split: str) -> None:
    evaluate, _ = evaluator_for(
        {"a": 0.0, "b": 0.0},
        splits={"a": split, "b": split},
    )

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=(action("a"), action("b")),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=1,
        total_budget=2.0,
        max_expansions=2,
    )

    row = result.trace[0]
    child = next(node for node in result.nodes if node.node_id == row.node_id)
    assert row.status == "recorded_non_development_not_learned"
    assert row.learning_increment is None
    assert child.terminal is True
    assert child.value_sum == 0.0
    assert child.visits == 0
    assert child.development_evidence is False
    assert result.nodes[0].visits == 0
    assert result.selected_action_id is None


def test_explicit_stop_is_a_zero_cost_terminal_branch_without_evaluation() -> None:
    stop = action("stop", cost=0.0)
    evaluate, calls = evaluator_for({"work": 0.0})

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=(stop,),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=9,
        total_budget=0.0,
        max_expansions=1,
        stop_action_ids=("stop",),
    )

    assert calls == []
    assert result.trace[0].status == "stopped"
    assert result.spent_cost == 0.0
    assert result.selected_action_id is None


def test_unknown_development_observation_cannot_become_a_recommendation() -> None:
    evaluate, _ = evaluator_for({"a": None}, statuses={"a": "unknown"})

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=(action("a"),),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=9,
        total_budget=1.0,
        max_expansions=1,
    )

    child = next(node for node in result.nodes if node.parent_node_id == "n000")
    assert result.trace[0].status == "unknown"
    assert result.trace[0].learning_increment is None
    assert child.development_evidence is False
    assert result.selected_action_id is None


@pytest.mark.parametrize(
    ("result_value", "status"),
    [(2.0, "completed"), (None, "failed")],
)
def test_stop_outside_option_beats_negative_or_failed_root_branch(
    result_value: float | None,
    status: str,
) -> None:
    actions = (action("work"), action("stop", cost=0.0))
    evaluate, _ = evaluator_for(
        {"work": result_value},
        statuses={"work": status},
    )

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=actions,
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=4,
        total_budget=1.0,
        max_expansions=2,
        stop_action_ids=("stop",),
    )

    assert {row.action_id for row in result.trace} == {"work", "stop"}
    assert result.selected_action_id is None


def test_registered_stop_beats_negative_root_before_stop_is_expanded() -> None:
    actions = (action("work"), action("stop", cost=0.0))
    evaluate, _ = evaluator_for({"work": 2.0})

    result = run_action_mcts(
        enabled=True,
        initial_state=state(),
        actions=actions,
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=5,
        total_budget=1.0,
        max_expansions=1,
        stop_action_ids=("stop",),
    )

    assert [row.action_id for row in result.trace] == ["work"]
    assert result.trace[0].learning_increment == -1.0
    assert result.selected_action_id is None


def test_observation_must_match_action_context_and_protocol() -> None:
    selected = action("a")

    def wrong_context(branch: ResearchState, action_: Action, seed: int) -> ActionResult:
        del branch, seed
        other = Context.from_mapping(
            stage="development",
            objective="other",
            conditions={},
            evaluation_protocol=CONTEXT.evaluation_protocol,
        )
        return ActionResult(Observation(
            "wrong", action_.action_id, other, "development", other.evaluation_protocol,
            "recovery_error", -1, 1.0, 0.0, 1.0, 1.0, "completed", "evidence:wrong",
        ))

    with pytest.raises(ValueError, match="context"):
        run_action_mcts(
            enabled=True,
            initial_state=state(),
            actions=(selected,),
            evaluator=wrong_context,
            metric="recovery_error",
            direction=-1,
            seed=2,
            total_budget=1.0,
            max_expansions=1,
        )


def test_simple_scheduler_uses_same_actions_evaluator_and_hard_budget_contract() -> None:
    actions = (action("a", cost=1.0), action("b", mode="explore", cost=1.0))
    evaluate, calls = evaluator_for({"a": 0.4, "b": 0.2})

    result = run_simple_scheduler(
        enabled=True,
        initial_state=state(),
        actions=actions,
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=5,
        total_budget=2.0,
        max_expansions=2,
        max_depth=2,
        explore_share=0.5,
    )

    assert result.algorithm == "simple_scheduler"
    assert result.spent_cost == 2.0
    assert result.expansion_count == 2
    assert len(calls) == 2
    assert {row.action_id for row in result.trace} == {item.action_id for item in actions}
    assert result.selected_action_id is None
    assert result.first_executed_action_id == result.trace[0].action_id


@pytest.mark.parametrize("split", ["final", "confirmation"])
def test_simple_scheduler_never_returns_non_development_action_as_recommendation(
    split: str,
) -> None:
    evaluate, _ = evaluator_for({"a": 0.0}, splits={"a": split})

    result = run_simple_scheduler(
        enabled=True,
        initial_state=state(),
        actions=(action("a"),),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=5,
        total_budget=1.0,
        max_expansions=1,
    )

    assert result.trace[0].status == "recorded_non_development_not_learned"
    assert result.selected_action_id is None
    assert result.first_executed_action_id == "a"


@pytest.mark.parametrize("planner", [run_action_mcts, run_simple_scheduler])
def test_prior_path_and_cost_are_preserved_while_budget_is_invocation_local(planner) -> None:
    initial = ResearchState(
        context=CONTEXT,
        hypothesis_ref="hypothesis:resumed",
        prediction_refs=("prediction:resumed",),
        competing_explanation_refs=("alternative:resumed",),
        experiment_refs=("evidence:prior",),
        completed_action_ids=("prior-action",),
        incurred_cost=9.0,
        depth=1,
    )
    evaluate, _ = evaluator_for({"new-action": 0.5})

    result = planner(
        enabled=True,
        initial_state=initial,
        actions=(action("new-action"),),
        evaluator=evaluate,
        metric="recovery_error",
        direction=-1,
        seed=5,
        total_budget=9.0,
        max_expansions=1,
        max_depth=3,
        explore_share=0.0,
    )

    assert result.total_budget == 9.0
    assert result.prior_incurred_cost == 9.0
    assert result.spent_cost == 1.0
    assert result.cumulative_known_cost == 10.0
    assert result.trace[0].path_action_ids == ("prior-action", "new-action")
