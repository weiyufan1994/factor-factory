from __future__ import annotations

from copy import deepcopy

import pytest

from factor_factory import measurement_program as measurement_program_module
from factor_factory.measurement_program import (
    MEASUREMENT_PROGRAM_VERSION_V1,
    MEASUREMENT_PROGRAM_VERSION_V2,
    build_measurement_program_binding,
    build_strict_identity_contract,
    measurement_program_template,
    validate_measurement_program,
)
from factor_factory.mechanism_math.main_agent_memo import (
    _single_expectation_projection_suffix_is_safe,
    _validated_direct_code_measurement_program_projection_aliases,
)


PLACEHOLDER = "RESEARCHER_MUST_REPLACE"


def _filled_program(version: str) -> dict:
    program = measurement_program_template(
        placeholder=PLACEHOLDER,
        implementation_route="operator",
        contract_version=version,
    )

    def fill(value):
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if value == PLACEHOLDER:
            return "mechanism-specific auditable statement"
        return value

    program = fill(program)
    observation = program["observation_and_estimation"]
    observation.update(
        {
            "estimand": "conditional transient-impact decay payoff",
            "observation_map": "legal-time signed event path maps to transient impact state",
            "executable_formula_projection": "factor_t = estimate_transient_impact(event_path_t)",
            "estimator": "signed legal-time transient-impact kernel estimator",
        }
    )
    outcome = program["market_outcome_projection"]
    outcome.update(
        {
            "source_math_object": "transient price-impact state",
            "projection_equation_or_map": "expected_return_t1 = -decay(transient_impact_t)",
        }
    )
    candidates = program["model_selection"]["candidate_models"]
    candidates[0].update(
        {
            "model_family": "selected transient-impact response model",
            "mathematical_object": outcome["source_math_object"],
            "mechanism_equation_or_functional": "impact_t = constrained_flow_t - resilient_liquidity_t",
            "target_functional": observation["estimand"],
            "market_outcome_projection": outcome["projection_equation_or_map"],
            "observation_mapping": observation["observation_map"],
        }
    )
    candidates[1].update(
        {
            "model_family": "alternative permanent-information model",
            "mechanism_equation_or_functional": "price_change_t = permanent_information_t",
            "target_functional": "permanent information payoff",
            "market_outcome_projection": "no reversal after permanent information",
            "observation_mapping": "news-conditioned legal-time observation map",
        }
    )
    candidates[2].update(
        {
            "model_family": "null liquidity-volatility alias model",
            "mechanism_equation_or_functional": "score_t = alias_controls_t + noise_t",
            "target_functional": "zero incremental payoff after alias controls",
            "market_outcome_projection": "zero incremental after-cost return",
            "observation_mapping": "project score on legal-time alias controls",
        }
    )

    if version == MEASUREMENT_PROGRAM_VERSION_V2:
        equation = program["research_equation"]
        equation.update(
            {
                "equation_status": "behavioral_feedback",
                "equation_text": "constrained same-direction flow creates impact that decays with liquidity recovery",
                "assumptions": [
                    "the event path is observable before portfolio formation",
                    "liquidity recovery is slower than the triggering flow",
                ],
                "validity_scope": {
                    "market": "A-share equities",
                    "frequency": "intraday event to next-session payoff",
                    "regime": "tradable non-halted sessions",
                    "participant_structure": "constrained liquidity demanders face finite depth",
                },
                "symmetry_or_constraint": "balanced flow would create no persistent signed impact",
                "symmetry_breaking_mechanism": "one-sided constrained demand exhausts local depth",
                "participant_constraint_loop": {
                    "payer": "urgent liquidity demander",
                    "constraint": "execution urgency and finite displayed depth",
                    "repeat_mechanism": "new urgent orders repeatedly meet finite depth",
                    "failure_condition": "deep resilient liquidity absorbs the flow without transient impact",
                },
                "equation_quality": {
                    "evidence_tier": "report_specific_hypothesis",
                    "audit_basis": ["source report mechanism statement"],
                    "demotion_triggers": ["metric_signature_mismatch"],
                },
                "evidence_tier": "report_specific_hypothesis",
                "audit_basis": ["source report mechanism statement"],
                "demotion_triggers": ["metric_signature_mismatch"],
                "mathematical_object": candidates[0]["mathematical_object"],
                "observation_or_estimation_map": observation["observation_map"],
                "observable_estimator": observation["estimator"],
                "expected_metric_signature": [
                    "larger transient impact predicts stronger subsequent reversal"
                ],
                "falsification_tests": [
                    "control permanent-news and liquidity aliases before measuring decay"
                ],
                "kill_criteria": [
                    "kill if the effect is permanent or vanishes after alias controls"
                ],
            }
        )
    return program


