"""Run both D0.5 B2 search levels with synthetic evidence and scores."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research_search_d05_b1 import build_scope

from factor_factory.research_search.formula_bridge import compile_candidate, compute_candidate
from factor_factory.research_search.generator import run_expression_gp, run_expression_mcts
from factor_factory.research_search.mechanism import (
    ExperimentEvidence, MechanismEvaluation, MechanismState, Prediction,
    ResearchAction, run_mechanism_mcts,
)


def mechanism_run(outcome: str) -> dict:
    scope = build_scope()
    initial = MechanismState(
        state_id="root", mechanism="x drives a finite causal response",
        response_family=scope.response_family, response_structure="affine distributed lag",
        induction_record_hash=scope.induction_record.record_hash,
        assumptions=("x is observed by t",),
        predictions=(Prediction("p-sign", "the response has the declared sign", ("common-cause-only",)),),
        competing_mechanisms=("common-cause-only",), unknowns=("response sign",))
    actions = (
        ResearchAction("test-sign", "check_observation", "explore", 1.0,
                       "run the predeclared sign test", resolve_unknowns=("response sign",)),
        ResearchAction("deepen-supported", "deepen", "exploit", 1.0,
                       "estimate lag weights on the supported branch", add_unknowns=("lag weights",),
                       requires_assessment=("supported",)),
        ResearchAction("revise-refuted", "deepen", "explore", 1.0,
                       "revise the refuted mechanism", mechanism="a common cause drives both variables",
                       requires_assessment=("refuted",)),
    )

    def evaluator(state, action, seed):
        del state, seed
        return MechanismEvaluation(
            ExperimentEvidence(f"synthetic://{outcome}/{action.action_id}", "p-sign", "disc-v1",
                               outcome, True, True, 0.8), actual_cost=1.0,
            implementation_score=-3.0)

    result = run_mechanism_mcts(
        initial_state=initial, actions=actions, evaluator=evaluator, protocol_id="disc-v1",
        seed=4, total_budget=2.0, max_expansions=2, max_depth=2)
    return {
        "outcome": outcome, "next_action": result.planning.trace[1].action_id,
        "research_rewards": [row.research_reward for row in result.expansions],
        "assessments": [row.successor.mechanism_assessment for row in result.expansions],
        "successor_statuses": [row.successor.status for row in result.expansions],
        "implementation_scores": [row.implementation_score for row in result.expansions],
        "decision": result.decision,
    }


def main() -> None:
    scope = build_scope()
    dates = pd.date_range("2025-01-02", periods=20)
    frame = pd.DataFrame({
        "ts_code": ["A"] * 20 + ["B"] * 20,
        "trade_date": list(dates) * 2,
        "x": np.r_[np.arange(20, dtype=float), np.arange(20, dtype=float) / 2],
        "y": np.r_[np.arange(20, dtype=float)[::-1], np.arange(20, dtype=float)],
    })
    target_frame = frame.assign(target=lambda row: row.x + 0.5 * row.y)
    target = target_frame.rename(columns={"trade_date": "datetime", "ts_code": "instrument"})
    target = target.set_index(["datetime", "instrument"])["target"].sort_index()
    common_start = dates[max(scope.allowed_windows) * scope.max_depth]

    def score(candidate):
        compiled = compile_candidate(candidate, scope, available_columns=list(frame.columns))
        values = compute_candidate(compiled, {"daily_df": frame}).factor_value
        errors = (values - target).loc[common_start:].dropna()
        return -float((errors * errors).mean()) if len(errors) else -1_000_000.0

    gp = run_expression_gp(scope, evaluator=score, seed=11, population_size=8, generations=3)
    mcts = run_expression_mcts(scope, evaluator=score, seed=11, iterations=32)
    print(json.dumps({
        "level_1": [mechanism_run("supports"), mechanism_run("refutes")],
        "level_2": {
            "score_meaning": "negative MSE versus synthetic target x + 0.5*y after a fixed common warmup",
            "common_start": str(common_start.date()),
            "gp": {"best": gp.best_candidate.expression, "score": gp.best_score,
                   "unique_evaluations": len(gp.evaluated_candidates),
                   "reused": sum(row.status == "reused" for row in gp.trace)},
            "mcts": {"best": mcts.best_candidate.expression, "score": mcts.best_score,
                     "unique_evaluations": len(mcts.evaluated_candidates),
                     "reused": sum(row.status == "reused" for row in mcts.trace)},
        },
    }, indent=2))


if __name__ == "__main__":
    main()
