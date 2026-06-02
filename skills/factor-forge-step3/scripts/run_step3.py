#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
    resolve_clean_daily_layer_paths,
    resolve_local_tushare_paths,
)
from factor_factory.data_api import fetch_data_api_dataset, resolve_data_api_dataset
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id

FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FF.parent
OBJ = FF / 'objects'
RUNS = FF / 'runs'
REAL_PRICE_VOLUME_BASE = WORKSPACE / 'tmp' / 'price_volume_run_2016'
LOCAL_TUSHARE = resolve_local_tushare_paths()
CLEAN_DAILY_LAYER = resolve_clean_daily_layer_paths()
CSV_POLICY_VALUES = {'full_csv', 'sample_csv', 'no_csv'}
CSV_SAMPLE_MAX_ROWS = 10_000
SORT_CONTRACT_VERSION = 'factorforge_sort_contract_v1'
DIRECT_CODE_CONTRACT_VERSION = 'factorforge_direct_code_contract_v1'
DIRECT_CODE_ALLOWED_SOURCE_DERIVATIONS = {
    'source_code_preserved_from_formal_step2_raw_direct_code_contract',
    'source_code_preserved_from_step2_direct_code_contract',
    'source_code_generated_by_step3a_llm_provider',
}


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict | None, str | None]:
    """Apply the orchestrator-owned runtime manifest before any Step3 path writes."""
    global FF, WORKSPACE, OBJ, RUNS, REAL_PRICE_VOLUME_BASE, CLEAN_DAILY_LAYER
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FF = manifest_factorforge_root(manifest)
    WORKSPACE = FF.parent
    OBJ = FF / 'objects'
    RUNS = FF / 'runs'
    REAL_PRICE_VOLUME_BASE = WORKSPACE / 'tmp' / 'price_volume_run_2016'
    os.environ['FACTORFORGE_ROOT'] = str(FF)
    if manifest.get('clean_data_root'):
        clean_root = Path(manifest['clean_data_root'])
        CLEAN_DAILY_LAYER = CleanDailyLayerPaths(
            root=clean_root,
            daily_parquet=clean_root / 'daily_clean.parquet',
            metadata_json=clean_root / 'daily_clean.meta.json',
        )
    elif os.getenv('FACTORFORGE_CLEAN_DAILY_DIR'):
        CLEAN_DAILY_LAYER = resolve_clean_daily_layer_paths()
    return manifest, manifest_report_id(manifest)


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FF, WORKSPACE, OBJ, RUNS, REAL_PRICE_VOLUME_BASE, CLEAN_DAILY_LAYER
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
    REAL_PRICE_VOLUME_BASE = WORKSPACE / 'tmp' / 'price_volume_run_2016'
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


def resolve_csv_policy(explicit_policy: str | None = None) -> str:
    policy = explicit_policy or os.getenv('FACTORFORGE_CSV_OUTPUT_POLICY') or 'full_csv'
    if policy not in CSV_POLICY_VALUES:
        raise SystemExit(f'BLOCK_FACTORFORGE_INVALID_CSV_OUTPUT_POLICY:{policy}')
    return policy


def deterministic_csv_sample(df: pd.DataFrame, *, max_rows: int = CSV_SAMPLE_MAX_ROWS) -> pd.DataFrame:
    if len(df) <= max_rows:
        return df.copy()
    head_n = max_rows // 2
    tail_n = max_rows - head_n
    return pd.concat([df.head(head_n), df.tail(tail_n)], ignore_index=True)


def key_order_hash(df: pd.DataFrame) -> str:
    key_frame = df[['ts_code', 'trade_date']].astype(str).reset_index(drop=True)
    return hashlib.sha256(key_frame.to_csv(index=False).encode('utf-8')).hexdigest()


def stable_hash(data) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def source_hash(source_code: str) -> str:
    return hashlib.sha256(source_code.encode('utf-8')).hexdigest()


def _existing_code_contract_source(contract: dict) -> str:
    if not isinstance(contract, dict):
        return ''
    code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
    return str(
        code_contract.get('source_code')
        or contract.get('source_code')
        or ''
    )


def _contract_has_source(plan: dict) -> bool:
    if not isinstance(plan, dict):
        return False
    return bool(
        str((plan.get('code_contract') or {}).get('source_code') if isinstance(plan.get('code_contract'), dict) else '').strip()
        or _existing_code_contract_source(plan.get('implementation_contract') or {}).strip()
        or str(plan.get('source_code') or '').strip()
    )


