#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FACTORFORGE / 'objects'
ALLOWED = {'success', 'partial', 'failed'}
QLIB_NATIVE_STATUS_VALUES = {
    'not_attempted',
    'preflight_blocked',
    'preflight_ready',
    'partial_payload',
    'native_minimal_success',
    'native_backtest_success',
    'failed',
}

from factor_factory.artifact_identity import assert_identity_matches_strict
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id
from backtest_base_dataset import validate_backtest_base_dataset_contract


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict[str, Any] | None, str | None]:
    global FACTORFORGE, OBJ
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FACTORFORGE = manifest_factorforge_root(manifest)
    OBJ = FACTORFORGE / 'objects'
    os.environ['FACTORFORGE_ROOT'] = str(FACTORFORGE)
    return manifest, manifest_report_id(manifest)


def identity_or_issue(label: str, payload: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    identity = payload.get('artifact_identity') or {}
    required = ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'producer', 'spec_hash', 'branch_id', 'artifact_role']
    if not isinstance(identity, dict) or not identity:
        issues.append({'severity': 'error', 'code': f'{label.upper()}_ARTIFACT_IDENTITY_MISSING', 'message': f'{label}.artifact_identity missing'})
        return {}
    missing = [key for key in required if not identity.get(key)]
    if missing:
        issues.append({'severity': 'error', 'code': f'{label.upper()}_ARTIFACT_IDENTITY_INCOMPLETE', 'message': f'{label}.artifact_identity missing fields', 'evidence': {'missing': missing}})
    return identity


