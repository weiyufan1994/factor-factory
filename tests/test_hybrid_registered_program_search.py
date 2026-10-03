from __future__ import annotations

import math
import pytest

from factor_factory.hybrid_research.registered_program_search import (
    ProgramEvaluation,
    RegisteredProgram,
    run_registered_program_search,
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


def test_registered_program_search_is_deterministic_and_selects_with_complexity_tie_break():
    rows = (
        program("baseline", complexity=2),
        program("mutant", generation=1, parents=("baseline",), complexity=4),
    )
    def run():
        return run_registered_program_search(
            programs=rows, evaluator=lambda row, seed: result(row, 0.2),
            metric="loss", direction=-1, seed=20261003,
            total_budget=2, max_evaluations=2,
        )
    assert run() == run()
    assert run().selected_id == "baseline"
    assert run().spent_cost == 2


def test_single_registered_program_records_no_search_degree():
    row = program("D_times_c")
    report = run_registered_program_search(
        programs=(row,), evaluator=lambda item, seed: result(item, 0.4),
        metric="loss", direction=-1, seed=1, total_budget=1,
        max_evaluations=1,
    )
    assert report.selected_id == "D_times_c"
    assert report.stop_reason == "no_search_degree:single_registered_program"


def test_unknown_is_costed_but_never_becomes_reward():
    row = program("unknown")
    report = run_registered_program_search(
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
    report = run_registered_program_search(
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
    report = run_registered_program_search(
        programs=(row,), evaluator=wrong_hash, metric="loss", direction=-1,
        seed=1, total_budget=1, max_evaluations=1,
    )
    assert report.selected_id is None
    assert report.stop_reason == "evaluator_contract_violation"
    assert report.trace[0].reason == "program_hash_mismatch"
    assert report.trace[0].actual_cost == 1
    assert report.spent_cost == 1


def test_cost_above_reservation_is_retained_as_known_spend_before_stop():
    row = program("a", cost=1)
    report = run_registered_program_search(
        programs=(row,),
        evaluator=lambda item, seed: result(item, .2, cost=2),
        metric="loss", direction=-1, seed=1, total_budget=1,
        max_evaluations=1,
    )
    assert report.selected_id is None
    assert report.stop_reason == "evaluator_contract_violation"
    assert report.trace[0].reason == "actual_cost_exceeds_reservation"
    assert report.trace[0].actual_cost == 2
    assert report.spent_cost == 2


def test_wrong_return_type_stops_once_with_unknown_cost_trace():
    calls = 0
    def wrong_type(item, seed):
        nonlocal calls
        calls += 1
        return {"actual_cost": 1}
    report = run_registered_program_search(
        programs=(program("a"), program("b")), evaluator=wrong_type,
        metric="loss", direction=-1, seed=1, total_budget=2,
        max_evaluations=2,
    )
    assert calls == report.evaluator_calls == 1
    assert report.selected_id is None
    assert report.spent_cost == 0
    assert report.stop_reason == "evaluator_contract_violation_unknown_cost"
    assert report.trace[0].status == "evaluator_contract_violation"
    assert report.trace[0].actual_cost is None
    assert report.trace[0].reason == "evaluator must return ProgramEvaluation"


@pytest.mark.parametrize("bad_cost", ("bad", {}, True, math.inf, math.nan))
def test_invalid_cost_type_preserves_one_unknown_cost_trace(bad_cost):
    calls = 0
    def invalid_cost(item, seed):
        nonlocal calls
        calls += 1
        return ProgramEvaluation(
            item.program_hash, "development", "loss", -1, .2,
            bad_cost, "completed", "evidence",
        )
    report = run_registered_program_search(
        programs=(program("a"), program("b")), evaluator=invalid_cost,
        metric="loss", direction=-1, seed=1, total_budget=2,
        max_evaluations=2,
    )
    assert calls == report.evaluator_calls == 1
    assert report.spent_cost == 0
    assert report.stop_reason == "evaluator_contract_violation_unknown_cost"
    assert report.trace[0].actual_cost is None
    assert report.trace[0].reason == "actual_cost_invalid"


@pytest.mark.parametrize("bad_score", (True, "0.2", {}, math.inf, math.nan))
def test_invalid_score_type_stops_with_known_cost(bad_score):
    row = program("a")
    report = run_registered_program_search(
        programs=(row,),
        evaluator=lambda item, seed: ProgramEvaluation(
            item.program_hash, "development", "loss", -1,
            bad_score, 1, "completed", "evidence",
        ),
        metric="loss", direction=-1, seed=1, total_budget=1,
        max_evaluations=1,
    )
    assert report.spent_cost == 1
    assert report.stop_reason == "evaluator_contract_violation"
    assert report.trace[0].reason == "score_invalid"


def test_boolean_direction_is_rejected_before_evaluator_call():
    calls = 0
    def never(item, seed):
        nonlocal calls
        calls += 1
        return result(item, .2)
    with pytest.raises(ValueError, match="direction"):
        run_registered_program_search(
            programs=(program("a"),), evaluator=never, metric="loss",
            direction=True, seed=1, total_budget=1, max_evaluations=1,  # type: ignore[arg-type]
        )
    assert calls == 0


def test_boolean_result_direction_is_contract_violation_with_known_cost():
    row = program("a")
    report = run_registered_program_search(
        programs=(row,),
        evaluator=lambda item, seed: ProgramEvaluation(
            item.program_hash, "development", "loss", True, .2, 1,
            "completed", "evidence",  # type: ignore[arg-type]
        ),
        metric="loss", direction=1, seed=1, total_budget=1,
        max_evaluations=1,
    )
    assert report.spent_cost == 1
    assert report.stop_reason == "evaluator_contract_violation"
    assert report.trace[0].reason == "metric_contract_mismatch"


def test_boolean_program_cost_is_rejected_at_construction():
    with pytest.raises(ValueError, match="estimated cost"):
        program("a", cost=True)


@pytest.mark.parametrize("bad_count", (True, 1.5, math.inf))
def test_invalid_evaluation_count_is_rejected_before_callback(bad_count):
    calls = 0
    def never(item, seed):
        nonlocal calls
        calls += 1
        return result(item, .2)
    with pytest.raises(ValueError, match="evaluations positive"):
        run_registered_program_search(
            programs=(program("a"),), evaluator=never, metric="loss",
            direction=-1, seed=1, total_budget=1,
            max_evaluations=bad_count,  # type: ignore[arg-type]
        )
    assert calls == 0


@pytest.mark.parametrize("bad_budget", (True, math.inf, math.nan, "1"))
def test_invalid_total_budget_is_rejected_before_callback(bad_budget):
    calls = 0
    def never(item, seed):
        nonlocal calls
        calls += 1
        return result(item, .2)
    with pytest.raises(ValueError, match="budget"):
        run_registered_program_search(
            programs=(program("a"),), evaluator=never, metric="loss",
            direction=-1, seed=1, total_budget=bad_budget,  # type: ignore[arg-type]
            max_evaluations=1,
        )
    assert calls == 0


def test_registry_rejects_unmaterialized_lineage_and_duplicate_math():
    with pytest.raises(ValueError, match="unknown parent"):
        run_registered_program_search(
            programs=(program("x", generation=1, parents=("missing",)),),
            evaluator=lambda row, seed: result(row, 0), metric="loss",
            direction=-1, seed=1, total_budget=1, max_evaluations=1,
        )
    duplicate = RegisteredProgram(
        "y", "expr:x", "registered D/c object", 0, (), "initialize", 3, 1,
        ("step2:y",),
    )
    with pytest.raises(ValueError, match="duplicate program hash"):
        run_registered_program_search(
            programs=(program("x"), duplicate),
            evaluator=lambda row, seed: result(row, 0), metric="loss",
            direction=-1, seed=1, total_budget=2, max_evaluations=2,
        )
