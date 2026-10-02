"""W08 v1 toy scheduler fixture; forbidden as research-effect evidence.

This historical module tests pairing and reporting interfaces, but its action
scores are prescribed rather than produced by mechanism experiments.  Use
``evaluation_v2`` for the mechanism-bound candidate. Importing either module
never runs an evaluation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from time import perf_counter
from typing import Literal

from .decision import Action, Context, Observation
from .mcts import ActionResult, PlanningResult, ResearchState, run_action_mcts, run_simple_scheduler


PROTOCOL_VERSION = "hybrid-w08-v1"
TASK_FAMILIES = ("matching", "condition_change", "misleading_prior")
NUMERIC_SEEDS = (11, 29, 47)
TARGET_BUDGET = 4.0
MAX_EXPANSIONS = 4
MAX_DEPTH = 3
EXPLORE_SHARE = 0.5
PLANNER_SEED_NAMESPACE = "planner-v1"
ENVIRONMENT_NOISE_NAMESPACE = "environment-v1"
_BASE_SCORE_TABLES = {
    "matching": {
        "source": {"deepen": 0.75, "rival": 0.35, "diagnostic": 0.50},
        "target": {"deepen": 0.75, "rival": 0.35, "diagnostic": 0.50},
    },
    "condition_change": {
        "source": {"deepen": 0.75, "rival": 0.35, "diagnostic": 0.50},
        "target": {"deepen": 0.35, "rival": 0.75, "diagnostic": 0.55},
    },
    "misleading_prior": {
        "source": {"deepen": 0.80, "rival": 0.30, "diagnostic": 0.45},
        "target": {"deepen": 0.30, "rival": 0.80, "diagnostic": 0.55},
    },
}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    family: str
    numeric_seed: int
    source_context: Context
    target_context: Context


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
    development_quality: float | None
    final_quality: float | None
    target_spent_cost: float
    transfer_learning_cost: float
    total_observed_cost: float
    unused_target_budget: float
    evaluator_calls: int
    failed_attempts: int
    stopped: bool
    planner_selected_action_id: str | None
    first_executed_action_id: str | None
    elapsed_seconds: float


@dataclass(frozen=True)
class ComparisonReport:
    protocol: dict[str, object]
    records: tuple[EvaluationRecord, ...]
    algorithm_pairs: tuple[dict[str, object], ...]
    transfer_pairs: tuple[dict[str, object], ...]
    llm_auxiliary_status: str
    token_usage: str
    api_cost: str


def registered_actions() -> tuple[Action, ...]:
    derivation_ref = "docs/design/self-improvement-d04/02_construction.zh-CN.md#4-w04-响应研究切片"
    return (
        Action(
            "deepen-fast", "deepen", "exploit", 1.0,
            "deepen the registered transient response with the fast estimator",
            (derivation_ref,),
        ),
        Action(
            "deepen-robust", "deepen", "exploit", 1.0,
            "deepen the same response family with the robust estimator",
            (derivation_ref,),
        ),
        Action(
            "check-rival", "rival", "explore", 1.0,
            "test a registered competing response structure",
            (derivation_ref,),
        ),
        Action(
            "run-diagnostic", "diagnostic", "explore", 1.0,
            "run a registered distinguishing diagnostic",
            (derivation_ref,),
        ),
        Action(
            "stop", "stop", "exploit", 0.0,
            "stop when no positive registered development route is supported",
            (derivation_ref,),
        ),
    )


def locked_task_specs() -> tuple[TaskSpec, ...]:
    rows: list[TaskSpec] = []
    for family in TASK_FAMILIES:
        for numeric_seed in NUMERIC_SEEDS:
            source_regime = "shared"
            target_regime = "shared"
            if family == "condition_change":
                source_regime = "source-condition"
                target_regime = "target-condition"
            source = _context(family=family, regime=source_regime)
            target = _context(family=family, regime=target_regime)
            rows.append(TaskSpec(
                task_id=f"{family}-seed-{numeric_seed}",
                family=family,
                numeric_seed=numeric_seed,
                source_context=source,
                target_context=target,
            ))
    return tuple(rows)


def protocol_manifest() -> dict[str, object]:
    latent_digest = sha256(json.dumps(
        _BASE_SCORE_TABLES, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    manifest: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "task_families": list(TASK_FAMILIES),
        "numeric_seeds": list(NUMERIC_SEEDS),
        "task_count": len(TASK_FAMILIES) * len(NUMERIC_SEEDS),
        "algorithms": ["mcts", "simple_scheduler"],
        "transfer_arms": ["C0", "C1"],
        "target_budget_per_run": TARGET_BUDGET,
        "max_expansions": MAX_EXPANSIONS,
        "max_depth": MAX_DEPTH,
        "explore_share": EXPLORE_SHARE,
        "action_ids": [action.action_id for action in registered_actions()],
        "paired_environment_randomness": (
            "sha256(task family, numeric seed, phase, action id, environment namespace); "
            "independent of planner RNG and call order"
        ),
        "development_endpoint_rule": (
            "highest positive unique development learning_increment; STOP on no positive evidence; "
            "tie by action_id"
        ),
        "primary_quality_metric": "held-out final score of the common development endpoint rule",
        "cost_fields": [
            "target_spent_cost",
            "transfer_learning_cost",
            "total_observed_cost",
            "unused_target_budget",
            "evaluator_calls",
            "failed_attempts",
            "elapsed_seconds",
        ],
        "algorithm_comparison": "MCTS minus simple, C0 only",
        "transfer_comparison": "C1 minus C0 within each algorithm",
        "c0_adaptation": "full target-episode feedback and revision enabled; no cross-task prior",
        "c1_difference": "development-only source observations supplied as cross-task prior",
        "final_feedback": "forbidden; final score is computed after planning and never returned to a planner",
        "latent_rule_version": "bounded-response-family-map-v1",
        "latent_environment_digest": latent_digest,
        "llm_auxiliary": "not executed in harness; requires real researcher dispatch",
        "token_and_api_cost": "Unknown when provider telemetry is unavailable",
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["protocol_hash"] = sha256(encoded).hexdigest()
    return manifest


def run_locked_evaluation(*, include_final: bool = False) -> ComparisonReport:
    """Run the frozen comparison; held-out scoring is opt-in and post-planning."""
    manifest = protocol_manifest()
    protocol_hash = str(manifest["protocol_hash"])
    records: list[EvaluationRecord] = []
    for task in locked_task_specs():
        for algorithm in ("mcts", "simple_scheduler"):
            for arm in ("C0", "C1"):
                records.append(_run_one(
                    task=task,
                    algorithm=algorithm,
                    arm=arm,
                    protocol_hash=protocol_hash,
                    include_final=include_final,
                ))
    return ComparisonReport(
        protocol=manifest,
        records=tuple(records),
        algorithm_pairs=_algorithm_pairs(records, include_final=include_final),
        transfer_pairs=_transfer_pairs(records, include_final=include_final),
        llm_auxiliary_status="not_executed_real_researcher_required",
        token_usage="Unknown",
        api_cost="Unknown",
    )


def report_as_dict(report: ComparisonReport) -> dict[str, object]:
    return asdict(report)


def _run_one(
    *,
    task: TaskSpec,
    algorithm: str,
    arm: str,
    protocol_hash: str,
    include_final: bool,
) -> EvaluationRecord:
    started = perf_counter()
    actions = registered_actions()
    source_priors = _source_observations(task, actions) if arm == "C1" else ()
    transfer_cost = sum(row.actual_cost or 0.0 for row in source_priors)
    evaluator_calls = 0

    def evaluate(branch: ResearchState, action: Action, evaluator_seed: int) -> ActionResult:
        nonlocal evaluator_calls
        del evaluator_seed
        evaluator_calls += 1
        return ActionResult(_observation(
            task=task,
            context=branch.context,
            action=action,
            phase="target-development",
            split="development",
        ))

    initial_state = ResearchState(
        context=task.target_context,
        hypothesis_ref=f"hypothesis:{task.family}:bounded-response",
        prediction_refs=(f"prediction:{task.family}:distinguishing-response",),
        competing_explanation_refs=(f"rival:{task.family}:alternative-response",),
    )
    planner = run_action_mcts if algorithm == "mcts" else run_simple_scheduler
    result: PlanningResult = planner(
        enabled=True,
        initial_state=initial_state,
        actions=actions,
        evaluator=evaluate,
        metric="distinguishing_gain",
        direction=1,
        seed=_planner_seed(task, algorithm),
        total_budget=TARGET_BUDGET,
        max_expansions=MAX_EXPANSIONS,
        max_depth=MAX_DEPTH,
        exploration_weight=0.7,
        explore_share=EXPLORE_SHARE,
        stop_action_ids=("stop",),
        prior_observations=source_priors,
    )
    elapsed = perf_counter() - started
    endpoint_action_id, development_quality = _development_endpoint(result)
    final_quality = None
    if include_final:
        final_quality = (
            _score(task, endpoint_action_id, phase="target-final")
            if endpoint_action_id is not None
            else 0.0
        )
    failed_attempts = sum(
        row.status not in {"completed", "stopped", "duplicate_observation_not_relearned"}
        for row in result.trace
    )
    return EvaluationRecord(
        task_id=task.task_id,
        family=task.family,
        numeric_seed=task.numeric_seed,
        algorithm=algorithm,  # type: ignore[arg-type]
        arm=arm,  # type: ignore[arg-type]
        protocol_hash=protocol_hash,
        development_only=not include_final,
        endpoint_action_id=endpoint_action_id,
        development_quality=development_quality,
        final_quality=final_quality,
        target_spent_cost=result.spent_cost,
        transfer_learning_cost=transfer_cost,
        total_observed_cost=result.spent_cost + transfer_cost,
        unused_target_budget=TARGET_BUDGET - result.spent_cost,
        evaluator_calls=evaluator_calls + len(source_priors),
        failed_attempts=failed_attempts,
        stopped=endpoint_action_id is None,
        planner_selected_action_id=result.selected_action_id,
        first_executed_action_id=result.first_executed_action_id,
        elapsed_seconds=elapsed,
    )


def _source_observations(
    task: TaskSpec,
    actions: tuple[Action, ...],
) -> tuple[Observation, ...]:
    return tuple(
        _observation(
            task=task,
            context=task.source_context,
            action=action,
            phase="source-development",
            split="development",
        )
        for action in actions
        if action.action_id != "stop"
    )


def _observation(
    *,
    task: TaskSpec,
    context: Context,
    action: Action,
    phase: str,
    split: str,
) -> Observation:
    score = _score(task, action.action_id, phase=phase)
    return Observation(
        run_id=f"{PROTOCOL_VERSION}:{task.task_id}:{phase}:{action.action_id}",
        action_id=action.action_id,
        context=context,
        split=split,
        protocol_id=context.evaluation_protocol,
        metric="distinguishing_gain",
        direction=1,
        baseline=0.0,
        result=score,
        scale=1.0,
        actual_cost=action.estimated_cost,
        status="completed",
        evidence_ref=f"synthetic-engineering:{task.task_id}:{phase}:{action.action_id}",
    )


def _development_endpoint(result: PlanningResult) -> tuple[str | None, float | None]:
    eligible = [
        (row.learning_increment, row.action_id)
        for row in result.trace
        if row.split == "development"
        and row.learning_increment is not None
        and row.status == "completed"
    ]
    if not eligible:
        return None, 0.0
    increment, action_id = max(eligible, key=lambda row: (row[0], row[1]))
    if increment <= 0:
        return None, 0.0
    return action_id, increment


def _score(task: TaskSpec, action_id: str, *, phase: str) -> float:
    family = next(action.family for action in registered_actions() if action.action_id == action_id)
    source = phase == "source-development"
    base = _base_score(task.family, family, source=source)
    variant = 0.02 if action_id == "deepen-robust" else 0.0
    noise = _paired_noise(task, action_id=action_id, phase=phase)
    return max(0.0, min(1.0, base + variant + noise))


def _base_score(task_family: str, action_family: str, *, source: bool) -> float:
    try:
        table = _BASE_SCORE_TABLES[task_family]["source" if source else "target"]
        return table[action_family]
    except KeyError as exc:
        raise ValueError(
            f"unknown task/action family: {task_family}/{action_family}"
        ) from exc


def _paired_noise(task: TaskSpec, *, action_id: str, phase: str) -> float:
    payload = (
        f"{ENVIRONMENT_NOISE_NAMESPACE}|{task.family}|{task.numeric_seed}|{phase}|{action_id}"
    ).encode("utf-8")
    integer = int.from_bytes(sha256(payload).digest()[:8], "big")
    return ((integer / (2**64 - 1)) * 2.0 - 1.0) * 0.08


def _planner_seed(task: TaskSpec, algorithm: str) -> int:
    payload = (
        f"{PLANNER_SEED_NAMESPACE}|{task.family}|{task.numeric_seed}|{algorithm}"
    ).encode("utf-8")
    return int.from_bytes(sha256(payload).digest()[:8], "big")


def _context(*, family: str, regime: str) -> Context:
    return Context.from_mapping(
        stage="development",
        objective="bounded response structure discrimination",
        conditions={"task_family": family, "visible_regime": regime},
        evaluation_protocol=f"{PROTOCOL_VERSION}:{family}:{regime}",
    )


def _algorithm_pairs(
    records: list[EvaluationRecord],
    *,
    include_final: bool,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for task in locked_task_specs():
        pair = {
            row.algorithm: row for row in records
            if row.task_id == task.task_id and row.arm == "C0"
        }
        simple = pair["simple_scheduler"]
        mcts = pair["mcts"]
        rows.append({
            "task_id": task.task_id,
            "quality_metric": "final_quality" if include_final else "development_quality_preview",
            "mcts_minus_simple_quality": _difference(
                mcts.final_quality if include_final else mcts.development_quality,
                simple.final_quality if include_final else simple.development_quality,
            ),
            "mcts_minus_simple_total_cost": mcts.total_observed_cost - simple.total_observed_cost,
        })
    return tuple(rows)


def _transfer_pairs(
    records: list[EvaluationRecord],
    *,
    include_final: bool,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for task in locked_task_specs():
        for algorithm in ("mcts", "simple_scheduler"):
            pair = {
                row.arm: row for row in records
                if row.task_id == task.task_id and row.algorithm == algorithm
            }
            c0 = pair["C0"]
            c1 = pair["C1"]
            rows.append({
                "task_id": task.task_id,
                "algorithm": algorithm,
                "quality_metric": "final_quality" if include_final else "development_quality_preview",
                "c1_minus_c0_quality": _difference(
                    c1.final_quality if include_final else c1.development_quality,
                    c0.final_quality if include_final else c0.development_quality,
                ),
                "c1_minus_c0_total_cost": c1.total_observed_cost - c0.total_observed_cost,
            })
    return tuple(rows)


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right
