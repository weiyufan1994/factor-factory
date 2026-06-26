from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATASET_ID = 'smart_money_intraday_state_v1'
SCHEMA_VERSION = 'smart_money_intraday_state_v1_p0'
PRODUCER_VERSION = 'factorforge_data_api_smart_money_intraday_state_20260622'
SOURCE_DATASET = 'minute_bar'
UNIQUE_KEY = ['ts_code', 'trade_date']
SORT_KEYS = ['trade_date', 'ts_code']
VARIANTS = (
    'log_volume',
    'beta_0p1',
    'beta_0p25',
    'original_beta_0p5',
    'volume_only',
    'rank_absret_plus_rankvol',
)
OUTPUT_COLUMNS = [
    'ts_code',
    'trade_date',
    'q_log_volume',
    'q_beta_0p1',
    'q_beta_0p25',
    'q_original_beta_0p5',
    'q_volume_only',
    'q_rank_absret_plus_rankvol',
    'vwap_smart_log_volume',
    'vwap_all',
    'selected_volume_share',
    'selected_minute_count',
    'lookback_trading_days',
    'cutoff_volume_share',
    'volume_unit',
    'price_field',
    'amount_unit',
    'source_min_date',
    'source_max_date',
    'minute_count',
    'valid_minute_count',
    'missing_minute_count',
    'zero_volume_count',
    'log_volume_invalid_count',
    'qa_status',
    'schema_version',
    'producer_version',
    'source_dataset',
    'no_future_data',
    'no_future_intraday_minutes',
    'research_window',
]


@dataclass(frozen=True)
class SmartMoneyIntradayStateParams:
    lookback_trading_days: int = 10
    cutoff_volume_share: float = 0.20
    volume_unit: str = 'minute_bar_vol_as_delivered'
    amount_unit: str = 'minute_bar_amount_as_delivered'
    price_field: str = 'amount_div_vol_else_close'
    research_window: str = 'IS'
    min_valid_minutes: int = 5
    eps: float = 1e-12


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '')
    text = re.sub(r'\s+00:00:00$', '', text)
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'invalid trade_date: {value!r}')
    return parsed.strftime('%Y%m%d')


def time_key(series: pd.Series) -> pd.Series:
    token = series.astype(str).str.strip().str.split().str[-1].str.replace(':', '', regex=False)
    digits = token.str.extract(r'(\d{3,6})$', expand=False).fillna('150000')
    numeric = pd.to_numeric(digits, errors='coerce')
    short = numeric.where(digits.str.len() > 4, numeric * 100)
    return short.fillna(150000).astype(int)


def prepare_minute_frame(minute_df: pd.DataFrame, params: SmartMoneyIntradayStateParams | None = None) -> pd.DataFrame:
    cfg = params or SmartMoneyIntradayStateParams()
    required = {'ts_code', 'trade_date', 'open', 'close', 'vol', 'amount'}
    missing = sorted(required - set(minute_df.columns))
    if missing:
        raise ValueError(f'minute_df missing required columns: {missing}')
    minute = minute_df.copy()
    if 'trade_time' not in minute.columns:
        minute['trade_time'] = minute['bar_time'] if 'bar_time' in minute.columns else '15:00:00'
    minute['trade_date'] = minute['trade_date'].map(normalize_trade_date)
    minute['hhmmss'] = time_key(minute['trade_time'])
    for col in ['open', 'close', 'vol', 'amount']:
        minute[col] = pd.to_numeric(minute[col], errors='coerce')
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'hhmmss', 'open', 'close', 'vol', 'amount'])
    minute = minute[(minute['open'] > 0) & (minute['close'] > 0)].copy()
    minute = minute.sort_values(['ts_code', 'trade_date', 'hhmmss']).reset_index(drop=True)
    prev_close = minute.groupby('ts_code', sort=False)['close'].shift(1)
    close_to_prev = minute['close'] / prev_close - 1.0
    open_to_close = minute['close'] / minute['open'] - 1.0
    minute['minute_return'] = close_to_prev.where(prev_close.gt(0), open_to_close)
    minute['price_for_vwap'] = np.where(minute['vol'] > 0, minute['amount'] / (minute['vol'] + cfg.eps), minute['close'])
    minute['abs_return'] = minute['minute_return'].abs()
    return minute.reset_index(drop=True)


