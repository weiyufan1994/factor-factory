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

from factor_factory.data_api import DataApiClient, DataQuery
from factor_factory.data_api.catalog import resolve_default_catalog_path
from factor_factory.data_api.errors import DataCatalogNotFound
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id

FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FF.parent
OBJ = FF / 'objects'
RUNS = FF / 'runs'


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict | None, str | None]:
    """Apply the orchestrator-owned runtime manifest before any Step3 path writes."""
    global FF, WORKSPACE, OBJ, RUNS
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FF = manifest_factorforge_root(manifest)
    WORKSPACE = FF.parent
    OBJ = FF / 'objects'
    RUNS = FF / 'runs'
    os.environ['FACTORFORGE_ROOT'] = str(FF)
    return manifest, manifest_report_id(manifest)


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FF, WORKSPACE, OBJ, RUNS
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
        return pd.Timestamp.today().strftime('%Y%m%d')
    return normalized


def data_requirement_path(report_id: str) -> Path:
    return OBJ / 'data_requirements' / f'factorforge_data_requirement__{report_id}.json'


def default_data_catalog_path() -> Path:
    try:
        return resolve_default_catalog_path()
    except DataCatalogNotFound:
        return FF / 'data' / 'catalog' / 'data_catalog.json'


def build_data_query(dataset: str, sample_window: dict, fields: list[str], frequency: str) -> DataQuery:
    return DataQuery(
        dataset=dataset,
        start_date=api_window_value(sample_window.get('start')),
        end_date=api_window_value(sample_window.get('end')),
        universe='a_share_all',
        fields=fields,
        frequency=frequency,
    )


def catalog_missing_resolution(required_daily_fields: list[str], required_minute_fields: list[str], sample_window: dict, catalog_path: Path) -> dict:
    datasets = {
        'clean_daily_bar': {
            'status': 'catalog_missing',
            'query': build_data_query('clean_daily_bar', sample_window, required_daily_fields, 'daily').__dict__,
            'blocked_reason': f'data catalog not found: {catalog_path}',
            'source': {'dataset_id': 'clean_daily_bar', 'catalog_path': str(catalog_path), 'backend': 'none'},
        }
    }
    if required_minute_fields:
        datasets[MINUTE_DATASET_ID] = {
            'status': 'catalog_missing',
            'query': build_data_query(MINUTE_DATASET_ID, sample_window, required_minute_fields, '1min').__dict__,
            'blocked_reason': f'data catalog not found: {catalog_path}',
            'source': {'dataset_id': MINUTE_DATASET_ID, 'catalog_path': str(catalog_path), 'backend': 'none'},
        }
    return {
        'engine': 'factor_factory.data_api',
        'dataset_id': 'step3a_data_contract',
        'status': 'catalog_missing',
        'catalog_path': str(catalog_path),
        'catalog_exists': False,
        'available_datasets': [],
        'required_daily_fields': required_daily_fields,
        'required_minute_fields': required_minute_fields,
        'datasets': datasets,
        'resolved_fields': {},
        'missing_fields': {},
        'missing_datasets': ['clean_daily_bar', *([MINUTE_DATASET_ID] if required_minute_fields else [])],
        'proxy_rules': {},
        'blocked_reason': f'FactorForge data catalog is missing at {catalog_path}; Step3A cannot resolve required datasets through DataApiClient.',
        'warnings': ['catalog_missing'],
    }


