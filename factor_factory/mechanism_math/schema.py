from __future__ import annotations

CONTRACT_VERSION = "factorforge_mechanism_math_contract_v1"

VALID_MODEL_STATUSES = {"specified", "under_specified", "invalid"}

VALID_MODEL_FAMILIES = {
    "valuation_identity",
    "stochastic_process",
    "price_volume_microstructure",
    "cross_sectional_statistics",
    "linear_factor_projection",
    "functional_filter",
    "constraint_model",
    "other",
}

VALID_TOOLKITS = {
    "probability_theory",
    "statistics",
    "stochastic_process_calculus",
    "time_series_and_filtering",
    "linear_algebra",
    "functional_analysis",
    "real_analysis",
    "ordinary_differential_equations",
    "partial_differential_equations",
    "optimization_and_control",
    "information_theory",
    "accounting_or_valuation_identity",
    "microstructure_model",
    "constraint_model",
}

REQUIRED_SPECIFIED_FIELDS = [
    "model_family",
    "math_toolkits",
    "economic_mechanism",
    "state_or_object",
    "observable_inputs",
    "factor_as_estimator",
    "target_functional",
    "process_hypothesis",
    "latent_state",
    "observable_estimator",
    "conditional_distribution_hypothesis",
    "relationship_shape",
    "monotonicity_claim",
    "information_set",
    "necessary_conditions",
    "expected_metric_signature",
    "metric_signature_match",
    "revision_operators",
    "falsification_tests",
    "mechanism_falsification_tests",
    "kill_criteria",
]

REQUIRED_INFORMATION_SET_FIELDS = [
    "filtration",
    "uses_future_information",
    "lag_or_delay_required",
    "notes",
]

REVISION_TARGET_MATH_OBJECTS = {
    "estimator_kernel",
    "lag_window",
    "state_variable",
    "projection_operator",
    "smoothing_regularization",
    "stopping_rule",
    "threshold_boundary",
    "model_family_challenge",
}

REQUIRED_REVISION_OPERATOR_FIELDS = [
    "operator_name",
    "revision_target_math_object",
    "math_change",
    "expected_effects",
    "forbidden_interpretation",
]

FORBIDDEN_REPAIR_TERMS = [
    "portfolio expression",
    "portfolio repair",
    "rebalance",
    "short leg",
    "short-leg",
    "long-short adoption",
    "decile trading",
    "buy decile",
    "sell decile",
    "shared clean data",
    "clean data mutation",
    "mutate clean data",
]

PRICE_FIELDS = {"open", "high", "low", "close", "price", "return", "returns", "pct_chg"}
VOLUME_FIELDS = {"volume", "vol", "amount", "turnover"}
FUNDAMENTAL_FIELDS = {
    "pb",
    "p_b",
    "book_to_market",
    "book_value",
    "roe",
    "roa",
    "ep",
    "earnings",
    "net_profit",
    "cashflow",
    "revenue",
    "profit",
    "equity",
    "assets",
}
