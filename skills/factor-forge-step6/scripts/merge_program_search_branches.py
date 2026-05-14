#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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
    if result.get('recommended_next_action') == 'consider_revision':
        score += 1.5
    if result.get('recommended_next_action') in {'reject_branch', 'kill_factor'}:
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
        'recommended_next_action': result.get('recommended_next_action'),
        'score': result_score(result),
        'researcher_summary': result.get('researcher_summary'),
        'falsification_result': (result.get('research_assessment') or {}).get('falsification_result'),
        'overfit_assessment': (result.get('research_assessment') or {}).get('overfit_assessment'),
        'failure_signatures': as_list((result.get('evidence') or {}).get('failure_signatures')),
    }


def validate_branch_results_or_block(rid: str) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name('validate_search_branch_result.py')
    cmd = [sys.executable, str(script), '--report-id', rid]
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(FF)
    return subprocess.run(cmd, text=True, capture_output=True, env=env)


def forbidden_writeback_paths(rid: str) -> list[Path]:
    return [
        OBJ / 'handoff' / f'handoff_to_step3b__{rid}.json',
        FF / 'generated_code' / rid,
        OBJ / 'factor_library_official' / f'factor_record__{rid}.json',
        OBJ / 'implementation_plan_master' / f'implementation_plan_master__{rid}.json',
        OBJ / 'research_iteration_master' / f'revision_proposal__{rid}.json',
    ]


def block_forbidden_writebacks(rid: str, paths: list[Path]) -> None:
    diagnostic = {
        'report_id': rid,
        'block_reason': 'forbidden_writeback_present',
        'forbidden_paths': [str(path) for path in paths],
        'merge_written': False,
        'created_at_utc': utc_now(),
    }
    diagnostic_path = OBJ / 'validation' / f'program_search_merge_prewrite_block__{rid}.json'
    write_json(diagnostic_path, diagnostic)
    raise SystemExit(
        'BLOCK_PROGRAM_SEARCH_FORBIDDEN_WRITEBACK_PRESENT: '
        + ', '.join(str(path) for path in paths)
    )


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
    forbidden_paths = [path for path in forbidden_writeback_paths(rid) if path.exists()]
    if forbidden_paths:
        block_forbidden_writebacks(rid, forbidden_paths)

    if result_paths:
        validation_proc = validate_branch_results_or_block(rid)
        if validation_proc.returncode != 0:
            merge = {
                'report_id': rid,
                'producer': 'program_search_engine_v1',
                'created_at_utc': utc_now(),
                'merge_status': 'blocked',
                'status': 'blocked',
                'plan_path': str(plan_path),
                'ledger_path': str(ledger_path) if ledger_path.exists() else None,
                'branch_result_count': len(result_paths),
                'recommended_step3b_action': 'rerun_audit',
                'recommendation': 'rerun_audit',
                'selected_branch_for_review': None,
                'branch_results_used': [str(path) for path in result_paths],
                'rationale': ['At least one branch result failed advisory-result validation; do not merge or prepare a Step3B action.'],
                'recommended_research_direction': 'Repair invalid branch result provenance or rerun an audit branch before considering any revision.',
                'branch_summaries': [],
                'audit_summary': [],
                'selection_protocol': plan.get('selection_protocol') or {},
                'advisory_only': True,
                'canonical_write_permission': False,
                'requires_human_approval_before_step3b_change': True,
                'forbidden_actions_confirmed': [
                    'no_portfolio_expression_repair',
                    'no_short_leg_adoption',
                    'no_decile_trading',
                    'no_shared_clean_data_mutation',
                ],
                'why_not_auto_apply': 'Program search merge is blocked because branch results are invalid; canonical writes remain forbidden.',
                'validation_stdout_tail': validation_proc.stdout[-5000:],
                'validation_stderr_tail': validation_proc.stderr[-5000:],
                'hard_rule': 'This merge report is advisory. It must not update handoff_to_step3b or canonical code without explicit human approval.',
            }
            out = OBJ / 'research_iteration_master' / f'program_search_merge__{rid}.json'
            write_json(out, merge)
            raise SystemExit('PROGRAM_SEARCH_MERGE_BLOCKED: branch result validation failed')

    results = [load_json(path) for path in result_paths]
    summaries = [summarize_result(result) for result in results]
    summaries.sort(key=lambda row: row.get('score') or 0.0, reverse=True)

    audit_results = [row for row in summaries if row.get('branch_role') == 'audit']
    workflow_blocks = [
        row for row in summaries
        if row.get('recommended_next_action') == 'needs_human_review' and row.get('outcome') == 'bug_found'
        or row.get('outcome') == 'bug_found'
        or row.get('status') == 'blocked'
    ]
    usable = [
        row for row in summaries
        if row.get('recommended_next_action') == 'consider_revision'
        and row.get('status') == 'completed'
        and row.get('outcome') == 'improved'
    ]

    if not results:
        merge_status = 'needs_more_evidence'
        recommendation = 'none'
        rationale = ['No branch results have been recorded yet. Do not modify Step3B.']
        selected_branch = None
    elif workflow_blocks:
        merge_status = 'blocked'
        recommendation = 'rerun_audit'
        rationale = ['At least one branch found a workflow/evidence/data issue; repair this before formula search.']
        selected_branch = workflow_blocks[0].get('branch_id')
    elif usable:
        merge_status = 'advisory_completed'
        recommendation = 'prepare_human_review_patch'
        rationale = [
            'A branch is eligible for human review, but it cannot become canonical Step3B automatically.',
            'Step6 must compare it against baseline evidence and confirm thesis preservation before approval.',
        ]
        selected_branch = usable[0].get('branch_id')
    else:
        merge_status = 'needs_more_evidence'
        recommendation = 'kill_factor' if summaries and summaries[0].get('recommended_next_action') == 'kill_factor' else 'none'
        rationale = [
            'Recorded branches did not produce an approved improved candidate.',
            'Step6 should either refine the search plan or apply kill criteria from the research memo.',
        ]
        selected_branch = summaries[0].get('branch_id') if summaries else None

    merge = {
        'report_id': rid,
        'producer': 'program_search_engine_v1',
        'created_at_utc': utc_now(),
        'merge_status': merge_status,
        'status': merge_status,
        'plan_path': str(plan_path),
        'ledger_path': str(ledger_path) if ledger_path.exists() else None,
        'branch_result_count': len(results),
        'recommended_step3b_action': recommendation,
        'recommendation': recommendation,
        'selected_branch_for_review': selected_branch,
        'branch_results_used': [str(path) for path in result_paths],
        'rationale': rationale,
        'recommended_research_direction': '; '.join(rationale),
        'branch_summaries': summaries,
        'audit_summary': audit_results,
        'selection_protocol': plan.get('selection_protocol') or {},
        'advisory_only': True,
        'canonical_write_permission': False,
        'requires_human_approval_before_step3b_change': True,
        'forbidden_actions_confirmed': [
            'no_portfolio_expression_repair',
            'no_short_leg_adoption',
            'no_decile_trading',
            'no_shared_clean_data_mutation',
        ],
        'why_not_auto_apply': 'Program search branch results are advisory; canonical Step3B changes require separate human review and an explicit approved workflow.',
        'hard_rule': 'This merge report is advisory. It must not update handoff_to_step3b or canonical code without explicit human approval.',
    }
    out = OBJ / 'research_iteration_master' / f'program_search_merge__{rid}.json'
    write_json(out, merge)


if __name__ == '__main__':
    main()
