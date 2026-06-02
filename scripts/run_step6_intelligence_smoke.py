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

from factor_factory.artifact_identity import build_artifact_identity, stable_hash
from factor_factory.mechanism_math.formula_specific import (
    build_formula_specific_derivation,
    validate_formula_specific_derivation,
    validate_mechanism_formula_consistency,
)
from factor_factory.mechanism_math.main_agent_memo import (
    build_main_agent_mechanism_memo,
    render_main_agent_mechanism_memo_markdown,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


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
    return {
        'polluted': bool(added),
        'new_files': added,
    }


def forbidden_writeback_paths(root: Path, report_id: str) -> dict[str, Path]:
    return {
        'research_iteration_master': root / 'objects' / 'research_iteration_master' / f'research_iteration_master__{report_id}.json',
        'factor_library_all': root / 'objects' / 'factor_library_all' / f'factor_record__{report_id}.json',
        'factor_library_official': root / 'objects' / 'factor_library_official' / f'factor_record__{report_id}.json',
        'knowledge_record': root / 'objects' / 'research_knowledge_base' / f'knowledge_record__{report_id}.json',
        'handoff_to_step3b': root / 'objects' / 'handoff' / f'handoff_to_step3b__{report_id}.json',
    }


def retrieval_docs_for(case_name: str, factor_id: str, current_identity: dict[str, Any]) -> list[dict[str, Any]]:
    if case_name == 'similar_failure_imported':
        return [{
            'report_id': 'PRIOR_FAILURE_SHORT_SIDE',
            'factor_id': 'PRIOR_PRICE_VOLUME_FAILURE',
            'doc_type': 'knowledge_record',
            'decision': 'iterate',
            'knowledge_scope': 'anti_pattern',
            'factor_family': 'price_volume_correlation',
            'failure_signature': 'short_side_dominance',
            'text': 'SMOKE_PRICE_VOLUME synthetic Step6 smoke lesson price volume correlation failed because long-short spread was driven by short-side dominance and high turnover cost.',
        }]
    if case_name in {'similar_success_rejected_condition_mismatch', 'alpha013_like_advisory_mechanism_challenge_branch'}:
        return [{
            'report_id': 'PRIOR_SUCCESS_LOW_TURNOVER',
            'factor_id': 'PRIOR_PRICE_VOLUME_SUCCESS',
            'doc_type': 'factor_record',
            'decision': 'promote_official',
            'knowledge_scope': 'similar_case',
            'factor_family': 'price_volume_correlation',
            'failure_signature': 'low_turnover_success_condition',
            'text': 'SMOKE_PRICE_VOLUME synthetic Step6 smoke lesson price volume correlation succeeded only under low turnover and positive cost adjusted long side Sharpe.',
        }]
    if case_name == 'same_factor_cross_identity_negative':
        bad_identity = dict(current_identity)
        bad_identity['formula_hash'] = 'different_formula_hash'
        bad_identity['run_id'] = str(current_identity.get('run_id') or '') + '__stale'
        return [{
            'report_id': 'BAD_SAME_FACTOR_CASE',
            'factor_id': factor_id,
            'doc_type': 'knowledge_record',
            'decision': 'promote_official',
            'knowledge_scope': 'same_factor',
            'factor_family': 'price_volume_correlation',
            'formula_hash': 'different_formula_hash',
            'artifact_identity': bad_identity,
            'text': 'SMOKE_PRICE_VOLUME malformed same_factor evidence with mismatched formula hash and run identity.',
        }]
    return []


def write_retrieval_index(root: Path, case_name: str, factor_id: str, current_identity: dict[str, Any]) -> Path:
    path = root / 'objects' / 'retrieval' / f'factorforge_retrieval_index__{case_name}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    docs = retrieval_docs_for(case_name, factor_id, current_identity)
    path.write_text('\n'.join(json.dumps(item, ensure_ascii=False) for item in docs), encoding='utf-8')
    return path


def base_identity(report_id: str, factor_id: str) -> dict[str, Any]:
    formula_text = 'rank(close + volume)'
    formula_hash = stable_hash({'formula_text': formula_text})
    spec_hash = stable_hash({'report_id': report_id, 'factor_id': factor_id, 'formula_text': formula_text})
    return build_artifact_identity(
        report_id=report_id,
        factor_id=factor_id,
        source_type='natural_language_hypothesis',
        implementation_mode='operator',
        contract_version='factorforge_step2_source_contract_v2',
        producer='step4',
        upstream_producer='step12_hypothesis_intake',
        spec_hash=spec_hash,
        branch_id='main',
        run_id=f'{report_id}__run_001',
        formula_hash=formula_hash,
        artifact_role='factor_run_master',
    )


def identity_for(parent: dict[str, Any], role: str, producer: str) -> dict[str, Any]:
    out = dict(parent)
    out['artifact_role'] = role
    out['producer'] = producer
    return out


def long_metrics(kind: str) -> dict[str, Any]:
    metrics = {
        'rank_ic_mean': 0.045,
        'rank_ic_ir': 0.55,
        'pearson_ic_mean': 0.03,
        'pearson_ic_ir': 0.35,
        'long_side_mean_return_daily': 0.00055,
        'long_side_annual_return': 0.18,
        'long_side_return_std_daily': 0.006,
        'long_side_annual_volatility': 0.095,
        'long_side_sharpe': 1.2,
        'long_side_max_drawdown': -0.12,
        'long_side_recovery_days': 80,
        'long_side_turnover_mean_daily': 0.08,
        'turnover_mean': 0.08,
        'trading_cogs_daily': 0.08 * 0.003,
        'trading_cogs_annual': 0.08 * 0.003 * 252,
        'cost_adjusted_return_daily': 0.00031,
        'cost_adjusted_annual_return': 0.11,
        'cost_adjusted_long_side_sharpe': 0.92,
        'cost_adjusted_long_side_max_drawdown': -0.15,
        'cost_adjusted_long_side_recovery_days': 110,
        'long_short_spread_mean': 0.0007,
        'long_short_spread_ir': 0.7,
        'top_decile_mean_return': 0.00055,
        'bottom_decile_mean_return': -0.00015,
    }
    if kind == 'missing_long_side_metrics':
        for key in [
            'long_side_annual_volatility',
            'long_side_sharpe',
            'long_side_max_drawdown',
            'long_side_recovery_days',
            'trading_cogs_daily',
            'trading_cogs_annual',
            'cost_adjusted_annual_return',
            'cost_adjusted_long_side_sharpe',
        ]:
            metrics.pop(key, None)
    elif kind == 'short_side_dominance':
        metrics.update({
            'rank_ic_mean': 0.02,
            'long_side_mean_return_daily': -0.00005,
            'long_side_annual_return': -0.01,
            'long_side_sharpe': -0.05,
            'cost_adjusted_annual_return': -0.04,
            'cost_adjusted_long_side_sharpe': -0.2,
            'top_decile_mean_return': -0.00005,
            'bottom_decile_mean_return': -0.00120,
            'long_short_spread_mean': 0.00115,
        })
    elif kind == 'long_side_negative':
        metrics.update({
            'rank_ic_mean': -0.01,
            'long_side_mean_return_daily': -0.00018,
            'long_side_annual_return': -0.05,
            'long_side_sharpe': -0.35,
            'cost_adjusted_annual_return': -0.08,
            'cost_adjusted_long_side_sharpe': -0.45,
            'top_decile_mean_return': -0.00018,
            'bottom_decile_mean_return': 0.00002,
            'long_short_spread_mean': -0.00020,
        })
    elif kind == 'non_monotonic':
        metrics.update({
            'rank_ic_mean': 0.015,
            'long_side_mean_return_daily': 0.00008,
            'long_side_annual_return': 0.03,
            'long_side_sharpe': 0.25,
            'cost_adjusted_annual_return': 0.01,
            'cost_adjusted_long_side_sharpe': 0.10,
            'top_decile_mean_return': 0.00003,
            'bottom_decile_mean_return': 0.00010,
            'long_short_spread_mean': -0.00007,
        })
    elif kind == 'unknown_mechanism_iterate':
        metrics.update({
            'rank_ic_mean': 0.0,
            'rank_ic_ir': 0.02,
            'long_side_annual_return': 0.04,
            'long_side_sharpe': 0.30,
            'cost_adjusted_annual_return': 0.02,
            'cost_adjusted_long_side_sharpe': 0.15,
            'top_decile_mean_return': 0.00012,
            'bottom_decile_mean_return': 0.00001,
            'long_short_spread_mean': 0.00011,
        })
    elif kind == 'high_turnover_cost':
        metrics.update({
            'long_side_annual_return': 0.10,
            'long_side_sharpe': 0.62,
            'long_side_turnover_mean_daily': 2.0,
            'turnover_mean': 2.0,
            'trading_cogs_daily': 2.0 * 0.003,
            'trading_cogs_annual': 2.0 * 0.003 * 252,
            'cost_adjusted_return_daily': -0.0055,
            'cost_adjusted_annual_return': -1.40,
            'cost_adjusted_long_side_sharpe': -0.8,
        })
    elif kind == 'open_close_intraday_position':
        metrics.update({
            'rank_ic_mean': 0.048,
            'rank_ic_ir': 0.36,
            'pearson_ic_mean': 0.032,
            'pearson_ic_ir': 0.22,
            'long_side_mean_return_daily': -0.0010,
            'long_side_annual_return': -0.25,
            'long_side_sharpe': -0.96,
            'long_side_max_drawdown': -0.94,
            'long_side_recovery_days': 3670,
            'long_side_turnover_mean_daily': 0.86,
            'turnover_mean': 0.86,
            'trading_cogs_daily': 0.86 * 0.003,
            'trading_cogs_annual': 0.86 * 0.003 * 252,
            'cost_adjusted_return_daily': -0.0036,
            'cost_adjusted_annual_return': -0.90,
            'cost_adjusted_long_side_sharpe': -3.2,
            'top_decile_mean_return': -0.0010,
            'bottom_decile_mean_return': -0.0014,
            'long_short_spread_mean': 0.0004,
            'long_short_spread_ir': 0.20,
        })
    elif kind == 'alpha013_cost_contradiction':
        metrics.update({
            'rank_ic_mean': 0.0358735,
            'rank_ic_ir': 0.6114,
            'long_side_annual_return': 0.1644,
            'long_side_sharpe': 0.687,
            'long_side_max_drawdown': -0.3994,
            'long_side_recovery_days': 1774,
            'long_side_turnover_mean_daily': 0.4723,
            'turnover_mean': 0.4723,
            'trading_cogs_daily': 0.4723 * 0.003,
            'trading_cogs_annual': 0.3570,
            'cost_adjusted_return_daily': -0.00076,
            'cost_adjusted_annual_return': -0.1926,
            'cost_adjusted_long_side_sharpe': -0.805,
            'top_decile_mean_return': 0.00010,
            'bottom_decile_mean_return': -0.00120,
            'long_short_spread_mean': 0.00130,
        })
    return metrics


def write_fixture(root: Path, report_id: str, *, kind: str, factor_id: str | None = None) -> None:
    factor_id = factor_id or 'SMOKE_PRICE_VOLUME'
    identity_run = base_identity(report_id, factor_id)
    identity_case = identity_for(identity_run, 'factor_case_master', 'step5')
    identity_eval = identity_for(identity_run, 'factor_evaluation', 'step4')
    objects = root / 'objects'
    evaluations = root / 'evaluations' / report_id
    metrics = long_metrics(kind)
    backend_status = 'skipped' if kind == 'all_backends_skipped' else 'success'
    backend_runs = [
        {
            'backend': 'self_quant_analyzer',
            'status': backend_status,
            'payload_path': str(evaluations / 'self_quant_analyzer' / 'evaluation_payload.json'),
            'artifact_identity': identity_eval,
        },
        {
            'backend': 'qlib_backtest',
            'status': backend_status,
            'payload_path': str(evaluations / 'qlib_backtest' / 'evaluation_payload.json'),
            'artifact_identity': identity_eval,
        },
    ]
    if backend_status != 'skipped':
        write_json(evaluations / 'self_quant_analyzer' / 'evaluation_payload.json', {
            'artifact_identity': identity_eval,
            'ic_summary': {k: metrics[k] for k in ['rank_ic_mean', 'rank_ic_ir', 'pearson_ic_mean', 'pearson_ic_ir'] if k in metrics},
            'group_backtest_summary': {k: metrics[k] for k in ['long_short_spread_mean', 'long_short_spread_ir', 'top_decile_mean_return', 'bottom_decile_mean_return'] if k in metrics},
            'long_side_performance': {k: v for k, v in metrics.items() if k.startswith('long_side_') or k in {
                'turnover_mean',
                'trading_cogs_daily',
                'trading_cogs_annual',
                'cost_adjusted_return_daily',
                'cost_adjusted_annual_return',
                'cost_adjusted_long_side_sharpe',
                'cost_adjusted_long_side_max_drawdown',
                'cost_adjusted_long_side_recovery_days',
            }},
        })
        write_json(evaluations / 'qlib_backtest' / 'evaluation_payload.json', {
            'artifact_identity': identity_eval,
            'native_backtest_metrics': {
                'final_account': 101_000_000,
                'mean_return': 0.0003,
                'annual_return': metrics.get('cost_adjusted_annual_return', 0.04),
                'sharpe': metrics.get('cost_adjusted_long_side_sharpe', 0.4),
                'max_drawdown': metrics.get('long_side_max_drawdown', -0.15),
                'recovery_days': metrics.get('long_side_recovery_days', 100),
                'turnover_mean': metrics.get('turnover_mean', 0.1),
            },
            'stub_backtest_metrics': {
                'long_short_spread_mean': metrics.get('long_short_spread_mean'),
                'long_short_spread_ir': metrics.get('long_short_spread_ir'),
                'top_decile_mean_return': metrics.get('top_decile_mean_return'),
                'bottom_decile_mean_return': metrics.get('bottom_decile_mean_return'),
            },
        })

    implementation_mode_decision = {
        'decision_version': 'factorforge_implementation_mode_decision_v1',
        'selected_mode': 'operator',
        'operator_attempted': True,
        'operator_result': 'success',
        'hybrid_attempted': False,
        'hybrid_result': 'not_applicable',
        'hybrid_failure_reason': 'operator mode was sufficient',
        'direct_code_attempted': False,
        'direct_code_result': 'not_applicable',
        'direct_code_failure_reason': 'operator mode was sufficient',
        'final_decision_reason': 'synthetic Step6 smoke fixture',
        'correctness_risk': 'low',
        'human_review_required': False,
    }
    run_master = {
        'report_id': report_id,
        'factor_id': factor_id,
        'run_status': 'success',
        'artifact_identity': identity_run,
        'implementation_mode_decision': implementation_mode_decision,
        'diagnostic_summary': {'row_count': 20, 'date_count': 5, 'ticker_count': 4, 'nan_ratio': 0.05},
        'evaluation_results': {'backend_runs': backend_runs},
    }
    case_quality = {
        'step4_has_successful_backend': True,
        'self_quant_required_and_present': True,
        'long_side_metrics_present': True,
        'identity_chain_verified': True,
        'mode_decision_present': True,
    }
    case = {
        'report_id': report_id,
        'factor_id': factor_id,
        'final_status': 'validated',
        'artifact_identity': identity_case,
        'implementation_mode_decision': implementation_mode_decision,
        'evidence_quality': case_quality,
        'lessons': ['synthetic Step6 smoke lesson'],
        'next_actions': ['synthetic Step6 smoke next action'],
    }
    evaluation = {
        'report_id': report_id,
        'factor_id': factor_id,
        'artifact_identity': identity_eval,
        'backend_summary': [
            {'backend': item['backend'], 'status': item['status'], 'key_metrics': metrics}
            for item in backend_runs
        ],
    }
    handoff = {
        'report_id': report_id,
        'factor_id': factor_id,
        'artifact_identity': identity_for(identity_run, 'handoff_to_step6', 'step5'),
        'implementation_mode_decision': implementation_mode_decision,
        'lessons': case['lessons'],
        'next_actions': case['next_actions'],
    }
    if kind in {'unknown_mechanism', 'unknown_mechanism_iterate'}:
        formula_text = 'rank(custom_signal_z)'
        required_inputs = ['custom_signal_z']
        operators = ['rank']
    elif kind == 'invalid_formula_specific_derivation':
        formula_text = 'custom_signal_z'
        required_inputs = ['custom_signal_z']
        operators = []
    elif kind == 'open_close_intraday_position':
        formula_text = 'rank(negate(signedpower(minus(1, divide(open, close)), 1)))'
        required_inputs = ['open', 'close']
        operators = ['rank', 'negate', 'signedpower', 'minus', 'divide']
    elif kind in {'price_volume_correlation', 'strong_mechanism_support', 'alpha013_cost_contradiction'}:
        formula_text = '(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))'
        required_inputs = ['high', 'volume']
        operators = ['rank', 'correlation', 'sum', 'multiply']
    else:
        formula_text = 'rank(close + volume)'
        required_inputs = ['close', 'volume']
        operators = ['rank', 'plus']
    factor_spec = {
        'report_id': report_id,
        'factor_id': factor_id,
        'artifact_identity': identity_for(identity_run, 'factor_spec_master', 'step2'),
        'canonical_spec': {
            'formula_text': formula_text,
            'required_inputs': required_inputs,
            'operators': operators,
            'mechanism_analysis': {'strong_mechanism_support': kind == 'strong_mechanism_support'},
            'time_series_steps': [],
            'cross_sectional_steps': ['rank'],
            'preprocessing': ['delay(1) information lag documented'],
        },
    }
    idea = {
        'report_id': report_id,
        'factor_id': factor_id,
        'source_type': 'natural_language_hypothesis',
    }
    researcher_memo = {
        'report_id': report_id,
        'factor_id': factor_id,
        'memo': 'Synthetic external researcher memo for isolated Step6 intelligence smoke.',
        'reviewer': 'smoke',
    }
    write_json(objects / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
    write_json(objects / 'factor_case_master' / f'factor_case_master__{report_id}.json', case)
    write_json(objects / 'validation' / f'factor_evaluation__{report_id}.json', evaluation)
    write_json(objects / 'handoff' / f'handoff_to_step6__{report_id}.json', handoff)
    write_json(objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json', factor_spec)
    write_json(objects / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json', idea)
    write_json(objects / 'research_iteration_master' / f'researcher_memo__{report_id}.json', researcher_memo)


def write_current_agent_memo_fixture(root: Path, report_id: str, runtime: str = 'codex_smoke') -> Path:
    objects = root / 'objects'
    spec = read_json(objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    case = read_json(objects / 'factor_case_master' / f'factor_case_master__{report_id}.json')
    evaluation = read_json(objects / 'validation' / f'factor_evaluation__{report_id}.json')
    canonical = spec.get('canonical_spec') or {}
    formula = str(canonical.get('formula_text') or '')
    fields = ', '.join(str(item) for item in (canonical.get('required_inputs') or []))
    operators = ', '.join(str(item) for item in (canonical.get('operators') or []))
    memo = build_main_agent_mechanism_memo(
        report_id=report_id,
        factor_spec=spec,
        factor_case=case,
        evaluation_summary=evaluation,
        step6_iteration={},
    )
    formula_terms = f"the formula uses fields {fields} and operators {operators}"
    fields_l = fields.lower()
    operators_l = operators.lower()
    if 'volume' in fields_l and ('correlation' in operators_l or 'close' in fields_l or 'high' in fields_l):
        selected_model_family = 'transient_impact'
        process_text = 'r_i,t+1 follows a transient impact and liquidity-pressure process with imbalance decay, inventory transfer, or participation-driven state migration depending on the formula-defined state and evidence'
    else:
        selected_model_family = 'stochastic_process'
        process_text = 'r_i,t+1 follows a conditional stochastic return process with drift, reversal, impact decay, or state migration depending on the formula-defined state and evidence'
    memo['producer'] = 'current_main_agent'
    memo['agent_authorship'] = {
        'authoring_mode': 'current_agent_freeform',
        'agent_role': 'main_agent',
        'runtime': runtime,
        'answered_without_deterministic_template': True,
    }
    memo['mechanism_qa'] = {
        'formula_state_answer': (
            f"The current main agent reads {formula_terms}. The formula state is the observable security-day state "
            "defined by those actual inputs, not a reused factor-family label; this answer ties the state to the formula components."
        ),
        'economic_hypothesis_answer': (
            "The economic hypothesis is that the formula-defined state can be monetized only if a counterparty faces delayed belief revision, "
            "liquidity demand, risk-transfer pressure, or constrained rebalancing that creates a next-horizon conditional return."
        ),
        'math_model_answer': (
            "The baseline model is a conditional stochastic return process indexed by the formula state; the mutation for this formula is to "
            "let the observed component map define the latent state variable, payoff direction, and horizon instead of applying a generic template."
        ),
        'payer_answer': (
            "The likely payer is the constrained or delayed counterparty on the other side of the formula-defined state: delayed updaters, "
            "liquidity demanders, or risk-transfer accounts whose behavior creates drift, reversal, impact decay, or state migration."
        ),
        'payoff_answer': (
            "The payoff argument is E[r_i,t+1 | F_t, formula_state_i,t]; the sign must be determined by the stated state direction and must survive "
            "long-side, cost-adjusted evidence rather than relying on short-leg diagnostics."
        ),
        'estimator_mapping_answer': (
            f"Estimator mapping follows {formula_terms}: each listed field/operator contributes an observable component to the latent state; rank terms "
            "test cross-sectional ordering, arithmetic terms define state direction or scale, and the mapping remains within F_t."
        ),
        'metric_signature_answer': (
            "The expected metric signature is aligned rank IC, positive high-score long-side return, positive cost-adjusted return, monotonic top groups, "
            "and turnover low enough that the modeled payoff is not consumed by trading costs."
        ),
        'falsification_answer': (
            "Falsify if the high-score long side is negative after costs; falsify if G9 beats G10 or the expected direction reverses; falsify if component "
            "ablation shows the formula state is not the source of IC; kill if no concrete payer remains."
        ),
    }
    memo['economic_hypothesis'] = {
        'return_source_class': 'mixed',
        'payer_or_counterparty': 'delayed updaters, liquidity demanders, or risk-transfer accounts tied to the formula-defined state',
        'why_they_pay': 'they trade against the formula-defined state because belief adjustment, immediacy demand, or risk-transfer constraints can leave a next-horizon conditional payoff',
        'necessary_market_structure': 'the formula-defined state must predict legal next-horizon returns strongly enough to survive turnover and implementation costs',
    }
    memo['math_hypothesis'] = {
        'selected_model_family': selected_model_family,
        'why_this_model': 'the open-ended memo treats the formula output as a state variable in a conditional return process, with payoff sign and horizon tested by evidence',
        'why_not_generic_template': 'the model is accepted only because the current agent supplied freeform answers tying formula components to payer behavior, payoff, estimator mapping, and falsification',
        'random_object': 'security-day forward return conditional on legal information set F_t and formula-defined state',
        'latent_state': 'formula-defined conditional return state from the actual fields and operators',
        'process_or_distribution': process_text,
        'target_functional': 'E[r_i,t+1 | F_t, formula_state_i,t]',
        'formula_as_estimator': memo['mechanism_qa']['estimator_mapping_answer'],
        'expected_metric_signature': {
            'rank_ic': 'rank IC sign must match the declared payoff direction',
            'long_side': 'high-score long side must be positive if the state is monetizable',
            'cost_adjusted': 'cost-adjusted return must remain positive after turnover and impact',
            'monotonicity': 'quantile ordering must match the stated direction',
            'turnover': 'turnover must not consume the expected payoff',
        },
    }
    memo_path = objects / 'research_iteration_master' / f'main_agent_mechanism_memo__{report_id}.json'
    memo_md_path = objects / 'research_iteration_master' / f'main_agent_mechanism_memo__{report_id}.md'
    write_json(memo_path, memo)
    memo_md_path.parent.mkdir(parents=True, exist_ok=True)
    memo_md_path.write_text(render_main_agent_mechanism_memo_markdown(memo), encoding='utf-8')
    return memo_path


def run_case(root: Path, case_name: str, kind: str, expected: str, token: str, factor_id: str | None = None, memo_mode: str = 'valid') -> dict[str, Any]:
    report_id = f'STEP6_INTEL_{case_name.upper()}'
    write_fixture(root, report_id, kind=kind, factor_id=factor_id)
    if memo_mode == 'valid':
        write_current_agent_memo_fixture(root, report_id)
    run_master_path = root / 'objects' / 'factor_run_master' / f'factor_run_master__{report_id}.json'
    run_master = read_json(run_master_path) if run_master_path.exists() else {}
    current_identity = run_master.get('artifact_identity') or {}
    retrieval_index = write_retrieval_index(root, case_name, factor_id or 'SMOKE_PRICE_VOLUME', current_identity)
    proof = root / 'objects' / 'runtime_context' / f'ultimate_run_report__{report_id}.json'
    cmd = [
        sys.executable,
        'scripts/run_factorforge_ultimate.py',
        '--report-id',
        report_id,
        '--start-step',
        '6',
        '--end-step',
        '6',
        '--skip-researcher-packets',
        '--factorforge-root',
        str(root),
        '--council-mode',
        'off',
        '--proof-output',
        str(proof),
    ]
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    env['FACTORFORGE_RETRIEVAL_INDEX'] = str(retrieval_index)
    env['FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL'] = '1'
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    output = proc.stdout + '\n' + proc.stderr
    if proof.exists():
        try:
            proof_payload = read_json(proof)
            for command in proof_payload.get('commands') or []:
                output += '\n' + str(command.get('stdout_tail') or '')
                output += '\n' + str(command.get('stderr_tail') or '')
        except Exception:
            pass
    iteration_path = root / 'objects' / 'research_iteration_master' / f'research_iteration_master__{report_id}.json'
    official_path = root / 'objects' / 'factor_library_official' / f'factor_record__{report_id}.json'
    prewrite_block_path = root / 'objects' / 'validation' / f'step6_prewrite_block__{report_id}.json'
    main_agent_status_path = root / 'objects' / 'research_iteration_master' / f'main_agent_mechanism_memo_status__{report_id}.json'
    forbidden_paths = forbidden_writeback_paths(root, report_id)
    forbidden_exists = {name: path.exists() for name, path in forbidden_paths.items()}
    forbidden_absent = not any(forbidden_exists.values())
    iteration = read_json(iteration_path) if iteration_path.exists() else {}
    research_memo = ((iteration.get('research_judgment') or {}).get('research_memo') or {})
    evidence_status_split = ((research_memo.get('evidence_audit') or {}).get('evidence_status_split') or {})
    loop_brief_ref = iteration.get('loop_research_brief') or {}
    loop_brief_json_path = Path(loop_brief_ref.get('json_path')) if loop_brief_ref.get('json_path') else root / '__missing_loop_brief.json'
    loop_brief_md_path = Path(loop_brief_ref.get('markdown_path')) if loop_brief_ref.get('markdown_path') else root / '__missing_loop_brief.md'
    loop_brief_json = read_json(loop_brief_json_path) if loop_brief_json_path.exists() else {}
    actual = 'PASS' if proc.returncode == 0 else 'BLOCK'
    token_present = token in output or token in json.dumps(iteration, ensure_ascii=False)
    revision_strategy = research_memo.get('revision_strategy') or {}
    case_comparison = research_memo.get('case_comparison') or {}
    search_policy_decision = research_memo.get('search_policy_decision') or {}
    branch_templates = search_policy_decision.get('branch_templates') or []
    first_branch = branch_templates[0] if branch_templates and isinstance(branch_templates[0], dict) else {}
    hypotheses = revision_strategy.get('revision_hypotheses') or []
    expression_changes = [str(item.get('expression_change') or '') for item in hypotheses]
    forbidden_expression_terms = [
        term
        for term in ['portfolio', 'rebalance', 'short leg', 'short-leg', 'long-short', 'decile trading', 'buy q1/sell q10', 'buy q10/sell q1']
        if any(term in expression.lower() for expression in expression_changes)
    ]
    ok = (
        (expected == 'PASS' and proc.returncode == 0 and token_present)
        or (expected == 'BLOCK' and proc.returncode != 0 and token_present and prewrite_block_path.exists() and forbidden_absent)
        or (expected == 'NO_PROMOTE' and proc.returncode == 0 and not official_path.exists() and token_present)
        or (expected == 'NO_OFFICIAL' and proc.returncode == 0 and not official_path.exists() and token_present)
        or (expected == 'PROMOTE' and proc.returncode == 0 and official_path.exists() and token_present)
        or (expected == 'PAUSE' and proc.returncode == 0 and token_present and main_agent_status_path.exists() and forbidden_absent)
    )
    if forbidden_expression_terms:
        ok = False
    loop_authorization = revision_strategy.get('loop_authorization')
    handoff_exists = forbidden_exists['handoff_to_step3b']
    rejected_lessons = case_comparison.get('rejected_lessons') or []
    recommended_mode = search_policy_decision.get('recommended_mode')
    branch_count = len(branch_templates)
    branch_execution_flags = [
        branch.get('execution_allowed_by_default')
        for branch in branch_templates
        if isinstance(branch, dict)
    ]
    branch_approval_flags = [
        branch.get('requires_human_approval_before_execution')
        for branch in branch_templates
        if isinstance(branch, dict)
    ]
    program_search_validation: dict[str, Any] | None = None
    if case_name == 'alpha013_like_advisory_mechanism_challenge_branch':
        build_cmd = [
            sys.executable,
            'skills/factor-forge-step6/scripts/build_program_search_plan.py',
            '--report-id',
            report_id,
        ]
        validate_cmd = [
            sys.executable,
            'skills/factor-forge-step6/scripts/validate_program_search_plan.py',
            '--report-id',
            report_id,
        ]
        build_proc = subprocess.run(build_cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
        validate_proc = subprocess.run(validate_cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
        plan_path = root / 'objects' / 'research_iteration_master' / f'program_search_plan__{report_id}.json'
        plan = read_json(plan_path) if plan_path.exists() else {}
        plan_branches = plan.get('branches') or []
        plan_first_branch = plan_branches[0] if plan_branches and isinstance(plan_branches[0], dict) else {}
        program_search_validation = {
            'build_command': build_cmd,
            'build_rc': build_proc.returncode,
            'build_stdout_tail': tail(build_proc.stdout),
            'build_stderr_tail': tail(build_proc.stderr),
            'validate_command': validate_cmd,
            'validate_rc': validate_proc.returncode,
            'validate_stdout_tail': tail(validate_proc.stdout),
            'validate_stderr_tail': tail(validate_proc.stderr),
            'plan_path': str(plan_path),
            'plan_exists': plan_path.exists(),
            'plan_status': plan.get('status'),
            'branch_count': len(plan_branches),
            'first_branch': plan_first_branch,
        }
    loop_contract_ok = True
    if case_name == 'similar_success_rejected_condition_mismatch':
        loop_contract_ok = (
            proc.returncode == 0
            and not official_path.exists()
            and not handoff_exists
            and loop_authorization == 'advisory_only'
            and bool(rejected_lessons)
            and all(flag is False for flag in branch_execution_flags)
        )
    elif case_name == 'high_turnover_revision':
        success_text = json.dumps(first_branch.get('success_criteria') or [], ensure_ascii=False).lower()
        loop_contract_ok = (
            handoff_exists
            and loop_authorization == 'approved_for_step3b_handoff'
            and recommended_mode == 'bayesian_exploit'
            and branch_count >= 1
            and first_branch.get('branch_role') == 'exploit'
            and first_branch.get('search_mode') == 'bayesian_search'
            and first_branch.get('requires_human_approval_before_execution') is True
            and first_branch.get('execution_allowed_by_default') is False
            and 'cost-adjusted' in success_text
            and 'turnover' in success_text
        )
    elif case_name == 'non_monotonic_revision':
        branch_text = json.dumps(first_branch, ensure_ascii=False).lower()
        loop_contract_ok = (
            handoff_exists
            and loop_authorization == 'approved_for_step3b_handoff'
            and recommended_mode == 'genetic_explore'
            and branch_count >= 1
            and first_branch.get('branch_role') == 'explore'
            and first_branch.get('search_mode') == 'genetic_algorithm'
            and first_branch.get('requires_human_approval_before_execution') is True
            and first_branch.get('execution_allowed_by_default') is False
            and ('monotonic' in branch_text or 'state split' in branch_text or 'operator transform' in branch_text)
        )
    elif case_name == 'mechanism_unclear_revision':
        branch_text = json.dumps(first_branch, ensure_ascii=False).lower()
        loop_contract_ok = (
            handoff_exists
            and loop_authorization == 'approved_for_step3b_handoff'
            and recommended_mode == 'mechanism_challenge'
            and branch_count >= 1
            and first_branch.get('branch_role') == 'macro'
            and first_branch.get('search_mode') == 'mechanism_challenge'
            and first_branch.get('requires_human_approval_before_execution') is True
            and first_branch.get('execution_allowed_by_default') is False
            and 'bayesian' not in branch_text
        )
    elif case_name == 'long_side_negative_revision':
        loop_contract_ok = (
            not handoff_exists
            and loop_authorization == 'advisory_only'
            and recommended_mode in {'kill', 'mechanism_challenge'}
            and all(flag is False for flag in branch_execution_flags)
        )
    elif case_name == 'alpha013_like_advisory_mechanism_challenge_branch':
        branch_text_payload = {
            key: value
            for key, value in first_branch.items()
            if key not in {'hard_guards', 'forbidden_search'}
        }
        branch_text = json.dumps(branch_text_payload, ensure_ascii=False).lower()
        plan_first_branch = ((program_search_validation or {}).get('first_branch') or {})
        loop_contract_ok = (
            proc.returncode == 0
            and not official_path.exists()
            and not handoff_exists
            and recommended_mode == 'mechanism_challenge'
            and branch_count == 1
            and first_branch.get('branch_id') == 'challenge_mechanism_cost_contradiction'
            and first_branch.get('branch_role') == 'macro'
            and first_branch.get('search_mode') == 'mechanism_challenge'
            and first_branch.get('advisory_only') is True
            and first_branch.get('step3b_handoff_allowed') is False
            and first_branch.get('requires_human_approval_before_execution') is True
            and first_branch.get('execution_allowed_by_default') is False
            and loop_authorization == 'advisory_only'
            and case_comparison.get('similar_success_condition_mismatch') is True
            and (program_search_validation or {}).get('build_rc') == 0
            and (program_search_validation or {}).get('validate_rc') == 0
            and (program_search_validation or {}).get('plan_status') == 'pending_human_approval'
            and (program_search_validation or {}).get('branch_count') == 1
            and plan_first_branch.get('branch_role') == 'macro'
            and plan_first_branch.get('search_mode') == 'mechanism_challenge'
            and plan_first_branch.get('status') == 'proposed'
            and plan_first_branch.get('requires_human_approval_before_execution') is True
            and plan_first_branch.get('execution_allowed_by_default') is False
            and not any(term in branch_text for term in ['portfolio', 'rebalance', 'short leg', 'long-short', 'decile trading', 'shared clean data'])
        )
    elif case_name == 'valid_promote_no_revision_needed':
        loop_contract_ok = (
            official_path.exists()
            and recommended_mode == 'none'
            and branch_count == 0
            and not handoff_exists
        )
    elif case_name == 'loop_research_brief_generated_pass':
        required_sections = {
            'decision_snapshot',
            'economic_interpretation',
            'metrics',
            'chart_evidence',
            'metric_analysis',
            'knowledge_comparison',
            'next_research_direction',
            'final_loop_conclusion',
        }
        loop_contract_ok = (
            loop_brief_json_path.exists()
            and loop_brief_md_path.exists()
            and loop_brief_json.get('brief_version') == 'factorforge_loop_research_brief_v1'
            and required_sections.issubset(set(loop_brief_json.keys()))
            and 'long_short_nav_diagnostic_only' in (loop_brief_json.get('chart_evidence') or {})
            and loop_brief_json.get('metrics', {}).get('rank_ic_mean') is not None
            and loop_brief_json.get('next_research_direction', {}).get('why_not_portfolio_fix')
        )
    elif expected == 'BLOCK':
        loop_contract_ok = not handoff_exists
    if not loop_contract_ok:
        ok = False
    return {
        'case': case_name,
        'report_id': report_id,
        'command': cmd,
        'rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'expected': expected,
        'actual': actual,
        'ok': ok,
        'expected_token': token,
        'token_present': token_present,
        'proof_path': str(proof),
        'proof_exists': proof.exists(),
        'prewrite_diagnostic': {
            'path': str(prewrite_block_path),
            'exists': prewrite_block_path.exists(),
        },
        'main_agent_memo_status': {
            'path': str(main_agent_status_path),
            'exists': main_agent_status_path.exists(),
            'payload': read_json(main_agent_status_path) if main_agent_status_path.exists() else {},
        },
        'forbidden_writebacks_absent': forbidden_absent,
        'forbidden_writebacks': {
            name: {'path': str(path), 'exists': forbidden_exists[name]}
            for name, path in forbidden_paths.items()
        },
        'produced_files': {
            'research_iteration_master': iteration_path.exists(),
            'factor_library_official': official_path.exists(),
            'factor_library_all': (root / 'objects' / 'factor_library_all' / f'factor_record__{report_id}.json').exists(),
            'knowledge_record': (root / 'objects' / 'research_knowledge_base' / f'knowledge_record__{report_id}.json').exists(),
            'loop_research_brief_markdown': loop_brief_md_path.exists(),
            'loop_research_brief_json': loop_brief_json_path.exists(),
        },
        'loop_research_brief': {
            'ref': loop_brief_ref,
            'markdown_path': str(loop_brief_md_path) if loop_brief_ref.get('markdown_path') else '',
            'json_path': str(loop_brief_json_path) if loop_brief_ref.get('json_path') else '',
            'json_exists': loop_brief_json_path.exists(),
            'markdown_exists': loop_brief_md_path.exists(),
            'brief_version': loop_brief_json.get('brief_version'),
            'sections': sorted(loop_brief_json.keys()) if loop_brief_json else [],
            'core_metric_rank_ic_mean': (loop_brief_json.get('metrics') or {}).get('rank_ic_mean') if loop_brief_json else None,
            'chart_keys': sorted((loop_brief_json.get('chart_evidence') or {}).keys()) if loop_brief_json else [],
        },
        'research_intelligence': {
            'evidence_verdict': (research_memo.get('evidence_audit') or {}).get('evidence_verdict'),
            'evidence_status_split': evidence_status_split,
            'wrapper_validation_status': evidence_status_split.get('wrapper_validation_status'),
            'self_quant_evidence_status': evidence_status_split.get('self_quant_evidence_status'),
            'qlib_native_status': evidence_status_split.get('qlib_native_status'),
            'research_decision_status': evidence_status_split.get('research_decision'),
            'short_side_dominance_suspected': ((research_memo.get('evidence_audit') or {}).get('metric_consistency') or {}).get('short_side_dominance_suspected'),
            'cost_adjusted_status': ((research_memo.get('evidence_audit') or {}).get('long_side_evidence_quality') or {}).get('cost_adjusted_status'),
            'factor_family': (research_memo.get('mechanism_analysis') or {}).get('factor_family'),
            'return_source': (research_memo.get('mechanism_analysis') or {}).get('return_source'),
            'mechanism_fit': (research_memo.get('mechanism_analysis') or {}).get('mechanism_fit'),
            'necessary_conditions': (research_memo.get('mechanism_analysis') or {}).get('necessary_conditions'),
            'classification_uncertainty': (research_memo.get('mechanism_analysis') or {}).get('classification_uncertainty'),
            'similar_failure_cases_count': len((research_memo.get('case_comparison') or {}).get('similar_failure_cases') or []),
            'similar_success_cases_count': len((research_memo.get('case_comparison') or {}).get('similar_success_cases') or []),
            'imported_lessons': case_comparison.get('imported_lessons'),
            'rejected_lessons': case_comparison.get('rejected_lessons'),
            'knowledge_gap': case_comparison.get('knowledge_gap'),
            'case_comparison_verdict': case_comparison.get('case_comparison_verdict'),
            'similar_success_condition_mismatch': case_comparison.get('similar_success_condition_mismatch'),
            'identity_mismatch_cases': case_comparison.get('identity_mismatch_cases'),
            'decision': ((iteration.get('research_judgment') or {}).get('decision')),
            'primary_failure_signature': revision_strategy.get('primary_failure_signature'),
            'revision_quality': revision_strategy.get('revision_quality'),
            'revision_needed': revision_strategy.get('revision_needed'),
            'loop_authorization': loop_authorization,
            'loop_contract_ok': loop_contract_ok,
            'revision_hypotheses_count': len(hypotheses),
            'revision_hypotheses': hypotheses,
            'revision_forbidden_expression_terms': forbidden_expression_terms,
            'forbidden_search': (research_memo.get('search_policy_decision') or {}).get('forbidden_search'),
            'search_policy_recommended_mode': recommended_mode,
            'search_policy_branch_templates_count': branch_count,
            'search_policy_first_branch_role': first_branch.get('branch_role'),
            'search_policy_first_search_mode': first_branch.get('search_mode'),
            'search_policy_branch_human_approval_flags': branch_approval_flags,
            'search_policy_branch_execution_allowed_flags': branch_execution_flags,
            'search_policy_branch_templates': branch_templates,
        },
        'program_search_validation': program_search_validation,
    }


def run_program_search_plan_smoke(root: Path, report_id: str) -> dict[str, Any]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    build_cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/build_program_search_plan.py',
        '--report-id',
        report_id,
    ]
    validate_cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/validate_program_search_plan.py',
        '--report-id',
        report_id,
    ]
    build_proc = subprocess.run(build_cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    validate_proc = subprocess.run(validate_cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    plan_path = root / 'objects' / 'research_iteration_master' / f'program_search_plan__{report_id}.json'
    plan = read_json(plan_path) if plan_path.exists() else {}
    branches = plan.get('branches') or []
    first_branch = branches[0] if branches and isinstance(branches[0], dict) else {}
    branch_text = json.dumps(first_branch, ensure_ascii=False).lower()
    ok = (
        build_proc.returncode == 0
        and validate_proc.returncode == 0
        and plan_path.exists()
        and bool(branches)
        and first_branch.get('branch_id') == 'exploit_cost_persistence'
        and first_branch.get('search_mode') == 'bayesian_search'
        and first_branch.get('branch_role') == 'exploit'
        and first_branch.get('status') == 'proposed'
        and first_branch.get('requires_human_approval_before_execution') is True
        and first_branch.get('execution_allowed_by_default') is False
        and {'no_portfolio_expression_repair', 'no_short_leg_adoption', 'no_decile_trading', 'no_shared_clean_data_mutation'}.issubset(set(first_branch.get('hard_guards') or []))
        and 'portfolio' not in branch_text.replace('no_portfolio_expression_repair', '')
    )
    return {
        'report_id': report_id,
        'build_command': build_cmd,
        'build_rc': build_proc.returncode,
        'build_stdout_tail': tail(build_proc.stdout),
        'build_stderr_tail': tail(build_proc.stderr),
        'validate_command': validate_cmd,
        'validate_rc': validate_proc.returncode,
        'validate_stdout_tail': tail(validate_proc.stdout),
        'validate_stderr_tail': tail(validate_proc.stderr),
        'plan_path': str(plan_path),
        'plan_exists': plan_path.exists(),
        'branch_templates_used': first_branch.get('search_policy_decision_source') is not None,
        'branch_count': len(branches),
        'first_branch': first_branch,
        'ok': ok,
    }


def copy_iteration_for_program_search_case(root: Path, source_report_id: str, target_report_id: str) -> dict[str, Any]:
    src = root / 'objects' / 'research_iteration_master' / f'research_iteration_master__{source_report_id}.json'
    if not src.exists():
        raise FileNotFoundError(src)
    payload = read_json(src)
    payload['report_id'] = target_report_id
    payload['source_program_search_smoke_report_id'] = source_report_id
    path = root / 'objects' / 'research_iteration_master' / f'research_iteration_master__{target_report_id}.json'
    write_json(path, payload)
    return payload


def run_program_search_missing_templates_smoke(root: Path, source_report_id: str) -> dict[str, Any]:
    report_id = 'STEP6_INTEL_PROGRAM_SEARCH_MISSING_TEMPLATES_BLOCK'
    iteration = copy_iteration_for_program_search_case(root, source_report_id, report_id)
    research_memo = ((iteration.get('research_judgment') or {}).get('research_memo') or {})
    search_policy_decision = research_memo.get('search_policy_decision') or {}
    search_policy_decision['branch_templates'] = []
    if search_policy_decision.get('recommended_mode') in {'none', 'kill', None}:
        search_policy_decision['recommended_mode'] = 'bayesian_exploit'
    write_json(root / 'objects' / 'research_iteration_master' / f'research_iteration_master__{report_id}.json', iteration)

    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    build_cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/build_program_search_plan.py',
        '--report-id',
        report_id,
    ]
    validate_cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/validate_program_search_plan.py',
        '--report-id',
        report_id,
    ]
    build_proc = subprocess.run(build_cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    validate_proc = subprocess.run(validate_cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    plan_path = root / 'objects' / 'research_iteration_master' / f'program_search_plan__{report_id}.json'
    validation_path = root / 'objects' / 'validation' / f'program_search_plan_validation__{report_id}.json'
    plan = read_json(plan_path) if plan_path.exists() else {}
    validation = read_json(validation_path) if validation_path.exists() else {}
    token_blob = '\n'.join([
        build_proc.stdout,
        build_proc.stderr,
        validate_proc.stdout,
        validate_proc.stderr,
        json.dumps(plan, ensure_ascii=False),
        json.dumps(validation, ensure_ascii=False),
    ])
    ok = (
        plan_path.exists()
        and plan.get('status') == 'blocked_missing_branch_templates'
        and plan.get('branches') == []
        and 'missing_search_policy_branch_templates' in set(plan.get('blockers') or [])
        and validate_proc.returncode != 0
        and ('missing_search_policy_branch_templates' in token_blob or 'blocked_missing_branch_templates' in token_blob)
    )
    return {
        'report_id': report_id,
        'build_command': build_cmd,
        'build_rc': build_proc.returncode,
        'build_stdout_tail': tail(build_proc.stdout),
        'build_stderr_tail': tail(build_proc.stderr),
        'validate_command': validate_cmd,
        'validate_rc': validate_proc.returncode,
        'validate_stdout_tail': tail(validate_proc.stdout),
        'validate_stderr_tail': tail(validate_proc.stderr),
        'plan_path': str(plan_path),
        'plan_status': plan.get('status'),
        'branch_count': len(plan.get('branches') or []),
        'blockers': plan.get('blockers') or [],
        'validation_result': validation.get('result'),
        'token_present': 'missing_search_policy_branch_templates' in token_blob or 'blocked_missing_branch_templates' in token_blob,
        'ok': ok,
    }


def validate_mutated_program_search_plan(root: Path, source_report_id: str, mutation_name: str, mutator) -> dict[str, Any]:
    report_id = f'STEP6_INTEL_PROGRAM_SEARCH_FORBIDDEN_{mutation_name.upper()}'
    copy_iteration_for_program_search_case(root, source_report_id, report_id)
    source_plan_path = root / 'objects' / 'research_iteration_master' / f'program_search_plan__{source_report_id}.json'
    source_ledger_path = root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{source_report_id}.json'
    plan = read_json(source_plan_path)
    ledger = read_json(source_ledger_path)
    plan['report_id'] = report_id
    ledger['report_id'] = report_id
    for branch in plan.get('branches') or []:
        if isinstance(branch, dict):
            branch['parent_report_id'] = report_id
    mutator(plan)
    plan_path = root / 'objects' / 'research_iteration_master' / f'program_search_plan__{report_id}.json'
    ledger_path = root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{report_id}.json'
    write_json(plan_path, plan)
    write_json(ledger_path, ledger)

    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    validate_cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/validate_program_search_plan.py',
        '--report-id',
        report_id,
    ]
    validate_proc = subprocess.run(validate_cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    validation_path = root / 'objects' / 'validation' / f'program_search_plan_validation__{report_id}.json'
    validation = read_json(validation_path) if validation_path.exists() else {}
    token_blob = '\n'.join([
        validate_proc.stdout,
        validate_proc.stderr,
        json.dumps(validation, ensure_ascii=False),
    ]).lower()
    ok = validate_proc.returncode != 0 and 'forbidden' in token_blob
    return {
        'case': mutation_name,
        'report_id': report_id,
        'validate_command': validate_cmd,
        'validate_rc': validate_proc.returncode,
        'validate_stdout_tail': tail(validate_proc.stdout),
        'validate_stderr_tail': tail(validate_proc.stderr),
        'validation_path': str(validation_path),
        'validation_result': validation.get('result'),
        'token_present': 'forbidden' in token_blob,
        'ok': ok,
    }


def run_program_search_forbidden_text_smoke(root: Path, source_report_id: str) -> dict[str, Any]:
    def first_branch(plan: dict[str, Any]) -> dict[str, Any]:
        return (plan.get('branches') or [{}])[0]

    mutations = {
        'research_question': lambda plan: first_branch(plan).__setitem__('research_question', 'Should we use portfolio expression repair for this branch?'),
        'success_criteria': lambda plan: first_branch(plan).__setitem__('success_criteria', ['portfolio expression improves headline metrics']),
        'falsification_tests': lambda plan: first_branch(plan).__setitem__('falsification_tests', ['rebalance failure should be ignored']),
        'expected_outputs': lambda plan: first_branch(plan).__setitem__('expected_outputs', ['factorforge/shared clean data mutation/output.json']),
        'execution_instructions': lambda plan: first_branch(plan).__setitem__('execution_instructions', {'note': 'mutate clean data before search'}),
    }
    results = [
        validate_mutated_program_search_plan(root, source_report_id, name, mutator)
        for name, mutator in mutations.items()
    ]
    return {
        'source_report_id': source_report_id,
        'mutations': results,
        'ok': all(item['ok'] for item in results),
    }


def create_phase_f_execution_plan(root: Path, source_report_id: str, report_id: str = 'STEP6_INTEL_PHASE_F_BRANCH_EXECUTION') -> str:
    copy_iteration_for_program_search_case(root, source_report_id, report_id)
    object_specs = [
        ('factor_run_master', 'factor_run_master'),
        ('factor_case_master', 'factor_case_master'),
        ('validation', 'factor_evaluation'),
        ('factor_spec_master', 'factor_spec_master'),
        ('alpha_idea_master', 'alpha_idea_master'),
        ('handoff', 'handoff_to_step6'),
        ('research_iteration_master', 'researcher_memo'),
    ]
    for directory, prefix in object_specs:
        source = root / 'objects' / directory / f'{prefix}__{source_report_id}.json'
        target = root / 'objects' / directory / f'{prefix}__{report_id}.json'
        if source.exists() and not target.exists():
            payload = read_json(source)
            payload['report_id'] = report_id
            write_json(target, payload)
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    subprocess.run(
        [
            sys.executable,
            'skills/factor-forge-step6/scripts/build_program_search_plan.py',
            '--report-id',
            report_id,
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    return report_id


def run_tool(root: Path, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)


def add_audit_branch_to_plan(root: Path, report_id: str) -> str:
    plan_path = root / 'objects' / 'research_iteration_master' / f'program_search_plan__{report_id}.json'
    ledger_path = root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{report_id}.json'
    plan = read_json(plan_path)
    ledger = read_json(ledger_path)
    branch_id = 'audit_evidence_and_implementation'
    if not any((branch.get('branch_id') == branch_id) for branch in plan.get('branches') or [] if isinstance(branch, dict)):
        template = {
            'branch_id': branch_id,
            'parent_report_id': report_id,
            'branch_role': 'audit',
            'search_mode': 'research_audit',
            'status': 'proposed',
            'requires_human_approval_before_execution': True,
            'execution_allowed_by_default': False,
            'research_first_guardrail': 'This research audit branch remains proposed until human approval.',
            'research_question': 'Is the evidence chain clean enough before any expression search?',
            'hypothesis': 'Evidence-chain audit must pass before formula or parameter search is trusted.',
            'mechanism_target': 'evidence_integrity_and_provenance',
            'revision_hypothesis_id': None,
            'return_source_target': 'behavioral_microstructure',
            'market_structure_hypothesis': {'hypothesis': 'audit branch checks evidence quality rather than changing factor mechanics'},
            'knowledge_priors': {'anti_patterns': ['dirty evidence must block search'], 'similar_cases': ['synthetic audit branch']},
            'modification_scope': ['evidence_integrity_and_provenance'],
            'budget': {'max_trials': 1, 'max_runtime_minutes': 10, 'max_parallel_agents': 1},
            'success_criteria': ['evidence objects exist', 'handoff identities are consistent'],
            'falsification_tests': ['missing evidence blocks search', 'identity mismatch blocks search'],
            'hard_guards': ['no_portfolio_expression_repair', 'no_short_leg_adoption', 'no_decile_trading', 'no_shared_clean_data_mutation'],
            'expected_outputs': [f'factorforge/objects/research_iteration_master/search_branch_result__{report_id}__{branch_id}.json'],
            'search_policy_decision_source': {'branch_id': branch_id, 'search_mode': 'research_audit', 'branch_role': 'audit'},
        }
        plan.setdefault('branches', []).append(template)
        ledger.setdefault('branches', []).append({
            'branch_id': branch_id,
            'branch_role': 'audit',
            'search_mode': 'research_audit',
            'status': 'proposed',
            'requires_human_approval_before_execution': True,
            'execution_allowed_by_default': False,
            'last_event': 'proposed_from_phase_f_smoke',
            'result_path': f'factorforge/objects/research_iteration_master/search_branch_result__{report_id}__{branch_id}.json',
        })
    write_json(plan_path, plan)
    write_json(ledger_path, ledger)
    return branch_id


def write_bayesian_worker_inputs(root: Path, report_id: str, *, include_audit_refs: bool = False) -> dict[str, str]:
    import csv

    runs = root / 'runs' / report_id
    runs.mkdir(parents=True, exist_ok=True)
    factor_values = runs / f'factor_values__{report_id}.csv'
    daily = root / 'research_branches' / report_id / 'synthetic_daily_snapshot.csv'
    daily.parent.mkdir(parents=True, exist_ok=True)
    dates = ['2020-01-02', '2020-01-03', '2020-01-06', '2020-01-07', '2020-01-08', '2020-01-09']
    tickers = ['000001.SZ', '000002.SZ', '000003.SZ']
    with factor_values.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['ts_code', 'trade_date', 'factor_value'])
        writer.writeheader()
        for d_idx, date in enumerate(dates[:-1]):
            for t_idx, ticker in enumerate(tickers):
                writer.writerow({'ts_code': ticker, 'trade_date': date, 'factor_value': (d_idx + 1) * (t_idx + 1) / 10})
    with daily.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['ts_code', 'trade_date', 'close', 'pct_chg'])
        writer.writeheader()
        for d_idx, date in enumerate(dates):
            for t_idx, ticker in enumerate(tickers):
                close = 10 + d_idx * 0.2 + t_idx * 0.1
                writer.writerow({'ts_code': ticker, 'trade_date': date, 'close': close, 'pct_chg': 0.01 * (t_idx + 1)})
    handoff4 = {
        'report_id': report_id,
        'first_run_outputs': {'output_paths': [str(factor_values)]},
        'local_input_paths': {'daily_df_csv': str(daily)},
    }
    if include_audit_refs:
        handoff4.update({
            'data_prep_master_ref': f'data_prep_master__{report_id}.json',
            'qlib_adapter_config_ref': f'qlib_adapter_config__{report_id}.json',
            'implementation_plan_master_ref': f'implementation_plan_master__{report_id}.json',
            'factor_spec_master_ref': f'factor_spec_master__{report_id}.json',
            'factor_impl_ref': str(root / 'research_branches' / report_id / 'synthetic_factor_impl.py'),
        })
    handoff5 = {'report_id': report_id, 'handoff_status': 'synthetic_smoke'}
    write_json(root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json', handoff4)
    write_json(root / 'objects' / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff5)
    if include_audit_refs:
        eval_path = root / 'objects' / 'validation' / f'factor_evaluation__{report_id}.json'
        evaluation = read_json(eval_path)
        evaluation['evaluation_status'] = 'validated'
        evaluation['artifact_ready'] = True
        evaluation['run_status'] = 'success'
        payload_rows = []
        for backend in ['self_quant_analyzer', 'qlib_backtest']:
            payload_path = root / 'evaluations' / report_id / backend / 'evaluation_payload.json'
            write_json(payload_path, {'report_id': report_id, 'backend': backend, 'status': 'success'})
            payload_rows.append({'backend': backend, 'status': 'success', 'payload_path': str(payload_path)})
        evaluation['backend_summary'] = payload_rows
        write_json(eval_path, evaluation)
        write_json(root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json', {'report_id': report_id, 'artifact_ready': True})
        write_json(root / 'objects' / 'qlib_adapter_config' / f'qlib_adapter_config__{report_id}.json', {'report_id': report_id, 'adapter_ready': True})
        write_json(root / 'objects' / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json', {'report_id': report_id, 'implementation_mode': 'operator'})
        impl = root / 'research_branches' / report_id / 'synthetic_factor_impl.py'
        impl.parent.mkdir(parents=True, exist_ok=True)
        impl.write_text('def compute_factor(daily_df):\n    return daily_df\n', encoding='utf-8')
    return {'factor_values': str(factor_values), 'daily_snapshot': str(daily)}


def approve_branch(root: Path, report_id: str, branch_id: str, notes: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/approve_program_search_branch.py',
        '--report-id',
        report_id,
        '--branch-id',
        branch_id,
        '--decision',
        'approve',
        '--notes',
        notes,
    ]
    proc = run_tool(root, cmd)
    path = root / 'objects' / 'research_iteration_master' / f'search_branch_approval__{report_id}__{branch_id}.json'
    payload = read_json(path) if path.exists() else {}
    return {
        'command': cmd,
        'rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'path': str(path),
        'exists': path.exists(),
        'approval_status': payload.get('approval_status'),
        'canonical_write_permission': payload.get('canonical_write_permission'),
        'ok': proc.returncode == 0 and path.exists() and payload.get('approval_status') == 'approved' and payload.get('canonical_write_permission') is False,
    }


def prepare_branch(root: Path, report_id: str, branch_id: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/prepare_approved_search_branch.py',
        '--report-id',
        report_id,
        '--branch-id',
        branch_id,
    ]
    proc = run_tool(root, cmd)
    manifest = root / 'research_branches' / report_id / branch_id / 'branch_manifest.json'
    handoff = root / 'objects' / 'handoff' / f'handoff_to_step3b__{report_id}.json'
    generated = root / 'generated_code' / report_id
    payload = read_json(manifest) if manifest.exists() else {}
    return {
        'command': cmd,
        'rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'manifest_path': str(manifest),
        'manifest_exists': manifest.exists(),
        'branch_status': payload.get('branch_status'),
        'canonical_write_permission': payload.get('canonical_write_permission'),
        'handoff_to_step3b_exists': handoff.exists(),
        'generated_code_exists': generated.exists(),
        'ok': proc.returncode == 0 and manifest.exists() and payload.get('branch_status') == 'prepared' and payload.get('canonical_write_permission') is False and not handoff.exists() and not generated.exists(),
    }


def run_and_validate_branch_worker(root: Path, report_id: str, branch_id: str, worker: str, extra: list[str] | None = None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        f'skills/factor-forge-step6/scripts/{worker}',
        '--report-id',
        report_id,
        '--branch-id',
        branch_id,
    ] + list(extra or [])
    proc = run_tool(root, cmd)
    validate_cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/validate_search_branch_result.py',
        '--report-id',
        report_id,
        '--branch-id',
        branch_id,
    ]
    validate_proc = run_tool(root, validate_cmd)
    result_path = root / 'objects' / 'research_iteration_master' / f'search_branch_result__{report_id}__{branch_id}.json'
    result = read_json(result_path) if result_path.exists() else {}
    worker_output = root / 'research_branches' / report_id / branch_id / 'branch_worker_output.json'
    return {
        'command': cmd,
        'rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'validate_command': validate_cmd,
        'validate_rc': validate_proc.returncode,
        'validate_stdout_tail': tail(validate_proc.stdout),
        'validate_stderr_tail': tail(validate_proc.stderr),
        'result_path': str(result_path),
        'result_exists': result_path.exists(),
        'worker_output_exists': worker_output.exists(),
        'advisory_only': result.get('advisory_only'),
        'canonical_write_permission': result.get('canonical_write_permission'),
        'recommended_next_action': result.get('recommended_next_action'),
        'ok': proc.returncode == 0 and validate_proc.returncode == 0 and result_path.exists() and worker_output.exists() and result.get('advisory_only') is True and result.get('canonical_write_permission') is False,
    }


def run_phase_f_branch_execution_smoke(root: Path, report_id: str) -> dict[str, Any]:
    branch_id = 'exploit_cost_persistence'
    write_bayesian_worker_inputs(root, report_id)
    approval = approve_branch(root, report_id, branch_id, 'human approval for isolated phase f bayesian smoke')
    prepare = prepare_branch(root, report_id, branch_id)
    bayesian = run_and_validate_branch_worker(root, report_id, branch_id, 'run_program_search_bayesian_worker.py', ['--max-trials', '2'])

    audit_report_id = create_phase_f_execution_plan(root, report_id, 'STEP6_INTEL_PHASE_F_AUDIT_BRANCH_EXECUTION')
    write_bayesian_worker_inputs(root, audit_report_id, include_audit_refs=True)
    audit_branch_id = add_audit_branch_to_plan(root, audit_report_id)
    audit_approval = approve_branch(root, audit_report_id, audit_branch_id, 'human approval for isolated phase f audit smoke')
    audit_prepare = prepare_branch(root, audit_report_id, audit_branch_id)
    audit_worker = run_and_validate_branch_worker(root, audit_report_id, audit_branch_id, 'run_program_search_audit_worker.py')

    merge_cmd = [
        sys.executable,
        'skills/factor-forge-step6/scripts/merge_program_search_branches.py',
        '--report-id',
        report_id,
    ]
    merge_proc = run_tool(root, merge_cmd)
    merge_path = root / 'objects' / 'research_iteration_master' / f'program_search_merge__{report_id}.json'
    merge = read_json(merge_path) if merge_path.exists() else {}
    canonical_handoff = root / 'objects' / 'handoff' / f'handoff_to_step3b__{report_id}.json'
    generated_code = root / 'generated_code' / report_id
    official = root / 'objects' / 'factor_library_official' / f'factor_record__{report_id}.json'
    merge_ok = (
        merge_proc.returncode == 0
        and merge_path.exists()
        and merge.get('advisory_only') is True
        and merge.get('canonical_write_permission') is False
        and merge.get('recommended_step3b_action') in {'none', 'prepare_human_review_patch', 'rerun_audit', 'kill_factor'}
        and not canonical_handoff.exists()
        and not generated_code.exists()
        and not official.exists()
    )
    return {
        'report_id': report_id,
        'approve_proposed_branch_pass': approval,
        'prepare_approved_branch_pass': prepare,
        'bayesian_worker_advisory_result_pass': bayesian,
        'audit_worker_advisory_result_pass': {
            'report_id': audit_report_id,
            'approval': audit_approval,
            'prepare': audit_prepare,
            'worker': audit_worker,
            'ok': audit_approval['ok'] and audit_prepare['ok'] and audit_worker['ok'],
        },
        'merge_advisory_only_pass': {
            'command': merge_cmd,
            'rc': merge_proc.returncode,
            'stdout_tail': tail(merge_proc.stdout),
            'stderr_tail': tail(merge_proc.stderr),
            'merge_path': str(merge_path),
            'merge_exists': merge_path.exists(),
            'merge_status': merge.get('merge_status'),
            'advisory_only': merge.get('advisory_only'),
            'canonical_write_permission': merge.get('canonical_write_permission'),
            'handoff_to_step3b_exists': canonical_handoff.exists(),
            'generated_code_exists': generated_code.exists(),
            'official_exists': official.exists(),
            'ok': merge_ok,
        },
    }


def create_valid_bayesian_branch_chain(root: Path, source_report_id: str, report_id: str) -> dict[str, Any]:
    branch_id = 'exploit_cost_persistence'
    create_phase_f_execution_plan(root, source_report_id, report_id)
    write_bayesian_worker_inputs(root, report_id)
    approval = approve_branch(root, report_id, branch_id, f'approve valid merge-boundary setup for {report_id}')
    prepare = prepare_branch(root, report_id, branch_id)
    worker = run_and_validate_branch_worker(root, report_id, branch_id, 'run_program_search_bayesian_worker.py', ['--max-trials', '1'])
    return {
        'report_id': report_id,
        'branch_id': branch_id,
        'approval': approval,
        'prepare': prepare,
        'worker': worker,
        'valid_branch_result': approval['ok'] and prepare['ok'] and worker['ok'],
    }


def run_merge_forbidden_writeback_case(root: Path, source_report_id: str, case_name: str, injector) -> dict[str, Any]:
    safe_case_token = case_name.upper().replace('OFFICIAL', 'FORMAL')
    report_id = f'STEP6_INTEL_{safe_case_token}'
    setup = create_valid_bayesian_branch_chain(root, source_report_id, report_id)
    injected_path = injector(root, report_id)
    merge_path = root / 'objects' / 'research_iteration_master' / f'program_search_merge__{report_id}.json'
    if merge_path.exists():
        merge_path.unlink()
    diagnostic_path = root / 'objects' / 'validation' / f'program_search_merge_prewrite_block__{report_id}.json'
    if diagnostic_path.exists():
        diagnostic_path.unlink()
    merge_cmd = [sys.executable, 'skills/factor-forge-step6/scripts/merge_program_search_branches.py', '--report-id', report_id]
    merge_proc = run_tool(root, merge_cmd)
    diagnostic = read_json(diagnostic_path) if diagnostic_path.exists() else {}
    token_blob = '\n'.join([merge_proc.stdout, merge_proc.stderr, json.dumps(diagnostic, ensure_ascii=False)])
    forbidden_paths = diagnostic.get('forbidden_paths') or []
    ok = (
        setup['valid_branch_result']
        and merge_proc.returncode != 0
        and 'BLOCK_PROGRAM_SEARCH_FORBIDDEN_WRITEBACK_PRESENT' in token_blob
        and not merge_path.exists()
        and diagnostic_path.exists()
        and diagnostic.get('block_reason') == 'forbidden_writeback_present'
        and diagnostic.get('merge_written') is False
        and str(injected_path) in forbidden_paths
    )
    return {
        'report_id': report_id,
        'setup_valid_branch_result': setup['valid_branch_result'],
        'setup': setup,
        'injected_path': str(injected_path),
        'command': merge_cmd,
        'rc': merge_proc.returncode,
        'stdout_tail': tail(merge_proc.stdout),
        'stderr_tail': tail(merge_proc.stderr),
        'token_present': 'BLOCK_PROGRAM_SEARCH_FORBIDDEN_WRITEBACK_PRESENT' in token_blob,
        'merge_path': str(merge_path),
        'merge_exists': merge_path.exists(),
        'diagnostic_path': str(diagnostic_path),
        'diagnostic_exists': diagnostic_path.exists(),
        'diagnostic_forbidden_paths': forbidden_paths,
        'ok': ok,
    }


def inject_generated_code_writeback(root: Path, report_id: str) -> Path:
    path = root / 'generated_code' / report_id
    path.mkdir(parents=True, exist_ok=True)
    (path / 'fake.py').write_text('# forbidden smoke artifact\n', encoding='utf-8')
    return path


def run_phase_f_negative_smoke(root: Path, source_report_id: str) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    # 1. Approval must block missing-templates plans.
    cases['approve_missing_templates_block'] = approve_branch(
        root,
        'STEP6_INTEL_PROGRAM_SEARCH_MISSING_TEMPLATES_BLOCK',
        'exploit_cost_persistence',
        'should block because plan has no branch templates',
    )
    cases['approve_missing_templates_block']['ok'] = cases['approve_missing_templates_block']['rc'] != 0

    # 2. Approval must block no-search plans.
    none_report = 'STEP6_INTEL_VALID_PROMOTE_NO_REVISION_NEEDED'
    run_tool(root, [
        sys.executable,
        'skills/factor-forge-step6/scripts/build_program_search_plan.py',
        '--report-id',
        none_report,
    ])
    cases['approve_no_search_recommended_block'] = approve_branch(
        root,
        none_report,
        'exploit_cost_persistence',
        'should block because no search was recommended',
    )
    cases['approve_no_search_recommended_block']['ok'] = cases['approve_no_search_recommended_block']['rc'] != 0

    # 3. Prepare without approval.
    no_approval_report = 'STEP6_INTEL_PREPARE_WITHOUT_APPROVAL_BLOCK'
    copy_iteration_for_program_search_case(root, source_report_id, no_approval_report)
    src_plan = read_json(root / 'objects' / 'research_iteration_master' / f'program_search_plan__{source_report_id}.json')
    src_ledger = read_json(root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{source_report_id}.json')
    src_plan['report_id'] = no_approval_report
    src_ledger['report_id'] = no_approval_report
    write_json(root / 'objects' / 'research_iteration_master' / f'program_search_plan__{no_approval_report}.json', src_plan)
    write_json(root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{no_approval_report}.json', src_ledger)
    cases['prepare_without_approval_block'] = prepare_branch(root, no_approval_report, 'exploit_cost_persistence')
    cases['prepare_without_approval_block']['ok'] = cases['prepare_without_approval_block']['rc'] != 0

    # 4. Worker without prepare.
    no_prepare_report = 'STEP6_INTEL_WORKER_WITHOUT_PREPARE_BLOCK'
    copy_iteration_for_program_search_case(root, source_report_id, no_prepare_report)
    src_plan['report_id'] = no_prepare_report
    src_ledger['report_id'] = no_prepare_report
    write_json(root / 'objects' / 'research_iteration_master' / f'program_search_plan__{no_prepare_report}.json', src_plan)
    write_json(root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{no_prepare_report}.json', src_ledger)
    approve_branch(root, no_prepare_report, 'exploit_cost_persistence', 'approve but do not prepare')
    cases['worker_without_prepare_block'] = run_and_validate_branch_worker(root, no_prepare_report, 'exploit_cost_persistence', 'run_program_search_bayesian_worker.py', ['--max-trials', '1'])
    cases['worker_without_prepare_block']['ok'] = cases['worker_without_prepare_block']['rc'] != 0

    # 5. Wrong worker for branch.
    wrong_report = 'STEP6_INTEL_WRONG_WORKER_FOR_BRANCH_BLOCK'
    copy_iteration_for_program_search_case(root, source_report_id, wrong_report)
    wrong_plan = read_json(root / 'objects' / 'research_iteration_master' / f'program_search_plan__{source_report_id}.json')
    wrong_ledger = read_json(root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{source_report_id}.json')
    wrong_plan['report_id'] = wrong_report
    wrong_ledger['report_id'] = wrong_report
    for branch in wrong_plan.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == 'exploit_cost_persistence':
            branch['branch_role'] = 'macro'
            branch['search_mode'] = 'mechanism_challenge'
    for branch in wrong_ledger.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == 'exploit_cost_persistence':
            branch['branch_role'] = 'macro'
            branch['search_mode'] = 'mechanism_challenge'
    write_json(root / 'objects' / 'research_iteration_master' / f'program_search_plan__{wrong_report}.json', wrong_plan)
    write_json(root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{wrong_report}.json', wrong_ledger)
    approve_branch(root, wrong_report, 'exploit_cost_persistence', 'approve wrong worker negative')
    prepare_branch(root, wrong_report, 'exploit_cost_persistence')
    cases['wrong_worker_for_branch_block'] = run_and_validate_branch_worker(root, wrong_report, 'exploit_cost_persistence', 'run_program_search_bayesian_worker.py', ['--max-trials', '1'])
    cases['wrong_worker_for_branch_block']['ok'] = cases['wrong_worker_for_branch_block']['rc'] != 0

    # 6-9. Mutate a valid branch result and prove validator blocks.
    valid_result_path = root / 'objects' / 'research_iteration_master' / f'search_branch_result__{source_report_id}__exploit_cost_persistence.json'
    base = read_json(valid_result_path)
    mutations = {
        'branch_result_claims_adopted_block': lambda payload: payload.update({'researcher_summary': 'This result was adopted and applied to production.'}),
        'branch_result_canonical_write_permission_block': lambda payload: payload.update({'canonical_write_permission': True}),
        'forbidden_text_in_branch_result_block': lambda payload: payload.update({'researcher_summary': 'Use portfolio expression and short leg adoption.'}),
    }
    for name, mutator in mutations.items():
        report_id = f'STEP6_INTEL_{name.upper()}'
        branch_id = 'exploit_cost_persistence'
        copy_iteration_for_program_search_case(root, source_report_id, report_id)
        plan = read_json(root / 'objects' / 'research_iteration_master' / f'program_search_plan__{source_report_id}.json')
        ledger = read_json(root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{source_report_id}.json')
        plan['report_id'] = report_id
        ledger['report_id'] = report_id
        write_json(root / 'objects' / 'research_iteration_master' / f'program_search_plan__{report_id}.json', plan)
        write_json(root / 'objects' / 'research_iteration_master' / f'search_branch_ledger__{report_id}.json', ledger)
        approve_branch(root, report_id, branch_id, f'approve {name}')
        prepare_branch(root, report_id, branch_id)
        payload = dict(base)
        payload['report_id'] = report_id
        payload['branch_id'] = branch_id
        mutator(payload)
        result_path = root / 'objects' / 'research_iteration_master' / f'search_branch_result__{report_id}__{branch_id}.json'
        write_json(result_path, payload)
        validate_cmd = [
            sys.executable,
            'skills/factor-forge-step6/scripts/validate_search_branch_result.py',
            '--report-id',
            report_id,
            '--branch-id',
            branch_id,
        ]
        proc = run_tool(root, validate_cmd)
        cases[name] = {
            'command': validate_cmd,
            'rc': proc.returncode,
            'stdout_tail': tail(proc.stdout),
            'stderr_tail': tail(proc.stderr),
            'ok': proc.returncode != 0,
        }

    # 10-12. Merge must block forbidden canonical writebacks even when branch result provenance is valid.
    cases['merge_attempts_handoff_write_block'] = run_merge_forbidden_writeback_case(
        root,
        source_report_id,
        'merge_attempts_handoff_write_block',
        lambda root, report_id: (write_json(root / 'objects' / 'handoff' / f'handoff_to_step3b__{report_id}.json', {'illegal': 'preexisting smoke side effect'}) or (root / 'objects' / 'handoff' / f'handoff_to_step3b__{report_id}.json')),
    )
    cases['merge_attempts_generated_code_write_block'] = run_merge_forbidden_writeback_case(
        root,
        source_report_id,
        'merge_attempts_generated_code_write_block',
        inject_generated_code_writeback,
    )
    cases['merge_attempts_official_library_write_block'] = run_merge_forbidden_writeback_case(
        root,
        source_report_id,
        'merge_attempts_official_library_write_block',
        lambda root, report_id: (write_json(root / 'objects' / 'factor_library_official' / f'factor_record__{report_id}.json', {'illegal': 'preexisting smoke side effect'}) or (root / 'objects' / 'factor_library_official' / f'factor_record__{report_id}.json')),
    )
    return {'cases': cases, 'ok': all(row.get('ok') for row in cases.values())}


def validate_step6_report(root: Path, report_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    return subprocess.run(
        [sys.executable, 'skills/factor-forge-step6/scripts/validate_step6.py', '--report-id', report_id],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def run_loop_research_brief_mutation_smoke(root: Path, source_report_id: str) -> dict[str, Any]:
    iteration_path = root / 'objects' / 'research_iteration_master' / f'research_iteration_master__{source_report_id}.json'
    iteration = read_json(iteration_path)
    original_iteration = json.loads(json.dumps(iteration))
    ref = iteration.get('loop_research_brief') or {}
    json_path = Path(ref.get('json_path') or '')
    md_path = Path(ref.get('markdown_path') or '')
    original_brief = read_json(json_path)
    original_md = md_path.read_text(encoding='utf-8') if md_path.exists() else ''

    def restore() -> None:
        write_json(iteration_path, original_iteration)
        write_json(json_path, original_brief)
        if md_path:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(original_md, encoding='utf-8')

    generated_proc = validate_step6_report(root, source_report_id)
    generated_ok = (
        generated_proc.returncode == 0
        and json_path.exists()
        and md_path.exists()
        and original_brief.get('brief_version') == 'factorforge_loop_research_brief_v1'
        and 'long_short_nav_diagnostic_only' in (original_brief.get('chart_evidence') or {})
    )
    cases: dict[str, Any] = {
        'loop_research_brief_generated_pass': {
            'case': 'loop_research_brief_generated_pass',
            'report_id': source_report_id,
            'rc': generated_proc.returncode,
            'json_path': str(json_path),
            'markdown_path': str(md_path),
            'json_exists': json_path.exists(),
            'markdown_exists': md_path.exists(),
            'stdout_tail': tail(generated_proc.stdout),
            'stderr_tail': tail(generated_proc.stderr),
            'ok': generated_ok,
        }
    }

    def run_mutation(case_name: str, mutator) -> None:
        restore()
        mutated_iteration = read_json(iteration_path)
        mutated_brief = read_json(json_path)
        mutator(mutated_iteration, mutated_brief)
        write_json(iteration_path, mutated_iteration)
        write_json(json_path, mutated_brief)
        proc = validate_step6_report(root, source_report_id)
        output = proc.stdout + '\n' + proc.stderr
        if 'mechanism_consistency' in case_name:
            expected_token = 'loop_research_brief_mechanism_consistency'
        elif 'metric' in case_name or 'pearson' in case_name or 'volatility' in case_name or 'recovery' in case_name or 'group' in case_name or 'diagnostic' in case_name and 'long_short_not' not in case_name:
            expected_token = 'loop_research_brief_core_metrics_present'
        else:
            expected_token = 'loop_research_brief'
        cases[case_name] = {
            'case': case_name,
            'report_id': source_report_id,
            'rc': proc.returncode,
            'stdout_tail': tail(proc.stdout),
            'stderr_tail': tail(proc.stderr),
            'expected_token': expected_token,
            'token_present': expected_token in output or 'loop brief core metrics missing/empty' in output,
            'ok': proc.returncode != 0 and (expected_token in output or 'loop brief core metrics missing/empty' in output),
        }

    def missing_ref(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
        del brief_payload
        iteration_payload['loop_research_brief']['json_path'] = str(root / 'objects' / 'research_iteration_master' / 'missing_loop_research_brief.json')

    def missing_metric(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
        del iteration_payload
        brief_payload.setdefault('metrics', {})['rank_ic_mean'] = None

    def missing_metric_keys(*keys: str):
        def mutate(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
            del iteration_payload
            metrics = brief_payload.setdefault('metrics', {})
            for key in keys:
                metrics.pop(key, None)
        return mutate

    def blank_metric_key(key: str):
        def mutate(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
            del iteration_payload
            brief_payload.setdefault('metrics', {})[key] = ''
        return mutate

    def non_numeric_metric_key(key: str):
        def mutate(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
            del iteration_payload
            brief_payload.setdefault('metrics', {})[key] = 'not_numeric'
        return mutate

    def missing_chart_key(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
        del iteration_payload
        brief_payload.setdefault('chart_evidence', {}).pop('rank_ic_timeseries', None)

    def long_short_not_diagnostic(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
        del iteration_payload
        charts = brief_payload.setdefault('chart_evidence', {})
        value = charts.pop('long_short_nav_diagnostic_only', 'some_path.png')
        charts['long_short_nav'] = value

    def stale_mechanism_without_brief_refresh(iteration_payload: dict[str, Any], brief_payload: dict[str, Any]) -> None:
        del brief_payload
        mechanism = (
            iteration_payload
            .setdefault('research_judgment', {})
            .setdefault('research_memo', {})
            .setdefault('mechanism_analysis', {})
        )
        mechanism['factor_family'] = 'fundamental_quality'
        mechanism['return_source'] = 'information_advantage'
        mechanism['mechanism_fit'] = 'partial'
        mechanism.setdefault('mechanism_math_summary', {})['model_family'] = 'valuation_identity'
        mechanism.setdefault('mechanism_math_contract', {})['model_family'] = 'valuation_identity'

    run_mutation('loop_research_brief_missing_block', missing_ref)
    run_mutation('loop_research_brief_missing_metric_block', missing_metric)
    run_mutation('loop_research_brief_missing_pearson_ic_block', missing_metric_keys('pearson_ic_mean', 'pearson_ic_ir'))
    run_mutation('loop_research_brief_missing_volatility_block', missing_metric_keys('long_side_annual_volatility'))
    run_mutation('loop_research_brief_missing_recovery_block', missing_metric_keys('long_side_recovery_days'))
    run_mutation('loop_research_brief_missing_top_bottom_group_block', missing_metric_keys('group_top_decile_mean_return', 'group_bottom_decile_mean_return'))
    run_mutation('loop_research_brief_missing_long_short_diagnostic_block', missing_metric_keys('group_long_short_spread_mean', 'group_long_short_spread_ir'))
    run_mutation('loop_research_brief_blank_metric_block', blank_metric_key('rank_ic_ir'))
    run_mutation('loop_research_brief_non_numeric_metric_block', non_numeric_metric_key('long_side_sharpe'))
    run_mutation('loop_research_brief_missing_chart_key_block', missing_chart_key)
    run_mutation('loop_research_brief_long_short_not_diagnostic_block', long_short_not_diagnostic)
    run_mutation('loop_research_brief_mechanism_consistency_block', stale_mechanism_without_brief_refresh)

    restore()
    taxonomy_iteration = read_json(iteration_path)
    taxonomy_brief = read_json(json_path)
    mechanism = (
        taxonomy_iteration
        .setdefault('research_judgment', {})
        .setdefault('research_memo', {})
        .setdefault('mechanism_analysis', {})
    )
    mechanism['factor_family'] = 'price_volume_correlation'
    mechanism['return_source'] = 'behavioral_microstructure'
    mechanism['mechanism_fit'] = 'partial'
    mechanism_math_summary = mechanism.setdefault('mechanism_math_summary', {})
    mechanism_math_summary['model_family'] = 'price_volume_microstructure'
    mechanism_math_summary['economic_mechanism_family'] = 'transient_impact'
    mechanism_math_summary['math_tool_family'] = 'stochastic_process'
    mechanism_math_summary['model_equation_family'] = 'conditional_diffusion_with_flow_impact'
    mechanism_math_contract = mechanism.setdefault('mechanism_math_contract', {})
    mechanism_math_contract['model_family'] = 'price_volume_microstructure'
    mechanism_math_contract['economic_mechanism_family'] = 'transient_impact'
    mechanism_math_contract['math_tool_family'] = 'stochastic_process'
    mechanism_math_contract['model_equation_family'] = 'conditional_diffusion_with_flow_impact'
    mechanism.setdefault('formula_specific_derivation', {})['selected_model_family'] = 'stochastic_process'
    taxonomy_brief.setdefault('economic_interpretation', {})['factor_family'] = 'price_volume_correlation'
    taxonomy_brief['economic_interpretation']['return_source'] = 'behavioral_microstructure'
    taxonomy_brief['economic_interpretation']['mechanism_fit'] = 'partial'
    taxonomy_brief['mechanism_math_summary'] = dict(mechanism_math_summary)
    taxonomy_brief.setdefault('formula_specific_derivation', {})['selected_model_family'] = 'stochastic_process'
    write_json(iteration_path, taxonomy_iteration)
    write_json(json_path, taxonomy_brief)
    md_path.write_text(
        original_md
        + "\n\nPhase Q taxonomy: price_volume_microstructure uses stochastic_process math_tool_family and conditional_diffusion_with_flow_impact equations.\n",
        encoding='utf-8',
    )
    taxonomy_proc = validate_step6_report(root, source_report_id)
    taxonomy_output = taxonomy_proc.stdout + '\n' + taxonomy_proc.stderr
    cases['loop_research_brief_allows_math_tool_family_token'] = {
        'case': 'loop_research_brief_allows_math_tool_family_token',
        'report_id': source_report_id,
        'rc': taxonomy_proc.returncode,
        'stdout_tail': tail(taxonomy_proc.stdout),
        'stderr_tail': tail(taxonomy_proc.stderr),
        'blocked_by_markdown_consistency': (
            taxonomy_proc.returncode != 0
            and 'loop_research_brief_mechanism_markdown_consistency' in taxonomy_output
        ),
        'ok': taxonomy_proc.returncode == 0,
    }
    restore()
    return {'cases': cases, 'ok': all(row.get('ok') for row in cases.values())}


def alpha019_like_spec() -> dict[str, Any]:
    return {
        'factor_id': 'ALPHA019_LIKE_NO_VOLUME',
        'economic_hypothesis': 'winner pullback / temporary behavioral reversal after long-horizon trend state',
        'canonical_spec': {
            'formula_text': '-sign(close - delay(close, 7)) * rank(sum(returns, 250))',
            'required_inputs': ['close', 'returns'],
            'operators': ['sign', 'minus', 'delay', 'rank', 'sum'],
            'formula_ir': {
                'type': 'operator',
                'operator': 'mul',
                'args': [
                    {
                        'type': 'operator',
                        'operator': 'neg',
                        'args': [
                            {
                                'type': 'operator',
                                'operator': 'sign',
                                'args': [
                                    {
                                        'type': 'operator',
                                        'operator': 'minus',
                                        'args': [
                                            {'type': 'field', 'field': 'close'},
                                            {'type': 'operator', 'operator': 'delay', 'args': [{'type': 'field', 'field': 'close'}, {'type': 'constant', 'value': 7}]},
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        'type': 'operator',
                        'operator': 'rank',
                        'args': [
                            {
                                'type': 'operator',
                                'operator': 'sum',
                                'args': [{'type': 'field', 'field': 'returns'}, {'type': 'constant', 'value': 250}],
                            }
                        ],
                    },
                ],
            },
        },
    }


def run_formula_specific_mechanism_smoke() -> dict[str, Any]:
    spec = alpha019_like_spec()
    bad_mechanism = {
        'return_source': 'behavioral_microstructure',
        'factor_family': 'reversal',
        'mechanism_hypothesis': 'Generic price-volume dependence and volume covariance explain liquidity shock.',
        'mechanism_fit': 'weak',
    }
    polluted_mechanism = {
        'return_source': 'behavioral_microstructure',
        'factor_family': 'reversal',
        'mechanism_hypothesis': 'Generic price-volume dependence and volume liquidity explain this signal.',
        'mechanism_fit': 'weak',
        'mechanism_math_contract': {
            'observable_inputs': ['close', 'returns', 'volume'],
        },
        'mechanism_math_summary': {
            'model_family': 'price_volume_microstructure',
        },
    }
    good_mechanism = {
        'return_source': 'behavioral_microstructure',
        'factor_family': 'reversal',
        'mechanism_hypothesis': (
            'Slow winner state interacts with short-horizon pullback and temporary dislocation. '
            'The sign transform creates a threshold state boundary, discontinuity, turnover, and bucket instability risk.'
        ),
        'mechanism_fit': 'partial',
    }
    bad_derivation = build_formula_specific_derivation(spec, bad_mechanism, {})
    bad_consistency = validate_mechanism_formula_consistency(spec, bad_mechanism, bad_derivation)
    polluted_derivation = build_formula_specific_derivation(spec, polluted_mechanism, {})
    polluted_consistency = validate_mechanism_formula_consistency(spec, polluted_mechanism, polluted_derivation)
    good_derivation = build_formula_specific_derivation(spec, good_mechanism, {})
    good_consistency = validate_mechanism_formula_consistency(spec, good_mechanism, good_derivation)
    good_derivation_failures = validate_formula_specific_derivation(good_derivation, spec, good_mechanism)
    restated = dict(good_derivation)
    restated['process_or_distribution'] = 'rank sum returns delay close sign formula'
    restated_failures = validate_formula_specific_derivation(restated, spec, good_mechanism)
    generic_payer = dict(good_derivation)
    generic_payer['profit_payer_derivation'] = {
        'payer_or_counterparty': 'the counterparty implied by the economic hypothesis',
        'why_they_pay': 'they pay only if constrained behavior, delayed information diffusion, risk transfer, or liquidity demand creates a repeatable state',
        'mechanism_generating_profit': 'expected payoff arises only if the formula estimates the state that causes that payer behavior or constraint',
        'expected_payoff_expression_or_argument': 'E[r_{t+1:t+h} | F_t, estimated_state_t] must be monotone in the declared direction after costs.',
    }
    generic_payer_failures = validate_formula_specific_derivation(generic_payer, spec, good_mechanism)
    alpha033_like_spec = {
        'canonical_spec': {
            'formula_text': 'rank(negate(signedpower(minus(1, divide(open, close)), 1)))',
            'required_inputs': ['open', 'close'],
            'operators': ['rank', 'negate', 'signedpower', 'minus', 'divide'],
        }
    }
    alpha033_like_mechanism = {
        'return_source': 'behavioral_microstructure',
        'factor_family': 'liquidity_shock',
        'mechanism_hypothesis': 'Open/close price-location state tests overnight-to-intraday pressure and close-location reversal after costs.',
        'mechanism_fit': 'weak',
    }
    alpha033_derivation = build_formula_specific_derivation(alpha033_like_spec, alpha033_like_mechanism, {})
    alpha033_failures = validate_formula_specific_derivation(alpha033_derivation, alpha033_like_spec, alpha033_like_mechanism)
    alpha033_text = json.dumps(alpha033_derivation, ensure_ascii=False).lower()
    alpha033_stale_mechanism = {
        'return_source': 'behavioral_microstructure',
        'factor_family': 'liquidity_shock',
        'mechanism_hypothesis': 'Legacy deterministic text says price-volume liquidity shock and volume participation.',
        'mechanism_fit': 'weak',
        'mechanism_math_contract': {
            'observable_inputs': ['open', 'close', 'volume'],
            'factor_as_estimator': 'stale price-volume dependence estimator text',
        },
    }
    alpha033_stale_no_takeover = validate_mechanism_formula_consistency(
        alpha033_like_spec,
        alpha033_stale_mechanism,
        alpha033_derivation,
    )
    alpha033_takeover_mechanism = dict(alpha033_stale_mechanism)
    alpha033_takeover_mechanism['main_agent_mechanism_memo_takeover'] = {
        'enabled': True,
        'validation_scope': 'main_agent_formula_specific_derivation',
        'legacy_deterministic_mechanism_retained_for_audit': {
            'mechanism_hypothesis': 'Legacy audit snapshot still says price-volume liquidity shock.',
            'mechanism_math_summary': {
                'factor_as_estimator': 'stale volume participation estimator retained for audit only',
            },
        },
    }
    alpha033_stale_with_takeover = validate_mechanism_formula_consistency(
        alpha033_like_spec,
        alpha033_takeover_mechanism,
        alpha033_derivation,
    )
    hypothesis_specs = [
        (
            'valuation',
            {'economic_hypothesis': 'earnings growth cash flow valuation risk premium', 'canonical_spec': {'formula_text': 'rank(earnings_growth)', 'required_inputs': ['earnings_growth'], 'operators': ['rank']}},
            'valuation_identity',
        ),
        (
            'information',
            {'economic_hypothesis': 'information advantage delayed diffusion and attention constraint', 'canonical_spec': {'formula_text': 'rank(delta(close, 5))', 'required_inputs': ['close'], 'operators': ['rank', 'delta']}},
            'state_space',
        ),
        (
            'market_structure',
            {'economic_hypothesis': 'liquidity impact order imbalance inventory constraint', 'canonical_spec': {'formula_text': 'rank(volume / close)', 'required_inputs': ['volume', 'close'], 'operators': ['rank', 'div']}},
            'transient_impact',
        ),
    ]
    model_cases = []
    for name, case_spec, expected_family in hypothesis_specs:
        derivation = build_formula_specific_derivation(case_spec, {'mechanism_hypothesis': case_spec['economic_hypothesis']}, {})
        failures = validate_formula_specific_derivation(derivation, case_spec, {'mechanism_hypothesis': case_spec['economic_hypothesis']})
        model_cases.append({
            'case': name,
            'expected_family': expected_family,
            'actual_family': derivation.get('selected_model_family'),
            'failures': failures,
            'ok': derivation.get('selected_model_family') == expected_family and not failures,
        })
    bad_codes = {item.get('code') for item in bad_consistency.get('failures') or []}
    polluted_codes = {item.get('code') for item in polluted_consistency.get('failures') or []}
    restated_codes = {item.get('code') for item in restated_failures}
    generic_payer_codes = {item.get('code') for item in generic_payer_failures}
    model_specific_pass = [
        row for row in model_cases
        if row['case'] in {'valuation', 'information', 'market_structure'} and row['ok']
    ]
    return {
        'alpha019_price_volume_contradiction_block': {
            'ok': 'BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION' in bad_codes,
            'consistency': bad_consistency,
        },
        'alpha019_polluted_mechanism_observable_volume_still_blocks': {
            'ok': (
                'BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION' in polluted_codes
                and polluted_consistency.get('features', {}).get('has_volume') is False
                and 'volume' in (polluted_consistency.get('mechanism_inputs_not_in_formula') or [])
            ),
            'consistency': polluted_consistency,
        },
        'alpha019_formula_specific_valid_pass': {
            'ok': good_consistency.get('status') == 'PASS' and not good_derivation_failures,
            'consistency': good_consistency,
            'derivation_failures': good_derivation_failures,
            'selected_model_family': good_derivation.get('selected_model_family'),
            'profit_payer_derivation': good_derivation.get('profit_payer_derivation'),
        },
        'process_or_distribution_not_formula_restatement': {
            'ok': 'BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING' in restated_codes,
            'failures': restated_failures,
        },
        'generic_profit_payer_derivation_blocks': {
            'ok': 'BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC' in generic_payer_codes,
            'failures': generic_payer_failures,
        },
        'alpha033_open_close_formula_specific_valid_pass': {
            'ok': (
                not alpha033_failures
                and alpha033_derivation.get('selected_model_family') == 'stochastic_process'
                and 'open/close' in alpha033_text
                and 'investors' not in alpha033_text
                and 'volume participation gate' not in alpha033_text
                and 'signed price state' not in alpha033_text
            ),
            'selected_model_family': alpha033_derivation.get('selected_model_family'),
            'failures': alpha033_failures,
            'profit_payer_derivation': alpha033_derivation.get('profit_payer_derivation'),
        },
        'alpha033_main_agent_memo_takeover_ignores_stale_legacy_mechanism_text': {
            'ok': (
                alpha033_stale_no_takeover.get('status') == 'BLOCK'
                and alpha033_stale_with_takeover.get('status') == 'PASS'
                and not alpha033_stale_with_takeover.get('failures')
            ),
            'without_takeover': alpha033_stale_no_takeover,
            'with_takeover': alpha033_stale_with_takeover,
        },
        'model_specific_profit_payer_derivation_pass': {
            'ok': len(model_specific_pass) == 3,
            'cases': model_specific_pass,
        },
        'economic_hypothesis_model_selection_cases': model_cases,
        'ok': (
            'BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION' in bad_codes
            and 'BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION' in polluted_codes
            and polluted_consistency.get('features', {}).get('has_volume') is False
            and 'volume' in (polluted_consistency.get('mechanism_inputs_not_in_formula') or [])
            and good_consistency.get('status') == 'PASS'
            and not good_derivation_failures
            and not alpha033_failures
            and alpha033_stale_no_takeover.get('status') == 'BLOCK'
            and alpha033_stale_with_takeover.get('status') == 'PASS'
            and 'BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING' in restated_codes
            and 'BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC' in generic_payer_codes
            and len(model_specific_pass) == 3
            and all(item['ok'] for item in model_cases)
            and len({item['actual_family'] for item in model_cases}) >= 3
        ),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Synthetic Step6 research intelligence smoke; never uses clean data.')
    ap.add_argument('--root', default=None, help='Must be under /tmp. Default creates /tmp/factorforge_step6_intelligence_<timestamp>.')
    ap.add_argument('--fresh', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root or (Path('/tmp') / f'factorforge_step6_intelligence_{datetime.now().strftime("%Y%m%d_%H%M%S")}')).expanduser()
    resolved = str(root.resolve())
    if not (resolved.startswith('/tmp/') or resolved.startswith('/private/tmp/')):
        raise SystemExit(f'BLOCK_NON_TMP_FACTORFORGE_ROOT: {root}')
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = snapshot_repo_canonical()
    cases = [
        ('valid_supportive_evidence', 'price_volume_correlation', 'PASS', 'price_volume_correlation', 'SMOKE_PRICE_VOLUME'),
        ('loop_research_brief_generated_pass', 'price_volume_correlation', 'PASS', 'loop_research_brief', 'SMOKE_PRICE_VOLUME'),
        ('price_volume_correlation_mechanism', 'price_volume_correlation', 'NO_OFFICIAL', 'price_volume_correlation', 'ALPHA013_LIKE'),
        ('all_backends_skipped', 'all_backends_skipped', 'BLOCK', 'evidence_audit_evidence_verdict_blocked', 'SMOKE_PRICE_VOLUME'),
        ('missing_long_side_metrics', 'missing_long_side_metrics', 'BLOCK', 'evidence_audit_evidence_verdict_blocked', 'SMOKE_PRICE_VOLUME'),
        ('short_side_dominance', 'short_side_dominance', 'NO_PROMOTE', 'short_side_dominance_suspected', 'SMOKE_PRICE_VOLUME'),
        ('long_side_negative_revision', 'long_side_negative', 'NO_PROMOTE', 'rev_direction_state_001', 'SMOKE_PRICE_VOLUME'),
        ('non_monotonic_revision', 'non_monotonic', 'NO_PROMOTE', 'rev_monotonic_state_001', 'SMOKE_PRICE_VOLUME'),
        ('high_turnover_cost', 'high_turnover_cost', 'NO_PROMOTE', 'cogs_destroy_alpha', 'SMOKE_PRICE_VOLUME'),
        ('high_turnover_revision', 'high_turnover_cost', 'NO_PROMOTE', 'rev_cost_persistence_001', 'SMOKE_PRICE_VOLUME'),
        ('iterate_requires_expression_revision', 'high_turnover_cost', 'NO_PROMOTE', 'no_portfolio_expression_repair', 'SMOKE_PRICE_VOLUME'),
        ('unknown_mechanism_cannot_promote', 'unknown_mechanism', 'BLOCK', 'mechanism_return_source_known', 'SMOKE_UNKNOWN'),
        ('mechanism_unclear_revision', 'unknown_mechanism_iterate', 'NO_OFFICIAL', 'rev_mechanism_challenge_001', 'SMOKE_UNKNOWN'),
        ('main_agent_memo_missing_pauses_before_handoff', 'open_close_intraday_position', 'PAUSE', 'AWAITING_MAIN_AGENT_MECHANISM_MEMO', 'SMOKE_OPEN_CLOSE_POSITION', 'missing'),
        ('open_close_intraday_position_revision', 'open_close_intraday_position', 'NO_PROMOTE', 'open_close_position_state', 'SMOKE_OPEN_CLOSE_POSITION'),
        ('similar_failure_imported', 'short_side_dominance', 'NO_PROMOTE', 'Retrieved failure lesson', 'SMOKE_PRICE_VOLUME'),
        ('similar_success_rejected_condition_mismatch', 'high_turnover_cost', 'NO_PROMOTE', 'turnover/cost', 'SMOKE_PRICE_VOLUME'),
        ('alpha013_like_advisory_mechanism_challenge_branch', 'alpha013_cost_contradiction', 'NO_PROMOTE', 'challenge_mechanism_cost_contradiction', 'ALPHA013_LIKE_ADVISORY'),
        ('cold_start_knowledge_gap', 'price_volume_correlation', 'NO_OFFICIAL', 'future retrieval anchor', 'SMOKE_COLD_START'),
        ('same_factor_cross_identity_negative', 'price_volume_correlation', 'BLOCK', 'same_factor_identity_mismatch', 'SMOKE_PRICE_VOLUME'),
        ('valid_promote_no_revision_needed', 'strong_mechanism_support', 'PROMOTE', 'strong_mechanism_support', 'SMOKE_PROMOTE'),
    ]
    results = [run_case(root, *case) for case in cases]
    program_search_plan_smoke = run_program_search_plan_smoke(root, 'STEP6_INTEL_HIGH_TURNOVER_REVISION')
    program_search_missing_templates_smoke = run_program_search_missing_templates_smoke(root, 'STEP6_INTEL_HIGH_TURNOVER_REVISION')
    program_search_forbidden_text_smoke = run_program_search_forbidden_text_smoke(root, 'STEP6_INTEL_HIGH_TURNOVER_REVISION')
    phase_f_report_id = create_phase_f_execution_plan(root, 'STEP6_INTEL_HIGH_TURNOVER_REVISION')
    phase_f_branch_execution_smoke = run_phase_f_branch_execution_smoke(root, phase_f_report_id)
    phase_f_negative_smoke = run_phase_f_negative_smoke(root, phase_f_report_id)
    loop_research_brief_smoke = run_loop_research_brief_mutation_smoke(root, 'STEP6_INTEL_LOOP_RESEARCH_BRIEF_GENERATED_PASS')
    formula_specific_mechanism_smoke = run_formula_specific_mechanism_smoke()
    pollution = canonical_pollution(before)
    verdict = 'ACCEPT' if (
        all(item['ok'] for item in results)
        and program_search_plan_smoke['ok']
        and program_search_missing_templates_smoke['ok']
        and program_search_forbidden_text_smoke['ok']
        and phase_f_branch_execution_smoke['approve_proposed_branch_pass']['ok']
        and phase_f_branch_execution_smoke['prepare_approved_branch_pass']['ok']
        and phase_f_branch_execution_smoke['bayesian_worker_advisory_result_pass']['ok']
        and phase_f_branch_execution_smoke['audit_worker_advisory_result_pass']['ok']
        and phase_f_branch_execution_smoke['merge_advisory_only_pass']['ok']
        and phase_f_negative_smoke['ok']
        and loop_research_brief_smoke['ok']
        and formula_specific_mechanism_smoke['ok']
        and not pollution['polluted']
    ) else 'BLOCK'
    summary = {
        'contract_version': 'factorforge_step6_intelligence_smoke_v1',
        'created_at_utc': utc_now(),
        'factorforge_root': str(root),
        'root_is_tmp': True,
        'cases': results,
        'program_search_plan_smoke': program_search_plan_smoke,
        'program_search_missing_templates_smoke': program_search_missing_templates_smoke,
        'program_search_forbidden_text_smoke': program_search_forbidden_text_smoke,
        'phase_f_report_id': phase_f_report_id,
        'phase_f_branch_execution_smoke': phase_f_branch_execution_smoke,
        'phase_f_negative_smoke': phase_f_negative_smoke,
        'loop_research_brief_smoke': loop_research_brief_smoke,
        'formula_specific_mechanism_smoke': formula_specific_mechanism_smoke,
        'canonical_pollution': pollution,
        'verdict': verdict,
        'notes': [
            'Synthetic /tmp-only smoke.',
            'No real factor research was run.',
            'No clean data was read or processed.',
        ],
    }
    summary_path = root / 'step6_intelligence_smoke_summary.json'
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'[SUMMARY] {summary_path}')
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
