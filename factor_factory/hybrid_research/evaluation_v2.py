"""W08 v2: source-bound mechanism experiments with held-out oracle scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from time import perf_counter
from typing import Literal

from .decision import Action, Context, Observation
from .gp_adapter import ResponseProgram, evaluate_program, run_response_gp
from .mcts import (
    ActionResult,
    PlannerContractError,
    PlanningResult,
    ResearchState,
    run_action_mcts,
    run_simple_scheduler,
)
from .synthetic import FitData, HiddenSyntheticTruth, hidden_recovery_mse, make_response_scenario
from .variation import DerivationScope


PROTOCOL_VERSION = "hybrid-w08-mechanism-v2"
TASK_FAMILIES = ("matching", "condition_change", "misleading_prior")
NUMERIC_SEEDS = (11, 29, 47)
TARGET_BUDGET = 32.0
MAX_EXPANSIONS = 4
MAX_DEPTH = 3
EXPLORE_SHARE = 0.5
SUCCESSFUL_TRACE_STATUSES = {
    "completed",
    "diagnostic_completed",
    "stopped",
    "duplicate_observation_not_relearned",
}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    family: str
    numeric_seed: int
    source_scenario: str
    target_scenario: str
    source_context: Context
    target_context: Context


@dataclass(frozen=True)
class ExperimentArtifact:
    program: ResponseProgram
    development_loss: float
    candidate_evaluations: int
    development_quality: float = 0.0
    diagnostic_value: float | None = None


@dataclass(frozen=True)
class EvaluationRecord:
    task_id: str
    family: str
    numeric_seed: int
    algorithm: Literal["mcts", "simple_scheduler"]
    arm: Literal["C0", "C1"]
    protocol_hash: str
    development_only: bool
    endpoint_action_id: str | None
    development_quality: float
    final_quality: float | None
    target_spent_cost: float
    shared_history_cost: float
    experience_consumption_cost: float
    total_observed_cost: float | None
    known_cost_lower_bound: float
    cost_complete: bool
    run_complete: bool
    failure_kind: str | None
    unused_target_budget: float
    evaluator_calls: int
    candidate_evaluations: int
    failed_attempts: int
    stopped: bool
    max_tree_depth: int
    best_root_action_id: str | None
    first_deeper_parent_action_id: str | None
    first_deeper_parent_increment: float | None
    best_root_increment: float | None
    first_deeper_parent_utility: float | None
    best_root_utility: float | None
    planner_selected_action_id: str | None
    first_executed_action_id: str | None
    elapsed_seconds: float


@dataclass(frozen=True)
class ComparisonReport:
    protocol: dict[str, object]
    records: tuple[EvaluationRecord, ...]
    algorithm_pairs: tuple[dict[str, object], ...]
    transfer_pairs: tuple[dict[str, object], ...]
    summaries: tuple[dict[str, object], ...]
    llm_auxiliary_status: str
    token_usage: str
    api_cost: str


def registered_actions() -> tuple[Action, ...]:
    ref = "docs/design/self-improvement-d04/02_construction.zh-CN.md#4-w04-响应研究切片"
    return (
        Action("fit-single", "single", "exploit", 8.0, "fit the declared single-kernel family", (ref,)),
        Action("fit-two-scale", "two-scale", "exploit", 12.0, "fit the declared two-scale rival", (ref,)),
        Action("fit-permanent", "permanent", "exploit", 12.0, "fit the declared permanent-plus-transient rival", (ref,)),
        Action("refine-single", "single", "exploit", 3.0, "locally refit the single-kernel branch", (ref,)),
        Action("refine-two-scale", "two-scale", "explore", 3.0, "locally refit the two-scale branch", (ref,)),
        Action("diagnose-single", "diagnostic", "explore", 1.0, "measure held-development residual dependence", (ref,)),
        Action("diagnose-two-scale", "diagnostic", "explore", 1.0, "measure held-development residual dependence", (ref,)),
        Action("refine-permanent", "permanent", "explore", 3.0, "locally refit the permanent-response branch", (ref,)),
        Action("diagnose-permanent", "diagnostic", "explore", 1.0, "measure held-development residual dependence", (ref,)),
        Action("stop", "stop", "exploit", 0.0, "stop without positive development evidence", (ref,)),
    )


def locked_task_specs() -> tuple[TaskSpec, ...]:
    scenarios = {
        "matching": ("two_scale", "two_scale", "shared", "shared"),
        "condition_change": ("single_slow", "two_scale", "source", "target"),
        "misleading_prior": ("permanent_plus_transient", "two_scale", "shared", "shared"),
    }
    rows = []
    for family in TASK_FAMILIES:
        source_scenario, target_scenario, source_regime, target_regime = scenarios[family]
        for seed in NUMERIC_SEEDS:
            rows.append(TaskSpec(
                f"{family}-seed-{seed}", family, seed, source_scenario, target_scenario,
                _context(family, source_regime), _context(family, target_regime),
            ))
    return tuple(rows)


def protocol_manifest() -> dict[str, object]:
    manifest: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "task_families": list(TASK_FAMILIES),
        "numeric_seeds": list(NUMERIC_SEEDS),
        "task_count": 9,
        "source_target_scenarios": {
            "matching": ["two_scale", "two_scale"],
            "condition_change": ["single_slow", "two_scale"],
            "misleading_prior": ["permanent_plus_transient", "two_scale"],
        },
        "actions": [row.action_id for row in registered_actions()],
        "actual_experiments": "GP fit, local response refit, residual dependence diagnostic",
        "target_budget": TARGET_BUDGET,
        "max_expansions": MAX_EXPANSIONS,
        "max_depth": MAX_DEPTH,
        "root_actions": ["fit-single", "fit-two-scale", "fit-permanent"],
        "root_progressive_width": 2,
        "branch_actions": ["refine matching branch", "diagnose matching branch", "stop"],
        "paired_environment": "scenario+seed+phase identity; experiment GP seed binds task+phase+action+parent path and ignores planner call order",
        "common_history": "C0 and C1 both incur the same three source experiments; only C1 consumes them",
        "cost_unit": "actual finite candidate evaluations with per-action reservation caps",
        "diagnostic_policy": "real residual diagnostic retained as non-learning material",
        "endpoint": "best positive absolute target-development program quality against common zero baseline; STOP=0",
        "final": "independent synthetic truth used only after planning; never returned to planner",
        "decision_rule": "same predeclared 6/9 and family-floor rules as v1",
        "v1_status": "toy scheduler fixture only; forbidden as W08 effect evidence",
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["protocol_hash"] = sha256(payload).hexdigest()
    return manifest


def run_locked_evaluation(*, include_final: bool = False) -> ComparisonReport:
    protocol = protocol_manifest()
    records = []
    for task in locked_task_specs():
        for algorithm in ("mcts", "simple_scheduler"):
            for arm in ("C0", "C1"):
                records.append(_run_one(task, algorithm, arm, str(protocol["protocol_hash"]), include_final))
    algorithm_pairs = _pairs(records, comparison="algorithm", include_final=include_final)
    transfer_pairs = _pairs(records, comparison="transfer", include_final=include_final)
    return ComparisonReport(
        protocol,
        tuple(records),
        algorithm_pairs,
        transfer_pairs,
        _summaries(algorithm_pairs, transfer_pairs, include_final=include_final),
        "not_executed_real_researcher_required",
        "Unknown",
        "Unknown",
    )


def report_as_dict(report: ComparisonReport) -> dict[str, object]:
    return asdict(report)


def _run_one(
    task: TaskSpec,
    algorithm: str,
    arm: str,
    protocol_hash: str,
    include_final: bool,
) -> EvaluationRecord:
    started = perf_counter()
    actions = registered_actions()
    candidate_evaluations = 0
    evaluator_calls = 0
    artifacts: dict[tuple[str, ...], ExperimentArtifact] = {}
    source_observations: list[Observation] = []
    source_cost = 0.0
    source_cost_complete = True
    source_failure: str | None = None
    source_fit, _ = _data(task, phase="source-development")
    for action_id in ("fit-single", "fit-two-scale", "fit-permanent"):
        action = next(row for row in actions if row.action_id == action_id)
        try:
            evaluator_calls += 1
            result, artifact = _execute_action(
                task=task, context=task.source_context, fit=source_fit,
                branch_actions=(), action=action, phase="source-development",
                evaluator_seed=_stable_seed(task, phase=f"source:{action_id}"), artifacts=artifacts,
            )
            candidate_evaluations += artifact.candidate_evaluations
            cost = result.observation.actual_cost
            if cost is None or not isfinite(cost) or cost < 0:
                raise ValueError("source observation cost is unknown or invalid")
            if cost > action.estimated_cost:
                source_cost += cost
                raise ValueError("source observation cost exceeds reservation")
            source_observations.append(result.observation)
            artifacts[(action.action_id,)] = artifact
            source_cost += cost
        except Exception as exc:
            source_failure = f"{type(exc).__name__}: {exc}"
            source_cost_complete = False
            break

    target_fit, _ = _data(task, phase="target-development")
    target_artifacts: dict[tuple[str, ...], ExperimentArtifact] = {}

    def evaluator(branch: ResearchState, action: Action, evaluator_seed: int) -> ActionResult:
        nonlocal evaluator_calls, candidate_evaluations
        evaluator_calls += 1
        result, artifact = _execute_action(
            task=task, context=branch.context, fit=target_fit,
            branch_actions=branch.completed_action_ids, action=action,
            phase="target-development", evaluator_seed=evaluator_seed,
            artifacts=target_artifacts,
        )
        target_artifacts[branch.completed_action_ids + (action.action_id,)] = artifact
        candidate_evaluations += artifact.candidate_evaluations
        return result

    initial = ResearchState(
        task.target_context,
        f"hypothesis:{task.family}:causal-response",
        (f"prediction:{task.family}:out-of-sample-response",),
        (f"rival:{task.family}:single-vs-two-scale",),
    )
    planner = run_action_mcts if algorithm == "mcts" else run_simple_scheduler
    partial_error: PlannerContractError | None = None
    if source_failure is None:
        try:
            planner_kwargs = dict(
                enabled=True,
                initial_state=initial,
                actions=actions,
                evaluator=evaluator,
                metric="recovery_error",
                direction=-1,
                seed=_stable_seed(task, phase=f"planner:{algorithm}"),
                total_budget=TARGET_BUDGET,
                max_expansions=MAX_EXPANSIONS,
                max_depth=MAX_DEPTH,
                exploration_weight=0.7,
                explore_share=EXPLORE_SHARE,
                stop_action_ids=("stop",),
                prior_observations=tuple(source_observations) if arm == "C1" else (),
                action_available=_action_available,
                max_children_per_node=2 if algorithm == "mcts" else None,
            )
            if algorithm == "simple_scheduler":
                planner_kwargs.update(
                    avoid_nonpositive_families=True,
                    feedback_family=_feedback_family,
                )
            result = planner(**planner_kwargs)
        except PlannerContractError as exc:
            partial_error = exc
            result = exc.partial_result
    else:
        result = _empty_result(algorithm, initial)

    endpoint_id, dev_quality, endpoint_program = _endpoint(result, target_artifacts)
    final_quality = None
    if include_final and endpoint_program is not None:
        final_fit, final_truth = _data(task, phase="target-final")
        final_quality = _oracle_quality(endpoint_program, final_fit, final_truth)
    elif include_final:
        final_quality = 0.0

    failure_kind = source_failure and "source_history_failure"
    if result.failure is not None:
        failure_kind = result.failure.kind
    if partial_error is not None and result.failure is not None:
        failure_kind = result.failure.kind
    target_cost_complete = not (
        result.failure is not None and result.failure.known_actual_cost is None
    )
    cost_complete = source_cost_complete and target_cost_complete
    known_lower = source_cost + result.spent_cost
    total_cost = known_lower if cost_complete else None
    run_complete = source_failure is None and result.failure is None and partial_error is None
    failed_attempts = sum(
        row.status not in SUCCESSFUL_TRACE_STATUSES
        for row in result.trace
    )
    max_depth = max((row.depth for row in result.trace), default=initial.depth)
    root_rows = [
        row for row in result.trace
        if row.depth == 1 and row.learning_increment is not None
    ]
    root_utilities = {
        row.action_id: row.learning_increment / row.actual_cost
        for row in root_rows
        if row.actual_cost is not None and row.actual_cost > 0
    }
    best_root_action = (
        max(root_utilities, key=lambda action_id: (root_utilities[action_id], action_id))
        if root_utilities else None
    )
    first_deeper_parent = next(
        (row.path_action_ids[0] for row in result.trace if row.depth >= 2),
        None,
    )
    root_increments = {row.action_id: row.learning_increment for row in root_rows}
    return EvaluationRecord(
        task.task_id, task.family, task.numeric_seed,
        algorithm, arm, protocol_hash, not include_final,
        endpoint_id, dev_quality, final_quality,
        result.spent_cost, source_cost, 0.0,
        total_cost, known_lower, cost_complete, run_complete, failure_kind,
        max(0.0, TARGET_BUDGET - result.spent_cost), evaluator_calls,
        candidate_evaluations, failed_attempts, endpoint_id is None, max_depth,
        best_root_action, first_deeper_parent,
        root_increments.get(first_deeper_parent),
        max(root_increments.values()) if root_increments else None,
        root_utilities.get(first_deeper_parent),
        max(root_utilities.values()) if root_utilities else None,
        result.selected_action_id, result.first_executed_action_id,
        perf_counter() - started,
    )


def _execute_action(
    *,
    task: TaskSpec,
    context: Context,
    fit: FitData,
    branch_actions: tuple[str, ...],
    action: Action,
    phase: str,
    evaluator_seed: int,
    artifacts: dict[tuple[str, ...], ExperimentArtifact],
) -> tuple[ActionResult, ExperimentArtifact]:
    run_id = f"{PROTOCOL_VERSION}:{task.task_id}:{phase}:{'/'.join(branch_actions)}:{action.action_id}"
    evaluator_seed = _stable_seed(
        task,
        phase=f"experiment:{phase}:{'/'.join(branch_actions)}:{action.action_id}",
    )
    train, validation_indexes = _train_and_validation(fit)
    parent = None
    if branch_actions:
        parent = _parent_artifact(branch_actions, artifacts)
    if action.action_id in {"fit-single", "fit-two-scale", "fit-permanent"}:
        broad = action.action_id != "fit-single"
        allowed_rates = (
            (0.0, 0.2, 0.5) if action.action_id == "fit-permanent"
            else (0.0, 0.2, 0.5, 1.0) if broad
            else (0.2, 0.5, 1.0)
        )
        search = run_response_gp(
            scope=_scope(broad=broad), fit_data=train,
            allowed_rates=allowed_rates,
            allowed_scales=(0.3, 0.7, 1.0), seed=evaluator_seed,
            generations=1, population_size=6,
            max_evaluations=12 if broad else 8, max_attempts=24 if broad else 16,
        )
        if search.selected is None or search.selected.program is None:
            raise ValueError("GP search produced no finite program")
        program = search.selected.program
        candidate_count = search.evaluated_count
        diagnostic = None
    else:
        if parent is None:
            raise ValueError("branch action requires a fitted parent")
        program = parent.program
        candidate_count = 1
        diagnostic = None
        if action.action_id.startswith("refine-"):
            program, candidate_count = _local_refit(parent.program, train)
        elif action.action_id.startswith("diagnose-"):
            prediction = evaluate_program(program, fit)
            residuals = tuple(
                fit.observed_response[i] - prediction[i] for i in validation_indexes
            )
            diagnostic = _lag_one_dependence(residuals)
        else:
            raise ValueError(f"unsupported experiment action: {action.action_id}")
    prediction = evaluate_program(program, fit)
    loss = _mse(fit.observed_response, prediction, validation_indexes)
    zero_baseline = _mse(
        fit.observed_response,
        tuple(0.0 for _ in fit.observed_response),
        validation_indexes,
    )
    baseline = (
        parent.development_loss
        if parent is not None and not action.action_id.startswith("fit-")
        else zero_baseline
    )
    observation = Observation(
        run_id, action.action_id, context, "development", context.evaluation_protocol,
        "recovery_error", -1, baseline, loss, max(baseline, 1e-12),
        float(candidate_count),
        "diagnostic_completed" if action.action_id.startswith("diagnose-") else "completed",
        f"numeric:{run_id}",
    )
    absolute_quality = max(0.0, min(1.0, 1.0 - loss / max(zero_baseline, 1e-12)))
    artifact = ExperimentArtifact(
        program, loss, candidate_count, absolute_quality, diagnostic
    )
    return ActionResult(
        observation,
        added_prediction_refs=(
            f"numeric-loss:{loss:.12g}",
            f"residual-dependence:{diagnostic:.12g}" if diagnostic is not None else "model-fit",
        ),
        experiment_ref=observation.evidence_ref,
    ), artifact


def _action_available(state: ResearchState, action: Action) -> bool:
    path = state.completed_action_ids
    root_models = {"fit-single", "fit-two-scale", "fit-permanent"}
    if not path:
        return action.action_id in root_models
    if action.action_id in root_models:
        return True
    active = next(
        (
            item for item in reversed(path)
            if item.startswith("fit-") or item.startswith("refine-")
        ),
        "",
    )
    if active.endswith("single"):
        return action.action_id in {"refine-single", "diagnose-single", "stop"}
    if active.endswith("two-scale"):
        return action.action_id in {"refine-two-scale", "diagnose-two-scale", "stop"}
    if active.endswith("permanent"):
        return action.action_id in {"refine-permanent", "diagnose-permanent", "stop"}
    return action.action_id == "stop"


def _feedback_family(action: Action) -> str:
    mapping = {
        "refine-single": "single", "diagnose-single": "single",
        "refine-two-scale": "two-scale", "diagnose-two-scale": "two-scale",
        "refine-permanent": "permanent", "diagnose-permanent": "permanent",
    }
    return mapping.get(action.action_id, action.family)


def _endpoint(
    result: PlanningResult,
    artifacts: dict[tuple[str, ...], ExperimentArtifact],
) -> tuple[str | None, float, ResponseProgram | None]:
    candidates = [
        (row, artifacts.get(row.path_action_ids))
        for row in result.trace
        if row.status == "completed"
    ]
    candidates = [(row, artifact) for row, artifact in candidates if artifact is not None]
    if not candidates:
        return None, 0.0, None
    best, artifact = max(
        candidates,
        key=lambda item: (item[1].development_quality, item[0].action_id),
    )
    if artifact.development_quality <= 0:
        return None, 0.0, None
    return best.action_id, artifact.development_quality, artifact.program


def _source_prior_artifact_key(action_id: str) -> str:
    return action_id


def _parent_artifact(
    path: tuple[str, ...],
    artifacts: dict[tuple[str, ...], ExperimentArtifact],
) -> ExperimentArtifact:
    artifact = artifacts.get(path)
    if artifact is not None:
        return artifact
    raise ValueError("branch has no prior fitted response artifact")


def _local_refit(program: ResponseProgram, train: FitData) -> tuple[ResponseProgram, int]:
    candidates = [program]
    for factor in (0.8, 1.2):
        candidates.append(ResponseProgram(tuple(
            type(term)(term.scale * factor, term.decay_rate) for term in program.terms
        )))
    ranked = [(_mse(train.observed_response, evaluate_program(row, train), range(len(train.observed_response))), row) for row in candidates]
    return min(ranked, key=lambda item: item[0])[1], len(candidates)


def _train_and_validation(fit: FitData) -> tuple[FitData, tuple[int, ...]]:
    cut = max(8, len(fit.signed_impulses) * 2 // 3)
    train = FitData(fit.signed_impulses[:cut], fit.observed_response[:cut], fit.step)
    return train, tuple(range(cut, len(fit.signed_impulses)))


def _mse(actual, predicted, indexes) -> float:
    indexes = tuple(indexes)
    return sum((actual[i] - predicted[i]) ** 2 for i in indexes) / len(indexes)


def _lag_one_dependence(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    return sum(values[i] * values[i - 1] for i in range(1, len(values))) / (len(values) - 1)


def _oracle_quality(
    program: ResponseProgram,
    fit: FitData,
    truth: HiddenSyntheticTruth,
) -> float:
    prediction = evaluate_program(program, fit)
    loss = hidden_recovery_mse(prediction, truth)
    baseline = sum(value * value for value in truth.noiseless_response) / len(truth.noiseless_response)
    return max(0.0, min(1.0, 1.0 - loss / max(baseline, 1e-12)))


def _data(task: TaskSpec, *, phase: str) -> tuple[FitData, HiddenSyntheticTruth]:
    source = phase == "source-development"
    scenario = task.source_scenario if source else task.target_scenario
    phase_offset = {"source-development": 1000, "target-development": 2000, "target-final": 3000}[phase]
    return make_response_scenario(
        scenario=scenario,
        seed=task.numeric_seed + phase_offset,
        length=24,
        noise_scale=0.03 if phase != "target-final" else 0.0,
    )


def _scope(*, broad: bool):
    return DerivationScope(
        "docs/design/self-improvement-d04/02_construction.zh-CN.md#4-w04-响应研究切片",
        "causal kernels", "finite signed impulses", "zero", "event",
        "missing is not zero", "signed J to y",
        ("causal convolution", "linear superposition") if broad else ("causal convolution",),
        ("temporary response decays", "two scales leave structured residuals"),
        "single versus two-scale response remains to be distinguished",
        ("transient_exponential_kernel", "permanent_component", "two_scale_superposition") if broad else ("transient_exponential_kernel",),
        ("parameter_search", "structure_search") if broad else ("parameter_search",),
    )


def _context(family: str, regime: str) -> Context:
    return Context.from_mapping(
        stage="development", objective="causal response recovery",
        conditions={"task_family": family, "visible_regime": regime},
        evaluation_protocol=f"{PROTOCOL_VERSION}:{family}:{regime}",
    )


def _stable_seed(task: TaskSpec, *, phase: str) -> int:
    payload = f"{PROTOCOL_VERSION}|{task.task_id}|{phase}".encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big")


def _empty_result(algorithm: str, initial: ResearchState) -> PlanningResult:
    return PlanningResult(
        algorithm=algorithm, enabled=True, seed=0, total_budget=TARGET_BUDGET,
        spent_cost=0.0, prior_incurred_cost=initial.incurred_cost,
        cumulative_known_cost=initial.incurred_cost, expansion_count=0,
        selected_action_id=None, first_executed_action_id=None,
        stop_reason="source_history_failure", trace=(), nodes=(),
    )


def _pairs(records, *, comparison: str, include_final: bool):
    rows = []
    if comparison == "algorithm":
        for task in locked_task_specs():
            pair = {r.algorithm: r for r in records if r.task_id == task.task_id and r.arm == "C0"}
            rows.append(_pair_row(task, "mcts-simple", pair["mcts"], pair["simple_scheduler"], include_final))
    else:
        for task in locked_task_specs():
            for algorithm in ("mcts", "simple_scheduler"):
                pair = {r.arm: r for r in records if r.task_id == task.task_id and r.algorithm == algorithm}
                rows.append(_pair_row(task, f"C1-C0:{algorithm}", pair["C1"], pair["C0"], include_final))
    return tuple(rows)


def _pair_row(task, label, left, right, include_final):
    left_quality = left.final_quality if include_final else left.development_quality
    right_quality = right.final_quality if include_final else right.development_quality
    complete = left.run_complete and right.run_complete and left.cost_complete and right.cost_complete
    return {
        "task_id": task.task_id, "family": task.family, "comparison": label,
        "quality_delta": left_quality - right_quality if complete and left_quality is not None and right_quality is not None else None,
        "cost_delta": left.total_observed_cost - right.total_observed_cost if complete and left.total_observed_cost is not None and right.total_observed_cost is not None else None,
        "complete": complete,
    }


def _summaries(algorithm_pairs, transfer_pairs, *, include_final: bool):
    groups = {"algorithm:mcts-simple": list(algorithm_pairs)}
    for algorithm in ("mcts", "simple_scheduler"):
        groups[f"transfer:{algorithm}"] = [
            row for row in transfer_pairs if row["comparison"] == f"C1-C0:{algorithm}"
        ]
    rows = []
    for label, pairs in groups.items():
        complete = [row for row in pairs if row["complete"] and row["quality_delta"] is not None]
        deltas = [row["quality_delta"] for row in complete]
        family_means = {}
        for family in TASK_FAMILIES:
            values = [row["quality_delta"] for row in complete if row["family"] == family]
            family_means[family] = sum(values) / len(values) if values else None
        rows.append({
            "comparison": label,
            "metric": "final_quality" if include_final else "development_preview",
            "complete_pairs": len(complete), "incomplete_pairs": len(pairs) - len(complete),
            "mean_delta": sum(deltas) / len(deltas) if deltas else None,
            "positive": sum(value > 0 for value in deltas),
            "zero": sum(value == 0 for value in deltas),
            "negative": sum(value < 0 for value in deltas),
            "family_means": family_means,
            "decision": _decision(deltas, family_means) if include_final else "not_evaluated_final",
        })
    return tuple(rows)


def _decision(deltas, family_means):
    if len(deltas) != 9 or any(value is None for value in family_means.values()):
        return "incomplete_no_net_claim"
    mean = sum(deltas) / len(deltas)
    nonnegative = sum(value >= 0 for value in deltas)
    floor = min(family_means.values())
    if mean > 0 and nonnegative >= 6 and floor >= -0.05:
        return "bounded_positive_with_cost_report"
    if mean < 0 or floor < -0.05:
        return "harmful_boundary"
    return "no_clear_increment"
