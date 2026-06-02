from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from factor_factory.mechanism_math.formula_specific import (
    build_formula_understanding,
    select_math_model_from_economic_hypothesis,
)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z_]{3,}|[\u4e00-\u9fff]{1,}", text.lower()))


def _text_blob(*objects: Any) -> str:
    return " ".join(_stringify(obj) for obj in objects).lower()


def infer_step1_random_object(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["成交量", "换手", "volume", "turnover", "amount", "order", "flow"]):
        return "A-share liquidity/order-flow and price panel observed through tradable market data"
    if any(tok in text for tok in ["close", "open", "high", "low", "return", "收益", "价格", "价量", "影线"]):
        return "A-share daily/intraday price-return panel and cross-sectional return ordering"
    if any(tok in text for tok in ["revenue", "profit", "cash", "contract", "inventory", "liability", "营收", "利润", "现金流", "合同负债", "存货"]):
        return "firm fundamental information state observed through accounting and disclosure fields"
    if any(tok in text for tok in ["北交所", "转板", "公募", "保险", "mandate", "index", "rebalance"]):
        return "security panel affected by objective market-structure or mandate constraints"
    return "report-defined security panel; researcher must restate the precise random object before promotion"


def infer_target_statistic_hint(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["rank", "排名", "分组", "quantile", "bucket"]):
        return "cross-sectional ordering / rank statistic for future returns"
    if any(tok in text for tok in ["corr", "相关", "cov"]):
        return "rolling dependence statistic used to predict cross-sectional return ordering"
    if any(tok in text for tok in ["std", "vol", "波动", "方差"]):
        return "conditional dispersion / volatility statistic linked to future returns"
    if any(tok in text for tok in ["skew", "偏度", "tail", "尾部"]):
        return "higher-moment or tail-shape statistic linked to future returns"
    return "conditional expected return or cross-sectional ranking effect inferred from the report thesis"


def infer_return_source_hypothesis(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["value", "size", "beta", "quality", "价值", "规模", "风险补偿", "低波"]):
        return "risk_premium"
    if any(tok in text for tok in ["财报", "基本面", "合同负债", "现金流", "revenue", "profit", "cash", "information", "disclosure"]):
        return "information_advantage"
    if any(tok in text for tok in ["北交所", "转板", "公募", "保险", "约束", "制度", "mandate", "rebalance", "liquidity", "流动性"]):
        return "constraint_driven_arbitrage"
    if any(tok in text for tok in ["momentum", "reversal", "过度反应", "反转", "动量", "行为"]):
        return "mixed"
    return "mixed"


def normalize_macro_return_source(value: str) -> str:
    if value == "constraint_driven_arbitrage":
        return "market_structure_arbitrage"
    if value in {"risk_premium", "information_advantage", "market_structure_arbitrage", "mixed"}:
        return value
    return "mixed"


def infer_second_layer_mechanism(alpha_idea_master: Dict[str, Any], macro_source: str, *context: Any) -> Dict[str, Any]:
    text = _text_blob(alpha_idea_master, *context)
    if macro_source == "risk_premium":
        if any(tok in text for tok in ["earnings", "profit", "roe", "roa", "盈利", "利润", "业绩"]):
            subtype = "earnings_or_profitability_risk"
        elif any(tok in text for tok in ["growth", "revenue", "sales", "成长", "营收"]):
            subtype = "growth_risk"
        elif any(tok in text for tok in ["duration", "interest", "rate", "久期", "利率"]):
            subtype = "duration_or_discount_rate_risk"
        else:
            subtype = "priced_state_risk"
        payer = "investors who require compensation for bearing the stated state risk"
    elif macro_source == "information_advantage":
        if any(tok in text for tok in ["smart money", "fund flow", "institution", "北向", "聪明钱", "资金流"]):
            subtype = "smart_money_or_informed_flow_advantage"
        elif any(tok in text for tok in ["attention", "overreaction", "underreaction", "bias", "行为", "注意力", "过度反应", "反应不足"]):
            subtype = "behavioral_bias_or_slow_information_diffusion"
        else:
            subtype = "slow_information_diffusion"
        payer = "slower or behaviorally biased counterparties who incorporate information later or at worse prices"
    elif macro_source == "market_structure_arbitrage":
        if any(tok in text for tok in ["order", "imbalance", "volume", "turnover", "liquidity", "成交量", "换手", "流动性"]):
            subtype = "order_imbalance_or_liquidity_pressure"
        elif any(tok in text for tok in ["index", "rebalance", "mandate", "北交所", "转板", "制度", "约束"]):
            subtype = "mandate_rebalance_or_constraint_flow"
        else:
            subtype = "market_microstructure_constraint"
        payer = "constrained liquidity demanders, forced rebalancers, or crowded-flow participants"
    else:
        subtype = "mixed_or_unresolved"
        payer = "unidentified counterparties; Step2 and Council must separate risk, information, and structure channels"
    return {
        "subtype": subtype,
        "expected_counterparty_or_payer": payer,
        "why_they_may_pay": "The report thesis implies this group trades for risk transfer, delayed information processing, behavioral pressure, or market-structure constraints rather than because the factor is mechanically convenient.",
    }


