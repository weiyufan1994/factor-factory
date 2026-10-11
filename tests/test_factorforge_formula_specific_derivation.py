from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import runpy

import pytest

from factor_factory.formula import parse_formula
from factor_factory.mechanism_math.formula_specific import (
    build_formula_specific_derivation,
    build_formula_specific_headline,
    build_formula_understanding,
    formula_features,
    select_math_model_from_economic_hypothesis,
    validate_mechanism_formula_consistency,
    validate_formula_specific_derivation,
)
from factor_factory.mechanism_math.main_agent_memo import (
    formula_specific_derivation_from_main_agent_memo,
    validate_main_agent_mechanism_memo,
)


@lru_cache(maxsize=1)
def _frozen_transient_recognizer():
    path = Path(__file__).parent / 'fixtures/transient_impact_before_cleanup.py'
    return runpy.run_path(str(path))['_has_explicit_transient_impact_model']


@pytest.fixture(autouse=True)
def _transient_refactor_parity(monkeypatch):
    """Every existing positive/negative derivation test also checks old/new identity."""
    from factor_factory.mechanism_math import formula_specific
    native = formula_specific._has_explicit_transient_impact_model

    def checked(*args, **kwargs):
        actual = native(*args, **kwargs)
        assert actual == _frozen_transient_recognizer()(*args, **kwargs)
        return actual

    monkeypatch.setattr(formula_specific, '_has_explicit_transient_impact_model', checked)


@pytest.mark.parametrize('formula', ['1000*amount', '250*amount', 'amount/250',
                                    'where(amount>250,amount,0)', 'multiply(1000,amount)'])
def test_scales_and_thresholds_are_not_temporal_windows(formula):
    spec = {'canonical_spec': {'formula_text': formula}}
    features = formula_features(spec)
    assert features['has_long_window'] is features['has_250_window'] is False
    assert not features['window_evidence']
    understanding = build_formula_understanding(spec)
    assert understanding['interaction_structure'] != 'slow_state_x_short_horizon_threshold'
    assert 'slow state times short-horizon' not in json.dumps(understanding)
    assert 'sum(returns' not in json.dumps(understanding)


def test_registered_temporal_positions_separate_lags_from_scales():
    features = formula_features({'formula_text': '1000*amount*delay(close,2)'})
    assert features['has_short_delay_or_delta'] and not features['has_long_window']
    assert [(item['operator'], item['window']) for item in features['window_evidence']] == [('delay', 2)]


def test_actual_long_return_sum_and_nonreturn_window_are_distinct():
    returns = formula_features({'formula_text': 'sum(returns,250)'})
    assert returns['has_250_window'] and returns['has_long_return_window']
    volume_spec = {'formula_text': 'sum(amount,250)'}
    volume = formula_features(volume_spec)
    assert volume['has_250_window'] and not volume['has_long_return_window']
    assert 'slow winner' not in json.dumps(build_formula_understanding(volume_spec))
    assert not formula_features({'formula_text': 'sum(returns,240)'})['has_250_window']


def test_temporal_interaction_requires_same_product_branches():
    actual = {'formula_text': 'sum(returns,250)*sign(delta(close,5))'}
    unrelated = {'formula_text': '1000*amount+sum(returns,250)+sign(delta(close,5))'}
    assert build_formula_understanding(actual)['interaction_structure'] == 'long_return_aggregate_x_short_lag_or_difference'
    assert formula_features(unrelated)['has_multiplication']
    assert not formula_features(unrelated)['has_long_return_short_temporal_product']
    assert build_formula_understanding(unrelated)['interaction_structure'] != 'long_return_aggregate_x_short_lag_or_difference'


def test_unsupported_direct_code_does_not_guess_windows():
    code = {'formula_text': 'def feature():\n    n=250\n    return 1000*amount'}
    features = formula_features(code)
    assert features['window_analysis_status'] == 'unknown' and features['window_evidence'] == []
    assert not features['has_250_window'] and not features['has_short_delay_or_delta']
    assert 'long_window_return_sum' not in json.dumps(build_formula_understanding(code))
    assert build_formula_understanding(code)['component_interpretations'][0]['economic_state'].startswith('unresolved')


def test_explicit_measurement_projection_can_supply_recognized_window():
    spec = {'formula_text': 'implementation://custom.py', 'mechanism_conditioned_measurement_program': {
        'observation_and_estimation': {'executable_formula_projection': 'sum(returns,250)'}}}
    features = formula_features(spec)
    assert features['window_analysis_status'] == 'known' and features['has_250_window']
    assert features['window_evidence'][0]['source'] == 'measurement_program.executable_formula_projection'
    spec['mechanism_conditioned_measurement_program']['observation_and_estimation']['executable_formula_projection'] = 'unknown_program_250(amount)'
    assert formula_features(spec)['window_analysis_status'] == 'unknown'


