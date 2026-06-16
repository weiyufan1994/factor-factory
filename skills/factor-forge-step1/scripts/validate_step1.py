#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'

from factor_factory.knowledge_reference import build_legacy_knowledge_reference_contract, validate_knowledge_reference_contract


def check(name: str, condition: bool, error: str | None = None, severity: str = 'BLOCK'):
    status = 'PASS' if condition else severity
    return {'name': name, 'ok': bool(condition), 'status': status, 'severity': severity, 'error': None if condition else error}


def nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value) -> bool:
    return isinstance(value, list) and bool(value)


def valid_knowledge_reference_contract(value, lessons=None) -> bool:
    candidate = value
    if not candidate and nonempty_list(lessons):
        candidate = build_legacy_knowledge_reference_contract(
            similar_case_lessons=lessons,
            producer='step1_legacy_artifact_validator',
        )
    return not validate_knowledge_reference_contract(candidate or {}, retrieval_required=False)


def valid_economic_hypothesis(value) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    if value.get('macro_return_source') not in {'risk_premium', 'information_advantage', 'market_structure_arbitrage', 'mixed'}:
        return False
    second = value.get('second_layer')
    return (
        isinstance(second, dict)
        and nonempty_str(second.get('subtype'))
        and nonempty_str(second.get('expected_counterparty_or_payer'))
        and nonempty_str(second.get('why_they_may_pay'))
        and nonempty_str(value.get('counterparty_loss_hypothesis'))
    )


def valid_math_hypothesis_candidates(value) -> bool:
    if not isinstance(value, list) or not value:
        return False
    required = {
        'hypothesis_id',
        'linked_economic_hypothesis',
        'model_family',
        'math_tools',
        'state_or_object',
        'process_or_distribution_hypothesis',
        'observable_estimator',
        'target_functional',
        'why_suitable',
        'falsification_tests',
    }
    for item in value:
        if not isinstance(item, dict):
            return False
        if any(key not in item for key in required):
            return False
        if not nonempty_list(item.get('math_tools')) or not nonempty_list(item.get('falsification_tests')):
            return False
        for key in required - {'math_tools', 'falsification_tests'}:
            if not nonempty_str(item.get(key)):
                return False
    return True


def not_vague(value) -> bool:
    if not nonempty_str(value):
        return False
    return str(value).strip().lower() not in {'under_specified', 'unknown', 'n/a', 'none', 'todo', 'tbd'}


def meaningful_list(value) -> bool:
    return isinstance(value, list) and any(not_vague(item) for item in value)


def valid_market_process_thesis(value) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    required = ['market_phenomenon', 'economic_hypothesis', 'return_source_family', 'payer_or_counterparty', 'why_they_pay']
    source = value.get('return_source_family')
    alternatives = value.get('alternative_return_source_tests')
    valid_sources = {'risk_premium', 'information_advantage', 'market_structure_arbitrage', 'constraint_driven_arbitrage', 'mixed'}
    has_alternative_test = False
    if isinstance(alternatives, list):
        for item in alternatives:
            if not isinstance(item, dict):
                continue
            if (
                item.get('alternative_source') in valid_sources
                and item.get('alternative_source') != source
                and not_vague(item.get('why_not_primary'))
                and not_vague(item.get('discriminating_test'))
                and not_vague(item.get('expected_signature_if_alternative_true'))
            ):
                has_alternative_test = True
                break
    return (
        all(not_vague(value.get(key)) for key in required)
        and source in valid_sources
        and meaningful_list(value.get('what_must_be_true'))
        and meaningful_list(value.get('what_would_break_it'))
        and has_alternative_test
    )


def valid_primary_model_candidates(value) -> bool:
    if not isinstance(value, list) or not value:
        return False
    has_preferred = False
    for item in value:
        if not isinstance(item, dict):
            return False
        has_preferred = has_preferred or item.get('preferred') is True or item.get('rank') == 1
        if not not_vague(item.get('selected_model_family')):
            return False
        if not not_vague(item.get('why_this_model_fits')):
            return False
        if not meaningful_list(item.get('why_alternatives_are_less_suitable')):
            return False
        if not meaningful_list(item.get('state_variables')) and not meaningful_list(item.get('observable_proxies')):
            return False
    return has_preferred


