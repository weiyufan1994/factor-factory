from __future__ import annotations

from copy import deepcopy

from factor_factory.formula.parser import parse_formula
from factor_factory.measurement_program import (
    MEASUREMENT_PROGRAM_VERSION_V1,
    measurement_program_template,
    validate_measurement_program,
)
from factor_factory.mechanism_math.main_agent_memo import (
    _bound_measured_object_projection_aliases,
    _formula_source_is_fully_represented,
    _validated_direct_code_measurement_program_projection_aliases,
    _validated_v1_direct_code_measurement_program_projection_aliases,
    validate_main_agent_mechanism_memo,
)


FORMULA = (
    "PF=SD20(sum_m[skew_cs(d_m)>0]*log1p(d_i,m)); "
    "VV=SD20(z_cs(SD_segments(prod_m_in_segment(1+r_i,m)-1))); "
    "score=-(z_cs(PF)+z_cs(VV))/2."
)
OBSERVATION = (
    "Completed minute returns and volume -> daily PF and VV -> common-universe "
    "z-scores -> negative equal-weight score."
)
PROJECTION = "E[r_(t+h)-r_t | F_t]=conditional_price_pressure_payoff."
MEMO_PROJECTION = (
    "E[r_{i,t+20}|F_t, measured_object_{i,t}] positive for high factor scores; "
    "entry t+1 vwap, exit t+20 vwap"
)
METHOD_NODES = ["node::method::conditional", "node::method::transient"]


