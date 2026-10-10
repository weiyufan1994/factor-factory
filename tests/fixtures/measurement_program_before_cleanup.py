"""Frozen a5aea7cc validator for refactor parity; test-only, not a second runtime."""
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
        flexible_local_profile(compatibility_profile, scope)
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
