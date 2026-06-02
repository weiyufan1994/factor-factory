from __future__ import annotations

CONTRACT_VERSION = "factorforge_mechanism_math_contract_v1"
CONTRACT_VERSION_V2 = "mechanism_math_contract_v2"

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

VALID_PRIMARY_MODEL_FAMILIES_V2 = {
    "stochastic_process",
    "microstructure_response_function",
    "dimensional_scaling_analysis",
    "potential_field_or_barrier_model",
    "entropy_or_information_theory",
    "wavelet_or_spectral_model",
    "copula_or_dependence_model",
    "regime_switching_model",
    "behavioral_constraint_model",
    "inventory_or_execution_model",
    "network_or_contagion_model",
    # Compatibility aliases from the v1 classifier. These are accepted as
    # primary families only when the v2 positive modelling fields are present.
    "valuation_identity",
    "price_volume_microstructure",
    "cross_sectional_statistics",
    "linear_factor_projection",
    "functional_filter",
    "constraint_model",
    "other",
}

VALID_PRICE_PROCESS_TERMS_V2 = {
    "drift",
    "diffusion",
    "jump_intensity",
    "friction",
    "regime_transition",
    "observation_equation",
}

VALID_FORMULA_MODEL_ROLES_V2 = {
    "state_variable",
    "response_variable",
    "conditioning_variable",
    "barrier_proxy",
    "entropy_proxy",
    "regime_proxy",
}

VALID_PRICE_PROCESS_PROJECTION_ROLES_V2 = {
    "drift",
    "diffusion",
    "jump",
    "friction",
    "regime",
    "observation",
}

VALID_RESEARCH_EQUATION_STATUSES = {
    "strict_identity",
    "institutional_constraint",
    "behavioral_feedback",
    "empirical_invariance",
    "research_conjecture",
}

VALID_SYMMETRY_BREAKING_TYPES = {
    "none",
    "institutional_constraint",
    "liquidity_constraint",
    "behavioral_bias",
    "information_delay",
    "funding_pressure",
    "inventory_pressure",
    "market_microstructure_friction",
    "capacity_or_crowding",
    "regime_shift",
    "other",
}

REQUIRED_RESEARCH_EQUATION_FIELDS = [
    "equation_text",
    "equation_status",
    "assumptions",
    "validity_scope",
    "symmetry_or_constraint",
    "symmetry_breaking_mechanism",
    "latent_state",
    "observable_estimator",
    "expected_metric_signature",
    "falsification_tests",
    "kill_criteria",
]

VALID_T0_T1_PRICE_PROCESS_TERMS = {
    "drift",
    "diffusion",
    "jump",
    "friction",
    "regime_transition",
    "observation_equation",
}

REQUIRED_T0_T1_BENCHMARK_FIELDS = [
    "benchmark_required",
    "horizon",
    "affected_terms",
    "conditional_distribution_claim",
    "benchmark_implication",
    "when_primary_model_cannot_infer",
    "falsification_tests",
]

DRAWDOWN_GEOMETRY_FIELDS = [
    "drawdown_area",
    "normalized_drawdown_area",
    "max_drawdown_episode_area",
    "recovery_pain_area",
]

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
