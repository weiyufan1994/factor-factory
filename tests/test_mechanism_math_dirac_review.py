from __future__ import annotations

import copy

from factor_factory.mechanism_math.classifier import build_mechanism_math_contract_v2
from factor_factory.mechanism_math.main_agent_memo import (
    _claims_correlation_or_covariance_from_text,
    _has_explicit_forward_price_payoff,
    _has_explicit_named_return_payoff,
    validate_main_agent_mechanism_memo,
)
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


def test_operator_claim_scan_keeps_positive_corr_cov_claims_blockable():
    assert _claims_correlation_or_covariance_from_text(
        "The formula is a rolling rank correlation estimator of price and volume."
    )
    assert _claims_correlation_or_covariance_from_text(
        "The formula is a Pearson correlation estimator of price and volume."
    )
    assert _claims_correlation_or_covariance_from_text(
        "The formula is not without covariance."
    )
    assert _claims_correlation_or_covariance_from_text(
        "Daily cross-sectional Pearson correlation of F, while the formula is a covariance estimator, with forward return."
    )
    assert _claims_correlation_or_covariance_from_text(
        "The formula is a correlation estimator but has no covariance claim."
    )
    assert _claims_correlation_or_covariance_from_text(
        "The estimator is covariance-based and does not use correlation."
    )
    assert _claims_correlation_or_covariance_from_text(
        "The formula estimates correlations between price and volume."
    )
    assert _claims_correlation_or_covariance_from_text(
        "The estimator models rolling covariances."
    )
    assert _claims_correlation_or_covariance_from_text(
        "This is a correlational price-volume estimator."
    )
    assert _claims_correlation_or_covariance_from_text(
        "It is false that the formula has no correlation operator."
    )
    assert _claims_correlation_or_covariance_from_text(
        "The formula has no correlation operator, except that it does."
    )
    assert _claims_correlation_or_covariance_from_text(
        "公式无 correlation 算子，但实际上有。"
    )
    assert _claims_correlation_or_covariance_from_text(
        "Without implying correlation, except that the formula does."
    )
    assert _claims_correlation_or_covariance_from_text(
        "Daily cross-sectional Pearson correlation of F with forward return; this is also the formula mechanism."
    )
    assert _claims_correlation_or_covariance_from_text(
        "Daily cross-sectional Pearson correlation of F with forward return = the formula mechanism."
    )


def test_operator_claim_scan_ignores_explicit_corr_cov_absence():
    assert not _claims_correlation_or_covariance_from_text(
        "The formula has no correlation operator."
    )
    assert not _claims_correlation_or_covariance_from_text(
        "The formula has no correlation/covariance operator."
    )
    assert not _claims_correlation_or_covariance_from_text(
        "公式无 correlation/covariance 算子。"
    )


def test_operator_claim_scan_ignores_named_evaluation_correlation():
    assert not _claims_correlation_or_covariance_from_text(
        "Daily cross-sectional Spearman/Pearson correlation of F with forward return."
    )


def test_explicit_forward_price_payoff_is_a_legal_target_functional():
    target = (
        "E[close_{i,t+2}/close_{i,t+1} - 1 | F_t, S_{i,t}], "
        "entry t+1 close, exit t+2 close"
    )
    assert _has_explicit_forward_price_payoff(target)
    assert _has_explicit_forward_price_payoff(
        "E[close_{i,t+n}/close_{i,t}-1 | F_t, S_{i,t}]"
    )
    assert _has_explicit_forward_price_payoff(
        "E[close.shift(-n)/close-1 | F_t, S_{i,t}]"
    )
    assert _has_explicit_forward_price_payoff(
        "E[close_{i,t+1}/open_{i,t+1}-1 | F_t, S_{i,t}]"
    )
    assert _has_explicit_forward_price_payoff(
        "E[close_{asset,t+2}/close_{asset,t+1}-1 | F_t, S_{asset,t}]"
    )
    assert _has_explicit_forward_price_payoff(
        r"E[(close_{i,t+2}/close_{i,t+1}-1) | \mathcal{F}_{t}]"
    )
    assert _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, S_{i,t-1}, close.shift(1)]"
    )
    assert _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, S_{i,t-k}, close.shift(k)]"
    )
    assert _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, observed_state_{i,t}]",
        allowed_information_names={"observed_state"},
    )


def test_explicit_price_payoff_requires_future_net_return_and_expectation():
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t}/close_{i,t-1} - 1 | F_t, S_{i,t}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "close_{i,t+2}/close_{i,t+1} - 1 | F_t, S_{i,t}"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2} | F_t, S_{i,t}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2} | F_t]; diagnostic=x/y-1"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t}/close_{i,t-1}-1 | F_t], evaluated at t+2"
    )
    assert not _has_explicit_forward_price_payoff(
        "We expect close_{i,t+2} conditional on F_t; scale=x/y-1"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | S_{i,t}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1not_a_payoff | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | stuff_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2garbage}/close_{i,t+1}-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{j,t+2}/close_{i,t+1}-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,,t+2}/close_{i,t+1}-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{,t+2}/close-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i$,t+2}/close_{i$,t+1}-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[(close_{i,t+2}/close_{i,t+1}-1)garbage | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1,garbage | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{j,t+2}/close.shift(-1)-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close.shift(-2)/close_{i,t+1}-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+3} | E[close_{i,t+2}/close_{i,t+1}-1 | F_t]]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[x | E[close_{i,t+2}/close_{i,t+1}-1 | F_t]]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+3} | F_t]; E[close_{i,t+2}/close_{i,t+1}-1 | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | S_{i,t} | F_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, close_{i,t+3}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, S_{i,t+1}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close.shift(-2)/close.shift(-1)-1 | F_t, close.shift(-3)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, S_{i,t+h}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, lead(close, 1)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, delay(close, -1)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, shift(close, -1)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, close.shift(periods=-1)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, delay(log(close), -1)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, S_{i,t--1}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, S_{i,t^{+1}}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, future_close_{i,t}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, future_close.shift(0)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, next_close.shift(1)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, lead_state.shift(0)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, lookahead_x.shift(2)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, tomorrow_close.shift(1)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | state_{f_t,t}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | state_{i,f_t,t}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, unknown_state_{i,t}]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, forward_return_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, fwd_return_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, target_return_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, label_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, outcome_t]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, forward_return.shift(0)]"
    )
    assert not _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, close_tp1_t]"
    )


