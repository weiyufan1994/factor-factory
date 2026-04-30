#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJECTS = FACTORFORGE / 'objects'


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
    master_path = OBJECTS / 'factor_spec_master' / f'factor_spec_master__{rid}.json'
    handoff_path = OBJECTS / 'handoff' / f'handoff_to_step3__{rid}.json'
    checks = [
        check('factor_spec_master_exists', master_path.exists(), f'missing {master_path}'),
        check('handoff_to_step3_exists', handoff_path.exists(), f'missing {handoff_path}'),
    ]
    errors = []
    warnings = []
    if master_path.exists():
        master = json.loads(master_path.read_text(encoding='utf-8'))
        canonical = master.get('canonical_spec') or {}
        thesis = master.get('thesis') or {}
        math_review = master.get('math_discipline_review') or {}
        learning = master.get('learning_and_innovation') or {}
        research_contract = master.get('research_contract') or {}
        info_legality = str(math_review.get('information_set_legality') or '').lower()
        checks.extend([
            check('report_id_match', master.get('report_id') == rid, 'report_id mismatch'),
            check('canonical_formula_present', nonempty_str(canonical.get('formula_text')), 'canonical formula_text missing'),
            check('canonical_required_inputs_present', nonempty_list(canonical.get('required_inputs')), 'required_inputs missing'),
            check('canonical_operators_present', nonempty_list(canonical.get('operators')), 'operators missing'),
            check('thesis_alpha_thesis_present', nonempty_str(thesis.get('alpha_thesis')), 'thesis.alpha_thesis missing'),
            check('thesis_target_prediction_present', nonempty_str(thesis.get('target_prediction')), 'thesis.target_prediction missing'),
            check('thesis_economic_mechanism_present', nonempty_str(thesis.get('economic_mechanism')), 'thesis.economic_mechanism missing'),
            check('target_statistic_present', nonempty_str(math_review.get('target_statistic') or research_contract.get('target_statistic')), 'target_statistic missing'),
            check('economic_mechanism_present', nonempty_str(research_contract.get('economic_mechanism')), 'economic_mechanism missing'),
            check('expected_failure_modes_present', nonempty_list(research_contract.get('expected_failure_modes') or math_review.get('expected_failure_modes')), 'expected_failure_modes missing'),
            check('innovative_idea_seeds_present', nonempty_list(learning.get('innovative_idea_seeds') or research_contract.get('innovative_idea_seeds')), 'innovative_idea_seeds missing'),
            check('reuse_instruction_present', nonempty_list(learning.get('reuse_instruction_for_future_agents') or research_contract.get('reuse_instruction_for_future_agents')), 'reuse_instruction_for_future_agents missing'),
            check('similar_case_lessons_imported_present', nonempty_list(learning.get('similar_case_lessons_imported') or research_contract.get('similar_case_lessons_imported')), 'similar_case_lessons_imported missing'),
            check('information_set_not_illegal', 'illegal' not in info_legality and 'forward_reference' not in info_legality, f'information_set_legality blocks Step2 acceptance: {info_legality}', severity='WARN'),
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
