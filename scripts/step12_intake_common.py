#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJECTS = FACTORFORGE / 'objects'
VALIDATION = OBJECTS / 'validation'
REPORT_MAPS = OBJECTS / 'report_maps'
ALPHA_IDEA_MASTER = OBJECTS / 'alpha_idea_master'


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def dedupe(items: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out


def infer_formula_inputs(formula: str) -> List[str]:
    aliases = {
        'vol': 'volume',
        'returns': 'return',
        'ret': 'return',
        'adv': 'volume',
    }
    tokens = re.findall(r'\b(?:open|high|low|close|vwap|volume|vol|amount|turnover|returns?|ret|adv\d*)\b', formula.lower())
    normalized = []
    for token in tokens:
        if token.startswith('adv'):
            normalized.append('volume')
        else:
            normalized.append(aliases.get(token, token))
    return dedupe(normalized) or ['close', 'volume']


def infer_formula_operators(formula: str) -> List[str]:
    known = [
        'rank', 'correlation', 'corr', 'sum', 'mean', 'std', 'delta', 'delay',
        'ts_rank', 'argmax', 'argmin', 'decay_linear', 'signedpower', 'scale',
        'indneutralize', 'regression', 'zscore',
    ]
    text = formula.lower()
    operators = []
    for name in known:
        if name in text:
            operators.append(f'{name}()')
    return dedupe(operators) or ['formula_expression()']


def infer_hypothesis_variables(hypothesis: str) -> List[str]:
    text = hypothesis.lower()
    mapping = [
        (['合同负债', 'contract liability', 'deferred revenue'], 'contract_liabilities'),
        (['经营现金流', 'operating cash flow', 'cfo'], 'operating_cash_flow'),
        (['收入', '营收', 'revenue'], 'revenue'),
        (['订单', 'backlog'], 'orders_or_backlog'),
        (['利润', 'profit', 'earnings'], 'earnings'),
        (['毛利', 'gross margin'], 'gross_margin'),
        (['成交量', 'volume'], 'volume'),
        (['换手', 'turnover'], 'turnover'),
        (['价格', 'price', 'close'], 'close'),
    ]
    variables = []
    for needles, variable in mapping:
        if any(needle in text for needle in needles):
            variables.append(variable)
    return dedupe(variables) or ['close', 'return']


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def common_research_discipline(
    source_type: str,
    random_object: str,
    target_statistic: str,
    return_source: str,
    information_set: str,
    what_must_be_true: List[str],
    what_would_break_it: List[str],
) -> Dict[str, Any]:
    return {
        'step1_random_object': random_object,
        'target_statistic_hint': target_statistic,
        'information_set_hint': information_set,
        'initial_return_source_hypothesis': return_source,
        'similar_case_lessons_imported': [
            'Canonical intake preserves the source thesis before implementation optimization.',
            'Step4/5 must test long-only risk-adjusted evidence before Step6 promotion.',
        ],
        'what_must_be_true': what_must_be_true,
        'what_would_break_it': what_would_break_it,
        'source_type': source_type,
    }


def canonical_formula_hypotheses(formula: str, inputs: List[str], operators: List[str]) -> Dict[str, Any]:
    text = formula.lower()
    op_text = ' '.join(operators).lower()
    uses_price = any(item in inputs for item in ['open', 'high', 'low', 'close', 'vwap', 'return'])
    uses_liquidity = any(item in inputs for item in ['volume', 'amount', 'turnover'])
    uses_rank = 'rank' in op_text
    uses_delta = 'delta' in op_text
    uses_ts_rank = 'ts_rank' in op_text
    uses_volume_ratio = uses_liquidity and any(tok in text for tok in ['mean(volume', 'adv', 'divide(volume'])

    if uses_price and uses_liquidity:
        second_layer = {
            'subtype': 'price_volume_crowding_and_short_horizon_reversal',
            'expected_counterparty_or_payer': (
                'late trend followers, attention-driven retail flow, and mandate-constrained liquidity demand '
                'that chase visible price and volume states'
            ),
            'why_they_may_pay': (
                'their demand is triggered by observable recent price/volume strength rather than stable '
                'fundamental information, so temporary impact can decay over the next return window'
            ),
        }
        economic = {
            'macro_return_source': 'mixed',
            'second_layer': second_layer,
            'counterparty_loss_hypothesis': (
                'the payer is the marginal investor who buys crowded recent strength or supplies liquidity '
                'at the wrong time when short-horizon impact reverts'
            ),
            'risk_or_behavioral_compensation': (
                'compensation may combine transient liquidity risk, behavioral overreaction, and market-structure '
                'harvesting of delayed or constrained flow'
            ),
        }
        model_family = 'ranked_price_volume_state_process'
        state = 'cross-sectional security-day state built from price location, price acceleration, and relative volume intensity'
        process = (
            'observed price follows P_i,t = F_i,t + I_i,t + epsilon_i,t, where I_i,t is a transient impact state '
            'driven by recent price motion and abnormal volume; the hypothesis requires partial mean reversion '
            'E[I_i,t+1 - I_i,t | formula state] < 0 for crowded states'
        )
        estimator_parts = []
        if uses_ts_rank:
            estimator_parts.append('time-series rank of recent price level')
        if uses_delta:
            estimator_parts.append('second-order price difference / acceleration')
        if uses_volume_ratio:
            estimator_parts.append('time-series rank of volume relative to rolling average volume')
        observable = '; '.join(estimator_parts) or 'canonical ranked formula score'
        falsification = [
            'long-side high-score decile fails to earn positive risk-adjusted return after costs',
            'rank IC sign is unstable across 2016-2019, 2020-2024-09-23, and post-2024-09-24 regimes',
            'decile ordering is driven only by catastrophic short-leg losses rather than a usable high-score long side',
            'turnover costs consume the expected one-day transient-impact payoff',
        ]
    elif uses_price:
        economic = {
            'macro_return_source': 'mixed',
            'second_layer': {
                'subtype': 'short_horizon_price_state_reversal_or_continuation',
                'expected_counterparty_or_payer': 'investors extrapolating recent price states or providing liquidity under pressure',
                'why_they_may_pay': 'recent price states may contain temporary impact, stale information adjustment, or behavioral extrapolation',
            },
            'counterparty_loss_hypothesis': 'the payer is the marginal trader whose recent price-impact demand mean reverts or is repriced',
            'risk_or_behavioral_compensation': 'compensation may come from short-horizon reversal, momentum continuation, or liquidity provision risk',
        }
        model_family = 'ranked_price_state_process'
        state = 'cross-sectional security-day price state'
        process = (
            'price contains a latent short-horizon state whose conditional drift depends on ranked recent price '
            'movement and its time-series position'
        )
        observable = 'canonical ranked price-state formula score'
        falsification = [
            'long-side high-score decile lacks positive risk-adjusted return',
            'rank IC sign is unstable out of sample',
            'drawdown and recovery imply the state is regime-specific rather than persistent',
        ]
    else:
        economic = {
            'macro_return_source': 'mixed',
            'second_layer': {
                'subtype': 'canonical_formula_state_premium',
                'expected_counterparty_or_payer': 'market participants exposed to the state described by the canonical formula',
                'why_they_may_pay': 'the formula may isolate a priced state, information delay, or behavioral imbalance',
            },
            'counterparty_loss_hypothesis': 'the payer is the investor taking the other side of the formula-defined state',
            'risk_or_behavioral_compensation': 'compensation source remains under-specified until Step4/Step6 evidence is reviewed',
        }
        model_family = 'canonical_formula_state_process'
        state = 'formula-defined security-day state'
        process = 'future returns have a conditional distribution that changes with the canonical formula state'
        observable = 'canonical formula score'
        falsification = [
            'formula score has no stable rank IC',
            'high-score long side fails after costs',
            'metric signature cannot be linked to the stated economic mechanism',
        ]

    math = [
        {
            'hypothesis_id': 'H1_formula_state_conditional_return',
            'linked_economic_hypothesis': economic['second_layer']['subtype'],
            'model_family': model_family,
            'math_tools': [
                'cross-sectional rank transform',
                'rolling time-series state estimator',
                'conditional expectation of forward return',
            ],
            'state_or_object': state,
            'process_or_distribution_hypothesis': process,
            'observable_estimator': observable,
            'target_functional': (
                'E[r_i,t+1 | formula_state_i,t] and the monotone relation between formula_state_i,t '
                'and next-period cross-sectional return rank'
            ),
            'why_suitable': (
                'the canonical Alpha101 formula is an explicit low-lag transformation of observable market states; '
                'ranking reduces scale dependence and makes the hypothesis a cross-sectional conditional-return test'
            ),
            'falsification_tests': falsification,
        }
    ]
    if uses_rank:
        math[0]['math_tools'].append('copula/rank-order robustness check')
    if uses_delta:
        math[0]['math_tools'].append('finite-difference acceleration estimator')
    if uses_liquidity:
        math[0]['math_tools'].append('relative liquidity intensity estimator')
    return {
        'economic_hypothesis': economic,
        'math_hypothesis_candidates': math,
    }


def write_step1_artifacts(report_id: str, aim: Dict[str, Any], primary: Dict[str, Any], challenger: Dict[str, Any], report_map: Dict[str, Any]) -> None:
    write_json(ALPHA_IDEA_MASTER / f'alpha_idea_master__{report_id}.json', aim)
    write_json(VALIDATION / f'report_map_validation__{report_id}__alpha_thesis.json', primary)
    write_json(VALIDATION / f'report_map_validation__{report_id}__challenger_alpha_thesis.json', challenger)
    write_json(REPORT_MAPS / f'report_map__{report_id}__primary.json', report_map)


def build_canonical_formula_step1(
    report_id: str,
    factor_id: str,
    source_name: str,
    source_url: str,
    formula: str,
    window_start: str | None,
    window_end: str | None,
) -> Dict[str, Dict[str, Any]]:
    inputs = infer_formula_inputs(formula)
    operators = infer_formula_operators(formula)
    research = common_research_discipline(
        source_type='paper_canonical_formula',
        random_object='cross-sectional equity panel observed through price, volume, and other formula inputs',
        target_statistic='canonical formula score used to rank future cross-sectional returns',
        return_source='published formula may capture behavioral, liquidity, or microstructure effects embedded in ranked price-volume transformations',
        information_set='uses only contemporaneous and lagged market fields required by the formula',
        what_must_be_true=[
            'The canonical expression is implemented with no future-looking window alignment.',
            'The ranked formula score contains cross-sectional information after costs and risk controls.',
        ],
        what_would_break_it=[
            'Operator semantics differ from the published Alpha101 convention.',
            'Liquidity or turnover costs consume the long-only return source.',
        ],
    )
    hypotheses = canonical_formula_hypotheses(formula, inputs, operators)
    research.update(hypotheses)
    aim = {
        'contract_version': 'factorforge.step1.alpha_idea_master.v2',
        'producer': 'step12_canonical_formula_intake',
        'source_type': 'paper_canonical_formula',
        'report_id': report_id,
        'factor_id': factor_id,
        'source_name': source_name,
        'source_url': source_url,
        'raw_formula': formula,
        'window_start': window_start,
        'window_end': window_end,
        'created_at': now_iso(),
        'factor_intuition': research['initial_return_source_hypothesis'],
        'candidate_variables': inputs,
        'expected_direction': 'formula_defined',
        'return_source_hypothesis': research['initial_return_source_hypothesis'],
        'economic_hypothesis': research['economic_hypothesis'],
        'math_hypothesis_candidates': research['math_hypothesis_candidates'],
        'information_set': research['information_set_hint'],
        'what_must_be_true': research['what_must_be_true'],
        'what_would_break_it': research['what_would_break_it'],
        'ambiguities': ['Exact Alpha101 operator semantics and data-field conventions must be preserved by Step3B.'],
        'human_review_required': False,
        'research_discipline': research,
        'final_factor': {
            'name': factor_id,
            'direction': 'formula_defined',
            'assembly_steps': [formula],
            'economic_logic': research['initial_return_source_hypothesis'],
        },
        'math_discipline_review': {
            'step1_random_object': research['step1_random_object'],
            'target_statistic': research['target_statistic_hint'],
            'information_set_legality': research['information_set_hint'],
            'expected_failure_modes': research['what_would_break_it'],
        },
    }
    primary = {
        'contract_version': 'factorforge.step1.report_map_validation.v2',
        'producer': 'step12_canonical_formula_intake',
        'source_type': 'paper_canonical_formula',
        'factor_id': factor_id,
        'thesis_name': f'{factor_id} canonical formula thesis',
        'key_variables': inputs,
        'operators': operators,
        'signals': [formula],
        'raw_formula_text': formula,
        'economic_logic': research['initial_return_source_hypothesis'],
        'target_prediction': research['target_statistic_hint'],
    }
    challenger = {
        **primary,
        'producer': 'step12_canonical_formula_intake_challenger',
        'thesis_name': f'{factor_id} challenger formula reconstruction',
        'ambiguities': aim['ambiguities'],
        'signals': [f'Challenger independently preserves formula: {formula}'],
    }
    report_map = {
        'contract_version': 'factorforge.step1.report_map.v2',
        'producer': 'step12_canonical_formula_intake',
        'source_type': 'paper_canonical_formula',
        'report_id': report_id,
        'factor_id': factor_id,
        'source_name': source_name,
        'source_url': source_url,
        'variables': inputs,
        'operators': operators,
        'raw_formula': formula,
    }
    return {'aim': aim, 'primary': primary, 'challenger': challenger, 'report_map': report_map}


def build_hypothesis_step1(
    report_id: str,
    title: str,
    hypothesis: str,
    window_start: str | None,
    window_end: str | None,
) -> Dict[str, Dict[str, Any]]:
    variables = infer_hypothesis_variables(hypothesis)
    vague = len(hypothesis.strip()) < 24 or variables == ['close', 'return']
    return_source = 'user-proposed information signal may forecast future returns if its economic state change precedes market repricing'
    research = common_research_discipline(
        source_type='natural_language_hypothesis',
        random_object='security-level panel combining the named observable fields in the user hypothesis',
        target_statistic='cross-sectional score derived from the stated hypothesis and tested against future returns',
        return_source=return_source,
        information_set='must be limited to data known at each rebalance date; disclosure lag must be enforced for fundamental fields',
        what_must_be_true=[
            'The named variables are observable before the target return window.',
            'The hypothesized improvement or deterioration has incremental information after standard risk controls.',
        ],
        what_would_break_it=[
            'Disclosure timing makes the feature unavailable at rebalance time.',
            'The hypothesis proxies only broad style exposure rather than a distinct return source.',
        ],
    )
    aim = {
        'contract_version': 'factorforge.step1.alpha_idea_master.v2',
        'producer': 'step12_hypothesis_intake',
        'source_type': 'natural_language_hypothesis',
        'report_id': report_id,
        'title': title,
        'raw_user_hypothesis': hypothesis,
        'window_start': window_start,
        'window_end': window_end,
        'created_at': now_iso(),
        'factor_intuition': hypothesis,
        'candidate_variables': variables,
        'expected_direction': 'positive_if_hypothesis_strengthens',
        'return_source_hypothesis': return_source,
        'information_set': research['information_set_hint'],
        'what_must_be_true': research['what_must_be_true'],
        'what_would_break_it': research['what_would_break_it'],
        'ambiguities': [
            'Exact formula, disclosure lag, and normalization choices require human confirmation.'
        ] if vague else [
            'Step2 must preserve uncertainty around exact formula and lag assumptions rather than inventing precision.'
        ],
        'human_review_required': True,
        'research_discipline': research,
        'final_factor': {
            'name': title,
            'direction': 'positive_if_hypothesis_strengthens',
            'assembly_steps': [f'hypothesis_score({", ".join(variables)})'],
            'economic_logic': hypothesis,
        },
        'math_discipline_review': {
            'step1_random_object': research['step1_random_object'],
            'target_statistic': research['target_statistic_hint'],
            'information_set_legality': research['information_set_hint'],
            'expected_failure_modes': research['what_would_break_it'],
        },
    }
    primary = {
        'contract_version': 'factorforge.step1.report_map_validation.v2',
        'producer': 'step12_hypothesis_intake',
        'source_type': 'natural_language_hypothesis',
        'factor_id': title,
        'thesis_name': title,
        'key_variables': variables,
        'operators': ['change()', 'rank()', 'zscore()', 'lag_guard()'],
        'signals': [hypothesis],
        'raw_formula_text': f'hypothesis_score({", ".join(variables)})',
        'economic_logic': hypothesis,
        'target_prediction': research['target_statistic_hint'],
    }
    challenger = {
        **primary,
        'producer': 'step12_hypothesis_intake_challenger',
        'thesis_name': f'{title} challenger uncertainty audit',
        'signals': [f'Challenger tests whether the hypothesis is tradable without forward-looking data: {hypothesis}'],
        'ambiguities': aim['ambiguities'],
    }
    report_map = {
        'contract_version': 'factorforge.step1.report_map.v2',
        'producer': 'step12_hypothesis_intake',
        'source_type': 'natural_language_hypothesis',
        'report_id': report_id,
        'title': title,
        'variables': variables,
        'operators': primary['operators'],
        'raw_user_hypothesis': hypothesis,
    }
    return {'aim': aim, 'primary': primary, 'challenger': challenger, 'report_map': report_map}
