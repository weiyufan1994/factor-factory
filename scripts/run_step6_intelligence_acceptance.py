#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.risk.drawdown_geometry import drawdown_geometry


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def tail(text: str, limit: int = 5000) -> str:
    return text[-limit:] if len(text) > limit else text


def snapshot_repo_canonical() -> set[str]:
    roots = [
        REPO_ROOT / 'objects',
        REPO_ROOT / 'runs',
        REPO_ROOT / 'evaluations',
        REPO_ROOT / 'generated_code',
        REPO_ROOT / 'archive',
        REPO_ROOT / 'factorforge',
        REPO_ROOT / 'data' / 'clean',
    ]
    files: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if path.is_file():
                files.add(str(path.relative_to(REPO_ROOT)))
    return files


def canonical_pollution(before: set[str]) -> dict[str, Any]:
    after = snapshot_repo_canonical()
    added = [
        item for item in sorted(after - before)
        if 'STEP6_INTEL_' in item or 'factorforge_step6_intelligence' in item
    ]
    return {'polluted': bool(added), 'new_files': added}


def run_cmd(cmd: list[str], *, root: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if root is not None:
        env['FACTORFORGE_ROOT'] = str(root)
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)


def run_smoke(root: Path, fresh: bool) -> dict[str, Any]:
    cmd = [
        sys.executable,
        'scripts/run_step6_intelligence_smoke.py',
        '--root',
        str(root),
    ]
    if fresh:
        cmd.append('--fresh')
    proc = run_cmd(cmd, root=root)
    summary_path = root / 'step6_intelligence_smoke_summary.json'
    summary = read_json(summary_path) if summary_path.exists() else {}
    return {
        'command': cmd,
        'rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'summary_path': str(summary_path),
        'summary_exists': summary_path.exists(),
        'summary': summary,
    }


def case_by_name(smoke: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get('case'): item
        for item in smoke.get('cases') or []
        if isinstance(item, dict) and item.get('case')
    }


def pass_fail(ok: bool) -> str:
    return 'PASS' if ok else 'FAIL'


def phase(status_cases: list[dict[str, Any]]) -> dict[str, Any]:
    ok = all(bool(item.get('ok')) for item in status_cases)
    return {'status': pass_fail(ok), 'cases': status_cases}


def validate_step6_case(root: Path, report_id: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/validate_step6.py',
        '--report-id',
        report_id,
    ]
    proc = run_cmd(cmd, root=root)
    return {
        'command': cmd,
        'rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': proc.returncode == 0,
    }


