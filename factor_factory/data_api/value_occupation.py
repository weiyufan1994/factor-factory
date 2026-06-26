from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATASET_ID = 'intraday_value_occupation_state_v1'
SCHEMA_VERSION = 'intraday_value_occupation_state_v1_p0'
PRODUCER_VERSION = 'factorforge_data_api_value_occupation_20260610'
SOURCE_DATASET = 'minute_bar'
UNIQUE_KEY = ['ts_code', 'trade_date', 'cutoff_time', 'lookback_days']
SORT_KEYS = ['trade_date', 'ts_code', 'cutoff_time', 'lookback_days']
P0_COLUMNS = [
    'ts_code',
    'trade_date',
    'cutoff_time',
    'lookback_days',
    'minute_count',
    'current_day_minute_count',
    'amount_total',
    'schema_version',
    'producer_version',
    'source_dataset',
    'no_future_intraday_minutes',
    'reference_price',
    'vwap_cost',
    'poc_price',
    'value_area_low',
    'value_area_high',
    'distance_to_poc',
    'distance_to_val',
    'distance_to_vah',
    'bin_width_bps',
    'near_band_bps',
    'profile_bin_count',
    'lower_support_mass',
    'upper_overhang_mass',
    'below_price_amount_mass',
    'above_price_amount_mass',
    'lower_support_ratio',
    'upper_overhang_ratio',
    'below_mass_ratio',
    'above_mass_ratio',
    'below_cost_depth',
    'below_cost_depth_score',
    'downside_lvn_gap',
    'upside_lvn_vacuum',
    'no_break_gate',
    'defended_support_gate',
]


@dataclass(frozen=True)
class ValueOccupationParams:
    lookback_days: int = 20
    cutoff_time: str = '14:50:00'
    bin_width_bps: float = 20.0
    value_area_mass: float = 0.70
    near_band_bps: float = 300.0
    min_minutes: int = 20


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '')
    text = re.sub(r'\s+00:00:00$', '', text)
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'invalid trade_date: {value!r}')
    return parsed.strftime('%Y%m%d')


def cutoff_to_hhmmss(value: str | int | None) -> int:
    raw = str(value or '14:50:00').strip()
    digits = re.sub(r'[^0-9]', '', raw)
    if len(digits) <= 4:
        return int(digits) * 100
    return int(digits[:6])


def normalize_cutoff_time(value: str | int | None) -> str:
    hhmmss = f'{cutoff_to_hhmmss(value):06d}'
    return f'{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}'


def time_key(series: pd.Series) -> pd.Series:
    token = series.astype(str).str.strip().str.split().str[-1].str.replace(':', '', regex=False)
    digits = token.str.extract(r'(\d{3,6})$', expand=False).fillna('145000')
    numeric = pd.to_numeric(digits, errors='coerce')
    short = numeric.where(digits.str.len() > 4, numeric * 100)
    return short.fillna(145000).astype(int)


def prepare_minute_frame(minute_df: pd.DataFrame, params: ValueOccupationParams) -> pd.DataFrame:
    minute = minute_df.copy()
    required = {'ts_code', 'trade_date', 'close'}
    missing = sorted(required - set(minute.columns))
    if missing:
        raise ValueError(f'minute_df missing required columns: {missing}')
    if 'trade_time' not in minute.columns:
        minute['trade_time'] = minute['bar_time'] if 'bar_time' in minute.columns else params.cutoff_time
    if 'amount' not in minute.columns:
        if 'vol' not in minute.columns:
            raise ValueError('minute_df must include amount or vol')
        minute['amount'] = minute['vol']
    for col in ['close', 'amount']:
        minute[col] = pd.to_numeric(minute[col], errors='coerce')
    minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
    minute['hhmmss'] = time_key(minute['trade_time'])
    minute = minute[minute['hhmmss'] <= cutoff_to_hhmmss(params.cutoff_time)].copy()
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'close', 'amount'])
    minute = minute[(minute['close'] > 0) & (minute['amount'].abs() > 0)]
    minute['price'] = minute['close'].astype(float)
    minute['mass'] = minute['amount'].abs().astype(float)
    return minute.sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0 else 0.0


