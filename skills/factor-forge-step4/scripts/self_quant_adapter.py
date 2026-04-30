#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FF.parent
MPLCONFIGDIR = WORKSPACE / '.cache' / 'matplotlib'
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(MPLCONFIGDIR))

from factor_factory.data_access import (
    build_forward_return_frame,
    load_daily_snapshot,
    load_factor_values_with_signal,
    normalize_trade_date_series,
)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

TRADING_COST_RATE = 0.003
ANNUALIZATION_DAYS = 252


def _load_snapshot_note(report_id: str) -> str | None:
    dpm_path = FF / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json'
    if not dpm_path.exists():
        return None
    payload = json.loads(dpm_path.read_text(encoding='utf-8'))
    local_paths = payload.get('local_input_paths') or {}
    note = local_paths.get('snapshot_note')
    return str(note) if note else None


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _series_stats(series: pd.Series) -> dict[str, float | None]:
    valid = series.dropna()
    if valid.empty:
        return {'mean': None, 'std': None, 'ir': None}
    std = valid.std()
    return {
        'mean': _safe_float(valid.mean()),
        'std': _safe_float(std),
        'ir': _safe_float(valid.mean() / std) if std and not np.isnan(std) else None,
    }


def _plot_title(report_id: str, suffix: str) -> str:
    short_id = report_id if len(report_id) <= 48 else report_id[:48] + '...'
    short_id = ''.join(ch if ord(ch) < 128 else '_' for ch in short_id)
    return f'{short_id} {suffix}'


