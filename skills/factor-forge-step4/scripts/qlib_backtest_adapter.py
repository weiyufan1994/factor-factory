#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import hashlib
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


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _shared_context_env_path() -> Path | None:
    raw = os.getenv('FACTORFORGE_SHARED_EVALUATION_CONTEXT_PATH')
    if not raw:
        return None
    return Path(raw).expanduser()


def _validate_shared_context_identity(report_id: str, context: dict[str, Any]) -> tuple[bool, str | None]:
    if context.get('version') != 'factorforge_shared_evaluation_context_v1':
        return False, 'version_mismatch'
    if context.get('report_id') != report_id:
        return False, 'report_id_mismatch'
    paths = context.get('paths') if isinstance(context.get('paths'), dict) else {}
    artifacts = context.get('artifacts') if isinstance(context.get('artifacts'), dict) else {}
    factor_path = RUNS / report_id / f'factor_values__{report_id}.parquet'
    daily_path_raw = context.get('daily_input_path')
    daily_path = Path(daily_path_raw).expanduser() if daily_path_raw else None
    if not factor_path.exists():
        return False, 'factor_values_path_missing'
    if not daily_path or not daily_path.exists():
        return False, 'daily_input_path_missing'
    if context.get('factor_values_hash') != _sha256_file(factor_path):
        return False, 'factor_values_hash_mismatch'
    if context.get('daily_input_hash') != _sha256_file(daily_path):
        return False, 'daily_input_hash_mismatch'
    if context.get('label_policy') != {'horizon': 'T+1', 'return_type': 'simple', 'price_field': 'close'}:
        return False, 'label_policy_mismatch'

    required = {
        'factor_signal': 'factor_signal_parquet',
        'daily_forward_returns': 'daily_forward_returns_parquet',
        'merged_signal_return': 'merged_signal_return_parquet',
    }
    for artifact_name, path_key in required.items():
        raw = paths.get(path_key)
        if not raw:
            return False, f'{path_key}_missing'
        path = Path(str(raw)).expanduser()
        if not path.exists():
            return False, f'{path_key}_missing'
        declared = artifacts.get(artifact_name) if isinstance(artifacts.get(artifact_name), dict) else None
        if not declared:
            return False, f'{artifact_name}_artifact_contract_missing'
        if str(path) != str(Path(str(declared.get('path') or '')).expanduser()):
            return False, f'{artifact_name}_artifact_path_mismatch'
        if declared.get('sha256') != _sha256_file(path):
            return False, f'{artifact_name}_artifact_hash_mismatch'
    return True, None


def _try_load_shared_context(report_id: str, performance_profile: dict[str, Any]) -> tuple[pd.DataFrame | None, pd.DataFrame | None, str | None, str | None, int | None, dict[str, Any]]:
    context_path = _shared_context_env_path()
    profile = {
        'available': bool(context_path),
        'used': False,
        'source': None,
        'identity_validated': False,
        'fallback_reason': None,
        'context_path': str(context_path) if context_path else None,
    }
    if context_path is None:
        profile['fallback_reason'] = 'not_configured'
        return None, None, None, None, None, profile
    if not context_path.exists():
        profile['fallback_reason'] = 'context_json_missing'
        return None, None, None, None, None, profile
    try:
        context = _read_json(context_path)
        ok, reason = _validate_shared_context_identity(report_id, context)
        if not ok:
            profile['fallback_reason'] = reason
            return None, None, None, None, None, profile
        paths = context.get('paths') or {}
        signal_col = str(context.get('signal_column') or '')
        phase_started = time.perf_counter()
        factor_df = pd.read_parquet(paths['factor_signal_parquet'])
        factor_df = factor_df.rename(columns={'code': 'ts_code'}).copy()
        performance_profile['phase_seconds']['load_factor_values'] = round(time.perf_counter() - phase_started, 6)
        performance_profile['phase_seconds']['load_daily_snapshot'] = 0.0
        phase_started = time.perf_counter()
        merged = pd.read_parquet(paths['merged_signal_return_parquet'])
        performance_profile['phase_seconds']['merge_forward_returns'] = round(time.perf_counter() - phase_started, 6)
        row_counts = context.get('row_counts') if isinstance(context.get('row_counts'), dict) else {}
        profile.update({
            'used': True,
            'source': 'merged_signal_return_parquet',
            'identity_validated': True,
            'fallback_reason': None,
            'daily_forward_returns_path': paths.get('daily_forward_returns_parquet'),
        })
        return factor_df, merged, signal_col, context.get('factor_id'), int(row_counts.get('daily_forward_returns') or 0), profile
    except Exception as exc:
        profile['fallback_reason'] = f'{type(exc).__name__}: {exc}'
        return None, None, None, None, None, profile


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


