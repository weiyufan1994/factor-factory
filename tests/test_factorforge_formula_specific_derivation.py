from __future__ import annotations

from copy import deepcopy

from factor_factory.mechanism_math.formula_specific import (
    validate_formula_specific_derivation,
)


def _overnight_reversal_derivation() -> dict:
    payer = (
        "Retail news chasers and quant momentum desks buying gap-ups at the open; "
        "margin-call and panic sellers on gap-down opens; patient market makers "
        "and dealer desks on the other side."
    )
    return {
        "version": "factorforge_formula_specific_derivation_v1",
        "economic_to_math_model_selection": {
            "baseline_model_family": "stochastic_process",
            "why_selected_from_economic_hypothesis": (
                "A conditional return equation tests whether opening news shocks reverse."
            ),
            "why_not_generic_template": (
                "The state binds the legal opening gap, intraday rejection, and volume demand."
            ),
        },
        "profit_payer_derivation": {
            "payer_or_counterparty": payer,
            "why_they_pay": (
                "These retail news traders and momentum desks demand immediacy after the "
                "overnight shock and transfer spread and reversal losses to liquidity suppliers."
            ),
            "mechanism_generating_profit": (
                "Temporary opening impact reverses when closing-price confirmation fails."
            ),
            "expected_payoff_expression_or_argument": (
                "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, formula_state_{i,t}] = theta * formula_state_{i,t}."
            ),
            "economic_hypothesis_source": (
                "Overnight information diffusion creates urgent opening demand."
            ),
            "math_model_link": (
                "A stochastic reversal equation separates the news innovation from residual return noise."
            ),
            "formula_state_link": (
                "The opening gap, failed close confirmation, and relative volume estimate the reversal state."
            ),
        },
        "formula_components": [
            {
                "component": "opening_gap",
                "formula_feature": "open/pre_close-1",
                "state_interpretation": "overnight news shock",
                "mechanism_requirement": "nonzero opening displacement",
            }
        ],
        "selected_model_family": "stochastic_process",
        "process_or_distribution": (
            "g_{i,t}=open/pre_close-1=eta_{i,t}; r_intra=beta*eta+u and "
            "epsilon|F_t~N(0,sigma^2*(1+lambda*v)); theta>0 is reversal."
        ),
        "formula_as_estimator": (
            "formula_state equals the signed opening gap gated by failed close confirmation and volume."
        ),
        "metric_feedback_to_model": (
            "Negative RankIC contradicts the declared positive reversal coefficient."
        ),
        "falsification_tests": [
            "Reject if the sign survives after removing the failed-confirmation gate.",
            "Reject if the named payer strata do not bear the loss after costs.",
        ],
        "kill_criteria": [
            "Kill if after-cost long-side return is non-positive.",
            "Kill if the payer-stratified reversal coefficient is absent.",
        ],
        "revision_implication": "Revise the stochastic state, not the portfolio wrapper.",
    }


def _spec() -> dict:
    return {
        "canonical_spec": {
            "formula_text": (
                "multiply(negate(open/pre_close-1), failed_close_confirmation, relative_volume)"
            ),
            "required_inputs": ["open", "close", "pre_close", "volume"],
        }
    }


def test_specific_trader_types_and_stochastic_equation_are_not_false_rejected() -> None:
    failures = validate_formula_specific_derivation(
        _overnight_reversal_derivation(),
        _spec(),
        {},
    )

    assert failures == []


def test_bare_generic_trader_label_and_formula_restatement_still_block() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["profit_payer_derivation"]["payer_or_counterparty"] = "traders"
    derivation["process_or_distribution"] = (
        "open close pre_close relative_volume failed_close_confirmation formula"
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})
    codes = {failure["code"] for failure in failures}

    assert "BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC" in codes
    assert "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING" in codes


def test_unqualified_generic_actor_combinations_still_block() -> None:
    for actor in ("traders and investors", "market participants or investors"):
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["profit_payer_derivation"]["payer_or_counterparty"] = actor

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert any(
            failure["code"] == "BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC"
            for failure in failures
        )


def test_stochastic_marker_words_without_model_structure_still_block() -> None:
    malformed_models = (
        "open/pre_close-1=epsilon; beta",
        "rank=beta*open/pre_close-1+u; epsilon|F_t~N(0,sigma^2)",
        "r_state=beta*eta+u; u|F_t~sigma",
        "r_state=beta*eta+u; u|F_t~variance",
        "dp=beta*eta+u; u|F_t~N(0,sigma^2)",
        "dp_t=beta*eta+u; u|F_t~N(0,sigma^2)",
        "r=beta*eta+u; u|F_t~N(0,var())",
    )
    for malformed_model in malformed_models:
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["process_or_distribution"] = malformed_model

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert any(
            failure["code"] == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
            for failure in failures
        )


def test_chinese_jump_threshold_equations_and_specific_payers_pass() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "jump_threshold"
    )
    derivation["selected_model_family"] = "jump_threshold"
    derivation["process_or_distribution"] = (
        "O_t=pre_close_t*(1+J_t), J_t 为不对称隔夜跳; C_t=O_t*(1+d_t); "
        "S_t=-sign(J_t)*(1-sign(J_t)*sign(d_t))/2*v_t; "
        "E[r_{i,t+1}|F_t,S_t]=alpha*S_t, 纠错假设 alpha>0。"
    )
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "跳跃阈值模型把隔夜跳、确认失败边界和后续纠错收益连接起来。"
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []


def test_jump_words_without_threshold_state_structure_still_block() -> None:
    malformed_models = (
        "notes pending",
        "a=b; c=d; jump S_t",
        "open=close; relative_volume=1; jump S_t",
        "open=pre_close; failed_close_confirmation=1; threshold sign(",
        "open=epsilon; close=beta; jump",
        "J_t=foo; S_t=sign(foo); E[r|F_t]=alpha*signal_t; jump",
        "J_t=foo; S_t=sign(foo); E[r|F_t]=alpha*situation_t; jump",
    )
    for malformed_model in malformed_models:
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "jump_threshold"
        )
        derivation["selected_model_family"] = "jump_threshold"
        derivation["process_or_distribution"] = malformed_model
        derivation["profit_payer_derivation"]["math_model_link"] = "jump threshold"

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert any(
            failure["code"] == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
            for failure in failures
        )
