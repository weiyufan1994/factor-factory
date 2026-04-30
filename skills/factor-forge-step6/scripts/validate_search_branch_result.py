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


def validate_one(path: Path, rid: str, branch_id: str | None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [check(f'{path.name}_exists', path.exists(), f'missing {path}')]
    if not path.exists():
        return checks
    result = load_json(path)
    assessment = result.get('research_assessment') or {}
    evidence = result.get('evidence') or {}
    checks.extend([
        check(f'{path.name}_report_id_match', result.get('report_id') == rid, 'report_id mismatch'),
        check(f'{path.name}_branch_id_match', branch_id is None or result.get('branch_id') == branch_id, 'branch_id mismatch'),
        check(f'{path.name}_status_present', result.get('status') in {'completed', 'failed', 'killed', 'blocked', 'inconclusive'}, 'invalid status'),
        check(f'{path.name}_outcome_present', result.get('outcome') in {'improved', 'not_improved', 'bug_found', 'thesis_rejected', 'needs_more_evidence', 'inconclusive'}, 'invalid outcome'),
        check(f'{path.name}_recommendation_present', result.get('recommendation') in {'use_branch_for_next_step3b', 'keep_exploring', 'kill_branch', 'repair_workflow_first', 'needs_human_review'}, 'invalid recommendation'),
        check(f'{path.name}_research_question_present', nonempty_str(result.get('research_question')), 'research_question missing'),
        check(f'{path.name}_hypothesis_present', nonempty_str(result.get('branch_hypothesis')), 'branch_hypothesis missing'),
        check(f'{path.name}_return_source_present', nonempty_str(result.get('return_source_target')), 'return_source_target missing'),
        check(f'{path.name}_market_structure_present', isinstance(result.get('market_structure_hypothesis'), dict) and nonempty_str((result.get('market_structure_hypothesis') or {}).get('hypothesis')), 'market_structure_hypothesis missing'),
        check(f'{path.name}_knowledge_priors_present', isinstance(result.get('knowledge_priors'), dict) and bool(result.get('knowledge_priors')), 'knowledge_priors missing'),
        check(f'{path.name}_summary_present', nonempty_str(result.get('researcher_summary')), 'researcher_summary missing'),
        check(f'{path.name}_assessment_present', isinstance(assessment, dict) and bool(assessment), 'research_assessment missing'),
        check(f'{path.name}_falsification_result_present', nonempty_str(assessment.get('falsification_result')) and assessment.get('falsification_result') != 'not_assessed', 'falsification_result must be assessed'),
        check(f'{path.name}_overfit_assessment_present', nonempty_str(assessment.get('overfit_assessment')) and assessment.get('overfit_assessment') != 'not_assessed', 'overfit_assessment must be assessed'),
        check(f'{path.name}_evidence_present', isinstance(evidence, dict) and bool(evidence), 'evidence missing'),
        check(
            f'{path.name}_evidence_or_failure_present',
            bool(evidence.get('metric_delta')) or nonempty_list(evidence.get('step4_artifacts')) or nonempty_list(evidence.get('failure_signatures')),
            'branch result must include metric_delta, artifacts, or failure signatures',
        ),
        check(f'{path.name}_approval_required', result.get('human_approval_required_before_canonicalization') is True, 'human approval must be required before canonicalization'),
    ])
    if result.get('recommendation') == 'use_branch_for_next_step3b':
        checks.append(check(
            f'{path.name}_use_branch_requires_completed_or_review',
            result.get('status') == 'completed' and result.get('outcome') == 'improved',
            'use_branch_for_next_step3b requires completed/improved branch',
        ))
        checks.append(check(
            f'{path.name}_use_branch_requires_artifacts',
            nonempty_list(evidence.get('step4_artifacts')),
            'use_branch_for_next_step3b requires Step4 artifacts or equivalent evidence',
        ))
    return checks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--branch-id', default=None)
    args = ap.parse_args()

    rid = args.report_id
    if args.branch_id:
        paths = [OBJ / 'research_iteration_master' / f'search_branch_result__{rid}__{args.branch_id}.json']
    else:
        paths = sorted((OBJ / 'research_iteration_master').glob(f'search_branch_result__{rid}__*.json'))
        if not paths:
            paths = [OBJ / 'research_iteration_master' / f'search_branch_result__{rid}__<branch_id>.json']

    checks: list[dict[str, Any]] = []
    for path in paths:
        checks.extend(validate_one(path, rid, args.branch_id))

    has_block = any(item['status'] == 'BLOCK' for item in checks)
    has_warn = any(item['status'] == 'WARN' for item in checks)
    result = 'BLOCK' if has_block else 'WARN' if has_warn else 'PASS'
    report = {'report_id': rid, 'branch_id': args.branch_id, 'result': result, 'checks': checks}
    out = OBJ / 'validation' / f'search_branch_result_validation__{rid}{("__" + args.branch_id) if args.branch_id else ""}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {out}')
    print(f'RESULT: {result}')
    if has_block:
        sys.exit(1)


if __name__ == '__main__':
    main()
