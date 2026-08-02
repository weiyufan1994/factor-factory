from __future__ import annotations

import os
import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from .paths import path_exists_accessibly

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FACTORFORGE = Path(
    os.getenv('FACTORFORGE_ROOT')
    or (
        LEGACY_WORKSPACE / 'factorforge'
        if path_exists_accessibly(LEGACY_WORKSPACE / 'factorforge')
        else REPO_ROOT
    )
)
RUNS = FACTORFORGE / 'runs'
OBJ = FACTORFORGE / 'objects'


def normalize_trade_date_series(series: pd.Series) -> pd.Series:
    """Normalize common Factor Forge trade_date encodings to pandas datetime.

    Step3B implementations sometimes emit `YYYYMMDD` integers/strings, while
    ad-hoc scripts may emit pandas Timestamp or `YYYY-MM-DD` strings. Step4
    consumers must accept these encodings at the boundary instead of letting
    every factor implementation reinvent date parsing.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors='coerce').dt.normalize()

    text = series.astype(str).str.strip()
    text = (
        text
        .str.replace('.0', '', regex=False)
        .str.replace(r'\s+00:00:00$', '', regex=True)
    )
    compact = text.str.replace('-', '', regex=False).str.replace('/', '', regex=False)
    parsed = pd.to_datetime(compact, format='%Y%m%d', errors='coerce')
    unresolved = parsed.isna()
    if unresolved.any():
        parsed.loc[unresolved] = pd.to_datetime(text.loc[unresolved], errors='coerce')
    return parsed.dt.normalize()


def load_factor_values(
    report_id: str,
    columns: Iterable[str] | None = None,
    runs_root: Path | None = None,
) -> pd.DataFrame:
    root = runs_root or RUNS
    factor_path = root / report_id / f'factor_values__{report_id}.parquet'
    if not factor_path.exists():
        raise FileNotFoundError(f'missing factor values: {factor_path}')
    return pd.read_parquet(factor_path, columns=list(columns) if columns else None)


def sanitize_factor_id(factor_id: str | None) -> str:
    raw = str(factor_id or '').strip().lower()
    sanitized = re.sub(r'[^0-9a-zA-Z]+', '_', raw).strip('_')
    return sanitized or 'factor'


def default_signal_column_name(factor_id: str | None) -> str:
    sanitized = sanitize_factor_id(factor_id)
    return sanitized if sanitized.endswith('_factor') else f'{sanitized}_factor'


def get_factor_id(report_id: str, objects_root: Path | None = None) -> str | None:
    root = objects_root or OBJ
    spec_path = root / 'factor_spec_master' / f'factor_spec_master__{report_id}.json'
    if not spec_path.exists():
        return None
    payload = json.loads(spec_path.read_text(encoding='utf-8'))
    factor_id = payload.get('factor_id')
    return str(factor_id) if factor_id else None


def infer_signal_column(frame: pd.DataFrame, factor_id: str | None = None) -> str:
    reserved = {'ts_code', 'trade_date', 'datetime', 'code', 'instrument'}
    candidates = [column for column in frame.columns if column not in reserved]
    if not candidates:
        raise KeyError('could not infer signal column: no non-key columns found')

    preferred = default_signal_column_name(factor_id) if factor_id else None
    if preferred and preferred in candidates:
        return preferred
    if len(candidates) == 1:
        return candidates[0]
    return candidates[-1]


def load_factor_values_with_signal(
    report_id: str,
    runs_root: Path | None = None,
    objects_root: Path | None = None,
) -> tuple[pd.DataFrame, str, str | None]:
    frame = load_factor_values(report_id, runs_root=runs_root)
    factor_id = get_factor_id(report_id, objects_root=objects_root)
    signal_col = infer_signal_column(frame, factor_id=factor_id)
    return frame, signal_col, factor_id


def resolve_daily_snapshot_path(report_id: str, runs_root: Path | None = None) -> tuple[Path, str]:
    root = runs_root or RUNS
    base = root / report_id / 'step3a_local_inputs'
    parquet_path = base / f'daily_input__{report_id}.parquet'
    csv_path = base / f'daily_input__{report_id}.csv'
    if parquet_path.exists():
        return parquet_path, 'parquet'
    if csv_path.exists():
        return csv_path, 'csv'
    raise FileNotFoundError(f'missing daily input: {parquet_path} or {csv_path}')


def load_daily_snapshot(
    report_id: str,
    columns: Iterable[str] | None = None,
    runs_root: Path | None = None,
) -> pd.DataFrame:
    daily_path, fmt = resolve_daily_snapshot_path(report_id, runs_root=runs_root)
    if fmt == 'parquet':
        return pd.read_parquet(daily_path, columns=list(columns) if columns else None)
    return pd.read_csv(daily_path, usecols=list(columns) if columns else None)


def add_datetime_column(frame: pd.DataFrame, date_col: str = 'trade_date') -> pd.DataFrame:
    enriched = frame.copy()
    enriched['datetime'] = normalize_trade_date_series(enriched[date_col])
    return enriched


def build_forward_return_frame(
    daily_df: pd.DataFrame,
    instrument_col: str = 'ts_code',
    date_col: str = 'trade_date',
    price_col: str = 'close',
    return_col: str | None = 'pct_chg',
    horizon: int = 1,
    entry_offset: int = 0,
    exit_offset: int | None = None,
) -> pd.DataFrame:
    if horizon <= 0:
        raise ValueError('horizon must be positive')
    if entry_offset < 0:
        raise ValueError('entry_offset must be non-negative')
    resolved_exit_offset = entry_offset + horizon if exit_offset is None else exit_offset
    if resolved_exit_offset <= entry_offset:
        raise ValueError('exit_offset must be greater than entry_offset')

    enriched = add_datetime_column(daily_df, date_col=date_col)
    enriched = enriched.sort_values([instrument_col, 'datetime'])
    if entry_offset == 0 and resolved_exit_offset == horizon and return_col and return_col in enriched.columns:
        next_ret = pd.to_numeric(enriched[return_col], errors='coerce').groupby(enriched[instrument_col], sort=False).shift(-1) / 100.0
        if horizon == 1:
            enriched[f'future_return_{horizon}d'] = next_ret
            return enriched

    grouped_price = enriched.groupby(instrument_col, sort=False)[price_col]
    entry_price = grouped_price.shift(-entry_offset) if entry_offset else enriched[price_col]
    exit_price = grouped_price.shift(-resolved_exit_offset)
    enriched[f'future_return_{horizon}d'] = exit_price / entry_price - 1
    return enriched
