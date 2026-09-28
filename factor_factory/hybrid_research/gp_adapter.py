"""Mechanism-constrained program evolution for bounded causal responses."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from random import Random

import numpy as np

from .response import (
    ResponseSemantics,
    initial_state_column,
    recursive_transient_response,
    response_column,
    retention_from_parameter,
)
from .synthetic import FitData
from .variation import DerivationScope


@dataclass(frozen=True, order=True)
class KernelTerm:
    scale: float
    decay_rate: float


@dataclass(frozen=True)
class ResponseProgram:
    terms: tuple[KernelTerm, ...]

    def __post_init__(self) -> None:
        if not 0 <= len(self.terms) <= 2:
            raise ValueError("program requires zero, one, or two memory kernels")

    @property
    def structure(self) -> str:
        if not self.terms:
            return "zero_memory"
        return "single_kernel" if len(self.terms) == 1 else "linear_superposition"


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    generation: int
    program: ResponseProgram | None
    parents: tuple[str, ...]
    operation: str
    loss: float | None
    status: str
    reason: str
    fit: "ProgramFit | None" = None


@dataclass(frozen=True)
class ProgramFit:
    prediction: tuple[float, ...]
    coefficients: tuple[tuple[str, float], ...]
    training_indexes: tuple[int, ...]
    score_indexes: tuple[int, ...]
    training_loss: float
    score_loss: float
    design_rank: int
    design_columns: tuple[str, ...]
    unidentified_coefficients: tuple[str, ...]
    continuation_indexes: tuple[int, ...]
    continuation_semantics: str
    state_count: int
    linear_parameter_count: int


@dataclass(frozen=True)
class SearchResult:
    seed: int
    derivation_ref: str
    prediction_refs: tuple[str, ...]
    targeted_gap: str
    trace: tuple[Candidate, ...]
    selected_id: str | None
    evaluated_count: int
    attempt_count: int
    stop_reason: str

    @property
    def selected(self) -> Candidate | None:
        return next((row for row in self.trace if row.candidate_id == self.selected_id), None)


def evaluate_program(program: ResponseProgram, data: FitData) -> tuple[float, ...]:
    columns: list[tuple[float, ...]] = []
    for term in program.terms:
        if not isfinite(term.scale):
            raise ValueError("kernel scale must be finite")
        base = recursive_transient_response(
            data.signed_impulses, decay_rate=term.decay_rate, step=data.step
        )
        try:
            column = tuple(term.scale * value for value in base)
        except OverflowError as exc:
            raise ValueError("candidate output overflow") from exc
        columns.append(column)
    try:
        output = tuple(sum(column[index] for column in columns) for index in range(len(data.signed_impulses)))
    except OverflowError as exc:
        raise ValueError("candidate output overflow") from exc
    if any(not isfinite(value) for value in output):
        raise ValueError("candidate output must be finite")
    return output


def fit_response_program(
    program: ResponseProgram,
    data: FitData,
    semantics: ResponseSemantics,
) -> ProgramFit:
    """Profile declared linear coefficients using training observations only."""
    size = len(data.observed_response)
    training, score = validate_response_fit_contract(data, semantics)
    _validate_representable(program, data, semantics)

    bases = [
        response_column(
            data.signed_impulses,
            rate=term.decay_rate,
            step=data.step,
            semantics=semantics,
        )
        for term in program.terms
    ]
    fixed = np.zeros(size, dtype=float)
    columns: list[np.ndarray] = []
    names: list[str] = []
    constrained: set[int] = set()
    if semantics.gain_mode == "evolved_component":
        for term, base in zip(program.terms, bases):
            if not isfinite(term.scale):
                raise ValueError("kernel scale must be finite")
            fixed += term.scale * np.asarray(base, dtype=float)
    elif semantics.gain_mode == "profiled_shared":
        columns.append(sum(
            (term.scale * np.asarray(base, dtype=float) for term, base in zip(program.terms, bases)),
            np.zeros(size, dtype=float),
        ))
        names.append("shared_gain")
        if semantics.gain_constraint == "nonnegative":
            constrained.add(0)
    else:
        for index, base in enumerate(bases):
            columns.append(np.asarray(base, dtype=float))
            names.append(f"component_gain_{index}")
            if semantics.gain_constraint == "nonnegative":
                constrained.add(len(columns) - 1)

    if semantics.intercept == "profiled":
        columns.append(np.ones(size, dtype=float))
        names.append("intercept")
    if semantics.direct_input == "profiled_same_event":
        columns.append(np.asarray(tuple(
            data.signed_impulses[index] if index >= semantics.input_start_index else 0.0
            for index in range(size)
        ), dtype=float))
        names.append("direct_input")
    if semantics.initial_state == "profiled_component":
        for index, term in enumerate(program.terms):
            retention = retention_from_parameter(
                term.decay_rate,
                parameterization=semantics.rate_parameterization,
                step=data.step,
            )
            if retention == 0.0 and semantics.initial_power_offset > 0:
                continue
            if (
                retention == 1.0
                and semantics.intercept == "profiled"
                and semantics.initial_state_start_index == 0
            ):
                continue
            columns.append(np.asarray(initial_state_column(
                size, rate=term.decay_rate, step=data.step, semantics=semantics
            ), dtype=float))
            names.append(f"initial_state_{index}")

    actual = np.asarray(data.observed_response, dtype=float)
    train_rows = np.asarray(training, dtype=int)
    if columns:
        design = np.column_stack(columns)
        coefficients, _active_rank = _profile_coefficients(
            design[train_rows], actual[train_rows] - fixed[train_rows], constrained
        )
        prediction = fixed + design @ coefficients
    else:
        design = np.empty((size, 0), dtype=float)
        coefficients = np.empty(0, dtype=float)
        prediction = fixed
    if not np.all(np.isfinite(prediction)):
        raise ValueError("candidate output must be finite")
    training_loss = _indexed_mse(actual, prediction, training)
    score_loss = _indexed_mse(actual, prediction, score)
    training_design = design[train_rows]
    rank = (
        int(np.linalg.matrix_rank(training_design))
        if training_design.shape[1]
        else 0
    )
    unidentified = _structurally_unidentified(names, training_design, rank)
    continuation = tuple(index for index in range(max(training) + 1, size))
    return ProgramFit(
        tuple(float(value) for value in prediction),
        tuple((name, float(value)) for name, value in zip(names, coefficients)),
        training,
        score,
        training_loss,
        score_loss,
        rank,
        tuple(names),
        unidentified,
        continuation,
        "coefficients frozen after training; continuation advances state with declared inputs and never refits on continuation observations",
        len(program.terms),
        len(names),
    )


def run_response_gp(
    *,
    scope: DerivationScope,
    fit_data: FitData,
    allowed_rates: tuple[float, ...],
    allowed_scales: tuple[float, ...],
    seed: int,
    generations: int = 2,
    population_size: int = 6,
    max_evaluations: int = 16,
    max_attempts: int = 32,
    response_semantics: ResponseSemantics | None = None,
) -> SearchResult:
    """Run a bounded program search.

    ``max_attempts`` is a conservative total-generation limit, including valid
    and invalid programs. ``max_evaluations`` separately caps finite candidates.
    Hidden synthetic truth is absent from this interface.
    """
    if generations < 1 or population_size < 3 or max_evaluations < 1 or max_attempts < 1:
        raise ValueError("invalid search budget")
    rates, scales = validate_response_search_contract(
        scope=scope,
        allowed_rates=allowed_rates,
        allowed_scales=allowed_scales,
        response_semantics=response_semantics,
        step=fit_data.step,
    )
    rng = Random(seed)
    strict_memory_domain = (
        response_semantics is not None
        and response_semantics.memory_rate_policy == "strict_increasing_unique"
    )
    trace: list[Candidate] = []
    seen: set[ResponseProgram] = set()
    evaluated = attempts = 0
    stop_reason = "completed"

    def propose(
        program: ResponseProgram | None,
        generation: int,
        parents: tuple[str, ...],
        operation: str,
    ) -> Candidate | None:
        nonlocal attempts, evaluated, stop_reason
        if attempts >= max_attempts:
            stop_reason = "attempt_budget_exhausted"
            return None
        if program is not None and evaluated >= max_evaluations:
            stop_reason = "evaluation_budget_exhausted"
            return None
        candidate_id = f"g{generation}-{attempts:02d}"
        attempts += 1
        if program is None:
            return Candidate(candidate_id, generation, None, parents, operation, None, "rejected", "grammar_disallowed")
        if program in seen:
            return Candidate(candidate_id, generation, program, parents, operation, None, "rejected", "duplicate_program")
        seen.add(program)
        try:
            fit = (
                fit_response_program(program, fit_data, response_semantics)
                if response_semantics is not None
                else None
            )
            prediction = fit.prediction if fit is not None else evaluate_program(program, fit_data)
            loss = fit.score_loss if fit is not None else sum(
                (actual - predicted) ** 2
                for actual, predicted in zip(fit_data.observed_response, prediction)
            ) / len(prediction)
            if not isfinite(loss):
                raise ValueError("loss must be finite")
        except (OverflowError, ValueError) as exc:
            return Candidate(candidate_id, generation, program, parents, operation, None, "rejected", f"numeric_invalid:{exc}")
        evaluated += 1
        return Candidate(
            candidate_id, generation, program, parents, operation, loss,
            "eligible", "finite_development_loss", fit,
        )

    if strict_memory_domain:
        zero_memory = ResponseProgram(())
        remaining = [
            ResponseProgram((KernelTerm(scale, rate),))
            for scale in scales
            for rate in rates
        ]
        rng.shuffle(remaining)
        initial_programs = [zero_memory, *remaining]
        sample_size = min(
            population_size, max_attempts, max_evaluations, len(initial_programs)
        )
        initial_programs = initial_programs[:sample_size]
    else:
        total_initial = len(scales) * len(rates)
        sample_size = min(
            population_size, max_attempts, max_evaluations, total_initial
        )
        order = rng.sample(range(total_initial), k=sample_size)
        initial_programs = []
        for encoded in order:
            scale_index, rate_index = divmod(encoded, len(rates))
            initial_programs.append(ResponseProgram((KernelTerm(
                scales[scale_index], rates[rate_index]
            ),)))
    for program in initial_programs:
        if len(trace) >= population_size or attempts >= max_attempts or evaluated >= max_evaluations:
            break
        row = propose(
            program,
            0,
            (),
            "initialize_structure",
        )
        if row is not None:
            trace.append(row)
    trace = _select_global_elites(trace, elite_limit=2)

    for generation in range(1, generations + 1):
        parents = sorted((row for row in trace if row.status == "kept"), key=lambda row: row.loss)
        if len(parents) < 2 or attempts >= max_attempts or evaluated >= max_evaluations:
            break
        proposals: list[tuple[ResponseProgram | None, tuple[str, ...], str]] = []
        for row in parents[:2]:
            terms = list(row.program.terms)
            if terms:
                index = rng.randrange(len(terms))
                terms[index] = KernelTerm(rng.choice(scales), rng.choice(rates))
                mutated = _normalized_program(tuple(terms), strict=strict_memory_domain)
            else:
                mutated = None
            proposals.append((mutated, (row.candidate_id,), "parameter_mutation"))
        allow_structure = (
            "linear superposition" in scope.allowed_transformations
            and "two_scale_superposition" in scope.allowed_response_families
            and "structure_search" in scope.allowed_research_actions
        )
        base = parents[0]
        if allow_structure and len(base.program.terms) < 2:
            # Bounded local structural neighborhood.  Programs are materialized
            # one at a time and generation stops before either budget is crossed.
            structural_limit = min(
                4,
                max_attempts - attempts - len(proposals),
                max_evaluations - evaluated - len(proposals),
            )
            added = 0
            for scale in scales:
                for rate in rates:
                    if added >= structural_limit:
                        break
                    proposals.append((
                        _normalized_program(
                            base.program.terms + (KernelTerm(scale, rate),),
                            strict=strict_memory_domain,
                        ),
                        (base.candidate_id,),
                        "structure_mutation_add",
                    ))
                    added += 1
                if added >= structural_limit:
                    break
        else:
            proposals.append((None, (base.candidate_id,), "structure_mutation_add"))
        if strict_memory_domain and allow_structure and base.program.terms:
            proposals.append((
                ResponseProgram(base.program.terms[:-1]),
                (base.candidate_id,),
                "structure_mutation_remove",
            ))
        if allow_structure:
            crossover_terms = tuple(
                term
                for term in (
                    parents[0].program.terms[0] if parents[0].program.terms else None,
                    parents[1].program.terms[-1] if parents[1].program.terms else None,
                )
                if term is not None
            )
            crossed = _normalized_program(
                crossover_terms, strict=strict_memory_domain
            ) if crossover_terms else (ResponseProgram(()) if strict_memory_domain else None)
        else:
            crossed = None
        proposals.append((crossed, tuple(row.candidate_id for row in parents[:2]), "structure_crossover"))
        for program, parent_ids, operation in proposals:
            if attempts >= max_attempts or (program is not None and evaluated >= max_evaluations):
                stop_reason = "attempt_budget_exhausted" if attempts >= max_attempts else "evaluation_budget_exhausted"
                break
            row = propose(program, generation, parent_ids, operation)
            if row is not None:
                trace.append(row)
        trace = _select_global_elites(trace, elite_limit=2)

    ranked = sorted((row for row in trace if row.status == "kept"), key=lambda row: row.loss)
    selected = ranked[0].candidate_id if ranked else None
    if evaluated >= max_evaluations:
        stop_reason = "evaluation_budget_exhausted"
    elif attempts >= max_attempts:
        stop_reason = "attempt_budget_exhausted"
    if selected is None and stop_reason == "completed":
        stop_reason = "no_fittable_candidate"
    return SearchResult(
        seed,
        scope.derivation_ref,
        scope.distinguishing_predictions,
        scope.current_gap,
        tuple(trace),
        selected,
        evaluated,
        attempts,
        stop_reason,
    )


def validate_response_search_contract(
    *,
    scope: DerivationScope,
    allowed_rates: tuple[float, ...],
    allowed_scales: tuple[float, ...],
    response_semantics: ResponseSemantics | None,
    step: float = 1.0,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Validate the common grammar/domain contract before any proposer runs."""
    _validate_scope(scope, response_semantics)
    rates = _domain(allowed_rates, "rate", nonnegative=True)
    scales = _domain(allowed_scales, "scale")
    parameterization = (
        response_semantics.rate_parameterization
        if response_semantics is not None
        else "continuous_decay"
    )
    for rate in rates:
        retention_from_parameter(rate, parameterization=parameterization, step=step)
    if (
        response_semantics is not None
        and response_semantics.gain_mode == "profiled_component"
        and scales != (1.0,)
    ):
        raise ValueError(
            "profiled_component gains require allowed_scales=(1.0,); component scales are fitted"
        )
    permanent_rate_present = (
        (response_semantics is None or response_semantics.rate_parameterization == "continuous_decay")
        and 0.0 in rates
    ) or (
        response_semantics is not None
        and response_semantics.rate_parameterization == "retention"
        and 1.0 in rates
    )
    if permanent_rate_present and "permanent_component" not in scope.allowed_response_families:
        raise ValueError("permanent response requires an explicitly allowed permanent component")
    if response_semantics is not None:
        if (
            response_semantics.direct_input == "profiled_same_event"
            and "direct_input_component" not in scope.allowed_response_families
        ):
            raise ValueError("profiled direct input requires direct_input_component authorization")
        if response_semantics.memory_rate_policy == "strict_increasing_unique":
            required = (
                response_semantics.pre_sample_input == "zero"
                and response_semantics.initial_state == "zero"
                and response_semantics.intercept == "profiled"
                and response_semantics.direct_input == "profiled_same_event"
                and response_semantics.gain_mode == "profiled_component"
                and response_semantics.gain_constraint == "unrestricted"
            )
            if not required:
                raise ValueError(
                    "strict K0/K1/K2 domain requires zero history/state and profiled b/d/component gains"
                )
            if any(not 0.0 < rate < 1.0 for rate in rates):
                raise ValueError("strict memory retention rates must lie in (0, 1)")
            if "zero_memory_component" not in scope.allowed_response_families:
                raise ValueError("strict K0/K1/K2 domain requires zero_memory_component authorization")
    return rates, scales


