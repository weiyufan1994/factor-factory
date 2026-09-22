from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from factor_factory.mechanism_math.equation_quality import (
    VALID_DEMOTION_TRIGGERS,
    VALID_EVIDENCE_TIERS,
    score_research_equation,
)
from factor_factory.mechanism_math.schema import VALID_RESEARCH_EQUATION_STATUSES


MEASUREMENT_PROGRAM_VERSION_V1 = (
    "factorforge_mechanism_conditioned_measurement_program_v1"
)
MEASUREMENT_PROGRAM_VERSION_V2 = (
    "factorforge_mechanism_conditioned_measurement_program_v2"
)
# Backward-compatible name used by legacy migration code.  New callers must
# opt in to V2 explicitly; changing this alias would silently relabel V1 bytes.
MEASUREMENT_PROGRAM_VERSION = MEASUREMENT_PROGRAM_VERSION_V1
MEASUREMENT_PROGRAM_VERSIONS = frozenset(
    {MEASUREMENT_PROGRAM_VERSION_V1, MEASUREMENT_PROGRAM_VERSION_V2}
)
IMPLEMENTATION_ROUTES = frozenset({"operator", "direct_code", "hybrid"})
KNOWLEDGE_AUTHORITY = "advisory_prior_and_counterexample_only"
MATH_AUTHORITY = "economic_hypothesis_and_math_mechanism"
MODEL_CANDIDATE_ROLES = frozenset(
    {"primary", "mechanism_alternative", "null_alias"}
)
ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE = (
    "factorforge_ordinary_local_is_flexible_v1"
)
AUTHORITY_ORDER_V1 = [
    "economic_hypothesis",
    "open_math_tool_selection",
    "competing_model_selection",
    "primary_math_mechanism",
    "market_outcome_projection",
    "applicable_audits",
    "observation_equation",
    "measurement_program",
    "data_and_implementation",
    "empirical_falsification",
]
# V2 makes the classified, falsifiable market relation explicit before model
# selection.  It does not displace the selected model's mechanism functional as
# the sole formula carried by the downstream measurement-program binding.
AUTHORITY_ORDER_V2 = [
    "economic_hypothesis",
    "classified_research_equation",
    *AUTHORITY_ORDER_V1[1:],
]
# Legacy public name remains byte-for-byte V1.
AUTHORITY_ORDER = AUTHORITY_ORDER_V1
BLOCK_MEASUREMENT_PROGRAM_INVALID = (
    "BLOCK_FACTORFORGE_MEASUREMENT_PROGRAM_INVALID"
)
INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING = (
    "__invalid_research_compatibility_profile_binding__"
)


def research_compatibility_profile_from_spec(spec: Any) -> str | None:
    """Return only the profile consistently bound on the current Step2 spec."""
    if not isinstance(spec, dict):
        return None
    contract = spec.get("research_contract")
    contract_has_profile = (
        isinstance(contract, dict) and "research_compatibility_profile" in contract
    )
    top_has_profile = "research_compatibility_profile" in spec
    contract_profile = (
        contract.get("research_compatibility_profile")
        if isinstance(contract, dict)
        else None
    )
    if top_has_profile and (
        not contract_has_profile
        or spec.get("research_compatibility_profile") != contract_profile
    ):
        return INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING
    return contract_profile if contract_has_profile else None