def _validate(program: dict) -> list[str]:
    return validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=True,
    )


def test_v2_accepts_one_closed_classified_research_equation() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)

    assert _validate(program) == []
    assert program["authority_order"][0:3] == [
        "economic_hypothesis",
        "classified_research_equation",
        "open_math_tool_selection",
    ]
    binding = build_measurement_program_binding(program)
    assert binding["measurement_program_contract_version"] == (
        MEASUREMENT_PROGRAM_VERSION_V2
    )
    assert binding["mechanism_equation_or_functional"] == (
        program["model_selection"]["candidate_models"][0][
            "mechanism_equation_or_functional"
        ]
    )
    assert "equation_text" not in binding

    changed_relation = deepcopy(program)
    changed_relation["research_equation"]["equation_text"] += " under stress"
    changed_binding = build_measurement_program_binding(changed_relation)
    assert changed_binding["mechanism_equation_or_functional"] == binding[
        "mechanism_equation_or_functional"
    ]
    assert changed_binding["measurement_program_hash"] != binding[
        "measurement_program_hash"
    ]


def test_v2_direct_code_projection_binding_requires_validated_current_time_chain() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    program["implementation"].update(
        {
            "route": "direct_code",
            "web_execution_status": "model_only_requires_trusted_isolated_code_harness",
            "components": [
                {
                    "component_id": "unreversed_pressure",
                    "binding_role": "selected_primary_object",
                    "economic_claim": "legal-time event pressure is a candidate state",
                    "math_term_or_functional": "u=event_impact-event_relaxation",
                    "mechanism_role": "measure the selected primary object",
                    "observable_or_input": "same-day event path",
                    "input_fields": ["event_return", "event_volume"],
                    "transformation_or_estimator": "bounded event aggregation",
                    "implementation_binding": "direct-code event aggregator",
                    "input_measurement_semantics": "only observations through the current close",
                    "output_measurement_semantics": "u is a current stock-day state",
                    "information_time": "close d",
                    "preserved_information": "event timing and signed relaxation",
                    "discarded_information": "unobserved account identity",
                    "expected_metric_signature": "larger u has the registered conditional relation",
                    "ablation_test": "randomized event-time placebo",
                    "falsifier": "event response is indistinguishable from the placebo",
                    "knowledge_node_ids": [],
                },
                {
                    "component_id": "terminal_score",
                    "binding_role": "terminal_market_projection",
                    "economic_claim": "the terminal score maps current pressure to ranking",
                    "math_term_or_functional": "s=robust_rank(u)",
                    "mechanism_role": "project the primary object to a score",
                    "observable_or_input": "u",
                    "input_fields": ["u"],
                    "transformation_or_estimator": "cross-sectional robust rank",
                    "implementation_binding": "direct-code terminal score adapter",
                    "input_measurement_semantics": "current u only",
                    "output_measurement_semantics": "s is the current score",
                    "information_time": "score after close d, execution T+1",
                    "preserved_information": "score ordering",
                    "discarded_information": "within-score cardinal scale",
                    "expected_metric_signature": "the registered high-score relation",
                    "ablation_test": "identity score comparator",
                    "falsifier": "ranking fails the registered relation",
                    "knowledge_node_ids": [],
                },
            ],
        }
    )
    selected = program["model_selection"]["candidate_models"][0]
    selected["mathematical_object"] = "unreversed pressure state u"
    program["market_outcome_projection"]["source_math_object"] = (
        "unreversed pressure state u"
    )
    program["research_equation"]["mathematical_object"] = (
        "unreversed pressure state u"
    )
    selected["observation_mapping"] = program["observation_and_estimation"][
        "observation_map"
    ]
    assert validate_measurement_program(
        program,
        placeholder=PLACEHOLDER,
        require_web_executable=False,
    ) == []
    memo = {
        "formula": "u=event_impact-event_relaxation; s=robust_rank(u)",
        "math_hypothesis": {
            "selected_model_family": selected["model_family"],
            "mathematical_object": "measured_object_{i,t}=s_{i,t}",
            "observation_mapping": "measured_object_{i,t}=s_{i,t} from current u",
        },
        "mathematical_object_mapping": {
            "mathematical_object": "measured_object_{i,t}=s_{i,t}",
            "observation_mapping": "measured_object_{i,t}=s_{i,t} from current u",
            "component_links": ["pressure", "score"],
        },
        "formula_component_map": [
            {"component_id": "pressure", "formula_subexpression": "u=event_impact-event_relaxation"},
            {"component_id": "score", "formula_subexpression": "s=robust_rank(u)"},
        ],
    }
    spec = {
        "implementation_mode": "direct_code",
        "mechanism_conditioned_measurement_program": program,
        "canonical_spec": {
            "mechanism_conditioned_measurement_program": deepcopy(program),
        },
    }

    assert _validated_direct_code_measurement_program_projection_aliases(
        memo, spec
    ) == {"measured_object"}

    future_leak = deepcopy(memo)
    future_leak["math_hypothesis"]["observation_mapping"] = (
        "measured_object_{i,t}=s_{i,t} from future return"
    )
    future_leak["mathematical_object_mapping"]["observation_mapping"] = (
        "measured_object_{i,t}=s_{i,t} from future return"
    )
    assert _validated_direct_code_measurement_program_projection_aliases(
        future_leak, spec
    ) == set()

    missing_terminal = deepcopy(spec)
    missing_terminal["mechanism_conditioned_measurement_program"]["implementation"][
        "components"
    ][1]["binding_role"] = "unbound_component"
    missing_terminal["canonical_spec"]["mechanism_conditioned_measurement_program"] = deepcopy(
        missing_terminal["mechanism_conditioned_measurement_program"]
    )
    assert _validated_direct_code_measurement_program_projection_aliases(
        memo, missing_terminal
    ) == set()