def build_economic_hypothesis(alpha_idea_master: Dict[str, Any], return_source: str, *context: Any) -> Dict[str, Any]:
    formula_understanding = build_formula_understanding_from_step1(alpha_idea_master, *context)
    if formula_understanding.get("interaction_structure") == "slow_state_x_short_horizon_threshold":
        second_layer = {
            "subtype": "slow_winner_state_short_horizon_reversal_or_threshold_migration",
            "expected_counterparty_or_payer": (
                "trend extrapolators, delayed updaters, or short-horizon liquidity/dislocation traders "
                "around winner-state pullbacks"
            ),
            "why_they_may_pay": (
                "they extrapolate the slow winner state or react late to threshold crossings, creating "
                "conditional next-period payoff when the short-horizon state reverses or migrates"
            ),
        }
        return {
            "hypothesis_version": "factorforge_step1_economic_hypothesis_v1",
            "macro_return_source": "mixed",
            "legacy_initial_return_source_hypothesis": return_source,
            "second_layer": second_layer,
            "counterparty_loss_hypothesis": second_layer["expected_counterparty_or_payer"],
            "researcher_question": "Who pays me, why do they pay, and how does this slow-state x short-state formula estimate that condition?",
        }
    macro_source = normalize_macro_return_source(return_source)
    second_layer = infer_second_layer_mechanism(alpha_idea_master, macro_source, *context)
    return {
        "hypothesis_version": "factorforge_step1_economic_hypothesis_v1",
        "macro_return_source": macro_source,
        "legacy_initial_return_source_hypothesis": return_source,
        "second_layer": second_layer,
        "counterparty_loss_hypothesis": second_layer["expected_counterparty_or_payer"],
        "researcher_question": "Who is the likely counterparty paying this return, and why would that behavior or constraint persist after costs?",
    }


def build_formula_understanding_from_step1(alpha_idea_master: Dict[str, Any], *context: Any) -> Dict[str, Any]:
    final_factor = alpha_idea_master.get("final_factor") or {}
    formula = (
        alpha_idea_master.get("raw_formula")
        or "; ".join(str(item) for item in _as_list(final_factor.get("assembly_steps")))
        or "; ".join(str(item) for item in _as_list(alpha_idea_master.get("assembly_path")))
    )
    fields: list[str] = []
    operators: list[str] = []
    for source in [alpha_idea_master, final_factor, *context]:
        if isinstance(source, dict):
            fields.extend(str(item) for item in _as_list(source.get("candidate_variables") or source.get("key_variables") or source.get("variables")) if str(item).strip())
            operators.extend(str(item) for item in _as_list(source.get("operators")) if str(item).strip())
    return build_formula_understanding({
        "canonical_spec": {
            "formula_text": str(formula or ""),
            "required_inputs": fields,
            "operators": operators,
        }
    })


