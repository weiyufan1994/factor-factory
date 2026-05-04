#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

# Runtime root policy:
# - prefer FACTORFORGE_ROOT when explicitly configured
# - otherwise keep legacy EC2 compatibility
# - fallback to current repository root for local runs
# COMMENT_POLICY: runtime_path
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
LEGACY_REPO_ROOT = LEGACY_WORKSPACE / 'repos' / 'factor-factory'
REPO_ROOT = LEGACY_REPO_ROOT if LEGACY_REPO_ROOT.exists() else Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import (
    CleanDailyLayerPaths,
    build_data_requirement,
    clean_daily_layer_ready,
    load_clean_daily_layer,
    load_dataset,
    resolve_dataset,
    resolve_daily_dataset,
    resolve_clean_daily_layer_paths,
    write_data_requirement,
)
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id

FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FF.parent
OBJ = FF / 'objects'
RUNS = FF / 'runs'
REAL_CPV_BASE = WORKSPACE / 'tmp' / 'cpv_run_2016'
CLEAN_DAILY_LAYER = resolve_clean_daily_layer_paths()


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict | None, str | None]:
    """Apply the orchestrator-owned runtime manifest before any Step3 path writes."""
    global FF, WORKSPACE, OBJ, RUNS, REAL_CPV_BASE, CLEAN_DAILY_LAYER
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FF = manifest_factorforge_root(manifest)
    WORKSPACE = FF.parent
    OBJ = FF / 'objects'
    RUNS = FF / 'runs'
    REAL_CPV_BASE = WORKSPACE / 'tmp' / 'cpv_run_2016'
    os.environ['FACTORFORGE_ROOT'] = str(FF)
    clean_root = Path(manifest.get('clean_data_root') or (FF / 'data' / 'clean'))
    CLEAN_DAILY_LAYER = CleanDailyLayerPaths(
        root=clean_root,
        daily_parquet=clean_root / 'daily_clean.parquet',
        metadata_json=clean_root / 'daily_clean.meta.json',
    )
    return manifest, manifest_report_id(manifest)


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FF, WORKSPACE, OBJ, RUNS, REAL_CPV_BASE, CLEAN_DAILY_LAYER
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step3 execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FF.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    if manifest_path:
        manifest = load_runtime_manifest(manifest_path)
        if manifest_factorforge_root(manifest).expanduser().resolve() != debug_root:
            raise SystemExit('BLOCKED_DIRECT_STEP: direct debug manifest must point to FACTORFORGE_DEBUG_ROOT.')
    FF = debug_root
    WORKSPACE = FF.parent
    OBJ = FF / 'objects'
    RUNS = FF / 'runs'
    REAL_CPV_BASE = WORKSPACE / 'tmp' / 'cpv_run_2016'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