def _select_by_score(frame: pd.DataFrame, score: pd.Series, params: SmartMoneyIntradayStateParams) -> dict[str, float | int]:
    current = frame.assign(_score=pd.to_numeric(score, errors='coerce')).dropna(subset=['_score']).copy()
    current = current[(current['vol'] > 0) & np.isfinite(current['_score']) & np.isfinite(current['price_for_vwap'])].copy()
    if current.empty:
        return {'q': np.nan, 'vwap_smart': np.nan, 'selected_volume_share': 0.0, 'selected_minute_count': 0}
    current = current.sort_values(['_score', 'hhmmss'], ascending=[False, True])
    total_volume = float(current['vol'].sum())
    if not np.isfinite(total_volume) or total_volume <= 0:
        return {'q': np.nan, 'vwap_smart': np.nan, 'selected_volume_share': 0.0, 'selected_minute_count': 0}
    cumulative = current['vol'].cumsum().to_numpy(dtype=np.float64)
    cutoff = max(float(params.cutoff_volume_share), 0.0) * total_volume
    stop = int(np.searchsorted(cumulative, cutoff, side='left')) + 1
    selected = current.iloc[: max(stop, 1)]
    selected_volume = float(selected['vol'].sum())
    vwap_smart = float((selected['price_for_vwap'] * selected['vol']).sum() / selected_volume)
    vwap_all = float((current['price_for_vwap'] * current['vol']).sum() / total_volume)
    q = vwap_smart / vwap_all if np.isfinite(vwap_all) and abs(vwap_all) > params.eps else np.nan
    return {
        'q': q,
        'vwap_smart': vwap_smart,
        'selected_volume_share': selected_volume / total_volume,
        'selected_minute_count': int(len(selected)),
    }


def _select_by_score_arrays(
    price: np.ndarray,
    volume: np.ndarray,
    hhmmss: np.ndarray,
    score: np.ndarray,
    params: SmartMoneyIntradayStateParams,
    *,
    total_volume: float,
    vwap_all: float,
) -> dict[str, float | int]:
    valid_mask = (
        (volume > 0)
        & np.isfinite(volume)
        & np.isfinite(price)
        & np.isfinite(score)
    )
    if not bool(valid_mask.any()):
        return {'q': np.nan, 'vwap_smart': np.nan, 'selected_volume_share': 0.0, 'selected_minute_count': 0}
    vol = volume[valid_mask].astype(np.float64, copy=False)
    px = price[valid_mask].astype(np.float64, copy=False)
    sc = score[valid_mask].astype(np.float64, copy=False)
    tm = hhmmss[valid_mask].astype(np.int64, copy=False)
    if not np.isfinite(total_volume) or total_volume <= 0:
        return {'q': np.nan, 'vwap_smart': np.nan, 'selected_volume_share': 0.0, 'selected_minute_count': 0}
    order = np.lexsort((tm, -sc))
    ordered_volume = vol[order]
    cumulative = np.cumsum(ordered_volume, dtype=np.float64)
    cutoff = max(float(params.cutoff_volume_share), 0.0) * total_volume
    stop = int(np.searchsorted(cumulative, cutoff, side='left')) + 1
    stop = max(stop, 1)
    selected_index = order[:stop]
    selected_volume = float(vol[selected_index].sum())
    if not np.isfinite(selected_volume) or selected_volume <= 0:
        return {'q': np.nan, 'vwap_smart': np.nan, 'selected_volume_share': 0.0, 'selected_minute_count': 0}
    vwap_smart = float((px[selected_index] * vol[selected_index]).sum() / selected_volume)
    q = vwap_smart / vwap_all if np.isfinite(vwap_all) and abs(vwap_all) > params.eps else np.nan
    return {
        'q': q,
        'vwap_smart': vwap_smart,
        'selected_volume_share': selected_volume / total_volume,
        'selected_minute_count': int(stop),
    }