def summarize_ab(root: Path, cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    valid = cases.get('valid_supportive_evidence') or {}
    valid_report = valid.get('report_id') or 'STEP6_INTEL_VALID_SUPPORTIVE_EVIDENCE'
    validate_result = validate_step6_case(root, valid_report)
    blocked = ['all_backends_skipped', 'missing_long_side_metrics', 'unknown_mechanism_cannot_promote']
    rows = [
        {
            'case': 'valid_supportive_evidence',
            'rc': valid.get('rc'),
            'research_iteration_master_exists': bool((valid.get('produced_files') or {}).get('research_iteration_master')),
            'factor_library_all_exists': bool((valid.get('produced_files') or {}).get('factor_library_all')),
            'knowledge_record_exists': bool((valid.get('produced_files') or {}).get('knowledge_record')),
            'validate_step6': validate_result,
            'ok': bool(valid.get('ok'))
            and valid.get('rc') == 0
            and bool((valid.get('produced_files') or {}).get('research_iteration_master'))
            and bool((valid.get('produced_files') or {}).get('factor_library_all'))
            and bool((valid.get('produced_files') or {}).get('knowledge_record'))
            and validate_result['ok'],
        }
    ]
    for name in blocked:
        row = cases.get(name) or {}
        rows.append({
            'case': name,
            'rc': row.get('rc'),
            'token_present': row.get('token_present'),
            'prewrite_diagnostic_exists': bool((row.get('prewrite_diagnostic') or {}).get('exists')),
            'forbidden_writebacks_absent': row.get('forbidden_writebacks_absent'),
            'ok': bool(row.get('ok'))
            and row.get('rc') != 0
            and row.get('token_present') is True
            and bool((row.get('prewrite_diagnostic') or {}).get('exists'))
            and row.get('forbidden_writebacks_absent') is True,
        })
    return phase(rows)


def summarize_c(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    pvm = cases.get('price_volume_correlation_mechanism') or {}
    pvm_ri = pvm.get('research_intelligence') or {}
    rows.append({
        'case': 'price_volume_correlation_mechanism',
        'rc': pvm.get('rc'),
        'factor_family': pvm_ri.get('factor_family'),
        'return_source': pvm_ri.get('return_source'),
        'mechanism_fit': pvm_ri.get('mechanism_fit'),
        'official_exists': bool((pvm.get('produced_files') or {}).get('factor_library_official')),
        'ok': bool(pvm.get('ok'))
        and pvm.get('rc') == 0
        and pvm_ri.get('factor_family') == 'price_volume_correlation'
        and pvm_ri.get('return_source') == 'behavioral_microstructure'
        and pvm_ri.get('mechanism_fit') == 'partial'
        and not bool((pvm.get('produced_files') or {}).get('factor_library_official')),
    })
    cold = cases.get('cold_start_knowledge_gap') or {}
    cold_ri = cold.get('research_intelligence') or {}
    rows.append({
        'case': 'cold_start_knowledge_gap',
        'rc': cold.get('rc'),
        'knowledge_gap': cold_ri.get('knowledge_gap'),
        'mechanism_fit': cold_ri.get('mechanism_fit'),
        'official_exists': bool((cold.get('produced_files') or {}).get('factor_library_official')),
        'ok': bool(cold.get('ok'))
        and cold.get('rc') == 0
        and bool(cold_ri.get('knowledge_gap'))
        and cold_ri.get('mechanism_fit') == 'partial'
        and not bool((cold.get('produced_files') or {}).get('factor_library_official')),
    })
    same = cases.get('same_factor_cross_identity_negative') or {}
    rows.append({
        'case': 'same_factor_cross_identity_negative',
        'rc': same.get('rc'),
        'token_present': same.get('token_present'),
        'prewrite_diagnostic_exists': bool((same.get('prewrite_diagnostic') or {}).get('exists')),
        'forbidden_writebacks_absent': same.get('forbidden_writebacks_absent'),
        'ok': bool(same.get('ok'))
        and same.get('rc') != 0
        and same.get('token_present') is True
        and bool((same.get('prewrite_diagnostic') or {}).get('exists'))
        and same.get('forbidden_writebacks_absent') is True,
    })
    fail = cases.get('similar_failure_imported') or {}
    fail_ri = fail.get('research_intelligence') or {}
    rows.append({
        'case': 'similar_failure_imported',
        'rc': fail.get('rc'),
        'imported_lessons': fail_ri.get('imported_lessons'),
        'official_exists': bool((fail.get('produced_files') or {}).get('factor_library_official')),
        'ok': bool(fail.get('ok'))
        and fail.get('rc') == 0
        and bool(fail_ri.get('imported_lessons'))
        and not bool((fail.get('produced_files') or {}).get('factor_library_official')),
    })
    mismatch = cases.get('similar_success_rejected_condition_mismatch') or {}
    mismatch_ri = mismatch.get('research_intelligence') or {}
    branch_exec = mismatch_ri.get('search_policy_branch_execution_allowed_flags') or []
    rows.append({
        'case': 'similar_success_rejected_condition_mismatch',
        'rc': mismatch.get('rc'),
        'rejected_lessons': mismatch_ri.get('rejected_lessons'),
        'official_exists': bool((mismatch.get('produced_files') or {}).get('factor_library_official')),
        'handoff_exists': bool(((mismatch.get('forbidden_writebacks') or {}).get('handoff_to_step3b') or {}).get('exists')),
        'execution_allowed_flags': branch_exec,
        'ok': bool(mismatch.get('ok'))
        and mismatch.get('rc') == 0
        and bool(mismatch_ri.get('rejected_lessons'))
        and not bool((mismatch.get('produced_files') or {}).get('factor_library_official'))
        and not bool(((mismatch.get('forbidden_writebacks') or {}).get('handoff_to_step3b') or {}).get('exists'))
        and all(flag is False for flag in branch_exec),
    })
    return phase(rows)


def summarize_d(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    specs = [
        ('high_turnover_revision', 'iterate', 'cost_too_high', 'actionable', 'approved_for_step3b_handoff', True, False, None),
        ('non_monotonic_revision', 'iterate', 'non_monotonic', 'actionable', 'approved_for_step3b_handoff', True, False, None),
        ('long_side_negative_revision', 'reject', 'long_side_negative', 'actionable', 'advisory_only', False, False, None),
        ('valid_promote_no_revision_needed', 'promote_official', None, 'not_needed', None, False, True, False),
    ]
    rows = []
    for name, decision, signature, quality, loop_auth, handoff_expected, official_expected, revision_needed in specs:
        row = cases.get(name) or {}
        ri = row.get('research_intelligence') or {}
        handoff_exists = bool(((row.get('forbidden_writebacks') or {}).get('handoff_to_step3b') or {}).get('exists'))
        official_exists = bool((row.get('produced_files') or {}).get('factor_library_official'))
        ok = bool(row.get('ok')) and row.get('rc') == 0
        ok = ok and ri.get('decision') == decision and ri.get('revision_quality') == quality
        if signature is not None:
            ok = ok and ri.get('primary_failure_signature') == signature
        if loop_auth is not None:
            ok = ok and ri.get('loop_authorization') == loop_auth
        if revision_needed is not None:
            ok = ok and ri.get('revision_needed') is revision_needed
        ok = ok and handoff_exists is handoff_expected and official_exists is official_expected
        rows.append({
            'case': name,
            'rc': row.get('rc'),
            'decision': ri.get('decision'),
            'primary_failure_signature': ri.get('primary_failure_signature'),
            'revision_quality': ri.get('revision_quality'),
            'loop_authorization': ri.get('loop_authorization'),
            'revision_needed': ri.get('revision_needed'),
            'handoff_to_step3b_exists': handoff_exists,
            'official_exists': official_exists,
            'ok': ok,
        })
    return phase(rows)


def summarize_e(smoke: dict[str, Any], cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for name, mode, role, search_mode in [
        ('high_turnover_revision', 'bayesian_exploit', 'exploit', 'bayesian_search'),
        ('non_monotonic_revision', 'genetic_explore', 'explore', 'genetic_algorithm'),
        ('mechanism_unclear_revision', 'mechanism_challenge', 'macro', 'mechanism_challenge'),
    ]:
        row = cases.get(name) or {}
        ri = row.get('research_intelligence') or {}
        rows.append({
            'case': f'{name}_search_policy',
            'recommended_mode': ri.get('search_policy_recommended_mode'),
            'branch_count': ri.get('search_policy_branch_templates_count'),
            'branch_role': ri.get('search_policy_first_branch_role'),
            'search_mode': ri.get('search_policy_first_search_mode'),
            'approval_flags': ri.get('search_policy_branch_human_approval_flags'),
            'execution_flags': ri.get('search_policy_branch_execution_allowed_flags'),
            'ok': ri.get('search_policy_recommended_mode') == mode
            and ri.get('search_policy_branch_templates_count') == 1
            and ri.get('search_policy_first_branch_role') == role
            and ri.get('search_policy_first_search_mode') == search_mode
            and all(flag is True for flag in (ri.get('search_policy_branch_human_approval_flags') or []))
            and all(flag is False for flag in (ri.get('search_policy_branch_execution_allowed_flags') or [])),
        })
    missing = smoke.get('program_search_missing_templates_smoke') or {}
    rows.append({
        'case': 'missing_branch_templates_block',
        'plan_status': missing.get('plan_status'),
        'branch_count': missing.get('branch_count'),
        'validate_rc': missing.get('validate_rc'),
        'ok': bool(missing.get('ok'))
        and missing.get('plan_status') == 'blocked_missing_branch_templates'
        and missing.get('branch_count') == 0
        and missing.get('validate_rc') != 0,
    })
    alpha = cases.get('alpha013_like_advisory_mechanism_challenge_branch') or {}
    alpha_ri = alpha.get('research_intelligence') or {}
    alpha_program = alpha.get('program_search_validation') or {}
    alpha_branch = (alpha_ri.get('search_policy_branch_templates') or [{}])[0]
    alpha_plan_branch = alpha_program.get('first_branch') or {}
    rows.append({
        'case': 'alpha013_like_advisory_mechanism_challenge_branch',
        'rc': alpha.get('rc'),
        'recommended_mode': alpha_ri.get('search_policy_recommended_mode'),
        'loop_authorization': alpha_ri.get('loop_authorization'),
        'similar_success_condition_mismatch': alpha_ri.get('similar_success_condition_mismatch'),
        'branch_count': alpha_ri.get('search_policy_branch_templates_count'),
        'branch_id': alpha_branch.get('branch_id'),
        'branch_role': alpha_branch.get('branch_role'),
        'search_mode': alpha_branch.get('search_mode'),
        'program_search_validate_rc': alpha_program.get('validate_rc'),
        'handoff_exists': bool(((alpha.get('forbidden_writebacks') or {}).get('handoff_to_step3b') or {}).get('exists')),
        'official_exists': bool((alpha.get('produced_files') or {}).get('factor_library_official')),
        'ok': bool(alpha.get('ok'))
        and alpha.get('rc') == 0
        and alpha_ri.get('search_policy_recommended_mode') == 'mechanism_challenge'
        and alpha_ri.get('loop_authorization') == 'advisory_only'
        and alpha_ri.get('similar_success_condition_mismatch') is True
        and alpha_ri.get('search_policy_branch_templates_count') == 1
        and alpha_branch.get('branch_id') == 'challenge_mechanism_cost_contradiction'
        and alpha_branch.get('branch_role') == 'macro'
        and alpha_branch.get('search_mode') == 'mechanism_challenge'
        and alpha_branch.get('advisory_only') is True
        and alpha_branch.get('execution_allowed_by_default') is False
        and alpha_branch.get('requires_human_approval_before_execution') is True
        and alpha_program.get('validate_rc') == 0
        and alpha_program.get('plan_status') == 'pending_human_approval'
        and alpha_plan_branch.get('status') == 'proposed'
        and not bool(((alpha.get('forbidden_writebacks') or {}).get('handoff_to_step3b') or {}).get('exists'))
        and not bool((alpha.get('produced_files') or {}).get('factor_library_official')),
    })
    forbidden = smoke.get('program_search_forbidden_text_smoke') or {}
    mutation_rows = forbidden.get('mutations') or []
    required_mutations = {'research_question', 'success_criteria', 'falsification_tests', 'expected_outputs', 'execution_instructions'}
    seen = {row.get('case') for row in mutation_rows if row.get('ok') and row.get('validate_rc') != 0}
    rows.append({
        'case': 'forbidden_text_recursive_block',
        'mutations': mutation_rows,
        'ok': bool(forbidden.get('ok')) and required_mutations.issubset(seen),
    })
    return phase(rows)


def summarize_f(smoke: dict[str, Any]) -> dict[str, Any]:
    pos = smoke.get('phase_f_branch_execution_smoke') or {}
    neg = (smoke.get('phase_f_negative_smoke') or {}).get('cases') or {}
    rows = []
    for name in [
        'approve_proposed_branch_pass',
        'prepare_approved_branch_pass',
        'audit_worker_advisory_result_pass',
        'bayesian_worker_advisory_result_pass',
        'merge_advisory_only_pass',
    ]:
        row = pos.get(name) or {}
        rows.append({'case': name, 'rc': row.get('rc'), 'ok': bool(row.get('ok'))})
    for name in [
        'approve_missing_templates_block',
        'approve_no_search_recommended_block',
        'prepare_without_approval_block',
        'worker_without_prepare_block',
        'wrong_worker_for_branch_block',
        'branch_result_claims_adopted_block',
        'branch_result_canonical_write_permission_block',
        'forbidden_text_in_branch_result_block',
        'merge_attempts_handoff_write_block',
        'merge_attempts_generated_code_write_block',
        'merge_attempts_official_library_write_block',
    ]:
        row = neg.get(name) or {}
        extra_ok = True
        if name.startswith('merge_attempts_'):
            extra_ok = (
                row.get('setup_valid_branch_result') is True
                and row.get('token_present') is True
                and row.get('merge_exists') is False
                and row.get('diagnostic_exists') is True
            )
        rows.append({
            'case': name,
            'rc': row.get('rc'),
            'setup_valid_branch_result': row.get('setup_valid_branch_result'),
            'merge_exists': row.get('merge_exists'),
            'diagnostic_exists': row.get('diagnostic_exists'),
            'ok': bool(row.get('ok')) and extra_ok,
        })
    return phase(rows)


def summarize_loop_research_brief(smoke: dict[str, Any], cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    generated_case = cases.get('loop_research_brief_generated_pass') or {}
    brief = generated_case.get('loop_research_brief') or {}
    mutation_smoke = smoke.get('loop_research_brief_smoke') or {}
    mutation_cases = mutation_smoke.get('cases') or {}
    required_negative = [
        'loop_research_brief_missing_block',
        'loop_research_brief_missing_metric_block',
        'loop_research_brief_missing_pearson_ic_block',
        'loop_research_brief_missing_volatility_block',
        'loop_research_brief_missing_recovery_block',
        'loop_research_brief_missing_top_bottom_group_block',
        'loop_research_brief_missing_long_short_diagnostic_block',
        'loop_research_brief_blank_metric_block',
        'loop_research_brief_non_numeric_metric_block',
        'loop_research_brief_missing_chart_key_block',
        'loop_research_brief_long_short_not_diagnostic_block',
    ]
    negative_ok = all(
        bool((mutation_cases.get(name) or {}).get('ok'))
        and (mutation_cases.get(name) or {}).get('rc') != 0
        for name in required_negative
    )
    generated_ok = (
        bool(generated_case.get('ok'))
        and bool((generated_case.get('produced_files') or {}).get('loop_research_brief_markdown'))
        and bool((generated_case.get('produced_files') or {}).get('loop_research_brief_json'))
        and brief.get('brief_version') == 'factorforge_loop_research_brief_v1'
        and 'long_short_nav_diagnostic_only' in (brief.get('chart_keys') or [])
    )
    return {
        'status': pass_fail(generated_ok and negative_ok and bool(mutation_smoke.get('ok'))),
        'markdown_path': brief.get('markdown_path'),
        'json_path': brief.get('json_path'),
        'generated_case_ok': generated_ok,
        'negative_cases_ok': negative_ok,
        'mutation_cases': mutation_cases,
    }


def summarize_drawdown_geometry() -> dict[str, Any]:
    geometry = drawdown_geometry([1.0, 1.1, 1.0, 0.9, 1.1, 1.2])
    row = {
        'case': 'drawdown_geometry_area_computes_expected_values',
        'geometry': geometry,
        'ok': bool(
            geometry.get('drawdown_area') is not None
            and geometry.get('drawdown_area') > 0
            and geometry.get('normalized_drawdown_area') is not None
            and geometry.get('normalized_drawdown_area') > 0
            and geometry.get('max_drawdown_episode_area') is not None
            and geometry.get('max_drawdown_episode_area') > 0
            and geometry.get('recovery_pain_area') is not None
            and geometry.get('recovery_pain_area') > 0
            and geometry.get('episode_count') == 1
        ),
    }
    return phase([row])


def summarize_backend_evidence_status_split(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name in ['valid_supportive_evidence', 'price_volume_correlation_mechanism', 'high_turnover_revision']:
        row = cases.get(name) or {}
        ri = row.get('research_intelligence') or {}
        split = ri.get('evidence_status_split') or {}
        decision = ri.get('decision')
        rows.append({
            'case': f'{name}_evidence_status_split',
            'wrapper_validation_status': split.get('wrapper_validation_status'),
            'self_quant_evidence_status': split.get('self_quant_evidence_status'),
            'qlib_native_status': split.get('qlib_native_status'),
            'research_decision': split.get('research_decision'),
            'expected_decision': decision,
            'ok': (
                split.get('wrapper_validation_status') in {'PASS', 'WARN'}
                and split.get('self_quant_evidence_status') in {'present_success', 'present_partial'}
                and split.get('qlib_native_status') in {
                    'not_attempted',
                    'preflight_blocked',
                    'preflight_ready',
                    'partial_payload',
                    'native_minimal_success',
                    'native_backtest_success',
                    'failed',
                }
                and split.get('research_decision') == decision
            ),
        })
    return phase(rows)


def installed_sync() -> dict[str, Any]:
    installed_root = os.environ.get('FACTORFORGE_INSTALLED_SKILLS_ROOT')
    if installed_root:
        installed_root_path = Path(installed_root)
    else:
        candidates = [
            Path('/Users/humphrey/.codex/skills'),
            Path('/home/ubuntu/.openclaw/workspace/skills'),
        ]
        installed_root_path = next((p for p in candidates if p.exists()), candidates[0])
    checks = {}
    for key, repo_dir, installed_dir in [
        ('factor_forge_step6', REPO_ROOT / 'skills/factor-forge-step6', installed_root_path / 'factor-forge-step6'),
        ('factor_forge_research_brain', REPO_ROOT / 'skills/factor-forge-research-brain', installed_root_path / 'factor-forge-research-brain'),
    ]:
        cmd = ['diff', '-qr', '-x', '__pycache__', str(repo_dir), str(installed_dir)]
        proc = run_cmd(cmd)
        checks[key] = {
            'status': pass_fail(proc.returncode == 0),
            'command': cmd,
            'rc': proc.returncode,
            'stdout_tail': tail(proc.stdout),
            'stderr_tail': tail(proc.stderr),
        }
    return checks


def forbidden_writeback_checks(smoke: dict[str, Any], pollution: dict[str, Any]) -> dict[str, str]:
    neg = (smoke.get('phase_f_negative_smoke') or {}).get('cases') or {}
    return {
        'objects_handoff': pass_fail(bool((neg.get('merge_attempts_handoff_write_block') or {}).get('ok'))),
        'generated_code': pass_fail(bool((neg.get('merge_attempts_generated_code_write_block') or {}).get('ok'))),
        'official_library': pass_fail(bool((neg.get('merge_attempts_official_library_write_block') or {}).get('ok'))),
        'clean_data': pass_fail(not pollution.get('polluted') and not any(str(path).startswith('data/clean/') for path in pollution.get('new_files') or [])),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Acceptance harness for Step6 Intelligence Phase A-F.')
    ap.add_argument('--root', default=None, help='Must be under /tmp. Default creates /tmp/factorforge_step6_intelligence_acceptance_<timestamp>.')
    ap.add_argument('--fresh', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root or (Path('/tmp') / f'factorforge_step6_intelligence_acceptance_{datetime.now().strftime("%Y%m%d_%H%M%S")}')).expanduser()
    resolved = str(root.resolve())
    if not (resolved.startswith('/tmp/') or resolved.startswith('/private/tmp/')):
        raise SystemExit(f'BLOCK_NON_TMP_FACTORFORGE_ROOT: {root}')
    if args.fresh and root.exists():
        shutil.rmtree(root)

    before = snapshot_repo_canonical()
    smoke_run = run_smoke(root, fresh=args.fresh)
    smoke = smoke_run.get('summary') or {}
    cases = case_by_name(smoke)
    pollution = canonical_pollution(before)

    phase_results = {
        'phase_ab_evidence_gate': summarize_ab(root, cases),
        'phase_c_mechanism_case': summarize_c(cases),
        'phase_d_revision_loop': summarize_d(cases),
        'phase_e_search_policy': summarize_e(smoke, cases),
        'phase_f_branch_execution': summarize_f(smoke),
        'drawdown_geometry': summarize_drawdown_geometry(),
        'backend_evidence_status_split': summarize_backend_evidence_status_split(cases),
    }
    sync = installed_sync()
    forbidden_checks = forbidden_writeback_checks(smoke, pollution)
    loop_research_brief = summarize_loop_research_brief(smoke, cases)
    all_phases_pass = all(row.get('status') == 'PASS' for row in phase_results.values())
    sync_pass = all(row.get('status') == 'PASS' for row in sync.values())
    forbidden_pass = all(value == 'PASS' for value in forbidden_checks.values())
    accepted = (
        smoke_run.get('rc') == 0
        and smoke.get('verdict') == 'ACCEPT'
        and all_phases_pass
        and sync_pass
        and forbidden_pass
        and loop_research_brief.get('status') == 'PASS'
        and not pollution.get('polluted')
    )
    summary = {
        'verdict': 'ACCEPT' if accepted else 'BLOCK',
        'acceptance_token': 'STEP6_INTELLIGENCE_ACCEPTED' if accepted else 'STEP6_INTELLIGENCE_BLOCKED',
        'created_at_utc': utc_now(),
        'root_policy': {
            'factorforge_root': str(root),
            'is_tmp': True,
            'enforced': True,
        },
        'smoke_run': {
            key: value for key, value in smoke_run.items()
            if key != 'summary'
        },
        'phase_results': phase_results,
        'installed_sync': sync,
        'canonical_pollution': pollution,
        'forbidden_writeback_checks': forbidden_checks,
        'loop_research_brief': loop_research_brief,
        'notes': [
            'Synthetic /tmp-only acceptance.',
            'No real factor research was run.',
            'No clean data was read or processed.',
            'Acceptance delegates low-level fixtures to run_step6_intelligence_smoke.py and rechecks A-F contract semantics.',
        ],
    }
    summary_path = root / 'step6_intelligence_acceptance_summary.json'
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'[ACCEPTANCE_SUMMARY] {summary_path}')
    print(summary['acceptance_token'])
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