def _filled(value):
    if isinstance(value, dict):
        return {key: _filled(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_filled(item) for item in value]
    return "auditable frozen statement" if value == "RESEARCHER_MUST_REPLACE" else value


def _program() -> dict:
    program = _filled(
        measurement_program_template(
            placeholder="RESEARCHER_MUST_REPLACE",
            implementation_route="direct_code",
            contract_version=MEASUREMENT_PROGRAM_VERSION_V1,
        )
    )
    program["observation_and_estimation"].update(
        {
            "estimand": "conditional executable return association",
            "observation_map": OBSERVATION,
            "executable_formula_projection": FORMULA,
            "estimator": "frozen PFVV direct-code reconstruction",
        }
    )
    program["market_outcome_projection"].update(
        {
            "source_math_object": "transient price-pressure state",
            "projection_equation_or_map": PROJECTION,
        }
    )
    selected = program["model_selection"]["candidate_models"][0]
    program["model_selection"]["selection_target"] = (
        "conditional executable return association"
    )
    selected.update(
        {
            "model_family": "temporary price pressure",
            "mathematical_object": "transient price-pressure state",
            "mechanism_equation_or_functional": "p_t=v_t+b_t",
            "target_functional": "conditional executable return association",
            "market_outcome_projection": PROJECTION,
            "observation_mapping": OBSERVATION,
        }
    )
    program["model_selection"]["candidate_models"][1].update(
        {
            "model_family": "permanent information arrival",
            "mathematical_object": "permanent value innovation",
            "mechanism_equation_or_functional": "v_t=v_tminus1+information_t",
            "target_functional": "persistent information payoff",
            "market_outcome_projection": "price response persists after information arrival",
            "observation_mapping": "legal-time information-path observation map",
        }
    )
    program["model_selection"]["candidate_models"][2].update(
        {
            "model_family": "volatility liquidity alias",
            "mathematical_object": "volatility liquidity control state",
            "mechanism_equation_or_functional": "score_t=liquidity_t+volatility_t+noise_t",
            "target_functional": "zero residual payoff after controls",
            "market_outcome_projection": "no residual return after volatility liquidity controls",
            "observation_mapping": "legal-time volatility and liquidity control map",
        }
    )
    components = []
    for component_id, formula, observable, nodes in (
        ("PF", "PF_i,t=SD20(sum_selected_minutes(log1p(d_i,m)))", "completed minute-return cross-section", [METHOD_NODES[0]]),
        ("VV", "VV_i,t=SD20(z_cs(segment_return_sd_i,t))", "completed minute price-volume path", METHOD_NODES),
        ("COMPOSITE", "score_i,t=-(z_cs(PF_i,t)+z_cs(VV_i,t))/2", "common finite PF and VV cross-section", []),
    ):
        component = deepcopy(program["implementation"]["components"][0])
        component.update(
            {
                "component_id": component_id,
                "binding_role": "source_component",
                "math_term_or_functional": formula,
                "observable_or_input": observable,
                "knowledge_node_ids": nodes,
            }
        )
        components.append(component)
    program["implementation"]["components"] = components
    assert validate_measurement_program(
        program,
        available_knowledge_node_ids=set(METHOD_NODES),
        require_web_executable=False,
    ) == []
    return program


def _memo(program: dict) -> dict:
    components = program["implementation"]["components"]
    return {
        "formula": FORMULA,
        "math_hypothesis": {
            "mathematical_object": "measured_object_{i,t}=score_{i,t}",
            "observation_mapping": OBSERVATION,
            "market_outcome_projection": MEMO_PROJECTION,
        },
        "mathematical_object_mapping": {
            "mathematical_object": "measured_object_{i,t}=score_{i,t}",
            "observation_mapping": OBSERVATION,
            "component_links": [component["component_id"] for component in components],
        },
        "formula_component_map": [
            {
                "component_id": component["component_id"],
                "formula_subexpression": component["math_term_or_functional"],
                "observable_estimator": component["observable_or_input"],
            }
            for component in components
        ],
    }


def _complete_public_memo(program: dict) -> dict:
    memo = _memo(program)
    signature = {
        "rank_ic": "rank IC must have the frozen positive direction for the PF VV score",
        "long_side": "the high-score long basket is the declared executable payoff",
        "cost_adjusted": "the long basket must remain positive after the frozen cost model",
        "monotonicity": "group ordering is diagnostic and cannot repair the fixed score",
        "turnover": "monthly rebalancing turnover must remain consistent with the fixed route",
    }
    for component in memo["formula_component_map"]:
        component.update(
            {
                "operators": ["direct_code"],
                "economic_state": "frozen direct-code component state",
                "mathematical_object": "current PF VV score component",
                "expected_role": "contribute only through the frozen source component assembly",
                "metric_link": "the fixed component mapping is evaluated before any model mutation",
            }
        )
    memo.update(
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "report_id": "V1_DIRECT_CODE_SYNTHETIC",
            "factor_id": "V1_DIRECT_CODE_SYNTHETIC",
            "research_id": "v1_direct_code_synthetic",
            "producer": "current_main_agent",
            "agent_authorship": {
                "authoring_mode": "current_agent_freeform",
                "agent_role": "main_agent",
                "answered_without_deterministic_template": True,
            },
            "formula_understanding": {"formula_features": {"fields": ["open", "close", "vol"], "operators": ["direct_code"]}},
            "mechanism_qa": {
                "mathematical_object_answer": "The PF VV score is a current measured object built from completed minute paths, so the formula retains PF, VV, skew gating, and common-universe score assembly without a future return input.",
                "economic_hypothesis_answer": "This synthetic fixture treats temporary price pressure as an unverified hypothesis; counterparties may pay only if completed intraday dispersion is related to later executable reversal, which remains an empirical question.",
                "math_model_answer": "The selected temporary pressure model is a conditional interpretation, not an identified law: PF and VV are direct-code observations and the score does not itself identify the latent pressure process.",
                "payer_answer": "Liquidity demanders and short-horizon extrapolators are a tentative payer hypothesis; it fails if the fixed high-score long basket lacks the predeclared executable payoff after costs.",
                "payoff_answer": "The registered payoff is the explicit future executable return conditional on measured_object at time t, not a same-time price and not a claim that this fixture proves the return law.",
                "observation_mapping_answer": "Completed minute returns and volume construct PF and VV, then their common-universe z-score assembly constructs score; the observation uses no future minute or return as an input.",
                "metric_signature_answer": "Use fixed-direction Rank IC, high-score long-side gross and net return, turnover, and group diagnostics; none may select a new formula or reverse the registered score sign.",
                "falsification_answer": "Reject the temporary-pressure interpretation if the fixed PF VV score fails its executable long-side payoff, if component ablations show no distinct contribution, or if current-time mappings are replaced by a future label.",
            },
            "economic_hypothesis": {
                "return_source_class": "mixed",
                "payer_or_counterparty": "tentative liquidity demanders and short-horizon extrapolators",
                "why_they_pay": "their temporary price pressure may reverse after the completed signal time",
                "necessary_market_structure": "the completed minute cross-section must precede the declared executable payoff",
            },
            "math_hypothesis": {
                **memo["math_hypothesis"],
                "selected_model_family": "temporary price pressure",
                "why_this_model": "it is the frozen selected model used for the direct-code observation, not an identified causal law",
                "why_not_generic_template": "the PF VV component chain is frozen and cannot be replaced by an operator template",
                "mechanism_equation_or_functional": "price_t=value_t+pressure_t; measured_object_{i,t}=score_{i,t}",
                "target_functional": MEMO_PROJECTION,
                "expected_metric_signature": signature,
            },
            "math_model_selection": {
                "model_family": "temporary price pressure",
                "mechanism_equation_or_functional": "price_t=value_t+pressure_t; measured_object_{i,t}=score_{i,t}",
                "model_mutation": "no mutation is authorized by this synthetic binding fixture",
            },
            "payer": {
                "payer_or_counterparty": "tentative liquidity demanders and short-horizon extrapolators",
                "why_they_pay": "temporary price pressure may reverse after completed observations",
                "necessary_market_structure": "the signal close precedes the registered executable return",
            },
            "expected_metric_signature": signature,
            "falsification_tests": [
                "Reject if the fixed high-score long payoff fails after costs without changing the formula.",
                "Reject if PF or VV components cannot be mapped to the frozen direct-code program.",
            ],
            "evidence_comparison": {
                "observed_metrics": {"rank_ic_mean": 0.0},
                "mechanism_supported": "not established by this synthetic binding fixture",
                "contradictions": [],
                "revision_implications": ["no research conclusion is implied by this validation fixture"],
                "kill_criteria_triggered": [],
            },
            "operator_claim_consistency": {
                "claims_correlation_or_covariance": False,
                "formula_has_correlation_or_covariance_operator": False,
                "claims_dependence_without_operator_justification": False,
                "explicit_dependence_justification": "",
                "has_sign_or_threshold": False,
                "sign_threshold_discussion_present": False,
                "has_volume_ratio": False,
                "volume_ratio_participation_discussion_present": False,
                "has_additive_rank_raw_ratio": False,
                "additive_scale_commensurability_discussion_present": False,
            },
            "council_questions": ["Does this binding leave the temporary-pressure claim explicitly unvalidated?"],
            "canonical_write_permission": False,
            "execution_allowed_by_default": False,
        }
    )
    return memo


