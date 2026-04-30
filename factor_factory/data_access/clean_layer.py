from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .daily import _normalize_date, _normalize_symbols
from .daily_policy import DailyFilterPolicy, get_clean_daily
from .paths import LocalTusharePaths, default_local_data_root, resolve_local_tushare_paths

LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FACTORFORGE_ROOT = (
    Path(os.getenv('FACTORFORGE_ROOT'))
    if os.getenv('FACTORFORGE_ROOT')
    else (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT)
).expanduser()


@dataclass(frozen=True)
class CleanDailyLayerPaths:
    root: Path
    daily_parquet: Path
    metadata_json: Path
    source_label: str = 'shared_clean_daily_layer'


def default_clean_daily_layer_root() -> Path:
    explicit = os.getenv('FACTORFORGE_CLEAN_DAILY_DIR')
    if explicit:
        return Path(explicit).expanduser()
    return DEFAULT_FACTORFORGE_ROOT / 'data' / 'clean'


def resolve_clean_daily_layer_paths() -> CleanDailyLayerPaths:
    root = default_clean_daily_layer_root()
    return CleanDailyLayerPaths(
        root=root,
        daily_parquet=root / 'daily_clean.parquet',
        metadata_json=root / 'daily_clean.meta.json',
    )


def clean_daily_layer_ready(paths: CleanDailyLayerPaths | None = None) -> bool:
    resolved = paths or resolve_clean_daily_layer_paths()
    return resolved.daily_parquet.exists() and resolved.metadata_json.exists()


def materialize_clean_daily_layer(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    raw_paths: LocalTusharePaths | None = None,
    policy: DailyFilterPolicy | None = None,
    layer_paths: CleanDailyLayerPaths | None = None,
) -> tuple[CleanDailyLayerPaths, dict]:
    resolved_raw = raw_paths or resolve_local_tushare_paths()
    active_policy = policy or DailyFilterPolicy()
    resolved_layer = layer_paths or resolve_clean_daily_layer_paths()
    resolved_layer.root.mkdir(parents=True, exist_ok=True)

    daily_df, clean_meta = get_clean_daily(
        start=start,
        end=end,
        symbols=symbols,
        paths=resolved_raw,
        policy=active_policy,
        return_metadata=True,
    )
    daily_df.to_parquet(resolved_layer.daily_parquet, index=False)

    payload = {
        'mode': 'shared_clean_daily_layer',
        'source_label': resolved_raw.source_label,
        'source_root': str(resolved_raw.root),
        'source_daily_csv': str(resolved_raw.daily_csv),
        'source_adj_factor_csv': str(resolved_raw.adj_factor_csv),
        'request': {
            'start': _normalize_date(start),
            'end': _normalize_date(end),
            'symbols': sorted(_normalize_symbols(symbols)) if symbols else None,
        },
        'policy': asdict(active_policy),
        'clean_meta': clean_meta,
        'output_summary': {
            'rows': int(len(daily_df)),
            'tickers': int(daily_df['ts_code'].nunique()) if 'ts_code' in daily_df.columns else None,
            'trade_dates': int(daily_df['trade_date'].nunique()) if 'trade_date' in daily_df.columns else None,
        },
        'artifacts': {
            'daily_parquet': str(resolved_layer.daily_parquet),
            'metadata_json': str(resolved_layer.metadata_json),
        },
    }
    resolved_layer.metadata_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return resolved_layer, payload


def load_clean_daily_layer(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    layer_paths: CleanDailyLayerPaths | None = None,
    return_metadata: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict]:
    resolved = layer_paths or resolve_clean_daily_layer_paths()
    if not clean_daily_layer_ready(resolved):
        raise FileNotFoundError(
            f'shared clean daily layer missing under {resolved.root}; run scripts/build_clean_daily_layer.py first'
        )

    requested_columns = list(columns) if columns else None
    helper_columns = ['ts_code', 'trade_date']
    parquet_columns = None
    if requested_columns is not None:
        parquet_columns = list(dict.fromkeys([*requested_columns, *helper_columns]))

    frame = pd.read_parquet(resolved.daily_parquet, columns=parquet_columns)
    frame['trade_date'] = frame['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)

    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    if start_date:
        frame = frame[frame['trade_date'] >= start_date]
    if end_date and end_date != 'current':
        frame = frame[frame['trade_date'] <= end_date]

    symbol_set = _normalize_symbols(symbols)
    if symbol_set:
        frame = frame[frame['ts_code'].isin(symbol_set)]

    if requested_columns is not None:
        ordered_columns = [col for col in requested_columns if col in frame.columns]
        frame = frame[ordered_columns].copy()
    else:
        frame = frame.copy()

    if not return_metadata:
        return frame.reset_index(drop=True)

    meta = json.loads(resolved.metadata_json.read_text(encoding='utf-8'))
    meta['request_slice'] = {
        'start': start_date,
        'end': end_date,
        'symbols': sorted(symbol_set) if symbol_set else None,
    }
    meta['slice_summary'] = {
        'rows': int(len(frame)),
        'tickers': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns else None,
        'trade_dates': int(frame['trade_date'].nunique()) if 'trade_date' in frame.columns else None,
    }
    return frame.reset_index(drop=True), meta
