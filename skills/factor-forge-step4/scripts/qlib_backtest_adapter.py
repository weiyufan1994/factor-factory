#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault('MPLCONFIGDIR', '/home/ubuntu/.openclaw/workspace/.cache/matplotlib')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import qlib
from qlib.backtest import backtest
from qlib.backtest.executor import SimulatorExecutor
from qlib.contrib.strategy import TopkDropoutStrategy

WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = WORKSPACE / 'factorforge'


def _normalize_instrument(ts_code: str) -> str:
    if not isinstance(ts_code, str) or '.' not in ts_code:
        return ts_code
    code, market = ts_code.split('.', 1)
    return f'{market.upper()}{code}'


def _build_qlib_signal_table(factor_df: pd.DataFrame) -> pd.DataFrame:
    signal = factor_df[['ts_code', 'trade_date', 'cpv_factor']].dropna(subset=['cpv_factor']).copy()
    signal['datetime'] = pd.to_datetime(signal['trade_date'].astype(str))
    signal['instrument'] = signal['ts_code'].map(_normalize_instrument)
    signal = signal[['datetime', 'instrument', 'cpv_factor']]
    signal = signal.set_index(['datetime', 'instrument']).sort_index()
    signal.index = signal.index.set_names(['datetime', 'instrument'])
    return signal