PUBLIC_DERIVATION_FIELDS = frozenset(
    {
        "record_type",
        "definitions",
        "assumptions",
        "key_derivation_steps",
        "identification_gaps",
        "approximations",
        "overclaim_guard",
    }
)
PUBLIC_MEASUREMENT_PROGRAM_FIELDS_V1 = frozenset(
    {
        "contract_version",
        "authority_order",
        "knowledge_role",
        "math_tool_selection",
        "model_selection",
        "market_outcome_projection",
        "applicable_audits",
        "observation_and_estimation",
        "public_derivation_record",
        "implementation",
        "deterministic_validation_plan",
        "evaluation_design",
        "search_policy",
    }
)
PUBLIC_MEASUREMENT_PROGRAM_FIELDS_V2 = frozenset(
    {*PUBLIC_MEASUREMENT_PROGRAM_FIELDS_V1, "research_equation"}
)
# Preserve the public V1 name for callers that inspect the legacy closed shape.
PUBLIC_MEASUREMENT_PROGRAM_FIELDS = PUBLIC_MEASUREMENT_PROGRAM_FIELDS_V1
PUBLIC_MEASUREMENT_SECTION_FIELDS = {
    "knowledge_role": frozenset(
        {"authority", "uses", "cannot_override", "conflict_resolution"}
    ),
    "math_tool_selection": frozenset(
        {
            "search_space_policy",
            "candidate_tool_families",
            "selected_tool_families",
            "selection_rationale",
            "rejected_tool_families",
            "composition_or_new_object_allowed",
            "operator_availability_must_not_decide",
        }
    ),
    "model_selection": frozenset(
        {
            "selection_target",
            "candidate_models",
            "selection_argument",
            "rejected_model_reason",
        }
    ),
    "market_outcome_projection": frozenset(
        {
            "role",
            "market_outcome_contract",
            "projection_kind",
            "source_math_object",
            "traded_quantity",
            "affected_payoff_or_distribution_terms",
            "projection_equation_or_map",
            "link_to_observation_equation",
            "falsifier",
        }
    ),
    "applicable_audits": frozenset({"selection_rule", "selected", "rejected"}),
    "observation_and_estimation": frozenset(
        {
            "estimand",
            "observation_map",
            "executable_formula_projection",
            "estimator",
            "identification_assumptions",
            "bias_variance_and_noise",
            "legal_information_time",
            "data_construction_is_hypothesis_conditioned",
        }
    ),
    "public_derivation_record": PUBLIC_DERIVATION_FIELDS,
    "implementation": frozenset(
        {"route", "web_execution_status", "why_this_route", "components"}
    ),
    "deterministic_validation_plan": frozenset(
        {
            "schema_and_measurement_checks",
            "future_mutation_invariance",
            "limiting_case_oracles",
            "ablation_and_alias_tests",
            "implementation_parity",
        }
    ),
    "evaluation_design": frozenset(
        {"primary_metrics", "portfolio_contract", "proof_plan"}
    ),
    "search_policy": frozenset(
        {
            "invariant_estimand",
            "allowed_model_or_estimator_variations",
            "registered_diagnostic_trials",
            "quarantined_sensitivities",
            "forbidden_shortcuts",
            "objective_vector",
            "stop_rules",
        }
    ),
}
PUBLIC_REJECTED_TOOL_FIELDS = frozenset({"tool_family", "reason"})
PUBLIC_MODEL_CANDIDATE_FIELDS = frozenset(
    {
        "candidate_id",
        "candidate_role",
        "payoff_binding",
        "market_outcome_contract",
        "mechanism_target_contract",
        "model_family",
        "mathematical_object",
        "mechanism_equation_or_functional",
        "target_functional",
        "market_outcome_projection",
        "observation_mapping",
        "economic_implication",
        "identifiability_condition",
        "decisive_test",
        "selected",
    }
)
PUBLIC_SELECTED_AUDIT_FIELDS = frozenset(
    {"audit_family", "rationale", "audit_record", "falsifier"}
)
PUBLIC_REJECTED_AUDIT_FIELDS = frozenset({"audit_family", "reason"})
PUBLIC_MEASUREMENT_COMPONENT_FIELDS = frozenset(
    {
        "component_id",
        "binding_role",
        "economic_claim",
        "math_term_or_functional",
        "mechanism_role",
        "observable_or_input",
        "input_fields",
        "transformation_or_estimator",
        "implementation_binding",
        "input_measurement_semantics",
        "output_measurement_semantics",
        "information_time",
        "preserved_information",
        "discarded_information",
        "expected_metric_signature",
        "ablation_test",
        "falsifier",
        "knowledge_node_ids",
    }
)
PUBLIC_RESEARCH_EQUATION_FIELDS = frozenset(
    {
        "equation_status",
        "equation_text",
        "assumptions",
        "validity_scope",
        "symmetry_or_constraint",
        "symmetry_breaking_mechanism",
        "participant_constraint_loop",
        "equation_quality",
        # These three fields are compatibility mirrors of equation_quality.
        # V2 requires exact equality so they cannot become another authority.
        "evidence_tier",
        "audit_basis",
        "demotion_triggers",
        "mathematical_object",
        "observation_or_estimation_map",
        "observable_estimator",
        "expected_metric_signature",
        "falsification_tests",
        "kill_criteria",
        "identity_contract",
    }
)
PUBLIC_RESEARCH_EQUATION_VALIDITY_SCOPE_FIELDS = frozenset(
    {"market", "frequency", "regime", "participant_structure"}
)
PUBLIC_PARTICIPANT_CONSTRAINT_LOOP_FIELDS = frozenset(
    {"payer", "constraint", "repeat_mechanism", "failure_condition"}
)
PUBLIC_EQUATION_QUALITY_FIELDS = frozenset(
    {"evidence_tier", "audit_basis", "demotion_triggers"}
)
STRICT_IDENTITY_MIN_QUALITY_SCORE = 60
STRICT_IDENTITY_TYPES = frozenset(
    {
        "accounting_identity",
        "cash_flow_identity",
        "market_clearing_identity",
        "no_arbitrage_identity",
        "sdf_euler_identity",
        "balance_sheet_identity",
    }
)
STRICT_IDENTITY_RELATIONS = frozenset({"EQUAL_BY_DEFINITION"})
STRICT_IDENTITY_PROOF_STATUSES = frozenset(
    {
        "DERIVED_BY_DEFINITION",
        "DERIVED_FROM_ACCOUNTING_CLOSURE",
        "DERIVED_FROM_MARKET_CLEARING",
        "DERIVED_FROM_NO_ARBITRAGE",
    }
)
PUBLIC_STRICT_IDENTITY_CONTRACT_FIELDS = frozenset(
    {
        "identity_profile_id",
        "identity_type",
        "left_hand_side",
        "right_hand_side",
        "relation",
        "canonical_form",
        "normalization_or_units",
        "derivation_basis",
        "proof_steps",
        "proof_status",
        "empirical_claim_boundary",
        "audit_basis_sha256",
        "identity_expression_sha256",
    }
)
STRICT_IDENTITY_PROFILES = {
    "ACCOUNTING_PROFIT_EQ_REVENUE_MINUS_EXPENSE_V1": {
        "identity_type": "accounting_identity",
        "left_hand_side": "profit_t",
        "right_hand_side": "revenue_t - expense_t",
        "canonical_form": "profit_t - revenue_t + expense_t = 0",
        "proof_status": "DERIVED_FROM_ACCOUNTING_CLOSURE",
    },
    "CASH_FLOW_CLOSING_EQ_OPENING_PLUS_NET_FLOW_V1": {
        "identity_type": "cash_flow_identity",
        "left_hand_side": "closing_cash_t",
        "right_hand_side": "opening_cash_t + net_cash_flow_t",
        "canonical_form": (
            "closing_cash_t - opening_cash_t - net_cash_flow_t = 0"
        ),
        "proof_status": "DERIVED_FROM_ACCOUNTING_CLOSURE",
    },
    "MARKET_CLEARING_AGG_DEMAND_EQ_AGG_SUPPLY_V1": {
        "identity_type": "market_clearing_identity",
        "left_hand_side": "aggregate_executed_demand_t",
        "right_hand_side": "aggregate_executed_supply_t",
        "canonical_form": (
            "aggregate_executed_demand_t - aggregate_executed_supply_t = 0"
        ),
        "proof_status": "DERIVED_FROM_MARKET_CLEARING",
    },
    "NO_ARBITRAGE_ZERO_COST_ZERO_PAYOFF_V1": {
        "identity_type": "no_arbitrage_identity",
        "left_hand_side": "zero_cost_portfolio_value_t",
        "right_hand_side": "zero_payoff_value_t",
        "canonical_form": (
            "zero_cost_portfolio_value_t - zero_payoff_value_t = 0"
        ),
        "proof_status": "DERIVED_FROM_NO_ARBITRAGE",
    },
    "SDF_PRICE_EQ_EXPECTED_DISCOUNTED_PAYOFF_V1": {
        "identity_type": "sdf_euler_identity",
        "left_hand_side": "price_t",
        "right_hand_side": "conditional_expectation_t(sdf_t1 * payoff_t1)",
        "canonical_form": (
            "price_t - conditional_expectation_t(sdf_t1 * payoff_t1) = 0"
        ),
        "proof_status": "DERIVED_FROM_NO_ARBITRAGE",
    },
    "BALANCE_SHEET_ASSETS_EQ_LIABILITIES_PLUS_EQUITY_V1": {
        "identity_type": "balance_sheet_identity",
        "left_hand_side": "assets_t",
        "right_hand_side": "liabilities_t + equity_t",
        "canonical_form": "assets_t - liabilities_t - equity_t = 0",
        "proof_status": "DERIVED_FROM_ACCOUNTING_CLOSURE",
    },
}


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _strict_identity_expression_preimage(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        field: contract.get(field)
        for field in (
            "identity_profile_id",
            "identity_type",
            "left_hand_side",
            "right_hand_side",
            "relation",
            "canonical_form",
            "normalization_or_units",
            "derivation_basis",
            "proof_steps",
            "proof_status",
            "empirical_claim_boundary",
        )
    }


def build_strict_identity_contract(
    *,
    identity_profile_id: str,
    normalization_or_units: str,
    derivation_basis: list[str],
    proof_steps: list[str],
    audit_basis: list[str],
) -> dict[str, Any]:
    """Build the closed V2 identity proof object; it grants no authority."""
    profile = STRICT_IDENTITY_PROFILES.get(identity_profile_id)
    if not isinstance(profile, dict):
        raise ValueError("unknown strict identity profile")
    contract = {
        "identity_profile_id": identity_profile_id,
        "identity_type": profile["identity_type"],
        "left_hand_side": profile["left_hand_side"],
        "right_hand_side": profile["right_hand_side"],
        "relation": "EQUAL_BY_DEFINITION",
        "canonical_form": profile["canonical_form"],
        "normalization_or_units": normalization_or_units,
        "derivation_basis": list(derivation_basis),
        "proof_steps": list(proof_steps),
        "proof_status": profile["proof_status"],
        "empirical_claim_boundary": "DEFINITIONAL_NOT_ESTIMATED",
        "audit_basis_sha256": _canonical_sha256({"audit_basis": audit_basis}),
    }
    contract["identity_expression_sha256"] = _canonical_sha256(
        _strict_identity_expression_preimage(contract)
    )
    return contract


