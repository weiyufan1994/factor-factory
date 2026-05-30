from __future__ import annotations

import copy

from factor_factory.mechanism_math.classifier import build_mechanism_math_contract_v2
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract
from factor_factory.revision_council.validator import validate_revision_council_proposal


def _valid_spec():
    return {
        "report_id": "DIRAC_REVIEW",
        "factor_id": "DIRAC_REVIEW",
        "canonical_spec": {
            "formula_text": "rank(delta(close, 5))",
            "required_inputs": ["close"],
            "operators": ["rank()", "delta()"],
        },
        "research_contract": {
            "economic_mechanism": "delayed information diffusion creates continuation and reversal states",
            "economic_hypothesis": {
                "macro_return_source": "information_advantage",
                "second_layer": {
                    "expected_counterparty_or_payer": "slow information processors",
                    "why_they_may_pay": "they update beliefs later than the signal observer",
                },
            },
            "math_hypothesis_candidates": [
                {
                    "model_family": "stochastic_process",
                    "state_or_object": "latent drift continuation state",
                    "observable_estimator": "ranked lagged close delta",
                    "target_functional": "E[r_{t+1} | F_t, drift_state_t]",
                    "why_suitable": "lagged price changes estimate a conditional drift state",
                }
            ],
        },
    }


def test_mechanism_math_requires_formula_implied_information_review():
    contract = build_mechanism_math_contract_v2(_valid_spec())
    assert not validate_mechanism_math_contract(contract)

    mutated = copy.deepcopy(contract)
    mutated.pop("formula_implied_information_review")
    failures = validate_mechanism_math_contract(mutated)

    assert any(f["code"] == "BLOCK_MECHANISM_MATH_V2_FORMULA_IMPLIED_REVIEW_MISSING" for f in failures)


def test_mechanism_math_unclassified_unexpected_implication_blocks():
    contract = build_mechanism_math_contract_v2(_valid_spec())
    contract["formula_implied_information_review"]["unexpected_implications"] = [
        {"implication": "negative alpha side may be the real information-bearing state"}
    ]

    failures = validate_mechanism_math_contract(contract)

    assert any(f["code"] == "BLOCK_MECHANISM_MATH_V2_FORMULA_IMPLIED_REVIEW_MISSING" for f in failures)


def test_mechanism_math_anomaly_requires_branch_law_metric_and_kill_criteria():
    contract = build_mechanism_math_contract_v2(_valid_spec())
    contract["formula_implied_information_review"]["unexpected_implications"] = [
        {
            "implication": "formula suggests a negative solution with stronger return signature",
            "classification": "tradable_anomaly",
            "reasoning": "unexpected sign is not explained by the original hypothesis",
        }
    ]

    failures = validate_mechanism_math_contract(contract)

    assert any(f["code"] == "BLOCK_MECHANISM_MATH_V2_FORMULA_IMPLIED_REVIEW_MISSING" for f in failures)


def test_mechanism_math_valid_anomaly_branch_passes():
    contract = build_mechanism_math_contract_v2(_valid_spec())
    contract["formula_implied_information_review"]["unexpected_implications"] = [
        {
            "implication": "negative-side solution may identify forced unwinds",
            "classification": "tradable_anomaly",
            "reasoning": "it implies a distinct payer and state transition from the primary model",
            "branch_seed_if_any": {
                "child_formula_or_law": "rank(-delta(close, 5)) conditioned on unwind state",
                "expected_metric_signature": ["negative-side branch has positive long-side return", "turnover remains cost-survivable"],
                "kill_criteria": ["kill if long-side return is non-positive", "kill if effect is only short-leg loss"],
            },
        }
    ]

    assert not validate_mechanism_math_contract(contract)


def _minimal_council_proposal() -> dict:
    return {
        "contract_version": "factorforge_revision_council_proposal_v1",
        "proposal_id": "P",
        "agent_role": "symbolic_law_discovery",
        "revision_type": "expression_revision",
        "target_failure_signature": "mechanism_unclear",
        "return_source_hypothesis": "mixed",
        "confidence": "medium",
        "producer": "agentic_research",
        "research_depth": "medium",
        "proposal_generation_mode": "agentic_research",
        "revision_model_layer": "observable_estimator",
        "forbidden_changes_ack": [
            "no_portfolio_rebalance_fix",
            "no_metric_cherry_pick",
            "no_universe_or_cost_relaxation",
            "no_future_information",
        ],
        "why_not_portfolio_fix": "the failure belongs to the estimator, not portfolio construction",
        "symbolic_model": {"state_or_object": "latent drift state", "target_functional": "E[r|state]"},
        "selected_math_tools": ["probability_theory"],
        "dimensional_scaling_review": {
            "raw_field_units": {},
            "formula_output_dimension": "dimensionless rank",
            "dimension_erasing_transforms": [],
            "scale_invariance_claims": [],
            "natural_time_scale": "5d",
            "dimension_risks": [],
            "limiting_cases": [],
        },
        "candidate_revision_laws": [
            {
                "revision_model_layer": "observable_estimator",
                "falsification_tests": ["rank IC sign", "long return"],
                "kill_criteria": ["kill if no long return", "kill if only short leg"],
                "expected_metric_change": ["better long return", "lower turnover"],
            }
        ],
        "derivation_record": {
            "revision_model_layer": "observable_estimator",
            "research_question": "what latent state does the formula imply",
            "assumptions": [{"assumption": "lagged price is observable", "status": "observed", "why_needed": "information set", "how_to_falsify": "leakage scan"}],
            "mathematical_objects": [{"name": "S", "meaning": "latent state", "unit_or_dimension": "dimensionless", "information_set": "F_t"}],
            "selected_tools": [{"tool": "probability_theory", "why_selected": "conditional distribution", "what_it_can_answer": "state payoff", "what_it_cannot_answer": "capacity"}],
            "rejected_tools": [],
            "derivation_steps": [{"step_no": 1, "statement": "derive conditional expectation", "justification": "state model", "depends_on": [], "formula": "E[r|S]"}],
            "derived_implications": [{"claim": "higher state changes return distribution", "expected_metric_signature": ["rank IC", "long return"]}],
            "revision_hypotheses": [{"hypothesis": "flip estimator sign", "revision_model_layer": "observable_estimator", "expression_direction": "negative-side state", "expected_metric_change": ["long return improves", "turnover stable"], "falsification_tests": ["rank IC", "long return"], "kill_criteria": ["no long return", "only short leg"]}],
            "confidence_and_limits": {"mathematical_confidence": "medium", "empirical_confidence": "medium", "known_gaps": [], "overclaim_guard": "requires Step4/5 evidence"},
        },
    }


def test_council_unclassified_unexpected_implication_blocks():
    proposal = _minimal_council_proposal()
    proposal["formula_implied_information_review"] = {
        "unexpected_implications": [{"implication": "negative solution"}]
    }

    reasons = validate_revision_council_proposal(proposal)

    assert "BLOCK_COUNCIL_UNCLASSIFIED_UNEXPECTED_IMPLICATION" in reasons


def test_council_anomaly_requires_branch_law():
    proposal = _minimal_council_proposal()
    proposal["formula_implied_information_review"] = {
        "unexpected_implications": [
            {"implication": "negative solution", "classification": "new_factor_seed", "reasoning": "distinct state"}
        ]
    }

    reasons = validate_revision_council_proposal(proposal)

    assert "BLOCK_COUNCIL_ANOMALY_BRANCH_LAW_MISSING" in reasons