def build_math_hypothesis_candidates(
    alpha_idea_master: Dict[str, Any],
    economic_hypothesis: Dict[str, Any],
    random_object: str,
    target_hint: str,
    *context: Any,
) -> List[Dict[str, Any]]:
    formula_understanding = build_formula_understanding_from_step1(alpha_idea_master, *context)
    if formula_understanding.get("interaction_structure") == "slow_state_x_short_horizon_threshold":
        return [
            {
                "hypothesis_id": "math_slow_winner_short_reversal_process",
                "linked_economic_hypothesis": "mixed:slow_winner_state_short_horizon_reversal_or_threshold_migration",
                "model_family": "stochastic_process",
                "math_tools": ["probability_theory", "stochastic_process_calculus", "time_series_and_filtering", "statistics"],
                "state_or_object": "slow winner state interacting with short-horizon reversal/dislocation threshold state",
                "process_or_distribution_hypothesis": (
                    "return process with slow trend/winner state M_i,t and short-horizon reversal or temporary "
                    "dislocation state I_i,t; sign transform induces threshold migration"
                ),
                "model_mutation": "add threshold boundary induced by sign transform to a slow-trend stochastic process",
                "observable_estimator": "sum(returns,250), close-delay(close,7), delta(close,7), sign threshold, cross-sectional rank",
                "target_functional": "E[r_i,t+1 | slow_state_i,t, short_state_i,t, threshold_i,t]",
                "why_suitable": (
                    "Alpha019-like structure is not price-volume; it estimates a conditional return state from "
                    "long-window winner rank and short-horizon threshold movement"
                ),
                "falsification_tests": [
                    "Reject if long-side payoff does not align with slow-state x short-state conditional sign after costs.",
                    "Reject if ablation of long-window state or short-horizon threshold does not weaken the signal.",
                ],
            }
        ]
    text = _text_blob(alpha_idea_master, *context)
    macro_source = economic_hypothesis.get("macro_return_source")
    subtype = (economic_hypothesis.get("second_layer") or {}).get("subtype")
    candidates: List[Dict[str, Any]] = []

    def add(hid: str, family: str, tools: List[str], state: str, process: str, estimator: str, target: str, why: str) -> None:
        candidates.append(
            {
                "hypothesis_id": hid,
                "linked_economic_hypothesis": f"{macro_source}:{subtype}",
                "model_family": family,
                "math_tools": tools,
                "state_or_object": state,
                "process_or_distribution_hypothesis": process,
                "observable_estimator": estimator,
                "target_functional": target,
                "why_suitable": why,
                "falsification_tests": [
                    "Reject if Step4/5 evidence contradicts the declared relationship shape.",
                    "Reject if apparent performance is driven by forbidden portfolio repair, short-leg adoption, or data mutation.",
                ],
            }
        )

    if macro_source == "risk_premium":
        add(
            "math_risk_premium_valuation_state",
            "valuation_identity",
            ["accounting_or_valuation_identity", "statistics", "real_analysis"],
            "cash-flow, earnings, growth, or discount-rate state",
            "Asset value is a discounted functional of future cash flows or risk compensation; returns arise when the market reprices that state.",
            "lag-safe accounting, valuation, growth, or profitability estimator",
            "E[r_{i,t+1:t+h} | F_t, priced_state_{i,t}]",
            "Risk-premium hypotheses should explain which priced state is borne and why compensation is expected.",
        )
    if macro_source == "information_advantage":
        add(
            "math_information_advantage_belief_update",
            "stochastic_process",
            ["probability_theory", "statistics", "information_theory"],
            "latent information or belief-updating state",
            "Prices partially reveal information over time; returns depend on delayed belief updating or heterogeneous signal extraction.",
            "observable proxy for informed flow, disclosure surprise, slow diffusion, or behavioral bias",
            "E[r_{i,t+1:t+h} | F_t, information_state_{i,t}]",
            "Information-advantage hypotheses should state why the signal is known earlier or interpreted better than by marginal counterparties.",
        )
        if any(tok in text for tok in ["cointegration", "pair", "spread", "均衡", "协整"]):
            add(
                "math_information_advantage_cointegration",
                "stochastic_process",
                ["probability_theory", "statistics", "time_series_and_filtering"],
                "temporary deviation from a stable relation",
                "A spread or relation mean-reverts when counterparties underreact to a known equilibrium.",
                "cointegration residual, spread z-score, or deviation estimator",
                "E[Δspread_{t+1:t+h} | F_t, deviation_t]",
                "Cointegration is suitable only when the report thesis implies a stable relation and delayed correction.",
            )
    if macro_source == "market_structure_arbitrage":
        add(
            "math_market_structure_flow_pressure",
            "price_volume_microstructure",
            ["probability_theory", "statistics", "microstructure_model"],
            "order-imbalance, liquidity-demand, or transient-impact state",
            "Observed price and trading activity combine permanent information and transient pressure components.",
            "price-volume dependence, flow, turnover, or liquidity-pressure estimator",
            "E[r_{i,t+1:t+h} | F_t, flow_pressure_{i,t}]",
            "Market-structure hypotheses should identify constrained or crowded participants whose trading pressure can be harvested.",
        )
    if any(tok in text for tok in ["wavelet", "fourier", "frequency", "周期", "频率", "小波"]):
        add(
            "math_frequency_domain_signal",
            "functional_filter",
            ["functional_analysis", "time_series_and_filtering", "statistics"],
            "multi-scale latent signal state",
            "Observed prices or fundamentals contain components at different horizons; returns depend on a selected scale or frequency band.",
            "wavelet, Fourier, kernel, or multi-scale filtered estimator",
            "E[r_{i,t+1:t+h} | F_t, scale_state_{i,t}]",
            "Frequency-domain tools are suitable only when the report thesis identifies horizon separation or scale-specific behavior.",
        )
    if not candidates:
        add(
            "math_mixed_unresolved_research_prior",
            "other",
            ["probability_theory", "statistics"],
            random_object,
            "The report implies a return source, but the precise process/distribution hypothesis remains unresolved.",
            "report-defined observable estimator",
            f"E[target | F_t, factor_state_t], target_hint={target_hint}",
            "This keeps the hypothesis explicit without forcing a fixed mathematical tool before Step2/Council review.",
        )
    return candidates[:4]


