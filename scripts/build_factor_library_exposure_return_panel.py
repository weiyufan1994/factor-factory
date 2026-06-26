#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.fs as fs


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


REGISTRY_DATASET_ID = 'factor_library_registry_v1'
EXPOSURE_DATASET_ID = 'factor_library_exposure_panel_v1'
RETURN_DATASET_ID = 'factor_library_factor_return_panel_v1'
SCHEMA_VERSION = 'factor_library_exposure_return_panel_v1_20260622'
OOS_START = '20250714'
OOS_END = '20260612'
READ_SMOKE_DATES = ['20250714', '20251231', '20260612']

REGISTRY_COLUMNS = [
    'factor_id',
    'factor_version',
    'factor_name',
    'factor_family',
    'library_status',
    'direction',
    'horizon',
    'holding_period',
    'source_report_id',
    'implementation_mode',
    'formula_or_law_hash',
    'exposure_dataset_version',
    'return_dataset_version',
    'admission_status',
    'admission_date',
    'owner',
]

EXPOSURE_COLUMNS = [
    'trade_date',
    'ts_code',
    'factor_id',
    'factor_version',
    'factor_value_raw',
    'factor_value_z',
    'factor_rank',
    'factor_direction',
    'standardization_scope',
    'universe_policy',
    'information_date',
    'effective_trade_date',
    'no_future_data',
    'source_artifact_path',
    'factor_value_identity_hash',
    'factor_value_winsorized',
    'factor_value_neutralized',
    'neutralization_policy',
    'industry_neutralized',
    'size_neutralized',
    'liquidity_neutralized',
    'missing_value_policy',
    'tradability_policy',
    'is_official_factor',
    'is_candidate_feature',
    'is_state_diagnostic',
]

RETURN_COLUMNS = [
    'trade_date',
    'factor_id',
    'factor_version',
    'return_type',
    'horizon',
    'holding_period',
    'universe',
    'factor_return',
    'factor_return_gross',
    'factor_return_net',
    'cost_model',
    'construction_policy',
    'information_lag_policy',
    'source_exposure_version',
    'source_return_field',
    'no_future_exposure',
    'label_maturity_policy',
    'factor_return_tstat_window',
    'factor_return_vol_window',
    'factor_return_z',
    'factor_return_rank',
    'long_leg_return',
    'short_leg_return',
    'long_only_top_bucket_excess_return',
    'turnover',
    'coverage_count',
    'effective_name_count',
    'regression_weight_policy',
    'neutralization_policy',
]


@dataclass(frozen=True)
class FactorSource:
    factor_id: str
    factor_version: str
    factor_name: str
    factor_family: str
    library_status: str
    direction: str
    source_report_id: str
    implementation_mode: str
    formula_or_law_hash: str
    admission_status: str
    admission_date: str
    owner: str
    record_path: Path
    factor_values_path: Path | None
    include: bool
    exclude_reason: str
    coverage_min_date: str | None
    coverage_max_date: str | None
    coverage_date_count: int
    coverage_missing_dates: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build Factor Library registry, exposure panel, and factor return panel P0/P1 datamarts.')
    ap.add_argument('--factor-research-root', default='/Users/humphrey/projects/factor-factory/factor_research')
    ap.add_argument('--run-root', default='/tmp/factor_library_exposure_return_panel_v1_20260622')
    ap.add_argument('--start', default=OOS_START)
    ap.add_argument('--end', default=OOS_END)
    ap.add_argument('--source-prefix', default='s3://yufan-data-lake/tushares')
    ap.add_argument('--clean-oos-slice-s3', default='s3://yufan-data-lake/factorforge/research_datamart/clean_daily_bar_oos_slice/v1')
    ap.add_argument('--output-registry-s3', default='s3://yufan-data-lake/factorforge/datamart/factor_library_registry/v1')
    ap.add_argument('--output-exposure-s3', default='s3://yufan-data-lake/factorforge/datamart/factor_library_exposure_panel/v1')
    ap.add_argument('--output-return-s3', default='s3://yufan-data-lake/factorforge/datamart/factor_library_factor_return_panel/v1')
    ap.add_argument('--research-registry-s3', default='s3://yufan-data-lake/factorforge/research_runs/dongwu_20241229_cpv_price_path_occupation_v3/research_20260616/_inputs/factor_library_registry')
    ap.add_argument('--research-exposure-s3', default='s3://yufan-data-lake/factorforge/research_runs/dongwu_20241229_cpv_price_path_occupation_v3/research_20260616/_inputs/factor_library_exposure_panel')
    ap.add_argument('--research-return-s3', default='s3://yufan-data-lake/factorforge/research_runs/dongwu_20241229_cpv_price_path_occupation_v3/research_20260616/_inputs/factor_library_factor_return_panel')
    ap.add_argument('--registry-proof-s3', default='s3://yufan-data-lake/factorforge/proofs/factor_library/registry/v1/proof.json')
    ap.add_argument('--exposure-proof-s3', default='s3://yufan-data-lake/factorforge/proofs/factor_library/exposure_panel/v1/proof.json')
    ap.add_argument('--return-proof-s3', default='s3://yufan-data-lake/factorforge/proofs/factor_library/factor_return_panel/v1/proof.json')
    ap.add_argument('--registry-catalog-s3', default='s3://yufan-data-lake/factorforge/proofs/factor_library/registry/v1/catalog.json')
    ap.add_argument('--exposure-catalog-s3', default='s3://yufan-data-lake/factorforge/proofs/factor_library/exposure_panel/v1/catalog.json')
    ap.add_argument('--return-catalog-s3', default='s3://yufan-data-lake/factorforge/proofs/factor_library/factor_return_panel/v1/catalog.json')
    ap.add_argument('--s3-region', default='ap-southeast-1')
    ap.add_argument('--horizon', type=int, default=1)
    ap.add_argument('--skip-upload', action='store_true')
    return ap.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '').replace('.0', '')
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'invalid trade_date: {value!r}')
    return parsed.strftime('%Y%m%d')


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def load_trade_calendar(raw_root: Path, source_prefix: str) -> pd.DataFrame:
    raw_root.mkdir(parents=True, exist_ok=True)
    path = raw_root / 'trade_cal.csv'
    if not path.exists():
        run(['aws', 's3', 'cp', f'{source_prefix.rstrip("/")}/基础数据/trade_cal.csv', str(path), '--only-show-errors'])
    cal = pd.read_csv(path, usecols=lambda c: c in {'cal_date', 'is_open'}, dtype={'cal_date': 'string'})
    cal['cal_date'] = cal['cal_date'].map(normalize_trade_date)
    return cal