def _write_line_plot(series: pd.Series, path: Path, title: str, ylabel: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(series.index, series.values, linewidth=1.5)
    ax.set_title(title)
    ax.set_xlabel('datetime')
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _normalize_nav_to_one(nav: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    if nav.empty:
        return nav
    first = nav.iloc[0]
    if isinstance(nav, pd.Series):
        if first in {0, None} or pd.isna(first):
            return nav
        return nav / first
    first = first.replace(0, np.nan)
    return nav.div(first, axis='columns').fillna(1.0)


def _assign_quantile_labels(series: pd.Series, groups: int) -> pd.Series:
    valid = series.dropna()
    if valid.empty or len(valid) < 20:
        return pd.Series(index=series.index, dtype='float64')

    bucket_count = min(groups, int(valid.nunique()), len(valid))
    if bucket_count < 2:
        return pd.Series(index=series.index, dtype='float64')

    ranked = valid.rank(method='first')
    labels = pd.qcut(ranked, q=bucket_count, labels=False, duplicates='drop') + 1
    return labels.reindex(series.index)


def _build_quantile_nav(
    merged: pd.DataFrame,
    signal_col: str,
    group_count: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    working = merged[['trade_date', signal_col, 'future_return_1d']].copy()
    working['group_id'] = working.groupby('trade_date', sort=True)[signal_col].transform(
        lambda s: _assign_quantile_labels(s, groups=group_count)
    )
    grouped_source = (
        working.dropna(subset=['group_id', 'future_return_1d'])
        .assign(group_id=lambda df: df['group_id'].astype(int))
    )
    grouped = grouped_source.groupby(['trade_date', 'group_id'], sort=True)['future_return_1d'].mean().unstack('group_id').sort_index()
    counts = grouped_source.groupby(['trade_date', 'group_id'], sort=True).size().unstack('group_id').sort_index()
    grouped.index = normalize_trade_date_series(grouped.index.to_series())
    grouped.index.name = 'datetime'
    grouped = grouped.sort_index()
    grouped.columns = [f'G{int(col):02d}' for col in grouped.columns]
    counts.index = normalize_trade_date_series(counts.index.to_series())
    counts.index.name = 'datetime'
    counts = counts.sort_index()
    counts.columns = [f'G{int(col):02d}' for col in counts.columns]
    nav = _normalize_nav_to_one((1.0 + grouped.fillna(0.0)).cumprod())
    return grouped, nav, counts


def _build_long_short_series(quantile_returns: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if quantile_returns.empty or quantile_returns.shape[1] < 2:
        empty = pd.Series(dtype='float64')
        return empty, empty
    spread = (quantile_returns.iloc[:, -1] - quantile_returns.iloc[:, 0]).dropna()
    nav = _normalize_nav_to_one((1.0 + spread.fillna(0.0)).cumprod())
    nav.name = 'LS'
    spread.name = 'LS'
    return spread, nav


def _max_drawdown(nav: pd.Series) -> float | None:
    valid = nav.dropna().astype(float)
    if valid.empty:
        return None
    drawdown = valid / valid.cummax() - 1.0
    return _safe_float(drawdown.min())


def _max_recovery_days(nav: pd.Series) -> int | None:
    valid = nav.dropna().astype(float)
    if valid.empty:
        return None
    max_days = 0
    peak = valid.iloc[0]
    peak_date = valid.index[0]
    underwater_start = None
    for dt, value in valid.items():
        if value >= peak:
            if underwater_start is not None:
                max_days = max(max_days, int((dt - underwater_start).days))
                underwater_start = None
            peak = value
            peak_date = dt
        elif underwater_start is None:
            underwater_start = peak_date
    if underwater_start is not None:
        max_days = max(max_days, int((valid.index[-1] - underwater_start).days))
    return int(max_days)


def _build_long_side_evidence(
    merged: pd.DataFrame,
    signal_col: str,
    eval_dir: Path,
    report_id: str,
    group_count: int = 10,
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    working = merged[['datetime', 'trade_date', 'code', signal_col, 'future_return_1d']].copy()
    working['group_id'] = working.groupby('trade_date', sort=True)[signal_col].transform(
        lambda s: _assign_quantile_labels(s, groups=group_count)
    )
    assigned = working.dropna(subset=['group_id', 'future_return_1d']).copy()
    if assigned.empty:
        empty_metrics = {
            'metric_period': 'daily',
            'annualization_factor': ANNUALIZATION_DAYS,
            'long_side_label': None,
            'long_side_mean_return_daily': None,
            'long_side_annual_return': None,
            'long_side_annual_volatility': None,
            'long_side_sharpe': None,
            'long_side_max_drawdown': None,
            'long_side_recovery_days': None,
            'long_side_turnover_mean_daily': None,
            'trading_cogs_daily': None,
            'trading_cogs_annual': None,
            'cost_adjusted_return_daily': None,
            'cost_adjusted_annual_return': None,
            'cost_adjusted_long_side_sharpe': None,
        }
        return empty_metrics, {}, [_check(False, 'LONG_SIDE_ASSIGNMENTS_PRESENT', 'long-side assignments are missing')]

    assigned['group_id'] = assigned['group_id'].astype(int)
    top_group_id = int(assigned['group_id'].max())
    top = assigned[assigned['group_id'] == top_group_id].copy()
    long_returns = top.groupby('datetime', sort=True)['future_return_1d'].mean().dropna()
    long_returns.name = 'long_side_return'

    memberships = top.groupby('datetime', sort=True)['code'].apply(lambda s: set(s.astype(str)))
    turnovers: list[tuple[pd.Timestamp, float]] = []
    previous: set[str] | None = None
    for dt, current in memberships.items():
        if previous is None or not current:
            turnover = 0.0
        else:
            turnover = 1.0 - (len(current & previous) / len(current))
        turnovers.append((dt, turnover))
        previous = current
    turnover_series = pd.Series(dict(turnovers), dtype='float64').sort_index()
    turnover_series.name = 'long_side_turnover'
    turnover_for_returns = turnover_series.reindex(long_returns.index).fillna(0.0)
    trading_cogs = turnover_for_returns.abs() * TRADING_COST_RATE
    trading_cogs.name = 'trading_cogs'
    cost_adjusted_returns = (long_returns - trading_cogs).dropna()
    cost_adjusted_returns.name = 'cost_adjusted_long_side_return'

    gross_nav = _normalize_nav_to_one((1.0 + long_returns.fillna(0.0)).cumprod())
    gross_nav.name = 'long_side_nav'
    net_nav = _normalize_nav_to_one((1.0 + cost_adjusted_returns.fillna(0.0)).cumprod())
    net_nav.name = 'cost_adjusted_long_side_nav'

    long_returns_csv = eval_dir / 'long_side_returns.csv'
    long_nav_csv = eval_dir / 'long_side_nav.csv'
    long_turnover_csv = eval_dir / 'long_side_turnover.csv'
    long_nav_plot = eval_dir / 'long_side_nav.png'
    cost_adjusted_nav_plot = eval_dir / 'cost_adjusted_long_side_nav.png'

    long_returns.to_frame().to_csv(long_returns_csv, index=True)
    pd.concat([gross_nav, net_nav], axis=1).to_csv(long_nav_csv, index=True)
    turnover_series.to_frame().to_csv(long_turnover_csv, index=True)
    _write_line_plot(gross_nav, long_nav_plot, _plot_title(report_id, 'Long-Side NAV (Top Group)'), 'long_side_nav')
    _write_line_plot(net_nav, cost_adjusted_nav_plot, _plot_title(report_id, 'Cost-Adjusted Long-Side NAV'), 'cost_adjusted_long_side_nav')

    daily_mean = _safe_float(long_returns.mean()) if not long_returns.empty else None
    daily_std = _safe_float(long_returns.std()) if not long_returns.empty else None
    net_daily_mean = _safe_float(cost_adjusted_returns.mean()) if not cost_adjusted_returns.empty else None
    net_daily_std = _safe_float(cost_adjusted_returns.std()) if not cost_adjusted_returns.empty else None
    turnover_mean = _safe_float(turnover_series.iloc[1:].mean()) if len(turnover_series) > 1 else _safe_float(turnover_series.mean())
    metrics = {
        'metric_period': 'daily',
        'annualization_factor': ANNUALIZATION_DAYS,
        'long_side_label': f'G{top_group_id:02d}',
        'long_side_mean_return_daily': daily_mean,
        'long_side_annual_return': _safe_float(daily_mean * ANNUALIZATION_DAYS) if daily_mean is not None else None,
        'long_side_return_std_daily': daily_std,
        'long_side_annual_volatility': _safe_float(daily_std * np.sqrt(ANNUALIZATION_DAYS)) if daily_std is not None else None,
        'long_side_sharpe': _safe_float(daily_mean / daily_std * np.sqrt(ANNUALIZATION_DAYS)) if daily_mean is not None and daily_std not in {None, 0} else None,
        'long_side_final_nav': _safe_float(gross_nav.iloc[-1]) if not gross_nav.empty else None,
        'long_side_max_drawdown': _max_drawdown(gross_nav),
        'long_side_recovery_days': _max_recovery_days(gross_nav),
        'long_side_turnover_mean_daily': turnover_mean,
        'turnover_mean': turnover_mean,
        'trading_cogs_model': 'turnover * 0.003',
        'trading_cogs_rate': TRADING_COST_RATE,
        'trading_cogs_daily': _safe_float(turnover_mean * TRADING_COST_RATE) if turnover_mean is not None else None,
        'trading_cogs_annual': _safe_float(turnover_mean * TRADING_COST_RATE * ANNUALIZATION_DAYS) if turnover_mean is not None else None,
        'cost_adjusted_return_daily': net_daily_mean,
        'cost_adjusted_annual_return': _safe_float(net_daily_mean * ANNUALIZATION_DAYS) if net_daily_mean is not None else None,
        'cost_adjusted_return_std_daily': net_daily_std,
        'cost_adjusted_annual_volatility': _safe_float(net_daily_std * np.sqrt(ANNUALIZATION_DAYS)) if net_daily_std is not None else None,
        'cost_adjusted_long_side_sharpe': _safe_float(net_daily_mean / net_daily_std * np.sqrt(ANNUALIZATION_DAYS)) if net_daily_mean is not None and net_daily_std not in {None, 0} else None,
        'cost_adjusted_long_side_final_nav': _safe_float(net_nav.iloc[-1]) if not net_nav.empty else None,
        'cost_adjusted_long_side_max_drawdown': _max_drawdown(net_nav),
        'cost_adjusted_long_side_recovery_days': _max_recovery_days(net_nav),
    }
    artifacts = {
        'long_side_returns_csv': str(long_returns_csv),
        'long_side_nav_csv': str(long_nav_csv),
        'long_side_turnover_csv': str(long_turnover_csv),
        'long_side_nav_png': str(long_nav_plot),
        'cost_adjusted_long_side_nav_png': str(cost_adjusted_nav_plot),
    }
    checks = [
        _check(metrics['long_side_mean_return_daily'] is not None, 'LONG_SIDE_RETURN_PRESENT', 'long-side daily return is missing'),
        _check(metrics['long_side_sharpe'] is not None, 'LONG_SIDE_SHARPE_PRESENT', 'long-side Sharpe is missing'),
        _check(metrics['long_side_max_drawdown'] is not None, 'LONG_SIDE_DRAWDOWN_PRESENT', 'long-side max drawdown is missing'),
        _check(metrics['long_side_recovery_days'] is not None, 'LONG_SIDE_RECOVERY_PRESENT', 'long-side recovery days are missing'),
        _check(metrics['long_side_turnover_mean_daily'] is not None, 'LONG_SIDE_TURNOVER_PRESENT', 'long-side turnover is missing'),
        _check(metrics['trading_cogs_daily'] is not None, 'LONG_SIDE_TRADING_COGS_PRESENT', 'long-side trading COGS is missing'),
        _check(metrics['cost_adjusted_long_side_sharpe'] is not None, 'COST_ADJUSTED_LONG_SIDE_SHARPE_PRESENT', 'cost-adjusted long-side Sharpe is missing'),
    ]
    for key, path_text in artifacts.items():
        p = Path(path_text)
        checks.append(_check(p.exists() and p.stat().st_size > 0, f'ARTIFACT_{key.upper()}_EXISTS', f'missing or empty long-side artifact: {key}', evidence={'path': str(p)}))
    return metrics, artifacts, checks


def _build_quantile_summary_table(
    quantile_returns: pd.DataFrame,
    quantile_nav: pd.DataFrame,
    quantile_counts: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for column in quantile_returns.columns:
        returns = quantile_returns[column].dropna()
        counts = quantile_counts[column].dropna() if column in quantile_counts.columns else pd.Series(dtype='float64')
        std = returns.std()
        rows.append({
            'group': column,
            'mean_daily_return': _safe_float(returns.mean()) if not returns.empty else None,
            'std_daily_return': _safe_float(std) if not returns.empty else None,
            'daily_ir': _safe_float(returns.mean() / std) if not returns.empty and std not in {0, None} and not pd.isna(std) else None,
            'final_nav': _safe_float(quantile_nav[column].iloc[-1]) if column in quantile_nav.columns and not quantile_nav.empty else None,
            'member_count_min': int(counts.min()) if not counts.empty else None,
            'member_count_median': _safe_float(counts.median()) if not counts.empty else None,
            'member_count_max': int(counts.max()) if not counts.empty else None,
        })
    return pd.DataFrame(rows)


def _write_group_plot(nav_df: pd.DataFrame, path: Path, title: str, ylabel: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 5))
    for column in nav_df.columns:
        ax.plot(nav_df.index, nav_df[column], linewidth=1.1, label=column)
    ax.set_title(title)
    ax.set_xlabel('datetime')
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _check(condition: bool, code: str, message: str, severity: str = 'BLOCK', evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        'code': code,
        'status': 'PASS' if condition else severity,
        'ok': bool(condition),
        'severity': severity,
        'message': None if condition else message,
        'evidence': evidence or {},
    }


def _build_standard_output_checks(
    artifacts: dict[str, str],
    rank_stats: dict[str, float | None],
    pearson_stats: dict[str, float | None],
    quantile_returns: pd.DataFrame,
    quantile_nav: pd.DataFrame,
    quantile_counts: pd.DataFrame,
    long_short_nav: pd.Series,
    coverage_by_day: pd.Series,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
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
    ]
    for key in required_artifacts:
        p = Path(artifacts.get(key, ''))
        checks.append(_check(p.exists() and p.stat().st_size > 0, f'ARTIFACT_{key.upper()}_EXISTS', f'missing or empty Step4 standard artifact: {key}', evidence={'path': str(p)}))

    finite_rank = rank_stats.get('mean') is not None and np.isfinite(rank_stats['mean'])
    finite_pearson = pearson_stats.get('mean') is not None and np.isfinite(pearson_stats['mean'])
    checks.append(_check(bool(finite_rank), 'RANK_IC_FINITE', 'rank_ic_mean is missing or non-finite'))
    checks.append(_check(bool(finite_pearson), 'PEARSON_IC_FINITE', 'pearson_ic_mean is missing or non-finite'))
    checks.append(_check(quantile_returns.shape[1] == 10, 'DECILE_RETURN_TABLE_COMPLETE', 'quantile return table must contain exactly 10 decile groups', evidence={'columns': list(quantile_returns.columns)}))
    checks.append(_check(quantile_nav.shape[1] == 10, 'DECILE_NAV_TABLE_COMPLETE', 'quantile NAV table must contain exactly 10 decile groups', evidence={'columns': list(quantile_nav.columns)}))
    checks.append(_check(not quantile_counts.empty and int(quantile_counts.min().min()) > 0, 'DECILE_COUNTS_POSITIVE', 'each emitted decile must have positive member counts'))

    if not quantile_nav.empty:
        first_row = quantile_nav.iloc[0]
        checks.append(_check(bool(np.allclose(first_row.astype(float), 1.0, atol=1e-9)), 'DECILE_NAV_STARTS_AT_ONE', 'decile NAV must be normalized to start at 1.0', evidence={'first_row': {k: _safe_float(v) for k, v in first_row.items()}}))
        finite_nav = np.isfinite(quantile_nav.to_numpy(dtype=float)).all()
        positive_nav = (quantile_nav.to_numpy(dtype=float) > 0).all()
        checks.append(_check(bool(finite_nav and positive_nav), 'DECILE_NAV_FINITE_POSITIVE', 'decile NAV contains non-finite or non-positive values'))

    if not long_short_nav.empty:
        checks.append(_check(abs(float(long_short_nav.iloc[0]) - 1.0) <= 1e-9, 'LONG_SHORT_NAV_STARTS_AT_ONE', 'long-short NAV must be built from daily spread returns and normalized to 1.0'))
        checks.append(_check(bool(np.isfinite(long_short_nav.to_numpy(dtype=float)).all()), 'LONG_SHORT_NAV_FINITE', 'long-short NAV contains non-finite values'))

    avg_cross_section = _safe_float(coverage_by_day.mean()) if not coverage_by_day.empty else None
    checks.append(_check(avg_cross_section is not None and avg_cross_section >= 30, 'CROSS_SECTION_BREADTH_REASONABLE', 'average cross-section is too small for production Step4 evidence', severity='WARN', evidence={'avg_cross_section': avg_cross_section}))
    if finite_rank and avg_cross_section is not None:
        checks.append(_check(abs(float(rank_stats['mean'])) < 0.5 or avg_cross_section >= 200, 'IC_MAGNITUDE_NOT_SUSPICIOUS', 'rank IC magnitude is suspiciously high for the available breadth; check leakage or synthetic structure', severity='WARN', evidence={'rank_ic_mean': rank_stats.get('mean'), 'avg_cross_section': avg_cross_section}))
    return checks


def _build_quality_warnings(
    report_id: str,
    rank_stats: dict[str, float | None],
    coverage_by_day: pd.Series,
) -> tuple[list[str], str, dict[str, Any]]:
    warnings: list[str] = []
    flags: dict[str, Any] = {}

    snapshot_note = _load_snapshot_note(report_id)
    avg_cross_section = _safe_float(coverage_by_day.mean()) if not coverage_by_day.empty else None
    rank_ic_mean = rank_stats.get('mean')

    if snapshot_note:
        flags['snapshot_note'] = snapshot_note
    if snapshot_note and 'synthetic fallback' in snapshot_note.lower():
        warnings.append('Evaluation used a synthetic fallback snapshot; IC is diagnostic only and must not be treated as production evidence.')
        flags['synthetic_snapshot'] = True

    if avg_cross_section is not None and avg_cross_section <= 5:
        warnings.append(f'Cross-sectional breadth is only {avg_cross_section:.1f} names per day; IC is statistically fragile.')
        flags['tiny_cross_section'] = True

    if isinstance(rank_ic_mean, (int, float)) and abs(rank_ic_mean) >= 0.8 and avg_cross_section is not None and avg_cross_section <= 5:
        warnings.append(f'Absolute rank_ic_mean={rank_ic_mean:.3f} under a tiny universe is suspiciously high; check for synthetic structure or leakage before trusting the signal.')
        flags['suspiciously_high_ic'] = True

    interpretation = 'diagnostic_only' if warnings else 'normal'
    return warnings, interpretation, flags


def run_self_quant_quick(report_id: str) -> dict[str, Any]:
    factor_df, signal_col, _factor_id = load_factor_values_with_signal(report_id)
    required_columns = ['ts_code', 'trade_date', signal_col]
    factor_df = factor_df[required_columns].copy()
    daily_df = load_daily_snapshot(report_id, columns=['ts_code', 'trade_date', 'close', 'pct_chg'])

    factor_df = factor_df.rename(columns={'ts_code': 'code'}).copy()
    factor_df['datetime'] = normalize_trade_date_series(factor_df['trade_date'])
    daily_df = build_forward_return_frame(
        daily_df.rename(columns={'ts_code': 'code'}),
        instrument_col='code',
        date_col='trade_date',
        price_col='close',
        horizon=1,
    )

    merged = factor_df[['datetime', 'trade_date', 'code', signal_col]].merge(
        daily_df[['datetime', 'code', 'future_return_1d']],
        on=['datetime', 'code'],
        how='left',
    )
    merged = merged.dropna(subset=[signal_col, 'future_return_1d'])

    rank_ic = merged.groupby('datetime', sort=True).apply(
        lambda df: df[signal_col].corr(df['future_return_1d'], method='spearman')
    )
    pearson_ic = merged.groupby('datetime', sort=True).apply(
        lambda df: df[signal_col].corr(df['future_return_1d'], method='pearson')
    )

    rank_stats = _series_stats(rank_ic)
    pearson_stats = _series_stats(pearson_ic)
    quantile_returns, quantile_nav, quantile_counts = _build_quantile_nav(merged, signal_col=signal_col, group_count=10)
    long_side_metrics, long_side_artifacts, long_side_checks = _build_long_side_evidence(
        merged=merged,
        signal_col=signal_col,
        eval_dir=FF / 'evaluations' / report_id / 'self_quant_analyzer',
        report_id=report_id,
        group_count=10,
    )
    top_group = quantile_returns.iloc[:, -1] if not quantile_returns.empty else pd.Series(dtype='float64')
    bottom_group = quantile_returns.iloc[:, 0] if not quantile_returns.empty else pd.Series(dtype='float64')
    long_short_spread = (top_group - bottom_group).dropna() if not quantile_returns.empty else pd.Series(dtype='float64')

    coverage_by_day = merged.groupby('datetime', sort=True)['code'].count()
    signal_non_null = int(factor_df[signal_col].notna().sum())
    quality_warnings, interpretation, quality_flags = _build_quality_warnings(
        report_id=report_id,
        rank_stats=rank_stats,
        coverage_by_day=coverage_by_day,
    )

    eval_dir = FF / 'evaluations' / report_id / 'self_quant_analyzer'
    rank_plot_path = eval_dir / 'rank_ic_timeseries.png'
    pearson_plot_path = eval_dir / 'pearson_ic_timeseries.png'
    coverage_plot_path = eval_dir / 'coverage_by_day.png'
    quantile_returns_csv = eval_dir / 'quantile_returns_10groups.csv'
    quantile_nav_csv = eval_dir / 'quantile_nav_10groups.csv'
    quantile_counts_csv = eval_dir / 'quantile_counts_10groups.csv'
    quantile_summary_csv = eval_dir / 'quantile_summary_table.csv'
    long_short_returns_csv = eval_dir / 'long_short_returns_10groups.csv'
    long_short_nav_csv = eval_dir / 'long_short_nav_10groups.csv'
    quantile_nav_plot = eval_dir / 'quantile_nav_10groups.png'
    quantile_counts_plot = eval_dir / 'quantile_counts_10groups.png'
    long_short_nav_plot = eval_dir / 'long_short_nav_10groups.png'
    long_short_returns, long_short_nav = _build_long_short_series(quantile_returns)
    quantile_summary = _build_quantile_summary_table(quantile_returns, quantile_nav, quantile_counts)
    _write_line_plot(rank_ic.dropna(), rank_plot_path, _plot_title(report_id, 'Rank IC'), 'rank_ic')
    _write_line_plot(pearson_ic.dropna(), pearson_plot_path, _plot_title(report_id, 'Pearson IC'), 'pearson_ic')
    _write_line_plot(coverage_by_day, coverage_plot_path, _plot_title(report_id, 'Coverage by Day'), 'cross_section_count')
    quantile_returns.to_csv(quantile_returns_csv, index=True)
    quantile_nav.to_csv(quantile_nav_csv, index=True)
    quantile_counts.to_csv(quantile_counts_csv, index=True)
    quantile_summary.to_csv(quantile_summary_csv, index=False)
    long_short_returns.to_frame('long_short_return').to_csv(long_short_returns_csv, index=True)
    long_short_nav.to_frame('long_short_nav').to_csv(long_short_nav_csv, index=True)
    _write_group_plot(quantile_nav, quantile_nav_plot, _plot_title(report_id, 'Quantile NAV (10 groups)'), 'cumulative nav')
    _write_group_plot(quantile_counts, quantile_counts_plot, _plot_title(report_id, 'Quantile Counts (10 groups)'), 'group count')
    _write_line_plot(long_short_nav, long_short_nav_plot, _plot_title(report_id, 'Long-Short NAV (G10-G01)'), 'long_short_nav')

    artifacts = {
        'rank_ic_timeseries_png': str(rank_plot_path),
        'pearson_ic_timeseries_png': str(pearson_plot_path),
        'coverage_by_day_png': str(coverage_plot_path),
        'quantile_returns_10groups_csv': str(quantile_returns_csv),
        'quantile_nav_10groups_csv': str(quantile_nav_csv),
        'quantile_counts_10groups_csv': str(quantile_counts_csv),
        'quantile_summary_table_csv': str(quantile_summary_csv),
        'long_short_returns_10groups_csv': str(long_short_returns_csv),
        'long_short_nav_10groups_csv': str(long_short_nav_csv),
        'quantile_nav_10groups_png': str(quantile_nav_plot),
        'quantile_counts_10groups_png': str(quantile_counts_plot),
        'long_short_nav_10groups_png': str(long_short_nav_plot),
        **long_side_artifacts,
    }
    standard_checks = _build_standard_output_checks(
        artifacts=artifacts,
        rank_stats=rank_stats,
        pearson_stats=pearson_stats,
        quantile_returns=quantile_returns,
        quantile_nav=quantile_nav,
        quantile_counts=quantile_counts,
        long_short_nav=long_short_nav,
        coverage_by_day=coverage_by_day,
    )
    standard_checks.extend(long_side_checks)
    blocking_checks = [item for item in standard_checks if item['status'] == 'BLOCK']
    warning_checks = [item for item in standard_checks if item['status'] == 'WARN']

    summary = {
        'backend': 'self_quant_analyzer',
        'status': 'failed' if blocking_checks else 'success',
        'mode': 'quick',
        'report_id': report_id,
        'signal_name': signal_col,
        'engine': 'self_quant_adapter_quick_mode',
        'resource_profile': {
            'server_aware': True,
            'avoids_signal_analyzer_heavy_paths': True,
            'uses_long_table_pipeline': True,
            'parallelism': 1,
        },
        'coverage': {
            'signal_rows': int(len(factor_df)),
            'signal_non_null': signal_non_null,
            'merged_rows': int(len(merged)),
            'ticker_count': int(factor_df['code'].nunique()),
            'date_count': int(factor_df['trade_date'].nunique()),
            'rank_ic_count': int(rank_ic.dropna().shape[0]),
            'pearson_ic_count': int(pearson_ic.dropna().shape[0]),
            'avg_cross_section': _safe_float(coverage_by_day.mean()),
            'min_cross_section': int(coverage_by_day.min()) if not coverage_by_day.empty else None,
            'max_cross_section': int(coverage_by_day.max()) if not coverage_by_day.empty else None,
        },
        'ic_summary': {
            'rank_ic_mean': rank_stats['mean'],
            'rank_ic_std': rank_stats['std'],
            'rank_ic_ir': rank_stats['ir'],
            'pearson_ic_mean': pearson_stats['mean'],
            'pearson_ic_std': pearson_stats['std'],
            'pearson_ic_ir': pearson_stats['ir'],
        },
        'group_backtest_summary': {
            'group_count': 10,
            'top_group_label': str(quantile_nav.columns[-1]) if not quantile_nav.empty else None,
            'bottom_group_label': str(quantile_nav.columns[0]) if not quantile_nav.empty else None,
            'top_decile_mean_return': _safe_float(top_group.mean()) if not top_group.empty else None,
            'bottom_decile_mean_return': _safe_float(bottom_group.mean()) if not bottom_group.empty else None,
            'long_short_spread_mean': _safe_float(long_short_spread.mean()) if not long_short_spread.empty else None,
            'long_short_spread_std': _safe_float(long_short_spread.std()) if not long_short_spread.empty else None,
            'long_short_spread_ir': _safe_float(long_short_spread.mean() / long_short_spread.std()) if not long_short_spread.empty and long_short_spread.std() not in [0, None] else None,
            'long_short_final_nav': _safe_float(long_short_nav.iloc[-1]) if not long_short_nav.empty else None,
            'group_member_count_min': int(quantile_counts.min().min()) if not quantile_counts.empty else None,
            'group_member_count_median': _safe_float(quantile_counts.stack().median()) if not quantile_counts.empty else None,
            'group_member_count_max': int(quantile_counts.max().max()) if not quantile_counts.empty else None,
            'decile_return_table_path': str(quantile_returns_csv),
            'decile_nav_table_path': str(quantile_nav_csv),
            'long_short_return_table_path': str(long_short_returns_csv),
            'long_short_nav_table_path': str(long_short_nav_csv),
        },
        'long_side_performance': {
            **long_side_metrics,
            'objective': 'long_side_risk_adjusted_alpha',
            'adoption_policy': {
                'no_short_selling': True,
                'no_direct_decile_trading': True,
                'decile_groups_are_diagnostic_proxy_only': True,
                'formal_revision_scope': 'factor_expression_and_step3b_code_only',
            },
        },
        'standard_metric_contract': {
            'version': 'step4-standard-metrics-v2-long-side',
            'required_outputs': sorted(artifacts),
            'required_long_side_fields': [
                'long_side_annual_return',
                'long_side_sharpe',
                'long_side_max_drawdown',
                'long_side_recovery_days',
                'long_side_turnover_mean_daily',
                'trading_cogs_daily',
                'cost_adjusted_long_side_sharpe',
            ],
            'checks': standard_checks,
            'blocking_issue_count': len(blocking_checks),
            'warning_issue_count': len(warning_checks),
        },
        'tail_examples': {
            'rank_ic_head': [_safe_float(x) for x in rank_ic.head(10).tolist()],
            'rank_ic_tail': [_safe_float(x) for x in rank_ic.tail(10).tolist()],
            'pearson_ic_head': [_safe_float(x) for x in pearson_ic.head(10).tolist()],
            'pearson_ic_tail': [_safe_float(x) for x in pearson_ic.tail(10).tolist()],
        },
        'artifacts': artifacts,
        'warnings': quality_warnings + [str(item['message']) for item in warning_checks if item.get('message')],
        'result_interpretation': 'bug_suspected' if blocking_checks else interpretation,
        'quality_flags': quality_flags,
        'extensible_metrics': True,
    }
    return summary


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--manifest', help='Runtime context manifest passed by Step4 orchestration.')
    args = ap.parse_args()
    data = run_self_quant_quick(args.report_id)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {out}')


if __name__ == '__main__':
    main()