def _spec(program: dict) -> dict:
    learning = {
        "factor_knowledge_context": {
            "nodes": [{"id": node} for node in METHOD_NODES],
        }
    }
    return {
        "implementation_mode": "direct_code",
        "canonical_spec": {
            "formula_text": FORMULA,
            "implementation_mode": "direct_code",
            "mechanism_conditioned_measurement_program": deepcopy(program),
            "learning_and_innovation": deepcopy(learning),
        },
        "mechanism_conditioned_measurement_program": deepcopy(program),
        "learning_and_innovation": learning,
    }


def test_v1_pfvv_style_direct_code_requires_a_dedicated_projection_path() -> None:
    program = _program()
    memo = _memo(program)
    spec = _spec(program)

    # This frozen multi-assignment declaration is deliberately not Formula-IR.
    assert _formula_source_is_fully_represented(FORMULA) is False
    assert parse_formula(FORMULA).get("parse_status") == "failed"
    # The existing V2-only helper proves the prior V1 incompatibility.
    assert _validated_direct_code_measurement_program_projection_aliases(memo, spec) == set()
    assert _validated_v1_direct_code_measurement_program_projection_aliases(memo, spec) == {"measured_object"}
    assert _bound_measured_object_projection_aliases(memo, spec) == {"measured_object"}


