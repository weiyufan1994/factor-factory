import numpy as np
import pandas as pd

from factor_factory.research_search.formula_bridge import compile_candidate, compute_candidate
from factor_factory.research_search.generator import run_expression_gp, run_expression_mcts
from tests.research_search_d05_helpers import approved_scope


def _score(candidate):
    expression = candidate.expression
    return float(3 * expression.count("x") + expression.count("y") - 0.1 * candidate.root.complexity)


def test_gp_has_real_multigeneration_selection_mutation_and_crossover():
    result = run_expression_gp(approved_scope(max_depth=4), evaluator=_score, seed=41,
                               population_size=8, generations=3, max_attempts_per_generation=80)
    assert result.algorithm == "gp"
    assert result.best_candidate is not None
    assert len(result.evaluated_candidates) >= 16
    generations = {row.generation for row in result.trace if row.status == "completed"}
    assert generations == {0, 1, 2}
    assert any(row.operation == "subtree_mutation" and row.status == "accepted" for row in result.trace)
    assert any(row.operation == "typed_subtree_crossover" and row.status == "accepted" for row in result.trace)
    assert any(candidate.parents for candidate in result.evaluated_candidates)


def test_formula_mcts_expands_holes_rolls_out_complete_asts_and_backpropagates():
    seen = []

    def evaluator(candidate):
        assert "_" not in candidate.expression
        seen.append(candidate.root.node_hash)
        return _score(candidate)

    result = run_expression_mcts(approved_scope(max_depth=4), evaluator=evaluator, seed=12,
                                 iterations=36, exploration_weight=0.7)
    assert result.algorithm == "mcts"
    assert result.best_candidate is not None
    assert len(seen) == len(result.evaluated_candidates)
    assert len(seen) >= 20
    assert any("panel" in row.operation for row in result.trace)
    assert any(row.detail == "typed_rollout_backpropagated" for row in result.trace)
    assert all(row.score is not None for row in result.trace if row.status == "completed")


def test_formula_mcts_feedback_changes_later_tree_expansion():
    scope = approved_scope(max_depth=4)
    positive = run_expression_mcts(scope, evaluator=_score, seed=12, iterations=32, exploration_weight=0.2)
    negative = run_expression_mcts(scope, evaluator=lambda candidate: -_score(candidate), seed=12,
                                   iterations=32, exploration_weight=0.2)
    assert [row.operation for row in positive.trace] != [row.operation for row in negative.trace]


def test_gp_and_mcts_generate_candidates_instead_of_sorting_a_registered_queue():
    scope = approved_scope(max_depth=3)
    gp = run_expression_gp(scope, evaluator=_score, seed=5, population_size=6,
                           generations=2, max_attempts_per_generation=60)
    mcts = run_expression_mcts(scope, evaluator=_score, seed=5, iterations=24)
    assert any(row.operation in {"subtree_mutation", "typed_subtree_crossover"} for row in gp.trace)
    assert all(candidate.operation == "typed_hole_mcts" for candidate in mcts.evaluated_candidates)
    assert {row.root.node_hash for row in gp.evaluated_candidates} != {
        row.root.node_hash for row in mcts.evaluated_candidates}


def test_search_reuses_ast_scores_and_does_not_repeat_evaluator_trials():
    calls = []

    def evaluator(candidate):
        calls.append(candidate.root.node_hash)
        return _score(candidate)

    result = run_expression_gp(approved_scope(max_depth=4), evaluator=evaluator, seed=8,
                               population_size=8, generations=3, max_attempts_per_generation=80)
    assert len(calls) == len(set(calls)) == len(result.evaluated_candidates)
    assert any(row.status == "reused" and row.detail == "cached_ast_score" for row in result.trace)


def test_evaluator_exception_is_recorded_once_and_stops_without_retry():
    calls = []

    def evaluator(candidate):
        calls.append(candidate.root.node_hash)
        raise RuntimeError("synthetic evaluator failure")

    result = run_expression_mcts(approved_scope(), evaluator=evaluator, seed=3, iterations=20)
    assert result.stop_reason == "evaluator_error"
    assert len(calls) == 1
    assert result.trace[-1].status == "evaluator_error"
    assert "synthetic evaluator failure" in result.trace[-1].detail


def test_gp_and_mcts_can_optimize_actual_formula_outputs_against_synthetic_target():
    scope = approved_scope(max_depth=4)
    dates = pd.date_range("2025-01-02", periods=8)
    frame = pd.DataFrame({
        "ts_code": ["A"] * 8 + ["B"] * 8,
        "trade_date": list(dates) * 2,
        "x": np.r_[np.arange(8, dtype=float), np.arange(8, dtype=float) / 2],
        "y": np.r_[np.arange(8, dtype=float)[::-1], np.arange(8, dtype=float)],
    })
    target = (frame.set_index(["trade_date", "ts_code"]).sort_index().x
              + 0.5 * frame.set_index(["trade_date", "ts_code"]).sort_index().y)

    def formula_score(candidate):
        compiled = compile_candidate(candidate, scope, available_columns=list(frame.columns))
        values = compute_candidate(compiled, {"daily_df": frame}).factor_value
        target_aligned = target.reorder_levels(["trade_date", "ts_code"])
        target_aligned.index.names = ["datetime", "instrument"]
        errors = (values - target_aligned).dropna()
        return -float((errors * errors).mean()) if len(errors) else -1_000_000.0

    gp = run_expression_gp(scope, evaluator=formula_score, seed=22, population_size=8,
                           generations=2, max_attempts_per_generation=80)
    mcts = run_expression_mcts(scope, evaluator=formula_score, seed=22, iterations=24)
    assert gp.best_candidate is not None and np.isfinite(gp.best_score)
    assert mcts.best_candidate is not None and np.isfinite(mcts.best_score)
    assert gp.best_score <= 0 and mcts.best_score <= 0
