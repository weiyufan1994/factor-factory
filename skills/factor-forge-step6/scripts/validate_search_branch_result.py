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
REQUIRED_HARD_GUARDS = {
    'no_portfolio_expression_repair',
    'no_short_leg_adoption',
    'no_decile_trading',
    'no_shared_clean_data_mutation',
}
FORBIDDEN_TERMS = [
    'portfolio expression',
    'portfolio',
    'rebalance',
    'short leg',
    'short-leg',
    'short_side',
    'short side',
    'long-short',
    'long short',
    'decile trading',
    'buy decile',
    'sell decile',
    'shared clean data',
    'clean data mutation',
    'mutate clean data',
]
ADOPTION_CLAIM_TERMS = ['adopted', 'applied', 'promoted', 'official']
SKIP_SCAN_KEYS = {
    'forbidden_actions_confirmed',
    'hard_guards',
    'forbidden_search',
    'selection_protocol_snapshot',
    'search_policy_decision_source',
}


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


def load_optional(path: Path) -> dict[str, Any]:
    return load_json(path) if path.exists() else {}


def collect_text_hits(value: Any, terms: list[str], path: str = 'result') -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SKIP_SCAN_KEYS:
                continue
            hits.extend(collect_text_hits(child, terms, f'{path}.{key}'))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            hits.extend(collect_text_hits(child, terms, f'{path}[{idx}]'))
    elif isinstance(value, str):
        lowered = value.lower()
        for term in terms:
            if term in lowered:
                hits.append({'path': path, 'pattern': term})
    return hits


def path_outside_allowed(raw: Any, allowed: list[str], ff_root: Path) -> list[str]:
    offenders: list[str] = []
    if not isinstance(raw, str) or not raw.strip():
        return offenders
    if not (raw.startswith('/') or raw.startswith('research_branches/') or raw.startswith('objects/')):
        return offenders
    path = Path(raw)
    if not path.is_absolute():
        path = ff_root / path
    resolved = str(path.resolve())
    allowed_resolved = []
    for item in allowed:
        p = Path(item)
        if not p.is_absolute():
            p = ff_root / p
        allowed_resolved.append(str(p.resolve()))
    if allowed_resolved and not any(resolved == base or resolved.startswith(base + os.sep) for base in allowed_resolved):
        offenders.append(raw)
    return offenders


def collect_path_scope_violations(value: Any, allowed: list[str], ff_root: Path) -> list[str]:
    offenders: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            offenders.extend(collect_path_scope_violations(child, allowed, ff_root))
    elif isinstance(value, list):
        for child in value:
            offenders.extend(collect_path_scope_violations(child, allowed, ff_root))
    elif isinstance(value, str):
        offenders.extend(path_outside_allowed(value, allowed, ff_root))
    return offenders