def _variant_scores(stock: pd.DataFrame, params: SmartMoneyIntradayStateParams) -> dict[str, pd.Series]:
    volume = pd.to_numeric(stock['vol'], errors='coerce')
    abs_return = pd.to_numeric(stock['abs_return'], errors='coerce')
    safe_log_volume = np.log(volume.clip(lower=np.e))
    rank_abs = abs_return.rank(method='average', pct=True)
    rank_vol = volume.rank(method='average', pct=True)
    return {
        'log_volume': abs_return / safe_log_volume,
        'beta_0p1': abs_return / np.power(volume.clip(lower=params.eps), 0.1),
        'beta_0p25': abs_return / np.power(volume.clip(lower=params.eps), 0.25),
        'original_beta_0p5': abs_return / np.power(volume.clip(lower=params.eps), 0.5),
        'volume_only': volume,
        'rank_absret_plus_rankvol': rank_abs + rank_vol,
    }


def _variant_score_arrays(valid: pd.DataFrame, params: SmartMoneyIntradayStateParams) -> dict[str, np.ndarray]:
    volume = pd.to_numeric(valid['vol'], errors='coerce').to_numpy(dtype=np.float64, copy=False)
    abs_return = pd.to_numeric(valid['abs_return'], errors='coerce').to_numpy(dtype=np.float64, copy=False)
    safe_volume = np.clip(volume, params.eps, None)
    safe_log_volume = np.log(np.clip(volume, np.e, None))
    rank_abs = pd.Series(abs_return).rank(method='average', pct=True).to_numpy(dtype=np.float64, copy=False)
    rank_vol = pd.Series(volume).rank(method='average', pct=True).to_numpy(dtype=np.float64, copy=False)
    return {
        'log_volume': abs_return / safe_log_volume,
        'beta_0p1': abs_return / np.power(safe_volume, 0.1),
        'beta_0p25': abs_return / np.power(safe_volume, 0.25),
        'original_beta_0p5': abs_return / np.power(safe_volume, 0.5),
        'volume_only': volume,
        'rank_absret_plus_rankvol': rank_abs + rank_vol,
    }


def _stock_metrics(valid: pd.DataFrame, params: SmartMoneyIntradayStateParams) -> tuple[float, dict[str, dict[str, float | int]], int]:
    total_volume = float(valid['vol'].sum()) if not valid.empty else 0.0
    if valid.empty or total_volume <= 0:
        return np.nan, {}, 0
    volume = pd.to_numeric(valid['vol'], errors='coerce').to_numpy(dtype=np.float64, copy=False)
    price = pd.to_numeric(valid['price_for_vwap'], errors='coerce').to_numpy(dtype=np.float64, copy=False)
    hhmmss = pd.to_numeric(valid['hhmmss'], errors='coerce').fillna(150000).to_numpy(dtype=np.int64, copy=False)
    vwap_all = (
        float(np.sum(price * volume) / total_volume)
        if np.isfinite(total_volume) and total_volume > 0 else np.nan
    )
    scores = _variant_score_arrays(valid, params)
    metrics = {
        name: _select_by_score_arrays(
            price,
            volume,
            hhmmss,
            score,
            params,
            total_volume=total_volume,
            vwap_all=vwap_all,
        )
        for name, score in scores.items()
    }
    log_invalid = int((~np.isfinite(np.log(np.clip(volume, np.e, None)))).sum())
    return vwap_all, metrics, log_invalid