def _strict_identity_contract_failures(
    equation: dict[str, Any],
    *,
    prefix: str,
) -> list[str]:
    contract = equation.get("identity_contract")
    if not isinstance(contract, dict):
        return [f"{prefix}.strict_identity_contract_missing"]
    reasons: list[str] = []
    actual_fields = set(contract)
    if actual_fields != PUBLIC_STRICT_IDENTITY_CONTRACT_FIELDS:
        reasons.append(
            f"{prefix}.identity_contract.unexpected_or_missing_fields"
        )
    identity_type = contract.get("identity_type")
    if identity_type not in STRICT_IDENTITY_TYPES:
        reasons.append(f"{prefix}.identity_contract.identity_type_invalid")
    identity_profile_id = contract.get("identity_profile_id")
    identity_profile = STRICT_IDENTITY_PROFILES.get(identity_profile_id)
    if not isinstance(identity_profile, dict):
        reasons.append(f"{prefix}.identity_contract.identity_profile_id_invalid")
    else:
        for field, expected in identity_profile.items():
            if contract.get(field) != expected:
                reasons.append(
                    f"{prefix}.identity_contract.profile_{field}_mismatch"
                )
    if contract.get("relation") not in STRICT_IDENTITY_RELATIONS:
        reasons.append(f"{prefix}.identity_contract.relation_invalid")
    if contract.get("proof_status") not in STRICT_IDENTITY_PROOF_STATUSES:
        reasons.append(f"{prefix}.identity_contract.proof_status_invalid")
    if contract.get("empirical_claim_boundary") != "DEFINITIONAL_NOT_ESTIMATED":
        reasons.append(
            f"{prefix}.identity_contract.empirical_claim_boundary_invalid"
        )
    for field in (
        "left_hand_side",
        "right_hand_side",
        "canonical_form",
        "normalization_or_units",
    ):
        value = contract.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"{prefix}.identity_contract.{field}")
    if (
        isinstance(contract.get("left_hand_side"), str)
        and contract.get("left_hand_side") == contract.get("right_hand_side")
    ):
        reasons.append(f"{prefix}.identity_contract.trivial_same_side")
    for field in ("derivation_basis", "proof_steps"):
        value = contract.get(field)
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))
        ):
            reasons.append(f"{prefix}.identity_contract.{field}")
    expected_audit_digest = _canonical_sha256(
        {"audit_basis": equation.get("audit_basis")}
    )
    if contract.get("audit_basis_sha256") != expected_audit_digest:
        reasons.append(f"{prefix}.identity_contract.audit_basis_sha256_mismatch")
    expected_expression_digest = _canonical_sha256(
        _strict_identity_expression_preimage(contract)
    )
    if contract.get("identity_expression_sha256") != expected_expression_digest:
        reasons.append(
            f"{prefix}.identity_contract.identity_expression_sha256_mismatch"
        )
    equation_text = equation.get("equation_text")
    expected_equation_text = (
        f'{contract.get("left_hand_side")} = {contract.get("right_hand_side")}'
    )
    if equation_text != expected_equation_text:
        reasons.append(
            f"{prefix}.identity_contract.equation_text_not_exact_profile_identity"
        )
    return list(dict.fromkeys(reasons))