@pytest.mark.parametrize('ir', [
    {}, {'parse_status': 'failed', 'root': {}},
    {'parse_status': 'success', 'root': {'type': 'unsupported', 'window': 250}},
    {'type': 'operator', 'operator': 'custom_250', 'args': []},
    {'type': 'operator', 'operator': 'delay', 'args': [
        {'type': 'field', 'name': 'amount'}, {'type': 'constant', 'value': 2.5}]},
    {'type': 'operator', 'operator': 'sum', 'args': [
        {'type': 'field', 'name': 'returns'}, {'type': 'constant', 'value': 250},
        {'type': 'unsupported'}]},
    {'type': 'operator', 'operator': 'delay', 'args': 250},
])
def test_unrecognized_ir_stays_unknown_or_falls_back_to_valid_text(ir):
    unknown = formula_features({'formula_ir': ir, 'formula_text': 'implementation://custom.py'})
    assert unknown['window_analysis_status'] == 'unknown'
    assert unknown['window_evidence'] == []
    assert not unknown['has_long_window'] and not unknown['has_short_delay_or_delta']
    recovered = formula_features({'formula_ir': ir, 'formula_text': 'delay(amount,2)'})
    assert recovered['window_analysis_status'] == 'known'
    assert [item['window'] for item in recovered['window_evidence']] == [2]


def test_recognized_typed_ir_and_text_have_same_temporal_evidence():
    text = '1000*amount*delay(amount,2)'
    expected = formula_features({'formula_text': text})
    parsed = parse_formula(text)
    for ir in (parsed, parsed['root']):
        actual = formula_features({'formula_ir': ir})
        assert actual['window_analysis_status'] == 'known'
        assert actual['window_evidence'] == expected['window_evidence']
        assert actual['has_short_delay_or_delta'] and not actual['has_long_window']


def test_temporal_structure_does_not_invent_economic_model_or_payer():
    spec = {'formula_text': 'sum(returns,250)*delay(amount,2)'}
    understanding = build_formula_understanding(spec)
    neutral = json.dumps(understanding)
    for invented in ('slow winner', 'pullback', 'reversal', 'price_change'):
        assert invented not in neutral
    assert select_math_model_from_economic_hypothesis({}, [], understanding)['model_family'] == 'other'
    explicit = select_math_model_from_economic_hypothesis(
        {}, [{'model_family': 'dimensional_scaling'}], understanding)
    assert explicit['model_family'] == 'dimensional_scaling'
    assert 'under-specified' in build_formula_specific_headline({}, explicit, understanding)
    economics = {'second_layer': {'subtype': 'declared scale model',
                                 'expected_counterparty_or_payer': 'declared payer',
                                 'why_they_may_pay': 'declared constraint'}}
    headline = build_formula_specific_headline(economics, explicit, understanding)
    assert 'declared payer' in headline and 'declared constraint' in headline
    assert 'trend extrapolators' not in headline
    derived = build_formula_specific_derivation(spec, {})
    assert derived['selected_model_family'] == 'other'
    assert 'slow winner' not in json.dumps(derived)
    assert 'temporary dislocation' not in json.dumps(derived)


def test_temporal_consistency_does_not_require_an_invented_economic_story():
    spec = {'formula_text': 'sum(returns,250)*delay(amount,2)'}
    explanation = {'explanation': 'Declared aggregation and lag estimate the selected observable.'}
    assert validate_mechanism_formula_consistency(spec, {}, explanation)['status'] == 'PASS'
    # A mathematical discontinuity still requires discussion; the fix does not
    # disable the separate sign/threshold obligation or field contradictions.
    threshold = {'formula_text': 'sum(returns,250)*sign(delta(close,5))'}
    failures = validate_mechanism_formula_consistency(threshold, {}, explanation)['failures']
    assert any('sign/threshold' in item['message'] for item in failures)
    contradiction = {'explanation': 'A volume correlation model explains this feature.'}
    failures = validate_mechanism_formula_consistency(threshold, {}, contradiction)['failures']
    assert any(item['code'] == 'BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION' for item in failures)


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


def test_signed_conditional_mean_regression_is_a_model_not_formula_restatement() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = "other"
    derivation["selected_model_family"] = "other"
    derivation["process_or_distribution"] = (
        "E[next_month_return_{i,m+1}|F_m]=alpha_m+beta_L*measured_object_{i,m}"
        "+gamma'*controls_{i,m}, with beta_L>0 under liquidity compensation"
    )

    regression_spec = {
        "canonical_spec": {
            "formula_text": "X20=measured_object(amount)",
            "required_inputs": ["amount"],
        }
    }
    codes = {
        failure["code"]
        for failure in validate_formula_specific_derivation(derivation, regression_spec, {})
    }
    assert "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING" not in codes

    unsigned = deepcopy(derivation)
    unsigned["process_or_distribution"] = (
        "E[next_month_return_{i,m+1}|F_m]=alpha_m+beta_L*measured_object_{i,m}"
    )
    unsigned_codes = {
        failure["code"]
        for failure in validate_formula_specific_derivation(unsigned, regression_spec, {})
    }
    assert "BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING" in unsigned_codes