def derive_one_value_occupation_state(
    window: pd.DataFrame,
    trade_date: str,
    ts_code: str,
    params: ValueOccupationParams,
) -> dict[str, Any] | None:
    current = window[window['trade_date'] == trade_date].sort_values('hhmmss')
    if current.empty:
        return None
    reference_price = _safe_float(current['price'].iloc[-1])
    if reference_price is None or reference_price <= 0:
        return None
    minute_count = int(len(window))
    current_minute_count = int(len(current))
    if minute_count < params.min_minutes or current_minute_count < params.min_minutes:
        return None

    price = window['price'].to_numpy(dtype=float)
    mass = window['mass'].to_numpy(dtype=float)
    amount_total = float(mass.sum())
    if amount_total <= 0:
        return None

    bin_width = max(reference_price * params.bin_width_bps / 10000.0, 1e-8)
    bin_id = np.floor((price - reference_price) / bin_width).astype(int)
    profile = pd.DataFrame({'bin_id': bin_id, 'price': price, 'mass': mass})
    profile = profile.groupby('bin_id', sort=True).agg(mass=('mass', 'sum'), price_mean=('price', 'mean')).reset_index()
    profile['bin_price'] = reference_price + (profile['bin_id'] + 0.5) * bin_width
    profile = profile.sort_values('bin_id')

    poc_row = profile.loc[profile['mass'].idxmax()]
    poc_price = float(poc_row['bin_price'])
    ranked = profile.sort_values('mass', ascending=False).copy()
    ranked['cum_mass'] = ranked['mass'].cumsum()
    ranked['cum_mass_prev'] = ranked['cum_mass'] - ranked['mass']
    selected = ranked[ranked['cum_mass_prev'] < amount_total * params.value_area_mass]
    if selected.empty:
        selected = ranked.head(1)
    value_area_low = float(selected['bin_price'].min())
    value_area_high = float(selected['bin_price'].max())

    near_low = reference_price * (1.0 - params.near_band_bps / 10000.0)
    near_high = reference_price * (1.0 + params.near_band_bps / 10000.0)
    lower_mask = (price < reference_price) & (price >= near_low)
    upper_mask = (price > reference_price) & (price <= near_high)
    lower_support_mass = float(mass[lower_mask].sum())
    upper_overhang_mass = float(mass[upper_mask].sum())
    below_price_amount_mass = float(mass[price < reference_price].sum())
    above_price_amount_mass = float(mass[price > reference_price].sum())

    vwap_cost = float(np.average(price, weights=mass))
    below_cost_depth = max(0.0, (vwap_cost - reference_price) / reference_price)
    lower_support_ratio = _ratio(lower_support_mass, amount_total)
    upper_overhang_ratio = _ratio(upper_overhang_mass, amount_total)
    below_mass_ratio = _ratio(below_price_amount_mass, amount_total)
    above_mass_ratio = _ratio(above_price_amount_mass, amount_total)

    downside_lvn_gap = max(0.0, 1.0 - lower_support_ratio / max(params.near_band_bps / 10000.0, 1e-12))
    upside_lvn_vacuum = max(0.0, 1.0 - upper_overhang_ratio / max(params.near_band_bps / 10000.0, 1e-12))
    no_break_gate = 1.0 if reference_price >= value_area_low else 0.0
    defended_support_gate = 1.0 if lower_support_ratio > upper_overhang_ratio * 0.5 else 0.0

    return {
        'ts_code': str(ts_code),
        'trade_date': trade_date,
        'cutoff_time': normalize_cutoff_time(params.cutoff_time),
        'lookback_days': int(params.lookback_days),
        'minute_count': minute_count,
        'current_day_minute_count': current_minute_count,
        'amount_total': amount_total,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'no_future_intraday_minutes': True,
        'reference_price': reference_price,
        'vwap_cost': vwap_cost,
        'poc_price': poc_price,
        'value_area_low': value_area_low,
        'value_area_high': value_area_high,
        'distance_to_poc': (poc_price - reference_price) / reference_price,
        'distance_to_val': (value_area_low - reference_price) / reference_price,
        'distance_to_vah': (value_area_high - reference_price) / reference_price,
        'bin_width_bps': float(params.bin_width_bps),
        'near_band_bps': float(params.near_band_bps),
        'profile_bin_count': int(len(profile)),
        'lower_support_mass': lower_support_mass,
        'upper_overhang_mass': upper_overhang_mass,
        'below_price_amount_mass': below_price_amount_mass,
        'above_price_amount_mass': above_price_amount_mass,
        'lower_support_ratio': lower_support_ratio,
        'upper_overhang_ratio': upper_overhang_ratio,
        'below_mass_ratio': below_mass_ratio,
        'above_mass_ratio': above_mass_ratio,
        'below_cost_depth': below_cost_depth,
        'below_cost_depth_score': below_cost_depth * 100.0,
        'downside_lvn_gap': downside_lvn_gap,
        'upside_lvn_vacuum': upside_lvn_vacuum,
        'no_break_gate': no_break_gate,
        'defended_support_gate': defended_support_gate,
    }