def expected_open_dates(trade_calendar: pd.DataFrame, start: str, end: str) -> list[str]:
    return sorted(
        trade_calendar.loc[
            (trade_calendar['is_open'].astype(int) == 1)
            & (trade_calendar['cal_date'] >= start)
            & (trade_calendar['cal_date'] <= end),
            'cal_date',
        ].astype(str).unique().tolist()
    )


def label_source_dates(trade_calendar: pd.DataFrame, exposure_dates: list[str], horizon: int) -> list[str]:
    if not exposure_dates:
        return []
    open_dates = sorted(
        trade_calendar.loc[trade_calendar['is_open'].astype(int) == 1, 'cal_date']
        .astype(str)
        .unique()
        .tolist()
    )
    ranks = {date: idx for idx, date in enumerate(open_dates)}
    needed = set(exposure_dates)
    for date in exposure_dates:
        pos = ranks.get(date)
        if pos is None:
            continue
        fwd_pos = pos + int(horizon)
        if fwd_pos < len(open_dates):
            needed.add(open_dates[fwd_pos])
    return sorted(needed)


def download_daily_csv(raw_root: Path, source_prefix: str) -> Path:
    raw_root.mkdir(parents=True, exist_ok=True)
    path = raw_root / 'daily.csv'
    if not path.exists():
        run(['aws', 's3', 'cp', f'{source_prefix.rstrip("/")}/行情数据/daily.csv', str(path), '--only-show-errors'])
    return path


def sync_daily_incremental(raw_root: Path, source_prefix: str, trade_dates: list[str]) -> Path:
    root = raw_root / 'daily_incremental'
    root.mkdir(parents=True, exist_ok=True)
    source = f'{source_prefix.rstrip("/")}/行情数据/daily_incremental'
    for trade_date in trade_dates:
        target = root / f'trade_date={trade_date}'
        if target.exists() and any(target.iterdir()):
            continue
        run(['aws', 's3', 'sync', f'{source}/trade_date={trade_date}', str(target), '--only-show-errors'])
    return root


def read_daily_incremental(root: Path, trade_dates: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    wanted = set(trade_dates)
    for trade_date in trade_dates:
        part = root / f'trade_date={trade_date}'
        for path in sorted(part.glob('*')):
            if path.suffix == '.parquet':
                frame = pd.read_parquet(path, columns=['ts_code', 'trade_date', 'close'])
            elif path.suffix == '.csv':
                frame = pd.read_csv(
                    path,
                    usecols=lambda c: c in {'ts_code', 'trade_date', 'close'},
                    dtype={'ts_code': 'string', 'trade_date': 'string'},
                )
            else:
                continue
            frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
            frame = frame[frame['trade_date'].isin(wanted)]
            frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=['ts_code', 'trade_date', 'close'])


def read_return_labels_from_daily(daily: pd.DataFrame, required_dates: list[str], horizon: int) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(columns=['trade_date', 'ts_code', 'next_return'])
    daily = daily.copy()
    daily['trade_date'] = daily['trade_date'].map(normalize_trade_date)
    daily['close'] = pd.to_numeric(daily['close'], errors='coerce')
    daily = daily.sort_values(['ts_code', 'trade_date'])
    daily[f'close_fwd_{horizon}'] = daily.groupby('ts_code', sort=False)['close'].shift(-horizon)
    daily['next_return'] = daily[f'close_fwd_{horizon}'] / daily['close'] - 1.0
    labels = daily[daily['trade_date'].isin(required_dates)][['trade_date', 'ts_code', 'next_return']]
    return labels.dropna(subset=['next_return']).reset_index(drop=True)


