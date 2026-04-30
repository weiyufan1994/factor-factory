#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
LEGACY_REPO_ROOT = LEGACY_WORKSPACE / 'repos' / 'factor-factory'
REPO_ROOT = LEGACY_REPO_ROOT if LEGACY_REPO_ROOT.exists() else Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FF.parent
RUNS = FF / 'runs'

# Prefer the local editable qlib repository before any unrelated third-party `qlib` package.
for candidate in [Path(os.getenv('QLIB_REPO_ROOT')).expanduser()] if os.getenv('QLIB_REPO_ROOT') else []:
    if (candidate / 'qlib' / '__init__.py').exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
for candidate in [WORKSPACE / 'qlib_repo', Path.home() / 'projects' / 'qlib_repo']:
    if (candidate / 'qlib' / '__init__.py').exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

os.environ.setdefault('MPLCONFIGDIR', str(WORKSPACE / '.cache' / 'matplotlib'))

from factor_factory.data_access import (
    build_forward_return_frame,
    daily_to_qlib_features,
    load_daily_snapshot,
    load_factor_values_with_signal,
    normalize_trade_date_series,
    to_qlib_signal_frame,
)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Series):
        return {
            'type': 'Series',
            'length': int(len(value)),
            'dtype': str(value.dtype),
            'empty': bool(value.empty),
        }
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, 'item') and callable(getattr(value, 'item')):
        try:
            return value.item()
        except Exception:
            pass
    return value


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


def _assign_quantile_labels(series: pd.Series, groups: int) -> pd.Series:
    valid = series.dropna()
    if valid.empty:
        return pd.Series(index=series.index, dtype='float64')

    unique_count = int(valid.nunique())
    bucket_count = max(1, min(groups, unique_count, len(valid)))
    if bucket_count <= 1:
        return pd.Series(1, index=valid.index, dtype='int64').reindex(series.index)

    ranked = valid.rank(method='first')
    labels = pd.qcut(ranked, q=bucket_count, labels=False, duplicates='drop') + 1
    return labels.reindex(series.index)


def _candidate_qlib_repo_roots() -> list[Path]:
    candidates = []
    env_root = os.getenv('QLIB_REPO_ROOT')
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend([
        WORKSPACE / 'qlib_repo',
        Path.home() / 'projects' / 'qlib_repo',
    ])

    seen = set()
    ordered = []
    for item in candidates:
        key = str(item)
        if key not in seen:
            ordered.append(item)
            seen.add(key)
    return ordered


def _import_native_qlib():
    last_error: Exception | None = None
    for repo_root in _candidate_qlib_repo_roots():
        qlib_init = repo_root / 'qlib' / '__init__.py'
        if not qlib_init.exists():
            continue
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        try:
            import redis_lock  # noqa: F401
            import qlib
            from qlib.backtest import backtest
            from qlib.backtest.executor import SimulatorExecutor
            from qlib.contrib.strategy import TopkDropoutStrategy
            if not hasattr(qlib, 'init'):
                raise ImportError(f'qlib from {getattr(qlib, "__file__", "unknown")} does not expose init()')
            return qlib, backtest, SimulatorExecutor, TopkDropoutStrategy, repo_root
        except Exception as exc:
            last_error = exc

    try:
        import redis_lock  # noqa: F401
        import qlib
        from qlib.backtest import backtest
        from qlib.backtest.executor import SimulatorExecutor
        from qlib.contrib.strategy import TopkDropoutStrategy
        if not hasattr(qlib, 'init'):
            raise ImportError(f'qlib from {getattr(qlib, "__file__", "unknown")} does not expose init()')
        return qlib, backtest, SimulatorExecutor, TopkDropoutStrategy, None
    except Exception as exc:
        if last_error is None:
            last_error = exc
        raise last_error


def _resolve_provider_uri(report_id: str) -> str:
    candidates: list[Path] = []
    env_uri = os.getenv('QLIB_PROVIDER_URI')
    if env_uri:
        candidates.append(Path(env_uri).expanduser())
    candidates.extend([
        Path('/home/ubuntu/.qlib/qlib_data/cn_tushare_full_adj'),
        Path('/home/ubuntu/.qlib/qlib_data/cn_data'),
        Path.home() / '.qlib' / 'qlib_data' / 'cn_tushare_full_adj',
        Path.home() / '.qlib' / 'qlib_data' / 'cn_data',
        RUNS / report_id / 'qlib_provider',
    ])
    for item in candidates:
        if item.exists() and any(item.iterdir()):
            return str(item)
    raise FileNotFoundError(
        'No usable qlib provider found. Checked: ' + ', '.join(str(item) for item in candidates)
    )