def derive_intraday_value_occupation_state(
    minute_df: pd.DataFrame,
    params: ValueOccupationParams,
    *,
    target_dates: list[str] | None = None,
    calendar_dates: list[str] | None = None,
) -> pd.DataFrame:
    minute = prepare_minute_frame(minute_df, params)
    targets = {normalize_trade_date(date) for date in target_dates} if target_dates else None
    calendar = sorted({normalize_trade_date(date) for date in calendar_dates}) if calendar_dates else None
    calendar_index = {date: idx for idx, date in enumerate(calendar or [])}
    rows: list[dict[str, Any]] = []
    for ts_code, stock in minute.groupby('ts_code', sort=True):
        dates = sorted(stock['trade_date'].unique())
        iterate_dates = [date for date in (calendar or dates) if targets is None or date in targets]
        for idx, trade_date in enumerate(iterate_dates):
            if targets is not None and trade_date not in targets:
                continue
            if calendar:
                cal_idx = calendar_index[trade_date]
                window_dates = set(calendar[max(0, cal_idx - params.lookback_days + 1): cal_idx + 1])
            else:
                if trade_date not in dates:
                    continue
                stock_idx = dates.index(trade_date)
                window_dates = set(dates[max(0, stock_idx - params.lookback_days + 1): stock_idx + 1])
            window = stock[stock['trade_date'].isin(window_dates)]
            row = derive_one_value_occupation_state(window, trade_date, str(ts_code), params)
            if row is not None:
                rows.append(row)
    if not rows:
        return pd.DataFrame(columns=P0_COLUMNS)
    return pd.DataFrame(rows)[P0_COLUMNS].sort_values(SORT_KEYS).reset_index(drop=True)


def write_partitioned_datamart(frame: pd.DataFrame, output_root: str | Path) -> Path:
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(root, partition_cols=['trade_date'], index=False)
    return root


def build_catalog_entry(
    output_root: str | Path,
    qa_output: str | Path,
    start_date: str,
    end_date: str,
    *,
    storage: str | None = None,
) -> dict[str, Any]:
    uri = str(output_root) if str(output_root).startswith('s3://') else str(Path(output_root).expanduser())
    return {
        'uri': uri,
        'format': 'parquet',
        'storage': storage or ('s3' if uri.startswith('s3://') else 'local'),
        'description': 'Daily price-axis value occupation state from minute_bar, P0 state variables only.',
        'columns': P0_COLUMNS,
        'partition_columns': ['trade_date'],
        'date_column': 'trade_date',
        'symbol_column': 'ts_code',
        'metadata': {
            'source_dataset': SOURCE_DATASET,
            'schema_version': SCHEMA_VERSION,
            'producer_version': PRODUCER_VERSION,
            'unique_key': UNIQUE_KEY,
            'sort_keys': SORT_KEYS,
            'cutoff_times': ['14:50:00'],
            'lookback_days': [20],
            'bin_width_bps': 20,
            'value_area_mass': 0.70,
            'near_band_bps': 300,
            'no_future_intraday_minutes': True,
            'research_window': 'IS',
            'research_p0_confirmed_at': '2026-06-10',
            'research_p0_confirmed_scope': 'P0 state variables only; research side computes composite scores and alpha evaluation downstream.',
            'missing_date_policy': 'source_ready_trade_dates_only',
            'oos_holdout_policy': 'post_20250711_not_used_for_fitting',
            'field_boundary': 'state_variables_only_no_alpha_scores',
            'qa_summary_path': str(Path(qa_output).expanduser()),
        },
        'freshness': {
            'trade_date_min': normalize_trade_date(start_date),
            'trade_date_max': normalize_trade_date(end_date),
        },
    }