def _meaningful_list(values: Any) -> List[str]:
    out: List[str] = []
    for value in _as_list(values):
        text = str(value or "").strip()
        if text and text.lower() not in {"under_specified", "unknown", "n/a", "none", "todo", "tbd"} and text not in out:
            out.append(text)
    return out


def _explicit_market_process_thesis(alpha_idea_master: Dict[str, Any]) -> Dict[str, Any]:
    thesis = alpha_idea_master.get("market_process_thesis")
    if isinstance(thesis, dict):
        return {k: v for k, v in thesis.items() if v not in (None, "", [])}
    discipline = alpha_idea_master.get("research_discipline") or {}
    thesis = discipline.get("market_process_thesis") if isinstance(discipline, dict) else None
    if isinstance(thesis, dict):
        return {k: v for k, v in thesis.items() if v not in (None, "", [])}
    return {}


def build_market_process_thesis(economic_hypothesis: Dict[str, Any], what_must_be_true: List[str], what_would_break_it: List[str], explicit: Dict[str, Any] | None = None) -> Dict[str, Any]:
    second = economic_hypothesis.get("second_layer") if isinstance(economic_hypothesis.get("second_layer"), dict) else {}
    thesis = {
        "market_phenomenon": second.get("subtype") or "under_specified_market_process",
        "economic_hypothesis": second.get("why_they_may_pay") or "under_specified_economic_hypothesis",
        "return_source_family": economic_hypothesis.get("macro_return_source") or "mixed",
        "payer_or_counterparty": second.get("expected_counterparty_or_payer") or economic_hypothesis.get("counterparty_loss_hypothesis") or "under_specified_counterparty",
        "why_they_pay": second.get("why_they_may_pay") or "under_specified_payment_reason",
        "what_must_be_true": what_must_be_true,
        "what_would_break_it": what_would_break_it,
        "alternative_return_source_tests": [
            {
                "alternative_source": "risk_premium",
                "why_not_primary": "Step1 does not assume systematic risk compensation unless later evidence links payoff to a risk bearer.",
                "discriminating_test": "Control for beta, volatility, size, and liquidity style exposure before accepting the primary mechanism.",
                "expected_signature_if_alternative_true": "Metric support should collapse into broad risk/style exposure rather than the declared market process.",
            },
            {
                "alternative_source": "information_advantage",
                "why_not_primary": "Step1 observables do not by themselves prove private information or disclosure timing advantage.",
                "discriminating_test": "Test whether payoff concentrates around information events or survives component/state ablations.",
                "expected_signature_if_alternative_true": "Returns should align with event-timing information rather than the declared state estimator.",
            },
        ],
    }
    if explicit:
        for key in ["market_phenomenon", "economic_hypothesis", "return_source_family", "payer_or_counterparty", "why_they_pay"]:
            if explicit.get(key):
                thesis[key] = explicit[key]
        if isinstance(explicit.get("alternative_return_source_tests"), list) and explicit.get("alternative_return_source_tests"):
            thesis["alternative_return_source_tests"] = explicit["alternative_return_source_tests"]
        if _meaningful_list(explicit.get("what_must_be_true")):
            thesis["what_must_be_true"] = _meaningful_list(explicit.get("what_must_be_true"))
        if _meaningful_list(explicit.get("what_would_break_it")):
            thesis["what_would_break_it"] = _meaningful_list(explicit.get("what_would_break_it"))
    return thesis


