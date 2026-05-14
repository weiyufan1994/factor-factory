from __future__ import annotations

from pathlib import Path
from typing import Any


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
    aliases = dict(metrics)
    if 'long_side_turnover_mean_daily' in metrics:
        aliases.setdefault('turnover', metrics.get('long_side_turnover_mean_daily'))
    if 'trading_cogs_annual' in metrics:
        aliases.setdefault('trading_cogs', metrics.get('trading_cogs_annual'))
    missing_long = [key for key in sorted(LONG_SIDE_REQUIRED_METRICS) if aliases.get(key) is None]
    return {
        'step4_has_successful_backend': bool(_backend_successes(factor_run_master)),
        'self_quant_required_and_present': _self_quant_success(factor_run_master, factor_evaluation),
        'long_side_metrics_present': not missing_long,
        'missing_long_side_metrics': missing_long,
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