def derive_smart_money_intraday_state(
    minute_df: pd.DataFrame,
    *,
    target_dates: list[str] | None = None,
    params: SmartMoneyIntradayStateParams | None = None,
) -> pd.DataFrame:
    cfg = params or SmartMoneyIntradayStateParams()
    if cfg.lookback_trading_days <= 0:
        raise ValueError('lookback_trading_days must be positive')
    if not (0 < float(cfg.cutoff_volume_share) <= 1):
        raise ValueError('cutoff_volume_share must be in (0, 1]')
    minute = prepare_minute_frame(minute_df, cfg)
    all_dates = sorted(minute['trade_date'].dropna().unique().tolist())
    targets = sorted({normalize_trade_date(date) for date in (target_dates or all_dates)})
    date_pos = {date: index for index, date in enumerate(all_dates)}
    rows: list[dict[str, Any]] = []
    for target in targets:
        if target not in date_pos:
            continue
        end = date_pos[target]
        window_dates = all_dates[max(0, end - int(cfg.lookback_trading_days) + 1): end + 1]
        window = minute[minute['trade_date'].isin(window_dates)].copy()
        if window.empty:
            continue
        for ts_code, stock in window.groupby('ts_code', sort=True):
            stock = stock.sort_values(['trade_date', 'hhmmss']).reset_index(drop=True)
            valid = stock[(stock['vol'] > 0) & stock['minute_return'].notna() & stock['price_for_vwap'].notna()].copy()
            vwap_all, metrics, log_invalid = _stock_metrics(valid, cfg)
            primary = metrics.get('log_volume', {'selected_volume_share': 0.0, 'selected_minute_count': 0, 'vwap_smart': np.nan})
            qa_status = 'pass' if len(valid) >= int(cfg.min_valid_minutes) and metrics else 'insufficient_valid_minutes'
            rows.append({
                'ts_code': str(ts_code),
                'trade_date': str(target),
                'q_log_volume': metrics.get('log_volume', {}).get('q', np.nan),
                'q_beta_0p1': metrics.get('beta_0p1', {}).get('q', np.nan),
                'q_beta_0p25': metrics.get('beta_0p25', {}).get('q', np.nan),
                'q_original_beta_0p5': metrics.get('original_beta_0p5', {}).get('q', np.nan),
                'q_volume_only': metrics.get('volume_only', {}).get('q', np.nan),
                'q_rank_absret_plus_rankvol': metrics.get('rank_absret_plus_rankvol', {}).get('q', np.nan),
                'vwap_smart_log_volume': primary.get('vwap_smart', np.nan),
                'vwap_all': vwap_all,
                'selected_volume_share': primary.get('selected_volume_share', 0.0),
                'selected_minute_count': primary.get('selected_minute_count', 0),
                'lookback_trading_days': int(cfg.lookback_trading_days),
                'cutoff_volume_share': float(cfg.cutoff_volume_share),
                'volume_unit': cfg.volume_unit,
                'price_field': cfg.price_field,
                'amount_unit': cfg.amount_unit,
                'source_min_date': str(min(window_dates)) if window_dates else None,
                'source_max_date': str(max(window_dates)) if window_dates else None,
                'minute_count': int(len(stock)),
                'valid_minute_count': int(len(valid)),
                'missing_minute_count': max(0, len(window_dates) * 240 - int(len(stock))),
                'zero_volume_count': int((stock['vol'] <= 0).sum()),
                'log_volume_invalid_count': log_invalid,
                'qa_status': qa_status,
                'schema_version': SCHEMA_VERSION,
                'producer_version': PRODUCER_VERSION,
                'source_dataset': SOURCE_DATASET,
                'no_future_data': True,
                'no_future_intraday_minutes': True,
                'research_window': cfg.research_window,
            })
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = pd.DataFrame(rows)
    out = out[OUTPUT_COLUMNS].sort_values(SORT_KEYS).reset_index(drop=True)
    out['no_future_data'] = pd.Series([True] * len(out), dtype=object)
    out['no_future_intraday_minutes'] = pd.Series([True] * len(out), dtype=object)
    out.attrs['dataset_id'] = DATASET_ID
    out.attrs['schema_version'] = SCHEMA_VERSION
    return out