def test_v1_direct_code_rejects_formula_component_future_knowledge_and_copy_drift() -> None:
    program = _program()
    memo = _memo(program)
    spec = _spec(program)

    missing_link = deepcopy(memo)
    missing_link["mathematical_object_mapping"]["component_links"].pop()
    assert _validated_v1_direct_code_measurement_program_projection_aliases(missing_link, spec) == set()

    extra_component = deepcopy(memo)
    extra_component["formula_component_map"].append(
        {"component_id": "EXTRA", "formula_subexpression": "x_i,t=0", "observable_estimator": "invented"}
    )
    extra_component["mathematical_object_mapping"]["component_links"].append("EXTRA")
    assert _validated_v1_direct_code_measurement_program_projection_aliases(extra_component, spec) == set()

    drifted_component = deepcopy(memo)
    drifted_component["formula_component_map"][0]["formula_subexpression"] = "PF_i,t=0"
    assert _validated_v1_direct_code_measurement_program_projection_aliases(drifted_component, spec) == set()

    future_pollution = deepcopy(memo)
    future_pollution["math_hypothesis"]["observation_mapping"] = "measured_object_{i,t}=future_score_{i,t+1}"
    future_pollution["mathematical_object_mapping"]["observation_mapping"] = future_pollution["math_hypothesis"]["observation_mapping"]
    assert _validated_v1_direct_code_measurement_program_projection_aliases(future_pollution, spec) == set()

    unauthorized = deepcopy(spec)
    unauthorized["learning_and_innovation"]["factor_knowledge_context"]["nodes"] = []
    unauthorized["canonical_spec"]["learning_and_innovation"] = deepcopy(unauthorized["learning_and_innovation"])
    assert _validated_v1_direct_code_measurement_program_projection_aliases(memo, unauthorized) == set()

    mismatched_copy = deepcopy(spec)
    mismatched_copy["canonical_spec"]["mechanism_conditioned_measurement_program"]["observation_and_estimation"]["executable_formula_projection"] = "score=0"
    assert _validated_v1_direct_code_measurement_program_projection_aliases(memo, mismatched_copy) == set()


def test_v1_direct_code_full_public_memo_uses_measured_object_conditioned_payoff() -> None:
    program = _program()
    spec = _spec(program)
    memo = _complete_public_memo(program)

    assert validate_main_agent_mechanism_memo(memo, spec) == []

    wrong_object = deepcopy(memo)
    wrong_object["math_hypothesis"]["mathematical_object"] = "other_object_{i,t}=score_{i,t}"
    wrong_object["mathematical_object_mapping"]["mathematical_object"] = "other_object_{i,t}=score_{i,t}"
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in validate_main_agent_mechanism_memo(wrong_object, spec)

    future_conditioning = deepcopy(memo)
    future_conditioning["math_hypothesis"]["market_outcome_projection"] = "E[r_{i,t+20}|F_t, measured_object_{i,t+1}] positive for high factor scores; entry t+1 vwap, exit t+20 vwap"
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in validate_main_agent_mechanism_memo(future_conditioning, spec)

    tail_payoff = deepcopy(memo)
    tail_payoff["math_hypothesis"]["market_outcome_projection"] = MEMO_PROJECTION + "; E[r_{i,t+40}|F_t, measured_object_{i,t}] positive"
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in validate_main_agent_mechanism_memo(tail_payoff, spec)