def load_json(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {p}')


def read_existing_json(p: Path) -> dict:
    if not p.exists():
        return {}
    return load_json(p)


def merge_handoff(existing: dict, updates: dict) -> dict:
    merged = dict(existing)
    merged.update({k: v for k, v in updates.items() if v is not None})

    existing_local_inputs = existing.get('local_input_paths')
    update_local_inputs = updates.get('local_input_paths')
    if isinstance(existing_local_inputs, dict) and isinstance(update_local_inputs, dict):
        merged['local_input_paths'] = {**existing_local_inputs, **update_local_inputs}

    if 'first_run_outputs' in existing and updates.get('first_run_outputs') is None:
        merged['first_run_outputs'] = existing['first_run_outputs']
    if 'evaluation_plan' in existing and updates.get('evaluation_plan') is None:
        merged['evaluation_plan'] = existing['evaluation_plan']

    merged['report_id'] = updates.get('report_id') or existing.get('report_id')
    return merged


def merge_implementation_plan(existing: dict, updates: dict) -> dict:
    if not existing:
        return updates

    merged = dict(updates)
    merged.update(existing)
    merged['report_id'] = updates.get('report_id') or existing.get('report_id')
    merged['factor_id'] = updates.get('factor_id') or existing.get('factor_id')

    existing_notes = existing.get('notes')
    update_notes = updates.get('notes')
    if isinstance(existing_notes, list) and isinstance(update_notes, list):
        merged['notes'] = update_notes + [note for note in existing_notes if note not in update_notes]

    existing_rationale = existing.get('rationale')
    update_rationale = updates.get('rationale')
    if isinstance(existing_rationale, list) and isinstance(update_rationale, list):
        merged['rationale'] = update_rationale + [note for note in existing_rationale if note not in update_rationale]

    if existing.get('implementation_mode'):
        merged['implementation_mode'] = existing['implementation_mode']
        merged['preferred_execution_mode'] = existing['implementation_mode']

    return merged


def infer_sample_window(factor_id: str, required_text: str):
    if 'CPV' in factor_id.upper() or re.search(r'minute|分钟|高频', required_text, re.I):
        return {'start': '20160104', 'end': '20160329', 'calendar': 'A-share trading days'}
    return {'start': '20100104', 'end': 'current', 'calendar': 'A-share trading days'}


def _normalize_window_date(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() == 'current':
        return 'current'
    digits = re.sub(r'[^0-9]', '', text)
    return digits if len(digits) == 8 else text


def declared_sample_window(fsm: dict, handoff: dict, fallback: dict) -> dict:
    canonical = fsm.get('canonical_spec') or {}
    candidates = [
        canonical.get('sample_window'),
        canonical.get('backtest_window'),
        fsm.get('sample_window'),
        fsm.get('backtest_window'),
        handoff.get('sample_window'),
        handoff.get('backtest_window'),
        handoff.get('step4_backtest_window'),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        start = _normalize_window_date(candidate.get('start'))
        end = _normalize_window_date(candidate.get('end'))
        if start and end:
            return {
                'start': start,
                'end': end,
                'calendar': candidate.get('calendar') or fallback.get('calendar') or 'A-share trading days',
            }
    return fallback


def synthetic_fallback_allowed(report_id: str) -> bool:
    raw = os.getenv('ALLOW_SYNTHETIC_FALLBACK')
    if raw is not None:
        return raw.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}
    return report_id.startswith('STEP') or report_id.endswith('_DEMO')


def is_cpv_like_factor(factor_id: str, canonical: dict) -> bool:
    if 'CPV' in str(factor_id).upper():
        return True

    required_inputs = [str(x).lower() for x in (canonical.get('required_inputs') or [])]
    formula_text = str(canonical.get('formula_text') or '').lower()
    cross_steps = ' '.join(str(x).lower() for x in (canonical.get('cross_sectional_steps') or []))
    has_core_fields = {'close', 'vol', 'amount'}.issubset(set(required_inputs))
    has_pv_semantics = any(token in f'{formula_text} {cross_steps}' for token in ['price-volume', '价量', 'corr', '相关'])
    return has_core_fields and has_pv_semantics


FIELD_KEYWORDS = {
    'open': ['open', '开盘'],
    'high': ['high', '最高'],
    'low': ['low', '最低'],
    'close': ['close', '收盘'],
    'volume': ['volume', 'vol', '成交量'],
    'amount': ['amount', '成交额'],
    'pct_chg': ['pct_chg', 'return', 'ret', '收益率', '涨跌幅'],
    'turnover_rate': ['turnover_rate', 'turnover', '换手'],
    'market_cap': ['market_cap', 'total_mv', 'circ_mv', '市值'],
    'pe': ['pe', '市盈率'],
    'pb': ['pb', '市净率'],
    'ps': ['ps', '市销率'],
}

MINUTE_DATASET_ID = 'minute_bar'
REQUIRED_MINUTE_FIELDS = [
    'ts_code',
    'trade_date',
    'trade_time',
    'bar_time',
    'minute_index',
    'open',
    'high',
    'low',
    'close',
    'volume',
    'amount',
]


def infer_required_daily_fields(canonical: dict, need_daily_basic: bool) -> list[str]:
    """Extract a conservative Step3A daily data contract from Step2 text."""
    text_parts: list[str] = []
    for key in ['formula_text', 'raw_formula_text']:
        if canonical.get(key):
            text_parts.append(str(canonical[key]))
    for key in ['required_inputs', 'operators', 'time_series_steps', 'cross_sectional_steps', 'preprocessing', 'normalization']:
        value = canonical.get(key)
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        elif value:
            text_parts.append(str(value))
    text = ' '.join(text_parts).lower()
    fields = ['ts_code', 'trade_date']
    for logical, keywords in FIELD_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in keywords):
            fields.append(logical)
    if need_daily_basic:
        fields.extend(['turnover_rate', 'market_cap', 'pe', 'pb', 'ps'])
    if len(fields) <= 2:
        fields.extend(['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg'])
    return list(dict.fromkeys(fields))


def api_window_value(value):
    normalized = _normalize_window_date(value)
    if normalized == 'current':
        return None
    return normalized


def data_requirement_path(report_id: str) -> Path:
    return OBJ / 'data_requirements' / f'factorforge_data_requirement__{report_id}.json'


def build_step3a_data_api_resolution(required_daily_fields: list[str], required_minute_fields: list[str]) -> dict:
    daily_resolution = resolve_daily_dataset(required_daily_fields)
    minute_resolution = resolve_dataset(MINUTE_DATASET_ID, required_minute_fields) if required_minute_fields else None
    catalog_exists = bool(daily_resolution.get('catalog_exists') or (minute_resolution or {}).get('catalog_exists'))
    catalog_path = daily_resolution.get('catalog_path') or (minute_resolution or {}).get('catalog_path')
    child_resolutions = [daily_resolution, *([minute_resolution] if minute_resolution else [])]
    missing_datasets = [
        item['dataset_id']
        for item in child_resolutions
        if item and item.get('status') == 'missing_dataset'
    ]
    missing_fields = {
        item['dataset_id']: item.get('missing_fields') or []
        for item in child_resolutions
        if item and item.get('status') == 'missing_fields'
    }
    if not catalog_exists and not data_api_strict_required():
        status = 'catalog_absent_legacy_shared_clean_fallback'
    elif missing_datasets:
        status = 'missing_dataset'
    elif missing_fields:
        status = 'missing_fields'
    else:
        status = 'ready'
    resolution = {
        'dataset_id': 'step3a_data_contract',
        'status': status,
        'catalog_path': catalog_path,
        'catalog_exists': catalog_exists,
        'required_daily_fields': required_daily_fields,
        'required_minute_fields': required_minute_fields,
        'daily_resolution': daily_resolution,
        'minute_resolution': minute_resolution,
        'resolved_fields': {
            'clean_daily_bar': daily_resolution.get('resolved_fields') or {},
            **({'minute_bar': minute_resolution.get('resolved_fields') or {}} if minute_resolution else {}),
        },
        'missing_fields': missing_fields,
        'missing_datasets': missing_datasets,
        'available_datasets': daily_resolution.get('available_datasets') or (minute_resolution or {}).get('available_datasets') or [],
    }
    if status != 'ready':
        reasons = []
        for item in child_resolutions:
            if item and item.get('error'):
                reasons.append(item['error'])
        if status == 'catalog_absent_legacy_shared_clean_fallback':
            reasons.append(f'FactorForge data catalog is absent at {catalog_path}; legacy fallback is recorded explicitly.')
        resolution['error'] = ' '.join(reasons)
    return resolution


def write_step3a_data_requirement(report_id: str, sample_window: dict, resolution: dict) -> str:
    required_datasets = [
        {
            'dataset_id': 'clean_daily_bar',
            'frequency': '1day',
            'columns': resolution.get('required_daily_fields') or [],
            'required_transform': 'clean daily bars plus daily_basic enhancements, qlib-normalized field names',
        }
    ]
    if resolution.get('required_minute_fields'):
        required_datasets.append({
            'dataset_id': MINUTE_DATASET_ID,
            'frequency': '1min',
            'columns': resolution.get('required_minute_fields') or [],
            'required_transform': 'clean minute bars with qlib-normalized intraday fields',
        })
    unresolved = list(resolution.get('missing_datasets') or [])
    unresolved.extend(key for key, value in (resolution.get('missing_fields') or {}).items() if value and key not in unresolved)
    dataset_id = unresolved[0] if len(unresolved) == 1 else 'step3a_data_contract'
    columns = []
    for item in required_datasets:
        columns.extend(item['columns'])
    requirement = build_data_requirement(
        dataset_id,
        reason=(
            'Step3A requires all factor inputs to resolve through the FactorForge Data API catalog. '
            'Do not search raw/local paths or rebuild clean data inside factor research.'
        ),
        start=api_window_value(sample_window.get('start')),
        end=api_window_value(sample_window.get('end')),
        columns=list(dict.fromkeys(columns)),
        frequency='mixed' if len(required_datasets) > 1 else required_datasets[0]['frequency'],
        required_transform='publish the missing Step3A research-ready data mart(s) and update the catalog',
    )
    requirement['required_datasets'] = required_datasets
    requirement['resolution'] = resolution
    path = write_data_requirement(requirement, data_requirement_path(report_id))
    return path.name


def data_api_requirement_result(report_id: str, sample_window: dict, resolution: dict) -> dict:
    ref = write_step3a_data_requirement(report_id, sample_window, resolution)
    return {
        'snapshot_note': f'Data API contract is not ready: {resolution.get("status")}. Requirement written to {ref}.',
        'snapshot_source': 'data_api_requirement',
        'input_mode': 'blocked',
        'data_api_resolution': resolution,
        'data_requirement_ref': ref,
        'data_requirement_refs': [ref],
    }


def materialize_data_api_contract_slice(report_id: str, sample_window: dict, resolution: dict) -> dict:
    daily_resolution = resolution['daily_resolution']
    resolved_fields = daily_resolution.get('resolved_fields') or {}
    requested_columns = list(dict.fromkeys(resolved_fields.values()))
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    daily_meta = local_dir / f'daily_input_meta__{report_id}.json'
    if daily_csv.exists() or daily_csv.is_symlink():
        daily_csv.unlink()

    daily_df = load_dataset(
        'clean_daily_bar',
        start=api_window_value(sample_window.get('start')),
        end=api_window_value(sample_window.get('end')),
        columns=requested_columns,
        catalog_path=daily_resolution.get('catalog_path'),
    )
    daily_df.to_csv(daily_csv, index=False)
    meta = {
        'source': 'factorforge_data_api',
        'dataset_id': 'clean_daily_bar',
        'catalog_path': daily_resolution.get('catalog_path'),
        'dataset': daily_resolution.get('dataset'),
        'required_fields': resolution.get('required_daily_fields') or [],
        'resolved_fields': resolved_fields,
        'slice_summary': {
            'rows': int(len(daily_df)),
            'tickers': int(daily_df['ts_code'].nunique()) if 'ts_code' in daily_df.columns and not daily_df.empty else 0,
            'trade_date_min': str(daily_df['trade_date'].min()) if 'trade_date' in daily_df.columns and not daily_df.empty else None,
            'trade_date_max': str(daily_df['trade_date'].max()) if 'trade_date' in daily_df.columns and not daily_df.empty else None,
            'columns': list(daily_df.columns),
        },
    }
    daily_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    result = {
        'daily_df_csv': str(daily_csv.relative_to(WORKSPACE)),
        'daily_input_meta': str(daily_meta.relative_to(WORKSPACE)),
        'daily_input_meta_json': str(daily_meta.relative_to(WORKSPACE)),
        'snapshot_source': 'factorforge_data_api',
        'input_mode': 'daily_only',
        'data_api_resolution': resolution,
        'daily_filter_policy': 'factorforge_data_api_catalog_slice',
    }
    minute_resolution = resolution.get('minute_resolution')
    if minute_resolution:
        minute_fields = minute_resolution.get('resolved_fields') or {}
        minute_columns = list(dict.fromkeys(minute_fields.values()))
        minute_csv = local_dir / f'minute_input__{report_id}.csv'
        minute_meta = local_dir / f'minute_input_meta__{report_id}.json'
        if minute_csv.exists() or minute_csv.is_symlink():
            minute_csv.unlink()
        minute_df = load_dataset(
            MINUTE_DATASET_ID,
            start=api_window_value(sample_window.get('start')),
            end=api_window_value(sample_window.get('end')),
            columns=minute_columns,
            catalog_path=minute_resolution.get('catalog_path'),
        )
        minute_df.to_csv(minute_csv, index=False)
        minute_payload = {
            'source': 'factorforge_data_api',
            'dataset_id': MINUTE_DATASET_ID,
            'catalog_path': minute_resolution.get('catalog_path'),
            'dataset': minute_resolution.get('dataset'),
            'required_fields': resolution.get('required_minute_fields') or [],
            'resolved_fields': minute_fields,
            'slice_summary': {
                'rows': int(len(minute_df)),
                'tickers': int(minute_df['ts_code'].nunique()) if 'ts_code' in minute_df.columns and not minute_df.empty else 0,
                'trade_date_min': str(minute_df['trade_date'].min()) if 'trade_date' in minute_df.columns and not minute_df.empty else None,
                'trade_date_max': str(minute_df['trade_date'].max()) if 'trade_date' in minute_df.columns and not minute_df.empty else None,
                'columns': list(minute_df.columns),
            },
        }
        minute_meta.write_text(json.dumps(minute_payload, ensure_ascii=False, indent=2), encoding='utf-8')
        result.update({
            'minute_df_csv': str(minute_csv.relative_to(WORKSPACE)),
            'minute_input_meta': str(minute_meta.relative_to(WORKSPACE)),
            'minute_input_meta_json': str(minute_meta.relative_to(WORKSPACE)),
            'input_mode': 'daily_and_minute',
        })
    actual_window = {
        'start': meta['slice_summary']['trade_date_min'] or sample_window.get('start'),
        'end': meta['slice_summary']['trade_date_max'] or sample_window.get('end'),
        'calendar': sample_window.get('calendar'),
    }
    result['sample_window_actual'] = actual_window
    result['snapshot_note'] = 'Step3A input sliced from FactorForge Data API catalog datasets.'
    return result


def inspect_minute_root(path: Path) -> dict | None:
    if not path.exists():
        return None

    legacy_parts = sorted(path.glob('trade_date=*/part-*.parquet'))
    if legacy_parts:
        trade_dates = sorted({p.parent.name.replace('trade_date=', '') for p in legacy_parts})
        return {
            'path': path,
            'format': 'legacy_partitioned_parquet',
            'trade_dates': trade_dates,
            'trade_date_count': len(trade_dates),
        }

    day_dirs = sorted([p for p in path.iterdir() if p.is_dir() and p.name.lower().startswith('day')])
    if day_dirs:
        return {
            'path': path,
            'format': 'per_day_csv_dirs',
            'trade_dates': [p.name for p in day_dirs],
            'trade_date_count': len(day_dirs),
        }

    return None


def candidate_minute_roots() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.getenv('FACTORFORGE_MINUTE_DIR')
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend([
        # Preferred local raw cache layout for S3-synced minute partitions.
        Path.home() / '.qlib' / 'raw_tushare' / '分钟数据' / 'raw' / 'stk_mins_1min',
        WORKSPACE / 'tmp' / 'cpv_run_2016' / 'stk_mins_1min',
        WORKSPACE / 'qlib_test' / 'qlib_1min_src',
        Path.home() / 'projects' / 'qlib_test' / 'qlib_1min_src',
    ])

    deduped: list[Path] = []
    seen = set()
    for item in candidates:
        key = str(item)
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def materialize_shared_daily_slice(report_id: str, sample_window: dict, symbols: list[str] | None = None) -> dict:
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)

    if not clean_daily_layer_ready(CLEAN_DAILY_LAYER):
        return {
            'snapshot_note': (
                f'Shared clean daily layer is missing under {CLEAN_DAILY_LAYER.root}; '
                'run scripts/build_clean_daily_layer.py before Step 3A.'
            ),
            'snapshot_source': 'missing_clean_daily_layer',
            'input_mode': 'daily_only',
        }

    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    daily_meta = local_dir / f'daily_input_meta__{report_id}.json'
    if daily_csv.exists() or daily_csv.is_symlink():
        daily_csv.unlink()

    daily_df, clean_meta = load_clean_daily_layer(
        start=sample_window.get('start'),
        end=sample_window.get('end'),
        symbols=symbols,
        layer_paths=CLEAN_DAILY_LAYER,
        return_metadata=True,
    )
    daily_df.to_csv(daily_csv, index=False)
    daily_meta.write_text(json.dumps(clean_meta, ensure_ascii=False, indent=2), encoding='utf-8')

    actual_window = {
        'start': str(daily_df['trade_date'].min()) if not daily_df.empty else sample_window.get('start'),
        'end': str(daily_df['trade_date'].max()) if not daily_df.empty else sample_window.get('end'),
        'calendar': sample_window.get('calendar'),
    }
    return {
        'daily_df_csv': str(daily_csv.relative_to(WORKSPACE)),
        'daily_input_meta': str(daily_meta.relative_to(WORKSPACE)),
        'daily_input_meta_json': str(daily_meta.relative_to(WORKSPACE)),
        'sample_window_actual': actual_window,
        'snapshot_note': f'Daily input sliced from shared clean daily layer at {CLEAN_DAILY_LAYER.daily_parquet}.',
        'snapshot_source': 'shared_clean_daily_layer',
        'input_mode': 'daily_only',
        'clean_layer_root': str(CLEAN_DAILY_LAYER.root),
        'daily_filter_policy': clean_meta.get('policy'),
        'daily_filter_summary': (
            clean_meta.get('clean_meta', {}).get('counts', {})
            | clean_meta.get('clean_meta', {}).get('drop_counts', {})
        ),
    }