def build_smart_money_intraday_state_qa(
    frame: pd.DataFrame,
    *,
    params: SmartMoneyIntradayStateParams | None = None,
    missing_dates: list[str] | None = None,
    output_path: str | Path | None = None,
    runtime_seconds: float | None = None,
    input_minute_row_count: int | None = None,
) -> dict[str, Any]:
    cfg = params or SmartMoneyIntradayStateParams()
    dates = frame['trade_date'].astype(str) if 'trade_date' in frame.columns and not frame.empty else pd.Series(dtype=str)
    duplicate_key_count = int(frame.duplicated(UNIQUE_KEY).sum()) if all(col in frame.columns for col in UNIQUE_KEY) else 0
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    issues: list[str] = []
    if frame.empty:
        issues.append('row_count_zero')
    if duplicate_key_count:
        issues.append('duplicate_key_count_nonzero')
    if missing_columns:
        issues.append('missing_expected_columns')
    if missing_dates:
        issues.append('missing_dates_nonempty')
    qa_status_counts: dict[str, int] = {}
    if 'qa_status' in frame.columns and not frame.empty:
        qa_status_counts = {str(key): int(value) for key, value in frame['qa_status'].value_counts(dropna=False).items()}
        if qa_status_counts.get('pass', 0) <= 0:
            issues.append('qa_status_pass_row_count_zero')
    elif not frame.empty:
        issues.append('qa_status_missing')
    if 'no_future_intraday_minutes' in frame.columns and not frame.empty and not bool(frame['no_future_intraday_minutes'].all()):
        issues.append('no_future_intraday_minutes_not_true')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'producer_version': PRODUCER_VERSION,
        'source_dataset': SOURCE_DATASET,
        'unique_key': UNIQUE_KEY,
        'partition_column': 'trade_date',
        'lookback_trading_days': int(cfg.lookback_trading_days),
        'cutoff_volume_share': float(cfg.cutoff_volume_share),
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if not dates.empty else 0,
        'ticker_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'start_date': str(dates.min()) if not dates.empty else None,
        'end_date': str(dates.max()) if not dates.empty else None,
        'duplicate_key_count': duplicate_key_count,
        'qa_status_counts': qa_status_counts,
        'missing_columns': missing_columns,
        'missing_dates': list(missing_dates or []),
        'output_path': str(output_path) if output_path is not None else '',
        'runtime_seconds': runtime_seconds,
        'input_minute_row_count': input_minute_row_count,
        'issues': issues,
        'information_set_legality': {
            'no_future_data': True,
            'no_future_intraday_minutes': True,
            'window_rule': 'each target trade_date uses only minute rows whose trade_date is <= target trade_date',
            'state_only_no_alpha_labels': True,
        },
    }


def build_catalog_entry(
    uri: str | Path,
    qa_path: str | Path,
    start: str,
    end: str,
    *,
    params: SmartMoneyIntradayStateParams | None = None,
) -> dict[str, Any]:
    cfg = params or SmartMoneyIntradayStateParams()
    return {
        'dataset_id': DATASET_ID,
        'uri': str(uri),
        'format': 'parquet',
        'version': 'v1',
        'storage': 'local',
        'description': 'Smart-money intraday state Q variants from 10 trading days of minute_bar selected by S-score cumulative volume.',
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
            'variants': list(VARIANTS),
            'lookback_trading_days': int(cfg.lookback_trading_days),
            'cutoff_volume_share': float(cfg.cutoff_volume_share),
            'qa_summary_path': str(qa_path),
            'information_set_legality': 'uses only minute bars through target trade_date; no future returns or labels',
            'no_future_data': True,
            'no_future_intraday_minutes': True,
            'research_window': str(cfg.research_window),
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
