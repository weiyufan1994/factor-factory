#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = WORKSPACE / 'factorforge'
MPLCONFIGDIR = WORKSPACE / '.cache' / 'matplotlib'
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(MPLCONFIGDIR))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


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


def run_self_quant_quick(report_id: str) -> dict[str, Any]:
    run_dir = FF / 'runs' / report_id
    factor_path = run_dir / f'factor_values__{report_id}.parquet'
    daily_path = run_dir / 'step3a_local_inputs' / f'daily_input__{report_id}.csv'
    if not factor_path.exists():
        raise FileNotFoundError(f'missing factor values: {factor_path}')
    if not daily_path.exists():
        raise FileNotFoundError(f'missing daily input: {daily_path}')

    factor_df = pd.read_parquet(factor_path, columns=['ts_code', 'trade_date', 'cpv_factor'])
    daily_df = pd.read_csv(daily_path, usecols=['ts_code', 'trade_date', 'close'])

    factor_df = factor_df.rename(columns={'ts_code': 'code'}).copy()
    daily_df = daily_df.rename(columns={'ts_code': 'code'}).copy()
    factor_df['datetime'] = pd.to_datetime(factor_df['trade_date'].astype(str))
    daily_df['datetime'] = pd.to_datetime(daily_df['trade_date'].astype(str))

    daily_df = daily_df.sort_values(['code', 'datetime'])
    daily_df['future_return_1d'] = daily_df.groupby('code', sort=False)['close'].shift(-1) / daily_df['close'] - 1

    merged = factor_df[['datetime', 'trade_date', 'code', 'cpv_factor']].merge(
        daily_df[['datetime', 'code', 'future_return_1d']],
        on=['datetime', 'code'],
        how='left',
    )
    merged = merged.dropna(subset=['cpv_factor', 'future_return_1d'])

    rank_ic = merged.groupby('datetime', sort=True).apply(
        lambda df: df['cpv_factor'].corr(df['future_return_1d'], method='spearman')
    )
    pearson_ic = merged.groupby('datetime', sort=True).apply(
        lambda df: df['cpv_factor'].corr(df['future_return_1d'], method='pearson')
    )

    rank_stats = _series_stats(rank_ic)
    pearson_stats = _series_stats(pearson_ic)

    coverage_by_day = merged.groupby('datetime', sort=True)['code'].count()
    signal_non_null = int(factor_df['cpv_factor'].notna().sum())

    eval_dir = FF / 'evaluations' / report_id / 'self_quant_analyzer'
    rank_plot_path = eval_dir / 'rank_ic_timeseries.png'
    pearson_plot_path = eval_dir / 'pearson_ic_timeseries.png'
    coverage_plot_path = eval_dir / 'coverage_by_day.png'
    _write_line_plot(rank_ic.dropna(), rank_plot_path, _plot_title(report_id, 'Rank IC'), 'rank_ic')
    _write_line_plot(pearson_ic.dropna(), pearson_plot_path, _plot_title(report_id, 'Pearson IC'), 'pearson_ic')
    _write_line_plot(coverage_by_day, coverage_plot_path, _plot_title(report_id, 'Coverage by Day'), 'cross_section_count')

    summary = {
        'backend': 'self_quant_analyzer',
        'mode': 'quick',
        'report_id': report_id,
        'signal_name': 'cpv_factor',
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
        'tail_examples': {
            'rank_ic_head': [_safe_float(x) for x in rank_ic.head(10).tolist()],
            'rank_ic_tail': [_safe_float(x) for x in rank_ic.tail(10).tolist()],
            'pearson_ic_head': [_safe_float(x) for x in pearson_ic.head(10).tolist()],
            'pearson_ic_tail': [_safe_float(x) for x in pearson_ic.tail(10).tolist()],
        },
        'artifacts': {
            'rank_ic_timeseries_png': str(rank_plot_path),
            'pearson_ic_timeseries_png': str(pearson_plot_path),
            'coverage_by_day_png': str(coverage_plot_path),
        },
        'extensible_metrics': True,
    }
    return summary


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    data = run_self_quant_quick(args.report_id)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {out}')


if __name__ == '__main__':
    main()