def _write_line_plot(df: pd.DataFrame, cols: list[str], path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for c in cols:
        if c in df.columns:
            ax.plot(df.index, df[c], label=c, linewidth=1.5)
    ax.set_title(title)
    ax.set_xlabel('datetime')
    ax.grid(True, alpha=0.3)
    if len(cols) > 1:
        ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run_qlib_backtest_stub(report_id: str) -> dict[str, Any]:
    cfg_path = FF / 'objects' / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'
    run_dir = FF / 'runs' / report_id
    factor_path = run_dir / f'factor_values__{report_id}.parquet'
    daily_path = run_dir / 'step3a_local_inputs' / f'daily_input__{report_id}.csv'

    missing = [str(p) for p in [cfg_path, factor_path, daily_path] if not p.exists()]
    if missing:
        return {
            'backend': 'qlib_backtest',
            'mode': 'sample_stub',
            'report_id': report_id,
            'status': 'failed',
            'failure_reason': 'missing required qlib inputs',
            'missing_paths': missing,
            'extensible_metrics': True,
        }

    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    factor_df = pd.read_parquet(factor_path, columns=['ts_code', 'trade_date', 'cpv_factor'])
    daily_df = pd.read_csv(daily_path, usecols=['ts_code', 'trade_date', 'close'])

    qlib_signal = _build_qlib_signal_table(factor_df)
    factor_df['datetime'] = pd.to_datetime(factor_df['trade_date'].astype(str))
    daily_df['datetime'] = pd.to_datetime(daily_df['trade_date'].astype(str))
    daily_df = daily_df.sort_values(['ts_code', 'datetime'])
    daily_df['future_return_1d'] = daily_df.groupby('ts_code', sort=False)['close'].shift(-1) / daily_df['close'] - 1

    merged = factor_df.merge(
        daily_df[['ts_code', 'trade_date', 'future_return_1d']],
        on=['ts_code', 'trade_date'],
        how='left'
    ).dropna(subset=['cpv_factor', 'future_return_1d'])

    top = merged.groupby('trade_date')[['cpv_factor', 'future_return_1d']].apply(lambda df: df.nlargest(max(1, len(df)//10), 'cpv_factor')['future_return_1d'].mean())
    bottom = merged.groupby('trade_date')[['cpv_factor', 'future_return_1d']].apply(lambda df: df.nsmallest(max(1, len(df)//10), 'cpv_factor')['future_return_1d'].mean())
    spread = (top - bottom).dropna()

    qlib.init(provider_uri='/home/ubuntu/.qlib/qlib_data/cn_data', region='cn')
    strategy = TopkDropoutStrategy(signal=qlib_signal, topk=50, n_drop=5)
    executor = SimulatorExecutor(time_per_step='day', generate_portfolio_metrics=True)
    start = qlib_signal.index.get_level_values('datetime').min()
    end = qlib_signal.index.get_level_values('datetime').max()
    report, positions = backtest(
        start_time=start,
        end_time=end,
        strategy=strategy,
        executor=executor,
        benchmark='SH000300',
        account=100000000,
        exchange_kwargs={'freq': 'day', 'limit_threshold': 0.095, 'deal_price': 'close'}
    )
    freq_key = list(report.keys())[0]
    metrics_df = report[freq_key][0].copy()
    eval_dir = FF / 'evaluations' / report_id / 'qlib_backtest'
    port_plot = eval_dir / 'portfolio_value_timeseries.png'
    bench_plot = eval_dir / 'benchmark_vs_strategy.png'
    turnover_plot = eval_dir / 'turnover_timeseries.png'
    _write_line_plot(metrics_df, ['account'], port_plot, f'{report_id} portfolio value')
    _write_line_plot(metrics_df, ['return', 'bench'], bench_plot, f'{report_id} strategy vs benchmark return')
    _write_line_plot(metrics_df, ['total_turnover'], turnover_plot, f'{report_id} turnover')

    payload = {
        'backend': 'qlib_backtest',
        'mode': 'native_minimal',
        'report_id': report_id,
        'engine': 'qlib_backtest_adapter_native_minimal',
        'qlib_version': getattr(qlib, '__version__', 'unknown'),
        'readiness': {
            'qlib_import_ok': True,
            'adapter_config_ok': True,
            'local_snapshot_ok': True,
            'qlib_signal_table_ready': True,
            'qlib_signal_index_names': list(qlib_signal.index.names),
            'instrument_normalization': 'ts_code -> MARKET+CODE (e.g. 000001.SZ -> SZ000001)',
            'full_native_backtest_wired': True,
        },
        'input_summary': {
            'sample_window': cfg.get('sample_window', {}),
            'factor_rows': int(len(factor_df)),
            'daily_rows': int(len(daily_df)),
            'merged_rows': int(len(merged)),
            'ticker_count': int(factor_df['ts_code'].nunique()),
            'date_count': int(factor_df['trade_date'].nunique()),
        },
        'stub_backtest_metrics': {
            'top_decile_mean_return': float(top.mean()) if not top.dropna().empty else None,
            'bottom_decile_mean_return': float(bottom.mean()) if not bottom.dropna().empty else None,
            'long_short_spread_mean': float(spread.mean()) if not spread.empty else None,
            'long_short_spread_std': float(spread.std()) if not spread.empty else None,
            'long_short_spread_ir': float(spread.mean() / spread.std()) if not spread.empty and spread.std() not in [0, None] else None,
            'observation_count': int(spread.shape[0]),
        },
        'native_backtest_metrics': {
            'freq_key': str(freq_key),
            'nonzero_value_rows': int((metrics_df['value'] != 0).sum()) if 'value' in metrics_df.columns else None,
            'nonzero_turnover_rows': int((metrics_df['total_turnover'] != 0).sum()) if 'total_turnover' in metrics_df.columns else None,
            'mean_return': float(metrics_df['return'].mean()) if 'return' in metrics_df.columns else None,
            'mean_benchmark_return': float(metrics_df['bench'].mean()) if 'bench' in metrics_df.columns else None,
            'final_account': float(metrics_df['account'].iloc[-1]) if 'account' in metrics_df.columns and len(metrics_df) else None,
        },
        'artifacts': {
            'portfolio_value_timeseries_png': str(port_plot),
            'benchmark_vs_strategy_png': str(bench_plot),
            'turnover_timeseries_png': str(turnover_plot),
        },
        'notes': [
            'qlib dependency + adapter config + local snapshot are verified.',
            'Native minimal qlib backtest path has been executed with TopkDropoutStrategy + SimulatorExecutor + backtest(...).',
            'The adapter emits a qlib-friendly signal table with MultiIndex level names [datetime, instrument].'
        ],
        'extensible_metrics': True,
    }
    return payload


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    data = run_qlib_backtest_stub(args.report_id)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {out}')


if __name__ == '__main__':
    main()