def _resolve_native_benchmark() -> str | pd.Series:
    env_benchmark = os.getenv('QLIB_BENCHMARK')
    if env_benchmark:
        return env_benchmark
    # Report-scoped providers built from stock snapshots won't include index benchmarks.
    # Using an empty Series disables qlib's fallback to the default CSI300 benchmark.
    return pd.Series(dtype='float64')


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
    nav = (1.0 + grouped.fillna(0.0)).cumprod()
    return grouped, nav, counts


def _write_group_nav_plot(nav_df: pd.DataFrame, path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 5))
    for column in nav_df.columns:
        ax.plot(nav_df.index, nav_df[column], linewidth=1.1, label=column)
    ax.set_title(title)
    ax.set_xlabel('datetime')
    ax.set_ylabel('cumulative nav')
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8)
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
    factor_df, signal_col, factor_id = load_factor_values_with_signal(report_id)
    factor_df = factor_df[['ts_code', 'trade_date', signal_col]].copy()
    daily_df = load_daily_snapshot(report_id, columns=['ts_code', 'trade_date', 'close', 'pct_chg'])
    factor_df['trade_date'] = factor_df['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)
    daily_df['trade_date'] = daily_df['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)

    qlib_signal = to_qlib_signal_frame(factor_df, signal_col=signal_col)
    qlib_daily_features = daily_to_qlib_features(daily_df, value_columns=['close'], rename_fields={'close': '$close'})
    factor_df['datetime'] = normalize_trade_date_series(factor_df['trade_date'])
    daily_df = build_forward_return_frame(
        daily_df,
        instrument_col='ts_code',
        date_col='trade_date',
        price_col='close',
        horizon=1,
    )

    merged = factor_df.merge(
        daily_df[['ts_code', 'trade_date', 'future_return_1d']],
        on=['ts_code', 'trade_date'],
        how='left'
    ).dropna(subset=[signal_col, 'future_return_1d'])

    top = merged.groupby('trade_date')[[signal_col, 'future_return_1d']].apply(
        lambda df: df.nlargest(max(1, len(df)//10), signal_col)['future_return_1d'].mean()
    )
    bottom = merged.groupby('trade_date')[[signal_col, 'future_return_1d']].apply(
        lambda df: df.nsmallest(max(1, len(df)//10), signal_col)['future_return_1d'].mean()
    )
    spread = (top - bottom).dropna()
    quantile_returns, quantile_nav, quantile_counts = _build_quantile_nav(merged, signal_col=signal_col, group_count=10)
    eval_dir = FF / 'evaluations' / report_id / 'qlib_backtest'
    quantile_nav_plot = eval_dir / 'quantile_nav_10groups.png'
    quantile_returns_csv = eval_dir / 'quantile_returns_10groups.csv'
    quantile_nav_csv = eval_dir / 'quantile_nav_10groups.csv'
    quantile_counts_csv = eval_dir / 'quantile_counts_10groups.csv'
    quantile_counts_plot = eval_dir / 'quantile_counts_10groups.png'
    quantile_returns.to_csv(quantile_returns_csv, index=True)
    quantile_nav.to_csv(quantile_nav_csv, index=True)
    quantile_counts.to_csv(quantile_counts_csv, index=True)
    _write_group_nav_plot(quantile_nav, quantile_nav_plot, f'{report_id} quantile nav (10 groups)')
    _write_group_nav_plot(quantile_counts, quantile_counts_plot, f'{report_id} quantile counts (10 groups)')

    base_payload = {
        'backend': 'qlib_backtest',
        'report_id': report_id,
        'factor_id': factor_id,
        'signal_name': signal_col,
        'input_summary': {
            'sample_window': cfg.get('sample_window', {}),
            'factor_rows': int(len(factor_df)),
            'daily_rows': int(len(daily_df)),
            'qlib_daily_feature_rows': int(len(qlib_daily_features)),
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
            'group_count': 10,
            'top_group_label': str(quantile_nav.columns[-1]) if not quantile_nav.empty else None,
            'bottom_group_label': str(quantile_nav.columns[0]) if not quantile_nav.empty else None,
            'group_member_count_min': int(quantile_counts.min().min()) if not quantile_counts.empty else None,
            'group_member_count_median': float(quantile_counts.stack().median()) if not quantile_counts.empty else None,
            'group_member_count_max': int(quantile_counts.max().max()) if not quantile_counts.empty else None,
        },
        'artifacts': {
            'quantile_nav_10groups_png': str(quantile_nav_plot),
            'quantile_returns_10groups_csv': str(quantile_returns_csv),
            'quantile_nav_10groups_csv': str(quantile_nav_csv),
            'quantile_counts_10groups_csv': str(quantile_counts_csv),
            'quantile_counts_10groups_png': str(quantile_counts_plot),
        },
        'readiness': {
            'adapter_config_ok': True,
            'local_snapshot_ok': True,
            'qlib_signal_table_ready': True,
            'qlib_daily_feature_frame_ready': True,
            'qlib_signal_index_names': list(qlib_signal.index.names),
            'qlib_daily_feature_index_names': list(qlib_daily_features.index.names),
            'instrument_normalization': 'shared factor_factory.data_access.normalize_qlib_instrument()',
        },
        'notes': [
            'The adapter emits qlib-friendly signal and daily feature frames with MultiIndex level names [datetime, instrument].',
            'Quantile grouped NAV curves are computed from the same daily signal table for visual inspection.',
            'Quantile grouped constituent counts are emitted alongside returns/NAV for sanity-checking cross-sectional bucket sizes.'
        ],
        'extensible_metrics': True,
    }

    try:
        qlib, backtest, SimulatorExecutor, TopkDropoutStrategy, qlib_repo_root = _import_native_qlib()
    except Exception as exc:
        return {
            **base_payload,
            'mode': 'sample_stub',
            'status': 'partial',
            'engine': 'qlib_backtest_adapter_signal_diagnostics_only',
            'failure_reason': f'native qlib backtest unavailable: {type(exc).__name__}: {exc}',
            'readiness': {
                **base_payload['readiness'],
                'qlib_import_ok': False,
                'full_native_backtest_wired': False,
            },
            'notes': base_payload['notes'] + [
                'Native qlib portfolio backtest is unavailable in the current environment, so only grouped signal diagnostics were emitted.',
            ],
        }

    provider_uri = _resolve_provider_uri(report_id)
    benchmark = _resolve_native_benchmark()
    try:
        qlib.init(provider_uri=provider_uri, region='cn')
        qlib_signal_native = to_qlib_signal_frame(factor_df, signal_col=signal_col, instrument_style='ts_code')
        strategy = TopkDropoutStrategy(signal=qlib_signal_native, topk=50, n_drop=5)
        executor = SimulatorExecutor(time_per_step='day', generate_portfolio_metrics=True)
        start = qlib_signal.index.get_level_values('datetime').min()
        end = qlib_signal.index.get_level_values('datetime').max()
        report, positions = backtest(
            start_time=start,
            end_time=end,
            strategy=strategy,
            executor=executor,
            benchmark=benchmark,
            account=100000000,
            exchange_kwargs={'freq': 'day', 'limit_threshold': 0.095, 'deal_price': 'close'}
        )
    except Exception as exc:
        return {
            **base_payload,
            'mode': 'sample_stub',
            'status': 'partial',
            'engine': 'qlib_backtest_adapter_signal_diagnostics_only',
            'failure_reason': f'native qlib runtime unavailable: {type(exc).__name__}: {exc}',
            'readiness': {
                **base_payload['readiness'],
                'qlib_import_ok': True,
                'full_native_backtest_wired': False,
                'provider_uri': provider_uri,
                'benchmark': benchmark,
                'qlib_repo_root': str(qlib_repo_root) if qlib_repo_root else None,
            },
            'notes': base_payload['notes'] + [
                'Native qlib imports succeeded, but runtime backtest still failed. Grouped diagnostics remain available for debugging.',
            ],
        }
    freq_key = list(report.keys())[0]
    metrics_df = report[freq_key][0].copy()
    port_plot = eval_dir / 'portfolio_value_timeseries.png'
    bench_plot = eval_dir / 'benchmark_vs_strategy.png'
    turnover_plot = eval_dir / 'turnover_timeseries.png'
    _write_line_plot(metrics_df, ['account'], port_plot, f'{report_id} portfolio value')
    _write_line_plot(metrics_df, ['return', 'bench'], bench_plot, f'{report_id} strategy vs benchmark return')
    _write_line_plot(metrics_df, ['total_turnover'], turnover_plot, f'{report_id} turnover')

    return {
        **base_payload,
        'status': 'success',
        'mode': 'native_minimal',
        'engine': 'qlib_backtest_adapter_native_minimal',
        'qlib_version': getattr(qlib, '__version__', 'unknown'),
        'readiness': {
            **base_payload['readiness'],
            'qlib_import_ok': True,
            'full_native_backtest_wired': True,
            'provider_uri': provider_uri,
            'benchmark': benchmark,
            'qlib_repo_root': str(qlib_repo_root) if qlib_repo_root else None,
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
            **base_payload['artifacts'],
            'portfolio_value_timeseries_png': str(port_plot),
            'benchmark_vs_strategy_png': str(bench_plot),
            'turnover_timeseries_png': str(turnover_plot),
        },
        'notes': base_payload['notes'] + [
            'qlib dependency + adapter config + local snapshot are verified.',
            'Native minimal qlib backtest path has been executed with TopkDropoutStrategy + SimulatorExecutor + backtest(...).',
        ],
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--manifest', help='Runtime context manifest passed by Step4 orchestration.')
    args = ap.parse_args()
    data = run_qlib_backtest_stub(args.report_id)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_to_jsonable(data), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {out}')


if __name__ == '__main__':
    main()