def build_local_cpv_snapshots(report_id: str, sample_window: dict):
    # Step 3A output must be executable by Step 4:
    # produce local snapshot paths even when real historical data is unavailable.
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)

    minute_meta = next((meta for meta in (inspect_minute_root(p) for p in candidate_minute_roots()) if meta), None)
    real_minute_root = minute_meta['path'] if minute_meta else REAL_CPV_BASE / 'stk_mins_1min'
    if minute_meta and not clean_daily_layer_ready(CLEAN_DAILY_LAYER) and not synthetic_fallback_allowed(report_id):
        return {
            'snapshot_note': (
                f'Real local minute source found at {real_minute_root}, but the shared clean daily layer is missing under '
                f'{CLEAN_DAILY_LAYER.root}; run scripts/build_clean_daily_layer.py before Step 3A.'
            ),
            'snapshot_source': 'missing_clean_daily_layer',
        }
    # Preferred path: real local data package for realistic integration evidence.
    if clean_daily_layer_ready(CLEAN_DAILY_LAYER) and minute_meta and minute_meta.get('format') == 'legacy_partitioned_parquet':
        minute_parts = sorted(real_minute_root.glob('trade_date=*/part-*.parquet'))
        if minute_parts:
            minute_df = pd.concat([pd.read_parquet(p) for p in minute_parts], ignore_index=True)
            tickers = sorted(minute_df['ts_code'].dropna().unique().tolist())

            minute_parquet = local_dir / f'minute_input__{report_id}.parquet'
            if minute_parquet.exists() or minute_parquet.is_symlink():
                minute_parquet.unlink()
            minute_df.to_parquet(minute_parquet, index=False)
            daily_slice = materialize_shared_daily_slice(report_id, sample_window, symbols=tickers)
            sample_actual = {
                'start': str(minute_df['trade_date'].min()),
                'end': str(minute_df['trade_date'].max())
            }
            return {
                'minute_df_parquet': str(minute_parquet.relative_to(WORKSPACE)),
                **daily_slice,
                'sample_window_actual': sample_actual,
                'snapshot_note': (
                    f'Real local minute snapshot sourced from {real_minute_root}; daily leg is sliced from shared clean '
                    f'daily layer at {CLEAN_DAILY_LAYER.daily_parquet}.'
                ),
                'snapshot_source': 'shared_clean_daily_layer',
            }

    if clean_daily_layer_ready(CLEAN_DAILY_LAYER) and minute_meta and minute_meta.get('trade_date_count', 0) < 5:
        return {
            'snapshot_note': (
                f'Real local minute source found at {real_minute_root}, but only '
                f'{minute_meta.get("trade_date_count", 0)} trading day(s) are available; '
                'insufficient for CPV rolling-window reconstruction.'
            ),
            'snapshot_source': 'real_local_insufficient',
        }

    if not synthetic_fallback_allowed(report_id):
        return {
            'snapshot_note': (
                'No sufficient real local minute history discovered; synthetic fallback is disabled for non-sample reports.'
            ),
            'snapshot_source': 'missing_real_local_data',
        }

    # Fallback path: deterministic tiny synthetic dataset for reproducible CI/local smoke runs.
    trade_dates = pd.bdate_range(start='2016-01-04', end='2016-03-29')
    tickers = ['000001.SZ', '000002.SZ', '000004.SZ']

    minute_rows = []
    for date in trade_dates:
        d = date.strftime('%Y%m%d')
        for ticker_i, ticker in enumerate(tickers):
            base = 10 + ticker_i
            for minute_i in range(30):
                hh = 9 + (30 + minute_i) // 60
                mm = (30 + minute_i) % 60
                trade_time = f'{d} {hh:02d}:{mm:02d}:00'
                close = base + minute_i * 0.01 + (ticker_i * 0.02)
                vol = 1000 + minute_i * 10 + ticker_i * 20
                amount = close * vol
                minute_rows.append({
                    'ts_code': ticker,
                    'trade_date': d,
                    'trade_time': trade_time,
                    'bar_time': trade_time[-8:],
                    'minute_index': minute_i,
                    'open': close - 0.01,
                    'close': close,
                    'high': close + 0.02,
                    'low': close - 0.02,
                    'vol': vol,
                    'amount': amount,
                })
    minute_df = pd.DataFrame(minute_rows)

    daily_rows = []
    for date in trade_dates:
        d = date.strftime('%Y%m%d')
        for ticker_i, ticker in enumerate(tickers):
            close = 10 + ticker_i + date.day * 0.01
            daily_rows.append({
                'ts_code': ticker,
                'trade_date': d,
                'open': close - 0.1,
                'high': close + 0.2,
                'low': close - 0.2,
                'close': close,
                'pre_close': close - 0.05,
                'change': 0.05,
                'pct_chg': 0.5 + ticker_i * 0.1,
                'vol': 100000 + ticker_i * 1000,
                'amount': close * (100000 + ticker_i * 1000),
            })
    daily_df = pd.DataFrame(daily_rows)

    minute_csv = local_dir / f'minute_input__{report_id}.csv'
    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    minute_df.to_csv(minute_csv, index=False)
    daily_df.to_csv(daily_csv, index=False)

    sample_actual = {
        'start': str(minute_df['trade_date'].min()),
        'end': str(minute_df['trade_date'].max())
    }
    return {
        'minute_df_csv': str(minute_csv.relative_to(WORKSPACE)),
        'daily_df_csv': str(daily_csv.relative_to(WORKSPACE)),
        'sample_window_actual': sample_actual,
        'snapshot_note': 'Synthetic fallback snapshot; use only when real local data layer is unavailable.',
        'snapshot_source': 'synthetic_fallback',
    }