def test_main_agent_validator_accepts_explicit_forward_price_payoff_target():
    signature = {
        "rank_ic": "expected rank IC direction compared with observed evidence",
        "long_side": "expected long-side return compared with observed evidence",
        "cost_adjusted": "expected net return compared with observed evidence",
        "monotonicity": "expected ordering compared with observed evidence",
        "turnover": "expected turnover compared with observed evidence",
    }
    failures = validate_main_agent_mechanism_memo(
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "math_hypothesis": {
                "target_functional": (
                    "E[close_{i,t+2}/close_{i,t+1} - 1 | F_t, S_{i,t}]"
                ),
                "expected_metric_signature": signature,
            },
            "expected_metric_signature": dict(signature),
        }
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_TARGET_FUNCTIONAL_INVALID" not in failures


def test_named_return_target_requires_the_same_structured_contract():
    assert _has_explicit_named_return_payoff(
        "E[r_{i,t+1:t+h} | F_t, S_{i,t}]"
    )
    assert _has_explicit_named_return_payoff(
        "E[return_{i,t+1} | F_t, drift_state_t]"
    )
    assert not _has_explicit_named_return_payoff(
        "E[x | F_t]; forward return diagnostic"
    )
    assert not _has_explicit_named_return_payoff(
        "E[r_{i,t+999:t+h} | F_t, S_{i,t}]"
    )
    assert not _has_explicit_named_return_payoff(
        "E[r_{i,t+4097} | F_t, S_{i,t}]"
    )


def test_formal_validator_has_no_named_return_keyword_bypass():
    signature = {
        "rank_ic": "expected rank IC direction compared with observed evidence",
        "long_side": "expected long-side return compared with observed evidence",
        "cost_adjusted": "expected net return compared with observed evidence",
        "monotonicity": "expected ordering compared with observed evidence",
        "turnover": "expected turnover compared with observed evidence",
    }

    def target_failures(target: str, understanding: dict | None = None) -> list[str]:
        return validate_main_agent_mechanism_memo(
            {
                "contract_version": "factorforge_main_agent_mechanism_memo_v1",
                "formula_understanding": understanding or {},
                "math_hypothesis": {
                    "target_functional": target,
                    "expected_metric_signature": signature,
                },
                "expected_metric_signature": dict(signature),
            },
            {
                "canonical_spec": {
                    "formula_text": "close",
                    "required_inputs": ["close"],
                }
            },
        )

    blocker = "BLOCK_MAIN_AGENT_MECHANISM_MEMO_TARGET_FUNCTIONAL_INVALID"
    for target in [
        "E[price_ratio | F_t, forward_return_t]",
        "E[price_ratio | F_t, target_return_t]",
        "E[future_price_level | F_t, forward_return_t]",
        "E[x | F_t]; forward return diagnostic",
    ]:
        assert blocker in target_failures(target)
    assert blocker in target_failures(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, observed_state_{i,t}]",
        {"formula_features": {"fields": ["observed_state"]}},
    )
    huge_offset = "9" * 5_000
    assert blocker in target_failures(f"E[r_{{i,t+{huge_offset}}} | F_t]")
    assert blocker in target_failures(
        f"E[close_{{i,t+{huge_offset}}}/close_{{i,t+1}}-1 | F_t]"
    )
    assert blocker not in target_failures(
        "E[close_{asset,t+2}/close_{asset,t+1}-1 | F_t, S_{asset,t}]"
    )
    for target in [
        "E[close_{i,,t+2}/close_{i,t+1}-1 | F_t]",
        "E[close_{,t+2}/close-1 | F_t]",
        "E[close_{i$,t+2}/close_{i$,t+1}-1 | F_t]",
    ]:
        assert blocker in target_failures(target)


def _operator_claim_failures(claim: str) -> list[str]:
    signature = {
        "rank_ic": "expected rank IC direction is compared with observed evidence",
        "long_side": "expected long-side return is compared with observed evidence",
        "cost_adjusted": "expected net return is compared with observed evidence",
        "monotonicity": "expected ordering is compared with observed evidence",
        "turnover": "expected turnover is compared with observed evidence",
    }
    return validate_main_agent_mechanism_memo(
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "math_hypothesis": {
                "why_not_generic_template": claim,
                "expected_metric_signature": signature,
            },
            "expected_metric_signature": dict(signature),
            "operator_claim_consistency": {
                "claims_correlation_or_covariance": False,
                "formula_has_correlation_or_covariance_operator": False,
                "claims_dependence_without_operator_justification": False,
            },
        }
    )


def test_operator_claim_validator_uses_structured_string_values():
    token = "BLOCK_MAIN_AGENT_MECHANISM_MEMO_OPERATOR_CLAIM_CONTRADICTION"
    assert token not in _operator_claim_failures(
        "公式无 correlation/covariance 算子。"
    )
    assert token not in _operator_claim_failures(
        "Daily cross-sectional Spearman/Pearson correlation of F with forward return."
    )
    assert token in _operator_claim_failures(
        "The formula is a correlation estimator but has no covariance claim."
    )


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
