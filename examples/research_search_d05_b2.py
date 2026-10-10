"""Run both D0.5 B2 search levels with synthetic evidence and scores."""
from __future__ import annotations

import json

from research_search_d05_b1 import build_scope

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
                       "derive the supported branch", add_assumptions=("sign survived the test",),
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
        "implementation_scores": [row.implementation_score for row in result.expansions],
    }


def main() -> None:
    scope = build_scope()

    def score(candidate):
        return float(3 * candidate.expression.count("x") + candidate.expression.count("y")
                     - 0.1 * candidate.root.complexity)

    gp = run_expression_gp(scope, evaluator=score, seed=11, population_size=8, generations=3)
    mcts = run_expression_mcts(scope, evaluator=score, seed=11, iterations=32)
    print(json.dumps({
        "level_1": [mechanism_run("supports"), mechanism_run("refutes")],
        "level_2": {
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
