from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from factor_factory.mechanism_math.formula_specific import (
    validate_mechanism_formula_consistency,
    validate_formula_specific_derivation,
)
from factor_factory.mechanism_math.main_agent_memo import (
    formula_specific_derivation_from_main_agent_memo,
    validate_main_agent_mechanism_memo,
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


def test_chinese_transient_impact_decomposition_passes() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "结构模型 open/pre_close-1=s+u：s 为持久信息冲击，u 为开盘瞬时订单流冲击；"
        "确认失败日 sign(close-open)=-sign(g) 即 u 主导。"
        "条件期望 E[r_{i,t+1→t+2}|F_t,F_{i,t}]=theta*F_{i,t}，"
        "假设 theta>0，观测 theta 符号为负。"
    )
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "瞬时订单流冲击模型把开盘超调与后续收益连接起来。"
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []


def test_indexed_transient_state_dynamics_from_production_memo_pass() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "g_{i,t}=s_{i,t}+u_{i,t}; "
        "s_{i,t} iid(0,sigma_s^2) persistent news; "
        "u_{i,t+1}=rho*u_{i,t}+eta_{i,t+1}, |rho|<1, "
        "eta iid(0,sigma_e^2); "
        "r_{i,t}=-(1-rho_d)*u_{i,t}+eps_{i,t}; "
        "log v_{i,t}~N(mu_v,sigma_v^2) independent of sign(u); "
        "gate=1 iff (open-pre_close)*(close-open)<0, and "
        "P(|u|>|s||gate=1)>P(|u|>|s|)."
    )
    derivation["latent_state"] = (
        "g=open/pre_close-1=s+u with s persistent news and u an AR(1) "
        "temporary opening-flow component."
    )
    derivation["formula_as_estimator"] = (
        "formula_state estimates -(1-rho)*E[u|F_t,gate=1] scaled by "
        "relative volume; it estimates the temporary component, never s."
    )
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "Transient opening impact u decays separately from persistent news s."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []


def test_observable_bound_transient_model_from_v10_production_memo_passes() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "g_{i,t}=open_{i,t}/pre_close_{i,t}-1=s_{i,t}+u_{i,t}; "
        "s_{i,t} is persistent news absorbed by the t+1 close; "
        "u_{i,t+1}=rho*u_{i,t}+eta_{i,t+1}, |rho|<1, "
        "u is the temporary auction order-flow impact; "
        "return_{i,t+2}=-(1-rho)*u_{i,t}+epsilon_{i,t+2}; "
        "eta and epsilon are zero-mean innovations with finite variance."
    )
    derivation["latent_state"] = (
        "g is the observable opening gap, s is persistent news, and u is the "
        "temporary auction order-flow impact."
    )
    derivation["formula_as_estimator"] = (
        "formula_state estimates u through the observed opening gap, failed "
        "intraday confirmation gate, and relative volume."
    )
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "Transient opening impact u decays separately from persistent news s."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []


def test_observable_binding_cannot_replace_required_transient_structure() -> None:
    malformed_models = (
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u is temporary impact; return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact"
        ),
        (
            "g=open/pre_close-1=s+u; s is news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is a state; "
            "return=theta*u+epsilon"
        ),
        (
            "open pre_close close volume sign mean transient temporary "
            "impact return process formula"
        ),
        (
            "g=open/pre_close-1<=junk=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1>=junk=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1==junk=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1!=junk=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u*epsilon"
        ),
        (
            "g=open/pre_close-1, <=junk=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1 where ==junk=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1, where junk=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "return=theta*u+epsilon"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "收益=theta*u"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "收益=theta*u*epsilon"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "收益率=theta*u"
        ),
        (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            "收益率=theta*u*epsilon"
        ),
    )
    for malformed_model in malformed_models:
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "transient_impact"
        )
        derivation["selected_model_family"] = "transient_impact"
        derivation["process_or_distribution"] = malformed_model
        derivation["latent_state"] = "s and u are separate candidate states."
        derivation["formula_as_estimator"] = "formula_state estimates u."
        derivation["profit_payer_derivation"]["math_model_link"] = (
            "Impact state hypothesis under test."
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert any(
            failure["code"]
            == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
            for failure in failures
        )


def test_chinese_expected_return_can_omit_realized_return_residual() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "g=open/pre_close-1=s+u; s is persistent news; "
        "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
        "预期收益=theta*u"
    )
    derivation["latent_state"] = (
        "s is persistent news and u is temporary opening impact."
    )
    derivation["formula_as_estimator"] = "formula_state estimates u."
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "Transient opening impact u decays separately from persistent news s."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []


