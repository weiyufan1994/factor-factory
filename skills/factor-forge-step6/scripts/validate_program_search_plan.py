#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'

VALID_SEARCH_MODES = {
    'research_audit',
    'bayesian_search',
    'genetic_algorithm',
    'reinforcement_learning_advisory',
    'multi_agent_parallel_exploration',
}
VALID_ROLES = {'audit', 'exploit', 'explore', 'portfolio', 'macro'}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def check(name: str, condition: bool, error: str, severity: str = 'BLOCK') -> dict[str, Any]:
    return {
        'name': name,
        'ok': bool(condition),
        'status': 'PASS' if condition else severity,
        'severity': severity,
        'error': None if condition else error,
    }


def nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def nested(root: dict[str, Any], *keys: str) -> Any:
    cur: Any = root
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def validate_branch(branch: dict[str, Any], index: int) -> list[dict[str, Any]]:
    prefix = f'branch_{index}_{branch.get("branch_id") or "unknown"}'
    market = branch.get('market_structure_hypothesis') or {}
    priors = branch.get('knowledge_priors') or {}
    budget = branch.get('budget') or {}
    return [
        check(f'{prefix}_branch_id_present', nonempty_str(branch.get('branch_id')), 'branch_id missing'),
        check(f'{prefix}_role_enum', branch.get('branch_role') in VALID_ROLES, f'invalid branch_role: {branch.get("branch_role")}'),
        check(f'{prefix}_search_mode_enum', branch.get('search_mode') in VALID_SEARCH_MODES, f'invalid search_mode: {branch.get("search_mode")}'),
        check(f'{prefix}_approval_gate', branch.get('requires_human_approval_before_execution') is True, 'branch must require human approval before execution'),
        check(f'{prefix}_research_question_present', nonempty_str(branch.get('research_question')), 'research_question missing'),
        check(f'{prefix}_hypothesis_present', nonempty_str(branch.get('hypothesis')), 'hypothesis missing'),
        check(f'{prefix}_return_source_present', nonempty_str(branch.get('return_source_target')), 'return_source_target missing'),
        check(f'{prefix}_market_structure_hypothesis_present', nonempty_str(market.get('hypothesis')), 'market structure hypothesis missing'),
        check(f'{prefix}_knowledge_priors_present', isinstance(priors, dict) and bool(priors), 'knowledge_priors missing'),
        check(
            f'{prefix}_knowledge_or_cold_start_note_present',
            any(nonempty_list(priors.get(key)) for key in ['similar_cases', 'transferable_patterns', 'anti_patterns', 'innovative_idea_seeds', 'reuse_instruction_for_future_agents']),
            'branch must carry knowledge priors or explicit cold-start lessons',
            severity='WARN',
        ),
        check(f'{prefix}_modification_scope_present', nonempty_list(branch.get('modification_scope')), 'modification_scope missing'),
        check(f'{prefix}_budget_present', isinstance(budget.get('max_trials'), int) and isinstance(budget.get('max_runtime_minutes'), int), 'budget max_trials/max_runtime_minutes missing'),
        check(f'{prefix}_success_criteria_present', nonempty_list(branch.get('success_criteria')), 'success_criteria missing'),
        check(f'{prefix}_falsification_tests_present', nonempty_list(branch.get('falsification_tests')), 'falsification_tests missing'),
        check(f'{prefix}_hard_guards_present', nonempty_list(branch.get('hard_guards')), 'hard_guards missing'),
        check(f'{prefix}_expected_outputs_present', nonempty_list(branch.get('expected_outputs')), 'expected_outputs missing'),
        check(
            f'{prefix}_research_first_guardrail_present',
            'research' in str(branch.get('research_first_guardrail') or '').lower(),
            'research_first_guardrail missing or too weak',
        ),
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()

    rid = args.report_id
    plan_path = OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json'
    ledger_path = OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json'
    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json'

    checks: list[dict[str, Any]] = [
        check('program_search_plan_exists', plan_path.exists(), f'missing {plan_path}'),
        check('search_branch_ledger_exists', ledger_path.exists(), f'missing {ledger_path}'),
        check('research_iteration_master_exists', iteration_path.exists(), f'missing {iteration_path}'),
    ]

    if plan_path.exists():
        plan = load_json(plan_path)
        branches = plan.get('branches') or []
        checks.extend([
            check('report_id_match', plan.get('report_id') == rid, 'report_id mismatch'),
            check('status_pending_approval', plan.get('status') == 'pending_human_approval', 'program search plan must start pending_human_approval'),
            check('purpose_research_first', 'Algorithms are helpers' in str(plan.get('purpose') or ''), 'purpose must state algorithms are helpers, not replacements'),
            check('research_context_present', isinstance(plan.get('research_context'), dict) and bool(plan.get('research_context')), 'research_context missing'),
            check('return_source_in_context', nonempty_str(nested(plan, 'research_context', 'return_source')), 'research_context.return_source missing'),
            check('market_structure_in_context', nonempty_str(nested(plan, 'research_context', 'market_structure', 'hypothesis')), 'research_context.market_structure.hypothesis missing'),
            check('branch_generation_rule_present', nonempty_list(plan.get('branch_generation_rule')), 'branch_generation_rule missing'),
            check('branches_present', nonempty_list(branches), 'branches missing'),
            check('selection_protocol_present', isinstance(plan.get('selection_protocol'), dict) and bool(plan.get('selection_protocol')), 'selection_protocol missing'),
            check('selection_protocol_not_raw_metric_only', 'raw metric' in str(nested(plan, 'selection_protocol', 'primary_rule') or '').lower(), 'selection protocol must reject raw-metric-only selection'),
        ])
        roles = {branch.get('branch_role') for branch in branches if isinstance(branch, dict)}
        checks.append(check('audit_or_explicit_research_guard_present', 'audit' in roles or bool(plan.get('branch_generation_rule')), 'plan should include audit branch or explicit research guard'))
        for i, branch in enumerate(branches, start=1):
            if isinstance(branch, dict):
                checks.extend(validate_branch(branch, i))
            else:
                checks.append(check(f'branch_{i}_is_object', False, 'branch entry is not an object'))

    if ledger_path.exists() and plan_path.exists():
        plan = load_json(plan_path)
        ledger = load_json(ledger_path)
        plan_ids = [b.get('branch_id') for b in plan.get('branches') or [] if isinstance(b, dict)]
        ledger_ids = [b.get('branch_id') for b in ledger.get('branches') or [] if isinstance(b, dict)]
        checks.extend([
            check('ledger_report_id_match', ledger.get('report_id') == rid, 'ledger report_id mismatch'),
            check('ledger_status_pending_approval', ledger.get('status') == 'pending_human_approval', 'ledger must start pending_human_approval'),
            check('ledger_branch_ids_match_plan', plan_ids == ledger_ids, 'ledger branch ids do not match plan branch ids'),
        ])

    has_block = any(item['status'] == 'BLOCK' for item in checks)
    has_warn = any(item['status'] == 'WARN' for item in checks)
    result = 'BLOCK' if has_block else 'WARN' if has_warn else 'PASS'
    report = {
        'report_id': rid,
        'result': result,
        'checks': checks,
    }
    out = OBJ / 'validation' / f'program_search_plan_validation__{rid}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {out}')
    print(f'RESULT: {result}')
    if has_block:
        sys.exit(1)


if __name__ == '__main__':
    main()
