from __future__ import annotations

from copy import deepcopy

from factor_factory.measurement_program import (
    KNOWLEDGE_AUTHORITY,
    MATH_AUTHORITY,
    measurement_program_template,
    validate_measurement_program,
)


PLACEHOLDER = "RESEARCHER_MUST_REPLACE"


def _filled_program(route: str = "operator") -> dict:
    program = measurement_program_template(
        placeholder=PLACEHOLDER,
        implementation_route=route,
    )

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if value == PLACEHOLDER:
            return "auditable mechanism-specific statement"
        return value

    filled = replace(program)
    candidates = filled["model_selection"]["candidate_models"]
    candidates[0]["model_family"] = "selected transient-state model"
    candidates[1]["model_family"] = "alternative permanent-state model"
    candidates[2]["model_family"] = "null alias-only model"
    selected_target = filled["observation_and_estimation"]["estimand"]
    selected_projection = filled["market_outcome_projection"][
        "projection_equation_or_map"
    ]
    selected_observation = filled["observation_and_estimation"]["observation_map"]
    candidates[0].update(
        {
            "mechanism_equation_or_functional": "primary_object_t = primary_mechanism(inputs_t)",
            "target_functional": selected_target,
            "market_outcome_projection": selected_projection,
            "observation_mapping": selected_observation,
        }
    )
    candidates[1].update(
        {
            "mechanism_equation_or_functional": "alternative_object_t = alternative_mechanism(inputs_t)",
            "target_functional": "alternative mechanism estimand",
            "market_outcome_projection": "alternative object maps to a distinct signed payoff",
            "observation_mapping": "alternative legal-time observation map",
        }
    )
    candidates[2].update(
        {
            "mechanism_equation_or_functional": "score_t = alias_controls_t + noise_t",
            "target_functional": "incremental payoff after alias controls",
            "market_outcome_projection": "null predicts zero incremental after-cost payoff",
            "observation_mapping": "project score on known aliases at legal time t",
        }
    )
    return filled


def test_specialized_audits_can_be_empty_without_forcing_dimensions() -> None:
    program = _filled_program()
    program["applicable_audits"] = {
        "selection_rule": "select only audits justified by the mechanism",
        "selected": [],
        "rejected": [],
    }

    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    ) == []


def test_selected_specialized_audit_requires_record_and_falsifier() -> None:
    program = _filled_program()
    program["applicable_audits"]["selected"] = [
        {
            "audit_family": "dimensional_analysis",
            "rationale": "cash-flow and market-value units enter one ratio",
            "audit_record": "currency units cancel after per-share normalization",
            "falsifier": "the signal changes under a pure currency-unit conversion",
        }
    ]

    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    ) == []

    del program["applicable_audits"]["selected"][0]["audit_record"]
    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )
    assert "measurement_program.applicable_audits.selected[0].audit_record" in reasons


def test_measurement_program_keeps_math_authoritative_and_knowledge_advisory() -> None:
    program = _filled_program()

    assert MATH_AUTHORITY == "economic_hypothesis_and_math_mechanism"
    assert program["knowledge_role"]["authority"] == KNOWLEDGE_AUTHORITY
    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    ) == []


def test_selected_mathematical_object_must_bind_market_projection_source() -> None:
    program = _filled_program()
    program["market_outcome_projection"]["source_math_object"] = (
        program["model_selection"]["candidate_models"][0]["mathematical_object"]
    )
    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    ) == []

    program["market_outcome_projection"]["source_math_object"] = (
        "unrelated stochastic state"
    )
    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )
    assert (
        "measurement_program.model_selection.selected_model_"
        "mathematical_object_global_mismatch"
    ) in reasons


def test_math_tool_space_is_open_and_dcf_does_not_require_a_stochastic_core_model() -> None:
    program = _filled_program()
    program["math_tool_selection"].update(
        {
            "candidate_tool_families": [
                "discounted cash-flow valuation",
                "residual-income accounting identity",
                "structural causal model",
            ],
            "selected_tool_families": ["discounted cash-flow valuation"],
            "selection_rationale": "cash-flow timing and discount-rate assumptions define intrinsic value directly",
            "rejected_tool_families": [
                {
                    "tool_family": "stochastic price process",
                    "reason": "not required for the core intrinsic-value derivation",
                }
            ],
        }
    )
    program["market_outcome_projection"].update(
        {
            "projection_kind": "discounted_cash_flow_intrinsic_value_to_price_gap",
            "source_math_object": "present value of forecast free cash flows and terminal value",
            "traded_quantity": "intrinsic-value-to-market-price gap and expected convergence payoff",
            "affected_payoff_or_distribution_terms": [
                "intrinsic value",
                "valuation gap",
                "convergence payoff",
            ],
            "projection_equation_or_map": "V_t=sum_k FCF_t+k/(1+WACC)^k; alpha_t=V_t/P_t-1",
            "link_to_observation_equation": "reported fundamentals map to normalized FCF inputs at their legal publication time",
            "falsifier": "the valuation gap has no after-cost convergence payoff under cash-flow and discount-rate revisions",
        }
    )
    program["model_selection"]["candidate_models"][0][
        "mathematical_object"
    ] = program["market_outcome_projection"]["source_math_object"]
    program["model_selection"]["candidate_models"][0][
        "market_outcome_projection"
    ] = program["market_outcome_projection"]["projection_equation_or_map"]

    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    ) == []