def data_api_strict_required() -> bool:
    return os.getenv('FACTORFORGE_REQUIRE_DATA_API', '').strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def build_local_daily_snapshot(report_id: str, sample_window: dict, required_fields: list[str] | None = None):
    # Daily-only factors prefer the cataloged Data API. Legacy clean-layer fallback is allowed only
    # when no catalog has been published yet, so existing local research does not hard fail during migration.
    fields = required_fields or ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
    resolution = build_step3a_data_api_resolution(fields, [])
    catalog_path = Path(str(resolution.get('catalog_path') or '')).expanduser()
    if resolution.get('status') == 'ready':
        return materialize_data_api_contract_slice(report_id, sample_window, resolution)
    if resolution.get('status') == 'catalog_absent_legacy_shared_clean_fallback' and not catalog_path.exists():
        legacy = materialize_shared_daily_slice(report_id, sample_window)
        legacy['data_api_resolution'] = resolution | {'fallback_policy': 'allowed_until_factorforge_data_catalog_is_published'}
        return legacy
    return data_api_requirement_result(report_id, sample_window, resolution)


def build_step3a(report_id: str):
    fsm = load_json(OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    _aim = load_json(OBJ / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json')
    handoff_to_step3 = read_existing_json(OBJ / 'handoff' / f'handoff_to_step3__{report_id}.json')

    factor_id = fsm.get('factor_id', report_id)
    canonical = fsm.get('canonical_spec', {})
    cpv_like = is_cpv_like_factor(factor_id, canonical)
    required = canonical.get('required_inputs', [])
    required_text = ' '.join(required)
    need_minute = bool(re.search(r'minute|分钟|高频', required_text, re.I)) or cpv_like
    need_daily = True
    need_daily_basic = cpv_like or bool(re.search(r'market_cap|total_mv|circ_mv|turnover|pe|pb|ps|估值|市值', required_text, re.I))
    required_daily_fields = infer_required_daily_fields(canonical, need_daily_basic)
    required_minute_fields = REQUIRED_MINUTE_FIELDS if need_minute else []
    data_api_resolution = build_step3a_data_api_resolution(required_daily_fields, required_minute_fields)

    sample_window = declared_sample_window(fsm, handoff_to_step3, infer_sample_window(factor_id, required_text))
    data_sources = []
    coverage = []
    proxy_rules = []
    blocked = []
    field_mapping = {}
    notes = []

    if need_minute:
        data_sources.append({
            'name': 'minute_bar',
            'kind': 'factorforge_data_api_catalog',
            'path': 'catalog://minute_bar',
            'fields': required_minute_fields,
            'normalized_dataset': 'minute_bar'
        })
        coverage.append({'name': 'minute_bar', 'status': 'pending', 'detail': 'resolved through FactorForge Data API catalog or explicit legacy fallback'})
        field_mapping.update({
            'instrument': 'ts_code',
            'date': 'trade_date',
            'timestamp': 'trade_time',
            'minute_bar_time': 'bar_time',
            'minute_close': 'close',
            'minute_open': 'open',
            'minute_high': 'high',
            'minute_low': 'low',
            'minute_volume': 'vol',
            'minute_amount': 'amount'
        })

    if need_daily:
        data_sources.append({
            'name': 'clean_daily_bar',
            'kind': 'factorforge_data_api_catalog',
            'path': 'catalog://clean_daily_bar',
            'fields': required_daily_fields,
            'normalized_dataset': 'clean_daily_bar'
        })
        coverage.append({'name': 'clean_daily_bar', 'status': 'pending', 'detail': 'resolved through FactorForge Data API catalog or explicit legacy fallback'})
        field_mapping.update({
            'daily_open': 'open',
            'daily_high': 'high',
            'daily_low': 'low',
            'daily_close': 'close',
            'daily_return': 'pct_chg',
            'daily_volume': 'vol',
            'daily_amount': 'amount'
        })

    if need_daily_basic:
        coverage.append({
            'name': 'clean_daily_bar_daily_basic_enhancements',
            'status': 'pending',
            'detail': 'valuation and turnover fields must resolve through clean_daily_bar; missing fields block and write a data requirement',
        })
        field_mapping.update({
            'daily_turnover_rate': 'turnover_rate',
            'daily_turnover_rate_f': 'turnover_rate_f',
            'daily_volume_ratio': 'volume_ratio',
            'daily_pe': 'pe',
            'daily_pe_ttm': 'pe_ttm',
            'daily_pb': 'pb',
            'daily_ps': 'ps',
            'daily_ps_ttm': 'ps_ttm',
            'daily_total_share': 'total_share',
            'daily_float_share': 'float_share',
            'daily_free_share': 'free_share',
            'daily_market_cap': 'total_mv',
            'daily_circulating_market_cap': 'circ_mv'
        })

    local_input_paths = {}
    if need_minute:
        # Keep only non-catalog research risks here; data availability must be resolved above.
        proxy_rules.extend([
            {
                'missing_field': 'industry_dummy',
                'proxy_field': '',
                'reason': '当前未接入申万行业字段，不做纯行业中性化',
                'risk': 'high'
            }
        ])
        if data_api_resolution.get('status') == 'ready':
            local_input_paths = materialize_data_api_contract_slice(report_id, sample_window, data_api_resolution)
        elif data_api_resolution.get('status') == 'catalog_absent_legacy_shared_clean_fallback':
            local_input_paths = build_local_cpv_snapshots(report_id, sample_window)
            local_input_paths['data_api_resolution'] = data_api_resolution | {
                'fallback_policy': 'allowed_until_factorforge_data_catalog_is_published',
            }
        else:
            local_input_paths = data_api_requirement_result(report_id, sample_window, data_api_resolution)
        notes.append('CPV/minute Step 3A inputs must resolve through clean_daily_bar and minute_bar when the Data API catalog exists.')
        notes.append('Daily_basic / valuation / market-cap fields are required on clean_daily_bar in this contract.')
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        if snapshot_source in {'factorforge_data_api', 'shared_clean_daily_layer', 'synthetic_fallback'}:
            notes.append('Step 3A 已生成 Step 4 可直接消费的本地输入快照，供集成证明与样例执行使用')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source == 'data_api_requirement':
            blocked.append({
                'code': 'FACTORFORGE_DATA_API_REQUIREMENT',
                'detail': snapshot_note,
                'data_requirement_ref': local_input_paths.get('data_requirement_ref'),
            })
        elif snapshot_source in {'real_local_insufficient', 'missing_real_local_data', 'missing_clean_daily_layer'}:
            blocked.append({
                'code': 'SHARED_CLEAN_DAILY_LAYER_MISSING' if snapshot_source == 'missing_clean_daily_layer' else 'LOCAL_MINUTE_HISTORY_INSUFFICIENT',
                'detail': snapshot_note,
            })
    else:
        local_input_paths = build_local_daily_snapshot(report_id, sample_window, required_daily_fields)
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        data_api_resolution = local_input_paths.get('data_api_resolution') or {}
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source == 'data_api_requirement':
            blocked.append({
                'code': 'FACTORFORGE_DATA_API_REQUIREMENT',
                'detail': snapshot_note,
                'data_requirement_ref': local_input_paths.get('data_requirement_ref'),
            })
        elif snapshot_source == 'missing_clean_daily_layer':
            blocked.append({
                'code': 'SHARED_CLEAN_DAILY_LAYER_MISSING',
                'detail': snapshot_note,
            })
        if data_api_resolution.get('status') == 'ready':
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'pass',
                'detail': f"Step3A data contract resolved from catalog {data_api_resolution.get('catalog_path')}",
            })
        elif data_api_resolution.get('status') == 'catalog_absent_legacy_shared_clean_fallback':
            coverage.append({
                'name': 'factorforge_data_api_catalog',
                'status': 'legacy_fallback',
                'detail': f"catalog absent at {data_api_resolution.get('catalog_path')}; shared clean layer fallback recorded explicitly",
            })
        elif data_api_resolution:
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'blocked',
                'detail': data_api_resolution.get('error') or snapshot_note or str(data_api_resolution),
            })
    if need_minute:
        if data_api_resolution.get('status') == 'ready':
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'pass',
                'detail': f"clean_daily_bar and minute_bar resolved from catalog {data_api_resolution.get('catalog_path')}",
            })
        elif data_api_resolution.get('status') == 'catalog_absent_legacy_shared_clean_fallback':
            coverage.append({
                'name': 'factorforge_data_api_catalog',
                'status': 'legacy_fallback',
                'detail': f"catalog absent at {data_api_resolution.get('catalog_path')}; CPV/minute legacy fallback recorded explicitly",
            })
        else:
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'blocked',
                'detail': data_api_resolution.get('error') or str(data_api_resolution),
            })

    feasibility = 'blocked' if blocked else ('proxy_ready' if proxy_rules else 'ready')
    if local_input_paths.get('snapshot_source') == 'factorforge_data_api':
        notes.append('Step 3A reads clean_daily_bar through the FactorForge Data API catalog and materializes only report-scoped slices.')
    elif (local_input_paths.get('data_api_resolution') or {}).get('status') == 'catalog_absent_legacy_shared_clean_fallback':
        notes.append('Step 3A used the legacy shared clean fallback only because the Data API catalog file is absent; this is not Data API ready.')
    else:
        notes.append('Step 3A must use clean_daily_bar through the FactorForge Data API catalog; missing dataset or fields are emitted as data requirements.')

    data_prep_master = {
        'report_id': report_id,
        'factor_id': factor_id,
        'feasibility': feasibility,
        'sample_window': sample_window,
        'data_sources': data_sources,
        'field_mapping': field_mapping,
        'proxy_rules': proxy_rules,
        'coverage_checks': coverage,
        'implementation_notes': notes,
        'blocked_items': blocked,
        'local_input_paths': local_input_paths,
        'data_api_resolution': local_input_paths.get('data_api_resolution'),
        'data_requirement_ref': local_input_paths.get('data_requirement_ref'),
        'data_requirement_refs': local_input_paths.get('data_requirement_refs') or [],
        'required_daily_fields': required_daily_fields,
        'required_minute_fields': required_minute_fields,
        'daily_filter_policy': local_input_paths.get('daily_filter_policy'),
    }

    qlib_adapter_config = {
        'report_id': report_id,
        'factor_id': factor_id,
        'adapter_name': 'factorforge_step3a_qlib_adapter',
        'provider_priority': ['local_cache', 's3'],
        'normalized_datasets': [ds['normalized_dataset'] for ds in data_sources],
        'instrument_field': 'ts_code',
        'date_field': 'trade_date',
        'qlib_field_map': {
            '$open': 'open',
            '$high': 'high',
            '$low': 'low',
            '$close': 'close',
            '$volume': 'vol',
            '$amount': 'amount',
            '$ret': 'pct_chg'
        },
        'logical_fields': {
            'instrument': 'ts_code',
            'date': 'trade_date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'vol',
            'amount': 'amount',
            'return_daily': 'pct_chg',
            'turnover_rate': 'turnover_rate',
            'turnover_rate_f': 'turnover_rate_f',
            'volume_ratio': 'volume_ratio',
            'pe': 'pe',
            'pe_ttm': 'pe_ttm',
            'pb': 'pb',
            'ps': 'ps',
            'ps_ttm': 'ps_ttm',
            'total_mv': 'total_mv',
            'circ_mv': 'circ_mv'
        },
        'proxy_rules': proxy_rules,
        'daily_filter_policy': local_input_paths.get('daily_filter_policy'),
        'sample_window': sample_window,
        'local_input_paths': local_input_paths,
        'data_api_resolution': local_input_paths.get('data_api_resolution'),
        'data_requirement_ref': local_input_paths.get('data_requirement_ref'),
        'data_requirement_refs': local_input_paths.get('data_requirement_refs') or [],
        'step4_access_rule': 'Step 4 should prefer Step 3A normalized local inputs / adapter config, not raw S3 paths directly.'
    }

    implementation_plan_stub = {
        'report_id': report_id,
        'factor_id': factor_id,
        'preferred_execution_mode': 'hybrid' if cpv_like else 'direct_python',
        'candidate_paths': ['direct_python', 'qlib_operator', 'hybrid'],
        'current_decision': 'defer_to_step3b',
        'notes': [
            'Step 3A 已完成数据/API层，并补齐本地输入快照用于 Step 4 集成执行',
            '若 qlib 算子无法完整表达，则回退 direct_python'
        ]
    }

    return data_prep_master, qlib_adapter_config, implementation_plan_stub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    args = ap.parse_args()
    enforce_direct_step_policy(args.manifest)
    _manifest, manifest_rid = apply_runtime_manifest(args.manifest)
    report_id = args.report_id or manifest_rid
    if not report_id:
        raise SystemExit('run_step3.py requires --report-id or --manifest')

    data_prep_master, qlib_adapter_config, implementation_plan_stub = build_step3a(report_id)

    out_path = OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json'
    qlib_path = OBJ / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'
    impl_path = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    val_path = OBJ / 'validation' / f'data_feasibility_report__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'

    existing_impl = read_existing_json(impl_path)
    implementation_plan_payload = merge_implementation_plan(existing_impl, implementation_plan_stub)

    write_json(out_path, data_prep_master)
    write_json(qlib_path, qlib_adapter_config)
    write_json(impl_path, implementation_plan_payload)
    step3a_ready = data_prep_master['feasibility'] in {'ready', 'proxy_ready'}

    write_json(val_path, {
        'report_id': report_id,
        'final_result': data_prep_master['feasibility'],
        'checks': data_prep_master['coverage_checks'],
        'proxy_count': len(data_prep_master['proxy_rules']),
        'local_input_paths': data_prep_master['local_input_paths'],
        'data_api_resolution': data_prep_master.get('data_api_resolution'),
        'data_requirement_ref': data_prep_master.get('data_requirement_ref'),
        'data_requirement_refs': data_prep_master.get('data_requirement_refs') or [],
    })
    # COMMENT_POLICY: execution_handoff
    # Step 3A handoff is the contract boundary for Step 4 input resolution.
    existing_handoff = read_existing_json(handoff_path)
    handoff_payload = merge_handoff(existing_handoff, {
        'report_id': report_id,
        'step3a_ready': step3a_ready,
        'data_prep_master_ref': out_path.name,
        'qlib_adapter_config_ref': qlib_path.name,
        'implementation_plan_master_ref': impl_path.name,
        'factor_spec_master_ref': f'factor_spec_master__{report_id}.json',
        'local_input_paths': data_prep_master['local_input_paths'],
        'data_api_resolution': data_prep_master.get('data_api_resolution'),
        'data_requirement_ref': data_prep_master.get('data_requirement_ref'),
        'data_requirement_refs': data_prep_master.get('data_requirement_refs') or [],
    })
    write_json(handoff_path, handoff_payload)


if __name__ == '__main__':
    main()
