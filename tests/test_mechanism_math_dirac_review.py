from __future__ import annotations

import copy

from factor_factory.mechanism_math.classifier import build_mechanism_math_contract_v2
from factor_factory.mechanism_math.main_agent_memo import (
    _claims_correlation_or_covariance_from_text,
    _declared_current_state_names,
    _has_explicit_forward_price_payoff,
    _has_explicit_named_return_payoff,
    _normalize_current_observation_indices,
    _require_open_answer,
    formula_specific_qa_terms,
    memo_public_schema_failures,
    project_public_observed_metric_conflict_keys,
    project_public_observed_metrics,
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


def test_formula_specific_qa_terms_normalize_prompt_and_validator_collections():
    expected = {"close", "foo"}
    assert formula_specific_qa_terms(
        "rank(foo)",
        operators=["rank"],
        fields=["close"],
    ) == expected
    assert formula_specific_qa_terms(
        "rank(foo)",
        operators={"rank"},
        fields=frozenset({"close"}),
    ) == expected
    assert formula_specific_qa_terms(
        "rank(divide(close, open))",
        operators=set(),
        fields=frozenset(),
    ) == {"close", "open"}
    assert formula_specific_qa_terms(
        "rank(divide())",
        operators=set(),
        fields=frozenset(),
    ) == set()


def test_formula_specific_answers_each_require_a_literal_locked_token():
    formula_terms = formula_specific_qa_terms(
        "divide(abs(open - pre_close), close)",
        operators={"divide", "abs"},
        fields={"open", "pre_close", "close"},
    )
    alias_only = (
        "G, R, and J identify the measured object and its mapping while the "
        "derivation states why the constructed magnitude tracks the latent "
        "condition at the legal information time."
    )

    def answer_failures(state_answer: str, estimator_answer: str) -> list[str]:
        failures: list[str] = []
        qa = {
            "formula_state_answer": state_answer,
            "estimator_mapping_answer": estimator_answer,
        }
        for field in qa:
            _require_open_answer(
                failures,
                qa,
                field,
                formula_terms=formula_terms,
                generic_terms=[],
            )
        return failures

    state_blocker = (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_NOT_FORMULA_SPECIFIC:"
        "formula_state_answer"
    )
    estimator_blocker = (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_NOT_FORMULA_SPECIFIC:"
        "estimator_mapping_answer"
    )
    assert answer_failures(alias_only, alias_only) == [
        state_blocker,
        estimator_blocker,
    ]
    assert answer_failures(f"{alias_only} open", alias_only) == [
        estimator_blocker
    ]
    assert answer_failures(
        f"{alias_only} open",
        f"{alias_only} pre_close",
    ) == []


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
    assert _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, measured_object_{i,t}] "
        "positive for high-factor deciles, negative for low-factor deciles; "
        "entry t+1 close, exit t+2 close; F_t holds only t-close data.",
        allowed_information_names={"measured_object"},
    )
    assert _has_explicit_forward_price_payoff(
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, C_{i,t}]="
        "-lambda*C_{i,t}; entry t+1 close, exit t+2 close",
        allowed_information_names={"c"},
    )


def test_declared_current_state_requires_observable_nonanticipative_definition():
    current = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": (
                "C_{i,t}=rolling_kurtosis(close,5)+rolling_skew(volume,5)"
            )
        }
    }
    future_shift = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=close.shift(-1)"
        }
    }
    future_name = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=future_return+close"
        }
    }
    unobservable = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=unobserved_state"
        }
    }
    mixed_unobservable = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": (
                "C_{i,t}=rolling_kurtosis(close,5)+unobserved_state"
            )
        }
    }
    negative_lag = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=lag(close,-1)"
        }
    }
    prefixed_negative_lag = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=ts_delay(close,-1)"
        }
    }
    symbolic_negative_lags = [
        {
            "math_hypothesis": {
                "mechanism_equation_or_functional": equation
            }
        }
        for equation in (
            "C_{i,t}=ts_delay(close,-k)",
            "C_{i,t}=rolling_shift(close,-h)",
            "C_{i,t}=lag(close,-n)",
            "C_{i,t}=ts_delay(log(close),-k)",
            "C_{i,t}=close.shift(periods=-1)",
            "C_{i,t}=ts_delay(close,5,-1)",
            "C_{i,t}=ts_delay(close,5,periods=-1)",
            "C_{i,t}=ts_delay(close,5,k)",
            "C_{i,t}=ts_delay(close,periods=-1==5)",
            "C_{i,t}=close(",
            "C_{i,t}=close+\u672a\u6765\u6536\u76ca",
            "C_{i,t}=delta(close,-1)",
            "C_{i,t}=diff(close,-1)",
            "C_{i,t}=mean(close,window=5,center=1)",
            "C_{i,t}=rank(close,future_return=1)",
            "C_{i,t}=tsdelay(close,-1)",
            "C_{i,t}=close+\ud800",
            "C_{i,t}=close+returns",
        )
    ]
    unproven_symbolic_lag = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=ts_delay(close,k)"
        }
    }
    explicit_past_lag = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=ts_delay(log(close),5)"
        }
    }
    undeclared_operator = {
        "math_hypothesis": {
            "mechanism_equation_or_functional": "C_{i,t}=rolling_oracle(close,5)"
        }
    }

    assert _declared_current_state_names(
        current,
        {"close", "volume"},
        {"rolling_kurtosis", "rolling_skew"},
    ) == {"c"}
    assert _declared_current_state_names(future_shift, {"close"}) == set()
    assert _declared_current_state_names(future_name, {"close"}) == set()
    assert _declared_current_state_names(unobservable, {"close"}) == set()
    assert _declared_current_state_names(mixed_unobservable, {"close"}) == set()
    assert _declared_current_state_names(negative_lag, {"close"}) == set()
    assert _declared_current_state_names(
        prefixed_negative_lag,
        {"close"},
        {"ts_delay"},
    ) == set()
    for symbolic_negative_lag in symbolic_negative_lags:
        assert _declared_current_state_names(
            symbolic_negative_lag,
            {"close"},
            {"lag", "rolling_shift", "ts_delay"},
        ) == set()
    assert _declared_current_state_names(
        unproven_symbolic_lag,
        {"close"},
        {"ts_delay"},
    ) == set()
    assert _declared_current_state_names(
        explicit_past_lag,
        {"close"},
        {"ts_delay"},
    ) == {"c"}
    assert _declared_current_state_names(
        {
            "math_hypothesis": {
                "mechanism_equation_or_functional": "C_{i,t}=delta(close,5)"
            }
        },
        {"close"},
        {"delta"},
    ) == {"c"}
    assert _declared_current_state_names(
        {
            "math_hypothesis": {
                "mechanism_equation_or_functional": "C_{i,t}=close+returns"
            }
        },
        {"close", "returns"},
        set(),
    ) == {"c"}
    for equation, operators in (
        ("C_{i,t}=ts_delay(close,lag=5)", {"ts_delay"}),
        ("C_{i,t}=delta(close,window=5)", {"delta"}),
    ):
        assert _declared_current_state_names(
            {
                "math_hypothesis": {
                    "mechanism_equation_or_functional": equation
                }
            },
            {"close"},
            operators,
        ) == {"c"}
    assert _declared_current_state_names(
        {
            "math_hypothesis": {
                "mechanism_equation_or_functional": "C_{i,t}=" + "+" * 6_000 + "close"
            }
        },
        {"close"},
        set(),
    ) == set()
    assert _declared_current_state_names(
        undeclared_operator,
        {"close"},
        {"rolling_kurtosis"},
    ) == set()


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
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, measured_object_{i,t+1}]",
        allowed_information_names={"measured_object"},
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
                "mathematical_object": "Current observable crowding object",
                "observation_mapping": "rank(close) maps the crowding object at t",
                "target_functional": (
                    "E[close_{i,t+2}/close_{i,t+1} - 1 | F_t, S_{i,t}]"
                ),
                "market_outcome_projection": (
                    "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
                    "measured_object_{i,t}] positive for high-factor deciles, "
                    "negative for low-factor deciles; entry t+1 close, exit "
                    "t+2 close; F_t holds only t-close data."
                ),
                "expected_metric_signature": signature,
            },
            "mathematical_object_mapping": {
                "component_links": ["formula_root"],
                "mathematical_object": "Current observable crowding object",
                "observation_mapping": "rank(close) maps the crowding object at t",
            },
            "formula_component_map": [
                {
                    "component_id": "formula_root",
                    "formula_subexpression": "rank(close)",
                    "observable_estimator": "rank(close)",
                    "economic_state": "current crowding",
                    "mathematical_object": "current crowding object",
                    "expected_role": "rank current crowding",
                }
            ],
            "expected_metric_signature": dict(signature),
        },
        {
            "canonical_spec": {
                "formula_text": "rank(close)",
                "required_inputs": ["close"],
                "operators": ["rank"],
            }
        },
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_TARGET_FUNCTIONAL_INVALID" not in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" not in failures


