from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


MEASUREMENT_PROGRAM_VERSION = (
    "factorforge_mechanism_conditioned_measurement_program_v1"
)
IMPLEMENTATION_ROUTES = frozenset({"operator", "direct_code", "hybrid"})
KNOWLEDGE_AUTHORITY = "advisory_prior_and_counterexample_only"
MATH_AUTHORITY = "economic_hypothesis_and_math_mechanism"
MODEL_CANDIDATE_ROLES = frozenset(
    {"primary", "mechanism_alternative", "null_alias"}
)
AUTHORITY_ORDER = [
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
BLOCK_MEASUREMENT_PROGRAM_INVALID = (
    "BLOCK_FACTORFORGE_MEASUREMENT_PROGRAM_INVALID"
)
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
PUBLIC_MEASUREMENT_PROGRAM_FIELDS = frozenset(
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
        "search_policy",
    }
)
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
    "search_policy": frozenset(
        {
            "invariant_estimand",
            "allowed_model_or_estimator_variations",
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
) -> dict[str, Any]:
    if implementation_route not in IMPLEMENTATION_ROUTES:
        raise ValueError(
            f"unsupported measurement-program implementation route: "
            f"{implementation_route!r}"
        )
    route = implementation_route
    return {
        "contract_version": MEASUREMENT_PROGRAM_VERSION,
        "authority_order": list(AUTHORITY_ORDER),
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
        "search_policy": {
            "invariant_estimand": placeholder,
            "allowed_model_or_estimator_variations": [placeholder],
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


def validate_measurement_program(
    program: Any,
    *,
    placeholder: str | None = None,
    available_knowledge_node_ids: Iterable[str] = (),
    require_web_executable: bool = True,
) -> list[str]:
    reasons: list[str] = []
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
    reject_unexpected(
        program, PUBLIC_MEASUREMENT_PROGRAM_FIELDS, "measurement_program"
    )
    if program.get("contract_version") != MEASUREMENT_PROGRAM_VERSION:
        reasons.append("measurement_program.contract_version")
    if program.get("authority_order") != AUTHORITY_ORDER:
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
            minimum=2,
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
        if not isinstance(rejected, list) or not rejected:
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
        if not isinstance(candidates, list) or len(candidates) < 3:
            reasons.append("measurement_program.model_selection.candidate_models")
        else:
            selected_count = 0
            identities: set[str] = set()
            roles: set[str] = set()
            model_families: dict[str, str] = {}
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
                if role in roles:
                    reasons.append(f"{prefix}.candidate_role_duplicate")
                roles.add(role)
                model_families[role] = str(candidate.get("model_family") or "")
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
            if roles != MODEL_CANDIDATE_ROLES:
                reasons.append(
                    "measurement_program.model_selection.candidate_roles_incomplete"
                )
            if (
                model_families.get("primary")
                and model_families.get("primary")
                == model_families.get("mechanism_alternative")
            ):
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
            minimum=2,
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
            ("assumptions", 2),
            ("key_derivation_steps", 3),
            ("identification_gaps", 1),
            ("approximations", 1),
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

    return list(dict.fromkeys(reasons))
