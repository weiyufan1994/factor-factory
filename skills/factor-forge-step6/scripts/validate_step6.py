#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FF) not in sys.path:
    sys.path.append(str(FF))

from skills.factor_forge_step5.modules.io import load_json  # type: ignore
from factor_factory.artifact_identity import assert_identity_matches_strict
from factor_factory.mechanism_math.formula_specific import (
    validate_formula_specific_derivation,
    validate_mechanism_formula_consistency,
)
from factor_factory.mechanism_math.main_agent_memo import validate_main_agent_mechanism_memo
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract, validate_mechanism_math_contract_v2
from factor_factory.measurement_program import validate_measurement_program
from factor_factory.revision_council.guards import FORBIDDEN_TEXT_TOKEN, FORBIDDEN_PATTERNS
from factor_factory.revision_council.validator import validate_revision_council_proposal
from factor_factory.research_conjecture import (
    research_protocol_paths,
    validate_protocol_bundle,
)
from factor_factory.research_proof import validate_factor_proof_certificate
from validate_agentic_council_result import (
    expected_manifest_task,
    validate_agentic_result,
)

OBJ = FF / 'objects'
VALID_DECISIONS = {'promote_official', 'iterate', 'reject', 'needs_human_review'}
VALID_METRIC_VERDICTS = {'supportive', 'mixed', 'negative', 'inconclusive'}
VALID_EVIDENCE_VERDICTS = {'usable', 'usable_with_warnings', 'blocked'}
VALID_RETURN_SOURCES = {
    'risk_premium',
    'information_advantage',
    'constraint_driven_arbitrage',
    'behavioral_microstructure',
    'mixed',
    'unknown',
}
VALID_FACTOR_FAMILIES = {
    'price_volume_correlation',
    'reversal',
    'momentum_confirmation',
    'liquidity_shock',
    'volatility',
    'fundamental_quality',
    'event_constraint',
    'other',
}
VALID_MECHANISM_FITS = {'strong', 'partial', 'weak', 'contradicted'}
VALID_CLASSIFICATION_UNCERTAINTY = {'low', 'medium', 'high'}
VALID_PRIMARY_FAILURE_SIGNATURES = {
    'cost_too_high',
    'long_side_negative',
    'non_monotonic',
    'unstable_regime',
    'implementation_suspect',
    'mechanism_unclear',
    'same_factor_identity_mismatch',
    'none',
}
VALID_IMPLEMENTATION_MODE_PREFERENCES = {'operator', 'hybrid', 'direct_code', 'unknown'}
VALID_OVERFIT_RISKS = {'low', 'medium', 'high', 'unknown'}
VALID_REVISION_QUALITIES = {'actionable', 'weak', 'blocked', 'not_needed'}
VALID_LOOP_AUTHORIZATIONS = {'approved_for_step3b_handoff', 'advisory_only', 'blocked'}
REQUIRED_REVISION_FORBIDDEN_CHANGES = {
    'no_portfolio_expression_repair',
    'no_short_leg_adoption',
    'no_decile_trading',
    'no_shared_clean_data_mutation',
}
FORBIDDEN_EXPRESSION_REPAIR_TERMS = [
    'portfolio',
    'rebalance',
    'short leg',
    'short-leg',
    'long-short',
    'decile trading',
    'buy q1/sell q10',
    'buy q10/sell q1',
]
VALID_SEARCH_POLICY_MODES = {
    'audit',
    'bayesian_exploit',
    'genetic_explore',
    'mechanism_challenge',
    'multi_agent_parallel',
    'kill',
    'none',
}
VALID_STEP6_EVIDENCE_STATUS_VERSION = 'factorforge_step6_evidence_status_v1'
VALID_STEP6_Q_LIB_NATIVE_STATUS = {
    'not_applicable',
    'not_attempted',
    'preflight_blocked',
    'preflight_ready',
    'partial_payload',
    'native_minimal_success',
    'native_backtest_success',
    'failed',
}
REQUIRED_FORBIDDEN_SEARCH = {
    'no_portfolio_expression_repair',
    'no_short_leg_adoption',
    'no_decile_trading',
    'no_shared_clean_data_mutation',
}
REQUIRED_SEARCH_METHODS = {
    'genetic_algorithm',
    'bayesian_search',
    'reinforcement_learning',
    'multi_agent_parallel_exploration',
}
LOOP_RESEARCH_BRIEF_VERSION = 'factorforge_loop_research_brief_v1'
REQUIRED_LOOP_BRIEF_SECTIONS = {
    'decision_snapshot',
    'economic_interpretation',
    'metrics',
    'chart_evidence',
    'metric_analysis',
    'knowledge_comparison',
    'next_research_direction',
    'final_loop_conclusion',
    'mechanism_math_summary',
}
REQUIRED_LOOP_BRIEF_CHART_KEYS = {
    'rank_ic_timeseries',
    'pearson_ic_timeseries',
    'long_side_nav',
    'cost_adjusted_long_side_nav',
    'quantile_nav',
    'long_short_nav_diagnostic_only',
    'coverage_by_day',
}
CORE_LOOP_BRIEF_METRICS = {
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
}
SPECIFIED_MECHANISM_MATH_SUMMARY_FIELDS = {
    'model_family',
    'mathematical_object',
    'state_or_object',
    'factor_as_estimator',
    'target_functional',
    'observation_map',
    'identification_assumptions',
    'market_outcome_projection',
    'relationship_shape',
    'expected_metric_signature',
    'metric_signature_match',
    'mechanism_falsification_tests',
    'revision_operator_summary',
}
REVISION_MATH_OBJECTS = {
    'estimator_kernel',
    'lag_window',
    'state_variable',
    'projection_operator',
    'smoothing_regularization',
    'stopping_rule',
    'threshold_boundary',
    'model_family_challenge',
}
VALID_FINAL_REVISION_SOURCES = {'revision_council', 'deterministic_fallback', 'none'}
VALID_MODEL_LAYER_TARGETS = {
    'economic_hypothesis',
    'primary_mechanism_model',
    'market_outcome_projection',
    'stochastic_projection',
    'observable_estimator',
    'implementation_contract',
    'none',
}
REQUIRED_MODEL_LINKAGE_KEYS = {
    'economic_hypothesis',
    'primary_mechanism_model',
    'market_outcome_projection',
    'observable_estimator',
}
IMPLEMENTATION_MODEL_LINKAGE_KEYS = {
    'implementation_contract',
    'implementation_data_contract',
}
PLACEHOLDER_MODEL_LINKAGE_VALUES = {'', 'unknown', 'under_specified', 'n/a', 'none', 'todo', 'tbd'}
REQUIRED_RESEARCH_EQUATION_METRIC_LINKS = {
    'rank_ic',
    'long_side_return',
    'cost_adjusted_return',
    'turnover',
    'volatility_drag',
    'max_drawdown',
    'recovery_days',
}
VALID_RESEARCH_EQUATION_SUPPORT = {'supported', 'challenged', 'under_specified'}
VALID_FAILED_EQUATION_COMPONENTS = {
    'none',
    'assumptions',
    'math_tool_selection',
    'primary_math_mechanism',
    'mathematical_object',
    'latent_state',
    'observable_estimator',
    'price_process_projection',
    'market_outcome_projection',
    'applicable_audit',
    'implementation_contract',
    'trading_cost',
    'drawdown_geometry',
}
GENERIC_RESEARCH_EQUATION_METRIC_TEXT = {
    'metrics support the model',
    'metrics support mechanism',
    'supported by metrics',
    'good',
    'ok',
}
COUNCIL_FORBIDDEN_SKIP_KEYS = {
    'hard_guards',
    'forbidden_search',
    'forbidden_changes',
    'forbidden_changes_ack',
    'why_not_portfolio_fix',
    'why_no_automatic_step3b_handoff',
}


def check(name: str, condition: bool, error: str | None = None, severity: str = 'BLOCK'):
    status = 'PASS' if condition else severity
    return {
        'name': name,
        'ok': bool(condition),
        'status': status,
        'severity': severity,
        'error': None if condition else error,
    }


def validate_evidence_status_contract(status: dict[str, Any] | None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if not isinstance(status, dict) or not status:
        return [check('evidence_status_present', False, 'BLOCK_STEP6_EVIDENCE_STATUS_MISSING: evidence_status missing')]
    checks.extend([
        check('evidence_status_version', status.get('version') == VALID_STEP6_EVIDENCE_STATUS_VERSION, 'BLOCK_STEP6_EVIDENCE_STATUS_MISSING: invalid evidence_status.version'),
        check('evidence_status_wrapper_status', status.get('wrapper_validation_status') in {'PASS', 'BLOCK', 'FAILED'}, 'BLOCK_STEP6_EVIDENCE_STATUS_WRAPPER_MISSING: wrapper_validation_status missing'),
        check('evidence_status_self_quant', status.get('self_quant_evidence_status') in {'complete', 'partial', 'missing', 'failed'}, 'BLOCK_STEP6_EVIDENCE_STATUS_SELF_QUANT_MISSING: self_quant_evidence_status missing'),
        check('evidence_status_qlib', status.get('qlib_native_status') in VALID_STEP6_Q_LIB_NATIVE_STATUS, 'BLOCK_STEP6_EVIDENCE_STATUS_QLIB_MISSING: qlib_native_status missing'),
        check('evidence_status_long_side', status.get('long_side_evidence_status') in {'complete', 'partial', 'missing', 'failed'}, 'BLOCK_STEP6_EVIDENCE_STATUS_LONG_SIDE_MISSING: long_side_evidence_status missing'),
        check('evidence_status_cost', status.get('cost_model_status') in {'complete', 'partial', 'missing'}, 'BLOCK_STEP6_EVIDENCE_STATUS_COST_MISSING: cost_model_status missing'),
        check('evidence_status_drawdown', status.get('drawdown_geometry_status') in {'complete', 'partial', 'missing'}, 'BLOCK_STEP6_EVIDENCE_STATUS_DRAWDOWN_MISSING: drawdown_geometry_status missing'),
        check('evidence_status_research_decision', status.get('research_decision') in {'promote', 'iterate', 'reject', 'needs_human_review'}, 'BLOCK_STEP6_EVIDENCE_STATUS_RESEARCH_DECISION_MISSING: research_decision missing'),
        check('evidence_status_promotion_gate', status.get('promotion_gate_status') in {'open', 'blocked_by_long_side', 'blocked_by_cost', 'blocked_by_drawdown', 'blocked_by_evidence', 'not_applicable'}, 'BLOCK_STEP6_EVIDENCE_STATUS_PROMOTION_GATE_MISSING: promotion_gate_status missing'),
    ])
    if status.get('run_status') == 'partial' or status.get('status') == 'partial':
        checks.append(check('evidence_status_no_generic_partial', False, 'BLOCK_STEP6_EVIDENCE_STATUS_GENERIC_PARTIAL: do not use generic partial without naming layer'))
    return checks


def nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def normalized_words(value: Any) -> str:
    return ' '.join(re.findall(r'[a-zA-Z0-9_]+|[\u4e00-\u9fff]+', str(value or '').lower()))


def generic_research_equation_metric_text(value: Any) -> bool:
    normalized = normalized_words(value)
    if normalized in GENERIC_RESEARCH_EQUATION_METRIC_TEXT:
        return True
    generic_phrases = [
        'metrics support the model',
        'metrics support mechanism',
        'supported by metrics',
        'metrics improve',
        'test metrics',
    ]
    return any(phrase in normalized for phrase in generic_phrases)


def nonempty_list(value) -> bool:
    return isinstance(value, list) and bool(value)


def list_value(value) -> bool:
    return isinstance(value, list)


def nested_dict(root: dict, *keys: str) -> dict:
    cur = root
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, dict) else {}


def has_key_recursive(value, target: str) -> bool:
    if isinstance(value, dict):
        if target in value:
            return True
        return any(has_key_recursive(item, target) for item in value.values())
    if isinstance(value, list):
        return any(has_key_recursive(item, target) for item in value)
    return False


def empty_string_paths(value, prefix: str = '$') -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            paths.extend(empty_string_paths(child, f'{prefix}.{key}'))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            paths.extend(empty_string_paths(child, f'{prefix}[{idx}]'))
    elif isinstance(value, str) and not value.strip():
        paths.append(prefix)
    return paths