def build_qa_summary(
    frame: pd.DataFrame,
    *,
    params: ValueOccupationParams,
    source_min_trade_date: str | None,
    source_max_trade_date: str | None,
    missing_dates: list[str],
    output_path: str | Path,
    catalog_path: str | Path,
    runtime_seconds: float,
    input_minute_row_count: int,
    source_profile: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    numeric = frame.select_dtypes(include=['number']).columns.tolist() if not frame.empty else []
    null_ratio = {col: float(frame[col].isna().mean()) for col in frame.columns} if not frame.empty else {}
    finite_ratio = {
        col: float(np.isfinite(pd.to_numeric(frame[col], errors='coerce')).mean())
        for col in numeric
    } if not frame.empty else {}
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if not frame.empty else 0
    non_negative_fields = ['lower_support_ratio', 'upper_overhang_ratio', 'below_cost_depth', 'amount_total']
    non_negative_checks = {
        col: bool((pd.to_numeric(frame[col], errors='coerce') >= 0).all()) if col in frame.columns and not frame.empty else False
        for col in non_negative_fields
    }
    ratio_fields = ['lower_support_ratio', 'upper_overhang_ratio', 'below_mass_ratio', 'above_mass_ratio']
    ratio_checks = {
        col: bool(((pd.to_numeric(frame[col], errors='coerce') >= 0) & (pd.to_numeric(frame[col], errors='coerce') <= 1)).all())
        if col in frame.columns and not frame.empty else False
        for col in ratio_fields
    }
    minute_count_ok = bool((frame['minute_count'] >= params.min_minutes).all()) if 'minute_count' in frame.columns and not frame.empty else False
    no_future_ok = bool(frame['no_future_intraday_minutes'].eq(True).all()) if 'no_future_intraday_minutes' in frame.columns and not frame.empty else False
    hard_checks = {
        'duplicate_key_count_zero': duplicate_key_count == 0,
        'minute_count_gte_min_minutes': minute_count_ok,
        'no_future_intraday_minutes_true': no_future_ok,
        **non_negative_checks,
        **ratio_checks,
    }
    verdict = 'ACCEPT' if frame is not None and not frame.empty and all(hard_checks.values()) else 'BLOCK'
    return {
        'verdict': verdict,
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'params': asdict(params),
        'source_min_trade_date': source_min_trade_date,
        'source_max_trade_date': source_max_trade_date,
        'output_min_trade_date': str(frame['trade_date'].min()) if 'trade_date' in frame.columns and not frame.empty else None,
        'output_max_trade_date': str(frame['trade_date'].max()) if 'trade_date' in frame.columns and not frame.empty else None,
        'row_count': int(len(frame)),
        'date_count': int(frame['trade_date'].nunique()) if 'trade_date' in frame.columns and not frame.empty else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'duplicate_key_count': duplicate_key_count,
        'missing_dates': list(missing_dates),
        'cutoff_times': sorted(frame['cutoff_time'].dropna().unique().tolist()) if 'cutoff_time' in frame.columns and not frame.empty else [],
        'lookback_days': sorted(int(x) for x in frame['lookback_days'].dropna().unique().tolist()) if 'lookback_days' in frame.columns and not frame.empty else [],
        'null_ratio_by_field': null_ratio,
        'finite_ratio_by_numeric_field': finite_ratio,
        'non_negative_checks': non_negative_checks,
        'ratio_checks': ratio_checks,
        'hard_checks': hard_checks,
        'coverage_by_date': frame.groupby('trade_date')['ts_code'].nunique().astype(int).to_dict() if not frame.empty else {},
        'runtime_seconds': float(runtime_seconds),
        'input_minute_row_count': int(input_minute_row_count),
        'output_path': str(Path(output_path).expanduser()),
        'catalog_path': str(Path(catalog_path).expanduser()),
        'source_profile': source_profile or [],
        'generated_at_utc': utc_now(),
    }