def test_projection_grammar_accepts_high_factor_scores_without_decile_claim() -> None:
    assert _single_expectation_projection_suffix_is_safe(
        "E[r_{i,t+1:t+21}|F_t, measured_object_{i,t}] "
        "positive for high factor scores; entry t+1 vwap, exit t+21 vwap"
    )


def test_v1_shape_and_validation_remain_legacy_closed() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V1)
    assert "research_equation" not in program
    assert "classified_research_equation" not in program["authority_order"]
    assert _validate(program) == []

    program["research_equation"] = deepcopy(
        _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)["research_equation"]
    )
    reasons = _validate(program)
    assert any(
        reason.startswith("measurement_program.unexpected_fields:research_equation")
        for reason in reasons
    )


def test_v2_missing_or_open_research_equation_fails_closed() -> None:
    missing = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    del missing["research_equation"]
    assert "measurement_program.research_equation" in _validate(missing)

    open_shape = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    open_shape["research_equation"]["caller_selected_formula"] = "alternate"
    open_shape["research_equation"]["validity_scope"]["future_scope"] = "leak"
    open_shape["research_equation"]["participant_constraint_loop"][
        "ambient_actor"
    ] = "caller"
    open_shape["research_equation"]["equation_quality"]["caller_score"] = 100
    reasons = _validate(open_shape)
    assert any(
        reason.startswith("measurement_program.research_equation.unexpected_fields:")
        for reason in reasons
    )
    assert any(
        reason.startswith(
            "measurement_program.research_equation.validity_scope.unexpected_fields:"
        )
        for reason in reasons
    )
    assert any(
        reason.startswith(
            "measurement_program.research_equation.participant_constraint_loop.unexpected_fields:"
        )
        for reason in reasons
    )
    assert any(
        reason.startswith(
            "measurement_program.research_equation.equation_quality.unexpected_fields:"
        )
        for reason in reasons
    )


def test_v2_rejects_invalid_classification_and_evidence_vocabulary() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    equation = program["research_equation"]
    equation["equation_status"] = "proven_alpha_law"
    equation["evidence_tier"] = "caller_asserted_truth"
    equation["equation_quality"]["evidence_tier"] = "caller_asserted_truth"
    equation["demotion_triggers"] = ["never_demote"]
    equation["equation_quality"]["demotion_triggers"] = ["never_demote"]

    reasons = _validate(program)
    assert "measurement_program.research_equation.equation_status" in reasons
    assert "measurement_program.research_equation.evidence_tier_invalid" in reasons
    assert any("demotion_triggers_invalid" in reason for reason in reasons)


def test_v2_equation_quality_mirrors_cannot_diverge() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    program["research_equation"]["audit_basis"] = ["caller-selected second basis"]

    assert (
        "measurement_program.research_equation.audit_basis_quality_mirror_mismatch"
        in _validate(program)
    )