def test_measured_object_projection_requires_current_bound_observation_mapping():
    signature = {
        "rank_ic": "expected rank IC direction compared with observed evidence",
        "long_side": "expected long-side return compared with observed evidence",
        "cost_adjusted": "expected net return compared with observed evidence",
        "monotonicity": "expected ordering compared with observed evidence",
        "turnover": "expected turnover compared with observed evidence",
    }
    memo = {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "math_hypothesis": {
            "mathematical_object": "Current observable crowding object",
            "mechanism_equation_or_functional": "C_{i,t}=close",
            "observation_mapping": "rank(close) maps the crowding object at t",
            "target_functional": (
                "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, C_{i,t}]"
            ),
            "market_outcome_projection": (
                "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
                "measured_object_{i,t}] positive for high-factor deciles"
            ),
            "expected_metric_signature": signature,
        },
        "mathematical_object_mapping": {
            "component_links": ["formula_root"],
            "mathematical_object": "Current observable crowding object",
            "observation_mapping": "rank(close) maps the crowding object at t",
        },
        "formula_component_map": [
            {
                "component_id": "formula_root",
                "formula_subexpression": "rank(close)",
                "observable_estimator": "rank(close)",
                "economic_state": "current crowding",
                "mathematical_object": "current crowding object",
                "expected_role": "rank current crowding",
            }
        ],
        "expected_metric_signature": dict(signature),
    }
    spec = {
        "canonical_spec": {
            "formula_text": "rank(close)",
            "required_inputs": ["close"],
            "operators": ["rank"],
        }
    }

    failures = validate_main_agent_mechanism_memo(memo, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" not in failures

    for mismatched_projection in (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
        "measured_object_{oracle,t}] positive for high-factor deciles",
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
        "measured_object_{i,j,t}] positive for high-factor deciles",
    ):
        mismatched = copy.deepcopy(memo)
        mismatched["math_hypothesis"][
            "market_outcome_projection"
        ] = mismatched_projection
        failures = validate_main_agent_mechanism_memo(mismatched, spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for indexed_mapping in (
        "rank(close_{i,t}) maps the crowding object",
        "rank(close_t) maps the crowding object",
    ):
        indexed = copy.deepcopy(memo)
        indexed["math_hypothesis"]["observation_mapping"] = indexed_mapping
        indexed["mathematical_object_mapping"]["observation_mapping"] = (
            indexed_mapping
        )
        failures = validate_main_agent_mechanism_memo(indexed, spec)
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            not in failures
        )

    for domain_label in (
        "temporary order-flow pressure",
        "realized volatility regime",
        "participation ratio",
        "earnings quality accrual signal",
        "cross-sectional market-cap and value-weighted price-volume state",
        "market leader crowding state",
        "leadership score",
        "pleading score",
        "proxy for volatility",
    ):
        domain_mapping = copy.deepcopy(memo)
        mathematical_object = f"Current observable {domain_label} object"
        mapping = f"rank(close) estimates {domain_label}"
        domain_mapping["math_hypothesis"]["mathematical_object"] = (
            mathematical_object
        )
        domain_mapping["math_hypothesis"]["observation_mapping"] = mapping
        domain_mapping["mathematical_object_mapping"]["mathematical_object"] = (
            mathematical_object
        )
        domain_mapping["mathematical_object_mapping"]["observation_mapping"] = (
            mapping
        )
        failures = validate_main_agent_mechanism_memo(domain_mapping, spec)
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            not in failures
        )

    plain_current_alias = copy.deepcopy(memo)
    plain_current_alias["math_hypothesis"]["mathematical_object"] = (
        "Current observable crowding object Q_t"
    )
    plain_current_alias["mathematical_object_mapping"]["mathematical_object"] = (
        "Current observable crowding object Q_t"
    )
    plain_current_alias["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "Q_{i,t}=close"
    failures = validate_main_agent_mechanism_memo(plain_current_alias, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" not in failures

    explicit_current_definition = copy.deepcopy(memo)
    explicit_current_definition["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "measured_object_{i,t}=close"
    failures = validate_main_agent_mechanism_memo(explicit_current_definition, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" not in failures

    symbolic_named_range = copy.deepcopy(memo)
    symbolic_named_range["math_hypothesis"]["market_outcome_projection"] = (
        "E[r_{i,t+1->t+h} | F_t, measured_object_{i,t}] positive for "
        "high-factor deciles; entry t+1 close, exit t+h close"
    )
    failures = validate_main_agent_mechanism_memo(symbolic_named_range, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" not in failures

    parenthesized_sign_binding = copy.deepcopy(memo)
    parenthesized_sign_binding["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, measured_object_{i,t}] "
        "(positive for high) and negative for low"
    )
    failures = validate_main_agent_mechanism_memo(parenthesized_sign_binding, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" not in failures

    for canonical_formula, wrong_mapping, required_inputs, operators in (
        (
            "rank(abs(close))",
            "abs(rank(close)) maps the crowding object at t",
            ["close"],
            ["rank", "abs"],
        ),
        (
            "rank(close + volume)",
            "rank(close / volume) maps the crowding object at t",
            ["close", "volume"],
            ["rank", "plus"],
        ),
        (
            "rank(close + volume)",
            "rank(close + 0 * volume) maps the crowding object at t",
            ["close", "volume"],
            ["rank", "plus"],
        ),
    ):
        topology_mismatch = copy.deepcopy(memo)
        topology_mismatch["formula_component_map"][0][
            "formula_subexpression"
        ] = canonical_formula
        topology_mismatch["math_hypothesis"]["observation_mapping"] = wrong_mapping
        topology_mismatch["mathematical_object_mapping"][
            "observation_mapping"
        ] = wrong_mapping
        topology_spec = {
            "canonical_spec": {
                "formula_text": canonical_formula,
                "required_inputs": required_inputs,
                "operators": operators,
            }
        }
        failures = validate_main_agent_mechanism_memo(
            topology_mismatch,
            topology_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for canonical_formula, operators, required_inputs in (
        ("ts_sum(close, 5)", ["sum"], ["close"]),
        ("rolling_corr(close, volume, 5)", ["correlation"], ["close", "volume"]),
        ("lag(close, 1)", ["delay"], ["close"]),
        ("ref(close, 1)", ["delay"], ["close"]),
        ("signed_power(close, 2)", ["signedpower"], ["close"]),
        ("close + 1.", ["plus"], ["close"]),
        (
            "rank(close) + scale(volume)",
            ["plus", "rank", "scale"],
            ["close", "volume"],
        ),
        (
            "regression(close, volume, out_type=0)",
            ["cs_regression"],
            ["close", "volume"],
        ),
    ):
        parser_alias = copy.deepcopy(memo)
        parser_alias["formula_component_map"][0][
            "formula_subexpression"
        ] = canonical_formula
        parser_alias["math_hypothesis"]["observation_mapping"] = (
            f"{canonical_formula} maps the crowding object at t"
        )
        parser_alias["mathematical_object_mapping"]["observation_mapping"] = (
            parser_alias["math_hypothesis"]["observation_mapping"]
        )
        alias_spec = {
            "canonical_spec": {
                "formula_text": canonical_formula,
                "required_inputs": required_inputs,
                "operators": operators,
            }
        }
        failures = validate_main_agent_mechanism_memo(parser_alias, alias_spec)
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            not in failures
        )

    for unauthorized_clause in (
        "mean(close, 5) transforms the crowding object at t",
        "close % 2 transforms the crowding object at t",
        "close if close > 0 else -close transforms the crowding object at t",
        "rank(oracle) transforms the crowding object at t",
        "rank(close)- transforms the crowding object at t",
        "rank(close), transforms the crowding object at t",
    ):
        clause_injection = copy.deepcopy(memo)
        injected_mapping = (
            "rank(close) maps the crowding object at t; " + unauthorized_clause
        )
        clause_injection["math_hypothesis"]["observation_mapping"] = (
            injected_mapping
        )
        clause_injection["mathematical_object_mapping"][
            "observation_mapping"
        ] = injected_mapping
        failures = validate_main_agent_mechanism_memo(clause_injection, spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    ignored_canonical = copy.deepcopy(memo)
    ignored_canonical_formula = (
        "cs_regression(close, volume, 0, fill_predict=False)"
    )
    ignored_canonical["formula_component_map"][0][
        "formula_subexpression"
    ] = ignored_canonical_formula
    ignored_canonical_mapping = (
        f"{ignored_canonical_formula} maps the crowding object at t"
    )
    ignored_canonical["math_hypothesis"][
        "observation_mapping"
    ] = ignored_canonical_mapping
    ignored_canonical["mathematical_object_mapping"][
        "observation_mapping"
    ] = ignored_canonical_mapping
    ignored_canonical_spec = {
        "canonical_spec": {
            "formula_text": ignored_canonical_formula,
            "required_inputs": ["close", "volume"],
            "operators": ["cs_regression"],
        }
    }
    failures = validate_main_agent_mechanism_memo(
        ignored_canonical,
        ignored_canonical_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for ignored_keyword in (
        "Fill_Predict=oracle",
        "WITH_ONE_COL=oracle(close)",
        "DuMmIeS=oracle",
    ):
        uppercase_ignored = copy.deepcopy(memo)
        uppercase_formula = (
            f"cs_regression(close, volume, 0, {ignored_keyword})"
        )
        uppercase_ignored["formula_component_map"][0][
            "formula_subexpression"
        ] = uppercase_formula
        uppercase_mapping = (
            "cs_regression(close, volume, 0) maps the crowding object at t"
        )
        uppercase_ignored["math_hypothesis"][
            "observation_mapping"
        ] = uppercase_mapping
        uppercase_ignored["mathematical_object_mapping"][
            "observation_mapping"
        ] = uppercase_mapping
        uppercase_spec = {
            "canonical_spec": {
                "formula_text": uppercase_formula,
                "required_inputs": ["close", "volume"],
                "operators": ["cs_regression"],
            }
        }
        failures = validate_main_agent_mechanism_memo(
            uppercase_ignored,
            uppercase_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    ignored_non_root = copy.deepcopy(memo)
    ignored_non_root["formula_component_map"].append(
        {
            **copy.deepcopy(memo["formula_component_map"][0]),
            "component_id": "ignored_subtree",
            "formula_subexpression": (
                "cs_regression(close, volume, 0, Fill_Predict=oracle)"
            ),
        }
    )
    ignored_non_root["mathematical_object_mapping"]["component_links"].append(
        "ignored_subtree"
    )
    ignored_non_root_spec = {
        "canonical_spec": {
            "formula_text": "rank(close) + cs_regression(close, volume, 0)",
            "required_inputs": ["close", "volume"],
            "operators": ["cs_regression", "plus", "rank"],
        }
    }
    ignored_non_root["formula_component_map"][0]["formula_subexpression"] = (
        ignored_non_root_spec["canonical_spec"]["formula_text"]
    )
    ignored_non_root_mapping = (
        "rank(close) + cs_regression(close, volume, 0) "
        "maps the crowding object at t; "
        "cs_regression(close, volume, 0) maps the crowding object at t"
    )
    ignored_non_root["math_hypothesis"][
        "observation_mapping"
    ] = ignored_non_root_mapping
    ignored_non_root["mathematical_object_mapping"][
        "observation_mapping"
    ] = ignored_non_root_mapping
    failures = validate_main_agent_mechanism_memo(
        ignored_non_root,
        ignored_non_root_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for injected_mapping in (
        "rank(close) # oracle maps the crowding object at t",
        (
            "cs_regression(close, volume, 0, fill_predict=oracle) "
            "maps the crowding object at t"
        ),
    ):
        ignored_syntax = copy.deepcopy(memo)
        canonical_formula = (
            "rank(close)"
            if injected_mapping.startswith("rank")
            else "cs_regression(close, volume, 0)"
        )
        ignored_syntax["formula_component_map"][0][
            "formula_subexpression"
        ] = canonical_formula
        ignored_syntax["math_hypothesis"]["observation_mapping"] = (
            injected_mapping
        )
        ignored_syntax["mathematical_object_mapping"][
            "observation_mapping"
        ] = injected_mapping
        ignored_spec = {
            "canonical_spec": {
                "formula_text": canonical_formula,
                "required_inputs": (
                    ["close"]
                    if canonical_formula.startswith("rank")
                    else ["close", "volume"]
                ),
                "operators": (
                    ["rank"]
                    if canonical_formula.startswith("rank")
                    else ["cs_regression"]
                ),
            }
        }
        failures = validate_main_agent_mechanism_memo(
            ignored_syntax,
            ignored_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    historical_index = copy.deepcopy(memo)
    historical_mapping = (
        "rank(close_{i,t-1}) maps the crowding object at t"
    )
    historical_index["math_hypothesis"][
        "observation_mapping"
    ] = historical_mapping
    historical_index["mathematical_object_mapping"][
        "observation_mapping"
    ] = historical_mapping
    failures = validate_main_agent_mechanism_memo(historical_index, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for future_field in ("target_state", "forward_state", "lead_state", "fwd_signal"):
        future_observable = copy.deepcopy(memo)
        future_formula = f"rank({future_field})"
        future_observable["formula_component_map"][0][
            "formula_subexpression"
        ] = future_formula
        future_mapping = f"{future_formula} maps the crowding object at t"
        future_observable["math_hypothesis"][
            "observation_mapping"
        ] = future_mapping
        future_observable["mathematical_object_mapping"][
            "observation_mapping"
        ] = future_mapping
        future_spec = {
            "canonical_spec": {
                "formula_text": future_formula,
                "required_inputs": [future_field],
                "operators": ["rank"],
            }
        }
        failures = validate_main_agent_mechanism_memo(
            future_observable,
            future_spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    reduced_graph = copy.deepcopy(memo)
    reduced_graph["formula_component_map"] = [
        {
            **copy.deepcopy(memo["formula_component_map"][0]),
            "component_id": "close_component",
            "formula_subexpression": "close",
        }
    ]
    reduced_graph["mathematical_object_mapping"]["component_links"] = [
        "close_component"
    ]
    reduced_mapping = "close maps the crowding object at t"
    reduced_graph["math_hypothesis"]["observation_mapping"] = reduced_mapping
    reduced_graph["mathematical_object_mapping"][
        "observation_mapping"
    ] = reduced_mapping
    reduced_spec = {
        "canonical_spec": {
            "formula_text": "rank(close + volume)",
            "required_inputs": ["close", "volume"],
            "operators": ["plus", "rank"],
        }
    }
    failures = validate_main_agent_mechanism_memo(reduced_graph, reduced_spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    extra_declared_input = copy.deepcopy(memo)
    extra_declared_input["math_hypothesis"]["mathematical_object"] = (
        "Current observable q object Q_t"
    )
    extra_declared_input["mathematical_object_mapping"][
        "mathematical_object"
    ] = "Current observable q object Q_t"
    extra_declared_input["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "Q_{i,t}=oracle"
    extra_input_spec = {
        "canonical_spec": {
            "formula_text": "rank(close)",
            "required_inputs": ["close", "oracle"],
            "operators": ["rank"],
        }
    }
    failures = validate_main_agent_mechanism_memo(
        extra_declared_input,
        extra_input_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    direct_extra_input = copy.deepcopy(memo)
    direct_extra_input["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, oracle_{i,t}] "
        "positive for high-factor deciles"
    )
    failures = validate_main_agent_mechanism_memo(
        direct_extra_input,
        extra_input_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for unbound_projection_state in ("formula_state", "close"):
        unbound_projection = copy.deepcopy(memo)
        unbound_projection["math_hypothesis"]["market_outcome_projection"] = (
            "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
            f"{unbound_projection_state}_{{i,t}}] positive for high-factor deciles"
        )
        failures = validate_main_agent_mechanism_memo(
            unbound_projection,
            spec,
        )
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    unbound_prose_projection = copy.deepcopy(memo)
    unbound_prose_projection["math_hypothesis"]["market_outcome_projection"] = (
        "positive forward return at t+1 under continuation"
    )
    failures = validate_main_agent_mechanism_memo(
        unbound_prose_projection,
        spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    legacy_state_injection = copy.deepcopy(memo)
    legacy_state_injection["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] += "; formula_state_{i,t}=future_return_{i,t+1}"
    legacy_state_injection["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
        "measured_object_{i,t}, formula_state_{i,t}] positive for "
        "high-factor deciles"
    )
    failures = validate_main_agent_mechanism_memo(
        legacy_state_injection,
        spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    extra_declared_operator = copy.deepcopy(extra_declared_input)
    extra_declared_operator["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "Q_{i,t}=oracle(close)"
    extra_operator_spec = {
        "canonical_spec": {
            "formula_text": "rank(close)",
            "required_inputs": ["close"],
            "operators": ["rank", "oracle"],
        }
    }
    failures = validate_main_agent_mechanism_memo(
        extra_declared_operator,
        extra_operator_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    for surrogate_mapping in (
        "rank(close)\ud800 maps the crowding object at t",
        "rank(close) maps the crowding object \ud800 at t",
    ):
        invalid_unicode = copy.deepcopy(memo)
        invalid_unicode["math_hypothesis"][
            "observation_mapping"
        ] = surrogate_mapping
        invalid_unicode["mathematical_object_mapping"][
            "observation_mapping"
        ] = surrogate_mapping
        failures = validate_main_agent_mechanism_memo(invalid_unicode, spec)
        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    current_indexed_alias = copy.deepcopy(memo)
    current_indexed_alias["formula_component_map"][0][
        "formula_subexpression"
    ] = "rank(q)"
    current_indexed_alias["math_hypothesis"]["mathematical_object"] = (
        "Current observable q object Q_t"
    )
    current_indexed_alias["mathematical_object_mapping"][
        "mathematical_object"
    ] = "Current observable q object Q_t"
    current_indexed_alias["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "Q_{i,t}=q"
    current_q_mapping = "rank(q_{i,t}) maps the current q object"
    current_indexed_alias["math_hypothesis"][
        "observation_mapping"
    ] = current_q_mapping
    current_indexed_alias["mathematical_object_mapping"][
        "observation_mapping"
    ] = current_q_mapping
    current_q_spec = {
        "canonical_spec": {
            "formula_text": "rank(q)",
            "required_inputs": ["q"],
            "operators": ["rank"],
        }
    }
    failures = validate_main_agent_mechanism_memo(
        current_indexed_alias,
        current_q_spec,
    )
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
        not in failures
    )

    plain_indexed_addition = copy.deepcopy(current_indexed_alias)
    plain_indexed_addition["formula_component_map"][0][
        "formula_subexpression"
    ] = "close + volume"
    plain_indexed_addition["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "Q_{i,t}=close+volume"
    plain_addition_mapping = "close_t + volume_t maps the current q object"
    plain_indexed_addition["math_hypothesis"][
        "observation_mapping"
    ] = plain_addition_mapping
    plain_indexed_addition["mathematical_object_mapping"][
        "observation_mapping"
    ] = plain_addition_mapping
    failures = validate_main_agent_mechanism_memo(
        plain_indexed_addition,
        {
            "canonical_spec": {
                "formula_text": "close + volume",
                "required_inputs": ["close", "volume"],
                "operators": ["plus"],
            }
        },
    )
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
        not in failures
    )

    for future_field in (
        "close_t1",
        "close_t01",
        "close_later",
        "futur\u0435_close",
    ):
        unsafe_field_memo = copy.deepcopy(current_indexed_alias)
        unsafe_formula = f"rank({future_field})"
        unsafe_field_memo["formula_component_map"][0][
            "formula_subexpression"
        ] = unsafe_formula
        unsafe_field_memo["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = f"Q_{{i,t}}={future_field}"
        unsafe_mapping = f"{unsafe_formula} maps the current q object"
        unsafe_field_memo["math_hypothesis"][
            "observation_mapping"
        ] = unsafe_mapping
        unsafe_field_memo["mathematical_object_mapping"][
            "observation_mapping"
        ] = unsafe_mapping
        failures = validate_main_agent_mechanism_memo(
            unsafe_field_memo,
            {
                "canonical_spec": {
                    "formula_text": unsafe_formula,
                    "required_inputs": [future_field],
                    "operators": ["rank"],
                }
            },
        )
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            in failures
        )

    for alias_formula, canonical_operator, required_inputs in (
        ("ts_sum(close, 5)", "sum", ["close"]),
        (
            "rolling_corr(close, volume, 5)",
            "correlation",
            ["close", "volume"],
        ),
        ("lag(close, 1)", "delay", ["close"]),
        ("signed_power(close, 2)", "signedpower", ["close"]),
        (
            "regression(close, volume, 0)",
            "cs_regression",
            ["close", "volume"],
        ),
        (
            "regression(close, volume, out_type=0)",
            "cs_regression",
            ["close", "volume"],
        ),
    ):
        state_alias = copy.deepcopy(current_indexed_alias)
        state_alias["formula_component_map"][0][
            "formula_subexpression"
        ] = alias_formula
        state_alias["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = f"Q_{{i,t}}={alias_formula}"
        alias_mapping = f"{alias_formula} maps the current q object"
        state_alias["math_hypothesis"]["observation_mapping"] = alias_mapping
        state_alias["mathematical_object_mapping"][
            "observation_mapping"
        ] = alias_mapping
        alias_state_spec = {
            "canonical_spec": {
                "formula_text": alias_formula,
                "required_inputs": required_inputs,
                "operators": [canonical_operator],
            }
        }
        failures = validate_main_agent_mechanism_memo(
            state_alias,
            alias_state_spec,
        )
        assert (
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
            not in failures
        )

    negative_ref_state = copy.deepcopy(current_indexed_alias)
    negative_ref_state["formula_component_map"][0][
        "formula_subexpression"
    ] = "ref(close, 1)"
    negative_ref_state["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = "Q_{i,t}=ref(close,-1)"
    negative_ref_mapping = "ref(close, 1) maps the current q object"
    negative_ref_state["math_hypothesis"][
        "observation_mapping"
    ] = negative_ref_mapping
    negative_ref_state["mathematical_object_mapping"][
        "observation_mapping"
    ] = negative_ref_mapping
    failures = validate_main_agent_mechanism_memo(
        negative_ref_state,
        {
            "canonical_spec": {
                "formula_text": "ref(close, 1)",
                "required_inputs": ["close"],
                "operators": ["delay"],
            }
        },
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    unsupported_regression_mode = copy.deepcopy(current_indexed_alias)
    unsupported_formula = "regression(close, volume, out_type=3)"
    unsupported_regression_mode["formula_component_map"][0][
        "formula_subexpression"
    ] = unsupported_formula
    unsupported_regression_mode["math_hypothesis"][
        "mechanism_equation_or_functional"
    ] = f"Q_{{i,t}}={unsupported_formula}"
    unsupported_mapping = f"{unsupported_formula} maps the current q object"
    unsupported_regression_mode["math_hypothesis"][
        "observation_mapping"
    ] = unsupported_mapping
    unsupported_regression_mode["mathematical_object_mapping"][
        "observation_mapping"
    ] = unsupported_mapping
    failures = validate_main_agent_mechanism_memo(
        unsupported_regression_mode,
        {
            "canonical_spec": {
                "formula_text": unsupported_formula,
                "required_inputs": ["close", "volume"],
                "operators": ["cs_regression"],
            }
        },
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    fake_valuation = copy.deepcopy(memo)
    fake_valuation["math_hypothesis"][
        "selected_model_family"
    ] = "discounted cash-flow valuation"
    fake_valuation["math_hypothesis"][
        "target_functional"
    ] = "valuation_gap_t=intrinsic_value_t/market_price_t-1"
    fake_valuation["math_hypothesis"][
        "market_outcome_projection"
    ] = (
        "Forward return from t+1 to t+2 is increasing in valuation_gap_t "
        "under convergence."
    )
    fake_valuation["math_model_selection"] = {
        "model_family": "discounted cash-flow valuation",
        "mechanism_equation_or_functional": "V_t=forecast_fcf_t/wacc_t",
    }
    failures = validate_main_agent_mechanism_memo(fake_valuation, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    fake_program_spec = copy.deepcopy(spec)
    fake_program_spec["mechanism_conditioned_measurement_program"] = {
        "model_selection": {
            "candidate_models": [
                {
                    "selected": True,
                    "model_family": "discounted cash-flow valuation",
                }
            ]
        }
    }
    failures = validate_main_agent_mechanism_memo(
        fake_valuation,
        fake_program_spec,
    )
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MEASUREMENT_PROGRAM_INVALID"
        in failures
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    valid_program_spec = copy.deepcopy(fake_program_spec)
    valid_program_spec["canonical_spec"][
        "mechanism_conditioned_measurement_program"
    ] = valid_program_spec["mechanism_conditioned_measurement_program"]
    valid_program_spec["canonical_spec"][
        "mechanism_conditioned_measurement_program"
    ] = "bad"
    failures = validate_main_agent_mechanism_memo(
        fake_valuation,
        valid_program_spec,
    )
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MEASUREMENT_PROGRAM_INVALID"
        in failures
    )

    invalid_unicode_object = copy.deepcopy(memo)
    invalid_unicode_object["math_hypothesis"][
        "mathematical_object"
    ] += "\ud800"
    invalid_unicode_object["mathematical_object_mapping"][
        "mathematical_object"
    ] += "\ud800"
    failures = validate_main_agent_mechanism_memo(invalid_unicode_object, spec)
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    duplicate_subtree = copy.deepcopy(memo)
    duplicate_subtree["formula_component_map"] = [
        {
            **copy.deepcopy(memo["formula_component_map"][0]),
            "component_id": "formula_root",
            "formula_subexpression": "rank(close) + rank(close)",
        },
        *[
        {
            **copy.deepcopy(memo["formula_component_map"][0]),
            "component_id": component_id,
            "formula_subexpression": "rank(close)",
        }
        for component_id in ("left_rank", "right_rank")
        ],
    ]
    duplicate_subtree["mathematical_object_mapping"]["component_links"] = [
        "formula_root",
        "left_rank",
        "right_rank",
    ]
    duplicate_spec = {
        "canonical_spec": {
            "formula_text": "rank(close) + rank(close)",
            "required_inputs": ["close"],
            "operators": ["plus", "rank"],
        }
    }
    failures = validate_main_agent_mechanism_memo(
        duplicate_subtree,
        duplicate_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    repeated_mapping = (
        "rank(close) + rank(close) maps the crowding object at t; "
        "rank(close) maps the crowding object at t; "
        "rank(close) maps the crowding object at t"
    )
    duplicate_subtree["math_hypothesis"]["observation_mapping"] = repeated_mapping
    duplicate_subtree["mathematical_object_mapping"][
        "observation_mapping"
    ] = repeated_mapping
    failures = validate_main_agent_mechanism_memo(
        duplicate_subtree,
        duplicate_spec,
    )
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID"
        not in failures
    )

    lossy_constant = copy.deepcopy(memo)
    lossy_constant["formula_component_map"][0]["formula_subexpression"] = (
        "close + 9007199254740992"
    )
    wrong_constant_mapping = (
        "close + 9007199254740993 maps the crowding object at t"
    )
    lossy_constant["math_hypothesis"][
        "observation_mapping"
    ] = wrong_constant_mapping
    lossy_constant["mathematical_object_mapping"][
        "observation_mapping"
    ] = wrong_constant_mapping
    large_constant_spec = {
        "canonical_spec": {
            "formula_text": "close + 9007199254740992",
            "required_inputs": ["close"],
            "operators": ["plus"],
        }
    }
    failures = validate_main_agent_mechanism_memo(
        lossy_constant,
        large_constant_spec,
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures

    invalid_cases = []
    future_projection = copy.deepcopy(memo)
    future_projection["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
        "measured_object_{i,t+1}] predicts positive forward return from t+1 to t+2"
    )
    invalid_cases.append(future_projection)

    for unsafe_suffix in (
        "; E[close_{i,t+2}/close_{i,t+1}-1 | F_t, oracle_{i,t+1}]",
        " conditioned on oracle_{i,t+1}",
        " + oracle",
        " = oracle",
        " oracle (close)",
        " close.shift (-1)",
        " using futureclose",
        " positive when open t+1",
        " positive with open(t+1)",
        " expected payoff with price t+1",
        "; entry t+2 close, exit t+1 close",
        "; entry t+1 open, exit t+2 vwap",
    ):
        trailing_projection = copy.deepcopy(memo)
        trailing_projection["math_hypothesis"]["market_outcome_projection"] += (
            unsafe_suffix
        )
        invalid_cases.append(trailing_projection)

    for timing_clause in (
        "entry t+10 close, exit t+20 close",
        "entry t+2 close, exit t+3 close",
    ):
        named_timing_mismatch = copy.deepcopy(memo)
        named_timing_mismatch["math_hypothesis"]["market_outcome_projection"] = (
            "E[r_{i,t+1->t+2} | F_t, measured_object_{i,t}] positive for "
            f"high-factor deciles; {timing_clause}"
        )
        invalid_cases.append(named_timing_mismatch)

    symbolic_named_mismatch = copy.deepcopy(memo)
    symbolic_named_mismatch["math_hypothesis"]["market_outcome_projection"] = (
        "E[r_{i,t+1->t+h} | F_t, measured_object_{i,t}] positive for "
        "high-factor deciles; entry t+10 close, exit t+20 close"
    )
    invalid_cases.append(symbolic_named_mismatch)

    single_named_timing = copy.deepcopy(memo)
    single_named_timing["math_hypothesis"]["market_outcome_projection"] = (
        "E[r_{i,t+2} | F_t, measured_object_{i,t}] positive for "
        "high-factor deciles; entry t+10 open, exit t+20 vwap"
    )
    invalid_cases.append(single_named_timing)

    equal_named_range = copy.deepcopy(memo)
    equal_named_range["math_hypothesis"]["market_outcome_projection"] = (
        "E[r_{i,t+2->t+2} | F_t, measured_object_{i,t}] positive for "
        "high-factor deciles; entry t+2 close, exit t+2 close"
    )
    invalid_cases.append(equal_named_range)

    named_range_without_execution_timing = copy.deepcopy(memo)
    named_range_without_execution_timing["math_hypothesis"][
        "market_outcome_projection"
    ] = (
        "E[r_{i,t+1->t+2} | F_t, measured_object_{i,t}] positive for "
        "high-factor deciles"
    )
    invalid_cases.append(named_range_without_execution_timing)

    missing_direction = copy.deepcopy(memo)
    missing_direction["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, measured_object_{i,t}]"
    )
    invalid_cases.append(missing_direction)

    unbound_signs = copy.deepcopy(memo)
    unbound_signs["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, measured_object_{i,t}] "
        "positive and negative"
    )
    invalid_cases.append(unbound_signs)

    for sign_text in (
        "positive and negative for high for low",
        "positive for high and negative for high for low",
        "positive for high and negative for low (positive for low)",
        "positive for high and low and negative for low",
        "higher and lower",
        "increasing and decreasing",
        "continuation and reversal",
    ):
        malformed_signs = copy.deepcopy(memo)
        malformed_signs["math_hypothesis"]["market_outcome_projection"] = (
            "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, "
            f"measured_object_{{i,t}}] {sign_text}"
        )
        invalid_cases.append(malformed_signs)

    mismatched_binding = copy.deepcopy(memo)
    mismatched_binding["mathematical_object_mapping"]["observation_mapping"] = (
        "volume maps a different object at t"
    )
    invalid_cases.append(mismatched_binding)

    future_mapping = copy.deepcopy(memo)
    future_mapping["math_hypothesis"]["observation_mapping"] = (
        "future_return and close map the crowding object"
    )
    future_mapping["mathematical_object_mapping"]["observation_mapping"] = (
        "future_return and close map the crowding object"
    )
    invalid_cases.append(future_mapping)

    for object_text in (
        "future return",
        "expected future excess return",
        "next-period cumulative payoff",
        "forward one-day close level",
        "return over next horizon",
        "futureclose state",
        "nextclose object",
        "tplus1 return object",
        "t+1 return object",
        "t plus 1 return object",
        "t^{+1} return object",
        "t+h return object",
        "R_{i,t+1}",
        "close.shift(-1)",
        "shift(close,-1)",
        "R(i,t+1)",
        "t+10000 return object",
        "t+01 return object",
        "shift(close,-01)",
        "P_tplus1",
        "P_t+1",
        "return_t+1",
        "close.shift(-1,axis=0)",
        "Q_{i,t+1}",
        "Current object at t plus 1",
        "oracle_{i,t}",
        "Q_{i,t}[oracle]",
        "Current observable crowding object at t plus one",
        "Current observable crowding object one period ahead",
        "Current observable crowding object one day later",
        "Current observable crowding object subsequent period",
        "Q_{i,t} and Q_{i,u}",
        "Q_{i,t} and Q_{i,t plus one}",
        "Current observable crowding object at t+one",
        "Current observable crowding object at t + one",
        "Current observable crowding object at t plus thirteen",
        "Current observable crowding object at t plus thirty",
        "Current observable crowding object at tplusone",
        "Current observable close_tplusone object",
        "Current observable close_t_1 object",
        "Current observable crowding object one week ahead",
        "Current observable crowding object upcoming period",
        "Current observable crowding object forthcoming state",
        "oracle_ {i,t}",
        "Q_{i,{t}}",
        "Q_{i,t",
        "Q_{i,t-1}",
        "Q_{i,t-k}",
        "Q_{i,t-h}",
        "Q_{i,t-n}",
    ):
        future_object = copy.deepcopy(memo)
        future_object["math_hypothesis"]["mathematical_object"] = object_text
        future_object["mathematical_object_mapping"][
            "mathematical_object"
        ] = object_text
        invalid_cases.append(future_object)

    for future_text in (
        "next close maps the crowding object",
        "tomorrow close maps the crowding object",
        "forward close maps the crowding object",
        "futureclose and close map the crowding object",
        "unknown_state and close map the crowding object",
        "shift(close,-1) maps the crowding object",
        "close at t plus 1 maps the crowding object",
        "close_{i,t+01} maps the crowding object",
        "close_{i,t^{+1}} maps the crowding object",
        "oracle and close maps the crowding object",
        "close maps the object using futureclose as an additional input",
        "close maps the object; oracle supplies an additional input",
        "close maps oracle(close)",
        "close maps oracle + 1",
        "close maps the object with oracle",
        "close + q maps the object",
        "close maps oracle[0]",
        "close maps oracle - 1",
        "close maps oracle % 2",
        "close maps oracle.close",
        "close maps oracle²",
        "close maps the object conditional on oracle",
        "close maps object incorporating oracle",
        "close maps object incorporates oracle",
        "close maps object requires oracle",
        "close maps oracle incorporated in object",
        "close maps object relies on oracle",
        "close maps object uses oracle",
        "close maps object relying on oracle",
        "close maps object maps oracle",
        "close maps oracle-1",
        "close maps object relies-on oracle",
        "close maps object estimates oracle",
        "close maps object needs one period ahead price",
        "close maps .",
        "close maps 1-2",
        "close maps oracle1",
    ):
        invalid_mapping = copy.deepcopy(memo)
        invalid_mapping["math_hypothesis"]["observation_mapping"] = future_text
        invalid_mapping["mathematical_object_mapping"][
            "observation_mapping"
        ] = future_text
        invalid_cases.append(invalid_mapping)

    missing_mapping_label = copy.deepcopy(memo)
    missing_mapping_label["math_hypothesis"]["observation_mapping"] = "close maps"
    missing_mapping_label["mathematical_object_mapping"][
        "observation_mapping"
    ] = "close maps"
    invalid_cases.append(missing_mapping_label)

    for bare_mapping in ("close", "rank(close)"):
        bare_canonical_expression = copy.deepcopy(memo)
        bare_canonical_expression["math_hypothesis"][
            "observation_mapping"
        ] = bare_mapping
        bare_canonical_expression["mathematical_object_mapping"][
            "observation_mapping"
        ] = bare_mapping
        invalid_cases.append(bare_canonical_expression)

    for invalid_equation in (
        "measured_object_{i,t}=close.shift(-1)",
        "measured_object_t=close.shift(-1)",
        "measured_object_{i,t}:=close",
        "measured_object(close)",
        "measured_object_{future,t}=close",
        "measured_object_{i,t}=close; measured_object_{i,t}=close.shift(-1)",
    ):
        invalid_assignment = copy.deepcopy(memo)
        invalid_assignment["math_hypothesis"][
            "mechanism_equation_or_functional"
        ] = invalid_equation
        invalid_cases.append(invalid_assignment)

    for object_text, mapping_text in (
        ("Q_{tplus1,t}", "close maps observable; q standardizes object"),
        ("foo_{i,t}", "close maps observable; o standardizes object"),
    ):
        invalid_alias = copy.deepcopy(memo)
        invalid_alias["math_hypothesis"]["mathematical_object"] = object_text
        invalid_alias["mathematical_object_mapping"][
            "mathematical_object"
        ] = object_text
        invalid_alias["math_hypothesis"]["observation_mapping"] = mapping_text
        invalid_alias["mathematical_object_mapping"][
            "observation_mapping"
        ] = mapping_text
        invalid_cases.append(invalid_alias)

    future_identity = copy.deepcopy(memo)
    future_identity["math_hypothesis"]["mathematical_object"] = "Q_{i,t}"
    future_identity["mathematical_object_mapping"][
        "mathematical_object"
    ] = "Q_{i,t}"
    future_identity["math_hypothesis"]["observation_mapping"] = (
        "close maps observable; q_{future,t} maps object"
    )
    future_identity["mathematical_object_mapping"]["observation_mapping"] = (
        "close maps observable; q_{future,t} maps object"
    )
    invalid_cases.append(future_identity)

    for object_text, mapping_text in (
        (
            "Current observable object uses oracle",
            "close maps object uses oracle",
        ),
        ("oracle(volume) current object", "close maps object"),
        ("rank(oracle) current object", "close maps object"),
        ("mean(oracle) current object", "close maps object"),
        ("oracle[0] current object", "close maps object"),
        ("rank(tomorrow_state) current object", "close maps object"),
        ("rank/*x*/(oracle) current object", "rank(close) maps object"),
        (
            "Current observable object leverages oracle",
            "rank(close) maps current observable object",
        ),
        (
            "Current observable object draws on oracle",
            "rank(close) maps current observable object",
        ),
        (
            "Current observable object computed from oracle",
            "rank(close) maps current observable object",
        ),
        (
            "Current observable object powered by oracle",
            "rank(close) maps current observable object",
        ),
        (
            "Current observable object relies upon oracle",
            "rank(close) maps current observable object",
        ),
        (
            "Current object needs one period ahead price",
            "close maps object needs one period ahead price",
        ),
        (
            "Current observable object relies-on oracle",
            "close maps current observable object relies-on oracle",
        ),
        (
            "Current observable object estimates oracle",
            "close maps current observable object estimates oracle",
        ),
        (
            r"Current observable \operatorname{rank}(oracle) object",
            "close maps current observable object",
        ),
    ):
        washed_dependency = copy.deepcopy(memo)
        washed_dependency["math_hypothesis"]["mathematical_object"] = object_text
        washed_dependency["mathematical_object_mapping"][
            "mathematical_object"
        ] = object_text
        washed_dependency["math_hypothesis"]["observation_mapping"] = mapping_text
        washed_dependency["mathematical_object_mapping"][
            "observation_mapping"
        ] = mapping_text
        invalid_cases.append(washed_dependency)

    circular_alias = copy.deepcopy(memo)
    circular_alias["math_hypothesis"]["mathematical_object"] = (
        "Current observable Oracle_{i,t} object"
    )
    circular_alias["mathematical_object_mapping"]["mathematical_object"] = (
        "Current observable Oracle_{i,t} object"
    )
    circular_alias["math_hypothesis"]["observation_mapping"] = (
        "close estimates current observable object; "
        "oracle standardizes current object"
    )
    circular_alias["mathematical_object_mapping"]["observation_mapping"] = (
        "close estimates current observable object; "
        "oracle standardizes current object"
    )
    invalid_cases.append(circular_alias)

    for identity_expression in ("oracle + 0", "oracle * 1", "oracle - oracle"):
        circular_identity = copy.deepcopy(memo)
        circular_identity["math_hypothesis"]["mathematical_object"] = (
            "Current observable Oracle_{i,t} object"
        )
        circular_identity["mathematical_object_mapping"][
            "mathematical_object"
        ] = "Current observable Oracle_{i,t} object"
        mapping = (
            "rank(close) estimates current observable object; "
            f"{identity_expression} standardizes current object"
        )
        circular_identity["math_hypothesis"]["observation_mapping"] = mapping
        circular_identity["mathematical_object_mapping"][
            "observation_mapping"
        ] = mapping
        invalid_cases.append(circular_identity)

    missing_link_target = copy.deepcopy(memo)
    missing_link_target["formula_component_map"][0]["component_id"] = "other"
    invalid_cases.append(missing_link_target)

    duplicate_links = copy.deepcopy(memo)
    duplicate_links["mathematical_object_mapping"]["component_links"] = [
        "formula_root",
        "formula_root",
    ]
    invalid_cases.append(duplicate_links)

    unknown_extra_link = copy.deepcopy(memo)
    unknown_extra_link["mathematical_object_mapping"]["component_links"] = [
        "formula_root",
        "other",
    ]
    invalid_cases.append(unknown_extra_link)

    mismatched_root_formula = copy.deepcopy(memo)
    mismatched_root_formula["formula_component_map"][0][
        "formula_subexpression"
    ] = "close"
    invalid_cases.append(mismatched_root_formula)

    partial_nonroot_component = copy.deepcopy(memo)
    partial_nonroot_component["formula_component_map"][0]["component_id"] = (
        "partial"
    )
    partial_nonroot_component["formula_component_map"][0][
        "formula_subexpression"
    ] = "ank(cl"
    partial_nonroot_component["mathematical_object_mapping"][
        "component_links"
    ] = ["partial"]
    invalid_cases.append(partial_nonroot_component)

    oversized_offset = copy.deepcopy(memo)
    oversized_offset["math_hypothesis"]["market_outcome_projection"] = (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, measured_object_{i,t}] "
        "positive for high-factor deciles; entry t+"
        + "9" * 5000
        + " close, exit t+2 close"
    )
    invalid_cases.append(oversized_offset)

    assert _normalize_current_observation_indices(
        "q_{future,t} maps object",
        {"wacc"},
    ) is None

    for case_index, invalid in enumerate(invalid_cases):
        failures = validate_main_agent_mechanism_memo(invalid, spec)
        if "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" not in failures:
            raise AssertionError({
                "case_index": case_index,
                "projection": invalid["math_hypothesis"]["market_outcome_projection"],
                "mapping": invalid["math_hypothesis"]["observation_mapping"],
                "object": invalid["math_hypothesis"]["mathematical_object"],
                "equation": invalid["math_hypothesis"][
                    "mechanism_equation_or_functional"
                ],
                "links": invalid["mathematical_object_mapping"].get(
                    "component_links"
                ),
                "components": invalid.get("formula_component_map"),
            })


def test_memo_authored_operator_cannot_expand_trusted_state_functions():
    signature = {
        "rank_ic": "expected rank IC direction compared with observed evidence",
        "long_side": "expected long-side return compared with observed evidence",
        "cost_adjusted": "expected net return compared with observed evidence",
        "monotonicity": "expected ordering compared with observed evidence",
        "turnover": "expected turnover compared with observed evidence",
    }
    payoff = "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, C_{i,t}]"
    failures = validate_main_agent_mechanism_memo(
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "formula_understanding": {
                "formula_features": {
                    "fields": ["close"],
                    "operators": ["rolling_oracle"],
                }
            },
            "math_hypothesis": {
                "mechanism_equation_or_functional": (
                    "C_{i,t}=rolling_oracle(close,5)"
                ),
                "target_functional": payoff,
                "market_outcome_projection": payoff,
                "expected_metric_signature": signature,
            },
            "expected_metric_signature": dict(signature),
        },
        {
            "canonical_spec": {
                "formula_text": "rank(close)",
                "required_inputs": ["close"],
                "operators": ["rank"],
            }
        },
    )

    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures


def test_symbolic_negative_lag_cannot_define_trusted_current_state():
    signature = {
        "rank_ic": "expected rank IC direction compared with observed evidence",
        "long_side": "expected long-side return compared with observed evidence",
        "cost_adjusted": "expected net return compared with observed evidence",
        "monotonicity": "expected ordering compared with observed evidence",
        "turnover": "expected turnover compared with observed evidence",
    }
    payoff = "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, C_{i,t}]"
    for equation in (
        "C_{i,t}=ts_delay(close,-k)",
        "C_{i,t}=ts_delay(close,5,-1)",
        "C_{i,t}=ts_delay(close,5,periods=-1)",
        "C_{i,t}=ts_delay(close,5,k)",
        "C_{i,t}=ts_delay(close,periods=-1==5)",
        "C_{i,t}=close(",
        "C_{i,t}=close+\u672a\u6765\u6536\u76ca",
        "C_{i,t}=delta(close,-1)",
        "C_{i,t}=diff(close,-1)",
        "C_{i,t}=mean(close,window=5,center=1)",
        "C_{i,t}=rank(close,future_return=1)",
        "C_{i,t}=tsdelay(close,-1)",
        "C_{i,t}=close+\ud800",
        "C_{i,t}=close+returns",
    ):
        failures = validate_main_agent_mechanism_memo(
            {
                "contract_version": "factorforge_main_agent_mechanism_memo_v1",
                "math_hypothesis": {
                    "mechanism_equation_or_functional": equation,
                    "target_functional": payoff,
                    "market_outcome_projection": payoff,
                    "expected_metric_signature": signature,
                },
                "expected_metric_signature": dict(signature),
            },
            {
                "canonical_spec": {
                    "formula_text": "ts_delay(close,1)",
                    "required_inputs": ["close"],
                    "operators": [
                        "delta",
                        "diff",
                        "mean",
                        "rank",
                        "ts_delay",
                        "tsdelay",
                    ],
                }
            },
        )

        assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID" in failures


def test_public_metric_projection_accepts_formal_scalars_and_drops_backend_objects():
    source_metrics = {
        "metric_period": "2016-01-01/2025-07-11",
        "rank_ic_mean": 0.0069,
        "rank_ic_ir": 0.128,
        "pearson_ic_ir": 0.091,
        "long_side_annual_volatility": 0.26,
        "long_side_sharpe": -0.17,
        "long_side_recovery_days": 3474,
        "trading_cogs_annual": 0.515,
        "cost_adjusted_long_side_sharpe": -2.36,
        "long_short_spread_mean": 0.00059,
        "monotonicity_diagnostic": "top_group_not_above_bottom_group",
        "coverage_ratio": None,
        "coverage_row_count": 8_034_990,
        "group_member_count_median": 500.0,
        "backend_metrics": [{"backend": "self_quant"}],
        "backend_metric_conflicts": {"rank_ic_mean": {"status": "conflict"}},
        "rank_ic_std": {"status": "backend_conflict"},
        "pearson_ic_std": float("nan"),
        "pearson_ic_mean": float("inf"),
        "coverage_unapproved": 1.0,
        "group_unapproved": 2.0,
        "unapproved_metric": 1.0,
    }
    observed = project_public_observed_metrics(source_metrics)
    conflict_keys = project_public_observed_metric_conflict_keys(source_metrics)

    assert observed["metric_period"] == "2016-01-01/2025-07-11"
    assert observed["monotonicity_diagnostic"] == "top_group_not_above_bottom_group"
    assert observed["coverage_ratio"] is None
    assert observed["rank_ic_ir"] == 0.128
    assert "backend_metrics" not in observed
    assert "backend_metric_conflicts" not in observed
    assert "rank_ic_std" not in observed
    assert "pearson_ic_std" not in observed
    assert "pearson_ic_mean" not in observed
    assert "coverage_unapproved" not in observed
    assert "group_unapproved" not in observed
    assert "unapproved_metric" not in observed
    assert conflict_keys == ["rank_ic_mean", "rank_ic_std"]
    assert memo_public_schema_failures(
        {
            "evidence_comparison": {
                "observed_metrics": observed,
                "observed_metric_conflict_keys": conflict_keys,
            }
        }
    ) == []
    assert memo_public_schema_failures(
        {
            "evidence_comparison": {
                "observed_metrics": {"rank_ic_mean": float("nan")}
            }
        }
    ) == [
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
        "evidence_comparison.observed_metrics.rank_ic_mean"
    ]


def test_named_return_target_requires_the_same_structured_contract():
    assert _has_explicit_named_return_payoff(
        "E[r_{i,t+1:t+h} | F_t, S_{i,t}]"
    )
    assert _has_explicit_named_return_payoff(
        "E[return_{i,t+1} | F_t, drift_state_t]"
    )
    assert _has_explicit_named_return_payoff(
        "E[r_{i,t+1->t+2} | F_{i,t}]"
    )
    assert _has_explicit_named_return_payoff(
        r"E[r_{i,t+1\to t+h} | F_{i,t}]"
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
    assert not _has_explicit_named_return_payoff(
        "E[r_{i,t+2->t+1} | F_{i,t}]"
    )
    assert not _has_explicit_named_return_payoff(
        "E[r_{i,t+1->t+2} | F_{i,t+1}]"
    )
    assert not _has_explicit_named_return_payoff(
        "E[r_{i,t+1->t+2} | F_{label,t}]"
    )
    for invalid_filtration in [
        "F_{tp01,t}",
        "F_{tplus01,t}",
        "F_{t,i}",
        "F_{i,j,t}",
        "F_{i,t,j}",
    ]:
        assert not _has_explicit_named_return_payoff(
            f"E[r_{{i,t+1->t+2}} | {invalid_filtration}]"
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
    assert blocker not in target_failures(
        "E[r_{i,t+1->t+2} | F_{i,t}], "
        "r=close_{i,t+2}/close_{i,t+1}-1, known at after_close_t"
    )
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
        "E[r_{i,t+1->t+2} | F_{tp01,t}]",
        "E[r_{i,t+1->t+2} | F_{tplus01,t}]",
        "E[r_{i,t+1->t+2} | F_{t,i}]",
        "E[r_{i,t+1->t+2} | F_{i,j,t}]",
        "E[r_{i,t+1->t+2} | F_{i,t,j}]",
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


def test_council_dcf_tool_does_not_require_dimensional_review() -> None:
    proposal = _minimal_council_proposal()
    proposal["selected_math_tools"] = ["discounted_cash_flow"]
    proposal.pop("dimensional_scaling_review")
    proposal["symbolic_model"] = {
        "mathematical_object": "present value of forecast free cash flows",
        "mechanism_equation_or_functional": "V_t=sum_k FCF_t+k/(1+WACC)^k",
        "target_functional": "V_t=sum_k FCF_t+k/(1+WACC)^k",
    }

    reasons = validate_revision_council_proposal(proposal)

    assert "revision_council_dimensional_scaling_review_missing" not in reasons
    assert not any("stochastic" in reason for reason in reasons)


def test_council_anomaly_requires_branch_law():
    proposal = _minimal_council_proposal()
    proposal["formula_implied_information_review"] = {
        "unexpected_implications": [
            {"implication": "negative solution", "classification": "new_factor_seed", "reasoning": "distinct state"}
        ]
    }

    reasons = validate_revision_council_proposal(proposal)

    assert "BLOCK_COUNCIL_ANOMALY_BRANCH_LAW_MISSING" in reasons
