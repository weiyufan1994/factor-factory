#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections import Counter
import re
import urllib.request

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FF) not in sys.path:
    sys.path.append(str(FF))

from skills.factor_forge_step5.modules.io import load_json, write_json  # type: ignore
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id
from factor_factory.artifact_identity import assert_identity_matches_strict
from factor_factory.provenance import (
    build_decision_lineage,
    build_evidence_identity,
    build_knowledge_provenance,
    derive_identity as derive_provenance_identity,
)
from factor_factory.mechanism_math.classifier import build_mechanism_math_contract, build_mechanism_math_contract_v2
from factor_factory.mechanism_math.formula_specific import (
    build_formula_specific_derivation,
    validate_formula_specific_derivation,
    validate_mechanism_formula_consistency,
)
from factor_factory.mechanism_math.main_agent_memo import (
    build_main_agent_mechanism_questionnaire,
    formula_specific_derivation_from_main_agent_memo,
    render_main_agent_mechanism_questionnaire_markdown,
    validate_main_agent_mechanism_memo,
)
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract, validate_mechanism_math_contract_v2
from factor_factory.mechanism_math.factor_discovery_queue import build_default_discovery_queue

OBJ = FF / 'objects'
EVAL = FF / 'evaluations'
RETRIEVAL_INDEX = Path(os.getenv('FACTORFORGE_RETRIEVAL_INDEX') or (REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'))
LOOP_RESEARCH_BRIEF_VERSION = 'factorforge_loop_research_brief_v1'
REQUIRED_LOOP_BRIEF_CHART_KEYS = [
    'rank_ic_timeseries',
    'pearson_ic_timeseries',
    'long_side_nav',
    'cost_adjusted_long_side_nav',
    'quantile_nav',
    'long_short_nav_diagnostic_only',
    'coverage_by_day',
]
CORE_LOOP_BRIEF_METRICS = [
    'rank_ic_mean',
    'rank_ic_ir',
    'pearson_ic_mean',
    'pearson_ic_ir',
    'long_side_annual_return',
    'long_side_annual_volatility',
    'long_side_sharpe',
    'long_side_max_drawdown',
    'long_side_recovery_days',
    'long_side_turnover_mean_daily',
    'trading_cogs_annual',
    'cost_adjusted_annual_return',
    'cost_adjusted_long_side_sharpe',
    'cost_adjusted_long_side_max_drawdown',
    'group_top_decile_mean_return',
    'group_bottom_decile_mean_return',
    'group_long_short_spread_mean',
    'group_long_short_spread_ir',
]
CHART_ARTIFACT_FILENAMES = {
    'rank_ic_timeseries': 'rank_ic_timeseries.png',
    'pearson_ic_timeseries': 'pearson_ic_timeseries.png',
    'long_side_nav': 'long_side_nav.png',
    'cost_adjusted_long_side_nav': 'cost_adjusted_long_side_nav.png',
    'quantile_nav': 'quantile_nav_10groups.png',
    'long_short_nav_diagnostic_only': 'long_short_nav_10groups.png',
    'coverage_by_day': 'coverage_by_day.png',
}


def derive_identity(parent: dict[str, Any], role: str, producer: str = 'step6') -> dict[str, Any]:
    return derive_provenance_identity(parent, role, producer)
EMBEDDING_MATRIX = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_embeddings.npy'
EMBEDDING_META = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_embedding_metadata.jsonl'
EMBEDDING_ENDPOINT = os.getenv('FACTORFORGE_EMBEDDING_ENDPOINT', 'http://127.0.0.1:8008/v1/embeddings')


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FF, OBJ, EVAL
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step6 execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FF.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    if manifest_path:
        manifest = load_runtime_manifest(manifest_path)
        if manifest_factorforge_root(manifest).expanduser().resolve() != debug_root:
            raise SystemExit('BLOCKED_DIRECT_STEP: direct debug manifest must point to FACTORFORGE_DEBUG_ROOT.')
    FF = debug_root
    OBJ = FF / 'objects'
    EVAL = FF / 'evaluations'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def tokenize(text: str) -> list[str]:
    return re.findall(r'[a-zA-Z_]{3,}|[\u4e00-\u9fff]{1,}', text.lower())


def load_required_inputs(report_id: str) -> dict[str, Any]:
    preferred_handoff = OBJ / 'handoff' / f'handoff_to_step6__{report_id}.json'
    legacy_handoff = OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json'
    if not preferred_handoff.exists() and os.getenv('FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF') != '1':
        raise SystemExit(
            f'STEP6_INPUT_INVALID: formal Step6 requires handoff_to_step6 and will not fall back to legacy handoff_to_step5: {preferred_handoff}'
        )
    paths = {
        'factor_run_master': OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json',
        'factor_case_master': OBJ / 'factor_case_master' / f'factor_case_master__{report_id}.json',
        'factor_evaluation': OBJ / 'validation' / f'factor_evaluation__{report_id}.json',
        'handoff_to_step6': preferred_handoff if preferred_handoff.exists() else legacy_handoff,
        'factor_spec_master': OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json',
        'alpha_idea_master': OBJ / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json',
    }
    required = {'factor_run_master', 'factor_case_master', 'factor_evaluation', 'handoff_to_step6'}
    missing = [str(path) for key, path in paths.items() if key in required and not path.exists()]
    if missing:
        raise SystemExit('STEP6_INPUT_INVALID: missing required inputs: ' + ', '.join(missing))
    bundle = {
        'paths': paths,
        'factor_run_master': load_json(paths['factor_run_master']),
        'factor_case_master': load_json(paths['factor_case_master']),
        'factor_evaluation': load_json(paths['factor_evaluation']),
        'handoff_to_step6': load_json(paths['handoff_to_step6']),
    }
    for key in ['factor_spec_master', 'alpha_idea_master']:
        path = paths[key]
        bundle[key] = load_json(path) if path.exists() else {}
    return bundle


def load_backend_payloads(report_id: str, run_master: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    backend_runs = (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    for item in backend_runs:
        backend = item.get('backend')
        payload_path = item.get('payload_path')
        if not backend:
            continue
        if payload_path and Path(payload_path).exists():
            payloads[str(backend)] = load_json(payload_path)
            continue
        fallback = EVAL / report_id / str(backend) / 'evaluation_payload.json'
        if fallback.exists():
            payloads[str(backend)] = load_json(fallback)
    return payloads


def load_researcher_agent_memo(report_id: str) -> dict[str, Any] | None:
    path = OBJ / 'research_iteration_master' / f'researcher_memo__{report_id}.json'
    if not path.exists():
        return None
    try:
        data = load_json(path)
    except Exception:
        return {
            'load_error': f'failed to load researcher memo from {path}',
            'source_path': str(path),
        }
    if isinstance(data, dict):
        data.setdefault('source_path', str(path))
        return data
    return {
        'load_error': f'researcher memo at {path} is not a JSON object',
        'source_path': str(path),
    }


def load_researcher_journal(report_id: str) -> dict[str, Any] | None:
    path = OBJ / 'research_journal' / f'research_journal__{report_id}.json'
    if not path.exists():
        return None
    try:
        data = load_json(path)
    except Exception:
        return {
            'load_error': f'failed to load researcher journal from {path}',
            'source_path': str(path),
        }
    if isinstance(data, dict):
        data.setdefault('source_path', str(path))
        return data
    return {
        'load_error': f'researcher journal at {path} is not a JSON object',
        'source_path': str(path),
    }


def load_retrieval_docs() -> list[dict[str, Any]]:
    if not RETRIEVAL_INDEX.exists():
        return []
    docs: list[dict[str, Any]] = []
    for line in RETRIEVAL_INDEX.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line))
        except Exception:
            continue
    return docs


def load_embedding_docs() -> list[dict[str, Any]]:
    if not EMBEDDING_META.exists():
        return []
    docs: list[dict[str, Any]] = []
    for line in EMBEDDING_META.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line))
        except Exception:
            continue
    return docs