def resolve_step3a_data_contract(required_daily_fields: list[str], required_minute_fields: list[str], sample_window: dict) -> tuple[dict, dict[str, object]]:
    catalog_path = default_data_catalog_path()
    try:
        client = DataApiClient.from_env()
    except DataCatalogNotFound:
        return catalog_missing_resolution(required_daily_fields, required_minute_fields, sample_window, catalog_path), {}

    results = {
        'clean_daily_bar': client.fetch(build_data_query('clean_daily_bar', sample_window, required_daily_fields, 'daily')),
    }
    if required_minute_fields:
        results[MINUTE_DATASET_ID] = client.fetch(build_data_query(MINUTE_DATASET_ID, sample_window, required_minute_fields, '1min'))

    metadata = {dataset: result.to_metadata() for dataset, result in results.items()}
    statuses = {dataset: result.status for dataset, result in results.items()}
    if any(status == 'blocked' for status in statuses.values()):
        status = 'blocked'
    elif any(status == 'proxy_ready' for status in statuses.values()):
        status = 'proxy_ready'
    else:
        status = 'ready'

    missing_fields = {
        dataset: list(result.coverage.missing_fields)
        for dataset, result in results.items()
        if result.coverage.missing_fields
    }
    missing_datasets = [
        dataset
        for dataset, result in results.items()
        if result.status == 'blocked' and str(result.blocked_reason or '').startswith('dataset_not_found')
    ]
    blocked_reason = {
        dataset: result.blocked_reason
        for dataset, result in results.items()
        if result.status == 'blocked' or result.blocked_reason
    }
    proxy_rules = {
        dataset: metadata[dataset].get('proxy_rules') or []
        for dataset, result in results.items()
        if result.proxy_rules
    }
    resolution = {
        'engine': 'factor_factory.data_api',
        'dataset_id': 'step3a_data_contract',
        'status': status,
        'catalog_path': str(client.catalog.path),
        'catalog_exists': client.catalog.path.exists(),
        'available_datasets': client.list_datasets(),
        'required_daily_fields': required_daily_fields,
        'required_minute_fields': required_minute_fields,
        'datasets': metadata,
        'resolved_fields': {
            dataset: dict(result.resolved_fields)
            for dataset, result in results.items()
        },
        'missing_fields': missing_fields,
        'missing_datasets': missing_datasets,
        'proxy_rules': proxy_rules,
        'blocked_reason': blocked_reason,
        'warnings': {
            dataset: list(result.warnings)
            for dataset, result in results.items()
            if result.warnings
        },
    }
    return resolution, results


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
    blocked_reason = resolution.get('blocked_reason') or {}
    if isinstance(blocked_reason, dict):
        unresolved.extend(key for key, value in blocked_reason.items() if value and key not in unresolved)
    dataset_id = unresolved[0] if len(unresolved) == 1 else 'step3a_data_contract'
    columns = []
    for item in required_datasets:
        columns.extend(item['columns'])
    requirement = {
        'type': 'factorforge_data_requirement',
        'contract_version': 'factorforge_data_requirement_v1',
        'dataset_id': dataset_id,
        'reason': (
            'Step3A requires all factor inputs to resolve through factor_factory.data_api. '
            'Do not search raw/local paths or rebuild clean data inside factor research.'
        ),
        'request': {
            'start_date': api_window_value(sample_window.get('start')),
            'end_date': api_window_value(sample_window.get('end')),
            'columns': list(dict.fromkeys(columns)),
            'frequency': 'mixed' if len(required_datasets) > 1 else required_datasets[0]['frequency'],
            'required_transform': 'publish the missing Step3A research-ready data mart(s) and update the catalog',
        },
        'required_datasets': required_datasets,
        'resolution': resolution,
        'data_api_result_metadata': resolution.get('datasets') or {},
        'missing_fields': resolution.get('missing_fields') or {},
        'missing_datasets': resolution.get('missing_datasets') or [],
        'blocked_reason': blocked_reason,
    }
    path = data_requirement_path(report_id)
    write_json(path, requirement)
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


def frame_summary(frame: pd.DataFrame) -> dict:
    return {
        'rows': int(len(frame)),
        'tickers': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns and not frame.empty else 0,
        'trade_date_min': str(frame['trade_date'].min()) if 'trade_date' in frame.columns and not frame.empty else None,
        'trade_date_max': str(frame['trade_date'].max()) if 'trade_date' in frame.columns and not frame.empty else None,
        'columns': list(frame.columns),
    }


def sort_snapshot_frame(dataset: str, frame: pd.DataFrame) -> pd.DataFrame:
    sort_keys = ['ts_code', 'trade_date', 'trade_time'] if dataset == MINUTE_DATASET_ID else ['ts_code', 'trade_date']
    existing = [key for key in sort_keys if key in frame.columns]
    return frame.sort_values(existing).reset_index(drop=True) if existing else frame.reset_index(drop=True)


