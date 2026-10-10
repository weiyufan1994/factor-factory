"""Run the D0.5 B1 typed-expression slice on synthetic observations."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_search.formula_bridge import compile_candidate, compute_candidate
from factor_factory.research_search.generator import generate_population, mutate_candidate
from factor_factory.research_search.induction import (
    FieldSpec, ForwardInductionRecord, InductionScope, SemanticType, Unit,
)


def build_scope() -> InductionScope:
    signal = SemanticType("panel", "numeric", Unit.dimensionless(),
                          "session_close", "instrument_ts", "observed_at_or_before_t")
    observation_map = "x_t and y_t are available at session close t"
    record = ForwardInductionRecord(
        record_id="example-public-induction-v1", origin="synthetic_fixture",
        source_ref="synthetic://example/public-derivation-v1",
        assumptions=("x and y contain no observations later than t",),
        key_derivation_steps=(
            "define g_t = b + sum_j sum_{k>=0} w_{j,k} x_{j,t-k}; b is an explicit intercept",
            "delay shifts weights and trailing mean convolves them with a finite uniform causal kernel",
            "constant scaling/addition preserve the family; variable products and denominators leave it",
        ),
        parent_delta=(), observation_map=observation_map,
        response_family="causal_affine_response_estimator", response_constraint="causal_affine",
        grammar_productions=("field", "constant", "plus", "minus", "multiply", "delay", "mean"),
        conclusions=("the grammar preserves affine causal structure and makes no alpha-direction claim",),
        falsifiers=("a future perturbation changes an earlier output",),
        review_decision="proceed", data_exposure="synthetic_only")
    return InductionScope(
        induction_id="example-linear-response-v1", parent_induction_id=None, induction_record=record,
        response_family="causal_affine_response_estimator",
        mathematical_object="g_t = a0 + a1*x_t + a2*y_t with trailing observations",
        observation_map=observation_map,
        allowed_fields=(FieldSpec("x", signal), FieldSpec("y", signal)), output_type=signal,
        allowed_operators=("plus", "minus", "multiply", "delay", "mean"),
        allowed_constants=(-1.0, 0.5, 1.0, 2.0), allowed_windows=(1, 2, 3), max_depth=4,
        missing_value_policy="preserve warmup NaN", numeric_domain="finite real synthetic inputs",
        change_class="in_family_parameter",
    )


def main() -> None:
    scope = build_scope()
    generated = generate_population(scope, seed=19, population_size=6, max_attempts=40)
    parent = next(row for row in generated.candidates if row.root.kind == "operator")
    child, mutation = mutate_candidate(parent, scope, seed=7, candidate_id="example-mutant")
    selected = child or parent
    frame = pd.DataFrame({
        "ts_code": ["A"] * 5 + ["B"] * 5,
        "trade_date": list(pd.date_range("2025-01-02", periods=5)) * 2,
        "x": [0., 1., 2., 3., 4., 1., 1., 2., 3., 5.],
        "y": [2., 2., 1., 1., 0., 0., 1., 1., 2., 3.],
    })
    compiled = compile_candidate(selected, scope, available_columns=list(frame.columns))
    values = compute_candidate(compiled, {"daily_df": frame})
    print(json.dumps({
        "induction_scope_hash": scope.scope_hash,
        "generation": {"attempts": generated.attempts, "accepted": len(generated.candidates),
                       "rejected": generated.rejected, "stop_reason": generated.stop_reason},
        "parent": {"candidate_id": parent.candidate_id, "expression": parent.expression},
        "selected": {"candidate_id": selected.candidate_id, "parents": selected.parents,
                     "operation": selected.operation, "expression": selected.expression},
        "mutation_trace": mutation.__dict__,
        "formula_ir_hash": compiled.formula_ir.get("formula_hash"),
        "factor_head": values.reset_index().head(3).astype(str).to_dict("records"),
        "factor_tail": values.reset_index().tail(3).astype(str).to_dict("records"),
    }, indent=2))


if __name__ == "__main__":
    main()
