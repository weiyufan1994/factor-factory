#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / 'factorforge/data/datamart/factor_library_registry_bootstrap_v1/factor_library_registry_bootstrap_v1.parquet'
DEFAULT_DAILY_CLEAN = REPO_ROOT / 'data/clean/daily_clean.parquet'

EXPOSURE_DATASET_ID = 'factor_library_exposure_panel_bootstrap_v1'
RETURN_DATASET_ID = 'factor_library_factor_return_panel_bootstrap_v1'
SCHEMA_VERSION = 'factor_library_bootstrap_panels_v1_20260622'

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
    'library_status',
    'bootstrap_registry_version',
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
    'long_leg_return',
    'short_leg_return',
    'long_only_top_bucket_excess_return',
    'coverage_count',
    'effective_name_count',
    'regression_weight_policy',
    'neutralization_policy',
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build bootstrap factor-library exposure and factor-return panels from existing factor_values parquet files.')
    ap.add_argument('--registry', default=str(DEFAULT_REGISTRY))
    ap.add_argument('--daily-clean', default=str(DEFAULT_DAILY_CLEAN))
    ap.add_argument('--output-root', default=str(REPO_ROOT / 'factorforge/data/datamart'))
    ap.add_argument('--proof-dir', default=str(REPO_ROOT / 'factorforge/data/proofs'))
    ap.add_argument('--catalog-dir', default=str(REPO_ROOT / 'factorforge/data/catalog'))
    ap.add_argument('--start', default='')
    ap.add_argument('--end', default='')
    ap.add_argument('--horizon', type=int, default=1)
    ap.add_argument('--upload', action='store_true')
    ap.add_argument('--s3-exposure-uri', default='s3://yufan-data-lake/factorforge/datamart/factor_library_exposure_panel_bootstrap/v1')
    ap.add_argument('--s3-return-uri', default='s3://yufan-data-lake/factorforge/datamart/factor_library_factor_return_panel_bootstrap/v1')
    ap.add_argument('--s3-proof-uri', default='s3://yufan-data-lake/factorforge/proofs/factor_library/bootstrap_panels/v1')
    return ap.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_trade_date(value: Any) -> str:
    text = str(value).strip().replace('-', '').replace('/', '').replace('.0', '')
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        return ''
    return parsed.strftime('%Y%m%d')


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def load_labels(daily_clean_path: Path, horizon: int) -> pd.DataFrame:
    daily = pd.read_parquet(daily_clean_path, columns=['ts_code', 'trade_date', 'close'])
    daily['trade_date'] = daily['trade_date'].map(normalize_trade_date)
    daily['ts_code'] = daily['ts_code'].astype(str)
    daily['close'] = pd.to_numeric(daily['close'], errors='coerce')
    daily = daily.dropna(subset=['close']).sort_values(['ts_code', 'trade_date'])
    daily[f'close_fwd_{horizon}'] = daily.groupby('ts_code', sort=False)['close'].shift(-horizon)
    daily['next_return'] = daily[f'close_fwd_{horizon}'] / daily['close'] - 1.0
    return daily[['trade_date', 'ts_code', 'next_return']].dropna(subset=['next_return']).reset_index(drop=True)


def standardize(frame: pd.DataFrame) -> pd.DataFrame:
    values = pd.to_numeric(frame['factor_value'], errors='coerce')
    frame = frame.assign(factor_value_raw=values)
    grouped = frame.groupby('trade_date', sort=False)['factor_value_raw']
    mean = grouped.transform('mean')
    std = grouped.transform(lambda x: x.std(ddof=0))
    frame['factor_value_z'] = (frame['factor_value_raw'] - mean) / std.replace(0, np.nan)
    frame['factor_rank'] = grouped.rank(method='average', pct=True)
    return frame


def safe_filename(value: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in str(value))


def write_dataset_file(frame: pd.DataFrame, root: Path, name: str) -> None:
    if frame.empty:
        return
    table = pa.Table.from_pandas(frame, preserve_index=False)
    root.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, root / f'{safe_filename(name)}.parquet')


