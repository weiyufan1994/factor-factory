"""Bounded GP selection over preregistered, fully materialized programs.

This adapter is for research objects that do not fit the transient-response
grammar in :mod:`gp_adapter`.  It deliberately does not invent expressions at
runtime: mutation and crossover must be materialized, reviewed, and budgeted
before this function is called.  The evaluator owns the actual development
experiment and must bind its evidence to the canonical program hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from random import Random
from typing import Callable, Literal


Direction = Literal[-1, 1]


@dataclass(frozen=True)
class RegisteredProgram:
    program_id: str
    expression: str
    mathematical_object: str
    generation: int
    parents: tuple[str, ...]
    operation: str
    complexity: int
    estimated_cost: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.program_id or not self.expression or not self.mathematical_object:
            raise ValueError("program id, expression, and mathematical object are required")
        if self.generation < 0 or self.complexity < 1:
            raise ValueError("generation must be non-negative and complexity positive")
        if not self.operation or not self.evidence_refs:
            raise ValueError("operation and evidence refs are required")
        if not isfinite(self.estimated_cost) or self.estimated_cost < 0:
            raise ValueError("estimated cost must be finite and non-negative")

    @property
    def program_hash(self) -> str:
        payload = {
            "expression": self.expression,
            "mathematical_object": self.mathematical_object,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProgramEvaluation:
    program_hash: str
    split: str
    metric: str
    direction: Direction
    score: float | None
    actual_cost: float | None
    status: str
    evidence_ref: str | None


@dataclass(frozen=True)
class ProgramTrace:
    program_id: str
    program_hash: str
    generation: int
    parents: tuple[str, ...]
    operation: str
    evaluator_seed: int | None
    status: str
    reason: str
    score: float | None
    actual_cost: float | None
    evidence_ref: str | None


@dataclass(frozen=True)
class RegisteredGPSearchResult:
    seed: int
    metric: str
    direction: Direction
    trace: tuple[ProgramTrace, ...]
    selected_id: str | None
    attempted_count: int
    evaluator_calls: int
    spent_cost: float
    stop_reason: str


ProgramEvaluator = Callable[[RegisteredProgram, int], ProgramEvaluation]


def run_registered_program_gp(
    *,
    programs: tuple[RegisteredProgram, ...],
    evaluator: ProgramEvaluator,
    metric: str,
    direction: Direction,
    seed: int,
    total_budget: float,
    max_evaluations: int,
) -> RegisteredGPSearchResult:
    """Evaluate a finite reviewed GP population under one hard budget.

    Programs are visited generation by generation.  Seeded order only breaks
    order within a generation.  Cost is reserved before every callback; an
    exception has unknown cost and stops without retry.  Only completed
    development evidence with a matching program hash can become an elite.
    """
    if not metric or direction not in (-1, 1):
        raise ValueError("metric and direction (+1 or -1) are required")
    if not isfinite(total_budget) or total_budget < 0 or max_evaluations < 1:
        raise ValueError("budget must be finite/non-negative and evaluations positive")
    _validate_registry(programs)
    rng = Random(seed)
    ordered: list[RegisteredProgram] = []
    for generation in sorted({row.generation for row in programs}):
        rows = [row for row in programs if row.generation == generation]
        rng.shuffle(rows)
        ordered.extend(rows)

    trace: list[ProgramTrace] = []
    spent = 0.0
    calls = 0
    stop_reason = "completed"
    for program in ordered:
        if calls >= max_evaluations:
            stop_reason = "evaluation_budget_exhausted"
            break
        if spent + program.estimated_cost > total_budget:
            trace.append(_trace(program, None, "rejected", "insufficient_reserved_budget"))
            continue
        evaluator_seed = rng.randrange(0, 2**63)
        calls += 1
        try:
            result = evaluator(program, evaluator_seed)
        except Exception as exc:  # evaluator boundary: retain type, never retry
            trace.append(_trace(
                program, evaluator_seed, "evaluator_exception",
                f"{type(exc).__name__}: {exc}",
            ))
            stop_reason = "evaluator_exception_unknown_cost"
            break
        try:
            _validate_evaluation(program, result, metric, direction)
        except ValueError as exc:
            trace.append(_trace(
                program, evaluator_seed, "evaluator_contract_violation", str(exc),
                score=result.score, actual_cost=result.actual_cost,
                evidence_ref=result.evidence_ref,
            ))
            stop_reason = "evaluator_contract_violation"
            break
        assert result.actual_cost is not None
        spent += result.actual_cost
        eligible = result.status == "completed" and result.score is not None
        trace.append(_trace(
            program, evaluator_seed,
            "eligible" if eligible else result.status,
            "completed_development_evidence" if eligible else "no_eligible_reward",
            score=result.score, actual_cost=result.actual_cost,
            evidence_ref=result.evidence_ref,
        ))

    eligible_rows = [row for row in trace if row.status == "eligible"]
    selected_id = None
    if eligible_rows:
        by_id = {row.program_id: row for row in programs}
        selected_id = sorted(
            eligible_rows,
            key=lambda row: (
                -direction * float(row.score),
                by_id[row.program_id].complexity,
                row.program_hash,
            ),
        )[0].program_id
    if len(programs) == 1 and stop_reason == "completed":
        stop_reason = (
            "no_search_degree:single_registered_program"
            if eligible_rows
            else "no_eligible_development_evidence:single_registered_program"
        )
    elif not eligible_rows and stop_reason == "completed":
        stop_reason = "no_eligible_development_evidence"
    return RegisteredGPSearchResult(
        seed, metric, direction, tuple(trace), selected_id, len(trace), calls,
        spent, stop_reason,
    )


def _validate_registry(programs: tuple[RegisteredProgram, ...]) -> None:
    if not programs:
        raise ValueError("at least one preregistered program is required")
    ids: dict[str, RegisteredProgram] = {}
    hashes: set[str] = set()
    for row in programs:
        if row.program_id in ids:
            raise ValueError(f"duplicate program id: {row.program_id}")
        if row.program_hash in hashes:
            raise ValueError(f"duplicate program hash: {row.program_hash}")
        ids[row.program_id] = row
        hashes.add(row.program_hash)
    for row in programs:
        for parent_id in row.parents:
            parent = ids.get(parent_id)
            if parent is None:
                raise ValueError(f"unknown parent: {parent_id}")
            if parent.generation >= row.generation:
                raise ValueError("parents must belong to an earlier generation")
        if row.generation > 0 and not row.parents:
            raise ValueError("later-generation programs require explicit parents")


def _validate_evaluation(
    program: RegisteredProgram,
    result: ProgramEvaluation,
    metric: str,
    direction: Direction,
) -> None:
    if result.program_hash != program.program_hash:
        raise ValueError("program_hash_mismatch")
    if result.split != "development":
        raise ValueError("development_split_required")
    if result.metric != metric or result.direction != direction:
        raise ValueError("metric_contract_mismatch")
    if result.actual_cost is None:
        raise ValueError("actual_cost_unknown")
    if not isfinite(result.actual_cost) or result.actual_cost < 0:
        raise ValueError("actual_cost_invalid")
    if result.actual_cost > program.estimated_cost:
        raise ValueError("actual_cost_exceeds_reservation")
    if result.score is not None and not isfinite(result.score):
        raise ValueError("score_invalid")
    if result.status == "completed":
        if result.score is None or not result.evidence_ref:
            raise ValueError("completed_evidence_incomplete")
    elif result.score is not None:
        raise ValueError("noncompleted_result_cannot_reward")


def _trace(
    program: RegisteredProgram,
    evaluator_seed: int | None,
    status: str,
    reason: str,
    *,
    score: float | None = None,
    actual_cost: float | None = None,
    evidence_ref: str | None = None,
) -> ProgramTrace:
    return ProgramTrace(
        program.program_id, program.program_hash, program.generation,
        program.parents, program.operation, evaluator_seed, status, reason,
        score, actual_cost, evidence_ref,
    )
