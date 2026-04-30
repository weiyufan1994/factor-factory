#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'


def check(name: str, condition: bool, error: str | None = None, severity: str = 'BLOCK'):
    status = 'PASS' if condition else severity
    return {'name': name, 'ok': bool(condition), 'status': status, 'severity': severity, 'error': None if condition else error}


def nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value) -> bool:
    return isinstance(value, list) and bool(value)


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
            check('similar_case_lessons_imported_present', nonempty_list(discipline.get('similar_case_lessons_imported') or learning.get('similar_case_lessons_imported')), 'similar_case_lessons_imported missing'),
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