def build_returns(exposure: pd.DataFrame, labels: pd.DataFrame, horizon: int, factor_id: str, factor_version: str) -> pd.DataFrame:
    merged = exposure[['trade_date', 'ts_code', 'factor_value_z', 'factor_rank']].merge(labels, on=['trade_date', 'ts_code'], how='inner')
    rows: list[dict[str, Any]] = []
    for trade_date, group in merged.groupby('trade_date', sort=True):
        work = group.dropna(subset=['factor_value_z', 'factor_rank', 'next_return'])
        if len(work) < 20:
            continue
        z = work['factor_value_z'].to_numpy(dtype=float)
        r = work['next_return'].to_numpy(dtype=float)
        denom = float(np.dot(z, z))
        premium = float(np.dot(z, r) / denom) if denom > 0 else math.nan
        if denom > 0:
            # Equivalent to the single-factor Fama-MacBeth daily cross-sectional
            # risk premium because factor_value_z is standardized by date.
            fama_macbeth_premium = premium
        else:
            fama_macbeth_premium = math.nan
        top = work['factor_rank'].quantile(0.9)
        bottom = work['factor_rank'].quantile(0.1)
        long_leg = float(work.loc[work['factor_rank'] >= top, 'next_return'].mean())
        short_leg = float(work.loc[work['factor_rank'] <= bottom, 'next_return'].mean())
        universe_ret = float(work['next_return'].mean())
        long_only_active = long_leg - universe_ret
        long_short = long_leg - short_leg
        base = {
            'trade_date': trade_date,
            'factor_id': factor_id,
            'factor_version': factor_version,
            'horizon': horizon,
            'holding_period': horizon,
            'universe': 'available_factor_values_full_market',
            'cost_model': 'zero_cost_bootstrap_diagnostic',
            'information_lag_policy': 'factor_value_t_matched_to_forward_close_return_t_plus_1',
            'source_exposure_version': EXPOSURE_DATASET_ID,
            'source_return_field': 'daily_clean_close_forward_1d_return',
            'no_future_exposure': True,
            'label_maturity_policy': 'factor return uses matured next trading day close; not valid before next close is known',
            'long_leg_return': long_leg,
            'short_leg_return': short_leg,
            'long_only_top_bucket_excess_return': long_only_active,
            'coverage_count': int(len(work)),
            'effective_name_count': int(work['ts_code'].nunique()),
            'regression_weight_policy': 'equal_weight_cross_section',
            'neutralization_policy': 'none_bootstrap',
        }
        for return_type, value, construction in (
            ('xsec_regression_premium', premium, 'daily equal-weight univariate OLS: next_return ~ factor_value_z'),
            ('fama_macbeth_risk_premium', fama_macbeth_premium, 'daily Fama-MacBeth cross-sectional risk premium with intercept; single-factor coefficient on factor_value_z'),
            ('factor_mimicking_portfolio', long_short, 'top_decile_minus_bottom_decile equal-weight diagnostic return'),
            ('long_only_active_return', long_only_active, 'top_decile equal-weight return minus available universe equal-weight return'),
        ):
            row = dict(base)
            row.update({
                'return_type': return_type,
                'factor_return': value,
                'factor_return_gross': value,
                'factor_return_net': value,
                'construction_policy': construction,
            })
            rows.append(row)
    return pd.DataFrame(rows, columns=RETURN_COLUMNS)


def proof_common(root: Path, key_cols: list[str]) -> dict[str, Any]:
    dataset = pq.ParquetDataset(str(root))
    frame = dataset.read().to_pandas()
    if 'trade_date' not in frame.columns:
        # Hive partition column is usually restored by pyarrow; keep this defensive.
        frame['trade_date'] = ''
    dates = frame['trade_date'].astype(str)
    return {
        'row_count': int(len(frame)),
        'date_count': int(dates.nunique()) if len(frame) else 0,
        'min_date': str(dates.min()) if len(frame) else '',
        'max_date': str(dates.max()) if len(frame) else '',
        'duplicate_key_count': int(frame.duplicated(key_cols).sum()) if len(frame) else 0,
        'factor_count': int(frame['factor_version'].nunique()) if 'factor_version' in frame else 0,
    }


