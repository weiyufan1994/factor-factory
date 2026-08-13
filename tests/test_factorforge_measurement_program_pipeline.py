from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from factor_factory.measurement_program import (
    BLOCK_MEASUREMENT_PROGRAM_INVALID,
    build_measurement_program_binding,
    measurement_program_template,
    validate_measurement_program,
)
from factor_factory.mechanism_math.formula_specific import (
    _normalize_baseline_model_family,
    _select_baseline_model,
    validate_formula_specific_derivation,
)
from factor_factory.mechanism_math.main_agent_memo import (
    formula_specific_derivation_from_main_agent_memo,
    normalize_derivation_model_family,
    validate_main_agent_mechanism_memo,
)
from factor_factory.research_conjecture import validate_research_conjecture
from factor_factory.revision_council.validator import (
    validate_revision_council_proposal,
)
from scripts.run_factorforge_research_protocol_smoke import valid_conjecture
from scripts.step12_intake_common import (
    attach_agent_authored_measurement_program,
    build_canonical_formula_step1,
)
from skills.factor_forge_step5.modules.case_builder import build_factor_case_master
from skills.factor_forge_step1.modules.report_ingestion.intake.structured_intake_contract import (
    StructuredIntake,
)
from skills.factor_forge_step1.modules.report_ingestion.merge.merge_to_alpha_idea_master import (
    merge_to_alpha_idea_master,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEP2 = _load_script(
    "factorforge_step2_measurement_pipeline",
    "skills/factor-forge-step2/scripts/run_step2.py",
)
STEP1_VALIDATOR = _load_script(
    "factorforge_step1_measurement_pipeline_validator",
    "skills/factor-forge-step1/scripts/validate_step1.py",
)
STEP3 = _load_script(
    "factorforge_step3_measurement_pipeline",
    "skills/factor-forge-step3/scripts/run_step3.py",
)
STEP6 = _load_script(
    "factorforge_step6_measurement_pipeline",
    "skills/factor-forge-step6/scripts/run_step6.py",
)
COUNCIL_PACKET = _load_script(
    "factorforge_revision_council_measurement_pipeline",
    "skills/factor-forge-step6/scripts/build_revision_council_packet.py",
)
COUNCIL_RUN = _load_script(
    "factorforge_revision_council_measurement_pipeline_runner",
    "skills/factor-forge-step6/scripts/run_revision_council.py",
)
AGENTIC_VALIDATOR = _load_script(
    "factorforge_agentic_council_measurement_pipeline_validator",
    "skills/factor-forge-step6/scripts/validate_agentic_council_result.py",
)
AGENTIC_MOCK = _load_script(
    "factorforge_agentic_council_measurement_pipeline_mock",
    "skills/factor-forge-step6/scripts/run_agentic_council_local_mock.py",
)


def _program(route: str = "operator") -> dict:
    placeholder = "RESEARCHER_MUST_REPLACE"
    program = measurement_program_template(
        placeholder=placeholder,
        implementation_route=route,
    )

    def fill(value):
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if value == placeholder:
            return "mechanism-specific auditable statement"
        return value

    result = fill(program)
    result["model_selection"]["candidate_models"][0]["model_family"] = (
        "selected structural state model"
    )
    result["model_selection"]["candidate_models"][1]["model_family"] = (
        "alternative causal model"
    )
    result["model_selection"]["candidate_models"][2]["model_family"] = (
        "null alias-only model"
    )
    candidates = result["model_selection"]["candidate_models"]
    candidates[0].update(
        {
            "mechanism_equation_or_functional": "primary_object_t = primary_mechanism(inputs_t)",
            "target_functional": result["observation_and_estimation"]["estimand"],
            "market_outcome_projection": result["market_outcome_projection"]["projection_equation_or_map"],
            "observation_mapping": result["observation_and_estimation"]["observation_map"],
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
    return result


def test_step1_step2_step3_preserve_one_exact_measurement_program() -> None:
    program = _program()
    assert validate_measurement_program(
        program,
        require_web_executable=False,
    ) == []
    aim = {
        "implementation_mode": "operator",
        "mechanism_conditioned_measurement_program": deepcopy(program),
        "research_discipline": {
            "mechanism_conditioned_measurement_program": deepcopy(program),
        },
    }
    copied = STEP2.validated_step1_measurement_program(
        aim=aim,
        primary={"mechanism_conditioned_measurement_program": deepcopy(program)},
        implementation_mode="operator",
    )
    fsm = {
        "implementation_mode": "operator",
        "mechanism_conditioned_measurement_program": copied,
        "canonical_spec": {
            "mechanism_conditioned_measurement_program": deepcopy(copied),
        },
    }
    handoff = {
        "mechanism_conditioned_measurement_program": deepcopy(copied),
    }

    step3_program = STEP3.validated_measurement_program_for_step3(
        fsm,
        handoff,
        implementation_mode="operator",
    )

    assert step3_program == program


def test_pdf_step1_preserves_agent_program_and_chief_resolves_conflicts() -> None:
    program = _program("direct_code")
    primary = StructuredIntake(
        report_id="PDF_PROGRAM_HANDOFF",
        final_factor={"name": "pdf factor"},
        mechanism_conditioned_measurement_program=deepcopy(program),
    )
    challenger = StructuredIntake(
        report_id="PDF_PROGRAM_HANDOFF",
        final_factor={"name": "pdf factor"},
        mechanism_conditioned_measurement_program=deepcopy(program),
    )
    chief = {
        "final_factor": {
            "name": "pdf factor",
            "economic_logic": "legal-time observables measure a mechanism-specific object",
            "behavioral_logic": "the declared counterparty updates with delay",
            "causal_chain": "observation to object to payoff",
            "what_must_be_true": ["the observation map identifies the object"],
            "what_would_break_it": ["the controlled payoff is absent"],
        }
    }

    merged = merge_to_alpha_idea_master(
        primary,
        challenger,
        {},
        {},
        chief,
    )

    assert merged["mechanism_conditioned_measurement_program"] == program
    assert merged["research_discipline"][
        "mechanism_conditioned_measurement_program"
    ] == program
    assert merged["research_discipline"]["market_outcome_projection"] == program[
        "market_outcome_projection"
    ]
    assert merged["implementation_mode"] == "direct_code"
    assert merged["measurement_program_provenance"]["resolution"] == (
        "dual_route_exact_match"
    )

    conflicting = deepcopy(program)
    conflicting["model_selection"]["candidate_models"][0]["model_family"] = (
        "conflicting family"
    )
    challenger.mechanism_conditioned_measurement_program = conflicting
    blocked_merge = merge_to_alpha_idea_master(
        primary,
        challenger,
        {},
        {},
        chief,
    )
    assert "mechanism_conditioned_measurement_program" not in blocked_merge
    assert blocked_merge["measurement_program_provenance"]["resolution"] == (
        "unresolved_primary_challenger_conflict"
    )

    chief["mechanism_conditioned_measurement_program"] = deepcopy(program)
    resolved = merge_to_alpha_idea_master(
        primary,
        challenger,
        {},
        {},
        chief,
    )
    assert resolved["mechanism_conditioned_measurement_program"] == program
    assert resolved["measurement_program_provenance"]["resolution"] == (
        "chief_authored_resolution"
    )


def test_canonical_formula_intake_does_not_invent_a_stochastic_contract() -> None:
    bundle = build_canonical_formula_step1(
        report_id="CANONICAL_INTAKE_TEST",
        factor_id="CANONICAL_INTAKE_FACTOR",
        source_name="synthetic canonical formula",
        source_url="synthetic://canonical-formula",
        formula="rank(close)",
        window_start="2016-01-01",
        window_end="2025-07-11",
    )
    discipline = bundle["aim"]["research_discipline"]

    assert "stochastic_price_process_projection" not in discipline
    assert "mechanism_conditioned_measurement_program" not in discipline
    assert "step1_random_object" not in discipline
    assert discipline["step1_mathematical_object"]
    assert all(
        "mathematical_object" in candidate
        and "mechanism_equation_or_functional" in candidate
        and "state_or_object" not in candidate
        and "process_or_distribution_hypothesis" not in candidate
        for candidate in discipline["math_hypothesis_candidates"]
    )
    assert STEP1_VALIDATOR.valid_math_hypothesis_candidates(
        discipline["math_hypothesis_candidates"]
    )


def test_dcf_research_conjecture_needs_no_latent_state_or_stochastic_fields() -> None:
    conjecture = valid_conjecture()
    conjecture["economic_game"].pop("action_to_price_path", None)
    conjecture["economic_game"].pop("profit_transfer_equation", None)
    conjecture["economic_game"].update(
        {
            "action_to_market_outcome": (
                "Published cash-flow revisions change intrinsic value and the "
                "value-to-price convergence opportunity."
            ),
            "payoff_or_profit_transfer_equation": (
                "strategy_payoff = value_price_convergence - costs"
            ),
        }
    )
    conjecture["math_mechanism"] = {
        "model_family": "discounted cash-flow valuation",
        "mathematical_object": (
            "present value of legal-time forecast free cash flows and terminal value"
        ),
        "mechanism_equation_or_functional": (
            "V_t=sum_k FCF_{t+k}/(1+WACC)^k + TV_t/(1+WACC)^T"
        ),
        "market_outcome_equation": "alpha_t=V_t/P_t-1",
        "observation_equation": (
            "reported fundamentals at publication time map to normalized FCF inputs"
        ),
        "factor_estimator": "f_t=rank(V_t/P_t-1)",
        "information_set": "F_t contains only reports published by t",
        "alternative_models": [
            "residual-income valuation",
            "known value and quality aliases",
        ],
        "component_map": [
            {
                "formula_component": "forecast_free_cash_flow",
                "model_term": "FCF_{t+k}",
                "preserved_information": "cash-flow level and forecast horizon",
                "deleted_or_aliased_information": "unmodelled financing optionality",
                "ablation_test": "Replace FCF forecasts with consensus-neutral values.",
            }
        ],
        "limiting_cases": [
            "Zero excess FCF implies no operating-value premium.",
            "WACC tending upward reduces intrinsic value.",
            "V_t=P_t implies no value-price convergence gap.",
        ],
        "expected_metric_signatures": [
            {"metric": "long_side_return", "direction": "positive"},
            {"metric": "valuation_gap_decay", "direction": "toward_zero"},
        ],
    }

    assert validate_research_conjecture(conjecture) == []
    serialized = str(conjecture["math_mechanism"])
    assert "latent_state" not in serialized
    assert "state_space" not in serialized
    assert "stochastic" not in serialized.lower()


def test_dcf_main_agent_memo_and_derivation_need_no_stochastic_schema() -> None:
    formula = "forecast_fcf / (wacc - terminal_growth) / close - 1"
    signature = {
        "rank_ic": "positive when larger value-price gaps predict convergence",
        "long_side": "top valuation-gap portfolio earns positive gross return",
        "cost_adjusted": "top valuation-gap portfolio remains positive after costs",
        "monotonicity": "diagnostic ordering follows the frozen claim class",
        "turnover": "fundamental publication timing keeps turnover economically plausible",
    }
    spec = {
        "canonical_spec": {
            "formula_text": formula,
            "required_inputs": [
                "forecast_fcf",
                "wacc",
                "terminal_growth",
                "close",
            ],
            "operators": ["divide", "minus"],
        }
    }
    memo = {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "report_id": "DCF_GENERIC_MEMO",
        "factor_id": "DCF_VALUE_GAP",
        "research_id": "dcf_generic_memo",
        "producer": "current_main_agent",
        "agent_authorship": {
            "authoring_mode": "current_agent_freeform",
            "agent_role": "main_agent",
            "answered_without_deterministic_template": True,
        },
        "formula": formula,
        "formula_understanding": {
            "formula_features": {
                "fields": ["forecast_fcf", "wacc", "terminal_growth", "close"],
                "operators": ["divide", "minus"],
            }
        },
        "formula_component_map": [
            {
                "component_id": "formula_root",
                "formula_subexpression": formula,
                "operators": ["divide", "minus"],
                "observable_estimator": "forecast_fcf capitalized by wacc minus terminal_growth and scaled by close",
                "economic_state": "legal-time intrinsic-value-to-price gap",
                "mathematical_object": "discounted perpetuity-growth valuation functional",
                "expected_role": "measure underpricing relative to forecast free cash flow",
                "metric_link": "positive after-cost long-side convergence return is required",
            }
        ],
        "mechanism_qa": {
            "mathematical_object_answer": (
                "The selected object is the discounted forecast_fcf present-value functional, "
                "with wacc and terminal_growth determining capitalization and close defining the observable value-price gap."
            ),
            "economic_hypothesis_answer": (
                "Fundamental information is incorporated with delay when valuation-error counterparties retain stale cash-flow and discount-rate beliefs, so a legally observed value-price gap can converge."
            ),
            "math_model_answer": (
                "Use the DCF identity V_t=forecast_fcf_t/(wacc_t-terminal_growth_t), not a stochastic price process; the formula measures V_t/close_t-1 under explicit denominator assumptions."
            ),
            "payer_answer": (
                "Valuation-error counterparties holding stale forecast cash-flow, WACC, or terminal-growth beliefs pay when subsequent fundamental revisions and price convergence close the intrinsic-value gap."
            ),
            "payoff_answer": (
                "Forward return from t+1 to t+2 should be increasing in the legal-time valuation gap when price converges toward intrinsic value, and the relation must remain positive after costs."
            ),
            "observation_mapping_answer": (
                "forecast_fcf supplies the cash-flow numerator, wacc minus terminal_growth supplies the capitalization denominator, and close converts intrinsic value into the tradeable normalized gap."
            ),
            "metric_signature_answer": (
                "The DCF hypothesis requires positive RankIC, positive top-portfolio gross and net return, stable publication-time turnover, and no evidence that the score is only a size or value alias."
            ),
            "falsification_answer": (
                "Reject the mechanism if cash-flow, discount-rate, or terminal-growth ablations leave results unchanged, or if the frozen OOS valuation-gap long side is non-positive after costs."
            ),
        },
        "economic_hypothesis": {
            "return_source_class": "information_advantage",
            "payer_or_counterparty": "counterparties retaining stale cash-flow and discount-rate beliefs",
            "why_they_pay": "their valuation updates lag legally published fundamental information",
            "necessary_market_structure": "fundamental forecasts and prices share a legal publication-time information set",
        },
        "math_hypothesis": {
            "selected_model_family": "discounted cash-flow valuation",
            "why_this_model": "cash-flow timing, discount rates, and terminal value define intrinsic value directly",
            "why_not_generic_template": "the economic claim is a valuation identity and does not require latent-state or stochastic-process assumptions",
            "mathematical_object": "intrinsic value and intrinsic-value-to-market-price gap",
            "mechanism_equation_or_functional": (
                "V_t=forecast_fcf_t/(wacc_t-terminal_growth_t); valuation_gap_t=V_t/close_t-1"
            ),
            "target_functional": "valuation_gap_t=intrinsic_value_t/market_price_t-1",
            "market_outcome_projection": (
                "Forward return from t+1 to t+2 is increasing in valuation_gap_t under the declared convergence mechanism."
            ),
            "observation_mapping": (
                "forecast_fcf/(wacc-terminal_growth)/close-1 estimates intrinsic-value-to-market-price gap"
            ),
            "expected_metric_signature": dict(signature),
        },
        "math_model_selection": {
            "model_family": "discounted cash-flow valuation",
            "mechanism_equation_or_functional": (
                "V_t=forecast_fcf_t/(wacc_t-terminal_growth_t); valuation_gap_t=V_t/close_t-1"
            ),
            "model_mutation": "test DCF horizon and terminal-value sensitivity without changing the estimand",
        },
        "payer": {
            "payer_or_counterparty": "valuation-error counterparties with stale fundamental beliefs",
            "why_they_pay": "they revise forecast cash flow and discount rates after the legal signal time",
            "necessary_market_structure": "price convergence follows public fundamental revision without lookahead",
        },
        "mathematical_object_mapping": {
            "mathematical_object": "intrinsic value and intrinsic-value-to-market-price gap",
            "observation_mapping": (
                "forecast_fcf/(wacc-terminal_growth)/close-1 estimates intrinsic-value-to-market-price gap"
            ),
            "component_links": ["formula_root"],
        },
        "expected_metric_signature": dict(signature),
        "falsification_tests": [
            "Ablate forecast_fcf revisions and require the full DCF object to add OOS information.",
            "Replace the DCF gap with standard value aliases and reject if no distinct mechanism remains.",
        ],
        "evidence_comparison": {
            "observed_metrics": {
                "rank_ic_mean": 0.02,
                "cost_adjusted_annual_return": 0.08,
            },
            "mechanism_supported": "pending frozen OOS validation",
            "contradictions": [],
            "revision_implications": ["vary valuation assumptions without changing the core estimand"],
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
        "council_questions": [
            "Does residual-income valuation dominate the DCF identity under the same legal information set?"
        ],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }

    assert validate_main_agent_mechanism_memo(memo, spec) == []

    expectation_memo = deepcopy(memo)
    expectation_memo["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = f"valuation_gap_{{i,t}}={formula}"
    expectation_memo["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, valuation_gap_{i,t}] "
        "positive for high-factor deciles; entry t+1 close, exit t+2 close"
    )
    assert validate_main_agent_mechanism_memo(expectation_memo, spec) == []

    for indexed_observation in (
        "forecast_fcf_{oracle,t}/(wacc_{oracle,t}-terminal_growth_{oracle,t})/"
        "close_{oracle,t}-1 estimates intrinsic-value-to-market-price gap",
        "forecast_fcf_{i,j,t}/(wacc_{i,j,t}-terminal_growth_{i,j,t})/"
        "close_{i,j,t}-1 estimates intrinsic-value-to-market-price gap",
    ):
        indexed_memo = deepcopy(memo)
        indexed_memo["math_hypothesis"]["observation_mapping"] = indexed_observation
        indexed_memo["mathematical_object_mapping"][
            "observation_mapping"
        ] = indexed_observation
        failures = validate_main_agent_mechanism_memo(indexed_memo, spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures
    for unsafe_projection in (
        "Forward return from t+1 to t+2 is increasing in future_close_t under convergence.",
        "Forward return from t+1 to t+2 is increasing in valuation_gap_t using oracle_t.",
        "Forward return from t+1 to t+2 is increasing in valuation_gap_t with formula_state_t.",
        "Forward return from t+1 to t+2 is increasing in valuation_gap_t and tomorrow close under convergence.",
        "Forward return from t+1 to t+2 is increasing in oracle(valuation_gap_t) under convergence.",
        "Forward return from t+1 to t+2 is increasing in valuation_gap_t + oracle under convergence.",
        (
            "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, valuation_gap_{i,t}] "
            "positive for high-factor deciles; "
            "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, future_close_{i,t}]"
        ),
        "Forward return from t+1 to t+2 is increasing in valuation_gap_t under the declared convergence mechanism.\ud800",
    ):
        unsafe_memo = deepcopy(memo)
        unsafe_memo["math_hypothesis"][
            "market_outcome_projection"
        ] = unsafe_projection
        failures = validate_main_agent_mechanism_memo(unsafe_memo, spec)
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    incomplete_equation = deepcopy(memo)
    incomplete_equation["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "valuation_gap_t=close"
    failures = validate_main_agent_mechanism_memo(incomplete_equation, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for unsafe_equation in (
        (
            "valuation_gap_t=close; "
            "decoy_t=forecast_fcf/(wacc-terminal_growth)/close-1"
        ),
        (
            "valuation_gap_t=forecast_fcf/(wacc-terminal_growth)/close-1; "
            "valuation_gap_t=close"
        ),
    ):
        decoy_memo = deepcopy(memo)
        decoy_memo["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = unsafe_equation
        failures = validate_main_agent_mechanism_memo(decoy_memo, spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    for wrong_projected_state in ("close_t", "forecast_fcf_t"):
        wrong_projection = deepcopy(memo)
        wrong_projection["math_hypothesis"][
            "market_outcome_projection"
        ] = (
            "Forward return from t+1 to t+2 is increasing in "
            f"{wrong_projected_state} under the declared convergence mechanism."
        )
        failures = validate_main_agent_mechanism_memo(wrong_projection, spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    for mismatched_projection_state in (
        "valuation_gap_{oracle,t}",
        "valuation_gap_{j,t}",
        "valuation_gap_{i,j,t}",
    ):
        mismatched_index = deepcopy(memo)
        mismatched_index["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = f"valuation_gap_{{i,t}}={formula}"
        mismatched_index["math_hypothesis"]["market_outcome_projection"] = (
            "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
            f"{mismatched_projection_state}] positive for high-factor deciles; "
            "entry t+1 close, exit t+2 close"
        )
        failures = validate_main_agent_mechanism_memo(mismatched_index, spec)
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    for hidden_current_state in (
        "oracle.shift(0)",
        "oracle_t-0",
        "oracle_{i,t-0}",
    ):
        zero_lag_alias = deepcopy(memo)
        zero_lag_alias["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = f"valuation_gap_t={formula}; oracle_t=close"
        zero_lag_alias["math_hypothesis"]["market_outcome_projection"] = (
            "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, valuation_gap_t, "
            f"{hidden_current_state}] positive for high-factor deciles; "
            "entry t+1 close, exit t+2 close"
        )
        failures = validate_main_agent_mechanism_memo(zero_lag_alias, spec)
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    for shadowed_observable in ("close", "forecast_fcf"):
        shadowed_state = deepcopy(memo)
        shadowed_state["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = f"{shadowed_observable}_t={formula}"
        shadowed_state["math_hypothesis"]["market_outcome_projection"] = (
            "Forward return from t+1 to t+2 is increasing in "
            f"{shadowed_observable}_t under the declared convergence mechanism."
        )
        failures = validate_main_agent_mechanism_memo(shadowed_state, spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    def memo_for_formula(
        candidate_formula: str,
        required_inputs: list[str],
        operators: list[str],
    ) -> tuple[dict, dict]:
        candidate_spec = {
            "canonical_spec": {
                "formula_text": candidate_formula,
                "required_inputs": required_inputs,
                "operators": operators,
            }
        }
        candidate_memo = deepcopy(memo)
        candidate_memo["formula"] = candidate_formula
        candidate_memo["formula_understanding"]["formula_features"] = {
            "fields": required_inputs,
            "operators": operators,
        }
        candidate_memo["formula_component_map"][0][
            "formula_subexpression"
        ] = candidate_formula
        candidate_mapping = (
            f"{candidate_formula} estimates intrinsic-value-to-market-price gap"
        )
        candidate_memo["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = f"valuation_gap_t={candidate_formula}"
        candidate_memo["math_hypothesis"][
            "observation_mapping"
        ] = candidate_mapping
        candidate_memo["mathematical_object_mapping"][
            "observation_mapping"
        ] = candidate_mapping
        return candidate_memo, candidate_spec

    topology_attack_memo, topology_attack_spec = memo_for_formula(
        "sales + volume / amount + close",
        ["sales", "volume", "amount", "close"],
        ["plus", "divide"],
    )
    failures = validate_main_agent_mechanism_memo(
        topology_attack_memo,
        topology_attack_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    dimensional_attack_memo, dimensional_attack_spec = memo_for_formula(
        "close + dividend_yield",
        ["close", "dividend_yield"],
        ["plus"],
    )
    failures = validate_main_agent_mechanism_memo(
        dimensional_attack_memo,
        dimensional_attack_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for valuation_formula, valuation_field in (
        ("rank(dividend_yield)", "dividend_yield"),
        ("rank(ev_to_ebitda)", "ev_to_ebitda"),
    ):
        ratio_memo, ratio_spec = memo_for_formula(
            valuation_formula,
            [valuation_field],
            ["rank"],
        )
        failures = validate_main_agent_mechanism_memo(ratio_memo, ratio_spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" not in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            not in failures
        )

    for valuation_formula, valuation_inputs in (
        (
            "(book_value + residual_income / cost_of_equity) / market_cap - 1",
            ["book_value", "residual_income", "cost_of_equity", "market_cap"],
        ),
        (
            "(forecast_fcf / (wacc - terminal_growth) - net_debt) / "
            "shares_outstanding / close - 1",
            [
                "forecast_fcf",
                "wacc",
                "terminal_growth",
                "net_debt",
                "shares_outstanding",
                "close",
            ],
        ),
    ):
        derived_value_memo, derived_value_spec = memo_for_formula(
            valuation_formula,
            valuation_inputs,
            ["divide", "minus", "plus"],
        )
        failures = validate_main_agent_mechanism_memo(
            derived_value_memo,
            derived_value_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" not in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            not in failures
        )

    for dead_valuation_formula in (
        "0 * (forecast_fcf / close)",
        "(forecast_fcf / close) - (forecast_fcf / close)",
        "(forecast_fcf / close) / (forecast_fcf / close)",
    ):
        dead_memo, dead_spec = memo_for_formula(
            dead_valuation_formula,
            ["forecast_fcf", "close"],
            ["multiply", "divide", "minus"],
        )
        failures = validate_main_agent_mechanism_memo(dead_memo, dead_spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for fake_valuation_formula, fake_field in (
        ("rank(volume_yield)", "volume_yield"),
        ("rank(oracle_yield)", "oracle_yield"),
        ("noise_sales / close", "noise_sales"),
    ):
        fake_ratio_memo, fake_ratio_spec = memo_for_formula(
            fake_valuation_formula,
            [fake_field, "close"] if "/" in fake_valuation_formula else [fake_field],
            ["divide"] if "/" in fake_valuation_formula else ["rank"],
        )
        failures = validate_main_agent_mechanism_memo(
            fake_ratio_memo,
            fake_ratio_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    def dcf_program(observation_map: str) -> dict:
        program = _program()
        selected = program["model_selection"]["candidate_models"][0]
        selected_object = "valuation_gap_t"
        projection = (
            "Forward return from t+1 to t+2 is increasing in valuation_gap_t "
            "under the declared convergence mechanism."
        )
        program["observation_and_estimation"]["estimand"] = selected_object
        program["observation_and_estimation"][
            "observation_map"
        ] = observation_map
        program["market_outcome_projection"][
            "source_math_object"
        ] = selected_object
        program["market_outcome_projection"][
            "projection_equation_or_map"
        ] = projection
        selected.update(
            {
                "model_family": "discounted cash-flow valuation",
                "mathematical_object": selected_object,
                "target_functional": selected_object,
                "market_outcome_projection": projection,
                "observation_mapping": observation_map,
            }
        )
        return program

    program_only_memo = deepcopy(memo)
    program_only_memo["mathematical_object_mapping"]["component_links"] = []
    valid_program = dcf_program(f"valuation_gap_t={formula}")
    assert validate_measurement_program(
        valid_program,
        require_web_executable=False,
    ) == []
    valid_program_spec = deepcopy(spec)
    valid_program_spec["mechanism_conditioned_measurement_program"] = valid_program
    valid_program_spec["canonical_spec"][
        "mechanism_conditioned_measurement_program"
    ] = valid_program
    failures = validate_main_agent_mechanism_memo(
        program_only_memo,
        valid_program_spec,
    )
    assert failures == []

    for invalid_lhs in (
        "future_close_{i,t+1}",
        "Q_{i,t-1}",
        "oracle_{i,u}",
        "valuation_gap_{oracle,t}",
    ):
        invalid_program = dcf_program(f"{invalid_lhs}={formula}")
        assert validate_measurement_program(
            invalid_program,
            require_web_executable=False,
        ) == []
        invalid_program_spec = deepcopy(spec)
        invalid_program_spec[
            "mechanism_conditioned_measurement_program"
        ] = invalid_program
        invalid_program_spec["canonical_spec"][
            "mechanism_conditioned_measurement_program"
        ] = invalid_program
        failures = validate_main_agent_mechanism_memo(
            program_only_memo,
            invalid_program_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    for indexed_rhs in (
        "valuation_gap_t=forecast_fcf_{oracle,t}/"
        "(wacc_{oracle,t}-terminal_growth_{oracle,t})/close_{oracle,t}-1",
        "valuation_gap_t=forecast_fcf_{i,j,t}/"
        "(wacc_{i,j,t}-terminal_growth_{i,j,t})/close_{i,j,t}-1",
    ):
        invalid_program = dcf_program(indexed_rhs)
        invalid_program_spec = deepcopy(spec)
        invalid_program_spec[
            "mechanism_conditioned_measurement_program"
        ] = invalid_program
        invalid_program_spec["canonical_spec"][
            "mechanism_conditioned_measurement_program"
        ] = invalid_program
        failures = validate_main_agent_mechanism_memo(
            program_only_memo,
            invalid_program_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for shadowed_observable in ("close", "forecast_fcf"):
        shadow_program = dcf_program(f"{shadowed_observable}_t={formula}")
        selected = shadow_program["model_selection"]["candidate_models"][0]
        selected["mathematical_object"] = f"{shadowed_observable}_t"
        selected["target_functional"] = f"{shadowed_observable}_t"
        shadow_program["observation_and_estimation"][
            "estimand"
        ] = f"{shadowed_observable}_t"
        shadow_program["market_outcome_projection"][
            "source_math_object"
        ] = f"{shadowed_observable}_t"
        shadow_program_spec = deepcopy(spec)
        shadow_program_spec[
            "mechanism_conditioned_measurement_program"
        ] = shadow_program
        shadow_program_spec["canonical_spec"][
            "mechanism_conditioned_measurement_program"
        ] = shadow_program
        failures = validate_main_agent_mechanism_memo(
            program_only_memo,
            shadow_program_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    invented_knowledge_program = dcf_program(f"valuation_gap_t={formula}")
    invented_knowledge_program["implementation"]["components"][0][
        "knowledge_node_ids"
    ] = ["invented"]
    self_authorized_spec = deepcopy(spec)
    self_authorized_spec["cited_node_ids"] = ["invented"]
    self_authorized_spec["research_contract"] = {
        "factor_knowledge_context": {
            "schema_version": "factor_knowledge_context_v1",
            "node_count": 1,
            "query": {"text": "invented", "top_k": 1},
            "nodes": [{"id": "invented"}],
        }
    }
    self_authorized_spec[
        "mechanism_conditioned_measurement_program"
    ] = invented_knowledge_program
    self_authorized_spec["canonical_spec"][
        "mechanism_conditioned_measurement_program"
    ] = invented_knowledge_program
    failures = validate_main_agent_mechanism_memo(
        program_only_memo,
        self_authorized_spec,
    )
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MEASUREMENT_PROGRAM_INVALID"
        in failures
    )

    admitted_knowledge_program = dcf_program(f"valuation_gap_t={formula}")
    admitted_knowledge_program["implementation"]["components"][0][
        "knowledge_node_ids"
    ] = ["admitted-node"]
    admitted_knowledge_spec = deepcopy(spec)
    admitted_knowledge_spec["research_contract"] = {
        "factor_knowledge_context": {
            "schema_version": "factor_knowledge_context_v1",
            "node_count": 1,
            "query": {"text": "cash-flow valuation", "top_k": 1},
            "nodes": [{"id": "admitted-node"}],
        },
        "knowledge_reference_contract": {
            "contract_version": "factorforge_knowledge_reference_contract_v1",
            "producer": "host_retrieval",
            "retrieval_required": True,
            "retrieval_status": "retrieved",
            "query_hash": "a" * 64,
            "indexes_available": ["knowledge/retrieval/index.jsonl"],
            "hit_count": 1,
            "retrieved_case_ids": ["admitted-node"],
        },
    }
    admitted_knowledge_spec[
        "mechanism_conditioned_measurement_program"
    ] = admitted_knowledge_program
    admitted_knowledge_spec["canonical_spec"][
        "mechanism_conditioned_measurement_program"
    ] = admitted_knowledge_program
    assert validate_main_agent_mechanism_memo(
        program_only_memo,
        admitted_knowledge_spec,
    ) == []

    non_dict_copy_spec = deepcopy(valid_program_spec)
    non_dict_copy_spec["canonical_spec"][
        "mechanism_conditioned_measurement_program"
    ] = "bad"
    failures = validate_main_agent_mechanism_memo(
        program_only_memo,
        non_dict_copy_spec,
    )
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MEASUREMENT_PROGRAM_INVALID"
        in failures
    )

    for invalid_formula, required_inputs, operators in (
        ("future_fcf / close - 1", ["future_fcf", "close"], ["divide", "minus"]),
        ("close + sales", ["close", "sales"], ["plus"]),
    ):
        invalid_spec = {
            "canonical_spec": {
                "formula_text": invalid_formula,
                "required_inputs": required_inputs,
                "operators": operators,
            }
        }
        invalid_memo = deepcopy(memo)
        invalid_memo["formula"] = invalid_formula
        invalid_memo["formula_understanding"]["formula_features"] = {
            "fields": required_inputs,
            "operators": operators,
        }
        invalid_memo["formula_component_map"][0][
            "formula_subexpression"
        ] = invalid_formula
        invalid_mapping = (
            f"{invalid_formula} estimates intrinsic-value-to-market-price gap"
        )
        invalid_memo["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = f"valuation_gap_t={invalid_formula.replace(' ', '')}"
        invalid_memo["math_hypothesis"][
            "observation_mapping"
        ] = invalid_mapping
        invalid_memo["mathematical_object_mapping"][
            "observation_mapping"
        ] = invalid_mapping
        failures = validate_main_agent_mechanism_memo(invalid_memo, invalid_spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    valid_but_irrelevant_program = _program()
    valid_but_irrelevant_program["model_selection"]["candidate_models"][0][
        "model_family"
    ] = "discounted cash-flow valuation"
    irrelevant_spec = {
        "mechanism_conditioned_measurement_program": valid_but_irrelevant_program,
        "canonical_spec": {
            "formula_text": "rank(close)",
            "required_inputs": ["close"],
            "operators": ["rank"],
            "mechanism_conditioned_measurement_program": valid_but_irrelevant_program,
        },
    }
    irrelevant_memo = deepcopy(memo)
    irrelevant_memo["formula"] = "rank(close)"
    irrelevant_memo["formula_understanding"]["formula_features"] = {
        "fields": ["close"],
        "operators": ["rank"],
    }
    irrelevant_memo["formula_component_map"][0][
        "formula_subexpression"
    ] = "rank(close)"
    irrelevant_memo["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "valuation_gap_t=close"
    irrelevant_mapping = (
        "rank(close) estimates intrinsic-value-to-market-price gap"
    )
    irrelevant_memo["math_hypothesis"][
        "observation_mapping"
    ] = irrelevant_mapping
    irrelevant_memo["mathematical_object_mapping"][
        "observation_mapping"
    ] = irrelevant_mapping
    failures = validate_main_agent_mechanism_memo(
        irrelevant_memo,
        irrelevant_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    derivation = formula_specific_derivation_from_main_agent_memo(memo, spec)
    assert derivation["selected_model_family"] == "valuation_identity"
    assert validate_formula_specific_derivation(derivation, spec, {}) == []
    serialized = str(derivation).lower()
    assert "random_object" not in serialized
    assert "latent_state" not in serialized
    assert "process_or_distribution" not in serialized
    assert "dcf" in serialized or "forecast_fcf" in serialized


def test_fundamental_accounting_models_are_not_forced_into_dcf_valuation() -> None:
    assert normalize_derivation_model_family("accounting identity") == "other"
    assert normalize_derivation_model_family("accounting quality") == "other"
    assert normalize_derivation_model_family("unit economics") == "other"
    assert normalize_derivation_model_family("discounted cash-flow valuation") == (
        "valuation_identity"
    )
    assert normalize_derivation_model_family("residual-income valuation") == (
        "valuation_identity"
    )
    assert _normalize_baseline_model_family("accounting identity") == "other"
    assert _normalize_baseline_model_family("unit economics") == "other"
    neutral_features = {
        "operators": [],
        "has_sign_or_threshold": False,
        "has_long_window": False,
        "has_short_delay_or_delta": False,
    }
    for fundamental_mechanism in (
        "earnings quality and accrual reversal",
        "cash flow conversion under financing constraints",
        "profit reinvestment and capital allocation",
        "book-based accounting quality",
        "unit economics and operating leverage",
    ):
        assert _select_baseline_model(fundamental_mechanism, neutral_features) == (
            "other"
        )
    for explicit_valuation_mechanism in (
        "discounted cash flow convergence",
        "intrinsic value versus price",
        "residual income valuation gap",
    ):
        assert _select_baseline_model(
            explicit_valuation_mechanism,
            neutral_features,
        ) == "valuation_identity"


def test_canonical_formula_formal_path_attaches_current_agent_program() -> None:
    bundle = build_canonical_formula_step1(
        report_id="CANONICAL_ENRICHED_TEST",
        factor_id="CANONICAL_ENRICHED_FACTOR",
        source_name="synthetic canonical formula",
        source_url="synthetic://canonical-formula",
        formula="rank(close)",
        window_start="2016-01-01",
        window_end="2025-07-11",
    )
    program = _program()
    knowledge = {
        "cited_node_ids": [],
        "similar_case_lessons_imported": [
            "cold-start knowledge check completed without making knowledge authoritative"
        ],
    }

    enriched = attach_agent_authored_measurement_program(
        bundle,
        measurement_program=program,
        knowledge_reference_contract=knowledge,
    )
    aim = enriched["aim"]

    assert aim["mechanism_conditioned_measurement_program"] == program
    assert aim["research_discipline"][
        "mechanism_conditioned_measurement_program"
    ] == program
    assert aim["research_discipline"]["market_outcome_projection"] == program[
        "market_outcome_projection"
    ]
    assert "stochastic_price_process_projection" not in aim["research_discipline"]


def test_step2_blocks_missing_or_route_mismatched_program() -> None:
    with pytest.raises(SystemExit, match=BLOCK_MEASUREMENT_PROGRAM_INVALID):
        STEP2.validated_step1_measurement_program(
            aim={"research_discipline": {}},
            primary={},
            implementation_mode="operator",
        )

    program = _program("direct_code")
    with pytest.raises(SystemExit, match=BLOCK_MEASUREMENT_PROGRAM_INVALID):
        STEP2.validated_step1_measurement_program(
            aim={
                "mechanism_conditioned_measurement_program": program,
                "research_discipline": {
                    "mechanism_conditioned_measurement_program": program,
                },
            },
            primary={},
            implementation_mode="operator",
        )


def test_step3_blocks_any_program_copy_mismatch() -> None:
    program = _program()
    tampered = deepcopy(program)
    tampered["model_selection"]["selection_argument"] = "tampered after Step2"
    fsm = {
        "mechanism_conditioned_measurement_program": program,
        "canonical_spec": {
            "mechanism_conditioned_measurement_program": tampered,
        },
    }
    handoff = {"mechanism_conditioned_measurement_program": program}

    with pytest.raises(SystemExit, match=BLOCK_MEASUREMENT_PROGRAM_INVALID):
        STEP3.validated_measurement_program_for_step3(
            fsm,
            handoff,
            implementation_mode="operator",
        )


def test_step6_preserves_dcf_program_without_synthesizing_legacy_math_contracts() -> None:
    program = _program()
    selected = program["model_selection"]["candidate_models"][0]
    selected.update(
        {
            "model_family": "discounted cash-flow valuation",
            "mathematical_object": "enterprise value as discounted forecast free cash flow plus terminal value",
            "mechanism_equation_or_functional": "V_t=sum_k FCF_t+k/(1+WACC_t)^k + TV_t/(1+WACC_t)^T",
            "economic_implication": "price below legally observable intrinsic value predicts positive convergence return",
            "identifiability_condition": "forecast cash flow, discount rate, terminal growth and price share one legal information time",
            "decisive_test": "reject when valuation spread has no after-cost OOS long-side relation",
        }
    )
    program["observation_and_estimation"].update(
        {
            "estimand": "intrinsic-value-to-price spread",
            "observation_map": "forecast_fcf / (wacc - terminal_growth) / close - 1",
            "estimator": "discounted perpetuity-growth valuation spread",
        }
    )
    program["market_outcome_projection"]["source_math_object"] = selected[
        "mathematical_object"
    ]
    selected.update(
        {
            "target_functional": program["observation_and_estimation"]["estimand"],
            "market_outcome_projection": program["market_outcome_projection"]["projection_equation_or_map"],
            "observation_mapping": program["observation_and_estimation"]["observation_map"],
        }
    )
    program["math_tool_selection"].update(
        {
            "candidate_tool_families": [
                "discounted cash-flow valuation",
                "residual-income valuation",
                "null accounting alias",
            ],
            "selected_tool_families": ["discounted cash-flow valuation"],
            "selection_rationale": "cash-flow timing and discount rates define the selected intrinsic-value object",
            "rejected_tool_families": [
                {
                    "tool_family": "stochastic price process",
                    "reason": "not needed for the core intrinsic-value derivation",
                }
            ],
        }
    )
    program["applicable_audits"] = {
        "selection_rule": "select only audits justified by the chosen mechanism",
        "selected": [],
        "rejected": [],
    }
    bundle = {
        "factor_spec_master": {
            "mechanism_conditioned_measurement_program": deepcopy(program),
            "canonical_spec": {
                "mechanism_conditioned_measurement_program": deepcopy(program),
            },
        },
        "handoff_to_step6": {
            "mechanism_conditioned_measurement_program": deepcopy(program),
        },
    }

    assert STEP6.measurement_program_from_bundle(bundle) == program
    assert STEP6.mechanism_math_contract_from_bundle(bundle) == {}
    assert STEP6.mechanism_math_contract_v2_from_bundle(bundle) == {}
    summary = STEP6.mechanism_math_summary_from_bundle(bundle)
    assert summary["model_family"] == "discounted cash-flow valuation"
    assert summary["mathematical_object"].startswith("enterprise value")
    assert summary["target_functional"] == "intrinsic-value-to-price spread"
    assert "process_hypothesis" not in summary
    assert "latent_state" not in summary
    assert "conditional_distribution_hypothesis" not in summary
    assert COUNCIL_PACKET.mechanism_math_for_packet(
        bundle["factor_spec_master"],
        {},
        bundle["handoff_to_step6"],
        {},
    ) == {}
    step5_case = build_factor_case_master(
        {
            "report_id": "DCF_CURRENT_ONLY",
            "objects": {
                "factor_spec_master": bundle["factor_spec_master"],
                "factor_run_master": {
                    "factor_id": "DCF_VALUE_SPREAD",
                    "run_status": "success",
                },
                "data_prep_master": {},
            },
            "paths": {},
        },
        {"backend_summary": [], "step4_quality_gate": {}},
        [],
        "partial",
        "/tmp/dcf_evaluation.json",
    )
    assert step5_case["mechanism_conditioned_measurement_program"] == program
    assert "mechanism_math_contract" not in step5_case
    step5_ref = step5_case["math_discipline_review"][
        "mechanism_conditioned_measurement_program_ref"
    ]
    assert step5_ref["model_family"] == "discounted cash-flow valuation"
    assert step5_ref["estimand"] == "intrinsic-value-to-price spread"


def test_council_binds_dcf_core_equation_separately_from_payoff_projection() -> None:
    program = _program("direct_code")
    selected = program["model_selection"]["candidate_models"][0]
    program["market_outcome_projection"].update(
        {
            "projection_kind": "intrinsic-value gap to convergence payoff",
            "source_math_object": "discounted enterprise value",
            "traded_quantity": "next-horizon after-cost equity return",
            "affected_payoff_or_distribution_terms": ["conditional expected return"],
            "projection_equation_or_map": "E[R_t+1|F_t]=beta*(V_t/P_t-1)-cost_t",
            "link_to_observation_equation": "legal-time forecasts estimate V_t/P_t-1",
            "falsifier": "the frozen OOS value gap has no after-cost convergence payoff",
        }
    )
    program["observation_and_estimation"].update(
        {
            "estimand": "intrinsic-value-to-price spread",
            "observation_map": "forecast_fcf/(wacc-terminal_growth)/close-1",
            "estimator": "legal-time DCF value spread",
        }
    )
    selected.update(
        {
            "model_family": "discounted cash-flow valuation",
            "mathematical_object": "discounted enterprise value",
            "mechanism_equation_or_functional": "V_t=sum_k FCF_t+k/(1+WACC_t)^k",
            "target_functional": program["observation_and_estimation"]["estimand"],
            "market_outcome_projection": program["market_outcome_projection"]["projection_equation_or_map"],
            "observation_mapping": program["observation_and_estimation"]["observation_map"],
        }
    )
    packet = {
        "report_id": "DCF_COUNCIL_BINDING",
        "factor_formula": "forecast_fcf/(wacc-terminal_growth)/close-1",
        "mechanism_conditioned_measurement_program": program,
        "research_memo": {
            "revision_strategy": {"primary_failure_signature": "mechanism_unclear"},
            "mechanism_analysis": {
                "return_source": "information_advantage",
                "factor_family": "fundamental valuation",
                "mechanism_fit": "weak",
            },
        },
    }

    proposal = COUNCIL_RUN.symbolic_law(packet)
    proposal["derivation_record"] = COUNCIL_RUN.build_derivation_record(
        packet, proposal
    )
    reasons = validate_revision_council_proposal(
        proposal,
        measurement_program=program,
    )

    symbolic = proposal["symbolic_model"]
    assert symbolic["selected_model_family"] == "discounted cash-flow valuation"
    assert symbolic["mechanism_equation_or_functional"] == (
        "V_t=sum_k FCF_t+k/(1+WACC_t)^k"
    )
    assert symbolic["market_outcome_projection"] == (
        "E[R_t+1|F_t]=beta*(V_t/P_t-1)-cost_t"
    )
    assert symbolic["mechanism_equation_or_functional"] != symbolic[
        "market_outcome_projection"
    ]
    assert not any("MEASUREMENT_PROGRAM_BINDING" in reason for reason in reasons)

    tampered = deepcopy(proposal)
    tampered["symbolic_model"]["selected_model_family"] = "stochastic_process"
    tampered_reasons = validate_revision_council_proposal(
        tampered,
        measurement_program=program,
    )
    assert (
        "BLOCK_COUNCIL_MEASUREMENT_PROGRAM_BINDING_MISMATCH:selected_model_family"
        in tampered_reasons
    )


def test_agentic_council_cannot_replace_frozen_dcf_with_sde() -> None:
    program = _program("direct_code")
    selected = program["model_selection"]["candidate_models"][0]
    selected.update(
        {
            "model_family": "discounted cash-flow valuation",
            "mathematical_object": "discounted enterprise value",
            "mechanism_equation_or_functional": (
                "V_t=sum_k FCF_t+k/(1+WACC_t)^k"
            ),
        }
    )
    program["market_outcome_projection"]["source_math_object"] = (
        selected["mathematical_object"]
    )
    binding = build_measurement_program_binding(program)
    task = {
        "task_id": "route_dcf_mechanism",
        "agent_role": "mechanism_measurement_modeler",
        "expected_agent_identifier": "agent_dcf_mechanism",
        "route_id": "dcf_mechanism",
        "route_family": "mechanism_object_measurement",
        "route_fingerprint": "route-fingerprint",
        "blind_context_hash": "blind-context-hash",
        "task_packet_sha256": "task-packet-sha256",
        "measurement_program_binding": binding,
        "allowed_tools": ["open_math_tool_search"],
        "proof_obligation_ids": [],
        "shared_context": {},
        "exact_gap": "test whether the DCF observation map identifies value",
    }
    result = AGENTIC_MOCK.result_for_task(
        task,
        {"report_id": "DCF_AGENTIC_BINDING"},
    )
    assert AGENTIC_VALIDATOR.validate_agentic_result(
        result,
        expected_task=task,
        expected_report_id="DCF_AGENTIC_BINDING",
    ) == []

    tampered = deepcopy(result)
    tampered["math_mechanism_derivation"]["baseline_model"] = (
        "dP_t=mu_t*dt+sigma_t*dW_t"
    )
    tampered["math_mechanism_derivation"]["mathematical_objects"] = [
        "diffusion state"
    ]
    tampered["public_derivation_record"]["mathematical_objects"] = [
        {"name": "diffusion state"}
    ]
    reasons = AGENTIC_VALIDATOR.validate_agentic_result(
        tampered,
        expected_task=task,
        expected_report_id="DCF_AGENTIC_BINDING",
    )
    assert "BLOCK_COUNCIL_FROZEN_BASELINE_MODEL_MISMATCH" in reasons
    assert "BLOCK_COUNCIL_FROZEN_MATHEMATICAL_OBJECT_MISSING" in reasons
    assert "BLOCK_COUNCIL_PUBLIC_DERIVATION_FROZEN_OBJECT_MISSING" in reasons


def test_step6_blocks_measurement_program_copy_mismatch() -> None:
    program = _program()
    tampered = deepcopy(program)
    tampered["market_outcome_projection"]["projection_kind"] = "tampered"
    bundle = {
        "factor_spec_master": {
            "mechanism_conditioned_measurement_program": program,
            "canonical_spec": {
                "mechanism_conditioned_measurement_program": tampered,
            },
        }
    }

    with pytest.raises(SystemExit, match=BLOCK_MEASUREMENT_PROGRAM_INVALID):
        STEP6.measurement_program_from_bundle(bundle)
