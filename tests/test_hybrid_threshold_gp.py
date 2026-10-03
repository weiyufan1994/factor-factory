from __future__ import annotations

import pytest

from factor_factory.hybrid_research.registered_program_search import ProgramEvaluation
from factor_factory.hybrid_research.threshold_gp import (
    materialize_threshold_program,
    run_threshold_family_gp,
)


def evaluator(scores):
    calls = []
    def run(program, seed):
        calls.append((program.program_id, program.program_hash, seed))
        return ProgramEvaluation(
            program.program_hash, "development", "loss", -1,
            scores[program.program_id], 1.0, "completed",
            f"evidence:{program.program_hash}",
        )
    return run, calls


def test_runtime_mutation_materializes_two_distinct_reviewed_programs():
    evaluate, calls = evaluator({
        "amihud_threshold__uniform": .4,
        "amihud_threshold__beta_early": .2,
        "amihud_threshold__beta_late": .3,
    })
    result = run_threshold_family_gp(
        initial_family="uniform",
        allowed_families=("uniform", "beta_early", "beta_late"),
        evaluator=evaluate, evidence_ref="step2:threshold-family",
        metric="loss", direction=-1, seed=20261003, total_budget=3,
        max_evaluations=3,
    )
    assert result.mutation_attempts == result.materialized_mutations == 2
    assert result.duplicate_mutations == 0
    assert {row.child_family for row in result.mutations} == {"beta_early", "beta_late"}
    assert len({row.program_hash for row in result.programs}) == 3
    assert len(calls) == 3
    assert result.search.selected_id == "amihud_threshold__beta_early"


def test_signal_and_alias_are_materialized_together():
    early = materialize_threshold_program(
        "beta_early", generation=1,
        parents=("amihud_threshold__uniform",), evidence_ref="step2",
    )
    late = materialize_threshold_program(
        "beta_late", generation=1,
        parents=("amihud_threshold__uniform",), evidence_ref="step2",
    )
    assert early.expression == "D*(2*c-c*c)"
    assert "exact_price_alias_h=D*(2*a-a*a)" in early.mathematical_object
    assert late.expression == "D*c*c"
    assert "exact_price_alias_h=D*a*a" in late.mathematical_object


def test_crossover_is_explicitly_zero_for_nonclosed_grammar():
    evaluate, _ = evaluator({"amihud_threshold__uniform": .4})
    result = run_threshold_family_gp(
        initial_family="uniform", allowed_families=("uniform",),
        evaluator=evaluate, evidence_ref="step2", metric="loss", direction=-1,
        seed=1, total_budget=1, max_evaluations=1,
    )
    assert result.crossover_attempts == 0
    assert result.crossover_reason.startswith("grammar_not_closed")


def test_unreviewed_family_and_arbitrary_expression_cannot_enter_grammar():
    with pytest.raises(ValueError, match="unreviewed"):
        materialize_threshold_program(
            "beta_2_2", generation=0, parents=(), evidence_ref="step2"  # type: ignore[arg-type]
        )
    evaluate, _ = evaluator({"amihud_threshold__uniform": .4})
    with pytest.raises(ValueError, match="unreviewed"):
        run_threshold_family_gp(
            initial_family="uniform",
            allowed_families=("uniform", "beta_2_2"),  # type: ignore[arg-type]
            evaluator=evaluate, evidence_ref="step2", metric="loss", direction=-1,
            seed=1, total_budget=1, max_evaluations=1,
        )


def test_common_budget_prevents_unfunded_mutations_from_being_scored():
    evaluate, calls = evaluator({
        "amihud_threshold__uniform": .4,
        "amihud_threshold__beta_early": .2,
        "amihud_threshold__beta_late": .3,
    })
    result = run_threshold_family_gp(
        initial_family="uniform",
        allowed_families=("uniform", "beta_early", "beta_late"),
        evaluator=evaluate, evidence_ref="step2", metric="loss", direction=-1,
        seed=20261003, total_budget=1, max_evaluations=3,
    )
    assert len(calls) == 1
    assert result.search.spent_cost == 1
    assert sum(row.status == "rejected" for row in result.search.trace) == 2