def sample_sortedness_check(df: pd.DataFrame, *, max_points: int = 2048) -> bool:
    if df.empty:
        return True
    if len(df) <= max_points:
        sample = df[['ts_code', 'trade_date']].astype(str).reset_index(drop=True)
    else:
        step = max(1, len(df) // max_points)
        indices = sorted(set([0, len(df) - 1, *range(0, len(df), step)]))
        sample = df.iloc[indices][['ts_code', 'trade_date']].astype(str).reset_index(drop=True)
    expected = sample.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    return bool(sample.equals(expected))


def build_sort_contract(daily_df: pd.DataFrame) -> dict:
    return {
        'version': SORT_CONTRACT_VERSION,
        'sorted_by': ['ts_code', 'trade_date'],
        'row_count': int(len(daily_df)),
        'key_dtype': {
            'ts_code': str(daily_df['ts_code'].dtype),
            'trade_date': str(daily_df['trade_date'].dtype),
        },
        'source': 'step3a_local_input',
        'data_hash': key_order_hash(daily_df),
        'schema': list(daily_df.columns),
        'duplicate_key_check': not bool(daily_df[['ts_code', 'trade_date']].duplicated().any()),
        'sample_sortedness_check': sample_sortedness_check(daily_df),
    }


def materialize_daily_audit_csv(
    daily_df: pd.DataFrame,
    *,
    report_id: str,
    full_csv_path: Path,
    sample_csv_path: Path,
    policy: str,
) -> dict:
    for path in [full_csv_path, sample_csv_path]:
        if path.exists() or path.is_symlink():
            path.unlink()

    contract = {
        'version': 'factorforge_step3a_daily_io_contract_v1',
        'formal_evidence_format': 'parquet',
        'performance_path': 'parquet',
        'audit_path': 'csv' if policy == 'full_csv' else ('csv_sample' if policy == 'sample_csv' else 'none'),
        'csv_output_policy': policy,
        'csv_rows_written': 0,
        'parquet_rows_written': int(len(daily_df)),
        'csv_sample_strategy': 'none',
        'full_csv_available': False,
        'schema_parity_required': policy in {'full_csv', 'sample_csv'},
        'value_parity_required': policy == 'full_csv',
        'csv_required_for_audit': policy == 'full_csv',
        'parquet_required_for_performance': True,
        'sample_schema_parity': None,
        'full_csv_absent_validated': policy in {'sample_csv', 'no_csv'},
        'full_csv_absence_reason': f'step3a_{policy}_policy' if policy in {'sample_csv', 'no_csv'} else None,
        'sort_contract': build_sort_contract(daily_df),
    }
    payload: dict = {
        'audit_daily_format': 'none',
        'daily_io_contract': contract,
        'sort_contract': contract['sort_contract'],
        'daily_df_csv': None,
        'daily_df_csv_sample': None,
    }
    if policy == 'full_csv':
        daily_df.to_csv(full_csv_path, index=False)
        contract.update({
            'csv_rows_written': int(len(daily_df)),
            'csv_sample_strategy': 'full',
            'full_csv_available': True,
            'sample_schema_parity': True,
            'full_csv_absent_validated': False,
            'full_csv_absence_reason': None,
            'csv_path': str(full_csv_path.relative_to(WORKSPACE)),
            'csv_sample_path': None,
        })
        payload.update({
            'daily_df_csv': str(full_csv_path.relative_to(WORKSPACE)),
            'audit_daily_format': 'csv',
        })
    elif policy == 'sample_csv':
        sample_df = deterministic_csv_sample(daily_df)
        sample_df.to_csv(sample_csv_path, index=False)
        contract.update({
            'csv_rows_written': int(len(sample_df)),
            'csv_sample_strategy': 'head_tail',
            'sample_schema_parity': list(sample_df.columns) == list(daily_df.columns),
            'csv_path': None,
            'csv_sample_path': str(sample_csv_path.relative_to(WORKSPACE)),
        })
        payload.update({
            'daily_df_csv_sample': str(sample_csv_path.relative_to(WORKSPACE)),
            'audit_daily_format': 'csv_sample',
        })
    else:
        contract.update({'csv_path': None, 'csv_sample_path': None})
    return payload


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

    if updates.get('step3a_ready') is False:
        merged['step3a_ready'] = False
        merged['step3b_ready'] = False
        merged['first_run_outputs'] = {
            'status': 'blocked',
            'no_first_run_reason': 'step3a_feasibility_blocked',
            'output_paths': [],
            'run_metadata_path': None,
            'factor_values_path': None,
        }
        executable_local_input_keys = {
            'daily_df_path',
            'daily_df_parquet',
            'daily_df_csv',
            'daily_df_csv_sample',
            'minute_df_path',
            'minute_df_parquet',
            'minute_df_csv',
            'minute_df_csv_sample',
            'local_daily_path',
            'local_minute_path',
        }
        blocked_local_inputs = {}
        if isinstance(update_local_inputs, dict):
            blocked_local_inputs.update(update_local_inputs)
        if not blocked_local_inputs:
            blocked_local_inputs = {
                'input_mode': 'blocked',
                'snapshot_source': 'step3a_feasibility_blocked',
                'snapshot_note': 'Step3A feasibility blocked; stale executable local snapshots cleared.',
            }
        for key in executable_local_input_keys:
            blocked_local_inputs.pop(key, None)
        merged['local_input_paths'] = blocked_local_inputs
        for key in [
            'factor_impl_ref',
            'factor_impl_stub_ref',
            'qlib_expression_draft_ref',
            'hybrid_execution_scaffold_ref',
            'step3b_sample_run_metadata_ref',
            'step3b_sample_factor_values_ref',
            'implementation_path',
            'factor_values_path',
        ]:
            merged.pop(key, None)
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

    if _contract_has_source(updates) and not _contract_has_source(existing):
        for key in ['code_contract', 'implementation_contract', 'output_schema', 'source_code', 'code_hash', 'code_contract_hash']:
            if key in updates:
                merged[key] = updates[key]

    return merged


def infer_sample_window(factor_id: str, required_text: str):
    del factor_id
    if re.search(r'minute|分钟|高频', required_text, re.I):
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
    source_metadata = fsm.get('source_metadata') or {}
    candidates = [
        canonical.get('sample_window'),
        canonical.get('backtest_window'),
        fsm.get('sample_window'),
        fsm.get('backtest_window'),
        handoff.get('sample_window'),
        handoff.get('backtest_window'),
        handoff.get('step4_backtest_window'),
    ]
    if source_metadata.get('window_start') or source_metadata.get('window_end'):
        candidates.append({
            'start': source_metadata.get('window_start'),
            'end': source_metadata.get('window_end'),
            'calendar': source_metadata.get('calendar'),
        })
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


def is_price_volume_minute_formula(canonical: dict) -> bool:
    required_inputs = [str(x).lower() for x in (canonical.get('required_inputs') or [])]
    formula_text = str(canonical.get('formula_text') or '').lower()
    cross_steps = ' '.join(str(x).lower() for x in (canonical.get('cross_sectional_steps') or []))
    has_core_fields = {'close', 'vol', 'amount'}.issubset(set(required_inputs))
    has_pv_semantics = any(token in f'{formula_text} {cross_steps}' for token in ['price-volume', '价量', 'corr', '相关'])
    return has_core_fields and has_pv_semantics


def direct_code_requires_minute_inputs(fsm: dict) -> bool:
    contract = fsm.get('implementation_contract') if isinstance(fsm.get('implementation_contract'), dict) else {}
    code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
    canonical = fsm.get('canonical_spec') if isinstance(fsm.get('canonical_spec'), dict) else {}
    required_fields = (
        list(code_contract.get('required_fields') or [])
        + list(contract.get('required_fields') or [])
        + list(canonical.get('required_inputs') or [])
    )
    required_text = ' '.join(str(value).lower() for value in required_fields)
    source_text = str(code_contract.get('source_code') or contract.get('source_code') or '').lower()
    combined = f'{required_text} {source_text}'
    minute_tokens = {
        'minute',
        '分钟',
        '高频',
        'trade_time',
        'bar_time',
        'minute_index',
        'minute_bar',
        'stk_mins_1min',
    }
    if any(token in combined for token in minute_tokens):
        return True
    return bool(re.search(r'\bdatetime\b', combined))


def declared_implementation_mode(fsm: dict, *, price_volume_minute: bool) -> str:
    identity = fsm.get('artifact_identity') if isinstance(fsm.get('artifact_identity'), dict) else {}
    contract = fsm.get('implementation_contract') if isinstance(fsm.get('implementation_contract'), dict) else {}
    raw = (
        identity.get('implementation_mode')
        or fsm.get('implementation_mode')
        or contract.get('implementation_mode')
        or contract.get('mode')
    )
    if raw in {'operator', 'direct_code', 'hybrid'}:
        return str(raw)
    return 'hybrid' if price_volume_minute else 'direct_code'


def build_direct_code_contract_for_step3a(fsm: dict, qlib_adapter_config: dict) -> dict:
    canonical = fsm.get('canonical_spec') if isinstance(fsm.get('canonical_spec'), dict) else {}
    contract = fsm.get('implementation_contract') if isinstance(fsm.get('implementation_contract'), dict) else {}
    existing_code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
    existing_source = str(existing_code_contract.get('source_code') or '').strip()
    if existing_source:
        source = existing_source if existing_source.endswith('\n') else existing_source + '\n'
        source_derivation = existing_code_contract.get('source_derivation') if isinstance(existing_code_contract.get('source_derivation'), dict) else {}
        derivation = str(source_derivation.get('derivation') or 'source_code_preserved_from_step2_direct_code_contract')
        if derivation not in DIRECT_CODE_ALLOWED_SOURCE_DERIVATIONS:
            return {
                'status': 'blocked',
                'blocked_reason': f'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: unsupported source_code derivation {derivation}',
            }
    else:
        return {
            'status': 'blocked',
            'blocked_reason': 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: Step2 direct_code contract must explicitly provide code_contract.source_code',
        }

    required_fields = list(dict.fromkeys(
        list(existing_code_contract.get('required_fields') or [])
        + list(contract.get('required_fields') or [])
        + list(canonical.get('required_inputs') or [])
        + ['ts_code', 'trade_date']
    ))
    if 'vol' not in required_fields and 'volume' not in required_fields:
        required_fields.append('vol')
    if 'close' not in required_fields:
        required_fields.append('close')
    output_schema = (
        existing_code_contract.get('output_schema')
        or contract.get('output_schema')
        or {'columns': ['ts_code', 'trade_date', 'factor_value']}
    )
    imports = list(dict.fromkeys(list(existing_code_contract.get('imports') or []) + ['numpy', 'pandas']))
    code_contract = {
        **existing_code_contract,
        'code_contract_version': existing_code_contract.get('code_contract_version') or DIRECT_CODE_CONTRACT_VERSION,
        'function_name': existing_code_contract.get('function_name') or contract.get('function_name') or 'compute_factor',
        'entrypoint': existing_code_contract.get('entrypoint') or contract.get('entrypoint') or 'compute_factor',
        'source_code': source,
        'code_hash': source_hash(source),
        'imports': imports,
        'dependencies': list(dict.fromkeys(list(existing_code_contract.get('dependencies') or []) + imports)),
        'input_schema': existing_code_contract.get('input_schema') or {
            'daily_df': list((qlib_adapter_config.get('logical_fields') or {}).values()),
            'minute_df': ['ts_code', 'trade_date', 'trade_time', 'close', 'vol', 'amount'],
        },
        'output_schema': output_schema,
        'required_fields': required_fields,
        'information_set_rules': existing_code_contract.get('information_set_rules') or ['no future-looking fields or negative shifts'],
        'forbidden_patterns': existing_code_contract.get('forbidden_patterns') or [
            r'shift\s*\(\s*-\d+',
            r'\bfuture_return\b',
            r'\bnext_return\b',
            r'\blabel\b',
            r'\btarget\b',
            r'\bfuture_',
            r'\blookahead\b',
        ],
        'source_derivation': {
            **source_derivation,
            'derivation': derivation,
            'source_fields': [
                'factor_spec_master.implementation_contract.code_contract.source_code',
            ],
            'not_fallback': True,
        },
    }
    code_contract['code_contract_hash'] = stable_hash({
        key: value for key, value in code_contract.items() if key != 'code_contract_hash'
    })
    return {
        'status': 'ready',
        'code_contract': code_contract,
        'code_contract_hash': code_contract['code_contract_hash'],
        'source_code': source,
        'code_hash': code_contract['code_hash'],
        'output_schema': output_schema,
    }


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
        REAL_PRICE_VOLUME_BASE / 'stk_mins_1min',
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


def data_api_query_payload(
    dataset: str,
    sample_window: dict,
    fields: list[str],
    *,
    universe='a_share_all',
    frequency: str = 'daily',
) -> dict:
    return {
        'dataset': dataset,
        'start_date': _normalize_window_date(sample_window.get('start')) or '19000101',
        'end_date': _normalize_window_date(sample_window.get('end')) if _normalize_window_date(sample_window.get('end')) != 'current' else '29991231',
        'universe': universe,
        'fields': list(dict.fromkeys(fields)),
        'frequency': frequency,
    }


def build_step4_data_contract(
    *,
    sample_window: dict,
    daily_resolution: dict | None = None,
    minute_resolution: dict | None = None,
    daily_fields: list[str] | None = None,
    minute_fields: list[str] | None = None,
) -> dict:
    full_queries = {}
    sample_queries = {}
    if daily_resolution:
        fields = daily_fields or ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
        full_queries['clean_daily_bar'] = data_api_query_payload('clean_daily_bar', sample_window, fields)
        sample_queries['clean_daily_bar'] = data_api_query_payload(
            'clean_daily_bar',
            sample_window,
            fields,
            universe=['000001.SZ', '000002.SZ'],
        )
    if minute_resolution:
        fields = minute_fields or ['open', 'high', 'low', 'close', 'vol', 'amount']
        full_queries['minute_bar'] = data_api_query_payload('minute_bar', sample_window, fields, frequency='1min')
        sample_queries['minute_bar'] = data_api_query_payload(
            'minute_bar',
            sample_window,
            fields,
            universe=['000001.SZ', '000002.SZ'],
            frequency='1min',
        )
    catalog_path = None
    for resolution in [daily_resolution, minute_resolution]:
        if isinstance(resolution, dict) and resolution.get('catalog_path'):
            catalog_path = resolution.get('catalog_path')
            break
    return {
        'version': 'factorforge_step4_data_contract_v1',
        'producer': 'step3a',
        'data_api_package': 'factorforge_data_api',
        'catalog_path': catalog_path,
        'full_queries': full_queries,
        'sample_queries': sample_queries,
        'formal_factor_values_owner': 'Step4',
        'step3b_sample_policy': {
            'is_formal_factor_values': False,
            'purpose': 'step3_executability_proof',
            'full_execution_owner': 'Step4',
        },
    }


def _adv_window(field: str) -> int | None:
    match = re.fullmatch(r'adv([1-9][0-9]*)', str(field or '').strip().lower())
    if not match:
        return None
    return int(match.group(1))


def formula_required_daily_fields(fsm: dict) -> list[str]:
    canonical = fsm.get('canonical_spec') if isinstance(fsm.get('canonical_spec'), dict) else {}
    formula_ir = canonical.get('formula_ir') if isinstance(canonical.get('formula_ir'), dict) else {}
    candidates = (
        list(formula_ir.get('required_fields') or [])
        + list(canonical.get('required_inputs') or [])
        + list(fsm.get('required_inputs') or [])
    )
    return list(dict.fromkeys(str(field).strip().lower() for field in candidates if str(field).strip()))


def enrich_report_local_daily_fields(daily_df: pd.DataFrame, required_fields: list[str]) -> tuple[pd.DataFrame, dict]:
    """Materialize standard formula aliases in the report-local snapshot only."""
    required = {str(field).strip().lower() for field in (required_fields or [])}
    adv_fields = sorted((field, _adv_window(field)) for field in required if _adv_window(field) is not None)
    needs_volume = 'volume' in required or bool(adv_fields) or 'vwap' in required
    needs_returns = 'returns' in required or 'return' in required or 'ret' in required
    needs_vwap = 'vwap' in required

    added: list[str] = []
    sources: dict[str, str] = {}
    working = daily_df
    if needs_volume or needs_returns or needs_vwap or adv_fields:
        working = daily_df.copy()

    volume_col = 'volume' if 'volume' in working.columns else 'vol' if 'vol' in working.columns else None
    if needs_volume and 'volume' not in working.columns:
        if volume_col is None:
            raise SystemExit('BLOCK_FACTORFORGE_STEP3A_DERIVED_FIELD_MISSING_SOURCE: volume requires vol source')
        working['volume'] = pd.to_numeric(working[volume_col], errors='coerce')
        added.append('volume')
        sources['volume'] = volume_col
        volume_col = 'volume'

    if needs_returns and 'returns' not in working.columns:
        return_col = 'return' if 'return' in working.columns else 'pct_chg' if 'pct_chg' in working.columns else None
        if return_col is None:
            raise SystemExit('BLOCK_FACTORFORGE_STEP3A_DERIVED_FIELD_MISSING_SOURCE: returns requires pct_chg/return source')
        working['returns'] = pd.to_numeric(working[return_col], errors='coerce')
        added.append('returns')
        sources['returns'] = return_col

    if needs_vwap and 'vwap' not in working.columns:
        volume_col = 'volume' if 'volume' in working.columns else 'vol' if 'vol' in working.columns else None
        if volume_col is None or 'amount' not in working.columns:
            raise SystemExit('BLOCK_FACTORFORGE_STEP3A_DERIVED_FIELD_MISSING_SOURCE: vwap requires amount and volume/vol source')
        volume = pd.to_numeric(working[volume_col], errors='coerce').replace(0, pd.NA)
        amount = pd.to_numeric(working['amount'], errors='coerce')
        working['vwap'] = amount / volume
        added.append('vwap')
        sources['vwap'] = f'amount/{volume_col}'

    missing_adv = [field for field, _window in adv_fields if field not in working.columns]
    if missing_adv:
        volume_col = 'volume' if 'volume' in working.columns else 'vol' if 'vol' in working.columns else None
        if volume_col is None:
            raise SystemExit(
                'BLOCK_FACTORFORGE_STEP3A_DERIVED_FIELD_MISSING_SOURCE: '
                f'adv fields require volume/vol source: {missing_adv}'
            )
        volume = pd.to_numeric(working[volume_col], errors='coerce')
        grouped_volume = volume.groupby(working['ts_code'], sort=False)
        for field, window in adv_fields:
            if field in working.columns:
                continue
            working[field] = grouped_volume.transform(lambda s, window=window: s.rolling(window, min_periods=window).mean())
            added.append(field)
            sources[field] = f'rolling_mean({volume_col},{window})'

    return working, {
        'standard_formula_fields_added': added,
        'standard_formula_field_sources': sources,
        'required_formula_fields': sorted(required),
        'report_local_only': True,
        'clean_data_mutation': False,
    }


def materialize_shared_daily_slice(
    report_id: str,
    sample_window: dict,
    symbols: list[str] | None = None,
    csv_output_policy: str | None = None,
    required_fields: list[str] | None = None,
) -> dict:
    del symbols
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    daily_fields = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    daily_resolution = resolve_data_api_dataset(
        'clean_daily_bar',
        start=sample_window.get('start'),
        end=sample_window.get('end'),
        fields=daily_fields,
    )
    step4_data_contract = build_step4_data_contract(
        sample_window=sample_window,
        daily_resolution=daily_resolution,
        daily_fields=daily_fields,
    )

    if daily_resolution.get('status') != 'ready':
        return {
            'snapshot_note': (
                'Data API could not resolve ready clean_daily_bar. Factor Forge Step3A only consumes '
                'published clean data products; publish or sync the Data API catalog before Step3A.'
            ),
            'snapshot_source': 'missing_data_api_clean_daily_bar',
            'input_mode': 'daily_only',
            'data_api_resolution': {'clean_daily_bar': daily_resolution},
            'step4_data_contract': step4_data_contract,
        }

    daily_result = fetch_data_api_dataset(
        'clean_daily_bar',
        start=sample_window.get('start'),
        end=sample_window.get('end'),
        fields=daily_fields,
        universe='a_share_all',
        frequency='daily',
        catalog_path=daily_resolution.get('catalog_path'),
    )
    if daily_result.status not in {'ready', 'proxy_ready'}:
        return {
            'snapshot_note': (
                'Data API resolved clean_daily_bar metadata but failed to fetch the report-local daily snapshot.'
            ),
            'snapshot_source': 'missing_data_api_clean_daily_bar',
            'input_mode': 'daily_only',
            'data_api_resolution': {'clean_daily_bar': daily_result.to_metadata()},
            'step4_data_contract': step4_data_contract,
        }

    daily_df = daily_result.frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    daily_df, derived_field_contract = enrich_report_local_daily_fields(daily_df, required_fields or [])
    policy = resolve_csv_policy(csv_output_policy)
    daily_parquet = local_dir / f'daily_input__{report_id}.parquet'
    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    daily_sample_csv = local_dir / f'daily_input_sample__{report_id}.csv'
    daily_df.to_parquet(daily_parquet, index=False)
    audit_payload = materialize_daily_audit_csv(
        daily_df,
        report_id=report_id,
        full_csv_path=daily_csv,
        sample_csv_path=daily_sample_csv,
        policy=policy,
    )

    return {
        'sample_window_actual': sample_window,
        'snapshot_note': 'Step3A resolved clean_daily_bar through Data API and wrote a report-local daily snapshot for Step3B/Step4.',
        'snapshot_source': 'data_api_clean_daily_bar',
        'input_mode': 'daily_only',
        'daily_df_parquet': str(daily_parquet.relative_to(WORKSPACE)),
        'preferred_daily_format': 'parquet',
        **audit_payload,
        'data_api_resolution': {'clean_daily_bar': daily_resolution},
        'step4_data_contract': step4_data_contract,
        'daily_filter_policy': daily_resolution.get('daily_filter_policy'),
        'daily_filter_summary': daily_resolution.get('coverage') or {},
        'derived_field_contract': derived_field_contract,
    }


def build_local_price_volume_snapshots(report_id: str, sample_window: dict, csv_output_policy: str | None = None):
    del csv_output_policy
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    daily_fields = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    minute_fields = ['open', 'high', 'low', 'close', 'vol', 'amount']
    daily_resolution = resolve_data_api_dataset(
        'clean_daily_bar',
        start=sample_window.get('start'),
        end=sample_window.get('end'),
        fields=daily_fields,
    )
    minute_resolution = resolve_data_api_dataset(
        'minute_bar',
        start=sample_window.get('start'),
        end=sample_window.get('end'),
        fields=minute_fields,
        frequency='1min',
    )
    step4_data_contract = build_step4_data_contract(
        sample_window=sample_window,
        daily_resolution=daily_resolution,
        minute_resolution=minute_resolution,
        daily_fields=daily_fields,
        minute_fields=minute_fields,
    )
    if daily_resolution.get('status') != 'ready' or minute_resolution.get('status') not in {'ready', 'proxy_ready'}:
        return {
            'snapshot_note': 'Data API could not resolve required minute/daily datasets; Step3A will not guess raw minute paths or build clean layers.',
            'snapshot_source': 'missing_data_api_minute_or_daily',
            'input_mode': 'price_volume_minute',
            'data_api_resolution': {
                'clean_daily_bar': daily_resolution,
                'minute_bar': minute_resolution,
            },
            'step4_data_contract': step4_data_contract,
        }
    return {
        'sample_window_actual': sample_window,
        'snapshot_note': 'Step3A resolved minute_bar and clean_daily_bar through Data API; Step3B may fetch a small non-formal sample and Step4 owns full data execution.',
        'snapshot_source': 'data_api_minute_plus_daily',
        'input_mode': 'price_volume_minute',
        'data_api_resolution': {
            'clean_daily_bar': daily_resolution,
            'minute_bar': minute_resolution,
        },
        'step4_data_contract': step4_data_contract,
        'daily_filter_policy': daily_resolution.get('daily_filter_policy'),
        'daily_filter_summary': daily_resolution.get('coverage') or {},
    }

    minute_meta = next((meta for meta in (inspect_minute_root(p) for p in candidate_minute_roots()) if meta), None)
    real_minute_root = minute_meta['path'] if minute_meta else REAL_PRICE_VOLUME_BASE / 'stk_mins_1min'
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
                'input_mode': 'price_volume_minute',
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
                'insufficient for formula-declared price-volume rolling-window reconstruction.'
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
    daily_df = pd.DataFrame(daily_rows).sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

    policy = resolve_csv_policy(csv_output_policy)
    minute_csv = local_dir / f'minute_input__{report_id}.csv'
    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    daily_sample_csv = local_dir / f'daily_input_sample__{report_id}.csv'
    daily_parquet = local_dir / f'daily_input__{report_id}.parquet'
    minute_df.to_csv(minute_csv, index=False)
    daily_df.to_parquet(daily_parquet, index=False)
    audit_payload = materialize_daily_audit_csv(
        daily_df,
        report_id=report_id,
        full_csv_path=daily_csv,
        sample_csv_path=daily_sample_csv,
        policy=policy,
    )

    sample_actual = {
        'start': str(minute_df['trade_date'].min()),
        'end': str(minute_df['trade_date'].max())
    }
    return {
        'minute_df_csv': str(minute_csv.relative_to(WORKSPACE)),
        'daily_df_parquet': str(daily_parquet.relative_to(WORKSPACE)),
        'preferred_daily_format': 'parquet',
        **audit_payload,
        'input_mode': 'price_volume_minute',
        'sample_window_actual': sample_actual,
        'snapshot_note': 'Synthetic fallback snapshot; use only when real local data layer is unavailable.',
        'snapshot_source': 'synthetic_fallback',
    }


def build_local_daily_snapshot(
    report_id: str,
    sample_window: dict,
    csv_output_policy: str | None = None,
    required_fields: list[str] | None = None,
):
    # Daily-only factors resolve the published clean_daily_bar Data API contract.
    return materialize_shared_daily_slice(
        report_id,
        sample_window,
        csv_output_policy=csv_output_policy,
        required_fields=required_fields,
    )


def build_step3a(report_id: str, csv_output_policy: str | None = None):
    fsm = load_json(OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    _aim = load_json(OBJ / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json')
    handoff_to_step3 = read_existing_json(OBJ / 'handoff' / f'handoff_to_step3__{report_id}.json')

    factor_id = fsm.get('factor_id', report_id)
    canonical = fsm.get('canonical_spec', {})
    required_fields = formula_required_daily_fields(fsm)
    price_volume_minute = is_price_volume_minute_formula(canonical)
    direct_code_minute = direct_code_requires_minute_inputs(fsm)
    required = canonical.get('required_inputs', [])
    required_text = ' '.join(required)
    need_minute = bool(re.search(r'minute|分钟|高频', required_text, re.I)) or price_volume_minute or direct_code_minute
    need_daily = True
    need_daily_basic = price_volume_minute or bool(re.search(r'market_cap|total_mv|circ_mv|turnover|pe|pb|ps|估值|市值', required_text, re.I))

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
    if need_minute:
        # Formula-declared price-volume minute factors may need daily_basic for scale / turnover features.
        # Only keep risks that are truly unresolved in the current data contract.
        if price_volume_minute:
            proxy_rules.extend([
                {
                    'missing_field': 'industry_dummy',
                    'proxy_field': '',
                    'reason': '当前未接入申万行业字段，不做纯行业中性化',
                    'risk': 'high'
                }
            ])
        local_input_paths = build_local_price_volume_snapshots(report_id, sample_window, csv_output_policy=csv_output_policy)
        if price_volume_minute:
            notes.append('Formula-declared price-volume minute factors should prefer daily_basic_incremental for total_mv / circ_mv / turnover_rate / pe / pb when those fields are required.')
        if direct_code_minute and not price_volume_minute:
            notes.append('Step 3A selected minute local inputs because the direct_code contract references minute-level fields.')
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        if snapshot_source in {'data_api_clean_daily_bar', 'data_api_minute_plus_daily'}:
            notes.append('Step 3A 已生成 Step4 Data API contract；Step3B 只允许小样本 executability proof，Step4 负责全量正式数据执行')
        elif snapshot_source in {'shared_clean_daily_layer', 'synthetic_fallback'}:
            notes.append('Legacy local snapshot path retained only for compatibility; Data API contract path is preferred.')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source in {'real_local_insufficient', 'missing_real_local_data', 'missing_clean_daily_layer', 'missing_data_api_clean_daily_bar', 'missing_data_api_minute_or_daily'}:
            blocked.append({
                'code': (
                    'DATA_API_CLEAN_DAILY_BAR_UNAVAILABLE'
                    if snapshot_source in {'missing_data_api_clean_daily_bar', 'missing_data_api_minute_or_daily'}
                    else 'SHARED_CLEAN_DAILY_LAYER_MISSING'
                    if snapshot_source == 'missing_clean_daily_layer'
                    else 'LOCAL_MINUTE_HISTORY_INSUFFICIENT'
                ),
                'detail': snapshot_note,
            })
    else:
        local_input_paths = build_local_daily_snapshot(
            report_id,
            sample_window,
            csv_output_policy=csv_output_policy,
            required_fields=required_fields,
        )
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source in {'missing_clean_daily_layer', 'missing_data_api_clean_daily_bar'}:
            blocked.append({
                'code': 'DATA_API_CLEAN_DAILY_BAR_UNAVAILABLE'
                if snapshot_source == 'missing_data_api_clean_daily_bar'
                else 'SHARED_CLEAN_DAILY_LAYER_MISSING',
                'detail': snapshot_note,
            })

    feasibility = 'blocked' if blocked else ('proxy_ready' if proxy_rules else 'ready')
    notes.append(
        'Step 3A consumes Data API catalog contracts. Step3B may fetch a small non-formal sample; Step4 owns full formal data fetch and factor_values.'
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
        'data_api_resolution': local_input_paths.get('data_api_resolution') or {},
        'step4_data_contract': local_input_paths.get('step4_data_contract') or {},
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
        'data_api_resolution': local_input_paths.get('data_api_resolution') or {},
        'step4_data_contract': local_input_paths.get('step4_data_contract') or {},
        'sample_window': sample_window,
        'local_input_paths': local_input_paths,
        'step4_access_rule': 'Step 4 must consume Step3 data contract and fetch full formal data through factorforge_data_api, not raw S3/local path guessing.'
    }

    implementation_mode = declared_implementation_mode(fsm, price_volume_minute=price_volume_minute)
    direct_code_contract = (
        build_direct_code_contract_for_step3a(fsm, qlib_adapter_config)
        if implementation_mode == 'direct_code' else {}
    )
    direct_code_ready = direct_code_contract.get('status') == 'ready'
    implementation_plan_stub = {
        'report_id': report_id,
        'factor_id': factor_id,
        'preferred_execution_mode': implementation_mode,
        'implementation_mode': implementation_mode,
        'candidate_paths': ['operator', 'hybrid', 'direct_code'],
        'current_decision': 'defer_to_step3b',
        'notes': [
            'Step 3A 已完成 Data API contract；Step3B 只做小样本证明，Step4 负责全量正式执行',
            '正式实现顺序为 operator -> hybrid -> direct_code；无法保证正确时必须 BLOCK'
        ]
    }
    if implementation_mode == 'direct_code':
        implementation_plan_stub.update({
            'implementation_contract': {
                'implementation_mode': 'direct_code',
                'mode': 'direct_code',
                'code_contract': direct_code_contract.get('code_contract') if direct_code_ready else None,
                'output_schema': direct_code_contract.get('output_schema') if direct_code_ready else None,
            },
            'code_contract': direct_code_contract.get('code_contract') if direct_code_ready else None,
            'source_code': direct_code_contract.get('source_code') if direct_code_ready else None,
            'code_hash': direct_code_contract.get('code_hash') if direct_code_ready else None,
            'code_contract_hash': direct_code_contract.get('code_contract_hash') if direct_code_ready else None,
            'output_schema': direct_code_contract.get('output_schema') if direct_code_ready else {'columns': ['ts_code', 'trade_date', 'factor_value']},
            'direct_code_contract_status': direct_code_contract.get('status'),
            'direct_code_contract_blocked_reason': direct_code_contract.get('blocked_reason'),
        })

    return data_prep_master, qlib_adapter_config, implementation_plan_stub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    ap.add_argument('--csv-output-policy', help='Step3A daily CSV audit output policy. Defaults to full_csv.')
    args = ap.parse_args()
    csv_policy = resolve_csv_policy(args.csv_output_policy)
    enforce_direct_step_policy(args.manifest)
    _manifest, manifest_rid = apply_runtime_manifest(args.manifest)
    report_id = args.report_id or manifest_rid
    if not report_id:
        raise SystemExit('run_step3.py requires --report-id or --manifest')

    data_prep_master, qlib_adapter_config, implementation_plan_stub = build_step3a(report_id, csv_output_policy=csv_policy)

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
        'step3b_ready': False if not step3a_ready else None,
        'first_run_outputs': {
            'status': 'blocked',
            'no_first_run_reason': 'step3a_feasibility_blocked',
            'output_paths': [],
            'run_metadata_path': None,
            'factor_values_path': None,
        } if not step3a_ready else None,
        'data_prep_master_ref': out_path.name,
        'qlib_adapter_config_ref': qlib_path.name,
        'implementation_plan_master_ref': impl_path.name,
        'factor_spec_master_ref': f'factor_spec_master__{report_id}.json',
        'local_input_paths': data_prep_master['local_input_paths'],
        'step4_data_contract': data_prep_master.get('step4_data_contract') or {},
    })
    write_json(handoff_path, handoff_payload)


if __name__ == '__main__':
    main()