def test_fullwidth_colon_payoff_labels_pass() -> None:
    for payoff in (
        "模型：收益=theta*u+epsilon",
        "模型：预期收益=theta*u",
        "payoff：return=theta*u+epsilon",
    ):
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "transient_impact"
        )
        derivation["selected_model_family"] = "transient_impact"
        derivation["process_or_distribution"] = (
            "g=open/pre_close-1=s+u; s is persistent news; "
            "u_{t+1}=rho*u_t+eta, |rho|<1; u is temporary impact; "
            f"{payoff}"
        )
        derivation["latent_state"] = (
            "s is persistent news and u is temporary opening impact."
        )
        derivation["formula_as_estimator"] = "formula_state estimates u."
        derivation["profit_payer_derivation"]["math_model_link"] = (
            "Transient opening impact u decays separately from persistent news s."
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert failures == []


def test_transient_state_dynamics_require_stability_time_and_binding() -> None:
    base = deepcopy(_overnight_reversal_derivation())
    base["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    base["selected_model_family"] = "transient_impact"
    base["latent_state"] = (
        "g=s+u with s persistent news and u an AR(1) temporary impact state."
    )
    base["formula_as_estimator"] = (
        "formula_state estimates temporary impact u, not persistent news s."
    )
    malformed_models = (
        "g=s+u; u_{t+1}=rho*u_t+eta, |rho|>1; r=beta*u+eps",
        "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1.2; r=beta*u+eps",
        "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1e2; r=beta*u+eps",
        "g=s+u; u_{t+1}=rho*u_t+eta, not |rho|<1; r=beta*u+eps",
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, we do not assume |rho|<1; "
            "r=beta*u+eps"
        ),
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, not necessarily |rho|<1; "
            "r=beta*u+eps"
        ),
        "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1+1; r=beta*u+eps",
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1 and |rho|>1; "
            "r=beta*u+eps"
        ),
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "|rho|>1; r=beta*u+eps"
        ),
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "|rho|>1.2; r=beta*u+eps"
        ),
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "|rho|>=2; r=beta*u+eps"
        ),
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "|rho|=1; r=beta*u+eps"
        ),
        (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "rho=2; r=beta*u+eps"
        ),
        "g=s+u; u_{t+1}=rho_d*u_t+eta, |rho|<1; r=beta*u+eps",
        (
            "g=s+u; u_{t+1}=2*rho_d*u_t-rho*u_t+eta, |rho_d|<1; "
            "r=beta*u+eps"
        ),
        "g=s+u; u_{t+1}=2*rho*u_t+eta, |rho|<1; r=beta*u+eps",
        "g=s+u; u_{t+1}=rho*u_t+2*u_t+eta, |rho|<1; r=beta*u+eps",
        "g=s+u; u_{t+1}=rho*u_t+u_t^2+eta, |rho|<1; r=beta*u+eps",
        "g=s+u; u_{t+1}=theta*u_t+eta, |rho|<1; r=beta*u+eps",
        "g=s+u; u_{t+10}=rho*u_t+eta, |rho|<1; r=beta*u+eps",
        "g=s+u; u=rho*u+eta, |rho|<1; r=beta*u+eps",
        "g=s+r; r_{t+1}=rho*r_t+eps, |rho|<1; return=beta*r+eps",
        "g=s+u; x_{t+1}=rho*x_t+eta, |rho|<1; r=beta*u+eps",
    )
    for malformed_model in malformed_models:
        derivation = deepcopy(base)
        derivation["process_or_distribution"] = malformed_model

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert any(
            failure["code"] == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
            for failure in failures
        )


def test_dynamic_state_must_bind_to_formula_estimator() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "junk=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; return=beta*u+epsilon"
    )
    derivation["latent_state"] = "u is a temporary impact state."
    derivation["formula_as_estimator"] = "formula_state estimates x, not u."
    derivation["profit_payer_derivation"]["formula_state_link"] = (
        "The factor estimates x rather than u."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert any(
        failure["code"] == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
        for failure in failures
    )


def test_dynamic_state_formula_link_must_be_positive() -> None:
    for formula_as_estimator in (
        "formula_state does not estimate u.",
        "formula_state is not expected to estimate u.",
        "formula_state fails to estimate u.",
        "formula_state doesn't estimate u.",
        "formula_state estimates no u.",
        "formula_state estimates neither u.",
        "formula_state estimates every state except u.",
        "formula_state estimates no exposure to u.",
        "formula_state estimates without reference to u.",
        "formula_state estimates a state other than u.",
        "formula_state estimates a residual orthogonal to u.",
        "公式不估计 u。",
        "公式不会估计 u。",
        "公式估计不了 u。",
        "公式估计不到 u。",
        "公式估计不出与 u 相关的状态。",
        "公式估计除 u 以外的状态。",
    ):
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "transient_impact"
        )
        derivation["selected_model_family"] = "transient_impact"
        derivation["process_or_distribution"] = (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "return=beta*u+epsilon"
        )
        derivation["latent_state"] = "u is a temporary impact state."
        derivation["formula_as_estimator"] = formula_as_estimator
        derivation["profit_payer_derivation"]["formula_state_link"] = (
            "The factor estimates x rather than u."
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert any(
            failure["code"]
            == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
            for failure in failures
        )


def test_contradictory_formula_state_links_block() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; return=beta*u+epsilon"
    )
    derivation["latent_state"] = "u is a temporary impact state."
    derivation["formula_as_estimator"] = "formula_state estimates u."
    derivation["profit_payer_derivation"]["formula_state_link"] = (
        "The factor does not estimate u."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert any(
        failure["code"] == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
        for failure in failures
    )


def test_transient_role_cannot_be_assembled_across_derivation_fields() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; return=beta*u+epsilon"
    )
    derivation["latent_state"] = "u is"
    derivation["formula_as_estimator"] = "formula_state estimates u."
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "temporary impact state."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert any(
        failure["code"] == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
        for failure in failures
    )