def test_model_selection_requires_exactly_one_selected_candidate() -> None:
    program = _filled_program()
    program["model_selection"]["candidate_models"][1]["selected"] = True

    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )

    assert "measurement_program.model_selection.exactly_one_selected" in reasons


def test_model_selection_requires_mechanism_alternative_and_null_alias() -> None:
    program = _filled_program()
    program["model_selection"]["candidate_models"] = program["model_selection"][
        "candidate_models"
    ][:2]

    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )

    assert "measurement_program.model_selection.candidate_models" in reasons


def test_model_selection_rejects_identical_primary_and_alternative_models() -> None:
    program = _filled_program()
    candidates = program["model_selection"]["candidate_models"]
    candidates[1]["model_family"] = candidates[0]["model_family"]

    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )

    assert (
        "measurement_program.model_selection.alternative_model_not_distinct"
        in reasons
    )


def test_each_candidate_requires_core_mechanism_equation_separate_from_projection() -> None:
    program = _filled_program()
    primary = program["model_selection"]["candidate_models"][0]
    primary["mechanism_equation_or_functional"] = (
        "V_t=sum_k FCF_t+k/(1+WACC_t)^k"
    )
    program["market_outcome_projection"]["projection_equation_or_map"] = (
        "E[r_t+1|F_t] increases with V_t/P_t-1 after costs"
    )
    primary["market_outcome_projection"] = program["market_outcome_projection"][
        "projection_equation_or_map"
    ]

    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    ) == []

    del primary["mechanism_equation_or_functional"]
    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )
    assert (
        "measurement_program.model_selection.candidate_models[0]."
        "mechanism_equation_or_functional"
    ) in reasons


def test_each_candidate_requires_own_estimand_projection_and_observation_map() -> None:
    for field in (
        "target_functional",
        "market_outcome_projection",
        "observation_mapping",
    ):
        program = _filled_program()
        del program["model_selection"]["candidate_models"][1][field]

        reasons = validate_measurement_program(
            program,
            placeholder=PLACEHOLDER,
            require_web_executable=True,
        )

        assert (
            "measurement_program.model_selection.candidate_models[1]." + field
        ) in reasons


def test_mechanism_alternative_accepts_open_optimal_transport_model_when_bound() -> None:
    program = _filled_program()
    alternative = program["model_selection"]["candidate_models"][1]
    alternative.update(
        {
            "model_family": "pathwise optimal-transport imbalance geometry",
            "mathematical_object": "transport cost between lawful buy- and sell-pressure measures",
            "mechanism_equation_or_functional": "W_c(mu_t,nu_t)=inf_pi integral c(x,y)dpi_t(x,y)",
            "target_functional": "legal-time pressure transport cost W_c(mu_t,nu_t)",
            "market_outcome_projection": "larger constrained transport cost predicts a signed liquidity-rebalancing payoff",
            "observation_mapping": "construct mu_t and nu_t from legal-time pressure measures and solve the transport problem",
        }
    )

    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    ) == []


def test_template_rejects_unknown_implementation_route() -> None:
    try:
        measurement_program_template(
            placeholder=PLACEHOLDER,
            implementation_route="automatic_fallback",
        )
    except ValueError as exc:
        assert "unsupported measurement-program implementation route" in str(exc)
    else:
        raise AssertionError("unknown implementation route must not fall back")


def test_direct_code_is_a_valid_research_route_but_not_yet_a_web_execution_route() -> None:
    program = _filled_program("direct_code")

    research_reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=False,
    )
    web_reasons = validate_measurement_program(
        deepcopy(program),
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )

    assert research_reasons == []
    assert (
        "measurement_program.implementation.web_route_requires_trusted_harness"
        in web_reasons
    )
    assert "measurement_program.implementation.web_execution_status" in web_reasons


def test_knowledge_cannot_be_promoted_to_mechanism_authority() -> None:
    program = _filled_program()
    program["knowledge_role"]["authority"] = "historical_performance_decides"

    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )

    assert "measurement_program.knowledge_role.authority" in reasons


def test_public_derivation_rejects_private_reasoning_fields() -> None:
    program = _filled_program()
    program["public_derivation_record"]["private_chain_of_thought"] = (
        "hidden scratch reasoning"
    )

    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )

    assert any(
        reason.startswith(
            "measurement_program.public_derivation_record.unexpected_fields:"
        )
        for reason in reasons
    )


def test_every_measurement_section_rejects_private_reasoning_fields() -> None:
    program = _filled_program()
    program["model_selection"]["private_chain_of_thought"] = "hidden"
    program["implementation"]["components"][0]["scratchpad"] = "hidden"

    reasons = validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )

    assert any(
        reason.startswith("measurement_program.model_selection.unexpected_fields:")
        for reason in reasons
    )
    assert any(
        reason.startswith(
            "measurement_program.implementation.components[0].unexpected_fields:"
        )
        for reason in reasons
    )