def materialize_data_api_contract_slice(report_id: str, sample_window: dict, resolution: dict, results: dict[str, object]) -> dict:
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    daily_meta = local_dir / f'daily_input_meta__{report_id}.json'
    if daily_csv.exists() or daily_csv.is_symlink():
        daily_csv.unlink()

    daily_result = results['clean_daily_bar']
    daily_df = sort_snapshot_frame('clean_daily_bar', daily_result.frame.copy())
    daily_df.to_csv(daily_csv, index=False)
    meta = {
        'source': 'factor_factory.data_api',
        'dataset_id': 'clean_daily_bar',
        'catalog_path': resolution.get('catalog_path'),
        'query': resolution.get('datasets', {}).get('clean_daily_bar', {}).get('query'),
        'required_fields': resolution.get('required_daily_fields') or [],
        'resolved_fields': daily_result.resolved_fields,
        'data_api_result': daily_result.to_metadata(),
        'slice_summary': frame_summary(daily_df),
    }
    daily_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    result = {
        'daily_df_csv': str(daily_csv.relative_to(WORKSPACE)),
        'daily_input_meta': str(daily_meta.relative_to(WORKSPACE)),
        'daily_input_meta_json': str(daily_meta.relative_to(WORKSPACE)),
        'snapshot_source': 'factor_factory.data_api',
        'input_mode': 'daily_only',
        'data_api_resolution': resolution,
        'daily_filter_policy': 'factor_factory_data_api_fetch',
    }
    if MINUTE_DATASET_ID in results:
        minute_csv = local_dir / f'minute_input__{report_id}.csv'
        minute_meta = local_dir / f'minute_input_meta__{report_id}.json'
        if minute_csv.exists() or minute_csv.is_symlink():
            minute_csv.unlink()
        minute_result = results[MINUTE_DATASET_ID]
        minute_df = sort_snapshot_frame(MINUTE_DATASET_ID, minute_result.frame.copy())
        minute_df.to_csv(minute_csv, index=False)
        minute_payload = {
            'source': 'factor_factory.data_api',
            'dataset_id': MINUTE_DATASET_ID,
            'catalog_path': resolution.get('catalog_path'),
            'query': resolution.get('datasets', {}).get(MINUTE_DATASET_ID, {}).get('query'),
            'required_fields': resolution.get('required_minute_fields') or [],
            'resolved_fields': minute_result.resolved_fields,
            'data_api_result': minute_result.to_metadata(),
            'slice_summary': frame_summary(minute_df),
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
    result['snapshot_note'] = 'Step3A input fetched through factor_factory.data_api and materialized as report-scoped snapshots.'
    return result


def build_local_daily_snapshot(report_id: str, sample_window: dict, resolution: dict, results: dict[str, object]):
    # Daily-only factors consume the independent Data API. Missing catalogs, datasets, or fields block and write
    # a data requirement instead of searching shared clean or raw local paths.
    if resolution.get('status') in {'ready', 'proxy_ready'}:
        return materialize_data_api_contract_slice(report_id, sample_window, resolution, results)
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
    sample_window = declared_sample_window(fsm, handoff_to_step3, infer_sample_window(factor_id, required_text))
    data_api_resolution, data_api_results = resolve_step3a_data_contract(required_daily_fields, required_minute_fields, sample_window)
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
        coverage.append({'name': 'minute_bar', 'status': 'pending', 'detail': 'resolved through FactorForge Data API catalog'})
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
        coverage.append({'name': 'clean_daily_bar', 'status': 'pending', 'detail': 'resolved through FactorForge Data API catalog'})
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
        if data_api_resolution.get('status') in {'ready', 'proxy_ready'}:
            local_input_paths = materialize_data_api_contract_slice(report_id, sample_window, data_api_resolution, data_api_results)
        else:
            local_input_paths = data_api_requirement_result(report_id, sample_window, data_api_resolution)
        notes.append('CPV/minute Step 3A inputs must resolve through clean_daily_bar and minute_bar when the Data API catalog exists.')
        notes.append('Daily_basic / valuation / market-cap fields are required on clean_daily_bar in this contract.')
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        if snapshot_source == 'factor_factory.data_api':
            notes.append('Step 3A 已生成 Step 4 可直接消费的本地输入快照，供集成证明与样例执行使用')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source == 'data_api_requirement':
            blocked.append({
                'code': 'FACTORFORGE_DATA_API_REQUIREMENT',
                'detail': snapshot_note,
                'data_requirement_ref': local_input_paths.get('data_requirement_ref'),
            })
    else:
        local_input_paths = build_local_daily_snapshot(report_id, sample_window, data_api_resolution, data_api_results)
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
        if data_api_resolution.get('status') in {'ready', 'proxy_ready'}:
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'pass',
                'detail': f"Step3A data contract resolved from catalog {data_api_resolution.get('catalog_path')}",
            })
        elif data_api_resolution:
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'blocked',
                'detail': data_api_resolution.get('error') or snapshot_note or str(data_api_resolution),
            })
    if need_minute:
        if data_api_resolution.get('status') in {'ready', 'proxy_ready'}:
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'pass',
                'detail': f"clean_daily_bar and minute_bar resolved from catalog {data_api_resolution.get('catalog_path')}",
            })
        else:
            coverage.append({
                'name': 'factorforge_data_api_step3a_contract',
                'status': 'blocked',
                'detail': data_api_resolution.get('error') or str(data_api_resolution),
            })

    api_status = data_api_resolution.get('status')
    if api_status == 'blocked' and not blocked:
        blocked.append({
            'code': 'FACTORFORGE_DATA_API_REQUIREMENT',
            'detail': data_api_resolution.get('blocked_reason') or data_api_resolution,
            'data_requirement_ref': local_input_paths.get('data_requirement_ref'),
        })
    feasibility = 'blocked' if blocked else ('proxy_ready' if api_status == 'proxy_ready' else 'ready')
    proxy_rules = [
        rule
        for rules in (data_api_resolution.get('proxy_rules') or {}).values()
        for rule in rules
    ]
    if local_input_paths.get('snapshot_source') == 'factor_factory.data_api':
        notes.append('Step 3A reads clean_daily_bar through factor_factory.data_api and materializes only report-scoped slices.')
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
