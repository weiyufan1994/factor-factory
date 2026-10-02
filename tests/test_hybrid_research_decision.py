from __future__ import annotations

import pytest

from factor_factory.hybrid_research.decision import Action, Context, Observation, ScheduleState, learn_policy, select_action


CONTEXT = Context.from_mapping(
    stage="step2",
    objective="distinguish response structures",
    conditions={"market": "synthetic", "window": "development"},
    evaluation_protocol="response-recovery-v1",
)


def action(name: str, family: str, mode: str = "exploit", cost: float = 1.0) -> Action:
    return Action(name, family, mode, cost, "registered research action")  # type: ignore[arg-type]


def observation(
    run_id: str,
    action_id: str,
    *,
    context: Context = CONTEXT,
    result: float | None = 0.0,
    split: str = "development",
    protocol_id: str = "response-recovery-v1",
    status: str = "completed",
    actual_cost: float | None = 1.0,
    evidence_ref: str | None = None,
) -> Observation:
    return Observation(
        run_id, action_id, context, split, protocol_id, "recovery_error", -1,
        10.0, result, 10.0, actual_cost, status, evidence_ref if evidence_ref is not None else f"evidence:{run_id}",
    )


def test_comparable_feedback_changes_exploit_choice() -> None:
    actions = (action("kernel:short", "kernel"), action("state:two-scale", "state"))
    policy = learn_policy((
        observation("run-kernel", "kernel:short", result=8.0),
        observation("run-state", "state:two-scale", result=2.0),
    ), actions)

    decision = select_action(
        context=CONTEXT, actions=actions, candidates=policy,
        metric="recovery_error", direction=-1, remaining_budget=2.0,
    )

    assert decision.action == actions[1]
    assert decision.supporting_runs == ("run-state",)


def test_mismatched_context_metric_or_protocol_does_not_transfer() -> None:
    changed_conditions = Context.from_mapping(
        stage="step2", objective="distinguish response structures",
        conditions={"market": "synthetic", "window": "changed"},
        evaluation_protocol="response-recovery-v1",
    )
    actions = (action("kernel:short", "kernel"), action("state:two-scale", "state"))
    policy = learn_policy((
        observation("condition", "state:two-scale", context=changed_conditions, result=2.0),
        observation("protocol", "state:two-scale", protocol_id="other-v1", result=2.0),
    ), actions)

    decision = select_action(
        context=CONTEXT,
        actions=actions,
        candidates=policy, metric="recovery_error", direction=-1, remaining_budget=2.0,
    )

    assert decision.action is not None
    assert decision.action.action_id == "kernel:short"
    assert decision.reason.startswith("baseline")


def test_final_failure_and_non_finite_records_remain_but_do_not_learn() -> None:
    observations = (
        observation("final", "state:two-scale", result=0.0, split="final"),
        observation("failed", "state:two-scale", result=None, status="failed"),
        observation("nan", "state:two-scale", result=float("nan")),
    )

    assert learn_policy(observations, (action("state:two-scale", "state"),)) == ()


def test_duplicate_run_is_idempotent_but_conflict_is_rejected() -> None:
    row = observation("same", "kernel:short", result=8.0)
    actions = (action("kernel:short", "kernel"),)
    assert len(learn_policy((row, row), actions)) == 1

    with pytest.raises(ValueError, match="conflicting duplicate"):
        learn_policy((row, observation("same", "kernel:short", result=5.0)), actions)


def test_explore_and_stop_are_explicit_legal_outcomes() -> None:
    explore = action("mechanism:new", "mechanism", "explore", cost=1.0)
    chosen = select_action(
        context=CONTEXT, actions=(explore,), candidates=(), metric="recovery_error",
        direction=-1, remaining_budget=1.0, explore_share=1.0,
    )
    stopped = select_action(
        context=CONTEXT, actions=(explore,), candidates=(), metric="recovery_error",
        direction=-1, remaining_budget=0.0, explore_share=1.0,
    )

    assert chosen.action == explore
    assert chosen.reason.startswith("explore")
    assert stopped.action is None
    assert stopped.reason.startswith("STOP")


