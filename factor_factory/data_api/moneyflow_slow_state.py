from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .flow_distribution_moments import normalize_cutoff_time, normalize_trade_date
from .intraday_operator_kernels import grouped_ema_state_by_group


DATASET_ID = 'moneyflow_slow_state_v1'
SCHEMA_VERSION = 'moneyflow_slow_state_v1_p0'
PRODUCER_VERSION = 'factorforge_data_api_moneyflow_slow_state_20260617'
SOURCE_DATASET = 'intraday_flow_distribution_moments_v1'
UNIQUE_KEY = ['ts_code', 'trade_date', 'cutoff_time', 'lambda']
DEFAULT_LAMBDAS = (0.70, 0.85, 0.93)
DEFAULT_CUTOFF_TIMES = ('14:50:00',)


@dataclass(frozen=True)
class MoneyflowSlowStateParams:
    lambdas: tuple[float, ...] = DEFAULT_LAMBDAS
    cutoff_times: tuple[str, ...] = DEFAULT_CUTOFF_TIMES
    score_col: str = 'v19d_score'
    v18a_col: str = 'v18a_z'
    v18b_col: str = 'v18b_z'
    is_end_date: str = '20250711'
    state_init_policy: str = 'first_finite_signal'
    operator_backend: str = 'reference'
    max_workers: int | None = None


