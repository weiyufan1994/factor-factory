"""W11 bounded comparison of non-adaptive proposals and the actual response GP.

Development packages are public and source-bound. Confirmation observations
are accepted only by the separate scoring function after candidate selection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from random import Random
from time import perf_counter_ns
from typing import Any, Callable

from .gp_adapter import (
    Candidate,
    KernelTerm,
    ResponseProgram,
    SearchResult,
    fit_response_program,
    run_response_gp,
    validate_response_fit_contract,
    validate_response_search_contract,
)
from .response import ResponseSemantics, retention_from_parameter
from .synthetic import FitData
from .variation import DerivationScope


CONTRACT_VERSION = "hybrid_proposal_comparison_v1"
PROPOSERS = ("simple_seeded_nonadaptive", "response_gp")
_FORBIDDEN_PUBLIC_KEYS = {
    "confirmation_observed_response",
    "confirmation_result",
    "expected_winner",
    "hidden_truth",
    "oracle_parameters",
}


class ComparisonContractError(ValueError):
    """The frozen public comparison package is incomplete or unsafe."""


@dataclass(frozen=True)
class ProposalBudget:
    generations: int
    population_size: int
    max_evaluations: int
    max_attempts: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int
            for value in (
                self.generations,
                self.population_size,
                self.max_evaluations,
                self.max_attempts,
            )
        ):
            raise ComparisonContractError("proposal budgets must be integers")
        if self.generations < 1 or self.population_size < 3:
            raise ComparisonContractError("invalid proposal generation budget")
        if not 1 <= self.max_evaluations <= 32 or not 1 <= self.max_attempts <= 32:
            raise ComparisonContractError("each proposer budget must be in [1, 32]")


@dataclass(frozen=True)
class DevelopmentPackage:
    task_id: str
    problem_binding: dict[str, str]
    step2_binding: dict[str, str]
    fit_data: FitData
    scope: DerivationScope
    semantics: ResponseSemantics
    allowed_rates: tuple[float, ...]
    allowed_scales: tuple[float, ...]
    proposer_seeds: tuple[int, ...]
    budget: ProposalBudget
    package_hash: str


@dataclass(frozen=True)
class ArmResult:
    proposer: str
    seed: int
    search: SearchResult
    elapsed_ns: int
    actual_fit_evaluations: int
    proposal_attempts: int
    duplicate_attempts: int
    failed_attempts: int
    cost_unit: str = "fit_response_program_call"


@dataclass(frozen=True)
class DevelopmentComparison:
    task_id: str
    package_hash: str
    arms: tuple[ArmResult, ...]
    confirmation_status: str = "not_loaded_not_scored"
    interpretation: str = "development proposal evidence only"


@dataclass(frozen=True)
class ConfirmationScore:
    task_id: str
    package_hash: str
    proposer: str
    seed: int
    selected_candidate_id: str
    confirmation_indexes: tuple[int, ...]
    confirmation_mse: float
    coefficients_reproduced: bool
    confirmation_fit_evaluations: int
    confirmation_elapsed_ns: int
    cost_unit: str = "fit_response_program_call"


def load_development_package(path: str | Path) -> DevelopmentPackage:
    package_path = Path(path).expanduser().resolve()
    raw = json.loads(package_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("contract_version") != CONTRACT_VERSION:
        raise ComparisonContractError("unsupported comparison package contract")
    forbidden = _find_forbidden_keys(raw)
    if forbidden:
        raise ComparisonContractError(
            "public development package contains forbidden result fields: " + ", ".join(forbidden)
        )
    if raw.get("status") != "frozen_before_results":
        raise ComparisonContractError("comparison package must be frozen before results")
    problem_binding = _verify_binding(package_path.parent, raw.get("problem_binding"), "problem")
    step2_binding = _verify_binding(package_path.parent, raw.get("step2_binding"), "Step2 derivation")
    fit = raw["fit_data"]
    scope = raw["derivation_scope"]
    semantics = raw["response_semantics"]
    config = raw["comparison_config"]
    if tuple(config.get("proposers", ())) != PROPOSERS:
        raise ComparisonContractError("comparison requires exactly the simple and response_gp proposers")
    seeds = tuple(config["proposer_seeds"])
    if not 1 <= len(seeds) <= 3 or any(type(seed) is not int for seed in seeds):
        raise ComparisonContractError("comparison requires one to three integer proposer seeds")
    if len(set(seeds)) != len(seeds):
        raise ComparisonContractError("proposer seeds must be unique")
    package_hash = sha256(package_path.read_bytes()).hexdigest()
    try:
        expected_ref_prefix = f"{raw['step2_binding']['path']}#"
        if not str(scope["derivation_ref"]).startswith(expected_ref_prefix):
            raise ComparisonContractError(
                "derivation_scope.derivation_ref must point inside the bound Step2 artifact"
            )
        package = DevelopmentPackage(
            task_id=str(raw["task_id"]),
            problem_binding=problem_binding,
            step2_binding=step2_binding,
            fit_data=FitData(
                tuple(float(value) for value in fit["signed_impulses"]),
                tuple(float(value) for value in fit["observed_response"]),
                float(fit["step"]),
            ),
            scope=DerivationScope(
                derivation_ref=str(scope["derivation_ref"]),
                mathematical_object=str(scope["mathematical_object"]),
                domain=str(scope["domain"]),
                initial_state=str(scope["initial_state"]),
                clock=str(scope["clock"]),
                missing_value_policy=str(scope["missing_value_policy"]),
                observation_map=str(scope["observation_map"]),
                allowed_transformations=tuple(scope["allowed_transformations"]),
                distinguishing_predictions=tuple(scope["distinguishing_predictions"]),
                current_gap=str(scope["current_gap"]),
                allowed_response_families=tuple(scope["allowed_response_families"]),
                allowed_research_actions=tuple(scope["allowed_research_actions"]),
            ),
            semantics=ResponseSemantics(
                observation_timing=semantics["observation_timing"],
                rate_parameterization=semantics["rate_parameterization"],
                pre_sample_input=semantics["pre_sample_input"],
                initial_state=semantics["initial_state"],
                intercept=semantics["intercept"],
                direct_input=semantics["direct_input"],
                gain_mode=semantics["gain_mode"],
                gain_constraint=semantics["gain_constraint"],
                memory_rate_policy=semantics["memory_rate_policy"],
                training_indexes=tuple(semantics["training_indexes"]),
                score_indexes=tuple(semantics.get("score_indexes", ())),
                input_start_index=semantics.get("input_start_index", 0),
                initial_state_start_index=semantics.get("initial_state_start_index", 0),
                initial_power_offset=semantics.get("initial_power_offset", 1),
            ),
            allowed_rates=tuple(float(value) for value in config["allowed_rates"]),
            allowed_scales=tuple(float(value) for value in config["allowed_scales"]),
            proposer_seeds=seeds,
            budget=ProposalBudget(
                generations=config["generations"],
                population_size=config["population_size"],
                max_evaluations=config["max_evaluations"],
                max_attempts=config["max_attempts"],
            ),
            package_hash=package_hash,
        )
        if not package.task_id.strip():
            raise ComparisonContractError("task_id must be nonempty")
        if (
            package.semantics.gain_mode == "profiled_component"
            and package.allowed_scales != (1.0,)
        ):
            raise ComparisonContractError(
                "profiled_component comparison requires allowed_scales=[1.0]"
            )
        if not package.allowed_rates or not package.allowed_scales:
            raise ComparisonContractError("comparison parameter domains cannot be empty")
        if len(package.allowed_rates) * len(package.allowed_scales) > 64:
            raise ComparisonContractError("comparison program term domain exceeds the bounded limit")
        if any(not isfinite(value) for value in package.allowed_scales):
            raise ComparisonContractError("allowed_scales must be finite")
        for rate in package.allowed_rates:
            retention_from_parameter(
                rate,
                parameterization=package.semantics.rate_parameterization,
                step=package.fit_data.step,
            )
        if not package.semantics.training_indexes or not package.semantics.score_indexes:
            raise ComparisonContractError(
                "frozen comparison requires explicit nonempty training_indexes and score_indexes"
            )
        validate_response_search_contract(
            scope=package.scope,
            allowed_rates=package.allowed_rates,
            allowed_scales=package.allowed_scales,
            response_semantics=package.semantics,
            step=package.fit_data.step,
        )
        _preflight(package)
        return package
    except (KeyError, TypeError, ValueError) as exc:
        raise ComparisonContractError(f"invalid frozen comparison package: {exc}") from exc


def run_development_comparison(
    package: DevelopmentPackage,
    *,
    enabled: bool = False,
    after_arm: Callable[[ArmResult], None] | None = None,
) -> DevelopmentComparison:
    if not enabled:
        raise ComparisonContractError("development comparison requires explicit enabled=True")
    _preflight(package)
    arms: list[ArmResult] = []
    for seed in package.proposer_seeds:
        for runner in (_run_simple, _run_gp):
            arm = runner(package, seed)
            arms.append(arm)
            if after_arm is not None:
                after_arm(arm)
    return DevelopmentComparison(package.task_id, package.package_hash, tuple(arms))


def score_confirmation_after_selection(
    *,
    package: DevelopmentPackage,
    development: DevelopmentComparison,
    proposer: str,
    seed: int,
    continuation_impulses: tuple[float, ...],
    confirmation_observed_response: tuple[float, ...],
) -> ConfirmationScore:
    """Score one already-selected arm; confirmation values never enter search."""
    _preflight(package)
    if development.package_hash != package.package_hash or development.task_id != package.task_id:
        raise ComparisonContractError("development result does not bind to the package")
    matches = [row for row in development.arms if row.proposer == proposer and row.seed == seed]
    if len(matches) != 1 or matches[0].search.selected is None:
        raise ComparisonContractError("confirmation requires one selected development candidate")
    arm = matches[0]
    selected = arm.search.selected
    if selected.program is None or selected.fit is None:
        raise ComparisonContractError("selected development candidate has no reproducible fit")
    if len(continuation_impulses) != len(confirmation_observed_response) or not continuation_impulses:
        raise ComparisonContractError("confirmation inputs and observations must be nonempty and aligned")
    full = FitData(
        package.fit_data.signed_impulses + tuple(continuation_impulses),
        package.fit_data.observed_response + tuple(confirmation_observed_response),
        package.fit_data.step,
    )
    started = perf_counter_ns()
    reproduced = fit_response_program(selected.program, full, package.semantics)
    elapsed_ns = perf_counter_ns() - started
    coefficients_reproduced = _coefficients_match(
        reproduced.coefficients, selected.fit.coefficients
    )
    if not coefficients_reproduced:
        raise ComparisonContractError("development coefficients did not reproduce before confirmation scoring")
    indexes = tuple(range(len(package.fit_data.observed_response), len(full.observed_response)))
    loss = sum(
        (full.observed_response[index] - reproduced.prediction[index]) ** 2
        for index in indexes
    ) / len(indexes)
    if not isfinite(loss):
        raise ComparisonContractError("confirmation loss must be finite")
    return ConfirmationScore(
        package.task_id,
        package.package_hash,
        proposer,
        seed,
        selected.candidate_id,
        indexes,
        loss,
        True,
        1,
        elapsed_ns,
    )


def _preflight(package: DevelopmentPackage) -> None:
    if not package.semantics.training_indexes or not package.semantics.score_indexes:
        raise ComparisonContractError(
            "comparison requires frozen explicit training and score indexes"
        )
    validate_response_search_contract(
        scope=package.scope,
        allowed_rates=package.allowed_rates,
        allowed_scales=package.allowed_scales,
        response_semantics=package.semantics,
        step=package.fit_data.step,
    )
    validate_response_fit_contract(package.fit_data, package.semantics)
    if package.semantics.memory_rate_policy == "strict_increasing_unique":
        expected_rates = tuple(value / 10 for value in range(1, 10))
        if package.allowed_rates != expected_rates or package.allowed_scales != (1.0,):
            raise ComparisonContractError(
                "W11 strict program domain requires rates 0.1..0.9 and scale 1.0"
            )


def _run_gp(package: DevelopmentPackage, seed: int) -> ArmResult:
    started = perf_counter_ns()
    search = run_response_gp(
        scope=package.scope,
        fit_data=package.fit_data,
        allowed_rates=package.allowed_rates,
        allowed_scales=package.allowed_scales,
        seed=seed,
        generations=package.budget.generations,
        population_size=package.budget.population_size,
        max_evaluations=package.budget.max_evaluations,
        max_attempts=package.budget.max_attempts,
        response_semantics=package.semantics,
    )
    return _arm_result("response_gp", seed, search, perf_counter_ns() - started)


def _run_simple(package: DevelopmentPackage, seed: int) -> ArmResult:
    started = perf_counter_ns()
    programs = _program_universe(package)
    Random(seed).shuffle(programs)
    trace: list[Candidate] = []
    seen: set[ResponseProgram] = set()
    attempts = evaluations = 0
    for program in programs:
        if attempts >= package.budget.max_attempts or evaluations >= package.budget.max_evaluations:
            break
        candidate_id = f"s0-{attempts:02d}"
        attempts += 1
        if program in seen:
            trace.append(Candidate(
                candidate_id, 0, program, (), "simple_seeded_proposal", None,
                "rejected", "duplicate_program",
            ))
            continue
        seen.add(program)
        try:
            fit = fit_response_program(program, package.fit_data, package.semantics)
        except (OverflowError, ValueError) as exc:
            trace.append(Candidate(
                candidate_id, 0, program, (), "simple_seeded_proposal", None,
                "rejected", f"numeric_invalid:{exc}",
            ))
            continue
        evaluations += 1
        trace.append(Candidate(
            candidate_id, 0, program, (), "simple_seeded_proposal", fit.score_loss,
            "eligible", "finite_development_loss", fit,
        ))
    finite = sorted(
        (row for row in trace if row.status == "eligible"),
        key=lambda row: (row.loss, row.candidate_id),
    )
    selected_id = finite[0].candidate_id if finite else None
    trace = [
        replace(row, status="kept", reason="selected_simple_best")
        if row.candidate_id == selected_id
        else replace(row, status="rejected", reason="not_selected")
        if row.status == "eligible"
        else row
        for row in trace
    ]
    stop_reason = (
        "no_fittable_candidate" if selected_id is None
        else "evaluation_budget_exhausted" if evaluations >= package.budget.max_evaluations
        else "attempt_budget_exhausted" if attempts >= package.budget.max_attempts
        else "program_universe_exhausted"
    )
    search = SearchResult(
        seed,
        package.scope.derivation_ref,
        package.scope.distinguishing_predictions,
        package.scope.current_gap,
        tuple(trace),
        selected_id,
        evaluations,
        attempts,
        stop_reason,
    )
    return _arm_result(
        "simple_seeded_nonadaptive", seed, search, perf_counter_ns() - started
    )


def _program_universe(package: DevelopmentPackage) -> list[ResponseProgram]:
    terms = [KernelTerm(scale, rate) for scale in package.allowed_scales for rate in package.allowed_rates]
    strict = package.semantics.memory_rate_policy == "strict_increasing_unique"
    programs = [ResponseProgram(())] if strict else []
    programs.extend(ResponseProgram((term,)) for term in terms)
    allow_two = (
        "linear superposition" in package.scope.allowed_transformations
        and "two_scale_superposition" in package.scope.allowed_response_families
        and "structure_search" in package.scope.allowed_research_actions
    )
    if allow_two:
        if strict:
            programs.extend(
                ResponseProgram((first, second))
                for first_index, first in enumerate(terms)
                for second in terms[first_index + 1:]
            )
        else:
            programs.extend(
                ResponseProgram((first, second))
                for first in terms
                for second in terms
            )
    return list(dict.fromkeys(programs))


def _arm_result(proposer: str, seed: int, search: SearchResult, elapsed_ns: int) -> ArmResult:
    duplicates = sum(row.reason == "duplicate_program" for row in search.trace)
    failures = sum(row.reason.startswith("numeric_invalid:") for row in search.trace)
    actual_fit_calls = sum(
        row.program is not None and row.reason != "duplicate_program"
        for row in search.trace
    )
    return ArmResult(
        proposer,
        seed,
        search,
        elapsed_ns,
        actual_fit_calls,
        search.attempt_count,
        duplicates,
        failures,
    )


def comparison_as_dict(value: DevelopmentComparison | ConfirmationScore) -> dict[str, Any]:
    return asdict(value)


def _verify_binding(base: Path, value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ComparisonContractError(f"{label} binding requires path and SHA256")
    path = (base / value["path"]).resolve()
    declared = value.get("sha256")
    if not path.is_file() or not isinstance(declared, str):
        raise ComparisonContractError(f"{label} binding is missing")
    actual = sha256(path.read_bytes()).hexdigest()
    if declared != actual:
        raise ComparisonContractError(f"{label} binding is stale")
    return {"path": str(path), "sha256": actual}


def _find_forbidden_keys(value: Any) -> list[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_PUBLIC_KEYS:
                found.add(key)
            found.update(_find_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_forbidden_keys(item))
    return sorted(found)


def _coefficients_match(
    left: tuple[tuple[str, float], ...], right: tuple[tuple[str, float], ...]
) -> bool:
    if tuple(name for name, _ in left) != tuple(name for name, _ in right):
        return False
    return all(
        abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))
        for (_, a), (_, b) in zip(left, right)
    )
