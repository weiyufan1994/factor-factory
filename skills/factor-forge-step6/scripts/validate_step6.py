#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FF) not in sys.path:
    sys.path.append(str(FF))

from skills.factor_forge_step5.modules.io import load_json  # type: ignore

OBJ = FF / 'objects'
VALID_DECISIONS = {'promote_official', 'iterate', 'reject', 'needs_human_review'}
VALID_METRIC_VERDICTS = {'supportive', 'mixed', 'negative', 'inconclusive'}
REQUIRED_SEARCH_METHODS = {
    'genetic_algorithm',
    'bayesian_search',
    'reinforcement_learning',
    'multi_agent_parallel_exploration',
}


def check(name: str, condition: bool, error: str | None = None, severity: str = 'BLOCK'):
    status = 'PASS' if condition else severity
    return {
        'name': name,
        'ok': bool(condition),
        'status': status,
        'severity': severity,
        'error': None if condition else error,
    }


def nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value) -> bool:
    return isinstance(value, list) and bool(value)


def nested_dict(root: dict, *keys: str) -> dict:
    cur = root
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, dict) else {}


def has_key_recursive(value, target: str) -> bool:
    if isinstance(value, dict):
        if target in value:
            return True
        return any(has_key_recursive(item, target) for item in value.values())
    if isinstance(value, list):
        return any(has_key_recursive(item, target) for item in value)
    return False


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    rid = args.report_id

    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json'
    all_library_path = OBJ / 'factor_library_all' / f'factor_record__{rid}.json'
    official_library_path = OBJ / 'factor_library_official' / f'factor_record__{rid}.json'
    knowledge_path = OBJ / 'research_knowledge_base' / f'knowledge_record__{rid}.json'
    step3b_handoff_path = OBJ / 'handoff' / f'handoff_to_step3b__{rid}.json'
    step6_handoff_path = OBJ / 'handoff' / f'handoff_to_step6__{rid}.json'

    checks = []
    errors = []

    for label, path in [
        ('research_iteration_master_exists', iteration_path),
        ('factor_library_all_exists', all_library_path),
        ('knowledge_record_exists', knowledge_path),
    ]:
        checks.append(check(label, path.exists(), f'missing {path}'))

    if iteration_path.exists() and all_library_path.exists() and knowledge_path.exists():
        iteration = load_json(iteration_path)
        all_record = load_json(all_library_path)
        knowledge = load_json(knowledge_path)

        decision = iteration.get('research_judgment', {}).get('decision')
        checks.append(check('decision_enum', decision in VALID_DECISIONS, f'invalid decision: {decision}'))
        checks.append(check('report_id_match', iteration.get('report_id') == all_record.get('report_id') == knowledge.get('report_id') == rid, 'report_id mismatch'))
        checks.append(check('factor_id_match', iteration.get('factor_id') == all_record.get('factor_id') == knowledge.get('factor_id'), 'factor_id mismatch'))
        checks.append(check('headline_metrics_present', isinstance(iteration.get('evidence_summary', {}).get('headline_metrics'), dict), 'headline_metrics missing'))
        checks.append(check('modification_targets_present', isinstance(iteration.get('loop_action', {}).get('modification_targets'), list), 'modification_targets missing'))
        checks.append(check('step5_handoff_recorded', isinstance(iteration.get('upstream_handoff', {}).get('step5_handoff_path'), str), 'step5 handoff path missing from iteration payload'))
        checks.append(check('framework_present', isinstance(iteration.get('research_judgment', {}).get('factor_investing_framework'), dict), 'factor investing framework missing'))
        checks.append(check('legacy_dd_view_edge_trade_absent', not has_key_recursive(iteration, 'dd_view_edge_trade') and not has_key_recursive(knowledge, 'dd_view_edge_trade'), 'Step6 must not emit DD-view-edge-trade fields; that framework is outside Factor Forge'))
        checks.append(check('knowledge_return_hypothesis_present', isinstance(knowledge.get('return_source_hypothesis'), str), 'return_source_hypothesis missing'))
        checks.append(check('framework_review_checklist_present', isinstance(iteration.get('research_judgment', {}).get('factor_investing_framework', {}).get('review_checklist'), list), 'review_checklist missing'))
        checks.append(check('knowledge_revision_principles_present', isinstance(knowledge.get('revision_principles'), list), 'revision_principles missing'))

        research_judgment = iteration.get('research_judgment') or {}
        research_memo = research_judgment.get('research_memo') or {}
        metric_interpretation = nested_dict(research_judgment, 'research_memo', 'metric_interpretation')
        long_side_policy = (
            nested_dict(research_judgment, 'research_memo', 'long_side_adoption_policy')
            or nested_dict(metric_interpretation, 'long_side_adoption_review')
        )
        formula_understanding = nested_dict(research_judgment, 'research_memo', 'formula_understanding')
        return_source = nested_dict(research_judgment, 'research_memo', 'return_source_analysis')
        math_discipline = nested_dict(research_judgment, 'research_memo', 'math_discipline_review')
        learning = nested_dict(research_judgment, 'research_memo', 'learning_and_innovation')
        evidence_quality = nested_dict(research_judgment, 'research_memo', 'evidence_quality')
        failure_analysis = nested_dict(research_judgment, 'research_memo', 'failure_and_risk_analysis')
        experience_chain = research_memo.get('experience_chain') or research_judgment.get('experience_chain') or {}
        revision_taxonomy = research_memo.get('revision_taxonomy') or research_judgment.get('revision_taxonomy') or {}
        program_search_policy = research_memo.get('program_search_policy') or research_judgment.get('program_search_policy') or {}
        diversity_position = research_memo.get('diversity_position') or research_judgment.get('diversity_position') or {}
        method_library = program_search_policy.get('method_library') or {}
        search_branches = ((program_search_policy.get('recommended_next_search') or {}).get('branches')) or []
        information_set_legality = str(math_discipline.get('information_set_legality') or '').lower()
        overfit_risk_items = [str(item).lower() for item in (math_discipline.get('overfit_risk') or [])]
        metric_evidence_items = (
            (metric_interpretation.get('positive_evidence') or [])
            + (metric_interpretation.get('negative_evidence') or [])
            + (metric_interpretation.get('ambiguities') or [])
        )

        checks.append(check('research_memo_present', isinstance(research_memo, dict) and bool(research_memo), 'research_memo missing or empty'))
        checks.append(check('research_memo_formula_plain_language_present', nonempty_str(formula_understanding.get('plain_language')), 'formula understanding plain_language missing'))
        checks.append(check('research_memo_formula_break_conditions_present', nonempty_list(formula_understanding.get('what_would_break_it')), 'formula break conditions missing'))
        checks.append(check('research_memo_return_source_present', nonempty_str(return_source.get('primary_hypothesis')) and nonempty_str(return_source.get('explanation')), 'return source analysis missing'))
        checks.append(check('research_memo_metric_verdict_enum', metric_interpretation.get('verdict') in VALID_METRIC_VERDICTS, f"invalid metric verdict: {metric_interpretation.get('verdict')}"))
        checks.append(check('research_memo_metric_evidence_present', bool(metric_evidence_items), 'metric interpretation must include positive, negative, or ambiguity evidence'))
        checks.append(check('research_memo_raw_metrics_present', isinstance(metric_interpretation.get('raw_metrics_used'), dict) and bool(metric_interpretation.get('raw_metrics_used')), 'raw_metrics_used missing from research_memo'))
        checks.append(check('long_side_adoption_policy_present', isinstance(long_side_policy, dict) and bool(long_side_policy), 'long_side_adoption_policy missing from research_memo'))
        policy = long_side_policy.get('policy') if isinstance(long_side_policy.get('policy'), dict) else long_side_policy
        checks.append(check('long_side_policy_no_short_selling', policy.get('no_short_selling') is True, 'Step6 must enforce no_short_selling=true'))
        checks.append(check('long_side_policy_no_direct_decile_trading', policy.get('no_direct_decile_trading') is True, 'Step6 must enforce no_direct_decile_trading=true'))
        checks.append(check('long_side_policy_primary_objective', policy.get('primary_objective') == 'long_side_risk_adjusted_alpha', 'Step6 primary objective must be long_side_risk_adjusted_alpha'))
        checks.append(check('long_side_policy_revision_scope', policy.get('revision_scope') == 'factor_expression_and_step3b_code_only', 'Step6 revision scope must be factor_expression_and_step3b_code_only'))
        factor_business = long_side_policy.get('factor_as_business_review') if isinstance(long_side_policy, dict) else {}
        checks.append(check('long_side_factor_business_review_present', isinstance(factor_business, dict) and bool(factor_business), 'Step6 long_side_adoption_policy.factor_as_business_review missing'))
        thresholds = (factor_business or {}).get('thresholds') if isinstance(factor_business, dict) else {}
        checks.append(check('long_side_sharpe_thresholds_present', isinstance(thresholds, dict) and 'candidate_min_sharpe' in thresholds and 'official_min_sharpe' in thresholds, 'Step6 must record long-side Sharpe thresholds'))
        checks.append(check('research_memo_math_discipline_present', isinstance(math_discipline, dict) and bool(math_discipline), 'math_discipline_review missing from research_memo'))
        checks.append(check('math_random_object_present', nonempty_str(math_discipline.get('step1_random_object')), 'math discipline step1_random_object missing'))
        checks.append(check('math_target_statistic_present', nonempty_str(math_discipline.get('target_statistic')), 'math discipline target_statistic missing'))
        checks.append(check('math_information_legality_present', nonempty_str(math_discipline.get('information_set_legality')), 'math discipline information_set_legality missing'))
        checks.append(check('math_spec_stability_present', isinstance(math_discipline.get('spec_stability'), dict) and bool(math_discipline.get('spec_stability')), 'math discipline spec_stability missing'))
        checks.append(check('math_signal_portfolio_gap_present', nonempty_str(math_discipline.get('signal_vs_portfolio_gap')), 'math discipline signal_vs_portfolio_gap missing'))
        checks.append(check('math_long_side_objective_present', isinstance(math_discipline.get('long_side_objective'), dict) and bool(math_discipline.get('long_side_objective')), 'math discipline long_side_objective missing'))
        checks.append(check('math_monotonicity_objective_present', nonempty_str(math_discipline.get('monotonicity_objective')), 'math discipline monotonicity_objective missing'))
        checks.append(check('math_revision_scope_expression_only', math_discipline.get('revision_scope_constraint') == 'factor_expression_and_step3b_code_only', 'math discipline revision_scope_constraint must be expression/code only'))
        checks.append(check('math_revision_operator_present', nonempty_str(math_discipline.get('revision_operator')), 'math discipline revision_operator missing'))
        checks.append(check('math_generalization_argument_present', nonempty_str(math_discipline.get('generalization_argument')), 'math discipline generalization_argument missing'))
        checks.append(check('math_overfit_risk_present', nonempty_list(math_discipline.get('overfit_risk')), 'math discipline overfit_risk missing'))
        checks.append(check('math_kill_criteria_present', nonempty_list(math_discipline.get('kill_criteria')), 'math discipline kill_criteria missing'))
        checks.append(check(
            'math_information_set_legality_not_illegal',
            'illegal' not in information_set_legality,
            f'information_set_legality is blocking: {math_discipline.get("information_set_legality")}',
        ))
        checks.append(check(
            'promote_requires_confirmed_information_set_legality',
            decision != 'promote_official' or (
                'requires_researcher_confirmation' not in information_set_legality
                and 'unknown' not in information_set_legality
            ),
            'official promotion requires confirmed information-set legality, not unknown/requires confirmation',
        ))
        checks.append(check(
            'promote_requires_known_overfit_risk',
            decision != 'promote_official' or not any('unknown' in item or 'not assessed' in item for item in overfit_risk_items),
            'official promotion requires assessed overfit risk',
        ))
        checks.append(check('learning_and_innovation_present', isinstance(learning, dict) and bool(learning), 'learning_and_innovation missing from research_memo'))
        checks.append(check('learning_transferable_patterns_present', nonempty_list(learning.get('transferable_patterns')), 'learning transferable_patterns missing'))
        checks.append(check('learning_anti_patterns_present', nonempty_list(learning.get('anti_patterns')), 'learning anti_patterns missing'))
        checks.append(check('learning_similar_case_lessons_imported_present', nonempty_list(learning.get('similar_case_lessons_imported')), 'learning similar_case_lessons_imported missing; write explicit cold-start note if no cases exist'))
        checks.append(check('learning_idea_seeds_present', nonempty_list(learning.get('innovative_idea_seeds')), 'learning innovative_idea_seeds missing'))
        checks.append(check('learning_reuse_instruction_present', nonempty_list(learning.get('reuse_instruction_for_future_agents')), 'learning reuse_instruction_for_future_agents missing'))
        checks.append(check('experience_chain_present', isinstance(experience_chain, dict) and bool(experience_chain), 'experience_chain missing from Step6 research judgment'))
        checks.append(check('experience_chain_current_attempt_present', isinstance(experience_chain.get('current_attempt'), dict), 'experience_chain.current_attempt missing'))
        checks.append(check('revision_taxonomy_present', isinstance(revision_taxonomy, dict) and bool(revision_taxonomy), 'revision_taxonomy missing from Step6 research judgment'))
        checks.append(check('revision_taxonomy_macro_micro_present', isinstance(revision_taxonomy.get('macro_revision'), dict) and isinstance(revision_taxonomy.get('micro_revision'), dict), 'revision taxonomy must distinguish macro_revision and micro_revision'))
        checks.append(check('revision_taxonomy_expression_present', isinstance(revision_taxonomy.get('expression_revision'), dict), 'revision taxonomy must include expression_revision'))
        portfolio_revision_text = json.dumps(revision_taxonomy.get('portfolio_revision') or {}, ensure_ascii=False).lower()
        checks.append(check(
            'portfolio_revision_forbidden',
            'forbidden' in portfolio_revision_text and 'portfolio_expression_repair' not in portfolio_revision_text,
            'portfolio_revision must be explicitly forbidden; Step6 cannot repair adoption by changing portfolio/decile/short mechanics',
        ))
        checks.append(check('program_search_policy_present', isinstance(program_search_policy, dict) and bool(program_search_policy), 'program_search_policy missing from Step6 research judgment'))
        checks.append(check('program_search_methods_present', REQUIRED_SEARCH_METHODS.issubset(set(method_library.keys())), f'program_search_policy.method_library must include {sorted(REQUIRED_SEARCH_METHODS)}'))
        checks.append(check('diversity_position_present', isinstance(diversity_position, dict) and bool(diversity_position), 'diversity_position missing from Step6 research judgment'))
        checks.append(check(
            'iterate_requires_exploration_branches',
            decision != 'iterate' or nonempty_list(search_branches),
            'iterate decisions must include program_search_policy.recommended_next_search.branches',
        ))
        checks.append(check(
            'iterate_requires_human_approval_gate',
            decision != 'iterate' or bool((program_search_policy.get('recommended_next_search') or {}).get('requires_human_approval_before_code_change')),
            'iterate decisions must keep human approval before code changes',
        ))
        checks.append(check('research_memo_evidence_quality_notes_present', nonempty_list(evidence_quality.get('notes')), 'evidence quality notes missing'))
        checks.append(check('research_memo_failure_regimes_present', nonempty_list(failure_analysis.get('expected_failure_regimes')), 'failure regimes missing'))
        checks.append(check('research_memo_decision_rationale_present', nonempty_list(research_memo.get('decision_rationale')), 'decision rationale missing'))
        checks.append(check('research_memo_next_tests_present', nonempty_list(research_memo.get('next_research_tests')), 'next research tests missing'))
        checks.append(check('knowledge_research_memo_present', isinstance(knowledge.get('research_memo'), dict) and bool(knowledge.get('research_memo')), 'knowledge record must preserve research_memo'))
        checks.append(check(
            'external_researcher_context_present',
            isinstance(research_memo.get('researcher_journal'), dict) or isinstance(research_memo.get('researcher_agent_memo'), dict),
            'Step6 requires full-workflow researcher_journal or Step6 researcher_agent_memo; do not validate pure script-only analysis'
        ))

        if decision == 'promote_official':
            checks.append(check('promote_requires_supportive_metric_verdict', metric_interpretation.get('verdict') == 'supportive', 'official promotion requires supportive metric verdict'))
            checks.append(check(
                'promote_requires_official_ready_long_side',
                long_side_policy.get('long_side_status') == 'official_ready',
                'official promotion requires official-ready risk-adjusted long-side evidence; raw return, short/long-short diagnostics are insufficient',
            ))

        if step6_handoff_path.exists():
            checks.append(check('step6_handoff_exists', True, None))
        else:
            checks.append(check('step6_handoff_optional_fallback', True, None))

        if decision == 'promote_official':
            checks.append(check('official_library_exists', official_library_path.exists(), f'missing {official_library_path}'))
        else:
            checks.append(check('official_library_absent_when_not_promoted', not official_library_path.exists(), 'official library record should not exist'))

        if decision == 'iterate':
            checks.append(check('handoff_to_step3b_exists', step3b_handoff_path.exists(), f'missing {step3b_handoff_path}'))
        else:
            checks.append(check('handoff_to_step3b_absent_when_not_iterate', not step3b_handoff_path.exists(), 'handoff_to_step3b should not exist'))

    warnings = []
    for item in checks:
        if item['status'] == 'BLOCK':
            errors.append(item['error'])
        elif item['status'] == 'WARN':
            warnings.append(item['error'])

    result = 'BLOCK' if errors else 'WARN' if warnings else 'PASS'
    payload = {'report_id': rid, 'result': result, 'checks': checks, 'errors': errors, 'warnings': warnings}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result == 'BLOCK':
        raise SystemExit(1)