def read_return_labels(daily_csv: Path, required_dates: list[str], horizon: int) -> pd.DataFrame:
    if not required_dates:
        return pd.DataFrame(columns=['trade_date', 'ts_code', 'next_return'])
    needed_min = min(required_dates)
    frames: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        daily_csv,
        usecols=lambda c: c in {'ts_code', 'trade_date', 'close', 'pct_chg'},
        dtype={'ts_code': 'string', 'trade_date': 'string'},
        chunksize=1_000_000,
    ):
        chunk['trade_date'] = chunk['trade_date'].map(normalize_trade_date)
        chunk = chunk[chunk['trade_date'] >= needed_min]
        if not chunk.empty:
            frames.append(chunk)
    daily = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=['ts_code', 'trade_date', 'close', 'pct_chg'])
    daily['close'] = pd.to_numeric(daily['close'], errors='coerce')
    daily = daily.sort_values(['ts_code', 'trade_date'])
    daily[f'close_fwd_{horizon}'] = daily.groupby('ts_code', sort=False)['close'].shift(-horizon)
    daily['next_return'] = daily[f'close_fwd_{horizon}'] / daily['close'] - 1.0
    labels = daily[daily['trade_date'].isin(required_dates)][['trade_date', 'ts_code', 'next_return']]
    return labels.dropna(subset=['next_return']).reset_index(drop=True)


def find_record_paths(root: Path) -> list[Path]:
    return sorted(root.glob('**/objects/factor_library_all/factor_record__*.json'))


def infer_library_status(record: dict[str, Any]) -> str:
    decision = str(record.get('decision') or '').lower()
    final_status = str(record.get('final_status') or '').lower()
    gate = record.get('promotion_gate') if isinstance(record.get('promotion_gate'), dict) else {}
    if gate.get('official_promotion_allowed') is True:
        return 'official'
    if decision == 'reject' or final_status == 'rejected':
        return 'rejected_but_memorized'
    if 'diagnostic' in str(record.get('factor_family') or '').lower():
        return 'state_diagnostic'
    return 'candidate_feature'


def infer_admission_status(record: dict[str, Any]) -> str:
    gate = record.get('promotion_gate') if isinstance(record.get('promotion_gate'), dict) else {}
    if gate.get('official_promotion_allowed') is True:
        return 'admitted'
    if str(record.get('decision') or '').lower() == 'reject':
        return 'rejected'
    return 'not_admitted'


def identity_hash(record: dict[str, Any]) -> str:
    identity = record.get('artifact_identity') if isinstance(record.get('artifact_identity'), dict) else {}
    for key in ['formula_hash', 'code_contract_hash', 'code_hash', 'spec_hash']:
        value = identity.get(key) or record.get(key)
        if value:
            return str(value)
    return stable_hash(json.dumps(record, sort_keys=True, ensure_ascii=False))


def implementation_mode(record: dict[str, Any]) -> str:
    decision = record.get('implementation_mode_decision') if isinstance(record.get('implementation_mode_decision'), dict) else {}
    identity = record.get('artifact_identity') if isinstance(record.get('artifact_identity'), dict) else {}
    return str(decision.get('selected_mode') or identity.get('implementation_mode') or 'unknown')


