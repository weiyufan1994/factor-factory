#!/usr/bin/env python3
"""Run one bounded, development-only MCTS engineering demonstration."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.hybrid_research.decision import Action, Context, Observation
from factor_factory.hybrid_research.gp_adapter import KernelTerm, ResponseProgram, evaluate_program
from factor_factory.hybrid_research.mcts import (
    ActionResult,
    ResearchState,
    run_action_mcts,
    run_simple_scheduler,
)
from factor_factory.hybrid_research.synthetic import FitData


FIT_DATA = FitData(
    signed_impulses=(1.0, 0.0, -0.5, 0.0, 1.0, 0.0),
    observed_response=(1.0, 0.6, -0.14, -0.084, 0.9496, 0.56976),
    step=1.0,
)

CONTEXT = Context.from_mapping(
    stage="development",
    objective="compare bounded causal response structures",
    conditions={"clock": "event", "input": "signed impulses", "sample": "engineering-fixture-v1"},
    evaluation_protocol="bounded-response-structure-v1",
)

ACTIONS = (
    Action(
        "deepen-single-kernel", "single-kernel", "exploit", 6.0,
        "fit the registered single transient kernel family",
    ),
    Action(
        "test-two-scale", "two-scale", "explore", 8.0,
        "test a registered two-scale competing response",
    ),
    Action(
        "test-permanent-plus-transient", "permanent-plus-transient", "explore", 6.0,
        "test the registered permanent-plus-transient competing response",
    ),
    Action(
        "stop", "stop", "exploit", 0.0,
        "stop when further registered development work is not selected",
    ),
)


def _programs(action_id: str) -> tuple[ResponseProgram, ...]:
    if action_id == "deepen-single-kernel":
        return tuple(
            ResponseProgram((KernelTerm(scale, rate),))
            for scale in (0.5, 1.0, 1.5)
            for rate in (0.25, 0.75)
        )
    if action_id == "test-two-scale":
        return tuple(
            ResponseProgram((KernelTerm(major, 0.75), KernelTerm(minor, 0.25)))
            for major in (0.5, 1.0)
            for minor in (-0.25, 0.25, 0.5, 0.75)
        )
    if action_id == "test-permanent-plus-transient":
        return tuple(
            ResponseProgram((KernelTerm(permanent, 0.0), KernelTerm(transient, rate)))
            for permanent in (-0.25, 0.25)
            for transient, rate in ((0.5, 0.25), (0.5, 0.75), (1.0, 0.75))
        )
    raise ValueError(f"unsupported engineering action: {action_id}")


def _mse(prediction: tuple[float, ...]) -> float:
    return sum(
        (actual - predicted) ** 2
        for actual, predicted in zip(FIT_DATA.observed_response, prediction)
    ) / len(prediction)


def evaluate_engineering_action(
    branch: ResearchState,
    action: Action,
    evaluator_seed: int,
) -> ActionResult:
    programs = _programs(action.action_id)
    losses = tuple(_mse(evaluate_program(program, FIT_DATA)) for program in programs)
    baseline = _mse(tuple(0.0 for _ in FIT_DATA.observed_response))
    best_loss = min(losses)
    evidence_ref = f"engineering:{action.action_id}:seed-{evaluator_seed}"
    observation = Observation(
        run_id=f"{action.action_id}:{branch.depth}:{evaluator_seed}",
        action_id=action.action_id,
        context=branch.context,
        split="development",
        protocol_id=branch.context.evaluation_protocol,
        metric="recovery_error",
        direction=-1,
        baseline=baseline,
        result=best_loss,
        scale=baseline,
        actual_cost=float(len(programs)),
        status="completed",
        evidence_ref=evidence_ref,
    )
    return ActionResult(
        observation=observation,
        experiment_ref=evidence_ref,
        added_prediction_refs=(f"prediction-tested:{action.family}",),
    )


def run_demo(*, enabled: bool, seed: int, total_budget: float) -> dict[str, object]:
    initial_state = ResearchState(
        context=CONTEXT,
        hypothesis_ref="hypothesis:bounded-causal-response",
        prediction_refs=("prediction:response-decays-after-signed-impulse",),
        competing_explanation_refs=(
            "alternative:two-scale-response",
            "alternative:permanent-plus-transient-response",
        ),
    )
    common = dict(
        enabled=enabled,
        initial_state=initial_state,
        actions=ACTIONS,
        evaluator=evaluate_engineering_action,
        metric="recovery_error",
        direction=-1,
        seed=seed,
        total_budget=total_budget,
        max_expansions=8,
        max_depth=3,
        explore_share=0.5,
        stop_action_ids=("stop",),
    )
    mcts = run_action_mcts(exploration_weight=0.7, **common)
    simple = run_simple_scheduler(**common)
    return {
        "scope": "local synthetic development engineering only",
        "formal_proof_effect": "none",
        "quality_improvement_claim": False,
        "hidden_oracle_used_by_evaluator": False,
        "same_action_registry": True,
        "same_budget_cap": total_budget,
        "mcts": asdict(mcts),
        "simple_scheduler": asdict(simple),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-mcts", action="store_true")
    parser.add_argument("--seed", type=int, default=20260927)
    parser.add_argument("--total-budget", type=float, default=40.0)
    args = parser.parse_args()
    print(json.dumps(
        run_demo(enabled=args.enable_mcts, seed=args.seed, total_budget=args.total_budget),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
