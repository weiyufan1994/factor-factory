from __future__ import annotations

from dataclasses import replace

import pytest

import factor_factory.hybrid_research.evaluation_v2 as evaluation
from factor_factory.hybrid_research.decision import Observation
from factor_factory.hybrid_research.gp_adapter import KernelTerm, ResponseProgram
from factor_factory.hybrid_research.mcts import (
    ActionResult,
    ExpansionRecord,
    PlanningResult,
    ResearchState,
    run_simple_scheduler,
)


def test_v2_protocol_uses_real_mechanism_experiments_and_locked_tasks() -> None:
    manifest = evaluation.protocol_manifest()

    assert manifest["protocol_version"] == "hybrid-w08-mechanism-v2"
    assert manifest["task_families"] == [
        "matching", "condition_change", "misleading_prior",
    ]
    assert manifest["numeric_seeds"] == [11, 29, 47]
    assert manifest["task_count"] == 9
    assert "GP fit" in manifest["actual_experiments"]
    assert manifest["v1_status"].startswith("toy scheduler fixture")


def test_development_run_executes_gp_and_never_reads_hidden_final(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("hidden final oracle was read")

    monkeypatch.setattr(evaluation, "_oracle_quality", forbidden)
    report = evaluation.run_locked_evaluation(include_final=False)

    assert len(report.records) == 36
    assert all(row.final_quality is None for row in report.records)
    assert all(row.candidate_evaluations > row.evaluator_calls for row in report.records)
    assert all(row.run_complete and row.cost_complete for row in report.records)
    assert all(row.failed_attempts == 0 for row in report.records)


def test_mcts_reaches_tree_depth_two_and_feedback_selects_first_deeper_branch() -> None:
    report = evaluation.run_locked_evaluation(include_final=False)
    records = [row for row in report.records if row.algorithm == "mcts"]

    assert len(records) == 18
    assert all(row.max_tree_depth == 2 for row in records)
    assert all(row.target_spent_cost <= evaluation.TARGET_BUDGET for row in records)
    assert all(row.candidate_evaluations > 4 for row in records)
    assert all(
        row.candidate_evaluations == row.shared_history_cost + row.target_spent_cost
        for row in records
    )
    assert all(
        row.first_deeper_parent_utility == pytest.approx(row.best_root_utility)
        for row in records
    )


def test_common_source_history_cost_is_matched_between_c0_and_c1() -> None:
    report = evaluation.run_locked_evaluation(include_final=False)
    grouped = {(row.task_id, row.algorithm, row.arm): row for row in report.records}

    for task in evaluation.locked_task_specs():
        for algorithm in ("mcts", "simple_scheduler"):
            c0 = grouped[(task.task_id, algorithm, "C0")]
            c1 = grouped[(task.task_id, algorithm, "C1")]
            assert c0.shared_history_cost == c1.shared_history_cost
            assert c0.shared_history_cost > 0
            assert c0.experience_consumption_cost == c1.experience_consumption_cost == 0.0
            assert c0.total_observed_cost == c0.shared_history_cost + c0.target_spent_cost
            assert c1.total_observed_cost == c1.shared_history_cost + c1.target_spent_cost


def test_condition_change_blocks_transfer() -> None:
    report = evaluation.run_locked_evaluation(include_final=False)
    transfer = report.transfer_pairs

    condition = [row for row in transfer if row["family"] == "condition_change"]
    assert all(row["quality_delta"] == 0 for row in condition)


def test_simple_scheduler_can_pivot_to_competing_family_after_negative_feedback() -> None:
    task = evaluation.locked_task_specs()[0]
    actions = evaluation.registered_actions()
    initial = ResearchState(
        task.target_context,
        "hypothesis:test",
        ("prediction:test",),
        ("rival:test",),
    )
    prior = Observation(
        "prior:single", "fit-single", task.target_context, "development",
        task.target_context.evaluation_protocol, "recovery_error", -1,
        1.0, 0.0, 1.0, 8.0, "completed", "evidence:prior:single",
    )

    def run(result_value):
        calls = []

        def evaluator(branch, action, seed):
            calls.append(action.action_id)
            return ActionResult(Observation(
                f"run:{len(calls)}", action.action_id, branch.context, "development",
                branch.context.evaluation_protocol, "recovery_error", -1,
                1.0, result_value if len(calls) == 1 else 0.5, 1.0,
                1.0, "completed", f"evidence:{len(calls)}",
            ))

        run_simple_scheduler(
            enabled=True, initial_state=initial, actions=actions, evaluator=evaluator,
            metric="recovery_error", direction=-1, seed=1, total_budget=20.0,
            max_expansions=2, max_depth=3, explore_share=0.0,
            prior_observations=(prior,), action_available=lambda state, action: (
                evaluation._action_available(state, action)
                and not action.action_id.startswith("diagnose-")
            ), avoid_nonpositive_families=True,
            feedback_family=evaluation._feedback_family,
        )
        return calls

    positive = run(0.0)
    negative = run(2.0)
    assert positive[0] == negative[0] == "fit-single"
    assert positive[1] == "refine-single"
    assert negative[1] in {"fit-two-scale", "fit-permanent"}


def test_generic_simple_scheduler_does_not_enable_family_avoidance_by_default() -> None:
    task = evaluation.locked_task_specs()[0]
    actions = evaluation.registered_actions()
    initial = ResearchState(
        task.target_context, "hypothesis:test", ("prediction:test",), ("rival:test",),
    )
    prior = Observation(
        "prior:single", "fit-single", task.target_context, "development",
        task.target_context.evaluation_protocol, "recovery_error", -1,
        1.0, 0.0, 1.0, 8.0, "completed", "evidence:prior:single",
    )

    def execute(first_result):
        calls = []

        def evaluator(branch, action, seed):
            calls.append(action.action_id)
            return ActionResult(Observation(
                f"default:{len(calls)}", action.action_id, branch.context, "development",
                branch.context.evaluation_protocol, "recovery_error", -1,
                1.0, first_result if len(calls) == 1 else 0.5, 1.0,
                1.0, "completed", f"evidence:default:{len(calls)}",
            ))

        run_simple_scheduler(
            enabled=True, initial_state=initial, actions=actions, evaluator=evaluator,
            metric="recovery_error", direction=-1, seed=1, total_budget=20.0,
            max_expansions=2, max_depth=3, explore_share=0.0,
            prior_observations=(prior,), action_available=lambda state, action: (
                evaluation._action_available(state, action)
                and not action.action_id.startswith("diagnose-")
            ),
        )
        return calls

    assert execute(0.0) == execute(2.0) == ["fit-single", "refine-single"]


def test_active_branch_family_uses_latest_fit_or_refine_action() -> None:
    task = evaluation.locked_task_specs()[0]
    state = ResearchState(
        task.target_context, "hypothesis:test", ("prediction:test",), ("rival:test",),
        completed_action_ids=("fit-single", "fit-two-scale"), depth=2,
    )
    actions = {action.action_id: action for action in evaluation.registered_actions()}

    assert evaluation._action_available(state, actions["refine-two-scale"])
    assert not evaluation._action_available(state, actions["refine-single"])


def test_parent_artifact_requires_exact_path() -> None:
    artifact = evaluation.ExperimentArtifact(
        ResponseProgram((KernelTerm(1.0, 0.5),)), 0.2, 1, 0.8,
    )
    rows = {("fit-single",): artifact}

    assert evaluation._parent_artifact(("fit-single",), rows) is artifact
    with pytest.raises(ValueError):
        evaluation._parent_artifact(("fit-single", "refine-single"), rows)


def test_endpoint_ranks_common_absolute_quality_not_local_increment() -> None:
    trace = (
        ExpansionRecord(0, "n000", "n001", "fit-single", "exploit", 1, 1,
                        "completed", "development", 1.0, 0.9, "evidence:a", ("fit-single",)),
        ExpansionRecord(1, "n000", "n002", "fit-two-scale", "exploit", 1, 2,
                        "completed", "development", 1.0, 0.1, "evidence:b", ("fit-two-scale",)),
    )
    result = PlanningResult(
        "mcts", True, 1, 2.0, 2.0, 0.0, 2.0, 2, "fit-single", "fit-single",
        "completed", trace, (),
    )
    first = evaluation.ExperimentArtifact(
        ResponseProgram((KernelTerm(1.0, 0.5),)), 0.8, 1, 0.2,
    )
    second = evaluation.ExperimentArtifact(
        ResponseProgram((KernelTerm(0.5, 0.2),)), 0.2, 1, 0.8,
    )

    action_id, quality, program = evaluation._endpoint(
        result, {("fit-single",): first, ("fit-two-scale",): second},
    )
    assert action_id == "fit-two-scale"
    assert quality == pytest.approx(0.8)
    assert program == second.program


def test_experiment_seed_is_independent_of_planner_seed() -> None:
    task = evaluation.locked_task_specs()[0]
    fit, _ = evaluation._data(task, phase="target-development")
    action = next(a for a in evaluation.registered_actions() if a.action_id == "fit-single")

    _, first = evaluation._execute_action(
        task=task, context=task.target_context, fit=fit, branch_actions=(),
        action=action, phase="target-development", evaluator_seed=1, artifacts={},
    )
    _, second = evaluation._execute_action(
        task=task, context=task.target_context, fit=fit, branch_actions=(),
        action=action, phase="target-development", evaluator_seed=999, artifacts={},
    )

    assert first == second


def test_target_callback_failure_preserves_row_and_unknown_cost(monkeypatch) -> None:
    original = evaluation._execute_action
    calls = 0

    def interrupted(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:  # three common-history calls, one target success, then interruption
            raise RuntimeError("synthetic target interruption")
        return original(**kwargs)

    monkeypatch.setattr(evaluation, "_execute_action", interrupted)
    task = evaluation.locked_task_specs()[0]
    row = evaluation._run_one(
        task, "mcts", "C0", evaluation.protocol_manifest()["protocol_hash"], False
    )

    assert row.run_complete is False
    assert row.cost_complete is False
    assert row.failure_kind == "evaluator_exception"
    assert row.total_observed_cost is None
    assert row.known_cost_lower_bound > row.shared_history_cost
    assert row.failed_attempts == 1


def test_source_unknown_cost_is_not_coerced_to_zero(monkeypatch) -> None:
    original = evaluation._execute_action
    calls = 0

    def unknown_source_cost(**kwargs):
        nonlocal calls
        calls += 1
        result, artifact = original(**kwargs)
        if calls == 1:
            result = replace(
                result,
                observation=replace(result.observation, actual_cost=None),
            )
        return result, artifact

    monkeypatch.setattr(evaluation, "_execute_action", unknown_source_cost)
    task = evaluation.locked_task_specs()[0]
    row = evaluation._run_one(
        task, "mcts", "C1", evaluation.protocol_manifest()["protocol_hash"], False
    )

    assert row.run_complete is False
    assert row.cost_complete is False
    assert row.failure_kind == "source_history_failure"
    assert row.shared_history_cost == 0.0
    assert row.total_observed_cost is None
    assert row.known_cost_lower_bound == 0.0
    assert row.evaluator_calls == 1
    assert row.candidate_evaluations > 0


@pytest.mark.parametrize("bad_cost", [None, 50.0])
def test_target_cost_violation_consumes_partial_result_without_losing_row(
    monkeypatch,
    bad_cost,
) -> None:
    original = evaluation._execute_action
    calls = 0

    def invalid_cost(**kwargs):
        nonlocal calls
        calls += 1
        result, artifact = original(**kwargs)
        if calls == 5:
            result = replace(
                result,
                observation=replace(result.observation, actual_cost=bad_cost),
            )
        return result, artifact

    monkeypatch.setattr(evaluation, "_execute_action", invalid_cost)
    task = evaluation.locked_task_specs()[0]
    row = evaluation._run_one(
        task, "mcts", "C0", evaluation.protocol_manifest()["protocol_hash"], False
    )

    assert row.run_complete is False
    assert row.failure_kind == "evaluator_contract_violation"
    assert row.failed_attempts == 1
    if bad_cost is None:
        assert row.cost_complete is False and row.total_observed_cost is None
        assert row.known_cost_lower_bound > row.shared_history_cost
    else:
        assert row.cost_complete is True
        assert row.total_observed_cost == row.known_cost_lower_bound
        assert row.total_observed_cost > row.shared_history_cost + evaluation.TARGET_BUDGET


def test_summaries_report_incomplete_and_do_not_decide_before_final() -> None:
    report = evaluation.run_locked_evaluation(include_final=False)

    assert {row["comparison"] for row in report.summaries} == {
        "algorithm:mcts-simple", "transfer:mcts", "transfer:simple_scheduler",
    }
    assert all(row["complete_pairs"] == 9 for row in report.summaries)
    assert all(row["incomplete_pairs"] == 0 for row in report.summaries)
    assert all(row["decision"] == "not_evaluated_final" for row in report.summaries)