def test_chinese_order_flow_imbalance_is_not_role_negation() -> None:
    for formula_as_estimator in (
        "公式基于订单流不平衡估计 u。",
        "u 由订单流不平衡因子估计。",
    ):
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "transient_impact"
        )
        derivation["selected_model_family"] = "transient_impact"
        derivation["process_or_distribution"] = (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1 and 订单流不平衡; "
            "return=beta*u+epsilon"
        )
        derivation["latent_state"] = "u 为订单流不平衡的临时状态。"
        derivation["formula_as_estimator"] = formula_as_estimator
        derivation["profit_payer_derivation"]["formula_state_link"] = (
            formula_as_estimator
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert failures == []


def test_passive_formula_state_links_are_accepted() -> None:
    for formula_as_estimator in (
        "u is estimated by formula_state.",
        "u 由公式估计。",
    ):
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "transient_impact"
        )
        derivation["selected_model_family"] = "transient_impact"
        derivation["process_or_distribution"] = (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "return=beta*u+epsilon"
        )
        derivation["latent_state"] = "u is a temporary impact state."
        derivation["formula_as_estimator"] = formula_as_estimator
        derivation["profit_payer_derivation"]["formula_state_link"] = (
            formula_as_estimator
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert failures == []


def test_formula_state_links_allow_other_object_qualifiers() -> None:
    for formula_as_estimator in (
        "formula_state estimates a component independent of noise that represents u.",
        "formula_state estimates a component orthogonal to beta that represents u.",
        "formula_state estimates a no arbitrage projection of u.",
        "公式估计非线性变换后的 u。",
        "公式估计独立于噪声的 u。",
    ):
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "transient_impact"
        )
        derivation["selected_model_family"] = "transient_impact"
        derivation["process_or_distribution"] = (
            "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
            "return=beta*u+epsilon"
        )
        derivation["latent_state"] = "u is a temporary impact state."
        derivation["formula_as_estimator"] = formula_as_estimator
        derivation["profit_payer_derivation"]["formula_state_link"] = (
            formula_as_estimator
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert failures == []


def test_transient_state_contrast_does_not_negate_model() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "g=s+u; u_{t+1}=rho*u_t+eta, |rho|<1; "
        "return=beta*u+epsilon"
    )
    derivation["latent_state"] = (
        "u is the temporary impact state, not persistent news s."
    )
    derivation["formula_as_estimator"] = (
        "formula_state estimates temporary impact u, not persistent news s."
    )
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "Transient opening impact u decays separately from persistent news s."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []


