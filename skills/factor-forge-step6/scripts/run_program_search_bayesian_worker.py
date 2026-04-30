#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import load_json, resolve_factorforge_context, update_json_locked, write_json_atomic
from factor_factory.data_access import build_forward_return_frame, infer_signal_column, normalize_trade_date_series

import numpy as np
import pandas as pd

try:  # Optional. The worker remains useful on a minimal EC2 image without sklearn.
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import Matern, WhiteKernel
    from sklearn.preprocessing import OneHotEncoder
except Exception:  # pragma: no cover - dependency availability varies by host
    GaussianProcessRegressor = None
    Matern = None
    WhiteKernel = None
    OneHotEncoder = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


CTX = resolve_factorforge_context()
FF = CTX.factorforge_root
OBJ = CTX.objects_root
RUNS = CTX.runs_root


def write_json(path: Path, data: dict[str, Any]) -> None:
    write_json_atomic(path, data)
    print(f'[WRITE] {path}')


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding='utf-8')
    print(f'[WRITE] {path}')


def resolve_path(raw: str | None) -> Path | None:
    return CTX.remap_legacy_path(raw)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        out = float(value)
        if not math.isfinite(out):
            return None
        return out
    except Exception:
        return None


def series_stats(series: pd.Series) -> dict[str, float | None]:
    valid = series.dropna()
    if valid.empty:
        return {'mean': None, 'std': None, 'ir': None, 'annualized_sharpe': None}
    std = float(valid.std())
    mean = float(valid.mean())
    daily_ir = safe_float(mean / std) if std else None
    return {
        'mean': safe_float(mean),
        'std': safe_float(std),
        'ir': daily_ir,
        'annualized_sharpe': safe_float((daily_ir or 0.0) * math.sqrt(252.0)) if daily_ir is not None else None,
    }


def drawdown_stats(returns: pd.Series) -> dict[str, float | int | None]:
    valid = returns.dropna()
    if valid.empty:
        return {'max_drawdown': None, 'recovery_days': None, 'final_nav': None}
    nav = (1.0 + valid).cumprod()
    running_max = nav.cummax()
    drawdown = nav / running_max - 1.0
    max_drawdown = safe_float(drawdown.min())
    underwater = drawdown < 0
    longest = 0
    current = 0
    for flag in underwater:
        if bool(flag):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return {
        'max_drawdown': max_drawdown,
        'recovery_days': int(longest),
        'final_nav': safe_float(nav.iloc[-1]),
    }


def find_branch(plan: dict[str, Any], branch_id: str) -> dict[str, Any]:
    for branch in plan.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            return branch
    raise SystemExit(f'BAYESIAN_WORKER_INVALID: branch_id not found in plan: {branch_id}')


def find_taskbook(report_id: str, branch_id: str) -> dict[str, Any]:
    path = CTX.search_branch_taskbook_path(report_id, branch_id)
    if not path.exists():
        raise SystemExit(f'BAYESIAN_WORKER_INVALID: missing approved branch taskbook {path}')
    return load_json(path)


def locate_factor_values(report_id: str, handoff: dict[str, Any]) -> Path:
    output_paths = as_list((handoff.get('first_run_outputs') or {}).get('output_paths'))
    for raw in output_paths:
        path = resolve_path(str(raw))
        if path and path.exists() and path.suffix in {'.parquet', '.csv'}:
            return path
    for suffix in ['parquet', 'csv']:
        path = CTX.factor_values_path(report_id, suffix)
        if path.exists():
            return path
    raise FileNotFoundError('missing baseline factor_values from handoff_to_step4.first_run_outputs or runs directory')


def locate_daily_snapshot(report_id: str, handoff: dict[str, Any]) -> Path:
    local_paths = handoff.get('local_input_paths') or {}
    daily_path = resolve_path(local_paths.get('daily_df_csv'))
    if daily_path and daily_path.exists():
        return daily_path
    path = CTX.step3a_daily_input_path(report_id)
    if path.exists():
        return path
    raise FileNotFoundError('missing Step3A daily snapshot; Bayesian worker reads snapshots but does not build clean data')