def validate_top_level_acceptance_fields(label: str, payload: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    identity = payload.get('artifact_identity') if isinstance(payload.get('artifact_identity'), dict) else {}
    required = ['report_id', 'factor_id', 'run_id', 'artifact_root', 'producer', 'status', 'verdict']
    missing = [field for field in required if payload.get(field) is None or payload.get(field) == '' or payload.get(field) == []]
    if missing:
        issues.append({
            'severity': 'error',
            'code': 'BLOCK_FORMAL_ARTIFACT_TOP_LEVEL_IDENTITY_MISSING',
            'message': f'{label} missing top-level formal acceptance fields',
            'evidence': {'missing': missing},
        })
    for field in ['report_id', 'factor_id', 'run_id']:
        if identity.get(field) and payload.get(field) and identity.get(field) != payload.get(field):
            issues.append({
                'severity': 'error',
                'code': 'BLOCK_FORMAL_ARTIFACT_TOP_LEVEL_IDENTITY_MISMATCH',
                'message': f'{label}.{field} differs from artifact_identity.{field}',
                'evidence': {'top_level': payload.get(field), 'artifact_identity': identity.get(field)},
            })


def validate_acceptance_summary(summary: dict[str, Any] | None, issues: list[dict[str, Any]]) -> None:
    if not isinstance(summary, dict) or not summary:
        issues.append({'severity': 'error', 'code': 'BLOCK_ACCEPTANCE_SUMMARY_MISSING', 'message': 'acceptance_summary missing'})
        return
    if summary.get('version') != 'factorforge_production_acceptance_summary_v1':
        issues.append({'severity': 'error', 'code': 'BLOCK_ACCEPTANCE_SUMMARY_MISSING', 'message': 'invalid acceptance_summary.version'})
    identity_missing = [field for field in ['report_id', 'factor_id', 'run_id', 'artifact_root', 'repo_sha'] if not summary.get(field)]
    if identity_missing:
        issues.append({'severity': 'error', 'code': 'BLOCK_ACCEPTANCE_SUMMARY_RUN_IDENTITY_MISSING', 'message': 'acceptance_summary run identity missing', 'evidence': {'missing': identity_missing}})
    step4 = summary.get('step4') if isinstance(summary.get('step4'), dict) else {}
    if not step4.get('self_quant_status') or step4.get('qlib_native_status') not in QLIB_NATIVE_STATUS_VALUES:
        issues.append({'severity': 'error', 'code': 'BLOCK_ACCEPTANCE_SUMMARY_BACKEND_SPLIT_MISSING', 'message': 'acceptance_summary must split self_quant_status and qlib_native_status'})
    reuse = summary.get('reuse') if isinstance(summary.get('reuse'), dict) else {}
    if reuse.get('reuse_gate_status') not in {'recomputed', 'reused', 'blocked', 'not_applicable'}:
        issues.append({'severity': 'error', 'code': 'BLOCK_ACCEPTANCE_SUMMARY_REUSE_STATUS_MISSING', 'message': 'acceptance_summary.reuse.reuse_gate_status missing'})
    side_effects = summary.get('side_effects') if isinstance(summary.get('side_effects'), dict) else {}
    for field in ['clean_data_mutated', 'generated_code_digest_changed', 'official_record_written', 'search_worker_started']:
        if side_effects.get(field) is not False:
            issues.append({'severity': 'error', 'code': 'BLOCK_ACCEPTANCE_SUMMARY_SIDE_EFFECTS_MISSING', 'message': f'acceptance_summary.side_effects.{field}=false required'})


def validate_factor_output_policy(policy: dict[str, Any] | None, issues: list[dict[str, Any]]) -> None:
    if not isinstance(policy, dict) or not policy:
        issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN', 'message': 'factor_output_policy missing'})
        return
    if policy.get('formal_format') != 'parquet':
        issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN', 'message': 'formal factor output must be parquet'})
    if policy.get('full_factor_csv_written') is True and policy.get('full_csv_non_default_opt_in') is not True:
        issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN', 'message': 'full factor CSV written without explicit non-default opt-in'})
    if policy.get('sample_csv_required') is True and policy.get('sample_csv_written') is not True:
        issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN', 'message': 'sample CSV proof must be written while full CSV is disabled'})


def validate_backtest_base_profile(profile: dict[str, Any] | None, issues: list[dict[str, Any]]) -> None:
    if not isinstance(profile, dict) or not profile:
        issues.append({'severity': 'error', 'code': 'BLOCK_BACKTEST_BASE_DATASET_MISSING', 'message': 'backtest_base_profile missing'})
        return
    if profile.get('version') != 'factorforge_backtest_base_profile_v1':
        issues.append({'severity': 'error', 'code': 'BLOCK_BACKTEST_BASE_DATASET_MISSING', 'message': 'invalid backtest_base_profile.version'})
    if not profile.get('backtest_base_dataset_id'):
        issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_REUSE_GATE_AMBIGUOUS', 'message': 'backtest_base_profile missing dataset id'})
    if profile.get('backtest_base_reuse_reason') == 'ambiguous_identity':
        issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_REUSE_GATE_AMBIGUOUS', 'message': 'backtest base reuse identity is ambiguous'})


def validate_qlib_taxonomy(payload: dict[str, Any], *, mandatory: bool, issues: list[dict[str, Any]]) -> None:
    status = payload.get('qlib_native_status')
    if status not in QLIB_NATIVE_STATUS_VALUES:
        issues.append({'severity': 'error', 'code': 'BLOCK_QLIB_NATIVE_STATUS_INVALID', 'message': 'qlib payload missing supported qlib_native_status', 'evidence': payload})
        return
    if payload.get('mode') == 'sample_stub' and status in {'native_minimal_success', 'native_backtest_success'}:
        issues.append({'severity': 'error', 'code': 'BLOCK_QLIB_SAMPLE_STUB_NATIVE_SUCCESS', 'message': 'sample_stub cannot be qlib native success', 'evidence': payload})
    if payload.get('status') == 'success' and status == 'partial_payload':
        issues.append({'severity': 'error', 'code': 'BLOCK_QLIB_PARTIAL_LABELED_SUCCESS', 'message': 'partial_payload cannot be reported as qlib success', 'evidence': payload})
    if mandatory and status == 'partial_payload':
        issues.append({'severity': 'error', 'code': 'BLOCK_QLIB_PARTIAL_MANDATORY', 'message': 'mandatory qlib native run cannot accept partial_payload', 'evidence': payload})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest')
    args = ap.parse_args()
    _manifest, manifest_rid = apply_runtime_manifest(args.manifest)
    rid = args.report_id or manifest_rid
    if not rid:
        raise SystemExit('validate_step4 requires --report-id or --manifest')

    run_master_path = OBJ / 'factor_run_master' / f'factor_run_master__{rid}.json'
    diag_path = OBJ / 'validation' / f'factor_run_diagnostics__{rid}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step5__{rid}.json'
    revision_path = OBJ / 'validation' / f'factor_run_validation_revision__{rid}.json'

    assert run_master_path.exists(), f'missing run master: {run_master_path}'
    assert diag_path.exists(), f'missing diagnostics: {diag_path}'
    assert handoff_path.exists(), f'missing handoff: {handoff_path}'

    run_master = load_json(run_master_path)
    diagnostics = load_json(diag_path)
    handoff = load_json(handoff_path)

    issues: list[dict[str, Any]] = []
    run_identity = identity_or_issue('factor_run_master', run_master, issues)
    handoff_identity = identity_or_issue('handoff_to_step5', handoff, issues)
    validate_top_level_acceptance_fields('factor_run_master', run_master, issues)
    validate_top_level_acceptance_fields('handoff_to_step5', handoff, issues)
    validate_acceptance_summary(run_master.get('acceptance_summary'), issues)
    issues.extend(validate_backtest_base_dataset_contract(run_master.get('backtest_base_dataset_contract')))
    validate_backtest_base_profile(run_master.get('backtest_base_profile'), issues)
    validate_factor_output_policy(run_master.get('factor_output_policy'), issues)
    if run_identity and handoff_identity:
        try:
            assert_identity_matches_strict(
                run_identity,
                handoff_identity,
                expected_label='factor_run_master',
                actual_label='handoff_to_step5',
                allowed_role_transitions={('factor_run_master', 'handoff_to_step5')},
            )
        except AssertionError as exc:
            issues.append({'severity': 'error', 'code': 'STEP4_ARTIFACT_IDENTITY_MISMATCH', 'message': str(exc)})
        if run_identity.get('artifact_role') != 'factor_run_master':
            issues.append({'severity': 'error', 'code': 'STEP4_RUN_MASTER_ROLE_INVALID', 'message': f"factor_run_master artifact_role={run_identity.get('artifact_role')}"})
        if handoff_identity.get('artifact_role') != 'handoff_to_step5':
            issues.append({'severity': 'error', 'code': 'STEP4_HANDOFF_ROLE_INVALID', 'message': f"handoff_to_step5 artifact_role={handoff_identity.get('artifact_role')}"})
    proposed_status = run_master.get('run_status')

    if proposed_status not in ALLOWED:
        issues.append({'severity': 'error', 'code': 'INVALID_RUN_STATUS', 'message': f'invalid run_status={proposed_status}'})
        proposed_status = 'failed'

    output_paths = [Path(p) for p in run_master.get('output_paths', [])]
    output_exists = [p.exists() for p in output_paths]

    if run_master.get('run_status') in {'success', 'partial'}:
        if not output_paths:
            issues.append({'severity': 'error', 'code': 'MISSING_OUTPUT_PATHS', 'message': 'success/partial requires material output paths'})
            proposed_status = 'failed'
        elif not all(output_exists):
            issues.append({'severity': 'error', 'code': 'OUTPUT_PATH_NOT_FOUND', 'message': 'declared output path missing', 'evidence': {'paths': [str(p) for p in output_paths], 'exists': output_exists}})
            proposed_status = 'failed'
        elif diagnostics.get('output_validation', {}).get('row_count', 0) <= 0:
            issues.append({'severity': 'error', 'code': 'NONPOSITIVE_ROW_COUNT', 'message': 'success/partial requires positive row count'})
            proposed_status = 'failed'

    if run_master.get('run_status') == 'partial':
        scope = handoff.get('recommended_step5_scope')
        notes = ' '.join(handoff.get('notes_for_step5', []))
        if scope != 'partial_scope_only' and 'partial' not in notes.lower():
            issues.append({'severity': 'error', 'code': 'PARTIAL_SCOPE_UNDECLARED', 'message': 'partial result must declare evaluable scope in handoff'})
            proposed_status = 'failed'

    if run_master.get('run_status') == 'failed' and not run_master.get('failure_reason'):
        issues.append({'severity': 'error', 'code': 'FAILED_WITHOUT_REASON', 'message': 'failed run must declare failure_reason'})

    eval_plan = run_master.get('evaluation_plan')
    eval_results = run_master.get('evaluation_results', {})
    backend_runs = eval_results.get('backend_runs') if isinstance(eval_results, dict) else None
    if not isinstance(eval_plan, dict):
        issues.append({'severity': 'error', 'code': 'MISSING_EVALUATION_PLAN', 'message': 'factor_run_master must expose evaluation_plan'})
        proposed_status = 'failed'
    else:
        if not isinstance(eval_plan.get('backends'), list) or not eval_plan.get('backends'):
            issues.append({'severity': 'error', 'code': 'INVALID_EVALUATION_BACKENDS', 'message': 'evaluation_plan.backends must be a non-empty list'})
            proposed_status = 'failed'
        if eval_plan.get('metric_policy') in {None, ''}:
            issues.append({'severity': 'error', 'code': 'MISSING_METRIC_POLICY', 'message': 'evaluation_plan.metric_policy must be explicit'})
            proposed_status = 'failed'

    if not isinstance(backend_runs, list):
        issues.append({'severity': 'error', 'code': 'MISSING_BACKEND_RUNS', 'message': 'factor_run_master must expose evaluation_results.backend_runs'})
        proposed_status = 'failed'
    else:
        successful_backends = [item for item in backend_runs if item.get('status') in {'success', 'partial'}]
        if not successful_backends:
            issues.append({'severity': 'error', 'code': 'BLOCK_NO_SUCCESSFUL_BACKEND', 'message': 'Step4 must have at least one successful or partial backend; all-skipped/all-failed evidence cannot pass'})
            proposed_status = 'failed'
        self_quant = next((item for item in backend_runs if item.get('backend') == 'self_quant_analyzer' or item.get('name') == 'self_quant_analyzer'), None)
        if not self_quant or self_quant.get('status') not in {'success', 'partial'}:
            issues.append({'severity': 'error', 'code': 'BLOCK_MISSING_SELF_QUANT_EVIDENCE', 'message': 'formal Step4 requires self_quant_analyzer success/partial long-only evidence'})
            proposed_status = 'failed'
        for item in backend_runs:
            if item.get('status') not in {'success', 'partial', 'failed', 'skipped'}:
                issues.append({'severity': 'error', 'code': 'INVALID_BACKEND_STATUS', 'message': 'backend run status must be explicit', 'evidence': item})
                proposed_status = 'failed'
            if item.get('status') in {'success', 'partial'}:
                payload_path = item.get('payload_path')
                if not payload_path or not Path(payload_path).exists():
                    issues.append({'severity': 'error', 'code': 'BACKEND_PAYLOAD_MISSING', 'message': 'backend claims success/partial but payload_path is missing', 'evidence': item})
                    proposed_status = 'failed'
                else:
                    payload = load_json(Path(payload_path))
                    payload_status = payload.get('status')
                    if payload_status in {'success', 'partial', 'failed', 'skipped'} and payload_status != item.get('status'):
                        issues.append({'severity': 'error', 'code': 'BACKEND_STATUS_PAYLOAD_MISMATCH', 'message': 'backend run status must match payload status', 'evidence': {'backend_run': item.get('status'), 'payload': payload_status, 'payload_path': payload_path}})
                        proposed_status = 'failed'
                    if item.get('backend') == 'qlib_backtest':
                        mandatory_qlib = bool((run_master.get('evaluation_plan') or {}).get('qlib_native_mandatory'))
                        validate_qlib_taxonomy(payload, mandatory=mandatory_qlib, issues=issues)
                        if payload.get('mode') not in {'sample_stub', 'native_minimal'}:
                            issues.append({'severity': 'error', 'code': 'QLIB_MODE_INVALID', 'message': 'qlib_backtest payload must declare supported mode', 'evidence': payload})
                            proposed_status = 'failed'
                        if payload.get('mode') == 'native_minimal':
                            metrics = payload.get('native_backtest_metrics') or {}
                            artifacts = payload.get('artifacts') or {}
                            if metrics.get('nonzero_value_rows') in {None, 0}:
                                issues.append({'severity': 'error', 'code': 'QLIB_NATIVE_EMPTY_PORTFOLIO', 'message': 'native qlib payload must show nonzero portfolio activity', 'evidence': metrics})
                                proposed_status = 'failed'
                            required_artifacts = ['portfolio_value_timeseries_png', 'benchmark_vs_strategy_png', 'turnover_timeseries_png']
                            for key in required_artifacts:
                                ap = artifacts.get(key)
                                if not ap or not Path(ap).exists():
                                    issues.append({'severity': 'error', 'code': 'QLIB_NATIVE_ARTIFACT_MISSING', 'message': f'missing qlib native artifact: {key}', 'evidence': artifacts})
                                    proposed_status = 'failed'
                    if item.get('backend') == 'self_quant_analyzer':
                        contract = payload.get('standard_metric_contract') or {}
                        artifacts = payload.get('artifacts') or {}
                        if not contract:
                            issues.append({'severity': 'error', 'code': 'SELF_QUANT_STANDARD_CONTRACT_MISSING', 'message': 'self_quant_analyzer must emit standard_metric_contract'})
                            proposed_status = 'failed'
                        else:
                            blocking_count = contract.get('blocking_issue_count')
                            if blocking_count not in {0, None}:
                                issues.append({'severity': 'error', 'code': 'SELF_QUANT_STANDARD_CONTRACT_BLOCKING', 'message': 'self_quant_analyzer standard metric contract has blocking issues', 'evidence': contract})
                                proposed_status = 'failed'
                        required_artifacts = [
                            'rank_ic_timeseries_png',
                            'pearson_ic_timeseries_png',
                            'coverage_by_day_png',
                            'quantile_returns_10groups_csv',
                            'quantile_nav_10groups_csv',
                            'quantile_counts_10groups_csv',
                            'quantile_summary_table_csv',
                            'long_short_returns_10groups_csv',
                            'long_short_nav_10groups_csv',
                            'quantile_nav_10groups_png',
                            'quantile_counts_10groups_png',
                            'long_short_nav_10groups_png',
                            'long_side_returns_csv',
                            'long_side_nav_csv',
                            'long_side_turnover_csv',
                            'long_side_nav_png',
                            'cost_adjusted_long_side_nav_png',
                        ]
                        for key in required_artifacts:
                            ap = artifacts.get(key)
                            if not ap or not Path(ap).exists():
                                issues.append({'severity': 'error', 'code': 'SELF_QUANT_ARTIFACT_MISSING', 'message': f'missing self_quant standard artifact: {key}', 'evidence': artifacts})
                                proposed_status = 'failed'
                        long_side = payload.get('long_side_performance') or {}
                        required_long_side_fields = [
                            'long_side_annual_return',
                            'long_side_annual_volatility',
                            'long_side_sharpe',
                            'long_side_max_drawdown',
                            'long_side_recovery_days',
                            'long_side_turnover_mean_daily',
                            'turnover',
                            'trading_cogs_daily',
                            'trading_cogs',
                            'cost_adjusted_long_side_sharpe',
                        ]
                        aliases = {
                            'long_side_turnover_mean_daily': ['long_side_turnover_mean_daily', 'turnover'],
                            'turnover': ['turnover', 'long_side_turnover_mean_daily'],
                            'trading_cogs_daily': ['trading_cogs_daily', 'trading_cogs'],
                            'trading_cogs': ['trading_cogs', 'trading_cogs_daily'],
                        }
                        missing_long_side = [
                            key for key in required_long_side_fields
                            if all(long_side.get(alias) is None for alias in aliases.get(key, [key]))
                        ]
                        if missing_long_side:
                            issues.append({'severity': 'error', 'code': 'SELF_QUANT_LONG_SIDE_EVIDENCE_MISSING', 'message': 'self_quant_analyzer must emit complete long-side risk-adjusted evidence', 'evidence': {'missing': missing_long_side}})
                            proposed_status = 'failed'
                        if long_side.get('metric_period') != 'daily' or long_side.get('annualization_factor') is None:
                            issues.append({'severity': 'error', 'code': 'SELF_QUANT_LONG_SIDE_UNITS_MISSING', 'message': 'self_quant_analyzer long-side evidence must declare metric_period and annualization_factor', 'evidence': long_side})
                            proposed_status = 'failed'

    if diagnostics.get('run_status') != run_master.get('run_status'):
        issues.append({'severity': 'warning', 'code': 'RUN_STATUS_MISMATCH', 'message': 'diagnostics run_status differs from run_master', 'evidence': {'run_master': run_master.get('run_status'), 'diagnostics': diagnostics.get('run_status')}})

    verdict = 'PASS' if not any(i['severity'] == 'error' for i in issues) else 'FAIL'
    revision = {
        'report_id': rid,
        'validator_generated_at_utc': utc_now(),
        'original_run_status': run_master.get('run_status'),
        'validated_run_status': proposed_status,
        'verdict': verdict,
        'issues': issues,
        'notes': [
            'Validator may output final acceptance conclusion.',
            'Validator does not silently rewrite original execution object.',
            'If statuses differ, this revision record is the explicit correction artifact.'
        ]
    }
    write_json(revision_path, revision)
    print(f'RESULT: {verdict}')
    print(f'VALIDATED_RUN_STATUS: {proposed_status}')
    if verdict != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
