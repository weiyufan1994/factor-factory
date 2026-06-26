from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .flow_distribution_moments import normalize_cutoff_time, normalize_trade_date
from .intraday_operator_kernels import grouped_ema_state_by_group


DATASET_ID = 'intraday_ema_slow_state_v1'
SCHEMA_VERSION = 'intraday_ema_slow_state_v1'
PRODUCER_VERSION = 'factorforge_data_api_intraday_ema_slow_state_20260618'
SOURCE_DATASET = 'intraday_flow_distribution_moments_v1'
UNIQUE_KEY = ['ts_code', 'trade_date', 'cutoff_time', 'lambda']
SORT_KEYS = ['ts_code', 'cutoff_time', 'lambda', 'trade_date']
DEFAULT_LAMBDAS = (0.70, 0.85, 0.93)
DEFAULT_CUTOFF_TIMES = ('14:50:00',)
OUTPUT_COLUMNS = [
    'ts_code',
    'trade_date',
    'cutoff_time',
    'lambda',
    'signal_value',
    'ema_state',
    'state_source',
    'source_signal_col',
    'no_future_data',
    'warmup_days',
    'state_init_policy',
    'research_window',
    'schema_version',
    'producer_version',
    'source_dataset',
]


@dataclass(frozen=True)
class IntradayEmaSlowStateParams:
    lambdas: tuple[float, ...] = DEFAULT_LAMBDAS
    cutoff_times: tuple[str, ...] = DEFAULT_CUTOFF_TIMES
    signal_col: str = 'v19d_score'
    is_end_date: str = '20250711'
    state_init_policy: str = 'first_finite_signal'
    operator_backend: str = 'array_grouped'
    max_workers: int | None = None


def _validate_lambdas(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values:
        raise ValueError('lambdas must not be empty')
    out = tuple(float(value) for value in values)
    invalid = [value for value in out if value < 0.0 or value > 1.0]
    if invalid:
        raise ValueError(f'lambdas must be between 0 and 1: {invalid}')
    return out


def _coerce_input(frame: pd.DataFrame, params: IntradayEmaSlowStateParams) -> pd.DataFrame:
    required = ['ts_code', 'trade_date', 'cutoff_time', params.signal_col]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f'frame missing required columns: {missing}')
    work = frame.copy()
    work['trade_date'] = work['trade_date'].map(normalize_trade_date)
    work['cutoff_time'] = work['cutoff_time'].map(normalize_cutoff_time)
    work['signal_value'] = pd.to_numeric(work[params.signal_col], errors='coerce')
    cutoff_set = {normalize_cutoff_time(value) for value in params.cutoff_times}
    work = work[work['cutoff_time'].isin(cutoff_set)].copy()
    work = work.dropna(subset=['ts_code', 'trade_date', 'cutoff_time', 'signal_value'])
    return work[['ts_code', 'trade_date', 'cutoff_time', 'signal_value']]


def _reference_ema_state(chunk: pd.DataFrame, *, decay: float) -> pd.DataFrame:
    out = chunk.sort_values(['_state_group', 'trade_date']).copy()
    values = np.zeros(len(out), dtype=np.float64)
    positions = np.arange(len(out), dtype=np.int64)
    for _, group in out.assign(_pos=positions).groupby('_state_group', sort=False):
        state = 0.0
        initialized = False
        for pos, signal in zip(group['_pos'].to_numpy(dtype=np.int64), group['signal_value'].to_numpy(dtype=np.float64), strict=True):
            if np.isfinite(signal):
                state = signal if not initialized else float(decay) * state + (1.0 - float(decay)) * signal
                initialized = True
            values[int(pos)] = state if initialized else 0.0
    out['ema_state'] = values
    return out


def derive_intraday_ema_slow_state(
    frame: pd.DataFrame,
    params: IntradayEmaSlowStateParams | None = None,
) -> pd.DataFrame:
    cfg = params or IntradayEmaSlowStateParams()
    lambdas = _validate_lambdas(tuple(cfg.lambdas))
    work = _coerce_input(frame, cfg)
    if work.empty:
        empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
        empty.attrs['dataset_id'] = DATASET_ID
        empty.attrs['schema_version'] = SCHEMA_VERSION
        empty.attrs['operator_backend'] = f'{cfg.operator_backend}_ema_state'
        return empty

    expanded = pd.concat([work.assign(**{'lambda': value}) for value in lambdas], ignore_index=True)
    expanded = expanded.sort_values(SORT_KEYS).reset_index(drop=True)
    expanded['_state_group'] = pd.factorize(pd.MultiIndex.from_frame(expanded[['ts_code', 'cutoff_time', 'lambda']]), sort=False)[0]
    expanded['warmup_days'] = expanded.groupby('_state_group', sort=False).cumcount().astype(int)

    pieces: list[pd.DataFrame] = []
    realized_backend = ''
    for lambda_value, chunk in expanded.groupby('lambda', sort=True):
        if str(cfg.operator_backend).lower() == 'reference':
            state = _reference_ema_state(chunk, decay=float(lambda_value))
            realized_backend = 'reference'
        else:
            state = grouped_ema_state_by_group(
                chunk,
                group_col='_state_group',
                order_col='trade_date',
                signal_col='signal_value',
                decay=float(lambda_value),
                output_col='ema_state',
                backend=cfg.operator_backend,
                max_workers=cfg.max_workers,
            )
            realized_backend = str(state.attrs.get('operator_backend') or realized_backend)
        pieces.append(state)
    out = pd.concat(pieces, ignore_index=True) if pieces else expanded.assign(ema_state=np.nan)
    out['state_source'] = 'prior_state_continuous'
    out['source_signal_col'] = str(cfg.signal_col)
    out['no_future_data'] = True
    out['state_init_policy'] = str(cfg.state_init_policy)
    is_end = normalize_trade_date(cfg.is_end_date)
    out['research_window'] = np.where(out['trade_date'] <= is_end, 'IS', 'OOS')
    out['schema_version'] = SCHEMA_VERSION
    out['producer_version'] = PRODUCER_VERSION
    out['source_dataset'] = SOURCE_DATASET
    out = out[OUTPUT_COLUMNS].sort_values(SORT_KEYS).reset_index(drop=True)
    out.attrs['dataset_id'] = DATASET_ID
    out.attrs['schema_version'] = SCHEMA_VERSION
    out.attrs['producer_version'] = PRODUCER_VERSION
    out.attrs['operator_backend'] = realized_backend or f'{cfg.operator_backend}_ema_state'
    out.attrs['unique_key'] = UNIQUE_KEY
    return out