def build_primary_mechanism_model_candidates(math_hypothesis_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(math_hypothesis_candidates):
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "candidate_id": item.get("hypothesis_id") or f"primary_model_candidate_{idx + 1}",
                "rank": idx + 1,
                "selected_model_family": item.get("model_family") or "other",
                "why_this_model_fits": item.get("why_suitable") or "under_specified",
                "why_alternatives_are_less_suitable": [
                    "Alternative model families are secondary until they better explain the payer, state variables, and formula estimator mapping."
                ],
                "state_variables": [item.get("state_or_object") or "under_specified_state"],
                "observable_proxies": [item.get("observable_estimator") or "under_specified_observable_estimator"],
                "target_functional": item.get("target_functional") or "under_specified_target_functional",
                "preferred": idx == 0,
            }
        )
    return out


def build_stochastic_price_process_projection(math_hypothesis_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    preferred = math_hypothesis_candidates[0] if math_hypothesis_candidates else {}
    estimator = preferred.get("observable_estimator") or "under_specified_observable_estimator"
    target = preferred.get("target_functional") or "E[r_{t+1} | F_t, estimated_state_t]"
    return {
        "projection_required": True,
        "price_process_form": preferred.get("process_or_distribution_hypothesis") or "under_specified_price_process_form",
        "affected_price_process_terms": ["drift", "observation_equation"],
        "conditional_distribution_claim": str(target),
        "formula_should_estimate": str(estimator),
        "expected_return_distribution_change": (
            "conditioning on the Step1 state estimator should shift next-period return rank or conditional mean in the declared direction"
        ),
    }


def infer_information_set_hint(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["future", "lead", "lookahead", "未来收益", "事后"]):
        return "possible_forward_reference_requires_human_review"
    if any(tok in text for tok in ["lag", "shift", "delay", "滞后", "前一日"]):
        return "explicit_lag_or_delay_documented"
    return "requires_researcher_confirmation_no_forward_leakage"


def load_similar_case_lessons(repo_root: Path, query_text: str, top_k: int = 3) -> List[str]:
    candidates: List[tuple[float, str]] = []
    q_tokens = _tokens(query_text)
    index_paths = [
        repo_root / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
        repo_root / "factorforge" / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
    ]
    for path in index_paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except Exception:
                continue
            text = _stringify(doc.get("text") or doc)
            overlap = len(q_tokens & _tokens(text))
            if overlap <= 0:
                continue
            label = " / ".join(str(x) for x in [doc.get("factor_id"), doc.get("decision")] if x)
            candidates.append((float(overlap), (label + ": " + text[:300]).strip(": ")))
    candidates.sort(key=lambda item: item[0], reverse=True)
    lessons = []
    seen = set()
    for _, item in candidates:
        if item and item not in seen:
            lessons.append(item)
            seen.add(item)
        if len(lessons) >= top_k:
            break
    if not lessons:
        lessons.append("No similar prior case was retrieved at Step1; treat this as a cold-start prior and write back lessons after Step6.")
    return lessons


def build_step1_research_discipline(
    alpha_idea_master: Dict[str, Any],
    repo_root: Path | None = None,
    *context: Any,
) -> Dict[str, Any]:
    repo = repo_root or Path.cwd()
    final_factor = alpha_idea_master.get("final_factor") or {}
    query_text = _text_blob(alpha_idea_master.get("report_id"), final_factor.get("name"), final_factor, alpha_idea_master.get("assembly_path"), *context)
    random_object = infer_step1_random_object(alpha_idea_master, *context)
    target_hint = infer_target_statistic_hint(alpha_idea_master, *context)
    return_source = infer_return_source_hypothesis(alpha_idea_master, *context)
    economic_hypothesis = build_economic_hypothesis(alpha_idea_master, return_source, *context)
    math_hypothesis_candidates = build_math_hypothesis_candidates(alpha_idea_master, economic_hypothesis, random_object, target_hint, *context)
    formula_understanding = build_formula_understanding_from_step1(alpha_idea_master, *context)
    economic_to_math = {
        "economic_hypothesis": economic_hypothesis,
        "selected_baseline_model": select_math_model_from_economic_hypothesis(economic_hypothesis, math_hypothesis_candidates, formula_understanding),
        "model_mutations": [item.get("model_mutation") for item in math_hypothesis_candidates if isinstance(item, dict) and item.get("model_mutation")],
        "expected_metric_signature": {
            "rank_ic": "positive after sign convention",
            "long_side": "positive after costs if the state is monetizable",
        },
        "metric_feedback_rules": [
            "Unsupported metrics must mutate sign, horizon, state interaction, or kill the thesis.",
            "Do not repair with portfolio expression, short leg, direct decile trading, or clean-data mutation.",
        ],
    }
    info_hint = infer_information_set_hint(alpha_idea_master, *context)
    similar_lessons = load_similar_case_lessons(repo, query_text)
    explicit_thesis = _explicit_market_process_thesis(alpha_idea_master)
    existing_discipline = alpha_idea_master.get("research_discipline") if isinstance(alpha_idea_master.get("research_discipline"), dict) else {}
    what_must_be_true = (
        _meaningful_list(final_factor.get("what_must_be_true"))
        or _meaningful_list(explicit_thesis.get("what_must_be_true"))
        or _meaningful_list(existing_discipline.get("what_must_be_true"))
        or _meaningful_list(final_factor.get("economic_logic"))[:1]
    )
    what_would_break_it = (
        _meaningful_list(final_factor.get("what_would_break_it"))
        or _meaningful_list(explicit_thesis.get("what_would_break_it"))
        or _meaningful_list(existing_discipline.get("what_would_break_it"))
        or _meaningful_list(final_factor.get("key_implementation_risks"))
    )
    return {
        "step1_random_object": random_object,
        "target_statistic_hint": target_hint,
        "information_set_hint": info_hint,
        "initial_return_source_hypothesis": return_source,
        "formula_understanding": formula_understanding,
        "economic_hypothesis_candidates": alpha_idea_master.get("economic_hypothesis_candidates") or [],
        "preferred_economic_hypothesis": alpha_idea_master.get("preferred_economic_hypothesis") or {},
        "alternative_return_source_tests": alpha_idea_master.get("alternative_return_source_tests") or [],
        "primary_mathematical_model": alpha_idea_master.get("primary_mathematical_model") or {},
        "formula_as_observable_estimator": alpha_idea_master.get("formula_as_observable_estimator") or {},
        "economic_hypothesis": economic_hypothesis,
        "economic_to_math_modelling": economic_to_math,
        "math_hypothesis_candidates": math_hypothesis_candidates,
        "market_process_thesis": build_market_process_thesis(economic_hypothesis, [str(x) for x in what_must_be_true if str(x).strip()], [str(x) for x in what_would_break_it if str(x).strip()], explicit_thesis),
        "primary_mechanism_model_candidates": build_primary_mechanism_model_candidates(math_hypothesis_candidates),
        "stochastic_price_process_projection": build_stochastic_price_process_projection(math_hypothesis_candidates),
        "what_must_be_true": [str(x) for x in what_must_be_true if str(x).strip()],
        "what_would_break_it": [str(x) for x in what_would_break_it if str(x).strip()],
        "what_must_be_true_provenance": alpha_idea_master.get("market_process_thesis_provenance"),
        "similar_case_lessons_imported": similar_lessons,
        "producer": "step1_research_discipline",
    }


def attach_step1_research_discipline(
    alpha_idea_master: Dict[str, Any],
    repo_root: Path | None = None,
    *context: Any,
) -> Dict[str, Any]:
    out = dict(alpha_idea_master)
    discipline = build_step1_research_discipline(out, repo_root, *context)
    out["research_discipline"] = {
        **(out.get("research_discipline") or {}),
        **discipline,
    }
    out.setdefault("step1_random_object", discipline["step1_random_object"])
    math_review = dict(out.get("math_discipline_review") or {})
    math_review.setdefault("step1_random_object", discipline["step1_random_object"])
    math_review.setdefault("target_statistic", discipline["target_statistic_hint"])
    math_review.setdefault("information_set_legality", discipline["information_set_hint"])
    out["math_discipline_review"] = math_review
    learning = dict(out.get("learning_and_innovation") or {})
    learning.setdefault("similar_case_lessons_imported", discipline["similar_case_lessons_imported"])
    out["learning_and_innovation"] = learning
    return out
