from __future__ import annotations

from pathlib import Path
from typing import Any

from factor_factory.primary_evaluator import primary_evaluator_plan, recovery_evidence_complete


LONG_SIDE_REQUIRED_METRICS = {
    'long_side_annual_return',
    'long_side_annual_volatility',
    'long_side_sharpe',
    'long_side_max_drawdown',
    'long_side_recovery_days',
    'turnover',
    'trading_cogs',
    'cost_adjusted_long_side_sharpe',
}

EVENT_STUDY_METRIC_PERIOD = 'signal_event_t_plus_1'
EVENT_STUDY_REQUIRED_METRICS = {
    'long_side_mean_return_per_signal_event',
    'long_side_return_std_per_signal_event',
    'long_side_signal_event_ir',
    'long_side_max_drawdown',
    'long_side_turnover_mean_per_rebalance',
    'trading_cogs_per_rebalance',
    'cost_adjusted_return_per_signal_event',
    'cost_adjusted_return_std_per_signal_event',
    'cost_adjusted_long_side_signal_event_ir',
    'cost_adjusted_long_side_max_drawdown',
}


def classify_long_side_evidence(metrics: dict[str, Any]) -> dict[str, Any]:
    """Classify evidence without converting sparse events into daily returns.

    A signal-event study is admissible as diagnostic evidence only.  It can be
    archived and handed to Step6, but it cannot satisfy the tradable next-month
    holding estimand or produce annualized investment-performance claims.
    """
    metric_period = metrics.get('metric_period')
    if metric_period == EVENT_STUDY_METRIC_PERIOD:
        missing = [key for key in sorted(EVENT_STUDY_REQUIRED_METRICS) if metrics.get(key) is None]
        if not recovery_evidence_complete(metrics):
            missing.append('long_side_recovery_evidence')
        forbidden_annualized = [
            key for key in sorted({
                'long_side_mean_return_daily',
                'long_side_annual_return',
                'long_side_return_std_daily',
                'long_side_annual_volatility',
                'long_side_sharpe',
                'long_side_turnover_mean_daily',
                'trading_cogs_daily',
                'trading_cogs_annual',
                'cost_adjusted_return_daily',
                'cost_adjusted_annual_return',
                'cost_adjusted_return_std_daily',
                'cost_adjusted_annual_volatility',
                'cost_adjusted_long_side_sharpe',
            })
            if metrics.get(key) is not None
        ]
        boundary_errors: list[str] = []
        if metrics.get('annualization_factor') is not None:
            boundary_errors.append('annualization_factor_must_be_null')
        if metrics.get('annualized_metrics_admissible') is not False:
            boundary_errors.append('annualized_metrics_admissible_must_be_false')
        if metrics.get('tradable_net_alpha_evidence') is not False:
            boundary_errors.append('tradable_net_alpha_evidence_must_be_false')
        if forbidden_annualized:
            boundary_errors.append('annualized_metrics_must_be_null:' + ','.join(forbidden_annualized))
        return {
            'evidence_mode': 'signal_event_diagnostic',
            'required_metrics': sorted(EVENT_STUDY_REQUIRED_METRICS),
            'missing_metrics': missing,
            'boundary_errors': boundary_errors,
            'complete': not missing and not boundary_errors,
            'tradable_net_alpha_evidence': False,
            'next_month_holding_estimand_executed': False,
            'promotion_eligible': False,
        }

    aliases = dict(metrics)
    if 'long_side_turnover_mean_daily' in metrics:
        aliases.setdefault('turnover', metrics.get('long_side_turnover_mean_daily'))
    if 'trading_cogs_annual' in metrics:
        aliases.setdefault('trading_cogs', metrics.get('trading_cogs_annual'))
    if 'trading_cogs_daily' in metrics:
        aliases.setdefault('trading_cogs', metrics.get('trading_cogs_daily'))
    missing = [key for key in sorted(LONG_SIDE_REQUIRED_METRICS) if aliases.get(key) is None]
    if 'long_side_recovery_days' in missing and recovery_evidence_complete(aliases):
        missing.remove('long_side_recovery_days')
    return {
        'evidence_mode': 'daily_annualized',
        'required_metrics': sorted(LONG_SIDE_REQUIRED_METRICS),
        'missing_metrics': missing,
        'boundary_errors': [],
        'complete': not missing,
        'tradable_net_alpha_evidence': metrics.get('tradable_net_alpha_evidence'),
        'next_month_holding_estimand_executed': metrics.get('next_month_holding_estimand_executed'),
        # Metric completeness supports review, not a tradability claim.
        'promotion_eligible': not missing and metrics.get('tradable_net_alpha_evidence') is True,
    }


