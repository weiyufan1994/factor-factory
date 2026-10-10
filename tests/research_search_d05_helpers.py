from __future__ import annotations

from factor_factory.research_search.induction import (
    FieldSpec, ForwardInductionRecord, InductionScope, SemanticType, Unit,
)


def panel_type(*, unit: Unit | None = None, clock: str = "session_close",
               grouping: str = "instrument_ts", information: str = "observed_at_or_before_t") -> SemanticType:
    return SemanticType("panel", "numeric", unit or Unit.dimensionless(), clock, grouping, information)


def approved_scope(**changes) -> InductionScope:
    signal_type = panel_type()
    record = ForwardInductionRecord(
        record_id="synthetic-linear-response-v1", origin="synthetic_fixture",
        source_ref="synthetic://linear-response/public-derivation-v1",
        assumptions=("x_t and y_t are observed without future information",),
        key_derivation_steps=(
            "define g_t = b + sum_j sum_{k>=0} w_{j,k} x_{j,t-k}; b is an explicit intercept",
            "delay shifts kernel weights and trailing mean convolves them with a finite uniform causal kernel",
            "constant scaling and addition preserve this family; variable products and denominators leave it",
        ),
        parent_delta=(), observation_map="x_t and y_t observed by session close t for instrument i",
        response_family="causal_affine_response_estimator", response_constraint="causal_affine",
        grammar_productions=("field", "constant", "plus", "minus", "multiply", "divide", "delay", "mean"),
        conclusions=("the grammar preserves affine structure and information at t or earlier; it makes no return-direction claim",),
        falsifiers=("future perturbation changes an earlier estimate",),
        review_decision="proceed", data_exposure="synthetic_only",
    )
    values = dict(
        induction_id="induction-linear-response-v1",
        parent_induction_id=None,
        induction_record=record,
        response_family="causal_affine_response_estimator",
        mathematical_object="g_t = a0 + a1*x_t + a2*y_t with trailing transforms allowed",
        observation_map="x_t and y_t observed by session close t for instrument i",
        allowed_fields=(FieldSpec("x", signal_type), FieldSpec("y", signal_type)),
        output_type=signal_type,
        allowed_operators=("plus", "minus", "multiply", "divide", "delay", "mean"),
        allowed_constants=(-1.0, 0.0, 0.5, 1.0, 2.0),
        allowed_windows=(1, 2, 3),
        max_depth=4,
        missing_value_policy="preserve Formula engine warmup and input NaN",
        numeric_domain="finite real inputs; division may yield rejected infinity at factor boundary",
        change_class="in_family_parameter",
    )
    values.update(changes)
    return InductionScope(**values)