def test_v2_behavioral_sentence_cannot_be_relabelled_strict_identity() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    equation = program["research_equation"]
    equation["equation_status"] = "strict_identity"
    equation["evidence_tier"] = "logical_identity"
    equation["equation_quality"]["evidence_tier"] = "logical_identity"

    reasons = _validate(program)

    assert (
        "measurement_program.research_equation."
        "strict_identity_contract_missing"
    ) in reasons


def test_v2_irrelevant_identity_keyword_cannot_replace_closed_proof_object() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    equation = program["research_equation"]
    equation["equation_status"] = "strict_identity"
    equation["equation_text"] += (
        "; accounting window is merely the measurement interval"
    )
    equation["evidence_tier"] = "logical_identity"
    equation["equation_quality"]["evidence_tier"] = "logical_identity"

    assert (
        "measurement_program.research_equation."
        "strict_identity_contract_missing"
    ) in _validate(program)


def test_v2_strict_identity_requires_recomputable_closed_identity_contract() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    equation = program["research_equation"]
    lhs = "assets_t"
    rhs = "liabilities_t + equity_t"
    equation["equation_status"] = "strict_identity"
    equation["equation_text"] = f"{lhs} = {rhs}"
    equation["evidence_tier"] = "logical_identity"
    equation["equation_quality"]["evidence_tier"] = "logical_identity"
    equation["identity_contract"] = build_strict_identity_contract(
        identity_profile_id=(
            "BALANCE_SHEET_ASSETS_EQ_LIABILITIES_PLUS_EQUITY_V1"
        ),
        normalization_or_units="same reporting currency and timestamp",
        derivation_basis=["closed balance-sheet definitions"],
        proof_steps=["partition claims into liabilities and residual equity"],
        audit_basis=equation["audit_basis"],
    )

    assert _validate(program) == []

    tampered = deepcopy(program)
    tampered["research_equation"]["identity_contract"][
        "right_hand_side"
    ] = "liabilities_t"
    reasons = _validate(tampered)
    assert (
        "measurement_program.research_equation.identity_contract."
        "identity_expression_sha256_mismatch"
    ) in reasons
    assert (
        "measurement_program.research_equation.identity_contract."
        "equation_text_not_exact_profile_identity"
    ) in reasons


def test_v2_caller_cannot_relabel_predictive_relation_as_accounting_identity() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    equation = program["research_equation"]
    equation["equation_status"] = "strict_identity"
    equation["equation_text"] = (
        "next_return_t = investor_underreaction_t by caller assertion"
    )
    equation["evidence_tier"] = "logical_identity"
    equation["equation_quality"]["evidence_tier"] = "logical_identity"
    contract = build_strict_identity_contract(
        identity_profile_id=(
            "ACCOUNTING_PROFIT_EQ_REVENUE_MINUS_EXPENSE_V1"
        ),
        normalization_or_units="caller-selected units",
        derivation_basis=["caller says the relation is accounting"],
        proof_steps=["rename the behavioral relation"],
        audit_basis=equation["audit_basis"],
    )
    contract.update(
        {
            "left_hand_side": "next_return_t",
            "right_hand_side": "investor_underreaction_t",
            "canonical_form": (
                "next_return_t - investor_underreaction_t = 0"
            ),
        }
    )
    contract["identity_expression_sha256"] = (
        measurement_program_module._canonical_sha256(
            measurement_program_module._strict_identity_expression_preimage(
                contract
            )
        )
    )
    equation["identity_contract"] = contract

    reasons = _validate(program)

    assert (
        "measurement_program.research_equation.identity_contract."
        "profile_left_hand_side_mismatch"
    ) in reasons
    assert (
        "measurement_program.research_equation.identity_contract."
        "profile_right_hand_side_mismatch"
    ) in reasons


def test_v2_strict_identity_cannot_hitchhike_a_predictive_relation() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    equation = program["research_equation"]
    equation["equation_status"] = "strict_identity"
    equation["evidence_tier"] = "logical_identity"
    equation["equation_quality"]["evidence_tier"] = "logical_identity"
    equation["equation_text"] = (
        "profit_t = revenue_t - expense_t; therefore "
        "next_return_t = investor_underreaction_t"
    )
    equation["identity_contract"] = build_strict_identity_contract(
        identity_profile_id=(
            "ACCOUNTING_PROFIT_EQ_REVENUE_MINUS_EXPENSE_V1"
        ),
        normalization_or_units="same currency and reporting period",
        derivation_basis=["closed income-statement definitions"],
        proof_steps=["partition revenue into expense and residual profit"],
        audit_basis=equation["audit_basis"],
    )

    assert (
        "measurement_program.research_equation.identity_contract."
        "equation_text_not_exact_profile_identity"
    ) in _validate(program)