def load_frame(path: Path) -> pd.DataFrame:
    if path.suffix == '.parquet':
        return pd.read_parquet(path)
    if path.suffix == '.csv':
        return pd.read_csv(path)
    raise ValueError(f'unsupported data file: {path}')


def default_search_space(branch: dict[str, Any]) -> dict[str, list[Any]]:
    raw = branch.get('search_space') or branch.get('parameters') or {}
    if isinstance(raw, dict) and raw:
        normalized: dict[str, list[Any]] = {}
        for key, value in raw.items():
            values = value.get('values') if isinstance(value, dict) else value
            normalized[str(key)] = as_list(values)
        return normalized
    return {
        'direction': [1, -1],
        'delay': [0, 1],
        'smooth_window': [1, 3, 5],
        'winsorize_q': [0.0, 0.01, 0.025],
        'cross_section_transform': ['rank', 'zscore'],
    }


def encode_params(params: dict[str, Any], search_space: dict[str, list[Any]]) -> list[float]:
    vec: list[float] = []
    for key in sorted(search_space):
        values = search_space[key]
        value = params.get(key)
        if all(isinstance(v, (int, float)) for v in values):
            min_v = min(float(v) for v in values)
            max_v = max(float(v) for v in values)
            denom = max(max_v - min_v, 1e-12)
            vec.append((float(value) - min_v) / denom)
        else:
            for option in values:
                vec.append(1.0 if value == option else 0.0)
    return vec


def parameter_space_size(search_space: dict[str, list[Any]]) -> int:
    size = 1
    for values in search_space.values():
        size *= max(1, len(values))
    return size


def select_trials(search_space: dict[str, list[Any]], max_trials: int, seed: int) -> tuple[list[dict[str, Any]], str]:
    keys = sorted(search_space)
    total_size = parameter_space_size(search_space)
    rng = random.Random(seed)
    if total_size <= 4096:
        import itertools
        grid = [dict(zip(keys, combo)) for combo in itertools.product(*(search_space[key] for key in keys))]
        rng.shuffle(grid)
        if len(grid) <= max_trials:
            return grid, 'exhaustive_grid'
        pool_size = min(len(grid), max(max_trials * 8, max_trials))
        return grid[:pool_size], 'bayesian_sequential_gp' if GaussianProcessRegressor is not None else 'bounded_random_fallback'

    # Large spaces must never materialize the full Cartesian product. Sample a bounded,
    # unique candidate pool and let GP rerank within that pool after early observations.
    pool_size = min(total_size, max(max_trials * 8, 128), 512)
    seen: set[tuple[Any, ...]] = set()
    grid: list[dict[str, Any]] = []
    attempts = 0
    max_attempts = pool_size * 50
    while len(grid) < pool_size and attempts < max_attempts:
        attempts += 1
        combo = tuple(rng.choice(search_space[key]) for key in keys)
        if combo in seen:
            continue
        seen.add(combo)
        grid.append(dict(zip(keys, combo)))
    rng.shuffle(grid)
    return grid, 'bayesian_sequential_gp_sampled_pool' if GaussianProcessRegressor is not None else 'bounded_random_fallback_sampled_pool'


def rank_remaining_by_gp(
    completed: list[dict[str, Any]],
    remaining: list[dict[str, Any]],
    search_space: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    if GaussianProcessRegressor is None or Matern is None or WhiteKernel is None:
        return remaining
    scored = [item for item in completed if item.get('score') is not None]
    if len(scored) < 4 or not remaining:
        return remaining
    x = np.array([encode_params(item['params'], search_space) for item in scored], dtype=float)
    y = np.array([float(item['score']) for item in scored], dtype=float)
    kernel = Matern(nu=2.5) + WhiteKernel(noise_level=1e-5)
    model = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=0)
    try:
        model.fit(x, y)
        xr = np.array([encode_params(params, search_space) for params in remaining], dtype=float)
        mean, std = model.predict(xr, return_std=True)
        best = float(np.max(y))
        std = np.maximum(std, 1e-9)
        improvement = mean - best
        z = improvement / std
        pdf = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
        cdf = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))
        # Standard Expected Improvement is less brittle than a hand-rolled
        # UCB/EI blend when an early best point is an outlier.
        acquisition = improvement * cdf + std * pdf
        order = np.argsort(-acquisition)
        return [remaining[int(i)] for i in order]
    except Exception:
        return remaining