def test_derivation_preserves_explicit_reject_evidence_instead_of_forcing_iteration() -> None:
    memo = {
        "mechanism_qa": {
            "metric_signature_answer": "Legacy summary that must not replace observed evidence.",
            "falsification_answer": "Legacy fallback that must not replace observed evidence.",
        },
        "math_hypothesis": {},
        "economic_hypothesis": {},
        "formula_component_map": [],
        "evidence_comparison": {
            "observed_metrics": {"long_side_sharpe": -0.31},
            "mechanism_supported": "not_supported_for_current_realization",
            "contradictions": ["after-cost long side is negative"],
            "revision_implications": ["Reject and preserve this realization."],
            "kill_criteria_triggered": [
                "negative net long-side payoff",
                "incremental signal unsupported",
            ],
        },
    }

    derivation = formula_specific_derivation_from_main_agent_memo(memo)

    assert derivation["kill_criteria"] == [
        "negative net long-side payoff",
        "incremental signal unsupported",
    ]
    assert derivation["revision_implication"] == "Reject and preserve this realization."
    assert '"long_side_sharpe": -0.31' in derivation["observed_metric_comparison"]
    assert derivation["metric_feedback_to_model"] == derivation[
        "observed_metric_comparison"
    ]


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


def test_v11_chinese_transient_memo_retains_operator_and_state_binding() -> None:
    derivation = deepcopy(_overnight_reversal_derivation())
    derivation["economic_to_math_model_selection"]["baseline_model_family"] = (
        "transient_impact"
    )
    derivation["selected_model_family"] = "transient_impact"
    derivation["process_or_distribution"] = (
        "g_{i,t}=open_{i,t}/pre_close_{i,t}-1=s_{i,t}+u_{i,t}; "
        "u_{i,t+1}=rho*u_{i,t}+eta_{i,t+1}, |rho|<1; "
        "return_{i,t+2}=-(1-rho)*u_{i,t}+epsilon_{i,t+2}; "
        "u_{i,t} is the temporary opening-auction impact state"
    )
    derivation["latent_state"] = (
        "临时开盘订单流冲击 u_{i,t} 按 AR(1) 衰减；s_{i,t} 是持久信息冲击。"
    )
    derivation["formula_as_estimator"] = (
        "formula_state_{i,t}=-g_{i,t}*h_{i,t}*v_{i,t}，估计 -u_{i,t}；"
        "v 是非负强度缩放，不独立决定方向。"
    )
    derivation["formula_state_estimator"] = {
        "latent_state": "temporary opening-auction impact u",
        "observable_mapping": "formula_state=-g*h*v，估计 -u*v。",
        "component_links": ["formula_root"],
    }
    derivation["operator_consistency_discussion"] = {
        "formula_state_answer": (
            "z=(open-pre_close)*(close-open)；z<0 时 h=1，z>0 时 h=0，"
            "z=0 时 h=0.5；零点是不连续边界，会造成 bucket、rank 与 turnover 不稳定。"
        ),
        "estimator_mapping_answer": "公式 F=-g*h*v 直接估计临时冲击 -u。",
        "operator_claim_consistency": {
            "sign_threshold_discussion_present": True,
            "explicit_dependence_justification": (
                "因子与后续收益的依赖由 return=-(1-rho)*u+epsilon 与公式 F=-g*h*v（估计 -u）给出。"
            ),
        },
    }
    derivation["profit_payer_derivation"]["math_model_link"] = (
        "临时开盘冲击 u 与持久信息 s 分离，并按稳定 AR(1) 衰减。"
    )

    assert validate_formula_specific_derivation(derivation, _spec(), {}) == []

    spec = {
        "canonical_spec": {
            "formula_text": (
                "-(open / pre_close - 1.0) * "
                "(1.0 - sign((open - pre_close) * (close - open))) / 2.0 * "
                "(vol / mean(vol, 5))"
            ),
            "required_inputs": ["open", "close", "pre_close", "vol"],
            "operators": ["divide", "mean", "minus", "multiply", "negate", "sign"],
        }
    }
    analysis = {
        "formula_specific_derivation": derivation,
        "main_agent_mechanism_memo_takeover": {
            "enabled": True,
            "validation_scope": "main_agent_formula_specific_derivation",
        },
    }
    assert validate_mechanism_formula_consistency(
        spec,
        analysis,
        derivation,
    )["failures"] == []


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


