from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from .daily import DEFAULT_DAILY_COLUMNS, get_daily
from .nonminute import get_tushare_dataset
from .paths import LocalTusharePaths

DEFAULT_DAILY_MERGE_COLUMNS = ['ts_code', 'trade_date']


@dataclass(frozen=True)
class FinancialDatasetConfig:
    dataset_name: str
    default_source_label: str
    available_date_columns: tuple[str, ...] = ()
    period_column: str | None = 'end_date'
    source_priority: int = 0
    requires_disclosure_anchor: bool = False


FINANCIAL_DATASETS: dict[str, FinancialDatasetConfig] = {
    'income_vip': FinancialDatasetConfig('income_vip', 'actual', ('f_ann_date', 'ann_date'), source_priority=30),
    'balancesheet_vip': FinancialDatasetConfig('balancesheet_vip', 'actual', ('f_ann_date', 'ann_date'), source_priority=30),
    'cashflow_vip': FinancialDatasetConfig('cashflow_vip', 'actual', ('f_ann_date', 'ann_date'), source_priority=30),
    'forecast_vip': FinancialDatasetConfig('forecast_vip', 'forecast', ('ann_date',), source_priority=10),
    'express_vip': FinancialDatasetConfig('express_vip', 'express', ('ann_date',), source_priority=20),
    'fina_indicator_vip': FinancialDatasetConfig('fina_indicator_vip', 'actual', ('ann_date',), source_priority=30),
    'fina_mainbz_vip': FinancialDatasetConfig(
        'fina_mainbz_vip',
        'actual',
        available_date_columns=(),
        source_priority=30,
        requires_disclosure_anchor=True,
    ),
    'disclosure_date': FinancialDatasetConfig('disclosure_date', 'disclosure', ('ann_date',), source_priority=5),
    'report_rc': FinancialDatasetConfig(
        'report_rc',
        'report_rc',
        ('report_date',),
        period_column=None,
        source_priority=5,
    ),
}


def _normalize_date_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype='string')
    normalized = series.astype('string').str.replace('.0', '', regex=False).str.strip()
    normalized = normalized.where(normalized.ne(''), pd.NA)
    normalized = normalized.where(normalized.ne('nan'), pd.NA)
    return normalized.str.zfill(8)


def _normalize_symbols(symbols: Iterable[str] | None) -> set[str] | None:
    if symbols is None:
        return None
    normalized = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
    return normalized or None


def _get_financial_dataset_config(name: str) -> FinancialDatasetConfig:
    try:
        return FINANCIAL_DATASETS[name]
    except KeyError as exc:
        known = ', '.join(sorted(FINANCIAL_DATASETS))
        raise KeyError(f'unknown financial dataset: {name}. available={known}') from exc


def _prepare_base_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    for column in ['ts_code', 'ann_date', 'f_ann_date', 'end_date', 'report_date', 'actual_date', 'pre_date', 'period', 'trade_date']:
        if column in prepared.columns:
            prepared[column] = _normalize_date_series(prepared[column])
    if 'quarter' in prepared.columns:
        prepared['quarter'] = prepared['quarter'].astype('string')
    return prepared


def _choose_available_date(frame: pd.DataFrame, candidates: Sequence[str]) -> pd.Series:
    available = pd.Series(pd.NA, index=frame.index, dtype='string')
    for column in candidates:
        if column not in frame.columns:
            continue
        available = available.fillna(frame[column].astype('string'))
    return _normalize_date_series(available)


def _report_type_priority(frame: pd.DataFrame) -> pd.Series:
    if 'report_type' not in frame.columns:
        return pd.Series(0, index=frame.index, dtype='int64')
    normalized = frame['report_type'].astype('string').fillna('')
    priority = pd.Series(0, index=frame.index, dtype='int64')
    priority[normalized.eq('1')] = 3
    priority[normalized.eq('4')] = 2
    priority[normalized.eq('5')] = 1
    return priority