def test_explore_share_and_episode_index_produce_replayable_mixed_schedule() -> None:
    actions = (
        action("a:exploit", "a"), action("b:exploit", "b"),
        action("e:explore", "e", "explore"), action("f:explore", "f", "explore"),
    )
    state = ScheduleState()
    selected = []
    for _ in range(8):
        decision = select_action(
            context=CONTEXT, actions=actions, candidates=(), metric="recovery_error",
            direction=-1, remaining_budget=1.0, explore_share=0.5, schedule_state=state,
        )
        selected.append(decision)
        state = decision.next_schedule_state

    assert [decision.action.action_id for decision in selected if decision.action] == [
        "a:exploit", "e:explore", "b:exploit", "f:explore",
        "a:exploit", "e:explore", "b:exploit", "f:explore",
    ]
    assert selected[3].next_schedule_state == ScheduleState(4, 2, 2)


def test_baseline_round_robin_can_resume_from_saved_episode_index() -> None:
    actions = (action("a:kernel", "kernel"), action("b:state", "state"))
    first = select_action(
        context=CONTEXT, actions=actions, candidates=(), metric="recovery_error",
        direction=-1, remaining_budget=1.0, episode_index=0,
    )
    resumed = select_action(
        context=CONTEXT, actions=actions, candidates=(), metric="recovery_error",
        direction=-1, remaining_budget=1.0, episode_index=first.next_episode_index,
    )

    assert first.action == actions[0]
    assert resumed.action == actions[1]


def test_unknown_cost_never_receives_a_gain_per_cost_advantage() -> None:
    actions = (action("unknown:one", "unknown"), action("priced:one", "priced"))
    policy = learn_policy((
        observation("unknown", "unknown:one", result=0.0, actual_cost=None),
        observation("priced", "priced:one", result=5.0, actual_cost=100.0),
    ), actions)

    decision = select_action(
        context=CONTEXT, actions=actions, candidates=policy, metric="recovery_error",
        direction=-1, remaining_budget=1.0,
    )

    assert decision.action == actions[1]
    assert next(item for item in policy if item.family == "unknown").efficiency is None


def test_failed_attempt_cost_counts_without_becoming_negative_mechanism_evidence() -> None:
    actions = (action("kernel:one", "kernel"),)
    policy = learn_policy((
        observation("pass", "kernel:one", result=0.0, actual_cost=1.0),
        observation("failed", "kernel:one", result=None, status="failed", actual_cost=100.0),
    ), actions)

    candidate = policy[0]
    assert candidate.mean_increment == 1.0
    assert candidate.mean_attempt_cost == 50.5
    assert candidate.total_increment == 1.0
    assert candidate.total_attempt_cost == 101.0
    assert candidate.failed_attempt_count == 1


def test_positive_cost_failures_cannot_increase_evidence_efficiency_or_reverse_priority() -> None:
    actions = (action("a:one", "a"), action("b:one", "b"))
    baseline = learn_policy((
        observation("a-success", "a:one", result=0.0, actual_cost=10.0),
        observation("b-success", "b:one", result=1.0, actual_cost=10.0),
    ), actions)
    with_failures = learn_policy((
        observation("a-success", "a:one", result=0.0, actual_cost=10.0),
        observation("b-success", "b:one", result=1.0, actual_cost=10.0),
        *(observation(f"a-fail-{index}", "a:one", result=None, status="failed", actual_cost=1.0) for index in range(9)),
    ), actions)

    initial_a = next(item for item in baseline if item.family == "a")
    failed_a = next(item for item in with_failures if item.family == "a")
    decision = select_action(
        context=CONTEXT, actions=actions, candidates=with_failures,
        metric="recovery_error", direction=-1, remaining_budget=1.0,
    )

    assert failed_a.efficiency is not None and initial_a.efficiency is not None
    assert failed_a.efficiency < initial_a.efficiency
    assert decision.action == actions[1]


def test_completed_observation_requires_nonempty_evidence_reference_to_learn() -> None:
    actions = (action("kernel:one", "kernel"),)
    policy = learn_policy((
        observation("missing", "kernel:one", result=0.0, evidence_ref=""),
    ), actions)

    assert policy == ()
