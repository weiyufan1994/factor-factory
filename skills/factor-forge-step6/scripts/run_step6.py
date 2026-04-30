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

OBJ = FF / 'objects'
EVAL = FF / 'evaluations'
RETRIEVAL_INDEX = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'
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
        'long_side_turnover_mean_daily',
        'turnover_mean',
        'trading_cogs_daily',
        'trading_cogs_annual',
        'cost_adjusted_return_daily',
        'cost_adjusted_annual_return',
        'cost_adjusted_long_side_sharpe',
        'cost_adjusted_long_side_max_drawdown',
        'cost_adjusted_long_side_recovery_days',
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


def build_formula_understanding(bundle: dict[str, Any]) -> dict[str, Any]:
    spec = bundle.get('factor_spec_master') or {}
    canonical = spec.get('canonical_spec') or {}
    factor_id = str(spec.get('factor_id') or bundle['factor_run_master'].get('factor_id') or '')
    formula_text = str(canonical.get('formula_text') or '')
    lower_formula = formula_text.lower()

    if factor_id.upper() == 'ALPHA002' or ('delta(log(volume)' in lower_formula and '(close - open)' in lower_formula):
        return {
            'factor_type': 'Alpha101 daily price-volume interaction factor',
            'plain_language': 'Alpha002 measures whether recent acceleration in trading volume is correlated with intraday price pressure, then takes the negative of that rolling relationship.',
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
                'If liquidity improves or many participants trade the same Alpha101 formula, spread can compress.',
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
        'Compare against related Alpha101 price-volume factors to avoid promoting a redundant signal.',
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
            'source_path': doc.get('source_path'),
            'overlap_terms': sorted(overlap)[:12],
            'snippet': snippet,
        })

    embedding_available = EMBEDDING_MATRIX.exists() and EMBEDDING_META.exists()
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
            'step5_lessons': case.get('lessons') or handoff.get('lessons') or [],
            'step5_next_actions': case.get('next_actions') or handoff.get('next_actions') or [],
        },
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
            'should_modify_step3b': decision == 'iterate',
            'modification_targets': modification_targets,
            'parallel_exploration_branches': (program_search_policy.get('recommended_next_search') or {}).get('branches') or [],
            'search_methods': list((program_search_policy.get('method_library') or {}).keys()),
            'requires_human_approval_before_code_change': decision == 'iterate',
            'next_runner': 'step3b' if decision == 'iterate' else 'stop',
            'stop_reason': None if decision == 'iterate' else decision,
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
        'created_at_utc': iteration['created_at_utc'],
        'producer': 'step6',
    }


def build_handoff_to_step3b(iteration: dict[str, Any]) -> dict[str, Any]:
    return {
        'report_id': iteration['report_id'],
        'factor_id': iteration['factor_id'],
        'trigger': 'step6_iteration',
        'modification_targets': iteration['loop_action']['modification_targets'],
        'research_judgment': iteration['research_judgment'],
        'knowledge_writeback': iteration['knowledge_writeback'],
        'created_at_utc': iteration['created_at_utc'],
        'producer': 'step6',
    }


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

    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{report_id}.json'
    all_library_path = OBJ / 'factor_library_all' / f'factor_record__{report_id}.json'
    official_library_path = OBJ / 'factor_library_official' / f'factor_record__{report_id}.json'
    knowledge_path = OBJ / 'research_knowledge_base' / f'knowledge_record__{report_id}.json'
    step3b_handoff_path = OBJ / 'handoff' / f'handoff_to_step3b__{report_id}.json'

    write_json(iteration_path, iteration)
    print(f'[WRITE] {iteration_path}')

    all_record = build_factor_record(iteration, bundle)
    write_json(all_library_path, all_record)
    print(f'[WRITE] {all_library_path}')

    knowledge_record = build_knowledge_record(iteration)
    write_json(knowledge_path, knowledge_record)
    print(f'[WRITE] {knowledge_path}')

    if iteration['research_judgment']['decision'] == 'promote_official':
        write_json(official_library_path, all_record)
        print(f'[WRITE] {official_library_path}')
    elif official_library_path.exists():
        official_library_path.unlink()

    if iteration['loop_action']['should_modify_step3b']:
        write_json(step3b_handoff_path, build_handoff_to_step3b(iteration))
        print(f'[WRITE] {step3b_handoff_path}')
    elif step3b_handoff_path.exists():
        step3b_handoff_path.unlink()


if __name__ == '__main__':
    main()
