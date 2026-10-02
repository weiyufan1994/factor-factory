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
    # Standard output always wins; the only legacy alternative is an explicitly
    # bound factor ID. Column order is never a signal-selection policy.
    if 'factor_value' in frame.columns:
        return 'factor_value'
    preferred = default_signal_column_name(factor_id) if factor_id else None
    if preferred and preferred in frame.columns:
        return preferred
    raise KeyError('factor_value or an explicitly bound factor-ID signal column is required')


def load_factor_values_with_signal(
    report_id: str,
    runs_root: Path | None = None,
    objects_root: Path | None = None,
) -> tuple[pd.DataFrame, str, str | None]:
    frame = load_factor_values(report_id, runs_root=runs_root)
    factor_id = get_factor_id(report_id, objects_root=objects_root)
    signal_col = infer_signal_column(frame, factor_id=factor_id)
    from factor_factory.research_api import normalize_factor_frame
    normalize_factor_frame(frame[['ts_code', 'trade_date', signal_col]].rename(columns={signal_col: 'factor_value'}))
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
    include_label_path: bool = False,
    calendar_dates: Iterable[object] | None = None,
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
    calendar = None
    if calendar_dates is not None:
        from factor_factory.research_api import _dates
        calendar = _dates(list(calendar_dates), name='calendar_dates')
        if calendar.empty or calendar.has_duplicates or not calendar.is_monotonic_increasing:
            raise ValueError('calendar_dates must be sorted and unique')
        if enriched.duplicated([instrument_col, 'datetime']).any():
            raise ValueError('calendar-aligned returns require unique instrument/date rows')
        if enriched['datetime'].isna().any() or not enriched['datetime'].isin(calendar).all():
            raise ValueError('daily dates must be valid and belong to calendar_dates')
    if (
        entry_offset == 0
        and resolved_exit_offset == horizon
        and return_col
        and return_col in enriched.columns
    ):
        next_ret = pd.to_numeric(enriched[return_col], errors='coerce').groupby(enriched[instrument_col], sort=False).shift(-1) / 100.0
        if horizon == 1:
            if calendar is not None:
                # pct_chg is a percentage-point field: preserve its return
                # semantics, but look up the exact next calendar session.
                expected_next = enriched['datetime'].map(dict(zip(calendar[:-1], calendar[1:])))
                returns = pd.Series(pd.to_numeric(enriched[return_col], errors='coerce').to_numpy(),
                                    index=pd.MultiIndex.from_arrays([enriched['datetime'], enriched[instrument_col]]))
                keys = pd.MultiIndex.from_arrays([expected_next, enriched[instrument_col]])
                next_ret = pd.Series(returns.reindex(keys).to_numpy() / 100., index=enriched.index)
            enriched[f'future_return_{horizon}d'] = next_ret
            enriched.attrs['label_timing'] = {'expression': f'{return_col}(next_session)/100',
                'calendar_alignment': 'independent_calendar' if calendar is not None else 'legacy_observed_rows_unverified'}
            return enriched

    grouped_price = enriched.groupby(instrument_col, sort=False)[price_col]
    entry_price = grouped_price.shift(-entry_offset) if entry_offset else enriched[price_col]
    exit_price = grouped_price.shift(-resolved_exit_offset)
    label_start_date: pd.Series
    label_end_date: pd.Series
    if calendar_dates is not None:
        if enriched.duplicated([instrument_col, 'datetime']).any():
            raise ValueError('calendar-aligned returns require unique instrument/date rows')
        calendar = normalize_trade_date_series(
            pd.Series(list(calendar_dates), dtype='object')
        )
        if calendar.empty or calendar.isna().any():
            raise ValueError('calendar_dates must contain valid dates')
        calendar_values = calendar.tolist()
        if calendar_values != sorted(set(calendar_values)):
            raise ValueError('calendar_dates must be sorted and unique')

        def expected_date(offset: int) -> pd.Series:
            mapping = {
                calendar_values[index]: calendar_values[index + offset]
                for index in range(len(calendar_values) - offset)
            }
            return enriched['datetime'].map(mapping)

        expected_entry = expected_date(entry_offset)
        expected_exit = expected_date(resolved_exit_offset)
        price_lookup = pd.Series(enriched[price_col].to_numpy(), index=pd.MultiIndex.from_arrays(
            [enriched['datetime'], enriched[instrument_col]]))
        entry_price = pd.Series(price_lookup.reindex(pd.MultiIndex.from_arrays(
            [expected_entry, enriched[instrument_col]])).to_numpy(), index=enriched.index)
        exit_price = pd.Series(price_lookup.reindex(pd.MultiIndex.from_arrays(
            [expected_exit, enriched[instrument_col]])).to_numpy(), index=enriched.index)
        label_start_date = expected_entry.dt.strftime('%Y%m%d')
        label_end_date = expected_exit.dt.strftime('%Y%m%d')
    else:
        grouped_date = enriched.groupby(instrument_col, sort=False)[date_col]
        label_start_date = (
            grouped_date.shift(-entry_offset)
            if entry_offset
            else enriched[date_col]
        )
        label_end_date = grouped_date.shift(-resolved_exit_offset)

    enriched[f'future_return_{horizon}d'] = exit_price / entry_price - 1
    if calendar is not None:
        from factor_factory.research_api import build_forward_returns
        price_input = enriched[[instrument_col, date_col, price_col]].rename(columns={
            instrument_col: 'ts_code', date_col: 'trade_date', price_col: 'close'})
        labels = build_forward_returns(price_input, calendar=calendar,
                                       entry_offset=entry_offset, horizon=resolved_exit_offset-entry_offset)
        keys = pd.MultiIndex.from_arrays([enriched['datetime'], enriched[instrument_col]], names=['datetime', 'instrument'])
        enriched[f'future_return_{horizon}d'] = labels['forward_return'].reindex(keys).to_numpy()
    enriched.attrs['label_timing'] = {'expression': f'close(t+{resolved_exit_offset})/close(t+{entry_offset})-1',
        'calendar_alignment': 'independent_calendar' if calendar is not None else 'legacy_observed_rows_unverified'}
    if include_label_path:
        enriched['label_start_date'] = label_start_date
        enriched['label_end_date'] = label_end_date
        enriched['label_start_price'] = entry_price
        enriched['label_end_price'] = exit_price
    return enriched