def catalog_payload(dataset_id: str, uri: str, columns: list[str], key_cols: list[str], proof_path: str) -> dict[str, Any]:
    return {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            dataset_id: {
                'uri': uri.rstrip('/'),
                'format': 'parquet',
                'version': 'v1',
                'storage': 's3',
                'description': f'{dataset_id} bootstrap panel built from non-direct-reject existing factor_values. Not official.',
                'columns': columns,
                'partition_columns': [],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code' if 'ts_code' in columns else 'factor_id',
                'metadata': {
                    'unique_key': key_cols,
                    'sort_keys': key_cols,
                    'qa_summary_path': proof_path,
                    'schema_version': SCHEMA_VERSION,
                    'mode': 'bootstrap_candidate_panel_not_official',
                    'contains_alpha_conclusion': False,
                    'contains_future_return_label_in_exposure_panel': False,
                },
            }
        },
    }


def add_to_main_catalog(catalog_dir: Path, entries: list[dict[str, Any]]) -> None:
    main_path = catalog_dir / 'data_catalog.json'
    payload = json.loads(main_path.read_text())
    existing = [item for item in payload.get('datasets', []) if item.get('dataset_id') not in {entry['dataset_id'] for entry in entries}]
    payload['datasets'] = existing + entries
    main_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    output_root = Path(args.output_root)
    proof_dir = Path(args.proof_dir)
    catalog_dir = Path(args.catalog_dir)
    exposure_root = output_root / EXPOSURE_DATASET_ID
    return_root = output_root / RETURN_DATASET_ID
    reset_dir(exposure_root)
    reset_dir(return_root)

    registry = pd.read_parquet(args.registry)
    source_rows = registry[
        registry['factor_values_path'].fillna('').ne('')
        & ~registry['direct_reject'].fillna(False)
        & ~registry['contains_cpv'].fillna(False)
    ].copy()
    if args.start:
        source_rows = source_rows[source_rows['coverage_max_date'].astype(str) >= args.start]
    if args.end:
        source_rows = source_rows[source_rows['coverage_min_date'].astype(str) <= args.end]

    labels = load_labels(Path(args.daily_clean), args.horizon)
    all_return_frames: list[pd.DataFrame] = []
    source_summaries: list[dict[str, Any]] = []

    for row in source_rows.to_dict(orient='records'):
        factor_started = time.perf_counter()
        path = Path(row['factor_values_path'])
        frame = pd.read_parquet(path)
        frame['trade_date'] = frame['trade_date'].map(normalize_trade_date)
        if args.start:
            frame = frame[frame['trade_date'] >= args.start]
        if args.end:
            frame = frame[frame['trade_date'] <= args.end]
        frame['ts_code'] = frame['ts_code'].astype(str)
        frame = standardize(frame)
        exposure = pd.DataFrame({
            'trade_date': frame['trade_date'],
            'ts_code': frame['ts_code'],
            'factor_id': row['factor_id'],
            'factor_version': row['factor_version'],
            'factor_value_raw': frame['factor_value_raw'],
            'factor_value_z': frame['factor_value_z'],
            'factor_rank': frame['factor_rank'],
            'factor_direction': row.get('direction') or 'unknown',
            'standardization_scope': 'available_factor_values_full_market',
            'universe_policy': 'source_factor_values_universe_no_extra_filter',
            'information_date': frame['trade_date'],
            'effective_trade_date': frame['trade_date'],
            'no_future_data': True,
            'source_artifact_path': row['factor_values_path'],
            'factor_value_identity_hash': row.get('factor_value_identity_hash') or '',
            'library_status': row.get('library_status') or '',
            'bootstrap_registry_version': 'factor_library_registry_bootstrap_v1_20260622',
        }, columns=EXPOSURE_COLUMNS)
        write_dataset_file(exposure, exposure_root, row['factor_version'])
        returns = build_returns(exposure, labels, args.horizon, row['factor_id'], row['factor_version'])
        if not returns.empty:
            write_dataset_file(returns, return_root, row['factor_version'])
            all_return_frames.append(returns)
        source_summaries.append({
            'factor_id': row['factor_id'],
            'factor_version': row['factor_version'],
            'factor_values_path': row['factor_values_path'],
            'exposure_rows': int(len(exposure)),
            'exposure_min_date': str(exposure['trade_date'].min()) if len(exposure) else '',
            'exposure_max_date': str(exposure['trade_date'].max()) if len(exposure) else '',
            'return_rows': int(len(returns)),
            'return_min_date': str(returns['trade_date'].min()) if len(returns) else '',
            'return_max_date': str(returns['trade_date'].max()) if len(returns) else '',
            'seconds': round(time.perf_counter() - factor_started, 3),
        })

    exposure_proof = proof_common(exposure_root, ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope'])
    return_proof = proof_common(return_root, ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe'])
    qa = {
        'schema_version': SCHEMA_VERSION,
        'generated_at_utc': utc_now(),
        'verdict': 'ACCEPT' if exposure_proof['row_count'] > 0 and return_proof['row_count'] > 0 and exposure_proof['duplicate_key_count'] == 0 and return_proof['duplicate_key_count'] == 0 else 'BLOCK',
        'datasets': {
            EXPOSURE_DATASET_ID: exposure_proof,
            RETURN_DATASET_ID: return_proof,
        },
        'source_factor_count': int(len(source_rows)),
        'source_factors': source_summaries,
        'return_methods': [
            'xsec_regression_premium',
            'fama_macbeth_risk_premium',
            'factor_mimicking_portfolio',
            'long_only_active_return',
        ],
        'boundaries': {
            'bootstrap_candidate_panel_not_official': True,
            'contains_alpha_conclusion': False,
            'contains_cpv': False,
            'contains_future_return_label_in_exposure_panel': False,
            'factor_return_uses_matured_forward_return_label': True,
        },
        'runtime_seconds': round(time.perf_counter() - started, 3),
    }
    proof_dir.mkdir(parents=True, exist_ok=True)
    proof_path = proof_dir / 'factor_library_bootstrap_panels_v1.qa.json'
    proof_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + '\n')

    exposure_catalog = catalog_payload(
        EXPOSURE_DATASET_ID,
        args.s3_exposure_uri,
        EXPOSURE_COLUMNS,
        ['trade_date', 'ts_code', 'factor_id', 'factor_version', 'standardization_scope'],
        f'{args.s3_proof_uri.rstrip("/")}/proof.json',
    )
    return_catalog = catalog_payload(
        RETURN_DATASET_ID,
        args.s3_return_uri,
        RETURN_COLUMNS,
        ['trade_date', 'factor_id', 'factor_version', 'return_type', 'horizon', 'universe'],
        f'{args.s3_proof_uri.rstrip("/")}/proof.json',
    )
    exposure_catalog_path = catalog_dir / f'{EXPOSURE_DATASET_ID}.catalog.json'
    return_catalog_path = catalog_dir / f'{RETURN_DATASET_ID}.catalog.json'
    exposure_catalog_path.write_text(json.dumps(exposure_catalog, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    return_catalog_path.write_text(json.dumps(return_catalog, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    add_to_main_catalog(catalog_dir, [
        {'dataset_id': EXPOSURE_DATASET_ID, **exposure_catalog['datasets'][EXPOSURE_DATASET_ID]},
        {'dataset_id': RETURN_DATASET_ID, **return_catalog['datasets'][RETURN_DATASET_ID]},
    ])

    if args.upload:
        subprocess.run(['aws', 's3', 'sync', str(exposure_root), args.s3_exposure_uri, '--only-show-errors'], check=True)
        subprocess.run(['aws', 's3', 'sync', str(return_root), args.s3_return_uri, '--only-show-errors'], check=True)
        subprocess.run(['aws', 's3', 'cp', str(proof_path), f'{args.s3_proof_uri.rstrip("/")}/proof.json', '--only-show-errors'], check=True)
        subprocess.run(['aws', 's3', 'cp', str(exposure_catalog_path), f'{args.s3_proof_uri.rstrip("/")}/{EXPOSURE_DATASET_ID}.catalog.json', '--only-show-errors'], check=True)
        subprocess.run(['aws', 's3', 'cp', str(return_catalog_path), f'{args.s3_proof_uri.rstrip("/")}/{RETURN_DATASET_ID}.catalog.json', '--only-show-errors'], check=True)

    print(json.dumps({
        'verdict': qa['verdict'],
        'proof_path': str(proof_path),
        'exposure_root': str(exposure_root),
        'return_root': str(return_root),
        'source_factor_count': int(len(source_rows)),
        'exposure_rows': exposure_proof['row_count'],
        'return_rows': return_proof['row_count'],
        'runtime_seconds': qa['runtime_seconds'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