def test_v2_strict_identity_reuses_shared_quality_threshold() -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    equation = program["research_equation"]
    equation["equation_status"] = "strict_identity"
    equation["equation_text"] = (
        "the accounting identity balances assets against liabilities and equity"
    )
    equation["evidence_tier"] = "logical_identity"
    equation["equation_quality"]["evidence_tier"] = "logical_identity"
    equation["audit_basis"] = []
    equation["equation_quality"]["audit_basis"] = []

    reasons = _validate(program)

    assert (
        "measurement_program.research_equation.strict_identity_quality_below_60"
        in reasons
    )


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        (
            "mathematical_object",
            "unbound alternate object",
            "measurement_program.research_equation.mathematical_object_selected_model_mismatch",
        ),
        (
            "observation_or_estimation_map",
            "unbound alternate observation map",
            "measurement_program.research_equation.observation_or_estimation_map_global_mismatch",
        ),
        (
            "observable_estimator",
            "unbound alternate estimator",
            "measurement_program.research_equation.observable_estimator_global_mismatch",
        ),
    ],
)
def test_v2_equation_measurement_bindings_are_exact(
    field: str,
    replacement: str,
    reason: str,
) -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    program["research_equation"][field] = replacement

    assert reason in _validate(program)


@pytest.mark.parametrize(
    ("source_path", "reason"),
    [
        (
            ("market_outcome_projection", "projection_equation_or_map"),
            "measurement_program.research_equation.equation_text_equals_market_outcome_projection",
        ),
        (
            ("observation_and_estimation", "executable_formula_projection"),
            "measurement_program.research_equation.equation_text_equals_executable_formula_projection",
        ),
    ],
)
def test_v2_classified_relation_cannot_alias_payoff_or_executable_formula(
    source_path: tuple[str, str],
    reason: str,
) -> None:
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    section, field = source_path
    program["research_equation"]["equation_text"] = program[section][field]

    assert reason in _validate(program)


def test_unknown_contract_version_is_not_coerced_to_v1_or_v2() -> None:
    with pytest.raises(ValueError, match="unsupported measurement-program contract"):
        measurement_program_template(
            placeholder=PLACEHOLDER,
            contract_version="factorforge_mechanism_conditioned_measurement_program_v3",
        )

    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V1)
    program["contract_version"] = "factorforge_mechanism_conditioned_measurement_program_v3"
    assert "measurement_program.contract_version" in _validate(program)

    program["contract_version"] = {"caller_selected": "v2"}
    assert "measurement_program.contract_version" in _validate(program)


def test_ultimate_public_projection_preserves_and_revalidates_v2_equation() -> None:
    from factor_factory.console.ultimate_reader import (
        _public_measurement_program_copy,
        _research_notebooks,
    )

    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    projected = _public_measurement_program_copy(program)

    assert projected["research_equation"] == program["research_equation"]
    assert validate_measurement_program(
        projected,
        require_web_executable=False,
    ) == []

    _research_notebook, math_notebook = _research_notebooks(
        main_agent_memo={},
        research_method={},
        economic_game={},
        math_mechanism={},
        measurement_program=program,
    )
    assert math_notebook["research_equation"] == program["research_equation"]


def test_ultimate_v2_projection_fails_closed_and_v1_shape_is_unchanged() -> None:
    from factor_factory.console.ultimate_reader import (
        _public_measurement_program_copy,
        _research_notebooks,
    )

    invalid_v2 = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    invalid_v2["research_equation"]["caller_selected_claim"] = "alternate"
    assert _public_measurement_program_copy(invalid_v2) == {}

    v1 = _filled_program(MEASUREMENT_PROGRAM_VERSION_V1)
    projected_v1 = _public_measurement_program_copy(v1)
    assert "research_equation" not in projected_v1
    assert "return_path" not in projected_v1["evaluation_design"][
        "portfolio_contract"
    ]
    assert projected_v1["contract_version"] == MEASUREMENT_PROGRAM_VERSION_V1
    _research_notebook, math_notebook = _research_notebooks(
        main_agent_memo={},
        research_method={},
        economic_game={},
        math_mechanism={},
        measurement_program=v1,
    )
    assert "research_equation" not in math_notebook
