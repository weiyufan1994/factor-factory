"""Independent W08 review cases; no frozen task or final oracle evaluation."""

from __future__ import annotations

from dataclasses import replace
from math import exp

import pytest

from factor_factory.hybrid_research import evaluation_v2 as evaluation
from factor_factory.hybrid_research.decision import Context, Observation
from factor_factory.hybrid_research.gp_adapter import KernelTerm, ResponseProgram
from factor_factory.hybrid_research.mcts import (
    ActionResult,
    ExpansionRecord,
    ResearchState,
    run_simple_scheduler,
)
from factor_factory.hybrid_research.synthetic import FitData


def artifact(scale: float) -> evaluation.ExperimentArtifact:
    return evaluation.ExperimentArtifact(
        ResponseProgram((KernelTerm(scale, 0.5),)), 0.0, 1
    )


@pytest.fixture(autouse=True)
def forbid_hidden_or_frozen_data(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("independent review must not access frozen data or final oracle")

    monkeypatch.setattr(evaluation, "_data", forbidden)
    monkeypatch.setattr(evaluation, "_oracle_quality", forbidden)


def test_root_lookup_does_not_take_a_later_child_artifact():
    root, child = artifact(1.0), artifact(0.8)
    rows = {
        ("fit-single",): root,
        ("fit-single", "refine-single"): child,
    }

    assert evaluation._parent_artifact(("fit-single",), rows) is root


def test_child_lookup_does_not_take_an_unrelated_sibling_artifact():
    root, child, sibling = artifact(1.0), artifact(0.8), artifact(1.2)
    rows = {
        ("fit-single",): root,
        ("fit-single", "refine-single"): child,
        ("fit-single", "diagnose-single"): sibling,
    }

    assert evaluation._parent_artifact(("fit-single", "refine-single"), rows) is child


def test_parent_identity_is_not_a_substring_match():
    rows = {("not-fit-single",): artifact(1.0)}

    with pytest.raises(ValueError):
        evaluation._parent_artifact(("fit-single",), rows)


def test_missing_exact_parent_does_not_silently_revert_to_an_ancestor():
    rows = {("fit-single",): artifact(1.0)}

    with pytest.raises(ValueError):
        evaluation._parent_artifact(("fit-single", "refine-single"), rows)


@pytest.mark.parametrize("preferred_family", (None, "single", "two-scale", "permanent"))
def test_simple_has_a_real_choice_after_current_evidence(preferred_family):
    context = Context.from_mapping(
        stage="development",
        objective="independent feedback sensitivity check",
        conditions={"fixture": "not-a-frozen-task"},
        evaluation_protocol="independent-w08-feedback",
    )
    actions = evaluation.registered_actions()
    priors = tuple(
        Observation(
            f"independent:prior:{a.action_id}", a.action_id, context,
            "development", context.evaluation_protocol, "review_gain", 1,
            0.0, 0.9 if a.family == preferred_family else 0.2,
            1.0, a.estimated_cost, "completed", f"review:prior:{a.action_id}",
        )
        for a in actions if a.action_id.startswith("fit-")
    ) if preferred_family is not None else ()

    def execute(gain):
        calls = []

        def callback(state, action, seed):
            calls.append(action.action_id)
            return ActionResult(Observation(
                f"independent:current:{len(calls)}", action.action_id, context,
                "development", context.evaluation_protocol, "review_gain", 1,
                0.0, gain, 1.0, action.estimated_cost, "completed",
                f"review:current:{len(calls)}",
            ))

        result = run_simple_scheduler(
            enabled=True,
            initial_state=ResearchState(context, "hypothesis:review", ("prediction:review",), ("rival:review",)),
            actions=actions,
            evaluator=callback,
            metric="review_gain",
            direction=1,
            seed=1,
            total_budget=4 * max(a.estimated_cost for a in actions),
            max_expansions=4,
            max_depth=3,
            explore_share=0.5,
            stop_action_ids=("stop",),
            prior_observations=priors,
            action_available=evaluation._action_available,
            avoid_nonpositive_families=True,
            feedback_family=evaluation._feedback_family,
        )
        return tuple(row.action_id for row in result.trace)

    negative = execute(-0.8)
    positive = execute(0.8)

    assert negative != positive, (
        "Current evidence cannot affect the actual simple-scheduler action sequence: "
        f"prior={preferred_family}, both={positive}"
    )


def test_zero_residual_diagnostic_does_not_relearn_existing_perfect_fit():
    context = Context.from_mapping(
        stage="development", objective="independent diagnostic review",
        conditions={}, evaluation_protocol="independent-diagnostic-v1",
    )
    state = ResearchState(
        context, "hypothesis:review", ("prediction:review",), ("rival:review",),
        completed_action_ids=("fit-single",), depth=1,
    )
    diagnostic = next(
        (a for a in evaluation.registered_actions() if a.action_id == "diagnose-single"),
        None,
    )
    if diagnostic is None or not evaluation._action_available(state, diagnostic):
        # Excluding a non-informative diagnostic from utility search is valid.
        return
    task = evaluation.TaskSpec(
        "independent-not-frozen", "matching", 991,
        "single_fast", "single_fast", context, context,
    )
    fit = FitData(
        (1.0,) + (0.0,) * 11,
        tuple(exp(-0.5 * i) for i in range(12)),
        1.0,
    )
    parent = artifact(1.0)
    result, computed = evaluation._execute_action(
        task=task, context=context, fit=fit,
        branch_actions=("fit-single",), action=diagnostic,
        phase="target-development", evaluator_seed=7,
        artifacts={("fit-single",): parent},
    )

    assert computed.program == parent.program
    assert computed.diagnostic_value == pytest.approx(0.0)
    assert result.observation.learning_increment() in (None, 0.0)


def test_latest_fitted_model_controls_the_available_refinement_family():
    context = Context.from_mapping(
        stage="development", objective="active-model identity", conditions={},
        evaluation_protocol="independent-active-model",
    )
    state = ResearchState(
        context, "hypothesis:review", ("prediction:review",), ("rival:review",),
        completed_action_ids=("fit-single", "fit-two-scale"), depth=2,
    )
    actions = {a.action_id: a for a in evaluation.registered_actions()}

    assert not evaluation._action_available(state, actions["refine-single"])
    assert evaluation._action_available(state, actions["refine-two-scale"])


def test_endpoint_uses_common_absolute_quality_not_mixed_local_rewards():
    context = Context.from_mapping(
        stage="development", objective="endpoint identity", conditions={},
        evaluation_protocol="independent-endpoint",
    )
    state = ResearchState(context, "h", ("p",), ("r",))
    rows = (
        ExpansionRecord(
            0, "n0", "n1", "fit-single", "exploit", 1, 1,
            "completed", "development", 1.0, 0.9, "review:root", ("fit-single",),
        ),
        ExpansionRecord(
            1, "n1", "n2", "refine-single", "exploit", 2, 2,
            "completed", "development", 1.0, 0.5, "review:refined",
            ("fit-single", "refine-single"),
        ),
    )
    result = replace(evaluation._empty_result("mcts", state), trace=rows)
    root = replace(artifact(1.0), development_loss=0.1, development_quality=0.9)
    refined = replace(artifact(0.8), development_loss=0.05, development_quality=0.95)
    selected, quality, program = evaluation._endpoint(
        result,
        {("fit-single",): root, ("fit-single", "refine-single"): refined},
    )

    assert selected == "refine-single"
    assert quality == pytest.approx(0.95)
    assert program == refined.program


def test_same_experiment_solver_seed_does_not_depend_on_planner_rng(monkeypatch):
    context = Context.from_mapping(
        stage="development", objective="paired experiment randomness", conditions={},
        evaluation_protocol="independent-solver-pairing",
    )
    task = evaluation.TaskSpec(
        "independent-not-frozen", "matching", 991,
        "single_fast", "single_fast", context, context,
    )
    fit = FitData((1.0,) + (0.0,) * 11, tuple(exp(-0.5 * i) for i in range(12)), 1.0)
    action = next(a for a in evaluation.registered_actions() if a.action_id == "fit-single")
    original = evaluation.run_response_gp
    solver_seeds = []

    def record_seed(**kwargs):
        solver_seeds.append(kwargs["seed"])
        return original(**kwargs)

    monkeypatch.setattr(evaluation, "run_response_gp", record_seed)
    for planner_seed in (1, 999):
        evaluation._execute_action(
            task=task, context=context, fit=fit, branch_actions=(), action=action,
            phase="target-development", evaluator_seed=planner_seed, artifacts={},
        )

    assert len(solver_seeds) == 2
    assert solver_seeds[0] == solver_seeds[1]


def test_successful_diagnostic_is_not_reported_as_a_failed_experiment(monkeypatch):
    context = Context.from_mapping(
        stage="development", objective="diagnostic accounting", conditions={},
        evaluation_protocol="independent-diagnostic-accounting",
    )
    task = evaluation.TaskSpec(
        "independent-not-frozen", "matching", 991,
        "single_fast", "single_fast", context, context,
    )
    fit = FitData((1.0,) + (0.0,) * 11, tuple(exp(-0.5 * i) for i in range(12)), 1.0)
    diagnostics = []
    original = evaluation._execute_action

    def data(_task, *, phase):
        assert phase in {"source-development", "target-development"}
        return fit, None

    def record_action(**kwargs):
        result, computed = original(**kwargs)
        if kwargs["action"].action_id.startswith("diagnose-"):
            diagnostics.append(result.observation.status)
        return result, computed

    monkeypatch.setattr(evaluation, "_data", data)
    monkeypatch.setattr(evaluation, "_execute_action", record_action)
    result = evaluation._run_one(task, "simple_scheduler", "C0", "independent", False)

    assert diagnostics == ["diagnostic_completed"]
    assert result.run_complete
    assert result.failure_kind is None
    assert result.failed_attempts == 0
