"""Generate and execute the frozen W11 synthetic comparison exactly once.

The real preset is only loaded by :func:`locked_plan`; importing this module or
running the CLI without ``--execute-once`` does not generate observations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from random import Random
from typing import Any

from factor_factory.runtime_context import write_json_atomic

from .proposal_comparison import (
    comparison_as_dict,
    load_development_package,
    run_development_comparison,
    score_confirmation_after_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_ROOT = REPO_ROOT / "docs/design/self-improvement-d04"
PROBLEM_PATH = DESIGN_ROOT / "w11-proposal-comparison/common_problem.json"
MATH_PATH = DESIGN_ROOT / "17_w11_math_adjudication.zh-CN.md"
PRESET_PATH = DESIGN_ROOT / "w11-proposal-comparison/synthetic_presets.evaluation-only.json"
PUBLIC_IDS = ("w11-task-01", "w11-task-02", "w11-task-03")
EXPECTED_PROBLEM_SHA256 = "017486f18d2e5f98a72e79d6cafd30e79c4274d8e818ca22693bad55e9858e85"
EXPECTED_MATH_SHA256 = "84e36fce1a2baaf67e5b8be3a519dbc99ca2d455b668cabee90d56b90e355b8b"
EXPECTED_PRESET_SHA256 = "c27fb484ef25d450613002ce823696a378ac69d1fb7f482a5fa432f2f566ed9b"


class LockedDriverError(RuntimeError):
    """The frozen one-shot run cannot proceed or be resumed automatically."""


@dataclass(frozen=True)
class GenerationTask:
    evaluation_id: str
    public_id: str
    generation_seed: int
    intercept: float
    direct_gain: float
    memory: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class LockedPlan:
    problem_path: str
    problem_sha256: str
    math_path: str
    math_sha256: str
    preset_path: str
    preset_sha256: str
    development_impulses: tuple[float, ...]
    confirmation_impulses: tuple[float, ...]
    noise_low: float
    noise_high: float
    proposer_seeds: tuple[int, ...]
    max_attempts: int
    max_evaluations: int
    gp_generations: int
    gp_population_size: int
    tasks: tuple[GenerationTask, ...]


def locked_plan() -> LockedPlan:
    plan = _source_plan()
    _validate_locked_plan(plan)
    return plan


def _source_plan() -> LockedPlan:
    problem = _load_json(PROBLEM_PATH)
    preset = _load_json(PRESET_PATH)
    if preset.get("status") != "fixed_before_generation_not_executed":
        raise LockedDriverError("preset is not frozen before generation")
    raw_tasks = preset.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) != len(PUBLIC_IDS):
        raise LockedDriverError("preset must contain exactly three ordered tasks")
    tasks = []
    for public_id, raw in zip(PUBLIC_IDS, raw_tasks):
        memory = tuple((float(row["r"]), float(row["g"])) for row in raw["memory"])
        tasks.append(GenerationTask(
            evaluation_id=str(raw["task_id"]),
            public_id=public_id,
            generation_seed=int(raw["generation_seed"]),
            intercept=float(raw["b"]),
            direct_gain=float(raw["d"]),
            memory=memory,
        ))
    visible = problem["common_visible_input"]
    noise = preset["noise"]
    budgets = preset["budgets"]
    return LockedPlan(
        str(PROBLEM_PATH), _sha(PROBLEM_PATH),
        str(MATH_PATH), _sha(MATH_PATH),
        str(PRESET_PATH), _sha(PRESET_PATH),
        tuple(float(value) for value in visible["signed_impulses"]),
        tuple(float(value) for value in preset["confirmation_inputs"]),
        float(noise["low"]), float(noise["high"]),
        tuple(int(value) for value in preset["proposal_seeds"]),
        int(budgets["max_attempts"]), int(budgets["max_evaluations"]),
        int(budgets["gp_generations"]), int(budgets["gp_population_size"]),
        tuple(tasks),
    )


def execute_plan_once(
    plan: LockedPlan,
    output_root: str | Path,
    *,
    enforce_locked: bool = True,
) -> dict[str, Any]:
    """Generate, run all development arms, persist, then load confirmation."""
    if enforce_locked:
        _validate_locked_plan(plan)
    root = Path(output_root).expanduser().resolve()
    if root.exists():
        raise LockedDriverError("output root already exists; selective rerun is forbidden")
    root.mkdir(parents=True)
    evaluation_root = root / "evaluation"
    evaluation_root.mkdir()
    write_json_atomic(evaluation_root / "locked_plan.json", asdict(plan))
    state_path = root / "run_state.json"
    state: dict[str, Any] = {
        "status": "started",
        "phase": "generation",
        "plan_identity": _plan_identity(plan),
        "plan": _public_plan_projection(plan),
        "completed_public_tasks": [],
        "development_saved": False,
        "completed_development_arms": 0,
        "confirmation_load_attempted": False,
        "confirmation_loaded": False,
        "confirmation_loaded_count": 0,
        "completed_confirmation_scores": 0,
        "rerun_allowed": False,
    }
    write_json_atomic(state_path, state)
    try:
        package_paths = _generate_packages(plan, root)
        state.update(
            phase="development",
            completed_public_tasks=[path.parent.name for path in package_paths],
        )
        write_json_atomic(state_path, state)

        packages = [load_development_package(path) for path in package_paths]
        development = []
        development_payload = {
            "status": "development_in_progress_confirmation_not_loaded",
            "plan_identity": _plan_identity(plan),
            "completed_arms": [],
            "results": [],
        }
        development_path = root / "development_results.json"

        for package in packages:
            def persist_arm(arm, *, task_id=package.task_id):
                development_payload["completed_arms"].append({
                    "task_id": task_id,
                    "arm": asdict(arm),
                })
                write_json_atomic(development_path, development_payload)
                state["completed_development_arms"] = len(
                    development_payload["completed_arms"]
                )
                write_json_atomic(state_path, state)

            result = run_development_comparison(
                package, enabled=True, after_arm=persist_arm
            )
            development.append(result)
            development_payload["results"].append(comparison_as_dict(result))
            write_json_atomic(development_path, development_payload)
        _validate_all_development_selected(packages, development)
        development_payload["status"] = "all_development_selected_confirmation_not_loaded"
        write_json_atomic(development_path, development_payload)
        state.update(
            phase="confirmation",
            development_saved=True,
            development_path=str(development_path),
            development_sha256=_sha(development_path),
        )
        write_json_atomic(state_path, state)

        scores = []
        confirmation_path = root / "confirmation_scores.json"
        confirmation_payload = {
            "status": "confirmation_in_progress_after_all_development_saved",
            "plan_identity": _plan_identity(plan),
            "scores": scores,
            "confirmation_fit_evaluations": 0,
            "confirmation_elapsed_ns": 0,
            "cost_unit": "fit_response_program_call",
            "interpretation": "raw bounded synthetic comparison evidence; no winner or self-improvement claim",
        }
        for package, result in zip(packages, development):
            state["confirmation_load_attempted"] = True
            write_json_atomic(state_path, state)
            confirmation = _load_confirmation_after_development_saved(
                root, package.task_id, state
            )
            state["confirmation_loaded"] = True
            state["confirmation_loaded_count"] += 1
            write_json_atomic(state_path, state)
            for arm in result.arms:
                score = asdict(score_confirmation_after_selection(
                    package=package,
                    development=result,
                    proposer=arm.proposer,
                    seed=arm.seed,
                    continuation_impulses=tuple(confirmation["signed_impulses"]),
                    confirmation_observed_response=tuple(confirmation["observed_response"]),
                ))
                scores.append(score)
                confirmation_payload["confirmation_fit_evaluations"] += score[
                    "confirmation_fit_evaluations"
                ]
                confirmation_payload["confirmation_elapsed_ns"] += score[
                    "confirmation_elapsed_ns"
                ]
                write_json_atomic(confirmation_path, confirmation_payload)
                state["completed_confirmation_scores"] = len(scores)
                write_json_atomic(state_path, state)
        confirmation_payload["status"] = "scored_after_all_development_saved"
        write_json_atomic(confirmation_path, confirmation_payload)
        state.update(
            status="complete",
            phase="complete",
            confirmation_path=str(confirmation_path),
            confirmation_sha256=_sha(confirmation_path),
        )
        write_json_atomic(state_path, state)
        return state
    except Exception as exc:
        state.update(
            status="failed_partial_preserved",
            failure={"type": type(exc).__name__, "message": str(exc)},
            rerun_allowed=False,
        )
        if state.get("phase") == "confirmation":
            state["failed_confirmation_fit_cost"] = "Unknown"
        write_json_atomic(state_path, state)
        raise


def _generate_packages(plan: LockedPlan, root: Path) -> list[Path]:
    public_root = root / "public"
    evaluation_root = root / "evaluation"
    public_root.mkdir()
    evaluation_root.mkdir(exist_ok=True)
    package_paths = []
    for task in plan.tasks:
        full_impulses = plan.development_impulses + plan.confirmation_impulses
        noiseless, observed = _generate_series(
            impulses=full_impulses,
            intercept=task.intercept,
            direct_gain=task.direct_gain,
            memory=task.memory,
            seed=task.generation_seed,
            noise_low=plan.noise_low,
            noise_high=plan.noise_high,
        )
        task_root = public_root / task.public_id
        task_root.mkdir()
        package_path = task_root / "package.json"
        write_json_atomic(package_path, _public_package(
            plan, task, observed[:len(plan.development_impulses)]
        ))
        write_json_atomic(evaluation_root / f"{task.public_id}.json", {
            "visibility": "evaluation_side_only",
            "public_task_id": task.public_id,
            "evaluation_id": task.evaluation_id,
            "generation_seed": task.generation_seed,
            "truth": {
                "b": task.intercept,
                "d": task.direct_gain,
                "memory": [{"r": rate, "g": gain} for rate, gain in task.memory],
                "noiseless_response": noiseless,
            },
            "confirmation": {
                "signed_impulses": plan.confirmation_impulses,
                "observed_response": observed[len(plan.development_impulses):],
            },
        })
        package_paths.append(package_path)
    return package_paths


def _validate_locked_plan(plan: LockedPlan) -> None:
    expected = _source_plan()
    if plan != expected:
        raise LockedDriverError(
            "locked W11 plan differs from the current bound problem/math/preset sources"
        )
    expected_confirmation = (-1.0, 1.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)
    checks = (
        plan.problem_sha256 == EXPECTED_PROBLEM_SHA256,
        plan.math_sha256 == EXPECTED_MATH_SHA256,
        plan.preset_sha256 == EXPECTED_PRESET_SHA256,
        len(plan.development_impulses) == 16,
        plan.confirmation_impulses == expected_confirmation,
        plan.noise_low == -0.02 and plan.noise_high == 0.02,
        plan.proposer_seeds == (101, 211, 307),
        plan.max_attempts == plan.max_evaluations == 32,
        plan.gp_generations == 8 and plan.gp_population_size == 6,
        tuple(task.public_id for task in plan.tasks) == PUBLIC_IDS,
        tuple(len(task.memory) for task in plan.tasks) == (0, 1, 2),
    )
    if not all(checks):
        raise LockedDriverError("locked W11 plan differs from the pre-generation adjudication")
    for task in plan.tasks:
        rates = tuple(rate for rate, _gain in task.memory)
        if rates != tuple(sorted(set(rates))) or any(
            rate not in tuple(value / 10 for value in range(1, 10)) for rate in rates
        ):
            raise LockedDriverError("locked W11 task has a noncanonical memory domain")


def _validate_all_development_selected(packages, development) -> None:
    expected = {
        (package.task_id, proposer, seed)
        for package in packages
        for seed in package.proposer_seeds
        for proposer in ("simple_seeded_nonadaptive", "response_gp")
    }
    observed: set[tuple[str, str, int]] = set()
    for result in development:
        for arm in result.arms:
            identity = (result.task_id, arm.proposer, arm.seed)
            if identity in observed:
                raise LockedDriverError(f"duplicate development arm: {identity}")
            observed.add(identity)
            selected_id = arm.search.selected_id
            matches = [
                row for row in arm.search.trace if row.candidate_id == selected_id
            ] if selected_id is not None else []
            if (
                len(matches) != 1
                or matches[0].program is None
                or matches[0].fit is None
                or matches[0].status != "kept"
            ):
                raise LockedDriverError(
                    f"development arm has no complete selected program and fit: {identity}"
                )
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise LockedDriverError(
            f"development arm identity set mismatch; missing={missing}, extra={extra}"
        )


def _public_package(
    plan: LockedPlan, task: GenerationTask, development_response: tuple[float, ...]
) -> dict[str, Any]:
    indexes = list(range(len(plan.development_impulses)))
    return {
        "contract_version": "hybrid_proposal_comparison_v1",
        "status": "frozen_before_results",
        "task_id": task.public_id,
        "problem_binding": {"path": plan.problem_path, "sha256": plan.problem_sha256},
        "step2_binding": {"path": plan.math_path, "sha256": plan.math_sha256},
        "fit_data": {
            "signed_impulses": plan.development_impulses,
            "observed_response": development_response,
            "step": 1.0,
        },
        "derivation_scope": {
            "derivation_ref": f"{plan.math_path}#结果前固定的共同选择",
            "mathematical_object": "causal kernels",
            "domain": "finite signed impulses",
            "initial_state": "zero",
            "clock": "event",
            "missing_value_policy": "missing is not zero",
            "observation_map": "signed J to y",
            "allowed_transformations": ["causal convolution", "linear superposition"],
            "distinguishing_predictions": ["direct jump and zero, one, or two stable memory tails"],
            "current_gap": "bounded K0/K1/K2 proposal quality remains to be compared",
            "allowed_response_families": [
                "transient_exponential_kernel", "two_scale_superposition",
                "direct_input_component", "zero_memory_component"
            ],
            "allowed_research_actions": ["parameter_search", "structure_search"],
        },
        "response_semantics": {
            "observation_timing": "same_event",
            "rate_parameterization": "retention",
            "pre_sample_input": "zero",
            "initial_state": "zero",
            "intercept": "profiled",
            "direct_input": "profiled_same_event",
            "gain_mode": "profiled_component",
            "gain_constraint": "unrestricted",
            "memory_rate_policy": "strict_increasing_unique",
            "training_indexes": indexes,
            "score_indexes": indexes,
            "input_start_index": 0,
            "initial_state_start_index": 0,
            "initial_power_offset": 1,
        },
        "comparison_config": {
            "proposers": ["simple_seeded_nonadaptive", "response_gp"],
            "proposer_seeds": plan.proposer_seeds,
            "allowed_rates": [value / 10 for value in range(1, 10)],
            "allowed_scales": [1.0],
            "generations": plan.gp_generations,
            "population_size": plan.gp_population_size,
            "max_evaluations": plan.max_evaluations,
            "max_attempts": plan.max_attempts,
        },
    }


def _generate_series(
    *,
    impulses: tuple[float, ...],
    intercept: float,
    direct_gain: float,
    memory: tuple[tuple[float, float], ...],
    seed: int,
    noise_low: float,
    noise_high: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    states = [0.0] * len(memory)
    noiseless = []
    for impulse in impulses:
        for index, (rate, _gain) in enumerate(memory):
            states[index] = rate * states[index] + impulse
        noiseless.append(
            intercept
            + direct_gain * impulse
            + sum(gain * states[index] for index, (_rate, gain) in enumerate(memory))
        )
    rng = Random(seed)
    observed = tuple(value + rng.uniform(noise_low, noise_high) for value in noiseless)
    return tuple(noiseless), observed


def _load_confirmation_after_development_saved(
    root: Path, public_task_id: str, state: dict[str, Any]
) -> dict[str, Any]:
    if not state.get("development_saved") or not Path(state["development_path"]).is_file():
        raise LockedDriverError("confirmation cannot load before all development is saved")
    payload = _load_json(root / "evaluation" / f"{public_task_id}.json")
    return payload["confirmation"]


def _plan_identity(plan: LockedPlan) -> str:
    encoded = json.dumps(asdict(plan), sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _public_plan_projection(plan: LockedPlan) -> dict[str, Any]:
    return {
        "plan_identity": _plan_identity(plan),
        "source_bindings": {
            "problem": {"path": plan.problem_path, "sha256": plan.problem_sha256},
            "math": {"path": plan.math_path, "sha256": plan.math_sha256},
            "preset": {"path": plan.preset_path, "sha256": plan.preset_sha256},
        },
        "public_task_ids": [task.public_id for task in plan.tasks],
        "development_impulses": plan.development_impulses,
        "confirmation_impulses": plan.confirmation_impulses,
        "proposer_seeds": plan.proposer_seeds,
        "budgets": {
            "max_attempts": plan.max_attempts,
            "max_evaluations": plan.max_evaluations,
            "gp_generations": plan.gp_generations,
            "gp_population_size": plan.gp_population_size,
        },
        "hidden_generation_parameters": "evaluation/locked_plan.json",
        "boundary": "information-discipline projection; not filesystem access isolation",
    }


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LockedDriverError(f"expected JSON object: {path}")
    return value