def _provider_instrument_style(provider_uri: str) -> str:
    metadata_path = Path(provider_uri) / 'provider_metadata.json'
    if not metadata_path.exists():
        return 'ts_code'
    try:
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    except Exception:
        return 'ts_code'
    style = metadata.get('instrument_style')
    if style in {'ts_code', 'tushare', 'provider', 'legacy_qlib', 'qlib', 'raw'}:
        return str(style)
    return 'ts_code'


def _resolve_native_benchmark() -> str | pd.Series:
    env_benchmark = os.getenv('QLIB_BENCHMARK')
    if env_benchmark:
        return env_benchmark
    # Report-scoped providers built from stock snapshots won't include index benchmarks.
    # Using an empty Series disables qlib's fallback to the default CSI300 benchmark.
    return pd.Series(dtype='float64')


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(str(raw).replace('_', '').strip())
    except ValueError:
        return default


def _native_resource_guard(*, merged_rows: int, factor_rows: int, daily_rows: int) -> dict[str, Any]:
    mode = (os.getenv('FACTORFORGE_QLIB_NATIVE_MODE') or 'auto').strip().lower()
    max_merged_rows = _env_int('FACTORFORGE_QLIB_NATIVE_MAX_MERGED_ROWS', 5_000_000)
    max_factor_rows = _env_int('FACTORFORGE_QLIB_NATIVE_MAX_FACTOR_ROWS', 5_000_000)
    max_daily_rows = _env_int('FACTORFORGE_QLIB_NATIVE_MAX_DAILY_ROWS', 5_000_000)
    guard = {
        'version': 'factorforge_qlib_native_resource_guard_v1',
        'mode': mode,
        'merged_rows': int(merged_rows),
        'factor_rows': int(factor_rows),
        'daily_rows': int(daily_rows),
        'max_merged_rows': int(max_merged_rows),
        'max_factor_rows': int(max_factor_rows),
        'max_daily_rows': int(max_daily_rows),
        'native_backtest_skipped': False,
        'reason': None,
    }
    if mode in {'0', 'off', 'skip', 'disabled', 'diagnostics_only', 'sample_stub'}:
        guard['native_backtest_skipped'] = True
        guard['reason'] = 'native_mode_disabled'
    elif max_merged_rows > 0 and merged_rows > max_merged_rows:
        guard['native_backtest_skipped'] = True
        guard['reason'] = 'merged_rows_exceeds_limit'
    elif max_factor_rows > 0 and factor_rows > max_factor_rows:
        guard['native_backtest_skipped'] = True
        guard['reason'] = 'factor_rows_exceeds_limit'
    elif max_daily_rows > 0 and daily_rows > max_daily_rows:
        guard['native_backtest_skipped'] = True
        guard['reason'] = 'daily_rows_exceeds_limit'
    return guard


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
    started_total = time.perf_counter()
    performance_profile: dict[str, Any] = {
        'version': 'factorforge_qlib_backtest_performance_profile_v1',
        'phase_seconds': {},
        'row_counts': {},
    }

    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        performance_profile['phase_seconds']['total'] = round(time.perf_counter() - started_total, 6)
        payload['performance_profile'] = performance_profile
        return payload

    cfg_path = FF / 'objects' / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'
    run_dir = FF / 'runs' / report_id
    factor_path = run_dir / f'factor_values__{report_id}.parquet'

    missing = [str(p) for p in [cfg_path, factor_path] if not p.exists()]
    if missing:
        return finish({
            'backend': 'qlib_backtest',
            'mode': 'sample_stub',
            'report_id': report_id,
            'status': 'failed',
            'qlib_native_status': 'failed',
            'failure_reason': 'missing required qlib inputs',
            'missing_paths': missing,
            'extensible_metrics': True,
        })

    phase_started = time.perf_counter()
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    performance_profile['phase_seconds']['read_config'] = round(time.perf_counter() - phase_started, 6)

    factor_df, merged, signal_col, factor_id, shared_daily_rows, shared_context_profile = _try_load_shared_context(
        report_id,
        performance_profile,
    )
    daily_df = None
    if shared_context_profile.get('used') is not True or factor_df is None or merged is None or not signal_col:
        phase_started = time.perf_counter()
        factor_df, signal_col, factor_id = load_factor_values_with_signal(report_id)
        factor_df = factor_df[['ts_code', 'trade_date', signal_col]].copy()
        performance_profile['phase_seconds']['load_factor_values'] = round(time.perf_counter() - phase_started, 6)

        phase_started = time.perf_counter()
        daily_df = load_daily_snapshot(report_id, columns=['ts_code', 'trade_date', 'close', 'pct_chg'])
        performance_profile['phase_seconds']['load_daily_snapshot'] = round(time.perf_counter() - phase_started, 6)

        phase_started = time.perf_counter()
        factor_df['trade_date'] = factor_df['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)
        daily_df['trade_date'] = daily_df['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)
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
        performance_profile['phase_seconds']['merge_forward_returns'] = round(time.perf_counter() - phase_started, 6)
    else:
        factor_df['trade_date'] = factor_df['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)
        if 'datetime' not in factor_df.columns:
            factor_df['datetime'] = normalize_trade_date_series(factor_df['trade_date'])
    performance_profile['shared_evaluation_context'] = shared_context_profile
    performance_profile['row_counts'] = {
        'factor_rows': int(len(factor_df)),
        'daily_rows': int(shared_daily_rows or (len(daily_df) if daily_df is not None else 0)),
        'merged_rows': int(len(merged)),
    }
    daily_row_count = int(performance_profile['row_counts']['daily_rows'])

    phase_started = time.perf_counter()
    top = merged.groupby('trade_date')[[signal_col, 'future_return_1d']].apply(
        lambda df: df.nlargest(max(1, len(df)//10), signal_col)['future_return_1d'].mean()
    )
    bottom = merged.groupby('trade_date')[[signal_col, 'future_return_1d']].apply(
        lambda df: df.nsmallest(max(1, len(df)//10), signal_col)['future_return_1d'].mean()
    )
    spread = (top - bottom).dropna()
    quantile_returns, quantile_nav, quantile_counts = _build_quantile_nav(merged, signal_col=signal_col, group_count=10)
    performance_profile['phase_seconds']['quantile_diagnostics'] = round(time.perf_counter() - phase_started, 6)

    eval_dir = FF / 'evaluations' / report_id / 'qlib_backtest'
    eval_dir.mkdir(parents=True, exist_ok=True)
    quantile_nav_plot = eval_dir / 'quantile_nav_10groups.png'
    quantile_returns_csv = eval_dir / 'quantile_returns_10groups.csv'
    quantile_nav_csv = eval_dir / 'quantile_nav_10groups.csv'
    quantile_counts_csv = eval_dir / 'quantile_counts_10groups.csv'
    quantile_counts_plot = eval_dir / 'quantile_counts_10groups.png'

    phase_started = time.perf_counter()
    quantile_returns.to_csv(quantile_returns_csv, index=True)
    quantile_nav.to_csv(quantile_nav_csv, index=True)
    quantile_counts.to_csv(quantile_counts_csv, index=True)
    _write_group_nav_plot(quantile_nav, quantile_nav_plot, f'{report_id} quantile nav (10 groups)')
    _write_group_nav_plot(quantile_counts, quantile_counts_plot, f'{report_id} quantile counts (10 groups)')
    performance_profile['phase_seconds']['write_quantile_artifacts'] = round(time.perf_counter() - phase_started, 6)

    base_payload = {
        'backend': 'qlib_backtest',
        'report_id': report_id,
        'factor_id': factor_id,
        'signal_name': signal_col,
        'input_summary': {
            'sample_window': cfg.get('sample_window', {}),
            'factor_rows': int(len(factor_df)),
            'daily_rows': daily_row_count,
            'qlib_daily_feature_rows': None,
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
            'diagnostic_quantile_tables_ready': True,
            'qlib_signal_table_ready': False,
            'qlib_daily_feature_frame_ready': False,
            'qlib_signal_index_names': None,
            'qlib_daily_feature_index_names': None,
            'instrument_normalization': 'shared factor_factory.data_access.normalize_qlib_instrument()',
        },
        'notes': [
            'Quantile grouped NAV curves are computed from the same daily signal table for visual inspection.',
            'Quantile grouped constituent counts are emitted alongside returns/NAV for sanity-checking cross-sectional bucket sizes.',
            'Native qlib frames are built only after the resource guard allows native execution.'
        ],
        'extensible_metrics': True,
    }

    phase_started = time.perf_counter()
    resource_guard = _native_resource_guard(
        merged_rows=len(merged),
        factor_rows=len(factor_df),
        daily_rows=daily_row_count,
    )
    performance_profile['phase_seconds']['native_resource_guard'] = round(time.perf_counter() - phase_started, 6)
    if resource_guard.get('native_backtest_skipped'):
        return finish({
            **base_payload,
            'mode': 'sample_stub',
            'status': 'partial',
            'qlib_native_status': 'partial_payload',
            'engine': 'qlib_backtest_adapter_signal_diagnostics_only',
            'failure_reason': f'native qlib backtest skipped by resource guard: {resource_guard.get("reason")}',
            'resource_guard': resource_guard,
            'readiness': {
                **base_payload['readiness'],
                'qlib_import_ok': None,
                'full_native_backtest_wired': False,
            },
            'notes': base_payload['notes'] + [
                'Native qlib portfolio backtest was skipped before import/backtest to protect the production resource envelope.',
            ],
        })

    phase_started = time.perf_counter()
    try:
        qlib, backtest, SimulatorExecutor, TopkDropoutStrategy, qlib_repo_root = _import_native_qlib()
    except Exception as exc:
        performance_profile['phase_seconds']['import_native_qlib'] = round(time.perf_counter() - phase_started, 6)
        return finish({
            **base_payload,
            'mode': 'sample_stub',
            'status': 'partial',
            'qlib_native_status': 'partial_payload',
            'engine': 'qlib_backtest_adapter_signal_diagnostics_only',
            'failure_reason': f'native qlib backtest unavailable: {type(exc).__name__}: {exc}',
            'resource_guard': resource_guard,
            'readiness': {
                **base_payload['readiness'],
                'qlib_import_ok': False,
                'full_native_backtest_wired': False,
            },
            'notes': base_payload['notes'] + [
                'Native qlib portfolio backtest is unavailable in the current environment, so only grouped signal diagnostics were emitted.',
            ],
        })
    performance_profile['phase_seconds']['import_native_qlib'] = round(time.perf_counter() - phase_started, 6)

    provider_uri = _resolve_provider_uri(report_id)
    provider_style = _provider_instrument_style(provider_uri)
    benchmark = _resolve_native_benchmark()
    try:
        phase_started = time.perf_counter()
        if daily_df is None:
            daily_df = load_daily_snapshot(report_id, columns=['ts_code', 'trade_date', 'close', 'pct_chg'])
            daily_df['trade_date'] = daily_df['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)
        qlib_signal_native = to_qlib_signal_frame(factor_df, signal_col=signal_col, instrument_style=provider_style)
        qlib_daily_features = daily_to_qlib_features(daily_df, value_columns=['close'], rename_fields={'close': '$close'})
        base_payload['input_summary']['qlib_daily_feature_rows'] = int(len(qlib_daily_features))
        base_payload['readiness'] = {
            **base_payload['readiness'],
            'qlib_signal_table_ready': True,
            'qlib_daily_feature_frame_ready': True,
            'qlib_signal_index_names': list(qlib_signal_native.index.names),
            'qlib_daily_feature_index_names': list(qlib_daily_features.index.names),
        }
        performance_profile['phase_seconds']['prepare_native_frames'] = round(time.perf_counter() - phase_started, 6)

        phase_started = time.perf_counter()
        qlib.init(provider_uri=provider_uri, region='cn')
        strategy = TopkDropoutStrategy(signal=qlib_signal_native, topk=50, n_drop=5)
        executor = SimulatorExecutor(time_per_step='day', generate_portfolio_metrics=True)
        trading_calendar = sorted(qlib_signal_native.index.get_level_values('datetime').unique())
        start = trading_calendar[0]
        # qlib's simulator reads the next trading step while settling the final bar.
        # Avoid using the last available provider date as the backtest end.
        end = trading_calendar[-2] if len(trading_calendar) > 1 else trading_calendar[-1]
        report, positions = backtest(
            start_time=start,
            end_time=end,
            strategy=strategy,
            executor=executor,
            benchmark=benchmark,
            account=100000000,
            exchange_kwargs={'freq': 'day', 'limit_threshold': 0.095, 'deal_price': 'close'}
        )
        performance_profile['phase_seconds']['native_backtest'] = round(time.perf_counter() - phase_started, 6)
    except Exception as exc:
        performance_profile['phase_seconds'].setdefault('native_backtest', round(time.perf_counter() - phase_started, 6))
        return finish({
            **base_payload,
            'mode': 'sample_stub',
            'status': 'partial',
            'qlib_native_status': 'partial_payload',
            'engine': 'qlib_backtest_adapter_signal_diagnostics_only',
            'failure_reason': f'native qlib runtime unavailable: {type(exc).__name__}: {exc}',
            'resource_guard': resource_guard,
            'readiness': {
                **base_payload['readiness'],
                'qlib_import_ok': True,
                'full_native_backtest_wired': False,
                'provider_uri': provider_uri,
                'instrument_style': provider_style,
                'benchmark': benchmark,
                'qlib_repo_root': str(qlib_repo_root) if qlib_repo_root else None,
            },
            'notes': base_payload['notes'] + [
                'Native qlib imports succeeded, but runtime backtest still failed. Grouped diagnostics remain available for debugging.',
            ],
        })

    phase_started = time.perf_counter()
    freq_key = list(report.keys())[0]
    metrics_df = report[freq_key][0].copy()
    port_plot = eval_dir / 'portfolio_value_timeseries.png'
    bench_plot = eval_dir / 'benchmark_vs_strategy.png'
    turnover_plot = eval_dir / 'turnover_timeseries.png'
    _write_line_plot(metrics_df, ['account'], port_plot, f'{report_id} portfolio value')
    _write_line_plot(metrics_df, ['return', 'bench'], bench_plot, f'{report_id} strategy vs benchmark return')
    _write_line_plot(metrics_df, ['total_turnover'], turnover_plot, f'{report_id} turnover')
    performance_profile['phase_seconds']['write_native_artifacts'] = round(time.perf_counter() - phase_started, 6)

    return finish({
        **base_payload,
        'status': 'success',
        'mode': 'native_minimal',
        'qlib_native_status': 'native_minimal_success',
        'engine': 'qlib_backtest_adapter_native_minimal',
        'qlib_version': getattr(qlib, '__version__', 'unknown'),
        'resource_guard': resource_guard,
        'readiness': {
            **base_payload['readiness'],
            'qlib_import_ok': True,
            'full_native_backtest_wired': True,
            'provider_uri': provider_uri,
            'instrument_style': provider_style,
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
    })


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