def test_transient_impact_keywords_without_structural_model_still_block() -> None:
    malformed_models = (
        "open close pre_close relative_volume transient impact",
        "冲击=冲击；衰减=衰减；收益",
        "transient impact=temporary; return=impact",
        "notes pending",
        (
            "transient impact with persistent and temporary states; "
            "impact_state=persistent_state+temporary_state; "
            "return=theta*unrelated_state"
        ),
        (
            "transient impact with persistent and temporary states; "
            "impact_{i,t}=persistent_{i,t}+temporary_{i,t}; "
            "return_{i,t+1}=theta*unrelated_{i,t}"
        ),
        (
            "transient impact with persistent and temporary states; "
            "x=x+y-y; return=theta*z"
        ),
        (
            "transient impact with persistent and temporary states; "
            "x=2*x+y-y-x; return=theta*x"
        ),
        (
            "transient impact with temporary decay; "
            "impact_state=persistent_state+temporary_state; "
            "return=alphabet*impact_state"
        ),
        "transient impact with temporary decay; return=theta*statement+epsilon",
        (
            "transient impact; open=signal+noise; signal is persistent component, "
            "noise is temporary component; E[r_t|F_t]=theta*formula_noise"
        ),
        (
            "transient impact; multiply_state=signal+noise; "
            "signal is persistent component, noise is temporary component; "
            "E[r_t|F_t]=theta*F_t"
        ),
        (
            "transient impact with persistent and temporary states; "
            "impact_state=sign(foo)+bar; return=theta*sign(unrelated)"
        ),
        (
            "x=a+b because impact state; "
            "return=theta*z because transient impact state"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state+epsilon-epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state+0*epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*unrelated+impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta+impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "impact_state=rho*lagged_state+eta; "
            "return=theta*unrelated under impact_state"
        ),
        (
            "transient impact; open=s+u; s is not persistent component; "
            "u is not temporary component; E[r_t|F_t]=theta*F_t"
        ),
        (
            "transient impact with temporary decay; "
            "非收益=theta*impact_state"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state-theta*impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=0*theta*impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*unrelated alongside impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*unrelated 配合 impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*unrelated,impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*unrelated|impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state)+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state/2-0.5*theta*impact_state+epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state+epsilon/2-0.5*epsilon"
        ),
        (
            "transient impact with temporary decay; impact_state=foo-foo; "
            "return=theta*impact_state"
        ),
        (
            "transient impact; open=s+u; s is nonpersistent component; "
            "u is nontemporary component; E[r_t|F_t]=theta*F_t"
        ),
        (
            "transient impact; open=s+u; s is never persistent component; "
            "u is never temporary component; E[r_t|F_t]=theta*F_t"
        ),
        (
            "transient impact with temporary decay; "
            "impact_state=rho*impact_state+eta; "
            "return=theta*impact_state-theta*impact_state"
        ),
        (
            "transient impact with temporary decay; impact_state=foo-foo+1; "
            "return=theta*impact_state"
        ),
        (
            "transient impact; open=s+u; s is persistent component; "
            "u is temporary component; "
            "E[r_t|F_t]=theta*F_t-theta*F_t"
        ),
        (
            "transient impact; open=s-s+u-u+1; s is persistent component; "
            "u is temporary component; E[r_t|F_t]=theta*F_t"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state*epsilon"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state+epsilon^2"
        ),
        (
            "transient impact with temporary decay; "
            "return=theta*impact_state+unrelated_state*epsilon"
        ),
        (
            "not transient impact with no temporary decay; "
            "return=theta*impact_state+epsilon"
        ),
        (
            "not transient impact with no temporary decay; "
            "impact_state=rho*impact_state+eta; "
            "return=theta*impact_state"
        ),
        (
            "transient impact; open=s+u; s is persistent component; "
            "s is not persistent component; u is temporary component; "
            "u is not temporary component; E[r_t|F_t]=theta*F_t"
        ),
        (
            "不存在瞬时冲击；不存在临时衰减；"
            "return=theta*impact_state+epsilon"
        ),
        (
            "transient impact; open=s+u; s is persistent component; "
            "s 不为持久分量; u is temporary component; "
            "E[r_t|F_t]=theta*F_t"
        ),
        (
            "瞬时冲击不存在；临时衰减不存在；"
            "return=theta*impact_state+epsilon"
        ),
        (
            "transient impact does not exist; temporary decay does not exist; "
            "return=theta*impact_state+epsilon"
        ),
        (
            "transient impact exists; no temporary decay; "
            "return=theta*impact_state+epsilon"
        ),
        "瞬时冲击存在；不存在临时衰减；return=theta*impact_state+epsilon",
        (
            "nontransient impact with temporary decay; "
            "return=theta*impact_state+epsilon"
        ),
        (
            "nonimpact transient process with temporary decay; "
            "return=theta*impact_state+epsilon"
        ),
        (
            "transient impact; open=s_{i,t}+u_{i,t}; "
            "s_{i,t} is persistent component; s_{i,t} 不为持久分量; "
            "u_{i,t} is temporary component; E[r_t|F_t]=theta*F_t"
        ),
    )
    for malformed_model in malformed_models:
        derivation = deepcopy(_overnight_reversal_derivation())
        derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
            "transient_impact"
        )
        derivation["selected_model_family"] = "transient_impact"
        derivation["process_or_distribution"] = malformed_model

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert any(
            failure["code"] == "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING"
            for failure in failures
        )