def _validate_lambdas(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values:
        raise ValueError('lambdas must not be empty')
    out = tuple(float(value) for value in values)
    invalid = [value for value in out if value < 0.0 or value > 1.0]
    if invalid:
        raise ValueError(f'lambdas must be between 0 and 1: {invalid}')
    return out


def _required_columns(params: MoneyflowSlowStateParams) -> list[str]:
    return ['ts_code', 'trade_date', 'cutoff_time', params.score_col]


def _coerce_input(frame: pd.DataFrame, params: MoneyflowSlowStateParams) -> pd.DataFrame:
    missing = [col for col in _required_columns(params) if col not in frame.columns]
    if missing:
        raise ValueError(f'frame missing required columns: {missing}')
    work = frame.copy()
    work['trade_date'] = work['trade_date'].map(normalize_trade_date)
    work['cutoff_time'] = work['cutoff_time'].map(normalize_cutoff_time)
    work['v19d_score'] = pd.to_numeric(work[params.score_col], errors='coerce')
    work['v18a_z'] = pd.to_numeric(work[params.v18a_col], errors='coerce') if params.v18a_col in work.columns else np.nan
    work['v18b_z'] = pd.to_numeric(work[params.v18b_col], errors='coerce') if params.v18b_col in work.columns else np.nan
    cutoff_set = {normalize_cutoff_time(item) for item in params.cutoff_times}
    work = work[work['cutoff_time'].isin(cutoff_set)].copy()
    work = work.dropna(subset=['ts_code', 'trade_date', 'cutoff_time', 'v19d_score'])
    return work


def _reference_slow_state(chunk: pd.DataFrame, *, decay: float) -> pd.DataFrame:
    out = chunk.sort_values(['_state_group', 'trade_date']).copy()
    values = np.zeros(len(out), dtype=np.float64)
    positions = np.arange(len(out), dtype=np.int64)
    for _, group in out.assign(_pos=positions).groupby('_state_group', sort=False):
        state = 0.0
        initialized = False
        for pos, signal in zip(group['_pos'].to_numpy(dtype=np.int64), group['v19d_score'].to_numpy(dtype=np.float64), strict=True):
            if np.isfinite(signal):
                state = signal if not initialized else float(decay) * state + (1.0 - float(decay)) * signal
                initialized = True
            values[int(pos)] = state if initialized else 0.0
    out['h_slow_state'] = values
    return out


def derive_moneyflow_slow_state_v1(frame: pd.DataFrame, params: MoneyflowSlowStateParams | None = None) -> pd.DataFrame:
    cfg = params or MoneyflowSlowStateParams()
    lambdas = _validate_lambdas(tuple(cfg.lambdas))
    work = _coerce_input(frame, cfg)
    out_cols = [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'lambda',
        'v18a_z',
        'v18b_z',
        'v19d_score',
        'h_slow_state',
        'v20a_score',
        'v20b_score',
        'state_source',
        'no_future_data',
        'warmup_days',
        'state_init_policy',
        'research_window',
        'schema_version',
        'producer_version',
        'source_dataset',
    ]
    if work.empty:
        empty = pd.DataFrame(columns=out_cols)
        empty.attrs['dataset_id'] = DATASET_ID
        empty.attrs['operator_backend'] = f'{cfg.operator_backend}_ema_state'
        return empty

    expanded = pd.concat(
        [
            work.assign(**{'lambda': lambda_value})
            for lambda_value in lambdas
        ],
        ignore_index=True,
    )
    expanded = expanded.sort_values(['ts_code', 'cutoff_time', 'lambda', 'trade_date']).reset_index(drop=True)
    expanded['_state_group'] = pd.factorize(pd.MultiIndex.from_frame(expanded[['ts_code', 'cutoff_time', 'lambda']]), sort=False)[0]
    expanded['warmup_days'] = expanded.groupby('_state_group', sort=False).cumcount().astype(int)

    pieces: list[pd.DataFrame] = []
    realized_backend = ''
    for lambda_value, chunk in expanded.groupby('lambda', sort=True):
        if str(cfg.operator_backend).lower() == 'reference':
            state = _reference_slow_state(chunk, decay=float(lambda_value))
            realized_backend = 'reference'
        else:
            state = grouped_ema_state_by_group(
                chunk,
                group_col='_state_group',
                order_col='trade_date',
                signal_col='v19d_score',
                decay=float(lambda_value),
                output_col='h_slow_state',
                backend=cfg.operator_backend,
                max_workers=cfg.max_workers,
            )
            realized_backend = str(state.attrs.get('operator_backend') or realized_backend)
        pieces.append(state)
    result = pd.concat(pieces, ignore_index=True) if pieces else expanded.assign(h_slow_state=np.nan)
    result['v20a_score'] = result['h_slow_state']
    result['v20b_score'] = result['h_slow_state'].where(result['v18b_z'] > 0)
    result['state_source'] = 'prior_state_continuous'
    result['no_future_data'] = True
    result['state_init_policy'] = cfg.state_init_policy
    is_end = normalize_trade_date(cfg.is_end_date)
    result['research_window'] = np.where(result['trade_date'] <= is_end, 'IS', 'OOS')
    result['schema_version'] = SCHEMA_VERSION
    result['producer_version'] = PRODUCER_VERSION
    result['source_dataset'] = SOURCE_DATASET
    result = result[out_cols].sort_values(['ts_code', 'cutoff_time', 'lambda', 'trade_date']).reset_index(drop=True)
    result.attrs['dataset_id'] = DATASET_ID
    result.attrs['schema_version'] = SCHEMA_VERSION
    result.attrs['producer_version'] = PRODUCER_VERSION
    result.attrs['operator_backend'] = realized_backend or f'{cfg.operator_backend}_ema_state'
    result.attrs['unique_key'] = UNIQUE_KEY
    return result


def build_moneyflow_slow_state_qa(frame: pd.DataFrame) -> dict[str, Any]:
    required = set(UNIQUE_KEY + ['h_slow_state', 'research_window', 'no_future_data'])
    missing = sorted(required - set(frame.columns))
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if not missing else 0
    return {
        'dataset_id': DATASET_ID,
        'verdict': 'ACCEPT' if not missing and duplicate_key_count == 0 and bool(frame['no_future_data'].all()) else 'BLOCK',
        'row_count': int(len(frame)),
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns else 0,
        'date_count': int(frame['trade_date'].nunique()) if 'trade_date' in frame.columns else 0,
        'duplicate_key_count': duplicate_key_count,
        'missing_columns': missing,
        'research_windows': sorted(frame['research_window'].dropna().unique().tolist()) if 'research_window' in frame.columns else [],
        'unique_key': UNIQUE_KEY,
        'source_dataset': SOURCE_DATASET,
    }