def validate_one(path: Path, rid: str, branch_id: str | None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [check(f'{path.name}_exists', path.exists(), f'missing {path}')]
    if not path.exists():
        return checks
    result = load_json(path)
    assessment = result.get('research_assessment') or {}
    evidence = result.get('evidence') or {}
    plan_path = OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json'
    approval_path = OBJ / 'research_iteration_master' / f'search_branch_approval__{rid}__{result.get("branch_id")}.json'
    manifest_path = FF / 'research_branches' / rid / str(result.get('branch_id')) / 'branch_manifest.json'
    plan = load_optional(plan_path)
    approval = load_optional(approval_path)
    manifest = load_optional(manifest_path)
    plan_branch = {}
    for branch in plan.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == result.get('branch_id'):
            plan_branch = branch
            break
    forbidden_hits = collect_text_hits(result, FORBIDDEN_TERMS)
    adoption_hits = collect_text_hits(result, ADOPTION_CLAIM_TERMS)
    canonical_reference_surface = {
        'proposed_expression_change': result.get('proposed_expression_change'),
        'proposed_step3b_patch': result.get('proposed_step3b_patch'),
        'branch_output_paths': result.get('branch_output_paths'),
        'worker_output_paths': result.get('worker_output_paths'),
        'researcher_summary': result.get('researcher_summary'),
        'research_assessment_text': result.get('research_assessment_text'),
    }
    forbidden_scope_hits = [
        hit for hit in collect_text_hits(canonical_reference_surface, [
            f'generated_code/{rid}',
            'handoff_to_step3b',
            'objects/factor_library_official',
            'data/clean',
            'objects/implementation_plan_master',
        ])
    ]
    allowed_write_scope = manifest.get('allowed_write_scope') or []
    scope_violations = collect_path_scope_violations(result.get('branch_output_paths') or result.get('worker_output_paths') or [], allowed_write_scope, FF)
    guards = set(result.get('forbidden_actions_confirmed') or [])
    checks.extend([
        check(f'{path.name}_report_id_match', result.get('report_id') == rid, 'report_id mismatch'),
        check(f'{path.name}_branch_id_match', branch_id is None or result.get('branch_id') == branch_id, 'branch_id mismatch'),
        check(f'{path.name}_approval_exists', approval_path.exists(), f'missing approval {approval_path}'),
        check(f'{path.name}_approval_approved', approval.get('approval_status') == 'approved', 'branch result requires approved branch'),
        check(f'{path.name}_prepared_manifest_exists', manifest_path.exists(), f'missing prepared manifest {manifest_path}'),
        check(f'{path.name}_prepared_manifest_status', manifest.get('branch_status') == 'prepared', 'prepared manifest branch_status must be prepared'),
        check(f'{path.name}_branch_role_matches_plan', not plan_branch or result.get('branch_role') == plan_branch.get('branch_role'), 'branch_role mismatch vs source plan'),
        check(f'{path.name}_search_mode_matches_plan', not plan_branch or result.get('search_mode') == plan_branch.get('search_mode'), 'search_mode mismatch vs source plan'),
        check(f'{path.name}_status_present', (result.get('result_status') or result.get('status')) in {'completed', 'failed', 'blocked'}, 'invalid result_status'),
        check(f'{path.name}_outcome_present', result.get('outcome') in {'improved', 'not_improved', 'bug_found', 'thesis_rejected', 'needs_more_evidence', 'inconclusive'}, 'invalid outcome'),
        check(f'{path.name}_recommendation_present', result.get('recommended_next_action') in {'consider_revision', 'reject_branch', 'needs_human_review', 'kill_factor'}, 'invalid recommended_next_action'),
        check(f'{path.name}_advisory_only', result.get('advisory_only') is True, 'branch result must be advisory_only=true'),
        check(f'{path.name}_no_canonical_write_permission', result.get('canonical_write_permission') is False, 'canonical_write_permission must be false'),
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
            bool(evidence.get('metric_delta')) or nonempty_list(evidence.get('step4_artifacts')) or nonempty_str(result.get('evidence_or_failure_signature')) or nonempty_list(evidence.get('failure_signatures')),
            'branch result must include metric_delta, artifacts, or failure signatures',
        ),
        check(f'{path.name}_approval_required', result.get('human_approval_required_before_canonicalization') is True, 'human approval must be required before canonicalization'),
        check(f'{path.name}_code_change_approval_required', result.get('requires_human_approval_for_any_code_change') is True, 'code changes must require human approval'),
        check(f'{path.name}_proposed_patch_not_auto_apply', result.get('proposed_step3b_patch') is None or result.get('proposed_step3b_patch') == '', 'proposed_step3b_patch must be null/advisory, not an applied patch'),
        check(f'{path.name}_forbidden_actions_confirmed', REQUIRED_HARD_GUARDS.issubset(guards), f'forbidden_actions_confirmed must include {sorted(REQUIRED_HARD_GUARDS)}'),
        check(f'{path.name}_write_scope_observed', result.get('write_scope_observed') is True, 'write_scope_observed must be true'),
        check(f'{path.name}_no_forbidden_text', not forbidden_hits, f'forbidden text in branch result: {forbidden_hits}'),
        check(f'{path.name}_no_adoption_claim', not adoption_hits, f'branch result cannot claim adopted/applied/promoted/official: {adoption_hits}'),
        check(f'{path.name}_no_canonical_reference', not forbidden_scope_hits, f'branch result references canonical write target: {forbidden_scope_hits}'),
        check(f'{path.name}_outputs_within_allowed_scope', not scope_violations, f'branch output outside allowed scope: {scope_violations}'),
    ])
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
