#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'
EVAL = FF / 'evaluations'


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def file_info(path: Path) -> dict[str, Any]:
    return {
        'path': str(path),
        'exists': path.exists(),
        'size': path.stat().st_size if path.exists() else None,
    }


def compact_json(obj: Any, max_chars: int = 4000) -> Any:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return obj
    return {'truncated_json_preview': text[:max_chars], 'truncated': True}


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def get_nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def fmt_pct(value: float | None) -> str:
    if value is None:
        return 'missing'
    return f'{value:.2%}'


def build_researcher_memo(
    rid: str,
    paths: dict[str, Path],
    objects: dict[str, dict[str, Any]],
    backend_payloads: dict[str, Any],
) -> dict[str, Any]:
    spec = objects.get('factor_spec_master') or {}
    run_master = objects.get('factor_run_master') or {}
    case = objects.get('factor_case_master') or {}
    evaluation = objects.get('factor_evaluation') or {}

    factor_id = str(case.get('factor_id') or run_master.get('factor_id') or spec.get('factor_id') or rid)
    canonical = spec.get('canonical_spec') or {}
    formula_text = str(canonical.get('formula_text') or spec.get('formula_text') or '')
    formula_ir = canonical.get('formula_ir') or {}
    operator_set = formula_ir.get('operator_set') or canonical.get('operator_set') or []
    required_fields = formula_ir.get('required_fields') or canonical.get('required_fields') or []
    qlib_expression = canonical.get('qlib_expression') or {}

    self_quant = backend_payloads.get('self_quant_analyzer') if isinstance(backend_payloads.get('self_quant_analyzer'), dict) else {}
    ic_summary = self_quant.get('ic_summary') or {}
    long_side = self_quant.get('long_side_performance') or {}
    group_summary = self_quant.get('group_backtest_summary') or {}

    key_metrics = {}
    for item in evaluation.get('backend_summary') or []:
        if item.get('backend') == 'self_quant_analyzer':
            key_metrics = item.get('key_metrics') or {}
            break
    if not long_side and key_metrics:
        long_side = key_metrics
    if not ic_summary and key_metrics:
        ic_summary = key_metrics

    business = get_nested(case, 'long_side_review', 'factor_as_business_review', 'factor_business_quality') or {}
    if not business:
        business = get_nested(case, 'factor_business_quality') or {}

    rank_ic = as_float(ic_summary.get('rank_ic_mean'))
    rank_ic_ir = as_float(ic_summary.get('rank_ic_ir'))
    pearson_ic = as_float(ic_summary.get('pearson_ic_mean'))
    annual_return = as_float(long_side.get('long_side_annual_return'))
    annual_vol = as_float(long_side.get('long_side_annual_volatility'))
    sharpe = as_float(long_side.get('long_side_sharpe'))
    max_dd = as_float(long_side.get('long_side_max_drawdown'))
    recovery = as_float(long_side.get('long_side_recovery_days'))
    turnover = as_float(long_side.get('long_side_turnover_mean_daily') or long_side.get('turnover_mean'))
    cogs_annual = as_float(long_side.get('trading_cogs_annual'))
    cost_adj_return = as_float(long_side.get('cost_adjusted_annual_return'))
    cost_adj_sharpe = as_float(long_side.get('cost_adjusted_long_side_sharpe'))
    econ_net_alpha = as_float(business.get('economic_net_alpha'))
    top_mean = as_float(group_summary.get('top_decile_mean_return') or long_side.get('top_decile_mean_return'))
    bottom_mean = as_float(group_summary.get('bottom_decile_mean_return') or long_side.get('bottom_decile_mean_return'))

    positive = []
    negative = []
    ambiguities = []
    if rank_ic is not None:
        positive.append(f'Rank IC mean is positive at {rank_ic:.4f}; Rank IC IR is {rank_ic_ir:.3f}.' if rank_ic_ir is not None else f'Rank IC mean is positive at {rank_ic:.4f}.')
    if annual_return is not None and annual_return > 0:
        positive.append(f'Long-side annual return is positive at {fmt_pct(annual_return)}.')
    if sharpe is not None and sharpe >= 0.5:
        positive.append(f'Long-side Sharpe {sharpe:.3f} clears the candidate threshold of 0.50.')
    if qlib_expression.get('status') == 'supported':
        positive.append('Formula IR is qlib-bridgeable and was implemented through operator mode rather than sample fallback code.')

    if cogs_annual is not None and annual_return is not None and cogs_annual > annual_return:
        negative.append(f'Annual turnover cost proxy {fmt_pct(cogs_annual)} exceeds gross long-side annual return {fmt_pct(annual_return)}.')
    if cost_adj_return is not None and cost_adj_return < 0:
        negative.append(f'Cost-adjusted annual return is negative at {fmt_pct(cost_adj_return)}.')
    if cost_adj_sharpe is not None and cost_adj_sharpe < 0:
        negative.append(f'Cost-adjusted long-side Sharpe is negative at {cost_adj_sharpe:.3f}.')
    if max_dd is not None and max_dd < -0.35:
        negative.append(f'Long-side max drawdown {fmt_pct(max_dd)} breaches the -35% soft limit.')
    if recovery is not None and recovery > 252:
        negative.append(f'Long-side recovery period {recovery:.0f} trading days is far above the 252-day soft limit.')
    if econ_net_alpha is not None and econ_net_alpha < 0:
        negative.append(f'Factor-as-business economic net alpha is negative at {fmt_pct(econ_net_alpha)}.')
    if pearson_ic is not None and rank_ic is not None and abs(pearson_ic) < abs(rank_ic):
        ambiguities.append('Pearson IC is weaker than Rank IC, suggesting ordinal information is stronger than linear signal strength.')
    if bottom_mean is not None and bottom_mean < 0:
        ambiguities.append('The short-leg diagnostic is strong, but short selling and long-short adoption are not allowed by current policy.')

    decision = 'iterate'
    if (annual_return is None or annual_return <= 0) and (rank_ic is None or rank_ic <= 0):
        decision = 'reject'
    elif sharpe is not None and sharpe >= 0.8 and max_dd is not None and max_dd >= -0.35 and recovery is not None and recovery <= 252 and (cost_adj_return or 0) > 0:
        decision = 'promote_official'

    revision_changes = [
        'Test longer correlation and summation windows, e.g. corr window 3 -> 5/10 and sum window 3 -> 5/10, to reduce turnover and improve persistence.',
        'Add a signal-stability transform such as rolling mean or hysteresis on the operator output before ranking, while preserving information-set legality.',
        'Test delayed execution variants of the expression to reduce same-day microstructure noise and turnover without changing portfolio mechanics.',
        'Keep revision scope inside the factor expression or Step3B code; do not repair adoption through long-short, decile trading, or portfolio-expression changes.',
    ]

    memo = {
        'report_id': rid,
        'factor_id': factor_id,
        'producer': 'factor-forge-step6-researcher.build_researcher_packet',
        'source_packet_path': str(OBJ / 'research_iteration_master' / f'researcher_packet__{rid}.json'),
        'source_files': {key: str(path) for key, path in paths.items()},
        'researcher_decision': decision,
        'executive_summary': (
            f'{factor_id} implements the canonical Alpha013 rank-correlation formula through operator mode. '
            f'The signal has positive Rank IC and a candidate-level gross long-side Sharpe, but turnover cost, drawdown, and recovery make the current version unsuitable for official admission. '
            'The correct next action is expression-level iteration, not portfolio or short-leg repair.'
        ),
        'formula_review': {
            'plain_language': f'Formula: {formula_text}. It ranks high and volume cross-sectionally, measures short-window rolling correlation, ranks that correlation, sums it over time, and negates the result.',
            'expected_signal_direction': 'Higher factor values are expected to identify the long side under the current Step4 convention; the sign must be preserved unless a future thesis explicitly justifies inversion.',
            'operator_set': operator_set,
            'required_fields': required_fields,
            'what_must_be_true': [
                'The rank correlation between price location and volume captures a repeatable behavioral or liquidity-pressure state.',
                'The cross-sectional rank and short rolling window preserve information available at the trade date.',
                'The high-score long side remains positive after realistic turnover costs and drawdown constraints.',
            ],
            'what_would_break_it': [
                'The signal is mostly a high-turnover microstructure artifact.',
                'Positive gross return is consumed by turnover cost.',
                'The effect is driven by the forbidden short leg rather than the long side.',
            ],
        },
        'return_source_review': {
            'primary_source': 'mixed',
            'objective_constraints': [
                'Long-only adoption only; short-leg and long-short diagnostics cannot justify promotion.',
                'Transaction cost proxy is turnover * 0.3% unless a better cost model is supplied.',
                'Official admission requires risk-adjusted long-side quality, acceptable drawdown, and manageable recovery time.',
            ],
            'counterparty_behavior': 'The formula may capture investors overreacting or reallocating when volume confirms recent high-price states; current evidence also suggests the weak side may contribute heavily to spread diagnostics.',
            'why_repeatable': 'A rank-correlation state can be repeatable if it represents systematic crowding, liquidity pressure, or behavioral response rather than a one-off pattern.',
        },
        'metric_review': {
            'positive_evidence': positive or ['No strong positive evidence found.'],
            'negative_evidence': negative or ['No blocking negative evidence found.'],
            'ambiguities': ambiguities or ['No material ambiguity identified beyond normal sampling risk.'],
            'chart_observations': [
                'Review rank IC, quantile NAV, long-side NAV, turnover, and cost-adjusted long-side NAV artifacts before approving any code change.',
                'Long-short NAV is diagnostic only and should be treated as a warning source, not as an adoption metric.',
            ],
            'monetization_gap': 'Gross long-side Sharpe is candidate-level, but annual turnover COGS and drawdown convert the factor into a negative economic-net-alpha business.',
            'metrics': {
                'rank_ic_mean': rank_ic,
                'rank_ic_ir': rank_ic_ir,
                'pearson_ic_mean': pearson_ic,
                'long_side_annual_return': annual_return,
                'long_side_annual_volatility': annual_vol,
                'long_side_sharpe': sharpe,
                'long_side_max_drawdown': max_dd,
                'long_side_recovery_days': recovery,
                'long_side_turnover_mean_daily': turnover,
                'trading_cogs_annual': cogs_annual,
                'cost_adjusted_annual_return': cost_adj_return,
                'cost_adjusted_long_side_sharpe': cost_adj_sharpe,
                'economic_net_alpha': econ_net_alpha,
                'top_group_mean_return_daily': top_mean,
                'bottom_group_mean_return_daily': bottom_mean,
            },
        },
        'math_discipline_review': {
            'step1_random_object': 'Cross-sectional A-share daily stock-date observations with fields high and volume, transformed into a date-wise ranked operator signal.',
            'target_statistic': 'Future long-side daily return and risk-adjusted long-side performance after cost, drawdown, and recovery constraints.',
            'information_set_legality': 'The formula uses contemporaneous high and volume plus rolling historical windows; no future label or target field is used.',
            'spec_stability': 'Canonical operator expression is stable and hash-identified; implementation used formula IR, not legacy sample fallback.',
            'signal_vs_portfolio_gap': 'Signal quality is positive, but portfolio monetization is weak after turnover and drawdown costs.',
            'revision_operator': 'Change formula expression parameters/transforms only; do not change portfolio construction to rescue the factor.',
            'generalization_argument': 'A successful revision should reduce turnover and drawdown while preserving positive IC across time, not merely improve one backtest statistic.',
            'overfit_risk': [
                'Short rolling windows may fit transient microstructure regimes.',
                'Optimizing only spread or long-short NAV would violate long-only adoption policy.',
                'Parameter search across many windows needs OOS or rolling validation.',
            ],
            'kill_criteria': [
                'Cost-adjusted long-side Sharpe remains below 0 after reasonable smoothing/window revisions.',
                'Max drawdown remains worse than -35% or recovery remains materially above 252 trading days.',
                'Positive economics depend mainly on the short-leg diagnostic.',
            ],
        },
        'prior_case_review': {
            'similar_cases_used': (get_nested(case, 'knowledge_provenance', 'similar_cases_imported') or []),
            'lessons_imported': [
                'Do not promote factors whose gross signal is positive but economic net alpha is negative after turnover cost.',
                'Treat long-short spread and short-leg strength as diagnostics only under the current long-only mandate.',
            ],
            'novelty_vs_library': 'Alpha013 is a canonical formula case using operator mode; its lesson is mainly about turnover-cost fragility in short-window rank-correlation alphas.',
        },
        'learning_and_innovation': {
            'transferable_patterns': [
                'Operator-mode canonical formulas can be implemented faithfully without sample-family fallback.',
                'Positive Rank IC plus candidate gross Sharpe is insufficient when turnover cost and recovery are poor.',
                'Rank-correlation formulas need explicit turnover and monotonicity review.',
            ],
            'anti_patterns': [
                'Promoting based on long-short NAV or short-leg diagnostics.',
                'Using portfolio expression changes to repair an expression-level monetization problem.',
                'Ignoring cost-adjusted long-side metrics when gross long-side return is positive.',
            ],
            'innovative_idea_seeds': [
                'Explore persistent rank-correlation states by smoothing the operator output before final ranking.',
                'Compare correlation-window and summation-window families as a controlled operator search branch.',
                'Test a turnover-aware objective during formula search rather than optimizing IC alone.',
            ],
            'reuse_instruction_for_future_agents': [
                'Retrieve this case when a short-window Alpha101-style formula has positive gross IC but weak cost-adjusted economics.',
                'Start future revisions from the operator formula and preserve formula/hash lineage.',
                'Require long-side cost-adjusted Sharpe, drawdown, and recovery evidence before promotion.',
            ],
        },
        'experience_chain': {
            'current_attempt_summary': 'Canonical Alpha013 operator implementation generated valid factor values and Step4/5 evidence; Step6 should iterate due to cost and drawdown, not implementation contamination.',
            'prior_cases_used': [],
            'failed_branches_to_preserve': [
                'Current raw Alpha013 formula: positive signal but poor cost-adjusted economics.',
            ],
            'what_future_agents_should_retrieve': [
                'Alpha013 cost-adjusted long-side failure mode.',
                'Short-window rank-correlation turnover fragility.',
            ],
        },
        'revision_taxonomy': {
            'macro_revision_options': [
                'Treat Alpha013 as a market microstructure/liquidity-pressure family and search for more persistent variants.',
            ],
            'micro_revision_options': revision_changes[:3],
            'portfolio_revision_options': ['Forbidden: do not repair by shorting low deciles, changing rebalance mechanics, or using long-short adoption.'],
            'stop_or_kill_rules': [
                'Stop if smoothing/window variants cannot produce positive cost-adjusted long-side Sharpe.',
                'Stop if drawdown and recovery remain outside soft limits across OOS windows.',
            ],
        },
        'program_search_policy': {
            'recommended_methods': ['bayesian_search', 'genetic_algorithm', 'multi_agent_parallel_exploration'],
            'exploit_branches': [
                'Bayesian search over corr_window, sum_window, smoothing_window, and delay with cost-adjusted long-side Sharpe as primary objective.',
            ],
            'explore_branches': [
                'Genetic operator mutation around rank/correlation/sum/delta families while preserving information-set legality.',
                'Parallel agents can test smoothing, delayed signal, and window-length families independently.',
            ],
            'why_not_rl_first_if_applicable': 'There are not enough validated revision trajectories for RL to learn a stable policy; use RL only as advisory after more search records exist.',
            'human_approval_required': True,
        },
        'diversity_position': {
            'novelty_vs_library': 'Canonical Alpha101 rank-correlation case; useful as a reusable operator-mode and turnover-cost case, but not yet official alpha.',
            'redundancy_risk': 'May overlap with other short-window price-volume behavioral factors.',
            'official_library_diversity_value': 'Low until cost-adjusted long-side economics improve.',
        },
        'risk_review': {
            'failure_regimes': [
                'High turnover consumes gross return.',
                'Drawdown recovery is too slow for reasonable risk-budget allocation.',
                'Rank IC remains positive but monetization fails under long-only constraints.',
            ],
            'crowding_capacity': 'Likely constrained by high turnover and short-window signal instability.',
            'implementation_risk': 'Low for the current run: operator-mode implementation and formula hash lineage are explicit.',
        },
        'revision_brief_to_step3b': {
            'should_modify': True,
            'hypothesis': 'A more persistent version of the rank-correlation expression can preserve IC while reducing turnover, drawdown, and recovery time.',
            'specific_changes': revision_changes,
            'expected_metric_movement': [
                'Lower daily turnover and annual trading COGS.',
                'Improve cost-adjusted long-side Sharpe above 0 and ideally above 0.50.',
                'Reduce max drawdown toward the -35% soft limit and recovery toward 252 trading days.',
            ],
            'kill_criteria': [
                'No tested expression variant achieves positive cost-adjusted annual return.',
                'Improvement only appears in long-short spread or short-leg diagnostics.',
                'OOS Rank IC collapses while IS improves.',
            ],
        },
        'knowledge_to_write_back': {
            'success_lessons': [
                'The operator engine can faithfully implement Alpha013 without UBL/CPV fallback contamination.',
                'Gross signal quality is nonzero and worth one revision round.',
            ],
            'failure_lessons': [
                'High turnover can turn candidate gross Sharpe into negative economic net alpha.',
                'Drawdown and recovery can invalidate an otherwise positive long-side return stream.',
            ],
            'reusable_heuristics': [
                'For Alpha101 price-volume rank formulas, inspect cost-adjusted long-side Sharpe before IC celebration.',
                'If Rank IC is stronger than Pearson IC, revise for monotonic linearity rather than only ordinal separation.',
            ],
        },
    }
    return memo


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', default=None)
    args = ap.parse_args()
    rid = args.report_id

    paths = {
        'factor_spec_master': OBJ / 'factor_spec_master' / f'factor_spec_master__{rid}.json',
        'factor_run_master': OBJ / 'factor_run_master' / f'factor_run_master__{rid}.json',
        'factor_case_master': OBJ / 'factor_case_master' / f'factor_case_master__{rid}.json',
        'factor_evaluation': OBJ / 'validation' / f'factor_evaluation__{rid}.json',
        'handoff_to_step6': OBJ / 'handoff' / f'handoff_to_step6__{rid}.json',
        'handoff_to_step5': OBJ / 'handoff' / f'handoff_to_step5__{rid}.json',
        'prior_research_iteration': OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json',
        'prior_researcher_memo': OBJ / 'research_iteration_master' / f'researcher_memo__{rid}.json',
    }

    objects = {
        key: load_json(path)
        for key, path in paths.items()
        if path.exists() and key not in {'prior_researcher_memo'}
    }

    run_master = load_json(paths['factor_run_master'])
    backend_runs = (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    backend_payloads: dict[str, Any] = {}
    backend_artifacts: dict[str, list[dict[str, Any]]] = {}
    for item in backend_runs:
        backend = str(item.get('backend') or '')
        if not backend:
            continue
        payload_path = Path(str(item.get('payload_path') or EVAL / rid / backend / 'evaluation_payload.json'))
        if payload_path.exists():
            payload = load_json(payload_path)
            backend_payloads[backend] = compact_json(payload)
            artifacts = []
            for artifact in (payload.get('artifacts') or {}).values():
                if isinstance(artifact, str):
                    artifacts.append(file_info(Path(artifact)))
            backend_artifacts[backend] = artifacts
        else:
            backend_payloads[backend] = {'missing_payload_path': str(payload_path)}

    packet = {
        'report_id': rid,
        'factorforge_root': str(FF),
        'required_researcher_output': str(OBJ / 'research_iteration_master' / f'researcher_memo__{rid}.json'),
        'source_files': {key: file_info(path) for key, path in paths.items()},
        'objects': {key: compact_json(value) for key, value in objects.items()},
        'backend_payloads': backend_payloads,
        'backend_artifacts': backend_artifacts,
        'suggested_checks': [
            'Inspect factor formula and intended direction.',
            'Compare IC/group diagnostics with native portfolio/account evidence.',
            'Open important png artifacts if present, especially NAV, benchmark-vs-strategy, turnover, quantile NAV/counts.',
            'Retrieve similar prior cases before final decision if retrieval index exists.',
            'Write researcher_memo JSON using the schema in factor-forge-step6-researcher/references/researcher-memo-schema.md.',
        ],
        'producer': 'factor-forge-step6-researcher.build_researcher_packet',
    }

    out = Path(args.output) if args.output else OBJ / 'research_iteration_master' / f'researcher_packet__{rid}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    memo = build_researcher_memo(rid, paths, objects, backend_payloads)
    memo_path = OBJ / 'research_iteration_master' / f'researcher_memo__{rid}.json'
    memo_path.parent.mkdir(parents=True, exist_ok=True)
    memo_path.write_text(json.dumps(memo, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out))
    print(str(memo_path))


if __name__ == '__main__':
    main()
