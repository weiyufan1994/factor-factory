#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def load_optional(path: Path) -> dict[str, Any]:
    return load_json(path) if path.exists() else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def text(value: Any, default: str = 'unknown') -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def nested(root: dict[str, Any], *keys: str) -> dict[str, Any]:
    cur: Any = root
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, dict) else {}


def compact_strings(values: list[Any], limit: int = 6) -> list[str]:
    out = []
    for value in values:
        if isinstance(value, dict):
            candidate = value.get('lesson_hint') or value.get('report_id') or value.get('factor_id') or value.get('snippet')
        else:
            candidate = value
        if isinstance(candidate, str) and candidate.strip():
            out.append(candidate.strip())
        if len(out) >= limit:
            break
    return out


def build_knowledge_priors(iteration: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    memo = nested(iteration, 'research_judgment', 'research_memo')
    learning = memo.get('learning_and_innovation') or {}
    experience_chain = memo.get('experience_chain') or {}
    imported = as_list(experience_chain.get('similar_experience_imported'))
    return {
        'similar_cases': [
            {
                'report_id': item.get('report_id'),
                'factor_id': item.get('factor_id'),
                'decision': item.get('decision'),
                'lesson_hint': item.get('lesson_hint'),
                'source_path': item.get('source_path'),
            }
            for item in imported
            if isinstance(item, dict)
        ][:5],
        'transferable_patterns': compact_strings(as_list(learning.get('transferable_patterns')) or as_list(knowledge.get('success_patterns'))),
        'anti_patterns': compact_strings(as_list(learning.get('anti_patterns')) or as_list(knowledge.get('failure_patterns'))),
        'innovative_idea_seeds': compact_strings(as_list(learning.get('innovative_idea_seeds')) or as_list(knowledge.get('modification_hypotheses'))),
        'reuse_instruction_for_future_agents': compact_strings(as_list(learning.get('reuse_instruction_for_future_agents'))),
    }


def infer_return_source(iteration: dict[str, Any], knowledge: dict[str, Any]) -> str:
    memo = nested(iteration, 'research_judgment', 'research_memo')
    return_source = nested(memo, 'return_source_analysis').get('primary_hypothesis')
    framework_source = nested(iteration, 'research_judgment', 'factor_investing_framework').get('monetization_model')
    knowledge_source = knowledge.get('monetization_model')
    return text(return_source or framework_source or knowledge_source, 'mixed')


def build_market_structure(iteration: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    framework = nested(iteration, 'research_judgment', 'factor_investing_framework')
    memo_return = nested(iteration, 'research_judgment', 'research_memo', 'return_source_analysis')
    return {
        'hypothesis': text(framework.get('return_source_hypothesis') or memo_return.get('explanation') or knowledge.get('return_source_hypothesis')),
        'constraint_sources': as_list(framework.get('constraint_sources') or memo_return.get('constraint_sources') or knowledge.get('constraint_sources')),
        'objective_constraint_dependency': text(framework.get('objective_constraint_dependency') or memo_return.get('objective_constraint_dependency') or knowledge.get('objective_constraint_dependency')),
        'expected_failure_regimes': as_list(framework.get('expected_failure_regimes') or knowledge.get('expected_failure_regimes')),
        'capacity_constraints': text(framework.get('capacity_constraints') or knowledge.get('capacity_constraints')),
        'implementation_risk': text(framework.get('implementation_risk') or knowledge.get('implementation_risk')),
    }


def branch_base(
    *,
    report_id: str,
    branch_id: str,
    branch_role: str,
    search_mode: str,
    return_source: str,
    market_structure: dict[str, Any],
    knowledge_priors: dict[str, Any],
    research_question: str,
    hypothesis: str,
    modification_scope: list[str],
    success_criteria: list[str],
    falsification_tests: list[str],
    budget: dict[str, Any],
) -> dict[str, Any]:
    return {
        'branch_id': branch_id,
        'parent_report_id': report_id,
        'branch_role': branch_role,
        'search_mode': search_mode,
        'status': 'proposed',
        'requires_human_approval_before_execution': True,
        'research_first_guardrail': 'This branch exists to test a Step6 research hypothesis; it must not optimize metrics without explaining return source, market structure, and prior lessons.',
        'research_question': research_question,
        'hypothesis': hypothesis,
        'return_source_target': return_source,
        'market_structure_hypothesis': market_structure,
        'knowledge_priors': knowledge_priors,
        'modification_scope': modification_scope,
        'budget': budget,
        'success_criteria': success_criteria,
        'falsification_tests': falsification_tests,
        'hard_guards': [
            'do not mutate shared clean data',
            'do not overwrite canonical Step3B implementation before approval',
            'do not propose short selling, direct decile trading, or portfolio-expression repair',
            'all revisions must change factor expression or Step3B code, not the trading wrapper',
            'do not use a single in-sample metric as success',
            'record failed variants and failure signatures',
            'preserve information-set legality',
        ],
        'expected_outputs': [
            f'factorforge/objects/research_iteration_master/search_branch_result__{report_id}__{branch_id}.json',
            f'factorforge/evaluations/{report_id}/{branch_id}/',
        ],
    }


def build_branches(
    *,
    report_id: str,
    decision: str,
    metric_verdict: str,
    signal_vs_portfolio_gap: str,
    return_source: str,
    market_structure: dict[str, Any],
    knowledge_priors: dict[str, Any],
    modification_targets: list[str],
    max_branches: int,
    include_audit: bool,
) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    base_budget = {'max_trials': 3, 'max_runtime_minutes': 45, 'max_parallel_agents': 1}

    if include_audit:
        branches.append(branch_base(
            report_id=report_id,
            branch_id='audit_evidence_and_thesis',
            branch_role='audit',
            search_mode='research_audit',
            return_source=return_source,
            market_structure=market_structure,
            knowledge_priors=knowledge_priors,
            research_question='Is the current iterate decision caused by a real factor weakness, or by evidence/data/contract bugs?',
            hypothesis='Before searching formulas, verify Step4/Step5 artifacts, information-set legality, implementation fidelity, and known anti-patterns.',
            modification_scope=['no_code_change', 'evidence_quality', 'thesis_preservation'],
            success_criteria=[
                'all official Step4 artifacts exist and pass validators',
                'Step5 quality gate is not hiding a backend or data bug',
                'the original Step1/2 thesis is still represented by Step3B code',
            ],
            falsification_tests=[
                'if evidence is incomplete or inconsistent, stop search and repair workflow first',
                'if information-set legality is uncertain, block promotion and code mutation',
            ],
            budget={'max_trials': 1, 'max_runtime_minutes': 20, 'max_parallel_agents': 1},
        ))

    if decision == 'iterate':
        branches.append(branch_base(
            report_id=report_id,
            branch_id='exploit_parameter_search',
            branch_role='exploit',
            search_mode='bayesian_search',
            return_source=return_source,
            market_structure=market_structure,
            knowledge_priors=knowledge_priors,
            research_question='Can the current thesis be made more stable by small, interpretable parameter changes?',
            hypothesis='If the return-source thesis is basically right, limited parameter search should improve long-side monotonicity without changing the economic story.',
            modification_scope=modification_targets[:4] or ['lookback_window', 'delay', 'normalization', 'winsorization'],
            success_criteria=[
                'improves long-side return and validation/OOS robustness, not only in-sample IC',
                'improves or preserves monotonic relation between factor value and future return',
                'keeps the same return-source explanation',
            ],
            falsification_tests=[
                'if only one sample improves, mark as overfit',
                'if improvement requires extreme parameter values, kill this branch',
            ],
            budget=base_budget,
        ))

        if metric_verdict in {'mixed', 'negative', 'inconclusive'} or return_source in {'mixed', 'constraint_driven_arbitrage'}:
            branches.append(branch_base(
                report_id=report_id,
                branch_id='explore_formula_mutation',
                branch_role='explore',
                search_mode='genetic_algorithm',
                return_source=return_source,
                market_structure=market_structure,
                knowledge_priors=knowledge_priors,
                research_question='Is there a neighboring formula that expresses the same market logic more cleanly?',
                hypothesis='Controlled formula mutation can test nearby mechanisms while preserving the underlying risk/information/constraint thesis.',
                modification_scope=['operator_substitution', 'sign_or_direction_test', 'lag_insertion', 'rank_vs_raw_transform', 'family_neighbor_test'],
                success_criteria=[
                    'child formula has a clearer mechanism than parent',
                    'child formula improves long-side Sharpe, drawdown/recovery, and monotonic expression behavior',
                    'complexity penalty remains acceptable',
                ],
                falsification_tests=[
                    'if mutations improve metrics but break thesis, reject as data mining',
                    'if multiple children converge to known failed anti-patterns, stop branch',
                ],
                budget={'max_trials': 6, 'max_runtime_minutes': 90, 'max_parallel_agents': 1},
            ))

        if return_source in {'mixed', 'constraint_driven_arbitrage'}:
            branches.append(branch_base(
                report_id=report_id,
                branch_id='macro_mechanism_challenge',
                branch_role='macro',
                search_mode='multi_agent_parallel_exploration',
                return_source=return_source,
                market_structure=market_structure,
                knowledge_priors=knowledge_priors,
                research_question='Can we articulate a repeatable market-structure mechanism rather than only a price pattern?',
                hypothesis='Constraint-driven or mixed-source factors should first identify the objective constraint, participant behavior, and decay risk.',
                modification_scope=['return_source_rewrite', 'constraint_source_test', 'regime_boundary', 'family_taxonomy_update'],
                success_criteria=[
                    'produces a sharper return-source thesis',
                    'identifies specific participants or constraints',
                    'defines where the factor should stop working',
                ],
                falsification_tests=[
                    'if no repeatable constraint or information mechanism can be stated, do not keep mutating the formula',
                ],
                budget={'max_trials': 2, 'max_runtime_minutes': 60, 'max_parallel_agents': 2},
            ))

    return branches[:max_branches]


def build_selection_protocol() -> dict[str, Any]:
    return {
        'primary_rule': 'Step6 chooses branches by thesis preservation plus robust evidence, not by raw metric maximization.',
        'score_components': [
            {'name': 'return_source_coherence', 'weight': 0.25},
            {'name': 'knowledge_prior_alignment_or_useful_contradiction', 'weight': 0.15},
            {'name': 'validation_or_oos_metric_improvement', 'weight': 0.15},
            {'name': 'long_side_risk_adjusted_quality', 'weight': 0.20},
            {'name': 'factor_value_return_monotonicity', 'weight': 0.15},
            {'name': 'simplicity_and_thesis_preservation', 'weight': 0.10},
            {'name': 'novelty_without_repeating_known_anti_patterns', 'weight': 0.05},
        ],
        'hard_blocks': [
            'lookahead or information-set illegality',
            'missing official Step4 artifacts',
            'metric improvement without explainable return-source mechanism',
            'improvement that only comes from short leg, long-short spread, direct decile trading, raw return without Sharpe/drawdown improvement, or portfolio-expression repair',
            'promotion based only on one in-sample run',
        ],
        'merge_rule': 'No branch becomes canonical Step3B without a branch result, Step4 evidence, Step5 quality gate, Step6 comparison, and human approval.',
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--max-branches', type=int, default=4)
    ap.add_argument('--no-audit', action='store_true')
    args = ap.parse_args()

    rid = args.report_id
    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json'
    if not iteration_path.exists():
        raise SystemExit(f'PROGRAM_SEARCH_PLAN_INVALID: missing {iteration_path}')

    iteration = load_json(iteration_path)
    knowledge = load_optional(OBJ / 'research_knowledge_base' / f'knowledge_record__{rid}.json')
    proposal = load_optional(OBJ / 'research_iteration_master' / f'revision_proposal__{rid}.json')

    research_judgment = iteration.get('research_judgment') or {}
    research_memo = research_judgment.get('research_memo') or {}
    metric_verdict = text(nested(research_memo, 'metric_interpretation').get('verdict'), 'inconclusive')
    math_review = research_memo.get('math_discipline_review') or {}
    decision = text(research_judgment.get('decision'), 'needs_human_review')
    signal_vs_portfolio_gap = text(math_review.get('signal_vs_portfolio_gap'), 'unknown')
    return_source = infer_return_source(iteration, knowledge)
    market_structure = build_market_structure(iteration, knowledge)
    knowledge_priors = build_knowledge_priors(iteration, knowledge)
    modification_targets = as_list((iteration.get('loop_action') or {}).get('modification_targets'))
    proposal_branches = nested(proposal, 'proposal').get('candidate_branches') or []

    branches = build_branches(
        report_id=rid,
        decision=decision,
        metric_verdict=metric_verdict,
        signal_vs_portfolio_gap=signal_vs_portfolio_gap,
        return_source=return_source,
        market_structure=market_structure,
        knowledge_priors=knowledge_priors,
        modification_targets=[str(x) for x in modification_targets],
        max_branches=max(1, args.max_branches),
        include_audit=not args.no_audit,
    )

    plan = {
        'report_id': rid,
        'factor_id': iteration.get('factor_id'),
        'producer': 'program_search_engine_v1',
        'created_at_utc': utc_now(),
        'status': 'pending_human_approval',
        'purpose': 'Translate Step6 researcher judgment into research-first, approval-gated search branches. Algorithms are helpers, not replacements for Step6 reasoning.',
        'step6_decision': decision,
        'research_context': {
            'metric_verdict': metric_verdict,
            'signal_vs_portfolio_gap': signal_vs_portfolio_gap,
            'return_source': return_source,
            'market_structure': market_structure,
            'knowledge_priors': knowledge_priors,
            'step6_revision_proposal_path': str((OBJ / 'research_iteration_master' / f'revision_proposal__{rid}.json')) if proposal else None,
            'proposal_candidate_branch_count': len(proposal_branches),
        },
        'branch_generation_rule': [
            'Start from Step6 return-source and market-structure thesis.',
            'Use knowledge-base priors before choosing algorithmic search mode.',
            'Run audit before formula search if evidence may be dirty.',
            'Keep exploit and explore separate so tuning does not masquerade as discovery.',
            'Require human approval before any branch changes Step3B execution.',
        ],
        'branches': branches,
        'selection_protocol': build_selection_protocol(),
    }

    ledger = {
        'report_id': rid,
        'created_at_utc': plan['created_at_utc'],
        'producer': 'program_search_engine_v1',
        'status': 'pending_human_approval',
        'branches': [
            {
                'branch_id': branch['branch_id'],
                'branch_role': branch['branch_role'],
                'search_mode': branch['search_mode'],
                'status': branch['status'],
                'requires_human_approval_before_execution': branch['requires_human_approval_before_execution'],
                'last_event': 'proposed_from_step6_research_judgment',
                'result_path': branch['expected_outputs'][0],
            }
            for branch in branches
        ],
    }

    write_json(OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json', plan)
    write_json(OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json', ledger)


if __name__ == '__main__':
    main()