def factor_values_path_for(record_path: Path, report_id: str) -> Path | None:
    workspace = Path(str(record_path).split('/objects/factor_library_all/', 1)[0])
    candidates = [
        workspace / 'runs' / report_id / f'factor_values__{report_id}.parquet',
        workspace / 'archive' / report_id / 'runs' / f'factor_values__{report_id}.parquet',
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def inspect_factor_values(path: Path | None, expected_dates: list[str]) -> tuple[str | None, str | None, int, tuple[str, ...]]:
    if path is None or not path.exists():
        return None, None, 0, tuple(expected_dates)
    frame = pd.read_parquet(path, columns=['trade_date'])
    dates = set(frame['trade_date'].map(normalize_trade_date).astype(str).unique().tolist())
    missing = tuple(date for date in expected_dates if date not in dates)
    return (min(dates) if dates else None, max(dates) if dates else None, len(dates), missing)


def discover_factors(root: Path, expected_dates: list[str]) -> list[FactorSource]:
    factors = []
    for record_path in find_record_paths(root):
        record = json.loads(record_path.read_text(encoding='utf-8'))
        report_id = str(record.get('report_id') or record_path.stem.removeprefix('factor_record__'))
        factor_id = str(record.get('factor_id') or report_id)
        factor_version = report_id
        factor_values_path = factor_values_path_for(record_path, report_id)
        min_date, max_date, date_count, missing_dates = inspect_factor_values(factor_values_path, expected_dates)
        contains_cpv = 'cpv' in factor_id.lower() or 'cpv' in report_id.lower()
        include = factor_values_path is not None and not missing_dates and not contains_cpv
        if contains_cpv:
            exclude_reason = 'contains_cpv_not_allowed_for_p0_seed_library'
        elif factor_values_path is None:
            exclude_reason = 'factor_values_parquet_missing'
        elif missing_dates:
            exclude_reason = 'oos_coverage_missing'
        else:
            exclude_reason = ''
        factors.append(FactorSource(
            factor_id=factor_id,
            factor_version=factor_version,
            factor_name=str(record.get('factor_name') or factor_id),
            factor_family=str(record.get('factor_family') or 'unknown'),
            library_status=infer_library_status(record),
            direction=str(record.get('direction') or 'unknown'),
            source_report_id=report_id,
            implementation_mode=implementation_mode(record),
            formula_or_law_hash=identity_hash(record),
            admission_status=infer_admission_status(record),
            admission_date=str(record.get('admission_date') or ''),
            owner=str(record.get('owner') or 'factorforge_research'),
            record_path=record_path,
            factor_values_path=factor_values_path,
            include=include,
            exclude_reason=exclude_reason,
            coverage_min_date=min_date,
            coverage_max_date=max_date,
            coverage_date_count=date_count,
            coverage_missing_dates=missing_dates,
        ))
    return factors


def build_registry(factors: list[FactorSource]) -> pd.DataFrame:
    rows = []
    for f in factors:
        rows.append({
            'factor_id': f.factor_id,
            'factor_version': f.factor_version,
            'factor_name': f.factor_name,
            'factor_family': f.factor_family,
            'library_status': f.library_status,
            'direction': f.direction,
            'horizon': 1,
            'holding_period': 1,
            'source_report_id': f.source_report_id,
            'implementation_mode': f.implementation_mode,
            'formula_or_law_hash': f.formula_or_law_hash,
            'exposure_dataset_version': 'v1',
            'return_dataset_version': 'v1',
            'admission_status': f.admission_status,
            'admission_date': f.admission_date,
            'owner': f.owner,
        })
    return pd.DataFrame(rows, columns=REGISTRY_COLUMNS).sort_values(['factor_id', 'factor_version']).reset_index(drop=True)


def standardize_factor_values(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out['factor_value_raw'] = pd.to_numeric(out['factor_value'], errors='coerce')

    def _z(group: pd.DataFrame) -> pd.DataFrame:
        values = group['factor_value_raw']
        mean = values.mean(skipna=True)
        std = values.std(skipna=True, ddof=0)
        if not np.isfinite(std) or std == 0:
            group['factor_value_z'] = np.nan
        else:
            group['factor_value_z'] = (values - mean) / std
        group['factor_rank'] = values.rank(method='average', pct=True)
        return group

    return out.groupby(['trade_date', 'factor_id', 'factor_version'], group_keys=False, sort=False).apply(_z)


def build_exposure(factors: list[FactorSource], start: str, end: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for f in factors:
        if not f.include or f.factor_values_path is None:
            continue
        source_hash = file_hash(f.factor_values_path)
        frame = pd.read_parquet(f.factor_values_path)
        frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        frame = frame[(frame['trade_date'] >= start) & (frame['trade_date'] <= end)].copy()
        frame['ts_code'] = frame['ts_code'].astype(str)
        frame['factor_id'] = f.factor_id
        frame['factor_version'] = f.factor_version
        frame['factor_direction'] = f.direction
        frame['standardization_scope'] = 'full_market'
        frame['universe_policy'] = 'a_share_all_available_factor_values'
        frame['information_date'] = frame['trade_date']
        frame['effective_trade_date'] = frame['trade_date']
        frame['no_future_data'] = True
        frame['source_artifact_path'] = str(f.factor_values_path)
        frame['factor_value_identity_hash'] = source_hash
        frame['factor_value_winsorized'] = np.nan
        frame['factor_value_neutralized'] = np.nan
        frame['neutralization_policy'] = 'none_p0_raw_z_rank_only'
        frame['industry_neutralized'] = False
        frame['size_neutralized'] = False
        frame['liquidity_neutralized'] = False
        frame['missing_value_policy'] = 'drop_missing_factor_value_for_standardization'
        frame['tradability_policy'] = 'source_factor_values_universe_no_extra_filter'
        frame['is_official_factor'] = f.library_status == 'official'
        frame['is_candidate_feature'] = f.library_status == 'candidate_feature'
        frame['is_state_diagnostic'] = f.library_status == 'state_diagnostic'
        frames.append(frame)
    exposure = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=['trade_date', 'ts_code', 'factor_id', 'factor_version', 'factor_value'])
    exposure = standardize_factor_values(exposure)
    return exposure[EXPOSURE_COLUMNS].sort_values(['trade_date', 'factor_id', 'factor_version', 'ts_code']).reset_index(drop=True)


def safe_tstat(values: pd.Series) -> float:
    series = pd.to_numeric(values, errors='coerce').dropna()
    if len(series) < 3:
        return math.nan
    std = series.std(ddof=1)
    if not np.isfinite(std) or std == 0:
        return math.nan
    return float(series.mean() / (std / math.sqrt(len(series))))


def build_return_panel(exposure: pd.DataFrame, labels: pd.DataFrame, horizon: int) -> pd.DataFrame:
    merged = exposure[['trade_date', 'ts_code', 'factor_id', 'factor_version', 'factor_value_z', 'factor_rank']].merge(
        labels,
        on=['trade_date', 'ts_code'],
        how='inner',
    )
    rows = []
    for (trade_date, factor_id, factor_version), group in merged.groupby(['trade_date', 'factor_id', 'factor_version'], sort=True, observed=True):
        work = group.dropna(subset=['factor_value_z', 'factor_rank', 'next_return']).copy()
        if len(work) < 20:
            continue
        z = work['factor_value_z'].to_numpy(dtype=float)
        r = work['next_return'].to_numpy(dtype=float)
        premium = float(np.dot(z, r) / np.dot(z, z)) if np.dot(z, z) > 0 else math.nan
        top_q = work['factor_rank'].quantile(0.9)
        bottom_q = work['factor_rank'].quantile(0.1)
        long_leg = float(work.loc[work['factor_rank'] >= top_q, 'next_return'].mean())
        short_leg = float(work.loc[work['factor_rank'] <= bottom_q, 'next_return'].mean())
        universe_ret = float(work['next_return'].mean())
        long_only_active = long_leg - universe_ret
        long_short = long_leg - short_leg
        base = {
            'trade_date': trade_date,
            'factor_id': factor_id,
            'factor_version': factor_version,
            'horizon': horizon,
            'holding_period': horizon,
            'universe': 'full_market',
            'cost_model': 'zero_cost_p0_diagnostic',
            'information_lag_policy': 'exposure_trade_date_t_close_to_close_forward_1d_realized_label',
            'source_exposure_version': 'factor_library_exposure_panel_v1',
            'source_return_field': 'tushare_daily_close_forward_1d_return',
            'no_future_exposure': True,
            'label_maturity_policy': 'requires next trading day close; raw daily source covers 20260612 next-day label',
            'factor_return_tstat_window': np.nan,
            'factor_return_vol_window': np.nan,
            'factor_return_z': np.nan,
            'factor_return_rank': np.nan,
            'long_leg_return': long_leg,
            'short_leg_return': short_leg,
            'long_only_top_bucket_excess_return': long_only_active,
            'turnover': np.nan,
            'coverage_count': int(len(work)),
            'effective_name_count': int(work['ts_code'].nunique()),
            'regression_weight_policy': 'equal_weight_cross_section',
            'neutralization_policy': 'none_p0_raw_factor_z',
        }
        for return_type, value, construction in [
            ('xsec_regression_premium', premium, 'daily equal-weight univariate OLS next_return ~ factor_value_z'),
            ('factor_mimicking_portfolio', long_short, 'top_decile_minus_bottom_decile equal-weight diagnostic portfolio'),
            ('long_only_active_return', long_only_active, 'top_decile equal-weight return minus full available universe equal-weight return'),
        ]:
            row = dict(base)
            row.update({
                'return_type': return_type,
                'factor_return': value,
                'factor_return_gross': value,
                'factor_return_net': value,
                'construction_policy': construction,
            })
            rows.append(row)
    panel = pd.DataFrame(rows, columns=RETURN_COLUMNS)
    if panel.empty:
        return panel
    for (factor_id, factor_version, return_type), idx in panel.groupby(['factor_id', 'factor_version', 'return_type'], observed=True).groups.items():
        values = panel.loc[idx, 'factor_return']
        rolling_mean = values.rolling(20, min_periods=5).mean()
        rolling_std = values.rolling(20, min_periods=5).std(ddof=1)
        panel.loc[idx, 'factor_return_vol_window'] = rolling_std
        panel.loc[idx, 'factor_return_tstat_window'] = [
            safe_tstat(values.iloc[max(0, pos - 19):pos + 1])
            for pos in range(len(values))
        ]
        panel.loc[idx, 'factor_return_z'] = (values - rolling_mean) / rolling_std.replace(0, np.nan)
        panel.loc[idx, 'factor_return_rank'] = values.rank(method='average', pct=True)
    return panel.sort_values(['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe']).reset_index(drop=True)


def write_partitioned(frame: pd.DataFrame, output_root: Path, partition_col: str = 'trade_date') -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for value, group in frame.groupby(partition_col, sort=True, observed=True):
        part_dir = output_root / f'{partition_col}={value}'
        if part_dir.exists():
            for old in part_dir.glob('*.parquet'):
                old.unlink()
        part_dir.mkdir(parents=True, exist_ok=True)
        group.drop(columns=[partition_col]).to_parquet(part_dir / 'part-000.parquet', index=False)


def write_outputs(registry: pd.DataFrame, exposure: pd.DataFrame, returns: pd.DataFrame, run_root: Path) -> dict[str, Path]:
    paths = {
        'registry': run_root / 'registry' / 'factor_library_registry.parquet',
        'exposure': run_root / 'exposure_panel',
        'returns': run_root / 'factor_return_panel',
    }
    paths['registry'].parent.mkdir(parents=True, exist_ok=True)
    registry.to_parquet(paths['registry'], index=False)
    write_partitioned(exposure, paths['exposure'])
    write_partitioned(returns, paths['returns'])
    return paths


def dataset_for_path(path: Path):
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    return ds.dataset(str(path), format='parquet', partitioning=partitioning)


def dataset_for_s3(uri: str, region: str):
    stripped = uri.removeprefix('s3://').rstrip('/')
    bucket, _, key = stripped.partition('/')
    filesystem = fs.S3FileSystem(region=region)
    partitioning = ds.partitioning(pa.schema([('trade_date', pa.large_string())]), flavor='hive')
    return ds.dataset(f'{bucket}/{key}', filesystem=filesystem, format='parquet', partitioning=partitioning)


def read_clean_oos_slice(uri: str, region: str, start: str, end: str) -> pd.DataFrame:
    dataset = dataset_for_s3(uri, region)
    table = dataset.to_table(
        columns=['trade_date', 'ts_code', 'close'],
        filter=(ds.field('trade_date') >= str(start)) & (ds.field('trade_date') <= str(end)),
    )
    frame = table.to_pandas()
    frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
    return frame[['trade_date', 'ts_code', 'close']]


def sync_clean_oos_slice(raw_root: Path, uri: str) -> Path:
    target = raw_root / 'clean_daily_bar_oos_slice'
    marker = target / '.sync_complete'
    if not marker.exists():
        target.mkdir(parents=True, exist_ok=True)
        run(['aws', 's3', 'sync', uri.rstrip('/'), str(target), '--only-show-errors'])
        marker.write_text(utc_now() + '\n', encoding='utf-8')
    return target


def read_clean_oos_slice_local(root: Path, start: str, end: str) -> pd.DataFrame:
    dataset = dataset_for_path(root)
    table = dataset.to_table(
        columns=['trade_date', 'ts_code', 'close'],
        filter=(ds.field('trade_date') >= str(start)) & (ds.field('trade_date') <= str(end)),
    )
    frame = table.to_pandas()
    frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
    return frame[['trade_date', 'ts_code', 'close']]


def read_smoke_partitioned(dataset, dates: list[str], key_cols: list[str], columns: list[str]) -> dict[str, Any]:
    samples = []
    for date in dates:
        started = time.perf_counter()
        frame = dataset.to_table(columns=columns, filter=ds.field('trade_date') == str(date)).to_pandas()
        if 'trade_date' in frame:
            frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        duplicate_key_count = int(frame.duplicated(key_cols).sum()) if not frame.empty else 0
        samples.append({
            'trade_date': date,
            'status': 'PASS' if len(frame) > 0 and duplicate_key_count == 0 else 'FAIL',
            'row_count': int(len(frame)),
            'factor_count': int(frame['factor_id'].nunique()) if 'factor_id' in frame else 0,
            'duplicate_key_count': duplicate_key_count,
            'elapsed_seconds': time.perf_counter() - started,
        })
    return {'status': 'PASS' if all(s['status'] == 'PASS' for s in samples) else 'FAIL', 'samples': samples}


def proof_common(frame: pd.DataFrame, expected_dates: list[str], key_cols: list[str], required_cols: list[str]) -> dict[str, Any]:
    dates = sorted(frame['trade_date'].astype(str).unique().tolist()) if 'trade_date' in frame and not frame.empty else []
    return {
        'min_date': min(dates) if dates else None,
        'max_date': max(dates) if dates else None,
        'date_count': len(dates),
        'row_count': int(len(frame)),
        'duplicate_key_count': int(frame.duplicated(key_cols).sum()) if not frame.empty else 0,
        'missing_dates': sorted(set(expected_dates) - set(dates)),
        'missing_required_columns': sorted(set(required_cols) - set(frame.columns)),
    }


def build_catalog(dataset_id: str, uri: str, columns: list[str], partitioned: bool, key_cols: list[str], proof_s3: str) -> dict[str, Any]:
    payload = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            dataset_id: {
                'uri': uri.rstrip('/'),
                'format': 'parquet',
                'version': 'v1',
                'storage': 's3',
                'description': f'{dataset_id} generated for Factor Library exposure/return infrastructure.',
                'columns': columns,
                'partition_columns': ['trade_date'] if partitioned else [],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code' if 'ts_code' in columns else 'factor_id',
                'metadata': {
                    'unique_key': key_cols,
                    'sort_keys': key_cols,
                    'qa_summary_path': proof_s3,
                    'schema_version': SCHEMA_VERSION,
                    'contains_alpha_conclusion': False,
                },
            },
        },
    }
    return payload