def resolve_artifact_path(value: str | None) -> Path:
    if not value:
        return FF / '__missing_artifact_path__'
    path = Path(value)
    if path.is_absolute():
        return path
    return FF / path


def present_metric(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text.startswith('missing:'):
            return False
        try:
            float(text)
            return True
        except Exception:
            return False
    try:
        float(value)
        return True
    except Exception:
        return False


def scan_forbidden_revision_text(value, prefix: str = '$') -> list[dict]:
    findings: list[dict] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in COUNCIL_FORBIDDEN_SKIP_KEYS:
                continue
            findings.extend(scan_forbidden_revision_text(child, f'{prefix}.{key}'))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            findings.extend(scan_forbidden_revision_text(child, f'{prefix}[{idx}]'))
    elif isinstance(value, str):
        normalized = ' '.join(value.lower().split())
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in normalized:
                findings.append({'path': prefix, 'pattern': pattern})
    return findings


def validate_step6_model_linkage(mechanism_analysis: dict, revision_strategy: dict | None = None) -> list[str]:
    revision_strategy = revision_strategy or {}
    failures: list[str] = []
    model_layer_failure_attribution = mechanism_analysis.get('model_layer_failure_attribution')
    revision_model_target = mechanism_analysis.get('revision_model_target')
    projection_diagnosis = mechanism_analysis.get('mechanism_projection_diagnosis')
    metric_signature_match = mechanism_analysis.get('metric_signature_match')
    def has_required_model_linkage_keys(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        keys = set(value.keys())
        return REQUIRED_MODEL_LINKAGE_KEYS.issubset(keys) and bool(keys & IMPLEMENTATION_MODEL_LINKAGE_KEYS)

    projection_keys_ok = has_required_model_linkage_keys(projection_diagnosis)
    metric_keys_ok = has_required_model_linkage_keys(metric_signature_match)

    def meaningful_model_link_values(value: Any) -> bool:
        if not isinstance(value, dict) or not value:
            return False
        for item in value.values():
            if isinstance(item, str) and item.strip().lower() in PLACEHOLDER_MODEL_LINKAGE_VALUES:
                return False
            if item in (None, {}, []):
                return False
        return True

    metrics_linked_to_model = (
        projection_keys_ok
        and metric_keys_ok
        and meaningful_model_link_values(projection_diagnosis)
        and meaningful_model_link_values(metric_signature_match)
        and isinstance(model_layer_failure_attribution, list)
        and bool(model_layer_failure_attribution)
        and all(str(item) in VALID_MODEL_LAYER_TARGETS for item in model_layer_failure_attribution)
        and revision_model_target in VALID_MODEL_LAYER_TARGETS - {'none'}
    )
    if not metrics_linked_to_model:
        failures.append('BLOCK_STEP6_METRICS_NOT_LINKED_TO_MODEL')
    revision_hypotheses = revision_strategy.get('revision_hypotheses') or []
    if revision_hypotheses and not all(isinstance(item, dict) and item.get('revision_model_layer') in VALID_MODEL_LAYER_TARGETS - {'none'} for item in revision_hypotheses):
        failures.append('BLOCK_COUNCIL_REVISION_MODEL_LAYER_MISSING')

    research_equation_review = mechanism_analysis.get('research_equation_review')
    mechanism_math_contract_v2 = mechanism_analysis.get('mechanism_math_contract_v2') if isinstance(mechanism_analysis.get('mechanism_math_contract_v2'), dict) else {}
    research_equation = mechanism_math_contract_v2.get('research_equation') if isinstance(mechanism_math_contract_v2.get('research_equation'), dict) else {}
    expected_equation_status = research_equation.get('equation_status')
    if not isinstance(research_equation_review, dict):
        failures.append('BLOCK_STEP6_RESEARCH_EQUATION_NOT_LINKED_TO_METRICS')
    else:
        metric_links = research_equation_review.get('metric_links')
        metric_link_values_ok = isinstance(metric_links, dict) and REQUIRED_RESEARCH_EQUATION_METRIC_LINKS.issubset(set(metric_links.keys()))
        if metric_link_values_ok:
            for key in REQUIRED_RESEARCH_EQUATION_METRIC_LINKS:
                value = metric_links.get(key)
                normalized = str(value or '').strip().lower()
                if (
                    not nonempty_str(value)
                    or normalized in PLACEHOLDER_MODEL_LINKAGE_VALUES
                    or generic_research_equation_metric_text(value)
                ):
                    metric_link_values_ok = False
                    break
        review_ok = (
            research_equation_review.get('reviewer_task') == 'research_equation_reviewer'
            and research_equation_review.get('equation_supported_by_metrics') in VALID_RESEARCH_EQUATION_SUPPORT
            and research_equation_review.get('failed_equation_component') in VALID_FAILED_EQUATION_COMPONENTS
            and nonempty_str(research_equation_review.get('revision_implication'))
            and metric_link_values_ok
        )
        if expected_equation_status:
            review_ok = review_ok and research_equation_review.get('equation_status') == expected_equation_status
        if not review_ok:
            failures.append('BLOCK_STEP6_RESEARCH_EQUATION_NOT_LINKED_TO_METRICS')
    return failures


def proposal_by_id(report_id: str, proposal_id: str) -> tuple[Path | None, dict | None]:
    council_dir = OBJ / 'research_iteration_master' / 'revision_council' / report_id
    for path in sorted(council_dir.glob(f'proposal__{report_id}__*.json')):
        try:
            proposal = load_json(path)
        except Exception:
            continue
        if proposal.get('proposal_id') == proposal_id:
            return path, proposal
    for path in sorted((council_dir / 'agent_results').glob(f'agent_result__{report_id}__*.json')):
        try:
            result = load_json(path)
        except Exception:
            continue
        if result.get('task_id') == proposal_id:
            return path, result
    return None, None


def loop_research_brief_checks(iteration: dict, decision: str) -> list[dict]:
    checks: list[dict] = []
    ref = iteration.get('loop_research_brief') or {}
    checks.append(check('loop_research_brief_ref_present', isinstance(ref, dict) and bool(ref), 'loop_research_brief reference missing'))
    if not isinstance(ref, dict) or not ref:
        return checks

    md_path = resolve_artifact_path(ref.get('markdown_path'))
    json_path = resolve_artifact_path(ref.get('json_path'))
    checks.append(check('loop_research_brief_markdown_exists', md_path.exists(), f'missing loop research brief markdown: {md_path}'))
    checks.append(check('loop_research_brief_json_exists', json_path.exists(), f'missing loop research brief json: {json_path}'))
    checks.append(check('loop_research_brief_ref_version', ref.get('brief_version') == LOOP_RESEARCH_BRIEF_VERSION, f'invalid loop brief ref version: {ref.get("brief_version")}'))
    checks.append(check('loop_research_brief_ref_iteration_no', ref.get('iteration_no') == iteration.get('iteration_no'), 'loop brief iteration_no must match research_iteration_master'))
    if not json_path.exists():
        return checks

    try:
        brief = load_json(json_path)
    except Exception as exc:
        checks.append(check('loop_research_brief_json_loadable', False, f'failed to load loop research brief json: {exc}'))
        return checks
    checks.append(check('loop_research_brief_json_loadable', True))
    checks.append(check('loop_research_brief_version', brief.get('brief_version') == LOOP_RESEARCH_BRIEF_VERSION, f'invalid loop brief version: {brief.get("brief_version")}'))
    missing_sections = sorted(REQUIRED_LOOP_BRIEF_SECTIONS - set(brief.keys()))
    checks.append(check('loop_research_brief_sections_present', not missing_sections, f'loop brief missing sections: {missing_sections}'))
    checks.append(check('loop_research_brief_report_id_match', brief.get('report_id') == iteration.get('report_id'), 'loop brief report_id mismatch'))
    checks.append(check('loop_research_brief_factor_id_match', brief.get('factor_id') == iteration.get('factor_id'), 'loop brief factor_id mismatch'))
    checks.append(check('loop_research_brief_iteration_match', brief.get('iteration_no') == iteration.get('iteration_no'), 'loop brief iteration_no mismatch'))

    research_memo = nested_dict(nested_dict(iteration, 'research_judgment'), 'research_memo')
    mechanism_analysis = nested_dict(research_memo, 'mechanism_analysis')
    current_factor_family = str(mechanism_analysis.get('factor_family') or '')
    current_return_source = str(mechanism_analysis.get('return_source') or '')
    current_mechanism_fit = str(mechanism_analysis.get('mechanism_fit') or '')
    current_math_summary = mechanism_analysis.get('mechanism_math_summary') if isinstance(mechanism_analysis.get('mechanism_math_summary'), dict) else {}
    current_contract = mechanism_analysis.get('mechanism_math_contract') if isinstance(mechanism_analysis.get('mechanism_math_contract'), dict) else {}
    current_model_family = str(current_math_summary.get('model_family') or current_contract.get('model_family') or '')
    current_formula_derivation = mechanism_analysis.get('formula_specific_derivation') if isinstance(mechanism_analysis.get('formula_specific_derivation'), dict) else {}
    current_derivation_family = str(
        current_formula_derivation.get('selected_model_family')
        or (current_formula_derivation.get('economic_to_math_model_selection') or {}).get('baseline_model_family')
        or ''
    )
    current_economic_mechanism_family = str(current_math_summary.get('economic_mechanism_family') or current_contract.get('economic_mechanism_family') or current_model_family or '')
    current_math_tool_family = str(current_math_summary.get('math_tool_family') or current_contract.get('math_tool_family') or current_derivation_family or '')
    current_model_equation_family = str(current_math_summary.get('model_equation_family') or current_contract.get('model_equation_family') or '')
    brief_econ = nested_dict(brief, 'economic_interpretation')
    brief_math_summary = brief.get('mechanism_math_summary') if isinstance(brief.get('mechanism_math_summary'), dict) else {}
    mechanism_consistency_failures: list[str] = []
    if current_factor_family and brief_econ.get('factor_family') != current_factor_family:
        mechanism_consistency_failures.append(
            f"factor_family current={current_factor_family} brief={brief_econ.get('factor_family')}"
        )
    if current_return_source and brief_econ.get('return_source') != current_return_source:
        mechanism_consistency_failures.append(
            f"return_source current={current_return_source} brief={brief_econ.get('return_source')}"
        )
    if current_mechanism_fit and brief_econ.get('mechanism_fit') != current_mechanism_fit:
        mechanism_consistency_failures.append(
            f"mechanism_fit current={current_mechanism_fit} brief={brief_econ.get('mechanism_fit')}"
        )
    if current_model_family and brief_math_summary.get('model_family') != current_model_family:
        mechanism_consistency_failures.append(
            f"mechanism_model_family current={current_model_family} brief={brief_math_summary.get('model_family')}"
        )
    taxonomy_fields = {
        'economic_mechanism_family': current_economic_mechanism_family,
        'math_tool_family': current_math_tool_family,
        'model_equation_family': current_model_equation_family,
    }
    for field, current_value in taxonomy_fields.items():
        if current_value and field in brief_math_summary and brief_math_summary.get(field) != current_value:
            mechanism_consistency_failures.append(
                f"{field} current={current_value} brief={brief_math_summary.get(field)}"
            )
    checks.append(check(
        'loop_research_brief_mechanism_consistency',
        not mechanism_consistency_failures,
        f'loop brief mechanism fields stale or inconsistent: {mechanism_consistency_failures}',
    ))

    metrics = brief.get('metrics') if isinstance(brief.get('metrics'), dict) else {}
    missing_metrics = sorted(key for key in CORE_LOOP_BRIEF_METRICS if not present_metric(metrics.get(key)))
    checks.append(check('loop_research_brief_core_metrics_present', not missing_metrics, f'loop brief core metrics missing/empty: {missing_metrics}'))

    charts = brief.get('chart_evidence') if isinstance(brief.get('chart_evidence'), dict) else {}
    missing_charts = sorted(REQUIRED_LOOP_BRIEF_CHART_KEYS - set(charts.keys()))
    checks.append(check('loop_research_brief_chart_keys_present', not missing_charts, f'loop brief chart_evidence missing keys: {missing_charts}'))
    checks.append(check(
        'loop_research_brief_long_short_diagnostic_key',
        'long_short_nav_diagnostic_only' in charts and 'long_short_nav' not in charts,
        'loop brief long-short chart must be keyed as long_short_nav_diagnostic_only',
    ))
    checks.append(check(
        'loop_research_brief_why_not_portfolio_fix',
        nonempty_str(nested_dict(brief, 'next_research_direction').get('why_not_portfolio_fix')),
        'loop brief next_research_direction.why_not_portfolio_fix missing',
    ))
    checks.append(check(
        'loop_research_brief_current_conclusion',
        nonempty_str(nested_dict(brief, 'final_loop_conclusion').get('current_conclusion')),
        'loop brief final_loop_conclusion.current_conclusion missing',
    ))
    math_summary = brief.get('mechanism_math_summary') if isinstance(brief.get('mechanism_math_summary'), dict) else {}
    checks.append(check(
        'loop_research_brief_mechanism_math_summary_present',
        isinstance(math_summary, dict) and bool(math_summary),
        'loop brief mechanism_math_summary missing',
    ))
    status = math_summary.get('math_model_status')
    checks.append(check(
        'loop_research_brief_mechanism_math_status_present',
        nonempty_str(status),
        'loop brief mechanism_math_summary.math_model_status missing',
    ))
    if status == 'specified':
        missing_math_summary = sorted(
            key for key in SPECIFIED_MECHANISM_MATH_SUMMARY_FIELDS
            if not (
                (isinstance(math_summary.get(key), dict) and bool(math_summary.get(key)))
                or (isinstance(math_summary.get(key), list) and bool(math_summary.get(key)))
                or nonempty_str(math_summary.get(key))
            )
        )
        checks.append(check(
            'loop_research_brief_specified_mechanism_math_complete',
            not missing_math_summary,
            f'specified mechanism_math_summary missing fields: {missing_math_summary}',
        ))
    if status == 'under_specified':
        checks.append(check(
            'loop_research_brief_under_specified_reason_present',
            nonempty_str(math_summary.get('under_specified_reason')),
            'under_specified mechanism_math_summary requires under_specified_reason',
        ))
        checks.append(check(
            'loop_research_brief_under_specified_next_question_present',
            nonempty_str(math_summary.get('next_human_research_question')),
            'under_specified mechanism_math_summary requires next_human_research_question',
        ))
    if status == 'invalid':
        checks.append(check(
            'loop_research_brief_invalid_math_no_promotion',
            decision != 'promote_official',
            'invalid mechanism math contract cannot promote_official',
        ))
    if decision == 'iterate':
        snapshot = nested_dict(brief, 'decision_snapshot')
        next_dir = nested_dict(brief, 'next_research_direction')
        next_branch = str(snapshot.get('next_branch') or '')
        branch_template = next_dir.get('branch_template')
        checks.append(check(
            'loop_research_brief_iterate_next_direction',
            bool(next_branch and next_branch != 'none') or isinstance(branch_template, dict) and bool(branch_template) or snapshot.get('loop_authorization') in {'advisory_only', 'blocked'},
            'iterate loop brief must include a next branch or explicit advisory/approval reason',
        ))
    if decision == 'promote_official':
        requirements = nested_dict(brief, 'final_loop_conclusion').get('promotion_requirements')
        text = json.dumps(requirements, ensure_ascii=False).lower()
        checks.append(check(
            'loop_research_brief_promote_requirements_met',
            nonempty_list(requirements) and ('met' in text or 'already' in text),
            'promote_official loop brief must explain promotion requirements already met',
        ))
    if md_path.exists():
        markdown = md_path.read_text(encoding='utf-8')
        required_headers = [f'## {idx}.' for idx in range(1, 9)]
        missing_headers = [header for header in required_headers if header not in markdown]
        checks.append(check('loop_research_brief_markdown_sections', not missing_headers, f'loop brief markdown missing sections: {missing_headers}'))
        authoritative_markdown_fields = {
            'Factor family': current_factor_family,
            'Model family': current_model_family,
            'Economic mechanism family': current_economic_mechanism_family,
            'Math tool family': current_math_tool_family,
            'Model equation family': current_model_equation_family,
            'Selected model family': current_derivation_family,
        }
        markdown_field_failures: list[str] = []
        for label, expected_value in authoritative_markdown_fields.items():
            if not expected_value:
                continue
            match = re.search(
                rf'(?m)^-\s+{re.escape(label)}:\s*(.*?)\s*$',
                markdown,
            )
            actual_value = match.group(1).strip() if match else None
            if actual_value != expected_value:
                markdown_field_failures.append(
                    f'{label} expected={expected_value} actual={actual_value}'
                )
        checks.append(check(
            'loop_research_brief_mechanism_markdown_consistency',
            not markdown_field_failures,
            (
                'loop brief markdown mechanism text stale or inconsistent: '
                f'field_failures={markdown_field_failures}'
            ),
        ))
        if (iteration.get('revision_council_ref') or {}).get('enabled') is True:
            checks.append(check(
                'loop_research_brief_council_markdown_section_present_when_enabled',
                '## Revision Council Summary' in markdown,
                'loop brief missing Revision Council Summary markdown section while revision_council_ref.enabled=true',
            ))
    if (iteration.get('revision_council_ref') or {}).get('enabled') is True:
        council_section = brief.get('revision_council_summary')
        checks.append(check(
            'loop_research_brief_council_section_present_when_enabled',
            isinstance(council_section, dict) and bool(council_section),
            'loop brief JSON missing revision_council_summary while revision_council_ref.enabled=true',
        ))
        if isinstance(council_section, dict):
            checks.append(check(
                'loop_research_brief_council_no_auto_handoff_reason',
                nonempty_str(council_section.get('why_no_automatic_step3b_handoff')),
                'loop brief revision_council_summary.why_no_automatic_step3b_handoff missing',
            ))
    return checks


def artifact_identity_checks(left_label: str, left: dict, right_label: str, right: dict):
    checks = []
    left_identity = left.get('artifact_identity') or {}
    right_identity = right.get('artifact_identity') or {}
    required = ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'producer', 'spec_hash', 'branch_id', 'artifact_role']
    checks.append(check(f'{left_label}_artifact_identity_present', isinstance(left_identity, dict) and bool(left_identity), f'{left_label}.artifact_identity missing'))
    checks.append(check(f'{right_label}_artifact_identity_present', isinstance(right_identity, dict) and bool(right_identity), f'{right_label}.artifact_identity missing'))
    checks.append(check(f'{left_label}_artifact_identity_required', all(nonempty_str(left_identity.get(k)) for k in required), f'{left_label}.artifact_identity required fields missing: {left_identity}'))
    checks.append(check(f'{right_label}_artifact_identity_required', all(nonempty_str(right_identity.get(k)) for k in required), f'{right_label}.artifact_identity required fields missing: {right_identity}'))
    if left_identity and right_identity:
        try:
            assert_identity_matches_strict(
                left_identity,
                right_identity,
                expected_label=left_label,
                actual_label=right_label,
                allowed_role_transitions={(left_identity.get('artifact_role'), right_identity.get('artifact_role'))},
            )
            checks.append(check(f'{left_label}_{right_label}_identity_match', True))
        except AssertionError as exc:
            checks.append(check(f'{left_label}_{right_label}_identity_match', False, str(exc)))
    return checks


def check_identity_transition(expected_label: str, expected: dict, actual_label: str, actual: dict, actual_role: str):
    expected_identity = expected.get('artifact_identity') or {}
    actual_identity = actual.get('artifact_identity') or {}
    if not expected_identity or not actual_identity:
        return [check(f'{expected_label}_{actual_label}_strict_identity', False, f'{expected_label}/{actual_label} artifact_identity missing')]
    try:
        assert_identity_matches_strict(
            expected_identity,
            actual_identity,
            expected_label=expected_label,
            actual_label=actual_label,
            allowed_role_transitions={(expected_identity.get('artifact_role'), actual_role)},
        )
        return [check(f'{expected_label}_{actual_label}_strict_identity', True)]
    except AssertionError as exc:
        return [check(f'{expected_label}_{actual_label}_strict_identity', False, str(exc))]


def provenance_checks(label: str, obj: dict):
    checks = []
    checks.append(check(f'{label}_evidence_identity_present', isinstance(obj.get('evidence_identity'), dict) and bool(obj.get('evidence_identity')), f'{label}.evidence_identity missing'))
    checks.append(check(f'{label}_source_case_identity_present', isinstance(obj.get('source_case_identity'), dict) and bool(obj.get('source_case_identity')), f'{label}.source_case_identity missing'))
    checks.append(check(f'{label}_implementation_mode_decision_present', isinstance(obj.get('implementation_mode_decision'), dict) and bool(obj.get('implementation_mode_decision')), f'{label}.implementation_mode_decision missing'))
    checks.append(check(f'{label}_decision_lineage_present', isinstance(obj.get('decision_lineage'), dict) and bool(obj.get('decision_lineage')), f'{label}.decision_lineage missing'))
    checks.append(check(f'{label}_knowledge_provenance_present', isinstance(obj.get('knowledge_provenance'), dict) and bool(obj.get('knowledge_provenance')), f'{label}.knowledge_provenance missing'))
    return checks


def official_gate_checks(iteration: dict, case: dict, official_record: dict | None):
    checks = []
    decision = ((iteration.get('research_judgment') or {}).get('decision'))
    case_quality = case.get('evidence_quality') or {}
    promotion_gate = iteration.get('promotion_gate') or {}
    if decision == 'promote_official':
        checks.append(check('official_promotion_gate_present', isinstance(promotion_gate, dict) and bool(promotion_gate), 'promotion_gate missing for official promotion'))
        checks.append(check('official_promotion_gate_allows', promotion_gate.get('official_promotion_allowed') is True, f'official promotion gate blocked: {promotion_gate.get("promote_blocked_reason")}'))
        checks.append(check('official_requires_case_validated', case.get('final_status') == 'validated', 'official promotion requires factor_case_master.final_status=validated'))
        for key in ['identity_chain_verified', 'long_side_metrics_present', 'step4_has_successful_backend', 'mode_decision_present']:
            checks.append(check(f'official_requires_{key}', case_quality.get(key) is True, f'official promotion requires evidence_quality.{key}=true'))
        checks.append(check('official_record_exists_when_promoted', isinstance(official_record, dict), 'official promotion requires factor_library_official record'))
    return checks


def knowledge_scope_checks(iteration: dict, knowledge: dict):
    checks = []
    scope = knowledge.get('knowledge_scope')
    source_identity = knowledge.get('source_identity') or knowledge.get('source_case_identity') or {}
    knowledge_identity = knowledge.get('artifact_identity') or {}
    checks.append(check('knowledge_scope_valid', scope in {'same_factor', 'similar_case', 'general_methodology', 'anti_pattern'}, f'invalid knowledge_scope: {scope}'))
    checks.append(check('knowledge_source_identity_present', isinstance(source_identity, dict) and bool(source_identity), 'knowledge source_identity missing'))
    if scope == 'same_factor':
        checks.append(check(
            'knowledge_same_factor_identity_match',
            source_identity.get('factor_id') == knowledge.get('factor_id') == knowledge_identity.get('factor_id'),
            'same_factor knowledge must not cross factor_id',
        ))
    if scope == 'similar_case':
        checks.append(check(
            'similar_case_not_same_factor_evidence',
            ((iteration.get('research_judgment') or {}).get('decision') != 'promote_official'),
            'similar_case knowledge cannot support official promotion as same-factor evidence',
        ))
    checks.append(check(
        'knowledge_reuse_constraints_present',
        nonempty_list(knowledge.get('reuse_constraints')),
        'knowledge record must declare reuse_constraints',
    ))
    provenance = knowledge.get('knowledge_provenance') or {}
    checks.append(check(
        'knowledge_provenance_not_same_factor_guard',
        provenance.get('not_same_factor_unless_identity_matches') is True,
        'knowledge_provenance.not_same_factor_unless_identity_matches must be true',
    ))
    return checks


def iterate_lineage_checks(iteration: dict, handoff_path: Path):
    checks = []
    decision = ((iteration.get('research_judgment') or {}).get('decision'))
    if decision != 'iterate':
        return checks
    if not handoff_path.exists():
        checks.append(check('iterate_handoff_lineage_present', False, f'missing {handoff_path}'))
        return checks
    handoff = load_json(handoff_path)
    parent_identity = handoff.get('parent_identity') or {}
    source_identity = iteration.get('source_case_identity') or {}
    checks.append(check('iterate_parent_identity_present', isinstance(parent_identity, dict) and bool(parent_identity), 'handoff_to_step3b.parent_identity missing'))
    checks.append(check('iterate_new_branch_id_present', nonempty_str(handoff.get('new_branch_id')), 'handoff_to_step3b.new_branch_id missing'))
    checks.append(check('iterate_parent_run_id_present', nonempty_str(handoff.get('parent_run_id')), 'handoff_to_step3b.parent_run_id missing'))
    checks.append(check('iterate_parent_run_matches_source', handoff.get('parent_run_id') == source_identity.get('run_id'), 'iterate parent_run_id must match source run_id'))
    checks.append(check('iterate_parent_identity_matches_source', parent_identity.get('run_id') == source_identity.get('run_id') and parent_identity.get('branch_id') == source_identity.get('branch_id'), 'iterate parent_identity must match source_case_identity'))
    checks.append(check('iterate_preserve_change_forbidden_present', nonempty_list(handoff.get('must_preserve')) and nonempty_list(handoff.get('must_change')) and nonempty_list(handoff.get('forbidden_changes')), 'iterate handoff must declare must_preserve/must_change/forbidden_changes'))
    checks.append(check('iterate_decision_lineage_present', isinstance(handoff.get('decision_lineage'), dict) and bool(handoff.get('decision_lineage')), 'iterate handoff decision_lineage missing'))
    return checks


def revision_council_attachment_checks(iteration: dict, research_memo: dict, step3b_handoff_path: Path) -> list[dict]:
    checks: list[dict] = []
    report_id = str(iteration.get('report_id') or '')
    ref = iteration.get('revision_council_ref') or {}
    final_strategy = research_memo.get('final_revision_strategy') or {}
    if not ref and not final_strategy:
        return checks

    source = final_strategy.get('source') if isinstance(final_strategy, dict) else None
    checks.append(check('final_revision_strategy_source_enum', source in VALID_FINAL_REVISION_SOURCES, f'invalid final_revision_strategy.source: {source}'))
    if not isinstance(ref, dict) or ref.get('enabled') is not True:
        checks.append(check('revision_council_ref_valid', False, 'revision_council_ref.enabled must be true when final_revision_strategy is present'))
        return checks

    summary_path = resolve_artifact_path(ref.get('summary_path'))
    packet_path = resolve_artifact_path(ref.get('packet_path'))
    checks.append(check('revision_council_ref_valid', ref.get('enabled') is True and ref.get('status') == 'completed', 'revision_council_ref must be enabled and completed'))
    checks.append(check('revision_council_packet_exists_when_enabled', packet_path.exists(), f'missing revision council packet: {packet_path}'))
    checks.append(check('revision_council_summary_exists_when_enabled', summary_path.exists(), f'missing revision council summary: {summary_path}'))
    checks.append(check('revision_council_no_canonical_write_permission', ref.get('canonical_write_permission') is False, 'revision_council_ref.canonical_write_permission must be false'))
    checks.append(check('revision_council_no_execution_by_default', ref.get('execution_allowed_by_default') is False, 'revision_council_ref.execution_allowed_by_default must be false'))
    checks.append(check('revision_council_human_approval_required', ref.get('human_approval_required') is True, 'revision council attachment must require human approval'))

    packet: dict = {}
    if packet_path.exists():
        try:
            packet = load_json(packet_path)
        except Exception as exc:
            checks.append(check('revision_council_packet_loadable', False, f'failed to load revision council packet: {exc}'))

    summary: dict = {}
    if summary_path.exists():
        try:
            summary = load_json(summary_path)
        except Exception as exc:
            checks.append(check('revision_council_summary_loadable', False, f'failed to load revision council summary: {exc}'))
    if summary:
        branches = summary.get('recommended_branch_templates') or []
        checks.append(check('revision_council_summary_no_canonical_write_permission', summary.get('canonical_write_permission') is not True, 'revision council summary must not grant canonical_write_permission'))
        checks.append(check('revision_council_summary_no_execution_by_default', summary.get('execution_allowed_by_default') is False, 'revision council summary.execution_allowed_by_default must be false'))
        checks.append(check(
            'revision_council_summary_branches_no_execution',
            all((not isinstance(branch, dict)) or branch.get('execution_allowed_by_default') is False for branch in branches),
            'revision council branch templates must not execute by default',
        ))

    if source == 'revision_council':
        selected_ids = final_strategy.get('selected_council_proposal_ids') or []
        checks.append(check('final_revision_strategy_council_requires_valid_summary', summary_path.exists(), 'final_revision_strategy.source=revision_council requires summary file'))
        checks.append(check('final_revision_strategy_selected_proposals_present', nonempty_list(selected_ids), 'revision_council final strategy requires selected proposal ids'))
        checks.append(check('final_revision_strategy_human_approval_gate', final_strategy.get('approval_required_before_step3b') is True or final_strategy.get('requires_human_approval_before_code_change') is True, 'final revision strategy must require human approval before Step3B changes'))
        checks.append(check(
            'final_revision_strategy_no_forbidden_changes',
            not scan_forbidden_revision_text(final_strategy),
            f'final_revision_strategy contains forbidden change text: {scan_forbidden_revision_text(final_strategy)[:5]}',
        ))
        for idx, proposal_id in enumerate(selected_ids if isinstance(selected_ids, list) else []):
            if not nonempty_str(proposal_id):
                checks.append(check(f'final_revision_strategy_selected_proposal_{idx}_id_valid', False, 'selected proposal id must be nonempty string'))
                continue
            proposal_path, proposal = proposal_by_id(report_id, proposal_id)
            checks.append(check(f'final_revision_strategy_selected_proposal_{idx}_exists', proposal is not None, f'selected council proposal missing: {proposal_id}'))
            if not isinstance(proposal, dict):
                continue
            is_agentic_result = proposal.get('result_version') == 'factorforge_agentic_revision_council_result_v1'
            derivation = proposal.get('public_derivation_record') if is_agentic_result else proposal.get('derivation_record')
            checks.append(check(
                f'final_revision_strategy_selected_proposal_{idx}_derivation_record_present',
                isinstance(derivation, dict) and bool(derivation),
                f'selected council proposal missing derivation_record: {proposal_id}',
            ))
            proposal_reasons = (
                validate_agentic_result(
                    proposal,
                    expected_task=expected_manifest_task(report_id, proposal_path),
                    expected_report_id=report_id,
                )
                if is_agentic_result
                else validate_revision_council_proposal(
                    proposal,
                    measurement_program=packet.get(
                        'mechanism_conditioned_measurement_program'
                    ),
                    evo_v2_required=packet.get('evo_v2') is not None,
                    workspace_root=FF,
                )
            )
            checks.append(check(
                f'final_revision_strategy_selected_proposal_{idx}_valid',
                not proposal_reasons,
                f'selected council proposal invalid: {proposal_path}: {proposal_reasons}',
            ))
            forbidden = scan_forbidden_revision_text(proposal)
            checks.append(check(
                f'final_revision_strategy_selected_proposal_{idx}_no_forbidden_text',
                not forbidden,
                FORBIDDEN_TEXT_TOKEN + ':' + ','.join(f"{item['path']}={item['pattern']}" for item in forbidden[:5]),
            ))

    checks.append(check(
        'handoff_absent_without_approved_final_revision_strategy',
        final_strategy.get('loop_authorization') == 'approved_for_step3b_handoff' or not step3b_handoff_path.exists(),
        'handoff_to_step3b requires approved final_revision_strategy.loop_authorization',
    ))
    return checks


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--expected-host-trust-manifest-sha256', default=None)
    args = ap.parse_args()
    rid = args.report_id

    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json'
    all_library_path = OBJ / 'factor_library_all' / f'factor_record__{rid}.json'
    official_library_path = OBJ / 'factor_library_official' / f'factor_record__{rid}.json'
    knowledge_path = OBJ / 'research_knowledge_base' / f'knowledge_record__{rid}.json'
    step3b_handoff_path = OBJ / 'handoff' / f'handoff_to_step3b__{rid}.json'
    step6_handoff_path = OBJ / 'handoff' / f'handoff_to_step6__{rid}.json'
    frm_path = OBJ / 'factor_run_master' / f'factor_run_master__{rid}.json'
    case_path = OBJ / 'factor_case_master' / f'factor_case_master__{rid}.json'

    checks = []
    errors = []

    for label, path in [
        ('research_iteration_master_exists', iteration_path),
        ('factor_run_master_exists', frm_path),
        ('factor_case_master_exists', case_path),
        ('factor_library_all_exists', all_library_path),
        ('knowledge_record_exists', knowledge_path),
    ]:
        checks.append(check(label, path.exists(), f'missing {path}'))

    if iteration_path.exists() and all_library_path.exists() and knowledge_path.exists() and frm_path.exists() and case_path.exists():
        iteration = load_json(iteration_path)
        all_record = load_json(all_library_path)
        knowledge = load_json(knowledge_path)
        frm = load_json(frm_path)
        from factor_factory.evo_child_execution import validate_evo_child_execution_gate

        evo_gate_reasons = validate_evo_child_execution_gate(
            workspace_root=FF,
            report_id=rid,
            factor_run_master=frm,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
        )
        checks.append(check(
            'evo_child_execution_gate',
            not evo_gate_reasons,
            ';'.join(evo_gate_reasons) if evo_gate_reasons else None,
        ))
        iteration_tension = (
            ((iteration.get('research_judgment') or {}).get('research_memo') or {})
            .get('evo_transfer_tension_ledger')
        )
        knowledge_tension = (
            (knowledge.get('research_memo') or {})
            .get('evo_transfer_tension_ledger')
        )
        transfer_review_gate = knowledge.get(
            'evo_transfer_tension_review_gate'
        )
        checks.append(check(
            'evo_unreviewed_tension_not_copied_to_reusable_knowledge',
            knowledge_tension is None,
            'raw EVO transfer tension ledger requires a separate Host adjudication before reusable knowledge writeback',
        ))
        if iteration_tension is not None:
            expected_test_ids = [
                item.get('test_id')
                for item in (iteration_tension.get('tests') or [])
                if isinstance(item, dict)
            ] if isinstance(iteration_tension, dict) else []
            checks.append(check(
                'evo_pending_tension_review_gate',
                isinstance(transfer_review_gate, dict)
                and transfer_review_gate.get('status')
                == 'HOST_ADJUDICATION_REQUIRED_NOT_REUSABLE'
                and transfer_review_gate.get('diagnostic_contract_sha256')
                == iteration_tension.get('diagnostic_contract_sha256')
                and transfer_review_gate.get('execution_result_ref')
                == iteration_tension.get('execution_result_ref')
                and transfer_review_gate.get('ordered_test_ids')
                == expected_test_ids
                and transfer_review_gate.get(
                    'raw_tension_ledger_copied_to_knowledge'
                ) is False
                and transfer_review_gate.get('reusable_as_analogy') is False
                and transfer_review_gate.get(
                    'canonical_memory_promotion_allowed'
                ) is False
                and transfer_review_gate.get('factor_acceptance_affected')
                is False,
                'pending EVO transfer diagnostics must remain non-reusable and exact-bound to the iteration evidence',
            ))
        else:
            checks.append(check(
                'evo_pending_tension_review_gate_absent_without_diagnostic',
                transfer_review_gate is None,
                'EVO transfer review gate cannot appear without an iteration diagnostic ledger',
            ))
        case = load_json(case_path)
        official_record = load_json(official_library_path) if official_library_path.exists() else None
        checks.extend(check_identity_transition('factor_run_master', frm, 'factor_case_master', case, 'factor_case_master'))
        checks.extend(check_identity_transition('factor_case_master', case, 'research_iteration_master', iteration, 'research_iteration_master'))
        checks.extend(check_identity_transition('factor_case_master', case, 'factor_library_all', all_record, 'factor_library_all'))
        checks.extend(check_identity_transition('factor_case_master', case, 'research_knowledge_base', knowledge, 'research_knowledge_base'))
        if official_record:
            checks.extend(check_identity_transition('factor_case_master', case, 'factor_library_official', official_record, 'factor_library_official'))
        checks.extend(artifact_identity_checks('research_iteration_master', iteration, 'factor_library_all', all_record))
        checks.extend(artifact_identity_checks('research_iteration_master', iteration, 'knowledge_record', knowledge))
        checks.extend(provenance_checks('research_iteration_master', iteration))
        checks.extend(provenance_checks('factor_library_all', all_record))
        checks.extend(provenance_checks('research_knowledge_base', knowledge))
        checks.extend(official_gate_checks(iteration, case, official_record))
        checks.extend(knowledge_scope_checks(iteration, knowledge))
        checks.append(check('knowledge_provenance_branch_run_present', nonempty_str(nested_dict(knowledge, 'provenance').get('branch_id')) and nonempty_str(nested_dict(knowledge, 'provenance').get('run_id')), 'knowledge provenance must keep branch_id/run_id'))

        decision = iteration.get('research_judgment', {}).get('decision')
        checks.append(check('decision_enum', decision in VALID_DECISIONS, f'invalid decision: {decision}'))
        protocol_paths = research_protocol_paths(FF, rid)
        protocol_required = (
            os.getenv('FACTORFORGE_LEGACY_RESEARCH_PROTOCOL_SMOKE') != '1'
            and (
                os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1'
                or decision == 'promote_official'
            )
        )
        if protocol_required or protocol_paths['conjecture'].exists():
            protocol_report = validate_protocol_bundle(
                root=FF,
                report_id=rid,
                stage=(
                    'pre_promotion'
                    if decision == 'promote_official'
                    else 'pre_revision'
                ),
                iteration_path=iteration_path,
            )
            checks.append(check(
                (
                    'research_conjecture_protocol_pre_promotion'
                    if decision == 'promote_official'
                    else 'research_conjecture_protocol_pre_revision'
                ),
                protocol_report.get('verdict') == 'PASS',
                '; '.join(protocol_report.get('block_reasons') or []),
            ))
        if protocol_required and decision == 'promote_official':
            factor_proof_path = protocol_paths['factor_proof']
            try:
                factor_proof = (
                    load_json(factor_proof_path)
                    if factor_proof_path.exists()
                    else {}
                )
                factor_proof_report = (
                    validate_factor_proof_certificate(
                        factor_proof,
                        workspace_root=FF,
                        expected_report_id=rid,
                        expected_factor_id=str(iteration.get('factor_id') or ''),
                    )
                    if factor_proof
                    else {
                        'verdict': 'BLOCK',
                        'block_reasons': ['BLOCK_FACTORFORGE_PROMOTION_FACTOR_PROOF_MISSING'],
                    }
                )
            except Exception as exc:
                factor_proof = {}
                factor_proof_report = {
                    'verdict': 'BLOCK',
                    'block_reasons': [
                        f'BLOCK_FACTORFORGE_PROMOTION_FACTOR_PROOF_INVALID:{exc}'
                    ],
                }
            conjecture = (
                load_json(protocol_paths['conjecture'])
                if protocol_paths['conjecture'].exists()
                else {}
            )
            claim_class_matches = (
                bool(factor_proof)
                and factor_proof.get('claim_class') == conjecture.get('claim_class')
            )
            checks.append(check(
                'official_promotion_factor_proof_accept',
                factor_proof_report.get('verdict') == 'ACCEPT',
                '; '.join(factor_proof_report.get('block_reasons') or []),
            ))
            checks.append(check(
                'official_promotion_factor_proof_claim_class_matches_conjecture',
                claim_class_matches,
                'BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_CLAIM_CLASS_MISMATCH',
            ))
        checks.append(check('report_id_match', iteration.get('report_id') == all_record.get('report_id') == knowledge.get('report_id') == rid, 'report_id mismatch'))
        checks.append(check('factor_id_match', iteration.get('factor_id') == all_record.get('factor_id') == knowledge.get('factor_id'), 'factor_id mismatch'))
        checks.append(check('headline_metrics_present', isinstance(iteration.get('evidence_summary', {}).get('headline_metrics'), dict), 'headline_metrics missing'))
        checks.extend(validate_evidence_status_contract(iteration.get('evidence_status') or (iteration.get('evidence_summary') or {}).get('evidence_status')))
        checks.append(check('modification_targets_present', isinstance(iteration.get('loop_action', {}).get('modification_targets'), list), 'modification_targets missing'))
        checks.append(check('step5_handoff_recorded', isinstance(iteration.get('upstream_handoff', {}).get('step5_handoff_path'), str), 'step5 handoff path missing from iteration payload'))
        checks.append(check('framework_present', isinstance(iteration.get('research_judgment', {}).get('factor_investing_framework'), dict), 'factor investing framework missing'))
        checks.append(check('legacy_dd_view_edge_trade_absent', not has_key_recursive(iteration, 'dd_view_edge_trade') and not has_key_recursive(knowledge, 'dd_view_edge_trade'), 'Step6 must not emit DD-view-edge-trade fields; that framework is outside Factor Forge'))
        checks.append(check('knowledge_return_hypothesis_present', isinstance(knowledge.get('return_source_hypothesis'), str), 'return_source_hypothesis missing'))
        checks.append(check('framework_review_checklist_present', isinstance(iteration.get('research_judgment', {}).get('factor_investing_framework', {}).get('review_checklist'), list), 'review_checklist missing'))
        checks.append(check('knowledge_revision_principles_present', isinstance(knowledge.get('revision_principles'), list), 'revision_principles missing'))
        checks.extend(loop_research_brief_checks(iteration, str(decision)))

        research_judgment = iteration.get('research_judgment') or {}
        research_memo = research_judgment.get('research_memo') or {}
        metric_interpretation = nested_dict(research_judgment, 'research_memo', 'metric_interpretation')
        long_side_policy = (
            nested_dict(research_judgment, 'research_memo', 'long_side_adoption_policy')
            or nested_dict(metric_interpretation, 'long_side_adoption_review')
        )
        formula_understanding = nested_dict(research_judgment, 'research_memo', 'formula_understanding')
        return_source = nested_dict(research_judgment, 'research_memo', 'return_source_analysis')
        math_discipline = nested_dict(research_judgment, 'research_memo', 'math_discipline_review')
        learning = nested_dict(research_judgment, 'research_memo', 'learning_and_innovation')
        evidence_quality = nested_dict(research_judgment, 'research_memo', 'evidence_quality')
        failure_analysis = nested_dict(research_judgment, 'research_memo', 'failure_and_risk_analysis')
        experience_chain = research_memo.get('experience_chain') or research_judgment.get('experience_chain') or {}
        revision_taxonomy = research_memo.get('revision_taxonomy') or research_judgment.get('revision_taxonomy') or {}
        program_search_policy = research_memo.get('program_search_policy') or research_judgment.get('program_search_policy') or {}
        diversity_position = research_memo.get('diversity_position') or research_judgment.get('diversity_position') or {}
        evidence_audit = research_memo.get('evidence_audit') or {}
        mechanism_analysis = research_memo.get('mechanism_analysis') or {}
        case_comparison = research_memo.get('case_comparison') or {}
        revision_strategy = research_memo.get('revision_strategy') or {}
        search_policy_decision = research_memo.get('search_policy_decision') or {}
        method_library = program_search_policy.get('method_library') or {}
        search_branches = ((program_search_policy.get('recommended_next_search') or {}).get('branches')) or []
        information_set_legality = str(math_discipline.get('information_set_legality') or '').lower()
        overfit_risk_items = [str(item).lower() for item in (math_discipline.get('overfit_risk') or [])]
        metric_evidence_items = (
            (metric_interpretation.get('positive_evidence') or [])
            + (metric_interpretation.get('negative_evidence') or [])
            + (metric_interpretation.get('ambiguities') or [])
        )
        checks.extend(revision_council_attachment_checks(iteration, research_memo, step3b_handoff_path))
        memo_ref = iteration.get('main_agent_mechanism_memo_ref') or research_memo.get('main_agent_mechanism_memo_ref') or {}
        memo_path_value = memo_ref.get('json_path') if isinstance(memo_ref, dict) else None
        memo_path = Path(memo_path_value) if memo_path_value else OBJ / 'research_iteration_master' / f'main_agent_mechanism_memo__{rid}.json'
        if not memo_path.is_absolute():
            memo_path = FF / memo_path
        checks.append(check(
            'main_agent_mechanism_memo_ref_present',
            isinstance(memo_ref, dict) and bool(memo_ref.get('json_path')),
            'main_agent_mechanism_memo_ref missing',
        ))
        checks.append(check(
            'main_agent_mechanism_memo_exists',
            memo_path.exists(),
            f'main agent mechanism memo missing: {memo_path}',
        ))
        if memo_path.exists():
            try:
                main_agent_memo = load_json(memo_path)
                memo_failures = validate_main_agent_mechanism_memo(main_agent_memo, load_json(OBJ / 'factor_spec_master' / f'factor_spec_master__{rid}.json') if (OBJ / 'factor_spec_master' / f'factor_spec_master__{rid}.json').exists() else {})
            except Exception as exc:
                memo_failures = ['BLOCK_MAIN_AGENT_MECHANISM_MEMO_MISSING']
                checks.append(check('main_agent_mechanism_memo_loadable', False, f'failed to load main agent mechanism memo: {exc}'))
            for token in memo_failures:
                checks.append(check(token, False, token))
            if not memo_failures:
                checks.append(check('main_agent_mechanism_memo_valid', True, None))

        checks.append(check('research_memo_present', isinstance(research_memo, dict) and bool(research_memo), 'research_memo missing or empty'))
        for field, value in [
            ('evidence_audit', evidence_audit),
            ('mechanism_analysis', mechanism_analysis),
            ('case_comparison', case_comparison),
            ('revision_strategy', revision_strategy),
            ('search_policy_decision', search_policy_decision),
        ]:
            checks.append(check(f'research_intelligence_{field}_present', isinstance(value, dict) and bool(value), f'research_memo.{field} missing or empty'))
            checks.append(check(
                f'research_intelligence_{field}_no_empty_strings',
                not empty_string_paths(value),
                f'research_memo.{field} contains empty string fields: {empty_string_paths(value)[:5]}',
            ))

        backend_integrity = evidence_audit.get('backend_integrity') or {}
        metric_consistency = evidence_audit.get('metric_consistency') or {}
        factor_value_health = evidence_audit.get('factor_value_health') or {}
        long_side_quality = evidence_audit.get('long_side_evidence_quality') or {}
        cost_turnover = evidence_audit.get('cost_and_turnover_risk') or {}
        checks.append(check('evidence_audit_backend_integrity_present', isinstance(backend_integrity, dict) and bool(backend_integrity), 'evidence_audit.backend_integrity missing'))
        checks.append(check('evidence_audit_metric_consistency_present', isinstance(metric_consistency, dict) and bool(metric_consistency), 'evidence_audit.metric_consistency missing'))
        checks.append(check('evidence_audit_factor_value_health_present', isinstance(factor_value_health, dict) and bool(factor_value_health), 'evidence_audit.factor_value_health missing'))
        checks.append(check('evidence_audit_long_side_quality_present', isinstance(long_side_quality, dict) and bool(long_side_quality), 'evidence_audit.long_side_evidence_quality missing'))
        checks.append(check('evidence_audit_cost_turnover_present', isinstance(cost_turnover, dict) and bool(cost_turnover), 'evidence_audit.cost_and_turnover_risk missing'))
        checks.append(check('evidence_audit_suspicions_list', list_value(evidence_audit.get('data_or_implementation_suspicions')), 'evidence_audit.data_or_implementation_suspicions must be a list'))
        checks.append(check('evidence_audit_verdict_enum', evidence_audit.get('evidence_verdict') in VALID_EVIDENCE_VERDICTS, f"invalid evidence_verdict: {evidence_audit.get('evidence_verdict')}"))
        checks.append(check(
            'evidence_audit_not_blocked',
            evidence_audit.get('evidence_verdict') != 'blocked',
            'evidence_audit.evidence_verdict=blocked cannot validate closed-loop Step6 output',
        ))
        checks.append(check(
            'evidence_blocked_cannot_promote',
            evidence_audit.get('evidence_verdict') != 'blocked' or decision != 'promote_official',
            'blocked evidence_audit cannot promote_official',
        ))
        checks.append(check(
            'evidence_blocked_no_official_record',
            evidence_audit.get('evidence_verdict') != 'blocked' or not official_library_path.exists(),
            'blocked evidence_audit must not write official record',
        ))

        checks.append(check('mechanism_return_source_enum', mechanism_analysis.get('return_source') in VALID_RETURN_SOURCES, f"invalid return_source: {mechanism_analysis.get('return_source')}"))
        checks.append(check('mechanism_factor_family_enum', mechanism_analysis.get('factor_family') in VALID_FACTOR_FAMILIES, f"invalid factor_family: {mechanism_analysis.get('factor_family')}"))
        checks.append(check('mechanism_hypothesis_present', nonempty_str(mechanism_analysis.get('mechanism_hypothesis')), 'mechanism_hypothesis missing'))
        checks.append(check('mechanism_necessary_conditions_present', nonempty_list(mechanism_analysis.get('necessary_conditions')), 'necessary_conditions missing'))
        checks.append(check('mechanism_expected_signature_present', isinstance(mechanism_analysis.get('expected_metric_signature'), dict) and bool(mechanism_analysis.get('expected_metric_signature')), 'expected_metric_signature missing'))
        checks.append(check('mechanism_observed_signature_present', isinstance(mechanism_analysis.get('observed_metric_signature'), dict) and bool(mechanism_analysis.get('observed_metric_signature')), 'observed_metric_signature missing'))
        checks.append(check('mechanism_fit_enum', mechanism_analysis.get('mechanism_fit') in VALID_MECHANISM_FITS, f"invalid mechanism_fit: {mechanism_analysis.get('mechanism_fit')}"))
        checks.append(check('mechanism_failure_regimes_present', nonempty_list(mechanism_analysis.get('failure_regimes')), 'failure_regimes missing'))
        checks.append(check('mechanism_mind_change_present', nonempty_list(mechanism_analysis.get('what_would_change_my_mind')), 'what_would_change_my_mind missing'))
        checks.append(check('mechanism_classification_evidence_present', isinstance(mechanism_analysis.get('classification_evidence'), dict) and bool(mechanism_analysis.get('classification_evidence')), 'classification_evidence missing'))
        checks.append(check('mechanism_classification_uncertainty_enum', mechanism_analysis.get('classification_uncertainty') in VALID_CLASSIFICATION_UNCERTAINTY, f"invalid classification_uncertainty: {mechanism_analysis.get('classification_uncertainty')}"))
        mechanism_math_contract = mechanism_analysis.get('mechanism_math_contract') or {}
        mechanism_math_contract_v2 = mechanism_analysis.get('mechanism_math_contract_v2') or {}
        measurement_program = mechanism_analysis.get('mechanism_conditioned_measurement_program') or {}
        mechanism_math_failures = (
            validate_mechanism_math_contract(mechanism_math_contract)
            if isinstance(mechanism_math_contract, dict) and mechanism_math_contract
            else []
        )
        mechanism_math_v2_failures = validate_mechanism_math_contract_v2(mechanism_math_contract_v2) if isinstance(mechanism_math_contract_v2, dict) and mechanism_math_contract_v2 else []
        declared_node_ids = {
            str(node_id)
            for component in ((measurement_program.get('implementation') or {}).get('components') or [])
            if isinstance(component, dict)
            for node_id in (component.get('knowledge_node_ids') or [])
            if str(node_id).strip()
        } if isinstance(measurement_program, dict) else set()
        measurement_program_failures = validate_measurement_program(
            measurement_program,
            available_knowledge_node_ids=declared_node_ids,
            require_web_executable=False,
        ) if isinstance(measurement_program, dict) and measurement_program else []
        checks.append(check(
            'legacy_mechanism_math_contract_valid_if_present',
            not mechanism_math_failures,
            f'mechanism_analysis.mechanism_math_contract invalid: {mechanism_math_failures}',
        ))
        checks.append(check(
            'mechanism_conditioned_measurement_program_present',
            isinstance(measurement_program, dict) and bool(measurement_program),
            'mechanism_analysis.mechanism_conditioned_measurement_program missing',
        ))
        checks.append(check(
            'mechanism_math_contract_v2_valid_if_present',
            not mechanism_math_v2_failures,
            f'mechanism_analysis.mechanism_math_contract_v2 invalid: {mechanism_math_v2_failures}',
        ))
        checks.append(check(
            'mechanism_conditioned_measurement_program_valid',
            not measurement_program_failures,
            f'mechanism_analysis.mechanism_conditioned_measurement_program invalid: {measurement_program_failures}',
        ))
        model_linkage_failures = validate_step6_model_linkage(mechanism_analysis, revision_strategy)
        checks.append(check(
            'BLOCK_STEP6_METRICS_NOT_LINKED_TO_MODEL',
            'BLOCK_STEP6_METRICS_NOT_LINKED_TO_MODEL' not in model_linkage_failures,
            'BLOCK_STEP6_METRICS_NOT_LINKED_TO_MODEL: Step6 metrics must attribute evidence to economic_hypothesis, primary_mechanism_model, market_outcome_projection, observable_estimator, or implementation_contract',
        ))
        checks.append(check(
            'BLOCK_STEP6_RESEARCH_EQUATION_NOT_LINKED_TO_METRICS',
            'BLOCK_STEP6_RESEARCH_EQUATION_NOT_LINKED_TO_METRICS' not in model_linkage_failures,
            'BLOCK_STEP6_RESEARCH_EQUATION_NOT_LINKED_TO_METRICS: Step6 metrics must explicitly link to research_equation_review and required metric links',
        ))
        research_equation = mechanism_math_contract_v2.get('research_equation') if isinstance(mechanism_math_contract_v2.get('research_equation'), dict) else {}
        research_equation_review = mechanism_analysis.get('research_equation_review') if isinstance(mechanism_analysis.get('research_equation_review'), dict) else {}
        checks.append(check(
            'research_conjecture_promotion_requires_supported_equation',
            decision != 'promote_official'
            or research_equation.get('equation_status') != 'research_conjecture'
            or research_equation_review.get('equation_supported_by_metrics') == 'supported',
            'research_conjecture cannot promote unless research_equation_review.equation_supported_by_metrics=supported',
        ))
        factor_spec_path = OBJ / 'factor_spec_master' / f'factor_spec_master__{rid}.json'
        factor_spec = load_json(factor_spec_path) if factor_spec_path.exists() else {}
        canonical_spec = factor_spec.get('canonical_spec') if isinstance(factor_spec.get('canonical_spec'), dict) else {}
        upstream_programs = [
            factor_spec.get('mechanism_conditioned_measurement_program'),
            canonical_spec.get('mechanism_conditioned_measurement_program'),
        ]
        upstream_programs = [
            item for item in upstream_programs if isinstance(item, dict) and item
        ]
        checks.append(check(
            'mechanism_conditioned_measurement_program_preserved_from_step2',
            not upstream_programs
            or (
                isinstance(measurement_program, dict)
                and bool(measurement_program)
                and all(item == measurement_program for item in upstream_programs)
            ),
            'mechanism_analysis must preserve the exact Step2 measurement program when present',
        ))
        formula_specific_derivation = mechanism_analysis.get('formula_specific_derivation') or {}
        formula_derivation_failures = validate_formula_specific_derivation(
            formula_specific_derivation,
            factor_spec,
            mechanism_analysis,
        )
        mechanism_formula_consistency = validate_mechanism_formula_consistency(
            factor_spec,
            mechanism_analysis,
            formula_specific_derivation,
        )
        checks.append(check(
            'formula_specific_derivation_valid',
            not formula_derivation_failures,
            f'formula_specific_derivation invalid: {formula_derivation_failures}',
        ))
        checks.append(check(
            'mechanism_formula_consistency_valid',
            not mechanism_formula_consistency.get('failures'),
            f"mechanism_formula_consistency invalid: {mechanism_formula_consistency.get('failures')}",
        ))
        recorded_consistency = mechanism_analysis.get('mechanism_formula_consistency') or {}
        if isinstance(recorded_consistency, dict) and recorded_consistency:
            checks.append(check(
                'mechanism_formula_consistency_recorded_current',
                recorded_consistency.get('status') == mechanism_formula_consistency.get('status')
                and recorded_consistency.get('failures') == mechanism_formula_consistency.get('failures'),
                f"mechanism_formula_consistency stale: recorded={recorded_consistency} current={mechanism_formula_consistency}",
            ))
        checks.append(check(
            'invalid_mechanism_math_cannot_promote',
            decision != 'promote_official'
            or (mechanism_analysis.get('mechanism_math_summary') or {}).get('math_model_status') != 'invalid',
            'official promotion is forbidden when the current mechanism math summary is invalid',
        ))
        checks.append(check(
            'unknown_or_contradicted_mechanism_cannot_promote',
            decision != 'promote_official' or (
                mechanism_analysis.get('return_source') != 'unknown'
                and mechanism_analysis.get('mechanism_fit') != 'contradicted'
            ),
            'official promotion requires known return_source and non-contradicted mechanism_fit',
        ))

        for field in [
            'similar_success_cases',
            'similar_failure_cases',
            'mechanism_neighbors',
            'imported_lessons',
            'rejected_lessons',
            'why_this_case_is_different',
            'knowledge_gap',
            'same_factor_cases',
            'similar_case_cases',
            'anti_pattern_cases',
            'identity_mismatch_cases',
        ]:
            checks.append(check(f'case_comparison_{field}_list', list_value(case_comparison.get(field)), f'case_comparison.{field} must be a list'))
        checks.append(check(
            'case_comparison_verdict_not_blocked',
            case_comparison.get('case_comparison_verdict') != 'blocked',
            'case_comparison_verdict=blocked cannot validate Step6 output',
        ))
        checks.append(check(
            'case_comparison_identity_mismatch_absent',
            not case_comparison.get('identity_mismatch_cases'),
            f"same_factor retrieval identity mismatch: {case_comparison.get('identity_mismatch_cases')}",
        ))
        checks.append(check('case_comparison_retrieval_used_bool', isinstance(case_comparison.get('retrieval_used'), bool), 'case_comparison.retrieval_used must be bool'))
        checks.append(check('case_comparison_imported_lessons_present', nonempty_list(case_comparison.get('imported_lessons')), 'case_comparison.imported_lessons missing'))
        checks.append(check('case_comparison_difference_present', nonempty_list(case_comparison.get('why_this_case_is_different')), 'case_comparison.why_this_case_is_different missing'))
        retrieved_case_count = sum(len(case_comparison.get(key) or []) for key in ['same_factor_cases', 'similar_case_cases', 'anti_pattern_cases'])
        checks.append(check(
            'case_comparison_cold_start_gap_present',
            retrieved_case_count > 0 or nonempty_list(case_comparison.get('knowledge_gap')),
            'case_comparison.knowledge_gap must be nonempty when no cases were retrieved',
        ))
        checks.append(check(
            'case_comparison_retrieved_lessons_used',
            retrieved_case_count == 0 or nonempty_list(case_comparison.get('imported_lessons')) or nonempty_list(case_comparison.get('rejected_lessons')),
            'retrieved cases require imported_lessons or rejected_lessons',
        ))
        source_identity_for_compare = iteration.get('source_case_identity') or {}
        same_factor_bad = []
        for idx, item in enumerate(case_comparison.get('same_factor_cases') or []):
            item_identity = item.get('artifact_identity') or item.get('source_identity') or {}
            item_factor = item_identity.get('factor_id') or item.get('factor_id')
            item_formula = item_identity.get('formula_hash') or item.get('formula_hash')
            if item_factor != source_identity_for_compare.get('factor_id'):
                same_factor_bad.append(f'idx={idx}:factor_id')
            if item_formula and source_identity_for_compare.get('formula_hash') and item_formula != source_identity_for_compare.get('formula_hash'):
                same_factor_bad.append(f'idx={idx}:formula_hash')
        checks.append(check('case_comparison_same_factor_identity_match', not same_factor_bad, f'same_factor_cases identity mismatch: {same_factor_bad}'))
        checks.append(check(
            'similar_case_not_promotion_evidence',
            case_comparison.get('similar_case_promotion_evidence_used') is not True,
            'similar_case_cases cannot be used as official promotion evidence',
        ))

        checks.append(check('revision_strategy_revision_needed_bool', isinstance(revision_strategy.get('revision_needed'), bool), 'revision_strategy.revision_needed must be boolean'))
        checks.append(check('revision_strategy_failure_signature_enum', revision_strategy.get('primary_failure_signature') in VALID_PRIMARY_FAILURE_SIGNATURES, f"invalid primary_failure_signature: {revision_strategy.get('primary_failure_signature')}"))
        checks.append(check('revision_strategy_quality_enum', revision_strategy.get('revision_quality') in VALID_REVISION_QUALITIES, f"invalid revision_quality: {revision_strategy.get('revision_quality')}"))
        checks.append(check('revision_strategy_loop_authorization_enum', revision_strategy.get('loop_authorization') in VALID_LOOP_AUTHORIZATIONS, f"invalid loop_authorization: {revision_strategy.get('loop_authorization')}"))
        checks.append(check(
            'revision_strategy_human_approval_gate',
            revision_strategy.get('revision_needed') is False or revision_strategy.get('requires_human_approval_before_code_change') is True,
            'revision_strategy.requires_human_approval_before_code_change must be true when revision_needed=true',
        ))
        checks.append(check('revision_strategy_hypotheses_list', list_value(revision_strategy.get('revision_hypotheses')), 'revision_hypotheses must be a list'))
        for idx, hypothesis in enumerate(revision_strategy.get('revision_hypotheses') or []):
            expression_change = str(hypothesis.get('expression_change') or '').lower()
            forbidden_expression_terms = [term for term in FORBIDDEN_EXPRESSION_REPAIR_TERMS if term in expression_change]
            forbidden_changes = set(hypothesis.get('forbidden_changes') or [])
            checks.append(check(f'revision_hypothesis_{idx}_id_present', nonempty_str(hypothesis.get('hypothesis_id')), 'revision hypothesis_id missing'))
            checks.append(check(f'revision_hypothesis_{idx}_hypothesis_present', nonempty_str(hypothesis.get('hypothesis')), 'revision hypothesis text missing'))
            checks.append(check(f'revision_hypothesis_{idx}_mechanism_target_present', nonempty_str(hypothesis.get('mechanism_target')), 'revision mechanism_target missing'))
            checks.append(check(f'revision_hypothesis_{idx}_expression_change_present', nonempty_str(hypothesis.get('expression_change')), 'revision expression_change missing'))
            checks.append(check(f'revision_hypothesis_{idx}_target_math_object_enum', hypothesis.get('revision_target_math_object') in REVISION_MATH_OBJECTS, f"invalid revision_target_math_object: {hypothesis.get('revision_target_math_object')}"))
            checks.append(check(f'revision_hypothesis_{idx}_math_change_present', nonempty_str(hypothesis.get('math_change')), 'revision math_change missing'))
            checks.append(check(f'revision_hypothesis_{idx}_expected_metric_effect_present', nonempty_list(hypothesis.get('expected_metric_effect')), 'revision expected_metric_effect missing'))
            checks.append(check(f'revision_hypothesis_{idx}_math_falsification_tests_present', nonempty_list(hypothesis.get('math_falsification_tests')), 'revision math_falsification_tests missing'))
            checks.append(check(f'revision_hypothesis_{idx}_mode_preference_enum', hypothesis.get('implementation_mode_preference') in VALID_IMPLEMENTATION_MODE_PREFERENCES, f"invalid implementation_mode_preference: {hypothesis.get('implementation_mode_preference')}"))
            checks.append(check(f'revision_hypothesis_{idx}_expected_metric_change_present', nonempty_list(hypothesis.get('expected_metric_change')), 'expected_metric_change missing'))
            checks.append(check(f'revision_hypothesis_{idx}_expected_metric_change_minimum', len(hypothesis.get('expected_metric_change') or []) >= 2, 'expected_metric_change must contain at least 2 items'))
            checks.append(check(f'revision_hypothesis_{idx}_falsification_tests_present', nonempty_list(hypothesis.get('falsification_tests')), 'falsification_tests missing'))
            checks.append(check(f'revision_hypothesis_{idx}_falsification_tests_minimum', len(hypothesis.get('falsification_tests') or []) >= 2, 'falsification_tests must contain at least 2 items'))
            checks.append(check(f'revision_hypothesis_{idx}_overfit_enum', hypothesis.get('risk_of_overfit') in VALID_OVERFIT_RISKS, f"invalid risk_of_overfit: {hypothesis.get('risk_of_overfit')}"))
            checks.append(check(f'revision_hypothesis_{idx}_kill_criteria_present', nonempty_list(hypothesis.get('kill_criteria')), 'kill_criteria missing'))
            checks.append(check(f'revision_hypothesis_{idx}_kill_criteria_minimum', len(hypothesis.get('kill_criteria') or []) >= 2, 'kill_criteria must contain at least 2 items'))
            checks.append(check(f'revision_hypothesis_{idx}_why_not_portfolio_fix_present', nonempty_str(hypothesis.get('why_not_portfolio_fix')), 'why_not_portfolio_fix missing'))
            checks.append(check(
                f'revision_hypothesis_{idx}_forbidden_changes_complete',
                REQUIRED_REVISION_FORBIDDEN_CHANGES.issubset(forbidden_changes),
                f'forbidden_changes must contain {sorted(REQUIRED_REVISION_FORBIDDEN_CHANGES)}',
            ))
            checks.append(check(
                f'revision_hypothesis_{idx}_expression_change_no_portfolio_repair_terms',
                not forbidden_expression_terms,
                f'expression_change contains forbidden portfolio repair terms: {forbidden_expression_terms}',
            ))
        checks.append(check(
            'iterate_requires_revision_strategy',
            decision != 'iterate' or (
                revision_strategy.get('revision_needed') is True
                and nonempty_list(revision_strategy.get('revision_hypotheses'))
                and revision_strategy.get('revision_quality') == 'actionable'
                and all(nonempty_str(item.get('expression_change')) and nonempty_str(item.get('why_not_portfolio_fix')) for item in revision_strategy.get('revision_hypotheses') or [])
            ),
            'iterate requires revision_needed=true, revision_quality=actionable, and expression-level revision hypotheses',
        ))
        checks.append(check(
            'blocked_failure_signature_blocks_revision',
            revision_strategy.get('primary_failure_signature') not in {'implementation_suspect', 'same_factor_identity_mismatch'} or (
                revision_strategy.get('revision_quality') == 'blocked'
                and not revision_strategy.get('revision_hypotheses')
            ),
            'implementation_suspect/same_factor_identity_mismatch must use blocked revision_quality and no actionable expression revision',
        ))
        checks.append(check(
            'mechanism_unclear_requires_challenge_or_reject',
            revision_strategy.get('primary_failure_signature') != 'mechanism_unclear' or (
                revision_strategy.get('revision_quality') in {'actionable', 'blocked'}
                and (
                    any('mechanism' in str(item.get('mechanism_target') or item.get('hypothesis') or '').lower() for item in revision_strategy.get('revision_hypotheses') or [])
                    or nonempty_str(revision_strategy.get('reject_reason_if_no_revision'))
                )
            ),
            'mechanism_unclear requires a mechanism challenge hypothesis or reject rationale',
        ))
        revision_hypotheses = revision_strategy.get('revision_hypotheses') or []
        if revision_hypotheses:
            checks.append(check(
                'revision_hypotheses_model_layer_present',
                'BLOCK_COUNCIL_REVISION_MODEL_LAYER_MISSING' not in model_linkage_failures,
                'BLOCK_COUNCIL_REVISION_MODEL_LAYER_MISSING: revision hypotheses must declare the model layer being revised',
            ))
        checks.append(check(
            'reject_requires_revision_reject_reason',
            decision != 'reject' or nonempty_str(revision_strategy.get('reject_reason_if_no_revision')),
            'reject requires revision_strategy.reject_reason_if_no_revision',
        ))
        final_strategy = research_memo.get('final_revision_strategy') or {}
        if isinstance(final_strategy, dict) and final_strategy.get('source') == 'revision_council':
            handoff_authorized = final_strategy.get('loop_authorization') == 'approved_for_step3b_handoff'
        else:
            handoff_authorized = (
                decision == 'iterate'
                and revision_strategy.get('loop_authorization') == 'approved_for_step3b_handoff'
                and revision_strategy.get('revision_quality') == 'actionable'
                and case_comparison.get('case_comparison_verdict') != 'blocked'
                and case_comparison.get('similar_success_condition_mismatch') is not True
            )
        checks.append(check(
            'step3b_handoff_authorization_consistency',
            (isinstance(final_strategy, dict) and final_strategy.get('source') == 'revision_council')
            or revision_strategy.get('loop_authorization') != 'approved_for_step3b_handoff'
            or handoff_authorized,
            'approved Step3B handoff requires decision=iterate, actionable revision, usable case comparison, and no similar-success condition mismatch',
        ))
        checks.append(check(
            'condition_mismatch_not_handoff_authorized',
            case_comparison.get('similar_success_condition_mismatch') is not True or revision_strategy.get('loop_authorization') != 'approved_for_step3b_handoff',
            'similar success condition mismatch must remain advisory and cannot authorize Step3B handoff',
        ))

        checks.append(check('search_policy_decision_mode_enum', search_policy_decision.get('recommended_mode') in VALID_SEARCH_POLICY_MODES, f"invalid recommended_mode: {search_policy_decision.get('recommended_mode')}"))
        checks.append(check('search_policy_decision_reason_present', nonempty_str(search_policy_decision.get('why_this_mode')), 'search_policy_decision.why_this_mode missing'))
        branch_templates = search_policy_decision.get('branch_templates') or []
        checks.append(check('search_policy_decision_branch_templates_list', list_value(branch_templates), 'search_policy_decision.branch_templates must be a list'))
        for idx, branch in enumerate(branch_templates):
            hard_guards = set(branch.get('hard_guards') or []) if isinstance(branch, dict) else set()
            checks.append(check(f'search_branch_{idx}_object', isinstance(branch, dict), 'search_policy_decision branch template must be an object'))
            if not isinstance(branch, dict):
                continue
            checks.append(check(f'search_branch_{idx}_branch_id_present', nonempty_str(branch.get('branch_id')), 'branch_id missing'))
            checks.append(check(f'search_branch_{idx}_role_present', branch.get('branch_role') in {'audit', 'exploit', 'explore', 'macro'}, f"invalid branch_role: {branch.get('branch_role')}"))
            checks.append(check(f'search_branch_{idx}_mode_present', branch.get('search_mode') in {'research_audit', 'bayesian_search', 'genetic_algorithm', 'mechanism_challenge', 'multi_agent_parallel_exploration'}, f"invalid search_mode: {branch.get('search_mode')}"))
            checks.append(check(f'search_branch_{idx}_question_present', nonempty_str(branch.get('research_question')), 'research_question missing'))
            checks.append(check(f'search_branch_{idx}_hypothesis_present', nonempty_str(branch.get('hypothesis')), 'hypothesis missing'))
            checks.append(check(f'search_branch_{idx}_mechanism_target_present', nonempty_str(branch.get('mechanism_target')), 'mechanism_target missing'))
            checks.append(check(f'search_branch_{idx}_success_criteria_present', nonempty_list(branch.get('success_criteria')), 'success_criteria missing'))
            checks.append(check(f'search_branch_{idx}_falsification_tests_present', nonempty_list(branch.get('falsification_tests')), 'falsification_tests missing'))
            checks.append(check(
                f'search_branch_{idx}_hard_guards_complete',
                REQUIRED_FORBIDDEN_SEARCH.issubset(hard_guards),
                f'branch hard_guards must contain {sorted(REQUIRED_FORBIDDEN_SEARCH)}',
            ))
            checks.append(check(f'search_branch_{idx}_approval_required', branch.get('requires_human_approval_before_execution') is True, 'branch must require human approval before execution'))
            checks.append(check(f'search_branch_{idx}_execution_disabled', branch.get('execution_allowed_by_default') is False, 'branch execution_allowed_by_default must be false'))
        checks.append(check(
            'advisory_loop_no_executable_branch',
            revision_strategy.get('loop_authorization') != 'advisory_only' or all((branch.get('execution_allowed_by_default') is False) for branch in branch_templates if isinstance(branch, dict)),
            'advisory_only search branches must not be executable by default',
        ))
        checks.append(check(
            'none_or_kill_branch_policy',
            search_policy_decision.get('recommended_mode') not in {'none', 'kill'} or all((branch.get('execution_allowed_by_default') is False and branch.get('advisory_only') is True) for branch in branch_templates if isinstance(branch, dict)),
            'none/kill modes must have no executable branch templates',
        ))
        checks.append(check(
            'search_policy_decision_human_approval_required',
            search_policy_decision.get('human_approval_required') is True,
            'search_policy_decision.human_approval_required must be true',
        ))
        forbidden_search = set(search_policy_decision.get('forbidden_search') or [])
        checks.append(check(
            'search_policy_decision_forbidden_search_required',
            REQUIRED_FORBIDDEN_SEARCH.issubset(forbidden_search),
            f'search_policy_decision.forbidden_search must contain {sorted(REQUIRED_FORBIDDEN_SEARCH)}',
        ))
        checks.append(check('search_policy_decision_blockers_list', list_value(search_policy_decision.get('search_blockers')), 'search_blockers must be a list'))
        checks.append(check('search_policy_decision_rationale_list', nonempty_list(search_policy_decision.get('selection_rationale')), 'selection_rationale must be nonempty'))

        checks.append(check('research_memo_formula_plain_language_present', nonempty_str(formula_understanding.get('plain_language')), 'formula understanding plain_language missing'))
        checks.append(check('research_memo_formula_break_conditions_present', nonempty_list(formula_understanding.get('what_would_break_it')), 'formula break conditions missing'))
        checks.append(check('research_memo_return_source_present', nonempty_str(return_source.get('primary_hypothesis')) and nonempty_str(return_source.get('explanation')), 'return source analysis missing'))
        checks.append(check('research_memo_metric_verdict_enum', metric_interpretation.get('verdict') in VALID_METRIC_VERDICTS, f"invalid metric verdict: {metric_interpretation.get('verdict')}"))
        checks.append(check('research_memo_metric_evidence_present', bool(metric_evidence_items), 'metric interpretation must include positive, negative, or ambiguity evidence'))
        checks.append(check('research_memo_raw_metrics_present', isinstance(metric_interpretation.get('raw_metrics_used'), dict) and bool(metric_interpretation.get('raw_metrics_used')), 'raw_metrics_used missing from research_memo'))
        checks.append(check('long_side_adoption_policy_present', isinstance(long_side_policy, dict) and bool(long_side_policy), 'long_side_adoption_policy missing from research_memo'))
        policy = long_side_policy.get('policy') if isinstance(long_side_policy.get('policy'), dict) else long_side_policy
        checks.append(check('long_side_policy_no_short_selling', policy.get('no_short_selling') is True, 'Step6 must enforce no_short_selling=true'))
        checks.append(check('long_side_policy_no_direct_decile_trading', policy.get('no_direct_decile_trading') is True, 'Step6 must enforce no_direct_decile_trading=true'))
        checks.append(check('long_side_policy_primary_objective', policy.get('primary_objective') == 'long_side_risk_adjusted_alpha', 'Step6 primary objective must be long_side_risk_adjusted_alpha'))
        checks.append(check('long_side_policy_revision_scope', policy.get('revision_scope') == 'factor_expression_and_step3b_code_only', 'Step6 revision scope must be factor_expression_and_step3b_code_only'))
        factor_business = long_side_policy.get('factor_as_business_review') if isinstance(long_side_policy, dict) else {}
        checks.append(check('long_side_factor_business_review_present', isinstance(factor_business, dict) and bool(factor_business), 'Step6 long_side_adoption_policy.factor_as_business_review missing'))
        thresholds = (factor_business or {}).get('thresholds') if isinstance(factor_business, dict) else {}
        checks.append(check('long_side_sharpe_thresholds_present', isinstance(thresholds, dict) and 'candidate_min_sharpe' in thresholds and 'official_min_sharpe' in thresholds, 'Step6 must record long-side Sharpe thresholds'))
        checks.append(check('research_memo_math_discipline_present', isinstance(math_discipline, dict) and bool(math_discipline), 'math_discipline_review missing from research_memo'))
        checks.append(check(
            'math_mathematical_object_present',
            nonempty_str(
                math_discipline.get('mathematical_object')
                or math_discipline.get('step1_random_object')
            ),
            'math discipline mathematical_object missing',
        ))
        checks.append(check('math_target_statistic_present', nonempty_str(math_discipline.get('target_statistic')), 'math discipline target_statistic missing'))
        checks.append(check('math_information_legality_present', nonempty_str(math_discipline.get('information_set_legality')), 'math discipline information_set_legality missing'))
        checks.append(check('math_spec_stability_present', isinstance(math_discipline.get('spec_stability'), dict) and bool(math_discipline.get('spec_stability')), 'math discipline spec_stability missing'))
        checks.append(check('math_signal_portfolio_gap_present', nonempty_str(math_discipline.get('signal_vs_portfolio_gap')), 'math discipline signal_vs_portfolio_gap missing'))
        checks.append(check('math_long_side_objective_present', isinstance(math_discipline.get('long_side_objective'), dict) and bool(math_discipline.get('long_side_objective')), 'math discipline long_side_objective missing'))
        checks.append(check('math_monotonicity_objective_present', nonempty_str(math_discipline.get('monotonicity_objective')), 'math discipline monotonicity_objective missing'))
        checks.append(check('math_revision_scope_expression_only', math_discipline.get('revision_scope_constraint') == 'factor_expression_and_step3b_code_only', 'math discipline revision_scope_constraint must be expression/code only'))
        checks.append(check('math_revision_operator_present', nonempty_str(math_discipline.get('revision_operator')), 'math discipline revision_operator missing'))
        checks.append(check('math_generalization_argument_present', nonempty_str(math_discipline.get('generalization_argument')), 'math discipline generalization_argument missing'))
        checks.append(check('math_overfit_risk_present', nonempty_list(math_discipline.get('overfit_risk')), 'math discipline overfit_risk missing'))
        checks.append(check('math_kill_criteria_present', nonempty_list(math_discipline.get('kill_criteria')), 'math discipline kill_criteria missing'))
        checks.append(check(
            'math_information_set_legality_not_illegal',
            'illegal' not in information_set_legality,
            f'information_set_legality is blocking: {math_discipline.get("information_set_legality")}',
        ))
        checks.append(check(
            'promote_requires_confirmed_information_set_legality',
            decision != 'promote_official' or (
                'requires_researcher_confirmation' not in information_set_legality
                and 'unknown' not in information_set_legality
            ),
            'official promotion requires confirmed information-set legality, not unknown/requires confirmation',
        ))
        checks.append(check(
            'promote_requires_known_overfit_risk',
            decision != 'promote_official' or not any('unknown' in item or 'not assessed' in item for item in overfit_risk_items),
            'official promotion requires assessed overfit risk',
        ))
        checks.append(check('learning_and_innovation_present', isinstance(learning, dict) and bool(learning), 'learning_and_innovation missing from research_memo'))
        checks.append(check('learning_transferable_patterns_present', nonempty_list(learning.get('transferable_patterns')), 'learning transferable_patterns missing'))
        checks.append(check('learning_anti_patterns_present', nonempty_list(learning.get('anti_patterns')), 'learning anti_patterns missing'))
        checks.append(check('learning_similar_case_lessons_imported_present', nonempty_list(learning.get('similar_case_lessons_imported')), 'learning similar_case_lessons_imported missing; write explicit cold-start note if no cases exist'))
        checks.append(check('learning_idea_seeds_present', nonempty_list(learning.get('innovative_idea_seeds')), 'learning innovative_idea_seeds missing'))
        checks.append(check('learning_reuse_instruction_present', nonempty_list(learning.get('reuse_instruction_for_future_agents')), 'learning reuse_instruction_for_future_agents missing'))
        checks.append(check('experience_chain_present', isinstance(experience_chain, dict) and bool(experience_chain), 'experience_chain missing from Step6 research judgment'))
        checks.append(check('experience_chain_current_attempt_present', isinstance(experience_chain.get('current_attempt'), dict), 'experience_chain.current_attempt missing'))
        checks.append(check('revision_taxonomy_present', isinstance(revision_taxonomy, dict) and bool(revision_taxonomy), 'revision_taxonomy missing from Step6 research judgment'))
        checks.append(check('revision_taxonomy_macro_micro_present', isinstance(revision_taxonomy.get('macro_revision'), dict) and isinstance(revision_taxonomy.get('micro_revision'), dict), 'revision taxonomy must distinguish macro_revision and micro_revision'))
        checks.append(check('revision_taxonomy_expression_present', isinstance(revision_taxonomy.get('expression_revision'), dict), 'revision taxonomy must include expression_revision'))
        portfolio_revision_text = json.dumps(revision_taxonomy.get('portfolio_revision') or {}, ensure_ascii=False).lower()
        checks.append(check(
            'portfolio_revision_forbidden',
            'forbidden' in portfolio_revision_text and 'portfolio_expression_repair' not in portfolio_revision_text,
            'portfolio_revision must be explicitly forbidden; Step6 cannot repair adoption by changing portfolio/decile/short mechanics',
        ))
        checks.append(check('program_search_policy_present', isinstance(program_search_policy, dict) and bool(program_search_policy), 'program_search_policy missing from Step6 research judgment'))
        checks.append(check('program_search_methods_present', REQUIRED_SEARCH_METHODS.issubset(set(method_library.keys())), f'program_search_policy.method_library must include {sorted(REQUIRED_SEARCH_METHODS)}'))
        checks.append(check('diversity_position_present', isinstance(diversity_position, dict) and bool(diversity_position), 'diversity_position missing from Step6 research judgment'))
        checks.append(check(
            'iterate_requires_exploration_branches',
            decision != 'iterate'
            or revision_strategy.get('loop_authorization') != 'approved_for_step3b_handoff'
            or nonempty_list(search_branches),
            'approved iterate decisions must include program_search_policy.recommended_next_search.branches',
        ))
        checks.append(check(
            'iterate_requires_human_approval_gate',
            decision != 'iterate' or bool((program_search_policy.get('recommended_next_search') or {}).get('requires_human_approval_before_code_change')),
            'iterate decisions must keep human approval before code changes',
        ))
        checks.append(check('research_memo_evidence_quality_notes_present', nonempty_list(evidence_quality.get('notes')), 'evidence quality notes missing'))
        checks.append(check('research_memo_failure_regimes_present', nonempty_list(failure_analysis.get('expected_failure_regimes')), 'failure regimes missing'))
        checks.append(check('research_memo_decision_rationale_present', nonempty_list(research_memo.get('decision_rationale')), 'decision rationale missing'))
        checks.append(check('research_memo_next_tests_present', nonempty_list(research_memo.get('next_research_tests')), 'next research tests missing'))
        checks.append(check('knowledge_research_memo_present', isinstance(knowledge.get('research_memo'), dict) and bool(knowledge.get('research_memo')), 'knowledge record must preserve research_memo'))
        checks.append(check(
            'external_researcher_context_present',
            isinstance(research_memo.get('researcher_journal'), dict) or isinstance(research_memo.get('researcher_agent_memo'), dict),
            'Step6 requires full-workflow researcher_journal or Step6 researcher_agent_memo; do not validate pure script-only analysis'
        ))

        if decision == 'promote_official':
            checks.append(check('promote_requires_supportive_metric_verdict', metric_interpretation.get('verdict') == 'supportive', 'official promotion requires supportive metric verdict'))
            checks.append(check(
                'promote_requires_official_ready_long_side',
                long_side_policy.get('long_side_status') == 'official_ready',
                'official promotion requires official-ready risk-adjusted long-side evidence; raw return, short/long-short diagnostics are insufficient',
            ))

        if step6_handoff_path.exists():
            checks.append(check('step6_handoff_exists', True, None))
        else:
            checks.append(check('step6_handoff_optional_fallback', True, None))

        if decision == 'promote_official':
            checks.append(check('official_library_exists', official_library_path.exists(), f'missing {official_library_path}'))
        else:
            checks.append(check('official_library_absent_when_not_promoted', not official_library_path.exists(), 'official library record should not exist'))

        if handoff_authorized:
            checks.extend(iterate_lineage_checks(iteration, step3b_handoff_path))
            checks.append(check('handoff_to_step3b_exists_when_authorized', step3b_handoff_path.exists(), f'missing {step3b_handoff_path}'))
        else:
            checks.append(check('handoff_to_step3b_absent_when_not_authorized', not step3b_handoff_path.exists(), 'handoff_to_step3b requires explicit approved_for_step3b_handoff authorization'))

    warnings = []
    for item in checks:
        if item['status'] == 'BLOCK':
            errors.append(item['error'])
        elif item['status'] == 'WARN':
            warnings.append(item['error'])

    result = 'BLOCK' if errors else 'WARN' if warnings else 'PASS'
    payload = {'report_id': rid, 'result': result, 'checks': checks, 'errors': errors, 'warnings': warnings}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result == 'BLOCK':
        raise SystemExit(1)