def derive_identity(parent: dict[str, Any] | None, role: str, producer: str) -> dict[str, Any]:
    identity = dict(parent or {})
    identity['artifact_role'] = role
    identity['producer'] = producer
    return identity


def identity_hashes(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        'spec_hash': identity.get('spec_hash'),
        'formula_hash': identity.get('formula_hash'),
        'code_hash': identity.get('code_hash'),
        'code_contract_hash': identity.get('code_contract_hash'),
        'custom_block_hash': identity.get('custom_block_hash'),
        'hybrid_hash': identity.get('hybrid_hash'),
    }


def _path_if_exists(path: Path) -> str | None:
    return str(path) if path.exists() else None


def _backend_payload_refs(factor_run_master: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in ((factor_run_master.get('evaluation_results') or {}).get('backend_runs') or []):
        path = item.get('payload_path')
        if isinstance(path, str) and path.strip():
            refs.append(path)
    return refs


def _backend_identities(factor_run_master: dict[str, Any], payloads: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []
    for item in ((factor_run_master.get('evaluation_results') or {}).get('backend_runs') or []):
        backend = str(item.get('backend') or '')
        payload = (payloads or {}).get(backend) or {}
        identity = payload.get('artifact_identity') or item.get('artifact_identity') or {}
        identities.append({
            'backend': backend,
            'status': item.get('status'),
            'payload_path': item.get('payload_path'),
            'artifact_identity': identity,
        })
    return identities


def extract_implementation_mode_decision(
    factor_run_master: dict[str, Any],
    factor_case_master: dict[str, Any] | None = None,
    handoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    for obj in [factor_run_master, factor_case_master or {}, handoff or {}]:
        decision = obj.get('implementation_mode_decision')
        if isinstance(decision, dict) and decision:
            return decision
        evidence = obj.get('evidence_identity') or {}
        decision = evidence.get('implementation_mode_decision')
        if isinstance(decision, dict) and decision:
            return decision
    return {}


def build_evidence_identity(
    *,
    factorforge_root: Path,
    report_id: str,
    factor_run_master: dict[str, Any],
    factor_case_master: dict[str, Any] | None = None,
    factor_evaluation: dict[str, Any] | None = None,
    handoff: dict[str, Any] | None = None,
    backend_payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    objects = factorforge_root / 'objects'
    proof_candidates = [
        factorforge_root / 'proof' / f'ultimate_proof__{report_id}.json',
        objects / 'proof' / f'ultimate_proof__{report_id}.json',
        objects / 'ultimate_proof' / f'ultimate_proof__{report_id}.json',
    ]
    mode_decision = extract_implementation_mode_decision(factor_run_master, factor_case_master, handoff)
    return {
        'factor_run_master_ref': str(objects / 'factor_run_master' / f'factor_run_master__{report_id}.json'),
        'factor_run_master_identity': factor_run_master.get('artifact_identity') or {},
        'factor_case_master_ref': str(objects / 'factor_case_master' / f'factor_case_master__{report_id}.json'),
        'factor_case_master_identity': (factor_case_master or {}).get('artifact_identity') or {},
        'factor_evaluation_ref': str(objects / 'validation' / f'factor_evaluation__{report_id}.json'),
        'factor_evaluation_identity': (factor_evaluation or {}).get('artifact_identity') or {},
        'step4_backend_payload_refs': _backend_payload_refs(factor_run_master),
        'step4_backend_identities': _backend_identities(factor_run_master, backend_payloads),
        'step3b_mode_decision_ref': (
            str(objects / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json')
            if mode_decision else None
        ),
        'implementation_mode_decision': mode_decision,
        'ultimate_proof_ref': next((_path_if_exists(path) for path in proof_candidates if path.exists()), None),
    }


def _backend_successes(factor_run_master: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in ((factor_run_master.get('evaluation_results') or {}).get('backend_runs') or [])
        if item.get('status') in {'success', 'partial'}
    ]


def _self_quant_success(factor_run_master: dict[str, Any], factor_evaluation: dict[str, Any] | None = None) -> bool:
    for item in ((factor_run_master.get('evaluation_results') or {}).get('backend_runs') or []):
        if item.get('backend') == 'self_quant_analyzer' and item.get('status') in {'success', 'partial'}:
            return True
    for item in ((factor_evaluation or {}).get('backend_summary') or []):
        if item.get('backend') == 'self_quant_analyzer' and item.get('status') in {'success', 'partial'}:
            return True
    return False


def _primary_evaluator_success(factor_run_master: dict[str, Any], factor_evaluation: dict[str, Any] | None = None) -> bool:
    """Use an explicitly declared local primary evaluator, never a fallback."""
    try:
        plan = primary_evaluator_plan(factor_run_master.get('evaluation_plan'))
    except ValueError:
        return False
    if plan is None:
        return _self_quant_success(factor_run_master, factor_evaluation)
    backend = plan['backend']
    for item in ((factor_run_master.get('evaluation_results') or {}).get('backend_runs') or []):
        if item.get('backend') == backend and item.get('status') in {'success', 'partial'}:
            return True
    for item in ((factor_evaluation or {}).get('backend_summary') or []):
        if item.get('backend') == backend and item.get('status') in {'success', 'partial'}:
            return True
    return False


def _flatten_key_metrics(factor_evaluation: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in factor_evaluation.get('backend_summary') or []:
        if not isinstance(item, dict):
            continue
        metrics = item.get('key_metrics') or {}
        if isinstance(metrics, dict):
            out.update(metrics)
    return out


def build_evidence_quality(
    *,
    factor_run_master: dict[str, Any],
    factor_evaluation: dict[str, Any],
    evidence_identity: dict[str, Any],
    identity_chain_verified: bool,
) -> dict[str, Any]:
    metrics = _flatten_key_metrics(factor_evaluation)
    long_side = classify_long_side_evidence(metrics)
    missing_long = list(long_side['missing_metrics']) + list(long_side['boundary_errors'])
    try:
        primary_plan = primary_evaluator_plan(factor_run_master.get('evaluation_plan'))
    except ValueError:
        primary_plan = None
    return {
        'step4_has_successful_backend': bool(_backend_successes(factor_run_master)),
        'self_quant_required_and_present': _self_quant_success(factor_run_master, factor_evaluation),
        'primary_evaluator_required_and_present': _primary_evaluator_success(factor_run_master, factor_evaluation),
        'required_primary_evaluator': (primary_plan or {}).get('backend', 'self_quant_analyzer'),
        'long_side_metrics_present': not missing_long,
        'missing_long_side_metrics': missing_long,
        'long_side_evidence_mode': long_side['evidence_mode'],
        'tradable_net_alpha_evidence': long_side['tradable_net_alpha_evidence'],
        'next_month_holding_estimand_executed': long_side['next_month_holding_estimand_executed'],
        # This is a necessary evidence gate, not final Step6/OOS approval.
        'promotion_eligible': (
            long_side['promotion_eligible']
            and identity_chain_verified is True
            and bool(evidence_identity.get('implementation_mode_decision'))
            and factor_evaluation.get('evaluation_status') == 'validated'
            and _primary_evaluator_success(factor_run_master, factor_evaluation)
        ),
        'identity_chain_verified': bool(identity_chain_verified),
        'mode_decision_present': bool(evidence_identity.get('implementation_mode_decision')),
    }


def build_source_evidence_refs(evidence_identity: dict[str, Any]) -> dict[str, Any]:
    payload_refs = evidence_identity.get('step4_backend_payload_refs') or []
    return {
        'factor_run_master': evidence_identity.get('factor_run_master_ref'),
        'factor_run_diagnostics': None,
        'self_quant_payload': next((ref for ref in payload_refs if 'self_quant_analyzer' in str(ref)), None),
        'qlib_payload': next((ref for ref in payload_refs if 'qlib_backtest' in str(ref)), None),
        'ultimate_proof': evidence_identity.get('ultimate_proof_ref'),
    }


def build_decision_lineage(
    *,
    decision: str,
    factor_case_master: dict[str, Any],
    factor_run_master: dict[str, Any],
    evidence_identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        'decision': decision,
        'decision_basis': [
            'long_side_risk_adjusted_alpha',
            'identity_chain_verified',
            'evidence_quality_verified',
            'researcher_memo_reviewed',
        ],
        'source_case_master_ref': evidence_identity.get('factor_case_master_ref'),
        'source_case_identity': factor_case_master.get('artifact_identity') or {},
        'source_run_identity': factor_run_master.get('artifact_identity') or {},
        'source_step3b_mode_decision': evidence_identity.get('implementation_mode_decision') or {},
    }


def build_knowledge_provenance(
    *,
    source_identity: dict[str, Any],
    decision: str,
    similar_cases_imported: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        'source_factor_id': source_identity.get('factor_id'),
        'source_report_id': source_identity.get('report_id'),
        'source_branch_id': source_identity.get('branch_id'),
        'source_run_id': source_identity.get('run_id'),
        'source_decision': decision,
        'source_implementation_mode': source_identity.get('implementation_mode'),
        'source_hashes': identity_hashes(source_identity),
        'similar_cases_imported': similar_cases_imported or [],
        'not_same_factor_unless_identity_matches': True,
    }