def build_proofs(
    registry: pd.DataFrame,
    exposure: pd.DataFrame,
    returns: pd.DataFrame,
    factors: list[FactorSource],
    expected_dates: list[str],
    local_exposure_smoke: dict[str, Any],
    local_return_smoke: dict[str, Any],
    s3_exposure_smoke: dict[str, Any] | None,
    s3_return_smoke: dict[str, Any] | None,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    included = [f for f in factors if f.include]
    excluded = [f for f in factors if not f.include]
    factor_payload = {
        'source_factor_list': [
            {
                'factor_id': f.factor_id,
                'factor_version': f.factor_version,
                'library_status': f.library_status,
                'admission_status': f.admission_status,
                'record_path': str(f.record_path),
                'factor_values_path': str(f.factor_values_path) if f.factor_values_path else None,
                'coverage_min_date': f.coverage_min_date,
                'coverage_max_date': f.coverage_max_date,
                'coverage_date_count': f.coverage_date_count,
                'included': f.include,
                'exclude_reason': f.exclude_reason,
            }
            for f in factors
        ],
        'included_factor_count': len(included),
        'excluded_factor_count': len(excluded),
        'included_factor_versions': [f.factor_version for f in included],
        'excluded_factor_versions': [
            {'factor_version': f.factor_version, 'reason': f.exclude_reason, 'missing_date_count': len(f.coverage_missing_dates)}
            for f in excluded
        ],
    }
    registry_checks = {
        'row_count_positive': len(registry) > 0,
        'duplicate_key_count_zero': int(registry.duplicated(['factor_id', 'factor_version']).sum()) == 0,
        'required_columns_present': not (set(REGISTRY_COLUMNS) - set(registry.columns)),
    }
    registry_proof = {
        'status': 'ACCEPT' if all(registry_checks.values()) else 'BLOCK',
        'dataset_id': REGISTRY_DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'row_count': int(len(registry)),
        'duplicate_key_count': int(registry.duplicated(['factor_id', 'factor_version']).sum()) if not registry.empty else 0,
        'required_columns': REGISTRY_COLUMNS,
        'missing_required_columns': sorted(set(REGISTRY_COLUMNS) - set(registry.columns)),
        'factor_status_distribution': registry['library_status'].value_counts().to_dict() if 'library_status' in registry else {},
        'factor_direction_distribution': registry['direction'].value_counts().to_dict() if 'direction' in registry else {},
        'contains_alpha_conclusion': False,
        'contains_cpv': False,
        'hard_checks': registry_checks,
        'generated_at_utc': utc_now(),
        **factor_payload,
    }
    exposure_common = proof_common(
        exposure,
        expected_dates,
        ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope'],
        EXPOSURE_COLUMNS,
    )
    exposure_checks = {
        'row_count_positive': len(exposure) > 0,
        'duplicate_key_count_zero': exposure_common['duplicate_key_count'] == 0,
        'missing_dates_empty': not exposure_common['missing_dates'],
        'required_columns_present': not exposure_common['missing_required_columns'],
        'contains_future_return_label_in_exposure_panel_false': True,
        'local_read_smoke_pass': local_exposure_smoke['status'] == 'PASS',
        's3_read_smoke_pass': (s3_exposure_smoke or {}).get('status') == 'PASS',
    }
    exposure_proof = {
        'status': 'ACCEPT' if all(exposure_checks.values()) else 'BLOCK',
        'dataset_id': EXPOSURE_DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'standardization_scope_coverage': exposure['standardization_scope'].value_counts().to_dict() if 'standardization_scope' in exposure else {},
        'universe_policy_coverage': exposure['universe_policy'].value_counts().to_dict() if 'universe_policy' in exposure else {},
        'factor_status_distribution': registry[registry['factor_version'].isin(exposure['factor_version'].unique())]['library_status'].value_counts().to_dict() if not exposure.empty else {},
        'factor_direction_distribution': exposure['factor_direction'].value_counts().to_dict() if 'factor_direction' in exposure else {},
        'contains_alpha_conclusion': False,
        'contains_cpv': False,
        'contains_future_return_label_in_exposure_panel': False,
        'local_read_smoke': local_exposure_smoke,
        's3_read_smoke': s3_exposure_smoke,
        'hard_checks': exposure_checks,
        'generated_at_utc': utc_now(),
        **exposure_common,
        **factor_payload,
    }
    return_common = proof_common(
        returns,
        expected_dates,
        ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe'],
        RETURN_COLUMNS,
    )
    return_checks = {
        'row_count_positive': len(returns) > 0,
        'duplicate_key_count_zero': return_common['duplicate_key_count'] == 0,
        'missing_dates_empty': not return_common['missing_dates'],
        'required_columns_present': not return_common['missing_required_columns'],
        'local_read_smoke_pass': local_return_smoke['status'] == 'PASS',
        's3_read_smoke_pass': (s3_return_smoke or {}).get('status') == 'PASS',
    }
    return_proof = {
        'status': 'ACCEPT' if all(return_checks.values()) else 'BLOCK',
        'dataset_id': RETURN_DATASET_ID,
        'schema_version': SCHEMA_VERSION,
        'return_type_coverage': returns['return_type'].value_counts().to_dict() if 'return_type' in returns else {},
        'horizon_coverage': returns['horizon'].value_counts().to_dict() if 'horizon' in returns else {},
        'universe_coverage': returns['universe'].value_counts().to_dict() if 'universe' in returns else {},
        'factor_status_distribution': registry[registry['factor_version'].isin(returns['factor_version'].unique())]['library_status'].value_counts().to_dict() if not returns.empty else {},
        'factor_direction_distribution': registry[registry['factor_version'].isin(returns['factor_version'].unique())]['direction'].value_counts().to_dict() if not returns.empty else {},
        'contains_alpha_conclusion': False,
        'contains_cpv': False,
        'source_return_field': 'tushare_daily_close_forward_1d_return',
        'label_maturity_policy': 'requires next trading day close; verified for every delivered trade_date',
        'local_read_smoke': local_return_smoke,
        's3_read_smoke': s3_return_smoke,
        'hard_checks': return_checks,
        'generated_at_utc': utc_now(),
        **return_common,
        **factor_payload,
    }
    return registry_proof, exposure_proof, return_proof


def upload_outputs(paths: dict[str, Path], args: argparse.Namespace) -> None:
    run(['aws', 's3', 'cp', str(paths['registry']), args.output_registry_s3.rstrip('/') + '/factor_library_registry.parquet', '--only-show-errors'])
    run(['aws', 's3', 'cp', args.output_registry_s3.rstrip('/') + '/factor_library_registry.parquet', args.research_registry_s3.rstrip('/') + '/factor_library_registry.parquet', '--only-show-errors'])
    run(['aws', 's3', 'sync', str(paths['exposure']), args.output_exposure_s3.rstrip('/'), '--only-show-errors'])
    run(['aws', 's3', 'sync', args.output_exposure_s3.rstrip('/'), args.research_exposure_s3.rstrip('/'), '--only-show-errors'])
    run(['aws', 's3', 'sync', str(paths['returns']), args.output_return_s3.rstrip('/'), '--only-show-errors'])
    run(['aws', 's3', 'sync', args.output_return_s3.rstrip('/'), args.research_return_s3.rstrip('/'), '--only-show-errors'])


def main() -> int:
    args = parse_args()
    run_root = Path(args.run_root).expanduser()
    raw_root = run_root / 'raw'
    run_root.mkdir(parents=True, exist_ok=True)
    trade_calendar = load_trade_calendar(raw_root, args.source_prefix)
    expected_dates = expected_open_dates(trade_calendar, args.start, args.end)
    factors = discover_factors(Path(args.factor_research_root).expanduser(), expected_dates)
    registry = build_registry(factors)
    exposure = build_exposure(factors, args.start, args.end)
    source_label_dates = label_source_dates(trade_calendar, expected_dates, args.horizon)
    clean_slice_root = sync_clean_oos_slice(raw_root, args.clean_oos_slice_s3)
    clean_daily = read_clean_oos_slice_local(clean_slice_root, args.start, args.end)
    incremental_dates = [date for date in source_label_dates if date > args.end]
    if incremental_dates:
        daily_incremental_root = sync_daily_incremental(raw_root, args.source_prefix, incremental_dates)
        incremental_daily = read_daily_incremental(daily_incremental_root, incremental_dates)
        daily = pd.concat([clean_daily, incremental_daily], ignore_index=True, sort=False)
    else:
        daily = clean_daily
    labels = read_return_labels_from_daily(daily, expected_dates, args.horizon)
    returns = build_return_panel(exposure, labels, args.horizon)
    paths = write_outputs(registry, exposure, returns, run_root / 'datamart')

    local_exposure_smoke = read_smoke_partitioned(
        dataset_for_path(paths['exposure']),
        READ_SMOKE_DATES,
        ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope'],
        ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope', 'factor_value_z'],
    )
    local_return_smoke = read_smoke_partitioned(
        dataset_for_path(paths['returns']),
        READ_SMOKE_DATES,
        ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe'],
        ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe', 'factor_return'],
    )
    if not args.skip_upload:
        upload_outputs(paths, args)
        s3_exposure_smoke = read_smoke_partitioned(
            dataset_for_s3(args.output_exposure_s3, args.s3_region),
            READ_SMOKE_DATES,
            ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope'],
            ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope', 'factor_value_z'],
        )
        s3_return_smoke = read_smoke_partitioned(
            dataset_for_s3(args.output_return_s3, args.s3_region),
            READ_SMOKE_DATES,
            ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe'],
            ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe', 'factor_return'],
        )
    else:
        s3_exposure_smoke = None
        s3_return_smoke = None

    registry_proof, exposure_proof, return_proof = build_proofs(
        registry,
        exposure,
        returns,
        factors,
        expected_dates,
        local_exposure_smoke,
        local_return_smoke,
        s3_exposure_smoke,
        s3_return_smoke,
        args,
    )
    proof_paths = {
        'registry': run_root / 'proof_registry.json',
        'exposure': run_root / 'proof_exposure_panel.json',
        'returns': run_root / 'proof_factor_return_panel.json',
    }
    proof_paths['registry'].write_text(json.dumps(registry_proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    proof_paths['exposure'].write_text(json.dumps(exposure_proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    proof_paths['returns'].write_text(json.dumps(return_proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    catalogs = {
        'registry': build_catalog(REGISTRY_DATASET_ID, args.output_registry_s3.rstrip('/') + '/factor_library_registry.parquet', REGISTRY_COLUMNS, False, ['factor_id', 'factor_version'], args.registry_proof_s3),
        'exposure': build_catalog(EXPOSURE_DATASET_ID, args.output_exposure_s3, EXPOSURE_COLUMNS, True, ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope'], args.exposure_proof_s3),
        'returns': build_catalog(RETURN_DATASET_ID, args.output_return_s3, RETURN_COLUMNS, True, ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe'], args.return_proof_s3),
    }
    catalog_paths = {
        'registry': run_root / 'catalog_registry.json',
        'exposure': run_root / 'catalog_exposure_panel.json',
        'returns': run_root / 'catalog_factor_return_panel.json',
    }
    for key, payload in catalogs.items():
        catalog_paths[key].write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not args.skip_upload:
        run(['aws', 's3', 'cp', str(proof_paths['registry']), args.registry_proof_s3, '--only-show-errors'])
        run(['aws', 's3', 'cp', str(proof_paths['exposure']), args.exposure_proof_s3, '--only-show-errors'])
        run(['aws', 's3', 'cp', str(proof_paths['returns']), args.return_proof_s3, '--only-show-errors'])
        run(['aws', 's3', 'cp', str(catalog_paths['registry']), args.registry_catalog_s3, '--only-show-errors'])
        run(['aws', 's3', 'cp', str(catalog_paths['exposure']), args.exposure_catalog_s3, '--only-show-errors'])
        run(['aws', 's3', 'cp', str(catalog_paths['returns']), args.return_catalog_s3, '--only-show-errors'])
    summary = {
        'registry_status': registry_proof['status'],
        'exposure_status': exposure_proof['status'],
        'return_status': return_proof['status'],
        'included_factor_versions': exposure_proof['included_factor_versions'],
        'excluded_factor_versions': exposure_proof['excluded_factor_versions'],
        'exposure_rows': exposure_proof['row_count'],
        'return_rows': return_proof['row_count'],
        'registry_rows': registry_proof['row_count'],
        'proof_paths': {k: str(v) for k, v in proof_paths.items()},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(p['status'] == 'ACCEPT' for p in [registry_proof, exposure_proof, return_proof]) else 2


if __name__ == '__main__':
    raise SystemExit(main())
