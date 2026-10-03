from __future__ import annotations

import pytest

from factor_factory.hybrid_research.registered_gp import (
    ProgramEvaluation,
    RegisteredProgram,
    run_registered_program_gp,
)


def program(pid: str, *, generation: int = 0, parents=(), cost=1.0, complexity=3):
    return RegisteredProgram(
        pid, f"expr:{pid}", "registered D/c object", generation, parents,
        "initialize" if generation == 0 else "registered_mutation",
        complexity, cost, (f"step2:{pid}",),
    )


def result(row, score, *, cost=1.0, status="completed"):
    return ProgramEvaluation(
        row.program_hash, "development", "loss", -1,
        score if status == "completed" else None, cost, status,
        f"evidence:{row.program_id}" if status == "completed" else None,
    )


def test_registered_gp_is_deterministic_and_selects_with_complexity_tie_break():
    rows = (
        program("baseline", complexity=2),
        program("mutant", generation=1, parents=("baseline",), complexity=4),
    )
    def run():
        return run_registered_program_gp(
            programs=rows, evaluator=lambda row, seed: result(row, 0.2),
            metric="loss", direction=-1, seed=20261003,
            total_budget=2, max_evaluations=2,
        )
    assert run() == run()
    assert run().selected_id == "baseline"
    assert run().spent_cost == 2


def test_single_registered_program_records_no_search_degree():
    row = program("D_times_c")
    report = run_registered_program_gp(
        programs=(row,), evaluator=lambda item, seed: result(item, 0.4),
        metric="loss", direction=-1, seed=1, total_budget=1,
        max_evaluations=1,
    )
    assert report.selected_id == "D_times_c"
    assert report.stop_reason == "no_search_degree:single_registered_program"


def test_unknown_is_costed_but_never_becomes_reward():
    row = program("unknown")
    report = run_registered_program_gp(
        programs=(row,),
        evaluator=lambda item, seed: result(item, None, status="unknown"),
        metric="loss", direction=-1, seed=1, total_budget=1,
        max_evaluations=1,
    )
    assert report.selected_id is None
    assert report.spent_cost == 1
    assert report.trace[0].status == "unknown"


def test_exception_stops_without_retry_or_invented_cost():
    calls = 0
    def broken(item, seed):
        nonlocal calls
        calls += 1
        raise RuntimeError("backend lost")
    report = run_registered_program_gp(
        programs=(program("a"), program("b")), evaluator=broken,
        metric="loss", direction=-1, seed=1, total_budget=2,
        max_evaluations=2,
    )
    assert calls == 1
    assert report.evaluator_calls == 1
    assert report.spent_cost == 0
    assert report.stop_reason == "evaluator_exception_unknown_cost"


def test_hash_and_split_contracts_fail_closed():
    row = program("a")
    def wrong_hash(item, seed):
        return ProgramEvaluation("wrong", "development", "loss", -1, .2, 1, "completed", "e")
    report = run_registered_program_gp(
        programs=(row,), evaluator=wrong_hash, metric="loss", direction=-1,
        seed=1, total_budget=1, max_evaluations=1,
    )
    assert report.selected_id is None
    assert report.stop_reason == "evaluator_contract_violation"
    assert report.trace[0].reason == "program_hash_mismatch"


def test_registry_rejects_unmaterialized_lineage_and_duplicate_math():
    with pytest.raises(ValueError, match="unknown parent"):
        run_registered_program_gp(
            programs=(program("x", generation=1, parents=("missing",)),),
            evaluator=lambda row, seed: result(row, 0), metric="loss",
            direction=-1, seed=1, total_budget=1, max_evaluations=1,
        )
    duplicate = RegisteredProgram(
        "y", "expr:x", "registered D/c object", 0, (), "initialize", 3, 1,
        ("step2:y",),
    )
    with pytest.raises(ValueError, match="duplicate program hash"):
        run_registered_program_gp(
            programs=(program("x"), duplicate),
            evaluator=lambda row, seed: result(row, 0), metric="loss",
            direction=-1, seed=1, total_budget=2, max_evaluations=2,
        )