def _attach_mainbz_available_date(
    frame: pd.DataFrame,
    paths: LocalTusharePaths | None = None,
) -> pd.Series:
    disclosure = get_tushare_dataset('disclosure_date', paths=paths)
    if disclosure.empty:
        return pd.Series(pd.NA, index=frame.index, dtype='string')
    disclosure = _prepare_base_frame(disclosure)
    disclosure = disclosure[['ts_code', 'end_date', 'actual_date', 'ann_date']].copy()
    disclosure = disclosure.dropna(subset=['ts_code', 'end_date'])
    disclosure['available_date'] = _normalize_date_series(disclosure['actual_date'])
    disclosure = disclosure.dropna(subset=['available_date'])
    disclosure = disclosure.sort_values(['ts_code', 'end_date', 'available_date', 'ann_date'])
    anchored = disclosure.drop_duplicates(subset=['ts_code', 'end_date'], keep='last')
    merged = frame.merge(
        anchored[['ts_code', 'end_date', 'available_date']],
        on=['ts_code', 'end_date'],
        how='left',
    )
    return _normalize_date_series(merged['available_date'])


def _prepare_financial_events(
    dataset_name: str,
    frame: pd.DataFrame,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    config = _get_financial_dataset_config(dataset_name)
    prepared = _prepare_base_frame(frame)
    if prepared.empty:
        if 'available_date' not in prepared.columns:
            prepared['available_date'] = pd.Series(dtype='string')
        prepared['source_dataset'] = dataset_name
        prepared['source_label'] = config.default_source_label
        prepared['_source_priority'] = pd.Series(dtype='int64')
        return prepared

    if config.requires_disclosure_anchor:
        prepared['available_date'] = _attach_mainbz_available_date(prepared, paths=paths)
        prepared['available_date_source'] = 'disclosure_actual_date'
    else:
        prepared['available_date'] = _choose_available_date(prepared, config.available_date_columns)
        prepared['available_date_source'] = next(iter(config.available_date_columns), pd.NA)

    prepared['source_dataset'] = dataset_name
    prepared['source_label'] = config.default_source_label
    prepared['_source_priority'] = int(config.source_priority)
    prepared['_report_type_priority'] = _report_type_priority(prepared)
    prepared['_available_date_int'] = pd.to_numeric(prepared['available_date'], errors='coerce')
    prepared['_period_int'] = (
        pd.to_numeric(prepared[config.period_column], errors='coerce')
        if config.period_column and config.period_column in prepared.columns
        else -1
    )

    dedupe_keys = ['ts_code', 'available_date']
    if config.period_column and config.period_column in prepared.columns:
        dedupe_keys.append(config.period_column)

    prepared = prepared.dropna(subset=['ts_code', 'available_date'])
    prepared = prepared.sort_values(
        ['ts_code', '_available_date_int', '_period_int', '_source_priority', '_report_type_priority']
    )
    prepared = prepared.drop_duplicates(subset=dedupe_keys, keep='last').reset_index(drop=True)
    return prepared


def _maybe_limit_columns(frame: pd.DataFrame, columns: Iterable[str] | None) -> pd.DataFrame:
    requested = list(dict.fromkeys(columns)) if columns else None
    if requested is None:
        return frame
    limited = frame.copy()
    for column in requested:
        if column not in limited.columns:
            limited[column] = pd.NA
    return limited[requested]


def get_financial_events(
    dataset_name: str,
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    frame = get_tushare_dataset(
        dataset_name,
        symbols=symbols,
        paths=paths,
    )
    prepared = _prepare_financial_events(dataset_name, frame, paths=paths)
    start_key = _normalize_date_series(pd.Series([start])).iloc[0] if start is not None else None
    end_key = _normalize_date_series(pd.Series([end])).iloc[0] if end is not None else None
    if 'available_date' in prepared.columns:
        if start_key is not None:
            prepared = prepared[prepared['available_date'].isna() | (prepared['available_date'] >= start_key)]
        if end_key is not None:
            prepared = prepared[prepared['available_date'].isna() | (prepared['available_date'] <= end_key)]
        prepared = prepared.reset_index(drop=True)
    return _maybe_limit_columns(prepared, columns)


def combine_periodic_sources(
    frames: Sequence[pd.DataFrame],
    symbol_col: str = 'ts_code',
    period_col: str = 'end_date',
    available_date_col: str = 'available_date',
    source_priority_col: str = '_source_priority',
) -> pd.DataFrame:
    non_empty = [frame.copy() for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()

    combined = pd.concat(non_empty, ignore_index=True, sort=False)
    if symbol_col not in combined.columns or period_col not in combined.columns or available_date_col not in combined.columns:
        raise KeyError(f'combine_periodic_sources requires columns: {symbol_col}, {period_col}, {available_date_col}')

    combined[available_date_col] = _normalize_date_series(combined[available_date_col])
    combined[period_col] = _normalize_date_series(combined[period_col])
    combined['_available_date_int'] = pd.to_numeric(combined[available_date_col], errors='coerce')
    combined['_period_int'] = pd.to_numeric(combined[period_col], errors='coerce')
    if source_priority_col not in combined.columns:
        combined[source_priority_col] = 0

    cleaned_groups: list[pd.DataFrame] = []
    for _, group in combined.groupby([symbol_col, period_col], sort=False, dropna=False):
        group = group.dropna(subset=[available_date_col])
        if group.empty:
            continue
        group = group.sort_values(['_available_date_int', source_priority_col])
        best_priority = -10**9
        kept_index: list[int] = []
        for idx, row in group.iterrows():
            priority = int(row[source_priority_col])
            if priority < best_priority:
                continue
            kept_index.append(int(idx))
            best_priority = max(best_priority, priority)
        if kept_index:
            cleaned_groups.append(group.loc[kept_index])

    if not cleaned_groups:
        return pd.DataFrame(columns=combined.columns)
    return pd.concat(cleaned_groups, ignore_index=True, sort=False)


def align_events_to_daily(
    daily_df: pd.DataFrame,
    events_df: pd.DataFrame,
    available_date_col: str = 'available_date',
    symbol_col: str = 'ts_code',
    trade_date_col: str = 'trade_date',
    period_col: str | None = 'end_date',
) -> pd.DataFrame:
    daily = daily_df.copy()
    daily[trade_date_col] = _normalize_date_series(daily[trade_date_col])
    daily['_trade_date_int'] = pd.to_numeric(daily[trade_date_col], errors='coerce')

    if events_df.empty:
        return daily.drop(columns=['_trade_date_int'])

    events = events_df.copy()
    if available_date_col not in events.columns:
        raise KeyError(f'missing available date column: {available_date_col}')

    events[available_date_col] = _normalize_date_series(events[available_date_col])
    events['_available_date_int'] = pd.to_numeric(events[available_date_col], errors='coerce')
    if period_col and period_col in events.columns:
        events[period_col] = _normalize_date_series(events[period_col])
        events['_period_int'] = pd.to_numeric(events[period_col], errors='coerce').fillna(-1)
    else:
        events['_period_int'] = -1
    if '_source_priority' not in events.columns:
        events['_source_priority'] = 0

    events = events.dropna(subset=[symbol_col, available_date_col])
    event_groups = {
        symbol: group.sort_values(['_available_date_int', '_period_int', '_source_priority']).reset_index(drop=True)
        for symbol, group in events.groupby(symbol_col, sort=False)
    }

    merged_groups: list[pd.DataFrame] = []
    for symbol, daily_group in daily.groupby(symbol_col, sort=False):
        daily_group = daily_group.sort_values('_trade_date_int').reset_index(drop=True)
        events_group = event_groups.get(symbol)
        if events_group is None or events_group.empty:
            merged_groups.append(daily_group)
            continue
        right = events_group.drop(columns=[symbol_col], errors='ignore')
        merged = pd.merge_asof(
            daily_group,
            right,
            left_on='_trade_date_int',
            right_on='_available_date_int',
            direction='backward',
            allow_exact_matches=True,
        )
        merged_groups.append(merged)

    merged = pd.concat(merged_groups, ignore_index=True, sort=False)
    merged = merged.sort_values([symbol_col, '_trade_date_int']).reset_index(drop=True)
    return merged.drop(columns=['_trade_date_int'])


def _default_daily_frame(
    start: str | int | None,
    end: str | int | None,
    symbols: Iterable[str] | None,
    daily_columns: Iterable[str] | None,
    paths: LocalTusharePaths | None,
) -> pd.DataFrame:
    return get_daily(
        start=start,
        end=end,
        symbols=symbols,
        columns=list(daily_columns) if daily_columns else list(DEFAULT_DAILY_MERGE_COLUMNS),
        paths=paths,
    )


def _infer_daily_columns(
    columns: Iterable[str] | None,
    daily_columns: Iterable[str] | None,
) -> list[str] | None:
    if daily_columns is not None:
        return list(dict.fromkeys(daily_columns))
    if columns is None:
        return None
    requested = list(dict.fromkeys(columns))
    inferred = [column for column in requested if column in DEFAULT_DAILY_COLUMNS]
    merged = list(dict.fromkeys([*DEFAULT_DAILY_MERGE_COLUMNS, *inferred]))
    return merged


def get_financial_daily(
    dataset_name: str,
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    daily_columns: Iterable[str] | None = None,
    event_columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    daily = _default_daily_frame(start, end, symbols, _infer_daily_columns(columns, daily_columns), paths=paths)
    events = get_financial_events(dataset_name, end=end, symbols=symbols, paths=paths)
    aligned = align_events_to_daily(daily, events)
    final_columns = list(dict.fromkeys(columns)) if columns is not None else None
    if final_columns is None and event_columns is not None:
        final_columns = [*daily.columns, *event_columns]
    return _maybe_limit_columns(aligned, final_columns)


def get_profit_preview_daily(
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    daily_columns: Iterable[str] | None = None,
    event_columns: Iterable[str] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    daily = _default_daily_frame(start, end, symbols, _infer_daily_columns(columns, daily_columns), paths=paths)
    actual = get_financial_events('income_vip', end=end, symbols=symbols, paths=paths)
    express = get_financial_events('express_vip', end=end, symbols=symbols, paths=paths)
    forecast = get_financial_events('forecast_vip', end=end, symbols=symbols, paths=paths)
    combined = combine_periodic_sources([forecast, express, actual])
    aligned = align_events_to_daily(daily, combined)
    final_columns = list(dict.fromkeys(columns)) if columns is not None else None
    if final_columns is None and event_columns is not None:
        final_columns = [*daily.columns, *event_columns]
    return _maybe_limit_columns(aligned, final_columns)


def get_income_statement(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('income_vip', **kwargs)


def get_balancesheet(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('balancesheet_vip', **kwargs)


def get_cashflow(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('cashflow_vip', **kwargs)


def get_forecast(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('forecast_vip', **kwargs)


def get_express(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('express_vip', **kwargs)


def get_fina_indicator(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('fina_indicator_vip', **kwargs)


def get_fina_mainbz(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('fina_mainbz_vip', **kwargs)


def get_disclosure_date(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('disclosure_date', **kwargs)


def get_report_rc(**kwargs: object) -> pd.DataFrame:
    return get_financial_events('report_rc', **kwargs)


def get_income_statement_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('income_vip', **kwargs)


def get_balancesheet_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('balancesheet_vip', **kwargs)


def get_cashflow_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('cashflow_vip', **kwargs)


def get_forecast_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('forecast_vip', **kwargs)


def get_express_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('express_vip', **kwargs)


def get_fina_indicator_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('fina_indicator_vip', **kwargs)


def get_fina_mainbz_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('fina_mainbz_vip', **kwargs)


def get_disclosure_date_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('disclosure_date', **kwargs)


def get_report_rc_daily(**kwargs: object) -> pd.DataFrame:
    return get_financial_daily('report_rc', **kwargs)