def stable_measurement_program_hash(program: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            program,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def selected_measurement_model(program: Any) -> dict[str, Any]:
    if not isinstance(program, dict):
        return {}
    selection = program.get("model_selection")
    if not isinstance(selection, dict):
        return {}
    selected = [
        item
        for item in selection.get("candidate_models") or []
        if isinstance(item, dict) and item.get("selected") is True
    ]
    return selected[0] if len(selected) == 1 else {}


def build_measurement_program_binding(program: Any) -> dict[str, Any]:
    selected = selected_measurement_model(program)
    if not isinstance(program, dict) or not program or not selected:
        return {}
    return {
        "measurement_program_contract_version": program.get("contract_version"),
        "measurement_program_hash": stable_measurement_program_hash(program),
        "selected_model_candidate_id": selected.get("candidate_id"),
        "selected_model_family": selected.get("model_family"),
        "mathematical_object": selected.get("mathematical_object"),
        "mechanism_equation_or_functional": selected.get(
            "mechanism_equation_or_functional"
        ),
        "target_functional": selected.get("target_functional"),
        "market_outcome_projection": selected.get("market_outcome_projection"),
        "observation_mapping": selected.get("observation_mapping"),
    }


def measurement_program_binding_failures(
    binding: Any,
    program: Any,
    *,
    prefix: str = "measurement_program_binding",
) -> list[str]:
    expected = build_measurement_program_binding(program)
    if not expected:
        return [f"{prefix}:measurement_program_invalid"]
    if not isinstance(binding, dict):
        return [f"{prefix}:missing"]
    reasons = [
        f"{prefix}:{field}"
        for field, expected_value in expected.items()
        if binding.get(field) != expected_value
    ]
    if set(binding) != set(expected):
        reasons.append(f"{prefix}:unexpected_or_missing_fields")
    if (
        binding.get("mechanism_equation_or_functional")
        == binding.get("market_outcome_projection")
    ):
        reasons.append(f"{prefix}:core_mechanism_equals_market_projection")
    return list(dict.fromkeys(reasons))


def measurement_program_template(
    *,
    placeholder: str,
    implementation_route: str = "operator",
    contract_version: str = MEASUREMENT_PROGRAM_VERSION_V1,
) -> dict[str, Any]:
    if implementation_route not in IMPLEMENTATION_ROUTES:
        raise ValueError(
            f"unsupported measurement-program implementation route: "
            f"{implementation_route!r}"
        )
    if (
        not isinstance(contract_version, str)
        or contract_version not in MEASUREMENT_PROGRAM_VERSIONS
    ):
        raise ValueError(
            f"unsupported measurement-program contract version: "
            f"{contract_version!r}"
        )
    route = implementation_route
    program = {
        "contract_version": contract_version,
        "authority_order": list(
            AUTHORITY_ORDER_V2
            if contract_version == MEASUREMENT_PROGRAM_VERSION_V2
            else AUTHORITY_ORDER_V1
        ),
        "knowledge_role": {
            "authority": KNOWLEDGE_AUTHORITY,
            "uses": ["candidate_model_prior", "counterexample", "tool_candidate"],
            "cannot_override": [
                "selected_estimand",
                "selected_math_mechanism",
                "information_set",
                "falsification_result",
            ],
            "conflict_resolution": placeholder,
        },
        "math_tool_selection": {
            "search_space_policy": "open_and_mechanism_conditioned",
            "candidate_tool_families": [placeholder, placeholder],
            "selected_tool_families": [placeholder],
            "selection_rationale": placeholder,
            "rejected_tool_families": [
                {"tool_family": placeholder, "reason": placeholder}
            ],
            "composition_or_new_object_allowed": True,
            "operator_availability_must_not_decide": True,
        },
        "model_selection": {
            "selection_target": placeholder,
            "candidate_models": [
                {
                    "candidate_id": "preferred_mechanism",
                    "candidate_role": "primary",
                    "model_family": placeholder,
                    "mathematical_object": placeholder,
                    "mechanism_equation_or_functional": placeholder,
                    "target_functional": placeholder,
                    "market_outcome_projection": placeholder,
                    "observation_mapping": placeholder,
                    "economic_implication": placeholder,
                    "identifiability_condition": placeholder,
                    "decisive_test": placeholder,
                    "selected": True,
                },
                {
                    "candidate_id": "alternative_mechanism",
                    "candidate_role": "mechanism_alternative",
                    "model_family": placeholder,
                    "mathematical_object": placeholder,
                    "mechanism_equation_or_functional": placeholder,
                    "target_functional": placeholder,
                    "market_outcome_projection": placeholder,
                    "observation_mapping": placeholder,
                    "economic_implication": placeholder,
                    "identifiability_condition": placeholder,
                    "decisive_test": placeholder,
                    "selected": False,
                },
                {
                    "candidate_id": "null_alias",
                    "candidate_role": "null_alias",
                    "model_family": placeholder,
                    "mathematical_object": placeholder,
                    "mechanism_equation_or_functional": placeholder,
                    "target_functional": placeholder,
                    "market_outcome_projection": placeholder,
                    "observation_mapping": placeholder,
                    "economic_implication": placeholder,
                    "identifiability_condition": placeholder,
                    "decisive_test": placeholder,
                    "selected": False,
                },
            ],
            "selection_argument": placeholder,
            "rejected_model_reason": placeholder,
        },
        "market_outcome_projection": {
            "role": "terminal_tradeable_quantity_bridge_not_core_model_restriction",
            "projection_kind": placeholder,
            "source_math_object": placeholder,
            "traded_quantity": placeholder,
            "affected_payoff_or_distribution_terms": [placeholder],
            "projection_equation_or_map": placeholder,
            "link_to_observation_equation": placeholder,
            "falsifier": placeholder,
        },
        "applicable_audits": {
            "selection_rule": (
                "Select only audits justified by the chosen mechanism and "
                "estimand; no audit family is universally mandatory."
            ),
            "selected": [],
            "rejected": [],
        },
        "observation_and_estimation": {
            "estimand": placeholder,
            "observation_map": placeholder,
            "executable_formula_projection": placeholder,
            "estimator": placeholder,
            "identification_assumptions": [placeholder, placeholder],
            "bias_variance_and_noise": placeholder,
            "legal_information_time": placeholder,
            "data_construction_is_hypothesis_conditioned": True,
        },
        "public_derivation_record": {
            "record_type": "auditable_summary_not_private_chain_of_thought",
            "definitions": [placeholder],
            "assumptions": [placeholder, placeholder],
            "key_derivation_steps": [placeholder, placeholder, placeholder],
            "identification_gaps": [placeholder],
            "approximations": [placeholder],
            "overclaim_guard": placeholder,
        },
        "implementation": {
            "route": route,
            "web_execution_status": (
                "trusted_formula_ir_execution"
                if route == "operator"
                else "model_only_requires_trusted_isolated_code_harness"
            ),
            "why_this_route": placeholder,
            "components": [
                {
                    "component_id": "component_1",
                    "binding_role": "full_formula" if route == "operator" else "component",
                    "economic_claim": placeholder,
                    "math_term_or_functional": placeholder,
                    "mechanism_role": placeholder,
                    "observable_or_input": placeholder,
                    "input_fields": [placeholder],
                    "transformation_or_estimator": placeholder,
                    "implementation_binding": placeholder,
                    "input_measurement_semantics": placeholder,
                    "output_measurement_semantics": placeholder,
                    "information_time": placeholder,
                    "preserved_information": placeholder,
                    "discarded_information": placeholder,
                    "expected_metric_signature": placeholder,
                    "ablation_test": placeholder,
                    "falsifier": placeholder,
                    "knowledge_node_ids": [],
                }
            ],
        },
        "deterministic_validation_plan": {
            "schema_and_measurement_checks": [placeholder],
            "future_mutation_invariance": placeholder,
            "limiting_case_oracles": [placeholder],
            "ablation_and_alias_tests": [placeholder],
            "implementation_parity": placeholder,
        },
        "evaluation_design": {
            "primary_metrics": [
                {
                    "metric": placeholder,
                    "direction": placeholder,
                    "candidate_threshold": placeholder,
                    "official_threshold": placeholder,
                    "evidence_role": "promotion_gate_evidence",
                }
            ],
            "portfolio_contract": {
                "long_side_definition": placeholder,
                "weighting": placeholder,
                "rebalance": placeholder,
                "return_path": placeholder,
                "nav_construction": placeholder,
                "turnover_definition": placeholder,
                "cost_model": placeholder,
                "capacity_model": placeholder,
                "minimum_eligible_names": 1,
                "maximum_excluded_fraction": 0.99,
            },
            "proof_plan": {
                "raw_evidence_artifacts": [placeholder],
                "hash_policy": placeholder,
                "replay_obligations": [placeholder],
                "authority_boundary": placeholder,
            },
        },
        "search_policy": {
            "invariant_estimand": placeholder,
            "allowed_model_or_estimator_variations": [placeholder],
            "registered_diagnostic_trials": [],
            "quarantined_sensitivities": [],
            "forbidden_shortcuts": [
                "choose a story because an operator already exists",
                "change the estimand because an available field is convenient",
                "accept in-sample fitness without mechanism discrimination",
            ],
            "objective_vector": [
                "mechanism_consistency",
                "identifiability",
                "applicable_audit_consistency",
                "out_of_sample_evidence",
                "after_cost_long_side_value",
            ],
            "stop_rules": [placeholder],
        },
    }
    if contract_version == MEASUREMENT_PROGRAM_VERSION_V2:
        program["research_equation"] = {
            "equation_status": "research_conjecture",
            "equation_text": placeholder,
            "assumptions": [placeholder],
            "validity_scope": {
                "market": placeholder,
                "frequency": placeholder,
                "regime": placeholder,
                "participant_structure": placeholder,
            },
            "symmetry_or_constraint": placeholder,
            "symmetry_breaking_mechanism": placeholder,
            "participant_constraint_loop": {
                "payer": placeholder,
                "constraint": placeholder,
                "repeat_mechanism": placeholder,
                "failure_condition": placeholder,
            },
            "equation_quality": {
                "evidence_tier": "report_specific_hypothesis",
                "audit_basis": [placeholder],
                "demotion_triggers": ["metric_signature_mismatch"],
            },
            "evidence_tier": "report_specific_hypothesis",
            "audit_basis": [placeholder],
            "demotion_triggers": ["metric_signature_mismatch"],
            "mathematical_object": placeholder,
            "observation_or_estimation_map": placeholder,
            "observable_estimator": placeholder,
            "expected_metric_signature": [placeholder],
            "falsification_tests": [placeholder],
            "kill_criteria": [placeholder],
        }
    return program


def validate_measurement_program(
    program: Any,
    *,
    placeholder: str | None = None,
    available_knowledge_node_ids: Iterable[str] = (),
    require_web_executable: bool = True,
    compatibility_profile: str | None = None,
    scope: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    flexible_local = (
        compatibility_profile == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
        and scope == "local_is_only"
    )
    if compatibility_profile is not None and not flexible_local:
        reasons.append("measurement_program.compatibility_profile_invalid")
    available_nodes = {str(item) for item in available_knowledge_node_ids}

    def nonempty(value: Any) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        normalized = value.strip().lower()
        if normalized in {
            "under_specified",
            "unknown",
            "todo",
            "tbd",
            "n/a",
            "none",
        }:
            return False
        return not placeholder or placeholder not in value

    def require_string(container: dict[str, Any], field: str, prefix: str) -> None:
        if not nonempty(container.get(field)):
            reasons.append(f"{prefix}.{field}")

    def require_string_list(
        container: dict[str, Any],
        field: str,
        prefix: str,
        *,
        minimum: int = 1,
    ) -> list[str]:
        value = container.get(field)
        if (
            not isinstance(value, list)
            or len(value) < minimum
            or any(not nonempty(item) for item in value)
        ):
            reasons.append(f"{prefix}.{field}")
            return []
        return [str(item) for item in value]

    def reject_unexpected(
        container: dict[str, Any], allowed: frozenset[str], prefix: str
    ) -> None:
        unexpected = sorted(set(container) - allowed)
        if unexpected:
            reasons.append(f"{prefix}.unexpected_fields:" + ",".join(unexpected))

    if not isinstance(program, dict):
        return ["measurement_program"]
    contract_version = program.get("contract_version")
    allowed_program_fields = (
        PUBLIC_MEASUREMENT_PROGRAM_FIELDS_V2
        if contract_version == MEASUREMENT_PROGRAM_VERSION_V2
        else PUBLIC_MEASUREMENT_PROGRAM_FIELDS_V1
    )
    if flexible_local:
        allowed_program_fields = frozenset(
            {*allowed_program_fields, "compatibility_profile"}
        )
    reject_unexpected(
        program, allowed_program_fields, "measurement_program"
    )
    if flexible_local and program.get("compatibility_profile") != compatibility_profile:
        reasons.append("measurement_program.compatibility_profile_binding_invalid")
    if (
        not isinstance(contract_version, str)
        or contract_version not in MEASUREMENT_PROGRAM_VERSIONS
    ):
        reasons.append("measurement_program.contract_version")
    expected_authority_order = (
        AUTHORITY_ORDER_V2
        if contract_version == MEASUREMENT_PROGRAM_VERSION_V2
        else AUTHORITY_ORDER_V1
    )
    if program.get("authority_order") != expected_authority_order:
        reasons.append("measurement_program.authority_order")

    knowledge = program.get("knowledge_role")
    if not isinstance(knowledge, dict):
        reasons.append("measurement_program.knowledge_role")
    else:
        reject_unexpected(
            knowledge,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["knowledge_role"],
            "measurement_program.knowledge_role",
        )
        if knowledge.get("authority") != KNOWLEDGE_AUTHORITY:
            reasons.append("measurement_program.knowledge_role.authority")
        require_string(knowledge, "conflict_resolution", "measurement_program.knowledge_role")
        uses = require_string_list(
            knowledge, "uses", "measurement_program.knowledge_role", minimum=2
        )
        if uses and not {"candidate_model_prior", "counterexample"} <= set(uses):
            reasons.append("measurement_program.knowledge_role.uses_required")
        cannot_override = require_string_list(
            knowledge,
            "cannot_override",
            "measurement_program.knowledge_role",
            minimum=3,
        )
        if cannot_override and "selected_estimand" not in cannot_override:
            reasons.append("measurement_program.knowledge_role.cannot_override_estimand")

    tool_selection = program.get("math_tool_selection")
    if not isinstance(tool_selection, dict):
        reasons.append("measurement_program.math_tool_selection")
    else:
        reject_unexpected(
            tool_selection,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["math_tool_selection"],
            "measurement_program.math_tool_selection",
        )
        if tool_selection.get("search_space_policy") != (
            "open_and_mechanism_conditioned"
        ):
            reasons.append(
                "measurement_program.math_tool_selection.search_space_policy"
            )
        candidates = require_string_list(
            tool_selection,
            "candidate_tool_families",
            "measurement_program.math_tool_selection",
            minimum=1 if flexible_local else 2,
        )
        selected = require_string_list(
            tool_selection,
            "selected_tool_families",
            "measurement_program.math_tool_selection",
        )
        if selected and candidates and not set(selected) <= set(candidates):
            reasons.append(
                "measurement_program.math_tool_selection.selected_not_candidate"
            )
        require_string(
            tool_selection,
            "selection_rationale",
            "measurement_program.math_tool_selection",
        )
        rejected = tool_selection.get("rejected_tool_families")
        if not isinstance(rejected, list):
            reasons.append(
                "measurement_program.math_tool_selection.rejected_tool_families"
            )
            rejected = []
        elif not rejected and not flexible_local:
            reasons.append(
                "measurement_program.math_tool_selection.rejected_tool_families"
            )
        else:
            for index, item in enumerate(rejected):
                prefix = (
                    "measurement_program.math_tool_selection."
                    f"rejected_tool_families[{index}]"
                )
                if not isinstance(item, dict):
                    reasons.append(prefix)
                    continue
                reject_unexpected(item, PUBLIC_REJECTED_TOOL_FIELDS, prefix)
                require_string(item, "tool_family", prefix)
                require_string(item, "reason", prefix)
        if tool_selection.get("composition_or_new_object_allowed") is not True:
            reasons.append(
                "measurement_program.math_tool_selection.new_object_not_allowed"
            )
        if tool_selection.get("operator_availability_must_not_decide") is not True:
            reasons.append(
                "measurement_program.math_tool_selection.operator_first_not_blocked"
            )

    selection = program.get("model_selection")
    selected_candidate: dict[str, Any] = {}
    if not isinstance(selection, dict):
        reasons.append("measurement_program.model_selection")
    else:
        reject_unexpected(
            selection,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["model_selection"],
            "measurement_program.model_selection",
        )
        for field in (
            "selection_target",
            "selection_argument",
            "rejected_model_reason",
        ):
            require_string(selection, field, "measurement_program.model_selection")
        candidates = selection.get("candidate_models")
        minimum_candidates = 2 if flexible_local else 3
        if not isinstance(candidates, list) or len(candidates) < minimum_candidates:
            reasons.append("measurement_program.model_selection.candidate_models")
        else:
            selected_count = 0
            identities: set[str] = set()
            roles: set[str] = set()
            model_families: dict[str, list[str]] = {}
            for index, candidate in enumerate(candidates):
                prefix = f"measurement_program.model_selection.candidate_models[{index}]"
                if not isinstance(candidate, dict):
                    reasons.append(prefix)
                    continue
                reject_unexpected(candidate, PUBLIC_MODEL_CANDIDATE_FIELDS, prefix)
                for field in (
                    "candidate_id",
                    "candidate_role",
                    "model_family",
                    "mathematical_object",
                    "mechanism_equation_or_functional",
                    "target_functional",
                    "market_outcome_projection",
                    "observation_mapping",
                    "economic_implication",
                    "identifiability_condition",
                    "decisive_test",
                ):
                    require_string(candidate, field, prefix)
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id in identities:
                    reasons.append(f"{prefix}.candidate_id_duplicate")
                identities.add(candidate_id)
                role = str(candidate.get("candidate_role") or "")
                if role not in MODEL_CANDIDATE_ROLES:
                    reasons.append(f"{prefix}.candidate_role_invalid")
                if role in roles and not (
                    flexible_local and role == "mechanism_alternative"
                ):
                    reasons.append(f"{prefix}.candidate_role_duplicate")
                roles.add(role)
                model_families.setdefault(role, []).append(
                    str(candidate.get("model_family") or "")
                )
                selected_count += candidate.get("selected") is True
                if candidate.get("selected") is True:
                    selected_candidate = candidate
                if (
                    str(candidate.get("mechanism_equation_or_functional") or "").strip()
                    == str(candidate.get("market_outcome_projection") or "").strip()
                ):
                    reasons.append(
                        f"{prefix}.core_mechanism_and_market_projection_not_distinct"
                    )
                if candidate.get("selected") is True and role != "primary":
                    reasons.append(
                        "measurement_program.model_selection.selected_role_not_primary"
                    )
            if selected_count != 1:
                reasons.append(
                    "measurement_program.model_selection.exactly_one_selected"
                )
            required_roles = (
                {"primary", "null_alias"}
                if flexible_local
                else set(MODEL_CANDIDATE_ROLES)
            )
            if not required_roles <= roles:
                reasons.append(
                    "measurement_program.model_selection.candidate_roles_incomplete"
                )
            primary_families = set(model_families.get("primary", []))
            for alternative_family in model_families.get("mechanism_alternative", []):
                if alternative_family and alternative_family in primary_families:
                    reasons.append(
                        "measurement_program.model_selection.alternative_model_not_distinct"
                    )

    outcome = program.get("market_outcome_projection")
    if not isinstance(outcome, dict):
        reasons.append("measurement_program.market_outcome_projection")
    else:
        reject_unexpected(
            outcome,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["market_outcome_projection"],
            "measurement_program.market_outcome_projection",
        )
        if outcome.get("role") != (
            "terminal_tradeable_quantity_bridge_not_core_model_restriction"
        ):
            reasons.append("measurement_program.market_outcome_projection.role")
        for field in (
            "projection_kind",
            "source_math_object",
            "traded_quantity",
            "projection_equation_or_map",
            "link_to_observation_equation",
            "falsifier",
        ):
            require_string(
                outcome,
                field,
                "measurement_program.market_outcome_projection",
            )
        require_string_list(
            outcome,
            "affected_payoff_or_distribution_terms",
            "measurement_program.market_outcome_projection",
        )

    audits = program.get("applicable_audits")
    if not isinstance(audits, dict):
        reasons.append("measurement_program.applicable_audits")
    else:
        reject_unexpected(
            audits,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["applicable_audits"],
            "measurement_program.applicable_audits",
        )
        require_string(
            audits,
            "selection_rule",
            "measurement_program.applicable_audits",
        )
        selected_audits = audits.get("selected")
        rejected_audits = audits.get("rejected")
        if not isinstance(selected_audits, list):
            reasons.append("measurement_program.applicable_audits.selected")
            selected_audits = []
        if not isinstance(rejected_audits, list):
            reasons.append("measurement_program.applicable_audits.rejected")
            rejected_audits = []
        for group_name, items, required_fields in (
            (
                "selected",
                selected_audits,
                ("audit_family", "rationale", "audit_record", "falsifier"),
            ),
            (
                "rejected",
                rejected_audits,
                ("audit_family", "reason"),
            ),
        ):
            for index, item in enumerate(items):
                prefix = (
                    "measurement_program.applicable_audits."
                    f"{group_name}[{index}]"
                )
                if not isinstance(item, dict):
                    reasons.append(prefix)
                    continue
                reject_unexpected(
                    item,
                    PUBLIC_SELECTED_AUDIT_FIELDS
                    if group_name == "selected"
                    else PUBLIC_REJECTED_AUDIT_FIELDS,
                    prefix,
                )
                for field in required_fields:
                    require_string(item, field, prefix)

    observation = program.get("observation_and_estimation")
    if not isinstance(observation, dict):
        reasons.append("measurement_program.observation_and_estimation")
    else:
        reject_unexpected(
            observation,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["observation_and_estimation"],
            "measurement_program.observation_and_estimation",
        )
        for field in (
            "estimand",
            "observation_map",
            "executable_formula_projection",
            "estimator",
            "bias_variance_and_noise",
            "legal_information_time",
        ):
            require_string(
                observation,
                field,
                "measurement_program.observation_and_estimation",
            )
        require_string_list(
            observation,
            "identification_assumptions",
            "measurement_program.observation_and_estimation",
            minimum=1 if flexible_local else 2,
        )
        if observation.get("data_construction_is_hypothesis_conditioned") is not True:
            reasons.append(
                "measurement_program.observation_and_estimation.data_construction_is_hypothesis_conditioned"
            )

    if selected_candidate and isinstance(outcome, dict) and isinstance(observation, dict):
        selected_global_pairs = (
            (
                "mathematical_object",
                outcome.get("source_math_object"),
            ),
            (
                "target_functional",
                observation.get("estimand"),
            ),
            (
                "market_outcome_projection",
                outcome.get("projection_equation_or_map"),
            ),
            (
                "observation_mapping",
                observation.get("observation_map"),
            ),
        )
        for field, global_value in selected_global_pairs:
            if selected_candidate.get(field) != global_value:
                reasons.append(
                    "measurement_program.model_selection.selected_model_"
                    f"{field}_global_mismatch"
                )

    if contract_version == MEASUREMENT_PROGRAM_VERSION_V2:
        equation_prefix = "measurement_program.research_equation"
        equation = program.get("research_equation")
        if not isinstance(equation, dict):
            reasons.append(equation_prefix)
        else:
            reject_unexpected(
                equation,
                PUBLIC_RESEARCH_EQUATION_FIELDS,
                equation_prefix,
            )
            equation_status = equation.get("equation_status")
            if equation_status not in VALID_RESEARCH_EQUATION_STATUSES:
                reasons.append(f"{equation_prefix}.equation_status")
            for field in (
                "equation_text",
                "evidence_tier",
                "symmetry_or_constraint",
                "symmetry_breaking_mechanism",
                "mathematical_object",
                "observation_or_estimation_map",
                "observable_estimator",
            ):
                require_string(equation, field, equation_prefix)
            top_demotion_triggers: list[str] = []
            for field in (
                "assumptions",
                "audit_basis",
                "demotion_triggers",
                "expected_metric_signature",
                "falsification_tests",
                "kill_criteria",
            ):
                values = require_string_list(equation, field, equation_prefix)
                if field == "demotion_triggers":
                    top_demotion_triggers = values
                if values and len(values) != len(set(values)):
                    reasons.append(f"{equation_prefix}.{field}_duplicate")

            validity_scope = equation.get("validity_scope")
            if not isinstance(validity_scope, dict):
                reasons.append(f"{equation_prefix}.validity_scope")
            else:
                reject_unexpected(
                    validity_scope,
                    PUBLIC_RESEARCH_EQUATION_VALIDITY_SCOPE_FIELDS,
                    f"{equation_prefix}.validity_scope",
                )
                for field in sorted(
                    PUBLIC_RESEARCH_EQUATION_VALIDITY_SCOPE_FIELDS
                ):
                    require_string(
                        validity_scope,
                        field,
                        f"{equation_prefix}.validity_scope",
                    )

            participant_loop = equation.get("participant_constraint_loop")
            if not isinstance(participant_loop, dict):
                reasons.append(f"{equation_prefix}.participant_constraint_loop")
            else:
                reject_unexpected(
                    participant_loop,
                    PUBLIC_PARTICIPANT_CONSTRAINT_LOOP_FIELDS,
                    f"{equation_prefix}.participant_constraint_loop",
                )
                for field in sorted(PUBLIC_PARTICIPANT_CONSTRAINT_LOOP_FIELDS):
                    require_string(
                        participant_loop,
                        field,
                        f"{equation_prefix}.participant_constraint_loop",
                    )

            equation_quality = equation.get("equation_quality")
            if not isinstance(equation_quality, dict):
                reasons.append(f"{equation_prefix}.equation_quality")
            else:
                quality_prefix = f"{equation_prefix}.equation_quality"
                reject_unexpected(
                    equation_quality,
                    PUBLIC_EQUATION_QUALITY_FIELDS,
                    quality_prefix,
                )
                require_string(equation_quality, "evidence_tier", quality_prefix)
                require_string_list(equation_quality, "audit_basis", quality_prefix)
                quality_demotion_triggers = require_string_list(
                    equation_quality,
                    "demotion_triggers",
                    quality_prefix,
                )
                if (
                    equation_quality.get("evidence_tier")
                    not in VALID_EVIDENCE_TIERS
                ):
                    reasons.append(f"{quality_prefix}.evidence_tier_invalid")
                invalid_quality_triggers = sorted(
                    set(quality_demotion_triggers) - VALID_DEMOTION_TRIGGERS
                )
                if invalid_quality_triggers:
                    reasons.append(
                        f"{quality_prefix}.demotion_triggers_invalid:"
                        + ",".join(invalid_quality_triggers)
                    )
                for field in sorted(PUBLIC_EQUATION_QUALITY_FIELDS):
                    if equation.get(field) != equation_quality.get(field):
                        reasons.append(
                            f"{equation_prefix}.{field}_quality_mirror_mismatch"
                        )

            if equation.get("evidence_tier") not in VALID_EVIDENCE_TIERS:
                reasons.append(f"{equation_prefix}.evidence_tier_invalid")
            invalid_demotion_triggers = sorted(
                set(top_demotion_triggers) - VALID_DEMOTION_TRIGGERS
            )
            if invalid_demotion_triggers:
                reasons.append(
                    f"{equation_prefix}.demotion_triggers_invalid:"
                    + ",".join(invalid_demotion_triggers)
                )
            if (
                equation_status == "strict_identity"
                and equation.get("evidence_tier") != "logical_identity"
            ):
                reasons.append(
                    f"{equation_prefix}.strict_identity_requires_logical_identity_evidence"
                )
            if equation_status == "strict_identity":
                reasons.extend(
                    _strict_identity_contract_failures(
                        equation,
                        prefix=equation_prefix,
                    )
                )
                equation_quality_result = score_research_equation(equation)
                if (
                    equation_quality_result.quality_score
                    < STRICT_IDENTITY_MIN_QUALITY_SCORE
                ):
                    reasons.append(
                        f"{equation_prefix}.strict_identity_quality_below_"
                        f"{STRICT_IDENTITY_MIN_QUALITY_SCORE}"
                    )
            elif equation.get("identity_contract") is not None:
                reasons.append(
                    f"{equation_prefix}.identity_contract_only_allowed_for_"
                    "strict_identity"
                )

            if selected_candidate:
                if (
                    equation.get("mathematical_object")
                    != selected_candidate.get("mathematical_object")
                ):
                    reasons.append(
                        f"{equation_prefix}.mathematical_object_selected_model_mismatch"
                    )
            if isinstance(observation, dict):
                if (
                    equation.get("observation_or_estimation_map")
                    != observation.get("observation_map")
                ):
                    reasons.append(
                        f"{equation_prefix}.observation_or_estimation_map_global_mismatch"
                    )
                if (
                    equation.get("observable_estimator")
                    != observation.get("estimator")
                ):
                    reasons.append(
                        f"{equation_prefix}.observable_estimator_global_mismatch"
                    )

            equation_text = str(equation.get("equation_text") or "").strip()
            forbidden_equation_aliases = (
                (
                    "market_outcome_projection",
                    outcome.get("projection_equation_or_map")
                    if isinstance(outcome, dict)
                    else None,
                ),
                (
                    "executable_formula_projection",
                    observation.get("executable_formula_projection")
                    if isinstance(observation, dict)
                    else None,
                ),
            )
            for alias_name, alias_value in forbidden_equation_aliases:
                if (
                    equation_text
                    and equation_text == str(alias_value or "").strip()
                ):
                    reasons.append(
                        f"{equation_prefix}.equation_text_equals_{alias_name}"
                    )

    public_record = program.get("public_derivation_record")
    if not isinstance(public_record, dict):
        reasons.append("measurement_program.public_derivation_record")
    else:
        reject_unexpected(
            public_record,
            PUBLIC_DERIVATION_FIELDS,
            "measurement_program.public_derivation_record",
        )
        if public_record.get("record_type") != (
            "auditable_summary_not_private_chain_of_thought"
        ):
            reasons.append(
                "measurement_program.public_derivation_record.record_type"
            )
        for field, minimum in (
            ("definitions", 1),
            ("assumptions", 1 if flexible_local else 2),
            ("key_derivation_steps", 1 if flexible_local else 3),
            ("identification_gaps", 1),
            ("approximations", 0 if flexible_local else 1),
        ):
            require_string_list(
                public_record,
                field,
                "measurement_program.public_derivation_record",
                minimum=minimum,
            )
        require_string(
            public_record,
            "overclaim_guard",
            "measurement_program.public_derivation_record",
        )

    implementation = program.get("implementation")
    if not isinstance(implementation, dict):
        reasons.append("measurement_program.implementation")
    else:
        reject_unexpected(
            implementation,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["implementation"],
            "measurement_program.implementation",
        )
        route = implementation.get("route")
        if route not in IMPLEMENTATION_ROUTES:
            reasons.append("measurement_program.implementation.route")
        if require_web_executable:
            if route != "operator":
                reasons.append(
                    "measurement_program.implementation.web_route_requires_trusted_harness"
                )
            if implementation.get("web_execution_status") != (
                "trusted_formula_ir_execution"
            ):
                reasons.append(
                    "measurement_program.implementation.web_execution_status"
                )
        require_string(
            implementation,
            "why_this_route",
            "measurement_program.implementation",
        )
        components = implementation.get("components")
        if not isinstance(components, list) or not components:
            reasons.append("measurement_program.implementation.components")
        else:
            for index, component in enumerate(components):
                prefix = f"measurement_program.implementation.components[{index}]"
                if not isinstance(component, dict):
                    reasons.append(prefix)
                    continue
                reject_unexpected(
                    component, PUBLIC_MEASUREMENT_COMPONENT_FIELDS, prefix
                )
                for field in (
                    "component_id",
                    "binding_role",
                    "economic_claim",
                    "math_term_or_functional",
                    "mechanism_role",
                    "observable_or_input",
                    "transformation_or_estimator",
                    "implementation_binding",
                    "input_measurement_semantics",
                    "output_measurement_semantics",
                    "information_time",
                    "preserved_information",
                    "discarded_information",
                    "expected_metric_signature",
                    "ablation_test",
                    "falsifier",
                ):
                    require_string(component, field, prefix)
                require_string_list(component, "input_fields", prefix)
                node_ids = component.get("knowledge_node_ids")
                if not isinstance(node_ids, list) or any(
                    not nonempty(node_id) for node_id in node_ids
                ):
                    reasons.append(f"{prefix}.knowledge_node_ids")
                elif not set(str(item) for item in node_ids) <= available_nodes:
                    reasons.append(f"{prefix}.knowledge_node_ids_not_in_summary")

    validation = program.get("deterministic_validation_plan")
    if not isinstance(validation, dict):
        reasons.append("measurement_program.deterministic_validation_plan")
    else:
        reject_unexpected(
            validation,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["deterministic_validation_plan"],
            "measurement_program.deterministic_validation_plan",
        )
        for field in (
            "schema_and_measurement_checks",
            "limiting_case_oracles",
            "ablation_and_alias_tests",
        ):
            require_string_list(
                validation,
                field,
                "measurement_program.deterministic_validation_plan",
            )
        for field in ("future_mutation_invariance", "implementation_parity"):
            require_string(
                validation,
                field,
                "measurement_program.deterministic_validation_plan",
            )

    evaluation = program.get("evaluation_design")
    evaluation_prefix = "measurement_program.evaluation_design"
    if not isinstance(evaluation, dict):
        reasons.append(evaluation_prefix)
    else:
        reject_unexpected(
            evaluation,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["evaluation_design"],
            evaluation_prefix,
        )
        metrics = evaluation.get("primary_metrics")
        metric_keys = {
            "metric", "direction", "candidate_threshold",
            "official_threshold", "evidence_role",
        }
        if not isinstance(metrics, list) or not metrics:
            reasons.append(f"{evaluation_prefix}.primary_metrics")
        else:
            seen_metrics: set[str] = set()
            for index, metric in enumerate(metrics):
                prefix = f"{evaluation_prefix}.primary_metrics[{index}]"
                if not isinstance(metric, dict) or set(metric) != metric_keys:
                    reasons.append(prefix)
                    continue
                for field in metric_keys:
                    require_string(metric, field, prefix)
                name = str(metric.get("metric") or "")
                if name in seen_metrics:
                    reasons.append(f"{prefix}.duplicate")
                seen_metrics.add(name)
                if metric.get("evidence_role") != "promotion_gate_evidence":
                    reasons.append(f"{prefix}.evidence_role")
        portfolio = evaluation.get("portfolio_contract")
        portfolio_keys = {
            "long_side_definition", "weighting", "rebalance", "return_path",
            "nav_construction", "turnover_definition", "cost_model",
            "capacity_model", "minimum_eligible_names",
            "maximum_excluded_fraction",
        }
        if not isinstance(portfolio, dict) or set(portfolio) != portfolio_keys:
            reasons.append(f"{evaluation_prefix}.portfolio_contract")
        else:
            for field in portfolio_keys - {
                "minimum_eligible_names", "maximum_excluded_fraction"
            }:
                require_string(portfolio, field, f"{evaluation_prefix}.portfolio_contract")
            if type(portfolio.get("minimum_eligible_names")) is not int or portfolio["minimum_eligible_names"] < 1:
                reasons.append(f"{evaluation_prefix}.portfolio_contract.minimum_eligible_names")
            excluded = portfolio.get("maximum_excluded_fraction")
            if isinstance(excluded, bool) or not isinstance(excluded, (int, float)) or not 0 <= float(excluded) < 1:
                reasons.append(f"{evaluation_prefix}.portfolio_contract.maximum_excluded_fraction")
        proof = evaluation.get("proof_plan")
        proof_keys = {
            "raw_evidence_artifacts", "hash_policy", "replay_obligations",
            "authority_boundary",
        }
        if not isinstance(proof, dict) or set(proof) != proof_keys:
            reasons.append(f"{evaluation_prefix}.proof_plan")
        else:
            require_string_list(proof, "raw_evidence_artifacts", f"{evaluation_prefix}.proof_plan")
            require_string_list(proof, "replay_obligations", f"{evaluation_prefix}.proof_plan")
            require_string(proof, "hash_policy", f"{evaluation_prefix}.proof_plan")
            require_string(proof, "authority_boundary", f"{evaluation_prefix}.proof_plan")

    search = program.get("search_policy")
    if not isinstance(search, dict):
        reasons.append("measurement_program.search_policy")
    else:
        reject_unexpected(
            search,
            PUBLIC_MEASUREMENT_SECTION_FIELDS["search_policy"],
            "measurement_program.search_policy",
        )
        require_string(search, "invariant_estimand", "measurement_program.search_policy")
        for field in (
            "allowed_model_or_estimator_variations",
            "forbidden_shortcuts",
            "objective_vector",
            "stop_rules",
        ):
            require_string_list(search, field, "measurement_program.search_policy")
        shortcuts = set(str(item) for item in search.get("forbidden_shortcuts") or [])
        if "choose a story because an operator already exists" not in shortcuts:
            reasons.append("measurement_program.search_policy.operator_first_forbidden")
        diagnostics = search.get("registered_diagnostic_trials")
        if not isinstance(diagnostics, list):
            reasons.append("measurement_program.search_policy.registered_diagnostic_trials")
        else:
            for index, item in enumerate(diagnostics):
                prefix = f"measurement_program.search_policy.registered_diagnostic_trials[{index}]"
                if not isinstance(item, dict) or set(item) != {
                    "trial_id",
                    "role",
                    "component_id",
                    "formula_or_law",
                    "affects_acceptance",
                    "multiple_testing_family",
                }:
                    reasons.append(prefix)
                    continue
                for field in (
                    "trial_id",
                    "role",
                    "component_id",
                    "formula_or_law",
                    "multiple_testing_family",
                ):
                    require_string(item, field, prefix)
                if item.get("role") not in {
                    "standalone_component",
                    "leave_one_out",
                    "sign_oracle",
                    "alias_diagnostic",
                    "regime_diagnostic",
                }:
                    reasons.append(f"{prefix}.role")
                if item.get("affects_acceptance") is not False:
                    reasons.append(f"{prefix}.affects_acceptance")
        sensitivities = search.get("quarantined_sensitivities")
        if not isinstance(sensitivities, list):
            reasons.append("measurement_program.search_policy.quarantined_sensitivities")
        else:
            for index, item in enumerate(sensitivities):
                prefix = f"measurement_program.search_policy.quarantined_sensitivities[{index}]"
                if not isinstance(item, dict) or set(item) != {
                    "sensitivity_id",
                    "reason",
                    "can_affect_acceptance",
                }:
                    reasons.append(prefix)
                    continue
                require_string(item, "sensitivity_id", prefix)
                require_string(item, "reason", prefix)
                if item.get("can_affect_acceptance") is not False:
                    reasons.append(f"{prefix}.can_affect_acceptance")

    return list(dict.fromkeys(reasons))
