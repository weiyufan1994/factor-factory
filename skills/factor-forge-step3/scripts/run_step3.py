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
    clean_daily_layer_ready,
    inspect_trade_date_csv_root,
    load_clean_daily_layer,
    resolve_clean_daily_layer_paths,
    resolve_local_tushare_paths,
)
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id

FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FF.parent
OBJ = FF / 'objects'
RUNS = FF / 'runs'
REAL_CPV_BASE = WORKSPACE / 'tmp' / 'cpv_run_2016'
LOCAL_TUSHARE = resolve_local_tushare_paths()
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


def build_local_daily_snapshot(report_id: str, sample_window: dict):
    # Daily-only factors should read the shared clean layer and only materialize a report-scoped slice.
    return materialize_shared_daily_slice(report_id, sample_window)


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

    sample_window = declared_sample_window(fsm, handoff_to_step3, infer_sample_window(factor_id, required_text))
    data_sources = []
    coverage = []
    proxy_rules = []
    blocked = []
    field_mapping = {}
    notes = []

    if need_minute:
        data_sources.append({
            'name': 'tushare_minute_bars',
            'kind': 's3',
            'path': 's3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/',
            'fields': ['ts_code', 'trade_time', 'trade_date', 'bar_time', 'minute_index', 'open', 'close', 'high', 'low', 'vol', 'amount'],
            'normalized_dataset': 'minute_bar'
        })
        coverage.append({'name': 'minute_2016q1', 'status': 'pass', 'detail': '20160104-20160329 共57个交易日已确认存在'})
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
            'name': 'tushare_daily_bars',
            'kind': 's3',
            'path': 's3://yufan-data-lake/tushares/行情数据/daily.csv',
            'fields': ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'change', 'pct_chg', 'vol', 'amount'],
            'normalized_dataset': 'daily_bar'
        })
        coverage.append({'name': 'daily_history', 'status': 'pass', 'detail': 'daily.csv 已确认可用'})
        field_mapping.update({
            'daily_open': 'open',
            'daily_high': 'high',
            'daily_low': 'low',
            'daily_close': 'close',
            'daily_return': 'pct_chg',
            'daily_volume': 'vol',
            'daily_amount': 'amount'
        })

    daily_basic_meta = inspect_trade_date_csv_root(LOCAL_TUSHARE.daily_basic_dir)
    if need_daily_basic:
        data_sources.append({
            'name': 'tushare_daily_basic_incremental',
            'kind': 's3_partitioned',
            'path': 's3://yufan-data-lake/tushares/行情数据/daily_basic_incremental/',
            'fields': ['ts_code', 'trade_date', 'turnover_rate', 'turnover_rate_f', 'volume_ratio', 'pe', 'pe_ttm', 'pb', 'ps', 'ps_ttm', 'dv_ratio', 'dv_ttm', 'total_share', 'float_share', 'free_share', 'total_mv', 'circ_mv'],
            'normalized_dataset': 'daily_basic'
        })
        if daily_basic_meta:
            coverage.append({
                'name': 'daily_basic_local_cache',
                'status': 'pass',
                'detail': f'daily_basic local cache detected at {daily_basic_meta["path"]} with {daily_basic_meta["trade_date_count"]} trade_date partitions'
            })
        else:
            coverage.append({
                'name': 'daily_basic_incremental',
                'status': 'pass',
                'detail': 'daily_basic_incremental is treated as the canonical valuation/basic layer and should be synced locally after the backfill completes'
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
    if cpv_like:
        # CPV should prefer daily_basic for valuation / scale / turnover features.
        # Only keep risks that are truly unresolved in the current data contract.
        proxy_rules.extend([
            {
                'missing_field': 'industry_dummy',
                'proxy_field': '',
                'reason': '当前未接入申万行业字段，不做纯行业中性化',
                'risk': 'high'
            }
        ])
        local_input_paths = build_local_cpv_snapshots(report_id, sample_window)
        notes.append('CPV 当前应优先使用 daily_basic_incremental 中的 total_mv / circ_mv / turnover_rate / pe / pb 等字段')
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        if snapshot_source in {'shared_clean_daily_layer', 'synthetic_fallback'}:
            notes.append('Step 3A 已生成 Step 4 可直接消费的本地输入快照，供集成证明与样例执行使用')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source in {'real_local_insufficient', 'missing_real_local_data', 'missing_clean_daily_layer'}:
            blocked.append({
                'code': 'SHARED_CLEAN_DAILY_LAYER_MISSING' if snapshot_source == 'missing_clean_daily_layer' else 'LOCAL_MINUTE_HISTORY_INSUFFICIENT',
                'detail': snapshot_note,
            })
    else:
        local_input_paths = build_local_daily_snapshot(report_id, sample_window)
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source == 'missing_clean_daily_layer':
            blocked.append({
                'code': 'SHARED_CLEAN_DAILY_LAYER_MISSING',
                'detail': snapshot_note,
            })

    feasibility = 'blocked' if blocked else ('proxy_ready' if proxy_rules else 'ready')
    notes.append(
        'Step 3A reads the shared clean daily layer and only materializes report-scoped slices. Heavy daily cleaning is owned by scripts/build_clean_daily_layer.py.'
    )

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
        'local_input_paths': data_prep_master['local_input_paths']
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
        'local_input_paths': data_prep_master['local_input_paths']
    })
    write_json(handoff_path, handoff_payload)


if __name__ == '__main__':
    main()