def valid_stochastic_projection(value) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    return (
        value.get('projection_required') is True
        and meaningful_list(value.get('affected_price_process_terms'))
        and not_vague(value.get('price_process_form'))
        and not_vague(value.get('conditional_distribution_claim'))
        and not_vague(value.get('formula_should_estimate'))
        and not_vague(value.get('expected_return_distribution_change'))
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    rid = args.report_id
    path = OBJ / 'alpha_idea_master' / f'alpha_idea_master__{rid}.json'
    checks = [check('alpha_idea_master_exists', path.exists(), f'missing {path}')]
    errors = []
    warnings = []
    if path.exists():
        aim = json.loads(path.read_text(encoding='utf-8'))
        discipline = aim.get('research_discipline') or {}
        math_review = aim.get('math_discipline_review') or {}
        learning = aim.get('learning_and_innovation') or {}
        info_hint = str(discipline.get('information_set_hint') or math_review.get('information_set_legality') or '').lower()
        checks.extend([
            check('report_id_match', aim.get('report_id') == rid, 'report_id mismatch'),
            check('final_factor_present', isinstance(aim.get('final_factor'), dict) and bool(aim.get('final_factor')), 'final_factor missing'),
            check('step1_random_object_present', nonempty_str(discipline.get('step1_random_object') or aim.get('step1_random_object') or math_review.get('step1_random_object')), 'step1_random_object missing'),
            check('target_statistic_hint_present', nonempty_str(discipline.get('target_statistic_hint') or math_review.get('target_statistic')), 'target_statistic_hint missing'),
            check('information_set_hint_present', nonempty_str(discipline.get('information_set_hint') or math_review.get('information_set_legality')), 'information_set_hint missing'),
            check('initial_return_source_hypothesis_present', nonempty_str(discipline.get('initial_return_source_hypothesis')), 'initial_return_source_hypothesis missing'),
            check('economic_hypothesis_present', valid_economic_hypothesis(discipline.get('economic_hypothesis')), 'research_discipline.economic_hypothesis missing or incomplete'),
            check('math_hypothesis_candidates_present', valid_math_hypothesis_candidates(discipline.get('math_hypothesis_candidates')), 'research_discipline.math_hypothesis_candidates missing or incomplete'),
            check('market_process_thesis_present', valid_market_process_thesis(discipline.get('market_process_thesis')), 'research_discipline.market_process_thesis missing or incomplete'),
            check('primary_mechanism_model_candidates_present', valid_primary_model_candidates(discipline.get('primary_mechanism_model_candidates')), 'research_discipline.primary_mechanism_model_candidates missing or incomplete'),
            check('stochastic_price_process_projection_present', valid_stochastic_projection(discipline.get('stochastic_price_process_projection')), 'research_discipline.stochastic_price_process_projection missing or incomplete'),
            check('similar_case_lessons_imported_present', nonempty_list(discipline.get('similar_case_lessons_imported') or learning.get('similar_case_lessons_imported')), 'similar_case_lessons_imported missing'),
            check(
                'knowledge_reference_contract_present',
                valid_knowledge_reference_contract(
                    discipline.get('knowledge_reference_contract') or learning.get('knowledge_reference_contract'),
                    discipline.get('similar_case_lessons_imported') or learning.get('similar_case_lessons_imported'),
                ),
                'knowledge_reference_contract missing or invalid',
            ),
            check('what_must_be_true_present', nonempty_list(discipline.get('what_must_be_true')), 'what_must_be_true missing'),
            check('what_would_break_it_present', nonempty_list(discipline.get('what_would_break_it')), 'what_would_break_it missing'),
            check('information_set_not_illegal', 'illegal' not in info_hint and 'forward_reference' not in info_hint, f'information_set_hint blocks Step1 acceptance: {info_hint}', severity='WARN'),
        ])
    for item in checks:
        if item['status'] == 'BLOCK':
            errors.append(item['error'])
        elif item['status'] == 'WARN':
            warnings.append(item['error'])
    result = 'BLOCK' if errors else 'WARN' if warnings else 'PASS'
    print(json.dumps({'report_id': rid, 'result': result, 'checks': checks, 'errors': errors, 'warnings': warnings}, ensure_ascii=False, indent=2))
    if result == 'BLOCK':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
