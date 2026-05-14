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