def test_transient_impact_reduced_form_accepts_greek_coefficients() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "transient impact with temporary decay; "
        "return_{t+1}=θ*impact_state+ε"
    )
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "transient impact links temporary order-flow pressure to future return."
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []

    for indexed_lambda in ("lambda_t", "lambda_{i,t}"):
        derivation["process_or_distribution"] = (
            "transient impact with temporary decay; "
            f"return_{{t+1}}={indexed_lambda}*impact_state+epsilon"
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert failures == []

    for positive_qualifier in (
        "not only transient impact but also temporary decay",
        "no-arbitrage transient impact with temporary decay",
        "without loss of generality transient impact with temporary decay",
        "缺乏流动性导致瞬时冲击并产生临时衰减",
        "without arbitrage capital causing transient impact and temporary decay",
    ):
        derivation["process_or_distribution"] = (
            f"{positive_qualifier}; return=theta*impact_state+epsilon"
        )

        failures = validate_formula_specific_derivation(derivation, _spec(), {})

        assert failures == []

    derivation["process_or_distribution"] = (
        "transient impact; open=s_{i,t}+u_{i,t}; "
        "s_{i,t} is persistent component; u_{i,t} is temporary component; "
        "E[r_t|F_t]=theta*F_t"
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []

    derivation["process_or_distribution"] = (
        "transient impact with temporary decay; "
        "return_{t+1}=2*theta*impact_state-theta*impact_state/2+epsilon"
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []

    derivation["process_or_distribution"] = (
        "transient impact with temporary decay; "
        "return_{t+1}=theta*impact_state+2*epsilon-epsilon"
    )

    failures = validate_formula_specific_derivation(derivation, _spec(), {})

    assert failures == []


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


def test_v9_agent_patch_rehydrates_and_closes_formula_contracts(tmp_path) -> None:
    from factor_factory.console.agent_adapter import AgentResumeTask
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    formula = (
        "-(open / pre_close - 1.0) * "
        "(1.0 - sign((open - pre_close) * (close - open))) / 2.0 * "
        "(vol / mean(vol, 5))"
    )
    signature = {
        "rank_ic": "expected positive; observed rank_ic_mean=-0.017245 contradicts",
        "long_side": "expected positive; observed annual return=-0.137989 contradicts",
        "cost_adjusted": "expected positive; observed annual return=-0.766912 contradicts",
        "monotonicity": "expected increasing deciles; observed top below bottom contradicts",
        "turnover": "expected survivable turnover; observed daily turnover=0.832269 contradicts",
    }
    spec = {
        "canonical_spec": {
            "formula_text": formula,
            "required_inputs": ["close", "open", "pre_close", "vol"],
            "operators": ["divide", "mean", "minus", "multiply", "negate", "sign"],
        }
    }
    estimator = (
        "formula_state estimates temporary impact u, not persistent news s; "
        "F_t=-(open/pre_close-1)*failed_confirmation*(vol/mean(vol,5)), "
        "where relative volume scales precision but never direction."
    )
    memo = {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "report_id": "V9_REGRESSION",
        "factor_id": "OVERNIGHT_REVERSAL_V9",
        "research_id": "v9_regression",
        "producer": "current_main_agent",
        "agent_authorship": {
            "authoring_mode": "current_agent_freeform",
            "agent_role": "main_agent",
            "answered_without_deterministic_template": True,
        },
        "formula": formula,
        "formula_understanding": {
            "formula_features": {
                "fields": ["close", "open", "pre_close", "vol"],
                "operators": ["divide", "mean", "minus", "multiply", "negate", "sign"],
            }
        },
        "formula_component_map": [
            {
                "component_id": "formula_root",
                "formula_subexpression": formula,
                "operators": ["divide", "mean", "minus", "multiply", "negate", "sign"],
                "observable_estimator": estimator,
                "economic_state": "signed temporary opening-auction impact",
                "mathematical_object": "gated and precision-scaled opening-gap state",
                "expected_role": "predict residual impact reversal after close t",
                "metric_link": "positive high-state forward return is required",
            }
        ],
        "mechanism_qa": {
            "formula_state_answer": (
                "open/pre_close identifies the opening gap; the failed close-open sign gate "
                "selects rejected gaps and vol/mean(vol,5) scales precision, yielding temporary impact u."
            ),
            "economic_hypothesis_answer": (
                "Urgent call-auction demand creates temporary impact that patient liquidity suppliers "
                "harvest only when the continuous session rejects the opening gap."
            ),
            "math_model_answer": (
                "A transient-impact model decomposes gap g into persistent news s and temporary u; "
                "stable AR(1) decay maps u to the next close-to-close payoff."
            ),
            "payer_answer": (
                "Retail news chasers, margin-constrained accounts, and panic sellers demand opening "
                "immediacy; institutional rebalancers and arbitrage desks supply liquidity."
            ),
            "payoff_answer": (
                "High formula_state should earn positive close t+2 over close t+1 return because "
                "temporary impact u decays after entry at t+1 close."
            ),
            "estimator_mapping_answer": (
                "open/pre_close sets gap direction, close-open determines failed confirmation, and "
                "vol/mean(vol,5) changes magnitude or precision without independently setting sign."
            ),
            "metric_signature_answer": (
                "The model requires positive rank_ic, top-decile long return, net return, and ordered "
                "deciles at survivable turnover; every observed signature contradicts it."
            ),
            "falsification_answer": (
                "Negative rank_ic_mean, top below bottom, negative gross and net long return, and "
                "0.832269 daily turnover jointly falsify the declared temporary-impact payoff."
            ),
        },
        "economic_hypothesis": {
            "return_source_class": "market_structure_arbitrage",
            "payer_or_counterparty": (
                "Retail news chasers, margin-constrained auction accounts, and panic sellers"
            ),
            "why_they_pay": "Opening immediacy and funding constraints make their demand price inelastic.",
            "necessary_market_structure": "Call auction followed by liquid continuous trading.",
        },
        "math_hypothesis": {
            "selected_model_family": "transient_impact",
            "why_this_model": "The hypothesis separates persistent information from temporary impact.",
            "why_not_generic_template": (
                "The sign gate is discontinuous at z=0; zero receives half weight. Active-boundary "
                "bucket and rank instability can amplify turnover, while relative volume is a "
                "non-negative precision scaler in this exact expression."
            ),
            "random_object": "Per-security-day persistent news s, temporary impact u, and innovations.",
            "latent_state": "u is the temporary impact state, not persistent news s.",
            "process_or_distribution": (
                "g_{i,t}=s_{i,t}+u_{i,t}; s_{i,t} is the persistent news component; "
                "u_{i,t+1}=rho*u_{i,t}+eta_{i,t+1}; |rho|<1; "
                "u_{i,t} is the temporary auction-impact state; "
                "return_{i,t+2}=-(1-rho)*u_{i,t}+epsilon_{i,t+2}"
            ),
            "target_functional": (
                "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, formula_state_{i,t}], "
                "entry t+1 close, exit t+2 close"
            ),
            "formula_as_estimator": estimator,
            "expected_metric_signature": dict(signature),
        },
        "math_model_selection": {
            "model_family": "transient_impact",
            "baseline_model": "g=s+u with stable AR(1) temporary impact u",
            "model_mutation": "failed-confirmation gate plus relative-volume precision scaling",
        },
        "payer": {
            "payer_or_counterparty": "Urgent auction traders facing attention or funding constraints.",
            "why_they_pay": "They demand immediacy at the opening print.",
            "necessary_market_structure": "Opening auction with patient opposite-side liquidity.",
        },
        "formula_state_estimator": {
            "latent_state": "temporary auction-impact state u",
            "observable_mapping": estimator,
            "component_links": ["formula_root"],
        },
        "expected_metric_signature": dict(signature),
        "falsification_tests": [
            "Ablate the failed-confirmation gate and require the full state to improve rank_ic.",
            "Set relative volume to one and require the full state to improve net long return.",
        ],
        "evidence_comparison": {
            "observed_metrics": {
                "rank_ic_mean": -0.017245,
                "long_side_annual_return": -0.137989,
                "cost_adjusted_annual_return": -0.766912,
                "turnover_mean": 0.832269,
            },
            "mechanism_supported": "The declared positive payoff is falsified.",
            "contradictions": ["Every directional and cost signature contradicts the model."],
            "revision_implications": ["Kill and preserve this exact factor identity."],
            "kill_criteria_triggered": ["Negative long-only return after costs."],
        },
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "formula_has_correlation_or_covariance_operator": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "has_sign_or_threshold": True,
            "sign_threshold_discussion_present": True,
            "has_volume_ratio": True,
            "volume_ratio_participation_discussion_present": True,
            "has_additive_rank_raw_ratio": False,
            "additive_scale_commensurability_discussion_present": False,
        },
        "council_questions": ["Confirm kill-and-preserve without sign inversion."],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }

    source = tmp_path / "source"
    workspace = source / "factor_research" / memo["factor_id"] / memo["research_id"]
    (workspace / "identity").mkdir(parents=True)
    (workspace / "objects/research_iteration_master").mkdir(parents=True)
    output_relative = (
        "objects/research_iteration_master/"
        f"main_agent_mechanism_memo__{memo['report_id']}.json"
    )
    task = AgentResumeTask(
        version="factorforge_console_resume_task_v1",
        attempt_id=f"resume_{'a' * 32}",
        job_id="job_v9regression",
        factor_id=memo["factor_id"],
        research_id=memo["research_id"],
        report_id=memo["report_id"],
        resume_start_step="6",
        pause_kind="main_agent_mechanism_memo",
        pause_token="AWAITING_MAIN_AGENT_MECHANISM_MEMO",
        session_policy="fresh_phase_agent",
        ultimate_proof_sha256="b" * 64,
        contract_relative="identity/web_agent_resume_contract.json",
        status_relative=(
            "objects/research_iteration_master/"
            f"main_agent_mechanism_memo_status__{memo['report_id']}.json"
        ),
        questionnaire_relative=(
            "objects/research_iteration_master/"
            f"main_agent_mechanism_questionnaire__{memo['report_id']}.json"
        ),
        questionnaire_markdown_relative=(
            "objects/research_iteration_master/"
            f"main_agent_mechanism_questionnaire__{memo['report_id']}.md"
        ),
        facts_relative="identity/web_main_agent_mechanism_facts.json",
        answer_form_relative="identity/web_main_agent_mechanism_answer_form.json",
        required_output_relative=output_relative,
        optional_output_relative=output_relative.removesuffix(".json") + ".md",
        read_only_inputs=(
            "identity/web_main_agent_mechanism_facts.json",
            "identity/web_main_agent_mechanism_answer_form.json",
        ),
        protected_inputs=(),
        allowed_model_families=("transient_impact",),
        validation_command="validate memo",
    )

    blank_signature = {field: "" for field in signature}
    answer_form = {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "resume_attempt_id": task.attempt_id,
        "report_id": memo["report_id"],
        "factor_id": memo["factor_id"],
        "research_id": memo["research_id"],
        "created_at_utc": "2026-08-04T00:00:00Z",
        "producer": "",
        "agent_authorship": {
            "authoring_mode": "",
            "agent_role": "",
            "answered_without_deterministic_template": False,
        },
        "source_refs": {
            "factor_spec_master": (
                "objects/factor_spec_master/factor_spec_master__V9_REGRESSION.json"
            ),
            "factor_case_master": (
                "objects/factor_case_master/factor_case_master__V9_REGRESSION.json"
            ),
            "evaluation_summary": (
                "objects/validation/factor_evaluation__V9_REGRESSION.json"
            ),
        },
        "formula": formula,
        "formula_understanding": deepcopy(memo["formula_understanding"]),
        "formula_component_map": [
            {
                "component_id": "formula_root",
                "formula_subexpression": formula,
                "operators": spec["canonical_spec"]["operators"],
                "observable_estimator": "",
                "economic_state": "",
                "mathematical_object": "",
                "expected_role": "",
                "metric_link": "",
            }
        ],
        "mechanism_qa": {field: "" for field in memo["mechanism_qa"]},
        "economic_hypothesis": {
            "return_source_class": "",
            "payer_or_counterparty": "",
            "why_they_pay": "",
            "necessary_market_structure": "",
        },
        "math_hypothesis": {
            "selected_model_family": "",
            "why_this_model": "",
            "why_not_generic_template": "",
            "random_object": "",
            "latent_state": "",
            "process_or_distribution": "",
            "target_functional": "",
            "formula_as_estimator": "",
            "expected_metric_signature": dict(blank_signature),
        },
        "math_model_selection": {
            "model_family": "",
            "baseline_model": "",
            "model_mutation": "",
        },
        "payer": {
            "payer_or_counterparty": "",
            "why_they_pay": "",
            "necessary_market_structure": "",
        },
        "formula_state_estimator": {
            "latent_state": "",
            "observable_mapping": "",
            "component_links": [],
        },
        "expected_metric_signature": dict(blank_signature),
        "falsification_tests": [],
        "evidence_comparison": {
            "observed_metrics": deepcopy(memo["evidence_comparison"]["observed_metrics"]),
            "mechanism_supported": "",
            "contradictions": [],
            "revision_implications": [],
            "kill_criteria_triggered": [],
        },
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "formula_has_correlation_or_covariance_operator": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "has_sign_or_threshold": True,
            "sign_threshold_discussion_present": False,
            "has_volume_ratio": True,
            "volume_ratio_participation_discussion_present": False,
            "has_additive_rank_raw_ratio": False,
            "additive_scale_commensurability_discussion_present": False,
        },
        "council_questions": [],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }
    pre_staging_failures = validate_main_agent_mechanism_memo(answer_form, spec)
    assert pre_staging_failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_INVALID" in (
        pre_staging_failures
    )
    answer_form_path = workspace / task.answer_form_relative
    answer_form_path.write_text(
        json.dumps(answer_form, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    facts = {
        "formula_facts": {
            "formula": formula,
            "fields": spec["canonical_spec"]["required_inputs"],
            "operators": spec["canonical_spec"]["operators"],
        },
        "revision_context": {
            "mode": "revision",
            "revision_number": 4,
            "failures": [
                "BLOCK_MECHANISM_FORMULA_OPERATOR_OMISSION",
            ],
        },
    }
    facts_path = workspace / task.facts_relative
    facts_path.write_text(
        json.dumps(facts, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract = {
        "version": task.version,
        "attempt_id": task.attempt_id,
        "job_id": task.job_id,
        "factor_id": task.factor_id,
        "research_id": task.research_id,
        "report_id": task.report_id,
        "answer_form": task.answer_form_relative,
        "input_sha256": {
            task.answer_form_relative: hashlib.sha256(
                answer_form_path.read_bytes()
            ).hexdigest(),
            task.facts_relative: hashlib.sha256(facts_path.read_bytes()).hexdigest(),
        },
    }
    (workspace / task.contract_relative).write_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "identity/web_agent_resume.md").write_text(
        "V9 formula-specific mechanism revision\n",
        encoding="utf-8",
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "parent ledger\n",
        encoding="utf-8",
    )

    agent_patch = {
        "producer": deepcopy(memo["producer"]),
        "agent_authorship": deepcopy(memo["agent_authorship"]),
        "mechanism_qa": deepcopy(memo["mechanism_qa"]),
        "economic_hypothesis": deepcopy(memo["economic_hypothesis"]),
        "math_hypothesis": deepcopy(memo["math_hypothesis"]),
        "math_model_selection": deepcopy(memo["math_model_selection"]),
        "payer": deepcopy(memo["payer"]),
        "formula_state_estimator": deepcopy(memo["formula_state_estimator"]),
        "expected_metric_signature": deepcopy(memo["expected_metric_signature"]),
        "falsification_tests": deepcopy(memo["falsification_tests"]),
        "council_questions": deepcopy(memo["council_questions"]),
        "formula_component_map": [
            {
                "observable_estimator": component["observable_estimator"],
                "economic_state": component["economic_state"],
                "mathematical_object": component["mathematical_object"],
                "expected_role": component["expected_role"],
                "metric_link": component["metric_link"],
            }
            for component in memo["formula_component_map"]
        ],
        "evidence_comparison": {
            "mechanism_supported": memo["evidence_comparison"]["mechanism_supported"],
            "contradictions": deepcopy(memo["evidence_comparison"]["contradictions"]),
            "revision_implications": deepcopy(
                memo["evidence_comparison"]["revision_implications"]
            ),
            "kill_criteria_triggered": deepcopy(
                memo["evidence_comparison"]["kill_criteria_triggered"]
            ),
        },
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "sign_threshold_discussion_present": True,
            "volume_ratio_participation_discussion_present": True,
            "additive_scale_commensurability_discussion_present": False,
        },
    }
    assert "formula" not in agent_patch
    assert "source_refs" not in agent_patch
    assert "observed_metrics" not in agent_patch["evidence_comparison"]
    assert "has_sign_or_threshold" not in agent_patch["operator_claim_consistency"]
    assert set(agent_patch["formula_component_map"][0]) == {
        "observable_estimator",
        "economic_state",
        "mathematical_object",
        "expected_role",
        "metric_link",
    }

    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=source,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    view = adapter._prepare_resume_workspace_view(
        runtime_root=runtime_root,
        workspace=workspace,
        resume_task=task,
    )
    adapter._stage_resume_terminal_delivery(
        view,
        terminal_text=json.dumps(
            {
                "status": "MEMO_DRAFT_COMPLETE",
                "memo": agent_patch,
                "ledger": "V9 formula-specific agent patch staged by Host",
            },
            ensure_ascii=False,
        ),
        resume_task=task,
        rehydrate_immutable_fields=True,
    )
    staged_memo = json.loads(
        (view.root / task.required_output_relative).read_text(encoding="utf-8")
    )
    assert staged_memo["producer"] == agent_patch["producer"]
    assert staged_memo["math_hypothesis"]["process_or_distribution"] == (
        agent_patch["math_hypothesis"]["process_or_distribution"]
    )
    assert staged_memo["formula_component_map"][0]["economic_state"] == (
        agent_patch["formula_component_map"][0]["economic_state"]
    )
    assert staged_memo["evidence_comparison"]["mechanism_supported"] == (
        agent_patch["evidence_comparison"]["mechanism_supported"]
    )
    assert staged_memo["operator_claim_consistency"][
        "sign_threshold_discussion_present"
    ] is True
    assert staged_memo["formula"] == formula
    assert staged_memo["formula_component_map"][0]["component_id"] == "formula_root"
    assert staged_memo["evidence_comparison"]["observed_metrics"] == answer_form[
        "evidence_comparison"
    ]["observed_metrics"]
    assert staged_memo["operator_claim_consistency"]["has_sign_or_threshold"] is True
    assert staged_memo["operator_claim_consistency"]["has_volume_ratio"] is True
    assert staged_memo["source_refs"] == answer_form["source_refs"]
    assert staged_memo["canonical_write_permission"] is False

    assert validate_main_agent_mechanism_memo(staged_memo, spec) == []
    derivation = formula_specific_derivation_from_main_agent_memo(staged_memo, spec)
    analysis = {
        "mechanism_hypothesis": (
            staged_memo["mechanism_qa"]["economic_hypothesis_answer"]
            + " "
            + staged_memo["mechanism_qa"]["math_model_answer"]
        ),
        "formula_specific_derivation": derivation,
        "main_agent_mechanism_memo_takeover": {
            "enabled": True,
            "validation_scope": "main_agent_formula_specific_derivation",
        },
    }
    assert validate_formula_specific_derivation(derivation, spec, analysis) == []
    assert validate_mechanism_formula_consistency(
        spec,
        analysis,
        derivation,
    )["failures"] == []
