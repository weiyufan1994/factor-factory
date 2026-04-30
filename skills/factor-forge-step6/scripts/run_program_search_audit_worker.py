#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
LEGACY_FACTORFORGE = LEGACY_WORKSPACE / 'factorforge'
LEGACY_REPO = LEGACY_WORKSPACE / 'repos' / 'factor-factory'
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_FACTORFORGE if LEGACY_FACTORFORGE.exists() else REPO_ROOT))
OBJ = FF / 'objects'


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def nested(root: dict[str, Any], *keys: str) -> Any:
    cur: Any = root
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def has_key_recursive(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(has_key_recursive(item, target) for item in value.values())
    if isinstance(value, list):
        return any(has_key_recursive(item, target) for item in value)
    return False


def find_branch(plan: dict[str, Any], branch_id: str) -> dict[str, Any]:
    for branch in plan.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            return branch
    raise SystemExit(f'AUDIT_WORKER_INVALID: branch_id not found in plan: {branch_id}')


def path_candidates(raw: str | None) -> list[Path]:
    if not raw:
        return []
    raw = str(raw)
    out: list[Path] = []
    p = Path(raw).expanduser()
    out.append(p)
    if raw.startswith(str(LEGACY_FACTORFORGE)):
        out.append(FF / Path(raw).relative_to(LEGACY_FACTORFORGE))
    if raw.startswith(str(LEGACY_REPO)):
        out.append(REPO_ROOT / Path(raw).relative_to(LEGACY_REPO))
    if raw.startswith('factorforge/'):
        out.append(FF / raw.removeprefix('factorforge/'))
    if not p.is_absolute():
        out.append(FF / raw)
        out.append(REPO_ROOT / raw)
    # Preserve order while dropping duplicates.
    seen = set()
    uniq = []
    for candidate in out:
        key = str(candidate)
        if key not in seen:
            uniq.append(candidate)
            seen.add(key)
    return uniq


def resolve_existing_path(raw: str | None) -> tuple[bool, str | None, list[str], bool]:
    candidates = path_candidates(raw)
    for candidate in candidates:
        if candidate.exists():
            return True, str(candidate), [str(x) for x in candidates], False
    remote_absolute = bool(raw) and str(raw).startswith(str(LEGACY_WORKSPACE)) and not str(FF).startswith(str(LEGACY_WORKSPACE))
    return False, None, [str(x) for x in candidates], remote_absolute


def issue(severity: str, code: str, message: str, evidence: Any = None) -> dict[str, Any]:
    row = {
        'severity': severity,
        'code': code,
        'message': message,
    }
    if evidence is not None:
        row['evidence'] = evidence
    return row


def add_object_check(issues: list[dict[str, Any]], artifacts: list[str], label: str, path: Path, required: bool = True) -> dict[str, Any]:
    exists = path.exists()
    if exists:
        artifacts.append(str(path))
    elif required:
        issues.append(issue('error', f'MISSING_{label.upper()}', f'missing required object: {path}'))
    else:
        issues.append(issue('warn', f'MISSING_OPTIONAL_{label.upper()}', f'missing optional object: {path}'))
    return {'label': label, 'path': str(path), 'exists': exists, 'required': required}


def inspect_artifact_paths(paths: list[Any], issues: list[dict[str, Any]], artifacts: list[str], label: str) -> list[dict[str, Any]]:
    rows = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        exists, resolved, candidates, remote_absolute = resolve_existing_path(raw)
        rows.append({
            'raw': raw,
            'exists': exists,
            'resolved': resolved,
            'remote_absolute_not_local': remote_absolute,
        })
        if exists and resolved:
            artifacts.append(resolved)
        elif remote_absolute:
            issues.append(issue('warn', f'{label.upper()}_REMOTE_PATH_NOT_LOCAL', f'{label} path points to another runtime and cannot be verified locally', {'raw': raw, 'candidates': candidates[:3]}))
        else:
            issues.append(issue('error', f'{label.upper()}_MISSING_ARTIFACT', f'{label} artifact path is missing', {'raw': raw, 'candidates': candidates[:3]}))
    return rows


def inspect_backend_payloads(evaluation: dict[str, Any], issues: list[dict[str, Any]], artifacts: list[str]) -> list[dict[str, Any]]:
    rows = []
    for backend in evaluation.get('backend_summary') or []:
        if not isinstance(backend, dict):
            continue
        name = backend.get('backend')
        status = backend.get('status')
        payload_path = backend.get('payload_path')
        if status != 'success':
            issues.append(issue('error', 'BACKEND_NOT_SUCCESS', f'backend {name} status is {status}', backend))
        exists, resolved, candidates, remote_absolute = resolve_existing_path(payload_path)
        row = {
            'backend': name,
            'status': status,
            'payload_path': payload_path,
            'payload_exists': exists,
            'resolved_payload_path': resolved,
            'remote_absolute_not_local': remote_absolute,
        }
        if exists and resolved:
            artifacts.append(resolved)
            try:
                payload = load_json(Path(resolved))
                row['payload_status'] = payload.get('status')
                row['payload_backend'] = payload.get('backend')
                if payload.get('status') not in {None, 'success'} and status == 'success':
                    issues.append(issue('error', 'BACKEND_PAYLOAD_STATUS_CONFLICT', f'backend {name} summary says success but payload status is {payload.get("status")}', {'payload_path': resolved}))
            except Exception as exc:
                issues.append(issue('error', 'BACKEND_PAYLOAD_JSON_INVALID', f'backend {name} payload is not valid JSON: {exc}', {'payload_path': resolved}))
        elif remote_absolute:
            issues.append(issue('warn', 'BACKEND_PAYLOAD_REMOTE_PATH_NOT_LOCAL', f'backend {name} payload points to another runtime and cannot be verified locally', {'payload_path': payload_path, 'candidates': candidates[:3]}))
        else:
            issues.append(issue('error', 'BACKEND_PAYLOAD_MISSING', f'backend {name} payload is missing', {'payload_path': payload_path, 'candidates': candidates[:3]}))
        rows.append(row)
        inspect_artifact_paths(as_list(backend.get('artifact_paths')), issues, artifacts, f'{name}_artifact')
    return rows


def inspect_first_run_outputs(handoff4: dict[str, Any], issues: list[dict[str, Any]], artifacts: list[str]) -> dict[str, Any]:
    outputs = handoff4.get('first_run_outputs') or {}
    rows = inspect_artifact_paths(as_list(outputs.get('output_paths')), issues, artifacts, 'factor_values')
    meta_rows = inspect_artifact_paths(as_list(outputs.get('run_metadata_path')), issues, artifacts, 'run_metadata')
    status = outputs.get('status')
    if status not in {None, 'ready', 'success'}:
        issues.append(issue('error', 'FIRST_RUN_NOT_READY', f'first_run_outputs.status is {status}', outputs))
    return {'status': status, 'factor_value_paths': rows, 'run_metadata_paths': meta_rows}


def inspect_reference_object(ref: Any, directory: str, issues: list[dict[str, Any]], artifacts: list[str], label: str, required: bool = True) -> dict[str, Any]:
    if not isinstance(ref, str) or not ref.strip():
        if required:
            issues.append(issue('error', f'{label.upper()}_REF_MISSING', f'{label} ref missing'))
        return {'ref': ref, 'exists': False}
    path = OBJ / directory / ref
    return add_object_check(issues, artifacts, label, path, required=required)


def inspect_information_legality(iteration: dict[str, Any], issues: list[dict[str, Any]]) -> str:
    legality = nested(iteration, 'research_judgment', 'research_memo', 'math_discipline_review', 'information_set_legality')
    legality_text = str(legality or '')
    if not legality_text:
        issues.append(issue('warn', 'INFORMATION_SET_LEGALITY_MISSING', 'Step6 math_discipline_review.information_set_legality is missing'))
    elif legality_text.lower().startswith('illegal'):
        issues.append(issue('error', 'INFORMATION_SET_ILLEGAL', 'information_set_legality is illegal', legality_text))
    elif 'requires_researcher_confirmation' in legality_text:
        issues.append(issue('warn', 'INFORMATION_SET_REQUIRES_CONFIRMATION', 'information set still requires researcher confirmation', legality_text))
    return legality_text


def summarize_issues(issues: list[dict[str, Any]]) -> tuple[str, str, str]:
    errors = [row for row in issues if row.get('severity') == 'error']
    warnings = [row for row in issues if row.get('severity') == 'warn']
    if errors:
        return 'blocked', 'bug_found', 'repair_workflow_first'
    if warnings:
        return 'completed', 'needs_more_evidence', 'keep_exploring'
    return 'completed', 'not_improved', 'keep_exploring'


def update_ledger(ledger_path: Path, branch_id: str, result_path: Path, status: str, outcome: str) -> None:
    if not ledger_path.exists():
        return
    ledger = load_json(ledger_path)
    for branch in ledger.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            branch['status'] = status
            branch['outcome'] = outcome
            branch['last_event'] = 'audit_worker_result_recorded'
            branch['result_path'] = str(result_path)
            branch['updated_at_utc'] = utc_now()
            break
    write_json(ledger_path, ledger)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--branch-id', default='audit_evidence_and_thesis')
    ap.add_argument('--allow-unapproved', action='store_true', help='Allow audit smoke runs without an approved branch/taskbook.')
    args = ap.parse_args()

    rid = args.report_id
    branch_id = args.branch_id
    plan_path = OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json'
    ledger_path = OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json'
    taskbook_path = OBJ / 'research_iteration_master' / f'search_branch_taskbook__{rid}__{branch_id}.json'
    if not plan_path.exists():
        raise SystemExit(f'AUDIT_WORKER_INVALID: missing program search plan {plan_path}')
    plan = load_json(plan_path)
    branch = find_branch(plan, branch_id)
    if branch.get('branch_role') != 'audit':
        raise SystemExit(f'AUDIT_WORKER_INVALID: branch {branch_id} is not an audit branch')
    if not args.allow_unapproved and ((branch.get('approval') or {}).get('status') != 'approved') and not taskbook_path.exists():
        raise SystemExit('AUDIT_WORKER_APPROVAL_REQUIRED: approve and prepare the audit branch, or pass --allow-unapproved for smoke/audit-only diagnostics')

    issues: list[dict[str, Any]] = []
    artifacts: list[str] = []
    object_checks: list[dict[str, Any]] = []

    paths = {
        'research_iteration_master': OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json',
        'factor_case_master': OBJ / 'factor_case_master' / f'factor_case_master__{rid}.json',
        'factor_evaluation': OBJ / 'validation' / f'factor_evaluation__{rid}.json',
        'factor_run_master': OBJ / 'factor_run_master' / f'factor_run_master__{rid}.json',
        'handoff_to_step4': OBJ / 'handoff' / f'handoff_to_step4__{rid}.json',
        'handoff_to_step5': OBJ / 'handoff' / f'handoff_to_step5__{rid}.json',
        'handoff_to_step6': OBJ / 'handoff' / f'handoff_to_step6__{rid}.json',
    }
    for label, path in paths.items():
        object_checks.append(add_object_check(issues, artifacts, label, path, required=(label != 'factor_run_master')))

    iteration = load_json(paths['research_iteration_master']) if paths['research_iteration_master'].exists() else {}
    case = load_json(paths['factor_case_master']) if paths['factor_case_master'].exists() else {}
    evaluation = load_json(paths['factor_evaluation']) if paths['factor_evaluation'].exists() else {}
    handoff4 = load_json(paths['handoff_to_step4']) if paths['handoff_to_step4'].exists() else {}
    handoff5 = load_json(paths['handoff_to_step5']) if paths['handoff_to_step5'].exists() else {}
    handoff6 = load_json(paths['handoff_to_step6']) if paths['handoff_to_step6'].exists() else {}

    if case.get('final_status') not in {None, 'validated'}:
        issues.append(issue('error', 'STEP5_CASE_NOT_VALIDATED', f'factor_case_master.final_status is {case.get("final_status")}'))
    if evaluation.get('evaluation_status') not in {None, 'validated'}:
        issues.append(issue('error', 'FACTOR_EVALUATION_NOT_VALIDATED', f'factor_evaluation.evaluation_status is {evaluation.get("evaluation_status")}'))
    if evaluation.get('artifact_ready') is not True:
        issues.append(issue('error', 'FACTOR_EVALUATION_ARTIFACT_NOT_READY', 'factor_evaluation.artifact_ready is not true', evaluation.get('artifact_ready')))
    if evaluation.get('run_status') not in {None, 'success', 'partial'}:
        issues.append(issue('error', 'FACTOR_EVALUATION_RUN_STATUS_BAD', f'factor_evaluation.run_status is {evaluation.get("run_status")}'))

    backend_rows = inspect_backend_payloads(evaluation, issues, artifacts) if evaluation else []
    first_run = inspect_first_run_outputs(handoff4, issues, artifacts) if handoff4 else {}
    information_set_legality = inspect_information_legality(iteration, issues)

    if has_key_recursive(iteration, 'dd_view_edge_trade'):
        issues.append(issue('warn', 'LEGACY_DD_VIEW_EDGE_TRADE_PRESENT', 'Step6 object still contains dd_view_edge_trade; this belongs outside Factor Forge Step6.'))
    if handoff4:
        inspect_reference_object(handoff4.get('data_prep_master_ref'), 'data_prep_master', issues, artifacts, 'data_prep_master')
        inspect_reference_object(handoff4.get('qlib_adapter_config_ref'), 'qlib_adapter_config', issues, artifacts, 'qlib_adapter_config')
        inspect_reference_object(handoff4.get('implementation_plan_master_ref'), 'implementation_plan_master', issues, artifacts, 'implementation_plan_master')
        inspect_reference_object(handoff4.get('factor_spec_master_ref'), 'factor_spec_master', issues, artifacts, 'factor_spec_master')
        inspect_artifact_paths([handoff4.get('factor_impl_ref') or handoff4.get('factor_impl_stub_ref')], issues, artifacts, 'factor_impl')

    if handoff5 and handoff6 and handoff5.get('report_id') != handoff6.get('report_id'):
        issues.append(issue('error', 'HANDOFF_REPORT_ID_MISMATCH', 'handoff_to_step5 and handoff_to_step6 report_id mismatch'))

    status, outcome, recommendation = summarize_issues(issues)
    errors = [row for row in issues if row.get('severity') == 'error']
    warnings = [row for row in issues if row.get('severity') == 'warn']
    summary = (
        f'Audit checked Factor Forge evidence chain for {rid}: '
        f'{len(errors)} blocking issue(s), {len(warnings)} warning(s), {len(artifacts)} locally verified artifact/object path(s).'
    )
    if errors:
        falsification_result = 'audit_falsified_search_prerequisites_until_workflow_is_repaired'
        overfit_assessment = 'not_applicable_because_evidence_chain_has_blocking_issues'
    elif warnings:
        falsification_result = 'audit_did_not_find_blocking_bug_but_found_warnings_requiring_researcher_confirmation'
        overfit_assessment = 'not_assessable_from_audit_only; downstream branch must still test overfit'
    else:
        falsification_result = 'audit_did_not_falsify_search_prerequisites'
        overfit_assessment = 'audit_only_no_algorithmic_overfit_detected; downstream branch must still validate OOS'

    result = {
        'report_id': rid,
        'branch_id': branch_id,
        'parent_plan_path': str(plan_path),
        'branch_role': branch.get('branch_role'),
        'search_mode': branch.get('search_mode'),
        'status': status,
        'outcome': outcome,
        'recommendation': recommendation,
        'created_at_utc': utc_now(),
        'research_question': branch.get('research_question'),
        'branch_hypothesis': branch.get('hypothesis'),
        'return_source_target': branch.get('return_source_target'),
        'market_structure_hypothesis': branch.get('market_structure_hypothesis'),
        'knowledge_priors': branch.get('knowledge_priors'),
        'researcher_summary': summary,
        'research_assessment': {
            'return_source_preserved_or_challenged': 'audit_preserves_step6_return_source_hypothesis_unless_evidence_chain_is_blocked',
            'market_structure_lesson': 'audit_worker checks whether evidence is clean enough before market-structure or formula search.',
            'knowledge_lesson': 'workflow/data/evidence bugs must be repaired before algorithmic search; failed audits are useful anti-data-mining priors.',
            'anti_pattern_observed': '; '.join(row['code'] for row in errors[:5]) if errors else None,
            'overfit_assessment': overfit_assessment,
            'falsification_result': falsification_result,
        },
        'evidence': {
            'metric_delta': {},
            'step4_artifacts': sorted(set(artifacts)),
            'validator_results': {
                'object_checks': object_checks,
                'backend_payloads': backend_rows,
                'first_run_outputs': first_run,
                'information_set_legality': information_set_legality,
            },
            'failure_signatures': [row['code'] for row in errors],
            'warnings': [row['code'] for row in warnings],
            'issues': issues,
            'notes': [
                'Audit worker does not mutate data, run optimization, or change Step3B.',
                'Remote absolute paths from another runtime are warnings unless current runtime can resolve them.',
            ],
        },
        'selection_protocol_snapshot': plan.get('selection_protocol') or {},
        'human_approval_required_before_canonicalization': True,
        'producer': 'program_search_audit_worker_v1',
    }
    out = OBJ / 'research_iteration_master' / f'search_branch_result__{rid}__{branch_id}.json'
    write_json(out, result)
    update_ledger(ledger_path, branch_id, out, status, outcome)
    print(f'RESULT: {status.upper()} {outcome} {recommendation}')
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