def strict_market_calendar_shift(
    working: pd.DataFrame,
    values: pd.Series,
    delay: int,
) -> pd.Series:
    """Shift by market-calendar rows, not merely by each stock's observed rows.

    If a stock is absent on the exact prior market date required by `delay`,
    the delayed value is invalidated instead of carrying a stale pre-suspension
    observation across a missing interval.
    """
    if delay <= 0:
        return values
    market_dates = pd.Index(sorted(working['datetime'].dropna().unique()))
    date_to_pos = pd.Series(np.arange(len(market_dates)), index=market_dates)
    current_pos = working['datetime'].map(date_to_pos)
    expected_prior_pos = current_pos - delay
    expected_prior = pd.Series(pd.NaT, index=working.index, dtype='datetime64[ns]')
    valid_expected = expected_prior_pos >= 0
    if valid_expected.any():
        expected_prior.loc[valid_expected] = market_dates.take(expected_prior_pos.loc[valid_expected].astype(int))

    grouped = values.groupby(working['ts_code'], sort=False)
    shifted = grouped.shift(delay)
    actual_prior = working['datetime'].groupby(working['ts_code'], sort=False).shift(delay)
    valid = actual_prior.eq(expected_prior)
    return shifted.where(valid)


def apply_transform(factor_df: pd.DataFrame, signal_col: str, params: dict[str, Any]) -> pd.DataFrame:
    working = factor_df[['ts_code', 'trade_date', signal_col]].copy()
    working['datetime'] = normalize_trade_date_series(working['trade_date'])
    working = working.sort_values(['ts_code', 'datetime'])
    values = pd.to_numeric(working[signal_col], errors='coerce')

    delay = int(params.get('delay', 0) or 0)
    if delay > 0:
        values = strict_market_calendar_shift(working, values, delay)

    smooth_window = int(params.get('smooth_window', 1) or 1)
    if smooth_window > 1:
        values = (
            values.groupby(working['ts_code'], sort=False)
            .rolling(smooth_window, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )

    direction = int(params.get('direction', 1) or 1)
    values = values * direction
    working['candidate_signal'] = values

    q = float(params.get('winsorize_q', 0.0) or 0.0)
    if q > 0:
        def _clip(s: pd.Series) -> pd.Series:
            lo = s.quantile(q)
            hi = s.quantile(1.0 - q)
            return s.clip(lo, hi)
        working['candidate_signal'] = working.groupby('trade_date', sort=False)['candidate_signal'].transform(_clip)

    transform = str(params.get('cross_section_transform') or 'raw')
    if transform == 'rank':
        working['candidate_signal'] = working.groupby('trade_date', sort=False)['candidate_signal'].rank(pct=True)
    elif transform == 'zscore':
        def _zscore(s: pd.Series) -> pd.Series:
            std = s.std()
            if not std or pd.isna(std):
                return s * np.nan
            return (s - s.mean()) / std
        working['candidate_signal'] = working.groupby('trade_date', sort=False)['candidate_signal'].transform(_zscore)
    elif transform != 'raw':
        raise ValueError(f'unsupported cross_section_transform={transform}')

    return working[['ts_code', 'trade_date', 'datetime', 'candidate_signal']]


def assign_quantile_labels(series: pd.Series, groups: int, min_count: int = 20) -> pd.Series:
    valid = series.dropna()
    if valid.empty or len(valid) < min_count:
        return pd.Series(index=series.index, dtype='float64')
    bucket_count = min(groups, int(valid.nunique()), len(valid))
    if bucket_count < 2:
        return pd.Series(index=series.index, dtype='float64')
    labels = pd.qcut(valid.rank(method='first'), q=bucket_count, labels=False, duplicates='drop') + 1
    return labels.reindex(series.index)


def evaluate_candidate(candidate: pd.DataFrame, daily_eval: pd.DataFrame) -> dict[str, Any]:
    merged = candidate.rename(columns={'ts_code': 'code'}).merge(
        daily_eval[['datetime', 'code', 'future_return_1d']],
        on=['datetime', 'code'],
        how='left',
    ).dropna(subset=['candidate_signal', 'future_return_1d'])
    if merged.empty:
        return {'status': 'failed', 'failure_reason': 'EMPTY_MERGED_FRAME', 'score': None}

    metric_cols = ['candidate_signal', 'future_return_1d']
    rank_ic = merged.groupby('datetime', sort=True)[metric_cols].apply(
        lambda df: df['candidate_signal'].corr(df['future_return_1d'], method='spearman')
    )
    pearson_ic = merged.groupby('datetime', sort=True)[metric_cols].apply(
        lambda df: df['candidate_signal'].corr(df['future_return_1d'], method='pearson')
    )

    grouped_source = merged.copy()
    grouped_source['group_id'] = grouped_source.groupby('datetime', sort=True)['candidate_signal'].transform(
        lambda s: assign_quantile_labels(s, groups=10)
    )
    grouped_source = grouped_source.dropna(subset=['group_id']).assign(group_id=lambda df: df['group_id'].astype(int))
    quantile_returns = grouped_source.groupby(['datetime', 'group_id'], sort=True)['future_return_1d'].mean().unstack('group_id')
    counts = grouped_source.groupby(['datetime', 'group_id'], sort=True).size().unstack('group_id')

    if quantile_returns.shape[1] >= 2:
        spread = (quantile_returns.iloc[:, -1] - quantile_returns.iloc[:, 0]).dropna()
    else:
        spread = pd.Series(dtype='float64')
    ls_stats = series_stats(spread)
    rank_stats = series_stats(rank_ic)
    pearson_stats = series_stats(pearson_ic)
    coverage_by_day = merged.groupby('datetime', sort=True)['code'].count()

    rank_ir = rank_stats.get('ir') or 0.0
    spread_bps = (ls_stats.get('mean') or 0.0) * 10000.0
    top_group_return = quantile_returns.iloc[:, -1].dropna() if quantile_returns.shape[1] >= 1 else pd.Series(dtype='float64')
    top_stats = series_stats(top_group_return)
    top_drawdown = drawdown_stats(top_group_return)
    top_bps = (top_stats.get('mean') or 0.0) * 10000.0
    top_sharpe = top_stats.get('annualized_sharpe') or 0.0
    max_drawdown = top_drawdown.get('max_drawdown') or 0.0
    drawdown_penalty = max(0.0, abs(float(max_drawdown)) - 0.20)
    breadth_penalty = 0.0 if (coverage_by_day.mean() if not coverage_by_day.empty else 0) >= 30 else 0.25

    monotonicity = None
    if not quantile_returns.empty and quantile_returns.shape[1] >= 3:
        group_means = quantile_returns.mean(axis=0).dropna()
        if len(group_means) >= 3:
            mono_corr = pd.Series(range(len(group_means)), index=group_means.index).corr(group_means, method='spearman')
            monotonicity = safe_float(mono_corr)
    mono_component = 0.0 if monotonicity is None else max(min(float(monotonicity), 1.0), -1.0)
    score = (
        0.45 * max(min(float(top_sharpe), 3.0), -3.0)
        + 0.20 * rank_ir
        + 0.20 * mono_component
        + 0.10 * max(min(top_bps / 5.0, 2.0), -2.0)
        - 0.50 * drawdown_penalty
        - breadth_penalty
    )

    return {
        'status': 'completed',
        'score': safe_float(score),
        'rank_ic': rank_stats,
        'pearson_ic': pearson_stats,
        'long_short': {
            'mean': ls_stats.get('mean'),
            'std': ls_stats.get('std'),
            'ir': ls_stats.get('ir'),
            'spread_bps_per_day': safe_float(spread_bps),
            'observation_count': int(spread.dropna().shape[0]),
        },
        'long_side': {
            'top_group_mean': top_stats.get('mean'),
            'top_group_std': top_stats.get('std'),
            'top_group_sharpe': top_stats.get('annualized_sharpe'),
            'top_group_bps_per_day': safe_float(top_bps),
            'volatility_drag_daily': safe_float(-0.5 * float(top_stats.get('std') or 0.0) ** 2) if top_stats.get('std') is not None else None,
            'geometric_growth_proxy_daily': safe_float(float(top_stats.get('mean') or 0.0) - 0.5 * float(top_stats.get('std') or 0.0) ** 2) if top_stats.get('std') is not None else None,
            'max_drawdown': top_drawdown.get('max_drawdown'),
            'recovery_days': top_drawdown.get('recovery_days'),
            'final_nav': top_drawdown.get('final_nav'),
            'observation_count': int(top_group_return.dropna().shape[0]),
            'adoption_basis': 'primary',
            'adoption_objective': 'long_side_risk_adjusted_alpha',
        },
        'coverage': {
            'merged_rows': int(len(merged)),
            'date_count': int(coverage_by_day.shape[0]),
            'avg_cross_section': safe_float(coverage_by_day.mean()),
            'min_cross_section': int(coverage_by_day.min()) if not coverage_by_day.empty else None,
            'max_cross_section': int(coverage_by_day.max()) if not coverage_by_day.empty else None,
            'group_count_observed': int(quantile_returns.shape[1]),
            'min_group_count': int(counts.min().min()) if not counts.empty else None,
        },
        'monotonicity': monotonicity,
    }


def write_best_candidate(
    out_dir: Path,
    report_id: str,
    best_trial: dict[str, Any],
    factor_df: pd.DataFrame,
    signal_col: str,
) -> list[str]:
    if best_trial.get('status') != 'completed':
        return []
    candidate = apply_transform(factor_df, signal_col, best_trial['params'])
    out = candidate[['ts_code', 'trade_date', 'candidate_signal']].rename(columns={'candidate_signal': f'candidate_{signal_col}'})
    pq = out_dir / f'candidate_factor_values__{report_id}__{best_trial["trial_id"]}.parquet'
    csv = out_dir / f'candidate_factor_values__{report_id}__{best_trial["trial_id"]}.csv'
    pq.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(pq, index=False)
    out.to_csv(csv, index=False)
    return [str(pq), str(csv)]


def update_ledger(report_id: str, branch_id: str, result_path: Path, status: str, outcome: str) -> None:
    ledger_path = CTX.object_path('search_branch_ledger', report_id)
    if not ledger_path.exists():
        return
    def _update(ledger: dict[str, Any]) -> dict[str, Any]:
        for branch in ledger.get('branches') or []:
            if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
                branch['status'] = status
                branch['outcome'] = outcome
                branch['last_event'] = 'bayesian_worker_result_recorded'
                branch['result_path'] = str(result_path)
                branch['updated_at_utc'] = utc_now()
                break
        return ledger
    update_json_locked(ledger_path, _update)
    print(f'[WRITE] {ledger_path}')


def build_result(
    report_id: str,
    branch_id: str,
    branch: dict[str, Any],
    taskbook: dict[str, Any],
    trials: list[dict[str, Any]],
    best_trial: dict[str, Any] | None,
    artifacts: list[str],
    failure_signatures: list[str],
    search_space: dict[str, list[Any]],
    selection_mode: str,
    source_paths: dict[str, str | None],
) -> dict[str, Any]:
    completed = [trial for trial in trials if trial.get('status') == 'completed' and trial.get('score') is not None]
    improved = False
    if best_trial:
        # V1 is conservative: improvement must be long-side risk-adjusted,
        # not short/long-short driven and not raw-return-only.
        long_side = best_trial.get('metrics', {}).get('long_side', {})
        improved = bool(
            (best_trial.get('score') or 0) > 0
            and (long_side.get('top_group_bps_per_day') or 0) > 0
            and (long_side.get('top_group_sharpe') or 0) >= 0.50
            and (long_side.get('max_drawdown') is None or (long_side.get('max_drawdown') or 0) >= -0.35)
        )
    status = 'completed' if completed else 'blocked'
    outcome = 'improved' if improved else ('not_improved' if completed else 'bug_found')
    recommendation = 'needs_human_review' if improved else ('keep_exploring' if completed else 'repair_workflow_first')
    summary = (
        f'Bayesian/local parameter worker evaluated {len(completed)}/{len(trials)} trials. '
        f'Best trial={best_trial.get("trial_id") if best_trial else None}, improved={improved}. '
        'This branch is advisory and does not canonicalize Step3B.'
    )
    return {
        'report_id': report_id,
        'branch_id': branch_id,
        'parent_plan_path': taskbook.get('parent_plan_path'),
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
            'return_source_preserved_or_challenged': 'preserved_current_thesis_parameters_only',
            'market_structure_lesson': 'Parameter sensitivity was tested without changing the economic thesis or information set.',
            'knowledge_lesson': 'Use Bayesian/local search only after Step6 has defined a bounded, thesis-preserving search space.',
            'anti_pattern_observed': None if completed else 'parameter_search_without_required_factor_or_daily_snapshot',
            'overfit_assessment': 'bounded_parameter_search; requires OOS/rolling confirmation before canonicalization',
            'falsification_result': 'not_falsified_by_parameter_search' if improved else 'no_parameter_setting_produced_clear_improvement',
        },
        'evidence': {
            'metric_delta': {
                'best_score': best_trial.get('score') if best_trial else None,
                'best_trial_id': best_trial.get('trial_id') if best_trial else None,
                'best_params': best_trial.get('params') if best_trial else None,
                'primary_improvement_target': 'long_side_sharpe_with_drawdown_recovery_guardrails',
                'completed_trials': len(completed),
                'total_trials': len(trials),
            },
            'step4_artifacts': artifacts,
            'validator_results': {},
            'failure_signatures': failure_signatures,
            'notes': [
                'Worker writes only isolated branch artifacts.',
                'It does not mutate shared clean data or canonical Step3B.',
                'Selection score is a research heuristic, not a promotion decision.',
            ],
        },
        'bayesian_search': {
            'version': 'bayesian_parameter_worker_v1',
            'selection_mode': selection_mode,
            'search_space': search_space,
            'parameter_space_size': parameter_space_size(search_space),
            'trial_count': len(trials),
            'completed_trial_count': len(completed),
            'best_trial': best_trial,
            'trials': trials,
            'algorithm_note': 'Uses Gaussian-process acquisition when sklearn is available; otherwise bounded randomized coverage. In both modes Step6 thesis and approval gate control the search.',
        },
        'source_paths': source_paths,
        'human_approval_required_before_canonicalization': True,
        'producer': 'program_search_bayesian_worker_v1',
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--branch-id', required=True)
    ap.add_argument('--max-trials', type=int, default=None)
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()

    rid = args.report_id
    branch_id = args.branch_id
    plan_path = CTX.object_path('program_search_plan', rid)
    handoff_path = CTX.object_path('handoff_to_step4', rid)
    if not plan_path.exists():
        raise SystemExit(f'BAYESIAN_WORKER_INVALID: missing program search plan {plan_path}')
    if not handoff_path.exists():
        raise SystemExit(f'BAYESIAN_WORKER_INVALID: missing handoff_to_step4 {handoff_path}')

    plan = load_json(plan_path)
    branch = find_branch(plan, branch_id)
    taskbook = find_taskbook(rid, branch_id)
    if ((branch.get('approval') or {}).get('status')) != 'approved':
        raise SystemExit('BAYESIAN_WORKER_APPROVAL_REQUIRED: branch must be approved before execution')
    if branch.get('search_mode') != 'bayesian_search' and branch.get('branch_role') != 'exploit':
        raise SystemExit('BAYESIAN_WORKER_INVALID: this worker only runs approved bayesian_search/exploit branches')

    branch_root = Path(taskbook.get('branch_root') or (FF / 'research_branches' / rid / branch_id))
    trial_dir = branch_root / 'evaluations' / 'bayesian_parameter_search'
    artifact_dir = branch_root / 'generated_code'
    handoff = load_json(handoff_path)

    failure_signatures: list[str] = []
    trials: list[dict[str, Any]] = []
    artifacts: list[str] = []
    best_trial: dict[str, Any] | None = None
    source_paths: dict[str, str | None] = {'factor_values': None, 'daily_snapshot': None}
    search_space = default_search_space(branch)
    max_trials = args.max_trials or int(((branch.get('budget') or {}).get('max_trials')) or 12)
    max_trials = max(1, min(max_trials, 64))
    selection_queue, selection_mode = select_trials(search_space, max_trials=max_trials, seed=args.seed)

    try:
        factor_path = locate_factor_values(rid, handoff)
        daily_path = locate_daily_snapshot(rid, handoff)
        source_paths = {'factor_values': str(factor_path), 'daily_snapshot': str(daily_path)}
        factor_df = load_frame(factor_path)
        signal_col = infer_signal_column(factor_df)
        required = {'ts_code', 'trade_date', signal_col}
        missing = required.difference(factor_df.columns)
        if missing:
            raise ValueError(f'factor_values missing columns: {sorted(missing)}')
        daily_df = pd.read_csv(daily_path, usecols=['ts_code', 'trade_date', 'close', 'pct_chg'])
        daily_eval = build_forward_return_frame(
            daily_df.rename(columns={'ts_code': 'code'}),
            instrument_col='code',
            date_col='trade_date',
            price_col='close',
            horizon=1,
        )

        completed_trials: list[dict[str, Any]] = []
        remaining = list(selection_queue)
        while remaining and len(trials) < max_trials:
            params = remaining.pop(0)
            trial_id = f'trial{len(trials) + 1:03d}'
            trial_path = trial_dir / f'bayesian_trial__{rid}__{branch_id}__{trial_id}.json'
            try:
                candidate = apply_transform(factor_df, signal_col, params)
                metrics = evaluate_candidate(candidate, daily_eval)
                trial = {
                    'trial_id': trial_id,
                    'params': params,
                    'status': metrics.get('status'),
                    'score': metrics.get('score'),
                    'metrics': metrics,
                    'created_at_utc': utc_now(),
                }
            except Exception as exc:  # Keep failed trials; they are knowledge too.
                trial = {
                    'trial_id': trial_id,
                    'params': params,
                    'status': 'failed',
                    'score': None,
                    'failure_reason': f'{type(exc).__name__}: {exc}',
                    'created_at_utc': utc_now(),
                }
                failure_signatures.append(f'{trial_id}: {trial["failure_reason"]}')
            write_json(trial_path, trial)
            artifacts.append(str(trial_path))
            trials.append(trial)
            if trial.get('status') == 'completed':
                completed_trials.append(trial)
                if best_trial is None or (trial.get('score') or -1e9) > (best_trial.get('score') or -1e9):
                    best_trial = trial
            # Re-rank remaining candidates after enough evidence when sklearn is available.
            remaining = rank_remaining_by_gp(completed_trials, remaining, search_space)

        if best_trial:
            artifacts.extend(write_best_candidate(artifact_dir, rid, best_trial, factor_df, signal_col))
    except Exception as exc:
        failure_signatures.append(f'{type(exc).__name__}: {exc}')

    result = build_result(
        report_id=rid,
        branch_id=branch_id,
        branch=branch,
        taskbook=taskbook,
        trials=trials,
        best_trial=best_trial,
        artifacts=artifacts,
        failure_signatures=failure_signatures,
        search_space=search_space,
        selection_mode=selection_mode,
        source_paths=source_paths,
    )
    result_path = CTX.search_branch_result_path(rid, branch_id)
    write_json(result_path, result)
    summary_path = trial_dir / 'SUMMARY.md'
    write_text(summary_path, '# Bayesian Parameter Search Summary\n\n' + json.dumps(result['evidence']['metric_delta'], ensure_ascii=False, indent=2) + '\n')
    update_ledger(rid, branch_id, result_path, result['status'], result['outcome'])

    if result['status'] == 'blocked':
        raise SystemExit('BAYESIAN_WORKER_BLOCKED: ' + '; '.join(failure_signatures or ['no completed trials']))


if __name__ == '__main__':
    main()
