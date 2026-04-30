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


def result_score(result: dict[str, Any]) -> float:
    score = 0.0
    if result.get('status') == 'completed':
        score += 1.0
    if result.get('outcome') == 'improved':
        score += 2.0
    if result.get('recommendation') == 'use_branch_for_next_step3b':
        score += 1.5
    if result.get('recommendation') in {'kill_branch', 'repair_workflow_first'}:
        score -= 1.0
    assessment = result.get('research_assessment') or {}
    if assessment.get('falsification_result') not in {None, '', 'not_assessed'}:
        score += 0.5
    if assessment.get('overfit_assessment') not in {None, '', 'not_assessed'}:
        score += 0.5
    evidence = result.get('evidence') or {}
    if evidence.get('metric_delta'):
        score += 0.5
    if as_list(evidence.get('step4_artifacts')):
        score += 0.5
    if as_list(evidence.get('failure_signatures')):
        score -= 0.5
    return score


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        'branch_id': result.get('branch_id'),
        'branch_role': result.get('branch_role'),
        'search_mode': result.get('search_mode'),
        'status': result.get('status'),
        'outcome': result.get('outcome'),
        'recommendation': result.get('recommendation'),
        'score': result_score(result),
        'researcher_summary': result.get('researcher_summary'),
        'falsification_result': (result.get('research_assessment') or {}).get('falsification_result'),
        'overfit_assessment': (result.get('research_assessment') or {}).get('overfit_assessment'),
        'failure_signatures': as_list((result.get('evidence') or {}).get('failure_signatures')),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()

    rid = args.report_id
    plan_path = OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json'
    ledger_path = OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json'
    if not plan_path.exists():
        raise SystemExit(f'PROGRAM_SEARCH_MERGE_INVALID: missing plan {plan_path}')

    plan = load_json(plan_path)
    result_paths = sorted((OBJ / 'research_iteration_master').glob(f'search_branch_result__{rid}__*.json'))
    results = [load_json(path) for path in result_paths]
    summaries = [summarize_result(result) for result in results]
    summaries.sort(key=lambda row: row.get('score') or 0.0, reverse=True)

    audit_results = [row for row in summaries if row.get('branch_role') == 'audit']
    workflow_blocks = [
        row for row in summaries
        if row.get('recommendation') == 'repair_workflow_first'
        or row.get('outcome') == 'bug_found'
        or row.get('status') == 'blocked'
    ]
    usable = [
        row for row in summaries
        if row.get('recommendation') == 'use_branch_for_next_step3b'
        and row.get('status') == 'completed'
        and row.get('outcome') == 'improved'
    ]

    if not results:
        recommendation = 'await_branch_results'
        rationale = ['No branch results have been recorded yet. Do not modify Step3B.']
        selected_branch = None
    elif workflow_blocks:
        recommendation = 'repair_workflow_first'
        rationale = ['At least one branch found a workflow/evidence/data issue; repair this before formula search.']
        selected_branch = workflow_blocks[0].get('branch_id')
    elif usable:
        recommendation = 'needs_human_review_before_step3b'
        rationale = [
            'A branch is eligible for human review, but it cannot become canonical Step3B automatically.',
            'Step6 must compare it against baseline evidence and confirm thesis preservation before approval.',
        ]
        selected_branch = usable[0].get('branch_id')
    else:
        recommendation = 'continue_or_kill_by_step6_judgment'
        rationale = [
            'Recorded branches did not produce an approved improved candidate.',
            'Step6 should either refine the search plan or apply kill criteria from the research memo.',
        ]
        selected_branch = summaries[0].get('branch_id') if summaries else None

    merge = {
        'report_id': rid,
        'producer': 'program_search_engine_v1',
        'created_at_utc': utc_now(),
        'status': 'pending_human_review',
        'plan_path': str(plan_path),
        'ledger_path': str(ledger_path) if ledger_path.exists() else None,
        'branch_result_count': len(results),
        'recommendation': recommendation,
        'selected_branch_for_review': selected_branch,
        'rationale': rationale,
        'branch_summaries': summaries,
        'audit_summary': audit_results,
        'selection_protocol': plan.get('selection_protocol') or {},
        'hard_rule': 'This merge report is advisory. It must not update handoff_to_step3b or canonical code without explicit human approval.',
    }
    out = OBJ / 'research_iteration_master' / f'program_search_merge__{rid}.json'
    write_json(out, merge)


if __name__ == '__main__':
    main()
