"""Typed GP for a reviewed finite threshold-response grammar.

The grammar represents ``D * h(c)`` where ``h`` is the CDF of one of three
reviewed threshold families.  Mutation changes the threshold-family gene and
materializes both the signal expression and its matching price-alias control.
The grammar is intentionally not closed under crossover, so crossover is
disabled and reported as such instead of creating an unreviewed Beta family.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Literal

from .registered_program_search import (
    ProgramEvaluator,
    RegisteredProgramSearchResult,
    RegisteredProgram,
    run_registered_program_search,
)


ThresholdFamily = Literal["uniform", "beta_early", "beta_late"]
_FAMILIES: tuple[ThresholdFamily, ...] = (
    "uniform", "beta_early", "beta_late",
)
_EXPRESSIONS = {
    "uniform": ("D*c", "D*a", 5),
    "beta_early": ("D*(2*c-c*c)", "D*(2*a-a*a)", 8),
    "beta_late": ("D*c*c", "D*a*a", 6),
}
_ADJACENCY = {
    "uniform": ("beta_early", "beta_late"),
    "beta_early": ("uniform",),
    "beta_late": ("uniform",),
}


@dataclass(frozen=True)
class MutationRecord:
    attempt: int
    parent_family: ThresholdFamily
    child_family: ThresholdFamily
    parent_program_hash: str
    child_program_hash: str | None
    status: str
    reason: str


@dataclass(frozen=True)
class ThresholdGPSearchResult:
    seed: int
    programs: tuple[RegisteredProgram, ...]
    mutations: tuple[MutationRecord, ...]
    mutation_attempts: int
    materialized_mutations: int
    duplicate_mutations: int
    crossover_attempts: int
    crossover_reason: str
    search: RegisteredProgramSearchResult


def materialize_threshold_program(
    family: ThresholdFamily,
    *,
    generation: int,
    parents: tuple[str, ...],
    evidence_ref: str,
) -> RegisteredProgram:
    """Materialize one complete signal/alias pair from a typed gene."""
    if family not in _FAMILIES:
        raise ValueError(f"unreviewed threshold family: {family}")
    expression, alias, complexity = _EXPRESSIONS[family]
    return RegisteredProgram(
        program_id=f"amihud_threshold__{family}",
        expression=expression,
        mathematical_object=(
            f"threshold_family={family}; signal_h={expression}; "
            f"exact_price_alias_h={alias}"
        ),
        generation=generation,
        parents=parents,
        operation="initialize_threshold_gene" if generation == 0 else "mutate_threshold_family",
        complexity=complexity,
        estimated_cost=1.0,
        evidence_refs=(evidence_ref,),
    )


def run_threshold_family_gp(
    *,
    initial_family: ThresholdFamily,
    allowed_families: tuple[ThresholdFamily, ...],
    evaluator: ProgramEvaluator,
    evidence_ref: str,
    metric: str,
    direction: Literal[-1, 1],
    seed: int,
    total_budget: float,
    max_evaluations: int,
    max_mutations: int = 2,
) -> ThresholdGPSearchResult:
    """Run one bounded generation of typed mutation plus common evaluation.

    The function creates candidates at runtime.  It never accepts arbitrary
    expressions or coefficients.  A program already materialized by another
    mutation is retained as a duplicate trace and is not evaluated twice.
    """
    if initial_family not in allowed_families:
        raise ValueError("initial family must be allowed")
    if not allowed_families or len(set(allowed_families)) != len(allowed_families):
        raise ValueError("allowed families must be nonempty and unique")
    if any(family not in _FAMILIES for family in allowed_families):
        raise ValueError("allowed families contain an unreviewed value")
    if max_mutations < 0:
        raise ValueError("max_mutations must be non-negative")

    parent = materialize_threshold_program(
        initial_family, generation=0, parents=(), evidence_ref=evidence_ref,
    )
    programs = [parent]
    seen = {parent.program_hash}
    rng = Random(seed)
    targets = [
        family for family in _ADJACENCY[initial_family]
        if family in allowed_families
    ]
    rng.shuffle(targets)
    records: list[MutationRecord] = []
    for attempt, child_family in enumerate(targets[:max_mutations], start=1):
        child = materialize_threshold_program(
            child_family,
            generation=1,
            parents=(parent.program_id,),
            evidence_ref=evidence_ref,
        )
        if child.program_hash in seen:
            records.append(MutationRecord(
                attempt, initial_family, child_family, parent.program_hash,
                child.program_hash, "duplicate", "program_hash_already_registered",
            ))
            continue
        seen.add(child.program_hash)
        programs.append(child)
        records.append(MutationRecord(
            attempt, initial_family, child_family, parent.program_hash,
            child.program_hash, "materialized", "reviewed_typed_mutation",
        ))

    search = run_registered_program_search(
        programs=tuple(programs), evaluator=evaluator, metric=metric,
        direction=direction, seed=seed, total_budget=total_budget,
        max_evaluations=max_evaluations,
    )
    return ThresholdGPSearchResult(
        seed=seed,
        programs=tuple(programs),
        mutations=tuple(records),
        mutation_attempts=len(records),
        materialized_mutations=sum(row.status == "materialized" for row in records),
        duplicate_mutations=sum(row.status == "duplicate" for row in records),
        crossover_attempts=0,
        crossover_reason=(
            "grammar_not_closed: crossing beta_early and beta_late can create "
            "an unreviewed threshold family"
        ),
        search=search,
    )