def build_intraday_ema_slow_state_qa(
    frame: pd.DataFrame,
    *,
    params: IntradayEmaSlowStateParams | None = None,
    output_path: str | Path | None = None,
    runtime_seconds: float | None = None,
) -> dict[str, Any]:
    cfg = params or IntradayEmaSlowStateParams()
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if not missing_columns else 0
    issues: list[str] = []
    if frame.empty:
        issues.append('row_count_zero')
    if missing_columns:
        issues.append('missing_expected_columns')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if 'no_future_data' in frame.columns and not frame.empty and not bool(frame['no_future_data'].all()):
        issues.append('no_future_data_not_true')
    if 'state_source' in frame.columns and not frame.empty and not frame['state_source'].eq('prior_state_continuous').all():
        issues.append('state_source_invalid')
    dates = frame['trade_date'].astype(str) if 'trade_date' in frame.columns and not frame.empty else pd.Series(dtype=str)
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'source_signal_col': str(cfg.signal_col),
        'unique_key': UNIQUE_KEY,
        'partition_column': 'trade_date',
        'supported_cutoff_times': [normalize_cutoff_time(value) for value in cfg.cutoff_times],
        'lambdas': [float(value) for value in cfg.lambdas],
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if not dates.empty else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'start_date': str(dates.min()) if not dates.empty else None,
        'end_date': str(dates.max()) if not dates.empty else None,
        'duplicate_key_count': duplicate_key_count,
        'missing_columns': missing_columns,
        'research_windows': sorted(frame['research_window'].dropna().unique().tolist()) if 'research_window' in frame.columns and not frame.empty else [],
        'output_path': str(output_path) if output_path is not None else '',
        'runtime_seconds': runtime_seconds,
        'issues': issues,
        'information_set_legality': {
            'no_future_data': True,
            'source_no_future_requirement': 'source datamart rows must already obey cutoff information set',
            'state_continuity': 'state is carried by ts_code + cutoff_time + lambda without yearly reset',
        },
    }


def build_catalog_entry(
    uri: str | Path,
    qa_path: str | Path,
    start: str,
    end: str,
    *,
    params: IntradayEmaSlowStateParams | None = None,
) -> dict[str, Any]:
    cfg = params or IntradayEmaSlowStateParams()
    return {
        'dataset_id': DATASET_ID,
        'uri': str(uri),
        'format': 'parquet',
        'version': 'v1',
        'storage': 'local',
        'description': 'Reusable intraday cutoff EMA slow-state features from accepted source datamarts.',
        'columns': OUTPUT_COLUMNS,
        'partition_columns': ['trade_date'],
        'date_column': 'trade_date',
        'symbol_column': 'ts_code',
        'metadata': {
            'source_dataset': SOURCE_DATASET,
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'partition_column': 'trade_date',
            'unique_key': UNIQUE_KEY,
            'sort_keys': SORT_KEYS,
            'supported_cutoff_times': [normalize_cutoff_time(value) for value in cfg.cutoff_times],
            'lambdas': [float(value) for value in cfg.lambdas],
            'source_signal_col': str(cfg.signal_col),
            'qa_summary_path': str(qa_path),
            'information_set_legality': 'source cutoff rows plus prior state only; no future data',
            'no_future_data': True,
            'state_init_policy': str(cfg.state_init_policy),
        },
        'freshness': {
            'trade_date_min': str(start),
            'trade_date_max': str(end),
        },
    }


def write_partitioned_datamart(frame: pd.DataFrame, output_root: str | Path) -> Path:
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    for trade_date, part in frame.groupby('trade_date', sort=True):
        part_dir = root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True, exist_ok=True)
        part.drop(columns=['trade_date']).to_parquet(part_dir / 'part.parquet', index=False)
    return root