def validate_response_fit_contract(
    data: FitData, semantics: ResponseSemantics
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Resolve and validate observation windows before any candidate is proposed."""
    size = len(data.observed_response)
    training = semantics.training_indexes or tuple(range(size))
    score = semantics.score_indexes or training
    _validate_indexes(training, size, "training_indexes")
    _validate_indexes(score, size, "score_indexes")
    if not set(score).issubset(training):
        raise ValueError("score_indexes must be a subset of training_indexes")
    if any(index < semantics.input_start_index for index in training):
        raise ValueError("training_indexes precede input_start_index")
    if semantics.input_start_index >= size:
        raise ValueError("input_start_index must be inside the observed series")
    if (
        semantics.initial_state == "profiled_component"
        and semantics.initial_state_start_index >= size
    ):
        raise ValueError("initial_state_start_index must be inside the observed series")
    return training, score


def _normalized_program(
    terms: tuple[KernelTerm, ...], *, strict: bool
) -> ResponseProgram | None:
    if not strict:
        return ResponseProgram(terms)
    ordered = tuple(sorted(terms, key=lambda term: term.decay_rate))
    if len({term.decay_rate for term in ordered}) != len(ordered):
        return None
    return ResponseProgram(ordered)


def _select_global_elites(trace: list[Candidate], *, elite_limit: int) -> list[Candidate]:
    pool = sorted(
        (row for row in trace if row.status in {"eligible", "kept"} and row.loss is not None),
        key=lambda row: (row.loss, row.candidate_id),
    )
    keep = {row.candidate_id for row in pool[:elite_limit]}
    selected: list[Candidate] = []
    for row in trace:
        if row.status not in {"eligible", "kept"}:
            selected.append(row)
        elif row.candidate_id in keep:
            selected.append(replace(row, status="kept", reason="selected_global_elite"))
        else:
            reason = "displaced_by_better_candidate" if row.status == "kept" else "not_selected"
            selected.append(replace(row, status="rejected", reason=reason))
    return selected


def _validate_scope(
    scope: DerivationScope, semantics: ResponseSemantics | None = None
) -> None:
    required = {
        "mathematical_object": "causal kernels",
        "domain": "finite signed impulses",
        "clock": "event",
        "missing_value_policy": "missing is not zero",
        "observation_map": "signed J to y",
    }
    for field, expected in required.items():
        if getattr(scope, field) != expected:
            raise ValueError(f"unsupported derivation scope: {field}")
    expected_initial = "zero" if semantics is None else semantics.initial_state
    if scope.initial_state != expected_initial:
        raise ValueError(
            f"unsupported derivation scope: initial_state must be {expected_initial!r}"
        )
    if "causal convolution" not in scope.allowed_transformations:
        raise ValueError("causal convolution not allowed")
    if "transient_exponential_kernel" not in scope.allowed_response_families:
        raise ValueError("transient exponential kernel family not authorized by the derivation")
    if "parameter_search" not in scope.allowed_research_actions:
        raise ValueError("parameter search action not authorized by the derivation")
    if not scope.distinguishing_predictions or not scope.current_gap.strip():
        raise ValueError("prediction references and current gap are required")


def _domain(values: tuple[float, ...], label: str, nonnegative: bool = False) -> tuple[float, ...]:
    if not values or any(not isfinite(value) for value in values):
        raise ValueError(f"invalid {label} domain")
    if nonnegative and any(value < 0 for value in values):
        raise ValueError(f"invalid {label} domain")
    return tuple(dict.fromkeys(values))


def _validate_indexes(indexes: tuple[int, ...], size: int, label: str) -> None:
    if not indexes:
        raise ValueError(f"{label} cannot be empty after resolution")
    if any(index < 0 or index >= size for index in indexes):
        raise ValueError(f"{label} contains an out-of-range index")


def _validate_representable(
    program: ResponseProgram, data: FitData, semantics: ResponseSemantics
) -> None:
    if semantics.memory_rate_policy == "strict_increasing_unique":
        rates = tuple(term.decay_rate for term in program.terms)
        if rates != tuple(sorted(set(rates))):
            raise ValueError("memory rates must be strictly increasing and unique")
        if any(not 0.0 < rate < 1.0 for rate in rates):
            raise ValueError("strict memory retention rates must lie in (0, 1)")
        if not program.terms and (
            semantics.direct_input != "profiled_same_event"
            or semantics.intercept != "profiled"
        ):
            raise ValueError("K0 requires profiled intercept and profiled same-event direct input")
    elif not program.terms:
        raise ValueError("zero-memory program requires the explicit strict K0/K1/K2 domain")
    if semantics.input_start_index >= len(data.signed_impulses):
        raise ValueError("input_start_index must be inside the observed series")
    if (
        semantics.initial_state == "profiled_component"
        and semantics.initial_state_start_index >= len(data.signed_impulses)
    ):
        raise ValueError("initial_state_start_index must be inside the observed series")
    if semantics.pre_sample_input == "unknown":
        for term in program.terms:
            retention = retention_from_parameter(
                term.decay_rate,
                parameterization=semantics.rate_parameterization,
                step=data.step,
            )
            needs_initial_state = (
                retention != 0.0
                or (
                    semantics.observation_timing == "lag_one"
                    and semantics.input_start_index == 0
                )
            )
            if needs_initial_state and semantics.initial_state != "profiled_component":
                raise ValueError(
                    "missing semantics: unknown pre-sample input requires profiled_component initial_state"
                )
            if (
                semantics.observation_timing == "lag_one"
                and retention == 0.0
                and (
                    semantics.initial_state_start_index != 0
                    or semantics.initial_power_offset != 0
                )
            ):
                raise ValueError(
                    "unrepresentable semantics: lag_one with unknown pre-sample input and retention=0"
                )


def _profile_coefficients(
    design: np.ndarray, target: np.ndarray, constrained: set[int]
) -> tuple[np.ndarray, int]:
    """Solve LS; enumerate active sets for the at-most-two constrained gains."""
    if not constrained:
        coefficients, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
        return coefficients, int(rank)
    constrained_order = tuple(sorted(constrained))
    best: tuple[float, np.ndarray, int] | None = None
    for mask in range(1 << len(constrained_order)):
        inactive = {
            constrained_order[position]
            for position in range(len(constrained_order))
            if not (mask & (1 << position))
        }
        active = [index for index in range(design.shape[1]) if index not in inactive]
        coefficients = np.zeros(design.shape[1], dtype=float)
        if active:
            fitted, _, rank, _ = np.linalg.lstsq(design[:, active], target, rcond=None)
            coefficients[active] = fitted
        else:
            rank = 0
        if any(coefficients[index] < -1e-12 for index in constrained):
            continue
        coefficients[list(constrained)] = np.maximum(coefficients[list(constrained)], 0.0)
        residual = target - design @ coefficients
        loss = float(residual @ residual)
        if best is None or loss < best[0]:
            best = (loss, coefficients, int(rank))
    if best is None:
        raise ValueError("nonnegative gain fit has no feasible active set")
    return best[1], best[2]


def _indexed_mse(actual: np.ndarray, predicted: np.ndarray, indexes: tuple[int, ...]) -> float:
    rows = np.asarray(indexes, dtype=int)
    residual = actual[rows] - predicted[rows]
    value = float(np.mean(residual * residual))
    if not isfinite(value):
        raise ValueError("loss must be finite")
    return value


def _structurally_unidentified(
    names: list[str], design: np.ndarray, rank: int
) -> tuple[str, ...]:
    if design.shape[1] == 0 or rank == design.shape[1]:
        return ()
    _, _, right_vectors = np.linalg.svd(design, full_matrices=True)
    tolerance = max(design.shape) * np.finfo(float).eps
    null_vectors = right_vectors[rank:]
    return tuple(
        names[index]
        for index in range(design.shape[1])
        if float(null_vectors[:, index] @ null_vectors[:, index]) > tolerance
    )