def embed_query(text: str) -> np.ndarray | None:
    try:
        req = urllib.request.Request(
            EMBEDDING_ENDPOINT,
            data=json.dumps({'input': [text]}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        return np.asarray(payload['data'][0]['embedding'], dtype=np.float32)
    except Exception:
        return None


def extract_headline_metrics(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    sq = payloads.get('self_quant_analyzer') or {}
    ql = payloads.get('qlib_backtest') or {}

    ic_summary = sq.get('ic_summary') or {}
    for key in ['rank_ic_mean', 'rank_ic_ir', 'pearson_ic_mean', 'pearson_ic_ir']:
        if key in ic_summary:
            metrics[key] = ic_summary.get(key)
    sq_group = sq.get('group_backtest_summary') or {}
    for key in [
        'long_short_spread_mean',
        'long_short_spread_ir',
        'top_decile_mean_return',
        'bottom_decile_mean_return',
    ]:
        if key in sq_group:
            metrics[f'group_{key}'] = sq_group.get(key)
    sq_long = sq.get('long_side_performance') or {}
    for key in [
        'metric_period',
        'annualization_factor',
        'long_side_mean_return_daily',
        'long_side_annual_return',
        'long_side_return_std_daily',
        'long_side_annual_volatility',
        'long_side_sharpe',
        'long_side_max_drawdown',
        'long_side_recovery_days',
        'long_side_drawdown_area',
        'long_side_normalized_drawdown_area',
        'long_side_max_drawdown_episode_area',
        'long_side_recovery_pain_area',
        'long_side_turnover_mean_daily',
        'turnover_mean',
        'trading_cogs_daily',
        'trading_cogs_annual',
        'cost_adjusted_return_daily',
        'cost_adjusted_annual_return',
        'cost_adjusted_long_side_sharpe',
        'cost_adjusted_long_side_max_drawdown',
        'cost_adjusted_long_side_recovery_days',
        'cost_adjusted_long_side_drawdown_area',
        'cost_adjusted_long_side_normalized_drawdown_area',
        'cost_adjusted_long_side_max_drawdown_episode_area',
        'cost_adjusted_long_side_recovery_pain_area',
    ]:
        if key in sq_long:
            metrics[key] = sq_long.get(key)

    ql_native = ql.get('native_backtest_metrics') or {}
    ql_stub = ql.get('stub_backtest_metrics') or {}
    for key in [
        'mean_return',
        'final_account',
        'nonzero_turnover_rows',
        'nonzero_value_rows',
        'annual_return',
        'max_drawdown',
        'sharpe',
        'volatility',
        'annual_volatility',
        'recovery_days',
        'drawdown_recovery_days',
        'calmar',
        'turnover_mean',
        'turnover',
        'transaction_cost',
        'trading_cost',
        'impact_cost',
        'turnover_cost',
    ]:
        if key in ql_native:
            metrics[f'qlib_{key}'] = ql_native.get(key)
    for key in [
        'long_short_spread_mean',
        'long_short_spread_ir',
        'top_decile_mean_return',
        'top_decile_return_std',
        'top_decile_sharpe',
        'top_decile_max_drawdown',
        'top_decile_recovery_days',
        'bottom_decile_mean_return',
    ]:
        if key in ql_stub:
            metrics[f'group_{key}'] = ql_stub.get(key)
    return metrics


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        out = float(value)
        if np.isnan(out):
            return None
        return out
    except Exception:
        return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


LONG_ONLY_POLICY = {
    'no_short_selling': True,
    'no_direct_decile_trading': True,
    'primary_objective': 'long_side_risk_adjusted_alpha',
    'revision_scope': 'factor_expression_and_step3b_code_only',
    'forbidden_decision_basis': [
        'short_leg_returns',
        'long_short_spread_as_adoption_metric',
        'direct_decile_portfolio_trading',
        'portfolio_expression_repair',
    ],
    'required_revision_direction': (
        'Revise the factor expression and Step3B implementation so higher factor values map to a clearer, '
        'more monotonic economic long-side return relationship.'
    ),
}

DEFAULT_TURNOVER_COST_RATE = 0.003

LONG_SIDE_PERFORMANCE_THRESHOLDS = {
    'candidate_min_sharpe': 0.50,
    'official_min_sharpe': 0.80,
    'max_drawdown_soft_limit': -0.35,
    'recovery_days_soft_limit': 252,
    'volatility_drag_model': 'log_growth_proxy = mean_return - 0.5 * volatility^2',
    'default_turnover_cost_rate': DEFAULT_TURNOVER_COST_RATE,
    'trading_cogs_model': 'annual_trading_cogs = daily_turnover * 0.003 * 252 when explicit costs are missing',
    'risk_capital_model': 'risk_capital_required = 2.0 * volatility unless VaR/ES is available',
    'drawdown_provision_model': 'drawdown_provision = abs(max_drawdown) / expected_drawdown_cycle_years',
    'default_required_return_on_risk_capital': 0.03,
    'default_expected_drawdown_cycle_years': 6.0,
    'business_analogy': {
        'revenue': 'long-side expected return / risk premium',
        'cogs': 'transaction cost, explicit impact cost, and turnover cost',
        'volatility_drag': 'stochastic-process drag on geometric growth, not direct COGS',
        'risk_capital': 'capital buffer implied by VaR/ES or volatility',
        'capital_impairment': 'maximum drawdown / asset impairment',
        'drawdown_provision': 'strategic risk reserve calibrated by drawdown, VaR, ES, and cycle length',
        'payback': 'time required to recover from drawdown',
        'risk_budget_driver': 'drawdown depth, recovery time, and confidence in repeatability',
    },
}


def _first_metric(metrics: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _safe_float(metrics.get(key))
        if value is not None:
            return value
    return None


def build_factor_business_review(metrics: dict[str, Any]) -> dict[str, Any]:
    mean_return = _first_metric(metrics, [
        'long_side_annual_return',
        'cost_adjusted_annual_return',
    ])
    volatility = _first_metric(metrics, [
        'long_side_annual_volatility',
        'cost_adjusted_annual_volatility',
    ])
    sharpe = _first_metric(metrics, [
        'long_side_sharpe',
        'cost_adjusted_long_side_sharpe',
    ])
    max_drawdown = _first_metric(metrics, [
        'group_top_decile_max_drawdown',
        'long_side_max_drawdown',
        'qlib_max_drawdown',
        'max_drawdown',
    ])
    recovery_days = _first_metric(metrics, [
        'group_top_decile_recovery_days',
        'long_side_recovery_days',
        'qlib_recovery_days',
        'drawdown_recovery_days',
        'recovery_days',
    ])
    trading_cogs = _first_metric(metrics, [
        'trading_cogs_annual',
    ])
    turnover = _first_metric(metrics, [
        'long_side_turnover_mean_daily',
        'turnover_mean',
    ])
    trading_cogs_source = 'explicit' if trading_cogs is not None else 'missing'
    if trading_cogs is None and turnover is not None:
        trading_cogs = abs(turnover) * DEFAULT_TURNOVER_COST_RATE * 252
        trading_cogs_source = 'estimated_from_turnover_30bps'
    value_at_risk = _first_metric(metrics, [
        'value_at_risk',
        'var_95',
        'var_99',
        'long_side_var',
    ])
    expected_shortfall = _first_metric(metrics, [
        'expected_shortfall',
        'es_95',
        'es_99',
        'long_side_expected_shortfall',
    ])

    volatility_drag = None
    log_growth_proxy = None
    if mean_return is not None and volatility is not None:
        volatility_drag = -0.5 * volatility * volatility
        log_growth_proxy = mean_return + volatility_drag

    thresholds = LONG_SIDE_PERFORMANCE_THRESHOLDS
    net_revenue_after_cogs = mean_return - trading_cogs if mean_return is not None and trading_cogs is not None else None
    risk_capital_required = None
    if expected_shortfall is not None:
        risk_capital_required = abs(expected_shortfall)
    elif value_at_risk is not None:
        risk_capital_required = abs(value_at_risk)
    elif volatility is not None:
        risk_capital_required = 2.0 * abs(volatility)
    capital_charge = (
        risk_capital_required * thresholds['default_required_return_on_risk_capital']
        if risk_capital_required is not None
        else None
    )
    drawdown_provision = (
        abs(max_drawdown) / thresholds['default_expected_drawdown_cycle_years']
        if max_drawdown is not None
        else None
    )
    economic_net_alpha = None
    if mean_return is not None:
        economic_net_alpha = (
            mean_return
            - (trading_cogs or 0.0)
            + (volatility_drag or 0.0)
            - (capital_charge or 0.0)
            - (drawdown_provision or 0.0)
        )
    calmar = (
        mean_return / abs(max_drawdown)
        if mean_return is not None and max_drawdown not in {None, 0}
        else None
    )
    raroc = (
        economic_net_alpha / risk_capital_required
        if economic_net_alpha is not None and risk_capital_required not in {None, 0}
        else None
    )

    if sharpe is None:
        sharpe_status = 'missing'
    elif sharpe >= thresholds['official_min_sharpe']:
        sharpe_status = 'official_ready'
    elif sharpe >= thresholds['candidate_min_sharpe']:
        sharpe_status = 'candidate'
    else:
        sharpe_status = 'below_threshold'

    if max_drawdown is None:
        drawdown_status = 'missing'
    elif max_drawdown >= thresholds['max_drawdown_soft_limit']:
        drawdown_status = 'acceptable'
    else:
        drawdown_status = 'too_deep'

    if recovery_days is None:
        recovery_status = 'missing'
    elif recovery_days <= thresholds['recovery_days_soft_limit']:
        recovery_status = 'acceptable'
    else:
        recovery_status = 'too_slow'

    drawdown_area = _first_metric(metrics, [
        'cost_adjusted_long_side_drawdown_area',
        'long_side_drawdown_area',
    ])
    normalized_drawdown_area = _first_metric(metrics, [
        'cost_adjusted_long_side_normalized_drawdown_area',
        'long_side_normalized_drawdown_area',
    ])
    max_drawdown_episode_area = _first_metric(metrics, [
        'cost_adjusted_long_side_max_drawdown_episode_area',
        'long_side_max_drawdown_episode_area',
    ])
    recovery_pain_area = _first_metric(metrics, [
        'cost_adjusted_long_side_recovery_pain_area',
        'long_side_recovery_pain_area',
    ])
    if normalized_drawdown_area is None:
        drawdown_area_status = 'missing'
    elif normalized_drawdown_area < 0.03:
        drawdown_area_status = 'acceptable'
    elif normalized_drawdown_area <= 0.08:
        drawdown_area_status = 'elevated'
    else:
        drawdown_area_status = 'high'

    return {
        'thresholds': thresholds,
        'metric_unit_policy': {
            'return_unit': 'annualized',
            'volatility_unit': 'annualized',
            'cost_unit': 'annualized',
            'turnover_unit': 'daily_mean',
            'source': 'Step4 long_side_performance contract',
        },
        'factor_business_quality': {
            'gross_revenue': mean_return,
            'trading_cogs': trading_cogs,
            'trading_cogs_source': trading_cogs_source,
            'default_turnover_cost_rate': DEFAULT_TURNOVER_COST_RATE,
            'turnover_proxy': turnover,
            'net_revenue_after_cogs': net_revenue_after_cogs,
            'cogs_status': 'explicit_or_estimated' if trading_cogs is not None else 'missing_turnover_and_explicit_trading_cost',
            'volatility': volatility,
            'volatility_drag': volatility_drag,
            'geometric_profit_proxy': log_growth_proxy,
            'risk_capital_required': risk_capital_required,
            'capital_charge': capital_charge,
            'value_at_risk': value_at_risk,
            'expected_shortfall': expected_shortfall,
            'capital_impairment': max_drawdown,
            'drawdown_geometry': {
                'drawdown_area': drawdown_area,
                'normalized_drawdown_area': normalized_drawdown_area,
                'max_drawdown_episode_area': max_drawdown_episode_area,
                'recovery_pain_area': recovery_pain_area,
                'status': drawdown_area_status,
                'interpretation': 'area measures total underwater investor pain; smaller is better',
            },
            'drawdown_provision': drawdown_provision,
            'payback_days': recovery_days,
            'economic_net_alpha': economic_net_alpha,
            'calmar_ratio': calmar,
            'raroc': raroc,
            'cost_basis_status': (
                'complete_enough'
                if trading_cogs is not None and (value_at_risk is not None or expected_shortfall is not None)
                else 'incomplete_cost_basis'
            ),
        },
        'revenue_proxy_mean_return': mean_return,
        'trading_cogs': trading_cogs,
        'net_revenue_after_cogs': net_revenue_after_cogs,
        'volatility_proxy': volatility,
        'volatility_drag': volatility_drag,
        'geometric_profit_proxy': log_growth_proxy,
        'risk_capital_required': risk_capital_required,
        'capital_charge': capital_charge,
        'drawdown_provision': drawdown_provision,
        'economic_net_alpha': economic_net_alpha,
        'sharpe_ratio': sharpe,
        'sharpe_status': sharpe_status,
        'capital_expenditure_proxy_max_drawdown': max_drawdown,
        'drawdown_geometry': {
            'drawdown_area': drawdown_area,
            'normalized_drawdown_area': normalized_drawdown_area,
            'max_drawdown_episode_area': max_drawdown_episode_area,
            'recovery_pain_area': recovery_pain_area,
            'status': drawdown_area_status,
            'interpretation': (
                'area measures total underwater investor pain; smaller is better. '
                'If normalized_drawdown_area is elevated or high, holder experience remains poor even if max drawdown alone is acceptable.'
            ),
        },
        'drawdown_status': drawdown_status,
        'depreciation_or_payback_proxy_recovery_days': recovery_days,
        'recovery_status': recovery_status,
        'risk_budget_note': (
            'Risk budget should follow Sharpe, explicit trading COGS, volatility drag, risk capital, max drawdown, and recovery time. '
            'A factor can have positive revenue but still be unfinanceable if economic net alpha is weak.'
        ),
    }


def build_long_side_adoption_review(metrics: dict[str, Any]) -> dict[str, Any]:
    """Long-only adoption policy: risk-adjusted long-side evidence is primary."""
    rank_ic = _safe_float(metrics.get('rank_ic_mean'))
    rank_ic_ir = _safe_float(metrics.get('rank_ic_ir'))
    top = _safe_float(metrics.get('long_side_annual_return'))
    bottom = _safe_float(metrics.get('group_bottom_decile_mean_return'))
    spread = _safe_float(metrics.get('group_long_short_spread_mean'))
    spread_ir = _safe_float(metrics.get('group_long_short_spread_ir'))
    business_review = build_factor_business_review(metrics)
    sharpe_status = business_review.get('sharpe_status')
    drawdown_status = business_review.get('drawdown_status')

    if top is None:
        status = 'unknown'
        verdict = 'Long-side evidence is missing; do not promote.'
    elif sharpe_status == 'missing':
        status = 'unknown'
        verdict = 'Long-side revenue evidence exists but Sharpe evidence is missing; do not promote until Step4 emits risk-adjusted long-side performance.'
    elif top > 0 and sharpe_status == 'official_ready' and drawdown_status != 'too_deep' and (rank_ic is None or rank_ic > 0):
        status = 'official_ready'
        verdict = 'Highest-score long side is positive, Sharpe clears the official threshold, and drawdown is not beyond the soft limit.'
    elif top > 0 and sharpe_status in {'candidate', 'official_ready'} and (rank_ic is None or rank_ic > 0):
        status = 'supportive'
        verdict = 'Highest-score long side is positive and risk-adjusted performance clears the candidate Sharpe threshold.'
    elif top > 0 and sharpe_status == 'below_threshold':
        status = 'mixed'
        verdict = 'Highest-score long side is positive, but Sharpe is below the candidate threshold; revenue exists but COGS/capital cost may be too high.'
    elif top > 0:
        status = 'mixed'
        verdict = 'Highest-score long-side bucket is positive, but rank evidence does not cleanly support the direction.'
    else:
        status = 'failed'
        verdict = 'Highest-score long-side bucket is not positive; do not adopt even if short-side or long-short diagnostics look good.'

    if top is not None and bottom is not None:
        if top > bottom:
            monotonicity = 'top_group_above_bottom_group'
        elif top == bottom:
            monotonicity = 'flat_top_vs_bottom'
        else:
            monotonicity = 'top_group_below_bottom_group'
    else:
        monotonicity = 'insufficient_group_evidence'

    return {
        'policy': LONG_ONLY_POLICY,
        'long_side_status': status,
        'verdict': verdict,
        'primary_long_side_metric': {
            'name': 'long_side_sharpe_ratio',
            'value': business_review.get('sharpe_ratio'),
            'interpretation': 'Primary adoption metric for the long side. Raw return is revenue; Sharpe accounts for volatility cost.',
        },
        'secondary_long_side_revenue_metric': {
            'name': 'long_side_annual_return',
            'value': top,
            'interpretation': 'Annualized highest-score long-side proxy return; revenue proxy only, not sufficient for official admission.',
        },
        'factor_as_business_review': business_review,
        'monotonicity_diagnostic': monotonicity,
        'diagnostic_only_metrics': {
            'group_bottom_decile_mean_return': bottom,
            'group_long_short_spread_mean': spread,
            'group_long_short_spread_ir': spread_ir,
            'rank_ic_mean': rank_ic,
            'rank_ic_ir': rank_ic_ir,
        },
        'adoption_rule': (
            'Official adoption requires risk-adjusted long-side evidence: positive long-side revenue, Sharpe above the official threshold, '
            'acceptable drawdown/recovery, and a defensible monotonic economic expression. Short-leg profits, long-short spreads, '
            'and direct decile portfolios are diagnostics only.'
        ),
    }


def build_metric_interpretation(metrics: dict[str, Any], payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rank_ic = _safe_float(metrics.get('rank_ic_mean'))
    rank_ic_ir = _safe_float(metrics.get('rank_ic_ir'))
    pearson_ic = _safe_float(metrics.get('pearson_ic_mean'))
    top_return = _safe_float(metrics.get('long_side_annual_return'))
    bottom_return = _safe_float(metrics.get('group_bottom_decile_mean_return'))
    spread = _safe_float(metrics.get('group_long_short_spread_mean'))
    spread_ir = _safe_float(metrics.get('group_long_short_spread_ir'))
    final_account = _safe_float(metrics.get('qlib_final_account'))
    mean_return = _safe_float(metrics.get('qlib_mean_return'))
    turnover_rows = _safe_float(metrics.get('qlib_nonzero_turnover_rows'))
    long_side_review = build_long_side_adoption_review(metrics)
    business_review = long_side_review.get('factor_as_business_review') or {}
    sharpe = _safe_float(business_review.get('sharpe_ratio'))
    max_drawdown = _safe_float(business_review.get('capital_expenditure_proxy_max_drawdown'))
    recovery_days = _safe_float(business_review.get('depreciation_or_payback_proxy_recovery_days'))
    log_growth_proxy = _safe_float(business_review.get('geometric_profit_proxy'))

    positives: list[str] = []
    negatives: list[str] = []
    ambiguities: list[str] = []

    if not metrics:
        ambiguities.append('No Step4 backend headline metrics were available; Step6 can enforce research policy but cannot promote or finish evidence interpretation.')

    if rank_ic is not None:
        if rank_ic > 0:
            positives.append(f'rank_ic_mean={rank_ic:.6f} is positive, so the raw cross-sectional ordering contains directional information.')
        else:
            negatives.append(f'rank_ic_mean={rank_ic:.6f} is not positive, so the raw ranking evidence does not support the current signal direction.')
    if rank_ic_ir is not None:
        if rank_ic_ir >= 0.3:
            positives.append(f'rank_ic_ir={rank_ic_ir:.3f} is usable for a first-pass daily factor, but not strong enough to ignore robustness checks.')
        elif rank_ic_ir > 0:
            ambiguities.append(f'rank_ic_ir={rank_ic_ir:.3f} is positive but weak; it needs regime and turnover checks before promotion.')
        else:
            negatives.append(f'rank_ic_ir={rank_ic_ir:.3f} is weak or negative.')
    if pearson_ic is not None and rank_ic is not None:
        if abs(pearson_ic) < abs(rank_ic):
            ambiguities.append('Pearson IC is weaker than Rank IC; the expression may be ordinal rather than linearly monotonic, so revision should improve the factor expression itself rather than switch to rank/decile trading.')
    if top_return is not None:
        if top_return > 0:
            positives.append(f'long-side highest-score group mean return={top_return:.6f} is positive; this is revenue evidence but no longer sufficient alone for adoption.')
        else:
            negatives.append(f'long-side highest-score group mean return={top_return:.6f} is not positive; this blocks adoption regardless of short-leg or long-short diagnostics.')
    if sharpe is not None:
        thresholds = LONG_SIDE_PERFORMANCE_THRESHOLDS
        if sharpe >= thresholds['official_min_sharpe']:
            positives.append(f'long-side Sharpe={sharpe:.3f} clears the official threshold {thresholds["official_min_sharpe"]:.2f}.')
        elif sharpe >= thresholds['candidate_min_sharpe']:
            positives.append(f'long-side Sharpe={sharpe:.3f} clears the candidate threshold {thresholds["candidate_min_sharpe"]:.2f}, but still needs more evidence for official admission.')
        else:
            negatives.append(f'long-side Sharpe={sharpe:.3f} is below the candidate threshold {thresholds["candidate_min_sharpe"]:.2f}; improve risk-adjusted performance rather than raw return only.')
    else:
        ambiguities.append('Long-side Sharpe is missing; Step6 cannot promote from raw long-side return alone.')
    if log_growth_proxy is not None:
        if log_growth_proxy > 0:
            positives.append(f'volatility-drag adjusted growth proxy={log_growth_proxy:.6f} is positive under mean - 0.5*sigma^2.')
        else:
            negatives.append(f'volatility-drag adjusted growth proxy={log_growth_proxy:.6f} is not positive; volatility COGS may consume the apparent return.')
    if max_drawdown is not None:
        if max_drawdown >= LONG_SIDE_PERFORMANCE_THRESHOLDS['max_drawdown_soft_limit']:
            positives.append(f'max_drawdown={max_drawdown:.3f} is within the soft capital-cost limit {LONG_SIDE_PERFORMANCE_THRESHOLDS["max_drawdown_soft_limit"]:.2f}.')
        else:
            negatives.append(f'max_drawdown={max_drawdown:.3f} breaches the soft capital-cost limit {LONG_SIDE_PERFORMANCE_THRESHOLDS["max_drawdown_soft_limit"]:.2f}; reduce drawdown before promotion.')
    else:
        ambiguities.append('Max drawdown is missing; risk budget cannot be assigned confidently.')
    if recovery_days is not None:
        if recovery_days <= LONG_SIDE_PERFORMANCE_THRESHOLDS['recovery_days_soft_limit']:
            positives.append(f'recovery_days={recovery_days:.0f} is within the soft payback limit.')
        else:
            negatives.append(f'recovery_days={recovery_days:.0f} is longer than the soft payback limit; the factor may not survive its drawdown cycle.')
    if top_return is not None and bottom_return is not None and top_return <= bottom_return:
        negatives.append('Highest-score group does not outperform the lowest-score group; the expression does not yet show the desired monotonic economic direction.')
    if spread is not None:
        if spread > 0:
            ambiguities.append(f'group long-short spread mean={spread:.6f} is positive, but this is diagnostic only because short selling and direct decile trading are not allowed.')
        else:
            ambiguities.append(f'group long-short spread mean={spread:.6f} is not positive; use this only to diagnose expression monotonicity, not as a trading objective.')
    if spread_ir is not None:
        if spread_ir > 0.2:
            ambiguities.append(f'group long-short spread IR={spread_ir:.3f} is positive, but cannot justify adoption without long-side evidence.')
        elif spread_ir > 0:
            ambiguities.append(f'group long-short spread IR={spread_ir:.3f} is only marginally positive.')
        else:
            ambiguities.append(f'group long-short spread IR={spread_ir:.3f} is not supportive as a monotonicity diagnostic.')
    if final_account is not None:
        if final_account >= 100_000_000:
            positives.append(f'native qlib final_account={final_account:.2f} is above the 100M initial account.')
        else:
            negatives.append(f'native qlib final_account={final_account:.2f} is below the 100M initial account; the signal may predict returns but the current TopkDropout implementation does not yet monetize it after trading frictions.')
    if mean_return is not None and final_account is not None and mean_return > 0 and final_account < 100_000_000:
        ambiguities.append('Native mean_return is positive while final account is below initial capital; this points to turnover/cost/path-dependence rather than a clean alpha failure.')
    if turnover_rows is not None and turnover_rows > 0:
        ambiguities.append(f'native qlib has {int(turnover_rows)} nonzero turnover days, so implementation cost and rebalance mechanics are material to the verdict.')

    qlib = payloads.get('qlib_backtest') or {}
    readiness = qlib.get('readiness') or {}
    if readiness.get('benchmark', {}).get('empty') is True:
        ambiguities.append('Benchmark is an empty Series, so native qlib output is absolute-strategy evidence rather than benchmark-relative alpha evidence.')

    verdict = 'supportive'
    if negatives and positives:
        verdict = 'mixed'
    elif negatives:
        verdict = 'negative'
    elif ambiguities and not positives:
        verdict = 'inconclusive'
    if long_side_review['long_side_status'] == 'failed':
        verdict = 'negative'
    elif long_side_review['long_side_status'] == 'unknown' and verdict == 'supportive':
        verdict = 'inconclusive'

    return {
        'verdict': verdict,
        'positive_evidence': positives,
        'negative_evidence': negatives,
        'ambiguities': ambiguities,
        'raw_metrics_used': metrics if metrics else {'metrics_available': False},
        'long_side_adoption_review': long_side_review,
    }


def _direction(value: float | None) -> str:
    if value is None:
        return 'missing'
    if value > 0:
        return 'positive'
    if value < 0:
        return 'negative'
    return 'neutral'


def _backend_bucket(backend_runs: list[dict[str, Any]], statuses: set[str]) -> list[str]:
    return [
        str(item.get('backend'))
        for item in backend_runs
        if str(item.get('status')) in statuses and item.get('backend')
    ]


def build_evidence_audit(bundle: dict[str, Any], payloads: dict[str, dict[str, Any]], headline_metrics: dict[str, Any]) -> dict[str, Any]:
    run_master = bundle['factor_run_master']
    case = bundle['factor_case_master']
    evaluation = bundle['factor_evaluation']
    backend_runs = (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    successful = _backend_bucket(backend_runs, {'success'})
    partial = _backend_bucket(backend_runs, {'partial'})
    skipped = _backend_bucket(backend_runs, {'skipped'})
    failed = _backend_bucket(backend_runs, {'failed'})
    self_quant_status = next((str(item.get('status')) for item in backend_runs if item.get('backend') == 'self_quant_analyzer'), 'missing')
    self_quant_present = self_quant_status in {'success', 'partial'} and bool(payloads.get('self_quant_analyzer'))
    all_skipped = bool(backend_runs) and not successful and not partial
    payload_missing = [
        str(item.get('backend'))
        for item in backend_runs
        if str(item.get('status')) in {'success', 'partial'} and item.get('backend') not in payloads
    ]
    fallback_or_stub = [
        str(item.get('backend'))
        for item in backend_runs
        if any(token in str(item).lower() for token in ['stub', 'fallback', 'placeholder'])
    ]

    rank_ic = _safe_float(headline_metrics.get('rank_ic_mean'))
    long_return = _safe_float(headline_metrics.get('long_side_annual_return'))
    top_daily = _safe_float(headline_metrics.get('group_top_decile_mean_return'))
    bottom_daily = _safe_float(headline_metrics.get('group_bottom_decile_mean_return'))
    spread = _safe_float(headline_metrics.get('group_long_short_spread_mean'))
    short_side_dominance = bool(
        (spread is not None and spread > 0)
        and (
            (long_return is not None and long_return <= 0)
            or (top_daily is not None and top_daily <= 0)
            or (bottom_daily is not None and bottom_daily < 0 and (top_daily is None or abs(bottom_daily) > abs(top_daily)))
        )
    )
    if rank_ic is None or (long_return is None and top_daily is None):
        ic_long_side_consistency = 'unknown'
    elif (rank_ic > 0 and (long_return or top_daily or 0) > 0) or (rank_ic < 0 and (long_return or top_daily or 0) < 0):
        ic_long_side_consistency = 'consistent'
    elif rank_ic == 0 or (long_return or top_daily or 0) == 0:
        ic_long_side_consistency = 'mixed'
    else:
        ic_long_side_consistency = 'conflicting'
    if top_daily is None or bottom_daily is None:
        monotonicity_support = 'unknown'
    elif top_daily > bottom_daily and top_daily > 0:
        monotonicity_support = 'strong'
    elif top_daily > bottom_daily:
        monotonicity_support = 'partial'
    else:
        monotonicity_support = 'weak'
    if ic_long_side_consistency == 'consistent' and monotonicity_support in {'strong', 'partial'} and not short_side_dominance:
        metric_verdict = 'supportive'
    elif short_side_dominance or ic_long_side_consistency == 'conflicting':
        metric_verdict = 'negative'
    elif ic_long_side_consistency == 'unknown':
        metric_verdict = 'inconclusive'
    else:
        metric_verdict = 'mixed'

    required_long_side = [
        'long_side_annual_return',
        'long_side_annual_volatility',
        'long_side_sharpe',
        'long_side_max_drawdown',
        'long_side_recovery_days',
        'long_side_turnover_mean_daily',
        'trading_cogs_daily',
        'trading_cogs_annual',
        'cost_adjusted_annual_return',
        'cost_adjusted_long_side_sharpe',
    ]
    missing_long = [key for key in required_long_side if headline_metrics.get(key) is None]
    sharpe = _safe_float(headline_metrics.get('long_side_sharpe'))
    max_drawdown = _safe_float(headline_metrics.get('long_side_max_drawdown'))
    recovery_days = _safe_float(headline_metrics.get('long_side_recovery_days'))
    turnover = _safe_float(headline_metrics.get('long_side_turnover_mean_daily') or headline_metrics.get('turnover_mean'))
    explicit_cogs_daily = _safe_float(headline_metrics.get('trading_cogs_daily'))
    turnover_times_30bps_daily = abs(turnover) * DEFAULT_TURNOVER_COST_RATE if turnover is not None else None
    cogs_daily = explicit_cogs_daily if explicit_cogs_daily is not None else turnover_times_30bps_daily
    cogs_annual = _safe_float(headline_metrics.get('trading_cogs_annual'))
    if cogs_annual is None and cogs_daily is not None:
        cogs_annual = cogs_daily * 252
    cost_adjusted_return = _safe_float(headline_metrics.get('cost_adjusted_annual_return'))
    cost_adjusted_sharpe = _safe_float(headline_metrics.get('cost_adjusted_long_side_sharpe'))

    if sharpe is None:
        sharpe_status = 'missing'
    elif sharpe >= LONG_SIDE_PERFORMANCE_THRESHOLDS['official_min_sharpe']:
        sharpe_status = 'official_ready'
    elif sharpe >= LONG_SIDE_PERFORMANCE_THRESHOLDS['candidate_min_sharpe']:
        sharpe_status = 'candidate'
    elif sharpe >= 0:
        sharpe_status = 'weak'
    else:
        sharpe_status = 'negative'
    if max_drawdown is None:
        drawdown_status = 'missing'
    elif max_drawdown < -0.50:
        drawdown_status = 'hard_breach'
    elif max_drawdown < LONG_SIDE_PERFORMANCE_THRESHOLDS['max_drawdown_soft_limit']:
        drawdown_status = 'soft_breach'
    else:
        drawdown_status = 'acceptable'
    if recovery_days is None:
        recovery_status = 'missing'
    elif recovery_days <= LONG_SIDE_PERFORMANCE_THRESHOLDS['recovery_days_soft_limit']:
        recovery_status = 'acceptable'
    else:
        recovery_status = 'slow'
    if cost_adjusted_return is None and cost_adjusted_sharpe is None:
        cost_adjusted_status = 'missing'
    elif (cost_adjusted_return is not None and cost_adjusted_return < 0) or (cost_adjusted_sharpe is not None and cost_adjusted_sharpe < 0):
        cost_adjusted_status = 'negative'
    else:
        cost_adjusted_status = 'positive'
    if missing_long:
        long_side_verdict = 'blocked'
    elif long_return is not None and long_return > 0 and sharpe_status in {'official_ready', 'candidate'} and cost_adjusted_status == 'positive':
        long_side_verdict = 'supportive'
    elif long_return is not None and long_return > 0:
        long_side_verdict = 'mixed'
    elif long_return is not None:
        long_side_verdict = 'weak'
    else:
        long_side_verdict = 'blocked'

    diagnostic = run_master.get('diagnostic_summary') or {}
    row_count = _safe_float(diagnostic.get('row_count') or run_master.get('row_count'))
    date_count = _safe_float(diagnostic.get('date_count') or run_master.get('date_count'))
    ticker_count = _safe_float(diagnostic.get('ticker_count') or run_master.get('ticker_count'))
    nan_ratio = _safe_float(diagnostic.get('nan_ratio') or diagnostic.get('factor_value_nan_ratio'))
    low_variance = bool(diagnostic.get('constant_factor') or diagnostic.get('low_variance_factor'))
    factor_value_verdict = 'unknown'
    if row_count is not None and row_count <= 0:
        factor_value_verdict = 'blocked'
    elif low_variance:
        factor_value_verdict = 'weak'
    elif row_count is not None and date_count is not None and ticker_count is not None:
        factor_value_verdict = 'usable'

    suspicions: list[str] = []
    if all_skipped:
        suspicions.append('all_backends_skipped')
    if not self_quant_present:
        suspicions.append('self_quant_required_evidence_missing')
    if payload_missing:
        suspicions.append('backend_payload_missing:' + ','.join(payload_missing))
    if fallback_or_stub:
        suspicions.append('fallback_or_stub_backend_detected:' + ','.join(fallback_or_stub))
    case_quality = case.get('evidence_quality') or {}
    if case_quality.get('identity_chain_verified') is False:
        suspicions.append('step5_identity_chain_not_verified')
    if not case_quality.get('long_side_metrics_present', True):
        suspicions.append('step5_long_side_metrics_missing')
    if not run_master.get('implementation_mode_decision'):
        suspicions.append('step3b_mode_decision_missing_or_not_propagated')
    if (run_master.get('implementation_mode_decision') or {}).get('selected_mode') == 'blocked':
        suspicions.append('step3b_implementation_blocked')

    gross_return = _safe_float(headline_metrics.get('long_side_annual_return'))
    cogs_destroy_alpha = bool(
        gross_return is not None
        and gross_return > 0
        and cost_adjusted_return is not None
        and cost_adjusted_return < 0
    )
    high_turnover = bool(turnover is not None and turnover > 0.5)
    if cogs_destroy_alpha:
        suspicions.append('trading_cost_destroyed_positive_gross_alpha')
    if high_turnover:
        suspicions.append('high_turnover_cost_risk')

    if all_skipped or not self_quant_present or missing_long or factor_value_verdict == 'blocked' or case_quality.get('identity_chain_verified') is False:
        evidence_verdict = 'blocked'
    elif cogs_destroy_alpha or high_turnover or failed or skipped or metric_verdict in {'mixed', 'negative', 'inconclusive'}:
        evidence_verdict = 'usable_with_warnings'
    else:
        evidence_verdict = 'usable'

    return {
        'backend_integrity': {
            'run_status': run_master.get('run_status'),
            'successful_backends': successful,
            'partial_backends': partial,
            'skipped_backends': skipped,
            'failed_backends': failed,
            'self_quant_required_and_present': self_quant_present,
            'all_backends_skipped': all_skipped,
            'payload_missing_backends': payload_missing,
            'fallback_or_stub_backends': fallback_or_stub,
            'backend_verdict': 'blocked' if all_skipped or not self_quant_present else 'usable_with_warnings' if failed or skipped or partial else 'usable',
        },
        'metric_consistency': {
            'rank_ic_direction': _direction(rank_ic),
            'long_side_direction': _direction(long_return if long_return is not None else top_daily),
            'short_side_dominance_suspected': short_side_dominance,
            'ic_long_side_consistency': ic_long_side_consistency,
            'monotonicity_support': monotonicity_support,
            'metric_verdict': metric_verdict,
        },
        'factor_value_health': {
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'nan_ratio': nan_ratio if nan_ratio is not None else 'unknown',
            'constant_or_low_variance_suspected': low_variance,
            'rolling_window_initial_nan_expected': 'unknown',
            'factor_value_verdict': factor_value_verdict,
        },
        'long_side_evidence_quality': {
            'long_side_return_positive': bool(long_return is not None and long_return > 0),
            'sharpe_status': sharpe_status,
            'drawdown_status': drawdown_status,
            'recovery_status': recovery_status,
            'cost_adjusted_status': cost_adjusted_status,
            'missing_long_side_metrics': missing_long,
            'long_side_verdict': long_side_verdict,
        },
        'cost_and_turnover_risk': {
            'turnover': turnover,
            'trading_cogs_rule': 'trading COGS = turnover * 0.3%',
            'turnover_times_30bps_daily': turnover_times_30bps_daily,
            'trading_cogs_daily_used': cogs_daily,
            'trading_cogs_annual_used': cogs_annual,
            'gross_annual_return': gross_return,
            'cost_adjusted_annual_return': cost_adjusted_return,
            'cost_adjusted_long_side_sharpe': cost_adjusted_sharpe,
            'turnover_too_high': high_turnover,
            'cogs_destroy_alpha': cogs_destroy_alpha,
            'high_revenue_bad_business_factor': cogs_destroy_alpha,
        },
        'data_or_implementation_suspicions': suspicions,
        'evidence_verdict': evidence_verdict,
    }


def _step6_spec_text(bundle: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    spec = bundle.get('factor_spec_master') or {}
    idea = bundle.get('alpha_idea_master') or {}
    canonical = spec.get('canonical_spec') or {}
    parts = [
        str(bundle['factor_run_master'].get('factor_id') or ''),
        str(bundle['factor_run_master'].get('report_id') or ''),
        str(canonical.get('formula_text') or ''),
        ' '.join(str(item) for item in _as_list(canonical.get('required_inputs'))),
        ' '.join(str(item) for item in _as_list(canonical.get('operators'))),
        ' '.join(str(item) for item in _as_list(canonical.get('time_series_steps'))),
        ' '.join(str(item) for item in _as_list(canonical.get('cross_sectional_steps'))),
        ' '.join(str(item) for item in _as_list(canonical.get('implementation_assumptions'))),
        json.dumps(idea, ensure_ascii=False),
    ]
    return ' '.join(parts).lower(), canonical


def mechanism_math_contract_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    spec = bundle.get('factor_spec_master') or {}
    case = bundle.get('factor_case_master') or {}
    handoff = bundle.get('handoff_to_step6') or {}
    canonical = spec.get('canonical_spec') or {}
    stale_failures: list[dict[str, str]] = []
    for candidate in [
        spec.get('mechanism_math_contract'),
        canonical.get('mechanism_math_contract'),
        case.get('mechanism_math_contract'),
        handoff.get('mechanism_math_contract'),
    ]:
        if isinstance(candidate, dict) and candidate:
            failures = validate_mechanism_math_contract(candidate)
            if not failures:
                return candidate
            stale_failures.extend(failures)
    rebuilt = build_mechanism_math_contract(spec or canonical or bundle)
    if stale_failures:
        evidence = rebuilt.get('classification_evidence')
        if not isinstance(evidence, dict):
            evidence = {}
        evidence['rebuilt_from_stale_or_invalid_upstream_contract'] = True
        evidence['upstream_contract_failure_codes'] = sorted({str(item.get('code')) for item in stale_failures if item.get('code')})
        rebuilt['classification_evidence'] = evidence
    return rebuilt


def mechanism_math_contract_v2_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    spec = bundle.get('factor_spec_master') or {}
    case = bundle.get('factor_case_master') or {}
    handoff = bundle.get('handoff_to_step6') or {}
    canonical = spec.get('canonical_spec') or {}
    for candidate in [
        spec.get('mechanism_math_contract_v2'),
        canonical.get('mechanism_math_contract_v2'),
        case.get('mechanism_math_contract_v2'),
        handoff.get('mechanism_math_contract_v2'),
    ]:
        if isinstance(candidate, dict) and candidate and not validate_mechanism_math_contract_v2(candidate):
            return candidate
    return build_mechanism_math_contract_v2(spec or canonical or bundle)


def mechanism_math_summary_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    revision_ops = contract.get('revision_operators') if isinstance(contract.get('revision_operators'), list) else []
    first_op = revision_ops[0] if revision_ops and isinstance(revision_ops[0], dict) else {}
    model_family = contract.get('model_family') or 'other'
    math_toolkits = contract.get('math_toolkits') or []
    toolkit_family = next(
        (
            str(item)
            for item in math_toolkits
            if str(item) in {
                'stochastic_process',
                'state_space',
                'valuation_identity',
                'cross_sectional_statistics',
                'linear_factor_projection',
                'functional_filter',
                'constraint_model',
            }
        ),
        None,
    )
    return {
        'math_model_status': contract.get('math_model_status') or 'under_specified',
        'model_family': model_family,
        'economic_mechanism_family': contract.get('economic_mechanism_family') or model_family,
        'math_tool_family': contract.get('math_tool_family') or toolkit_family or model_family,
        'model_equation_family': contract.get('model_equation_family') or 'under_specified',
        'math_toolkits': math_toolkits,
        'state_or_object': contract.get('state_or_object') or 'under_specified',
        'factor_as_estimator': contract.get('factor_as_estimator') or 'under_specified',
        'target_functional': contract.get('target_functional') or 'under_specified',
        'process_hypothesis': contract.get('process_hypothesis') or 'under_specified',
        'latent_state': contract.get('latent_state') or contract.get('state_or_object') or 'under_specified',
        'observable_estimator': contract.get('observable_estimator') or contract.get('factor_as_estimator') or 'under_specified',
        'conditional_distribution_hypothesis': contract.get('conditional_distribution_hypothesis') or 'under_specified',
        'relationship_shape': contract.get('relationship_shape') or 'under_specified',
        'monotonicity_claim': contract.get('monotonicity_claim') or 'under_specified',
        'expected_metric_signature': contract.get('expected_metric_signature') or {},
        'metric_signature_match': contract.get('metric_signature_match') or 'under_specified',
        'mechanism_falsification_tests': contract.get('mechanism_falsification_tests') or [],
        'revision_operator_summary': first_op,
        'under_specified_reason': contract.get('under_specified_reason'),
        'next_human_research_question': contract.get('next_human_research_question'),
    }


def _contains_any(text: str, tokens: set[str]) -> bool:
    return any(token in text for token in tokens)


def _classify_mechanism_family(text: str, canonical: dict[str, Any]) -> tuple[str, list[str], str]:
    operators = {str(item).lower() for item in _as_list(canonical.get('operators'))}
    inputs = {str(item).lower() for item in _as_list(canonical.get('required_inputs'))}
    price_fields = {'open', 'high', 'low', 'close', 'vwap', 'price', 'return', 'returns', 'pct_chg'}
    volume_fields = {'volume', 'vol', 'amount', 'turnover', 'liquidity'}
    evidence: list[str] = []

    has_price = bool(inputs & price_fields) or _contains_any(text, price_fields)
    has_volume = bool(inputs & volume_fields) or _contains_any(text, volume_fields)
    has_corr = (
        'correlation' in operators
        or 'corr' in operators
        or 'covariance' in operators
        or 'cov' in operators
        or 'correlation(' in text
        or 'rolling_corr' in text
        or 'covariance(' in text
        or 'rolling_cov' in text
        or re.search(r'\bcov\s*\(', text) is not None
    )
    if has_corr and has_price and has_volume:
        evidence.extend(['correlation_operator', 'price_field', 'volume_or_liquidity_field'])
        return 'price_volume_correlation', evidence, 'low'
    if _contains_any(text, {'illiquidity', 'impact', 'spread', 'liquidity', 'turnover', 'amount'}) or (has_volume and not has_price):
        evidence.append('liquidity_or_turnover_terms')
        return 'liquidity_shock', evidence, 'medium'
    if _contains_any(text, {'stddev', 'std', 'variance', 'volatility', 'atr', 'range', 'high-low'}):
        evidence.append('volatility_or_range_terms')
        return 'volatility', evidence, 'medium'
    if _contains_any(text, {'reversal', 'overreaction', 'mean_revert', 'mean revert'}) or ('delta' in operators and ('-1' in text or 'negative' in text)):
        evidence.append('short_window_reversal_terms')
        return 'reversal', evidence, 'medium'
    if _contains_any(text, {'momentum', 'trend', 'strength', 'continuation'}) and (has_price or has_volume):
        evidence.append('trend_or_confirmation_terms')
        return 'momentum_confirmation', evidence, 'medium'
    if _contains_any(text, {'cashflow', 'cash_flow', 'earnings', 'revenue', 'profit', 'margin', 'contract liability', 'liability', 'inventory', 'fundamental'}):
        evidence.append('fundamental_information_terms')
        return 'fundamental_quality', evidence, 'medium'
    if _contains_any(text, {'index inclusion', 'transfer board', 'convertible', 'etf', 'mandate', 'insurance', 'public fund', 'constraint', 'northbound'}):
        evidence.append('event_or_institutional_constraint_terms')
        return 'event_constraint', evidence, 'medium'
    return 'other', ['no_specific_mechanism_family_rule_matched'], 'high'


def _return_source_for_family(factor_family: str, text: str, uncertainty: str) -> str:
    if uncertainty == 'high' and factor_family == 'other':
        return 'unknown'
    if factor_family in {'price_volume_correlation', 'reversal', 'momentum_confirmation', 'liquidity_shock', 'volatility'}:
        return 'behavioral_microstructure'
    if factor_family == 'fundamental_quality':
        return 'information_advantage'
    if factor_family == 'event_constraint':
        return 'constraint_driven_arbitrage'
    if _contains_any(text, {'risk premium', 'style', 'value', 'size', 'beta', 'lowvol'}):
        return 'risk_premium'
    return 'mixed' if uncertainty != 'high' else 'unknown'


def build_mechanism_analysis(
    bundle: dict[str, Any],
    payloads: dict[str, dict[str, Any]],
    headline_metrics: dict[str, Any],
    evidence_audit: dict[str, Any],
    retrieval_context: dict[str, Any],
) -> dict[str, Any]:
    del payloads
    text, canonical = _step6_spec_text(bundle)
    mechanism_math_contract = mechanism_math_contract_from_bundle(bundle)
    mechanism_math_contract_v2 = mechanism_math_contract_v2_from_bundle(bundle)
    mechanism_math_summary = mechanism_math_summary_from_contract(mechanism_math_contract)
    factor_family, classification_evidence_items, uncertainty = _classify_mechanism_family(text, canonical)
    formula_understanding = mechanism_math_contract.get('formula_understanding') if isinstance(mechanism_math_contract, dict) else {}
    interaction_structure = str((formula_understanding or {}).get('interaction_structure') or '')
    state_text = ' '.join(
        str(mechanism_math_contract.get(key) or '')
        for key in ('state_or_object', 'factor_as_estimator', 'process_hypothesis', 'latent_state', 'observable_estimator')
    ).lower() if isinstance(mechanism_math_contract, dict) else ''
    if (
        interaction_structure == 'slow_state_x_short_horizon_threshold'
        or all(token in state_text for token in ('slow', 'short', 'threshold'))
    ):
        factor_family = 'reversal'
        classification_evidence_items = [
            'formula_understanding_slow_state_x_short_horizon_threshold',
            'mechanism_math_contract_formula_specific',
        ]
        uncertainty = 'low'
    return_source = _return_source_for_family(factor_family, text, uncertainty)
    if interaction_structure == 'slow_state_x_short_horizon_threshold':
        return_source = 'mixed'
    metrics = evidence_audit.get('metric_consistency') or {}
    long_quality = evidence_audit.get('long_side_evidence_quality') or {}
    cost_risk = evidence_audit.get('cost_and_turnover_risk') or {}
    evidence_verdict = evidence_audit.get('evidence_verdict')
    similar = retrieval_context.get('similar_cases') or []
    similar_success = [
        item for item in similar
        if str(item.get('decision')) == 'promote_official'
        and str(item.get('knowledge_scope') or '') in {'same_factor', 'similar_case'}
    ]
    similar_failure = [item for item in similar if str(item.get('decision')) in {'reject', 'iterate', 'needs_human_review'}]

    if interaction_structure == 'slow_state_x_short_horizon_threshold':
        hypothesis = (
            'The formula models a slow winner or long-window trend state interacting with a short-horizon reversal, '
            'temporary dislocation, or threshold-migration state. The economic claim is that delayed updaters, trend '
            'extrapolators, or liquidity-demand accounts may overpay around the short-state boundary, and the formula '
            'estimates that conditional state from its own long-window return and short-horizon price-threshold features.'
        )
        necessary = [
            'the long-window winner state must change the payoff sign or magnitude of the short-horizon threshold state',
            'the short-horizon sign boundary must map to next-period long-side expected return after costs',
            'turnover around threshold migration must not consume the gross expected payoff',
        ]
        failures = [
            'threshold migration is too noisy and turnover-heavy',
            'the long-window trend state does not condition the short-horizon reversal payoff',
            'observed performance comes from diagnostics rather than high-score long-side expected return',
        ]
    elif factor_family == 'price_volume_correlation':
        hypothesis = (
            'The formula tests whether recent price-position ranks and volume ranks co-move. '
            'The mechanism is behavioral microstructure: volume-confirmed price pressure, exhaustion, or liquidity shock must map monotonically to next-period long-side return, not merely to a long-short diagnostic.'
        )
        necessary = [
            'price-volume co-movement must map monotonically to next-period long-side expected return',
            'the signal must not be driven only by the weak short side',
            'turnover and cost-adjusted return must remain acceptable',
        ]
        failures = [
            'high turnover consumes the gross signal',
            'price-volume correlation captures noisy liquidity shock rather than persistent information',
            'direction flips across regimes',
        ]
    elif factor_family == 'liquidity_shock':
        hypothesis = 'The factor appears to monetize a liquidity or turnover shock; it must show long-side compensation after explicit turnover cost.'
        necessary = ['liquidity shock must predict future long-side return', 'capacity and turnover cost must not erase gross revenue']
        failures = ['transaction cost consumes signal', 'crowding compresses liquidity premium', 'signal concentrates in hard-to-trade names']
    elif factor_family == 'fundamental_quality':
        hypothesis = 'The factor appears to encode delayed fundamental information that the market may incorporate gradually.'
        necessary = ['input timing must be legal', 'fundamental signal must be stale enough for the market to underreact', 'effect must survive industry/regime checks']
        failures = ['market reprices faster', 'accounting feature only works in narrow industries', 'reporting lag is mis-specified']
    elif factor_family == 'event_constraint':
        hypothesis = 'The factor appears to rely on repeated behavior caused by institutional or market-structure constraints.'
        necessary = ['objective constraint must be real and persistent', 'trading path must be executable after cost', 'edge must not be pure one-off event timing']
        failures = ['rule changes remove constraint', 'capacity closes spread', 'execution cost overwhelms expected return']
    else:
        hypothesis = 'Mechanism remains under-specified; Step6 cannot identify a testable return source from the current formula/spec/thesis.'
        necessary = ['human researcher must restate the return source before promotion', 'Step4 long-side evidence alone is insufficient without a testable mechanism']
        failures = ['ambiguous mechanism', 'data-mined transform without stable economic state', 'unexplained regime dependence']

    short_dominance = bool(metrics.get('short_side_dominance_suspected'))
    cost_negative = long_quality.get('cost_adjusted_status') == 'negative' or bool(cost_risk.get('cogs_destroy_alpha'))
    long_negative = long_quality.get('long_side_return_positive') is False
    strong_mechanism_support = bool((canonical.get('mechanism_analysis') or {}).get('strong_mechanism_support'))
    if evidence_verdict == 'blocked' or short_dominance or long_negative:
        fit = 'contradicted'
    elif return_source == 'unknown':
        fit = 'weak'
    elif evidence_verdict == 'usable' and metrics.get('metric_verdict') == 'supportive' and not cost_negative and (similar_success or strong_mechanism_support):
        fit = 'strong'
    elif evidence_verdict in {'usable', 'usable_with_warnings'} and metrics.get('metric_verdict') in {'supportive', 'mixed'}:
        fit = 'partial' if not cost_negative else 'weak'
    else:
        fit = 'weak'

    expected_signature = {
        'rank_ic': 'positive_or_consistent_with_declared_direction',
        'long_side_return': 'positive_high_score_long_side',
        'cost_adjusted_sharpe': 'positive_after_turnover_times_30bps',
        'monotonicity': 'high_score_group_outperforms_without_short_side_dominance',
        'case_support': 'similar failures or successes should change confidence, never bypass evidence gates',
    }
    observed_signature = {
        'rank_ic_direction': metrics.get('rank_ic_direction'),
        'long_side_direction': metrics.get('long_side_direction'),
        'short_side_dominance_suspected': short_dominance,
        'metric_verdict': metrics.get('metric_verdict'),
        'long_side_verdict': long_quality.get('long_side_verdict'),
        'cost_adjusted_status': long_quality.get('cost_adjusted_status'),
        'turnover_too_high': cost_risk.get('turnover_too_high'),
        'similar_success_count': len(similar_success),
        'similar_failure_count': len(similar_failure),
    }
    research_equation = (
        mechanism_math_contract_v2.get('research_equation')
        if isinstance(mechanism_math_contract_v2.get('research_equation'), dict)
        else {}
    )
    equation_status = str(research_equation.get('equation_status') or 'research_conjecture')
    equation_supported = 'supported' if fit in {'strong', 'partial'} and not cost_negative and not short_dominance else (
        'challenged' if fit in {'weak', 'contradicted'} or cost_negative or short_dominance else 'under_specified'
    )
    failed_equation_component = 'none'
    if evidence_verdict == 'blocked':
        failed_equation_component = 'implementation_contract'
    elif cost_negative:
        failed_equation_component = 'trading_cost'
    elif short_dominance or long_negative:
        failed_equation_component = 'observable_estimator'
    elif metrics.get('metric_verdict') in {'negative', 'inconclusive'}:
        failed_equation_component = 'price_process_projection'

    return {
        'return_source': return_source,
        'factor_family': factor_family,
        'mechanism_hypothesis': hypothesis,
        'necessary_conditions': necessary,
        'expected_metric_signature': expected_signature,
        'observed_metric_signature': observed_signature,
        'mechanism_fit': fit,
        'failure_regimes': failures,
        'what_would_change_my_mind': [
            'Cost-adjusted high-score long-side evidence becomes positive and stable across regimes.',
            'Mechanism-specific monotonicity improves without relying on short-side losses.',
            'Comparable cases with verified provenance support the same mechanism under similar turnover and evidence conditions.',
        ],
        'classification_evidence': {
            'matched_rules': classification_evidence_items,
            'formula_text': canonical.get('formula_text'),
            'required_inputs': _as_list(canonical.get('required_inputs')),
            'operators': _as_list(canonical.get('operators')),
            'retrieved_success_cases': len(similar_success),
            'retrieved_failure_cases': len(similar_failure),
            'strong_mechanism_support': strong_mechanism_support,
            'mechanism_math_model_family': mechanism_math_summary.get('model_family'),
            'mechanism_math_status': mechanism_math_summary.get('math_model_status'),
        },
        'classification_uncertainty': uncertainty,
        'mechanism_math_contract': mechanism_math_contract,
        'mechanism_math_contract_v2': mechanism_math_contract_v2,
        'mechanism_math_summary': mechanism_math_summary,
        'research_equation_review': {
            'reviewer_task': 'research_equation_reviewer',
            'equation_status': equation_status,
            'equation_supported_by_metrics': equation_supported,
            'metric_links': {
                'rank_ic': f"rank_ic_direction={metrics.get('rank_ic_direction')}; rank_ic_mean={headline_metrics.get('rank_ic_mean')}",
                'long_side_return': f"long_side_direction={metrics.get('long_side_direction')}; annual_return={headline_metrics.get('long_side_annual_return')}",
                'cost_adjusted_return': f"cost_adjusted_status={long_quality.get('cost_adjusted_status')}; annual_return={headline_metrics.get('cost_adjusted_annual_return')}",
                'turnover': f"turnover_risk={cost_risk.get('turnover_too_high')}; daily_turnover={headline_metrics.get('long_side_turnover_mean_daily') or headline_metrics.get('turnover_mean')}",
                'volatility_drag': f"volatility_drag={headline_metrics.get('volatility_drag')}; annual_volatility={headline_metrics.get('long_side_annual_volatility')}",
                'max_drawdown': f"max_drawdown={headline_metrics.get('long_side_max_drawdown') or headline_metrics.get('cost_adjusted_long_side_max_drawdown')}",
                'recovery_days': f"recovery_days={headline_metrics.get('long_side_recovery_days') or headline_metrics.get('cost_adjusted_long_side_recovery_days')}",
            },
            'failed_equation_component': failed_equation_component,
            'revision_implication': (
                'No research-equation revision is indicated by current model-layer metrics.'
                if failed_equation_component == 'none'
                else f"Revise the {failed_equation_component} layer before promotion."
            ),
        },
        'mechanism_projection_diagnosis': {
            'economic_hypothesis': 'supported' if fit in {'strong', 'partial'} else 'challenged',
            'primary_mechanism_model': 'supported' if fit in {'strong', 'partial'} else 'challenged',
            'stochastic_projection': 'supported' if metrics.get('metric_verdict') in {'supportive', 'mixed'} else 'challenged',
            'observable_estimator': 'supported' if not short_dominance and not long_negative else 'challenged',
            'implementation_data_contract': evidence_verdict,
        },
        'metric_signature_match': {
            'economic_hypothesis': fit,
            'primary_mechanism_model': fit,
            'stochastic_projection': metrics.get('metric_verdict') or 'inconclusive',
            'observable_estimator': long_quality.get('long_side_verdict') or 'inconclusive',
            'implementation_contract': evidence_verdict,
        },
        'model_layer_failure_attribution': [
            layer
            for layer, failed in {
                'economic_hypothesis': fit in {'weak', 'contradicted'},
                'primary_mechanism_model': fit in {'weak', 'contradicted'},
                'stochastic_projection': metrics.get('metric_verdict') in {'negative', 'inconclusive'},
                'observable_estimator': short_dominance or long_negative,
                'implementation_contract': evidence_verdict == 'blocked',
            }.items()
            if failed
        ] or ['none'],
        'revision_model_target': 'implementation_contract' if evidence_verdict == 'blocked' else (
            'observable_estimator' if short_dominance or long_negative else (
                'stochastic_projection' if metrics.get('metric_verdict') in {'negative', 'inconclusive'} else 'primary_mechanism_model'
            )
        ),
    }


def _case_snippet(item: dict[str, Any]) -> str:
    return str(item.get('snippet') or item.get('lesson_hint') or item.get('text') or '').strip()


def build_case_comparison(
    mechanism_analysis: dict[str, Any],
    retrieval_context: dict[str, Any],
    current_identity: dict[str, Any],
    research_memo: dict[str, Any],
) -> dict[str, Any]:
    similar = retrieval_context.get('similar_cases') or []
    current_factor = str(current_identity.get('factor_id') or '')
    current_formula_hash = current_identity.get('formula_hash')
    family = mechanism_analysis.get('factor_family')
    evidence_audit = research_memo.get('evidence_audit') or {}
    cost_risk = evidence_audit.get('cost_and_turnover_risk') or {}
    metrics = evidence_audit.get('metric_consistency') or {}

    same_factor_cases: list[dict[str, Any]] = []
    similar_case_cases: list[dict[str, Any]] = []
    anti_pattern_cases: list[dict[str, Any]] = []
    identity_mismatch_cases: list[dict[str, Any]] = []
    for item in similar:
        item_identity = item.get('artifact_identity') or item.get('source_identity') or {}
        item_factor = str(item_identity.get('factor_id') or item.get('factor_id') or '')
        item_formula = item_identity.get('formula_hash') or item.get('formula_hash')
        scope = str(item.get('knowledge_scope') or '')
        item_family = item.get('factor_family')
        failure_signature = str(item.get('failure_signature') or '').lower()
        normalized = dict(item)
        normalized['reuse_as'] = 'analogy_only'
        if scope == 'same_factor':
            mismatch_fields: list[str] = []
            if item_factor != current_factor:
                mismatch_fields.append('factor_id')
            if current_formula_hash and item_formula != current_formula_hash:
                mismatch_fields.append('formula_hash')
            for field in ['code_hash', 'code_contract_hash', 'custom_block_hash', 'hybrid_hash', 'branch_id', 'run_id']:
                expected_value = current_identity.get(field)
                actual_value = item_identity.get(field) or item.get(field)
                if expected_value and actual_value != expected_value:
                    mismatch_fields.append(field)
            if mismatch_fields:
                identity_mismatch_cases.append({
                    'case_id': item.get('report_id') or item.get('source_path') or item.get('doc_type') or 'retrieved_same_factor_case',
                    'reason': 'same_factor_identity_mismatch',
                    'mismatch_fields': sorted(set(mismatch_fields)),
                    'expected_identity': current_identity,
                    'actual_identity': item_identity or item,
                })
                continue
            normalized['reuse_as'] = 'same_factor_history_with_provenance_check'
            same_factor_cases.append(normalized)
        elif scope == 'anti_pattern' or failure_signature in {'short_side_dominance', 'high_turnover_cost', 'cost_too_high'}:
            anti_pattern_cases.append(normalized)
            similar_case_cases.append(normalized)
        elif scope in {'similar_case', 'general_methodology'} or item_family == family:
            similar_case_cases.append(normalized)
        elif item:
            similar_case_cases.append(normalized)

    similar_success_cases = [item for item in similar_case_cases if str(item.get('decision')) == 'promote_official'][:3]
    similar_failure_cases = [
        item for item in similar_case_cases
        if str(item.get('decision')) in {'reject', 'iterate', 'needs_human_review'} or item in anti_pattern_cases
    ][:3]
    mechanism_neighbors = [
        {
            'neighbor_family': 'momentum_confirmation',
            'reason': 'price-volume correlation can represent volume-confirmed price pressure if trend state separation improves long-side monotonicity.',
            'reuse_as': 'possible explore branch, not adoption evidence',
        },
        {
            'neighbor_family': 'liquidity_shock',
            'reason': 'the same operator pattern may capture short-horizon liquidity shock or exhaustion instead of a stable premium.',
            'reuse_as': 'mechanism challenge',
        },
    ] if family == 'price_volume_correlation' else [
        {
            'neighbor_family': str(family or 'other'),
            'reason': 'neighbor exploration is advisory and cannot replace same-run evidence.',
            'reuse_as': 'research analogy only',
        }
    ]

    imported_lessons: list[str] = []
    rejected_lessons: list[str] = []
    if similar_failure_cases:
        imported_lessons.append('This case imports the prior anti-pattern that positive long-short spread is not enough when top long-side evidence is weak or short-side dominated.')
    if anti_pattern_cases and bool(metrics.get('short_side_dominance_suspected')):
        imported_lessons.append('Retrieved anti-pattern reinforces that short-side dominance is diagnostic only and cannot support adoption.')
    for item in similar_failure_cases[:2]:
        snippet = _case_snippet(item)
        if snippet:
            imported_lessons.append(f'Retrieved failure lesson: {snippet[:220]}')

    similar_success_condition_mismatch = bool(
        similar_success_cases
        and (cost_risk.get('cogs_destroy_alpha') or cost_risk.get('turnover_too_high'))
    )
    if similar_success_condition_mismatch:
        imported_lessons.append('Retrieved similar success was reviewed only as a condition check; its low-turnover success does not transfer to this high-cost case.')
        rejected_lessons.append('A prior similar success is not directly imported because the current case has materially worse turnover/cost-adjusted evidence.')
    elif similar_success_cases:
        imported_lessons.append('Retrieved similar success was reviewed as analogy only and does not override current-run evidence gates.')
        rejected_lessons.append('Similar success cases remain analogy only; they are not same-factor evidence and cannot justify official promotion.')
    rejected_lessons.append('Do not reuse similar-case evidence as same-factor evidence unless artifact identity and hash lineage match.')

    any_retrieved = bool(same_factor_cases or similar_case_cases or anti_pattern_cases)
    knowledge_gap = [] if any_retrieved else [
        'No comparable retrieved case was available; this run should become a future retrieval anchor with full mechanism and evidence provenance.',
    ]
    why_different = [
        'Current decision must stand on this run identity, Step4 long-side evidence, and mechanism fit rather than retrieved analogy.',
    ]
    if cost_risk.get('turnover_too_high'):
        why_different.append('Current turnover/cost profile differs materially from low-turnover successes.')
    if metrics.get('short_side_dominance_suspected'):
        why_different.append('Current long-short appearance is contaminated by short-side dominance, so similar spread success is not transferable.')

    return {
        'similar_success_cases': similar_success_cases,
        'similar_failure_cases': similar_failure_cases,
        'mechanism_neighbors': mechanism_neighbors,
        'imported_lessons': imported_lessons or (['cold_start_no_retrieved_case_lesson'] if not any_retrieved else []),
        'rejected_lessons': rejected_lessons,
        'why_this_case_is_different': why_different,
        'knowledge_gap': knowledge_gap,
        'retrieval_used': bool(retrieval_context.get('retrieval_index_available')) or bool(similar),
        'same_factor_cases': same_factor_cases,
        'similar_case_cases': similar_case_cases,
        'anti_pattern_cases': anti_pattern_cases,
        'identity_mismatch_cases': identity_mismatch_cases,
        'case_comparison_verdict': 'blocked' if identity_mismatch_cases else 'usable',
        'similar_success_condition_mismatch': similar_success_condition_mismatch,
        'similar_case_promotion_evidence_used': False,
    }


REVISION_FORBIDDEN_CHANGES = [
    'no_portfolio_expression_repair',
    'no_short_leg_adoption',
    'no_decile_trading',
    'no_shared_clean_data_mutation',
]


def _primary_failure_signature(
    evidence_audit: dict[str, Any],
    mechanism_analysis: dict[str, Any],
    case_comparison: dict[str, Any],
) -> str:
    long_quality = evidence_audit.get('long_side_evidence_quality') or {}
    cost_risk = evidence_audit.get('cost_and_turnover_risk') or {}
    metrics = evidence_audit.get('metric_consistency') or {}
    suspicions = evidence_audit.get('data_or_implementation_suspicions') or []
    backend = evidence_audit.get('backend_integrity') or {}
    factor_health = evidence_audit.get('factor_value_health') or {}
    if case_comparison.get('case_comparison_verdict') == 'blocked' or case_comparison.get('identity_mismatch_cases'):
        return 'same_factor_identity_mismatch'
    if (
        evidence_audit.get('evidence_verdict') == 'blocked'
        or backend.get('all_backends_skipped')
        or long_quality.get('long_side_verdict') == 'blocked'
        or factor_health.get('factor_value_verdict') == 'blocked'
        or 'step3b_implementation_blocked' in suspicions
        or 'step3b_mode_decision_missing_or_not_propagated' in suspicions
    ):
        return 'implementation_suspect'
    if long_quality.get('long_side_return_positive') is False:
        return 'long_side_negative'
    if cost_risk.get('cogs_destroy_alpha') or long_quality.get('cost_adjusted_status') == 'negative':
        return 'cost_too_high'
    if metrics.get('monotonicity_support') == 'weak' or metrics.get('short_side_dominance_suspected'):
        return 'non_monotonic'
    if mechanism_analysis.get('mechanism_fit') in {'weak', 'contradicted'}:
        return 'mechanism_unclear'
    if evidence_audit.get('evidence_verdict') == 'usable_with_warnings':
        return 'unstable_regime'
    return 'none'


def _revision_hypothesis(
    *,
    hypothesis_id: str,
    hypothesis: str,
    mechanism_target: str,
    expression_change: str,
    mode: str,
    expected_metric_change: list[str],
    falsification_tests: list[str],
    overfit: str,
    kill_criteria: list[str],
) -> dict[str, Any]:
    target_text = f'{mechanism_target} {expression_change}'.lower()
    if 'mechanism' in target_text:
        revision_target_math_object = 'model_family_challenge'
        revision_model_layer = 'primary_mechanism_model'
    elif 'regime' in target_text or 'state' in target_text:
        revision_target_math_object = 'state_variable'
        revision_model_layer = 'stochastic_projection'
    elif 'smooth' in target_text or 'persistence' in target_text or 'window' in target_text:
        revision_target_math_object = 'estimator_kernel'
        revision_model_layer = 'observable_estimator'
    else:
        revision_target_math_object = 'estimator_kernel'
        revision_model_layer = 'observable_estimator'
    return {
        'hypothesis_id': hypothesis_id,
        'hypothesis': hypothesis,
        'mechanism_target': mechanism_target,
        'expression_change': expression_change,
        'revision_target_math_object': revision_target_math_object,
        'revision_model_layer': revision_model_layer,
        'math_change': expression_change,
        'expected_metric_effect': expected_metric_change,
        'math_falsification_tests': falsification_tests,
        'implementation_mode_preference': mode,
        'expected_metric_change': expected_metric_change,
        'falsification_tests': falsification_tests,
        'risk_of_overfit': overfit,
        'kill_criteria': kill_criteria,
        'why_not_portfolio_fix': 'This revision changes the factor expression or Step3B code path; portfolio expression, short-leg adoption, decile trading, rebalance mechanics, and clean-data mutation are explicitly forbidden.',
        'forbidden_changes': REVISION_FORBIDDEN_CHANGES,
    }


def build_revision_strategy(
    decision: str,
    headline_metrics: dict[str, Any],
    evidence_audit: dict[str, Any],
    mechanism_analysis: dict[str, Any],
    case_comparison: dict[str, Any],
    framework: dict[str, Any],
    existing_math_discipline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del headline_metrics, framework
    mechanism_math_contract = mechanism_analysis.get('mechanism_math_contract') or {}
    mechanism_math_summary = mechanism_analysis.get('mechanism_math_summary') or mechanism_math_summary_from_contract(mechanism_math_contract)
    failure_signature = _primary_failure_signature(evidence_audit, mechanism_analysis, case_comparison)
    if decision == 'iterate' and failure_signature == 'none':
        failure_signature = 'mechanism_unclear'
    revision_needed = decision in {'iterate', 'needs_human_review'} or failure_signature not in {'none'}
    hypotheses: list[dict[str, Any]] = []
    revision_quality = 'not_needed'
    reject_reason = 'No rejection: revision or monitoring remains available.'

    if failure_signature in {'implementation_suspect', 'same_factor_identity_mismatch'}:
        revision_quality = 'blocked'
        reject_reason = (
            'Revision is blocked until evidence/provenance is repaired.'
            if failure_signature == 'implementation_suspect'
            else 'Revision is blocked until same-factor retrieval contamination and identity mismatch are repaired.'
        )
    elif failure_signature == 'none':
        revision_quality = 'not_needed'
        revision_needed = False
        hypotheses = []
    else:
        revision_quality = 'actionable'
        if failure_signature == 'cost_too_high':
            interaction_structure = str(
                ((mechanism_math_contract.get('formula_understanding') or {}) if isinstance(mechanism_math_contract, dict) else {}).get('interaction_structure') or ''
            )
            if interaction_structure == 'slow_state_x_short_horizon_threshold':
                cost_hypothesis = (
                    'Gross alpha is present but monetization fails because threshold migration between the slow winner state '
                    'and the short-horizon reversal/dislocation state is too noisy or turnover-heavy.'
                )
                cost_mechanism_target = (
                    'Make the slow-winner x short-horizon threshold state more persistent and economically separable, '
                    'so high factor values represent a durable conditional payoff state rather than boundary noise.'
                )
                cost_expression_change = (
                    'Revise the expression-level estimator by smoothing or confirming the short-horizon sign threshold, '
                    'testing the long-window winner-state interaction, and keeping only branches that reduce threshold churn '
                    'without weakening high-score long-side expected return.'
                )
                cost_falsification_tests = [
                    'Reject if threshold smoothing or confirmation does not lower turnover after expression-level revision.',
                    'Reject if ablations show the long-window winner state does not condition the short-horizon payoff.',
                    'Reject if cost-adjusted Sharpe remains negative despite positive gross return.',
                ]
            else:
                cost_hypothesis = 'Gross alpha is present but monetization fails because the expression is too short-lived and turnover-heavy.'
                cost_mechanism_target = 'Make the price/volume pressure state more persistent so high factor values represent durable pressure instead of one-day liquidity noise.'
                cost_expression_change = 'Replace the raw short-window signal with a persistence-confirmed expression: smooth the operator output, require multi-day agreement, or add a durable-signal confirmation term to lower turnover at the factor-expression level.'
                cost_falsification_tests = [
                    'Reject if turnover remains high after expression-level smoothing or persistence confirmation.',
                    'Reject if cost-adjusted Sharpe remains negative despite positive gross return.',
                ]
            hypotheses.append(_revision_hypothesis(
                hypothesis_id='rev_cost_persistence_001',
                hypothesis=cost_hypothesis,
                mechanism_target=cost_mechanism_target,
                expression_change=cost_expression_change,
                mode='operator',
                expected_metric_change=[
                    'lower long_side_turnover_mean_daily',
                    'positive cost_adjusted_annual_return',
                    'higher cost_adjusted_long_side_sharpe',
                ],
                falsification_tests=cost_falsification_tests,
                overfit='medium',
                kill_criteria=[
                    'Kill branch if cost-adjusted annual return remains negative.',
                    'Kill branch if turnover reduction also eliminates long-side annual return.',
                ],
            ))
        elif failure_signature == 'long_side_negative':
            hypotheses.append(_revision_hypothesis(
                hypothesis_id='rev_direction_state_001',
                hypothesis='High factor scores currently do not map to positive long-side return; sign or state interpretation may be inverted or mixing exhaustion with confirmation.',
                mechanism_target='Align high factor values with the intended positive economic state rather than relying on the weak side.',
                expression_change='Revise the expression direction and state split: test sign orientation, separate exhaustion versus confirmation states, and keep the branch only if high-score long-side returns become positive.',
                mode='operator',
                expected_metric_change=[
                    'positive long_side_annual_return',
                    'positive long_side_sharpe',
                    'reduced short_side_dominance_suspected',
                ],
                falsification_tests=[
                    'Reject if high-score long-side return remains non-positive after sign/state revision.',
                    'Reject if apparent improvement still comes only from bottom-decile losses.',
                ],
                overfit='medium',
                kill_criteria=[
                    'Kill branch if top/high-score long-side annual return remains non-positive.',
                    'Kill branch if long-short improvement is driven by short-side diagnostics only.',
                ],
            ))
        elif failure_signature == 'non_monotonic':
            hypotheses.append(_revision_hypothesis(
                hypothesis_id='rev_monotonic_state_001',
                hypothesis='The current expression mixes opposing mechanisms, so rank/decile ordering is not economically linear.',
                mechanism_target='Create a more monotonic factor state by separating or conditioning the mixed mechanism.',
                expression_change='Revise the expression to linearize the mechanism: split the signal by state variable, isolate confirmation from reversal, or transform the operator output so top scores represent a single economic condition.',
                mode='hybrid',
                expected_metric_change=[
                    'stronger monotonicity_support',
                    'top/high-score group outperforms middle and low groups',
                    'long-side Sharpe improves without short-side dependence',
                ],
                falsification_tests=[
                    'Reject if top group remains weaker than middle groups.',
                    'Reject if monotonicity improves only through bottom-decile deterioration.',
                ],
                overfit='high',
                kill_criteria=[
                    'Kill branch if monotonicity_support remains weak.',
                    'Kill branch if state split creates unstable regime-only performance.',
                ],
            ))
        elif failure_signature == 'unstable_regime':
            hypotheses.append(_revision_hypothesis(
                hypothesis_id='rev_regime_guard_001',
                hypothesis='The mechanism may be valid only in specific volatility/liquidity regimes.',
                mechanism_target='Condition the expression on a legal state variable that represents the mechanism regime.',
                expression_change='Add a factor-expression regime guard using volatility or liquidity state so the signal fires only when the hypothesized mechanism is active.',
                mode='hybrid',
                expected_metric_change=[
                    'lower max drawdown',
                    'shorter recovery days',
                    'more stable annual slices',
                ],
                falsification_tests=[
                    'Reject if guarded expression does not improve drawdown or recovery.',
                    'Reject if regime guard merely cherry-picks a small unstable sample.',
                ],
                overfit='high',
                kill_criteria=[
                    'Kill branch if recovery days remain slow.',
                    'Kill branch if performance concentrates in one unreproducible regime.',
                ],
            ))
        elif failure_signature == 'mechanism_unclear':
            hypotheses.append(_revision_hypothesis(
                hypothesis_id='rev_mechanism_challenge_001',
                hypothesis='The current expression lacks a testable return source; parameter tuning would be data mining.',
                mechanism_target='Restate and test the return-source hypothesis before changing parameters.',
                expression_change='Create a mechanism-challenge expression that isolates one hypothesized state variable and preserves only transforms tied to that return source; reject if no testable mechanism can be stated.',
                mode='unknown',
                expected_metric_change=[
                    'clearer observed_metric_signature',
                    'known return_source instead of unknown',
                    'mechanism_fit improves from weak/contradicted to partial before any promotion',
                ],
                falsification_tests=[
                    'Reject if return_source remains unknown after the challenge branch.',
                    'Reject if mechanism fit remains weak or contradicted even with cleaner expression state.',
                ],
                overfit='unknown',
                kill_criteria=[
                    'Kill branch if no falsifiable mechanism can be written.',
                    'Kill branch if improvements are only metric cosmetic without mechanism evidence.',
                ],
            ))
        else:
            revision_quality = 'weak'

    if decision == 'reject' and revision_quality == 'actionable':
        if failure_signature == 'long_side_negative':
            reject_reason_out = (
                'Rejected for current admission because the high-score long side is negative. '
                'The expression-level hypothesis is retained as an advisory future research idea, '
                'not an approved iterate loop, and Step6 must not write a Step3B handoff.'
            )
        else:
            reject_reason_out = (
                f'Rejected for current admission because primary_failure_signature={failure_signature}. '
                'Any actionable expression-level hypothesis is advisory future research only, '
                'not an approved iterate loop, and Step6 must not write a Step3B handoff.'
            )
    elif decision == 'reject' or revision_quality == 'blocked':
        reject_reason_out = reject_reason
    else:
        reject_reason_out = 'No rejection: revision or monitoring remains available.'

    if revision_quality == 'blocked':
        loop_authorization = 'blocked'
    elif decision == 'iterate' and revision_quality == 'actionable' and not case_comparison.get('similar_success_condition_mismatch'):
        loop_authorization = 'approved_for_step3b_handoff'
    else:
        loop_authorization = 'advisory_only'

    return {
        'revision_needed': bool(revision_needed),
        'primary_failure_signature': failure_signature,
        'revision_hypotheses': hypotheses,
        'reject_reason_if_no_revision': reject_reason_out,
        'revision_quality': revision_quality,
        'loop_authorization': loop_authorization,
        'mechanism_math_contract_ref': mechanism_math_summary,
        'math_discipline_ref': existing_math_discipline or {},
        'requires_human_approval_before_code_change': bool(revision_needed),
    }


def _search_branch_template(
    *,
    branch_id: str,
    branch_role: str,
    search_mode: str,
    research_question: str,
    hypothesis: str,
    mechanism_target: str,
    revision_hypothesis_id: str | None,
    success_criteria: list[str],
    falsification_tests: list[str],
) -> dict[str, Any]:
    return {
        'branch_id': branch_id,
        'branch_role': branch_role,
        'search_mode': search_mode,
        'research_question': research_question,
        'hypothesis': hypothesis,
        'mechanism_target': mechanism_target,
        'revision_hypothesis_id': revision_hypothesis_id,
        'success_criteria': success_criteria,
        'falsification_tests': falsification_tests,
        'hard_guards': REVISION_FORBIDDEN_CHANGES,
        'requires_human_approval_before_execution': True,
        'execution_allowed_by_default': False,
    }


def _first_revision_hypothesis_id(revision_strategy: dict[str, Any]) -> str | None:
    hypotheses = revision_strategy.get('revision_hypotheses') or []
    if hypotheses and isinstance(hypotheses[0], dict):
        value = hypotheses[0].get('hypothesis_id')
        return str(value) if value else None
    return None


def build_search_policy_decision(
    decision: str,
    evidence_audit: dict[str, Any],
    mechanism_analysis: dict[str, Any],
    case_comparison: dict[str, Any],
    revision_strategy: dict[str, Any],
    framework: dict[str, Any],
) -> dict[str, Any]:
    del framework
    signature = str(revision_strategy.get('primary_failure_signature') or 'none')
    quality = str(revision_strategy.get('revision_quality') or '')
    loop_authorization = str(revision_strategy.get('loop_authorization') or '')
    revision_hypothesis_id = _first_revision_hypothesis_id(revision_strategy)
    blockers: list[str] = []
    rationale: list[str] = [
        f'primary_failure_signature={signature}',
        f'revision_quality={quality}',
        f'loop_authorization={loop_authorization}',
        f'mechanism_fit={mechanism_analysis.get("mechanism_fit")}',
    ]
    branch_templates: list[dict[str, Any]] = []

    if evidence_audit.get('evidence_verdict') == 'blocked' or signature == 'implementation_suspect':
        mode = 'audit'
        why = 'Evidence or implementation is suspect; audit/repair must precede exploit or explore search.'
        blockers.append('implementation_or_evidence_suspect')
        branch_templates.append(_search_branch_template(
            branch_id='audit_evidence_and_implementation',
            branch_role='audit',
            search_mode='research_audit',
            research_question='Is the failure caused by evidence, backend, identity, or implementation defects rather than factor economics?',
            hypothesis='Repair provenance, evidence, and implementation fidelity before any expression or parameter search.',
            mechanism_target='evidence_integrity_and_implementation_fidelity',
            revision_hypothesis_id=None,
            success_criteria=['Step4/5 evidence identity verifies', 'required long-side metrics are present', 'implementation mode decision and hashes are consistent'],
            falsification_tests=['If backend evidence remains missing, do not search formulas', 'If identity or implementation hash mismatch persists, keep Step6 blocked'],
        ))
    elif case_comparison.get('case_comparison_verdict') == 'blocked' or signature == 'same_factor_identity_mismatch':
        mode = 'audit'
        why = 'Same-factor retrieval identity mismatch blocks research search until provenance is repaired.'
        blockers.append('same_factor_identity_mismatch')
        branch_templates.append(_search_branch_template(
            branch_id='audit_same_factor_provenance',
            branch_role='audit',
            search_mode='research_audit',
            research_question='Which retrieved same-factor record has mismatched factor/hash/run lineage?',
            hypothesis='The knowledge retrieval set is contaminated and must be repaired before it can guide revisions.',
            mechanism_target='knowledge_provenance_integrity',
            revision_hypothesis_id=None,
            success_criteria=['same_factor retrieved records match factor identity and hashes', 'similar cases are downgraded to analogy only'],
            falsification_tests=['If same-factor identity cannot be reconciled, block writeback and search', 'If provenance remains ambiguous, require human review'],
        ))
    elif signature == 'cost_too_high' and quality == 'actionable' and loop_authorization == 'approved_for_step3b_handoff':
        mode = 'bayesian_exploit'
        why = 'Cost failure is local enough for controlled smoothing/persistence parameter search.'
        branch_templates.append(_search_branch_template(
            branch_id='exploit_cost_persistence',
            branch_role='exploit',
            search_mode='bayesian_search',
            research_question='Can expression-level smoothing or persistence reduce turnover without destroying the thesis?',
            hypothesis='Preserve the mechanism while testing smoothing, persistence, and lower-turnover expression settings.',
            mechanism_target='durable_signal_lower_turnover',
            revision_hypothesis_id=revision_hypothesis_id,
            success_criteria=['cost-adjusted annual return improves', 'turnover decreases', 'long-side Sharpe is not worse'],
            falsification_tests=['lower turnover destroys the gross signal', 'cost-adjusted Sharpe remains negative'],
        ))
    elif signature == 'non_monotonic' and quality == 'actionable' and loop_authorization == 'approved_for_step3b_handoff':
        mode = 'genetic_explore'
        why = 'Non-monotonic behavior suggests mixed mechanisms; controlled expression exploration is appropriate.'
        branch_templates.append(_search_branch_template(
            branch_id='explore_monotonic_state_split',
            branch_role='explore',
            search_mode='genetic_algorithm',
            research_question='Can expression mutation separate mixed mechanisms into a monotonic long-side state?',
            hypothesis='Mutate the expression through state split, operator transform, or direction test while preserving the mechanism.',
            mechanism_target='monotonic_state_separation',
            revision_hypothesis_id=revision_hypothesis_id,
            success_criteria=['monotonicity improves', 'top long-side return improves', 'long-side Sharpe improves without short-side dependence'],
            falsification_tests=['no monotonic improvement', 'top group remains weaker than middle groups'],
        ))
    elif signature == 'long_side_negative':
        if decision == 'reject' and loop_authorization == 'advisory_only':
            mode = 'kill'
            why = 'Current case is rejected; the direction hypothesis is advisory only and not an executable loop.'
            blockers.append('current_case_rejected')
        elif decision == 'iterate' and loop_authorization == 'approved_for_step3b_handoff':
            mode = 'mechanism_challenge'
            why = 'Long-side direction failure requires mechanism and sign-state challenge before parameter tuning.'
            branch_templates.append(_search_branch_template(
                branch_id='challenge_long_side_direction',
                branch_role='macro',
                search_mode='mechanism_challenge',
                research_question='Is high-score direction inverted or mixing exhaustion with confirmation?',
                hypothesis='Clarify the economic state before authorizing expression mutation.',
                mechanism_target='long_side_direction_mechanism',
                revision_hypothesis_id=revision_hypothesis_id,
                success_criteria=['high-score long-side return becomes positive', 'short-side dominance is reduced'],
                falsification_tests=['improvement still comes only from bottom-decile losses', 'high-score long side remains non-positive'],
            ))
        else:
            mode = 'kill'
            why = 'Long-side direction failure is advisory only without loop authorization.'
            blockers.append('current_case_rejected')
    elif signature == 'mechanism_unclear' or mechanism_analysis.get('mechanism_fit') in {'weak', 'contradicted'}:
        mode = 'mechanism_challenge'
        why = 'Mechanism must be clarified before Bayesian parameter tuning or broad search.'
        if loop_authorization == 'approved_for_step3b_handoff':
            branch_templates.append(_search_branch_template(
                branch_id='challenge_return_source',
                branch_role='macro',
                search_mode='mechanism_challenge',
                research_question='Can the factor express a testable return source and necessary conditions?',
                hypothesis='Clarify return source and necessary conditions before parameter tuning.',
                mechanism_target='return_source_clarification',
                revision_hypothesis_id=revision_hypothesis_id,
                success_criteria=['return_source becomes known and testable', 'necessary conditions are measurable', 'mechanism_fit improves before promotion'],
                falsification_tests=['no testable mechanism can be stated', 'metric improvement is cosmetic without mechanism evidence'],
            ))
        elif (
            decision == 'iterate'
            and quality == 'actionable'
            and loop_authorization == 'advisory_only'
            and mechanism_analysis.get('mechanism_fit') in {'contradicted', 'weak', 'partial'}
        ):
            why = 'Advisory-only mechanism challenge is warranted because gross signal exists but cost-adjusted alpha and mechanism fit are weak or contradicted.'
            branch_templates.append(_search_branch_template(
                branch_id='challenge_mechanism_cost_contradiction',
                branch_role='macro',
                search_mode='mechanism_challenge',
                research_question='Why does the gross price-volume signal exist while cost-adjusted alpha fails?',
                hypothesis='Price-volume correlation may capture either persistent pressure or noisy liquidity shock; test whether persistence confirmation, smoothing, or information delay can separate the mechanism.',
                mechanism_target='price_volume_cost_contradiction',
                revision_hypothesis_id=revision_hypothesis_id,
                success_criteria=[
                    'explain whether price-volume correlation represents persistent pressure or noisy liquidity shock',
                    'identify whether persistence confirmation, smoothing, or delay is required before any expression change',
                    'show that cost-adjusted long-side evidence can improve without relying on forbidden adoption shortcuts',
                ],
                falsification_tests=[
                    'if smoothing or persistence removes the gross signal, reject the mechanism as noise',
                    'if cost-adjusted long-side evidence remains negative after mechanism clarification, keep the branch advisory',
                ],
            ))
            branch_templates[-1]['advisory_only'] = True
            branch_templates[-1]['step3b_handoff_allowed'] = False
            blockers.append('advisory_only')
        else:
            blockers.append('advisory_only')
    elif signature == 'none' and revision_strategy.get('revision_needed') is False and decision == 'promote_official':
        mode = 'none'
        why = 'No search is recommended after official promotion and no revision-needed signal.'
    else:
        mode = 'audit' if loop_authorization == 'blocked' else 'mechanism_challenge'
        why = 'Defaulting to non-executable research challenge because loop authorization is not an approved Step3B handoff.'
        if loop_authorization == 'advisory_only':
            blockers.append('advisory_only')

    if loop_authorization == 'advisory_only':
        for branch in branch_templates:
            branch['advisory_only'] = True
            branch['execution_allowed_by_default'] = False
        rationale.append('advisory_only prevents executable Step3B branch by default')

    return {
        'recommended_mode': mode,
        'why_this_mode': why,
        'branch_templates': branch_templates,
        'human_approval_required': True,
        'forbidden_search': REVISION_FORBIDDEN_CHANGES,
        'search_blockers': blockers,
        'selection_rationale': rationale,
    }


def should_write_step3b_handoff(
    decision: str,
    revision_strategy: dict[str, Any],
    case_comparison: dict[str, Any],
    search_policy_decision: dict[str, Any],
) -> bool:
    del search_policy_decision
    if decision != 'iterate':
        return False
    if revision_strategy.get('revision_quality') != 'actionable':
        return False
    if revision_strategy.get('loop_authorization') != 'approved_for_step3b_handoff':
        return False
    if case_comparison.get('similar_success_condition_mismatch') is True:
        return False
    if case_comparison.get('case_comparison_verdict') == 'blocked':
        return False
    return True


def build_formula_understanding(bundle: dict[str, Any]) -> dict[str, Any]:
    spec = bundle.get('factor_spec_master') or {}
    canonical = spec.get('canonical_spec') or {}
    formula_text = str(canonical.get('formula_text') or '')
    lower_formula = formula_text.lower()
    is_volume_acceleration_pressure_formula = 'delta(log(volume)' in lower_formula and '(close - open)' in lower_formula

    if is_volume_acceleration_pressure_formula:
        return {
            'factor_type': 'daily price-volume interaction factor',
            'plain_language': 'The formula measures whether recent acceleration in trading volume is associated with intraday price pressure, then applies the declared sign convention to that rolling relationship.',
            'economic_story': [
                'Volume acceleration can proxy attention, liquidity demand, or forced flow.',
                'Intraday close-minus-open pressure can proxy same-day buying/selling imbalance.',
                'The negative correlation sign assumes that certain volume-pressure patterns mean crowded/temporary price pressure that later unwinds.',
            ],
            'what_must_be_true': [
                'Volume shocks must contain information about temporary order-flow imbalance rather than only permanent news.',
                'The market must not immediately arbitrage away the intraday pressure-volume relationship.',
                'Trading costs and rebalance turnover must not consume the predicted spread.',
            ],
            'what_would_break_it': [
                'If volume shocks mostly reflect permanent information, reversal-style interpretation becomes wrong.',
                'If liquidity improves or many participants trade the same formula structure, spread can compress.',
                'If the signal requires high turnover, native portfolio performance can lag raw IC evidence.',
            ],
        }

    return {
        'factor_type': 'generic systematic factor',
        'plain_language': 'Step6 could not map this factor to a specialized formula template; interpretation is based on declared inputs/operators and Step4 evidence.',
        'economic_story': [
            'The declared inputs and operators must encode a repeatable state variable rather than a one-off sample artifact.',
        ],
        'what_must_be_true': [
            'The signal must be computable using only information available at decision time.',
            'The Step4 evidence must connect the formula output to future cross-sectional returns or tradable portfolio performance.',
        ],
        'what_would_break_it': [
            'The formula becomes a pure data-mined transform with no stable target statistic.',
            'Signal evidence improves while portfolio evidence remains negative after cost, turnover, and construction checks.',
        ],
    }


def build_research_memo(bundle: dict[str, Any], payloads: dict[str, dict[str, Any]], framework: dict[str, Any], metrics: dict[str, Any], decision: str) -> dict[str, Any]:
    formula = build_formula_understanding(bundle)
    metric_interpretation = build_metric_interpretation(metrics, payloads)
    math_discipline = build_math_discipline_review(bundle, payloads, framework, metrics, metric_interpretation, decision)
    run_master = bundle['factor_run_master']
    backend_runs = (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    backend_statuses = {str(item.get('backend')): str(item.get('status')) for item in backend_runs}

    evidence_quality_notes = [
        'Step4 produced real factor values and backend payloads; this is executable evidence, not prose-only evidence.',
        f'Backend statuses are {backend_statuses}.',
        'Long-short, short-leg, and decile outputs are diagnostics only; adoption is judged by long-side Sharpe/risk-adjusted evidence, drawdown/recovery, and factor-expression monotonicity.',
    ]
    if metric_interpretation['verdict'] == 'mixed':
        evidence_quality_notes.append('Evidence is mixed: signal-level metrics are supportive, but portfolio-level monetization has reservations.')
    if payloads.get('qlib_backtest', {}).get('mode') == 'native_minimal':
        evidence_quality_notes.append('qlib native_minimal path ran, so Step6 can evaluate portfolio construction evidence rather than only grouped diagnostics.')

    if decision == 'promote_official':
        decision_rationale = [
            'Both required backends succeeded.',
            'Signal-level metrics, long-side risk-adjusted performance, and monotonicity diagnostics support the same high-score-is-better direction.',
            'No blocking implementation or payload-contract issue remains.',
        ]
    elif decision == 'iterate':
        decision_rationale = [
            'The factor has usable predictive evidence, but at least one material concern remains.',
            'The next iteration should revise the factor expression or Step3B code so the long side becomes stronger and more linearly monotonic.',
        ]
    elif decision == 'reject':
        decision_rationale = [
            'The current evidence does not justify more research budget under the present hypothesis.',
        ]
    else:
        decision_rationale = [
            'The evidence is ambiguous enough that human review should precede automatic modification or official promotion.',
        ]

    next_tests = [
        'Run expression-direction comparison to verify whether higher factor values should represent stronger expected risk-adjusted long-side returns.',
        'Run monotonicity, long-side Sharpe, drawdown, recovery, and top-group return checks across years, regimes, industries, and market-cap buckets.',
        'Check yearly and regime-split stability, especially before and after major liquidity/regulatory regime changes.',
        'Check liquidity and market-cap buckets to see whether the edge is broad or concentrated in hard-to-trade names.',
        'Compare against related formula-family price-volume factors to avoid promoting a redundant signal.',
    ]

    return {
        'formula_understanding': formula,
        'return_source_analysis': {
            'primary_hypothesis': framework.get('monetization_model'),
            'factor_family': framework.get('factor_family'),
            'bias_type': framework.get('bias_type'),
            'explanation': framework.get('return_source_hypothesis'),
            'constraint_sources': framework.get('constraint_sources') or [],
            'objective_constraint_dependency': framework.get('objective_constraint_dependency'),
        },
        'metric_interpretation': metric_interpretation,
        'long_side_adoption_policy': metric_interpretation.get('long_side_adoption_review'),
        'math_discipline_review': math_discipline,
        'evidence_quality': {
            'notes': evidence_quality_notes,
            'backend_statuses': backend_statuses,
            'run_status': run_master.get('run_status'),
            'row_count': (run_master.get('diagnostic_summary') or {}).get('row_count'),
            'date_count': (run_master.get('diagnostic_summary') or {}).get('date_count'),
            'ticker_count': (run_master.get('diagnostic_summary') or {}).get('ticker_count'),
        },
        'failure_and_risk_analysis': {
            'expected_failure_regimes': framework.get('expected_failure_regimes') or [],
            'crowding_risk': framework.get('crowding_risk'),
            'capacity_constraints': framework.get('capacity_constraints'),
            'implementation_risk': framework.get('implementation_risk'),
        },
        'decision_rationale': decision_rationale,
        'next_research_tests': next_tests,
    }


def build_math_discipline_review(
    bundle: dict[str, Any],
    payloads: dict[str, dict[str, Any]],
    framework: dict[str, Any],
    metrics: dict[str, Any],
    metric_interpretation: dict[str, Any],
    decision: str,
) -> dict[str, Any]:
    spec = bundle.get('factor_spec_master') or {}
    idea = bundle.get('alpha_idea_master') or {}
    canonical = spec.get('canonical_spec') or {}
    formula_text = str(canonical.get('formula_text') or '')
    required_inputs = _as_list(canonical.get('required_inputs'))
    operators = [str(item).lower() for item in _as_list(canonical.get('operators'))]
    ts_steps = _as_list(canonical.get('time_series_steps'))
    cs_steps = _as_list(canonical.get('cross_sectional_steps'))
    metric_gap_items = list(metric_interpretation.get('ambiguities') or [])

    text_blob = ' '.join([
        formula_text,
        ' '.join(required_inputs),
        ' '.join(operators),
        ' '.join(ts_steps),
        ' '.join(cs_steps),
    ]).lower()

    if any(tok in text_blob for tok in ['return', 'close', 'open', 'high', 'low']):
        random_object = 'A-share daily price/return panel and cross-sectional return ordering'
    elif any(tok in text_blob for tok in ['volume', 'turnover', 'amount']):
        random_object = 'A-share liquidity and order-flow proxy panel'
    elif any(tok in text_blob for tok in ['pe', 'pb', 'profit', 'revenue', 'cash', 'liability']):
        random_object = 'firm fundamental information state observed through financial/accounting fields'
    else:
        random_object = 'not fully identified from canonical spec; researcher should restate the random object before promotion'

    if any(tok in text_blob for tok in ['rank', 'argmax', 'argmin', 'quantile']):
        target_statistic = 'cross-sectional or time-series ordering statistic'
    elif any(tok in text_blob for tok in ['std', 'var', 'volatility']):
        target_statistic = 'conditional dispersion / volatility statistic'
    elif any(tok in text_blob for tok in ['skew', 'kurt']):
        target_statistic = 'higher-moment / regime-shape statistic'
    elif any(tok in text_blob for tok in ['corr', 'cov']):
        target_statistic = 'rolling dependence statistic'
    else:
        target_statistic = 'conditional expected return or ranking effect inferred from Step4 evidence'

    lag_terms = [str(item).lower() for item in _as_list(canonical.get('preprocessing')) + ts_steps + cs_steps]
    has_explicit_lag = any('lag' in item or 'shift' in item or 'delay' in item for item in lag_terms)
    info_legality = (
        'explicit_lag_or_delay_documented'
        if has_explicit_lag
        else 'requires_researcher_confirmation_no_forward_leakage'
    )

    unstable_ops = sorted({op for op in operators if op in {'rank', 'ts_rank', 'bucket', 'quantile', 'winsorize', 'truncate', 'argmax', 'argmin'}})
    spec_stability = {
        'boundary_sensitive_operators': unstable_ops,
        'neutralization_declared': bool(canonical.get('neutralization')),
        'normalization_declared': bool(canonical.get('normalization')),
        'review_note': (
            'Ranking/bucketing/truncation style operators can change behavior at boundaries; Step6 must not promote without stability evidence.'
            if unstable_ops
            else 'No obvious boundary-sensitive operator was declared, but Step4 robustness checks are still required.'
        ),
    }

    rank_ic = _safe_float(metrics.get('rank_ic_mean'))
    top_return = _safe_float(metrics.get('long_side_annual_return'))
    bottom_return = _safe_float(metrics.get('group_bottom_decile_mean_return'))
    long_side_review = build_long_side_adoption_review(metrics)
    signal_vs_portfolio_gap = 'not_enough_long_side_evidence'
    if long_side_review.get('long_side_status') == 'official_ready':
        signal_vs_portfolio_gap = 'signal_and_risk_adjusted_long_side_align'
    elif rank_ic is not None and rank_ic > 0 and top_return is not None and top_return <= 0:
        signal_vs_portfolio_gap = 'positive_signal_but_long_side_failed'
    elif long_side_review.get('long_side_status') in {'mixed', 'unknown'} and top_return is not None and top_return > 0:
        signal_vs_portfolio_gap = 'long_side_revenue_positive_but_risk_adjusted_evidence_insufficient'
    elif top_return is not None and bottom_return is not None and top_return <= bottom_return:
        signal_vs_portfolio_gap = 'monotonicity_failed_top_group_not_best'
    elif rank_ic is not None and rank_ic > 0 and top_return is not None and top_return > 0:
        signal_vs_portfolio_gap = 'signal_and_long_side_align'
    elif metric_gap_items:
        signal_vs_portfolio_gap = 'metric_ambiguity_requires_followup'

    if decision == 'iterate':
        if signal_vs_portfolio_gap in {'positive_signal_but_long_side_failed', 'monotonicity_failed_top_group_not_best'}:
            revision_operator = 'factor_expression_monotonicity_revision'
            generalization_argument = 'The next revision must change the factor expression or Step3B code so high factor values represent the economic state that should earn long-side returns.'
        elif unstable_ops:
            revision_operator = 'robustness_transform_or_boundary_stability_revision'
            generalization_argument = 'The next revision should test whether smoother or more linear expression transforms improve long-side monotonicity without changing the thesis.'
        else:
            revision_operator = 'hypothesis_clarification_revision'
            generalization_argument = 'The next revision should identify whether the weak evidence comes from thesis, spec, implementation, or validation.'
    elif decision == 'promote_official':
        revision_operator = 'none'
        generalization_argument = 'Promotion is allowed only if evidence supports the return-source thesis through risk-adjusted long-side performance, acceptable drawdown/recovery, and a monotonic expression-to-return relationship.'
    else:
        revision_operator = 'stop_or_human_review'
        generalization_argument = 'Evidence does not justify automatic formula modification without clearer research hypothesis.'

    overfit_risk = []
    if decision == 'iterate':
        overfit_risk.append('Adaptive testing risk: repeated Step6->Step3B loops can select a lucky wrapper unless failed variants are written to the knowledge base.')
    if unstable_ops:
        overfit_risk.append('Boundary sensitivity risk: rank/bucket/truncation changes can improve one sample while hurting out-of-sample stability.')
    if framework.get('monetization_model') == 'constraint_driven_arbitrage':
        overfit_risk.append('Constraint decay risk: objective constraints may weaken after rules, mandates, or participant behavior change.')
    if not overfit_risk:
        overfit_risk.append('General overfit risk remains: require window/regime/universe and cost sensitivity before promotion.')

    kill_criteria = [
        'If the highest-score long-side bucket remains non-positive after expression/code revision, stop this revision direction.',
        'If long-side Sharpe remains below the candidate threshold after expression/code revision, stop or redesign the return-source thesis.',
        'If max drawdown or recovery time remains too large for the assigned risk budget, do not promote even if raw return is positive.',
        'If the factor only works through the short leg or long-short spread, do not adopt it under the current mandate.',
        'If monotonicity cannot be improved by changing the factor expression itself, stop rather than repairing portfolio construction.',
        'If the claimed return source cannot be linked to a repeatable risk, information, or constraint mechanism, do not promote.',
    ]

    return {
        'math_axis': [
            'probability_statistics',
            'time_series' if ts_steps else 'cross_sectional_statistics',
            'linear_algebra' if canonical.get('neutralization') else 'ranking_or_transformation_algebra',
            'optimization' if decision == 'iterate' else 'decision_control',
            'robustness_analysis',
        ],
        'step1_random_object': random_object,
        'target_statistic': target_statistic,
        'information_set_legality': info_legality,
        'spec_stability': spec_stability,
        'signal_vs_portfolio_gap': signal_vs_portfolio_gap,
        'long_side_objective': long_side_review,
        'monotonicity_objective': 'Higher factor values should correspond to stronger expected long-side returns under the factor thesis.',
        'revision_scope_constraint': LONG_ONLY_POLICY['revision_scope'],
        'revision_operator': revision_operator,
        'generalization_argument': generalization_argument,
        'overfit_risk': overfit_risk,
        'kill_criteria': kill_criteria,
        'source_thesis_trace': {
            'alpha_idea_available': bool(idea),
            'factor_spec_available': bool(spec),
            'formula_text_present': bool(formula_text.strip()),
        },
    }


def infer_research_framework(bundle: dict[str, Any], payloads: dict[str, dict[str, Any]], decision: str) -> dict[str, Any]:
    run_master = bundle['factor_run_master']
    case = bundle['factor_case_master']
    spec = bundle.get('factor_spec_master') or {}
    canonical = spec.get('canonical_spec') or {}
    factor_id = str(run_master.get('factor_id') or case.get('factor_id') or '')
    report_id = str(run_master.get('report_id') or case.get('report_id') or '')
    factor_tokens = tokenize(' '.join([
        factor_id,
        report_id,
        str(canonical.get('formula_text') or ''),
        ' '.join(canonical.get('operators') or []),
        ' '.join(canonical.get('required_inputs') or []),
        ' '.join(canonical.get('time_series_steps') or []),
        ' '.join(canonical.get('cross_sectional_steps') or []),
    ]))
    token_set = set(factor_tokens)
    metrics = extract_headline_metrics(payloads)

    style_tokens = {'value', 'size', 'beta', 'liquidity', 'lowvol', 'volatility', 'quality'}
    behavior_tokens = {'momentum', 'reversal', 'sentiment', 'overreaction', 'underreaction'}
    micro_tokens = {'price', 'volume', 'flow', 'turnover', 'imbalance', 'shadow', 'candlestick', 'williams', 'high', 'low', 'close', 'open', 'argmax', 'std', 'corr'}
    info_tokens = {'contract', 'cash', 'cashflow', 'revenue', 'profit', 'margin', 'liability', 'inventory', 'capex', 'client', 'financial'}

    if token_set & style_tokens:
        factor_family = 'style_risk_factor'
        monetization_model = 'risk_premium'
        return_source_hypothesis = 'Returns likely come from taking compensated systematic exposure rather than a purely private information edge.'
        bias_type = 'risk_compensation'
    elif token_set & info_tokens:
        factor_family = 'fundamental_information_factor'
        monetization_model = 'information_advantage'
        return_source_hypothesis = 'Returns likely come from structured interpretation of company-specific fundamentals before the market fully reprices them.'
        bias_type = 'information_diffusion'
    elif token_set & behavior_tokens:
        factor_family = 'behavioral_price_pattern_factor'
        monetization_model = 'mixed'
        return_source_hypothesis = 'Returns likely come from investor overreaction / underreaction that can be harvested with systematic price-pattern exposure.'
        bias_type = 'behavioral_bias'
    elif token_set & micro_tokens:
        factor_family = 'market_structure_microstructure_factor'
        monetization_model = 'constraint_driven_arbitrage'
        return_source_hypothesis = 'Returns likely come from recurring objective constraints or frictions, where other market participants are pushed into predictable behavior and the strategy acts as a structured, not strictly risk-free, arbitrageur.'
        bias_type = 'constraint_plus_behavior'
    else:
        factor_family = 'mixed_or_unclear'
        monetization_model = 'mixed'
        return_source_hypothesis = 'Current evidence suggests a usable signal, but the return source is still mixed or not yet crisply separated into risk premium vs information advantage.'
        bias_type = 'mixed_or_unclear'

    if factor_family == 'style_risk_factor':
        expected_failure_regimes = [
            'factor winter or long valuation compression against the style sleeve',
            'macro regime shifts that reverse the rewarded risk',
        ]
        objective_constraint_dependency = 'low_to_medium'
        constraint_sources = [
            'benchmarking and mandate-driven allocation can amplify style premia',
        ]
        crowding_risk = 'medium_to_high'
        capacity_constraints = 'usually better than microstructure signals, but depends on turnover and universe breadth'
        implementation_risk = 'mainly style timing and crowding rather than data sparsity'
        improvement_frontier = [
            'separate rewarded exposure from overlapping style bets',
            'improve risk budgeting and cross-factor neutralization',
        ]
    elif factor_family == 'fundamental_information_factor':
        expected_failure_regimes = [
            'when the market learns the accounting pattern and reprices faster',
            'when the feature only works in a narrow industry subset',
        ]
        objective_constraint_dependency = 'low'
        constraint_sources = [
            'coverage limits and processing delays can create temporary information-arbitrage windows',
        ]
        crowding_risk = 'medium'
        capacity_constraints = 'often decent, but may degrade if the screen concentrates into a small theme bucket'
        implementation_risk = 'mapping accounting features to tradable timing can be noisy'
        improvement_frontier = [
            'clarify where the feature is cross-sectionally valid vs only locally valid',
            'separate industry beta from true information edge',
        ]
    elif factor_family == 'behavioral_price_pattern_factor':
        expected_failure_regimes = [
            'behavioral regime change or crowding by similar fast-money strategies',
            'policy or structural shifts that compress the anomaly',
        ]
        objective_constraint_dependency = 'medium'
        constraint_sources = [
            'delegated capital, benchmark pressure, and common behavioral response functions can force repetitive order-flow patterns',
        ]
        crowding_risk = 'high'
        capacity_constraints = 'moderate and can deteriorate quickly if the pattern lives in small/illiquid names'
        implementation_risk = 'signal half-life and turnover can erode realized alpha'
        improvement_frontier = [
            'test whether the anomaly is robust outside the original sample window',
            'reduce turnover while preserving the edge',
        ]
    else:
        expected_failure_regimes = [
            'market-structure rule changes',
            'liquidity stress or execution degradation',
            'anomaly crowding after the pattern becomes widely known',
        ]
        objective_constraint_dependency = 'high'
        constraint_sources = [
            'exchange rules or transfer mechanisms',
            'fund mandate or benchmark constraints',
            'insurance / public-fund style behavior patterns',
            'execution and liquidity frictions that force predictable action',
        ]
        crowding_risk = 'medium_to_high'
        capacity_constraints = 'can be fragile if the alpha depends on small names, short holding periods, or thin liquidity'
        implementation_risk = 'realized alpha may be far more sensitive to execution, slippage, and data-contract choices than headline IC suggests'
        improvement_frontier = [
            'separate objective-constraint edge from pure noise',
            'stabilize the signal with robust transforms before increasing complexity',
            'verify monotonicity across wider windows and different liquidity buckets',
        ]

    program_search_axes = {
        'semantic_axis': 'preserve or revise the economic/research hypothesis carried by the formula',
        'operator_axis': 'mutate operators, signs, ranks, lags, windows, neutralization, and transforms as controlled program edits',
        'parameter_axis': 'search discrete/continuous hyperparameters such as lookback windows, clipping levels, decay, and normalization choices',
        'long_side_axis': 'test whether high factor values earn risk-adjusted long-side returns, survive drawdowns, and whether the expression is monotonic',
        'library_axis': 'compare against prior factor families to decide whether this is novel, redundant, or a known failure branch',
    }
    review_checklist = [
        '先判断这条收益更像风险补偿、信息优势，还是约束驱动套利；不要直接从 metric 下结论。',
        '明确对手盘为什么会在客观约束下做出可预测行为，例如制度规则、考核约束、资金属性、流动性约束。',
        '检查当前证据是在支持收益来源本身，还是只是在支持某个脆弱实现。',
        '区分 factor 与 feature：这是一条可重复交易的系统化暴露，还是局部有效但尚未稳定抽象的特征组合。',
        '在决定 promote / iterate / reject 前，先写清失效条件、容量约束、拥挤风险与实现风险。',
        '把每次失败当作搜索轨迹的一部分写回知识库；不要只保存胜出的公式。',
    ]
    revision_principles = [
        'revision 先服务于收益来源假说，而不是先服务于指标美化。',
        '若是风险补偿型，优先提升可交易性、稳健性和暴露控制，而不是过度压平风险特征。',
        '若是信息优势型，优先强化识别条件、样本边界和解释链条，而不是盲目扩大适用范围。',
        '若是约束驱动套利型，优先验证客观约束是否真实、是否持续、是否仍可被结构化利用。',
        '宏观修订改收益来源假说或因子家族；微观修订只改因子表达式、窗口、阈值、符号、输入变换或标准化，两者必须分开记录。',
        '不得通过卖空、long-short、直接分位数组交易或 portfolio expression 修复来让一个 long-side 不赚钱的因子通过。',
        '入库目标从 raw long-side return 升级为 long-side Sharpe / volatility drag / drawdown / recovery 的综合资本效率。',
        '迭代时至少保留一个 exploit 分支和一个 explore 分支，避免只在上一轮噪声附近局部爬山。',
        '每次修改都必须回答：它在强化哪一种收益来源，以及为什么比上一版更合理。',
    ]

    research_commentary = []
    if decision == 'promote_official':
        research_commentary.append('Current evidence is strong enough for official admission, but the hypothesis should still be monitored against regime drift.')
    elif decision == 'iterate':
        research_commentary.append('The signal is usable, but the current evidence still leaves room to sharpen either the economic story or the implementation path.')
    elif decision == 'reject':
        research_commentary.append('The current result does not justify more risk budget unless a materially different hypothesis emerges.')
    long_side = build_long_side_adoption_review(metrics)
    if long_side.get('long_side_status') in {'supportive', 'official_ready'} and (metrics.get('rank_ic_mean') or 0) > 0:
        research_commentary.append('Cross-sectional rank evidence and risk-adjusted long-side evidence point in the same positive direction.')

    return {
        'factor_family': factor_family,
        'monetization_model': monetization_model,
        'bias_type': bias_type,
        'return_source_hypothesis': return_source_hypothesis,
        'expected_failure_regimes': expected_failure_regimes,
        'objective_constraint_dependency': objective_constraint_dependency,
        'constraint_sources': constraint_sources,
        'crowding_risk': crowding_risk,
        'capacity_constraints': capacity_constraints,
        'implementation_risk': implementation_risk,
        'improvement_frontier': improvement_frontier,
        'program_search_axes': program_search_axes,
        'review_checklist': review_checklist,
        'revision_principles': revision_principles,
        'research_commentary': research_commentary,
    }


def build_retrieval_context(bundle: dict[str, Any], payloads: dict[str, dict[str, Any]], top_k: int = 5) -> dict[str, Any]:
    run_master = bundle['factor_run_master']
    case = bundle['factor_case_master']
    report_id = str(run_master.get('report_id') or '')
    factor_id = str(run_master.get('factor_id') or case.get('factor_id') or '')
    decision_hint = str(case.get('final_status') or run_master.get('run_status') or '')
    metrics = extract_headline_metrics(payloads)
    query_parts = [
        factor_id,
        decision_hint,
        json.dumps(metrics, ensure_ascii=False),
        ' '.join(case.get('lessons') or []),
        ' '.join(case.get('next_actions') or []),
    ]
    query_text = ' '.join(part for part in query_parts if part)
    query_tokens = tokenize(query_text)
    query_counter = Counter(query_tokens)

    retrieval_docs = load_retrieval_docs()
    candidates: list[dict[str, Any]] = []
    for doc in retrieval_docs:
        if str(doc.get('report_id')) == report_id:
            continue
        score = 0.0
        if str(doc.get('factor_id')) == factor_id:
            score += 5.0
        if str(doc.get('decision')) == decision_hint:
            score += 1.5
        doc_tokens = tokenize(str(doc.get('text') or ''))
        overlap = set(query_tokens) & set(doc_tokens)
        score += float(len(overlap)) * 0.25
        if not overlap and str(doc.get('factor_id')) != factor_id:
            continue
        snippet = str(doc.get('text') or '')[:280]
        candidates.append({
            'score': round(score, 4),
            'lexical_score': round(score, 4),
            'report_id': doc.get('report_id'),
            'factor_id': doc.get('factor_id'),
            'doc_type': doc.get('doc_type'),
            'decision': doc.get('decision'),
            'knowledge_scope': doc.get('knowledge_scope'),
            'factor_family': doc.get('factor_family') or doc.get('mechanism_family'),
            'failure_signature': doc.get('failure_signature'),
            'formula_hash': doc.get('formula_hash'),
            'artifact_identity': doc.get('artifact_identity') or doc.get('source_identity') or {},
            'source_identity': doc.get('source_identity') or doc.get('artifact_identity') or {},
            'source_path': doc.get('source_path'),
            'overlap_terms': sorted(overlap)[:12],
            'snippet': snippet,
        })

    embedding_available = (
        os.getenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL') != '1'
        and EMBEDDING_MATRIX.exists()
        and EMBEDDING_META.exists()
    )
    query_vec = embed_query(query_text) if embedding_available else None
    if embedding_available and query_vec is not None:
        try:
            matrix = np.load(EMBEDDING_MATRIX)
            emb_docs = load_embedding_docs()
            sims = matrix @ query_vec
            by_key = {(str(item.get('report_id')), str(item.get('doc_type'))): item for item in candidates}
            for idx, sim in enumerate(sims.tolist()):
                doc = emb_docs[idx]
                if str(doc.get('report_id')) == report_id:
                    continue
                key = (str(doc.get('report_id')), str(doc.get('doc_type')))
                item = by_key.get(key)
                if item is None:
                    item = {
                        'score': 0.0,
                        'lexical_score': 0.0,
                        'report_id': doc.get('report_id'),
                        'factor_id': doc.get('factor_id'),
                        'doc_type': doc.get('doc_type'),
                        'decision': doc.get('decision'),
                        'knowledge_scope': doc.get('knowledge_scope'),
                        'factor_family': doc.get('factor_family') or doc.get('mechanism_family'),
                        'failure_signature': doc.get('failure_signature'),
                        'formula_hash': doc.get('formula_hash'),
                        'artifact_identity': doc.get('artifact_identity') or doc.get('source_identity') or {},
                        'source_identity': doc.get('source_identity') or doc.get('artifact_identity') or {},
                        'source_path': doc.get('source_path'),
                        'overlap_terms': [],
                        'snippet': str(doc.get('text') or '')[:280],
                    }
                    candidates.append(item)
                    by_key[key] = item
                item['embedding_score'] = round(float(sim), 4)
                item['score'] = round(float(item.get('lexical_score', 0.0)) + float(sim), 4)
        except Exception:
            embedding_available = False

    candidates.sort(key=lambda item: (-item['score'], str(item.get('report_id') or ''), str(item.get('doc_type') or '')))
    top = candidates[:top_k]
    return {
        'retrieval_index_path': str(RETRIEVAL_INDEX),
        'retrieval_index_available': RETRIEVAL_INDEX.exists(),
        'embedding_index_available': embedding_available,
        'embedding_endpoint': EMBEDDING_ENDPOINT,
        'query_terms': query_tokens[:40],
        'similar_cases': top,
        'retrieval_notes': [
            'retrieval currently uses lightweight lexical + metadata matching over factorforge_retrieval_index.jsonl',
            'if local embedding index + endpoint are available, similarity scores are added on top of lexical family-aware matching',
            'same-factor_id cases are boosted to prefer family-aware reflection',
        ],
    }


def build_learning_and_innovation(
    framework: dict[str, Any],
    decision: str,
    strengths: list[str],
    weaknesses: list[str],
    modification_targets: list[str],
    retrieval_context: dict[str, Any],
) -> dict[str, Any]:
    similar_cases = retrieval_context.get('similar_cases') or []
    imported_lessons = []
    for item in similar_cases[:3]:
        label = ' / '.join(str(x) for x in [item.get('factor_id'), item.get('decision')] if x)
        snippet = str(item.get('snippet') or '').strip()
        if label or snippet:
            imported_lessons.append((label + ': ' + snippet).strip(': ')[:360])
    if not imported_lessons:
        imported_lessons.append(
            'No similar prior case was retrieved; treat this as a cold-start lesson and update the knowledge base after comparable cases exist.'
        )

    monetization_model = str(framework.get('monetization_model') or 'mixed')
    factor_family = str(framework.get('factor_family') or 'mixed_or_unclear')

    transferable_patterns = []
    if strengths:
        transferable_patterns.append('Preserve the strongest evidence pattern before adding complexity: ' + str(strengths[0]))
    if monetization_model == 'constraint_driven_arbitrage':
        transferable_patterns.append('For constraint-driven cases, first identify the objective constraint and its decay risk before optimizing formulas.')
    elif monetization_model == 'information_advantage':
        transferable_patterns.append('For information-advantage cases, narrow the valid universe and timing boundary before broadening the feature.')
    elif monetization_model == 'risk_premium':
        transferable_patterns.append('For risk-premium cases, separate compensated exposure from unwanted style/crowding overlap before neutralizing it away.')
    else:
        transferable_patterns.append('For mixed-source cases, split risk, information, and constraint hypotheses before choosing the next wrapper.')

    anti_patterns = []
    if weaknesses:
        anti_patterns.append('Do not ignore this failure signature in future cases: ' + str(weaknesses[0]))
    anti_patterns.append('Do not accept a revision merely because one metric improved; require return-source and robustness support.')

    if decision == 'iterate':
        idea_seed = [
            'Create a controlled ablation that tests the proposed modification against the raw signal and a sign-flip baseline.',
            'Try a neighboring factor family only if it preserves the same return-source thesis and adds a falsifiable mechanism.',
        ]
        if modification_targets:
            idea_seed.insert(0, 'Turn the top modification target into a separate idea seed: ' + str(modification_targets[0]))
    elif decision == 'reject':
        idea_seed = [
            'Consider whether the failed signal has value as a regime filter, risk control, or short-side-only component before abandoning the family.',
        ]
    else:
        idea_seed = [
            'Use this case as a retrieval anchor for future factors in the same family and test whether the same mechanism survives a new universe/window.',
        ]

    return {
        'learning_goal': 'Make future researcher agents better at extracting reusable factor ideas, anti-patterns, and innovative next experiments.',
        'factor_family': factor_family,
        'transferable_patterns': transferable_patterns,
        'anti_patterns': anti_patterns,
        'similar_case_lessons_imported': imported_lessons,
        'innovative_idea_seeds': idea_seed,
        'reuse_instruction_for_future_agents': [
            'Before modifying a similar factor, retrieve this case and decide whether to reuse, invert, or avoid its revision operator.',
            'When a case fails, preserve the failure as a search prior instead of treating it as dead output.',
            'Every new idea seed should state the return source it expects to strengthen and the kill criteria that would stop it.',
        ],
    }


def build_experience_chain(
    report_id: str,
    factor_id: str,
    iteration_no: int,
    decision: str,
    strengths: list[str],
    weaknesses: list[str],
    retrieval_context: dict[str, Any],
    prior_iteration_no: int,
) -> dict[str, Any]:
    similar_cases = retrieval_context.get('similar_cases') or []
    imported = []
    for item in similar_cases[:5]:
        imported.append({
            'report_id': item.get('report_id'),
            'factor_id': item.get('factor_id'),
            'decision': item.get('decision'),
            'doc_type': item.get('doc_type'),
            'score': item.get('score'),
            'lesson_hint': str(item.get('snippet') or '')[:220],
            'source_path': item.get('source_path'),
        })
    return {
        'purpose': 'Preserve the full search trajectory so future agents learn from both wins and dead ends.',
        'current_attempt': {
            'report_id': report_id,
            'factor_id': factor_id,
            'iteration_no': iteration_no,
            'decision': decision,
            'strongest_positive_evidence': strengths[:3],
            'strongest_failure_signature': weaknesses[:3],
        },
        'prior_iteration_no': prior_iteration_no,
        'similar_experience_imported': imported or [{
            'cold_start': True,
            'lesson_hint': 'No prior comparable case was retrieved; this run should become a future retrieval anchor.',
        }],
        'writeback_rule': [
            'Store the attempted hypothesis, metrics, revision operator, and kill criteria even when the factor fails.',
            'When a later factor retrieves this case, treat failure signatures as search priors rather than wasted work.',
        ],
    }


def build_revision_taxonomy(
    framework: dict[str, Any],
    metric_interpretation: dict[str, Any],
    math_discipline: dict[str, Any],
    modification_targets: list[str],
    decision: str,
) -> dict[str, Any]:
    monetization_model = str(framework.get('monetization_model') or 'mixed')
    gap = str(math_discipline.get('signal_vs_portfolio_gap') or '')
    revision_operator = str(math_discipline.get('revision_operator') or '')
    verdict = str(metric_interpretation.get('verdict') or '')
    macro_candidates = []
    micro_candidates = []
    expression_candidates = []
    kill_or_stop = []

    if decision == 'reject':
        kill_or_stop.append('Do not mutate around a rejected branch unless the researcher proposes a materially different return-source hypothesis.')
    if verdict in {'negative', 'inconclusive'}:
        macro_candidates.append('restate_or_replace_return_source_hypothesis')
    if monetization_model in {'mixed', 'constraint_driven_arbitrage'}:
        macro_candidates.append('separate_constraint_mechanism_from_price_noise')
    if gap in {'positive_signal_but_long_side_failed', 'monotonicity_failed_top_group_not_best'}:
        expression_candidates.extend([
            'factor_direction_or_sign_revision',
            'linearize_economic_state_mapping',
            'replace_short_leg_driven_component',
        ])
    if 'robustness' in revision_operator or 'boundary' in revision_operator:
        micro_candidates.extend([
            'window_mutation',
            'winsorize_or_rank_safe_transform',
            'lag_and_delay_sanity_check',
        ])
    if modification_targets:
        micro_candidates.append('targeted_patch_for_top_step5_modification')

    if not micro_candidates:
        micro_candidates.extend(['factor_direction_test', 'lookback_window_search', 'cross_sectional_normalization_search'])
    if not macro_candidates:
        macro_candidates.append('preserve_current_return_source_hypothesis')
    if not expression_candidates:
        expression_candidates.append('factor_expression_monotonicity_ablation')

    return {
        'macro_revision': {
            'meaning': 'Change the economic/research thesis, factor family, or information source.',
            'candidate_actions': macro_candidates,
            'approval_required': True,
        },
        'micro_revision': {
            'meaning': 'Keep the thesis but mutate formula parameters, signs, transforms, lags, windows, or normalizers.',
            'candidate_actions': micro_candidates,
            'approval_required': decision == 'iterate',
        },
        'expression_revision': {
            'meaning': 'Change the factor expression or Step3B code so high factor values better express the economic long-side thesis.',
            'candidate_actions': expression_candidates,
            'approval_required': decision == 'iterate',
        },
        'portfolio_revision': {
            'meaning': 'Forbidden under the current mandate: do not fix a factor by changing short selling, direct decile trading, or portfolio expression.',
            'candidate_actions': ['forbidden_no_short_no_direct_decile_no_trading_wrapper_repair'],
            'approval_required': False,
        },
        'stop_or_kill': {
            'candidate_actions': kill_or_stop or ['apply_existing_kill_criteria_if_next_iteration_fails'],
            'kill_criteria': math_discipline.get('kill_criteria') or [],
        },
    }


def build_program_search_policy(
    framework: dict[str, Any],
    metric_interpretation: dict[str, Any],
    math_discipline: dict[str, Any],
    decision: str,
    modification_targets: list[str],
    retrieval_context: dict[str, Any],
) -> dict[str, Any]:
    verdict = str(metric_interpretation.get('verdict') or '')
    budget = 3 if decision == 'iterate' else 1 if decision == 'needs_human_review' else 0
    method_library = {
        'genetic_algorithm': {
            'use_when': 'Formula is executable and we need program-level mutation/crossover over operators, signs, windows, transforms, and neutralizers.',
            'operators': [
                'sign_flip',
                'window_mutation',
                'rank_vs_raw_substitution',
                'operator_substitution_corr_cov_rank_argmax',
                'lag_or_delay_insertion',
                'neutralization_or_grouping_toggle',
            ],
            'selection_objective': [
                'out_of_sample_rank_ic_ir',
                'long_side_sharpe_ratio',
                'long_side_drawdown_and_recovery',
                'monotonicity_of_factor_value_to_forward_return',
                'robustness_across_year_regime_universe',
                'complexity_penalty',
            ],
            'guardrail': 'Every child formula must keep information-set legality and record its parent, mutation, and failure reason.',
        },
        'bayesian_search': {
            'use_when': 'The thesis is plausible and the main uncertainty is numeric/discrete parameters, not the semantic family.',
            'search_space_examples': [
                'lookback_window',
                'decay_halflife',
                'winsorize_quantile',
                'neutralization_scope',
            ],
            'objective': 'maximize long-side Sharpe and monotonic expression quality under leakage, drawdown, capacity, and complexity constraints',
            'guardrail': 'Do not tune on one sample only; require walk-forward or split-period validation before promotion.',
        },
        'reinforcement_learning': {
            'use_when': 'There is enough historical trajectory data to learn a policy over revise/promote/reject actions; not recommended for a single cold-start factor.',
            'state': [
                'factor_family',
                'metric_vector',
                'failure_signature',
                'revision_history',
                'retrieved_case_features',
            ],
            'actions': [
                'mutate_formula',
                'search_parameters',
                'request_human_review',
                'stop_branch',
            ],
            'reward': 'long-side improvement + monotonicity + robustness + novelty - complexity - repeated_failure_penalty',
            'guardrail': 'RL policy suggestions are advisory until enough validated trajectories exist in the knowledge base.',
        },
        'multi_agent_parallel_exploration': {
            'use_when': 'A factor has multiple plausible failure explanations and independent branches can be tested without write conflicts.',
            'coordination_rule': 'One branch per subagent, each with a disjoint generated_code output path and a required evidence report.',
            'aggregation_rule': 'Step6 compares branches by robust reward, novelty, and thesis preservation before choosing the next canonical Step3B candidate.',
        },
    }

    branches = []
    if decision == 'iterate':
        branches.append({
            'branch_id': 'exploit_micro_revision',
            'method': 'bayesian_search',
            'goal': 'Tune windows, clipping, delay, and normalization so the expression preserves the thesis and improves long-side monotonicity.',
            'owned_by': 'step3b_parameter_branch',
            'modification_targets': modification_targets[:3],
        })
        branches.append({
            'branch_id': 'explore_formula_mutation',
            'method': 'genetic_algorithm',
            'goal': 'Try controlled program mutations such as sign flip, operator substitution, and lag insertion.',
            'owned_by': 'step3b_formula_branch',
            'modification_targets': ['formula_operator_or_direction_search'],
        })
        if verdict in {'negative', 'inconclusive'}:
            branches.append({
                'branch_id': 'macro_hypothesis_branch',
                'method': 'multi_agent_parallel_exploration',
                'goal': 'Challenge the original return-source hypothesis and propose a neighboring factor family if justified.',
                'owned_by': 'researcher_macro_branch',
                'modification_targets': ['return_source_hypothesis_rewrite'],
            })
    elif decision == 'needs_human_review':
        branches.append({
            'branch_id': 'human_review_packet',
            'method': 'multi_agent_parallel_exploration',
            'goal': 'Prepare evidence packets for human selection before any code mutation.',
            'owned_by': 'researcher_review_branch',
            'modification_targets': modification_targets[:3],
        })

    return {
        'purpose': 'Choose how Step6 should explore or exploit the factor search space after reading Step4/5 evidence.',
        'long_only_policy': LONG_ONLY_POLICY,
        'search_budget_branches': budget,
        'explore_exploit_rule': (
            'When budget >= 2, run at least one exploit branch that refines the current factor and one explore branch that tests a neighboring formula/hypothesis.'
        ),
        'method_library': method_library,
        'recommended_next_search': {
            'decision': decision,
            'branches': branches,
            'requires_human_approval_before_code_change': decision == 'iterate',
            'why_not_rl_first': (
                'RL is kept as a future policy learner until the knowledge base contains enough revision trajectories; GA/Bayesian search are more appropriate for the current single-factor loop.'
            ),
        },
        'retrieval_used_for_priors': {
            'similar_case_count': len(retrieval_context.get('similar_cases') or []),
            'embedding_index_available': retrieval_context.get('embedding_index_available'),
        },
    }


def build_diversity_position(
    framework: dict[str, Any],
    retrieval_context: dict[str, Any],
    decision: str,
) -> dict[str, Any]:
    similar_cases = retrieval_context.get('similar_cases') or []
    same_family = [
        str(item.get('factor_id'))
        for item in similar_cases
        if item.get('factor_id')
    ][:5]
    return {
        'factor_family': framework.get('factor_family'),
        'library_overlap_signals': same_family,
        'novelty_assessment': (
            'potentially_redundant_until_distinguished_from_retrieved_cases'
            if same_family else 'cold_start_or_low_overlap_family'
        ),
        'diversity_value': (
            'Do not promote only because metrics pass; promotion should add a differentiated return source or robustness profile to the official library.'
            if decision == 'promote_official'
            else 'Use iteration to clarify whether this branch contributes new knowledge or merely repeats a known weak family.'
        ),
        'future_retrieval_tags': [
            str(framework.get('factor_family') or 'mixed_or_unclear'),
            str(framework.get('monetization_model') or 'mixed'),
            str(framework.get('bias_type') or 'mixed_or_unclear'),
        ],
    }


def derive_strengths_weaknesses(bundle: dict[str, Any], payloads: dict[str, dict[str, Any]]) -> tuple[list[str], list[str], list[str], list[str]]:
    run_master = bundle['factor_run_master']
    case = bundle['factor_case_master']
    evaluation = bundle['factor_evaluation']
    handoff = bundle['handoff_to_step6']
    run_status = str(run_master.get('run_status') or '')
    final_status = str(case.get('final_status') or '')
    backend_runs = (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    backend_status = {str(item.get('backend')): str(item.get('status')) for item in backend_runs}
    metrics = extract_headline_metrics(payloads)
    metric_interpretation = build_metric_interpretation(metrics, payloads)

    strengths: list[str] = []
    weaknesses: list[str] = []
    risks: list[str] = []
    modification_targets: list[str] = []

    if backend_status.get('self_quant_analyzer') == 'success':
        strengths.append('self_quant backend completed and produced interpretable IC diagnostics')
    if backend_status.get('qlib_backtest') == 'success':
        strengths.append('qlib backend completed and produced grouped diagnostics plus native minimal backtest outputs')
    if (metrics.get('rank_ic_mean') or 0) > 0:
        strengths.append('cross-sectional ranking signal is directionally positive in self_quant diagnostics')
    long_side_review = build_long_side_adoption_review(metrics)
    top_return = _safe_float(metrics.get('long_side_annual_return'))
    business_review = long_side_review.get('factor_as_business_review') or {}
    long_side_sharpe = _safe_float(business_review.get('sharpe_ratio'))
    if long_side_review['long_side_status'] == 'official_ready':
        strengths.append('long-side Sharpe clears the official admission threshold and raw long-side revenue is positive')
    elif long_side_review['long_side_status'] == 'supportive':
        strengths.append('long-side Sharpe clears the candidate threshold; this is adoption-relevant but still below official certainty')
    for item in metric_interpretation.get('positive_evidence') or []:
        if item not in strengths:
            strengths.append(str(item))

    if run_status == 'partial' or final_status == 'partial':
        weaknesses.append('current run is still partial rather than fully validated')
        modification_targets.append('close remaining partial coverage gap before promotion')
    if backend_status.get('qlib_backtest') != 'success':
        weaknesses.append('qlib backend is not yet consistently successful')
        modification_targets.append('stabilize qlib backtest path and payload contract')
    if (metrics.get('rank_ic_mean') or 0) <= 0:
        weaknesses.append('rank IC is not positive enough to support promotion')
        modification_targets.append('revisit signal construction and cross-sectional ranking behavior')
    if top_return is None:
        weaknesses.append('long-side highest-score group evidence is missing')
        modification_targets.append('add long-side Sharpe/drawdown/recovery diagnostics and rerun Step4/5 before any promotion')
    elif top_return <= 0:
        weaknesses.append('long-side highest-score group return is not positive; short-side or long-short evidence cannot rescue adoption')
        modification_targets.append('revise factor expression and Step3B code so high factor values map to positive long-side expected returns')
    if long_side_sharpe is None:
        weaknesses.append('long-side Sharpe is missing; raw return cannot justify admission')
        modification_targets.append('ensure Step4 emits long-side Sharpe, drawdown, and recovery evidence')
    elif long_side_sharpe < LONG_SIDE_PERFORMANCE_THRESHOLDS['candidate_min_sharpe']:
        weaknesses.append(f'long-side Sharpe={long_side_sharpe:.3f} is below candidate threshold {LONG_SIDE_PERFORMANCE_THRESHOLDS["candidate_min_sharpe"]:.2f}')
        modification_targets.append('revise factor expression/code to improve long-side Sharpe by reducing volatility drag and drawdown, not by adding short exposure')
    for item in metric_interpretation.get('negative_evidence') or []:
        if item not in weaknesses:
            weaknesses.append(str(item))
    for item in metric_interpretation.get('ambiguities') or []:
        if item not in risks:
            risks.append(str(item))
    if long_side_review['monotonicity_diagnostic'] in {'top_group_below_bottom_group', 'flat_top_vs_bottom'}:
        modification_targets.append('repair factor-expression monotonicity; do not switch to short selling, direct decile trading, or portfolio-expression fixes')

    for warning in evaluation.get('warnings') or []:
        risks.append(str(warning))
    for warning in case.get('known_limits') or []:
        if str(warning) not in risks:
            risks.append(str(warning))
    for item in handoff.get('known_limits') or []:
        if str(item) not in risks:
            risks.append(str(item))

    for lesson in case.get('lessons') or []:
        lesson_text = str(lesson)
        if lesson_text not in risks and lesson_text not in weaknesses and 'warning' in lesson_text.lower():
            risks.append(lesson_text)

    for action in handoff.get('next_actions') or []:
        action_text = str(action)
        if action_text and action_text not in modification_targets:
            modification_targets.append(action_text)

    if not modification_targets and final_status != 'validated':
        modification_targets.append('review factor logic against Step4 evidence and decide whether to iterate or stop')

    return strengths, weaknesses, risks, modification_targets


def decide(bundle: dict[str, Any], payloads: dict[str, dict[str, Any]]) -> str:
    run_master = bundle['factor_run_master']
    case = bundle['factor_case_master']
    run_status = str(run_master.get('run_status') or '')
    final_status = str(case.get('final_status') or '')
    backend_runs = (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    successful_backends = {str(item.get('backend')) for item in backend_runs if item.get('status') == 'success'}
    metrics = extract_headline_metrics(payloads)
    metric_interpretation = build_metric_interpretation(metrics, payloads)
    rank_ic = _safe_float(metrics.get('rank_ic_mean'))
    long_side_review = build_long_side_adoption_review(metrics)
    long_side_ok = long_side_review['long_side_status'] == 'official_ready'
    required_backends_ok = {'self_quant_analyzer', 'qlib_backtest'}.issubset(successful_backends)

    if run_status == 'failed' or final_status == 'failed':
        return 'reject'

    severe_signal_failure = (
        rank_ic is not None and rank_ic <= 0
        and long_side_review['long_side_status'] == 'failed'
    )
    if severe_signal_failure:
        return 'reject'

    if final_status == 'validated' and run_status == 'success' and required_backends_ok:
        promotion_metrics_ok = (
            metric_interpretation.get('verdict') == 'supportive'
            and (rank_ic is None or rank_ic > 0)
            and long_side_ok
        )
        if promotion_metrics_ok:
            return 'promote_official'
        return 'iterate'

    if successful_backends:
        return 'iterate'
    return 'needs_human_review'


def _status_from_backend(backend_statuses: dict[str, str], backend: str) -> str:
    status = str(backend_statuses.get(backend) or '').strip().lower()
    if status == 'success':
        return 'complete'
    if status == 'failed':
        return 'failed'
    if status:
        return 'partial'
    return 'missing'


def _qlib_native_status(payloads: dict[str, dict[str, Any]], backend_statuses: dict[str, str]) -> str:
    qlib = payloads.get('qlib_backtest') if isinstance(payloads.get('qlib_backtest'), dict) else {}
    status = str(backend_statuses.get('qlib_backtest') or qlib.get('status') or '').strip().lower()
    if status == 'failed':
        return 'failed'
    if not qlib:
        return 'not_attempted'
    mode = str(qlib.get('mode') or '').strip().lower()
    if status == 'success' and mode == 'native_minimal':
        return 'native_minimal_success'
    if status == 'success':
        return 'native_backtest_success'
    if qlib.get('readiness'):
        return 'preflight_ready'
    return 'partial_payload'


def build_evidence_status(
    *,
    run_master: dict[str, Any],
    evaluation: dict[str, Any],
    payloads: dict[str, dict[str, Any]],
    backend_statuses: dict[str, str],
    metrics: dict[str, Any],
    decision: str,
) -> dict[str, Any]:
    long_complete = all(_safe_float(metrics.get(key)) is not None for key in [
        'long_side_annual_return',
        'long_side_max_drawdown',
        'long_side_recovery_days',
    ])
    cost_complete = _safe_float(metrics.get('cost_adjusted_annual_return')) is not None
    drawdown_complete = all(_safe_float(metrics.get(key)) is not None for key in [
        'long_side_max_drawdown',
        'long_side_recovery_days',
    ])
    long_ret = _safe_float(metrics.get('long_side_annual_return'))
    cost_ret = _safe_float(metrics.get('cost_adjusted_annual_return'))
    max_dd = _safe_float(metrics.get('long_side_max_drawdown'))
    if cost_ret is not None and cost_ret <= 0:
        promotion_gate_status = 'blocked_by_cost'
    elif long_ret is not None and long_ret <= 0:
        promotion_gate_status = 'blocked_by_long_side'
    elif max_dd is not None and max_dd < -0.35:
        promotion_gate_status = 'blocked_by_drawdown'
    elif decision == 'promote_official':
        promotion_gate_status = 'open'
    else:
        promotion_gate_status = 'blocked_by_evidence'
    research_decision = 'promote' if decision == 'promote_official' else decision
    if research_decision not in {'promote', 'iterate', 'reject', 'needs_human_review'}:
        research_decision = 'needs_human_review'
    return {
        'version': 'factorforge_step6_evidence_status_v1',
        'status': 'complete' if evaluation.get('artifact_ready') is True else 'partial_evaluation_artifact',
        'run_status': str(run_master.get('run_status') or evaluation.get('run_status') or 'unknown'),
        'wrapper_validation_status': 'PASS' if evaluation.get('artifact_ready') is True else 'BLOCK',
        'self_quant_evidence_status': _status_from_backend(backend_statuses, 'self_quant_analyzer'),
        'qlib_native_status': _qlib_native_status(payloads, backend_statuses),
        'long_side_evidence_status': 'complete' if long_complete else 'missing',
        'cost_model_status': 'complete' if cost_complete else 'missing',
        'drawdown_geometry_status': 'complete' if drawdown_complete else 'missing',
        'research_decision': research_decision,
        'promotion_gate_status': promotion_gate_status,
        'source': 'step6_mapped_from_step4_step5_evidence',
    }


def build_iteration_payload(bundle: dict[str, Any], payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_master = bundle['factor_run_master']
    case = bundle['factor_case_master']
    evaluation = bundle['factor_evaluation']
    handoff = bundle['handoff_to_step6']
    report_id = run_master['report_id']
    factor_id = run_master.get('factor_id') or case.get('factor_id')
    decision = decide(bundle, payloads)
    strengths, weaknesses, risks, modification_targets = derive_strengths_weaknesses(bundle, payloads)
    metrics = extract_headline_metrics(payloads)
    retrieval_context = build_retrieval_context(bundle, payloads)
    prior_iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{report_id}.json'
    prior_iteration_no = 0
    if prior_iteration_path.exists():
        try:
            prior_iteration_no = int((load_json(prior_iteration_path).get('iteration_no') or 0))
        except Exception:
            prior_iteration_no = 0
    backend_statuses = {
        str(item.get('backend')): str(item.get('status'))
        for item in (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    }
    evidence_status = build_evidence_status(
        run_master=run_master,
        evaluation=evaluation,
        payloads=payloads,
        backend_statuses=backend_statuses,
        metrics=metrics,
        decision=decision,
    )

    thesis = (
        'Factor shows enough evidence to enter the official library.' if decision == 'promote_official'
        else 'Factor has usable evidence but still needs another implementation/evaluation round.' if decision == 'iterate'
        else 'Current evidence suggests the factor should be stopped rather than iterated further.' if decision == 'reject'
        else 'Current evidence is insufficient or ambiguous and needs explicit human review.'
    )
    framework = infer_research_framework(bundle, payloads, decision)
    research_memo = build_research_memo(bundle, payloads, framework, metrics, decision)
    learning_and_innovation = build_learning_and_innovation(framework, decision, strengths, weaknesses, modification_targets, retrieval_context)
    research_memo['learning_and_innovation'] = learning_and_innovation
    metric_interpretation = research_memo.get('metric_interpretation') or {}
    math_discipline = research_memo.get('math_discipline_review') or {}
    iteration_no = prior_iteration_no + 1
    experience_chain = build_experience_chain(
        str(report_id),
        str(factor_id),
        iteration_no,
        decision,
        strengths,
        weaknesses,
        retrieval_context,
        prior_iteration_no,
    )
    revision_taxonomy = build_revision_taxonomy(
        framework,
        metric_interpretation,
        math_discipline,
        modification_targets,
        decision,
    )
    program_search_policy = build_program_search_policy(
        framework,
        metric_interpretation,
        math_discipline,
        decision,
        modification_targets,
        retrieval_context,
    )
    diversity_position = build_diversity_position(framework, retrieval_context, decision)
    evidence_audit = build_evidence_audit(bundle, payloads, metrics)
    mechanism_analysis = build_mechanism_analysis(bundle, payloads, metrics, evidence_audit, retrieval_context)
    formula_specific_derivation = build_formula_specific_derivation(
        bundle.get('factor_spec_master') or {},
        mechanism_analysis,
        metrics,
    )
    mechanism_analysis['formula_specific_derivation'] = formula_specific_derivation
    mechanism_analysis['mechanism_formula_consistency'] = validate_mechanism_formula_consistency(
        bundle.get('factor_spec_master') or {},
        mechanism_analysis,
        formula_specific_derivation,
    )
    current_identity = (run_master.get('artifact_identity') or case.get('artifact_identity') or {})
    case_comparison = build_case_comparison(mechanism_analysis, retrieval_context, current_identity, {'evidence_audit': evidence_audit})
    if (
        decision == 'promote_official'
        and mechanism_analysis.get('mechanism_fit') != 'strong'
        and mechanism_analysis.get('return_source') != 'unknown'
    ):
        decision = 'iterate'
        thesis = 'Factor has usable evidence but needs mechanism support before official promotion.'
        experience_chain = build_experience_chain(
            str(report_id),
            str(factor_id),
            iteration_no,
            decision,
            strengths,
            weaknesses,
            retrieval_context,
            prior_iteration_no,
        )
        revision_taxonomy = build_revision_taxonomy(
            framework,
            metric_interpretation,
            math_discipline,
            modification_targets,
            decision,
        )
        program_search_policy = build_program_search_policy(
            framework,
            metric_interpretation,
            math_discipline,
            decision,
            modification_targets,
            retrieval_context,
        )
        diversity_position = build_diversity_position(framework, retrieval_context, decision)
    revision_strategy = build_revision_strategy(
        decision,
        metrics,
        evidence_audit,
        mechanism_analysis,
        case_comparison,
        framework,
        math_discipline,
    )
    search_policy_decision = build_search_policy_decision(
        decision,
        evidence_audit,
        mechanism_analysis,
        case_comparison,
        revision_strategy,
        framework,
    )
    program_search_policy.setdefault('recommended_next_search', {})['branches'] = search_policy_decision.get('branch_templates') or []
    program_search_policy['recommended_next_search']['recommended_mode'] = search_policy_decision.get('recommended_mode')
    program_search_policy['recommended_next_search']['requires_human_approval_before_code_change'] = search_policy_decision.get('human_approval_required') is True
    program_search_policy['recommended_next_search']['execution_allowed_by_default'] = False
    program_search_policy['recommended_next_search']['selection_rationale'] = search_policy_decision.get('selection_rationale') or []
    should_modify_step3b = should_write_step3b_handoff(
        decision,
        revision_strategy,
        case_comparison,
        search_policy_decision,
    )
    research_memo['evidence_audit'] = evidence_audit
    research_memo['mechanism_analysis'] = mechanism_analysis
    research_memo['case_comparison'] = case_comparison
    research_memo['revision_strategy'] = revision_strategy
    research_memo['search_policy_decision'] = search_policy_decision
    research_memo['experience_chain'] = experience_chain
    research_memo['revision_taxonomy'] = revision_taxonomy
    research_memo['program_search_policy'] = program_search_policy
    research_memo['diversity_position'] = diversity_position
    researcher_journal = load_researcher_journal(str(report_id))
    researcher_agent_memo = load_researcher_agent_memo(str(report_id))
    if researcher_journal:
        research_memo['researcher_journal'] = researcher_journal
        research_memo.setdefault('evidence_quality', {}).setdefault('notes', []).append(
            'Full-workflow researcher journal was loaded and preserved under research_memo.researcher_journal.'
        )
    if researcher_agent_memo:
        research_memo['researcher_agent_memo'] = researcher_agent_memo
        research_memo.setdefault('evidence_quality', {}).setdefault('notes', []).append(
            'External Step6 researcher-agent memo was loaded and preserved under research_memo.researcher_agent_memo.'
        )

    return {
        'report_id': report_id,
        'factor_id': factor_id,
        'iteration_no': iteration_no,
        'source_case_status': case.get('final_status'),
        'evidence_summary': {
            'run_status': run_master.get('run_status'),
            'backend_statuses': backend_statuses,
            'headline_metrics': metrics,
            'evidence_status': evidence_status,
            'step5_lessons': case.get('lessons') or handoff.get('lessons') or [],
            'step5_next_actions': case.get('next_actions') or handoff.get('next_actions') or [],
        },
        'evidence_status': evidence_status,
        'research_judgment': {
            'decision': decision,
            'thesis': thesis,
            'strengths': strengths,
            'weaknesses': weaknesses,
            'risks': risks,
            'why_now': 'Step6 research memo based on Step4/5 executable artifacts, backend payloads, return-source logic, and historical retrieval context.',
            'factor_investing_framework': framework,
            'research_memo': research_memo,
            'experience_chain': experience_chain,
            'revision_taxonomy': revision_taxonomy,
            'program_search_policy': program_search_policy,
            'diversity_position': diversity_position,
        },
        'knowledge_writeback': {
            'success_patterns': strengths,
            'failure_patterns': weaknesses,
            'modification_hypotheses': modification_targets,
            'factor_family': framework['factor_family'],
            'monetization_model': framework['monetization_model'],
            'bias_type': framework['bias_type'],
            'return_source_hypothesis': framework['return_source_hypothesis'],
            'expected_failure_regimes': framework['expected_failure_regimes'],
            'objective_constraint_dependency': framework['objective_constraint_dependency'],
            'constraint_sources': framework['constraint_sources'],
            'crowding_risk': framework['crowding_risk'],
            'capacity_constraints': framework['capacity_constraints'],
            'implementation_risk': framework['implementation_risk'],
            'improvement_frontier': framework['improvement_frontier'],
            'program_search_axes': framework['program_search_axes'],
            'review_checklist': framework['review_checklist'],
            'revision_principles': framework['revision_principles'],
            'research_commentary': framework['research_commentary'],
            'learning_and_innovation': learning_and_innovation,
            'experience_chain': experience_chain,
            'revision_taxonomy': revision_taxonomy,
            'program_search_policy': program_search_policy,
            'diversity_position': diversity_position,
            'research_memo': research_memo,
        },
        'retrieval_context': retrieval_context,
        'loop_action': {
            'should_modify_step3b': should_modify_step3b,
            'loop_authorization': revision_strategy.get('loop_authorization'),
            'modification_targets': modification_targets,
            'parallel_exploration_branches': (program_search_policy.get('recommended_next_search') or {}).get('branches') or [],
            'search_methods': list((program_search_policy.get('method_library') or {}).keys()),
            'requires_human_approval_before_code_change': should_modify_step3b,
            'next_runner': 'step3b' if should_modify_step3b else 'stop',
            'stop_reason': None if should_modify_step3b else (revision_strategy.get('loop_authorization') or decision),
        },
        'upstream_handoff': {
            'step5_handoff_path': str(bundle['paths']['handoff_to_step6']),
            'step5_next_actions': handoff.get('next_actions') or [],
        },
        'created_at_utc': utc_now(),
        'producer': 'step6',
    }


def build_factor_record(iteration: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    case = bundle['factor_case_master']
    run_master = bundle['factor_run_master']
    framework = iteration['research_judgment'].get('factor_investing_framework') or {}
    return {
        'report_id': iteration['report_id'],
        'factor_id': iteration['factor_id'],
        'decision': iteration['research_judgment']['decision'],
        'iteration_no': iteration['iteration_no'],
        'run_status': run_master.get('run_status'),
        'final_status': case.get('final_status'),
        'headline_metrics': iteration['evidence_summary']['headline_metrics'],
        'strengths': iteration['research_judgment']['strengths'],
        'weaknesses': iteration['research_judgment']['weaknesses'],
        'risks': iteration['research_judgment']['risks'],
        'factor_family': framework.get('factor_family'),
        'monetization_model': framework.get('monetization_model'),
        'bias_type': framework.get('bias_type'),
        'return_source_hypothesis': framework.get('return_source_hypothesis'),
        'expected_failure_regimes': framework.get('expected_failure_regimes'),
        'objective_constraint_dependency': framework.get('objective_constraint_dependency'),
        'constraint_sources': framework.get('constraint_sources'),
        'crowding_risk': framework.get('crowding_risk'),
        'capacity_constraints': framework.get('capacity_constraints'),
        'implementation_risk': framework.get('implementation_risk'),
        'improvement_frontier': framework.get('improvement_frontier'),
        'program_search_axes': framework.get('program_search_axes'),
        'review_checklist': framework.get('review_checklist'),
        'revision_principles': framework.get('revision_principles'),
        'learning_and_innovation': iteration['knowledge_writeback'].get('learning_and_innovation'),
        'experience_chain': iteration['knowledge_writeback'].get('experience_chain'),
        'revision_taxonomy': iteration['knowledge_writeback'].get('revision_taxonomy'),
        'program_search_policy': iteration['knowledge_writeback'].get('program_search_policy'),
        'diversity_position': iteration['knowledge_writeback'].get('diversity_position'),
        'research_memo': iteration['research_judgment'].get('research_memo'),
        'evidence_identity': iteration.get('evidence_identity') or {},
        'source_case_identity': iteration.get('source_case_identity') or {},
        'implementation_mode_decision': iteration.get('implementation_mode_decision') or {},
        'decision_lineage': iteration.get('decision_lineage') or {},
        'knowledge_provenance': iteration.get('knowledge_provenance') or {},
        'promotion_gate': iteration.get('promotion_gate') or {},
        'created_at_utc': iteration['created_at_utc'],
        'producer': 'step6',
    }


def build_knowledge_record(iteration: dict[str, Any]) -> dict[str, Any]:
    return {
        'report_id': iteration['report_id'],
        'factor_id': iteration['factor_id'],
        'decision': iteration['research_judgment']['decision'],
        'success_patterns': iteration['knowledge_writeback']['success_patterns'],
        'failure_patterns': iteration['knowledge_writeback']['failure_patterns'],
        'modification_hypotheses': iteration['knowledge_writeback']['modification_hypotheses'],
        'factor_family': iteration['knowledge_writeback']['factor_family'],
        'monetization_model': iteration['knowledge_writeback']['monetization_model'],
        'bias_type': iteration['knowledge_writeback']['bias_type'],
        'return_source_hypothesis': iteration['knowledge_writeback']['return_source_hypothesis'],
        'expected_failure_regimes': iteration['knowledge_writeback']['expected_failure_regimes'],
        'objective_constraint_dependency': iteration['knowledge_writeback']['objective_constraint_dependency'],
        'constraint_sources': iteration['knowledge_writeback']['constraint_sources'],
        'crowding_risk': iteration['knowledge_writeback']['crowding_risk'],
        'capacity_constraints': iteration['knowledge_writeback']['capacity_constraints'],
        'implementation_risk': iteration['knowledge_writeback']['implementation_risk'],
        'improvement_frontier': iteration['knowledge_writeback']['improvement_frontier'],
        'program_search_axes': iteration['knowledge_writeback']['program_search_axes'],
        'review_checklist': iteration['knowledge_writeback']['review_checklist'],
        'revision_principles': iteration['knowledge_writeback']['revision_principles'],
        'research_commentary': iteration['knowledge_writeback']['research_commentary'],
        'learning_and_innovation': iteration['knowledge_writeback'].get('learning_and_innovation'),
        'experience_chain': iteration['knowledge_writeback'].get('experience_chain'),
        'revision_taxonomy': iteration['knowledge_writeback'].get('revision_taxonomy'),
        'program_search_policy': iteration['knowledge_writeback'].get('program_search_policy'),
        'diversity_position': iteration['knowledge_writeback'].get('diversity_position'),
        'research_memo': iteration['knowledge_writeback'].get('research_memo'),
        'knowledge_scope': 'same_factor',
        'source_identity': iteration.get('source_case_identity') or {},
        'evidence_identity': iteration.get('evidence_identity') or {},
        'source_case_identity': iteration.get('source_case_identity') or {},
        'implementation_mode_decision': iteration.get('implementation_mode_decision') or {},
        'decision_lineage': iteration.get('decision_lineage') or {},
        'knowledge_provenance': iteration.get('knowledge_provenance') or {},
        'can_be_reused_by_future_agents': True,
        'reuse_constraints': [
            'Only reuse as same-factor evidence when artifact_identity matches.',
            'Use as similar-case analogy when factor/report/branch/run identity differs.',
        ],
        'created_at_utc': iteration['created_at_utc'],
        'producer': 'step6',
    }


def build_handoff_to_step3b(iteration: dict[str, Any]) -> dict[str, Any]:
    parent_identity = iteration.get('source_case_identity') or {}
    parent_branch = str(parent_identity.get('branch_id') or 'main')
    new_branch = f'{parent_branch}_iter_{int(iteration.get("iteration_no") or 1):03d}'
    return {
        'report_id': iteration['report_id'],
        'factor_id': iteration['factor_id'],
        'trigger': 'step6_iteration',
        'parent_identity': parent_identity,
        'new_branch_id': new_branch,
        'parent_run_id': parent_identity.get('run_id'),
        'revision_reason': iteration['research_judgment'].get('thesis'),
        'revision_target': parent_identity.get('implementation_mode'),
        'must_preserve': [
            'source_type',
            'factor_id',
            'original_formula_or_hypothesis',
        ],
        'must_change': iteration['loop_action']['modification_targets'],
        'forbidden_changes': [
            'portfolio expression',
            'decile trading',
            'short-side adoption',
        ],
        'modification_targets': iteration['loop_action']['modification_targets'],
        'research_judgment': iteration['research_judgment'],
        'knowledge_writeback': iteration['knowledge_writeback'],
        'artifact_identity': derive_identity(parent_identity, 'handoff_to_step3b'),
        'evidence_identity': iteration.get('evidence_identity') or {},
        'source_case_identity': parent_identity,
        'implementation_mode_decision': iteration.get('implementation_mode_decision') or {},
        'decision_lineage': iteration.get('decision_lineage') or {},
        'knowledge_provenance': iteration.get('knowledge_provenance') or {},
        'created_at_utc': iteration['created_at_utc'],
        'producer': 'step6',
    }


def _metric_or_none(metrics: dict[str, Any], key: str) -> Any:
    value = metrics.get(key)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _brief_scalar(value: Any) -> str:
    if value is None:
        return 'missing'
    if isinstance(value, float):
        return f'{value:.6g}'
    return str(value)


def _brief_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _brief_first_nonempty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return 'missing: source field unavailable'


def find_loop_brief_chart_evidence(report_id: str) -> dict[str, str]:
    search_roots = [
        EVAL / report_id / 'self_quant_analyzer',
        FF / 'archive' / report_id / 'evaluations' / 'self_quant_analyzer',
    ]
    evidence: dict[str, str] = {}
    searched = ', '.join(str(root) for root in search_roots)
    for key, filename in CHART_ARTIFACT_FILENAMES.items():
        found = None
        for root in search_roots:
            candidate = root / filename
            if candidate.exists():
                found = str(candidate)
                break
        evidence[key] = found or f'missing: {filename} not found under {searched}'
    return evidence


def build_loop_research_brief(iteration: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    research_judgment = iteration.get('research_judgment') or {}
    research_memo = research_judgment.get('research_memo') or {}
    metrics = (iteration.get('evidence_summary') or {}).get('headline_metrics') or {}
    mechanism = research_memo.get('mechanism_analysis') or {}
    mechanism_math_contract = mechanism.get('mechanism_math_contract') or mechanism_math_contract_from_bundle(bundle)
    mechanism_math_summary = dict(mechanism.get('mechanism_math_summary') or mechanism_math_summary_from_contract(mechanism_math_contract))
    mechanism_math_summary.setdefault('economic_mechanism_family', mechanism_math_summary.get('model_family') or mechanism_math_contract.get('model_family') or 'other')
    mechanism_math_summary.setdefault('math_tool_family', mechanism_math_contract.get('math_tool_family') or mechanism_math_summary.get('model_family') or 'other')
    mechanism_math_summary.setdefault('model_equation_family', mechanism_math_contract.get('model_equation_family') or 'under_specified')
    mechanism['mechanism_math_summary'] = mechanism_math_summary
    formula_specific_derivation = mechanism.get('formula_specific_derivation') or {}
    mechanism_formula_consistency = mechanism.get('mechanism_formula_consistency') or {}
    case_comparison = research_memo.get('case_comparison') or {}
    revision_strategy = research_memo.get('revision_strategy') or {}
    search_policy = research_memo.get('search_policy_decision') or {}
    evidence_audit = research_memo.get('evidence_audit') or {}
    math_discipline = research_memo.get('math_discipline_review') or {}
    formula_understanding = research_memo.get('formula_understanding') or {}
    metric_interpretation = research_memo.get('metric_interpretation') or {}
    long_side_quality = (evidence_audit.get('long_side_evidence_quality') or {})
    metric_consistency = (evidence_audit.get('metric_consistency') or {})
    cost_turnover = (evidence_audit.get('cost_and_turnover_risk') or {})
    spec = bundle.get('factor_spec_master') or {}
    canonical = spec.get('canonical_spec') or {}
    decision = str(research_judgment.get('decision') or '')
    branch_templates = search_policy.get('branch_templates') or []
    first_branch = branch_templates[0] if branch_templates and isinstance(branch_templates[0], dict) else {}
    hypotheses = revision_strategy.get('revision_hypotheses') or []
    first_hypothesis = hypotheses[0] if hypotheses and isinstance(hypotheses[0], dict) else {}
    promotion_gate = iteration.get('promotion_gate') or {}
    promoted = decision == 'promote_official' and promotion_gate.get('official_promotion_allowed') is True

    brief_metrics = {key: _metric_or_none(metrics, key) for key in CORE_LOOP_BRIEF_METRICS}
    brief_metrics['backend_statuses'] = (iteration.get('evidence_summary') or {}).get('backend_statuses') or {}

    gross_return = _safe_float(metrics.get('long_side_annual_return'))
    net_return = _safe_float(metrics.get('cost_adjusted_annual_return'))
    turnover = _safe_float(metrics.get('long_side_turnover_mean_daily') or metrics.get('turnover_mean'))
    sharpe = _safe_float(metrics.get('long_side_sharpe'))
    cost_sharpe = _safe_float(metrics.get('cost_adjusted_long_side_sharpe'))
    contradiction = []
    support = []
    if gross_return is not None and gross_return > 0:
        support.append(f'Gross long-side annual return is positive at {_brief_scalar(gross_return)}.')
    if _safe_float(metrics.get('rank_ic_mean')) is not None and _safe_float(metrics.get('rank_ic_mean')) > 0:
        support.append(f'Rank IC mean is positive at {_brief_scalar(metrics.get("rank_ic_mean"))}.')
    if net_return is not None and net_return < 0:
        contradiction.append(f'Cost-adjusted annual return is negative at {_brief_scalar(net_return)}.')
    if cost_sharpe is not None and cost_sharpe < 0:
        contradiction.append(f'Cost-adjusted long-side Sharpe is negative at {_brief_scalar(cost_sharpe)}.')
    if metric_consistency.get('short_side_dominance_suspected') is True:
        contradiction.append('Long-short diagnostics may be driven by short-side weakness; this is diagnostic only, not adoption evidence.')
    if not support:
        support.append('No strong supporting metric was available; treat this loop as evidence-gathering rather than promotion-ready.')
    if not contradiction:
        contradiction.append('No major contradiction was detected beyond normal robustness and monitoring requirements.')

    current_conclusion = (
        'Promoted to official library because evidence, mechanism, and promotion gate requirements are met.'
        if promoted
        else 'Not promoted. Step6 keeps this result as research evidence and requires more proof or human-approved revision before promotion.'
    )
    if decision == 'iterate' and revision_strategy.get('loop_authorization') == 'advisory_only':
        current_conclusion += ' The next branch is advisory only and does not authorize a Step3B handoff.'

    return {
        'brief_version': LOOP_RESEARCH_BRIEF_VERSION,
        'report_id': iteration.get('report_id'),
        'factor_id': iteration.get('factor_id'),
        'iteration_no': iteration.get('iteration_no'),
        'created_at_utc': utc_now(),
        'decision_snapshot': {
            'decision': decision,
            'promotion_status': 'official' if promoted else 'not_promoted',
            'loop_authorization': revision_strategy.get('loop_authorization') or ('not_needed' if not revision_strategy.get('revision_needed') else 'blocked'),
            'search_policy': search_policy.get('recommended_mode'),
            'next_branch': first_branch.get('branch_id') or (
                'advisory_or_human_approval_required' if decision == 'iterate' else 'none'
            ),
            'human_approval_required': search_policy.get('human_approval_required') is True or revision_strategy.get('requires_human_approval_before_code_change') is True,
        },
        'economic_interpretation': {
            'formula': str(canonical.get('formula_text') or 'missing: canonical formula unavailable'),
            'plain_english_interpretation': _brief_first_nonempty(
                formula_understanding.get('plain_language'),
                mechanism.get('mechanism_hypothesis'),
            ),
            'return_source': mechanism.get('return_source') or 'unknown',
            'factor_family': mechanism.get('factor_family') or 'other',
            'random_object': math_discipline.get('step1_random_object') or 'missing: random object unavailable',
            'target_statistic': math_discipline.get('target_statistic') or 'missing: target statistic unavailable',
            'information_set': math_discipline.get('information_set_legality') or 'missing: information-set review unavailable',
            'mechanism_hypothesis': mechanism.get('mechanism_hypothesis') or 'missing: mechanism hypothesis unavailable',
            'why_long_side_should_work': _brief_first_nonempty(
                (mechanism.get('expected_metric_signature') or {}).get('long_side_thesis'),
                metric_interpretation.get('summary'),
                research_judgment.get('thesis'),
            ),
            'necessary_conditions': _brief_list(mechanism.get('necessary_conditions')),
            'failure_regimes': _brief_list(mechanism.get('failure_regimes')),
            'mechanism_fit': mechanism.get('mechanism_fit') or 'unknown',
        },
        'metrics': brief_metrics,
        'chart_evidence': find_loop_brief_chart_evidence(str(iteration.get('report_id') or '')),
        'metric_analysis': {
            'supporting_evidence': support,
            'contradicting_evidence': contradiction,
            'cost_turnover_analysis': (
                f'Daily turnover={_brief_scalar(turnover)}; annual trading COGS={_brief_scalar(metrics.get("trading_cogs_annual"))}; '
                f'cost-adjusted annual return={_brief_scalar(net_return)}. '
                f"Cost verdict: {long_side_quality.get('cost_adjusted_status') or cost_turnover.get('turnover_verdict') or 'unknown'}."
            ),
            'drawdown_recovery_analysis': (
                f'Max drawdown={_brief_scalar(metrics.get("long_side_max_drawdown"))}; '
                f'recovery days={_brief_scalar(metrics.get("long_side_recovery_days"))}. '
                f"Drawdown status: {long_side_quality.get('drawdown_status') or 'unknown'}; "
                f"recovery status: {long_side_quality.get('recovery_status') or 'unknown'}."
            ),
            'monotonicity_analysis': (
                f"Monotonicity support is {metric_consistency.get('monotonicity_support') or 'unknown'}; "
                f'top decile mean={_brief_scalar(metrics.get("group_top_decile_mean_return"))}, '
                f'bottom decile mean={_brief_scalar(metrics.get("group_bottom_decile_mean_return"))}.'
            ),
            'short_side_long_short_diagnostic': (
                'Long-short and decile evidence are diagnostic_only. '
                f'Long-short spread mean={_brief_scalar(metrics.get("group_long_short_spread_mean"))}, '
                f'IR={_brief_scalar(metrics.get("group_long_short_spread_ir"))}; '
                f"short-side dominance suspected={metric_consistency.get('short_side_dominance_suspected')}."
            ),
            'implementation_or_data_concerns': _brief_list(evidence_audit.get('data_or_implementation_suspicions')),
        },
        'knowledge_comparison': {
            'same_factor_cases': _brief_list(case_comparison.get('same_factor_cases')),
            'similar_success_cases': _brief_list(case_comparison.get('similar_success_cases')),
            'similar_failure_cases': _brief_list(case_comparison.get('similar_failure_cases')),
            'imported_lessons': _brief_list(case_comparison.get('imported_lessons')),
            'rejected_lessons': _brief_list(case_comparison.get('rejected_lessons')),
            'anti_patterns': _brief_list(case_comparison.get('anti_pattern_cases')),
        },
        'mechanism_math_summary': mechanism_math_summary,
        'formula_specific_derivation': formula_specific_derivation,
        'mechanism_formula_consistency': mechanism_formula_consistency,
        'next_research_direction': {
            'primary_failure_signature': revision_strategy.get('primary_failure_signature') or 'none',
            'revision_hypothesis': first_hypothesis.get('hypothesis') or revision_strategy.get('reject_reason_if_no_revision') or 'No expression revision is currently approved.',
            'expression_level_change': first_hypothesis.get('expression_change') or 'none',
            'revision_target_math_object': first_hypothesis.get('revision_target_math_object') or (mechanism_math_summary.get('revision_operator_summary') or {}).get('revision_target_math_object') or 'under_specified',
            'math_change': first_hypothesis.get('math_change') or (mechanism_math_summary.get('revision_operator_summary') or {}).get('math_change') or 'under_specified',
            'why_not_portfolio_fix': first_hypothesis.get('why_not_portfolio_fix') or 'Portfolio expression, rebalance changes, short-leg adoption, and decile trading are forbidden repair paths; only factor expression or Step3B code changes may be considered after human approval.',
            'search_policy': search_policy.get('recommended_mode') or 'none',
            'branch_template': first_branch,
            'success_criteria': _brief_list(first_branch.get('success_criteria') or first_hypothesis.get('expected_metric_change')),
            'falsification_tests': _brief_list(first_branch.get('falsification_tests') or first_hypothesis.get('falsification_tests')),
            'kill_criteria': _brief_list(first_hypothesis.get('kill_criteria') or math_discipline.get('kill_criteria')),
        },
        'final_loop_conclusion': {
            'current_conclusion': current_conclusion,
            'promotion_requirements': (
                ['Promotion requirements already met: case validated, identity/evidence verified, long-side evidence official-ready, mechanism support accepted.']
                if promoted else
                [
                    'Identity and evidence chain must remain verified.',
                    'Long-side risk-adjusted evidence must meet promotion thresholds after costs.',
                    'Mechanism fit must be strong or supported by matching same-factor/strong mechanism evidence.',
                    'Any Step3B change requires human approval before code changes.',
                ]
            ),
            'human_decision_required': bool(search_policy.get('human_approval_required') is True or decision != 'promote_official'),
        },
    }


def render_loop_research_brief_markdown(brief: dict[str, Any]) -> str:
    decision = brief.get('decision_snapshot') or {}
    econ = brief.get('economic_interpretation') or {}
    metrics = brief.get('metrics') or {}
    charts = brief.get('chart_evidence') or {}
    analysis = brief.get('metric_analysis') or {}
    knowledge = brief.get('knowledge_comparison') or {}
    math_summary = brief.get('mechanism_math_summary') or {}
    formula_derivation = brief.get('formula_specific_derivation') or {}
    consistency = brief.get('mechanism_formula_consistency') or {}
    next_dir = brief.get('next_research_direction') or {}
    conclusion = brief.get('final_loop_conclusion') or {}

    def bullet_list(items: Any) -> str:
        values = _brief_list(items)
        if not values:
            return '- missing'
        return '\n'.join(f'- {json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item}' for item in values)

    metric_rows = [
        ('Rank IC mean', 'rank_ic_mean', 'Direction and magnitude of rank correlation.'),
        ('Rank IC IR', 'rank_ic_ir', 'Stability of rank IC.'),
        ('Pearson IC mean', 'pearson_ic_mean', 'Linear IC diagnostic.'),
        ('Pearson IC IR', 'pearson_ic_ir', 'Stability of Pearson IC.'),
        ('Long-side annual return', 'long_side_annual_return', 'Gross long-side revenue.'),
        ('Long-side annual volatility', 'long_side_annual_volatility', 'Risk-capital pressure.'),
        ('Long-side Sharpe', 'long_side_sharpe', 'Risk-adjusted long-side quality.'),
        ('Max drawdown', 'long_side_max_drawdown', 'Capital impairment.'),
        ('Recovery days', 'long_side_recovery_days', 'Payback/recovery burden.'),
        ('Daily turnover', 'long_side_turnover_mean_daily', 'Trading intensity.'),
        ('Annual trading COGS', 'trading_cogs_annual', 'Turnover cost burden.'),
        ('Cost-adjusted annual return', 'cost_adjusted_annual_return', 'Net long-side return after costs.'),
        ('Cost-adjusted Sharpe', 'cost_adjusted_long_side_sharpe', 'Net risk-adjusted long-side quality.'),
    ]
    table = ['| Metric | Value | Interpretation |', '|---|---:|---|']
    for label, key, interpretation in metric_rows:
        table.append(f'| {label} | {_brief_scalar(metrics.get(key))} | {interpretation} |')

    branch_template = next_dir.get('branch_template') or {}
    branch_text = json.dumps(branch_template, ensure_ascii=False) if branch_template else 'none'
    return f"""# Factor Forge Loop Brief: {brief.get('report_id')} / Iteration {brief.get('iteration_no')}

## 1. Decision Snapshot

- Decision: {decision.get('decision')}
- Promotion status: {decision.get('promotion_status')}
- Loop authorization: {decision.get('loop_authorization')}
- Search policy: {decision.get('search_policy')}
- Next branch: {decision.get('next_branch')}
- Human approval required: {decision.get('human_approval_required')}

## 2. Economic Interpretation

- Formula: {econ.get('formula')}
- Plain-English interpretation: {econ.get('plain_english_interpretation')}
- Return source: {econ.get('return_source')}
- Factor family: {econ.get('factor_family')}
- Random object: {econ.get('random_object')}
- Target statistic: {econ.get('target_statistic')}
- Information set: {econ.get('information_set')}
- Mechanism hypothesis: {econ.get('mechanism_hypothesis')}
- Why this should earn long-side return: {econ.get('why_long_side_should_work')}
- Necessary conditions:
{bullet_list(econ.get('necessary_conditions'))}
- Failure regimes:
{bullet_list(econ.get('failure_regimes'))}
- Mechanism fit: {econ.get('mechanism_fit')}

## 3. Evidence And Metrics

{chr(10).join(table)}

## 4. Chart Evidence

- Rank IC time series: {charts.get('rank_ic_timeseries')}
- Pearson IC time series: {charts.get('pearson_ic_timeseries')}
- Long-side NAV: {charts.get('long_side_nav')}
- Cost-adjusted long-side NAV: {charts.get('cost_adjusted_long_side_nav')}
- Quantile NAV: {charts.get('quantile_nav')}
- Long-short NAV, diagnostic only: {charts.get('long_short_nav_diagnostic_only')}
- Coverage by day: {charts.get('coverage_by_day')}

## 5. Metric Analysis

- What supports the factor:
{bullet_list(analysis.get('supporting_evidence'))}
- What contradicts the factor:
{bullet_list(analysis.get('contradicting_evidence'))}
- Cost / turnover analysis: {analysis.get('cost_turnover_analysis')}
- Drawdown / recovery analysis: {analysis.get('drawdown_recovery_analysis')}
- Monotonicity analysis: {analysis.get('monotonicity_analysis')}
- Short-side / long-short diagnostic: {analysis.get('short_side_long_short_diagnostic')}
- Implementation/data concerns:
{bullet_list(analysis.get('implementation_or_data_concerns'))}

## 6. Knowledge Comparison

- Same-factor cases:
{bullet_list(knowledge.get('same_factor_cases'))}
- Similar successful cases:
{bullet_list(knowledge.get('similar_success_cases'))}
- Similar failed cases:
{bullet_list(knowledge.get('similar_failure_cases'))}
- Imported lessons:
{bullet_list(knowledge.get('imported_lessons'))}
- Rejected lessons:
{bullet_list(knowledge.get('rejected_lessons'))}
- Anti-patterns:
{bullet_list(knowledge.get('anti_patterns'))}

## 7. Next Research Direction

- Primary failure signature: {next_dir.get('primary_failure_signature')}
- Revision hypothesis: {next_dir.get('revision_hypothesis')}
- Expression-level change: {next_dir.get('expression_level_change')}
- Why not portfolio fix: {next_dir.get('why_not_portfolio_fix')}
- Search policy: {next_dir.get('search_policy')}
- Branch template: {branch_text}
- Revision target math object: {next_dir.get('revision_target_math_object')}
- Math change: {next_dir.get('math_change')}
- Success criteria:
{bullet_list(next_dir.get('success_criteria'))}
- Falsification tests:
{bullet_list(next_dir.get('falsification_tests'))}
- Kill criteria:
{bullet_list(next_dir.get('kill_criteria'))}

## 8. Final Loop Conclusion

- Current conclusion: {conclusion.get('current_conclusion')}
- What must happen before next promotion consideration:
{bullet_list(conclusion.get('promotion_requirements'))}
- Human decision required: {conclusion.get('human_decision_required')}

## 9. Mechanism Math Summary

- Math model status: {math_summary.get('math_model_status')}
- Model family: {math_summary.get('model_family')}
- Economic mechanism family: {math_summary.get('economic_mechanism_family') or 'not_specified'}
- Math tool family: {math_summary.get('math_tool_family') or 'not_specified'}
- Model equation family: {math_summary.get('model_equation_family') or 'not_specified'}
- Math toolkits:
{bullet_list(math_summary.get('math_toolkits'))}
- State or object: {math_summary.get('state_or_object')}
- Factor as estimator: {math_summary.get('factor_as_estimator')}
- Target functional: {math_summary.get('target_functional')}
- Monotonicity claim: {math_summary.get('monotonicity_claim')}
- Expected metric signature: {json.dumps(math_summary.get('expected_metric_signature') or {}, ensure_ascii=False)}
- Revision operator summary: {json.dumps(math_summary.get('revision_operator_summary') or {}, ensure_ascii=False)}
- Under-specified reason: {math_summary.get('under_specified_reason') or 'not_applicable'}
- Next human research question: {math_summary.get('next_human_research_question') or 'not_applicable'}

## 10. Formula-Specific Derivation

- Consistency status: {consistency.get('status')}
- Consistency failures: {json.dumps(consistency.get('failures') or [], ensure_ascii=False)}
- Selected model family: {formula_derivation.get('selected_model_family') or (formula_derivation.get('economic_to_math_model_selection') or {}).get('baseline_model_family')}
- Why selected from economic hypothesis: {(formula_derivation.get('economic_to_math_model_selection') or {}).get('why_selected_from_economic_hypothesis')}
- Why not generic template: {formula_derivation.get('why_this_model_not_generic_template') or (formula_derivation.get('economic_to_math_model_selection') or {}).get('why_not_generic_template')}
- Profit payer: {(formula_derivation.get('profit_payer_derivation') or {}).get('payer_or_counterparty')}
- Why they pay: {(formula_derivation.get('profit_payer_derivation') or {}).get('why_they_pay')}
- Process or distribution: {formula_derivation.get('process_or_distribution')}
- Formula components:
{bullet_list(formula_derivation.get('formula_components'))}
- Latent-state mapping:
{bullet_list(formula_derivation.get('latent_state_mapping'))}
"""


def write_loop_research_brief(iteration: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    report_id = str(iteration.get('report_id') or '')
    iteration_no = int(iteration.get('iteration_no') or 0)
    created_at = utc_now()
    brief = build_loop_research_brief(iteration, bundle)
    brief['created_at_utc'] = created_at
    markdown_path = OBJ / 'research_iteration_master' / f'loop_research_brief__{report_id}__iter{iteration_no}.md'
    json_path = OBJ / 'research_iteration_master' / f'loop_research_brief__{report_id}__iter{iteration_no}.json'
    write_json(json_path, brief)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_loop_research_brief_markdown(brief), encoding='utf-8')
    return {
        'markdown_path': str(markdown_path),
        'json_path': str(json_path),
        'brief_version': LOOP_RESEARCH_BRIEF_VERSION,
        'iteration_no': iteration_no,
        'created_at_utc': created_at,
    }


def _contains_new_factor_seed(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get('classification') == 'new_factor_seed':
            return True
        return any(_contains_new_factor_seed(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_new_factor_seed(item) for item in value)
    return False


def should_write_dirac_discovery_queue(iteration: dict[str, Any]) -> tuple[bool, str]:
    if os.getenv('FACTORFORGE_STEP6_DIRAC_DISCOVERY_REQUEST') == '1':
        return True, 'explicit_discovery_request'
    research_memo = ((iteration.get('research_judgment') or {}).get('research_memo') or {})
    mechanism_analysis = research_memo.get('mechanism_analysis') or {}
    if _contains_new_factor_seed(mechanism_analysis):
        return True, 'step6_anomaly_review'
    return False, ''


def render_dirac_discovery_queue_markdown(queue: dict[str, Any]) -> str:
    rows = ['| Candidate | Source Equation | Branch Action | Auto Run |', '|---|---|---|---|']
    for candidate in queue.get('candidates') or []:
        rows.append(
            '| {candidate_id} | {source_equation_id} | {branch_action} | {auto_run_allowed} |'.format(
                candidate_id=candidate.get('candidate_id'),
                source_equation_id=candidate.get('source_equation_id'),
                branch_action=candidate.get('branch_action'),
                auto_run_allowed=candidate.get('auto_run_allowed'),
            )
        )
    return f"""# Dirac Discovery Queue: {queue.get('report_id')}

Source: {queue.get('source')}

No candidate may launch Step2, Step3, or Step4 automatically. Candidate packets are advisory until the existing loop or a human-approved branch request starts a formal factor run.

{chr(10).join(rows)}
"""


def write_dirac_discovery_queue(report_id: str, source: str) -> dict[str, str]:
    queue = build_default_discovery_queue()
    queue.update({
        'report_id': report_id,
        'source': source,
        'auto_run_allowed': False,
    })
    out_dir = OBJ / 'research_iteration_master' / 'revision_council' / report_id
    json_path = out_dir / f'dirac_discovery_queue__{report_id}.json'
    markdown_path = out_dir / f'dirac_discovery_queue__{report_id}.md'
    write_json(json_path, queue)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_dirac_discovery_queue_markdown(queue), encoding='utf-8')
    return {
        'json_path': str(json_path),
        'markdown_path': str(markdown_path),
        'source': source,
        'auto_run_allowed': False,
    }


def promotion_gate(iteration: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    case = bundle['factor_case_master']
    evidence_quality = case.get('evidence_quality') or {}
    research_memo = (((iteration.get('research_judgment') or {}).get('research_memo')) or {})
    evidence_audit = research_memo.get('evidence_audit') or {}
    mechanism_analysis = research_memo.get('mechanism_analysis') or {}
    mechanism_math_contract = mechanism_analysis.get('mechanism_math_contract') or mechanism_math_contract_from_bundle(bundle)
    unresolved_correctness_risk = bool(
        research_memo.get('unresolved_correctness_risk')
        or research_memo.get('human_review_required')
        or (iteration.get('implementation_mode_decision') or {}).get('human_review_required')
    )
    checks = {
        'case_validated': case.get('final_status') == 'validated',
        'identity_chain_verified': evidence_quality.get('identity_chain_verified') is True,
        'long_side_metrics_present': evidence_quality.get('long_side_metrics_present') is True,
        'step4_has_successful_backend': evidence_quality.get('step4_has_successful_backend') is True,
        'mode_decision_present': bool(iteration.get('implementation_mode_decision')),
        'no_unresolved_correctness_risk': not unresolved_correctness_risk,
        'evidence_audit_not_blocked': evidence_audit.get('evidence_verdict') != 'blocked',
        'mechanism_return_source_known': mechanism_analysis.get('return_source') != 'unknown',
        'mechanism_not_contradicted': mechanism_analysis.get('mechanism_fit') != 'contradicted',
        'mechanism_math_not_invalid': mechanism_math_contract.get('math_model_status') != 'invalid',
    }
    blocked = [key for key, ok in checks.items() if not ok]
    return {
        'official_promotion_allowed': not blocked,
        'checks': checks,
        'promote_blocked_reason': blocked,
    }


def _strict_identity_gate(expected_label: str, expected: dict[str, Any], actual_label: str, actual: dict[str, Any], actual_role: str) -> list[str]:
    expected_identity = expected.get('artifact_identity') or {}
    actual_identity = actual.get('artifact_identity') or {}
    if not expected_identity or not actual_identity:
        return [f'{expected_label}/{actual_label} artifact_identity missing']
    try:
        assert_identity_matches_strict(
            expected_identity,
            actual_identity,
            expected_label=expected_label,
            actual_label=actual_label,
            allowed_role_transitions={(expected_identity.get('artifact_role'), actual_role)},
        )
        return []
    except AssertionError as exc:
        return [str(exc)]


def step6_prewrite_failures(
    *,
    iteration: dict[str, Any],
    all_record: dict[str, Any],
    knowledge_record: dict[str, Any],
    official_record: dict[str, Any] | None,
    handoff_to_step3b: dict[str, Any] | None,
    bundle: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    case = bundle['factor_case_master']
    run = bundle['factor_run_master']
    required_iteration = [
        'source_case_identity',
        'decision_lineage',
        'knowledge_provenance',
        'implementation_mode_decision',
        'evidence_identity',
    ]
    for key in required_iteration:
        if not isinstance(iteration.get(key), dict) or not iteration.get(key):
            failures.append(f'{key}_missing')

    research_memo = ((iteration.get('research_judgment') or {}).get('research_memo') or {})
    evidence_audit = research_memo.get('evidence_audit') or {}
    if evidence_audit.get('evidence_verdict') == 'blocked':
        failures.append('evidence_audit_evidence_verdict_blocked')
    case_comparison = research_memo.get('case_comparison') or {}
    if case_comparison.get('case_comparison_verdict') == 'blocked':
        failures.append('case_comparison_verdict_blocked')
    if case_comparison.get('identity_mismatch_cases'):
        failures.append('same_factor_identity_mismatch')

    failures.extend(_strict_identity_gate('factor_run_master', run, 'factor_case_master', case, 'factor_case_master'))
    failures.extend(_strict_identity_gate('factor_case_master', case, 'research_iteration_master', iteration, 'research_iteration_master'))
    failures.extend(_strict_identity_gate('factor_case_master', case, 'factor_library_all', all_record, 'factor_library_all'))
    failures.extend(_strict_identity_gate('factor_case_master', case, 'research_knowledge_base', knowledge_record, 'research_knowledge_base'))
    if official_record is not None:
        failures.extend(_strict_identity_gate('factor_case_master', case, 'factor_library_official', official_record, 'factor_library_official'))

    case_quality = case.get('evidence_quality') or {}
    for key in [
        'identity_chain_verified',
        'mode_decision_present',
        'self_quant_required_and_present',
        'long_side_metrics_present',
        'step4_has_successful_backend',
    ]:
        if case_quality.get(key) is not True:
            failures.append(f'case_evidence_quality_{key}_not_true')

    if iteration['research_judgment']['decision'] == 'promote_official':
        gate = iteration.get('promotion_gate') or {}
        if gate.get('official_promotion_allowed') is not True:
            failures.append('official_promotion_gate_failed:' + ','.join(gate.get('promote_blocked_reason') or []))
        if official_record is None:
            failures.append('official_record_missing_for_promote_official')

    if knowledge_record.get('knowledge_scope') == 'same_factor':
        source_identity = knowledge_record.get('source_identity') or {}
        target_factor = knowledge_record.get('factor_id')
        if source_identity.get('factor_id') != target_factor:
            failures.append('same_factor_knowledge_cross_factor')
    if not (knowledge_record.get('knowledge_provenance') or {}).get('not_same_factor_unless_identity_matches'):
        failures.append('knowledge_provenance_identity_guard_missing')

    if iteration['loop_action']['should_modify_step3b']:
        if not handoff_to_step3b:
            failures.append('iterate_handoff_missing')
        else:
            parent_identity = handoff_to_step3b.get('parent_identity') or {}
            if not parent_identity:
                failures.append('iterate_parent_identity_missing')
            if not handoff_to_step3b.get('parent_run_id'):
                failures.append('iterate_parent_run_id_missing')
            if not handoff_to_step3b.get('new_branch_id'):
                failures.append('iterate_new_branch_id_missing')
            source_identity = iteration.get('source_case_identity') or {}
            if handoff_to_step3b.get('parent_run_id') != source_identity.get('run_id'):
                failures.append('iterate_parent_run_id_mismatch')
    return failures


def write_step6_prewrite_block(
    *,
    report_id: str,
    decision: str,
    reasons: list[str],
    would_have_written: list[str],
) -> None:
    diagnostic = {
        'report_id': report_id,
        'decision': decision,
        'prewrite_blocked': True,
        'prewrite_block_reasons': reasons,
        'would_have_written': would_have_written,
        'skipped_writes': [
            'research_iteration_master',
            'factor_library_all',
            'factor_library_official',
            'research_knowledge_base',
            'handoff_to_step3b',
        ],
    }
    diag_path = OBJ / 'validation' / f'step6_prewrite_block__{report_id}.json'
    write_json(diag_path, diagnostic)
    print(f'[WRITE] {diag_path}')


def main() -> None:
    global FF, OBJ, EVAL
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    args = ap.parse_args()
    enforce_direct_step_policy(args.manifest)
    manifest = load_runtime_manifest(args.manifest) if args.manifest else None
    if manifest:
        FF = manifest_factorforge_root(manifest)
        OBJ = FF / 'objects'
        EVAL = FF / 'evaluations'
    report_id = args.report_id or (manifest_report_id(manifest) if manifest else None)
    if not report_id:
        raise SystemExit('run_step6.py requires --report-id or --manifest')

    bundle = load_required_inputs(report_id)
    payloads = load_backend_payloads(report_id, bundle['factor_run_master'])
    iteration = build_iteration_payload(bundle, payloads)
    base_identity = (
        bundle['factor_case_master'].get('artifact_identity')
        or bundle['factor_run_master'].get('artifact_identity')
        or {}
    )
    iteration['artifact_identity'] = derive_identity(base_identity, 'research_iteration_master')
    iteration['evidence_identity'] = build_evidence_identity(
        factorforge_root=FF,
        report_id=str(report_id),
        factor_run_master=bundle['factor_run_master'],
        factor_case_master=bundle['factor_case_master'],
        factor_evaluation=bundle['factor_evaluation'],
        handoff=bundle['handoff_to_step6'],
        backend_payloads=payloads,
    )
    iteration['source_case_identity'] = bundle['factor_case_master'].get('artifact_identity') or {}
    iteration['implementation_mode_decision'] = iteration['evidence_identity'].get('implementation_mode_decision') or {}
    iteration['decision_lineage'] = build_decision_lineage(
        decision=iteration['research_judgment']['decision'],
        factor_case_master=bundle['factor_case_master'],
        factor_run_master=bundle['factor_run_master'],
        evidence_identity=iteration['evidence_identity'],
    )
    similar_cases = (((iteration.get('research_judgment') or {}).get('research_memo') or {}).get('learning_and_innovation') or {}).get('similar_case_lessons_imported') or []
    iteration['knowledge_provenance'] = build_knowledge_provenance(
        source_identity=iteration['source_case_identity'],
        decision=iteration['research_judgment']['decision'],
        similar_cases_imported=similar_cases,
    )
    iteration['promotion_gate'] = promotion_gate(iteration, bundle)

    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{report_id}.json'
    main_agent_memo_json_path = OBJ / 'research_iteration_master' / f'main_agent_mechanism_memo__{report_id}.json'
    main_agent_memo_md_path = OBJ / 'research_iteration_master' / f'main_agent_mechanism_memo__{report_id}.md'
    main_agent_questionnaire_json_path = OBJ / 'research_iteration_master' / f'main_agent_mechanism_questionnaire__{report_id}.json'
    main_agent_questionnaire_md_path = OBJ / 'research_iteration_master' / f'main_agent_mechanism_questionnaire__{report_id}.md'
    main_agent_status_path = OBJ / 'research_iteration_master' / f'main_agent_mechanism_memo_status__{report_id}.json'
    main_agent_memo_ref = {
        'json_path': str(main_agent_memo_json_path),
        'markdown_path': str(main_agent_memo_md_path),
        'contract_version': 'factorforge_main_agent_mechanism_memo_v1',
    }
    main_agent_questionnaire_ref = {
        'json_path': str(main_agent_questionnaire_json_path),
        'markdown_path': str(main_agent_questionnaire_md_path),
        'contract_version': 'factorforge_main_agent_mechanism_questionnaire_v1',
    }
    iteration['main_agent_mechanism_memo_ref'] = main_agent_memo_ref
    iteration['main_agent_mechanism_questionnaire_ref'] = main_agent_questionnaire_ref
    ((iteration.get('research_judgment') or {}).get('research_memo') or {})['main_agent_mechanism_memo_ref'] = main_agent_memo_ref
    ((iteration.get('research_judgment') or {}).get('research_memo') or {})['main_agent_mechanism_questionnaire_ref'] = main_agent_questionnaire_ref
    all_library_path = OBJ / 'factor_library_all' / f'factor_record__{report_id}.json'
    official_library_path = OBJ / 'factor_library_official' / f'factor_record__{report_id}.json'
    knowledge_path = OBJ / 'research_knowledge_base' / f'knowledge_record__{report_id}.json'
    step3b_handoff_path = OBJ / 'handoff' / f'handoff_to_step3b__{report_id}.json'

    questionnaire = build_main_agent_mechanism_questionnaire(
        report_id=str(report_id),
        factor_spec=bundle.get('factor_spec_master') or {},
        factor_case=bundle.get('factor_case_master') or {},
        evaluation_summary=bundle.get('factor_evaluation') or {},
        step6_iteration=iteration,
    )
    write_json(main_agent_questionnaire_json_path, questionnaire)
    main_agent_questionnaire_md_path.parent.mkdir(parents=True, exist_ok=True)
    main_agent_questionnaire_md_path.write_text(render_main_agent_mechanism_questionnaire_markdown(questionnaire), encoding='utf-8')
    print(f'[WRITE] {main_agent_questionnaire_json_path}')
    print(f'[WRITE] {main_agent_questionnaire_md_path}')

    if not main_agent_memo_json_path.exists():
        status = {
            'report_id': str(report_id),
            'status': 'awaiting_main_agent_mechanism_memo',
            'token': 'AWAITING_MAIN_AGENT_MECHANISM_MEMO',
            'questionnaire_ref': main_agent_questionnaire_ref,
            'expected_memo_ref': main_agent_memo_ref,
            'next_action': 'The currently active main agent must answer the questionnaire and write the memo before Step6 can continue.',
            'canonical_write_permission': False,
            'execution_allowed_by_default': False,
            'final_step6_write_allowed': False,
        }
        write_json(main_agent_status_path, status)
        print('AWAITING_MAIN_AGENT_MECHANISM_MEMO')
        raise SystemExit('AWAITING_MAIN_AGENT_MECHANISM_MEMO')

    main_agent_memo = load_json(main_agent_memo_json_path)
    factor_spec_master = bundle.get('factor_spec_master') or {}
    main_agent_memo_failures = validate_main_agent_mechanism_memo(main_agent_memo, factor_spec_master)
    if main_agent_memo_failures:
        status = {
            'report_id': str(report_id),
            'status': 'blocked_invalid_main_agent_mechanism_memo',
            'token': 'BLOCK_MAIN_AGENT_MECHANISM_MEMO_INVALID',
            'failures': main_agent_memo_failures,
            'questionnaire_ref': main_agent_questionnaire_ref,
            'memo_ref': main_agent_memo_ref,
            'canonical_write_permission': False,
            'execution_allowed_by_default': False,
            'final_step6_write_allowed': False,
        }
        write_json(main_agent_status_path, status)
        write_step6_prewrite_block(
            report_id=str(report_id),
            decision=iteration['research_judgment']['decision'],
            reasons=['BLOCK_MAIN_AGENT_MECHANISM_MEMO_INVALID:' + ','.join(main_agent_memo_failures)],
            would_have_written=[
                'research_iteration_master',
                'factor_library_all',
                'research_knowledge_base',
                'factor_library_official',
                'handoff_to_step3b',
            ],
        )
        raise SystemExit('BLOCK_MAIN_AGENT_MECHANISM_MEMO_INVALID: ' + ','.join(main_agent_memo_failures))

    research_memo = ((iteration.get('research_judgment') or {}).get('research_memo') or {})
    mechanism_analysis = research_memo.get('mechanism_analysis') or {}
    legacy_mechanism_snapshot = {
        key: mechanism_analysis.get(key)
        for key in [
            'return_source',
            'factor_family',
            'mechanism_hypothesis',
            'mechanism_math_summary',
            'mechanism_fit',
        ]
        if key in mechanism_analysis
    }
    mechanism_analysis['formula_specific_derivation'] = formula_specific_derivation_from_main_agent_memo(main_agent_memo, factor_spec_master)
    qa = main_agent_memo.get('mechanism_qa') if isinstance(main_agent_memo.get('mechanism_qa'), dict) else {}
    math_hypothesis = main_agent_memo.get('math_hypothesis') if isinstance(main_agent_memo.get('math_hypothesis'), dict) else {}
    if qa.get('economic_hypothesis_answer') or qa.get('math_model_answer'):
        mechanism_analysis['mechanism_hypothesis'] = ' '.join(
            str(part).strip()
            for part in [qa.get('economic_hypothesis_answer'), qa.get('math_model_answer')]
            if str(part or '').strip()
        )
    if isinstance(math_hypothesis.get('expected_metric_signature'), dict):
        mechanism_analysis['expected_metric_signature'] = math_hypothesis['expected_metric_signature']
    mechanism_analysis['main_agent_mechanism_memo_takeover'] = {
        'enabled': True,
        'memo_ref': main_agent_memo_ref,
        'validation_scope': 'main_agent_formula_specific_derivation',
        'legacy_deterministic_mechanism_retained_for_audit': legacy_mechanism_snapshot,
    }
    mechanism_analysis['mechanism_formula_consistency'] = validate_mechanism_formula_consistency(
        factor_spec_master,
        mechanism_analysis,
        mechanism_analysis.get('formula_specific_derivation') or {},
    )
    research_memo['mechanism_analysis'] = mechanism_analysis

    all_record = build_factor_record(iteration, bundle)
    all_record['artifact_identity'] = derive_identity(base_identity, 'factor_library_all')
    all_record['evidence_identity'] = iteration['evidence_identity']
    all_record['source_case_identity'] = iteration['source_case_identity']
    all_record['implementation_mode_decision'] = iteration['implementation_mode_decision']
    all_record['decision_lineage'] = iteration['decision_lineage']
    all_record['knowledge_provenance'] = iteration['knowledge_provenance']
    all_record['promotion_gate'] = iteration['promotion_gate']
    knowledge_record = build_knowledge_record(iteration)
    knowledge_record['artifact_identity'] = derive_identity(base_identity, 'research_knowledge_base')
    knowledge_record['evidence_identity'] = iteration['evidence_identity']
    knowledge_record['source_case_identity'] = iteration['source_case_identity']
    knowledge_record['source_identity'] = iteration['source_case_identity']
    knowledge_record['implementation_mode_decision'] = iteration['implementation_mode_decision']
    knowledge_record['decision_lineage'] = iteration['decision_lineage']
    knowledge_record['knowledge_provenance'] = iteration['knowledge_provenance']
    knowledge_record['provenance'] = {
        **(knowledge_record.get('provenance') or {}),
        'factor_id': base_identity.get('factor_id'),
        'report_id': base_identity.get('report_id'),
        'branch_id': base_identity.get('branch_id'),
        'run_id': base_identity.get('run_id'),
        'implementation_mode': base_identity.get('implementation_mode'),
        'spec_hash': base_identity.get('spec_hash'),
        'formula_hash': base_identity.get('formula_hash'),
        'code_hash': base_identity.get('code_hash') or base_identity.get('code_contract_hash'),
        'hybrid_hash': base_identity.get('hybrid_hash'),
    }

    official_record = None
    if iteration['research_judgment']['decision'] == 'promote_official' and iteration['promotion_gate']['official_promotion_allowed']:
        official_record = dict(all_record)
        official_record['artifact_identity'] = derive_identity(base_identity, 'factor_library_official')
        official_record['promotion_gate'] = iteration['promotion_gate']

    formula_derivation_failures = validate_formula_specific_derivation(
        mechanism_analysis.get('formula_specific_derivation') or {},
        factor_spec_master,
        mechanism_analysis,
    )
    mechanism_formula_consistency = validate_mechanism_formula_consistency(
        factor_spec_master,
        mechanism_analysis,
        mechanism_analysis.get('formula_specific_derivation') or {},
    )
    contract_failures: list[str] = []
    if formula_derivation_failures:
        contract_failures.append('formula_specific_derivation_invalid:' + json.dumps(formula_derivation_failures, ensure_ascii=False))
    if mechanism_formula_consistency.get('failures'):
        contract_failures.append('mechanism_formula_consistency_invalid:' + json.dumps(mechanism_formula_consistency.get('failures'), ensure_ascii=False))

    handoff_to_step3b = build_handoff_to_step3b(iteration) if iteration['loop_action']['should_modify_step3b'] else None
    would_have_written = [
        'research_iteration_master',
        'factor_library_all',
        'research_knowledge_base',
    ]
    if official_record is not None:
        would_have_written.append('factor_library_official')
    if handoff_to_step3b is not None:
        would_have_written.append('handoff_to_step3b')
    should_write_queue, queue_source = should_write_dirac_discovery_queue(iteration)
    if should_write_queue:
        would_have_written.append('dirac_discovery_queue')
    prewrite_failures = step6_prewrite_failures(
        iteration=iteration,
        all_record=all_record,
        knowledge_record=knowledge_record,
        official_record=official_record,
        handoff_to_step3b=handoff_to_step3b,
        bundle=bundle,
    )
    prewrite_failures.extend(contract_failures)
    if prewrite_failures:
        write_step6_prewrite_block(
            report_id=str(report_id),
            decision=iteration['research_judgment']['decision'],
            reasons=prewrite_failures,
            would_have_written=would_have_written,
        )
        raise SystemExit('STEP6_PREWRITE_BLOCK: ' + '; '.join(prewrite_failures))

    iteration['loop_research_brief'] = write_loop_research_brief(iteration, bundle)
    print(f"[WRITE] {iteration['loop_research_brief']['json_path']}")
    print(f"[WRITE] {iteration['loop_research_brief']['markdown_path']}")
    if should_write_queue:
        iteration['dirac_discovery_queue'] = write_dirac_discovery_queue(str(report_id), queue_source)
        print(f"[WRITE] {iteration['dirac_discovery_queue']['json_path']}")
        print(f"[WRITE] {iteration['dirac_discovery_queue']['markdown_path']}")
    write_json(iteration_path, iteration)
    print(f'[WRITE] {iteration_path}')
    write_json(all_library_path, all_record)
    print(f'[WRITE] {all_library_path}')
    write_json(knowledge_path, knowledge_record)
    print(f'[WRITE] {knowledge_path}')

    if official_record is not None:
        write_json(official_library_path, official_record)
        print(f'[WRITE] {official_library_path}')
    elif iteration['research_judgment']['decision'] == 'promote_official':
        all_record['promote_blocked_reason'] = iteration['promotion_gate']['promote_blocked_reason']
        iteration['promote_blocked_reason'] = iteration['promotion_gate']['promote_blocked_reason']
        write_json(iteration_path, iteration)
        write_json(all_library_path, all_record)
        if official_library_path.exists():
            official_library_path.unlink()
    elif official_library_path.exists():
        official_library_path.unlink()

    if handoff_to_step3b is not None:
        write_json(step3b_handoff_path, handoff_to_step3b)
        print(f'[WRITE] {step3b_handoff_path}')
    elif step3b_handoff_path.exists():
        step3b_handoff_path.unlink()


if __name__ == '__main__':
    main()
