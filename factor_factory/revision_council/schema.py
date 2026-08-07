from __future__ import annotations

COUNCIL_PROPOSAL_VERSION = "factorforge_revision_council_proposal_v1"
COUNCIL_SUMMARY_VERSION = "factorforge_revision_council_summary_v1"

COUNCIL_AGENT_ROLES = {
    "symbolic_law_discovery",
    "evidence_auditor",
    "economic_mechanism",
    "formula_engineer",
    "cost_turnover",
    "regime_robustness",
    "knowledge_retrieval_critic",
}

# Discoverability examples only. Council validation intentionally accepts
# mechanism-specific tools outside this set.
SYMBOLIC_MATH_TOOLS = {
    "discounted_cash_flow",
    "residual_income",
    "accounting_identity",
    "dimensional_analysis",
    "scaling_law_analysis",
    "invariance_analysis",
    "limiting_case_analysis",
    "perturbation_analysis",
    "stochastic_process_modeling",
    "stochastic_calculus",
    "jump_diffusion_reasoning",
    "natural_time_clock_analysis",
    "fourier_or_spectral_analysis",
    "robust_statistics",
    "tail_distribution_analysis",
    "linear_projection",
    "functional_analysis",
    "dynamical_systems",
    "stopping_time_reasoning",
    "information_theoretic_reasoning",
    "causal_structural_model",
    "optimization_and_control",
    "graph_interaction_model",
    "optimal_transport",
}

DIMENSIONAL_AUDIT_TOOLS = {
    "dimensional_analysis",
    "scaling_law_analysis",
}

REVISION_TYPES = {
    "expression_revision",
    "mechanism_challenge",
    "audit",
    "reject_advisory",
    "no_action",
}

FAILURE_SIGNATURES = {
    "cost_too_high",
    "long_side_negative",
    "non_monotonic",
    "mechanism_unclear",
    "implementation_suspect",
    "same_factor_identity_mismatch",
    "none",
}

RETURN_SOURCE_VALUES = {
    "risk_premium",
    "information_advantage",
    "constraint_driven_arbitrage",
    "market_structure_harvesting",
    "mixed",
    "unknown",
}

CONFIDENCE_VALUES = {"low", "medium", "high"}

PRODUCER_VALUES = {
    "agentic_research",
    "deterministic_scaffold",
    "human_authored",
}

RESEARCH_DEPTH_VALUES = {
    "low",
    "medium",
    "high",
}

PROPOSAL_GENERATION_MODE_VALUES = {
    "main_agent_self_run",
    "subagent_delegated",
    "deterministic_scaffold",
    "manual_debug",
}

REQUIRED_GUARDS = [
    "no_portfolio_expression_repair",
    "no_short_leg_adoption",
    "no_decile_trading",
    "no_shared_clean_data_mutation",
]

PROPOSAL_REQUIRED_FIELDS = [
    "contract_version",
    "report_id",
    "agent_role",
    "proposal_id",
    "proposal_status",
    "producer",
    "research_depth",
    "proposal_generation_mode",
    "revision_type",
    "target_failure_signature",
    "selected_math_tools",
    "market_phenomenon",
    "symbolic_model",
    "structural_findings",
    "candidate_revision_laws",
    "return_source_hypothesis",
    "expression_change",
    "why_not_portfolio_fix",
    "forbidden_changes_ack",
    "confidence",
    "risk_notes",
    "derivation_record",
]

BRANCH_HARD_GUARDS = REQUIRED_GUARDS
